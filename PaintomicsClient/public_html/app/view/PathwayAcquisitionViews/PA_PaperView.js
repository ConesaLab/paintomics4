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

	/* One scoped stylesheet, injected once per page. A manuscript is read,
	   not operated: a measured serif column, quiet chrome, figures as cards.
	   Scoped under .pa-paper-root so nothing leaks into the rest of Step 3. */
	if (!document.getElementById("pa-paper-style")) {
		var css = [
			".pa-paper-root{--pa-ink:#1a1f24;--pa-muted:#5f6b76;--pa-line:#e5e9ee;--pa-accent:#0b6bcb;--pa-ok:#0a7d4f;--pa-warn:#b45309;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:var(--pa-ink);}",
			".pa-paper-hero{max-width:820px;margin:8px auto 0;padding:28px 8px 8px;}",
			".pa-paper-hero h3{font-size:22px;font-weight:650;margin:0 0 10px;letter-spacing:-.01em;}",
			".pa-paper-hero p{color:var(--pa-muted);font-size:14.5px;line-height:1.65;margin:0 0 12px;max-width:64ch;}",
			".pa-paper-cta{display:inline-flex;align-items:center;gap:9px;background:var(--pa-accent);color:#fff!important;border:none;border-radius:10px;padding:11px 20px;font-size:14.5px;font-weight:600;cursor:pointer;box-shadow:0 1px 2px rgba(16,24,40,.1);transition:transform .06s ease,box-shadow .12s ease;}",
			".pa-paper-cta:hover{box-shadow:0 4px 10px rgba(11,107,203,.28);transform:translateY(-1px);text-decoration:none;}",
			".pa-paper-privacy{border-left:3px solid var(--pa-line);padding:2px 0 2px 14px;}",
			".pa-paper-progresscard{max-width:640px;margin:26px auto;padding:26px 30px;border:1px solid var(--pa-line);border-radius:14px;background:#fff;box-shadow:0 1px 3px rgba(16,24,40,.06);}",
			".pa-paper-progresscard h3{margin:0 0 4px;font-size:16px;font-weight:650;}",
			".pa-paper-progresscard .pa-paper-sub{color:var(--pa-muted);font-size:13px;margin:0 0 16px;}",
			".pa-paper-bar{height:6px;border-radius:999px;background:var(--pa-line);overflow:hidden;margin:0 0 18px;}",
			".pa-paper-bar i{display:block;height:100%;background:linear-gradient(90deg,var(--pa-accent),#3b93e8);border-radius:999px;transition:width .6s ease;}",
			".pa-paper-lane{display:flex;align-items:center;gap:10px;padding:7px 0;font-size:14px;border-bottom:1px dashed var(--pa-line);}",
			".pa-paper-lane:last-child{border-bottom:none;}",
			".pa-paper-lane .fa{width:18px;text-align:center;}",
			".pa-paper-lane.is-done{color:var(--pa-ink);}.pa-paper-lane.is-done .fa{color:var(--pa-ok);}",
			".pa-paper-lane.is-active{color:var(--pa-accent);font-weight:600;}",
			".pa-paper-lane.is-pending{color:#9aa4ae;}",
			".pa-paper-meta{max-width:820px;margin:0 auto;display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:14px 8px 6px;}",
			".pa-paper-chip{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;border-radius:999px;padding:4px 12px;border:1px solid var(--pa-line);background:#f7f9fb;color:var(--pa-muted);}",
			".pa-paper-chip.is-ok{background:#e8f5ee;border-color:#c3e5d2;color:var(--pa-ok);}",
			".pa-paper-chip.is-warn{background:#fef3e2;border-color:#f4d9ae;color:var(--pa-warn);}",
			".pa-paper-chip b{font-weight:650;}",
			".pa-paper-actions{margin-left:auto;display:flex;gap:8px;}",
			".pa-paper-btn{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--pa-line);background:#fff;border-radius:9px;padding:7px 14px;font-size:13px;font-weight:600;color:var(--pa-ink)!important;cursor:pointer;transition:border-color .12s;}",
			".pa-paper-btn:hover{border-color:var(--pa-accent);color:var(--pa-accent)!important;text-decoration:none;}",
			".pa-paper-body{max-width:760px;margin:6px auto 60px;padding:0 8px;font-family:Charter,'Iowan Old Style',Georgia,'Times New Roman',serif;font-size:17px;line-height:1.75;color:var(--pa-ink);}",
			".pa-paper-body h1{font-size:29px;line-height:1.25;font-weight:700;letter-spacing:-.012em;margin:26px 0 6px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;}",
			".pa-paper-body h2{font-size:19px;font-weight:700;margin:38px 0 10px;padding-top:18px;border-top:1px solid var(--pa-line);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;}",
			".pa-paper-body h3{font-size:16px;font-weight:650;margin:26px 0 6px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#2c3944;}",
			".pa-paper-body p{margin:0 0 16px;}",
			".pa-paper-body img{max-width:100%;border:1px solid var(--pa-line);border-radius:10px;padding:10px;background:#fff;box-shadow:0 1px 3px rgba(16,24,40,.05);margin:10px 0 4px;}",
			".pa-paper-body img+em,.pa-paper-body p>em:only-child{display:block;font-size:13.5px;color:var(--pa-muted);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;margin:2px 0 20px;}",
			".pa-paper-body ul{padding-left:22px;}.pa-paper-body li{margin:0 0 7px;font-size:15.5px;}",
			".pa-paper-body code{font-size:14px;background:#f4f6f8;border-radius:4px;padding:1px 5px;}",
			".pa-paper-error{max-width:640px;margin:14px auto;padding:12px 16px;border-radius:10px;background:#fdf1f1;border:1px solid #f2caca;color:#a13030;font-size:14px;}"
		].join("\n");
		var tag = document.createElement("style");
		tag.id = "pa-paper-style";
		tag.textContent = css;
		document.head.appendChild(tag);
	}

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
		var $hero = $("<div class='pa-paper-hero'>").append(
			$("<h3>").text("Draft a manuscript from this analysis"),
			$("<p>").text(
				"A team of specialist analysts runs every analysis this job " +
				"supports — data quality, pathway enrichment, GO terms, set " +
				"comparisons, the regulatory network — and a lead author " +
				"assembles a draft with painted pathway figures. Every number " +
				"in the prose is traced to a computed result."),
			$("<p class='pa-paper-privacy'>").text(
				"Summaries of this job's analysis results are sent to the " +
				"external AI service configured on this server, and PubMed is " +
				"queried for related literature. Nothing else leaves the " +
				"server."),
			$("<a href='javascript:void(0)' class='pa-paper-cta'>")
				.html('<i class="fa fa-file-text-o"></i> Write the paper')
				.on("click", function() { me._start(); }));
		this.$root.append($hero);
	};

	this._renderProgress = function(st) {
		var me = this;
		var status = String(st.status || "");
		var current = status.indexOf("specialist:") === 0 ?
			status.slice("specialist:".length) : status;
		var reached = false;
		this.$root.empty();
		var $card = $("<div class='pa-paper-progresscard'>");
		$card.append(
			$("<h3>").text(st.detail || "Working..."),
			$("<p class='pa-paper-sub'>").text(
				"This page refreshes itself; the run continues on the server " +
				"if you navigate away."),
			$("<div class='pa-paper-bar'>").append(
				$("<i>").css("width", Math.max(4, st.percent || 0) + "%")));
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
				state === "active" ? "fa-spinner fa-spin" : "fa-circle-thin";
			$card.append($("<div class='pa-paper-lane is-" + state + "'>")
				.append($("<i class='fa " + icon + "'>"),
				        $("<span>").text(label)));
		});
		this.$root.append($card);
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

		/* The meta strip: verification as chips a reader can parse at a
		   glance, actions on the right. The gate's story, not a log line. */
		var redactedNumbers = (verification.sentences_redacted_numbers || []).length;
		var redactedTokens = (verification.sentences_redacted_tokens || []).length;
		var totalRedacted = redactedNumbers + redactedTokens;
		var qaFailing = verification.figures_failing_qa || 0;
		var $meta = $("<div class='pa-paper-meta'>");

		function chip(cls, icon, html) {
			return $("<span class='pa-paper-chip " + cls + "'>")
				.append($("<i class='fa " + icon + "'>"), $("<span>").html(html));
		}
		$meta.append(
			chip("is-ok", "fa-check-circle",
			     "<b>" + (verification.facts_substituted || 0) +
			     "</b>&nbsp;numbers traced to tool results"),
			chip(totalRedacted ? "is-warn" : "is-ok",
			     totalRedacted ? "fa-scissors" : "fa-shield",
			     totalRedacted
			     ? "<b>" + totalRedacted + "</b>&nbsp;sentence(s) removed by the gate"
			     : "no sentence removed by the gate"),
			chip("", "fa-quote-right",
			     "<b>" + (verification.citations_kept || 0) + "</b>&nbsp;citations" +
			     ((verification.citations_dropped || 0)
			      ? " (<b>" + verification.citations_dropped + "</b> dropped)" : "")),
			chip(qaFailing ? "is-warn" : "is-ok", "fa-picture-o",
			     "<b>" + (verification.figures_total || 0) + "</b>&nbsp;figures" +
			     (qaFailing ? " (<b>" + qaFailing + "</b> failing QA)" : ", QA clean")));
		$meta.append($("<span class='pa-paper-actions'>").append(
			$("<a href='javascript:void(0)' class='pa-paper-btn'>")
				.html('<i class="fa fa-download"></i> Markdown')
				.on("click", function() {
					var blob = new Blob([markdown], {type: "text/markdown"});
					var a = document.createElement("a");
					a.href = URL.createObjectURL(blob);
					a.download = "paintomics-paper-" + me.jobID + ".md";
					document.body.appendChild(a);
					a.click();
					document.body.removeChild(a);
					URL.revokeObjectURL(a.href);
				})));

		var $paper = $("<div class='pa-paper-body'>");
		if (window.marked) {
			$paper.html(marked.parse(rendered));
		} else {
			$paper.text(markdown);
		}
		this.$root.append($meta, $paper);
	};

	return this;
}
