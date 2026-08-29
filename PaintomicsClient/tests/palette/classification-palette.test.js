/*
 * The pathway palettes are plain literals inside an ExtJS view, so there is no
 * module to require. The view is read as text and the three arrays are pulled
 * out of it, which is the point: this asserts the values that actually ship.
 *
 * What it guards is the defect these tests were written for - a category colour
 * that cannot be seen. The palette that lived here before ran from 1.07:1 to
 * 10.34:1 against the white page, and since one value paints the legend badge,
 * the pie slice and the network node at once, the eight entries under 2:1 meant
 * Reactome classifications like "Immune System" and "Hemostasis" drew a white
 * disc on white, a white wedge in the pie and a white dot in the network.
 */
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");

const VIEW = path.join(
    __dirname, "..", "..", "public_html", "app", "view",
    "PathwayAcquisitionViews", "PA_Step3Views.js"
);
const source = fs.readFileSync(VIEW, "utf8");

/* The comments in this view quote the code they replaced, so a search for an
   old expression finds the prose describing why it went. Assertions about what
   the file *does* run against the comment-free text. */
const code = source
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^[ \t]*\/\/.*$/gm, " ");

/* ---------------------------------------------------------------- helpers */

function channel(c) {
    return (c <= 0.04045) ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

/* Same relative luminance Util.js uses to choose the badge ink. */
function luminance(hex) {
    const p = [1, 3, 5].map(i => channel(parseInt(hex.substr(i, 2), 16) / 255));
    return 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2];
}

function contrast(a, b) {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
}

/* contrastingInk() picks whichever of black or white contrasts better, so the
   ink a badge will actually get is the better of the two ratios. */
function inkContrast(fill) {
    return Math.max(contrast(fill, "#000000"), contrast(fill, "#ffffff"));
}

/* Perceptual distance, so "these two are different colours" is a claim about
   what a reader can see rather than about the hex digits. */
function oklab(hex) {
    const [r, g, b] = [1, 3, 5].map(i => channel(parseInt(hex.substr(i, 2), 16) / 255));
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return [
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    ];
}

function distance(a, b) {
    const [x, y] = [oklab(a), oklab(b)];
    return Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]);
}

