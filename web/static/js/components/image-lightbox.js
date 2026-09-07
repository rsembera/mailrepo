/**
 * MailRepo - Image Lightbox
 *
 * Click-to-zoom overlay for images in the email viewer. Serves two
 * sources:
 *   - inline images in the rendered body iframe (already data: URLs after
 *     the server's cid: substitution), via attachImageZoom(doc)
 *   - image attachments listed under the body, via openImageLightbox({blob})
 *
 * The overlay lives in the main app document, not the email iframe, so it
 * is never subject to the email's own CSS. Only an <img> ever receives the
 * email-supplied src: <img> does not execute script for any image type
 * (including SVG), so this adds no capability the body iframe did not
 * already have.
 *
 * Two zoom states: "fit" (whole image inside the viewport) and "actual"
 * (1:1 pixels, stage scrolls). Click the image or the toolbar button to
 * toggle; toggling is disabled when the image already fits at 1:1.
 */

import { isDesktop, openBlobExternally } from '../desktop.js';

/** Images smaller than this on either axis are ignored: tracking pixels,
 *  spacers, emoji, social icons. */
const MIN_ZOOMABLE_PX = 48;

let root = null;
let stage = null;
let imgEl = null;
let nameEl = null;
let sizeEl = null;
let toggleBtn = null;
let externalBtn = null;

let current = null;   // { src, blob, objectUrl, filename }
let mode = 'fit';     // 'fit' | 'actual'

function build() {
    if (root) return;
    root = document.createElement('div');
    root.id = 'imageLightbox';
    root.className = 'image-lightbox';
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-modal', 'true');
    root.setAttribute('aria-label', 'Image preview');
    root.tabIndex = -1;
    root.innerHTML = `
        <div class="image-lightbox-toolbar">
            <span class="image-lightbox-name"></span>
            <span class="image-lightbox-size"></span>
            <span class="image-lightbox-actions">
                <button type="button" class="image-lightbox-btn" data-lb="toggle" title="Actual size"><i data-lucide="maximize-2"></i></button>
                <button type="button" class="image-lightbox-btn" data-lb="download" title="Download"><i data-lucide="download"></i></button>
                <button type="button" class="image-lightbox-btn" data-lb="external" title="Open in default app" hidden><i data-lucide="external-link"></i></button>
                <button type="button" class="image-lightbox-btn" data-lb="close" title="Close (Esc)"><i data-lucide="x"></i></button>
            </span>
        </div>
        <div class="image-lightbox-stage"><img alt=""></div>
    `;
    document.body.appendChild(root);

    stage = root.querySelector('.image-lightbox-stage');
    imgEl = stage.querySelector('img');
    nameEl = root.querySelector('.image-lightbox-name');
    sizeEl = root.querySelector('.image-lightbox-size');
    toggleBtn = root.querySelector('[data-lb="toggle"]');
    externalBtn = root.querySelector('[data-lb="external"]');

    root.querySelector('[data-lb="close"]').addEventListener('click', closeImageLightbox);
    toggleBtn.addEventListener('click', toggleMode);
    root.querySelector('[data-lb="download"]').addEventListener('click', downloadCurrent);
    externalBtn.addEventListener('click', openCurrentExternally);

    // Click on the dark stage (not the image) closes; click on the image toggles.
    stage.addEventListener('click', (e) => {
        if (e.target === imgEl) {
            if (!toggleBtn.disabled) toggleMode();
        } else {
            closeImageLightbox();
        }
    });
    imgEl.addEventListener('load', onImageLoaded);

    // Capture-phase so the viewer's own Escape / j / k handlers never see
    // keys while the lightbox is up.
    document.addEventListener('keydown', (e) => {
        if (!isImageLightboxOpen()) return;
        e.stopImmediatePropagation();
        if (e.key === 'Escape') {
            e.preventDefault();
            closeImageLightbox();
        }
    }, true);

    if (typeof lucide !== 'undefined') lucide.createIcons();
}

export function isImageLightboxOpen() {
    return !!(root && root.classList.contains('active'));
}

