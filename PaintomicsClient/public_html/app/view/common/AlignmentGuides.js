/* Alignment guides -----------------------------------------------------------
   A development overlay that draws red vertical rules down the page at every
   left edge text actually starts on, so a block that is off the rail shows up
   as an extra line rather than as a feeling that something is slightly wrong.

   It exists because the eye is bad at this. The hero used to sit 50px right of
   every other block on the landing page, and nothing about the screenshot said
   so - the two blocks are in different cards, hundreds of pixels apart, and a
   50px drift between them reads as "the hero is indented", which is a thing a
   design might mean to do. The overlay makes the question answerable instead of
   arguable: one rail, or two?

   OFF BY DEFAULT, and there is no code path that turns it on by itself. It is
   reached three ways, all of them deliberate:

     - Ctrl+Alt+G          toggles it
     - ?guides=1           in the URL, for a reload that comes up with it on
     - paGuides.toggle()   from the console

   Everything it draws is `pointer-events: none` inside one container that is
   removed on toggle-off, so an overlay left on cannot swallow a click or leak
   into a screenshot of anything but itself.

   Why measurement uses a Range and not getBoundingClientRect on the element:
   for a block element the border box is the full column width, so its `left`
   is where the *box* starts, not where the *glyphs* start. `<h2>` spanning the
   card reports left=77 while its text begins at 103. Ranges over the first
   non-empty text node report where the type actually lands, which is the only
   number a reader can see. This distinction is the whole reason the overlay is
   trustworthy - measuring boxes would have declared the page already aligned.
   ---------------------------------------------------------------------------*/
