//
// This file is part of Paintomics v4
//
// Paintomics is free software: you can redistribute it and/or modify it under
// the terms of the GNU General Public License as published by the Free
// Software Foundation, either version 3 of the License, or (at your option)
// any later version.
//
// Paintomics is distributed in the hope that it will be useful, but WITHOUT
// ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
// FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
// more details.
//
// You should have received a copy of the GNU General Public License along
// with Paintomics. If not, see <http://www.gnu.org/licenses/>.
//

/**
 * PA_Step4OmniPathNetworkView
 *
 * The pathway view for OmniPath, which is the one source Paintomics carries
 * that ships no diagram. The other three hand us an image and a coordinate per
 * gene; OmniPath hands us a signed, directed interaction network and nothing
 * to paint it on.
 *
 * Drawing that network as fixed lines over fixed boxes was tried first and is
 * not readable: a few hundred genes and a couple of thousand edges become a
 * smudge that no amount of layout tuning rescues, because the problem is that
 * a static picture of a dense graph carries no way to interrogate it. So the
 * pathway is rendered here as a real graph the user can move, zoom and
 * interrogate, with the neighbourhood of whatever they point at lifted out of
 * the rest.
 *
 * The nodes are NOT drawn from scratch. Each one uses the very same painted
 * glyph the raster pathway views place on their diagrams -- the data-URI
 * canvas that `PA_Step4KeggDiagramFeatureSetView.initComponent` returns, with
 * every visible omic already coloured into it. So a gene looks identical here
 * and on a KEGG map, and no colour-scale logic is duplicated.
 *
 * Cytoscape.js is already vendored and already loaded for the Step 3
 * regulator-target network; this view follows its conventions (a `cose`
 * layout, neighbourhood dimming, an edge budget that is stated rather than
 * silent).
 */
