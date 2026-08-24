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
//      more than five features is silently replaced by a PCA metagene. A solid
//      arrowhead cannot disambiguate a 46x17 px box holding six genes, so an
//      edge landing on a shared box is drawn HOLLOW -- same shape, empty
//      middle -- and says so in its tooltip. Shape carries the direction of
//      the effect, fill carries whether the endpoint is one gene.
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

	/**
	* Two of these three are the same answer for different reasons.
	*
	* Corroborated is one thing; novel and unsupported are both "no database
	* records this interaction", differing only in whether the databases were
	* in a position to record one. Listing them as three peers made the third
	* read as evidence AGAINST the relationship, which it never is -- it means
	* one partner has no curated interactions at all, so the silence says
	* nothing. They are therefore grouped under one heading with the reason
	* spelled out, and "unsupported" is not used as a user-facing word.
	*
	* The classification itself is unchanged: three classes, three line styles,
	* three counts.
	*/
	this.CLASS_LABEL = {
		corroborated: "Corroborated &mdash; a curated database records this interaction",
		novel:        "Novel &mdash; both partners are curated, nothing links them",
		unsupported:  "No coverage &mdash; a partner has no curated interactions"
	};

	//: The three classes as the legend groups them: what the databases record,
	//: and what they do not.
	this.CLASS_GROUPS = [
		{title: null, members: ["corroborated"]},
		{title: "Not recorded", members: ["novel", "unsupported"]}
	];

	this.CLASS_ORDER = ["corroborated", "novel", "unsupported"];

	/**
	* How close a regulator's OWN box has to be to its target before parking a
	* copy of it beside that target stops making sense.
	*
	* The satellite branch is only reachable for a regulator that HAS geometry
	* on this map, so every satellite is by construction a second drawing of a
	* box KEGG already placed. That is defensible when the original is half a
	* map away and indefensible when it is touching. Measured on mmu05167, the
	* three that read as absurd sit at 0, 6.0 and 26.0 raster px -- Fos and Jun
	* SHARE one drawn box, and Jun is drawn directly above Ccnd1 -- while the
	* five where a copy earns its place start at 289 px.
	*
	* 70 px is about one and a half KEGG gene boxes (46 x 17). It is a RASTER
	* distance on purpose: a canvas-unit threshold means a different thing at
	* every panel width, which is exactly the trap the arc layer's bow constant
	* fell into.
	*/
	this.NEAR_RADIUS = 70;

	/**
	* Size of a box this layer ADDS for a regulator the map does not print.
	*
	* Modelled on the target's own rectangle rather than a hard constant, so the
	* added box matches the map it lands on -- KEGG draws genes at 46x17 raster
	* px, Reactome and OmniPath do not. 0.85 is the same shrink a copied box
	* gets: an added box must never be pixel-identical to a printed one, or it
	* claims an annotation KEGG never made.
	*/
	this.ADDED_BOX_WIDTH = 46;
	this.ADDED_BOX_HEIGHT = 17;
	this.ADDED_BOX_SCALE = 0.85;

	/**
	* Every stroke width and mark size in this file is a RASTER px figure and
	* has to pass through here.
	*
	* The overlay draws in canvas units, which are raster px times the panel's
	* adjustFactor -- 0.607 on a full-width panel, and smaller as the panel
	* narrows. A constant written straight into an attribute is therefore a
	* different physical size on every layout. Measured before this existed: a
	* KEGG gene box came out 23.7 x 8.8 canvas units while a `size = 7`
	* arrowhead came out 11.9 wide, so the mark was half the width of the box
	* it pointed at, and a cluster of them covered the boxes underneath in
	* violet -- which reads as the boxes having changed colour.
	*
	* Same rule as the satellite offsets, for the same reason: raster px are
	* the only unit on this diagram that means one thing everywhere.
	*/
	this.ink = function(rasterPx) {
		return rasterPx * (this.options.adjustFactor || 1);
	};

	/** A dash pattern in raster px, scaled like every other stroke. */
	this.inkDash = function(dash) {
		if (!dash) { return dash; }
		var me = this;
		return String(dash).split(",").map(function(part) {
			return me.ink(parseFloat(part));
		}).join(",");
	};

	/**
	* Does MORE's fitted coefficient say this regulator pushes the target DOWN?
	*
	* This is the model's own sign, for the condition the payload selected --
	* NOT a claim that the curated databases agree. Sign concordance between
	* MORE and KEGG/Reactome/OmniPath measured 58.3% against 52.8% by chance,
	* so the terminal is driven by the coefficient and the line style by the
	* evidence class, and the two must never be crossed.
	*/
	this.isRepression = function(edge) {
		return typeof edge.coefficient === "number" && edge.coefficient < 0;
	};

	this.group = null;
	this.legendEl = null;
	this.payload = null;
	this.visible = true;
	/** edgeKey -> {dx, dy}, RASTER px, from the user dragging a satellite. */
	this.placement = {};
	/** Live satellite handles, so a drag moves one without a full redraw. */
	this.satellites = [];

	/**
	* @param {Object} options
	*   canvas            {SVG.Doc}  the live svg.js canvas the diagram drew into
	*   panelEl           {jQuery|Function} where to hang the control card, or a
	*                                function returning it. A function because the
	*                                card belongs in the Pathway information
	*                                column, which is BUILT AFTER the diagram
	*                                panel this overlay is created from
	*   jobID             {String}
	*   pathwayID         {String}
	*   graphicalOptions  {PathwayGraphicalData}
	*   adjustFactor      {Number}   raster scale already applied to every box
	*   boxOccupancy      {Object}   "x#y" -> number of features sharing that box
	*   placement         {Object}   edgeKey -> {dx, dy} in raster px, restored
	*                                from visualOptions so a nudge survives a
	*                                reopen and lands in the PNG/SVG export
	*   onPlacementChange {Function} optional, called with the placement map
	*                                after the user finishes a drag
	*   onReady           {Function} optional, called with the payload
	*/
	this.render = function(options) {
		var me = this;
		this.options = options;
		this.placement = options.placement || {};

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

	/**
	* Mark at the target end, oriented along the tangent.
	*
	* Two independent things to say, so two independent channels:
	*
	*   SHAPE  triangle = MORE fitted a positive coefficient, bar = negative.
	*   FILL   solid = the target box holds one gene, hollow = it holds several
	*          and the edge cannot say which of them is acted on.
	*
	* The hollow square this used to draw for a shared box collapsed both into
	* one mark and threw the direction away -- and 68.7% of drawn KEGG features
	* share their box, so on a map like mmu04330 every single terminal was a
	* square and the sign was never visible anywhere. A bar needs no hollow
	* variant: it lies ACROSS the arrival instead of pointing into it, so it
	* never singles a gene out in the first place.
	*/
	this.terminal = function(to, control, style, shared, repress) {
		var dx = to.x - control.x, dy = to.y - control.y;
		var length = Math.sqrt(dx * dx + dy * dy) || 1;
		var ux = dx / length, uy = dy / length;
		/* 6 raster px: KEGG draws its own arrowheads at about that. */
		var size = this.ink(6);
		var baseX = to.x - ux * size, baseY = to.y - uy * size;
		var normalX = -uy * size * 0.55, normalY = ux * size * 0.55;

		if (repress) {
			/* A bar across the tangent, the convention every pathway figure
			   uses for inhibition. Drawn at the endpoint rather than set back
			   from it: an arrowhead has a body to occupy the gap, a bar does
			   not, and a bar floating short of the box reads as a stray tick. */
			var barHalf = size * 0.85;
			return this.append("line", {
				x1: to.x - uy * barHalf, y1: to.y + ux * barHalf,
				x2: to.x + uy * barHalf, y2: to.y - ux * barHalf,
				stroke: style.stroke, "stroke-width": this.ink(2.2),
				"stroke-linecap": "round", opacity: style.opacity
			});
		}

		/* Hollow when the box holds several genes: the head still says which way
		   the effect runs, the empty middle says "one of the genes in here". */
		return this.append("polygon", {
			points: [to.x + "," + to.y,
					 (baseX + normalX) + "," + (baseY + normalY),
					 (baseX - normalX) + "," + (baseY - normalY)].join(" "),
			fill: shared ? "#ffffff" : style.stroke,
			stroke: shared ? style.stroke : "none",
			"stroke-width": shared ? this.ink(1.4) : 0,
			opacity: style.opacity
		});
	};

	/**
	* The same three marks as terminal(), painted onto an element that already
	* exists.
	*
	* A satellite's stub is redrawn on every drag, so its mark cannot be a node
	* appended once at draw time -- it has to be re-aimed with the line. One
	* <path> covers all three shapes, so the element survives a drag and only
	* its geometry and paint change.
	*/
	this.aimMark = function(element, to, from, style, shared, repress) {
		var dx = to.x - from.x, dy = to.y - from.y;
		var length = Math.sqrt(dx * dx + dy * dy) || 1;
		var ux = dx / length, uy = dy / length;
		var size = this.ink(6);

		if (repress) {
			var barHalf = size * 0.85;
			element.setAttribute("d",
				"M" + (to.x - uy * barHalf) + "," + (to.y + ux * barHalf) +
				"L" + (to.x + uy * barHalf) + "," + (to.y - ux * barHalf));
			element.setAttribute("fill", "none");
			element.setAttribute("stroke", style.stroke);
			element.setAttribute("stroke-width", this.ink(2.2));
		} else {
			var bx = to.x - ux * size, by = to.y - uy * size;
			var nx = -uy * size * 0.55, ny = ux * size * 0.55;
			element.setAttribute("d",
				"M" + to.x + "," + to.y +
				"L" + (bx + nx) + "," + (by + ny) +
				"L" + (bx - nx) + "," + (by - ny) + "Z");
			element.setAttribute("fill", shared ? "#ffffff" : style.stroke);
			element.setAttribute("stroke", shared ? style.stroke : "none");
			element.setAttribute("stroke-width", shared ? this.ink(1.4) : 0);
		}
		element.setAttribute("opacity", style.opacity);
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

		/* WHICH database, and WHERE. A relationship is routinely curated in a
		   pathway OTHER than the one on screen -- measured on mmu05167, 32 of
		   the 37 corroborated relationships are recorded on a different map --
		   and saying only "corroborated" would keep the fact and lose the
		   address the reader needs to go and check it. */
		(edge.evidenceSources || []).forEach(function(evidence) {
			var line = evidence.source;
			if (evidence.detail) { line += " (" + evidence.detail + ")"; }

			if (evidence.pathways && evidence.pathways.length) {
				line += " — recorded in " + evidence.pathways.map(function(pathway) {
					return pathway.name || pathway.id;
				}).join(", ");
				if (evidence.morePathways) {
					line += " and " + evidence.morePathways + " more";
				}
			} else if (evidence.onThisPathway) {
				line += " — drawn on this map";
			}

			if (evidence.references && evidence.references.length) {
				line += " — " + evidence.references.slice(0, 3).map(function(reference) {
					return (reference.resource ? reference.resource + " " : "") +
						(reference.pmid ? "PMID:" + reference.pmid : "");
				}).join(", ");
			} else if (evidence.source === "OmniPath") {
				/* The installed mmu OmniPath data predates the field, so the
				   edge is real but its PMIDs are not stored yet. Say which,
				   rather than letting a bare source name imply a citation. */
				line += " — no PMIDs stored; reinstall OmniPath to carry them";
			}

			lines.push(line);
		});

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

	/* ---------------------------------------------------------------------
	   SATELLITE PLACEMENT

	   All placement arithmetic happens in RASTER pixels -- the coordinate
	   space the pathway data is stored in -- and is multiplied by
	   adjustFactor only at draw time. Working in canvas units instead is what
	   made the arc layer sweep the map: its bow constant of 14 canvas units
	   is 68 raster px at the adjustFactor of 0.204 this panel actually uses,
	   so the geometry silently changed meaning with panel width.
	   --------------------------------------------------------------------- */

	/**
	* Raster-space box for a feature: centre plus half extents.
	*
	* @param {Object} near optional; when a feature is drawn at SEVERAL places
	*        on the map, return the box closest to this one. Taking [0] instead
	*        makes the near/far decision below depend on KGML entry order: Jun
	*        has three boxes on mmu05167 and only one of them is the 6 px
	*        neighbour of Ccnd1 that the reader is looking at.
	*/
	this.rasterBox = function(featureID, near) {
		var graphical = this.options.graphicalOptions.findFeatureGraphicalData(featureID);
		if (!graphical || !graphical.length) { return null; }

		var data = graphical[0];
		if (near && graphical.length > 1) {
			var best = Infinity;
			for (var i = 0; i < graphical.length; i++) {
				var dx = graphical[i].getX() - near.cx;
				var dy = graphical[i].getY() - near.cy;
				var distance = dx * dx + dy * dy;
				if (distance < best) { best = distance; data = graphical[i]; }
			}
		}

		return {
			cx: data.getX(),
			cy: data.getY(),
			width: data.getBoxWidth() || 20,
			height: data.getBoxHeight() || 20,
			key: data.getX() + "#" + data.getY(),
			boxes: graphical.length
		};
	};

	/**
	* Shortest raster distance between the EDGES of two boxes, 0 when they touch
	* or overlap. Centre-to-centre would call a wide box far from something
	* resting against its side.
	*/
	this.boxGap = function(a, b) {
		var dx = Math.max(0, Math.abs(a.cx - b.cx) - (a.width + b.width) / 2);
		var dy = Math.max(0, Math.abs(a.cy - b.cy) - (a.height + b.height) / 2);
		return Math.sqrt(dx * dx + dy * dy);
	};

	/** Stable identity for one drawn edge, so a dragged position can be found again. */
	this.edgeKey = function(edge) {
		return edge.regulatorID + ">" + edge.targetID;
	};

	/**
	* Everything already drawn on the canvas, as raster rectangles.
	*
	* Two sources, both of which the client already has or is now sent:
	* every painted feature box, and the cross-pathway rounded boxes
	* (relatedPathways) -- the largest printed obstacles on a KEGG map, 21 of
	* them on mmu05200, which the client had never been given.
	*
	* This set knows about 9.1% of the mmu05200 canvas while the map prints
	* ink on 9.2%, so it is blind to roughly as much drawn material as it can
	* see. Placement is therefore optimistic BY CONSTRUCTION: measured, about
	* two satellites in three clip some printed artwork, median overlap
	* 1.2-5.5%. That is a corner nick, against a 617 px chord dragging a
	* 23 px-wide swath across the whole diagram -- 14-80x less occlusion
	* overall. The honest fix if it ever bites is to threshold the served PNG
	* into an ink mask and use it to RANK slots; measured, that doubles the
	* share of satellites on clean paper and changes placement success by zero.
	*/
	this.buildOccupancy = function() {
		var rects = [];
		var items = this.options.items || [];

		for (var i in items) {
			try {
				var graphical = items[i].getModel().getFeatures()[0].getFeatureGraphicalData();
				if (!graphical) { continue; }
				var w = graphical.getBoxWidth() || 20, h = graphical.getBoxHeight() || 20;
				rects.push({
					left: graphical.getX() - w / 2, top: graphical.getY() - h / 2,
					right: graphical.getX() + w / 2, bottom: graphical.getY() + h / 2
				});
			} catch (error) { /* a set with no graphical data draws nothing */ }
		}

		((this.payload && this.payload.obstacles) || []).forEach(function(box) {
			rects.push({
				left: box.x - box.width / 2, top: box.y - box.height / 2,
				right: box.x + box.width / 2, bottom: box.y + box.height / 2
			});
		});

		return rects;
	};

	this.overlaps = function(candidate, rects) {
		for (var i = 0; i < rects.length; i++) {
			var r = rects[i];
			if (candidate.left < r.right && candidate.right > r.left &&
				candidate.top < r.bottom && candidate.bottom > r.top) {
				return true;
			}
		}
		return false;
	};

	/**
	* Find a free slot beside `target` for a satellite of satW x satH.
	*
	* South is tried before north because generateBox bakes the feature's
	* title along the TOP of its sprite, so a satellite sitting below a box
	* never lands under its own target's label.
	*
	* Returns {cx, cy, ring} in raster coordinates, or null.
	*/
	this.findSlot = function(target, satW, satH, gap, rects, imageWidth, imageHeight) {
		var best = null;

		for (var ring = 1; ring <= 3; ring++) {
			var offset = gap + (ring - 1) * (satH + gap);
			var south = target.cy + target.height / 2 + offset + satH / 2;
			var north = target.cy - target.height / 2 - offset - satH / 2;
			var east = target.cx + target.width / 2 + gap + (ring - 1) * (satW + gap) + satW / 2;
			var west = target.cx - target.width / 2 - gap - (ring - 1) * (satW + gap) - satW / 2;
			var shift = satW * 0.6;

			var candidates = [
				{cx: target.cx, cy: south},              // S-centre
				{cx: target.cx, cy: north},              // N-centre
				{cx: east, cy: target.cy},               // E
				{cx: west, cy: target.cy},               // W
				{cx: target.cx + shift, cy: south},      // S-right
				{cx: target.cx - shift, cy: south},      // S-left
				{cx: target.cx + shift, cy: north},      // N-right
				{cx: target.cx - shift, cy: north}       // N-left
			];

			for (var i = 0; i < candidates.length; i++) {
				var slot = {
					left: candidates[i].cx - satW / 2, right: candidates[i].cx + satW / 2,
					top: candidates[i].cy - satH / 2, bottom: candidates[i].cy + satH / 2
				};

				/* Hard rejects. Never "least-bad" an overlap with a feature
				   box: the overlay group is appended after every feature
				   <image>, so an opaque satellite over a real box would eat
				   that box's hover and click. */
				if (slot.left < 0 || slot.top < 0 ||
					slot.right > imageWidth || slot.bottom > imageHeight) { continue; }
				if (this.overlaps(slot, rects)) { continue; }

				var score = 3.0 * (ring - 1) + (i / 8);
				if (best === null || score < best.score) {
					best = {cx: candidates[i].cx, cy: candidates[i].cy, ring: ring, score: score};
				}
			}

			/* Ring 1 preference is strong enough that a hit there can never be
			   beaten by an outer ring; stop as soon as one is found. */
			if (best !== null) { return best; }
		}

		return best;
	};

	/**
	* The regulator's own measured values, collapsed the way a printed box
	* collapses them.
	*
	* A box the layer adds has no feature behind it on this map, so it cannot
	* go through generateBox. It can still be painted with exactly the same
	* numbers and the same scale: the server sends the regulator's values (its
	* own expression -- a regulatory omic stores TARGET:::REGULATOR rows and
	* every row of one regulator carries that regulator's profile), and
	* getMinMax/getColor are the globals the real boxes use. Painting it any
	* other way would put two colour languages on one diagram.
	*
	* @returns {Array} one colour per condition, or [] when nothing is known.
	*/
	this.regulatorColours = function(edge) {
		var stored = edge.regulatorValues;
		if (!stored) { return []; }

		var jobView = this.options.jobView;
		var mode = (jobView && jobView.getModel && jobView.getModel().getReplicateMode)
			? jobView.getModel().getReplicateMode() : "replicates";
		var values = (mode === "samples" && stored.sampleValues && stored.sampleValues.length)
			? stored.sampleValues : stored.values;
		if (!values || !values.length) { return []; }

		var omicName = stored.omicName;
		var summaries = this.options.summaries || {};
		var visual = this.options.visualOptions || {};
		if (typeof getMinMax !== "function" || typeof getColor !== "function"
				|| !summaries[omicName]) { return []; }

		var limits = getMinMax(summaries[omicName],
			(visual.colorReferences || {})[omicName]);
		return values.map(function(value) {
			return getColor(limits, value, visual.colorScale);
		});
	};

	/** Regenerate the regulator's own glyph so its gene symbol comes baked in. */
	this.satelliteGlyph = function(featureID, satW) {
		var item = (this.options.itemsByID || {})[featureID];
		if (!item) { return null; }
		try {
			/* Rendered at a factor that yields a wide source raster: generateBox
			   only paints the title when the box exceeds 80px, so a sprite made
			   at the diagram's own adjustFactor would come back unlabelled. The
			   result is downsampled into the slot, which keeps the text sharp. */
			var visual = Ext.apply({}, this.options.visualOptions);
			visual.adjustFactor = 10;
			var glyph = item.initComponent(this.options.summaries, visual);
			return (glyph && glyph.src) ? glyph : null;
		} catch (error) {
			return null;
		}
	};

	this.draw = function() {
		var me = this;
		var edges = (this.payload && this.payload.edges) || [];

		this.clear();
		/* Appended last, so the layer paints ABOVE the omics sprites. SVG has no
		   z-index; document order IS the stacking order. */
		this.group = this.svgEl("g", {"class": "evidenceOverlay"});
		this.options.canvas.node.appendChild(this.group);

		var factor = this.options.adjustFactor;
		var imageWidth = this.options.graphicalOptions.getImageWidth();
		var imageHeight = this.options.graphicalOptions.getImageHeight();
		/* Named occupancyRects, NOT occupancy: the arc fallback further down
		   declares `var occupancy` inside the same forEach callback, and var is
		   function-scoped, so that declaration hoists over this one for the whole
		   callback and the placer received undefined. */
		var occupancyRects = this.buildOccupancy();
		var perTarget = {};

		var counts = {drawn: 0, badged: 0, satellites: 0, fellBack: 0,
					  linked: 0, selfLoops: 0, moved: 0,
					  /* added: boxes this layer created for a regulator the map
					     does not print. unplaced: the same, with nowhere to put
					     it -- no arc fallback exists for a single endpoint. */
					  added: 0, unplaced: 0};

		edges.forEach(function(edge) {
			var targetRaster = me.rasterBox(edge.targetID);
			var regulatorRaster = me.rasterBox(edge.regulatorID, targetRaster);

			if (targetRaster && regulatorRaster) {
				/* THE REGULATOR IS ALREADY ON THIS MAP.
				   Every satellite is a second drawing of a box KEGG already
				   placed -- that is what the branch requires. Copying one the
				   reader can see without moving their eyes is what made the
				   layer look wrong, so inside NEAR_RADIUS we point at the
				   original instead of stamping a duplicate next to it. */
				if (regulatorRaster.key === targetRaster.key) {
					/* Same drawn box: co-located genes bucket by the literal
					   x#y string, so Fos and Jun ARE one rectangle. There is no
					   "beside" to park in and no two points to join -- the only
					   honest mark is a loop on the box itself. */
					me.drawSelfMarker(edge, targetRaster, factor);
					counts.selfLoops++;
					counts.drawn++;
					return;
				}
				if (me.boxGap(regulatorRaster, targetRaster) <= me.NEAR_RADIUS) {
					if (me.drawLink(edge, regulatorRaster, targetRaster, true)) {
						counts.linked++;
						counts.drawn++;
						return;
					}
				}

				/* Cap satellites per target at 4. Measured max fan-in at the
				   8-edge cap is 2 (3 on mmu04010), so this is headroom, not a
				   constraint -- but a box ringed by duplicates reads worse than
				   an arc, so the ceiling is deliberate. */
				var used = perTarget[edge.targetID] || 0;
				if (used < 4) {
					var satW = Math.max(30, regulatorRaster.width * 0.85);
					var satH = Math.max(12, regulatorRaster.height * 0.85);
					var gap = (me.payload.source === "Reactome") ? 8 : 6;
					var slot = me.findSlot(targetRaster, satW, satH, gap, occupancyRects,
										   imageWidth, imageHeight);
					if (slot) {
						var handle = me.drawSatellite(edge, targetRaster, slot,
													  satW, satH, factor, false);
						/* A placed satellite becomes an obstacle for the next.
						   Its AUTOMATIC slot, not the dragged one: a position
						   the user chose is their business, and letting a
						   hand-placed box push the next one around would make
						   the layout depend on drag order. */
						occupancyRects.push({
							left: slot.cx - satW / 2, right: slot.cx + satW / 2,
							top: slot.cy - satH / 2, bottom: slot.cy + satH / 2
						});
						perTarget[edge.targetID] = used + 1;
						counts.drawn++;
						counts.satellites++;
						if (handle && (handle.dx || handle.dy)) { counts.moved++; }
						return;
					}
				}
			}

			if (targetRaster && !regulatorRaster) {
				/* THE REGULATOR IS NOT ON THIS MAP AT ALL.
				   This is the majority case and it used to be discarded on the
				   server: 1,233 of 1,382 relationships on mmu05226, and 42 of
				   204 regulators that no map in the organism draws, so they
				   could never be seen anywhere. There is no box to copy and no
				   second point to draw a line from, so the layer makes the box
				   -- which is what a satellite already is. It carries the
				   regulator's own symbol as real text (no sprite exists to
				   bake one in) inside the same dashed violet frame, whose
				   documented meaning is exactly this: a box the layer added,
				   not a KEGG annotation. */
				var addedUsed = perTarget[edge.targetID] || 0;
				if (addedUsed < 4) {
					var addW = Math.max(30, (targetRaster.width || me.ADDED_BOX_WIDTH) * me.ADDED_BOX_SCALE);
					var addH = Math.max(12, (targetRaster.height || me.ADDED_BOX_HEIGHT) * me.ADDED_BOX_SCALE);
					var addGap = (me.payload.source === "Reactome") ? 8 : 6;
					var addSlot = me.findSlot(targetRaster, addW, addH, addGap, occupancyRects,
											  imageWidth, imageHeight);
					if (addSlot) {
						var addHandle = me.drawSatellite(edge, targetRaster, addSlot,
														 addW, addH, factor, true);
						occupancyRects.push({
							left: addSlot.cx - addW / 2, right: addSlot.cx + addW / 2,
							top: addSlot.cy - addH / 2, bottom: addSlot.cy + addH / 2
						});
						perTarget[edge.targetID] = addedUsed + 1;
						counts.drawn++;
						counts.added++;
						if (addHandle && (addHandle.dx || addHandle.dy)) { counts.moved++; }
						return;
					}
				}
				/* No free space, and the arc fallback below cannot help: it
				   needs two boxes and there is only one. Counted so the legend
				   can say so rather than leaving a silent hole. */
				counts.unplaced++;
				return;
			}

			/* FALLBACK: no free space beside the target, so fall back to the
			   bowed arc. It is worse, and it is honest -- the alternative is
			   dropping the edge, and the legend counts this. */
			var result = me.drawLink(edge, regulatorRaster, targetRaster, false);
			if (!result) { return; }
			counts.fellBack++;
			counts.drawn++;
			if (result.shared) { counts.badged++; }
		});

		this.renderLegend(counts);
	};

	/**
	* Frame a REAL box in the overlay's own dashed violet.
	*
	* Without this a short link is an anonymous violet tick between two red
	* rectangles: it says something is happening, but not what, and not which of
	* the two boxes it came FROM.
	*
	* SOLID, and deliberately not the satellite's dash. The legend states that
	* dashed violet boxes are regulators this layer placed and NOT KEGG
	* annotations; putting the same dash around a real KEGG box would make the
	* legend false and leave a reader unable to tell Jun (real, ringed) from
	* Rb1 (a copy) when the two sit side by side. So the layer has two marks
	* with one hue: SOLID ring = a box KEGG drew, that this layer is pointing
	* FROM; DASHED frame = a box this layer added.
	*
	* pointer-events is off: the ring sits directly over a real feature box and
	* must not take its hover or its click.
	*/
	this.markSource = function(box, style) {
		var pad = 1.8;
		return this.append("rect", {
			x: box.cx - box.halfWidth - pad,
			y: box.cy - box.halfHeight - pad,
			width: (box.halfWidth + pad) * 2,
			height: (box.halfHeight + pad) * 2,
			fill: "none",
			stroke: style.stroke, "stroke-width": this.ink(1.6),
			rx: 1.5, opacity: 0.95,
			"pointer-events": "none"
		});
	};

	/**
	* A short caption in the overlay's hue, drawn twice: a white stroked copy
	* underneath and the violet fill on top.
	*
	* paint-order would be one element instead of two, but CairoSVG (which
	* renders /pa_save_image) does not implement it, so the export would lose
	* the halo and the caption would disappear into the printed artwork.
	*/
	this.caption = function(x, y, text, style, size) {
		var attributes = {
			x: x, y: y, "text-anchor": "middle",
			"font-family": "Helvetica, Arial, sans-serif",
			"font-size": size, "pointer-events": "none"
		};

		var halo = this.append("text", Ext.apply({
			fill: "none", stroke: "#ffffff", "stroke-width": this.ink(2.4),
			"stroke-linejoin": "round", opacity: 0.85
		}, attributes));
		halo.textContent = text;

		var ink = this.append("text", Ext.apply({
			fill: style.stroke, "font-weight": 600
		}, attributes));
		ink.textContent = text;
		return ink;
	};

	/**
	* One edge drawn between the two REAL boxes, with no duplicate glyph.
	*
	* @param {Boolean} straight  true for a near pair. The bow is
	*        max(14, min(length * 0.16, 70)) CANVAS units, so over the ~4 canvas
	*        units separating Jun from Ccnd1 a curve is not a curve, it is a
	*        loop swinging out over unrelated artwork. Near pairs get the chord.
	* @returns {Object|null} {shared} once drawn, null when either endpoint has
	*        no geometry on this map.
	*/
	this.drawLink = function(edge, regulatorRaster, targetRaster, straight) {
		var fromBox = this.boxGeometry(edge.regulatorID);
		var toBox = this.boxGeometry(edge.targetID);
		if (!fromBox || !toBox) { return null; }

		/* boxGeometry takes graphical[0]; when the regulator is drawn several
		   times, the near/far decision was made about a SPECIFIC one of those
		   boxes and the line has to leave that same box. */
		if (regulatorRaster) {
			var factor = this.options.adjustFactor;
			fromBox = {
				cx: regulatorRaster.cx * factor, cy: regulatorRaster.cy * factor,
				halfWidth: (regulatorRaster.width * factor || 20) / 2,
				halfHeight: (regulatorRaster.height * factor || 20) / 2,
				key: regulatorRaster.key, boxes: regulatorRaster.boxes
			};
		}

		var from = this.perimeterPoint(fromBox, toBox.cx, toBox.cy, 2);
		var to = this.perimeterPoint(toBox, fromBox.cx, fromBox.cy, 4);
		var control = straight
			? {x: (from.x + to.x) / 2, y: (from.y + to.y) / 2}
			: this.controlPoint(from, to);
		var style = this.CLASS_STYLE[edge.evidenceClass] || this.CLASS_STYLE.unsupported;

		var occupancy = (this.options.boxOccupancy || {})[toBox.key] || 1;
		var shared = occupancy > 1;

		var d = "M" + from.x + "," + from.y +
				" Q" + control.x + "," + control.y + " " + to.x + "," + to.y;

		/* A white casing drawn UNDER the line keeps it legible where it crosses
		   the map's own printed lines and labels -- which the application cannot
		   see, so it cannot route around them. Thin enough to read as a halo
		   rather than as an erasure. */
		this.append("path", {
			d: d, fill: "none", stroke: "#ffffff",
			"stroke-width": this.ink(style.width + 2.4),
			"stroke-linecap": "round", opacity: 0.65
		});

		var path = this.append("path", {
			d: d, fill: "none", stroke: style.stroke,
			"stroke-width": this.ink(style.width),
			"stroke-linecap": "round",
			"stroke-dasharray": this.inkDash(style.dash),
			opacity: style.opacity
		});

		var head = this.terminal(to, control, style, shared, this.isRepression(edge));
		if (straight) {
			/* Only for the near case. Over a long bowed arc the reader can
			   follow the curve back to its origin, so a ring there would be
			   decoration; over a 4 px chord there is no curve to follow. */
			this.markSource(fromBox, style);
		}
		var tip = this.edgeTooltip(edge, shared) + (straight
			? "\n" + (edge.regulatorLabel || edge.regulator) +
			  " is drawn on this map (framed in violet), so it is joined to " +
			  (edge.targetLabel || edge.target) + " rather than copied beside it"
			: "");
		this.tooltip(path, tip);
		this.tooltip(head, tip);

		return {shared: shared};
	};

	/**
	* Regulator and target are the SAME drawn box.
	*
	* Features bucket by the literal string x + "#" + y, so genes KEGG placed at
	* one coordinate collapse into one rectangle -- Fos and Jun on mmu05167 are
	* not neighbours, they are the same 46x17 px box. A line needs two points and
	* a satellite needs a "beside"; neither exists here. A loop leaving the top
	* edge and returning to it claims exactly what is true: a relationship
	* between two things inside this box.
	*/
	this.drawSelfMarker = function(edge, box, factor) {
		var style = this.CLASS_STYLE[edge.evidenceClass] || this.CLASS_STYLE.unsupported;
		var cx = box.cx * factor;
		var top = (box.cy - box.height / 2) * factor;
		var halfWidth = Math.max(6, box.width * factor / 4);
		var rise = Math.max(9, box.height * factor * 0.9);

		var d = "M" + (cx - halfWidth) + "," + top +
				" C" + (cx - halfWidth) + "," + (top - rise) +
				" " + (cx + halfWidth) + "," + (top - rise) +
				" " + (cx + halfWidth) + "," + top;

		this.append("path", {
			d: d, fill: "none", stroke: "#ffffff",
			"stroke-width": this.ink(style.width + 2.4),
			"stroke-linecap": "round", opacity: 0.65
		});
		var loop = this.append("path", {
			d: d, fill: "none", stroke: style.stroke,
			"stroke-width": this.ink(style.width),
			"stroke-linecap": "round",
			"stroke-dasharray": this.inkDash(style.dash),
			opacity: style.opacity
		});
		/* Pointing straight down into the box it came from. */
		var head = this.terminal({x: cx + halfWidth, y: top},
								 {x: cx + halfWidth, y: top - rise}, style, true);

		this.markSource({
			cx: cx, cy: box.cy * factor,
			halfWidth: box.width * factor / 2,
			halfHeight: box.height * factor / 2
		}, style);

		/* The one place a caption is not optional. A ring says "this box", and
		   an arrow says "into this box" -- but the box holds SEVERAL genes and
		   the claim is about two specific ones inside it. Neither shape can
		   name them, and the printed label cannot either, because KEGG prints
		   only the first gene of a co-located group. */
		this.caption(cx, top - rise - Math.max(2, box.height * factor * 0.25),
					 (edge.regulatorLabel || edge.regulator) + " → " +
					 (edge.targetLabel || edge.target),
					 style, Math.max(5.5, Math.min(box.height * factor * 0.8, 9)));

		var tip = this.edgeTooltip(edge, true) +
			"\nboth genes are drawn in this one box, so this link is shown on it";
		this.tooltip(loop, tip);
		this.tooltip(head, tip);
	};

	/**
	* One satellite: the regulator's own glyph parked beside its target, joined
	* by a short stub.
	*
	* The glyph is deliberately NOT drawn at full fidelity. Rendered unchanged
	* it would be pixel-identical to a real feature box, which would assert
	* that this gene is annotated at a spot where KEGG never put it -- a false
	* claim printed on a curated diagram. It is therefore scaled to 0.85 and
	* framed in the overlay's own violet dash, so it reads as evidence-layer
	* furniture rather than as part of the map.
	*/
	/**
	* @param {Boolean} added true when this box is one the layer INVENTED for a
	*        regulator the map does not print, false when it duplicates a box
	*        KEGG drew elsewhere. Taken from the branch that called, not from
	*        edge.regulatorDrawn: the server decides that flag from the stored
	*        pathway document and the client from its own graphical data, and
	*        when those two disagree the tooltip must describe the box actually
	*        on screen.
	*/
	this.drawSatellite = function(edge, target, slot, satW, satH, factor, added) {
		var style = this.CLASS_STYLE[edge.evidenceClass] || this.CLASS_STYLE.unsupported;
		var glyph = this.satelliteGlyph(edge.regulatorID, satW);
		var key = this.edgeKey(edge);
		var saved = this.placement[key] || {};

		var width = satW * factor;
		var height = satH * factor;
		var left = (slot.cx - satW / 2) * factor;
		var top = (slot.cy - satH / 2) * factor;

		/* The stub stays a child of the overlay group, NOT of the draggable
		   group: one of its ends is nailed to the target box and must not move
		   with the hand. It is redrawn from the satellite's live centre instead. */
		var casing = this.append("path", {
			fill: "none", stroke: "#ffffff", "stroke-width": this.ink(3.2), opacity: 0.7
		});
		var stub = this.append("path", {
			fill: "none", stroke: style.stroke, "stroke-width": this.ink(1.5),
			"stroke-dasharray": this.inkDash(style.dash), opacity: style.opacity
		});
		/* Direction mark at the TARGET end of the stub, re-aimed by
		   applyPlacement so it follows the box when the reader moves it. */
		var mark = this.append("path", {fill: "none"});

		/* Everything that MOVES lives in one <g>, so a drag is a single
		   translate rather than five coordinate rewrites -- and so the export,
		   which serialises the live DOM, carries the moved position. */
		var node = this.svgEl("g", {"class": "evidenceSatellite"});
		this.group.appendChild(node);

		/* A white ground under the glyph: the sprite has transparent margins
		   and the printed map shows through them otherwise. */
		node.appendChild(this.svgEl("rect", {
			x: left, y: top, width: width, height: height,
			fill: "#ffffff", opacity: 0.92, rx: 1
		}));

		/* An ADDED box gets the regulator's own values painted as one cell per
		   condition, left to right, the same order and the same scale as every
		   printed box on this map. Without it the box is white, and a white box
		   on a coloured map states "no data" about a feature that is measured
		   in this very job. */
		var cellColours = added ? this.regulatorColours(edge) : [];
		if (cellColours.length) {
			var cellWidth = width / cellColours.length;
			for (var c = 0; c < cellColours.length; c++) {
				node.appendChild(this.svgEl("rect", {
					x: left + c * cellWidth, y: top,
					width: cellWidth + 0.2, height: height,
					fill: cellColours[c]
				}));
			}
		}

		if (glyph) {
			var image = this.svgEl("image", {
				x: left, y: top, width: width, height: height,
				preserveAspectRatio: "none"
			});
			image.setAttributeNS("http://www.w3.org/1999/xlink", "xlink:href", glyph.src);
			image.setAttribute("href", glyph.src);
			node.appendChild(image);
		} else {
			/* The regulator has coordinates on this map but is not a PAINTED
			   feature -- the user's data never matched it -- so there is no
			   sprite to reuse and no baked label. An unlabelled satellite is
			   worse than useless: it is an unexplained box on a curated
			   diagram. Fall back to real text, with a websafe stack and no
			   external font, so the CairoSVG export can still resolve it.
			   Measured on mmu04330: 2 of 6 satellites take this path. */
			var fontSize = Math.max(5, Math.min(height * 0.68, 11));
			var labelText = edge.regulatorLabel || edge.regulator;
			var labelAttrs = {
				x: left + width / 2, y: top + height / 2 + fontSize * 0.36,
				"text-anchor": "middle",
				"font-family": "Helvetica, Arial, sans-serif",
				"font-size": fontSize
			};

			/* Black straight over the cells, exactly as the printed boxes do
			   it, and with NO halo. A white halo was tried first and it wrecked
			   the thing it was meant to protect: at a 2.6px stroke on a 14px
			   box it painted over most of the strip, so a 12-condition box read
			   as a flat pale rectangle with a sliver of colour at each end.
			   The scale runs white -> red, so its luminance never drops far
			   enough to swallow black text -- which is why the printed boxes
			   need no halo either. Violet stays for an uncoloured box, where
			   there is no strip to protect and the hue carries the meaning. */
			var label = this.svgEl("text", Ext.apply({
				fill: cellColours.length ? "#1a1a1a" : style.stroke
			}, labelAttrs));
			label.textContent = labelText;
			node.appendChild(label);
		}

		var frame = this.svgEl("rect", {
			x: left, y: top, width: width, height: height,
			fill: "none",
			stroke: style.stroke, "stroke-width": this.ink(1.2),
			"stroke-dasharray": this.inkDash("3,2"), rx: 1, opacity: 0.95
		});
		node.appendChild(frame);

		/* Two different claims, and conflating them would make the second one
		   false: a satellite for a regulator KEGG drew elsewhere on this map is
		   a DUPLICATE the reader could have found; a box for a regulator the
		   map does not print at all is new information the layer is adding. */
		var provenance = added
			? "\n(" + edge.regulatorLabel + " is not drawn on this map — this box " +
			  "was added by the evidence layer, it is not a KEGG annotation)"
			: "\n(duplicate of " + edge.regulatorLabel +
			  ", placed here by the evidence layer — not a KEGG annotation)";
		var tip = this.edgeTooltip(edge, false) + provenance +
			"\ndrag to move it; “reset positions” in the legend puts it back";
		this.tooltip(frame, tip);
		this.tooltip(stub, tip);

		var handle = {
			key: key, node: node, stub: stub, casing: casing,
			mark: mark, style: style, edge: edge, added: !!added,
			shared: (this.options.boxOccupancy || {})[target.key] > 1,
			repress: this.isRepression(edge),
			slot: slot, width: width, height: height,
			dx: saved.dx || 0, dy: saved.dy || 0,
			target: {
				cx: target.cx * factor, cy: target.cy * factor,
				halfWidth: target.width * factor / 2,
				halfHeight: target.height * factor / 2
			}
		};
		this.satellites.push(handle);
		this.applyPlacement(handle);
		this.makeDraggable(handle);

		return handle;
	};

	/* ---------------------------------------------------------------------
	   MOVING A SATELLITE BY HAND

	   Automatic placement is blind to free text -- "Cell proliferation",
	   "Angiogenesis", the compartment labels -- because none of it is an entry
	   in any file the application reads. It is not going to be right every
	   time, so the reader gets to move it, and the move is kept.

	   Offsets are stored in RASTER px. The panel's adjustFactor changes with
	   its width, so a canvas-unit offset saved in a wide panel would move the
	   box somewhere else entirely when reopened in a narrow one.
	   --------------------------------------------------------------------- */

	/** Position a satellite and re-anchor its stub to the target box. */
	this.applyPlacement = function(handle) {
		var factor = this.options.adjustFactor;

		handle.node.setAttribute("transform", "translate(" +
			(handle.dx * factor) + "," + (handle.dy * factor) + ")");

		var cx = (handle.slot.cx + handle.dx) * factor;
		var cy = (handle.slot.cy + handle.dy) * factor;

		/* Straight, not bowed: over ~30 raster px a curve reads as a wobble. */
		var targetPoint = this.perimeterPoint(handle.target, cx, cy, 0);
		var satellitePoint = this.perimeterPoint(
			{cx: cx, cy: cy,
			 halfWidth: handle.width / 2, halfHeight: handle.height / 2},
			handle.target.cx, handle.target.cy, 0);

		var d = "M" + targetPoint.x + "," + targetPoint.y +
				" L" + satellitePoint.x + "," + satellitePoint.y;
		handle.stub.setAttribute("d", d);
		handle.casing.setAttribute("d", d);
		if (handle.mark) {
			this.aimMark(handle.mark, targetPoint,
						 {x: satellitePoint.x, y: satellitePoint.y},
						 handle.style, handle.shared, handle.repress);
		}
	};

	/**
	* Pointer-drag one satellite.
	*
	* The diagram sits inside jquery-svg-pan-zoom, which pans on mousedown and
	* touchstart at the root <svg>. Those are a SEPARATE event stream from
	* pointer events: for a mouse pointer, cancelling pointerdown does NOT
	* suppress the compatibility mousedown -- that guarantee only holds for
	* touch. Measured before this was added: the satellite moved correctly AND
	* the whole map panned under it by the same delta, so the box looked pinned
	* while everything else slid. The gesture is therefore swallowed in both
	* streams before the plugin can see it.
	*/
	this.makeDraggable = function(handle) {
		var me = this;
		var node = handle.node;

		["mousedown", "touchstart"].forEach(function(name) {
			node.addEventListener(name, function(event) {
				event.preventDefault();
				event.stopPropagation();
			}, {passive: false});
		});

		node.addEventListener("pointerdown", function(event) {
			var root = me.options.canvas.node;
			var screenMatrix = root.getScreenCTM();
			if (!screenMatrix) { return; }

			event.preventDefault();
			event.stopPropagation();

			var inverse = screenMatrix.inverse();
			var start = me.clientToCanvas(event.clientX, event.clientY, inverse);
			var origin = {dx: handle.dx, dy: handle.dy};
			/* Screen pixels, not canvas units: the threshold is about the
			   steadiness of a hand, which does not rescale with the zoom. */
			var pressedAt = {x: event.clientX, y: event.clientY};
			var factor = me.options.adjustFactor;
			try { node.setPointerCapture(event.pointerId); } catch (error) { /* no capture */ }

			var imageWidth = me.options.graphicalOptions.getImageWidth();
			var imageHeight = me.options.graphicalOptions.getImageHeight();

			var move = function(moveEvent) {
				var now = me.clientToCanvas(moveEvent.clientX, moveEvent.clientY, inverse);
				handle.dx = origin.dx + (now.x - start.x) / factor;
				handle.dy = origin.dy + (now.y - start.y) / factor;

				/* Clamped to the artwork. A box dragged off the canvas is not
				   hidden, it is LOST: the panel clips, so it cannot be grabbed
				   again, and only "reset positions" would bring it back. */
				var halfWidth = handle.width / factor / 2;
				var halfHeight = handle.height / factor / 2;
				var cx = Math.min(Math.max(handle.slot.cx + handle.dx, halfWidth),
								  imageWidth - halfWidth);
				var cy = Math.min(Math.max(handle.slot.cy + handle.dy, halfHeight),
								  imageHeight - halfHeight);
				handle.dx = cx - handle.slot.cx;
				handle.dy = cy - handle.slot.cy;

				me.applyPlacement(handle);
			};
			var release = function(releaseEvent) {
				node.removeEventListener("pointermove", move);
				node.removeEventListener("pointerup", release);
				node.removeEventListener("pointercancel", release);
				try { node.releasePointerCapture(releaseEvent.pointerId); }
				catch (error) { /* already released */ }

				if (handle.dx || handle.dy) {
					me.placement[handle.key] = {dx: handle.dx, dy: handle.dy};
				} else {
					delete me.placement[handle.key];
				}
				me.savePlacement();

				/* A press that did not travel is a CLICK, and a box that looks
				   like every other box on the map has to answer a click like
				   them: the feature panel, with this regulator's own values.
				   Decided here rather than with a separate click listener,
				   because pointerdown is cancelled above to keep the map from
				   panning, and a cancelled gesture emits no click event. */
				var travelled = Math.abs(releaseEvent.clientX - pressedAt.x) +
								Math.abs(releaseEvent.clientY - pressedAt.y);
				if (travelled <= 4) { me.openFeatureDetails(handle); }
			};

			node.addEventListener("pointermove", move);
			node.addEventListener("pointerup", release);
			node.addEventListener("pointercancel", release);
		});
	};

	/**
	* The Feature behind an added box.
	*
	* Built from the payload, NOT from the job's feature store, and that is
	* deliberate. In a MORE job a stored Feature is a TARGET: its omicsValues
	* hold one entry per regulator acting on it. Opening the store's entry for
	* Smad7 therefore filled the panel with Smad3, Rela, Sp1, Smad4, Egr1 and
	* Dand5 -- Smad7's own regulators -- under a heading naming Smad7, while
	* the box the reader clicked means "Smad7, the regulator, with this
	* profile". The payload carries exactly that profile, so the panel and the
	* box describe the same thing. The store is only a fallback for a job that
	* predates the payload field.
	*/
	this.featureForEdge = function(edge) {
		var stored = edge.regulatorValues;
		if (!stored || typeof Feature !== "function" || typeof SimpleOmicValue !== "function") {
			var jobView = this.options.jobView;
			var model = jobView && jobView.getModel ? jobView.getModel() : null;
			var store = (model && model.getOmicsValues) ? model.getOmicsValues() : null;
			return (store && store[edge.regulatorID]) ? store[edge.regulatorID] : null;
		}

		/* SimpleOmicValue, not the OmicValue base: the panel's addTableEntrie
		   asks every value isCompoundOmicsValue(), and the base class throws
		   "Not implemented" for it -- the panel then renders its headings and
		   nothing else. */
		var omicValue = new SimpleOmicValue();
		omicValue.setOmicName(stored.omicName);
		omicValue.setInputName(stored.originalName || edge.regulatorLabel);
		omicValue.setValues(stored.values || []);
		if (stored.sampleValues) { omicValue.setSampleValues(stored.sampleValues); }
		omicValue.originalName = stored.originalName || edge.regulatorLabel;
		omicValue.setRelevant([]);

		var feature = new Feature();
		feature.setID(edge.regulatorID);
		feature.setName(edge.regulatorLabel || edge.regulator);
		feature.setFeatureType("Gene");
		feature.setOmicsValues([omicValue]);
		return feature;
	};

	/**
	* Open the feature panel for an added box, as a printed box does on click.
	*
	* The panel takes a FeatureSet, so the regulator is wrapped in one of its
	* own -- placed at the slot the box occupies, which is where the reader
	* just clicked. FeatureSetElem's graphical data is null: this feature has
	* no box in the pathway document, which is the entire reason the layer drew
	* one, and every consumer that reads it guards for a missing value.
	*/
	this.openFeatureDetails = function(handle) {
		var pathwayView = this.options.pathwayView;
		if (!handle || !handle.edge || !pathwayView || !pathwayView.showFeatureSetDetails) {
			return;
		}
		if (typeof FeatureSet !== "function" || typeof FeatureSetElem !== "function") {
			return;
		}

		var feature = this.featureForEdge(handle.edge);
		if (!feature) { return; }

		try {
			var set = new FeatureSet(handle.slot.cx, handle.slot.cy);
			set.addFeature(new FeatureSetElem(feature, null));
			set.setMainFeature(feature);
			pathwayView.showFeatureSetDetails(handle.key, set);
		} catch (error) {
			console.warn("Evidence overlay: could not open the feature panel", error);
		}
	};

	/** Screen coordinates to the canvas units the overlay draws in. */
	this.clientToCanvas = function(clientX, clientY, inverse) {
		var point = this.options.canvas.node.createSVGPoint();
		point.x = clientX;
		point.y = clientY;
		return point.matrixTransform(inverse);
	};

	/** "reset positions" is inert until there is something to reset. */
	this.updateResetState = function() {
		if (!this.legendEl) { return; }
		this.legendEl.find(".evidenceLegend-reset")
			.toggleClass("is-disabled", !Object.keys(this.placement || {}).length);
	};

	this.savePlacement = function() {
		this.updateResetState();
		if (typeof this.options.onPlacementChange !== "function") { return; }
		try {
			this.options.onPlacementChange(this.placement);
		} catch (error) {
			/* Additive by design: a diagram that cannot persist a nudge still
			   shows the nudge for as long as it is open. */
			console.warn("Evidence overlay: placement not saved", error);
		}
	};

	/** Drop every hand-placed offset and lay the layer out automatically again. */
	this.resetPlacement = function() {
		this.placement = {};
		this.savePlacement();
		this.refresh();
	};

	/**
	* Where the control card goes.
	*
	* NOT the diagram panel's own body, which is where it used to go. That panel
	* is as tall as the map -- measured 865 px on mmu05167 against a 907 px
	* viewport -- so a card underneath it began 18 px from the bottom of the
	* screen and its 240 px of controls were entirely below the fold. Nobody
	* scrolls past a pathway diagram looking for a legend, so in practice the
	* layer had no controls at all.
	*
	* The Pathway information column beside the map is 300 px wide, always on
	* screen, and already holds this pathway's classification and its regulation
	* chart. Resolved through a function because that column is constructed
	* after the diagram panel that creates this overlay.
	*/
	this.legendHost = function() {
		var host = this.options.panelEl;
		if (typeof host === "function") {
			try { host = host(); } catch (error) { host = null; }
		}
		return (host && host.length) ? host : null;
	};

	this.renderLegend = function(counts) {
		var statistics = (this.payload && this.payload.statistics) || {};
		var byClass = statistics.byClass || {};
		var me = this;
		var drawn = counts.drawn, badged = counts.badged, fellBack = counts.fellBack;

		if (this.legendEl) { this.legendEl.remove(); }
		if (!statistics.totalRelationships) { return; }

		var host = this.legendHost();
		if (!host) { return; }

		var row = function(name) {
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
		};

		/* One list per group, so "Not recorded" can carry its two reasons under
		   a single heading with its own total. The heading states the total
		   because that is the number a reader compares against the corroborated
		   one; the two rows beneath say why each edge is in it. */
		var rows = this.CLASS_GROUPS.map(function(group) {
			var total = group.members.reduce(function(sum, name) {
				return sum + (byClass[name] || 0);
			}, 0);
			var heading = group.title
				? '<li class="evidenceLegend-group">' +
				  '<span class="evidenceLegend-name">' + group.title + '</span>' +
				  '<span class="evidenceLegend-count">' + total + '</span></li>'
				: "";
			return heading + group.members.map(row).join("");
		}).join("");

		/* Which databases actually corroborated anything here, strongest first.
		   Naming them is not decoration: "corroborated" means a different thing
		   when it comes from KEGG's own relation graph than from OmniPath's
		   literature list, and the reader cannot tell without being told. */
		var bySource = statistics.bySource || {};
		var sourceNames = Object.keys(bySource).sort(function(a, b) {
			return bySource[b] - bySource[a];
		}).map(function(name) {
			return '<span class="evidenceLegend-source-name">' + name + '</span> ' +
				bySource[name];
		});

		/* Everything the layer could NOT draw, stated on screen. A silently
		   truncated overlay reads as "this is all there is". */
		var omissions = [];
		if (statistics.hidden) {
			omissions.push(statistics.hidden + " more on this map are hidden by the " +
				drawn + "-edge readability cap");
		}
		if (statistics.offMapTargets) {
			/* The one endpoint that is still required. A mark has to be
			   anchored to something the map prints. */
			omissions.push(statistics.offMapTargets.toLocaleString() +
				" relationships act on a target this map does not draw");
		}
		if (counts.unplaced) {
			omissions.push(counts.unplaced + (counts.unplaced === 1
				? " added regulator had nowhere free to sit beside its target"
				: " added regulators had nowhere free to sit beside their target"));
		}
		if (fellBack) {
			/* Named, not hidden. An edge that could not be parked is drawn as
			   the old long arc, and the reader is told which ones those are. */
			omissions.push(fellBack + (fellBack === 1
				? " regulator had no free space beside its target and is drawn as an arc"
				: " regulators had no free space beside their target and are drawn as arcs"));
		}
		if (badged) {
			/* Counted from what was actually DRAWN, not from the server's
			   multiBoxEndpoints -- that statistic counts a gene appearing in
			   several boxes, which is the opposite situation and would put a
			   number here that does not match the hollow terminals on screen. */
			omissions.push(badged + (badged === 1
				? " edge ends on a box holding several genes"
				: " edges end on a box holding several genes") +
				" and cannot say which one (hollow arrowhead)");
		}
		if (statistics.recordedElsewhere) {
			/* The number that only exists because more than one database is
			   consulted. Before this it was invisible: those relationships were
			   labelled "no external evidence either way". */
			omissions.push(statistics.recordedElsewhere +
				(statistics.recordedElsewhere === 1
					? " interaction is curated on a different pathway map"
					: " interactions are curated on different pathway maps") +
				", not this one");
		}
		if (statistics.multiBoxEndpoints) {
			omissions.push(statistics.multiBoxEndpoints +
				" had an endpoint drawn at several places on this map; one was chosen");
		}
		if (counts.added) {
			/* The headline of what this layer now does. Kept separate from the
			   duplicate-satellite line above: one says a box was copied, this
			   one says a box was INVENTED, and a reader deciding how much to
			   trust the picture needs to know which. */
			omissions.push("<b>" + counts.added + "</b> of the drawn " +
				(counts.added === 1 ? "regulator is" : "regulators are") +
				" not printed on this map at all — added here beside their " +
				"target in a <b>dashed</b> violet frame");
		}
		if (counts.linked || counts.selfLoops) {
			/* Stated rather than silent: these are the edges that did NOT get a
			   parked copy, and the reason is worth one line -- otherwise the
			   layer looks inconsistent about when it duplicates a regulator. */
			var near = [];
			if (counts.linked) {
				near.push(counts.linked + (counts.linked === 1 ? " regulator is" : " regulators are") +
					" already drawn beside their target: ringed in <b>solid</b> violet " +
					"and joined by an arrow, rather than copied");
			}
			if (counts.selfLoops) {
				near.push(counts.selfLoops + (counts.selfLoops === 1 ? " pair shares" : " pairs share") +
					" one drawn box and is marked with a loop on it");
			}
			omissions.push(near.join("<br>"));
		}

		var html =
			/* Built from the Pathway information column's OWN vocabulary, not
			   from card chrome of its own. That column states a section with an
			   <h4>, sub-labels it with .pa-details-label, and renders anything
			   pill-shaped as .pa-details-chip -- flat, no borders, no shadows.
			   A bordered violet card with its own left rail sat in the middle
			   of that and read as a foreign widget pasted into the panel.
			   Violet survives only where it carries meaning: the three stroke
			   samples, which are the actual key to the marks on the map.

			   No data-guides="ignore". The section sits in flow at the column's
			   own content edge, so it can be CHECKED by the alignment guides
			   rather than exempted from them. */
			'<div class="evidenceLegend">' +
			'  <h4>Evidence overlay</h4>' +
			'  <span class="pa-details-label">' + drawn + ' relationship' +
			(drawn === 1 ? '' : 's') + ' drawn</span>' +
			'  <ul class="evidenceLegend-list">' + rows + '</ul>' +
			/* Which databases corroborated ANYTHING on this map, strongest
			   first. Its own line rather than beside the drawn count, because
			   these tally the whole classified set and not the handful the cap
			   let through -- putting the two numbers side by side invited them
			   to be read as the same total. */
			(sourceNames.length
				? '  <p class="evidenceLegend-sources">corroborated by ' +
				  sourceNames.join(' &middot; ') + '</p>'
				: "") +
			/* CONTROLS BEFORE PROSE. The section is the last thing in a column
			   that already holds a chart, so its tail is the first thing to
			   fall off a short viewport -- measured, the buttons sat 3 px from
			   the bottom edge when they came last. What the reader can act on
			   goes above what they can only read. */
			'  <div class="evidenceLegend-actions">' +
			'    <a href="javascript:void(0)" class="button evidenceLegend-button evidenceLegend-toggle" ' +
			'       title="Show or hide the whole evidence layer">' +
			'      <i class="fa fa-eye-slash"></i> Hide layer</a>' +
			/* Gated on BOTH: an added box is draggable exactly like a copied
			   one, so gating on counts.satellites alone left every map whose
			   boxes were all added with a drag and no way to undo it. */
			((counts.satellites || counts.added)
				? '    <a href="javascript:void(0)" class="button evidenceLegend-button evidenceLegend-reset" ' +
				  '       title="Put every dragged regulator back where the layer placed it">' +
				  '      <i class="fa fa-undo"></i> Reset positions</a>'
				: "") +
			'  </div>' +
			((counts.satellites || counts.added)
				? '  <p class="evidenceLegend-note evidenceLegend-hint">Drag any ' +
				  '<b>dashed</b> violet box on the map to move it. A <b>solid</b> ' +
				  'violet ring marks a regulator KEGG itself drew.<br>' +
				  /* The sign is the model's, and the sentence has to say so:
				     MORE and the curated databases agree on direction only
				     58.3% of the time, against 52.8% by chance. */
				  'An <b>arrow</b> ends an edge whose MORE coefficient is positive, ' +
				  'a <b>bar</b> one whose coefficient is negative — this job’s ' +
				  'model, not a curated claim. A <b>hollow</b> arrow means the box ' +
				  'it lands on holds several genes.</p>'
				: "") +
			(omissions.length
				? '<p class="evidenceLegend-note">' + omissions.join("<br>") + '</p>'
				: "") +
			'  <p class="evidenceLegend-source">from this job\'s MORE analysis, ' +
			'classified against KEGG, Reactome and OmniPath &mdash; every ' +
			'pathway of this organism, not just this one.</p>' +
			'</div>';

		this.legendEl = $(html);
		/* After the pathway details, not at the top: the column's first job is
		   still to say which pathway this is. Appended to the body when that
		   block is absent (a Reactome or MapMan diagram builds it differently). */
		var details = host.find(".patwaysDetailsContainer");
		if (details.length) { details.after(this.legendEl); } else { host.append(this.legendEl); }

		this.legendEl.find(".evidenceLegend-toggle").click(function() {
			me.setVisible(!me.visible);
			$(this).html(me.visible
				? '<i class="fa fa-eye-slash"></i> Hide layer'
				: '<i class="fa fa-eye"></i> Show layer');
			$(this).toggleClass("is-off", !me.visible);
		});
		/* Disabled until something has actually been moved, so the control does
		   not offer to undo nothing. */
		var resetEl = this.legendEl.find(".evidenceLegend-reset");
		this.updateResetState();
		resetEl.click(function() {
			if (!Object.keys(me.placement || {}).length) { return; }
			me.resetPlacement();
		});
	};

	/**
	* Redraw from the payload already held.
	*
	* applyVisualSettings -> updateObserver rewrites each feature glyph's href
	* by componentID, iterating this.items only. A satellite is not in items, so
	* without this it keeps the OLD colour scale after the user hits Apply --
	* silently showing stale data next to freshly repainted boxes.
	*/
	this.refresh = function() {
		if (!this.payload) { return; }
		try { this.draw(); } catch (error) {
			console.warn("Evidence overlay refresh failed", error);
		}
		this.setVisible(this.visible);
	};

	this.setVisible = function(visible) {
		this.visible = visible;
		if (this.group) {
			this.group.style.display = visible ? "" : "none";
		}
		return this;
	};

	this.clear = function() {
		/* The handles go with the <g> that held their nodes. Without this they
		   accumulate: every redraw -- a colour-scale Apply, a reset, a zoom --
		   pushed six more onto the list while removing their DOM, so a map with
		   6 boxes was carrying 24 handles, each pinning a detached SVG node and
		   a copy of its edge. Nothing read the stale ones, which is why it went
		   unnoticed, but they were retained for the life of the view. */
		this.satellites = [];
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
