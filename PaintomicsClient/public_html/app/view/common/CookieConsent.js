/*********************************************************************
 * COOKIE CONSENT                                   ******************
 *********************************************************************
 * The consent card in the corner, self-contained.
 *
 * This replaces the cookieconsent@3 CDN bundle. That library is
 * unmaintained, painted a grey banner no design token could reach, and
 * its `location: true` option asked a third-party geo-IP service where
 * the visitor was before the visitor had consented to anything. Nothing
 * in the product ever read its status beyond a console.log, so all it
 * owed a replacement was: show a notice, remember the answer.
 *
 * Storage is one localStorage key, with a cookie fallback for private
 * windows where localStorage throws. The old library stored its answer
 * in a `cookieconsent_status` cookie; that is read once and migrated so
 * returning visitors are not asked again for a choice they already made.
 *
 * Markup and styling live apart on purpose: this file injects the card
 * (see resources/css/cookie-consent.css for its look), and the card is
 * `data-guides="ignore"` because a floating overlay is off the layout
 * rails by design.
 *********************************************************************/
(function () {
	"use strict";

	var STORAGE_KEY = "pa-cookie-consent";
	var LEGACY_COOKIE = "cookieconsent_status";
	var ACCEPTED = "accepted";
	var DECLINED = "declined";

	function readCookie(name) {
		var match = document.cookie.match(new RegExp("(?:^|;\\s*)" + name + "=([^;]*)"));
		return match ? decodeURIComponent(match[1]) : null;
	}

	function readChoice() {
		var value = null;
		try { value = window.localStorage.getItem(STORAGE_KEY); } catch (e) { /* private mode */ }
		return value || readCookie(STORAGE_KEY) || null;
	}

	function storeChoice(value) {
		try { window.localStorage.setItem(STORAGE_KEY, value); } catch (e) { /* private mode */ }
		document.cookie = STORAGE_KEY + "=" + value + ";path=/;max-age=" + (60 * 60 * 24 * 365) + ";SameSite=Lax";
	}

	/* What cookieconsent@3 recorded, translated. Its "dismiss" was the only
	 * button most visitors ever saw ("Got it!"), so it counts as accepted. */
	function legacyChoice() {
		var value = readCookie(LEGACY_COOKIE);
		if (value === "deny") { return DECLINED; }
		if (value === "allow" || value === "dismiss") { return ACCEPTED; }
		return null;
	}

	function currentStatus() {
		var choice = readChoice();
		if (choice) { return choice; }
		var migrated = legacyChoice();
		if (migrated) { storeChoice(migrated); }
		return migrated;
	}

	function dismiss(card, choice) {
		storeChoice(choice);
		try {
			window.dispatchEvent(new CustomEvent("pa:cookie-consent", { detail: { status: choice } }));
		} catch (e) { /* CustomEvent missing: nobody to tell, nothing lost */ }
		card.classList.add("pa-cookie-card--leaving");
		window.setTimeout(function () {
			if (card.parentNode) { card.parentNode.removeChild(card); }
		}, 220);
	}

	function show() {
		if (document.getElementById("paCookieConsent")) { return; }

		var card = document.createElement("aside");
		card.id = "paCookieConsent";
		card.className = "pa-cookie-card";
		card.setAttribute("role", "region");
		card.setAttribute("aria-label", "Cookies notice");
		card.setAttribute("data-guides", "ignore");
		card.innerHTML =
			'<div class="pa-cookie-card__icon" aria-hidden="true">' +
				'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
					'<path d="M12 2a10 10 0 1 0 10 10 4 4 0 0 1-5-5 4 4 0 0 1-5-5"/>' +
					'<path d="M8.5 8.5v.01"/><path d="M16 15.5v.01"/><path d="M12 12v.01"/>' +
					'<path d="M11 17v.01"/><path d="M7 14v.01"/>' +
				'</svg>' +
			'</div>' +
			'<div class="pa-cookie-card__body">' +
				'<h2 class="pa-cookie-card__title">Cookies on PaintOmics</h2>' +
				'<p class="pa-cookie-card__text">We use cookies to keep your session and remember your preferences between visits. ' +
					'<a href="conditions.html" target="_blank" rel="noopener">Learn more</a></p>' +
			'</div>' +
			'<div class="pa-cookie-card__actions">' +
				'<button type="button" class="pa-cookie-card__btn pa-cookie-card__btn--quiet">Decline</button>' +
				'<button type="button" class="pa-cookie-card__btn pa-cookie-card__btn--primary">Accept</button>' +
			'</div>';

		card.querySelector(".pa-cookie-card__btn--quiet").addEventListener("click", function () {
			dismiss(card, DECLINED);
		});
		card.querySelector(".pa-cookie-card__btn--primary").addEventListener("click", function () {
			dismiss(card, ACCEPTED);
		});

		document.body.appendChild(card);
	}

	function init() {
		if (!currentStatus()) { show(); }
	}

	window.paCookieConsent = {
		status: currentStatus,
		hasConsented: function () { return currentStatus() === ACCEPTED; },
		reset: function () {
			try { window.localStorage.removeItem(STORAGE_KEY); } catch (e) { /* private mode */ }
			document.cookie = STORAGE_KEY + "=;path=/;max-age=0";
			document.cookie = LEGACY_COOKIE + "=;path=/;max-age=0";
			show();
		}
	};

	if (document.readyState === "loading") {
		document.addEventListener("DOMContentLoaded", init);
	} else {
		init();
	}
})();
