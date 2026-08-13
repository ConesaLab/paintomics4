/**
 * PA_Step3RegTargetNetworkView — Regulator↔Target network for MORE.
 *
 * Renders MORE's RegulationPerCondition (rpc) table as an interactive graph:
 * regulators fan out to the targets they regulate, edge colour carries the sign
 * of the coefficient and edge width its magnitude, and post-hoc filters
 * (condition, R², |coef|, edge budget) narrow what is on screen.
 *
 * Why this was rewritten
 * ----------------------
 * It ran on sigma.js — specifically the **Linkurious fork**, whose upstream was
 * last released in 2015 and whose plugin set this view had to reach around at
 * three separate points: `sigma.canvas.nodes.bordered` existed only because the
 * `def` renderer ignores `borderSize` outside the select plugin, ForceAtlas2 ran
 * in a web worker that had to be killed by hand on every teardown or it leaked
 * across job switches, and the layout was stopped on a wall-clock timer because
 * there was no convergence signal to wait for.
 *
 * This is Cytoscape.js: maintained, MIT, and the library the surrounding field
 * already uses — Reactome, WikiPathways and NDEx all render with it, so a
 * pathway-tool user has met its interaction model before. Concretely it removes
 * the custom renderer (borders are a first-class style property), the manual
 * worker lifecycle (`cy.destroy()` takes the layout with it), and the timer
 * (`layoutstop` is an event). Selectors and `.style()` replace the
 * read-modify-write-refresh dance sigma needed for every visual change.
 *
 * The layout is Cytoscape's built-in `cose`, deliberately, rather than the fcose
 * extension: fcose is better on large compound graphs but drags in `cose-base`
 * and `layout-base` as two further vendored files, and at the edge budget this
 * view enforces (400 by default, 2000 at most) the built-in reaches a readable
 * hub-and-spoke arrangement without them. One vendored file, not three.
 *
 * The pathway network in PA_Step3Views.js is a different view and still runs on
 * sigma; nothing here touches it.
 *
 * Data shape: identical to PA_Step3RegulationView — the same payload from
 * model.getRegulationPerConditionData() drives both. This view additionally
 * consumes payload.filters (sidecar metadata: filter_r2, alpha, vip, method).
 *
 * Self-suppression: returns a hidden container when no rpc data is present
 * (Pairwise jobs, or any job that didn't run MORE).
 */
