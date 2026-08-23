/* PA_PaperView — the Paper agent's tab: consent, progress lanes, manuscript.
 *
 * The server runs specialists whose contracts are executed as code
 * (src/classes/AIInterpret/paper_agent.py); this view only asks, watches and
 * renders. Three states, one root each:
 *   consent  — what will run and what leaves the machine, plus the button;
 *   progress — one lane per specialist, driven by paper_status.status
 *              ("specialist:<name>" makes the lane model trivial and honest);
 *   paper    — the manuscript (marked.js, same renderer as the interpreter),
 *              figures resolved through /ai_figure, a verification panel
 *              stating what the gate did, and a Markdown export.
 *
 * Every server string reaches the DOM through text nodes or through
 * marked + the same sanitisation path the AI report uses.
 */
function PA_PaperView() {
	this.name = "PA_PaperView";
	this.jobID = null;
	this.$root = null;
	this._pollTimer = null;

	var LANES = [
		["design_qc", "Design & QC analyst"],
		["pathway", "Pathway analyst"],
		["enrichment", "Enrichment analyst"],
		["network", "Network analyst"],
		["metabolite", "Metabolite analyst"],
		["literature", "Literature analyst"],
		["lead", "Lead author"],
		["storing", "Verification gate"]
	];

	this.load = function(jobID, container) {
		this.jobID = jobID;
		this.$root = $(container);
		this._fetchStatus();
	};

	this.destroy = function() {
		if (this._pollTimer) { clearTimeout(this._pollTimer); this._pollTimer = null; }
		if (this.$root) { this.$root.empty(); }
	};

	/* ------------------------------------------------------------ server */

	this._fetchStatus = function() {
		var me = this;
		$.get(SERVER_URL_PAPER_STATUS, {jobID: me.jobID})
			.done(function(response) {
				var st = (response && response.paper_status) || {status: "none"};
				if (st.status === "done") {
					me._fetchReport();
				} else if (st.status === "none" || st.status === "error") {
					me._renderConsent(st);
				} else {
					me._renderProgress(st);
					me._pollTimer = setTimeout(me._fetchStatus.bind(me), 4000);
				}
			})
			.fail(function() {
				me._renderMessage("The Paper agent is not available on this server.");
			});
	};

	this._start = function() {
		var me = this;
		$.post(SERVER_URL_PAPER_INITIATE, {jobID: me.jobID})
			.done(function() { me._fetchStatus(); })
			.fail(function(xhr) {
				var msg = "Could not start the Paper agent.";
				try { msg = JSON.parse(xhr.responseText).message || msg; } catch (e) {}
				me._renderMessage(msg);
			});
	};

	this._fetchReport = function() {
		var me = this;
		$.get(SERVER_URL_PAPER_REPORT, {jobID: me.jobID})
			.done(function(response) {
				if (response && response.success) {
					me._renderPaper(response);
				} else {
					me._renderMessage((response && response.message) || "The paper is not ready.");
				}
			})
			.fail(function() { me._renderMessage("Could not load the paper."); });
	};

	/* ------------------------------------------------------------ render */

	this._renderMessage = function(text) {
		this.$root.empty().append(
			$("<p class='infoTip'>").text(text));
	};

	this._renderConsent = function(st) {
		var me = this;
		this.$root.empty();
		if (st && st.status === "error") {
			this.$root.append($("<p class='pa-paper-error'>")
				.css({color: "#c0392b"})
				.text("The last run failed: " + (st.detail || "unknown error")));
		}
		this.$root.append(
			$("<p class='infoTip'>").text(
				"The Paper agent runs every analysis this job supports — data " +
				"quality, pathway enrichment, GO terms, set comparisons, the " +
				"regulatory network — and assembles a draft manuscript with " +
				"figures whose every number is traced to a computed result."),
			$("<p class='infoTip'>").text(
				"Summaries of this job's analysis results are sent to the " +
				"external AI service configured on this server, and PubMed is " +
				"queried for related literature. Nothing else leaves the server."),
			$("<a href='javascript:void(0)' class='button btn-info'>")
				.html('<i class="fa fa-file-text-o"></i> Write the paper')
				.on("click", function() { me._start(); }));
	};

	this._renderProgress = function(st) {
		var me = this;
		var status = String(st.status || "");
		var current = status.indexOf("specialist:") === 0 ?
			status.slice("specialist:".length) : status;
		var reached = false;
		this.$root.empty();
		var $list = $("<div class='pa-paper-lanes'>");
		LANES.forEach(function(pair) {
			var key = pair[0], label = pair[1];
			var state;
			if (key === current) { state = "active"; reached = true; }
			else if (!reached) { state = "done"; }
			else { state = "pending"; }
			if (["starting", "context", "queued"].indexOf(status) !== -1) {
				state = "pending";
			}
			var icon = state === "done" ? "fa-check" :
				state === "active" ? "fa-spinner fa-spin" : "fa-circle-o";
			$list.append($("<div class='pa-paper-lane'>")
				.css({padding: "4px 0", color: state === "pending" ? "#999" : "#333"})
				.append($("<i class='fa " + icon + "'>").css({width: "22px"}),
				        $("<span>").text(label)));
		});
		this.$root.append(
			$("<h3>").text(st.detail || "Working..."),
			$list,
			$("<p class='infoTip'>").text("This page refreshes itself; the run "
				+ "continues on the server if you navigate away."));
	};

	this._renderPaper = function(response) {
		var me = this;
		this.$root.empty();
		var markdown = response.paper || "";
		var figures = response.figures || [];
		var verification = response.verification || {};

		/* figure: URLs -> the /ai_figure route, same as the interpreter. */
		var byId = {};
		figures.forEach(function(f) { byId[f.id] = f; });
		var rendered = markdown.replace(/!\[([^\]]*)\]\(figure:([\w.-]+)\)/g,
			function(_m, alt, id) {
				var fig = byId[id];
				if (!fig || !fig.png) { return ""; }
				return "![" + (alt || id) + "](" + fig.png + ")";
			});

		var $toolbar = $("<div class='pa-paper-toolbar'>").css({margin: "0 0 12px"});
		$toolbar.append($("<a href='javascript:void(0)' class='button btn-default'>")
			.html('<i class="fa fa-download"></i> Download Markdown')
			.on("click", function() {
				var blob = new Blob([markdown], {type: "text/markdown"});
				var a = document.createElement("a");
				a.href = URL.createObjectURL(blob);
				a.download = "paintomics-paper-" + me.jobID + ".md";
				document.body.appendChild(a);
				a.click();
				document.body.removeChild(a);
				URL.revokeObjectURL(a.href);
			}));

		var $verification = $("<div class='pa-paper-verification contentbox'>")
			.css({padding: "10px 14px", margin: "0 0 14px",
			      background: "#f8f9fa", fontSize: "13px"});
		var redactedNumbers = (verification.sentences_redacted_numbers || []).length;
		var redactedTokens = (verification.sentences_redacted_tokens || []).length;
		$verification.append($("<b>").text("Verification gate: "),
			$("<span>").text(
				(verification.facts_substituted || 0) + " numbers substituted from " +
				"tool results; " + redactedNumbers + " sentence(s) removed for " +
				"unledgered numbers; " + redactedTokens + " for unknown tokens; " +
				(verification.citations_kept || 0) + " citation(s) kept, " +
				(verification.citations_dropped || 0) + " dropped; " +
				(verification.figures_total || 0) + " figure(s), " +
				(verification.figures_failing_qa || 0) + " failing QA."));

		var $paper = $("<div class='pa-paper-body ai-report-body'>");
		if (window.marked) {
			$paper.html(marked.parse(rendered));
		} else {
			$paper.text(markdown);
		}
		this.$root.append($toolbar, $verification, $paper);
	};

	return this;
}
