/**
 * PA_Step3RegTargetNetworkView — Regulator↔Target network for MORE.
 *
 * Renders the RegulationPerCondition rpc table as a free 2D sigma.js graph.
 * Role is encoded visually (regulator = larger + omic-colored + labelled;
 * target = small + gray + label on hover) rather than positionally — FA2
 * is allowed to run in 2D so that hub regulators land at the centre of
 * their fan of targets, making "who regulates whom" visually obvious.
 *
 * Post-hoc filters (condition, R², |coef|, max edges) live in a toolbar
 * (Step 6); side panel with omic toggles + legend in Step 7. Default view
 * is capped at the top 100 strongest edges so the network stays readable.
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
	this.fa2StopTimer    = null;
	this.containerId     = "more_regtarget_sigma_" +
	                       Math.floor(Math.random() * 1e9);
	this.hubsPanelId     = "more_regtarget_hubs_" +
	                       Math.floor(Math.random() * 1e9);
	this.toolbarId       = "more_regtarget_toolbar_" +
	                       Math.floor(Math.random() * 1e9);
	this.subtitleId      = "more_regtarget_subtitle_" +
	                       Math.floor(Math.random() * 1e9);
	this.sidePanelId     = "more_regtarget_side_" +
	                       Math.floor(Math.random() * 1e9);
	this.currentCondition = null;  // resolved on first render
	this.adjacency        = null;  // nodeId → { neighborId: true }; built once
	this.pinnedHighlight  = null;  // when set, hover doesn't change highlight
	this.conditions       = null;  // list of "22","28",… from rpc columns
	this.dataMaxAbsCoef   = 1;     // upper bound for |coef| slider; from data
	this.filterState      = null;  // {r2Min, absCoefMin, maxEdges}; built on init

	// ---- Visual constants -------------------------------------------------
	// Regulator palette — generic, 8 entries, assigned to omics in the order
	// they appear in the rpc (alphabetical, so stable across reloads of the
	// same job). No name-based hardcoding: regulators can be any omic the
	// user defined in MORE, so we don't try to predict semantics. Targets
	// are always rendered in TARGET_COLOR (grey) — gene expression in this
	// pipeline lives on the target side, never as a regulator omic.
	//
	// Colour choice avoids edge red and edge blue so the regulator-target
	// distinction stays clean against the line colours.
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
	var TARGET_COLOR      = "#B8B8B8";                  // light neutral grey
	var EDGE_POS_COLOR    = "rgba(46, 134, 193, 0.55)";  // blue
	var EDGE_NEG_COLOR    = "rgba(192, 57,  43,  0.55)"; // red

	// Install a custom canvas node renderer that always paints a same-hue
	// border around the fill — Linkurious's default `def` renderer ignores
	// `borderSize` (it's only consulted by the select/active plugin), so
	// without this borders never appear at rest. Idempotent: re-running this
	// constructor in a later view instance is a no-op.
	if (typeof sigma !== "undefined" && sigma.canvas && sigma.canvas.nodes &&
		!sigma.canvas.nodes.bordered) {
		sigma.canvas.nodes.bordered = function (node, context, settings) {
			var prefix = settings("prefix") || "";
			var size = node[prefix + "size"] || 1;
			var x    = node[prefix + "x"];
			var y    = node[prefix + "y"];
			context.fillStyle = node.color || settings("defaultNodeColor");
			context.beginPath();
			context.arc(x, y, size, 0, Math.PI * 2, true);
			context.closePath();
			context.fill();
			var border = node.borderColor;
			var bsize  = settings("borderSize");
			if (border && bsize > 0) {
				context.lineWidth   = bsize;
				context.strokeStyle = border;
				context.stroke();
			}
		};
	}
	// Dimmed colors applied to nodes/edges that are NOT direct neighbors of
	// the currently highlighted node. Very faint so the structure of interest
	// stands out without losing all background context.
	var DIM_NODE          = "rgba(200, 200, 200, 0.18)";
	var DIM_EDGE          = "rgba(200, 200, 200, 0.06)";

	// FA2 runs free in 2D. Hub regulators end up centred among their targets
	// because we enable outboundAttractionDistribution (LinLog mode) — that's
	// the bit that gives a hub-and-spoke look instead of a hairball.
	var FA2_DURATION_MS = 4500;

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
			maxAbsCoef: globalMaxAbsCoef,
			omics:      Object.keys(omicSet).sort()
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

	// Build {omic → colour} from a list of omic names. Pure positional
	// assignment against REG_PALETTE — index 0 gets the first palette colour,
	// etc. — and wraps around if there are more omics than palette entries.
	// Caller is expected to pass a stably-sorted list so the same omic gets
	// the same colour across reloads of the same job.
	var _buildOmicColorMap = function (omics) {
		var map = {};
		for (var i = 0; i < omics.length; i++) {
			map[omics[i]] = REG_PALETTE[i % REG_PALETTE.length];
		}
		return map;
	};

	// Parse "#rgb" / "#rrggbb" / "rgb(...)" / "rgba(...)" into {r,g,b}. Returns
	// null for inputs we can't read — callers should fall through to a static
	// border colour so a parsing miss never blanks out the node outline.
	var _parseColor = function (c) {
		if (!c) return null;
		if (c.charAt(0) === "#") {
			var h = c.substring(1);
			if (h.length === 3) {
				h = h.charAt(0) + h.charAt(0) + h.charAt(1) + h.charAt(1) +
				    h.charAt(2) + h.charAt(2);
			}
			if (h.length !== 6) return null;
			return {
				r: parseInt(h.substring(0, 2), 16),
				g: parseInt(h.substring(2, 4), 16),
				b: parseInt(h.substring(4, 6), 16)
			};
		}
		var m = c.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
		return m ? { r: +m[1], g: +m[2], b: +m[3] } : null;
	};

	// Mix the input colour toward black by `factor` (0 → unchanged, 1 → black).
	// Used to derive a same-hue, darker border from each node's fill so the
	// outline reads as "the same colour, just stronger" — keeps the visual
	// vocabulary tight (one colour per omic, just two shades of it).
	var _darkenColor = function (color, factor) {
		factor = factor != null ? factor : 0.4;
		var rgb = _parseColor(color);
		if (!rgb) return "#333333";
		var r = Math.max(0, Math.round(rgb.r * (1 - factor)));
		var g = Math.max(0, Math.round(rgb.g * (1 - factor)));
		var b = Math.max(0, Math.round(rgb.b * (1 - factor)));
		return "rgb(" + r + "," + g + "," + b + ")";
	};

	// Symbol-aware label for tooltips/labels. Mirrors PA_Step3RegulationView's
	// renderer: prefer the resolved gene symbol when available, fall back to
	// the raw ID. UPPERCASE keys to match server-side normalisation.
	var _label = function (id, symbols) {
		if (!id) return "";
		var sym = symbols && symbols[String(id).toUpperCase()];
		return sym ? sym + " (" + id + ")" : id;
	};

	// Role-based fixed sizing. Size encodes regulator-vs-target, not degree.
	// Reason: when omics with very different biological out-degree are mixed
	// (TFs target hundreds of genes, miRNAs/methylation a handful), √degree
	// sizing made TF hubs dominate the canvas and effectively hid the smaller
	// regulators from view. Hub-ness is still read off the *visible edge count*
	// radiating from each node, so the information isn't lost — just moved off
	// the size channel onto the channel that already carries it.
	var _regSize = function () { return 5.0; };
	var _tgtSize = function () { return 3.0; };

	// Map |coef| → edge thickness. Coefficients in MORE are unbounded but
	// typically |coef| ∈ [0, ~2]. Cap at the 95th-pctl-ish to avoid one
	// dominant edge swamping the rest visually.
	var _edgeSize = function (absCoef) {
		var s = Math.min(absCoef, 1.5);
		return 0.3 + s * 1.2;
	};

	// ---- Sigma instantiation ---------------------------------------------
	// Builds the sigma graph from the prepared {regulators, targets, edges}
	// triple, places nodes at random scatter, and instantiates sigma in
	// the supplied DOM container. Called from the panel's afterrender hook
	// because sigma needs a measurable parent element.
	this._instantiateSigma = function (containerEl) {
		var graph = this.buildBipartiteGraph();
		var symbols = this.symbols || {};
		// Expose for toolbar / filter logic.
		this.conditions     = graph.conditions;
		this.dataMaxAbsCoef = graph.maxAbsCoef || 1;
		this.dataOmics      = graph.omics || [];
		// Stable {omic → colour} for this view instance. Built once from the
		// sorted omic list so regulator fills, legend swatches, and any future
		// per-omic UI stay in lockstep without each caller re-deriving colour.
		this.omicColorMap   = _buildOmicColorMap(this.dataOmics);
		// Default current condition to the first one present, unless an
		// earlier initComponent() already chose it.
		if (!this.currentCondition && graph.conditions.length > 0) {
			this.currentCondition = graph.conditions[0];
		}
		// Initialise filter state.
		// R² floor: honour MORE-side filter_r2; user can only tighten it.
		// |coef| floor: start at 0 — MORE already gated by alpha/VIP.
		// maxEdges: default to top 75 by |coef|. The full unfiltered rpc is
		// a hairball at any meaningful canvas size; the user can lift the
		// cap. Lower options (50, 75) exist for very tight inspection.
		var r2Floor = (this.filters && this.filters.filter_r2 != null)
			? Number(this.filters.filter_r2) : 0;
		// enabledOmics: all on by default (any-omic union semantics — a
		// regulator stays visible while ≥1 of its omics is checked, which
		// drops out naturally because edges are filtered per-omic).
		var enabledOmics = {};
		for (var oi = 0; oi < this.dataOmics.length; oi++) {
			enabledOmics[this.dataOmics[oi]] = true;
		}
		this.filterState = {
			r2Floor:      r2Floor,
			r2Min:        r2Floor,
			absCoefMin:   0,
			maxEdges:     75,
			enabledOmics: enabledOmics
		};

		var regList = Object.keys(graph.regulators).map(function (k) {
			return graph.regulators[k];
		});
		var tgtList = Object.keys(graph.targets).map(function (k) {
			return graph.targets[k];
		});

		// Initial positions: small random scatter around the origin. FA2 with
		// outboundAttractionDistribution will then pull hubs to the centre
		// and push leaves outward. Regulators get a tighter inner radius so
		// the layout already nudges them centre-ward before FA2 even starts;
		// targets get a slightly wider band — this just gives FA2 a head start
		// and converges faster than starting everyone on top of each other.
		var sigmaNodes = [];
		var _randPos = function (radius) {
			var theta = Math.random() * Math.PI * 2;
			var r = radius * Math.sqrt(Math.random());
			return { x: Math.cos(theta) * r, y: Math.sin(theta) * r };
		};
		var omicColorMap = this.omicColorMap;
		regList.forEach(function (reg) {
			var primaryOmic = getPrimaryOmic(reg);
			var color  = omicColorMap[primaryOmic] || REG_PALETTE[0];
			var border = _darkenColor(color, 0.45);
			var p = _randPos(0.3);
			sigmaNodes.push({
				id:    reg.id,
				type:  "bordered",  // selects our custom canvas renderer
				label: _label(reg.name, symbols),
				x:     p.x,
				y:     p.y,
				size:  _regSize(),
				color:       color,
				borderColor: border,
				kind:        "regulator",
				rawName:     reg.name,
				primaryOmic: primaryOmic,
				omics:       Object.keys(reg.omics),
				degree:      reg.degree
			});
		});
		var targetBorder = _darkenColor(TARGET_COLOR, 0.4);
		tgtList.forEach(function (tgt) {
			var p = _randPos(1.0);
			sigmaNodes.push({
				id:    tgt.id,
				type:  "bordered",  // selects our custom canvas renderer
				label: _label(tgt.name, symbols),
				x:     p.x,
				y:     p.y,
				size:  _tgtSize(),
				color:       TARGET_COLOR,
				borderColor: targetBorder,
				kind:    "target",
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

		// Stamp originalColor + originalBorderColor + originalLabel on every
		// node so highlight can restore all three. Without saving the border,
		// _highlightNode would dim the fill but the darker outline would still
		// paint at full strength; without saving the label, blanking other
		// nodes' labels on selection would lose them permanently.
		for (var k = 0; k < sigmaNodes.length; k++) {
			sigmaNodes[k].originalColor       = sigmaNodes[k].color;
			sigmaNodes[k].originalBorderColor = sigmaNodes[k].borderColor;
			sigmaNodes[k].originalLabel       = sigmaNodes[k].label;
		}

		// Search index for the side-panel "Find node" box. Pre-computed once
		// and sorted alphabetically by label so the dropdown reads predictably;
		// lowercased copy stored so the per-keystroke filter is a pure
		// indexOf() without re-lowercasing N strings every event.
		this.searchIndex = sigmaNodes.map(function (n) {
			return {
				id:    n.id,
				label: n.label,
				lower: (n.label || "").toLowerCase(),
				kind:  n.kind
			};
		}).sort(function (a, b) {
			return a.lower < b.lower ? -1 : (a.lower > b.lower ? 1 : 0);
		});

		this.network = new sigma({
			graph: { nodes: sigmaNodes, edges: sigmaEdges },
			renderers: [{ container: containerEl, type: "canvas" }],
			settings: {
				zoomMin: 0.05,
				zoomMax: 10,
				zoomingRatio: 1.2,
				// labelThreshold gates labels on rendered pixel size. With
				// uniform sizing (regulator raw 5, target raw 3) mapped to
				// minNodeSize=4 / maxNodeSize=8, regulators render at 8 px
				// and targets at 4 px — labelThreshold=6 keeps regulator
				// labels visible (what the user is here to identify) and
				// leaves targets label-free until hovered.
				labelThreshold: 6,
				labelMaxLength: 18,
				defaultEdgeType: "line",
				defaultEdgeColor: "default",
				edgeColor: "default",
				batchEdgesDrawing: true,
				hideEdgesOnMove: true,
				minNodeSize:  4,
				maxNodeSize:  8,
				minEdgeSize:  0.3,
				maxEdgeSize:  2.5,
				defaultLabelSize: 11,
				// Outline support: each node carries `type: "bordered"` which
				// dispatches to our custom canvas renderer (registered above);
				// the stock `def` renderer only fills, never strokes. The
				// border width below is the px thickness of that stroke.
				borderSize: 1.4
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

		// Side panel (omic toggles + legend + counts) — needs dataOmics +
		// filterState, both ready by this point.
		this._buildSidePanel();

		// Wire hover/click highlight + render the top-hubs overlay (consults
		// current visibility, so it reflects whatever the active filters show).
		this._bindHighlight();
		this._renderTopHubs();

		// Run FA2 free in 2D. LinLog mode (outboundAttractionDistribution)
		// makes hubs gravitate centrally with their leaves on the periphery
		// — the look we want for "this regulator controls all these targets."
		// edgeWeightInfluence biased on |coef| via _edgeSize means stronger
		// regulatory links also pull harder.
		this.network.startForceAtlas2(this._fa2Config(this._visibleNodeCount()));

		var me = this;
		this.fa2StopTimer = setTimeout(function () {
			if (me.network && me.network.isForceAtlas2Running()) {
				me.network.stopForceAtlas2();
			}
			me.network.refresh({ skipIndexation: false });
		}, FA2_DURATION_MS);
	};

	// Count of currently-visible nodes (i.e., not hidden by the filter pipe).
	// Linkurious sigma's FA2 worker does NOT skip hidden nodes — they still
	// emit repulsion — so we tune FA2 params off this count rather than the
	// full graph size, otherwise a tight R² filter leaves visible survivors
	// being shoved around by thousands of invisible repulsors.
	this._visibleNodeCount = function () {
		if (this._lastFilterStats) {
			return (this._lastFilterStats.visibleRegulators || 0) +
			       (this._lastFilterStats.visibleTargets    || 0);
		}
		return this.network ? this.network.graph.nodes().length : 0;
	};

	// Adaptive FA2 params shared by initial layout and Resume. Smooth
	// √n-based interpolation rather than buckets so the transitions feel
	// natural as the user tightens/loosens filters. strongGravityMode is a
	// heavy hammer (linear-in-distance pull to centre, overriding repulsion)
	// — reserve it for truly tiny graphs where survivors would otherwise be
	// invisible specks at the canvas edge.
	this._fa2Config = function (nVisibleNodes) {
		var n = Math.max(nVisibleNodes || 0, 1);
		var sqrtN = Math.sqrt(n);
		// Two-flag attraction mode (read this if you ever touch FA2 params):
		//   - linLogMode:                       log(d) attraction instead of d.
		//   - outboundAttractionDistribution:   divides attraction by hub mass.
		// Without these, attraction is linear in distance × full hub degree —
		// hubs with degree 20 get pulled inward 20× harder than repulsion can
		// counter, which is exactly why "each Resume crushes the hubs tighter."
		// Both ON is the standard FA2 "balanced" preset and gives the look the
		// user is after: hubs centred among their fans, with enough breathing
		// room between hubs.
		// Scaling. LinLog+OAD attraction is gentle, so we don't need the huge
		// values classic FA2 demands. √n-based with a floor at 8 keeps sparse
		// graphs from looking cramped and caps at 24 so 500-node views don't
		// blow off the camera.
		var scaling = Math.max(8, Math.min(24, sqrtN * 1.5));
		// Gravity: low but non-zero so disconnected components stay anchored.
		// Inverse-√n shape — sparse graphs need less pull (own repulsion is
		// fine), dense graphs need a little more help against fly-apart.
		var gravity = Math.max(0.3, Math.min(1.0, 1.5 / sqrtN));
		return {
			worker: true,
			barnesHutOptimize: n > 500,
			barnesHutTheta: 0.6,
			scalingRatio: scaling,
			slowDown: 4,
			gravity: gravity,
			// strongGravityMode overrides repulsion with a linear pull to
			// centre — collapses sparse graphs into a black hole, never use.
			strongGravityMode: false,
			// Low edge-weight influence so strong (high |coef|) edges don't
			// dominate the layout — without this, the densest-coef cluster
			// crushes itself into a single point.
			edgeWeightInfluence: 0.3,
			linLogMode:                     true,
			outboundAttractionDistribution: true,
			// adjustSizes intentionally OFF. The Linkurious FA2 non-Barnes-Hut
			// branch has a sign bug in its anti-collision repulsion (it
			// applies the repulsion force to both n1 AND n2 with the same
			// sign instead of opposite signs — see plugins.js around line
			// 3346). With adjustSizes=true, hubs effectively stop repelling
			// each other and Resume keeps pulling them tighter. With it OFF,
			// the standard inverse-square repulsion branch (line ~3370) runs
			// and the simulation reaches a real spread-out equilibrium.
			adjustSizes:                    false
		};
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
			var inFocus = (n.id === nodeId || neighbors[n.id]);
			n.color       = inFocus ? n.originalColor       : DIM_NODE;
			n.borderColor = inFocus ? n.originalBorderColor : DIM_NODE;
			// Spotlight semantics for labels: focal + neighbour labels are
			// forced on (even targets, which normally fall under labelThreshold
			// and only show on hover); everything else has its label blanked
			// so the chosen connection isn't visually crowded out.
			if (inFocus) {
				n.label      = n.originalLabel;
				n.forceLabel = true;
			} else {
				n.label      = "";
				n.forceLabel = false;
			}
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
		for (var i = 0; i < nodes.length; i++) {
			nodes[i].color       = nodes[i].originalColor;
			nodes[i].borderColor = nodes[i].originalBorderColor;
			nodes[i].label       = nodes[i].originalLabel;
			nodes[i].forceLabel  = false;
		}
		for (var j = 0; j < edges.length; j++) edges[j].color = edges[j].originalColor;
		// If _focusEdge forcibly un-hid filtered nodes/edges to spotlight a
		// table row, re-run the filter pipe to restore their hidden state.
		// _applyFilters does its own refresh + side-panel updates, so we
		// branch the trailing refresh on whether we need the heavier path.
		if (this.focusEdgeUnhid) {
			this.focusEdgeUnhid = false;
			this._applyFilters();
		} else {
			this.network.refresh({ skipIndexation: true });
		}
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
		var hubsEl = document.getElementById(this.hubsPanelId);
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

		// Compact vertical row: symbol/id on the left, edge count on the right.
		// The whole row is the click target so the user doesn't have to hit
		// the name pixel-perfectly to highlight the node.
		var symbols = this.symbols || {};
		var fmtRow = function (item) {
			var sym = symbols[String(item.name).toUpperCase()];
			var disp = sym ? sym : item.name;
			return '<div class="more-hub-link" data-node-id="' +
				Ext.String.htmlEncode(item.id) + '" ' +
				'style="display:flex;justify-content:space-between;' +
				'align-items:center;font-size:0.78em;line-height:1.4;' +
				'padding:2px 4px;margin:1px -4px;cursor:pointer;' +
				'border-radius:2px;color:#1f77b4;" ' +
				'onmouseover="this.style.background=\'#eef4fb\'" ' +
				'onmouseout="this.style.background=\'transparent\'">' +
				'<span style="overflow:hidden;text-overflow:ellipsis;' +
				'white-space:nowrap;">' + Ext.String.htmlEncode(disp) + '</span>' +
				'<span style="color:#888;margin-left:6px;flex-shrink:0;">n=' +
				item.degree + '</span>' +
			'</div>';
		};
		var renderList = function (items) {
			if (!items.length) {
				return '<div style="font-size:0.78em;color:#999;' +
					'margin:3px 0;"><i>none</i></div>';
			}
			return items.map(fmtRow).join("");
		};

		hubsEl.innerHTML =
			'<div style="font-weight:bold;font-size:0.82em;color:#333;' +
			'margin-bottom:4px;">Top hubs</div>' +
			'<div style="font-size:0.72em;color:#666;text-transform:uppercase;' +
			'letter-spacing:0.04em;margin:6px 0 2px;">Regulators</div>' +
			renderList(topRegs) +
			'<div style="font-size:0.72em;color:#666;text-transform:uppercase;' +
			'letter-spacing:0.04em;margin:8px 0 2px;">Most-regulated targets</div>' +
			renderList(topTgts) +
			'<div style="margin-top:8px;font-size:0.7em;color:#888;' +
			'line-height:1.3;">Click a row to highlight; click again or ' +
			'click empty canvas to clear.</div>';

		// Wire clicks. Use the container so we don't have to re-bind if the
		// list ever re-renders.
		var me = this;
		hubsEl.onclick = function (ev) {
			var row = ev.target.closest &&
				ev.target.closest(".more-hub-link");
			if (!row) return;
			ev.preventDefault();
			var nodeId = row.getAttribute("data-node-id");
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

	// ---- Side panel: omic toggles, legend, live counts ------------------
	// Right-hand strip rendered into this.sidePanelId. Three sections:
	//   1. Edge sign legend (blue = positive coef, red = negative)
	//   2. Omic checkboxes — operates per-edge (each edge has a single omic).
	//      Unchecking an omic hides its edges and any-omic-union semantics
	//      drop out for free via the orphan-node sweep in _applyFilters.
	//   3. Live counts (regulators / targets / edges visible) — refreshed
	//      from _lastFilterStats by _updateSidePanelCounts.
	this._buildSidePanel = function () {
		var el = document.getElementById(this.sidePanelId);
		if (!el) return;
		var omics = this.dataOmics || [];
		var state = this.filterState;

		var html = "";

		// Find-node search box. Input on top, scrollable matches dropdown
		// below. Matches are populated by _refreshSearchResults on every
		// keystroke; the box stays visible at all times even when empty so
		// users can find it without scrolling.
		html +=
			'<div style="padding:10px 12px;border-bottom:1px solid #e0e0e0;">' +
				'<div style="font-weight:bold;font-size:0.82em;color:#333;' +
				'margin-bottom:6px;">Find node</div>' +
				'<input type="text" id="' + this.sidePanelId + '_search" ' +
				'placeholder="Gene symbol or ID" autocomplete="off" ' +
				'style="width:100%;padding:4px 6px;box-sizing:border-box;' +
				'font-size:0.82em;border:1px solid #ccc;border-radius:3px;">' +
				// The results container has its own white card-like look so
				// it stands out against the grey side panel — without this
				// the matches were rendered but hard to see (#f8f8f8 on
				// #f8f8f8). max-height keeps the panel from ballooning when
				// there are many hits.
				'<div id="' + this.sidePanelId + '_searchresults" ' +
				'style="margin-top:6px;max-height:200px;overflow-y:auto;' +
				'font-size:0.78em;line-height:1.35;background:#ffffff;' +
				'border:1px solid #d8d8d8;border-radius:3px;display:none;"></div>' +
			'</div>';

		// Edge sign legend.
		html +=
			'<div style="padding:10px 12px;border-bottom:1px solid #e0e0e0;">' +
				'<div style="font-weight:bold;font-size:0.82em;color:#333;' +
				'margin-bottom:6px;">Edge sign</div>' +
				'<div style="font-size:0.78em;display:flex;align-items:center;' +
				'margin-bottom:3px;">' +
					'<span style="display:inline-block;width:18px;height:3px;' +
					'background:#2E86C1;margin-right:8px;"></span>' +
					'positive coef</div>' +
				'<div style="font-size:0.78em;display:flex;align-items:center;">' +
					'<span style="display:inline-block;width:18px;height:3px;' +
					'background:#C03927;margin-right:8px;"></span>' +
					'negative coef</div>' +
			'</div>';

		// Omic toggles (= regulator-side filter via edge omic).
		html +=
			'<div style="padding:10px 12px;border-bottom:1px solid #e0e0e0;">' +
				'<div style="font-weight:bold;font-size:0.82em;color:#333;' +
				'margin-bottom:6px;">Omics</div>';
		var omicColorMap = this.omicColorMap || {};
		for (var i = 0; i < omics.length; i++) {
			var omic = omics[i];
			var color = omicColorMap[omic] || REG_PALETTE[0];
			var checked = state && state.enabledOmics &&
			              state.enabledOmics[omic] !== false ? " checked" : "";
			var safeOmic = Ext.String.htmlEncode(omic);
			html +=
				'<div style="font-size:0.78em;display:flex;align-items:center;' +
				'margin-bottom:3px;line-height:1.4;">' +
					'<input type="checkbox" data-omic="' + safeOmic + '" ' +
					'class="more-omic-toggle"' + checked +
					' style="margin:0 6px 0 0;">' +
					'<span style="display:inline-block;width:10px;height:10px;' +
					'background:' + color + ';border-radius:50%;' +
					'margin-right:6px;flex-shrink:0;"></span>' +
					'<label style="cursor:pointer;word-break:break-word;">' +
					safeOmic + '</label>' +
				'</div>';
		}
		html +=
				'<div style="margin-top:6px;font-size:0.72em;color:#888;' +
				'line-height:1.3;">' +
					'Any-omic union: a regulator stays visible while ≥1 of ' +
					'its omics is checked.' +
				'</div>' +
			'</div>';

		// Targets are encoded distinctly (gray). Surface that here so the
		// canvas legend is self-contained, not just an inferred convention.
		html +=
			'<div style="padding:10px 12px;border-bottom:1px solid #e0e0e0;">' +
				'<div style="font-weight:bold;font-size:0.82em;color:#333;' +
				'margin-bottom:6px;">Targets</div>' +
				'<div style="font-size:0.78em;display:flex;align-items:center;">' +
					'<span style="display:inline-block;width:10px;height:10px;' +
					'background:' + TARGET_COLOR + ';border-radius:50%;' +
					'margin-right:8px;"></span>' +
					'regulated gene</div>' +
			'</div>';

		// Top-hubs placeholder. _renderTopHubs paints into this every time the
		// filter pipe runs, so the list reflects whatever the user is currently
		// looking at. Initial content is a stub — first paint replaces it.
		html +=
			'<div id="' + this.hubsPanelId + '" ' +
			'style="padding:10px 12px;border-bottom:1px solid #e0e0e0;">' +
				'<div style="font-weight:bold;font-size:0.82em;color:#333;">' +
				'Top hubs</div>' +
				'<div style="font-size:0.78em;color:#999;margin-top:4px;">' +
				'<i>computing…</i></div>' +
			'</div>';

		// Live counts placeholder — populated by _updateSidePanelCounts.
		html +=
			'<div style="padding:10px 12px;">' +
				'<div style="font-weight:bold;font-size:0.82em;color:#333;' +
				'margin-bottom:6px;">Visible</div>' +
				'<div id="' + this.sidePanelId + '_counts" ' +
				'style="font-size:0.82em;line-height:1.6;color:#444;">' +
				'<i style="color:#999;">computing…</i></div>' +
			'</div>';

		el.innerHTML = html;

		// Wire checkboxes. Toggling re-runs the filter pipe — cheap (≲3k edges).
		var me = this;
		var boxes = el.querySelectorAll("input.more-omic-toggle");
		for (var b = 0; b < boxes.length; b++) {
			boxes[b].onchange = function () {
				var name = this.getAttribute("data-omic");
				me.filterState.enabledOmics[name] = this.checked;
				me._applyFilters();
			};
		}

		// Wire the search box. Debouncing isn't needed — the index is in
		// memory and indexOf over a few thousand entries is sub-millisecond.
		// Escape clears both the input and the pinned highlight, so the user
		// can dismiss a "found node" view with one keypress.
		var searchInput = document.getElementById(this.sidePanelId + "_search");
		if (searchInput) {
			searchInput.oninput = function () {
				me._refreshSearchResults(this.value);
			};
			searchInput.onkeydown = function (ev) {
				if (ev.key === "Escape") {
					this.value = "";
					me._refreshSearchResults("");
					if (me.pinnedHighlight) {
						me.pinnedHighlight = null;
						me._clearHighlight();
					}
				}
			};
		}

		// First counts paint reflects whatever filter pass already ran.
		this._updateSidePanelCounts();
	};

	// Repaint the counts block from _lastFilterStats. Safe to call before
	// the side panel exists — it's a no-op when the target element is gone.
	this._updateSidePanelCounts = function () {
		var el = document.getElementById(this.sidePanelId + "_counts");
		if (!el) return;
		var stats = this._lastFilterStats || {};
		el.innerHTML =
			'<div>Regulators: <b>' + (stats.visibleRegulators || 0) + '</b></div>' +
			'<div>Targets: <b>' + (stats.visibleTargets || 0) + '</b></div>' +
			'<div>Edges: <b>' + (stats.visibleEdges || 0) + '</b></div>';
	};

	// Recompute and repaint the search-results dropdown for the given query.
	// Substring match, case-insensitive, capped at 12 hits to keep the list
	// scannable. Hidden nodes (filtered out) are still listed but greyed out
	// so the user knows the node exists but the current filters hide it.
	this._refreshSearchResults = function (query) {
		var resultsEl = document.getElementById(this.sidePanelId + "_searchresults");
		if (!resultsEl) return;
		var q = String(query || "").trim().toLowerCase();
		if (q.length === 0) {
			resultsEl.innerHTML = "";
			resultsEl.style.display = "none";
			return;
		}
		var matches = [];
		var idx = this.searchIndex || [];
		var MAX = 12;
		for (var i = 0; i < idx.length && matches.length < MAX; i++) {
			if (idx[i].lower.indexOf(q) !== -1) matches.push(idx[i]);
		}
		// Always reveal the container while a query is active so users get
		// either matches or a "no matches" notice, never the silent-typing
		// state that made it look like the search wasn't working.
		resultsEl.style.display = "block";
		if (matches.length === 0) {
			resultsEl.innerHTML =
				'<div style="color:#999;padding:6px 8px;"><i>no matches</i></div>';
			return;
		}
		// Build the dropdown HTML. Look up hidden flag via the live graph so
		// the rendered state is always current; tiny lookup cost (1 hash hit
		// per result) is fine at MAX=12.
		var graph = this.network ? this.network.graph : null;
		var html = "";
		for (var j = 0; j < matches.length; j++) {
			var m  = matches[j];
			var nd = graph ? graph.nodes(m.id) : null;
			var hidden = !!(nd && nd.hidden);
			var swatchColor = (m.kind === "regulator")
				? (nd && nd.originalColor ? nd.originalColor : "#5E3C99")
				: TARGET_COLOR;
			html +=
				'<div class="more-search-hit" data-node-id="' +
				Ext.String.htmlEncode(m.id) + '" ' +
				'style="cursor:pointer;padding:3px 6px;border-radius:2px;' +
				'display:flex;align-items:center;' +
				(hidden ? "opacity:0.45;" : "") + '">' +
					'<span style="display:inline-block;width:8px;height:8px;' +
					'border-radius:50%;background:' + swatchColor + ';' +
					'margin-right:6px;flex-shrink:0;"></span>' +
					'<span style="overflow:hidden;text-overflow:ellipsis;' +
					'white-space:nowrap;">' +
					Ext.String.htmlEncode(m.label) +
					(hidden ? ' <i style="color:#aaa;">(filtered)</i>' : '') +
					'</span>' +
				'</div>';
		}
		resultsEl.innerHTML = html;

		// Wire hover + click for each hit. Hover gives the user the same
		// "preview" feel as the top-hubs strip; click pins the highlight and
		// flies the camera to the node.
		var me = this;
		var hits = resultsEl.querySelectorAll(".more-search-hit");
		for (var h = 0; h < hits.length; h++) {
			hits[h].onmouseover = function () { this.style.background = "#e8eef8"; };
			hits[h].onmouseout  = function () { this.style.background = ""; };
			hits[h].onclick = function () {
				me._focusNode(this.getAttribute("data-node-id"));
			};
		}
	};

	// Pin `nodeId` as the active highlight. Behaves identically to a direct
	// click on the node: dims the rest of the graph, spotlights the focal
	// node + its neighbours via _highlightNode. The camera is intentionally
	// left alone — zooming felt jarring and wasn't adding information that
	// the dim/highlight wasn't already conveying.
	this._focusNode = function (nodeId) {
		if (!this.network || !nodeId) return;
		var node = this.network.graph.nodes(nodeId);
		if (!node) return;
		this.pinnedHighlight = nodeId;
		this._highlightNode(nodeId);
	};

	// Tighter variant of _focusNode used by the row-click bridge from the
	// rpc table: spotlights just the (regulator, target) pair and any edges
	// running directly between them — not the regulator's whole fan of
	// targets. The motivation is that a table row is one relationship; the
	// user clicking it wants to find *that* relationship in the graph.
	// Multiple edges between the same two nodes (different omics) are all
	// kept lit so users can see when a pair has multi-omic support.
	this._focusEdge = function (regNodeId, tgtNodeId) {
		if (!this.network || !regNodeId || !tgtNodeId) return;
		var nodes = this.network.graph.nodes();
		var edges = this.network.graph.edges();
		var focal = {};
		focal[regNodeId] = true;
		focal[tgtNodeId] = true;
		// Track whether we forcibly un-hid anything; _clearHighlight then
		// re-runs filters to restore the proper hidden state. Without this,
		// clicking a row whose edge was filtered out (e.g., outside the
		// current condition, or below the |coef| floor) would light up the
		// nodes but the edge would stay invisible — the "sometimes buggy"
		// symptom.
		this.focusEdgeUnhid = false;
		for (var i = 0; i < nodes.length; i++) {
			var n = nodes[i];
			var inFocus = !!focal[n.id];
			n.color       = inFocus ? n.originalColor       : DIM_NODE;
			n.borderColor = inFocus ? n.originalBorderColor : DIM_NODE;
			n.label       = inFocus ? n.originalLabel       : "";
			n.forceLabel  = inFocus;
			if (inFocus && n.hidden) {
				n.hidden = false;
				this.focusEdgeUnhid = true;
			}
		}
		for (var j = 0; j < edges.length; j++) {
			var ed = edges[j];
			var isEdgeFocal =
				(ed.source === regNodeId && ed.target === tgtNodeId) ||
				(ed.source === tgtNodeId && ed.target === regNodeId);
			ed.color = isEdgeFocal ? ed.originalColor : DIM_EDGE;
			if (isEdgeFocal && ed.hidden) {
				ed.hidden = false;
				this.focusEdgeUnhid = true;
			}
		}
		// Stamp pinnedHighlight so a later clickStage clears via the existing
		// path. Use the regulator id — the click-stage handler doesn't care
		// which it is, only that it's truthy.
		this.pinnedHighlight = regNodeId;
		this.network.refresh({ skipIndexation: true });
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
		// enabledOmics may be absent on the very first call (built lazily
		// by the side panel); treat that as "all omics enabled" to keep
		// the initial render from blanking everything out.
		var enOmics = state.enabledOmics;
		var survivors = [];
		for (var i = 0; i < edges.length; i++) {
			var e = edges[i];
			if (e._missingForCondition) { e.hidden = true; continue; }
			if (e.r2 != null && e.r2 < state.r2Min) { e.hidden = true; continue; }
			if (e.absCoef < state.absCoefMin) { e.hidden = true; continue; }
			if (enOmics && e.omic && enOmics[e.omic] === false) {
				e.hidden = true; continue;
			}
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
		this._updateSidePanelCounts();
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
		[25, 50, 75, 100, 250, 500, 1000, 2500, "all"].forEach(function (v) {
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
				// Spacer pushes export/display actions to the right edge so
				// they're visually separated from the filter controls.
				'<span style="flex:1;"></span>' +
				'<button id="' + this.toolbarId + '_png" title="Download as PNG" ' +
					'style="padding:3px 10px;border:1px solid #aaa;background:white;' +
					'cursor:pointer;border-radius:3px;">PNG</button>' +
				'<button id="' + this.toolbarId + '_svg" title="Download as SVG" ' +
					'style="padding:3px 10px;border:1px solid #aaa;background:white;' +
					'cursor:pointer;border-radius:3px;">SVG</button>' +
				'<button id="' + this.toolbarId + '_full" title="Toggle fullscreen" ' +
					'style="padding:3px 10px;border:1px solid #aaa;background:white;' +
					'cursor:pointer;border-radius:3px;">⛶ Fullscreen</button>' +
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
		var pngBt  = $("_png");
		var svgBt  = $("_svg");
		var fullBt = $("_full");
		if (pngBt)  pngBt.onclick  = function () { me._downloadPng(); };
		if (svgBt)  svgBt.onclick  = function () { me._downloadSvg(); };
		if (fullBt) fullBt.onclick = function () { me._toggleFullscreen(); };
	};

	// ---- Resume layout --------------------------------------------------
	// Re-run FA2 on the current (possibly filtered) graph. "Continue from
	// here" semantics: positions aren't reset, so applying a tighter filter
	// then hitting Resume lets the surviving nodes relax into a cleaner
	// layout in-place.
	this._resumeLayout = function () {
		if (!this.network) return;
		if (this.network.isForceAtlas2Running()) return;
		this.network.startForceAtlas2(this._fa2Config(this._visibleNodeCount()));
		var me = this;
		if (this.fa2StopTimer) clearTimeout(this.fa2StopTimer);
		this.fa2StopTimer = setTimeout(function () {
			if (me.network && me.network.isForceAtlas2Running()) {
				me.network.stopForceAtlas2();
			}
			me.network.refresh({ skipIndexation: false });
		}, FA2_DURATION_MS);
	};

	// ---- Export & fullscreen -------------------------------------------
	// Resolve a stable filename stem from the active jobID. Falls back to
	// a timestamp so exports still work when the model is detached (it
	// shouldn't be at this point, but we don't want a silent NaN filename).
	this._filenameStem = function () {
		var jobID = (this.model && this.model.getJobID)
			? this.model.getJobID() : null;
		var stem = "more_regtarget_network_" + (jobID || Date.now());
		// Sanitise — job IDs in PaintOmics are alnum but defensive cleanup
		// keeps the filename safe if that ever changes.
		return stem.replace(/[^A-Za-z0-9_-]/g, "_");
	};

	// PNG export. Sigma's canvas renderer paints across several stacked
	// canvases (scene = edges/nodes, glyphs = labels, hovers, mouse layer,
	// etc.). We enumerate every canvas inside the container and composite
	// them in DOM order = rendering order, so whatever sigma chose to put
	// on which layer ends up in the export.
	//
	// Critically: dimensions are taken from the source canvas's natural
	// width/height (device pixels), NOT the CSS-pixel container size.
	// On HiDPI displays devicePixelRatio > 1 so the canvases internally
	// are e.g. 2× the CSS size; matching CSS pixels would crop the export
	// to the top-left quadrant — the symptom of the original bug.
	this._downloadPng = function () {
		if (!this.network) return;
		var containerEl = document.getElementById(this.containerId);
		if (!containerEl) return;
		var canvases = containerEl.querySelectorAll("canvas");
		if (!canvases.length) return;

		var w = canvases[0].width;
		var h = canvases[0].height;
		var out = document.createElement("canvas");
		out.width = w; out.height = h;
		var ctx = out.getContext("2d");
		// White background — sigma canvases are transparent; without this
		// the PNG looks broken in viewers that don't checkerboard alpha.
		ctx.fillStyle = "#ffffff";
		ctx.fillRect(0, 0, w, h);
		for (var i = 0; i < canvases.length; i++) {
			try { ctx.drawImage(canvases[i], 0, 0); }
			catch (ex) { /* tainted/empty layer — skip */ }
		}

		var a = document.createElement("a");
		a.href = out.toDataURL("image/png");
		a.download = this._filenameStem() + ".png";
		a.style.display = "none";
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
	};

	// SVG export. Sigma's toSVG() builds a fresh SVG renderer off-screen,
	// snapshots, and (with download:true) triggers a save. Vector output —
	// scales cleanly for publications.
	this._downloadSvg = function () {
		if (!this.network || typeof this.network.toSVG !== "function") return;
		try {
			this.network.toSVG({
				download: true,
				labels:   true,
				data:     true,
				filename: this._filenameStem() + ".svg"
			});
		} catch (ex) {
			console.error("RegTargetNetwork SVG export failed:", ex);
		}
	};

	// Fullscreen toggle. sigma.plugins.fullScreen escalates the sigma
	// container to the document's fullscreen element; pressing Esc (or
	// re-clicking the button) exits. The plugin internally handles
	// browser-prefix differences (webkit/moz) so we just hand it our
	// canvas container.
	this._toggleFullscreen = function () {
		var containerEl = document.getElementById(this.containerId);
		if (!containerEl) return;
		if (sigma && sigma.plugins && sigma.plugins.fullScreen) {
			sigma.plugins.fullScreen({ container: containerEl });
		} else {
			console.warn("RegTargetNetwork: fullScreen plugin not loaded");
		}
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
				// Top-hubs were historically rendered as a strip here, above
				// the canvas. They now live inside the side panel — see the
				// "Top hubs" block in _buildSidePanel / _renderTopHubs.
				// Canvas + side panel sit in a flex row. Canvas takes all
				// remaining width; side panel is fixed at 210px and scrolls
				// independently when omic lists get long.
				'<div style="display:flex; width:100%; height:600px;">' +
					'<div id="' + this.containerId + '" ' +
					'style="flex:1; height:100%; position:relative; ' +
					'background:#fafafa;"></div>' +
					'<div id="' + this.sidePanelId + '" ' +
					'style="width:210px; height:100%; overflow-y:auto; ' +
					'background:#f8f8f8; border-left:1px solid #e0e0e0; ' +
					'box-sizing:border-box;"></div>' +
				'</div>',
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
