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

	/* ---------------------------------------------------------------------
	   SATELLITE PLACEMENT

	   All placement arithmetic happens in RASTER pixels -- the coordinate
	   space the pathway data is stored in -- and is multiplied by
	   adjustFactor only at draw time. Working in canvas units instead is what
	   made the arc layer sweep the map: its bow constant of 14 canvas units
	   is 68 raster px at the adjustFactor of 0.204 this panel actually uses,
	   so the geometry silently changed meaning with panel width.
	   --------------------------------------------------------------------- */

	/** Raster-space box for a feature: centre plus half extents. */
	this.rasterBox = function(featureID) {
		var graphical = this.options.graphicalOptions.findFeatureGraphicalData(featureID);
		if (!graphical || !graphical.length) { return null; }
		var data = graphical[0];
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

		var drawn = 0, badged = 0, satellites = 0, fellBack = 0;

		edges.forEach(function(edge) {
			var targetRaster = me.rasterBox(edge.targetID);
			var regulatorRaster = me.rasterBox(edge.regulatorID);

			if (targetRaster && regulatorRaster) {
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
						me.drawSatellite(edge, targetRaster, slot, satW, satH, factor);
						/* A placed satellite becomes an obstacle for the next. */
						occupancyRects.push({
							left: slot.cx - satW / 2, right: slot.cx + satW / 2,
							top: slot.cy - satH / 2, bottom: slot.cy + satH / 2
						});
						perTarget[edge.targetID] = used + 1;
						drawn++;
						satellites++;
						return;
					}
				}
			}

			/* FALLBACK: no free space beside the target, so fall back to the
			   bowed arc. It is worse, and it is honest -- the alternative is
			   dropping the edge, and the legend counts this. */
			var fromBox = me.boxGeometry(edge.regulatorID);
			var toBox = me.boxGeometry(edge.targetID);
			if (!fromBox || !toBox) { return; }
			fellBack++;

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

		this.renderLegend(drawn, badged, satellites, fellBack);
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
	this.drawSatellite = function(edge, target, slot, satW, satH, factor) {
		var style = this.CLASS_STYLE[edge.evidenceClass] || this.CLASS_STYLE.unsupported;
		var glyph = this.satelliteGlyph(edge.regulatorID, satW);

		var left = (slot.cx - satW / 2) * factor;
		var top = (slot.cy - satH / 2) * factor;
		var width = satW * factor;
		var height = satH * factor;

		/* Stub from the target's perimeter to the satellite's nearest edge.
		   Straight, not bowed: over ~30 raster px a curve reads as a wobble. */
		var targetPoint = this.perimeterPoint(
			{cx: target.cx * factor, cy: target.cy * factor,
			 halfWidth: target.width * factor / 2, halfHeight: target.height * factor / 2},
			slot.cx * factor, slot.cy * factor, 0);
		var satellitePoint = this.perimeterPoint(
			{cx: slot.cx * factor, cy: slot.cy * factor,
			 halfWidth: width / 2, halfHeight: height / 2},
			target.cx * factor, target.cy * factor, 0);

		this.append("path", {
			d: "M" + targetPoint.x + "," + targetPoint.y +
			   " L" + satellitePoint.x + "," + satellitePoint.y,
			fill: "none", stroke: "#ffffff", "stroke-width": 3.2, opacity: 0.7
		});
		var stub = this.append("path", {
			d: "M" + targetPoint.x + "," + targetPoint.y +
			   " L" + satellitePoint.x + "," + satellitePoint.y,
			fill: "none", stroke: style.stroke, "stroke-width": 1.5,
			"stroke-dasharray": style.dash, opacity: style.opacity
		});

		/* A white ground under the glyph: the sprite has transparent margins
		   and the printed map shows through them otherwise. */
		this.append("rect", {
			x: left, y: top, width: width, height: height,
			fill: "#ffffff", opacity: 0.92, rx: 1
		});

		if (glyph) {
			var image = this.svgEl("image", {
				x: left, y: top, width: width, height: height,
				preserveAspectRatio: "none"
			});
			image.setAttributeNS("http://www.w3.org/1999/xlink", "xlink:href", glyph.src);
			image.setAttribute("href", glyph.src);
			this.group.appendChild(image);
		}

		if (!glyph) {
			/* The regulator has coordinates on this map but is not a PAINTED
			   feature -- the user's data never matched it -- so there is no
			   sprite to reuse and no baked label. An unlabelled satellite is
			   worse than useless: it is an unexplained box on a curated
			   diagram. Fall back to real text, with a websafe stack and no
			   external font, so the CairoSVG export can still resolve it.
			   Measured on mmu04330: 2 of 6 satellites take this path. */
			var fontSize = Math.max(5, Math.min(height * 0.68, 11));
			this.append("text", {
				x: left + width / 2, y: top + height / 2 + fontSize * 0.36,
				"text-anchor": "middle",
				"font-family": "Helvetica, Arial, sans-serif",
				"font-size": fontSize,
				fill: style.stroke
			}).textContent = edge.regulatorLabel || edge.regulator;
		}

		var frame = this.append("rect", {
			x: left, y: top, width: width, height: height,
			fill: "none",
			stroke: style.stroke, "stroke-width": 1.2,
			"stroke-dasharray": "3,2", rx: 1, opacity: 0.95
		});

		var tip = this.edgeTooltip(edge, false) +
			"\n(duplicate of " + edge.regulatorLabel +
			", placed here by the evidence layer — not a KEGG annotation)";
		this.tooltip(frame, tip);
		this.tooltip(stub, tip);
	};

	this.renderLegend = function(drawn, badged, satellites, fellBack) {
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
			'classified against OmniPath. Dashed violet boxes are regulators ' +
			'placed by this layer, not KEGG annotations.</p>' +
			'</div>';

		this.legendEl = $(html);
		this.options.panelEl.append(this.legendEl);
		this.legendEl.find(".evidenceLegend-toggle").click(function() {
			me.setVisible(!me.visible);
			$(this).text(me.visible ? "hide" : "show");
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
