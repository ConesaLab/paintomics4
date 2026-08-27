#!/usr/bin/env python3
"""An omic card must size itself from its contents, never from a measurement.

The behaviour this guards
-------------------------
The omic cards on Step 1 are items of an ExtJS vbox, which lays them out as
absolutely positioned elements carrying an inline `top`. Growing a card's DOM
therefore does not move the card below it.

InputFormat/format-panel.js adds a strip to each card, so it has to deal with
that. Its first answer was to compute the height the card ought to have and
setHeight() it. A computed height is a MEASUREMENT, and a measurement has a
moment -- which is where this went wrong twice:

    __paBaseHeight was recorded when the card was primed. The MORE panel is
    tall enough that its sections had not settled: 662px recorded against a
    settled 771px. The card was pinned 66px short of its own contents.

and the shortfall did not simply clip, because the omic title was declared
`xtype: "box", flex: 1` in all four panel types. A flexed item in a vbox is
where the layout puts leftover height -- and where it TAKES a shortfall from.
The 44px title was allocated 0px, CSS `min-height: 44px` painted it anyway,
and it came down on top of the first section heading. Measured on the reported
screenshot: title bottom 292, "Experimental Design" top 277.

The fix has two halves and this suite holds both:

  * the card leaves the vbox's height budget (`flex` and the inline height
    both cleared) and is then re-laid-out rather than re-measured, so there is
    no number left to get wrong;
  * no omic title is flexed, so a card that is short for any FUTURE reason
    cannot destroy its own header again.

Measured after the fix, in Chrome, on the MORE card: idle strip -> card 771px,
title 44px, overlap 0; strip grown 34px + updateLayout() -> card 805px and the
card below moved 1028 -> 1062. Plain cards 178 -> 175, which is the 3px the
title's flex had been stretching them by.

Usage:
    cd PaintomicsServer
    python -m src.tests.test_omic_card_sizes_itself
"""
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
VIEWS = os.path.join(REPO, "PaintomicsClient", "public_html", "app", "view",
                     "PathwayAcquisitionViews")
FORMAT_PANEL = os.path.join(VIEWS, "InputFormat", "format-panel.js")
STEP1_VIEWS = os.path.join(VIEWS, "PA_Step1Views.js")

# The three functions that stand between the module and the layout. Lifted
# verbatim so the test runs the shipped code rather than a copy of it.
LIFTED = ("hostForComponent", "freeCardHeight", "syncCardHeightFor")


def read(path):
    with io.open(path, encoding="utf-8") as handle:
        return handle.read()


def lift(source, name):
    """The text of one top-level `function name(...) {...}` in the module.

    The module indents its functions by four spaces and closes them on a line
    that is exactly `    }`, which makes the end unambiguous without parsing.
    """
    start = source.index("\n    function %s(" % name) + 1
    end = source.index("\n    }\n", start) + len("\n    }\n")
    return source[start:end]


