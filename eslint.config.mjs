// Lint gate for the client, run by .github/workflows/pr.yml.
//
// The client is the largest surface in the repository and until now the least
// guarded: 52,000 lines of first-party JavaScript against which CI ran only
// `node --check`, which answers "does this parse" and nothing else. The server
// has had ruff since the 2026-08 quality campaign; this is the same bargain on
// the other side of the wire.
//
// The rule set is deliberately the JavaScript analogue of ruff.toml's `E9, F`:
// code that cannot do what it says, never style. Nothing here has an opinion
// about quotes, semicolons, indentation or naming -- an ExtJS 4.2.1 codebase
// written over a decade would drown a style gate in findings nobody will fix,
// and a gate people wave through is worse than no gate.
//
// `no-unused-vars` and `no-undef` are OFF on purpose. Half this code is reached
// only by name -- ExtJS resolves `xtype`, `controller` and `itemId` strings at
// runtime, and Util.js publishes free functions that views call as globals --
// so both rules report live code as dead, which is the exact failure mode the
// server's vulture ratchet exists to work around. If they are ever wanted they
// need a declared-globals list first.
//
// Measured when this file was added: 5 findings across 86 first-party files,
// every one a real defect, all fixed in the same commit. Vendored trees (ExtJS,
// jQuery, Angular, Bootstrap, pyodide, marked) are ignored -- they are not ours
// to police, and pyodide alone accounted for 13 findings.

export default [
  {
    ignores: [
      "**/node_modules/**",
      // Vendored third-party trees. This mirrors the filter that the
      // "Client JavaScript" step in pr.yml used to apply with grep, plus
      // resources/pyodide, which that filter missed: it matches none of
      // lib/libs/vendor/extjs/jquery, so `node --check` was parsing the
      // pyodide runtime on every pull request.
      "**/lib/**",
      "**/libs/**",
      "**/vendor/**",
      "**/extjs/**",
      "**/jquery/**",
      "**/ext-[0-9]*/**",
      "PaintomicsClient/public_html/resources/pyodide/**",
      // Not source: build output, documentation assets, recorded experiment
      // artefacts.
      "dist/**",
      "docs/**",
      "runs/**",
    ],
  },
  {
    files: ["**/*.js"],
    // Util.js carries six `eslint-disable` comments for no-console, no-eval and
    // no-unused-vars -- written years before this file existed, for a linter
    // nobody ever wired up. None of those three rules is enabled here, so ESLint
    // calls all six directives unused and, left at its default, fails the gate
    // on them forever. They are kept rather than deleted: each one marks a real
    // hazard at a real line (the no-eval at Util.js:4796 is a genuine eval), and
    // that annotation is worth more than the tidiness of removing it. Anyone
    // running a stricter config locally still gets the benefit.
    linterOptions: { reportUnusedDisableDirectives: "off" },
    languageOptions: {
      // ExtJS 4.2.1 targets ES5 browsers, but the first-party code added since
      // uses let/const, arrow functions and template literals. 2021 parses
      // everything present without accepting module syntax the browser build
      // could not load.
      ecmaVersion: 2021,
      sourceType: "script",
      globals: {
        window: "readonly", document: "readonly", console: "readonly",
        navigator: "readonly", location: "readonly", history: "readonly",
        setTimeout: "readonly", clearTimeout: "readonly",
        setInterval: "readonly", clearInterval: "readonly",
        requestAnimationFrame: "readonly", getComputedStyle: "readonly",
        XMLHttpRequest: "readonly", fetch: "readonly", FormData: "readonly",
        Blob: "readonly", File: "readonly", FileReader: "readonly", URL: "readonly",
        localStorage: "readonly", sessionStorage: "readonly",
        Image: "readonly", MutationObserver: "readonly", CustomEvent: "readonly",
        // Libraries the page loads before any first-party file.
        Ext: "readonly", $: "readonly", jQuery: "readonly", d3: "readonly",
        marked: "readonly", cytoscape: "readonly", SVG: "readonly",
        // Node, for the corpus runners under PaintomicsServer/src/tests.
        require: "readonly", module: "writable", process: "readonly",
        __dirname: "readonly", Buffer: "readonly",
      },
    },
    rules: {
      // A conditional that assigns instead of comparing. `except-parens` is
      // the default and the right setting here: every one of the eight sites
      // in this tree writes the deliberate `while ((m = re.exec(s)) !== null)`
      // idiom with the extra parentheses, so this catches a bare `if (a = b)`
      // without a single false positive today.
      "no-cond-assign": ["error", "except-parens"],
      // A hole in an array literal, which is what a commented-out block
      // followed by its dangling comma leaves behind. Two of these were live
      // in an ExtJS `items:` array, where the hole becomes an `undefined`
      // child component.
      "no-sparse-arrays": "error",
      "no-unreachable": "error",
      "no-self-assign": "error",
      "no-dupe-keys": "error",
      "no-dupe-args": "error",
      "no-dupe-else-if": "error",
      "no-duplicate-case": "error",
      "no-func-assign": "error",
      "no-class-assign": "error",
      "no-const-assign": "error",
      "no-import-assign": "error",
      "no-obj-calls": "error",
      "no-setter-return": "error",
      "no-unsafe-negation": "error",
      "no-unsafe-finally": "error",
      "no-compare-neg-zero": "error",
      "no-async-promise-executor": "error",
      "no-this-before-super": "error",
      "getter-return": "error",
      "use-isnan": "error",
    },
  },
];
