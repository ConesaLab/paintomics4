/* global Ext, $, marked, SERVER_URL_AI_INTERPRET_REPORT, SERVER_URL_AI_INTERPRET_CHAT */

function PA_AIInterpretView() {
    this.$root = null;
    this.isExpanded = false;
    this.chatHistory = [];
    this.isWaitingResponse = false;
    this.jobID = null;
    this.reportLoaded = false;
    this.onRetry = null;
    this.isFullscreen = false;

    this.init = function(jobID) {
        this.jobID = jobID;
        var me = this;

        var html =
            '<div class="ai-widget" style="display:none;">' +
            '  <div class="ai-widget-panel">' +
            '    <div class="ai-widget-header">' +
            '      <span class="ai-widget-header-title">AI Assistant</span>' +
            '      <div class="ai-widget-header-actions">' +
            '        <button class="ai-fullscreen-btn" title="Fullscreen">&#x26F6;</button>' +
            '        <button class="ai-minimize-btn" title="Minimize">&mdash;</button>' +
            '      </div>' +
            '    </div>' +
            '    <div class="ai-widget-progress" style="display:none;">' +
            '      <div class="ai-progress-detail">Starting...</div>' +
            '      <div class="ai-progress-track"><div class="ai-progress-fill" style="width:0%"></div></div>' +
            '    </div>' +
            '    <div class="ai-widget-messages"></div>' +
            '    <div class="ai-widget-input-area">' +
            '      <textarea placeholder="Ask a follow-up question..." rows="1"></textarea>' +
            '      <button class="ai-send-btn" title="Send">&#10148;</button>' +
            '    </div>' +
            '  </div>' +
            '  <button class="ai-widget-fab" title="AI Interpretation">' +
            '    <span class="ai-fab-icon">&#129302;</span>' +
            '    <span class="ai-widget-fab-badge" style="display:none;"></span>' +
            '  </button>' +
            '</div>';

        this.$root = $(html);
        $("body").append(this.$root);

        // Bind events
        this.$root.find(".ai-widget-fab").on("click", function() {
            me.toggle();
        });

        this.$root.find(".ai-minimize-btn").on("click", function() {
            me.collapse();
        });

        this.$root.find(".ai-fullscreen-btn").on("click", function() {
            me.toggleFullscreen();
        });

        this.$root.find(".ai-send-btn").on("click", function() {
            me.sendChat();
        });

        this.$root.find(".ai-widget-input-area textarea").on("keydown", function(e) {
            if (e.keyCode === 13 && !e.shiftKey) {
                e.preventDefault();
                me.sendChat();
            }
        });
    };

    this.show = function() {
        if (this.$root) {
            this.$root.fadeIn(300);
        }
    };

    this.hide = function() {
        if (this.$root) {
            this.$root.fadeOut(300);
        }
    };

    this.expand = function() {
        if (!this.$root) return;
        this.$root.find(".ai-widget-panel").addClass("is-expanded");
        this.isExpanded = true;
        // Auto-scroll messages
        var msgs = this.$root.find(".ai-widget-messages");
        if (msgs.length) {
            msgs.scrollTop(msgs[0].scrollHeight);
        }
        // Auto-load report if done and not loaded
        if (!this.reportLoaded && this._lastStatus === "done") {
            this.loadReport();
        }
    };

    this.collapse = function() {
        if (!this.$root) return;
        if (this.isFullscreen) {
            this.$root.find(".ai-widget-panel").removeClass("is-fullscreen");
            this.$root.find(".ai-widget-fab").show();
            this.$root.find(".ai-fullscreen-btn").html("&#x26F6;").attr("title", "Fullscreen");
            this.isFullscreen = false;
        }
        this.$root.find(".ai-widget-panel").removeClass("is-expanded");
        this.isExpanded = false;
    };

    this.toggle = function() {
        if (this.isExpanded) {
            this.collapse();
        } else {
            this.expand();
        }
    };

    this.toggleFullscreen = function() {
        if (!this.$root) return;
        var $panel = this.$root.find(".ai-widget-panel");
        var $fab = this.$root.find(".ai-widget-fab");
        var $btn = this.$root.find(".ai-fullscreen-btn");

        if (this.isFullscreen) {
            // Exit fullscreen
            $panel.removeClass("is-fullscreen");
            $fab.show();
            $btn.html("&#x26F6;").attr("title", "Fullscreen");
            this.isFullscreen = false;
        } else {
            // Enter fullscreen - make sure panel is expanded first
            if (!this.isExpanded) {
                this.expand();
            }
            $panel.addClass("is-fullscreen");
            $fab.hide();
            $btn.html("&#x2716;").attr("title", "Exit fullscreen");
            this.isFullscreen = true;
        }
        // Auto-scroll messages
        var msgs = this.$root.find(".ai-widget-messages");
        if (msgs.length) {
            msgs.scrollTop(msgs[0].scrollHeight);
        }
    };

    this._lastStatus = null;

    this.updateProgress = function(status, percent, detail) {
        if (!this.$root) return;
        var $progress = this.$root.find(".ai-widget-progress");
        var $fab = this.$root.find(".ai-widget-fab");
        var $badge = this.$root.find(".ai-widget-fab-badge");

        this._lastStatus = status;

        if (status === "done") {
            $progress.hide();
            $fab.removeClass("is-processing");
            $badge.css("background", "#66bb6a").html("&#10003;").show();
            // Auto-load if expanded
            if (this.isExpanded && !this.reportLoaded) {
                this.loadReport();
            }
        } else if (status === "error") {
            $progress.show().removeClass("is-done").addClass("is-error");
            this.$root.find(".ai-progress-fill").css("width", "100%");
            this.$root.find(".ai-progress-detail").html(
                (detail || "Unknown error") +
                ' <button class="ai-retry-btn">Retry</button>'
            );
            $fab.removeClass("is-processing");
            $badge.css("background", "#ef5350").html("!").show();
            // Bind retry
            var me = this;
            this.$root.find(".ai-retry-btn").on("click", function() {
                $progress.removeClass("is-error");
                me.$root.find(".ai-progress-fill").css("width", "0%");
                me.$root.find(".ai-progress-detail").text("Retrying...");
                $badge.hide();
                $fab.addClass("is-processing");
                if (typeof me.onRetry === "function") {
                    me.onRetry();
                }
            });
        } else {
            // Processing
            $progress.show().removeClass("is-done is-error");
            this.$root.find(".ai-progress-fill").css("width", percent + "%");
            this.$root.find(".ai-progress-detail").text(detail || status || "Processing...");
            $fab.addClass("is-processing");
            $badge.hide();
        }
    };

    this.loadReport = function() {
        var me = this;
        $.ajax({
            type: "POST",
            url: SERVER_URL_AI_INTERPRET_REPORT,
            data: { jobID: me.jobID },
            success: function(response) {
                if (response.success && response.report) {
                    me.displayReport(response.report, response.papers || []);
                    me.displayCitations(response.papers || []);
                    me.reportLoaded = true;
                } else if (response.status === "error") {
                    me.addMessage("assistant",
                        "The AI interpretation failed: **" + (response.message || "Unknown error") + "**");
                } else {
                    me.addMessage("assistant",
                        "The AI interpretation is still in progress. Please wait for it to complete.");
                }
            },
            error: function() {
                me.addMessage("assistant", "Failed to load the report. Please try again.");
            }
        });
    };

    this._preprocessMarkdown = function(text) {
        // Ensure blank line before headings (required by CommonMark)
        text = text.replace(/([^\n])\n(#{1,6}\s)/g, "$1\n\n$2");
        // Ensure blank line before horizontal rules
        text = text.replace(/([^\n])\n(---+)/g, "$1\n\n$2");
        // Ensure blank line after horizontal rules
        text = text.replace(/(---+)\n([^\n])/g, "$1\n\n$2");
        // Fix numbered headings that LLM produces like "### 1. Title" inside lists
        // Convert "N. ### Title" pattern to "### N. Title"
        text = text.replace(/^(\d+)\.\s+(#{1,6}\s)/gm, "$2$1. ");
        return text;
    };

    this.displayReport = function(reportText, papers) {
        var html = "";
        try {
            reportText = this._preprocessMarkdown(reportText);
            html = marked.parse(reportText);
        } catch(e) {
            html = "<pre>" + reportText + "</pre>";
        }
        // Build ref_index -> pmid mapping and linkify [N] citations
        if (papers && papers.length > 0) {
            var refMap = {};
            for (var i = 0; i < papers.length; i++) {
                if (papers[i].ref_index && papers[i].pmid) {
                    refMap[papers[i].ref_index] = papers[i].pmid;
                }
            }
            html = html.replace(/\[(\d+)\]/g, function(match, num) {
                var pmid = refMap[parseInt(num, 10)];
                if (pmid) {
                    return '<a href="https://pubmed.ncbi.nlm.nih.gov/' + pmid + '/" target="_blank" rel="noopener" class="ai-citation-link" title="Open in PubMed">[' + num + ']</a>';
                }
                return match;
            });
        }
        this.addMessage("assistant", html, true);
    };

    this.displayCitations = function(papers) {
        if (!papers || papers.length === 0) return;

        var toggleHtml = '<div class="ai-citations-toggle">&#9656; Show ' + papers.length + ' citations</div>';
        var listHtml = '<div class="ai-citations-list" style="display:none;">';
        for (var i = 0; i < papers.length; i++) {
            var p = papers[i];
            var refLabel = p.ref_index ? '[' + p.ref_index + '] ' : '';
            listHtml += '<div class="ai-citation-item" data-pmid="' + (p.pmid || "") + '">';
            listHtml += '  <div class="ai-citation-title"><span class="ai-citation-ref">' + refLabel + '</span>' + (p.title || "Untitled") + '</div>';
            listHtml += '  <div class="ai-citation-meta">' + (p.first_author || "") + ' et al., ' + (p.journal || "") + ' (' + (p.year || "") + ')</div>';
            listHtml += '  <div class="ai-citation-pmid">PMID: ' + (p.pmid || "N/A") + '</div>';
            listHtml += '</div>';
        }
        listHtml += '</div>';

        var $container = this.$root.find(".ai-widget-messages");
        $container.append(toggleHtml + listHtml);

        // Bind toggle
        var $toggle = $container.find(".ai-citations-toggle").last();
        var $list = $container.find(".ai-citations-list").last();
        $toggle.on("click", function() {
            if ($list.is(":visible")) {
                $list.slideUp(200);
                $toggle.html("&#9656; Show " + papers.length + " citations");
            } else {
                $list.slideDown(200);
                $toggle.html("&#9662; Hide citations");
            }
        });

        // Citation click opens PubMed
        $list.find(".ai-citation-item").on("click", function() {
            var pmid = $(this).data("pmid");
            if (pmid) {
                window.open("https://pubmed.ncbi.nlm.nih.gov/" + pmid + "/", "_blank");
            }
        });

        // Scroll to bottom
        $container.scrollTop($container[0].scrollHeight);
    };

    this.addMessage = function(role, content, isHtml) {
        var $container = this.$root.find(".ai-widget-messages");
        var cssClass = role === "user" ? "ai-msg-user" : "ai-msg-assistant";
        var label = role === "user" ? "You" : "AI Assistant";
        var bubbleContent = isHtml ? content : $("<div>").text(content).html();

        if (role === "assistant" && !isHtml) {
            try {
                bubbleContent = marked.parse(this._preprocessMarkdown(content));
            } catch(e) {
                // fallback to escaped text
            }
        }

        var msgHtml = '<div class="ai-message ' + cssClass + '">' +
                      '  <div class="ai-msg-label">' + label + '</div>' +
                      '  <div class="ai-msg-bubble">' + bubbleContent + '</div>' +
                      '</div>';
        $container.append(msgHtml);
        $container.scrollTop($container[0].scrollHeight);
    };

    this.addLoadingIndicator = function() {
        var $container = this.$root.find(".ai-widget-messages");
        $container.append(
            '<div class="ai-message ai-msg-assistant ai-loading-msg">' +
            '  <div class="ai-loading"><div class="ai-loading-dots"><span></span><span></span><span></span></div> Thinking...</div>' +
            '</div>'
        );
        $container.scrollTop($container[0].scrollHeight);
    };

    this.removeLoadingIndicator = function() {
        if (this.$root) {
            this.$root.find(".ai-loading-msg").remove();
        }
    };

    this.sendChat = function() {
        var me = this;
        var $input = me.$root.find(".ai-widget-input-area textarea");
        var message = $input.val().trim();

        if (!message || me.isWaitingResponse) return;

        $input.val("");
        me.addMessage("user", message);
        me.isWaitingResponse = true;
        me.addLoadingIndicator();
        me.$root.find(".ai-send-btn").prop("disabled", true);

        $.ajax({
            type: "POST",
            url: SERVER_URL_AI_INTERPRET_CHAT,
            data: {
                jobID: me.jobID,
                message: message
            },
            success: function(response) {
                me.removeLoadingIndicator();
                me.isWaitingResponse = false;
                me.$root.find(".ai-send-btn").prop("disabled", false);

                if (response.success && response.response) {
                    me.addMessage("assistant", response.response);
                } else {
                    me.addMessage("assistant", "Sorry, I couldn't process your question. " + (response.message || ""));
                }
            },
            error: function() {
                me.removeLoadingIndicator();
                me.isWaitingResponse = false;
                me.$root.find(".ai-send-btn").prop("disabled", false);
                me.addMessage("assistant", "Failed to get a response. Please try again.");
            }
        });
    };

    this.destroy = function() {
        if (this.$root) {
            this.$root.remove();
            this.$root = null;
        }
        this.isExpanded = false;
        this.reportLoaded = false;
        this.chatHistory = [];
    };
}
