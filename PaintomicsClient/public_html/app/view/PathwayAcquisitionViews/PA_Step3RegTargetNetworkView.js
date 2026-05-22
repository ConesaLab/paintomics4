/**
 * PA_Step3RegTargetNetworkView — bipartite Regulator↔Target network for MORE.
 *
 * Renders the RegulationPerCondition rpc table as a sigma.js graph with
 * regulators on top and targets on bottom. Post-hoc filters (R², |coef|,
 * omic toggles, max edges) live in a toolbar / side panel (Steps 6–7).
 * ForceAtlas2 is used for X-axis untangling, with a Y-axis clamp that
 * preserves the bipartite split during and after layout.
 *
 * v1 scope: single-condition view, no all-conditions overlay or differential
 * mode (see /home/leyls/github/MORE/network/MORE_RegTargetNetwork_v1_Plan.md).
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

	// Per-instance handles. Kept on `this` so destroy() / model reload can
	// tear them down deterministically — sigma's web-worker FA2 must be
	// killed explicitly or it leaks across job switches.
	this.network         = null;
	this.clampInterval   = null;
	this.fa2StopTimer    = null;
	this.containerId     = "more_regtarget_sigma_" +
	                       Math.floor(Math.random() * 1e9);
	this.hubsContainerId = "more_regtarget_hubs_" +
	                       Math.floor(Math.random() * 1e9);
	this.toolbarId       = "more_regtarget_toolbar_" +
	                       Math.floor(Math.random() * 1e9);
	this.subtitleId      = "more_regtarget_subtitle_" +
	                       Math.floor(Math.random() * 1e9);
	this.currentCondition = null;  // resolved on first render
	this.adjacency        = null;  // nodeId → { neighborId: true }; built once
	this.pinnedHighlight  = null;  // when set, hover doesn't change highlight
	this.conditions       = null;  // list of "22","28",… from rpc columns
	this.dataMaxAbsCoef   = 1;     // upper bound for |coef| slider; from data
	this.filterState      = null;  // {r2Min, absCoefMin, maxEdges}; built on init

	// ---- Visual constants -------------------------------------------------
	// Omic palette — chosen to be distinguishable on a white canvas at small
	// node sizes. Unknown / unmapped omics fall through to DEFAULT_REG_COLOR.
	// Keys match the omic strings MORE writes into the rpc "omic" column.
	var OMIC_PALETTE = {
		"Gene expression":       "#1f77b4",
		"Gene Expression":       "#1f77b4",
		"miRNA-seq":             "#ff7f0e",
		"miRNA":                 "#ff7f0e",
		"TF":                    "#9467bd",
		"Transcription Factors": "#9467bd",
		"DNase-seq":             "#e377c2",
		"ATAC-seq":              "#2ca02c",
		"Methylation":           "#8c564b",
		"ChIP-seq":              "#bcbd22"
	};
	var DEFAULT_REG_COLOR = "#7f7f7f";
	var TARGET_COLOR      = "#444444";
	var EDGE_POS_COLOR    = "rgba(46, 134, 193, 0.55)";  // blue
	var EDGE_NEG_COLOR    = "rgba(192, 57,  43,  0.55)"; // red
	// Dimmed colors applied to nodes/edges that are NOT direct neighbors of
	// the currently highlighted node. Very faint so the structure of interest
	// stands out without losing all background context.
	var DIM_NODE          = "rgba(200, 200, 200, 0.18)";
	var DIM_EDGE          = "rgba(200, 200, 200, 0.06)";

	// Bipartite zones (sigma-coordinate space). Sigma uses screen-style
	// coordinates: +y is DOWN. So regulators-on-top means y < 0, and
	// targets-on-bottom means y > 0. The clamp re-pins every node to its
	// band each tick — we don't let FA2 move them vertically at all. The
	// bipartite is a hard constraint; FA2 is purely doing X-axis untangling.
	var REG_Y_PIN = -1.0;  // top of canvas
	var TGT_Y_PIN =  1.0;  // bottom of canvas
	var BAND_JITTER = 0.05; // small visual variation; computed once per node
	var FA2_DURATION_MS = 3500;
	var CLAMP_INTERVAL_MS = 60;

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
	// Single-pass build over rpc rows that stores per-condition coefficients
	// on each edge. Condition switching is then an O(E) attribute update,
	// not a full rebuild — preserves FA2 layout across condition changes.
	//
	// Returns {regulators, targets, edges, conditions, maxAbsCoef}.
	//
	// Edge .coefPerCondition is a {condName: numberOrNull} dict; null means
	// the underlying rpc cell was blank/NaN for that condition (regression
	// produced no value, often because the regulator wasn't significant for
	// that condition). An edge whose entire coefPerCondition is null gets
	// dropped — it can't contribute to any view.
	//
	// Any-omic union: a regulator stays in `regulators` if ANY of its omics
	// surfaced an edge. Per-omic counts are kept so getPrimaryOmic() can pick
	// the dominant one for coloring.
	this.buildBipartiteGraph = function () {
		var colIdx = {};
		for (var i = 0; i < this.columns.length; i++) {
			colIdx[this.columns[i]] = i;
		}
		var r2Idx    = colIdx.R2;
		var tgtIdx   = colIdx.targetF;
		var regIdx   = colIdx.regulator;
		var omicIdx  = colIdx.omic;

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
		var globalMaxAbsCoef = 0;

		var rows = this.rows;
		for (var r = 0; r < rows.length; r++) {
			var row = rows[r];
			var reg = row[regIdx];
			var tgt = row[tgtIdx];
			if (reg == null || reg === "" || tgt == null || tgt === "") continue;

			var omic = (omicIdx != null && row[omicIdx]) || "Unknown";

			// Build the per-condition coefficient map and track whether ANY
			// condition produced a usable value. Rows with all-null coefs
			// can't draw an edge in any view and are dropped.
			var coefMap = {};
			var anyCoef = false;
			var rowMaxAbsCoef = 0;
			for (var k = 0; k < conditions.length; k++) {
				var cond = conditions[k];
				var raw = row[coefIdxByCond[cond]];
				if (raw == null || raw === "" || raw === "None") {
					coefMap[cond] = null;
					continue;
				}
				var num = Number(raw);
				if (isNaN(num)) {
					coefMap[cond] = null;
					continue;
				}
				coefMap[cond] = num;
				anyCoef = true;
				var absN = Math.abs(num);
				if (absN > rowMaxAbsCoef) rowMaxAbsCoef = absN;
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
					id: regId, name: reg,
					omics: {}, omicCounts: {}, degree: 0
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
				id:               "e:" + regId + "->" + tgtId + ":" + omic + ":" + r,
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
			maxAbsCoef: globalMaxAbsCoef
		};
	};

	// Resolve a regulator's "primary" omic — the one contributing the most
	// edges to it. Used for node color when a regulator spans multiple omics
	// (e.g., a gene appearing as both target-side expression and as a TF).
	var getPrimaryOmic = function (regulator) {
		var best = null, bestCount = -1;
		var counts = regulator.omicCounts;
		for (var omic in counts) {
			if (counts[omic] > bestCount) {
				bestCount = counts[omic];
				best = omic;
			}
		}
		return best;
	};

	// Symbol-aware label for tooltips/labels. Mirrors PA_Step3RegulationView's
	// renderer: prefer the resolved gene symbol when available, fall back to
	// the raw ID. UPPERCASE keys to match server-side normalisation.
	var _label = function (id, symbols) {
		if (!id) return "";
		var sym = symbols && symbols[String(id).toUpperCase()];
		return sym ? sym + " (" + id + ")" : id;
	};

	// Map node degree → sigma display size. Linear with a floor so leaf nodes
	// stay visible. Sigma's auto-scaling handles final pixel size; this is
	// the relative weight.
	var _nodeSize = function (degree) {
		return 1 + Math.sqrt(degree);
	};

	// Map |coef| → edge thickness. Coefficients in MORE are unbounded but
	// typically |coef| ∈ [0, ~2]. Cap at the 95th-pctl-ish to avoid one
	// dominant edge swamping the rest visually.
	var _edgeSize = function (absCoef) {
		var s = Math.min(absCoef, 1.5);
		return 0.3 + s * 1.2;
	};

	// ---- Sigma instantiation ---------------------------------------------
	// Builds the sigma graph from the prepared {regulators, targets, edges}
	// triple, sets bipartite initial positions, and instantiates sigma in
	// the supplied DOM container. Called from the panel's afterrender hook
	// because sigma needs a measurable parent element.
	this._instantiateSigma = function (containerEl) {
		var graph = this.buildBipartiteGraph();
		var symbols = this.symbols || {};
		// Expose for toolbar / filter logic.
		this.conditions     = graph.conditions;
		this.dataMaxAbsCoef = graph.maxAbsCoef || 1;
		// Default current condition to the first one present, unless an
		// earlier initComponent() already chose it.
		if (!this.currentCondition && graph.conditions.length > 0) {
			this.currentCondition = graph.conditions[0];
		}
		// Initialise filter state.
		// R² floor: honour MORE-side filter_r2; user can only tighten it.
		// |coef| floor: start at 0 — MORE already gated by alpha/VIP.
		// maxEdges: cap at 500 by default. Plays well with 600px canvas.
		var r2Floor = (this.filters && this.filters.filter_r2 != null)
			? Number(this.filters.filter_r2) : 0;
		this.filterState = {
			r2Floor:     r2Floor,
			r2Min:       r2Floor,
			absCoefMin:  0,
			maxEdges:    500
		};

		var regList = Object.keys(graph.regulators).map(function (k) {
			return graph.regulators[k];
		});
		var tgtList = Object.keys(graph.targets).map(function (k) {
			return graph.targets[k];
		});

		// Initial X spread — evenly distributed across [-1, 1]. FA2 will then
		// pull connected nodes together along X. Y is pinned to the bipartite
		// zone with small jitter so FA2 doesn't see all nodes at identical Y
		// (which can cause its repulsion to overshoot).
		// Per-node Y jitter is fixed at creation so the bipartite bands
		// have a stable visual texture instead of flickering each clamp.
		var sigmaNodes = [];
		var nReg = regList.length;
		regList.forEach(function (reg, idx) {
			var primaryOmic = getPrimaryOmic(reg);
			var color = OMIC_PALETTE[primaryOmic] || DEFAULT_REG_COLOR;
			var jitter = (Math.random() - 0.5) * BAND_JITTER;
			sigmaNodes.push({
				id:    reg.id,
				label: _label(reg.name, symbols),
				x:     nReg > 1 ? -1 + 2 * (idx / (nReg - 1)) : 0,
				y:     REG_Y_PIN + jitter,
				size:  _nodeSize(reg.degree),
				color: color,
				kind:        "regulator",
				yPin:        REG_Y_PIN + jitter,
				rawName:     reg.name,
				primaryOmic: primaryOmic,
				omics:       Object.keys(reg.omics),
				degree:      reg.degree
			});
		});
		var nTgt = tgtList.length;
		tgtList.forEach(function (tgt, idx) {
			var jitter = (Math.random() - 0.5) * BAND_JITTER;
			sigmaNodes.push({
				id:    tgt.id,
				label: _label(tgt.name, symbols),
				x:     nTgt > 1 ? -1 + 2 * (idx / (nTgt - 1)) : 0,
				y:     TGT_Y_PIN + jitter,
				size:  _nodeSize(tgt.degree),
				color: TARGET_COLOR,
				kind:    "target",
				yPin:    TGT_Y_PIN + jitter,
				rawName: tgt.name,
				degree:  tgt.degree
			});
		});

		// Sigma edges carry the full coefPerCondition map. _applyCondition()
		// fills in coef / absCoef / size / color / originalColor based on the
		// active condition; without that call, edges have no visual yet.
		var sigmaEdges = graph.edges.map(function (e) {
			return {
				id:               e.id,
				source:           e.source,
				target:           e.target,
				omic:             e.omic,
				r2:               e.r2,
				coefPerCondition: e.coefPerCondition,
				maxAbsCoef:       e.maxAbsCoef,
				// Filled in by _applyCondition before first render.
				coef:    null,
				absCoef: 0,
				size:    0.5,
				color:   DIM_EDGE,
				originalColor: DIM_EDGE
			};
		});

		// Stamp originalColor on every node so highlight can restore.
		for (var k = 0; k < sigmaNodes.length; k++) {
			sigmaNodes[k].originalColor = sigmaNodes[k].color;
		}

		this.network = new sigma({
			graph: { nodes: sigmaNodes, edges: sigmaEdges },
			renderers: [{ container: containerEl, type: "canvas" }],
			settings: {
				zoomMin: 0.05,
				zoomMax: 10,
				zoomingRatio: 1.2,
				labelThreshold: 8,
				labelMaxLength: 18,
				defaultEdgeType: "line",
				defaultEdgeColor: "default",
				edgeColor: "default",
				batchEdgesDrawing: true,
				hideEdgesOnMove: true,
				minNodeSize:  2,
				maxNodeSize: 14,
				minEdgeSize:  0.3,
				maxEdgeSize:  2.5,
				defaultLabelSize: 11
			}
		});

		// Build adjacency once for hover/click highlight. Symmetric — the
		// graph is undirected for highlighting purposes (hovering a target
		// reveals its regulators, and vice-versa).
		this.adjacency = this._buildAdjacency(sigmaEdges);

		// Apply active condition (sets edge coef/size/color from coefMap)
		// and run the initial filter pass so the default view is already
		// trimmed to 500 strongest edges. Without these, sigma would render
		// edges with the placeholder DIM_EDGE color from above.
		this._applyCondition(this.currentCondition);
		this._applyFilters();

		// Toolbar lives above the hubs strip; build it now that we know
		// conditions list + dataMaxAbsCoef.
		this._buildToolbar();
		this._wireToolbar();

		// Wire hover/click highlight + render the top-hubs overlay (consults
		// current visibility, so it reflects whatever the active filters show).
		this._bindHighlight();
		this._renderTopHubs();

		// Run FA2 with hard Y-pin. FA2 untangles X-axis crossings; the clamp
		// loop pins every node to its precomputed yPin each tick. Effectively
		// this is a 1D force layout along X with the bipartite as a fixed
		// constraint. Low gravity + high scaling keeps clusters from
		// collapsing into the centre into an unreadable hairball.
		this._startBipartiteClamp();
		this.network.startForceAtlas2({
			worker: true,
			barnesHutOptimize: sigmaNodes.length > 500,
			barnesHutTheta: 0.6,
			scalingRatio: 20,
			slowDown: 3,
			gravity: 0.05,
			strongGravityMode: false,
			edgeWeightInfluence: 0.3,
			outboundAttractionDistribution: false,
			adjustSizes: true
		});

		var me = this;
		this.fa2StopTimer = setTimeout(function () {
			if (me.network && me.network.isForceAtlas2Running()) {
				me.network.stopForceAtlas2();
			}
			// One last clamp + refresh after FA2 stops, then halt the loop
			// so we're not chewing CPU forever.
			me._clampOnce();
			me.network.refresh({ skipIndexation: false });
			me._stopBipartiteClamp();
		}, FA2_DURATION_MS);
	};

	// ---- Highlight (hover + click + hub-link) ----------------------------
	// Symmetric adjacency map: each edge contributes both directions so
	// hovering a target lights up its regulators, and vice-versa. O(E)
	// build, O(1) lookups per render.
	this._buildAdjacency = function (sigmaEdges) {
		var adj = {};
		for (var i = 0; i < sigmaEdges.length; i++) {
			var e = sigmaEdges[i];
			if (!adj[e.source]) adj[e.source] = {};
			if (!adj[e.target]) adj[e.target] = {};
			adj[e.source][e.target] = true;
			adj[e.target][e.source] = true;
		}
		return adj;
	};

	// Dim everything except the focal node + its direct neighbors. Modifies
	// node.color / edge.color in place — sigma's renderer reads these on
	// every frame, so a refresh() is all that's needed to update the view.
	this._highlightNode = function (nodeId) {
		if (!this.network || !this.adjacency) return;
		var neighbors = this.adjacency[nodeId] || {};
		var nodes = this.network.graph.nodes();
		var edges = this.network.graph.edges();
		for (var i = 0; i < nodes.length; i++) {
			var n = nodes[i];
			n.color = (n.id === nodeId || neighbors[n.id])
				? n.originalColor
				: DIM_NODE;
		}
		for (var j = 0; j < edges.length; j++) {
			var ed = edges[j];
			// Edge is "in focus" if it touches the focal node directly.
			ed.color = (ed.source === nodeId || ed.target === nodeId)
				? ed.originalColor
				: DIM_EDGE;
		}
		this.network.refresh({ skipIndexation: true });
	};

	this._clearHighlight = function () {
		if (!this.network) return;
		var nodes = this.network.graph.nodes();
		var edges = this.network.graph.edges();
		for (var i = 0; i < nodes.length; i++) nodes[i].color = nodes[i].originalColor;
		for (var j = 0; j < edges.length; j++) edges[j].color = edges[j].originalColor;
		this.network.refresh({ skipIndexation: true });
	};

	// Sigma event wiring. Pinned (click) highlight wins over hover — once a
	// node is pinned, hovering elsewhere doesn't blow it away. Clicking the
	// empty stage unpins.
	this._bindHighlight = function () {
		var me = this;
		me.network.bind("overNode", function (e) {
			if (me.pinnedHighlight) return;
			me._highlightNode(e.data.node.id);
		});
		me.network.bind("outNode", function () {
			if (me.pinnedHighlight) return;
			me._clearHighlight();
		});
		me.network.bind("clickNode", function (e) {
			var id = e.data.node.id;
			if (me.pinnedHighlight === id) {
				me.pinnedHighlight = null;
				me._clearHighlight();
			} else {
				me.pinnedHighlight = id;
				me._highlightNode(id);
			}
		});
		me.network.bind("clickStage", function () {
			if (me.pinnedHighlight) {
				me.pinnedHighlight = null;
				me._clearHighlight();
			}
		});
	};

	// ---- Top-N hub overlay ----------------------------------------------
	// Computes top-5 regulators and top-5 targets by *currently visible*
	// degree — so hubs reflect the active filters, not the unfiltered graph.
	// Re-called from _applyFilters whenever visibility changes.
	this._renderTopHubs = function () {
		var hubsEl = document.getElementById(this.hubsContainerId);
		if (!hubsEl || !this.network) return;

		var nodes = this.network.graph.nodes();
		var edges = this.network.graph.edges();

		// Visible-degree map: only edges marked !hidden count.
		var degree = {};
		for (var i = 0; i < edges.length; i++) {
			var e = edges[i];
			if (e.hidden) continue;
			degree[e.source] = (degree[e.source] || 0) + 1;
			degree[e.target] = (degree[e.target] || 0) + 1;
		}
		var regs = [], tgts = [];
		for (var i = 0; i < nodes.length; i++) {
			var n = nodes[i];
			var d = degree[n.id] || 0;
			if (d === 0) continue;
			var item = { id: n.id, name: n.rawName, degree: d };
			if (n.kind === "regulator") regs.push(item);
			else tgts.push(item);
		}
		var topRegs = regs.sort(function (a, b) {
			return b.degree - a.degree;
		}).slice(0, 5);
		var topTgts = tgts.sort(function (a, b) {
			return b.degree - a.degree;
		}).slice(0, 5);

		var symbols = this.symbols || {};
		var fmt = function (item) {
			var sym = symbols[String(item.name).toUpperCase()];
			var disp = sym ? sym : item.name;
			return '<a class="more-hub-link" data-node-id="' +
				Ext.String.htmlEncode(item.id) + '" ' +
				'style="cursor:pointer;color:#1f77b4;text-decoration:none;' +
				'margin-right:8px;">' +
				Ext.String.htmlEncode(disp) +
				' <span style="color:#888;">(n=' + item.degree + ')</span>' +
				'</a>';
		};

		hubsEl.innerHTML =
			'<div style="padding:6px 14px;font-size:0.85em;color:#555;' +
			'border-bottom:1px solid #eee;background:#f5f5f5;">' +
				'<b>Top regulators:</b> ' +
				(topRegs.length ? topRegs.map(fmt).join("") : '<i>none</i>') +
				' &nbsp;·&nbsp; ' +
				'<b>Most-regulated targets:</b> ' +
				(topTgts.length ? topTgts.map(fmt).join("") : '<i>none</i>') +
				' &nbsp;<span style="color:#888;font-size:0.9em;">' +
				'(click to highlight · click again or click empty area to clear)' +
				'</span>' +
			'</div>';

		// Wire clicks. Use the container so we don't have to re-bind if the
		// overlay ever re-renders.
		var me = this;
		hubsEl.onclick = function (ev) {
			var a = ev.target.closest && ev.target.closest("a.more-hub-link");
			if (!a) return;
			ev.preventDefault();
			var nodeId = a.getAttribute("data-node-id");
			if (!nodeId) return;
			if (me.pinnedHighlight === nodeId) {
				me.pinnedHighlight = null;
				me._clearHighlight();
			} else {
				me.pinnedHighlight = nodeId;
				me._highlightNode(nodeId);
			}
		};
	};

	// ---- Condition & filter pipeline ------------------------------------
	// Apply a new active condition to every edge. Rewrites coef / absCoef /
	// size / color / originalColor from each edge's coefPerCondition map.
	// Edges with a null coef for this condition get a `_missingForCondition`
	// flag — _applyFilters() reads that to hide them. Does NOT refresh sigma
	// (the caller batches one refresh after _applyFilters).
	this._applyCondition = function (condition) {
		this.currentCondition = condition;
		if (!this.network) return;
		var edges = this.network.graph.edges();
		for (var i = 0; i < edges.length; i++) {
			var e = edges[i];
			var coef = e.coefPerCondition ? e.coefPerCondition[condition] : null;
			if (coef == null) {
				e._missingForCondition = true;
				continue;
			}
			e._missingForCondition = false;
			e.coef          = coef;
			e.absCoef       = Math.abs(coef);
			e.size          = _edgeSize(e.absCoef);
			e.color         = coef >= 0 ? EDGE_POS_COLOR : EDGE_NEG_COLOR;
			e.originalColor = e.color;
		}
		// Changing the condition invalidates any pinned highlight — colours
		// shifted, and the user is now looking at a different slice.
		this.pinnedHighlight = null;
	};

	// Apply the current filterState. Three-pass:
	//   1. Per-edge predicates: missing-for-condition, R² floor, |coef| floor.
	//   2. Max-edges cap: among edges that passed (1), keep the top |coef|.
	//   3. Orphan-node sweep: nodes with zero visible edges are hidden.
	// Then refresh sigma once + recompute top hubs + redraw subtitle.
	this._applyFilters = function () {
		if (!this.network || !this.filterState) return;
		var state = this.filterState;
		var edges = this.network.graph.edges();
		var nodes = this.network.graph.nodes();

		// Pass 1.
		var survivors = [];
		for (var i = 0; i < edges.length; i++) {
			var e = edges[i];
			if (e._missingForCondition) { e.hidden = true; continue; }
			if (e.r2 != null && e.r2 < state.r2Min) { e.hidden = true; continue; }
			if (e.absCoef < state.absCoefMin) { e.hidden = true; continue; }
			e.hidden = false;
			survivors.push(e);
		}

		// Pass 2: cap to top-N |coef|. "all" disables the cap.
		if (state.maxEdges !== "all") {
			var cap = Number(state.maxEdges);
			if (survivors.length > cap) {
				survivors.sort(function (a, b) { return b.absCoef - a.absCoef; });
				for (var j = cap; j < survivors.length; j++) {
					survivors[j].hidden = true;
				}
				survivors.length = cap;
			}
		}

		// Pass 3: hide orphan nodes (no visible edges).
		var connected = {};
		for (var i = 0; i < edges.length; i++) {
			var e = edges[i];
			if (!e.hidden) {
				connected[e.source] = true;
				connected[e.target] = true;
			}
		}
		var visibleRegs = 0, visibleTgts = 0;
		for (var i = 0; i < nodes.length; i++) {
			var n = nodes[i];
			n.hidden = !connected[n.id];
			if (!n.hidden) {
				if (n.kind === "regulator") visibleRegs++;
				else visibleTgts++;
			}
		}
		this._lastFilterStats = {
			visibleEdges:      survivors.length,
			visibleRegulators: visibleRegs,
			visibleTargets:    visibleTgts
		};

		this.network.refresh({ skipIndexation: true });
		this._renderTopHubs();
		this._updateSubtitle();
	};

	// ---- Toolbar build + wire -------------------------------------------
	// Compact horizontal strip rendered into this.toolbarId. Generated here
	// rather than in initComponent so the condition <select> can be populated
	// from the actual rpc condition list (only known after buildBipartiteGraph).
	this._buildToolbar = function () {
		var el = document.getElementById(this.toolbarId);
		if (!el || !this.conditions) return;
		var s = this.filterState;
		var dataMax = this.dataMaxAbsCoef;
		// Slider step ~ 1/100th of the dynamic range, with sane bounds.
		var coefStep = Math.max(0.01, Math.round(dataMax * 0.01 * 100) / 100);
		var r2Step   = 0.01;
		// Build the condition option list.
		var condOpts = this.conditions.map(function (c) {
			var sel = (c === this.currentCondition) ? " selected" : "";
			return '<option value="' + Ext.String.htmlEncode(c) + '"' + sel + '>'
				+ Ext.String.htmlEncode(c) + '</option>';
		}, this).join("");
		var maxEdgeOpts = "";
		[100, 250, 500, 1000, 2500, "all"].forEach(function (v) {
			var sel = (String(v) === String(s.maxEdges)) ? " selected" : "";
			var label = v === "all" ? "All" : v;
			maxEdgeOpts += '<option value="' + v + '"' + sel + '>' + label + '</option>';
		});

		el.innerHTML =
			'<div style="padding:8px 14px;display:flex;flex-wrap:wrap;gap:14px;' +
			'align-items:center;background:#f5f7fa;border-bottom:1px solid #e0e0e0;' +
			'font-size:0.85em;color:#444;">' +
				'<div><label style="margin-right:6px;">Condition:</label>' +
					'<select id="' + this.toolbarId + '_cond" style="padding:2px 4px;">' +
					condOpts + '</select></div>' +
				'<div><label style="margin-right:6px;">R²&nbsp;≥</label>' +
					'<input type="range" id="' + this.toolbarId + '_r2" ' +
					'min="' + s.r2Floor + '" max="1" step="' + r2Step + '" ' +
					'value="' + s.r2Min + '" style="vertical-align:middle;width:110px;">' +
					'<span id="' + this.toolbarId + '_r2val" ' +
					'style="display:inline-block;min-width:36px;text-align:right;">' +
					s.r2Min.toFixed(2) + '</span></div>' +
				'<div><label style="margin-right:6px;">|coef|&nbsp;≥</label>' +
					'<input type="range" id="' + this.toolbarId + '_coef" ' +
					'min="0" max="' + dataMax + '" step="' + coefStep + '" ' +
					'value="' + s.absCoefMin + '" style="vertical-align:middle;width:110px;">' +
					'<span id="' + this.toolbarId + '_coefval" ' +
					'style="display:inline-block;min-width:36px;text-align:right;">' +
					s.absCoefMin.toFixed(2) + '</span></div>' +
				'<div><label style="margin-right:6px;">Max edges:</label>' +
					'<select id="' + this.toolbarId + '_max" style="padding:2px 4px;">' +
					maxEdgeOpts + '</select></div>' +
				'<button id="' + this.toolbarId + '_resume" ' +
					'style="padding:3px 10px;border:1px solid #aaa;background:white;' +
					'cursor:pointer;border-radius:3px;">▶ Resume layout</button>' +
				(s.r2Floor > 0
					? '<span style="color:#888;font-size:0.9em;">' +
					  '(R² floor ' + s.r2Floor.toFixed(2) +
					  ' inherited from MORE)</span>'
					: '') +
			'</div>';
	};

	this._wireToolbar = function () {
		var me = this;
		var $ = function (suffix) {
			return document.getElementById(me.toolbarId + suffix);
		};
		var condSel  = $("_cond");
		var r2Sl     = $("_r2");
		var r2Val    = $("_r2val");
		var coefSl   = $("_coef");
		var coefVal  = $("_coefval");
		var maxSel   = $("_max");
		var resumeBt = $("_resume");

		if (condSel) condSel.onchange = function () {
			me._applyCondition(condSel.value);
			me._applyFilters();
		};
		// Sliders fire on every tick (input event). Filters are cheap enough
		// (3k edges max) that we don't need to debounce.
		if (r2Sl) r2Sl.oninput = function () {
			me.filterState.r2Min = Number(r2Sl.value);
			if (r2Val) r2Val.textContent = me.filterState.r2Min.toFixed(2);
			me._applyFilters();
		};
		if (coefSl) coefSl.oninput = function () {
			me.filterState.absCoefMin = Number(coefSl.value);
			if (coefVal) coefVal.textContent = me.filterState.absCoefMin.toFixed(2);
			me._applyFilters();
		};
		if (maxSel) maxSel.onchange = function () {
			me.filterState.maxEdges = maxSel.value;
			me._applyFilters();
		};
		if (resumeBt) resumeBt.onclick = function () {
			me._resumeLayout();
		};
	};

	// ---- Resume layout --------------------------------------------------
	// Re-run FA2 on the current (possibly filtered) graph. Cheap re-init —
	// we don't re-randomise X positions, so this is "continue layout from
	// here" rather than "redo from scratch". With many edges hidden, FA2
	// will pull the remaining visible nodes into tighter clusters.
	this._resumeLayout = function () {
		if (!this.network) return;
		if (this.network.isForceAtlas2Running()) return;
		this._clampOnce();
		this.network.refresh({ skipIndexation: true });
		this._startBipartiteClamp();
		this.network.startForceAtlas2({
			worker: true,
			barnesHutOptimize: this.network.graph.nodes().length > 500,
			barnesHutTheta: 0.6,
			scalingRatio: 20,
			slowDown: 3,
			gravity: 0.05,
			strongGravityMode: false,
			edgeWeightInfluence: 0.3,
			outboundAttractionDistribution: false,
			adjustSizes: true
		});
		var me = this;
		if (this.fa2StopTimer) clearTimeout(this.fa2StopTimer);
		this.fa2StopTimer = setTimeout(function () {
			if (me.network && me.network.isForceAtlas2Running()) {
				me.network.stopForceAtlas2();
			}
			me._clampOnce();
			me.network.refresh({ skipIndexation: false });
			me._stopBipartiteClamp();
		}, FA2_DURATION_MS);
	};

	// Subtitle reflects the active condition and filter outcome. Called from
	// _applyFilters so it stays in sync with what's actually visible.
	this._updateSubtitle = function () {
		var el = document.getElementById(this.subtitleId);
		if (!el) return;
		var stats = this._lastFilterStats || {};
		var parts = [];
		parts.push(this.rows.length + " rpc rows");
		if (this.currentCondition) {
			parts.push("showing <b>" +
				Ext.String.htmlEncode(this.currentCondition) + "</b>");
		}
		if (stats.visibleEdges != null) {
			parts.push(stats.visibleEdges + " edges · " +
				stats.visibleRegulators + " regulators · " +
				stats.visibleTargets + " targets visible");
		}
		if (this.filters) {
			var f = this.filters;
			parts.push("MORE: " + (f.method || "?") +
				", R²≥" + (f.filter_r2 != null ? f.filter_r2 : "?") +
				", α=" + (f.alpha != null ? f.alpha : "?") +
				", VIP≥" + (f.vip != null ? f.vip : "?"));
		}
		el.innerHTML = parts.join(" · ");
	};

	// Hard-pin every node to its yPin. Sigma is single-threaded for graph
	// state; the FA2 worker writes node.x/node.y back through postMessage,
	// so overwriting y here is race-free.
	this._clampOnce = function () {
		if (!this.network) return;
		var nodes = this.network.graph.nodes();
		for (var i = 0; i < nodes.length; i++) {
			nodes[i].y = nodes[i].yPin;
		}
	};

	this._startBipartiteClamp = function () {
		var me = this;
		if (me.clampInterval) clearInterval(me.clampInterval);
		me.clampInterval = setInterval(function () {
			me._clampOnce();
			// skipIndexation keeps the quadtree stable during clamping —
			// labels stay anchored, edges don't flicker.
			if (me.network) me.network.refresh({ skipIndexation: true });
		}, CLAMP_INTERVAL_MS);
	};

	this._stopBipartiteClamp = function () {
		if (this.clampInterval) {
			clearInterval(this.clampInterval);
			this.clampInterval = null;
		}
	};

	// ---- Ext component ---------------------------------------------------
	this.initComponent = function () {
		if (!this.hasData) {
			this.component = Ext.widget({ xtype: "container", hidden: true });
			return this.component;
		}

		// First Group_* column becomes the initial condition. Step 6 will add
		// a <select> bound to this.currentCondition.
		this.currentCondition = null;
		for (var i = 0; i < this.columns.length; i++) {
			if (this.columns[i].indexOf("Group_") === 0) {
				this.currentCondition = this.columns[i].replace(/^Group_/, "");
				break;
			}
		}

		var me = this;
		var nConditions = this.columns.filter(function (c) {
			return c.indexOf("Group_") === 0;
		}).length;

		// Subtitle line — surfaces dataset + filter context so users know
		// what's on screen without flipping back to the table.
		var subtitle =
			this.rows.length + " rpc rows · " +
			nConditions + " condition(s)" +
			(this.currentCondition
				? " · showing <b>" + Ext.String.htmlEncode(this.currentCondition) + "</b>"
				: "");
		if (this.filters) {
			var f = this.filters;
			subtitle += " · MORE: " + (f.method || "?") +
				", R²≥" + (f.filter_r2 != null ? f.filter_r2 : "?") +
				", α=" + (f.alpha != null ? f.alpha : "?") +
				", VIP≥" + (f.vip != null ? f.vip : "?");
		}

		this.component = Ext.create("Ext.panel.Panel", {
			title: "MORE Regulator–Target Network",
			collapsible: true,
			collapsed: false,
			titleCollapse: true,
			margin: "10 10 10 10",
			bodyPadding: 0,
			html:
				// Toolbar slot — populated by _buildToolbar() once we know
				// the rpc's condition list. Empty <div> until then.
				'<div id="' + this.toolbarId + '"></div>' +
				// Subtitle is updated by _updateSubtitle() with live filter stats.
				// Initial content is the "static" subtitle; will be overwritten.
				'<div id="' + this.subtitleId + '" ' +
				'style="padding:8px 14px; font-size:0.85em; color:#555; ' +
				'border-bottom:1px solid #e0e0e0;">' + subtitle + '</div>' +
				// Hubs overlay strip — populated after sigma is instantiated.
				'<div id="' + this.hubsContainerId + '"></div>' +
				'<div id="' + this.containerId + '" ' +
				'style="width:100%; height:600px; position:relative; ' +
				'background:#fafafa;"></div>',
			listeners: {
				afterrender: function () {
					// Defer sigma instantiation until the container DOM is
					// in-document AND the panel has its final width/height.
					// One animation frame is empirically enough on Sencha 6.
					requestAnimationFrame(function () {
						var el = document.getElementById(me.containerId);
						if (!el) {
							console.warn("RegTargetNetwork: container not found");
							return;
						}
						try {
							me._instantiateSigma(el);
						} catch (ex) {
							console.error("RegTargetNetwork init failed:", ex);
							el.innerHTML =
								'<div style="padding:30px;text-align:center;color:#a33;">' +
								'Failed to initialise network: ' +
								Ext.String.htmlEncode(String(ex && ex.message || ex)) +
								'</div>';
						}
					});
				},
				beforedestroy: function () {
					me._teardown();
				},
				collapse: function () {
					// Pause FA2 when the panel is collapsed — no point burning
					// a worker for an invisible canvas.
					if (me.network && me.network.isForceAtlas2Running()) {
						me.network.stopForceAtlas2();
					}
				}
			}
		});
		return this.component;
	};

	this._teardown = function () {
		this._stopBipartiteClamp();
		if (this.fa2StopTimer) {
			clearTimeout(this.fa2StopTimer);
			this.fa2StopTimer = null;
		}
		if (this.network) {
			try {
				if (this.network.isForceAtlas2Running()) {
					this.network.killForceAtlas2();
				}
				this.network.kill();
			} catch (ex) {
				console.warn("RegTargetNetwork teardown:", ex);
			}
			this.network = null;
		}
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
