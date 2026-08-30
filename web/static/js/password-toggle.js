/**
 * Show/hide toggle for password fields.
 *
 * Auto-wires every input[type="password"] present at load: wraps it,
 * adds the eye button, and flips input.type on click. Ported from
 * EdgeCase (cda8719) with its wiring changed from inline onclick to
 * listeners — house style, and safe under a future CSP.
 *
 * Traps this guards against (each one is a real way this widget breaks,
 * most of them found the hard way in Daybook — see its PLAN.md item 9ab):
 * - The button is type="button"; anything else submits the form.
 * - The right-hand reserve is NOT set in CSS. Page rules like
 *   `.form-group input[type="password"] { padding: ... }` outweigh any
 *   wrapper rule and the shorthand wipes padding-right — a fix that
 *   passes every static check while doing nothing. The reserve is set
 *   inline here, computed from the button's measured band plus a small
 *   margin, so it cannot lose a specificity fight and it recalibrates
 *   itself if the button ever changes size. (Safari's AutoFill key
 *   tracks padding-right one-for-one, so it parks itself just left of
 *   the reserve; no extra lane is needed and our button never moves.)
 * - The reserve lives on the input via this script, never keyed on the
 *   input's type: revealing flips type to "text", and a type-keyed rule
 *   would reshuffle the layout on every tap of the eye.
 * - The field re-masks on form submit. The naive version (flip type in
 *   a submit listener) changes the DOM but the webview never repaints
 *   once navigation starts, so the password stays on screen through the
 *   whole KDF wait. Submission is deferred by one painted frame instead.
 * - Inputs added to the DOM later are NOT wired; call
 *   window.wirePasswordToggles(container) after inserting one.
 *
 * Plain script, not a module: auth pages load it directly from base.html.
 */
(function () {
    'use strict';

    const EYE_OPEN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>';
    const EYE_CLOSED = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="display:none"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"></path><line x1="1" y1="1" x2="23" y2="23"></line></svg>';

    function setShown(input, button, shown) {
        input.type = shown ? 'text' : 'password';
        button.querySelector('svg:first-of-type').style.display = shown ? 'none' : '';
        button.querySelector('svg:last-of-type').style.display = shown ? '' : 'none';
        button.setAttribute('aria-label', shown ? 'Hide password' : 'Show password');
        button.setAttribute('aria-pressed', shown ? 'true' : 'false');
    }

    function wire(input) {
        if (input.dataset.toggleWired || input.dataset.noToggle !== undefined) return;
        input.dataset.toggleWired = '1';

        const wrapper = document.createElement('span');
        wrapper.className = 'password-toggle-wrapper';
        input.parentNode.insertBefore(wrapper, input);
        wrapper.appendChild(input);

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'password-toggle-btn';
        button.innerHTML = EYE_OPEN + EYE_CLOSED;
        wrapper.appendChild(button);
        setShown(input, button, false);

        // The reserve: measured band + 4px margin (relationship, not a
        // constant — Daybook calibrated 46 for a 44px band; ours differs).
        function applyReserve() {
            const band = wrapper.getBoundingClientRect().right
                - button.getBoundingClientRect().left;
            if (band > 0) input.style.paddingRight = Math.ceil(band + 4) + 'px';
        }
        if (document.readyState === 'complete') {
            applyReserve();
        } else {
            window.addEventListener('load', applyReserve, { once: true });
        }
        requestAnimationFrame(applyReserve);

        button.addEventListener('click', function () {
            setShown(input, button, input.type === 'password');
            input.focus();
        });

        // Never submit revealed — and make sure the re-mask is actually
        // painted. Flipping type inside the submit is invisible: the
        // webview stops repainting once navigation begins, so the
        // password would sit readable through the whole KDF wait. If any
        // field is revealed, hold the submit, re-mask, let one frame
        // paint, then resubmit for real.
        const form = input.form;
        if (form && !form.dataset.toggleRemask) {
            form.dataset.toggleRemask = '1';
            form.addEventListener('submit', function (event) {
                if (form.dataset.toggleResubmitting) return;
                const revealed = form.querySelectorAll('input[data-toggle-wired][type="text"]');
                if (revealed.length === 0) return;
                event.preventDefault();
                revealed.forEach(function (el) {
                    el.dispatchEvent(new CustomEvent('password-toggle:mask'));
                });
                requestAnimationFrame(function () {
                    requestAnimationFrame(function () {
                        form.dataset.toggleResubmitting = '1';
                        if (typeof form.requestSubmit === 'function') {
                            form.requestSubmit(event.submitter || undefined);
                        } else {
                            form.submit();
                        }
                        delete form.dataset.toggleResubmitting;
                    });
                });
            });
        }
        input.addEventListener('password-toggle:mask', function () {
            setShown(input, button, false);
        });
    }

    function wirePasswordToggles(root) {
        (root || document).querySelectorAll('input[type="password"]').forEach(wire);
    }

    window.wirePasswordToggles = wirePasswordToggles;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { wirePasswordToggles(); });
    } else {
        wirePasswordToggles();
    }
})();
