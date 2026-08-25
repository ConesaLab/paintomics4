/**
 * PA_Step3HubNetworkView -- metabolite hub analysis as a network, not a table.
 *
 * Why this exists. The KEGG interaction graph has always been on the server and
 * never reached the browser: compoundRegulateFeatures ships node SETS with no
 * pairs, no direction, no edge types and no intermediate hops, so a client could
 * not tell whether a radius-3 gene reached the metabolite via gene X or gene Y.
 * The hub table reported numbers about a network nobody could see.
 *
 * This panel replaces that table. A metabolite LIST -- one entry per compound,
 * ranked by significance -- selects the seed; the network draws its 1..4 step
 * neighbourhood as concentric rings; the step control and the expression
 * figures live INSIDE the network stage.
 *
 * Layout rule, learned the hard way: the detail sat below a 720px canvas, so
 * clicking a node put its heatmap 448px below the fold. It drew correctly and
 * nobody could see it, which from the user's seat is identical to a dead click.
 * Anything a click produces is now docked in the stage, above the fold, and the
 * canvas shrinks to make room rather than being covered.
 *
 * Encoding, decided colour-last:
 *
 *   position (ring) -> hop distance      the layout already carries it, so
 *                                        distance deliberately takes NO colour
 *   fill colour     -> DE direction      the scientific payload
 *   filled/hollow   -> DE vs not DE      so identity is never colour-alone
 *   dashed stroke   -> never measured    absence shown as absence
 *   shape           -> compound / gene
 *   size            -> the seed, only
 *
 * The two hues are validated, not chosen by eye: CVD dE 21.6 and normal-vision
 * dE 32.3 against the light surface (targets >=8 and >=15). The near-white
 * diverging midpoint was rejected at 1.12:1 contrast -- "measured but not DE" is
 * most of the graph, so those nodes are hollow and the STROKE carries contrast.
 */