function PA_Step3RegTargetNetworkView() {
	this.name = "PA_Step3RegTargetNetworkView";

	// Per-instance handles. Kept on `this` so _teardown() can dispose them
	// deterministically when the panel is destroyed or a new job is loaded.
	this.cy               = null;
	this.containerId      = "more_regtarget_cy_" + Math.floor(Math.random() * 1e9);
	this.toolbarId        = "more_regtarget_toolbar_" + Math.floor(Math.random() * 1e9);
	this.subtitleId       = "more_regtarget_subtitle_" + Math.floor(Math.random() * 1e9);
	this.sidePanelId      = "more_regtarget_side_" + Math.floor(Math.random() * 1e9);
	this.graph            = null;  // {regulators, targets, edges, conditions, …}
	this.currentCondition = null;  // resolved on first render
	this.pinnedNode       = null;  // when set, hover does not change the highlight
	this.omicColors       = {};    // omic name → colour
	this.hiddenOmics      = {};    // omic name → true when toggled off
	this.dataMaxAbsCoef   = 1;     // upper bound for the |coef| slider; from data
	this.filterState      = null;  // {r2Min, absCoefMin, maxEdges}

	// ---- Visual constants -------------------------------------------------
	// Regulator palette — generic, 8 entries, assigned to omics in the order
	// they appear in the rpc (alphabetical, so stable across reloads of the
	// same job). No name-based hardcoding: regulators can be any omic the user
	// defined in MORE, so we don't try to predict semantics. Targets are always
	// grey — gene expression in this pipeline lives on the target side, never
	// as a regulator omic.
	//
	// Deliberately avoids edge red and edge blue so the regulator/target
	// distinction stays readable against the line colours.
	var REG_PALETTE = [
		"#9C8AC9", // light purple
		"#5E3C99", // dark purple
		"#A6D96A", // light green
		"#1A7332", // dark green
		"#FFC726", // yellow
		"#7B5E3B", // warm brown
		"#1B9E77", // teal-green
		"#E08214"  // orange (warm, kept clear of edge red)
	];
	var TARGET_COLOR   = "#B8B8B8";
	var EDGE_POS_COLOR = "#2E86C1";  // blue: positive coefficient
	var EDGE_NEG_COLOR = "#C0392B";  // red: negative coefficient

	// Everything not adjacent to the highlighted node fades to this rather than
	// disappearing: the structure of interest has to stand out without losing
	// the context it stands out from.
	var DIM_OPACITY = 0.12;

	// Default edge budget. The whole graph is often tens of thousands of edges;
	// beyond a couple of thousand the layout stops being readable long before
	// it stops being fast, so the default view is the strongest 400 and the
	// slider says so.
	var DEFAULT_MAX_EDGES = 400;
	var EDGE_BUDGET_CEILING = 2000;

	// ---- Model wiring -----------------------------------------------------
	this.loadModel = function (model) {
		if (this.model !== null && this.model !== undefined) {
			this.model.deleteObserver(this);
		}
		this.model = model;
		this.model.addObserver(this);

		var payload = model.getRegulationPerConditionData();
		this.hasData = !!(payload && payload.rows && payload.rows.length);
		if (this.hasData) {
			this.columns = payload.columns;
			this.rows    = payload.rows;
			this.symbols = payload.symbols || {};
			this.filters = payload.filters || null;
		}
	};

	// ---- Graph build ------------------------------------------------------
	// Single-pass build over rpc rows that stores per-condition coefficients on
	// each edge. Switching condition is then an O(E) attribute update rather
	// than a rebuild, which is what lets the layout survive a condition change.
	//
	// Edge .coefPerCondition is a {condName: numberOrNull} dict; null means the
	// underlying rpc cell was blank or NaN for that condition (the regression
	// produced no value, usually because the regulator was not significant
	// there). An edge whose entire coefPerCondition is null is dropped — it
	// cannot contribute to any view.
	//
	// Any-omic union: a regulator stays in `regulators` if ANY of its omics
	// surfaced an edge. Per-omic counts are kept so getPrimaryOmic() can pick
	// the dominant one for colouring.
	this.buildBipartiteGraph = function () {
		var colIdx = {};
		for (var i = 0; i < this.columns.length; i++) {
			colIdx[this.columns[i]] = i;
		}
		var r2Idx   = colIdx.R2;
		var tgtIdx  = colIdx.targetF;
		var regIdx  = colIdx.regulator;
		var omicIdx = colIdx.omic;

		// Discover condition columns in their original order.
		var conditions = [];
		var coefIdxByCond = {};
		for (var c = 0; c < this.columns.length; c++) {
			var cname = this.columns[c];
			if (cname.indexOf("Group_") === 0) {
				var cond = cname.substring(6);
				conditions.push(cond);
				coefIdxByCond[cond] = c;
			}
		}

		var regulators = {};
		var targets    = {};
		var edges      = [];
		var omicSet    = {};
		var globalMaxAbsCoef = 0;

		var rows = this.rows;
		for (var r = 0; r < rows.length; r++) {
			var row = rows[r];
			var reg = row[regIdx];
			var tgt = row[tgtIdx];
			if (reg == null || reg === "" || tgt == null || tgt === "") continue;

			var omic = (omicIdx != null && row[omicIdx]) || "Unknown";
			omicSet[omic] = true;

			var coefMap = {};
			var anyCoef = false;
			var rowMaxAbsCoef = 0;
			for (var k = 0; k < conditions.length; k++) {
				var condName = conditions[k];
				var raw = row[coefIdxByCond[condName]];
				if (raw == null || raw === "" || raw === "None") {
					coefMap[condName] = null;
					continue;
				}
				var num = Number(raw);
				if (isNaN(num)) {
					coefMap[condName] = null;
					continue;
				}
				coefMap[condName] = num;
				anyCoef = true;
				if (Math.abs(num) > rowMaxAbsCoef) rowMaxAbsCoef = Math.abs(num);
			}
			if (!anyCoef) continue;
			if (rowMaxAbsCoef > globalMaxAbsCoef) globalMaxAbsCoef = rowMaxAbsCoef;

			var r2 = null;
			if (r2Idx != null) {
				var r2Raw = row[r2Idx];
				if (r2Raw != null && r2Raw !== "" && r2Raw !== "None") {
					var r2Num = Number(r2Raw);
					if (!isNaN(r2Num)) r2 = r2Num;
				}
			}

			var regId = "reg:" + reg;
			var tgtId = "tgt:" + tgt;

			if (!regulators[regId]) {
				regulators[regId] = {
					id: regId, name: reg, omics: {}, omicCounts: {}, degree: 0
				};
			}
			regulators[regId].omics[omic] = true;
			regulators[regId].omicCounts[omic] =
				(regulators[regId].omicCounts[omic] || 0) + 1;
			regulators[regId].degree += 1;

			if (!targets[tgtId]) {
				targets[tgtId] = { id: tgtId, name: tgt, degree: 0 };
			}
			targets[tgtId].degree += 1;

			edges.push({
				id:               "e" + r,
				source:           regId,
				target:           tgtId,
				omic:             omic,
				r2:               r2,
				coefPerCondition: coefMap,
				maxAbsCoef:       rowMaxAbsCoef
			});
		}

		return {
			regulators: regulators,
			targets:    targets,
			edges:      edges,
			conditions: conditions,
			maxAbsCoef: globalMaxAbsCoef,
			omics:      Object.keys(omicSet).sort()
		};
	};

	// A regulator's "primary" omic — the one contributing the most edges to it.
	// Used for node colour when a regulator spans several omics.
	var getPrimaryOmic = function (regulator) {
		var best = null, bestCount = -1;
		for (var omic in regulator.omicCounts) {
			if (regulator.omicCounts[omic] > bestCount) {
				bestCount = regulator.omicCounts[omic];
				best = omic;
			}
		}
		return best;
	};

	// {omic → colour}, positional against REG_PALETTE and wrapping. Caller
	// passes a stably-sorted list so an omic keeps its colour across reloads.
	var buildOmicColorMap = function (omics) {
		var map = {};
		for (var i = 0; i < omics.length; i++) {
			map[omics[i]] = REG_PALETTE[i % REG_PALETTE.length];
		}
		return map;
	};

	// Mix toward black, for a same-hue border that reads as "the same colour,
	// stronger". Keeps the vocabulary to one colour per omic in two shades.
	var darken = function (color, factor) {
		factor = factor != null ? factor : 0.4;
		var hex = String(color || "").replace("#", "");
		if (hex.length === 3) {
			hex = hex.charAt(0) + hex.charAt(0) + hex.charAt(1) + hex.charAt(1) +
			      hex.charAt(2) + hex.charAt(2);
		}
		if (hex.length !== 6) return "#333333";
		var channels = [0, 2, 4].map(function (offset) {
			var value = parseInt(hex.substring(offset, offset + 2), 16);
			return Math.max(0, Math.round(value * (1 - factor)));
		});
		return "rgb(" + channels.join(",") + ")";
	};

	// Prefer the resolved gene symbol over the raw ID, and show it alone rather
	// than "symbol (id)" — the parenthesised form crowds the canvas once many
	// nodes are labelled. The raw ID stays on the node for tooltips and search.
	// UPPERCASE keys, matching the server-side normalisation.
	var labelFor = function (id, symbols) {
		if (!id) return "";
		var symbol = symbols && symbols[String(id).toUpperCase()];
		return symbol ? symbol : id;
	};

	// ---- Cytoscape instantiation -----------------------------------------
	this._instantiate = function (containerEl) {
		var me = this;
		if (typeof cytoscape === "undefined") {
			throw new Error("Cytoscape.js is not loaded (js/libs/cytoscape/cytoscape.min.js)");
		}

		this.graph = this.buildBipartiteGraph();
		this.omicColors = buildOmicColorMap(this.graph.omics);
		this.dataMaxAbsCoef = this.graph.maxAbsCoef || 1;
		this.filterState = {
			r2Min: 0,
			absCoefMin: 0,
			maxEdges: DEFAULT_MAX_EDGES
		};

		var elements = [];
		var regulators = this.graph.regulators;
		for (var regId in regulators) {
			var regulator = regulators[regId];
			var omic = getPrimaryOmic(regulator);
			elements.push({
				group: "nodes",
				data: {
					id: regId,
					label: labelFor(regulator.name, this.symbols),
					rawId: regulator.name,
					role: "regulator",
					omic: omic,
					degree: regulator.degree,
					color: this.omicColors[omic] || REG_PALETTE[0],
					border: darken(this.omicColors[omic] || REG_PALETTE[0], 0.35)
				}
			});
		}
		var targets = this.graph.targets;
		for (var tgtId in targets) {
			elements.push({
				group: "nodes",
				data: {
					id: tgtId,
					label: labelFor(targets[tgtId].name, this.symbols),
					rawId: targets[tgtId].name,
					role: "target",
					omic: null,
					degree: targets[tgtId].degree,
					color: TARGET_COLOR,
					border: darken(TARGET_COLOR, 0.25)
				}
			});
		}
		for (var e = 0; e < this.graph.edges.length; e++) {
			var edge = this.graph.edges[e];
			elements.push({
				group: "edges",
				data: {
					id: edge.id,
					source: edge.source,
					target: edge.target,
					omic: edge.omic,
					r2: edge.r2,
					coefs: edge.coefPerCondition,
					maxAbsCoef: edge.maxAbsCoef,
					// Filled in by _applyCondition before the first paint.
					coef: 0, absCoef: 0, sign: "pos", width: 1
				}
			});
		}

		this.cy = cytoscape({
			container: containerEl,
			elements: elements,
			// The graph is filtered down to an edge budget anyway, and motion
			// blur on a canvas this dense costs more than it hides.
			motionBlur: false,
			textureOnViewport: true,
			pixelRatio: "auto",
			wheelSensitivity: 0.2,
			style: [
				{
					selector: "node",
					style: {
						"background-color": "data(color)",
						"border-color": "data(border)",
						// Borders are a first-class property here. Under sigma
						// this needed a custom `bordered` renderer, because the
						// default one consults borderSize only from the select
						// plugin and so drew nothing at rest.
						"border-width": 1.5,
						"label": "data(label)",
						"font-size": 9,
						"color": "#333",
						"text-valign": "center",
						"text-halign": "right",
						"text-margin-x": 3,
						"min-zoomed-font-size": 8
					}
				},
				{
					// Role, not degree, drives size. When omics with very
					// different out-degree are mixed (TFs target hundreds of
					// genes, miRNAs a handful), sqrt-degree sizing let TF hubs
					// dominate and hid the smaller regulators. Hub-ness is
					// still legible from the fan of edges, which is the channel
					// that already carries it.
					selector: 'node[role = "regulator"]',
					style: { "width": 16, "height": 16 }
				},
				{
					selector: 'node[role = "target"]',
					style: {
						"width": 7, "height": 7,
						// Target labels only on hover/selection: at the default
						// budget most nodes are targets, and labelling them all
						// turns the canvas into a wall of text.
						"label": ""
					}
				},
				{
					selector: "edge",
					style: {
						"width": "data(width)",
						"curve-style": "haystack",
						"haystack-radius": 0,
						"opacity": 0.55,
						"line-color": EDGE_POS_COLOR
					}
				},
				{ selector: 'edge[sign = "neg"]', style: { "line-color": EDGE_NEG_COLOR } },
				{
					selector: ".dimmed",
					style: { "opacity": DIM_OPACITY, "text-opacity": 0 }
				},
				{
					selector: ".highlighted",
					style: { "opacity": 1, "text-opacity": 1, "z-index": 10 }
				},
				{
					selector: "node.highlighted",
					style: { "border-width": 3, "border-color": "#222", "label": "data(label)" }
				},
				{
					selector: ".hidden",
					style: { "display": "none" }
				},
				{
					selector: "node:selected",
					style: { "border-width": 3, "border-color": "#111" }
				}
			]
		});

		this.currentCondition = this.graph.conditions.length
			? this.graph.conditions[0] : null;

		this._buildToolbar();
		this._buildSidePanel();
		this._applyCondition(this.currentCondition);
		this._applyFilters();
		this._bindInteraction();
		this._runLayout();
	};

	// ---- Layout -----------------------------------------------------------
	this._runLayout = function () {
		if (!this.cy) return;
		var me = this;
		var visible = this.cy.nodes(":visible");

		// Node repulsion has to fall as the graph grows or a large one flies
		// apart before it converges; these are the built-in cose defaults
		// scaled against the node count actually on screen.
		var layout = this.cy.layout({
			name: "cose",
			animate: false,          // one paint at the end, not sixty per second
			randomize: true,
			fit: true,
			padding: 24,
			nodeDimensionsIncludeLabels: false,
			idealEdgeLength: 45,
			nodeRepulsion: Math.max(4000, 400000 / Math.max(1, visible.length)),
			edgeElasticity: 100,
			gravity: 0.25,
			numIter: 1000,
			// `cose` reports convergence itself, so nothing here has to guess
			// when to stop. The sigma version ran ForceAtlas2 in a worker and
			// killed it on a 4.5-second timer, which was either too short for a
			// large graph or a waste of a core for a small one.
			eles: this.cy.elements(":visible")
		});
		layout.one("layoutstop", function () {
			me._updateSubtitle();
		});
		layout.run();
	};

	// ---- Condition ---------------------------------------------------------
	// Rewrites every edge's live coefficient from its per-condition map. O(E)
	// and does NOT move a node, which is the point: switching condition
	// compares the same layout under two coefficient sets.
	this._applyCondition = function (condition) {
		if (!this.cy) return;
		this.currentCondition = condition;
		var me = this;

		this.cy.batch(function () {
			me.cy.edges().forEach(function (edge) {
				var coefs = edge.data("coefs") || {};
				var raw = condition != null ? coefs[condition] : null;
				var coef = (raw == null || isNaN(raw)) ? null : Number(raw);
				var absCoef = coef == null ? 0 : Math.abs(coef);
				edge.data("coef", coef);
				edge.data("absCoef", absCoef);
				edge.data("sign", (coef != null && coef < 0) ? "neg" : "pos");
				// Width is |coef| RELATIVE TO THE STRONGEST EDGE IN THIS
				// DATASET, not against an absolute scale.
				//
				// The absolute version -- inherited from the sigma view, which
				// capped at 1.5 on the grounds that MORE coefficients "typically
				// land in [0, ~2]" -- assumes a coefficient scale that no data
				// is obliged to have. Measured on the STATegra example as it
				// was then bundled (TFLink "All", 600 targets), |coef| ran 0 to
				// 0.178 with a median of 0.031, so every edge came out between
				// 0.6 and 0.96 pixels wide: a channel carrying no information,
				// on the quantity the view exists to show.
				//
				// The rebuilt example (TFLink small-scale, 957 targets) runs 0
				// to 3.005 with a median of 0.176, where that same absolute cap
				// would have worked passably. Do not read that as a reason to
				// go back: the two measurements are a year apart in nothing but
				// the choice of network, and they differ by 17x. The scale is a
				// property of the user's data, not a constant, which is the
				// whole argument for scaling against the network in hand.
				//
				// Relative scaling means widths are not comparable between two
				// different jobs. They were not comparable before either -- they
				// were all the same -- and within one network, which is what a
				// reader is actually comparing, this is the encoding that works.
				var scale = me.dataMaxAbsCoef > 0 ? absCoef / me.dataMaxAbsCoef : 0;
				edge.data("width", 0.5 + Math.min(scale, 1) * 3.5);
			});
		});
	};

	// ---- Filters -----------------------------------------------------------
	// Hides rather than removes. Removing would lose the element's position and
	// force a relayout on every slider move; `display: none` keeps the layout
	// and is what makes the sliders feel immediate.
	this._applyFilters = function () {
		if (!this.cy) return;
		var me = this;
		var state = this.filterState;

		this.cy.batch(function () {
			var eligible = [];
			me.cy.edges().forEach(function (edge) {
				var coef = edge.data("coef");
				var r2 = edge.data("r2");
				var omic = edge.data("omic");
				var ok = coef != null &&
					!me.hiddenOmics[omic] &&
					edge.data("absCoef") >= state.absCoefMin &&
					(r2 == null || r2 >= state.r2Min);
				if (ok) { eligible.push(edge); } else { edge.addClass("hidden"); }
			});

			// The budget keeps the STRONGEST edges, not an arbitrary prefix:
			// truncating in row order would silently show a different network
			// depending on how MORE happened to sort its output.
			eligible.sort(function (a, b) {
				return b.data("absCoef") - a.data("absCoef");
			});
			for (var i = 0; i < eligible.length; i++) {
				if (i < state.maxEdges) {
					eligible[i].removeClass("hidden");
				} else {
					eligible[i].addClass("hidden");
				}
			}

			// A node with no visible edge is noise; hide it, and remember that
			// `:visible` in the layout call above depends on this having run.
			me.cy.nodes().forEach(function (node) {
				var connected = node.connectedEdges().filter(function (edge) {
					return !edge.hasClass("hidden");
				});
				if (connected.length) { node.removeClass("hidden"); }
				else { node.addClass("hidden"); }
			});
		});

		this._renderTopHubs();
		this._updateSubtitle();
	};

	// ---- Highlight ---------------------------------------------------------
	this._highlight = function (node) {
		if (!this.cy || !node) return;
		var neighbourhood = node.closedNeighborhood().filter(function (element) {
			return !element.hasClass("hidden");
		});
		this.cy.batch(function () {
			this.elements().addClass("dimmed").removeClass("highlighted");
			neighbourhood.removeClass("dimmed").addClass("highlighted");
		}.bind(this.cy));
	};

	this._clearHighlight = function () {
		if (!this.cy) return;
		this.cy.batch(function () {
			this.elements().removeClass("dimmed").removeClass("highlighted");
		}.bind(this.cy));
	};

	this._bindInteraction = function () {
		var me = this;

		this.cy.on("mouseover", "node", function (event) {
			if (me.pinnedNode) return;
			me._highlight(event.target);
			me._showTooltip(event.target, event.renderedPosition);
		});
		this.cy.on("mouseout", "node", function () {
			me._hideTooltip();
			if (me.pinnedNode) return;
			me._clearHighlight();
		});

		// Click pins the neighbourhood so it can be read without keeping the
		// pointer still; clicking the same node again, or the background,
		// releases it.
		this.cy.on("tap", "node", function (event) {
			var node = event.target;
			if (me.pinnedNode && me.pinnedNode.id() === node.id()) {
				me.pinnedNode = null;
				me._clearHighlight();
			} else {
				me.pinnedNode = node;
				me._highlight(node);
			}
		});
		this.cy.on("tap", function (event) {
			if (event.target === me.cy) {
				me.pinnedNode = null;
				me._clearHighlight();
			}
		});
	};

	// ---- Tooltip -----------------------------------------------------------
	this._showTooltip = function (node, position) {
		var container = document.getElementById(this.containerId);
		if (!container || !position) return;

		var tip = document.getElementById(this.containerId + "_tip");
		if (!tip) {
			tip = document.createElement("div");
			tip.id = this.containerId + "_tip";
			tip.className = "more-net-tip";
			container.appendChild(tip);
		}

		var visibleEdges = node.connectedEdges().filter(function (edge) {
			return !edge.hasClass("hidden");
		});
		var lines = [
			"<b>" + Ext.String.htmlEncode(node.data("label")) + "</b>",
			node.data("role") === "regulator"
				? "Regulator" + (node.data("omic")
					? " · " + Ext.String.htmlEncode(node.data("omic")) : "")
				: "Target",
			visibleEdges.length + " of " + node.connectedEdges().length + " edges shown"
		];
		if (node.data("rawId") !== node.data("label")) {
			lines.splice(1, 0, Ext.String.htmlEncode(node.data("rawId")));
		}
		tip.innerHTML = lines.join("<br>");
		tip.style.display = "block";
		tip.style.left = (position.x + 12) + "px";
		tip.style.top = (position.y + 12) + "px";
	};

	this._hideTooltip = function () {
		var tip = document.getElementById(this.containerId + "_tip");
		if (tip) tip.style.display = "none";
	};

	// ---- Toolbar -----------------------------------------------------------
	this._buildToolbar = function () {
		var host = document.getElementById(this.toolbarId);
		if (!host) return;
		var me = this;

		var conditionOptions = this.graph.conditions.map(function (condition) {
			return '<option value="' + Ext.String.htmlEncode(condition) + '">' +
				Ext.String.htmlEncode(condition) + '</option>';
		}).join("");

		host.innerHTML =
			'<div class="more-net-toolbar">' +
				(this.graph.conditions.length > 1
					? '<label>Condition ' +
						'<select class="more-net-condition">' + conditionOptions + '</select>' +
					  '</label>'
					: '') +
				'<label>R² ≥ <span class="more-net-r2-value">0.00</span>' +
					'<input type="range" class="more-net-r2" min="0" max="1" step="0.05" value="0">' +
				'</label>' +
				'<label>|coef| ≥ <span class="more-net-coef-value">0.00</span>' +
					'<input type="range" class="more-net-coef" min="0" max="' +
					(Math.ceil(this.dataMaxAbsCoef * 10) / 10) +
					'" step="0.01" value="0">' +
				'</label>' +
				'<label>Edges <span class="more-net-edges-value">' + DEFAULT_MAX_EDGES + '</span>' +
					'<input type="range" class="more-net-edges" min="50" max="' +
					EDGE_BUDGET_CEILING + '" step="50" value="' + DEFAULT_MAX_EDGES + '">' +
				'</label>' +
				'<input type="search" class="more-net-search" placeholder="Find a regulator or target">' +
				'<button type="button" class="more-net-relayout">Re-layout</button>' +
				'<button type="button" class="more-net-fit">Fit</button>' +
				'<button type="button" class="more-net-png">PNG</button>' +
			'</div>';

		var condition = host.querySelector(".more-net-condition");
		if (condition) {
			condition.addEventListener("change", function () {
				me._applyCondition(this.value);
				me._applyFilters();
			});
		}

		var r2 = host.querySelector(".more-net-r2");
		r2.addEventListener("input", function () {
			me.filterState.r2Min = Number(this.value);
			host.querySelector(".more-net-r2-value").textContent =
				me.filterState.r2Min.toFixed(2);
			me._applyFilters();
		});

		var coef = host.querySelector(".more-net-coef");
		coef.addEventListener("input", function () {
			me.filterState.absCoefMin = Number(this.value);
			host.querySelector(".more-net-coef-value").textContent =
				me.filterState.absCoefMin.toFixed(2);
			me._applyFilters();
		});

		var edges = host.querySelector(".more-net-edges");
		edges.addEventListener("input", function () {
			me.filterState.maxEdges = Number(this.value);
			host.querySelector(".more-net-edges-value").textContent =
				me.filterState.maxEdges;
			me._applyFilters();
		});

		host.querySelector(".more-net-relayout").addEventListener("click", function () {
			me._runLayout();
		});
		host.querySelector(".more-net-fit").addEventListener("click", function () {
			if (me.cy) me.cy.fit(me.cy.elements(":visible"), 24);
		});
		host.querySelector(".more-net-png").addEventListener("click", function () {
			me._downloadPng();
		});

		var search = host.querySelector(".more-net-search");
		search.addEventListener("input", function () {
			me._search(this.value);
		});
	};

	// Find by symbol or raw ID, centre on the first match and pin it. Substring
	// and case-insensitive, because the label on screen may be a symbol while
	// the identifier the user has in hand is an Ensembl ID, or the reverse.
	this._search = function (query) {
		if (!this.cy) return;
		query = String(query || "").trim().toLowerCase();
		if (!query) {
			this.pinnedNode = null;
			this._clearHighlight();
			return;
		}
		var match = this.cy.nodes().filter(function (node) {
			if (node.hasClass("hidden")) return false;
			return String(node.data("label")).toLowerCase().indexOf(query) !== -1 ||
				String(node.data("rawId")).toLowerCase().indexOf(query) !== -1;
		});
		if (!match.length) return;
		this.pinnedNode = match[0];
		this._highlight(match[0]);
		this.cy.animate({ center: { eles: match[0] }, zoom: 1.4 }, { duration: 250 });
	};

	this._downloadPng = function () {
		if (!this.cy) return;
		// `full: true` exports the graph rather than the viewport, and the
		// white background is deliberate: the canvas is transparent, and a
		// transparent PNG dropped into a document turns the edges invisible.
		var uri = this.cy.png({ full: true, scale: 2, bg: "#ffffff" });
		var link = document.createElement("a");
		link.href = uri;
		link.download = "MORE_regulator_target_network" +
			(this.currentCondition ? "_" + this.currentCondition : "") + ".png";
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
	};

	// ---- Side panel --------------------------------------------------------
	this._buildSidePanel = function () {
		var host = document.getElementById(this.sidePanelId);
		if (!host) return;
		var me = this;

		var legend = this.graph.omics.map(function (omic) {
			return '<label class="more-net-omic">' +
				'<input type="checkbox" checked data-omic="' +
					Ext.String.htmlEncode(omic) + '">' +
				'<span class="more-net-swatch" style="background:' +
					(me.omicColors[omic] || REG_PALETTE[0]) + '"></span>' +
				Ext.String.htmlEncode(omic) +
			'</label>';
		}).join("");

		host.innerHTML =
			'<div class="more-net-side">' +
				'<h6>Regulatory omics</h6>' +
				legend +
				'<h6>Target</h6>' +
				'<div class="more-net-omic">' +
					'<span class="more-net-swatch" style="background:' + TARGET_COLOR + '"></span>' +
					'Target feature</div>' +
				'<h6>Edge</h6>' +
				'<div class="more-net-omic">' +
					'<span class="more-net-swatch" style="background:' + EDGE_POS_COLOR + '"></span>' +
					'Positive coefficient</div>' +
				'<div class="more-net-omic">' +
					'<span class="more-net-swatch" style="background:' + EDGE_NEG_COLOR + '"></span>' +
					'Negative coefficient</div>' +
				'<p class="more-net-note">Width is |coefficient|. Click a node to pin ' +
					'its neighbourhood; click it again or the background to release.</p>' +
				'<h6>Top hubs</h6>' +
				'<div class="more-net-hubs"></div>' +
			'</div>';

		Array.prototype.forEach.call(
			host.querySelectorAll('input[data-omic]'), function (box) {
				box.addEventListener("change", function () {
					me.hiddenOmics[this.getAttribute("data-omic")] = !this.checked;
					me._applyFilters();
				});
			});
	};

	// The regulators with the most VISIBLE edges, which is not the same list as
	// the most edges overall — that is the point of showing it next to the
	// filters rather than once at build time.
	this._renderTopHubs = function () {
		var host = document.getElementById(this.sidePanelId);
		if (!host || !this.cy) return;
		var list = host.querySelector(".more-net-hubs");
		if (!list) return;
		var me = this;

		var hubs = this.cy.nodes('[role = "regulator"]').filter(function (node) {
			return !node.hasClass("hidden");
		}).map(function (node) {
			return {
				id: node.id(),
				label: node.data("label"),
				count: node.connectedEdges().filter(function (edge) {
					return !edge.hasClass("hidden");
				}).length
			};
		}).sort(function (a, b) { return b.count - a.count; }).slice(0, 10);

		if (!hubs.length) {
			list.innerHTML = '<p class="more-net-note">Nothing passes the current filters.</p>';
			return;
		}
		list.innerHTML = hubs.map(function (hub) {
			return '<a href="javascript:void(0)" class="more-net-hub" data-node="' +
				Ext.String.htmlEncode(hub.id) + '">' +
				Ext.String.htmlEncode(hub.label) +
				'<span class="more-net-hub-count">' + hub.count + '</span></a>';
		}).join("");

		Array.prototype.forEach.call(
			list.querySelectorAll(".more-net-hub"), function (link) {
				link.addEventListener("click", function () {
					var node = me.cy.getElementById(this.getAttribute("data-node"));
					if (!node || !node.length) return;
					me.pinnedNode = node;
					me._highlight(node);
					me.cy.animate({ center: { eles: node }, zoom: 1.3 }, { duration: 250 });
				});
			});
	};

	// ---- Subtitle ----------------------------------------------------------
	this._updateSubtitle = function () {
		var element = document.getElementById(this.subtitleId);
		if (!element || !this.cy) return;

		var visibleEdges = this.cy.edges().filter(function (edge) {
			return !edge.hasClass("hidden");
		}).length;
		var visibleNodes = this.cy.nodes().filter(function (node) {
			return !node.hasClass("hidden");
		}).length;

		var parts = [
			visibleNodes + " nodes · " + visibleEdges + " of " +
				this.graph.edges.length + " edges"
		];
		if (this.currentCondition) {
			parts.push("condition <b>" +
				Ext.String.htmlEncode(this.currentCondition) + "</b>");
		}
		if (this.filters) {
			var f = this.filters;
			parts.push("MORE: " + (f.method || "?") +
				", R²≥" + (f.filter_r2 != null ? f.filter_r2 : "?") +
				", α=" + (f.alpha != null ? f.alpha : "?") +
				", VIP≥" + (f.vip != null ? f.vip : "?"));
		}
		element.innerHTML = parts.join(" · ");
	};

	/**
	 * Instantiates the graph into its container, once.
	 *
	 * Extracted so that afterrender and expand can share it: the deferred build
	 * can be dropped (see the afterrender comment below), and expand is the
	 * natural place to notice and retry. Guarded on `this.cy` so a retry that
	 * was not needed costs nothing.
	 */
	this._buildGraph = function () {
		if (this.cy) return;

		var element = document.getElementById(this.containerId);
		if (!element) {
			console.warn("RegTargetNetwork: container not found");
			return;
		}
		try {
			this._instantiate(element);
		} catch (error) {
			console.error("RegTargetNetwork init failed:", error);
			element.innerHTML =
				'<div class="more-net-error">Failed to initialise ' +
				'network: ' + Ext.String.htmlEncode(
					String(error && error.message || error)) + '</div>';
		}
	};

	// ---- Ext component ----------------------------------------------------
	this.initComponent = function () {
		if (!this.hasData) {
			this.component = Ext.widget({ xtype: "container", hidden: true });
			return this.component;
		}

		var me = this;
		this.component = Ext.create("Ext.panel.Panel", {
			title: "MORE Regulator–Target Network",
			collapsible: true,
			collapsed: false,
			titleCollapse: true,
			margin: "10 10 10 10",
			bodyPadding: 0,
			cls: "more-net-panel",
			html:
				'<div id="' + this.toolbarId + '"></div>' +
				'<div id="' + this.subtitleId + '" class="more-net-subtitle">' +
					this.rows.length + ' rpc rows' +
				'</div>' +
				'<div class="more-net-body">' +
					'<div id="' + this.containerId + '" class="more-net-canvas"></div>' +
					'<div id="' + this.sidePanelId + '" class="more-net-sidepanel"></div>' +
				'</div>',
			listeners: {
				afterrender: function () {
					// Deferred a frame: Cytoscape measures its container, and
					// on Sencha 6 the panel does not have its final size until
					// after afterrender returns.
					//
					// paDeferFrame, not requestAnimationFrame. Chrome throttles
					// rAF to nothing in a background tab, and this is the call
					// that builds the graph - so on a hidden tab it never ran and
					// the panel came up empty: no canvas, no legend, no error, and
					// the subtitle stuck on its "N rpc rows" placeholder. Measured
					// that way before this change, on a tab that reported
					// document.visibilityState === "hidden".
					//
					// It did not recover either. Nothing retries, and the expand
					// handler below used to guard on `me.cy`, which is null in
					// exactly this case, so bringing the tab forward left the
					// panel blank for the rest of the session.
					//
					// Not a corner case: a job takes minutes, and reading
					// something else while it finishes is the ordinary way to use
					// this application, so the tab is commonly hidden at the
					// moment Step 3 renders.
					paDeferFrame(function () { me._buildGraph(); });
				},
				beforedestroy: function () { me._teardown(); },
				expand: function () {
					// Two cases. If the graph exists, its cached dimensions are
					// stale because the container had zero height while collapsed.
					// If it does not, this is the second chance for a build that
					// was dropped before it could run - a panel being expanded is
					// proof that someone is looking at it now.
					if (me.cy) {
						me.cy.resize();
						me.cy.fit(me.cy.elements(":visible"), 24);
					} else {
						me._buildGraph();
					}
				}
			}
		});
		return this.component;
	};

	this._teardown = function () {
		// One call, and the layout goes with it. The sigma version had to kill
		// a ForceAtlas2 web worker by hand here or it leaked across job
		// switches, and clear a wall-clock timer that might still be pending.
		if (this.cy) {
			try { this.cy.destroy(); }
			catch (error) { console.warn("RegTargetNetwork teardown:", error); }
			this.cy = null;
		}
		this.pinnedNode = null;
	};

	this.getComponent = function () {
		if (this.component === null || this.component === undefined) {
			return this.initComponent();
		}
		return this.component;
	};

	this.update = function () {
		// No-op — rpc data is immutable for the lifetime of a Step 3 session.
	};

	return this;
}
PA_Step3RegTargetNetworkView.prototype = new View();