function hexesIn(block) {
    return (block.match(/#[0-9a-fA-F]{6}/g) || []).map(h => h.toLowerCase());
}

/* ------------------------------------------------------------ extraction */

/* The literal must be the one that opens right after the marker. Scanning for
   the next `{` anywhere would happily walk past an array and pick up some
   unrelated object further down the file, and every assertion below would then
   pass against colours that are not the ones being read - a guard that cannot
   fail is worse than no guard. */
function slice(startMarker, open, close) {
    const from = source.indexOf(startMarker);
    assert.notStrictEqual(from, -1, "cannot find " + startMarker + " in PA_Step3Views.js");
    const begin = source.indexOf(open, from);
    const between = source.slice(from + startMarker.length, begin);
    assert.ok(
        begin !== -1 && /^[\s=]*$/.test(between),
        startMarker + " is no longer followed by a '" + open + "' literal"
    );
    const end = source.indexOf(close, begin);
    assert.notStrictEqual(end, -1, "unterminated literal after " + startMarker);
    return source.slice(begin, end + 1);
}

const CLASSIFICATION = hexesIn(slice("var colors =", "[", "]"));
const DATABASE_BLOCK = slice("var DB_COLORS =", "{", "}");
const DATABASE = hexesIn(DATABASE_BLOCK);
const OTHER = hexesIn(slice("this.OTHER_COLORS =", "[", "]"));

assert.ok(CLASSIFICATION.length > 30, "read only " + CLASSIFICATION.length + " classification colours");
assert.ok(DATABASE.length >= 3, "read only " + DATABASE.length + " database colours");
assert.ok(OTHER.length >= 3, "read only " + OTHER.length + " fallback colours");

/* The seven KEGG classifications are deliberately untouched - users read them
   off the Category Distribution pie and the pathway grid at the same time. The
   rebuilt Reactome tail starts after them. */
const KEGG_HEAD = 7;
const TAIL = CLASSIFICATION.slice(KEGG_HEAD);

/* ---------------------------------------------------------------- tests */

test("the classification palette has one colour per classification name", () => {
    const names = source
        .slice(source.indexOf("this.getClassificationColor = function"))
        .match(/var pos = \[[\s\S]*?\]\.indexOf/)[0];
    const count = (names.match(/"/g).length) / 2;
    assert.strictEqual(
        CLASSIFICATION.length, count,
        "a name without a colour reads colors[undefined]; a colour without a name is unreachable"
    );
});

test("every classification badge gets a letter that passes AA", () => {
    for (const fill of CLASSIFICATION.concat(OTHER, DATABASE)) {
        assert.ok(
            inkContrast(fill) >= 4.5,
            fill + " leaves the badge letter at " + inkContrast(fill).toFixed(2) + ":1"
        );
    }
});

test("no Reactome classification is invisible against the page", () => {
    /* The floor is the weakest colour the KEGG head is allowed to keep
       (#FFCD02 at 1.50:1), so the tail can never be worse than the set that
       was explicitly kept. In practice its lightest band clears 1.85:1, just
       above #4CD964. */
    for (const fill of TAIL.concat(OTHER)) {
        const seen = contrast(fill, "#ffffff");
        assert.ok(
            seen >= 1.5,
            fill + " is " + seen.toFixed(2) + ":1 against the white page - it draws a blank " +
            "badge, a blank pie slice and a blank network node"
        );
    }
});

test("no classification colour is a near-black blot", () => {
    for (const fill of TAIL) {
        const seen = contrast(fill, "#ffffff");
        assert.ok(seen <= 8.0, fill + " is " + seen.toFixed(2) + ":1 - it reads as ink, not as a category");
    }
});

test("two classifications in one legend are told apart", () => {
    let worst = { d: Infinity };
    for (let i = 0; i < TAIL.length; i++) {
        for (let j = i + 1; j < TAIL.length; j++) {
            const d = distance(TAIL[i], TAIL[j]);
            if (d < worst.d) worst = { d: d, a: TAIL[i], b: TAIL[j] };
        }
    }
    /* The old palette held #b9936c and #c1946a, 0.014 apart - two tans nobody
       could separate. */
    assert.ok(
        worst.d > 0.03,
        worst.a + " and " + worst.b + " are " + worst.d.toFixed(4) + " apart in OKLab"
    );
});

test("a Reactome classification clears the KEGG seven it shares a legend with", () => {
    /* The Reactome and OmniPath legends both contain "Metabolism", which is a
       KEGG name and so takes KEGG's colour. A Reactome entry landing beside it
       in the same legend is the same defect as any other duplicate - an early
       cut put #79c5f3 0.025 from the old #5AC8FB, two light blues three rows
       apart in the Reactome list. */
    const HEAD = CLASSIFICATION.slice(0, KEGG_HEAD);
    for (const fill of TAIL) {
        let worst = { d: Infinity };
        for (const h of HEAD) {
            const d = distance(fill, h);
            if (d < worst.d) worst = { d: d, h: h };
        }
        assert.ok(
            worst.d > 0.05,
            fill + " is " + worst.d.toFixed(4) + " from the KEGG colour " + worst.h
        );
    }
});

test("nothing in the palette is louder than 0.131 chroma", () => {
    /* The KEGG seven were once an iOS system palette at chroma up to 0.265 -
       six saturated discs in a quiet white card, which is the complaint this
       whole line of work started from.

       The ceiling is a literal on purpose. It used to be derived as "no louder
       than the loudest database badge", which worked only while the badges were
       a deliberately quiet family. They are brand colours now, and KEGG's is at
       chroma 0.177, so a derived ceiling would have quietly risen by a third and
       let the categories get louder than the palette that was just calmed. A
       ceiling that moves when something else moves is not a ceiling. */
    const chroma = hex => { const [, a, b] = oklab(hex); return Math.hypot(a, b); };
    for (const fill of CLASSIFICATION.concat(OTHER)) {
        assert.ok(
            chroma(fill) <= 0.131,
            fill + " is at chroma " + chroma(fill).toFixed(3) + ", past the palette's 0.131"
        );
    }
});

test("any two colours that can share a legend are told apart", () => {
    /* Deliberately not an adjacency test. The order of this array is NOT the
       order a reader sees: the legend renders a tree, parents with their
       sub-classifications nested underneath, and which classifications a job
       has varies. So any two entries can end up next to each other and the
       floor has to hold for every pair, not for consecutive ones. Measured on
       a KEGG+OmniPath+Reactome job the closest pair actually rendered in one
       legend is 0.0555. */
    const ALL = CLASSIFICATION.concat(OTHER);
    let worst = { d: Infinity };
    for (let i = 0; i < ALL.length; i++) {
        for (let j = i + 1; j < ALL.length; j++) {
            const d = distance(ALL[i], ALL[j]);
            if (d < worst.d) worst = { d: d, a: ALL[i], b: ALL[j] };
        }
    }
    assert.ok(
        worst.d > 0.05,
        worst.a + " and " + worst.b + " are " + worst.d.toFixed(4) + " apart in OKLab"
    );
});

test("a database badge is not wearing a classification colour", () => {
    /* The reported bug: DB_COLORS was the first six entries of the
       classification palette, so on one screen the KEGG badge and the
       "Cellular Processes" badge were both #007AFF. */
    for (const db of DATABASE) {
        assert.ok(
            !CLASSIFICATION.includes(db),
            db + " paints both a database and a pathway classification"
        );
        /* Not merely "not identical". Both systems use the whole hue circle -
           KEGG's database yellow shares a hue with some yellow category,
           necessarily - so hue cannot be what separates them and the distance
           has to be asserted rather than assumed.

           This assertion used to be a consequence of the geometry rather than a
           check on it: the badges sat together at L=0.645 and the palette was
           drawn from two bands either side of them, so the gap fell out of
           OKLab's first coordinate for free. The badges wear their brand
           lightnesses now and there are no bands, so nothing enforces this
           except this line and the generator that satisfies it. It is the one
           assertion in this file that a future palette cannot be regenerated
           without. */
        for (const cls of CLASSIFICATION.concat(OTHER)) {
            assert.ok(
                distance(db, cls) > 0.12,
                db + " is only " + distance(db, cls).toFixed(4) + " from " + cls +
                " - a source badge and a category badge on one screen in one colour"
            );
        }
    }
});

test("each database badge is its own colour, not a colour near it", () => {
    /* This replaces an assertion that the four badges sat within a narrow
       lightness band. That band was real, and it was what made the badges
       recognisably one family - but it also made them impossible to paint in
       the databases' own colours, because yellow has no dark form and the
       Reactome/OmniPath pair are nineteen degrees apart in hue and so collapse
       to 0.044 at any shared lightness. The badges are brand-anchored now and
       deliberately span L=0.530 to L=0.866; "one quiet family" is no longer a
       property this file should be asserting.

       What must still hold is that the four are the colours the databases
       actually use. Pinned to the references so a later edit that drifts one
       back toward the palette fails here rather than on the page. */
    const BRAND = {
        "#fcce00": "KEGG",       // brand value, exactly
        "#027b7f": "OmniPath",   // brand value, exactly
        "#9ad5e9": "Reactome",   // #b6deea lifted from chroma 0.045 to 0.066 - see below
        "#d3686e": "MapMan"      // the one hue the other three do not claim
    };
    for (const db of DATABASE) {
        assert.ok(BRAND[db], db + " is not one of the four database colours");
    }
    assert.strictEqual(DATABASE.length, Object.keys(BRAND).length);

    /* Reactome is the only one that is not its brand hex, and the amount it
       moved is the whole argument for moving it: #b6deea is at chroma 0.045,
       and a 24px disc that desaturated reads grey rather than blue. Held to a
       small correction so "similar to the brand" stays checkable. */
    assert.ok(
        distance("#9ad5e9", "#b6deea") < 0.06,
        "the Reactome badge has drifted away from its brand reference"
    );
});

test("two database badges are told apart from each other", () => {
    /* They no longer share a lightness, so the thing that used to keep them
       distinct - four hues at one L - is gone. Asserted directly instead. The
       tightest pair is KEGG against Reactome at 0.226. */
    for (let i = 0; i < DATABASE.length; i++) {
        for (let j = i + 1; j < DATABASE.length; j++) {
            const d = distance(DATABASE[i], DATABASE[j]);
            assert.ok(
                d > 0.15,
                DATABASE[i] + " and " + DATABASE[j] + " are " + d.toFixed(4) + " apart"
            );
        }
    }
});

test("the fallback list is read from one place, not restated", () => {
    /* Two ways this file's colours can be correct and the page still wrong,
       both found while regenerating the palette and both invisible until the
       values changed:

       The classification selector panel used to reset its shift-cursor by
       restating the four fallbacks as a literal, while the pie above it read a
       copy of me.OTHER_COLORS. Identical lists, so nothing showed - until one
       of them was edited, at which point a pie wedge and its own legend chip
       would have drawn in different colours.

       And applyVisualSettings() passed me.OTHER_COLORS itself into a function
       that takes its fallback with shift(), draining the instance array for the
       rest of the session. */
    const literals = code.match(/OTHER_COLORS\s*=\s*\[[^\]]*\]/g) || [];
    assert.strictEqual(
        literals.length, 1,
        "OTHER_COLORS is written as a literal in " + literals.length + " places: " + literals.join(" | ")
    );
    assert.ok(
        !/getClassificationColor\([^,)]*,\s*me\.OTHER_COLORS\s*\)/.test(code),
        "a caller hands getClassificationColor() the instance array, which it shifts empty"
    );
});

test("a database colour is keyed by name, not by position", () => {
    /* Keyed by index, Reactome was red in a three-database job and green in a
       two-database one. */
    assert.match(DATABASE_BLOCK, /"KEGG"\s*:/);
    assert.match(DATABASE_BLOCK, /"Reactome"\s*:/);
    assert.match(DATABASE_BLOCK, /"OmniPath"\s*:/);
    assert.ok(
        !/DB_COLORS\[i\]|DB_COLORS\.length/.test(code),
        "DB_COLORS is being read positionally again"
    );
});

test("an unlisted database still gets a colour", () => {
    /* The fallback used to be #000000, which reads as a disabled badge beside
       three coloured ones. */
    assert.ok(!/DB_COLORS\S*\s*\?[^:]*:\s*"#000000"/.test(code),
        "an unlisted database falls back to a black disc again");
    assert.ok(/DB_COLORS\[database\]\s*\|\|\s*me\.getClassificationColor\(database\)/.test(code),
        "the fallback to the classification palette is gone");
});

test("the fallback list collides with nothing it can appear beside", () => {
    /* A classification that takes an OTHER_COLOR sits in the same legend as
       classifications that took a palette colour by name, so these four must
       clear all 36 - taking them FROM the palette put "Drug ADME" and
       "Cell-Cell communication" on one hex in the Reactome legend. */
    for (const fill of OTHER) {
        let worst = { d: Infinity };
        for (const cls of CLASSIFICATION) {
            const d = distance(fill, cls);
            if (d < worst.d) worst = { d: d, cls: cls };
        }
        assert.ok(
            worst.d > 0.045,
            fill + " is " + worst.d.toFixed(4) + " from the palette colour " + worst.cls +
            " - two classifications in one legend would wear it"
        );
    }
    let worst = { d: Infinity };
    for (let i = 0; i < OTHER.length; i++) {
        for (let j = i + 1; j < OTHER.length; j++) {
            const d = distance(OTHER[i], OTHER[j]);
            if (d < worst.d) worst = { d: d, a: OTHER[i], b: OTHER[j] };
        }
    }
    /* They are handed out together, to consecutive classifications in one
       legend, so these four in particular have to be far apart. */
    assert.ok(
        worst.d > 0.15,
        worst.a + " and " + worst.b + " are " + worst.d.toFixed(4) + " apart in OKLab"
    );
});
