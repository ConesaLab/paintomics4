//
// PA_Step4EvidenceOverlay.js
//
// Draws MORE regulator -> target relationships as an evidence layer on top of
// a pathway diagram, and accounts out loud for everything it cannot draw.
//
// DESIGN CONSTRAINTS, ALL MEASURED
// --------------------------------
// The diagram underneath is a raster PNG. The application never parsed KGML
// <relation>/<reaction>, so it has no idea where KEGG's own arrows, boxes and
// labels sit -- there is no routing, no collision avoidance, and no way to ask
// whether an edge is already drawn. Three consequences shape everything here:
//
//   1. AN OVERLAY EDGE MUST NOT LOOK LIKE A PATHWAY EDGE. A dark straight line
//      between two box centres reads as curated KEGG biology. Every edge here
//      is therefore a consistently-bowed arc in a single alien hue (violet --
//      chosen because red and blue already encode coefficient sign in the MORE
//      network view, and red/gold/green are spent on the box corner glyphs).
//      Class is encoded by TEXTURE within that one hue, so the whole layer
//      reads as one foreign thing rather than three competing ones.
//
//   2. FEW EDGES, ALWAYS. The readable ceiling measured on real mouse maps is
//      5-8 edges: crossings per edge passes 1.0 between N=5 and N=10, and
//      bowing the edges changes that by under 8%. The server caps and ranks;
//      this view states what the cap hid rather than hiding it silently.
//
//   3. ENDPOINTS ARE OFTEN NOT GENES. Features bucket by the literal string
//      x + "#" + y, so co-located genes share one drawn box, and a box holding
//      more than five features is silently replaced by a PCA metagene. An
//      arrowhead cannot disambiguate a 46x17 px box holding six genes, so an
//      edge landing on a shared box gets a hollow BADGE terminal instead of an
//      arrowhead, and says so in its tooltip.
//
// Anchoring is at the box perimeter, never the centre, so an edge never
// disappears under the omics sprite it points at.
//
function PA_Step4EvidenceOverlay() {

	/** One hue, three textures. See constraint 1 above. */
	this.CLASS_STYLE = {
		corroborated: {stroke: "#5B1A8B", width: 2.4, dash: null,    opacity: 0.95},
		novel:        {stroke: "#8E44AD", width: 2.2, dash: "8,4",   opacity: 0.92},
		unsupported:  {stroke: "#B39DDB", width: 1.6, dash: "1.5,4", opacity: 0.8}
	};

	this.CLASS_LABEL = {
		corroborated: "Corroborated &mdash; literature reports this interaction",
		novel:        "Novel &mdash; both proteins known, no reported interaction",
		unsupported:  "Unsupported &mdash; no external evidence either way"
	};

	this.CLASS_ORDER = ["corroborated", "novel", "unsupported"];

	this.group = null;
	this.legendEl = null;
	this.payload = null;
	this.visible = true;

	/**
	* @param {Object} options
	*   canvas            {SVG.Doc}  the live svg.js canvas the diagram drew into
	*   panelEl           {jQuery}   the .lateralOptionsPanel-body to hang the legend on
	*   jobID             {String}
	*   pathwayID         {String}
	*   graphicalOptions  {PathwayGraphicalData}
	*   adjustFactor      {Number}   raster scale already applied to every box
	*   boxOccupancy      {Object}   "x#y" -> number of features sharing that box
	*   onReady           {Function} optional, called with the payload
	*/
	this.render = function(options) {
		var me = this;
		this.options = options;

		$.ajax({
			method: "POST",
			url: SERVER_URL_PA_PATHWAY_EVIDENCE,
			data: JSON.stringify({
				jobID: options.jobID,
				pathwayID: options.pathwayID,
				maxEdges: options.maxEdges || 8
			}),
			dataType: "json",
			contentType: "application/json",
			success: function(response) {
				if (!response || response.success !== true) {
					/* A job with no MORE analysis is the common case, not an
					   error: stay silent rather than showing an empty legend. */
					console.info("Evidence overlay: no evidence for " + options.pathwayID);
					return;
				}
				me.payload = response;
				try {
					me.draw();
				} catch (error) {
					console.error("Evidence overlay failed to draw", error);
				}
				if (options.onReady) { options.onReady(response); }
			},
			error: function() {
				console.warn("Evidence overlay: request failed for " + options.pathwayID);
			}
		});

		return this;
	};

	/**
	* Centre and half-extents of a feature's drawn box, in canvas coordinates.
	*
	* Mirrors PA_Step4KeggDiagramFeatureSetSVGBox exactly, including its
	* `|| 20` fallback: every MapMan feature is stored with width = height = 0
	* (the builder defaults the missing XML attribute), so without the fallback
	* every MapMan endpoint would collapse to a zero-size box at the origin.
	*/
	this.boxGeometry = function(featureID) {
		var graphical = this.options.graphicalOptions.findFeatureGraphicalData(featureID);
		if (!graphical || !graphical.length) { return null; }

		var data = graphical[0];
		var factor = this.options.adjustFactor;
		var width = (data.getBoxWidth() * factor) || 20;
		var height = (data.getBoxHeight() * factor) || 20;

		return {
			cx: data.getX() * factor,
			cy: data.getY() * factor,
			halfWidth: width / 2,
			halfHeight: height / 2,
			key: data.getX() + "#" + data.getY(),
			boxes: graphical.length
		};
	};

	/**
	* Where a ray leaving `box` toward (tx, ty) crosses the box perimeter.
	*
	* Anchoring at the centre would run the first and last few pixels of every
	* edge underneath the omics sprite, which is opaque -- the edge would appear
	* to stop short of the thing it points at.
	*/
	this.perimeterPoint = function(box, tx, ty, gap) {
		var dx = tx - box.cx, dy = ty - box.cy;
		if (dx === 0 && dy === 0) { return {x: box.cx, y: box.cy}; }

		var scaleX = dx === 0 ? Infinity : box.halfWidth / Math.abs(dx);
		var scaleY = dy === 0 ? Infinity : box.halfHeight / Math.abs(dy);
		var scale = Math.min(scaleX, scaleY);
		var length = Math.sqrt(dx * dx + dy * dy);
		var extra = (gap || 0) / length;

		return {x: box.cx + dx * (scale + extra), y: box.cy + dy * (scale + extra)};
	};

	/**
	* Quadratic control point, bowed consistently to one side of the chord.
	*
	* Consistency is the whole point: a systematically curved layer cannot be
	* confused with the straight printed connectors on the map underneath. The
	* bow is proportional to the chord so short edges stay legible and long ones
	* do not balloon.
	*/
	this.controlPoint = function(from, to) {
		var dx = to.x - from.x, dy = to.y - from.y;
		var length = Math.sqrt(dx * dx + dy * dy) || 1;
		var bow = Math.max(14, Math.min(length * 0.16, 70));

		return {
			x: (from.x + to.x) / 2 - (dy / length) * bow,
			y: (from.y + to.y) / 2 + (dx / length) * bow
		};
	};

	/**
	* Create an SVG element directly, bypassing svg.js.
	*
	* svg.js 2.0.5 parses a path's `d` by assigning it to a scratch <path> and
	* reading `.pathSegList`, an API Chrome REMOVED in version 48. Every call to
	* its .path() therefore dies with
	*     TypeError: Cannot read properties of undefined (reading 'numberOfItems')
	* in any current browser -- which is almost certainly why this application
	* has never drawn a single vector primitive on a pathway diagram. The rest
	* of svg.js (images, groups, viewbox, pan/zoom) is untouched by this and
	* keeps working; only geometry has to be built by hand.
	*/
	this.svgEl = function(tag, attributes) {
		var element = document.createElementNS("http://www.w3.org/2000/svg", tag);
		for (var name in attributes) {
			if (attributes[name] !== null && attributes[name] !== undefined) {
				element.setAttribute(name, attributes[name]);
			}
		}
		return element;
	};

	this.append = function(tag, attributes) {
		var element = this.svgEl(tag, attributes);
		this.group.appendChild(element);
		return element;
	};

	/** Arrowhead / badge polygon at the target end, oriented along the tangent. */
	this.terminal = function(to, control, style, shared) {
		var dx = to.x - control.x, dy = to.y - control.y;
		var length = Math.sqrt(dx * dx + dy * dy) || 1;
		var ux = dx / length, uy = dy / length;
		var size = shared ? 5 : 7;
		var baseX = to.x - ux * size, baseY = to.y - uy * size;
		var normalX = -uy * size * 0.55, normalY = ux * size * 0.55;

		if (shared) {
			/* The box holds several genes (or is a PCA metagene), so this edge
			   cannot honestly claim WHICH one it acts on. A hollow square says
			   "somewhere in this box" where an arrowhead would over-claim. */
			var half = size * 0.85;
			return this.append("rect", {
				x: to.x - half, y: to.y - half,
				width: half * 2, height: half * 2,
				fill: "none", stroke: style.stroke, "stroke-width": 1.6,
				opacity: style.opacity
			});
		}

		return this.append("polygon", {
			points: [to.x + "," + to.y,
					 (baseX + normalX) + "," + (baseY + normalY),
					 (baseX - normalX) + "," + (baseY - normalY)].join(" "),
			fill: style.stroke,
			opacity: style.opacity
		});
	};

	this.tooltip = function(element, text) {
		var title = document.createElementNS("http://www.w3.org/2000/svg", "title");
		title.textContent = text;
		element.appendChild(title);
	};

	this.edgeTooltip = function(edge, shared) {
		var lines = [
			edge.regulatorLabel + "  →  " + edge.targetLabel,
			this.CLASS_LABEL[edge.evidenceClass].replace(/&mdash;/g, "—"),
			"coefficient " + (edge.coefficient > 0 ? "+" : "") +
				Number(edge.coefficient).toFixed(4) + "  (" + edge.condition + ")",
			"omic: " + (edge.omic || "—")
		];

		if (edge.targetR2 !== null && edge.targetR2 !== undefined) {
			/* R2 is merged into MORE's table BY TARGET, so every relationship of
			   one target carries the same value. Labelling it as the edge's fit
			   would be wrong. */
			lines.push("R² " + Number(edge.targetR2).toFixed(3) +
				"  (fit of the target's whole model, not of this link)");
		}

		if (edge.references && edge.references.length) {
			lines.push("cited by: " + edge.references.slice(0, 4).map(function(reference) {
				return (reference.resource ? reference.resource + " " : "") +
					(reference.pmid ? "PMID:" + reference.pmid : "");
			}).join(", "));
		} else if (edge.evidenceClass === "corroborated") {
			lines.push("literature records this interaction; reinstall OmniPath " +
				"to carry its PMIDs");
		}

		if (shared) {
			lines.push("⚠ the target box holds several genes — this link " +
				"cannot say which one");
		}
		if (edge.regulatorBoxes > 1 || edge.targetBoxes > 1) {
			lines.push("⚠ an endpoint is drawn at several places on this map; " +
				"one was chosen");
		}

		return lines.join("\n");
	};

	this.draw = function() {
		var me = this;
		var edges = (this.payload && this.payload.edges) || [];

		this.clear();
		/* Appended last, so the layer paints ABOVE the omics sprites. SVG has no
		   z-index; document order IS the stacking order. */
		this.group = this.svgEl("g", {"class": "evidenceOverlay"});
		this.options.canvas.node.appendChild(this.group);

		var drawn = 0, badged = 0;
		edges.forEach(function(edge) {
			var fromBox = me.boxGeometry(edge.regulatorID);
			var toBox = me.boxGeometry(edge.targetID);
			if (!fromBox || !toBox) { return; }

			var from = me.perimeterPoint(fromBox, toBox.cx, toBox.cy, 2);
			var to = me.perimeterPoint(toBox, fromBox.cx, fromBox.cy, 4);
			var control = me.controlPoint(from, to);
			var style = me.CLASS_STYLE[edge.evidenceClass] || me.CLASS_STYLE.unsupported;

			var occupancy = (me.options.boxOccupancy || {})[toBox.key] || 1;
			var shared = occupancy > 1;

			/* A white casing drawn UNDER the arc keeps it legible where it
			   crosses the map's own printed lines and labels -- which the
			   application cannot see, so it cannot route around them. Thin
			   enough to read as a halo rather than as an erasure. */
			me.append("path", {
				d: "M" + from.x + "," + from.y +
				   " Q" + control.x + "," + control.y + " " + to.x + "," + to.y,
				fill: "none", stroke: "#ffffff",
				"stroke-width": style.width + 2.4,
				"stroke-linecap": "round", opacity: 0.65
			});

			var path = me.append("path", {
				d: "M" + from.x + "," + from.y +
				   " Q" + control.x + "," + control.y + " " + to.x + "," + to.y,
				fill: "none", stroke: style.stroke,
				"stroke-width": style.width,
				"stroke-linecap": "round",
				"stroke-dasharray": style.dash,
				opacity: style.opacity
			});

			var head = me.terminal(to, control, style, shared);
			var tip = me.edgeTooltip(edge, shared);
			me.tooltip(path, tip);
			me.tooltip(head, tip);
			drawn++;
			if (shared) { badged++; }
		});

		this.renderLegend(drawn, badged);
	};

	this.renderLegend = function(drawn, badged) {
		var statistics = (this.payload && this.payload.statistics) || {};
		var byClass = statistics.byClass || {};
		var me = this;

		if (this.legendEl) { this.legendEl.remove(); }
		if (!statistics.totalRelationships) { return; }

		var rows = this.CLASS_ORDER.map(function(name) {
			var style = me.CLASS_STYLE[name];
			var dash = style.dash ? ' stroke-dasharray="' + style.dash + '"' : "";
			return '<li>' +
				'<svg width="34" height="10" aria-hidden="true">' +
				'  <path d="M2,8 Q17,0 32,6" fill="none" stroke="' + style.stroke +
				'" stroke-width="' + style.width + '"' + dash + ' stroke-linecap="round"/>' +
				'</svg>' +
				'<span class="evidenceLegend-name">' + me.CLASS_LABEL[name] + '</span>' +
				'<span class="evidenceLegend-count">' + (byClass[name] || 0) + '</span>' +
				'</li>';
		}).join("");

		/* Everything the layer could NOT draw, stated on screen. A silently
		   truncated overlay reads as "this is all there is". */
		var omissions = [];
		if (statistics.hidden) {
			omissions.push(statistics.hidden + " more on this map are hidden by the " +
				drawn + "-edge readability cap");
		}
		if (statistics.offMapRegulators) {
			omissions.push(statistics.offMapRegulators.toLocaleString() +
				" relationships have a regulator with no box on this map");
		}
		if (badged) {
			/* Counted from what was actually DRAWN, not from the server's
			   multiBoxEndpoints -- that statistic counts a gene appearing in
			   several boxes, which is the opposite situation and would put a
			   number here that does not match the hollow terminals on screen. */
			omissions.push(badged + (badged === 1
				? " edge ends on a box holding several genes"
				: " edges end on a box holding several genes") +
				" and cannot say which one (hollow terminal)");
		}
		if (statistics.multiBoxEndpoints) {
			omissions.push(statistics.multiBoxEndpoints +
				" had an endpoint drawn at several places on this map; one was chosen");
		}

		var html =
			/* No data-guides="ignore" here on purpose. The card sits in flow at
			   the panel body's own content edge -- measured identical to the
			   panel <h2>'s rail -- so it can be CHECKED by the alignment guides
			   rather than exempted from them, and a future regression will show
			   up in the HUD instead of hiding behind the opt-out. */
			'<div class="evidenceLegend">' +
			'  <div class="evidenceLegend-header">' +
			'    <span class="evidenceLegend-title">Evidence overlay</span>' +
			'    <a href="javascript:void(0)" class="evidenceLegend-toggle" ' +
			'       title="Show or hide the evidence overlay">hide</a>' +
			'  </div>' +
			'  <ul class="evidenceLegend-list">' + rows + '</ul>' +
			(omissions.length
				? '<p class="evidenceLegend-note">' + omissions.join("<br>") + '</p>'
				: "") +
			'  <p class="evidenceLegend-source">from this job\'s MORE analysis, ' +
			'classified against OmniPath</p>' +
			'</div>';

		this.legendEl = $(html);
		this.options.panelEl.append(this.legendEl);
		this.legendEl.find(".evidenceLegend-toggle").click(function() {
			me.setVisible(!me.visible);
			$(this).text(me.visible ? "hide" : "show");
		});
	};

	this.setVisible = function(visible) {
		this.visible = visible;
		if (this.group) {
			this.group.style.display = visible ? "" : "none";
		}
		return this;
	};

	this.clear = function() {
		if (this.group) {
			try {
				if (this.group.parentNode) {
					this.group.parentNode.removeChild(this.group);
				}
			} catch (error) { /* canvas already gone */ }
			this.group = null;
		}
	};

	this.destroy = function() {
		this.clear();
		if (this.legendEl) { this.legendEl.remove(); this.legendEl = null; }
		this.payload = null;
	};

	return this;
}
