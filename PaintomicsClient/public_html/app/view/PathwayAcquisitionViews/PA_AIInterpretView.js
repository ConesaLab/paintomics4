/* global Ext, $, marked, SERVER_URL_AI_INTERPRET_REPORT, SERVER_URL_AI_INTERPRET_CHAT */

if (typeof marked !== "undefined" && marked.use) {
    marked.use({
        gfm: true,
        breaks: true,
        pedantic: false,
        headerIds: false,
        mangle: false
    });
}

function PA_AIInterpretView() {
    this.$root = null;
    this.isExpanded = false;
    this.chatHistory = [];
    this.isWaitingResponse = false;
    this.jobID = null;
    this.reportLoaded = false;
    this.onRetry = null;
    this.isFullscreen = false;
    // id/name/source of the pathways the report was written from, used to turn
    // pathway mentions into links.
    this.pathwayIndex = [];
    this._pathwayRequestInFlight = null;

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

        // Delegated so it covers pathway links in the report, in chat replies,
        // and in per-pathway reports added later. Deliberately not an inline
        // onclick: the sanitiser strips on* attributes, and this keeps the
        // rendered report free of executable attributes.
        this.$root.find(".ai-widget-messages").on("click", ".ai-pathway-link", function(e) {
            e.preventDefault();
            me.openPathway($(this).attr("data-pathway-id"),
                           $(this).attr("data-pathway-name"));
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
                    me.pathwayIndex = response.pathways || [];
                    me.displayReport(response.report, response.papers || [], me.pathwayIndex);
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
        // Ensure blank line before unordered list starts when preceded by non-list content
        text = text.replace(/([^\n])\n([-*+] )/g, "$1\n\n$2");
        // Ensure blank line before ordered list starts when preceded by non-list content
        text = text.replace(/([^\n])\n(\d+\. )/g, "$1\n\n$2");
        // Fix numbered headings that LLM produces like "### 1. Title" inside lists
        // Convert "N. ### Title" pattern to "### N. Title"
        text = text.replace(/^(\d+)\.\s+(#{1,6}\s)/gm, "$2$1. ");
        // Normalize excessive blank lines (3+ newlines to 2)
        text = text.replace(/\n{3,}/g, "\n\n");
        return text;
    };

    // Tags and attributes allowed to survive sanitising. Everything the report
    // legitimately uses is markdown, so this covers the full output of marked
    // plus the two link types we add ourselves.
    var SANITIZE_ALLOWED_TAGS = {
        A:1, B:1, BLOCKQUOTE:1, BR:1, CODE:1, DD:1, DEL:1, DIV:1, DL:1, DT:1,
        EM:1, H1:1, H2:1, H3:1, H4:1, H5:1, H6:1, HR:1, I:1, LI:1, OL:1, P:1,
        PRE:1, SPAN:1, STRONG:1, SUB:1, SUP:1, TABLE:1, TBODY:1, TD:1, TH:1,
        THEAD:1, TR:1, UL:1
    };
    var SANITIZE_ALLOWED_ATTRS = {
        href:1, title:1, "class":1, target:1, rel:1,
        "data-pathway-id":1, "data-pathway-name":1
    };

    /**
     * Strip anything executable from report HTML.
     *
     * The report text is model output, and the model reads uploaded data and
     * the user's experiment-design field -- so it is untrusted input that was
     * being handed to the DOM verbatim. Parsing happens in an inert document
     * (DOMParser never runs scripts or fetches subresources), then the tree is
     * walked against a whitelist: unknown elements are unwrapped rather than
     * dropped so their text survives, every on* handler is removed, and href
     * values are restricted to http/https/mailto so javascript: URLs cannot
     * get through.
     */
    this._sanitizeHtml = function(html) {
        var doc;
        try {
            doc = new DOMParser().parseFromString("<body>" + html + "</body>", "text/html");
        } catch (e) {
            return $("<div>").text(html).html();
        }

        var walk = function(node) {
            var children = Array.prototype.slice.call(node.childNodes);
            for (var i = 0; i < children.length; i++) {
                var child = children[i];
                if (child.nodeType === 3) { continue; }          // text: always safe
                if (child.nodeType !== 1) {                       // comments, CDATA, ...
                    node.removeChild(child);
                    continue;
                }
                var tag = child.tagName.toUpperCase();
                if (tag === "SCRIPT" || tag === "STYLE" || tag === "IFRAME" ||
                    tag === "OBJECT" || tag === "EMBED" || tag === "FORM") {
                    // Drop these entirely -- their text content is not worth keeping.
                    node.removeChild(child);
                    continue;
                }
                walk(child);
                if (!SANITIZE_ALLOWED_TAGS[tag]) {
                    // Unwrap: keep the text, discard the element.
                    while (child.firstChild) {
                        node.insertBefore(child.firstChild, child);
                    }
                    node.removeChild(child);
                    continue;
                }
                var attrs = Array.prototype.slice.call(child.attributes);
                for (var a = 0; a < attrs.length; a++) {
                    var name = attrs[a].name.toLowerCase();
                    var value = attrs[a].value;
                    if (!SANITIZE_ALLOWED_ATTRS[name]) {
                        child.removeAttribute(attrs[a].name);
                        continue;
                    }
                    if (name === "href" && !/^(https?:|mailto:|#)/i.test(value.replace(/\s/g, ""))) {
                        child.removeAttribute(attrs[a].name);
                    }
                }
                if (tag === "A" && child.getAttribute("target") === "_blank") {
                    child.setAttribute("rel", "noopener noreferrer");
                }
            }
        };

        walk(doc.body);
        return doc.body.innerHTML;
    };

    /**
     * Turn pathway names mentioned in the report into links that open the
     * pathway.
     *
     * Matching is done against the pathway index the server analysed, over text
     * nodes of the already-sanitised DOM -- not with a regex over the HTML
     * string. Working on text nodes means a pathway name can never be spliced
     * into a tag or an attribute, and it keeps the matcher from firing inside
     * existing links, code spans, or the References section.
     *
     * Names are matched longest-first so "MAPK signaling pathway" wins over a
     * shorter pathway whose name is a prefix of it.
     */
    this._linkifyPathways = function(rootEl, pathways) {
        if (!pathways || !pathways.length) return;

        var named = pathways.filter(function(p) { return p && p.id && p.name; });
        if (!named.length) return;
        named.sort(function(a, b) { return b.name.length - a.name.length; });

        var byLowerName = {};
        var alternatives = named.map(function(p) {
            byLowerName[p.name.toLowerCase()] = p;
            return p.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        });
        var pattern = new RegExp("(" + alternatives.join("|") + ")", "gi");

        var SKIP = { A:1, CODE:1, PRE:1 };
        var linked = 0;

        var walk = function(node) {
            var child = node.firstChild;
            while (child) {
                var next = child.nextSibling;
                if (child.nodeType === 1) {
                    if (!SKIP[child.tagName.toUpperCase()]) walk(child);
                } else if (child.nodeType === 3 && child.nodeValue &&
                           child.nodeValue.trim().length > 2) {
                    var text = child.nodeValue;
                    pattern.lastIndex = 0;
                    if (pattern.test(text)) {
                        pattern.lastIndex = 0;
                        var frag = document.createDocumentFragment();
                        var cursor = 0, match;
                        while ((match = pattern.exec(text)) !== null) {
                            var pw = byLowerName[match[1].toLowerCase()];
                            if (!pw) continue;
                            if (match.index > cursor) {
                                frag.appendChild(document.createTextNode(
                                    text.slice(cursor, match.index)));
                            }
                            var a = document.createElement("a");
                            a.className = "ai-pathway-link";
                            a.setAttribute("href", "#");
                            a.setAttribute("data-pathway-id", pw.id);
                            a.setAttribute("data-pathway-name", pw.name);
                            a.setAttribute("title",
                                "Open " + pw.name + " and interpret it with AI");
                            a.appendChild(document.createTextNode(match[1]));
                            frag.appendChild(a);
                            cursor = match.index + match[1].length;
                            linked++;
                        }
                        if (cursor > 0) {
                            if (cursor < text.length) {
                                frag.appendChild(document.createTextNode(text.slice(cursor)));
                            }
                            node.replaceChild(frag, child);
                        }
                    }
                }
                child = next;
            }
        };

        walk(rootEl);
        return linked;
    };

    this.displayReport = function(reportText, papers, pathways) {
        var html = "";
        try {
            reportText = this._preprocessMarkdown(reportText);
            html = marked.parse(reportText);
        } catch(e) {
            // Escape rather than interpolate: this branch previously injected
            // unparsed model output straight into the DOM.
            html = "<pre>" + $("<div>").text(reportText).html() + "</pre>";
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

        html = this._sanitizeHtml(html);

        // Pathway names become links only after sanitising, so the anchors we
        // add are not themselves subject to the whitelist pass.
        var holder = document.createElement("div");
        holder.innerHTML = html;
        this._linkifyPathways(holder, pathways);

        this.addMessage("assistant", holder.innerHTML, true);
    };

    /**
     * Open a pathway from a citation in the report, and interpret it.
     *
     * Two things happen together, which is the point of the feature: the
     * pathway diagram opens in the main view, and a pathway-specific
     * interpretation is requested and shown in this widget. The widget lives on
     * document.body rather than inside a step view, so it stays visible over
     * the pathway once the app switches to step 4.
     */
    this.openPathway = function(pathwayID, pathwayName) {
        if (!pathwayID) return;
        var me = this;
        var label = pathwayName || pathwayID;

        this.expand();

        var opened = false;
        try {
            var mainView = (typeof application !== "undefined" && application.getMainView)
                ? application.getMainView() : null;
            var jobView = mainView ? (mainView.getSubView("PA_Step3JobView") ||
                                      mainView.getLastJobView()) : null;
            if (jobView && typeof jobView.paintSelectedPathway === "function") {
                jobView.paintSelectedPathway(pathwayID);
                opened = true;
            }
        } catch (e) {
            opened = false;
        }

        if (!opened) {
            // Report it rather than silently showing only the text: the user
            // asked for the pathway, and a missing diagram is a real outcome.
            this.addMessage("assistant",
                "I could not open the **" + label + "** diagram from here, but the " +
                "interpretation below still applies to that pathway.");
        }

        if (this._pathwayRequestInFlight === pathwayID) return;
        this._pathwayRequestInFlight = pathwayID;

        this.addMessage("user", "Interpret " + label + " for this experiment.");
        this.addLoadingIndicator();

        $.ajax({
            type: "POST",
            url: SERVER_URL_AI_INTERPRET_PATHWAY,
            data: { jobID: me.jobID, pathwayID: pathwayID },
            success: function(response) {
                me.removeLoadingIndicator();
                me._pathwayRequestInFlight = null;
                if (response && response.success && response.report) {
                    me.displayReport(response.report, response.papers || [],
                                     me.pathwayIndex || []);
                } else {
                    me.addMessage("assistant",
                        "I could not interpret **" + label + "**: " +
                        ((response && response.message) || "unknown error") + ".");
                }
            },
            error: function() {
                me.removeLoadingIndicator();
                me._pathwayRequestInFlight = null;
                me.addMessage("assistant",
                    "The request for **" + label + "** failed. Please try again.");
            }
        });
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
                // Chat replies are model output too, so they get the same
                // sanitising pass as the report, and the same pathway links.
                var parsed = this._sanitizeHtml(
                    marked.parse(this._preprocessMarkdown(content)));
                var holder = document.createElement("div");
                holder.innerHTML = parsed;
                this._linkifyPathways(holder, this.pathwayIndex);
                bubbleContent = holder.innerHTML;
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