HARNESS = """
'use strict';
// A card, stubbed down to what the three lifted functions touch. Every call
// that could change the card's size is recorded, so the test can assert on
// HOW the card was sized and not merely that it ended up somewhere.
const calls = [];
function makeCard(overrides) {
    const card = Object.assign({
        flex: 1,
        height: 706,                 // what the vbox had already written
        isDestroyed: false,
        el: { dom: { style: { height: '706px' } } },
        _child: null,
        down(sel) { return sel === '[itemId=paFormatHost]' ? this._child : null; },
        add(child) { calls.push('add'); this._child = child; return child; },
        remove() { calls.push('remove'); this._child = null; },
        updateLayout() { calls.push('updateLayout'); },
        setHeight(h) { calls.push('setHeight:' + h); this.height = h; },
        getHeight() { return this.height; }
    }, overrides || {});
    return card;
}
const Ext = {
    suspendLayouts() { calls.push('suspend'); },
    resumeLayouts() { calls.push('resume'); },
    create(xtype, cfg) {
        return { cfg: cfg, getEl: () => ({ dom: { firstChild: { __strip: true } } }) };
    }
};

__LIFTED__

const out = {};

// 1. Adding the host must free the card and then re-lay it out.
let card = makeCard();
calls.length = 0;
const strip = hostForComponent(card);
out.first = {
    calls: calls.slice(),
    flex: card.flex,
    height: card.height,
    inlineHeight: card.el.dom.style.height,
    freed: card.__paFreed === true,
    gotStrip: !!(strip && strip.__strip)
};

// 2. A second call finds the host that is already there and changes nothing.
calls.length = 0;
hostForComponent(card);
out.second = { calls: calls.slice() };

// 3. Re-syncing after the message changes height re-lays out, nothing else.
calls.length = 0;
syncCardHeightFor(card);
out.sync = { calls: calls.slice() };

// 4. A card that was never freed, and a destroyed one, are both left alone.
calls.length = 0;
syncCardHeightFor(makeCard());
syncCardHeightFor(makeCard({ __paFreed: true, isDestroyed: true }));
syncCardHeightFor(null);
out.untouched = { calls: calls.slice() };

// 5. freeCardHeight is once-only: a card already freed is not re-cleared, so a
//    height the module itself did not write is never silently discarded.
const already = makeCard({ __paFreed: true });
freeCardHeight(already);
out.idempotent = { flex: already.flex, height: already.height };

console.log(JSON.stringify(out));
"""


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class OmicCardSizesItselfTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        source = read(FORMAT_PANEL)
        cls.panel_source = source
        script = HARNESS.replace(
            "__LIFTED__", "\n".join(lift(source, name) for name in LIFTED))
        directory = tempfile.mkdtemp(prefix="paintomics-card-height-")
        try:
            path = os.path.join(directory, "check.js")
            with io.open(path, "w", encoding="utf-8") as handle:
                handle.write(script)
            done = subprocess.run(["node", path], capture_output=True,
                                  text=True, timeout=60)
            if done.returncode != 0:
                raise AssertionError("node failed:\n%s" % done.stderr)
            cls.result = json.loads(done.stdout)
        finally:
            shutil.rmtree(directory, ignore_errors=True)

    # -- the card leaves the height budget --------------------------------

    def test_adding_the_host_frees_the_card_from_the_vbox_budget(self):
        first = self.result["first"]
        self.assertTrue(first["freed"])
        self.assertIsNone(first["flex"], "flex must go, or the layout keeps "
                                         "deciding the card's height")
        self.assertIsNone(first["height"])
        self.assertEqual(first["inlineHeight"], "",
                         "the inline height the layout already wrote pins the "
                         "DOM at that decision and has to be cleared too")

    def test_adding_the_host_relayouts_and_returns_the_strip(self):
        first = self.result["first"]
        self.assertTrue(first["gotStrip"])
        self.assertIn("add", first["calls"])
        self.assertIn("updateLayout", first["calls"],
                      "nothing rewrites the sibling cards' `top` without this")

    def test_the_card_is_never_given_a_computed_height(self):
        """The regression itself: a height is a measurement, and it was wrong."""
        for stage in ("first", "second", "sync", "untouched"):
            for call in self.result[stage]["calls"]:
                self.assertFalse(call.startswith("setHeight"),
                                 "%s called %s" % (stage, call))

    def test_a_second_host_request_changes_nothing(self):
        self.assertEqual(self.result["second"]["calls"], [])

    def test_freeing_is_once_only(self):
        """So a height the module did not write is never silently discarded."""
        self.assertEqual(self.result["idempotent"]["flex"], 1)
        self.assertEqual(self.result["idempotent"]["height"], 706)

    # -- re-syncing -------------------------------------------------------

    def test_sync_relayouts_and_does_nothing_else(self):
        self.assertEqual(self.result["sync"]["calls"], ["updateLayout"])

    def test_sync_leaves_unfreed_destroyed_and_missing_cards_alone(self):
        self.assertEqual(self.result["untouched"]["calls"], [])

    # -- the source-level halves ------------------------------------------

    def test_the_height_measurement_is_gone_from_the_module(self):
        """__paBaseHeight was the snapshot that was 66px short."""
        code = re.sub(r"/\*.*?\*/", "", self.panel_source, flags=re.S)
        self.assertNotIn("__paBaseHeight", code)
        self.assertNotIn("setHeight", code)

    def test_the_card_observer_does_not_schedule_on_a_bare_frame(self):
        """Chrome throttles requestAnimationFrame to zero in a hidden tab.

        The observer that primes each card deferred through a bare rAF, so a
        card added while the tab was behind something got no strip and no input
        check at all. Measured in a tab reporting visibilityState "hidden":
        MORE card primed=false, host=false before; primed=true, host=true after.
        Util.js keeps the house version -- rAF when visible, setTimeout(0) when
        hidden -- and four other pieces of this app have already been caught on
        the bare one.
        """
        code = re.sub(r"/\*.*?\*/", "", self.panel_source, flags=re.S)
        self.assertIn("window.paDeferFrame", code)
        primer = code[code.index("MutationObserver"):]
        primer = primer[:primer.index("observer.observe")]
        self.assertNotIn("requestAnimationFrame(function", primer,
                         "the card observer must defer through paDeferFrame")

    def test_no_omic_title_is_flexed(self):
        """A flexed 44px header is where a short card takes its shortfall from.

        All four panel types (plain, region-based, miRNA, MORE) declared the
        title as `xtype: "box", flex: 1`. Comments are stripped first, because
        the note explaining this bug quotes the very declaration it removed.
        """
        code = re.sub(r"/\*.*?\*/", "", read(STEP1_VIEWS), flags=re.S)
        titles = [m.start() for m in re.finditer(r'cls: "omicboxTitle', code)]
        self.assertEqual(len(titles), 4,
                         "expected the four omic panels; found %d" % len(titles))
        for start in titles:
            # The declaration is one object literal: look back to the `xtype`
            # that opens it and forward to the `html` that closes it.
            head = code.rfind("xtype:", 0, start)
            declaration = code[head:code.index("html:", start)]
            self.assertNotIn("flex", declaration,
                             "a flexed omic title absorbs the card's shortfall "
                             "and lands on the section below it:\n%s"
                             % declaration.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