(function (window, document) {
	"use strict";

	/* Two x positions count as the same rail if they are within this many CSS
	   pixels. Sub-pixel layout, italic side bearings and the odd 0.5px border
	   routinely shift a glyph box by a fraction; treating those as separate
	   rails would bury the real 50px drift under a dozen phantom ones. One
	   pixel is tight enough that a genuine 2px indent still reports. */
	var RAIL_TOLERANCE = 1.5;

	/* A rail needs this many elements on it before it counts as a rail rather
	   than as a stray. Below this the overlay still draws it, but as an
	   "off-rail" line - which is exactly what a lone misaligned block is. */
	var RAIL_QUORUM = 2;

	var STYLE_ID = "pa-alignment-guides-style";
	var LAYER_ID = "pa-alignment-guides";

	var state = { on: false, raf: 0, timer: 0, scanAll: false };

	/* The elements worth measuring: things a reader perceives as a line of text
	   starting somewhere. Deliberately excludes generic containers - a <div>
	   wrapping a paragraph inherits the paragraph's first text node and would
	   report the same rail twice, inflating every quorum. */
	var SELECTOR = [
		"h1", "h2", "h3", "h4", "h5", "h6",
		"p", "li", "dt", "dd", "blockquote",
		/* a[class*='po-btn'] because the hero's actions are po-btn-primary /
		   po-btn-outline / po-btn-quiet anchors, not a.button: the box-align
		   rule below already expected them and the selector never admitted
		   them, so the landing page's most prominent row of controls was
		   invisible to this tool - a nudged button measured clean. */
		"a.button", "a[class*='po-btn']", "label", "figcaption", "th", "td",
		/* An ExtJS grid's column headers are divs, not <th>, so a selector of
		   semantic elements cannot see them - and the tool reported the hub and
		   metabolite-class grids as clean while every header in them sat 5px
		   left of its own column's values (header padding 6px 5px against
		   cells' 5px 10px). A results page is mostly grids; missing their
		   headers missed most of what is on it. */
		".x-column-header-inner"
	].join(",");

	/* True when the element is part of a sentence rather than the start of a
	   block - an inline button or link with running text before it inside the
	   same paragraph. Such an element has no alignment obligation at all: where
	   it lands is decided by how the line before it wrapped, and if it happens
	   to wrap onto a fresh line it looks exactly like a block that starts
	   there. Four of the seven items this overlay reported on the landing page
	   were the same three inline "Load example" / "Next step" / "AI Interpret"
	   buttons sitting mid-clause in a step card's prose. */
	function isFlowContinuation(el) {
		for (var s = el.previousSibling; s; s = s.previousSibling) {
			if (s.nodeType === 3 && s.nodeValue.trim()) { return true; }
			if (s.nodeType === 1) { return window.getComputedStyle(s).display.indexOf("inline") === 0; }
		}
		return false;
	}

	function isVisible(el) {
		if (!el.offsetParent && window.getComputedStyle(el).position !== "fixed") {
			return false;
		}
		var r = el.getBoundingClientRect();
		if (r.width < 4 || r.height < 4) { return false; }
		/* Walk up for display/visibility rather than trusting offsetParent
		   alone: ExtJS hides inactive steps with `display:none` on a wrapper,
		   and a descendant of one still answers offsetParent in some layouts. */
		for (var n = el; n && n !== document.body; n = n.parentElement) {
			var s = window.getComputedStyle(n);
			if (s.display === "none" || s.visibility === "hidden" || s.opacity === "0") {
				return false;
			}
		}
		return true;
	}

	/* The rect of the first run of real text inside `el`, or null when the
	   element holds no text of its own. Leading whitespace is skipped so that
	   markup indentation in a template literal does not read as a text indent. */
	function firstGlyphRect(el) {
		var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
			acceptNode: function (n) {
				return n.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT
				                          : NodeFilter.FILTER_REJECT;
			}
		});
		var node = walker.nextNode();
		if (!node) { return null; }
		/* `block` is the union across every line, kept alongside the first
		   line because a cell aligned by `vertical-align: middle` is positioned
		   by the middle of its whole text block, not by any one line of it. */
		var lead = node.nodeValue.length - node.nodeValue.trimStart().length;
		var range = document.createRange();
		range.setStart(node, lead);
		range.setEnd(node, node.nodeValue.length);
		/* The FIRST line's box, not the union of every line. getBoundingClientRect
		   on a run that wraps returns a box from the top of line one to the
		   bottom of the last, so its `bottom` is the last line's - and the
		   baseline derived from it belongs to whichever line the text happened
		   to end on. Two table headers side by side, "Matched features" over
		   two lines and "p-value (Global)" over two, then disagree by a whole
		   line-height whenever one of them wraps differently at some width.
		   What a reader lines up is the first line of each. */
		var rects = range.getClientRects();
		/* The block extent spans the element's whole contents, not just this
		   first text node. Step 4's table writes "Matched<br>features", which
		   is two text nodes, so measuring the first alone made a two-line
		   header look one line tall - and its middle then sat 7.8px above the
		   middle of "p-value (Global)" beside it, which wraps inside a single
		   node. Both headers are two lines starting on the same top; the
		   disagreement was entirely in the measurement. */
		var block = document.createRange();
		block.selectNodeContents(el);
		var union = block.getBoundingClientRect();
		/* The first LINE's full extent, icons included. A centred action row
		   is an icon and a label centred as one unit, but the unit's first
		   text node starts after the icon - measuring the run alone put the
		   sign-in button's centre 8px right of the box it is centred in
		   exactly, half an icon of phantom misalignment on every icon-led
		   centred line. Full-width rects are the boxes of block wrappers (a
		   grid cell's inner div spans the cell whatever its text does) and
		   are skipped, or every centred cell would report its own column's
		   centre and the check would stop seeing ragged content. */
		var elBox = el.getBoundingClientRect();
		var rlist = block.getClientRects();
		block.detach && block.detach();
		var rect = (rects && rects.length) ? rects[0] : union;
		range.detach && range.detach();
		if (!(rect.width > 0)) { return null; }
		var lineLeft = rect.left, lineRight = rect.right;
		if (rlist && rlist.length) {
			var topMin = Infinity, k;
			for (k = 0; k < rlist.length; k++) {
				if (rlist[k].width > 0 && Math.abs(rlist[k].width - elBox.width) >= 2 &&
				    rlist[k].top < topMin) { topMin = rlist[k].top; }
			}
			if (isFinite(topMin)) {
				var ll = Infinity, rr = -Infinity;
				for (k = 0; k < rlist.length; k++) {
					var rk = rlist[k];
					if (!(rk.width > 0)) { continue; }
					if (Math.abs(rk.width - elBox.width) < 2) { continue; }
					if (rk.top < topMin + 4) {
						if (rk.left < ll) { ll = rk.left; }
						if (rk.right > rr) { rr = rk.right; }
					}
				}
				if (isFinite(ll)) { lineLeft = ll; lineRight = rr; }
			}
		}
		return {
			left: rect.left, right: rect.right, top: rect.top,
			bottom: rect.bottom, width: rect.width,
			blockTop: union.top, blockBottom: union.bottom,
			lineLeft: lineLeft, lineRight: lineRight
		};
	}

	/* Baselines -------------------------------------------------------------
	   The left rail answers "does this text start in the same place across the
	   page". The other half of the question is whether text sitting side by
	   side rests on the same line, and a top edge cannot answer it: two runs of
	   different sizes that share a baseline - a 26px card title beside its 13px
	   count - have tops 13px apart and are correctly aligned, while two runs of
	   the same size 3px apart look broken and have almost the same top. What a
	   reader sees line up is the baseline, so that is what is measured.

	   A Range rect for a text run spans the font's ascent-to-descent box, so
	   subtracting the font's own descent from its bottom lands on the baseline.
	   Chrome reports that descent through canvas text metrics; the measurement
	   is per font shorthand and cached, because it is the same handful of fonts
	   for hundreds of elements. */
	var fontMetrics = {};
	var metricCtx = null;
	function descentFor(el) {
		var cs = window.getComputedStyle(el);
		var font = cs.fontStyle + " " + cs.fontWeight + " " + cs.fontSize + " " + cs.fontFamily;
		if (fontMetrics[font] !== undefined) { return fontMetrics[font]; }
		if (!metricCtx) { metricCtx = document.createElement("canvas").getContext("2d"); }
		metricCtx.font = font;
		var m = metricCtx.measureText("Hxpy");
		/* fontBoundingBoxDescent is the font's own descent, which is what the
		   Range rect's bottom includes. Where it is unavailable the baseline is
		   unknowable, and reporting a guessed one would invent misalignments;
		   NaN propagates and those elements drop out of the check instead. */
		var d = (typeof m.fontBoundingBoxDescent === "number") ? m.fontBoundingBoxDescent : NaN;
		fontMetrics[font] = d;
		return d;
	}

	/* Every visible text-bearing element in the viewport, with the x its glyphs
	   start at. Restricted to what is on screen: the page is one tall column and
	   measuring the parts of it nobody is looking at only adds rails. */
	function measure() {
		var found = [];
		var nodes = document.querySelectorAll(SELECTOR);
		for (var i = 0; i < nodes.length; i++) {
			var el = nodes[i];
			if (!isVisible(el)) { continue; }
			/* A deliberate offset is declared, not detected: data-guides="ignore"
			   on an element or an ancestor takes it out of the measurement
			   entirely - rails, strays and baselines alike. The step cards'
			   disc-led headings sit 37px right of the copy below them because a
			   26px numbered disc leads them; that is the design, and no
			   detection rule for "a heading after a small numbered thing" would
			   earn the false negatives it risks elsewhere. */
			if (el.closest && el.closest("[data-guides='ignore']")) { continue; }
			/* The overlay must not measure itself. Its legend writes the
			   faults as <li> items - elements this selector matches - and the
			   moment any modal put enough text at body level for that group
			   to reach quorum, the tool reported its own report as a fault
			   1259px off a rail. */
			if (el.closest && el.closest("#" + LAYER_ID)) { continue; }
			if (isFlowContinuation(el)) { continue; }
			/* ExtJS builds every form row as a table and wraps the label in a
			   `td.x-field-label-cell`. That cell is a layout box, not a piece of
			   text: it holds one `<label>`, which is itself in SELECTOR and
			   carries the alignment the designer actually chose. Measuring both
			   reported each form row twice - the landing page listed "Data
			   file:" as two separate faults - and measured the wrapper's
			   inherited alignment rather than the label's own.

			   The same goes for every other cell ExtJS builds a form row out
			   of - the body cell, the check-group cell holding the KEGG and
			   Reactome boxes. They are all `x-form...`, they all hold the real
			   control as a child that gets measured on its own, and where the
			   cell itself starts is the table layout's business. Grid cells
			   (`x-grid-cell`) are deliberately not excluded: those hold the
			   data a reader reads down a column. */
			if ((el.tagName === "TD" || el.tagName === "TH") &&
			    /(^|\s)x-(form|field)/.test(
			        typeof el.className === "string" ? el.className : "")) {
				continue;
			}
			/* Action-column cells hold a centred row of icon links, not data
			   text. firstGlyphRect measures the FIRST link's run, which is a
			   fragment of a centred line - the pathway grid's "External
			   links" cells centre KEGG-plus-Reactome as one line whose middle
			   is the column's middle, and the fragment read 24.6px off a
			   header that is centred over them exactly. Fragments of centred
			   lines are not measurable; drop the cells and let the header
			   fall below quorum. */
			if ((el.tagName === "TD" || el.tagName === "TH") &&
			    /action-?col/i.test(typeof el.className === "string" ? el.className : "")) {
				continue;
			}
			/* Right-anchored text has no left rail, but it does have a
			   baseline. Dropping it here entirely - which is what this did -
			   took the whole right-hand summary card on Step 2 out of every
			   measurement, because its wrapper is floated right. The card still
			   sits beside its twin and still has to rest on the same line as
			   it, so it is kept and flagged, and only analyse() skips it. */
			var noLeftRail = isRightAnchored(el);
			var box = el.getBoundingClientRect();
			if (!state.scanAll && (box.bottom < 0 || box.top > window.innerHeight)) { continue; }
			var glyph = firstGlyphRect(el);
			if (!glyph) { continue; }
			var text = glyph;
			/* A button is aligned by its edge, not by its label. Buttons carry
			   20-25px of horizontal padding, so measuring the type inside one
			   reported every button on the page as off-rail while the buttons
			   themselves were sitting on it exactly - four false positives on
			   the landing page alone, which is the number at which a person
			   stops reading the list. */
			var boxAligned = false;
			if (el.matches("a.button, button, .btn, [class*='po-btn']")) {
				glyph = box;
				boxAligned = true;
			}
			/* A list item's visual left edge is its marker, not its text. Both
			   a real `list-style` bullet and the drawn `::before` squares this
			   app uses sit in the padding the text is indented past, so a list
			   correctly hung off the rail reported every item as off it. The
			   border box starts at the marker, which is the edge a reader
			   actually sees line up. */
			if (el.tagName === "LI") {
				glyph = box;
				boxAligned = true;
			}
			/* An ExtJS checkbox label is led by its box the way a list item is
			   led by its bullet: the input sits on the rail and the words follow
			   it, a checkbox and a gap further in. Judged on its own text edge,
			   Step 1's consent label reported 46px off a rail its checkbox sits
			   on exactly. The wrap cell starts where the checkbox does, which is
			   the edge a reader actually sees line up. */
			if (!boxAligned && el.tagName === "LABEL" &&
			    el.classList.contains("x-form-cb-label")) {
				var cbWrap = el.closest && el.closest("td.x-form-cb-wrap");
				if (cbWrap) {
					glyph = cbWrap.getBoundingClientRect();
					boxAligned = true;
				}
			}
			/* The same shape outside ExtJS: the network tools panel writes
			   its rows as <div class=radio><input><label></label></div>, the
			   control drawn in the label's own 23px padding. The row's box
			   sits exactly on the panel's heading rail; measured by glyph,
			   eleven correctly hung rows out-voted their own headings and
			   reported them 23px off a rail that is really the indent. */
			if (!boxAligned && el.tagName === "LABEL" &&
			    el.previousElementSibling && el.previousElementSibling.tagName === "INPUT" &&
			    /^(radio|checkbox)$/.test(el.previousElementSibling.type) &&
			    el.parentElement) {
				glyph = el.parentElement.getBoundingClientRect();
				boxAligned = true;
			}
			/* An element that draws its own accent bar is aligned by that
			   bar, like a button by its edge: the reader lines up the drawn
			   edge, not the type behind it. The example-note callout paints a
			   4px blue bar down its own left side with its text 16px in. Only
			   a bar of 3px or more counts - grid cells and headers carry 1px
			   hairlines that are borders of the lattice, not edges of the
			   element, and box-aligning those would hide genuinely ragged
			   cell text behind trivially aligned boxes. */
			if (!boxAligned && parseFloat(window.getComputedStyle(el).borderLeftWidth) >= 3) {
				glyph = box;
				boxAligned = true;
			}
			/* A heading led by an icon is the same shape as a list item led by
			   a bullet: the icon is the thing on the rail and the words follow
			   it. The Help card's "<i class=fa-info-circle></i> Help" put its
			   icon exactly on the rail its paragraphs use and its text 20.8px
			   further in, which read as a misaligned heading when what a reader
			   sees lined up is the icon. Only a genuinely empty leading element
			   counts - an icon font carries no text of its own - so a heading
			   that merely starts with a <span> of words is untouched. */
			var lead = el.firstElementChild;
			if (!boxAligned && lead && !(lead.textContent || "").trim() &&
			    lead.getBoundingClientRect().left <= glyph.left &&
			    /^(I|SVG|IMG|SPAN)$/.test(lead.tagName)) {
				glyph = box;
				boxAligned = true;
			}
			/* The baseline comes from the text run even where the left edge was
			   taken from the border box above: a button's label is aligned by
			   the button's edge horizontally, but vertically what has to line up
			   with the text beside it is the type inside it. */
			/* An ExtJS grid cell carries no alignment of its own: the <td>
			   inherits `left` while the real `text-align` is written inline on
			   the `.x-grid-cell-inner` div inside it. Reading the cell reported
			   every centred column as ragged - a 3-digit value and a 1-digit
			   one in the same column differ by half the width of two digits,
			   3.6px each way, which is exactly what centring means. 1,712
			   reports on one page, and the four largest buckets were all this. */
			var inner = el.firstElementChild;
			var styled = (inner && inner.classList &&
			              inner.classList.contains("x-grid-cell-inner")) ? inner : el;
			var cs = window.getComputedStyle(styled);
			/* Right-aligned text is aligned by its right edge, and measuring
			   its left one asks a question the design never answered: the
			   Step 3 count columns line up digit for digit on the right, so
			   their headers "Found" and "Significant" - longer words than the
			   numbers under them - start further left by exactly the
			   difference in width, and were reported as 13px and 40px off a
			   rail they are sitting on precisely. A column that mixes the two
			   still reports, because the two edges cluster apart.

			   Centred text is the same argument again: the Step 4 pathway
			   table centres every cell, so a two-word header over a ten-digit
			   p-value starts further right by half the difference and ends
			   further left by the other half. Its axis is the centre, and on
			   the centre the two agree exactly. */
			/* An element measured by its box is not aligned by what its label
			   does inside it. `text-align: center` on a button centres the word
			   on the button and says nothing about where the button sits.
			   For such an element the alignment that matters is the one its
			   PARENT applies to it. Step 4's Heatmap/Line-chart toggle sits in
			   a wrapper that centres it, and it is centred on the chart it
			   switches to within a pixel - 1172 against 1172. Read as a left
			   edge that is 86px off the panel's rail; read as what it is, it
			   is exactly where it belongs. */
			if (boxAligned && el.parentElement) {
				var pa = window.getComputedStyle(el.parentElement).textAlign;
				if (pa === "center" || pa === "right" || pa === "end") {
					/* Same conclusion as isRightAnchored, for the same reason:
					   where this box starts is a consequence of its own width,
					   so it has no left rail to be judged against. It is not
					   dropped from the vertical check - it still has to sit on
					   the line of whatever is beside it. */
					noLeftRail = true;
				}
			}
			var alignedRight = !boxAligned &&
				(cs.textAlign === "right" || cs.textAlign === "end");
			var alignedCentre = !boxAligned && (cs.textAlign === "center");
			/* An ExtJS column header is judged on the horizontal axis only,
			   and a centred one by its box, not its text run. Vertically,
			   grouped headers centre a spanning header's text with 44px of
			   padding while leaf headers sit in the lower row - framework
			   arithmetic that read as three headers 10px off their row's
			   baseline. Horizontally, a sort arrow or menu trigger reserves
			   width beside the text, shifting the run's centre by half the
			   reserve - the sorted column's header reported 8.5px off data
			   it is centred over. The box's centre IS the column's centre,
			   which is what a centred header has to agree with. */
			var isExtHeader = el.classList && el.classList.contains("x-column-header-inner");
			if (alignedCentre && isExtHeader) {
				glyph = box;
			}
			var vMiddle = (el.tagName === "TD" || el.tagName === "TH") &&
				cs.verticalAlign === "middle";
			found.push({
				el: el,
				noLeftRail: noLeftRail,
				edge: alignedRight ? "right" : (alignedCentre ? "centre" : "left"),
				x: alignedRight
					? (glyph.lineRight !== undefined ? glyph.lineRight : glyph.right)
					: (alignedCentre
						? (glyph.lineLeft !== undefined
							? (glyph.lineLeft + glyph.lineRight) / 2
							: (glyph.left + glyph.right) / 2)
						: glyph.left),
				top: glyph.top,
				bottom: glyph.bottom,
				/* A table cell set to `vertical-align: middle` is placed by the
				   centre of its whole text block, so that is its alignment
				   axis. On Step 4 the pathway table's label "Gene expression"
				   wraps to two lines next to a one-line "150 (107)"; both are
				   middle-aligned, which is what puts the number opposite the
				   middle of the label - correctly - and leaves their first
				   lines 7.8px apart. Judged on baselines that reads as a
				   fault, and moving either one would break the centring that
				   is actually right. */
				vedge: vMiddle ? "middle" : "baseline",
				baseline: isExtHeader ? NaN : (vMiddle
					? (glyph.blockTop + glyph.blockBottom) / 2
					: text.bottom - descentFor(el)),
				/* Two runs are peers when a reader would expect them to sit on
				   one line: same element type, same size, same weight. A
				   heading is not obliged to share a baseline with the caption
				   beside it, and checking every pair against every other turns
				   a page's ordinary vertical variety into a list of faults. */
				peer: el.tagName + "/" + cs.fontSize + "/" + cs.fontWeight +
					"/" + (vMiddle ? "middle" : "baseline"),
				label: (el.innerText || "").trim().replace(/\s+/g, " ").slice(0, 34)
			});
		}
		return found;
	}

	/* Cluster the measured x positions into rails. Sorted first so a single
	   forward pass is enough: any x within tolerance of the cluster's own
	   origin joins it, and the first x too far away opens the next cluster. */
	function railsFrom(hits) {
		var xs = hits.slice().sort(function (a, b) { return a.x - b.x; });
		var rails = [];
		var current = null;
		for (var i = 0; i < xs.length; i++) {
			if (!current || xs[i].x - current.x > RAIL_TOLERANCE) {
				current = { x: xs[i].x, members: [] };
				rails.push(current);
			}
			current.members.push(xs[i]);
		}
		return rails;
	}

	/* The column an element belongs to ---------------------------------------
	   The first draft of this overlay clustered every left edge on the page into
	   one flat list and reported nineteen "off-rail" items on a page that had
	   about three things wrong with it. Nearly all of the noise was text that is
	   *supposed* to start at a different x: the six header menu items sit in a
	   row, and the three "How it works" cards are three columns. Comparing those
	   against each other asks the wrong question.

	   The question worth asking is whether text stacked *vertically inside one
	   column* shares a left edge. So each element is keyed to the nearest
	   ancestor that is an item of a flex or grid container - that ancestor is
	   the column - and alignment is judged within a key, never across keys. */
	/* An ExtJS grid declares its columns too, and more usefully than a table:
	   the header carries `id="gridcolumn-1031"` and every cell beneath it
	   carries `class="... x-grid-cell-gridcolumn-1031"`. That link is the only
	   thing tying a header div to the cells it labels - they are in different
	   elements entirely, the header in the grid's header bar and the cells in
	   its item table - and without it a header and its column can never be
	   compared. */
	var gridColumnKeys = {};
	function extGridColumnKey(el) {
		if (!el.closest) { return null; }
		var id = null;
		var hdr = el.closest(".x-column-header");
		if (hdr && hdr.id) {
			id = hdr.id;
		} else {
			var cell = el.closest("td.x-grid-cell");
			var cls = cell && typeof cell.className === "string" ? cell.className : "";
			var m = cls.match(/x-grid-cell-([A-Za-z]+-\d+)/);
			if (m) { id = m[1]; }
		}
		if (!id) { return null; }
		if (!gridColumnKeys[id]) { gridColumnKeys[id] = { extColumn: id }; }
		return gridColumnKeys[id];
	}

	function columnKeyFor(el) {
		var gridCol = extGridColumnKey(el);
		if (gridCol) { return gridCol; }
		/* A table already declares its columns, so use them rather than
		   inferring them from geometry. Without this, a row's leader is
		   whichever of its cells is leftmost *and has text*, so a header row
		   whose first cell is deliberately empty - the badge column of the
		   Step 3 database summary - contributed its second cell as a leader and
		   was reported as sitting 42px right of the badges below it. Two cells
		   in different columns were never each other's business; two cells in
		   the same column always are. */
		var cell = el.closest && el.closest("td,th");
		if (cell) {
			var table = cell.closest("table");
			/* ExtJS lays forms out in tables, and a form is not a table: its
			   label cell and field cell are one row of one thing, so keying
			   them per column would hide a form row that has drifted off the
			   card's rail behind a quorum of one. Only real data tables - the
			   ones this app writes itself, with no framework classes - get
			   column keys. */
			if (table && !/(^|\s)x-/.test(typeof table.className === "string" ? table.className : "")) {
				if (!table.__paGuidesCols) { table.__paGuidesCols = {}; }
				var idx = cell.cellIndex;
				if (!table.__paGuidesCols[idx]) {
					/* A per-column token: it only has to be a stable, unique
					   object to key the group Map with. */
					table.__paGuidesCols[idx] = { table: table, column: idx };
				}
				return table.__paGuidesCols[idx];
			}
		}
		for (var n = el; n && n !== document.body; n = n.parentElement) {
			/* An out-of-flow box is its own alignment context at keying time,
			   not only as a fold barrier. ExtJS lays its box containers out
			   with `position: absolute` wrappers, so the "Selected omics"
			   column's title walked straight through its whole column to the
			   bordered form body and was judged against a rail three hundred
			   pixels to its left. The fold already refuses to cross these
			   boundaries; keying across them asks the same wrong question. */
			var ncs = window.getComputedStyle(n);
			if (ncs.position === "absolute" || ncs.position === "fixed") {
				return n;
			}
			var p = n.parentElement;
			if (!p) { break; }
			var ps = window.getComputedStyle(p);
			var d = ps.display;
			if (d === "flex" || d === "inline-flex" || d === "grid" || d === "inline-grid") {
				return n;
			}
			/* A box that insets its own contents is its own alignment context.
			   The hero's AI panel carries a 3px left border and 18px of padding,
			   so its paragraph starts 21px right of the card rail - correctly,
			   because it is inside a panel, and the panel's edge is the thing on
			   the rail. Judged against the card it looked like two more
			   misalignments; judged against the panel it is what it should be.
			   Cross-surface agreement is still checked: draw() collapses rails
			   that land within tolerance of each other into a single line. */
			if (parseFloat(ps.paddingLeft) > 0 || parseFloat(ps.borderLeftWidth) > 0) {
				return p;
			}
		}
		return document.getElementById("mainViewCenterPanel") || document.body;
	}

	/* Right-anchored containers align on their right edge, by construction. The
	   step-action toolbar is `position: fixed` with a `right` offset and
	   `left: auto`, so where its leftmost button starts is a consequence of how
	   wide the labels happen to be - a number that changes with the text and was
	   never anybody's left rail. */
	function isRightAnchored(el) {
		/* A toolbar packs its controls along a row, so where any one of them
		   starts is decided by the widths of the ones before it. Step 3's
		   metabolite grid carries a "Select a step:" combo in its bottom
		   toolbar, after a separator; its label was judged against the page's
		   left rail 92px away, which no arrangement of that toolbar could ever
		   satisfy. Same conclusion as a right-anchored box, same reason. */
		if (el.closest && el.closest(".x-toolbar, [role='toolbar']")) {
			return true;
		}
		for (var n = el; n && n !== document.body; n = n.parentElement) {
			var s = window.getComputedStyle(n);
			if ((s.position === "fixed" || s.position === "absolute") &&
			    s.left === "auto" && s.right !== "auto") {
				return true;
			}
			if (s.float === "right") { return true; }
			/* `left: auto` is not enough on its own here. The step-action
			   toolbar is anchored by `right` in the stylesheet, but ExtJS also
			   writes an inline `left` onto it from JavaScript, so its computed
			   left is a pixel value and the test above misses it. What it
			   cannot fake is the packing direction: a row-reverse flex row
			   fills from its right edge, which makes its left edge a function
			   of how wide the labels happen to be. */
			if (s.display.indexOf("flex") >= 0 && s.flexDirection === "row-reverse") {
				return true;
			}
			/* `justify-content: flex-end` packs a row from its right edge the
			   same way row-reverse does. The example dialog's "Load this
			   dataset" sits in a flex-end actions row at the card's bottom
			   right; judged on its left edge it reported 544px off a rail no
			   right-packed control could ever sit on - ten times, once per
			   card. */
			if (s.display.indexOf("flex") >= 0 &&
			    /^(flex-end|end|right)$/.test(s.justifyContent)) {
				return true;
			}
		}
		/* A stretching sibling earlier in a flex row decides where everything
		   after it starts. The pathway panel's search row is an input with
		   flex:1 and its button after it, so the button's left edge is
		   wherever the input chose to stop - a function of the panel's width,
		   not a rail any stylesheet placed. Judged on that edge it reported
		   1.9px off a rail it was never aimed at, on every pathway a user
		   painted.

		   Deliberately checked on the element itself and NOT on its
		   ancestors: a *container* placed after a stretcher can still have a
		   deterministic width and real rails inside it, and walking this test
		   up the tree would silently drop everything in it from measurement -
		   the exact regression class the probe battery exists to catch. */
		var flexParent = el.parentElement;
		if (flexParent) {
			var fp = window.getComputedStyle(flexParent);
			if (fp.display.indexOf("flex") >= 0 &&
			    fp.flexDirection.indexOf("row") === 0) {
				for (var sib = el.previousElementSibling; sib;
				     sib = sib.previousElementSibling) {
					if (parseFloat(window.getComputedStyle(sib).flexGrow) > 0) {
						return true;
					}
				}
			}
		}
		return false;
	}

	/* Horizontal rails: the baselines that side-by-side text rests on ---------
	   The mirror of analyse(). Where that asks "does text stacked in a column
	   share a left edge", this asks "does text placed across a row share a
	   line". Both are needed: the Step 2 summary cards sat on one left rail
	   while their headings rested 4px apart vertically, which no vertical rule
	   can show.

	   Two guards keep it honest, and both were needed to stop it inventing
	   faults. Only *peers* are compared - same tag, size and weight - because a
	   title and the caption beside it share no baseline by design. And only
	   text that is genuinely beside other text is compared: members whose x
	   ranges overlap are a wrapped run or a nested pair, not a row, and a
	   paragraph's second line would otherwise be reported as failing to align
	   with its own first. */
	var rowKeySeq = 0;
	function analyseBaselines(hits) {
		var usable = hits.filter(function (h) { return isFinite(h.baseline); });
		var byTop = usable.slice().sort(function (a, b) { return a.top - b.top; });
		var bands = [];
		byTop.forEach(function (m) {
			var band = null;
			for (var i = bands.length - 1; i >= 0; i--) {
				if (m.top < bands[i].bottom - 2) { band = bands[i]; break; }
			}
			if (!band) { band = { bottom: m.bottom, items: [] }; bands.push(band); }
			band.bottom = Math.max(band.bottom, m.bottom);
			band.items.push(m);
		});

		var rows = [];
		bands.forEach(function (band) {
			var byPeer = new Map();
			band.items.forEach(function (m) {
				/* A table cell's row-mates are the cells of its own <tr>, and
				   nothing else. Banding is geometric, and two unrelated tables
				   can occupy the same band: Step 3 renders the pathway grid and
				   the metabolite-class grid into the page at once, and their
				   rows interleaved in y, so every pathway row was judged
				   against a compound row 10px above it. 4193 reported faults,
				   none of them real, and the two tables have no edge in common
				   to be aligned on in the first place. */
				var tr = m.el.closest && m.el.closest("tr");
				var key = m.peer;
				if (tr) {
					if (!tr.__paGuidesRowKey) { tr.__paGuidesRowKey = { id: ++rowKeySeq }; }
					key += "#row" + tr.__paGuidesRowKey.id;
				}
				if (!byPeer.has(key)) { byPeer.set(key, []); }
				byPeer.get(key).push(m);
			});
			byPeer.forEach(function (members) {
				if (members.length < RAIL_QUORUM) { return; }
				var across = [];
				members.slice().sort(function (a, b) { return a.x - b.x; }).forEach(function (m) {
					var last = across[across.length - 1];
					var r = m.el.getBoundingClientRect();
					if (!last || r.left >= last.right - 2) {
						across.push({ hit: m, right: r.right });
					}
				});
				if (across.length < RAIL_QUORUM) { return; }
				var items = across.map(function (a) { return a.hit; });
				var sorted = items.slice().sort(function (a, b) { return a.baseline - b.baseline; });
				var clusters = [];
				var cur = null;
				sorted.forEach(function (m) {
					if (!cur || m.baseline - cur.baseline > RAIL_TOLERANCE) {
						cur = { baseline: m.baseline, members: [] };
						clusters.push(cur);
					}
					cur.members.push(m);
				});
				clusters.sort(function (a, b) {
					return b.members.length - a.members.length || a.baseline - b.baseline;
				});
				rows.push({
					baseline: clusters[0].baseline,
					onRail: clusters[0].members.length,
					strays: clusters.slice(1).reduce(function (acc, c) {
						return acc.concat(c.members);
					}, [])
				});
			});
		});
		return rows;
	}

	/* Elements whose glyph boxes overlap vertically are side by side, so their
	   left edges carry no alignment obligation to one another. Only the leftmost
	   of each such row establishes where that row starts, and it is those row
	   leaders that a column's rail is measured from. */
	function rowLeaders(members) {
		var byTop = members.slice().sort(function (a, b) { return a.top - b.top; });
		var rows = [];
		byTop.forEach(function (m) {
			var row = null;
			for (var i = rows.length - 1; i >= 0; i--) {
				/* Overlap test against the row's vertical extent rather than
				   against a fixed line-height: a 52px hero title and a 13px
				   caption in the same row have wildly different heights. */
				if (m.top < rows[i].bottom - 2) { row = rows[i]; break; }
			}
			if (!row) {
				row = { bottom: m.bottom, items: [] };
				rows.push(row);
			}
			row.bottom = Math.max(row.bottom, m.bottom);
			row.items.push(m);
		});
		return rows.map(function (r) {
			return r.items.reduce(function (a, b) { return b.x < a.x ? b : a; });
		});
	}

	/* Per-column analysis: the rail is the left edge the most rows in that
	   column start on, and anything not on it is off-rail. Ties go to the
	   leftmost, because when a column is split evenly the outdented text is
	   almost always the one that is right and the indented one the accident. */
	function analyse(hits) {
		var root = document.getElementById("mainViewCenterPanel") || document.body;
		var groups = new Map();
		groups.set(root, []);
		hits.forEach(function (h) {
			if (h.noLeftRail) { return; }
			var key = columnKeyFor(h.el);
			if (!groups.has(key)) { groups.set(key, []); }
			groups.get(key).push(h);
		});

		/* A flex item holding a single row of text is not a column - it is one
		   thing. Left as its own group it declares a rail nothing else is
		   measured against, and the six header menu items alone added six such
		   rails to a page with one left edge. Folding each into the nearest
		   enclosing group puts side-by-side items back in a single row, where
		   rowLeaders() correctly keeps only the leftmost and the rest stop
		   being lines. Repeated to a fixed point because a fold can leave the
		   parent itself thin. */
		/* Deepest first, and that ordering is the whole correctness of this loop.
		   The hero's AI panel is a padded box holding a paragraph and a flex row
		   of three verbs; the paragraph keys to the panel, each verb keys to
		   itself. Folded in document order the panel is judged while it still
		   holds only that one paragraph, so it reads as thin, dissolves into the
		   hero, and the verbs follow it there - after which the panel's contents
		   are measured against the card rail 21px away and reported as two
		   misalignments that were never misaligned. Folding the verbs into the
		   panel first leaves the panel two rows deep, which is what it is. */
		function depthOf(el) {
			var d = 0;
			for (var n = el; n; n = n.parentElement) { d++; }
			return d;
		}
		var changed = true;
		function foldToFixedPoint() {
			changed = true;
		while (changed) {
			changed = false;
			Array.from(groups.keys()).sort(function (a, b) {
				return depthOf(b) - depthOf(a);
			}).forEach(function (key) {
				var members = groups.get(key);
				if (!members || key === root) { return; }
				if (rowLeaders(members).length >= 2) { return; }
				/* When a thin group dissolves out of a key that paints its own
				   surface, what the parent column can judge is the surface's
				   edge, not the type inset within it. The omics pills are
				   painted boxes sitting exactly on the panel rail with their
				   h4 10px inside; judged on the type, four correctly placed
				   pills disagree with the title beside them, and judged not at
				   all a drifted pill goes unreported. Fold them, but aligned
				   to the box - the same argument that aligns a button by its
				   edge. A member that is itself the key is already box-aligned
				   by measure() and keeps its own x. */
				if (key.nodeType === 1) {
					var ks = window.getComputedStyle(key);
					if (parseFloat(ks.borderLeftWidth) > 0 ||
					    ks.backgroundImage !== "none" ||
					    (ks.backgroundColor && ks.backgroundColor !== "rgba(0, 0, 0, 0)" &&
					     ks.backgroundColor !== "transparent")) {
						/* Unconditionally: a full-width pill (the omics chips
						   stretch to their column below 1280px) still aligns by
						   its painted edge, and no local geometry separates it
						   from a panel's header band, whose type aligns to the
						   body inset instead - both are flush painted children
						   of their context. The one pattern where the box is
						   the wrong reading, the lateralOptionsPanel header,
						   declares itself data-guides="ignore" at its factory;
						   a rule cannot know what only the design language
						   does. */
						var keyRect = key.getBoundingClientRect();
						members.forEach(function (m) {
							if (m.el !== key) { m.x = keyRect.left; }
						});
					}
				}
				for (var n = key.parentElement; n; n = n.parentElement) {
					if (groups.has(n)) {
						groups.get(n).push.apply(groups.get(n), members);
						groups.delete(key);
						changed = true;
						return;
					}
					/* A fold must not cross out of the flow. The results steps
					   put their contents list in `nav.pa-toc`, which is
					   `position: fixed` down the left margin, and each of its
					   items is a lone flex item - thin, so the loop above folds
					   it upward looking for company. The only group above it is
					   the page column, 253px to the right, so three correctly
					   stacked nav links were reported as three 253px
					   misalignments against content they are not beside and
					   have no edge in common with. An out-of-flow box is its own
					   alignment context: fold into it, and let its own items be
					   judged against each other. */
					var ns = window.getComputedStyle(n);
					/* A left border marks a distinct surface, and the fold must
					   not cross one either. The hero's AI panel carries a 3px
					   left border and 18px of padding, so its prose starts 21px
					   inside the card - correctly, because the panel's edge is
					   the thing on the card's rail. columnKeyFor already keys it
					   to the panel; the fold then walked straight past the panel
					   to the card and reported the panel's own paragraph as 22px
					   off. Judged against the panel, it is exactly on it. */
					/* A painted background bounds a surface as surely as a
					   border draws one. Step 1's AI callout is a padded plate
					   whose gradient starts exactly on the section rail and
					   whose prose starts 22px inside it - columnKeyFor already
					   keys that prose to the plate, but the fold walked out of
					   it and reported the inset against the rail outside. A box
					   that paints its own ground is its own alignment context,
					   same as one that draws its own edge. */
					if (n !== root && (ns.position === "fixed" || ns.position === "absolute" ||
					    parseFloat(ns.borderLeftWidth) > 0 ||
					    ns.backgroundImage !== "none" ||
					    (ns.backgroundColor && ns.backgroundColor !== "rgba(0, 0, 0, 0)" &&
					     ns.backgroundColor !== "transparent"))) {
						groups.set(n, members);
						groups.delete(key);
						changed = true;
						return;
					}
				}
			});
		}
		}
		foldToFixedPoint();

		/* Second pass: a standing surface's own edge joins its parent context.
		   The contents of a painted card are judged inside it - that is what
		   the groups above establish - but where the card ITSELF sits was
		   never judged by anyone, and it is the card's edge, not its text,
		   that a reader lines up against the column. The "Selected omics"
		   title is padded 10px so its type lands exactly on the omic cards'
		   edges below it; with the cards standing as their own groups the
		   title was a loner, climbed out of its column, and reported 270px
		   off the form rail while sitting precisely where it was designed
		   to. The synthetic member carries no baseline - NaN drops it from
		   the vertical check, which compares type, not boxes. */
		var synth = [];
		groups.forEach(function (members, key) {
			if (!key || key.nodeType !== 1 || key === root) { return; }
			if (rowLeaders(members).length < 2) { return; }
			var ks = window.getComputedStyle(key);
			var painted = parseFloat(ks.borderLeftWidth) > 0 ||
				ks.backgroundImage !== "none" ||
				(ks.backgroundColor && ks.backgroundColor !== "rgba(0, 0, 0, 0)" &&
				 ks.backgroundColor !== "transparent");
			if (!painted) { return; }
			if (isRightAnchored(key)) { return; }
			if (key.closest && key.closest("[data-guides='ignore']")) { return; }
			var kr = key.getBoundingClientRect();
			if (!(kr.width > 0)) { return; }
			synth.push({ key: key, rect: kr });
		});
		synth.forEach(function (s) {
			var pkey = s.key.parentElement ? columnKeyFor(s.key.parentElement) : root;
			if (pkey === s.key) { return; }
			/* A box corroborates a neighbourhood; it does not found one. With
			   no group at its parent key the box has no designed rail-mates -
			   the help panel's edge sits where the layout's column split puts
			   it - and a synthetic member laddering out of an empty context
			   reported that split as a 914px fault. */
			if (!groups.has(pkey)) { return; }
			groups.get(pkey).push({
				el: s.key, noLeftRail: false, edge: "left",
				x: s.rect.left, top: s.rect.top, bottom: s.rect.bottom,
				vedge: "baseline", baseline: NaN, peer: "surface-box",
				label: "[box] " + (s.key.id || (typeof s.key.className === "string" &&
					s.key.className ? s.key.className.split(/\s+/)[0] : s.key.tagName.toLowerCase()))
			});
		});
		foldToFixedPoint();

		var columns = [];
		groups.forEach(function (members, key) {
			/* Axes are only comparable within one edge family: a left edge, a
			   centre and a right edge are three different questions, and one
			   vote across them elected the sign-in dialog's rail from a mix
			   of field edges and button centres - a number nothing in the
			   dialog was designed against, with every centred row 50-160px
			   "off" it. Each family gets its own rows, quorum and rail. */
			["left", "centre", "right"].forEach(function (edgeKind) {
			var fam = members.filter(function (m) { return m.edge === edgeKind; });
			if (!fam.length) { return; }
			var leaders = rowLeaders(fam);
			/* One row is one thing, and one thing is always aligned with
			   itself. Anything still thin after the fold above has no enclosing
			   group to be judged against, so it is reported as neither a rail
			   nor a stray rather than as a rail of its own. */
			if (leaders.length < RAIL_QUORUM) { return; }
			var rails = railsFrom(leaders).sort(function (a, b) {
				return b.members.length - a.members.length || a.x - b.x;
			});
			if (!rails.length) { return; }
			var rail = rails[0];
			columns.push({
				key: key,
				rail: rail.x,
				onRail: rail.members.length,
				rows: leaders.length,
				strays: rails.slice(1).reduce(function (acc, r) { return acc.concat(r.members); }, [])
			});
			});
		});
		return columns;
	}

	/* The page column's own edges, read off the one ancestor every step shares.
	   Drawn whether or not any text lands on them, because "the content box is
	   here and the text is 80px inside it" is a thing worth seeing. */
	function columnEdges() {
		var panel = document.getElementById("mainViewCenterPanel");
		if (!panel) { return null; }
		var r = panel.getBoundingClientRect();
		var s = window.getComputedStyle(panel);
		return {
			left: r.left + parseFloat(s.paddingLeft || 0),
			right: r.right - parseFloat(s.paddingRight || 0)
		};
	}

	function ensureStyle() {
		if (document.getElementById(STYLE_ID)) { return; }
		var css = [
			"#" + LAYER_ID + "{position:fixed;inset:0;z-index:2147483000;pointer-events:none;}",
			/* Lines are 1px and drawn with a box-shadow rather than a wider
			   border: a 2px rule is itself two pixels of ambiguity about where
			   the rail is, which defeats the point of the tool. */
			"#" + LAYER_ID + " .pa-g-line{position:absolute;top:0;bottom:0;width:1px;}",
			"#" + LAYER_ID + " .pa-g-rail{background:rgba(214,31,31,.85);}",
			"#" + LAYER_ID + " .pa-g-stray{background:rgba(214,31,31,.95);" +
				"box-shadow:0 0 0 1px rgba(255,255,255,.55);}",
			"#" + LAYER_ID + " .pa-g-edge{background:rgba(214,31,31,.30);}",
			/* Horizontal rails run the width of the viewport. They are drawn in
			   the same red so that one glance answers "is anything wrong"
			   without a colour key, and distinguished by direction. */
			"#" + LAYER_ID + " .pa-g-hline{position:absolute;left:0;right:0;height:1px;}",
			"#" + LAYER_ID + " .pa-g-baseline{background:rgba(214,31,31,.55);}",
			"#" + LAYER_ID + " .pa-g-hstray{background-image:linear-gradient(" +
				"to right,rgba(214,31,31,1) 0 6px,transparent 6px 12px);" +
				"background-size:12px 1px;background-repeat:repeat-x;}",
			/* Dashes mark a rail that only one element sits on. A solid line is
			   a rail the page agrees on; a dashed one is a candidate. */
			"#" + LAYER_ID + " .pa-g-stray{background-image:linear-gradient(" +
				"to bottom,rgba(214,31,31,1) 0 6px,transparent 6px 12px);" +
				"background-size:1px 12px;background-repeat:repeat-y;background-color:transparent;}",
			"#" + LAYER_ID + " .pa-g-tag{position:absolute;font:11px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;" +
				"color:#fff;background:rgba(214,31,31,.92);padding:1px 5px;border-radius:3px;white-space:nowrap;" +
				"transform:translateX(1px);}",
			"#" + LAYER_ID + " .pa-g-legend{position:absolute;right:12px;bottom:12px;max-width:340px;" +
				"font:11px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:#fff;background:rgba(20,20,22,.92);" +
				"padding:9px 11px;border-radius:6px;box-shadow:0 6px 22px rgba(0,0,0,.35);}",
			"#" + LAYER_ID + " .pa-g-legend b{color:#ff8a8a;font-weight:600;}",
			"#" + LAYER_ID + " .pa-g-legend .ok{color:#7ee08a;}",
			"#" + LAYER_ID + " .pa-g-legend .bad{color:#ff8a8a;}",
			"#" + LAYER_ID + " .pa-g-legend ul{margin:5px 0 0;padding-left:14px;}"
		].join("");
		var tag = document.createElement("style");
		tag.id = STYLE_ID;
		tag.textContent = css;
		document.head.appendChild(tag);
	}

	function line(cls, x) {
		var d = document.createElement("div");
		d.className = "pa-g-line " + cls;
		d.style.left = Math.round(x) + "px";
		return d;
	}

	function hline(cls, y) {
		var d = document.createElement("div");
		d.className = "pa-g-hline " + cls;
		d.style.top = Math.round(y) + "px";
		return d;
	}

	/* draw() runs inside a requestAnimationFrame callback, where a throw is
	   swallowed by everything except the console - and the visible result is an
	   overlay that switches on and draws nothing, which reads as "the page is
	   fine" rather than as "the tool is broken". The two are opposite
	   conclusions, so the failure is made loud. */
	function draw() {
		try {
			drawUnguarded();
		} catch (e) {
			state.raf = 0;
			if (window.console && console.error) {
				console.error("[paGuides] draw failed:", e && e.stack || e);
			}
		}
	}

	function drawUnguarded() {
		state.raf = 0;
		var layer = document.getElementById(LAYER_ID);
		if (!layer) { return; }
		layer.textContent = "";

		var hits = measure();
		var columns = analyse(hits);
		var edges = columnEdges();

		if (edges) {
			layer.appendChild(line("pa-g-edge", edges.left));
			layer.appendChild(line("pa-g-edge", edges.right));
		}

		/* Rails shared by several columns collapse to one line. Three cards in a
		   row each have their own rail, but the page only has one left edge, and
		   drawing it three times over would suggest otherwise. */
		var drawn = [];
		var strays = [];
		columns.forEach(function (col) {
			if (!drawn.some(function (x) { return Math.abs(x - col.rail) <= RAIL_TOLERANCE; })) {
				drawn.push(col.rail);
				layer.appendChild(line("pa-g-rail", col.rail));
			}
			col.strays.forEach(function (m) {
				strays.push(m);
				layer.appendChild(line("pa-g-stray", m.x));
				/* Label the offender where it sits, so it is identifiable
				   without counting lines back to a legend. */
				var tag = document.createElement("div");
				tag.className = "pa-g-tag";
				tag.style.left = Math.round(m.x) + "px";
				tag.style.top = Math.max(2, Math.round(m.top) - 16) + "px";
				tag.textContent = "+" + Math.round(m.x - col.rail) + "  " + m.label;
				layer.appendChild(tag);
			});
		});

		/* Horizontal rails are drawn only where a row disagrees. A line under
		   every aligned row would cover the page in red and hide the vertical
		   rules, which are the ones a reader is usually looking for; a row that
		   agrees needs no line to say so. */
		var baseStrays = [];
		analyseBaselines(hits).forEach(function (row) {
			if (!row.strays.length) { return; }
			layer.appendChild(hline("pa-g-baseline", row.baseline));
			row.strays.forEach(function (m) {
				baseStrays.push(m);
				layer.appendChild(hline("pa-g-hstray", m.baseline));
				var tag = document.createElement("div");
				tag.className = "pa-g-tag";
				tag.style.left = Math.round(m.x) + "px";
				tag.style.top = Math.round(m.baseline) + 2 + "px";
				tag.textContent = "↕" + (m.baseline > row.baseline ? "+" : "") +
					Math.round(m.baseline - row.baseline) + "  " + m.label;
				layer.appendChild(tag);
			});
		});

		var legend = document.createElement("div");
		legend.className = "pa-g-legend";
		drawn.sort(function (a, b) { return a - b; });
		legend.innerHTML =
			"<b>alignment guides</b> &nbsp;ctrl+alt+G<br>" +
			"viewport " + window.innerWidth + "px" +
			(edges ? " &nbsp;column " + Math.round(edges.left) + "–" + Math.round(edges.right) : "") +
			"<br>rails " + drawn.map(function (x) { return Math.round(x); }).join(", ") +
			"<br><span class='" + (strays.length ? "bad" : "ok") + "'>" +
			(strays.length ? strays.length + " off-rail" : "all text on rail") + "</span>" +
			(strays.length ? "<ul>" + strays.slice(0, 8).map(function (m) {
				return "<li>x" + Math.round(m.x) + " " + m.label + "</li>";
			}).join("") + "</ul>" : "") +
			"<br><span class='" + (baseStrays.length ? "bad" : "ok") + "'>" +
			(baseStrays.length ? baseStrays.length + " off-baseline" : "all rows on baseline") +
			"</span>" +
			(baseStrays.length ? "<ul>" + baseStrays.slice(0, 8).map(function (m) {
				return "<li>y" + Math.round(m.baseline) + " " + m.label + "</li>";
			}).join("") + "</ul>" : "");
		layer.appendChild(legend);

		/* The console line is the part that survives a screenshot: it is how a
		   verification run records what the overlay showed at the moment it was
		   looked at. */
		if (window.console && console.log) {
			console.log("[paGuides] " + window.innerWidth + "px  rails=" +
				drawn.map(function (x) { return Math.round(x); }).join(",") +
				"  offRail=" + (strays.length
					? strays.map(function (m) { return Math.round(m.x) + ":" + m.label; }).join(" | ")
					: "none") +
				"  offBaseline=" + (baseStrays.length
					? baseStrays.map(function (m) { return Math.round(m.baseline) + ":" + m.label; }).join(" | ")
					: "none"));
		}
	}

	/* rAF while the tab is visible, a timer when it is not. Chrome throttles
	   requestAnimationFrame to nothing in a background tab, and this overlay is
	   read as often through browser automation - where the tab under test is
	   frequently not the foreground one - as it is by a person looking at it.
	   Scheduled on rAF alone it switched on, appended nothing, and reported no
	   error, which is indistinguishable from a page with no misalignments. */
	function schedule() {
		if (state.raf || state.timer) { return; }
		if (document.visibilityState === "hidden") {
			state.timer = window.setTimeout(function () { state.timer = 0; draw(); }, 0);
		} else {
			state.raf = window.requestAnimationFrame(draw);
		}
	}

	function on() {
		if (state.on) { return; }
		ensureStyle();
		var layer = document.createElement("div");
		layer.id = LAYER_ID;
		document.body.appendChild(layer);
		state.on = true;
		window.addEventListener("scroll", schedule, true);
		window.addEventListener("resize", schedule);
		schedule();
	}

	function off() {
		if (!state.on) { return; }
		var layer = document.getElementById(LAYER_ID);
		if (layer) { layer.parentNode.removeChild(layer); }
		state.on = false;
		window.removeEventListener("scroll", schedule, true);
		window.removeEventListener("resize", schedule);
		if (state.raf) { window.cancelAnimationFrame(state.raf); state.raf = 0; }
		if (state.timer) { window.clearTimeout(state.timer); state.timer = 0; }
	}

	/* A one-line name for a column key, for report(). A stray is only
	   diagnosable when the report says which column judged it: "22px off
	   rail 140" reads as a page fault until the key shows the element was
	   measured against the wrong neighbourhood, which is a tool fault. */
	function keyDesc(key) {
		if (!key) { return "?"; }
		if (key.extColumn) { return "extcol:" + key.extColumn; }
		if (key.table) { return "tablecol:" + (key.table.id || "anon") + ":" + key.column; }
		if (key.nodeType === 1) {
			return key.tagName.toLowerCase() + (key.id ? "#" + key.id : "") +
				((typeof key.className === "string" && key.className)
					? "." + key.className.split(/\s+/).slice(0, 2).join(".") : "");
		}
		return String(key);
	}

	var api = {
		on: on,
		off: off,
		toggle: function () { state.on ? off() : on(); },
		/* Exposed so a verification run can read the numbers instead of
		   squinting at the lines: returns the rails and the off-rail members
		   without needing the overlay to be visible.

		   It reports what draw() draws, which means analyse() and not
		   railsFrom(). The first version of this called railsFrom(measure())
		   directly - one flat clustering of every left edge on the page - and
		   that is precisely the question this file spends thirty lines
		   explaining is the wrong one. On a results step it answered with
		   thirty-odd "rails", most of them a table column or a legend entry
		   that is supposed to start where it does, and no answer at all about
		   which text is off its own column's edge. A tool read by automation
		   has to report the faults, not the geometry.

		   `opts.all` lifts the viewport restriction. measure() looks only at
		   what is on screen because the landing page is one tall column and
		   rails from its unseen parts are just more lines. Steps 2 to 4 are
		   different: they are long results pages whose interesting blocks -
		   the pathway table, the metabolite panels - are usually below the
		   fold, and a viewport-only report on one of those measures the
		   header and calls the page clean. */
		report: function (opts) {
			var prev = state.scanAll;
			state.scanAll = !!(opts && opts.all);
			try {
				var hits = measure();
				var columns = analyse(hits);
				var strays = [];
				columns.forEach(function (col) {
					col.strays.forEach(function (m) {
						strays.push({
							x: Math.round(m.x * 10) / 10,
							edge: m.edge,
							off: Math.round((m.x - col.rail) * 10) / 10,
							rail: Math.round(col.rail * 10) / 10,
							tag: m.el.tagName.toLowerCase(),
							cls: (typeof m.el.className === "string" ? m.el.className : "").slice(0, 60),
							label: m.label,
							col: keyDesc(col.key)
						});
					});
				});
				var vStrays = [];
				analyseBaselines(hits).forEach(function (row) {
					row.strays.forEach(function (m) {
						vStrays.push({
							off: Math.round((m.baseline - row.baseline) * 10) / 10,
							baseline: Math.round(row.baseline * 10) / 10,
							tag: m.el.tagName.toLowerCase(),
							cls: (typeof m.el.className === "string" ? m.el.className : "").slice(0, 60),
							label: m.label
						});
					});
				});
				return {
					viewport: window.innerWidth,
					column: columnEdges(),
					columns: (opts && opts.columns) ? columns.map(function (c) {
						return { key: keyDesc(c.key), rail: Math.round(c.rail * 10) / 10,
						         rows: c.rows, onRail: c.onRail, strays: c.strays.length };
					}) : undefined,
					measured: hits.length,
					rails: columns.map(function (c) { return Math.round(c.rail); })
						.filter(function (x, i, a) { return a.indexOf(x) === i; })
						.sort(function (a, b) { return a - b; }),
					offRail: strays.length,
					strays: strays.sort(function (a, b) { return Math.abs(b.off) - Math.abs(a.off); }),
					offBaseline: vStrays.length,
					baselineStrays: vStrays.sort(function (a, b) {
						return Math.abs(b.off) - Math.abs(a.off);
					})
				};
			} finally {
				state.scanAll = prev;
			}
		}
	};

	window.paGuides = api;

	document.addEventListener("keydown", function (e) {
		/* Ctrl+Alt+G. Not Cmd on macOS: Cmd+Alt+G is Chrome's own "find
		   previous", and a devtool that fights the browser gets turned off. */
		if (e.ctrlKey && e.altKey && (e.key === "g" || e.key === "G")) {
			e.preventDefault();
			api.toggle();
		}
	});

	if (/[?&]guides=1\b/.test(window.location.search)) {
		if (document.readyState === "loading") {
			document.addEventListener("DOMContentLoaded", function () { setTimeout(on, 400); });
		} else {
			setTimeout(on, 400);
		}
	}
}(window, document));
