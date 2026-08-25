/**
 * PA_Step3HubNetworkView -- metabolite hub analysis as a network, not a table.
 *
 * Why this exists. The KEGG interaction graph has always been on the server and
 * never reached the browser: compoundRegulateFeatures ships node SETS with no
 * pairs, no direction, no edge types and no intermediate hops, so a client could
 * not tell whether a radius-3 gene reached the metabolite via gene X or gene Y.
 * The hub table reported numbers about a network nobody could see.
 *
 * This panel replaces that table. A metabolite LIST ranked by significance
 * selects the seed; the network draws its 1..4 step neighbourhood as concentric
 * rings; clicking any node opens its expression heatmap and plot underneath.
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
	this.summaryID = "hubNetSummary" + salt;
	this.detailID = "hubNetDetail" + salt;

	this.cy = null;
	this.level = 1;
	this.payload = null;
	this.seed = null;
	this.charts = [];        // Highcharts instances owned by the detail panel
	this.metabolites = [];   // one entry per compound, with its four step rows
	this.sortKey = "padjust";
	this.query = "";

	/* ------------------------------------------------------------------ *
	 * Model                                                               *
	 * ------------------------------------------------------------------ */

	this.loadModel = function (model) {
		var me = this;
		me.model = model;
		me.buildList();
		me.renderList();
		me.renderSummary();
		// loadModel and afterrender race: PA_Step3JobView constructs the view,
		// calls loadModel, and only then lays the panel out. Whichever runs
		// second has to do the work.
		if (me.component && me.component.rendered && me.hasData()) {
			me.component.show();
			me.renderList();
			me.renderSummary();
			me.bindControls();
			me.selectFirst();
		}
	};

	/**
	 * Collapse the hub rows to ONE entry per compound.
	 *
	 * getHubAnalysisResult() is one row per (compound, radius), so every
	 * metabolite appears four times -- which is why the grid it replaces needed
	 * a step filter to be readable at all. Here the four scores become a
	 * per-step array on a single entry and the network's ring buttons are the
	 * step control.
	 */
	this.buildList = function () {
		var rows = (this.model && this.model.getHubAnalysisResult()) || {};
		var mapping = (this.model && this.model.mappingComp) || {};
		var byID = {};
		for (var key in rows) {
			var row = paHubRow(rows[key]);
			if (!row || !row.ID) { continue; }
			var entry = byID[row.ID];
			if (!entry) {
				entry = byID[row.ID] = {
					ID: row.ID,
					name: mapping[row.ID] || row.ID,
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

	/* ------------------------------------------------------------------ *
	 * Summary                                                             *
	 * ------------------------------------------------------------------ */

	this.renderSummary = function () {
		var host = document.getElementById(this.summaryID);
		if (!host) { return; }
		var total = this.metabolites.length;
		var significant = this.metabolites.filter(function (m) {
			return m.padjust < 0.05;
		}).length;
		var deTotal = this.metabolites.reduce(function (sum, m) {
			return sum + (m.den || 0);
		}, 0);
		host.innerHTML =
			'<div class="po-band">' +
			  this.stat("flask", total, "Metabolites scored", false) +
			  this.stat("star", significant, "Significant (FDR &lt; 0.05)", significant > 0) +
			  this.stat("share-alt", deTotal, "DE neighbours found", false) +
			'</div>';
	};

	this.stat = function (icon, count, label, highlight) {
		return '<div class="po-pathway-stat">' +
			'<div class="po-pathway-icon' + (highlight ? " is-significant" : "") + '">' +
			  '<i class="fa fa-' + icon + '" aria-hidden="true"></i></div>' +
			'<div class="po-band-figure">' +
			  '<div class="po-pathway-count">' + count + '</div>' +
			  '<div class="po-pathway-label">' + label + '</div>' +
			'</div></div>';
	};

	/* ------------------------------------------------------------------ *
	 * Metabolite list                                                     *
	 * ------------------------------------------------------------------ */

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
				'" data-id="' + m.ID + '" data-step="' + m.bestStep + '" href="#">' +
				'<span class="pa-hub-item-name">' + Ext.String.htmlEncode(m.name) + '</span>' +
				'<span class="pa-hub-item-meta">FDR ' + me.fmt(fdr) +
				' &middot; ' + m.den + ' DE &middot; step ' + m.bestStep + '</span>' +
				'</a>';
		}).join("");
		Array.prototype.forEach.call(host.querySelectorAll(".pa-hub-item"), function (el) {
			el.addEventListener("click", function (event) {
				event.preventDefault();
				me.showCompound(el.getAttribute("data-id"),
				                el.getAttribute("data-step"));
			});
		});
	};

	this.fmt = function (value) {
		if (!isFinite(value)) { return "-"; }
		if (value < 0.001) { return Number(value).toExponential(1); }
		return Number(value).toFixed(3);
	};

	/* ------------------------------------------------------------------ *
	 * Network                                                             *
	 * ------------------------------------------------------------------ */

	this.showCompound = function (compoundID, level) {
		var me = this;
		me.seed = compoundID;
		me.level = Math.max(1, Math.min(4, parseInt(level, 10) || 1));
		me.note("Loading the neighbourhood of " + compoundID + "…");
		me.clearDetail();
		me.renderList();
		me.syncStepButtons();
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
			me.payload = payload;
			me.render(payload);
		}).fail(function () {
			me.note("Could not reach the server.");
		});
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
		var data = this.model && this.model.getGlobalExpressionData();
		var entry = data && ((kind === "compound")
			? (data.inputCompound || {})[id]
			: (data.inputGene || {})[id]);
		if (!entry) { return "absent"; }              // never measured
		var de = (typeof entry.isRelevant === "function")
			? (entry.isRelevant() || entry.isRelevantAssociation())
			: false;
		if (!de) { return "quiet"; }
		var values = (typeof entry.getValues === "function") ? entry.getValues() : entry.values;
		var first = (values && values.length) ? Number(values[0]) : 0;
		return (first < 0) ? "down" : "up";
	};

	this.elements = function (payload) {
		var me = this, out = [];
		var mapping = (me.model && me.model.mappingComp) || {};
		payload.nodes.forEach(function (n) {
			var state = (n.step === 0) ? "seed" : me.stateOf(n.id, n.type);
			out.push({ group: "nodes", data: {
				id: n.id,
				label: (n.step === 0) ? (mapping[n.id] || n.id) : n.id,
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
		// Height normally comes from --pa-net-canvas-height via .pa-net-canvas
		// in network-views.css -- do not hardcode over it. Only force a value
		// if the class produced nothing, which happens while still collapsed.
		if (host.getBoundingClientRect().height === 0) { host.style.height = "520px"; }

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
			lines.push("<b>" + (payload.seed || "This metabolite") +
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
			tip.innerHTML = "<b>" + n.data("label") + "</b><br>" +
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
			tip.innerHTML = "<b>" + e.data("source") + " — " + e.data("target") +
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

	this.bindTap = function () {
		var me = this;
		me.cy.on("tap", "node", function (event) {
			me.cy.nodes().removeClass("picked");
			event.target.addClass("picked");
			me.showDetail(event.target);
		});
		me.cy.on("tap", function (event) {
			if (event.target === me.cy) {
				me.cy.nodes().removeClass("picked");
				me.clearDetail();
			}
		});
	};

	/* ------------------------------------------------------------------ *
	 * Node detail: the expression heatmap                                 *
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
		if (host) { host.innerHTML = ""; }
	};

	this.showDetail = function (node) {
		var me = this;
		var host = document.getElementById(me.detailID);
		if (!host) { return; }
		me.clearDetail();

		var id = node.id();
		var kind = node.data("kind");
		var step = node.data("step");
		var data = me.model.getGlobalExpressionData() || {};
		var entry = (kind === "compound") ? (data.inputCompound || {})[id]
		                                  : (data.inputGene || {})[id];
		var title = (kind === "compound")
			? ((me.model.mappingComp || {})[id] || id)
			: id;
		var where = step === 0
			? "the metabolite this network is centred on"
			: step + " step" + (step === 1 ? "" : "s") + " from " +
			  ((me.model.mappingComp || {})[me.seed] || me.seed);

		if (!entry) {
			// The legitimate "absent" case. There is no client-side id->symbol
			// table for an unmeasured gene, so show what IS known -- and the
			// genuinely new information the old table could never give: HOW it
			// reaches the seed.
			var edges = node.connectedEdges().map(function (e) {
				return "<li><b>" + e.data("source") + " — " + e.data("target") +
					"</b> · " + e.data("kind") +
					(e.data("subtype") ? " · " + e.data("subtype") : "") +
					(e.data("pathway") ? " · " + e.data("pathway") : "") + "</li>";
			}).slice(0, 12).join("");
			host.innerHTML =
				'<h3 class="pa-hub-detail-title">' + Ext.String.htmlEncode(title) + '</h3>' +
				'<div class="contentbox paEmptyNote"><p>' + kind + ", " + where +
				". No expression was measured for it in the omics you uploaded, " +
				"so there is nothing to plot.</p></div>" +
				(edges ? '<p class="pa-hub-detail-sub">How it connects</p>' +
				         '<ul class="pa-hub-edges">' + edges + '</ul>' : "");
			return;
		}

		// omicName must be a KEY of dataDistributionSummaries, and it is not
		// carried on the entry -- the server ships omicsValues[0] only. Derive
		// it from the model rather than hardcoding "Gene expression" /
		// "Metabolomics", which is why the old handler drew nothing for any
		// other omic.
		var summaries = me.model.getDataDistributionSummaries() || {};
		var omics = (kind === "compound")
			? (me.model.getCompoundBasedInputOmics() || [])
			: (me.model.getGeneBasedInputOmics() || []);
		var omicName = null;
		for (var i = 0; i < omics.length; i++) {
			if (omics[i] && omics[i].omicName && (omics[i].omicName in summaries)) {
				omicName = omics[i].omicName;
				break;
			}
		}
		if (!omicName) {
			host.innerHTML =
				'<h3 class="pa-hub-detail-title">' + Ext.String.htmlEncode(title) + '</h3>' +
				'<div class="contentbox paEmptyNote"><p>' + kind + ", " + where +
				". This job carries no distribution summary for its omic, so the " +
				"heatmap cannot be scaled.</p></div>";
			return;
		}

		var width = Math.max(260, $(host).width() - 400);
		// The heatmap div and the plot div must be ADJACENT SIBLINGS with the
		// heatmap first: the heatmap's point handlers reach the plot with
		// .parent().next().highcharts(). Anything between them -- a title, a
		// legend -- makes that undefined and hovering a cell throws.
		host.innerHTML =
			'<h3 class="pa-hub-detail-title">' + Ext.String.htmlEncode(title) +
			  ' <span class="pa-hub-detail-where">' + where + '</span></h3>' +
			'<div class="contentbox">' +
			  '<div class="PA_step5_heatmapContainer" id="' + me.detailID + '_hm" ' +
			    'style="height:130px"></div>' +
			  '<div class="PA_step5_plotContainer" id="' + me.detailID + '_plot" ' +
			    'style="width:' + width + 'px;height:130px"></div>' +
			'</div>';

		var headers = paOmicHeaders(me.model, omicName);
		var visual = (me.getParent && me.getParent() && me.getParent().visualOptions) || {};
		try {
			me.charts = [
				generateHeatmap(me.detailID + "_hm", omicName, [entry], summaries, visual, headers),
				generatePlot(me.detailID + "_plot", omicName, [entry], summaries, null, visual, headers)
			];
		} catch (error) {
			// A silent guard reads as a dead button, so say what happened.
			console.warn("[hub] could not draw " + id + ": " + error);
			host.innerHTML +=
				'<div class="contentbox paEmptyNote"><p>The expression figure for ' +
				Ext.String.htmlEncode(title) + ' could not be drawn.</p></div>';
		}
	};

	/* ------------------------------------------------------------------ *
	 * Rings and zoom                                                      *
	 * ------------------------------------------------------------------ */

	this.fitToVisible = function () {
		if (!this.cy) { return; }
		var lit = this.cy.elements().not(".dim");
		this.cy.fit(lit.length ? lit : this.cy.elements(), 40);
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
	};

	this.syncStepButtons = function () {
		if (!this.stepButtons) { return; }
		var me = this;
		this.stepButtons.forEach(function (button, index) {
			button.toggle(index + 1 === me.level, true);
		});
	};

	/* ------------------------------------------------------------------ *
	 * Component                                                           *
	 * ------------------------------------------------------------------ */

	this.getComponent = function () {
		var me = this;
		me.stepButtons = [1, 2, 3, 4].map(function (n) {
			return Ext.create("Ext.button.Button", {
				text: String(n), enableToggle: true,
				toggleGroup: "hubNetStep" + me.canvasID,
				pressed: (n === 1),
				handler: function () { me.setLevel(n); }
			});
		});
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
				'<p class="pa-hub-intro">Genes within <b>1 to 4 network steps</b> of ' +
				'each metabolite, and how much of the differential expression ' +
				'sits among them. Pick a metabolite on the left; click any node ' +
				'for its expression.</p>' +
				'<div id="' + me.summaryID + '"></div>' +
				'<div class="pa-hub-controls">' +
				  '<input type="search" id="' + me.searchID + '" class="pa-hub-search" ' +
				    'placeholder="Search metabolites…" aria-label="Search metabolites">' +
				  '<label class="pa-hub-sortlabel" for="' + me.sortID + '">Rank by</label>' +
				  '<select id="' + me.sortID + '" class="pa-hub-sort">' +
				    '<option value="padjust">FDR</option>' +
				    '<option value="density">% DE neighbours</option>' +
				    '<option value="den">DE neighbours</option>' +
				    '<option value="name">Name</option>' +
				  '</select>' +
				'</div>' +
				legend +
				'<div id="' + me.noticeID + '" class="pa-net-notice"></div>' +
				'<div class="more-net-body">' +
				  '<div class="more-net-sidepanel pa-hub-listrail" id="' + me.listID + '"></div>' +
				  '<div class="pa-hub-stage more-net-canvas">' +
				    '<svg id="' + me.ringsID + '" class="pa-hub-rings"></svg>' +
				    '<div id="' + me.canvasID + '" class="pa-net-canvas"></div>' +
				    '<div id="' + me.tipID + '" class="pa-hub-tip"></div>' +
				  '</div>' +
				'</div>' +
				'<div id="' + me.detailID + '" class="pa-hub-detail"></div>',
			bbar: [{ xtype: "tbtext", text: "Steps from the metabolite:" }]
				.concat(me.stepButtons),
			listeners: {
				// paDeferFrame, NOT requestAnimationFrame: rAF never runs in a
				// background tab and the panel came up permanently blank.
				afterrender: function () {
					paDeferFrame(function () {
						if (!me.hasData()) { return; }   // stays hidden
						me.component.show();
						me.renderList();
						me.renderSummary();
						me.bindControls();
						me.selectFirst();
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
		if (search) {
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
		if (sort) {
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
		var first = this.metabolites[0];
		this.showCompound(first.ID, first.bestStep);
	};

	/** Whether this job has anything for the panel to show. */
	this.hasData = function () {
		return this.metabolites.length > 0;
	};
}
PA_Step3HubNetworkView.prototype = new View();
