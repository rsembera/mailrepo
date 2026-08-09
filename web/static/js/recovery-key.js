/**
 * Recovery key screen.
 *
 * The key is rendered into the page by the server and exists nowhere else —
 * not in the session, not on disk, not in the database. Everything here is
 * about helping the user get it off the screen and into somewhere durable
 * before they navigate away.
 *
 * No build step: plain DOM, no imports.
 */
(function () {
    'use strict';

    const keyEl = document.getElementById('recovery-key-value');
    const confirmEl = document.getElementById('confirm-saved');
    const continueEl = document.getElementById('continue-button');

    if (!keyEl) {
        return;
    }

    const recoveryKey = keyEl.textContent.trim();

    function flash(button, message) {
        const original = button.textContent;
        button.textContent = message;
        button.disabled = true;
        setTimeout(function () {
            button.textContent = original;
            button.disabled = false;
        }, 2000);
    }

    const copyButton = document.getElementById('copy-recovery-key');
    if (copyButton) {
        copyButton.addEventListener('click', function () {
            // Clipboard API needs a secure context. MailRepo runs on
            // 127.0.0.1, which counts as secure, but fall back rather than
            // leaving the button silently dead if it is ever unavailable.
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(recoveryKey).then(
                    function () { flash(copyButton, 'Copied'); },
                    function () { selectKeyText(); flash(copyButton, 'Press Cmd+C'); }
                );
            } else {
                selectKeyText();
                flash(copyButton, 'Press Cmd+C');
            }
        });
    }

    function selectKeyText() {
        const range = document.createRange();
        range.selectNodeContents(keyEl);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
    }

    const printButton = document.getElementById('print-recovery-key');
    if (printButton) {
        printButton.addEventListener('click', function () {
            window.print();
        });
    }

    const downloadButton = document.getElementById('download-recovery-key');
    if (downloadButton) {
        downloadButton.addEventListener('click', function () {
            const stamp = new Date().toISOString().slice(0, 10);
            const body = [
                'MailRepo recovery key',
                'Created: ' + stamp,
                '',
                recoveryKey,
                '',
                'This key opens your MailRepo archive WITHOUT the master password.',
                'Anyone who has it has full access to your archived mail.',
                '',
                'Keep it somewhere private and separate from your password.',
                'If it is ever lost or exposed, generate a new one from',
                'Settings > Security, which immediately revokes this one.',
                ''
            ].join('\n');

            const blob = new Blob([body], { type: 'text/plain' });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = 'mailrepo-recovery-key-' + stamp + '.txt';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);

            flash(downloadButton, 'Downloaded');
        });
    }

    if (confirmEl && continueEl) {
        confirmEl.addEventListener('change', function () {
            continueEl.disabled = !confirmEl.checked;
        });
    }

    // Leaving this page loses the key permanently, so make that explicit
    // for anything other than the deliberate Continue action.
    let leavingDeliberately = false;
    const form = confirmEl ? confirmEl.closest('form') : null;
    if (form) {
        form.addEventListener('submit', function () {
            leavingDeliberately = true;
        });
    }

    window.addEventListener('beforeunload', function (event) {
        if (leavingDeliberately) {
            return;
        }
        event.preventDefault();
        event.returnValue = '';
    });
})();
