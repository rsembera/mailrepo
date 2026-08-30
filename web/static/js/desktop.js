/**
 * Desktop shell bridge.
 *
 * In the packaged app the page runs inside a pywebview window, not a
 * browser. Two browser habits do not work there: opening a URL in a new
 * tab, and window.print(). Both are routed to the desktop shell instead
 * (launcher.py, DesktopApi), which writes the bytes to a private file and
 * asks the OS to open it — Preview for a PDF, and Preview's print dialog
 * is a real one.
 *
 * Everything else — <a download>, blob saves — goes through pywebview's
 * own native Save panel and needs nothing from here.
 *
 * In a normal browser every function here is a no-op that returns false,
 * so callers fall through to their browser behaviour.
 */

export function isDesktop() {
    return !!(window.pywebview && window.pywebview.api);
}

async function blobToBase64(blob) {
    const buffer = await blob.arrayBuffer();
    const bytes = new Uint8Array(buffer);
    let binary = '';
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return window.btoa(binary);
}

/**
 * Open a blob in the default application for its type.
 * Returns false (having done nothing) outside the desktop shell.
 */
export async function openBlobExternally(blob, filename) {
    if (!isDesktop()) return false;
    return window.pywebview.api.open_bytes(filename || 'file', await blobToBase64(blob));
}

/**
 * Fetch a same-origin URL (with the session cookie) and open the result
 * externally. Filename comes from Content-Disposition when present.
 */
export async function openUrlExternally(url, fallbackName) {
    if (!isDesktop()) return false;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Server error (${response.status})`);
    const cd = response.headers.get('Content-Disposition') || '';
    const match = cd.match(/filename="([^"]+)"/);
    const filename = match ? match[1] : (fallbackName || 'attachment');
    return openBlobExternally(await response.blob(), filename);
}

/**
 * Render a self-contained HTML document to PDF and open it for printing.
 */
export async function printHtmlExternally(title, html) {
    if (!isDesktop()) return false;
    return window.pywebview.api.print_html(title || 'Email', html);
}

/**
 * Intercept clicks on target="_blank" links: in the desktop shell those
 * would open in an external browser without the session, i.e. a login
 * page. Same-origin ones are fetched here and opened externally instead;
 * off-site ones are left to pywebview, which hands them to the browser.
 */
export function initDesktopLinkHandling() {
    if (!isDesktop()) return;
    document.addEventListener('click', (event) => {
        const link = event.target.closest('a[target="_blank"]');
        if (!link) return;
        const href = link.getAttribute('href') || '';
        if (!href || /^[a-z]+:/i.test(href)) return;  // absolute/off-site: leave it
        event.preventDefault();
        openUrlExternally(href, link.textContent.trim()).catch((error) => {
            console.error('Could not open link in desktop shell:', error);
        });
    }, true);
}
