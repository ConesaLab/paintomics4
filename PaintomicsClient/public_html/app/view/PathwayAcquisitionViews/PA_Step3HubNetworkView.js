/**
 * PA_Step3HubNetworkView -- a metabolite's 1..4 step neighbourhood, drawn as
 * concentric hop rings.
 *
 * Why this exists. The KEGG interaction graph has always been on the server and
 * has never reached the browser: compoundRegulateFeatures ships node SETS with
 * no pairs, no direction, no edge types and no intermediate hops, so a client
 * could not tell whether a radius-3 gene reached the metabolite via gene X or
 * gene Y. The hub table reported numbers about a network nobody could see.
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
	// reuses component ids across job loads.
	var salt = Math.floor(Math.random() * 1e9);
	this.canvasID = "hubNetCanvas" + salt;
	this.ringsID = "hubNetRings" + salt;
	this.noticeID = "hubNetNotice" + salt;
	this.tipID = "hubNetTip" + salt;
	this.cy = null;
	this.level = 1;
	this.payload = null;

	this.loadModel = function (model) {
		this.model = model;
	};

	this.showCompound = function (compoundID, level) {
		var me = this;
		me.level = Math.max(1, Math.min(4, parseInt(level, 10) || 1));
		me.note("Loading the neighbourhood of " + compoundID + "…");
		if (me.component && me.component.isHidden && me.component.isHidden()) {
			me.component.show();
		}
		$.post(SERVER_URL_PA_HUB_SUBGRAPH, {
			jobID: me.model.getJobID(),
			compoundID: compoundID,
			level: 4,                 // fetch all four; the control dims, never refetches
			maxEdges: 400
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
		if (el) { el.textContent = text || ""; }
	};

	/** DE state for one feature, from the expression data the job already ships. */
	this.stateOf = function (id) {
		var data = this.model && this.model.globalExpressionData;
		var entry = data && ((data.inputGene && data.inputGene[id]) ||
		                     (data.inputCompound && data.inputCompound[id]));
		if (!entry) { return "absent"; }              // never measured
		if (!(entry.relevant || entry.relevantAssociation)) { return "quiet"; }
		var first = (entry.values && entry.values.length) ? Number(entry.values[0]) : 0;
		return (first < 0) ? "down" : "up";
	};

	this.elements = function (payload) {
		var me = this, out = [];
		var mapping = (me.model && me.model.mappingComp) || {};
		payload.nodes.forEach(function (n) {
			var state = (n.step === 0) ? "seed" : me.stateOf(n.id);
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
		// A cap must never read as "this is all there is".
		me.note(payload.truncated
			? ("Showing the 400 edges closest to " + payload.seed +
			   " — the full neighbourhood is larger.")
			: (payload.source === "legacy-json"
				? "This organism has no KGML on disk, so only direct neighbours " +
				  "are drawn and relation types are unavailable."
				: ""));

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
				// Ring 2 alone can hold a hundred nodes; at the zoom that fits
				// them, every label is unreadable and only adds noise. They come
				// back as soon as the user zooms in far enough to read them.
				{ selector: ".far node, node.far", style: { "label": "" }},
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
					"border-width": 3, "border-color": "#18181b" }}
			]
		});

		me.cy.one("layoutstop", function () {
			// fit() on afterrender runs before any data exists, so the graph came
			// up as a speck in the middle of an empty canvas. The layout is the
			// only moment the node positions are real.
			me.fitToVisible();
			me.drawRings();
		});
		me.cy.on("pan zoom resize", function () {
			me.applyLabelZoom();
			me.drawRings();
		});
		me.bindHover();
		me.setLevel(me.level);
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
			text.textContent = "step " + step;
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
				(step ? "<br>" + step + " step" + (step === 1 ? "" : "s") + " away" : "");
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

	/**
	 * Fit to what is actually lit.
	 *
	 * Fitting to every element keeps the dimmed outer rings in frame, and
	 * radius 4 is wide enough that step 1 becomes a few pixels across. The
	 * dimmed rings are still THERE -- the guide circles show where they run --
	 * but the viewport belongs to the ring the user asked for.
	 */
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
	};

	this.getComponent = function () {
		var me = this;
		var steps = [1, 2, 3, 4].map(function (n) {
			return { xtype: "button", text: String(n), enableToggle: true,
			         toggleGroup: "hubNetStep" + me.canvasID,
			         pressed: (n === 1),
			         handler: function () { me.setLevel(n); } };
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
			title: "Metabolite neighbourhood",
			cls: "pa-hub-net-toolbar pa-hub-net",
			hidden: true,
			collapsible: true,
			html: '<div id="' + me.noticeID + '" class="pa-net-notice"></div>' +
			      legend +
			      '<div class="pa-hub-stage">' +
			        '<svg id="' + me.ringsID + '" class="pa-hub-rings"></svg>' +
			        '<div id="' + me.canvasID + '" class="pa-net-canvas"></div>' +
			        '<div id="' + me.tipID + '" class="pa-hub-tip"></div>' +
			      '</div>',
			bbar: [{ xtype: "tbtext", text: "Steps from the metabolite:" }].concat(steps),
			listeners: {
				// paDeferFrame, NOT requestAnimationFrame: rAF never runs in a
				// background tab and the panel came up permanently blank.
				afterrender: function () {
					paDeferFrame(function () {
						if (me.cy) { me.cy.resize(); me.fitToVisible(); me.drawRings(); }
					});
				},
				expand: function () {
					if (me.cy) { me.cy.resize(); me.fitToVisible(); me.drawRings(); }
				},
				beforedestroy: function () {
					if (me.cy) { me.cy.destroy(); me.cy = null; }
				}
			}
		});
		return this.component;
	};
}
PA_Step3HubNetworkView.prototype = new View();