function PA_Step4OmniPathNetworkView() {

	/** Non-adjacent elements fade to this rather than disappearing: the
	 *  structure of interest has to stand out without losing its context. */
	var DIM_OPACITY = 0.12;

	/** A causal sign is what OmniPath knows and a diagram does not, so the
	 *  colours say it plainly and the budget below discards it last. */
	var EDGE_STYLE = {
		stimulation: {colour: "#2e7d4f", arrow: "triangle"},
		inhibition:  {colour: "#c0392b", arrow: "tee"},
		unsigned:    {colour: "#9aa6a2", arrow: "none"}
	};

	this.name = "PA_Step4OmniPathNetworkView";
	this.cy = null;
	this.container = null;

	/**
	 * Build the network into a panel body.
	 *
	 * @param {jQuery} bodyEl the `.lateralOptionsPanel-body` to render into
	 * @param {Object} options
	 *        organism   {String}  organism code, for the network request
	 *        pathwayID  {String}  pathway whose network to fetch
	 *        items      {Array}   PA_Step4KeggDiagramFeatureSetView instances
	 *        summaries  {Object}  dataDistributionSummaries
	 *        visual     {Object}  visualOptions
	 *        maxEdges   {Number}  edge budget
	 * @returns {PA_Step4OmniPathNetworkView}
	 */
	this.render = function(bodyEl, options) {
		var me = this;

		bodyEl.empty();
		bodyEl.append(
			'<div class="omnipath-net-toolbar">' +
			'  <span class="omnipath-net-legend">' +
			'    <i class="omnipath-key" style="background:' + EDGE_STYLE.stimulation.colour + '"></i>stimulation' +
			'    <i class="omnipath-key" style="background:' + EDGE_STYLE.inhibition.colour + '"></i>inhibition' +
			'    <i class="omnipath-key" style="background:' + EDGE_STYLE.unsigned.colour + '"></i>unsigned' +
			'  </span>' +
			'  <label class="omnipath-net-field">Layout' +
			'    <select class="omnipath-net-layout">' +
			'      <option value="rings" selected>Rings (by connectivity)</option>' +
			'      <option value="cascade">Cascade (follows direction)</option>' +
			'      <option value="clusters">Clusters (force-directed)</option>' +
			'    </select>' +
			'  </label>' +
			'  <label class="omnipath-net-field">' +
			'    <input type="checkbox" class="omnipath-net-signed"> Causal edges only' +
			'  </label>' +
			'  <span class="omnipath-net-status">Loading interaction network&hellip;</span>' +
			'</div>' +
			'<div class="omnipath-net-canvas"></div>');

		this.container = bodyEl.find(".omnipath-net-canvas")[0];
		var status = bodyEl.find(".omnipath-net-status");

		/* Cytoscape measures its container once, at construction. A container
		   sized by a percentage of a parent that is itself still being laid out
		   measures as zero and the graph is drawn into nothing, so the height is
		   resolved to pixels here. */
		var available = bodyEl.height() - bodyEl.find(".omnipath-net-toolbar").outerHeight();
		$(this.container).height(Math.max(420, available || 0));

		if (typeof cytoscape === "undefined") {
			status.text("Cytoscape.js is not loaded (js/libs/cytoscape/cytoscape.min.js).");
			return this;
		}

		/* One node per painted feature, carrying its own glyph. The glyph is
		   generated at the diagram's adjustFactor, which is meaningless in a
		   graph that does its own zooming, so it is regenerated at 1:1. */
		var unscaled = Ext.apply({}, options.visual);
		unscaled.adjustFactor = 1;

		this._itemsByID = {};
		this._summaries = options.summaries;
		this._visual = options.visual;

		var nodes = [], byID = {};
		for (var i in options.items) {
			var item = options.items[i];
			var graphical = null;
			try {
				graphical = item.getModel().getFeatures()[0].getFeatureGraphicalData();
			} catch (error) { continue; }
			if (!graphical) { continue; }

			var identifier = graphical.getID();
			if (!identifier || byID[identifier]) { continue; }

			var glyph = item.initComponent(options.summaries, unscaled);
			var label = "";
			try { label = item.getModel().getFeatures()[0].getFeature().getName() || ""; } catch (e) { label = ""; }

			byID[identifier] = true;
			this._itemsByID[identifier] = item;
			nodes.push({data: {
				id: identifier,
				label: label,
				image: glyph.src,
				w: Math.max(40, glyph.width || 92),
				h: Math.max(14, glyph.height || 22)
			}});
		}

		if (!nodes.length) {
			status.text("No matched features to draw for this pathway.");
			return this;
		}

		$.getJSON(SERVER_URL_GET_OMNIPATH_NETWORK + "/" + options.organism + "/" + options.pathwayID)
			.done(function(response) {
				if (!response || !response.success || !response.network) {
					status.text("The interaction network for this pathway is unavailable.");
					me._nodes = nodes; me._edges = []; me._budget = 0; me._status = status;
					me._render();
					return;
				}
				var all = (response.network.edges || []).filter(function(edge) {
					return byID[edge[0]] && byID[edge[1]];
				});
				/* Signed edges survive the budget first -- they are the whole
				   reason this source is worth drawing. */
				all.sort(function(left, right) {
					return (left[2] === "unsigned" ? 1 : 0) - (right[2] === "unsigned" ? 1 : 0);
				});
				me._nodes = nodes;
				me._edges = all;
				me._budget = options.maxEdges || 900;
				me._status = status;
				me._bindControls(bodyEl);
				me._render();
			})
			.fail(function(xhr) {
				status.text("Could not load the interaction network (" +
					(xhr && xhr.status ? xhr.status : "network error") + ").");
				me._nodes = nodes; me._edges = []; me._budget = 0; me._status = status;
				me._render();
			});

		return this;
	};

	/** @private Wire the toolbar controls to a re-render. */
	this._bindControls = function(bodyEl) {
		var me = this;
		bodyEl.find(".omnipath-net-layout").on("change", function() {
			$(this).data("touched", true);
			me._render();
		});
		bodyEl.find(".omnipath-net-signed").on("change", function() { me._render(); });
		this._controls = bodyEl;
	};

	/** @private The layout the user has chosen, or the one that suits the graph.
	 *
	 *  Size decides the default because the failure modes are opposite: a force
	 *  layout balls up once a pathway is dense, while concentric rings scatter a
	 *  small pathway around a circumference far larger than it needs. */
	this._chosenLayout = function() {
		var select = this._controls && this._controls.find(".omnipath-net-layout");
		if (select && select.length && select.data("touched")) { return select.val(); }

		var suggested = ((this._nodes || []).length > 45) ? "rings" : "clusters";
		if (select && select.length) { select.val(suggested); }
		return suggested;
	};

	this._signedOnly = function() {
		var box = this._controls && this._controls.find(".omnipath-net-signed");
		return !!(box && box.length && box.prop("checked"));
	};

	/**
	 * @private Build (or rebuild) the graph from the current controls.
	 *
	 * A dense signed network has no good *unstructured* first impression: at
	 * ~9 edges per gene a force layout settles into a ball whatever its
	 * constants, and that ball is what a user sees before touching anything. So
	 * the default here is not a force layout at all -- it is concentric rings
	 * ordered by connectivity, which cannot overlap, always fills the panel and
	 * puts the hubs of the pathway in the middle where they belong. The force
	 * layout stays available for reading clusters, and a directed cascade for
	 * reading the pathway the way a diagram draws it.
	 */
	this._render = function() {
		var me = this;
		var edges = this._edges || [];
		if (this._signedOnly()) {
			edges = edges.filter(function(edge) { return edge[2] !== "unsigned"; });
		}
		var total = edges.length;
		var budget = this._budget || 900;
		edges = edges.slice(0, budget);

		var elements = (this._nodes || []).concat(edges.map(function(edge, index) {
			return {data: {id: "e" + index, source: edge[0], target: edge[1]}, classes: edge[2]};
		}));

		if (this.cy) { this.cy.destroy(); }

		this.cy = cytoscape({
			container: this.container,
			elements: elements,
			minZoom: 0.1, maxZoom: 4,
			style: [
				{selector: "node", style: {
					"shape": "round-rectangle",
					"width": "data(w)", "height": "data(h)",
					"background-image": "data(image)",
					"background-fit": "cover",
					"background-color": "#ffffff",
					"border-width": 1, "border-color": "#98a2a8"
				}},
				/* Edges are context, nodes are the data: thin and faint so the
				   painted glyphs read first, and curved so reciprocal pairs do
				   not sit on top of each other. */
				{selector: "edge", style: {
					"width": 1, "curve-style": "bezier", "opacity": 0.45,
					"line-color": EDGE_STYLE.unsigned.colour,
					"target-arrow-color": EDGE_STYLE.unsigned.colour,
					"target-arrow-shape": "none", "arrow-scale": 0.7
				}},
				{selector: "edge.stimulation", style: {
					"line-color": EDGE_STYLE.stimulation.colour,
					"target-arrow-color": EDGE_STYLE.stimulation.colour,
					"target-arrow-shape": EDGE_STYLE.stimulation.arrow
				}},
				{selector: "edge.inhibition", style: {
					"line-color": EDGE_STYLE.inhibition.colour,
					"target-arrow-color": EDGE_STYLE.inhibition.colour,
					"target-arrow-shape": EDGE_STYLE.inhibition.arrow
				}},
				{selector: ".dimmed", style: {"opacity": DIM_OPACITY}},
				{selector: "edge.lit", style: {"opacity": 0.95, "width": 2}},
				{selector: "node.focus", style: {
					"border-width": 3, "border-color": "#1c6b57", "z-index": 20}}
			],
			layout: {name: "preset"}
		});

		this._runLayout();
		this._bindGraphEvents();

		var message = (this._nodes || []).length + " genes, " + edges.length + " interactions";
		if (total > edges.length) {
			/* Never let a cap read as "this is all there is". */
			message += " (strongest " + budget + " of " + total + ")";
		}
		message += " · click a gene for its values, hover to isolate";
		if (this._status) { this._status.text(message); }
	};

	/** @private Run the chosen layout and frame it once it has settled. */
	this._runLayout = function() {
		var me = this;
		var choice = this._chosenLayout();
		var options;

		if (choice === "cascade") {
			/* Signalling runs receptor -> kinase -> transcription factor, so the
			   nodes nothing points at make the natural top row. */
			var roots = this.cy.nodes().filter(function(node) {
				return node.indegree(false) === 0 && node.outdegree(false) > 0;
			});
			options = {
				name: "breadthfirst", directed: true, animate: false,
				spacingFactor: 1.9, padding: 40, avoidOverlap: true,
				nodeDimensionsIncludeLabels: true, fit: false
			};
			if (roots.length) { options.roots = roots; }
		} else if (choice === "clusters") {
			options = {
				name: "cose", animate: false, randomize: true,
				nodeRepulsion: 450000, nodeOverlap: 90,
				idealEdgeLength: 220, edgeElasticity: 20,
				gravity: 0.08, numIter: 1500, componentSpacing: 200,
				padding: 40, nodeDimensionsIncludeLabels: true, fit: false
			};
		} else {
			/* Rings. Degree decides the ring, so the pathway's hubs land in the
			   centre; the spacing is set from the glyph width, which is what
			   makes overlap impossible rather than merely unlikely. */
			options = {
				name: "concentric", animate: false, padding: 40,
				minNodeSpacing: 45, avoidOverlap: true, equidistant: false,
				nodeDimensionsIncludeLabels: true, fit: false,
				concentric: function(node) { return node.degree(false); },
				levelWidth: function(nodes) { return Math.max(1, nodes.maxDegree(false) / 3); }
			};
		}

		var layout = this.cy.layout(options);
		layout.one("layoutstop", function() {
			/* The panel is still settling when the graph is built, so the height
			   measured then is a floor, not the real one. Re-measure once the
			   browser has laid out, or the graph is framed for a box smaller than
			   the one it ends up in and is clipped at the top. */
			/* Measured from the panel, not from the body: the body is height:auto
			   and therefore reports exactly the height of the canvas inside it,
			   which makes any comparison against it a no-op. */
			var panel = $(me.container).closest(".lateralOptionsPanel");
			var toolbar = $(me.container).siblings(".omnipath-net-toolbar").outerHeight() || 0;
			var header = panel.find(".lateralOptionsPanel-header").outerHeight() || 0;
			var full = (panel.height() || 0) - header - toolbar - 8;
			if (full > $(me.container).height()) {
				$(me.container).height(full);
				me.cy.resize();
			}
			/* Frame the whole pathway. Clamping the zoom to keep glyphs large was
			   tried and is worse: it crops the outer ring on arrival, so the first
			   thing the user sees is a pathway with its edges cut off. */
			me.cy.fit(undefined, 24);
		});
		layout.run();
	};

	/** @private Hover isolates a neighbourhood; a click opens the feature. */
	this._bindGraphEvents = function() {
		var me = this;

		this.cy.on("mouseover", "node", function(event) {
			var hood = event.target.closedNeighborhood();
			me.cy.elements().difference(hood).addClass("dimmed");
			hood.edges().addClass("lit");
			event.target.addClass("focus");
		});
		this.cy.on("mouseout", "node", function() {
			me.cy.elements().removeClass("dimmed").removeClass("lit").removeClass("focus");
		});

		/* The same panel a click on a box opens on a KEGG diagram: the point of
		   painting omics onto these nodes is being able to read the values
		   behind the colour. */
		this.cy.on("tap", "node", function(event) {
			var item = me._itemsByID && me._itemsByID[event.target.id()];
			if (!item) {
				console.warn("OmniPath: no feature view for node " + event.target.id());
				return;
			}
			/* The hover tooltip is anchored to an SVG box that only exists on a
			   raster diagram, so out here its charts render into a zero-height
			   container and come up blank. The details panel is a real panel and
			   is what the tooltip's own "Show details" button opens anyway. */
			try {
				var step4 = item.getParent();
				if (step4 && typeof step4.showFeatureSetDetails === "function") {
					step4.showFeatureSetDetails(event.target.id(), item.getModel());
				} else {
					item.showTooltip(me._summaries, me._visual, true);
				}
			} catch (error) {
				console.warn("OmniPath: could not open the feature panel: " + error.message);
			}
		});
	};

	/** Release the layout worker and the canvas with the panel. */
	this.destroy = function() {
		if (this.cy) {
			this.cy.destroy();
			this.cy = null;
		}
		return this;
	};

	return this;
}
PA_Step4OmniPathNetworkView.prototype = new View();