/**
 * Open the lightbox.
 * @param {Object} opts
 * @param {string} [opts.src]      - Image URL (data:, blob:, or same-origin)
 * @param {Blob}   [opts.blob]     - Image bytes; an object URL is created and revoked on close
 * @param {string} [opts.filename] - Shown in the toolbar and used for download
 */
export function openImageLightbox({ src, blob, filename } = {}) {
    build();
    releaseCurrent();

    let objectUrl = null;
    if (!src && blob) {
        objectUrl = URL.createObjectURL(blob);
        src = objectUrl;
    }
    if (!src) return;

    current = { src, blob: blob || null, objectUrl, filename: filename || '' };
    mode = 'fit';
    nameEl.textContent = current.filename || 'Image';
    sizeEl.textContent = '';
    toggleBtn.disabled = true;
    externalBtn.hidden = !isDesktop();
    applyMode();

    imgEl.src = src;
    root.classList.add('active');
    root.focus({ preventScroll: true });
}

export function closeImageLightbox() {
    if (!root) return;
    root.classList.remove('active');
    imgEl.removeAttribute('src');
    releaseCurrent();
}

function releaseCurrent() {
    if (current && current.objectUrl) URL.revokeObjectURL(current.objectUrl);
    current = null;
}

function onImageLoaded() {
    if (!current) return;
    const w = imgEl.naturalWidth;
    const h = imgEl.naturalHeight;
    sizeEl.textContent = w && h ? `${w} × ${h}` : '';
    // 1:1 only makes sense if the image would not fit anyway.
    const fits = w <= stage.clientWidth && h <= stage.clientHeight;
    toggleBtn.disabled = fits;
    applyMode();
}

function toggleMode() {
    mode = mode === 'fit' ? 'actual' : 'fit';
    applyMode();
}

function applyMode() {
    root.classList.toggle('actual-size', mode === 'actual');
    toggleBtn.title = mode === 'actual' ? 'Fit to window' : 'Actual size';
    if (mode === 'actual') {
        imgEl.style.cursor = 'zoom-out';
    } else {
        imgEl.style.cursor = toggleBtn.disabled ? 'default' : 'zoom-in';
    }
}

async function currentBlob() {
    if (!current) return null;
    if (current.blob) return current.blob;
    // data: and blob: URLs both resolve through fetch.
    const response = await fetch(current.src);
    current.blob = await response.blob();
    return current.blob;
}

function guessFilename(blob) {
    if (current && current.filename) return current.filename;
    const ext = { 'image/jpeg': 'jpg', 'image/png': 'png', 'image/gif': 'gif', 'image/webp': 'webp' }[blob?.type] || 'img';
    return `image.${ext}`;
}

async function downloadCurrent() {
    try {
        const blob = await currentBlob();
        if (!blob) return;
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = guessFilename(blob);
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (error) {
        console.error('Could not download image:', error);
    }
}

async function openCurrentExternally() {
    try {
        const blob = await currentBlob();
        if (blob) await openBlobExternally(blob, guessFilename(blob));
    } catch (error) {
        console.error('Could not open image externally:', error);
    }
}

function isZoomable(im) {
    return im.naturalWidth >= MIN_ZOOMABLE_PX && im.naturalHeight >= MIN_ZOOMABLE_PX;
}

function markZoomable(im) {
    if (isZoomable(im)) im.style.cursor = 'zoom-in';
}

function inlineImageName(im) {
    const alt = (im.getAttribute('alt') || im.getAttribute('title') || '').trim();
    if (alt && alt.length <= 80) return alt;
    return '';
}

/**
 * Make qualifying <img> elements in a rendered email body open the
 * lightbox on click. Call once per rendered iframe document. Images
 * wrapped in a link keep their link behaviour.
 * @param {Document} doc - The body iframe's document
 */
export function attachImageZoom(doc) {
    doc.querySelectorAll('img').forEach((im) => {
        if (im.complete) markZoomable(im);
        else im.addEventListener('load', () => markZoomable(im), { once: true });
    });

    doc.addEventListener('click', (e) => {
        const im = e.target && e.target.closest ? e.target.closest('img') : null;
        if (!im || im.closest('a[href]') || !isZoomable(im)) return;
        e.preventDefault();
        openImageLightbox({ src: im.currentSrc || im.src, filename: inlineImageName(im) });
    });
}