function PA_Step3HubNetworkView() {
	this.name = "PA_Step3HubNetworkView";
	// Randomised ids: Step 3 can hold more than one network panel, and Ext
	// reuses component ids across job loads. The old Paint handler used the
	// literal id "divIdComp" and collided with itself for exactly this reason.
	var salt = Math.floor(Math.random() * 1e9);
	this.canvasID = "hubNetCanvas" + salt;
	this.ringsID = "hubNetRings" + salt;
	this.noticeID = "hubNetNotice" + salt;
	this.tipID = "hubNetTip" + salt;
	this.listID = "hubNetList" + salt;
	this.searchID = "hubNetSearch" + salt;
	this.sortID = "hubNetSort" + salt;
	this.countID = "hubNetCount" + salt;
	this.stepsID = "hubNetSteps" + salt;
	this.seedNameID = "hubNetSeedName" + salt;
	this.detailID = "hubNetDetail" + salt;

	this.cy = null;
	this.level = 1;
	this.payload = null;
	this.seed = null;
	this.charts = [];        // Highcharts instances owned by the detail card
	this.metabolites = [];   // one entry per compound, with its four step rows
	this.featureCache = {};  // id|kind -> /pa_hub_feature payload
	this.compoundNames = {}; // KEGG compound id -> readable name
	this.sortKey = "padjust";
	this.query = "";

	/* ------------------------------------------------------------------ *
	 * Model                                                               *
	 * ------------------------------------------------------------------ */

	this.loadModel = function (model) {
		var me = this;
		me.model = model;
		me.buildList();
		// loadModel and afterrender race: PA_Step3JobView constructs the view,
		// calls loadModel, and only then lays the panel out. Whichever runs
		// second has to do the work.
		if (me.component && me.component.rendered && me.hasData()) {
			me.component.show();
			me.mount();
		}
	};

	/** Everything that needs the panel's DOM to exist. */
	this.mount = function () {
		this.loadNames();
		this.renderList();
		this.renderCount();
		this.renderSteps();
		this.bindControls();
		this.selectFirst();
	};

	/**
	 * Readable names for the scored compounds, in one call.
	 *
	 * The list was titled "C12145". mappingComp cannot help -- it holds the
	 * name the USER uploaded, so a metabolomics file keyed by KEGG id makes it
	 * the id again (measured: every one of this job's 213 entries). The names
	 * live in global-paintomics.kegg_compounds, server side only.
	 *
	 * Asynchronous on purpose: the panel renders from ids immediately and
	 * re-titles itself when the map lands, rather than holding an empty list
	 * behind a request.
	 */
	this.loadNames = function () {
		var me = this;
		if (!me.metabolites.length) { return; }
		// The ids come from HERE, not from the job's stored rows: jobs written
		// before the schema-2 rewrite still hold headerless lists in Mongo, and
		// only the recovery route upgrades them on the way out. This view is
		// already holding the upgraded rows.
		var ids = me.metabolites.map(function (m) { return m.ID; }).join(",");
		$.post(SERVER_URL_PA_HUB_NAMES, { jobID: me.model.getJobID(), ids: ids })
			.done(function (payload) {
				if (typeof payload === "string") {
					try { payload = JSON.parse(payload); } catch (e) { payload = null; }
				}
				if (!payload || !payload.success || !payload.names) { return; }
				me.mergeNames(payload.names);
				me.buildList();
				me.renderList();
				if (me.seed) { me.setSeedName(me.nameOf(me.seed, "compound")); }
			});
	};

	this.mergeNames = function (names) {
		for (var id in names) {
			if (names[id]) { this.compoundNames[id] = names[id]; }
		}
	};

	/**
	 * The display name for one node, or its id when nothing better is known.
	 *
	 * Compounds are named from the server map. Genes are named from
	 * globalExpressionData's `keggName`, which is the gene SYMBOL the mapper
	 * resolved (Aanat, Abca1, ...) -- so every measured gene has one, and only
	 * genes the job never measured fall back to the KEGG id. That is also
	 * every gene node this panel labels, since labels go to the seed and the
	 * DE nodes.
	 */
	this.nameOf = function (id, kind) {
		if (kind === "compound") {
			return this.compoundNames[id] ||
			       ((this.model && this.model.mappingComp) || {})[id] || id;
		}
		var entry = this.expressionFor(id, kind);
		var symbol = entry && entry.keggName;
		return (symbol && symbol !== id) ? symbol : id;
	};

	/** "Phytoceramide (C12145)", or just the id when it IS the name. */
	this.nameWithID = function (id, kind) {
		var name = this.nameOf(id, kind);
		return (name === id) ? Ext.String.htmlEncode(id)
		                     : Ext.String.htmlEncode(name) +
		                       ' <span class="pa-hub-id">' +
		                       Ext.String.htmlEncode(id) + '</span>';
	};

	/**
	 * Collapse the hub rows to ONE entry per compound.
	 *
	 * getHubAnalysisResult() is one row per (compound, radius), so every
	 * metabolite appears four times -- which is why the grid it replaces needed
	 * a step filter to be readable at all. Here the four scores become a
	 * per-step array on a single entry, the ring buttons are the step control,
	 * and the four rows are shown together in the metabolite's own summary.
	 */
	this.buildList = function () {
		var rows = (this.model && this.model.getHubAnalysisResult()) || {};
		var byID = {};
		for (var key in rows) {
			var row = paHubRow(rows[key]);
			if (!row || !row.ID) { continue; }
			var entry = byID[row.ID];
			if (!entry) {
				entry = byID[row.ID] = {
					ID: row.ID,
					name: this.nameOf(row.ID, "compound"),
					steps: {}
				};
			}
			entry.steps[row.Step] = row;
		}
		this.metabolites = [];
		for (var id in byID) {
			var item = byID[id];
			// Rank on the metabolite's BEST step -- a compound that is
			// significant at radius 2 and nowhere else is still a finding, and
			// ranking on a fixed radius would bury it.
			var best = null;
			for (var step in item.steps) {
				var candidate = item.steps[step];
				if (best === null || Number(candidate.padjust) < Number(best.padjust)) {
					best = candidate;
				}
			}
			item.best = best;
			item.bestStep = best ? Number(best.Step) : 1;
			item.padjust = best ? Number(best.padjust) : 1;
			item.pvalue = best ? Number(best.pvalue) : 1;
			item.density = best ? Number(best.Percentage) : 0;
			item.den = best ? Number(best.DEN) : 0;
			this.metabolites.push(item);
		}
		this.sortList();
	};

	this.SORTS = {
		padjust: function (a, b) { return a.padjust - b.padjust || a.name.localeCompare(b.name); },
		density: function (a, b) { return b.density - a.density || a.name.localeCompare(b.name); },
		den: function (a, b) { return b.den - a.den || a.name.localeCompare(b.name); },
		name: function (a, b) { return a.name.localeCompare(b.name); }
	};

	this.sortList = function () {
		this.metabolites.sort(this.SORTS[this.sortKey] || this.SORTS.padjust);
	};

	this.entryFor = function (compoundID) {
		for (var i = 0; i < this.metabolites.length; i++) {
			if (this.metabolites[i].ID === compoundID) { return this.metabolites[i]; }
		}
		return null;
	};

	/* ------------------------------------------------------------------ *
	 * Metabolite list                                                     *
	 * ------------------------------------------------------------------ */

	/**
	 * How much there is to look through, as one line of text.
	 *
	 * This replaces a three-tile figure band. The counts were worth keeping --
	 * "96 of 213 are significant" is the shape of the result -- but three
	 * circled icons and 48px numerals spent a quarter of the panel's height
	 * saying it, above the thing they describe.
	 */
	this.renderCount = function () {
		var host = document.getElementById(this.countID);
		if (!host) { return; }
		var total = this.metabolites.length;
		var significant = this.metabolites.filter(function (m) {
			return m.padjust < 0.05;
		}).length;
		host.innerHTML = total
			? total + " metabolites &middot; <b>" + significant + "</b> with FDR &lt; 0.05"
			: "";
	};

	this.renderList = function () {
		var me = this;
		var host = document.getElementById(this.listID);
		if (!host) { return; }
		var query = this.query.toLowerCase();
		var shown = this.metabolites.filter(function (m) {
			return !query || m.name.toLowerCase().indexOf(query) >= 0 ||
			       m.ID.toLowerCase().indexOf(query) >= 0;
		});
		if (!shown.length) {
			host.innerHTML = '<p class="pa-hub-list-empty">' +
				(this.metabolites.length ? "No metabolite matches that search."
				                         : "This job has no scored metabolites.") +
				'</p>';
			return;
		}
		host.innerHTML = shown.map(function (m) {
			var fdr = Number(m.padjust);
			// The grid tinted p-values with renderFunctionLimit; the same
			// signal survives here as a class rather than an inline colour.
			var tone = fdr < 0.05 ? " is-significant" : (fdr < 0.1 ? " is-marginal" : "");
			return '<a class="pa-hub-item' + tone +
				(m.ID === me.seed ? " is-current" : "") +
				'" data-id="' + m.ID + '" href="#">' +
				'<span class="pa-hub-item-name">' + Ext.String.htmlEncode(m.name) + '</span>' +
				// The id stays on the row: a KEGG id is what a reader carries
				// to another tool, and several compounds share a common name.
				'<span class="pa-hub-item-meta">' +
				(m.name === m.ID ? "" : m.ID + ' &middot; ') +
				'FDR ' + me.fmt(fdr) +
				' &middot; ' + m.den + ' DE &middot; best at step ' + m.bestStep + '</span>' +
				'</a>';
		}).join("");
		Array.prototype.forEach.call(host.querySelectorAll(".pa-hub-item"), function (el) {
			el.addEventListener("click", function (event) {
				event.preventDefault();
				me.showCompound(el.getAttribute("data-id"), null, true);
			});
		});
	};

	this.fmt = function (value) {
		if (!isFinite(value)) { return "-"; }
		if (value < 0.001) { return Number(value).toExponential(1); }
		return Number(value).toFixed(3);
	};

	/* ------------------------------------------------------------------ *
	 * Step control                                                        *
	 * ------------------------------------------------------------------ */

	/**
	 * The four steps, as chips carrying their own ring size.
	 *
	 * They were four toggle buttons in the panel's bottom toolbar -- as far from
	 * the graph as the layout allows, and silent about which of them had
	 * anything to show. Most compounds run out well before radius 4, so a
	 * pressable button that changes nothing was the common case, not the edge
	 * case. A chip whose ring is empty is disabled and says "0".
	 */
	this.renderSteps = function () {
		var me = this;
		var host = document.getElementById(me.stepsID);
		if (!host) { return; }
		var counts = {};
		((me.payload && me.payload.rings) || []).forEach(function (r) {
			counts[r.step] = r.total;
		});
		host.innerHTML = [1, 2, 3, 4].map(function (n) {
			var total = counts[n];
			var known = (total !== undefined);
			var empty = known && total === 0;
			// The badge is the size of THIS ring, not of the ball -- that is
			// what makes a 0 meaningful. The button itself is cumulative (it
			// lights every ring up to n), and the two numbers differ, so the
			// tooltip says which is which rather than leaving the reader to
			// reconcile "2 1" against a table row reading 33.
			return '<button type="button" class="pa-hub-step' +
				(n === me.level ? " is-current" : "") + (empty ? " is-empty" : "") +
				'" data-step="' + n + '"' + (empty ? " disabled" : "") +
				' title="' + (empty
					? "No neighbours exactly " + n + " steps out"
					: "Show everything within " + n + " step" + (n === 1 ? "" : "s") +
					  (known ? " — " + total + " exactly " + n + " out" : "")) + '">' +
				n + (known ? '<em>' + total + '</em>' : "") +
				'</button>';
		}).join("");
		Array.prototype.forEach.call(host.querySelectorAll(".pa-hub-step"), function (el) {
			el.addEventListener("click", function () {
				me.setLevel(parseInt(el.getAttribute("data-step"), 10));
			});
		});
	};

	/* ------------------------------------------------------------------ *
	 * Network                                                             *
	 * ------------------------------------------------------------------ */

	this.showCompound = function (compoundID, level, reveal) {
		var me = this;
		var entry = me.entryFor(compoundID);
		me.seed = compoundID;
		me.level = Math.max(1, Math.min(4,
			parseInt(level, 10) || (entry ? entry.bestStep : 1)));
		me.payload = null;
		me.note("Loading the neighbourhood of " + compoundID + "…");
		me.clearDetail();
		me.renderList();
		me.renderSteps();
		me.setSeedName(me.nameOf(compoundID, "compound"));
		$.post(SERVER_URL_PA_HUB_SUBGRAPH, {
			jobID: me.model.getJobID(),
			compoundID: compoundID,
			level: 4,             // fetch all four; the control dims, never refetches
			maxEdges: 600,
			perRing: 40
		}).done(function (payload) {
			if (typeof payload === "string") {
				try { payload = JSON.parse(payload); } catch (e) { payload = null; }
			}
			if (!payload || !payload.success) {
				me.note((payload && payload.errorMessage) || "No network available.");
				return;
			}
			if (!payload.nodes || !payload.nodes.length) {
				me.note(compoundID + " has no neighbours in the KEGG network " +
				        "for this organism.");
				return;
			}
			// Ring compounds the job never measured are not in the scored
			// list, so their names arrive with the subgraph instead.
			me.mergeNames(payload.names || {});
			me.payload = payload;
			me.render(payload);
			me.renderSteps();
			// Selecting a metabolite opens the metabolite, not an empty card:
			// its four step scores are the numbers the removed grid carried,
			// and this is now the only place they are printed.
			me.showSeedDetail(reveal);
		}).fail(function () {
			me.note("Could not reach the server.");
		});
	};

	this.setSeedName = function (name) {
		var el = document.getElementById(this.seedNameID);
		if (el) { el.innerHTML = Ext.String.htmlEncode(name || ""); }
	};

	this.note = function (text) {
		var el = document.getElementById(this.noticeID);
		if (el) { el.innerHTML = text || ""; }
	};

	/**
	 * DE state for one feature.
	 *
	 * `entry.relevant` is an ARRAY after OmicValue.loadFromJSON, and [] is
	 * truthy -- so testing the property directly made "measured but not DE"
	 * unreachable and painted every measured feature up or down. Ask the
	 * OmicValue instead; that is what its accessors are for.
	 */
	this.stateOf = function (id, kind) {
		var entry = this.expressionFor(id, kind);
		if (!entry) { return "absent"; }              // never measured
		var de = (typeof entry.isRelevant === "function")
			? (entry.isRelevant() || entry.isRelevantAssociation())
			: false;
		if (!de) { return "quiet"; }
		var values = (typeof entry.getValues === "function") ? entry.getValues() : entry.values;
		var first = (values && values.length) ? Number(values[0]) : 0;
		return (first < 0) ? "down" : "up";
	};

	this.expressionFor = function (id, kind) {
		var data = this.model && this.model.getGlobalExpressionData();
		return data && ((kind === "compound")
			? (data.inputCompound || {})[id]
			: (data.inputGene || {})[id]);
	};

	this.elements = function (payload) {
		var me = this, out = [];
		payload.nodes.forEach(function (n) {
			var state = (n.step === 0) ? "seed" : me.stateOf(n.id, n.type);
			var name = me.nameOf(n.id, n.type);
			out.push({ group: "nodes", data: {
				id: n.id,
				// Truncated on the canvas only. Compound names run long
				// ("Ultra-long-chain omega-hydroxy fatty acid"), and a label
				// wider than its ring is worse than an id. The tooltip and the
				// detail card carry the whole name.
				label: (name.length > 24) ? name.slice(0, 23) + "\u2026" : name,
				fullName: name,
				step: n.step,
				kind: n.type,
				state: state,
				seed: (n.step === 0) ? 1 : 0,
				// Only the seed and the DE nodes are labelled. Radius 4 can
				// reach thousands of nodes; a label on each is unreadable.
				showLabel: (n.step === 0 || state === "up" || state === "down") ? 1 : 0
			}});
		});
		(payload.edges || []).forEach(function (e, i) {
			var typed = (payload.source !== "legacy-json") && !!e.subtype;
			out.push({ group: "edges", data: {
				id: "e" + i, source: e.source, target: e.target,
				kind: e.kind, subtype: e.subtype || "", pathway: e.pathway || "",
				// Arrowheads ONLY from a real subtype on a real KGML parse. The
				// legacy-json fallback carries none, and drawing direction from
				// it would be inventing biology.
				directed: typed ? 1 : 0,
				inhibits: (typed && /inhibition|repression/.test(e.subtype)) ? 1 : 0
			}});
		});
		return out;
	};

	this.render = function (payload) {
		var me = this;
		me.describe(payload);

		var host = document.getElementById(me.canvasID);
		if (!host) { return; }
		// Cytoscape measures its container once, so the height must be real
		// BEFORE construction or the graph lays out into a zero-height box.
		// Height comes from the flex stage; only force a value if that produced
		// nothing, which happens while the panel is still collapsed.
		if (host.getBoundingClientRect().height === 0) { host.style.height = "420px"; }

		if (me.cy) { me.cy.destroy(); me.cy = null; }
		me.cy = cytoscape({
			container: host,
			elements: me.elements(payload),
			minZoom: 0.2,
			maxZoom: 3,
			layout: {
				name: "concentric",
				concentric: function (n) { return 5 - n.data("step"); },
				levelWidth: function () { return 1; },
				minNodeSpacing: 22,
				avoidOverlap: true,
				animate: false,
				padding: 28
			},
			style: [
				{ selector: "node", style: {
					"width": 13, "height": 13,
					"background-color": "#ffffff",
					"border-width": 1.5, "border-color": "#595959",
					"label": "", "font-size": 10,
					"color": "#18181b",
					"text-margin-y": -3,
					"text-background-color": "#ffffff",
					"text-background-opacity": 0.85,
					"text-background-padding": 2 }},
				{ selector: "node[kind = 'compound']", style: {
					"shape": "diamond", "width": 15, "height": 15 }},
				{ selector: "node[state = 'up']", style: {
					"background-color": "#e34948", "border-color": "#e34948" }},
				{ selector: "node[state = 'down']", style: {
					"background-color": "#2a78d6", "border-color": "#2a78d6" }},
				{ selector: "node[state = 'absent']", style: {
					"border-style": "dashed", "border-color": "#a1a1aa" }},
				{ selector: "node[seed = 1]", style: {
					"shape": "diamond", "width": 28, "height": 28,
					"background-color": "#ffffff",
					"border-width": 3, "border-color": "#18181b",
					"font-size": 12, "font-weight": "bold" }},
				{ selector: "node[showLabel = 1]", style: { "label": "data(label)" }},
				{ selector: "node.far", style: { "label": "" }},
				{ selector: "edge", style: {
					"width": 1, "line-color": "#d4d4d8",
					"curve-style": "bezier", "opacity": 0.75 }},
				{ selector: "edge[directed = 1]", style: {
					"target-arrow-shape": "triangle", "arrow-scale": 0.6,
					"target-arrow-color": "#d4d4d8" }},
				{ selector: "edge[inhibits = 1]", style: {
					"target-arrow-shape": "tee" }},
				{ selector: ".dim", style: { "opacity": 0.08 }},
				{ selector: ".hovered", style: {
					"border-width": 3, "border-color": "#18181b" }},
				// setLevel owns .dim; a click highlight must use its own class
				// or the two fight over the same property.
				{ selector: ".picked", style: {
					"border-width": 4, "border-color": "#18181b" }}
			]
		});

		me.cy.one("layoutstop", function () {
			// fit() on afterrender runs before any data exists, so the graph
			// came up as a speck in the middle of an empty canvas. The layout
			// is the only moment the node positions are real.
			me.fitToVisible();
			me.drawRings();
		});
		me.cy.on("pan zoom resize", function () {
			me.applyLabelZoom();
			me.drawRings();
		});
		me.bindHover();
		me.bindTap();
		me.setLevel(me.level);
	};

	/**
	 * Say what was drawn and what was not.
	 *
	 * The server budgets PER RING and reports shown/total for each, so a cap can
	 * never read as "this is all there is". The first version hardcoded
	 * "Showing the 400 edges closest to X" while rings 3 and 4 were missing
	 * entirely -- true, and useless.
	 */
	this.describe = function (payload) {
		if (!payload) { this.note(""); return; }
		var lines = [];
		if (payload.source === "legacy-json") {
			lines.push('<span class="pa-hub-warn">This organism has no KGML on ' +
				'disk, so only direct neighbours are drawn and relation types ' +
				'are unavailable.</span>');
		}
		// A step whose ring is genuinely empty must SAY so. Clicking 3 and
		// getting no visible change is indistinguishable from a broken control,
		// and most compounds run out well before radius 4.
		var reach = 0;
		(payload.rings || []).forEach(function (r) {
			if (r.total > 0) { reach = Math.max(reach, r.step); }
		});
		if (this.level > reach) {
			lines.push("<b>" + Ext.String.htmlEncode(payload.seed
					? this.nameOf(payload.seed, "compound") : "This metabolite") +
				"</b> has no neighbours beyond step " + reach +
				", so there is nothing to show at step " + this.level + ".");
		}

		var sampled = (payload.rings || []).filter(function (r) {
			return r.shown < r.total && r.step <= this.level;
		}, this);
		if (sampled.length) {
			lines.push("Large rings are sampled, differentially expressed features first: " +
				sampled.map(function (r) {
					return "step " + r.step + " showing <b>" + r.shown + " of " +
					       r.total + "</b>";
				}).join(" &middot; ") + ".");
		}
		this.note(lines.join(" "));
	};

	/**
	 * Faint guide circles plus a "step N" label, so the rings READ as steps
	 * rather than as an accident of the layout.
	 *
	 * Built with createElementNS, not svg.js: svg.js 2.0.5's .path() reads
	 * pathSegList, removed in Chrome 48, which is why no diagram in this
	 * application had ever carried a vector primitive.
	 */
	this.drawRings = function () {
		var me = this, cy = me.cy;
		var svg = document.getElementById(me.ringsID);
		if (!cy || !svg) { return; }
		while (svg.firstChild) { svg.removeChild(svg.firstChild); }
		var seed = cy.nodes("[seed = 1]");
		if (!seed.length) { return; }
		var origin = seed.position(), pan = cy.pan(), zoom = cy.zoom();
		var radii = {};
		cy.nodes().forEach(function (n) {
			var step = n.data("step");
			if (!step) { return; }
			var dx = n.position("x") - origin.x, dy = n.position("y") - origin.y;
			if (!radii[step]) { radii[step] = []; }
			radii[step].push(Math.sqrt(dx * dx + dy * dy));
		});
		var cx = origin.x * zoom + pan.x, cyy = origin.y * zoom + pan.y;
		var NS = "http://www.w3.org/2000/svg";
		var counts = {};
		(me.payload && me.payload.rings || []).forEach(function (r) { counts[r.step] = r; });
		Object.keys(radii).sort().forEach(function (step) {
			var list = radii[step];
			var mean = list.reduce(function (a, b) { return a + b; }, 0) / list.length;
			var r = mean * zoom;
			var current = (String(step) === String(me.level));
			var circle = document.createElementNS(NS, "circle");
			circle.setAttribute("cx", cx);
			circle.setAttribute("cy", cyy);
			circle.setAttribute("r", r);
			circle.setAttribute("class", "pa-hub-ring" + (current ? " is-current" : ""));
			svg.appendChild(circle);
			var text = document.createElementNS(NS, "text");
			text.setAttribute("x", cx);
			text.setAttribute("y", cyy - r - 5);
			text.setAttribute("text-anchor", "middle");
			text.setAttribute("class", "pa-hub-ring-label" + (current ? " is-current" : ""));
			var info = counts[step];
			text.textContent = "step " + step +
				(info && info.shown < info.total
					? " (" + info.shown + " of " + info.total + ")" : "");
			svg.appendChild(text);
		});
	};

	this.bindHover = function () {
		var me = this;
		var tip = document.getElementById(me.tipID);
		if (!tip) { return; }
		var WORDS = { up: "up", down: "down", quiet: "measured, not DE",
		              absent: "not measured", seed: "this metabolite" };
		me.cy.on("mouseover", "node", function (event) {
			var n = event.target;
			n.addClass("hovered");
			var step = n.data("step");
			var label = n.data("fullName") || n.data("label"), id = n.id();
			tip.innerHTML = "<b>" + Ext.String.htmlEncode(label) + "</b>" +
				(label === id ? "" :
					' <span class="pa-hub-tip-hint">' +
					Ext.String.htmlEncode(id) + "</span>") + "<br>" +
				(n.data("kind") || "feature") + " · " + WORDS[n.data("state")] +
				(step ? "<br>" + step + " step" + (step === 1 ? "" : "s") + " away" : "") +
				'<br><span class="pa-hub-tip-hint">click for expression</span>';
			tip.style.display = "block";
		});
		me.cy.on("mouseout", "node", function (event) {
			event.target.removeClass("hovered");
			tip.style.display = "none";
		});
		me.cy.on("mouseover", "edge", function (event) {
			var e = event.target;
			tip.innerHTML = "<b>" + Ext.String.htmlEncode(me.edgeEnd(e, "source")) +
				" — " + Ext.String.htmlEncode(me.edgeEnd(e, "target")) +
				"</b><br>" + e.data("kind") +
				(e.data("subtype") ? " · " + e.data("subtype") : "") +
				(e.data("pathway") ? "<br>" + e.data("pathway") : "");
			tip.style.display = "block";
		});
		me.cy.on("mouseout", "edge", function () { tip.style.display = "none"; });
		me.cy.on("mousemove", function (event) {
			if (!event.renderedPosition) { return; }
			tip.style.left = (event.renderedPosition.x + 14) + "px";
			tip.style.top = (event.renderedPosition.y + 14) + "px";
		});
	};

	/** An edge endpoint by name, using the node already on the graph. */
	this.edgeEnd = function (edge, which) {
		var id = edge.data(which);
		var node = this.cy && this.cy.getElementById(id);
		return (node && node.length)
			? (node.data("fullName") || node.data("label")) : id;
	};

	this.bindTap = function () {
		var me = this;
		me.cy.on("tap", "node", function (event) {
			me.cy.nodes().removeClass("picked");
			event.target.addClass("picked");
			me.showNodeDetail(event.target);
		});
		me.cy.on("tap", function (event) {
			// Tapping the background returns to the metabolite, rather than
			// emptying the card: an empty card below the graph reads as a
			// layout bug, and the seed's own numbers are always relevant here.
			if (event.target === me.cy) {
				me.cy.nodes().removeClass("picked");
				me.showSeedDetail(true);
			}
		});
	};

	/* ------------------------------------------------------------------ *
	 * The detail card: summary + one heatmap per omic                     *
	 * ------------------------------------------------------------------ */

	this.clearDetail = function () {
		// Highcharts instances keep resize and tooltip listeners; emptying the
		// container alone orphans them. The Paint handler this replaces never
		// destroyed a single chart.
		this.charts.forEach(function (chart) {
			try { if (chart && chart.destroy) { chart.destroy(); } } catch (e) {}
		});
		this.charts = [];
		var host = document.getElementById(this.detailID);
		if (host) {
			host.innerHTML = "";
			host.classList.remove("is-open");
		}
		this.resizeGraph();
	};

	/**
	 * Open the card, resizing the canvas so the graph is never covered.
	 *
	 * `reveal` scrolls the card into view, and only a click passes it: the
	 * panel opens its first metabolite by itself on load, and scrolling the
	 * page to Step 3's seventh section because a panel initialised would be a
	 * worse bug than the one this fixes. block:"nearest" is a no-op when the
	 * card is already fully visible, which is the common case once the reader
	 * has scrolled to the section.
	 */
	this.openDetail = function (html, reveal) {
		var me = this;
		var host = document.getElementById(me.detailID);
		if (!host) { return null; }
		host.innerHTML =
			'<button type="button" class="pa-hub-detail-close" ' +
			  'aria-label="Close">&times;</button>' + html;
		host.classList.add("is-open");
		var close = host.querySelector(".pa-hub-detail-close");
		if (close) {
			close.addEventListener("click", function () {
				if (me.cy) { me.cy.nodes().removeClass("picked"); }
				me.clearDetail();
			});
		}
		me.resizeGraph();
		if (reveal) { host.scrollIntoView({ block: "nearest" }); }
		return host;
	};

	/**
	 * The canvas is a flex child of the stage; opening the card resizes it.
	 *
	 * resize() alone is not enough, and the difference is visible: Cytoscape
	 * keeps its pan and zoom across a resize, so a canvas that lost 264px of
	 * height kept drawing the same extent and the bottom third of the graph
	 * was simply cut off by the card. Re-fitting costs a zoom change; being
	 * silently clipped costs the nodes.
	 */
	this.resizeGraph = function () {
		var me = this;
		if (!me.cy) { return; }
		// One frame after the class change, so the flex box has been laid out.
		// paDeferFrame, not rAF: rAF never fires in a background tab.
		paDeferFrame(function () {
			if (!me.cy) { return; }
			me.cy.resize();
			me.fitToVisible();
			me.drawRings();
		});
	};

	/**
	 * The selected metabolite: its four step scores, then its own expression.
	 *
	 * These four rows per compound are exactly what the removed grid held. The
	 * grid printed all 852 of them at once and made you filter by step to read
	 * any of them; here they are four rows about the one compound you asked
	 * about, with the step you are looking at marked.
	 */
	this.showSeedDetail = function (reveal) {
		var me = this;
		var entry = me.entryFor(me.seed);
		if (!entry) { me.clearDetail(); return; }
		me.clearDetail();

		var rows = [1, 2, 3, 4].map(function (step) {
			var row = entry.steps[step];
			if (!row) {
				return '<tr class="is-absent"><td>' + step +
					'</td><td colspan="4">not scored</td></tr>';
			}
			var fdr = Number(row.padjust);
			return '<tr' + (step === me.level ? ' class="is-current"' : "") + '>' +
				'<td>' + step + '</td>' +
				'<td>' + row.DEN + '</td>' +
				'<td>' + (Number(row.DEN) + Number(row.noDEN)) + '</td>' +
				'<td>' + (Number(row.Percentage) * 100).toFixed(1) + '%</td>' +
				'<td' + (fdr < 0.05 ? ' class="is-significant"' : "") + '>' +
				  me.fmt(fdr) + '</td></tr>';
		}).join("");

		var host = me.openDetail(
			'<h3 class="pa-hub-detail-title">' + me.nameWithID(entry.ID, "compound") +
			  ' <span class="pa-hub-detail-where">' +
			  'the metabolite this network is centred on</span></h3>' +
			'<div class="pa-hub-detail-body">' +
			  '<table class="pa-hub-steptable">' +
			    '<thead><tr><th>Step</th><th>DE</th><th>Measured</th>' +
			    '<th>% DE</th><th>FDR</th></tr></thead>' +
			    '<tbody>' + rows + '</tbody>' +
			  '</table>' +
			  // The two counts on screen measure different things and would
			  // otherwise look like a contradiction: the scorer counts only
			  // MEASURED genes and counts them cumulatively (scorer.py:88,
			  // `ids[measured_gene[ids]]`), while a chip counts every node --
			  // compounds and unmeasured genes included -- in one ring.
			  '<p class="pa-hub-detail-summary">Cumulative, and counting only ' +
			    'genes measured in your data. The step chips above count every ' +
			    'node in a single ring, so the two do not add up.</p>' +
			  '<div class="pa-hub-omics"></div>' +
			'</div>', reveal);
		if (host) { me.fillOmics(host, me.seed, "compound"); }
	};

	/** A clicked node: what it is, how far, how it connects, its expression. */
	this.showNodeDetail = function (node) {
		var me = this;
		var id = node.id();
		var kind = node.data("kind");
		var step = node.data("step");
		if (step === 0) { me.showSeedDetail(true); return; }

		me.clearDetail();
		var seedName = me.nameOf(me.seed, "compound");
		var WORDS = { up: "up in this comparison", down: "down in this comparison",
		              quiet: "measured, not differentially expressed",
		              absent: "not measured in any omic you uploaded" };
		var state = node.data("state");

		// How a gene reaches the seed is the genuinely new information here:
		// compoundRegulateFeatures shipped node sets, so no earlier view could
		// answer "via what?" for anything past the first ring.
		var edges = node.connectedEdges().map(function (e) {
			return '<li><b>' + Ext.String.htmlEncode(me.edgeEnd(e, "source")) +
				" → " + Ext.String.htmlEncode(me.edgeEnd(e, "target")) +
				'</b> · ' + e.data("kind") +
				(e.data("subtype") ? " · " + e.data("subtype") : "") +
				(e.data("pathway") ? ' <span class="pa-hub-edge-src">' +
				                     e.data("pathway") + '</span>' : "") + '</li>';
		}).slice(0, 8).join("");

		var host = me.openDetail(
			'<h3 class="pa-hub-detail-title">' + me.nameWithID(id, kind) +
			  ' <span class="pa-hub-detail-where">' + kind + " &middot; " + step +
			  " step" + (step === 1 ? "" : "s") + " from " +
			  Ext.String.htmlEncode(seedName) + '</span></h3>' +
			'<div class="pa-hub-detail-body">' +
			  '<p class="pa-hub-detail-summary">' + (WORDS[state] || state) + '.</p>' +
			  '<div class="pa-hub-omics"></div>' +
			  (edges ? '<p class="pa-hub-detail-sub">How it connects</p>' +
			           '<ul class="pa-hub-edges">' + edges + '</ul>' : "") +
			'</div>', true);
		if (host) { me.fillOmics(host, id, kind); }
	};

	/**
	 * Draw one heatmap + plot per omic, from /pa_hub_feature.
	 *
	 * globalExpressionData carries omicsValues[0] and nothing else, so drawing
	 * from it showed one of this job's four gene-based omics and said nothing
	 * about the other three -- while the pathway views on the same page show
	 * them all. The clicked feature's full set is a few hundred bytes, so it is
	 * fetched per click and cached.
	 */
	this.fillOmics = function (host, id, kind) {
		var me = this;
		var slot = host.querySelector(".pa-hub-omics");
		if (!slot) { return; }
		var key = kind + "|" + id;

		var draw = function (payload) {
			// The card may have been replaced while the request was in flight.
			if (!document.body.contains(slot)) { return; }
			var omics = (payload && payload.omics) || [];
			if (!omics.length) {
				slot.innerHTML = '<p class="pa-hub-detail-summary">' +
					'No expression was measured for it, so there is nothing to plot.</p>';
				return;
			}
			me.drawOmics(slot, omics);
		};

		if (me.featureCache[key]) { draw(me.featureCache[key]); return; }
		slot.innerHTML = '<p class="pa-hub-detail-summary">' +
			'<i class="fa fa-cog fa-spin"></i> Loading expression…</p>';
		$.post(SERVER_URL_PA_HUB_FEATURE, {
			jobID: me.model.getJobID(), featureID: id, featureType: kind
		}).done(function (payload) {
			if (typeof payload === "string") {
				try { payload = JSON.parse(payload); } catch (e) { payload = null; }
			}
			if (!payload || !payload.success) {
				if (!document.body.contains(slot)) { return; }
				slot.innerHTML = '<p class="pa-hub-detail-summary">' +
					((payload && payload.errorMessage) ||
					 "The expression for this feature could not be loaded.") + '</p>';
				return;
			}
			me.featureCache[key] = payload;
			draw(payload);
		}).fail(function () {
			if (!document.body.contains(slot)) { return; }
			slot.innerHTML = '<p class="pa-hub-detail-summary">' +
				'Could not reach the server for this feature’s expression.</p>';
		});
	};

	this.drawOmics = function (slot, omics) {
		var me = this;
		var summaries = me.model.getDataDistributionSummaries() || {};
		var visual = (me.getParent && me.getParent() && me.getParent().visualOptions) || {};
		var drawable = omics.filter(function (o) { return o.omicName in summaries; });

		if (!drawable.length) {
			slot.innerHTML = '<p class="pa-hub-detail-summary">This job carries no ' +
				'distribution summary for ' +
				omics.map(function (o) { return Ext.String.htmlEncode(o.omicName); }).join(", ") +
				', so the heatmap cannot be scaled.</p>';
			return;
		}

		slot.innerHTML = drawable.map(function (o, index) {
			// The colour ramp these heatmaps are painted with. The charts carry
			// legend:{enabled:false}, so without this the scale is stated
			// nowhere. Guarded: a bad summary for one omic must not stop the rest.
			var legend = "";
			try {
				legend = paColorLegend(
					getMinMax(summaries[o.omicName], visual.colorReferences
						? visual.colorReferences[o.omicName] : "p10p90"),
					visual.colorScale);
			} catch (error) {
				console.warn("[hub] no colour legend for " + o.omicName + ": " + error);
			}
			// The heatmap div and the plot div must be ADJACENT SIBLINGS with
			// the heatmap first: the heatmap's point handlers reach the plot
			// with .parent().next().highcharts(). Anything between them makes
			// that undefined and hovering a cell throws.
			return '<div class="contentbox pa-hub-omic">' +
				'<h4>' + Ext.String.htmlEncode(o.omicName) + '</h4>' + legend +
				'<div class="PA_step5_heatmapContainer" ' +
				  'id="' + me.detailID + '_hm' + index + '" style="height:130px"></div>' +
				'<div class="PA_step5_plotContainer" ' +
				  'id="' + me.detailID + '_pl' + index + '" style="height:130px"></div>' +
				'</div>';
		}).join("");

		drawable.forEach(function (o, index) {
			var value = OmicValue.loadFromJSON(o);
			try {
				me.charts.push(generateHeatmap(me.detailID + "_hm" + index, o.omicName,
					[value], summaries, visual, paOmicHeaders(me.model, o.omicName)));
				me.charts.push(generatePlot(me.detailID + "_pl" + index, o.omicName,
					[value], summaries, null, visual, paOmicHeaders(me.model, o.omicName)));
			} catch (error) {
				// A silent guard reads as a dead click, so say what happened.
				console.warn("[hub] could not draw " + o.omicName + ": " + error);
				var box = document.getElementById(me.detailID + "_hm" + index);
				if (box) {
					box.innerHTML = '<p class="pa-hub-detail-summary">This omic could ' +
						'not be drawn.</p>';
				}
			}
		});
	};

	/* ------------------------------------------------------------------ *
	 * Rings and zoom                                                      *
	 * ------------------------------------------------------------------ */

	/**
	 * Fit the lit subset, but never magnify past MAX_FIT_ZOOM.
	 *
	 * fit() alone scales to fill: step 1 of a compound with five neighbours
	 * came up at 3x, with node labels rendered 60px tall and five dots spread
	 * across a 1000px canvas. Zoom is not carrying information here -- the
	 * rings are -- so it is capped and the graph simply sits in the middle of
	 * the space it does not need.
	 */
	this.MAX_FIT_ZOOM = 1.3;
	this.fitToVisible = function () {
		if (!this.cy) { return; }
		var lit = this.cy.elements().not(".dim");
		var shown = lit.length ? lit : this.cy.elements();
		this.cy.fit(shown, 40);
		if (this.cy.zoom() > this.MAX_FIT_ZOOM) {
			this.cy.zoom(this.MAX_FIT_ZOOM);
			this.cy.center(shown);
		}
		this.applyLabelZoom();
	};

	/** Labels only where they can be read. */
	this.LABEL_ZOOM = 0.55;
	this.applyLabelZoom = function () {
		if (!this.cy) { return; }
		var far = this.cy.zoom() < this.LABEL_ZOOM;
		this.cy.nodes().toggleClass("far", far);
		// The seed keeps its label at every zoom -- it is the one node whose
		// identity the panel is about.
		this.cy.nodes("[seed = 1]").removeClass("far");
	};

	/**
	 * Light the chosen ring, dim the rest. Hide-don't-remove: removing elements
	 * forces a relayout and the rings jump between steps.
	 */
	this.setLevel = function (level) {
		var me = this;
		me.level = level;
		me.renderSteps();
		if (!me.cy) { return; }
		me.cy.batch(function () {
			me.cy.nodes().forEach(function (n) {
				var step = n.data("step");
				n.toggleClass("dim", !(step === 0 || step <= level));
			});
			me.cy.edges().forEach(function (e) {
				e.toggleClass("dim",
					e.source().hasClass("dim") || e.target().hasClass("dim"));
			});
		});
		me.fitToVisible();
		me.drawRings();
		me.describe(me.payload);
		// The step table marks the step you are looking at, so it has to be
		// redrawn -- but only while the card is showing the metabolite, or
		// changing step would throw away the node you clicked.
		var host = document.getElementById(me.detailID);
		if (host && host.querySelector(".pa-hub-steptable")) { me.showSeedDetail(); }
	};

	/* ------------------------------------------------------------------ *
	 * Component                                                           *
	 * ------------------------------------------------------------------ */

	this.getComponent = function () {
		var me = this;
		var legend =
			'<div class="pa-hub-legend">' +
			  '<span><i class="sw up"></i>up</span>' +
			  '<span><i class="sw down"></i>down</span>' +
			  '<span><i class="sw quiet"></i>measured, not DE</span>' +
			  '<span><i class="sw absent"></i>not measured</span>' +
			  '<span><i class="sw seed"></i>this metabolite</span>' +
			'</div>';

		this.component = Ext.create("Ext.panel.Panel", {
			// contentbox + the 10px margin every other Step 3 card uses; without
			// them this panel sits inset from its neighbours and draws no edge.
			cls: "contentbox pa-hub-net",
			border: 0,
			margin: "10 10 10 10",
			// Self-suppressing, the way the other network views are: the panel
			// starts hidden and reveals itself in afterrender only if the job
			// actually scored some metabolites. It is the whole hub UI now, not
			// a popup opened from a table, so it must not need a click to appear.
			hidden: true,
			// The heading is an <h2> in the body, NOT an Ext panel header:
			// paTocSections() queries h2 only, so an Ext header never reaches
			// the contents rail.
			html:
				'<h2 id="HubNetworkSection">Metabolite hub analysis</h2>' +
				'<p class="pa-hub-intro">Which metabolites have differentially ' +
				'expressed genes concentrated around them in the KEGG network. ' +
				'Pick a metabolite; click any node for its expression.</p>' +
				'<div class="more-net-body">' +
				  '<div class="more-net-sidepanel pa-hub-listrail">' +
				    '<div class="pa-hub-railhead">' +
				      '<input type="search" id="' + me.searchID + '" class="pa-hub-search" ' +
				        'placeholder="Search metabolites…" aria-label="Search metabolites">' +
				      '<div class="pa-hub-railsort">' +
				        '<label class="pa-hub-sortlabel" for="' + me.sortID + '">Rank by</label>' +
				        '<select id="' + me.sortID + '" class="pa-hub-sort">' +
				          '<option value="padjust">FDR</option>' +
				          '<option value="density">% DE neighbours</option>' +
				          '<option value="den">DE neighbours</option>' +
				          '<option value="name">Name</option>' +
				        '</select>' +
				      '</div>' +
				      '<p class="pa-hub-railcount" id="' + me.countID + '"></p>' +
				    '</div>' +
				    '<div class="pa-hub-listbody" id="' + me.listID + '"></div>' +
				  '</div>' +
				  '<div class="pa-hub-stage more-net-canvas">' +
				    '<div class="pa-hub-stagehead">' +
				      '<span class="pa-hub-seedname" id="' + me.seedNameID + '"></span>' +
				      '<span class="pa-hub-steplabel">steps away:</span>' +
				      '<span class="pa-hub-steps" id="' + me.stepsID + '"></span>' +
				      legend +
				    '</div>' +
				    '<div id="' + me.noticeID + '" class="pa-net-notice"></div>' +
				    '<div class="pa-hub-plot">' +
				      '<svg id="' + me.ringsID + '" class="pa-hub-rings"></svg>' +
				      '<div id="' + me.canvasID + '" class="pa-net-canvas"></div>' +
				      '<div id="' + me.tipID + '" class="pa-hub-tip"></div>' +
				    '</div>' +
				    '<div id="' + me.detailID + '" class="pa-hub-detail"></div>' +
				  '</div>' +
				'</div>',
			listeners: {
				// paDeferFrame, NOT requestAnimationFrame: rAF never runs in a
				// background tab and the panel came up permanently blank.
				afterrender: function () {
					paDeferFrame(function () {
						if (!me.hasData()) { return; }   // stays hidden
						me.component.show();
						me.mount();
						if (me.cy) { me.cy.resize(); me.fitToVisible(); me.drawRings(); }
					});
				},
				expand: function () {
					if (me.cy) { me.cy.resize(); me.fitToVisible(); me.drawRings(); }
				},
				beforedestroy: function () {
					me.clearDetail();
					if (me.cy) { me.cy.destroy(); me.cy = null; }
				}
			}
		});
		return this.component;
	};

	this.bindControls = function () {
		var me = this;
		var search = document.getElementById(me.searchID);
		if (search && !search.dataset.hubBound) {
			search.dataset.hubBound = "1";
			var timer = null;
			search.addEventListener("input", function () {
				// buffer:100 is the house debounce (ExtJS_extensions.js:209-239)
				clearTimeout(timer);
				timer = setTimeout(function () {
					me.query = search.value || "";
					me.renderList();
				}, 100);
			});
		}
		var sort = document.getElementById(me.sortID);
		if (sort && !sort.dataset.hubBound) {
			sort.dataset.hubBound = "1";
			sort.addEventListener("change", function () {
				me.sortKey = sort.value;
				me.sortList();
				me.renderList();
			});
		}
	};

	/** Open the most significant metabolite so the panel is never empty. */
	this.selectFirst = function () {
		if (this.seed || !this.metabolites.length) { return; }
		this.showCompound(this.metabolites[0].ID);
	};

	/** Whether this job has anything for the panel to show. */
	this.hasData = function () {
		return this.metabolites.length > 0;
	};
}
PA_Step3HubNetworkView.prototype = new View();
