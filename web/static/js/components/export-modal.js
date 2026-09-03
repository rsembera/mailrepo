/**
 * Export modal — bulk export of archived emails.
 *
 * The modal is a single shared component that handles three sources:
 * - A folder (with optional subfolders)
 * - A search result set (current query + scope)
 * - A manual batch-selection of message IDs
 *
 * Lifecycle:
 * 1. openExportModal({source, ...}) shows the form view, including a
 *    destination-folder picker (defaults to ~/Downloads or whatever the
 *    user used last time).
 * 2. User picks format (pdf/eml/both), sort order, optional toggles, and
 *    clicks Export.
 * 3. We POST /api/export/start with `output_dir` set; server writes the
 *    file directly to disk in that location, with a chronological/numeric
 *    suffix if a same-named file exists.
 * 4. On `complete`, the modal shows where the file was saved with a
 *    "Reveal in Finder" / "Open in Files" button.
 * 5. On `error`, we surface the message and let the user retry or close.
 *
 * Per-session preferences (format/sort/cover/subfolders) live on
 * _exportPrefs. Last-chosen destination path persists across sessions
 * in localStorage under the `mailrepo.exportDir` key.
 */

import { escapeHtml } from '../utils.js';

const MODAL_ID = 'exportModal';
const STORAGE_KEY_DEST = 'mailrepo.exportDir';
const STORAGE_KEY_WARNING = 'mailrepo.exportWarningDismissed';

let _modalEl = null;
let _eventSource = null;
let _currentJobId = null;
let _currentSource = null;
let _currentDir = null;        // the destination directory the user has chosen
let _pickerCwd = null;         // path currently shown in the picker view
let _pickerSelectedDir = null; // directory selected within the picker (if any)

// Per-session preferences. Lives at module scope so it survives across
// modal opens (user's last-used format / sort / include-subfolders /
// include-cover / load-remote-content choices are remembered for the
// next export in the same browser session). Not persisted to disk.
let _exportPrefs = {
    format: 'pdf',
    sort_order: 'chronological',
    include_subfolders: true,
    include_cover: true,
    load_remote_content: false,
};

/**
 * Open the export modal. The `options` argument describes what to export:
 *   {source: 'folder',   folder_id, folder_name}
 *   {source: 'search',   query, folder_id?, include_subfolders?}
 *   {source: 'messages', message_ids, label}
 *
 * On the user\'s first export ever (per browser), show a one-time warning
 * about exports being unencrypted before the form view. Once dismissed
 * (with "Don\'t show again"), we skip directly to the form. The user can
 * opt into per-export encryption from inside the form regardless.
 */
export function openExportModal(options) {
    _currentSource = options || {};
    _currentDir = _loadSavedDir() || _defaultDir();
    _ensureModal();
    if (_loadWarningDismissed()) {
        _renderFormView();
    } else {
        _renderFirstUseWarning();
    }
    _modalEl.classList.add('active');
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function _loadWarningDismissed() {
    try { return localStorage.getItem(STORAGE_KEY_WARNING) === '1'; }
    catch { return false; }
}

function _saveWarningDismissed() {
    try { localStorage.setItem(STORAGE_KEY_WARNING, '1'); }
    catch {}
}

/**
 * One-time friction modal that explains what exports are and aren\'t.
 *
 * Goal: make sure new users notice that an export crosses MailRepo\'s
 * encryption-at-rest boundary \u2014 the resulting file on disk is plaintext
 * unless they choose to encrypt it. Not a hard block; just a pause.
 */
function _renderFirstUseWarning() {
    _modalEl.innerHTML = `
        <div class="modal-content export-modal">
            <div class="modal-header">
                <h2>About exports</h2>
                <button class="btn-icon" id="exportWarningCloseBtn" title="Cancel">
                    <i data-lucide="x"></i>
                </button>
            </div>
            <div class="export-first-warning">
                <div class="export-first-warning-icon"><i data-lucide="alert-triangle"></i></div>
                <p>An export creates a regular file on your computer outside MailRepo\u2019s encrypted database.</p>
                <p>The file you create can be opened by anyone with access to it. If you need protection, choose <strong>Encrypt this export</strong> in the next screen and set a password.</p>
                <p class="export-first-warning-hint">You\u2019ll see this once. You can always opt into encryption per export.</p>
                <label class="export-checkbox-row export-first-warning-dontshow">
                    <input type="checkbox" id="exportWarningDontShow" checked>
                    <span>Don\u2019t show this again</span>
                </label>
            </div>
            <div class="modal-actions">
                <button class="btn btn-secondary" id="exportWarningCancelBtn">Cancel</button>
                <button class="btn btn-primary" id="exportWarningContinueBtn">I understand \u2014 continue</button>
            </div>
        </div>
    `;
    _modalEl.querySelector('#exportWarningCloseBtn').addEventListener('click', _closeModal);
    _modalEl.querySelector('#exportWarningCancelBtn').addEventListener('click', _closeModal);
    _modalEl.querySelector('#exportWarningContinueBtn').addEventListener('click', () => {
        const dontShow = _modalEl.querySelector('#exportWarningDontShow')?.checked;
        if (dontShow) _saveWarningDismissed();
        _renderFormView();
        if (typeof lucide !== 'undefined') lucide.createIcons();
    });
    if (typeof lucide !== 'undefined') lucide.createIcons();
}


// ---------------------------------------------------------------------------
// Destination dir helpers
// ---------------------------------------------------------------------------

function _loadSavedDir() {
    try { return localStorage.getItem(STORAGE_KEY_DEST) || null; }
    catch { return null; }
}

function _saveDir(dir) {
    try { localStorage.setItem(STORAGE_KEY_DEST, dir); }
    catch {}
}

function _defaultDir() {
    // Default to the user\'s home directory. Cross-platform: the server
    // expands "~" via os.path.expanduser, which works on Mac (/Users/...)
    // and Linux (/home/...) alike.
    return '~';
}

function _displayDir(dir) {
    // Pretty-display ~ for the home directory if applicable. The server has
    // already realpath\'d in some cases, so handle both.
    return dir || '';
}

// ---------------------------------------------------------------------------
// Modal scaffolding
// ---------------------------------------------------------------------------

function _ensureModal() {
    if (_modalEl) return;
    _modalEl = document.createElement('div');
    _modalEl.id = MODAL_ID;
    _modalEl.className = 'modal-overlay';
    document.body.appendChild(_modalEl);

    _modalEl.addEventListener('click', (e) => {
        // Backdrop click closes only when not actively running an export.
        if (e.target === _modalEl && !_currentJobId) {
            _closeModal();
        }
    });
}

// ---------------------------------------------------------------------------
// Form view
// ---------------------------------------------------------------------------

function _renderFormView() {
    const src = _currentSource;
    const scopeText = _scopeDescription(src);
    const showSubfolderToggle = src.source === 'folder';
    const prefs = _exportPrefs;

    _modalEl.innerHTML = `
        <div class="modal-content export-modal">
            <div class="modal-header">
                <h2>Export\u2026</h2>
                <button class="btn-icon" id="exportCloseBtn" title="Close">
                    <i data-lucide="x"></i>
                </button>
            </div>

            <div class="export-scope">
                <div class="export-scope-label">Exporting</div>
                <div class="export-scope-value">${escapeHtml(scopeText)}</div>
            </div>

            <div class="export-section">
                <div class="export-section-title">Format</div>
                <div class="export-format-options">
                    <label class="export-format-option">
                        <input type="radio" name="export-format" value="pdf" ${prefs.format === 'pdf' ? 'checked' : ''}>
                        <div class="export-format-card">
                            <div class="export-format-icon"><i data-lucide="file-text"></i></div>
                            <div class="export-format-name">PDF</div>
                            <div class="export-format-hint">Combined document, one email per page</div>
                        </div>
                    </label>
                    <label class="export-format-option">
                        <input type="radio" name="export-format" value="eml" ${prefs.format === 'eml' ? 'checked' : ''}>
                        <div class="export-format-card">
                            <div class="export-format-icon"><i data-lucide="folder-archive"></i></div>
                            <div class="export-format-name">.eml ZIP</div>
                            <div class="export-format-hint">Original .eml files for other tools</div>
                        </div>
                    </label>
                    <label class="export-format-option">
                        <input type="radio" name="export-format" value="both" ${prefs.format === 'both' ? 'checked' : ''}>
                        <div class="export-format-card">
                            <div class="export-format-icon"><i data-lucide="layers"></i></div>
                            <div class="export-format-name">Both</div>
                            <div class="export-format-hint">PDF and .eml files together</div>
                        </div>
                    </label>
                </div>
            </div>

            <div class="export-section" id="export-pdf-options">
                <div class="export-section-title">PDF options</div>
                <label class="export-checkbox-row">
                    <input type="checkbox" id="export-include-cover" ${prefs.include_cover ? 'checked' : ''}>
                    <span>Include cover page</span>
                    <span class="export-hint">Title, scope, date range, email count</span>
                </label>
                <label class="export-checkbox-row">
                    <input type="checkbox" id="export-load-remote" ${prefs.load_remote_content ? 'checked' : ''}>
                    <span>Load remote images</span>
                    <span class="export-hint">Fetches images over the internet; slower, and senders can see you exported</span>
                </label>
                <div class="export-radio-group">
                    <div class="export-radio-label">Order</div>
                    <label class="export-radio-row">
                        <input type="radio" name="export-sort" value="chronological" ${prefs.sort_order === 'chronological' ? 'checked' : ''}>
                        <span>Oldest first</span>
                    </label>
                    <label class="export-radio-row">
                        <input type="radio" name="export-sort" value="reverse_chronological" ${prefs.sort_order === 'reverse_chronological' ? 'checked' : ''}>
                        <span>Newest first</span>
                    </label>
                </div>
            </div>

            ${showSubfolderToggle ? `
                <div class="export-section">
                    <label class="export-checkbox-row">
                        <input type="checkbox" id="export-include-subfolders" ${prefs.include_subfolders ? 'checked' : ''}>
                        <span>Include subfolders</span>
                        <span class="export-hint">Also export emails in nested folders</span>
                    </label>
                </div>
            ` : ''}

            <div class="export-section">
                <div class="export-section-title">Save to</div>
                <div class="export-dest-row">
                    <i data-lucide="folder" class="export-dest-icon"></i>
                    <span class="export-dest-path" id="exportDestPath" title="${escapeHtml(_currentDir)}">${escapeHtml(_displayDir(_currentDir))}</span>
                    <button class="btn btn-secondary btn-small" id="exportChooseDestBtn">Choose\u2026</button>
                </div>
            </div>

            <div class="export-section">
                <div class="export-section-title">Encryption</div>
                <label class="export-checkbox-row">
                    <input type="checkbox" id="export-encrypt">
                    <span>Encrypt this export</span>
                    <span class="export-hint">AES-256 password-protected ZIP</span>
                </label>
                <div class="export-encryption-fields" id="export-encryption-fields" style="display: none;">
                    <div class="export-password-row">
                        <input type="password" id="export-password" placeholder="Password" autocomplete="new-password">
                        <input type="password" id="export-password-confirm" placeholder="Confirm password" autocomplete="new-password">
                    </div>
                    <div class="export-password-feedback" id="export-password-feedback"></div>
                    <div class="export-encryption-note">
                        <i data-lucide="info"></i>
                        <span>macOS needs The Unarchiver (free); Windows 11 23H2+ and Linux unzip 6.0+ open it natively. Share the password separately \u2014 it's not stored anywhere.</span>
                    </div>
                </div>
            </div>

            <div class="modal-actions">
                <button class="btn btn-secondary" id="exportCancelBtn">Cancel</button>
                <button class="btn btn-primary" id="exportStartBtn">
                    <i data-lucide="download"></i>
                    Export
                </button>
            </div>
        </div>
    `;

    _modalEl.querySelector('#exportCloseBtn').addEventListener('click', _closeModal);
    _modalEl.querySelector('#exportCancelBtn').addEventListener('click', _closeModal);
    _modalEl.querySelector('#exportStartBtn').addEventListener('click', _startExport);
    _modalEl.querySelector('#exportChooseDestBtn').addEventListener('click', _openPickerView);

    const updatePdfOptionsVisibility = () => {
        const fmt = _modalEl.querySelector('input[name="export-format"]:checked')?.value || 'pdf';
        const pdfOpts = _modalEl.querySelector('#export-pdf-options');
        if (pdfOpts) {
            pdfOpts.style.display = (fmt === 'eml') ? 'none' : '';
        }
    };
    _modalEl.querySelectorAll('input[name="export-format"]').forEach(input => {
        input.addEventListener('change', updatePdfOptionsVisibility);
    });
    updatePdfOptionsVisibility();

    // Persist every form change into _exportPrefs so view switches
    // (e.g. opening the destination picker) don\'t lose the user\'s choices.
    const formInputs = _modalEl.querySelectorAll(
        'input[name="export-format"], input[name="export-sort"], '
        + '#export-include-cover, #export-include-subfolders, #export-load-remote'
    );
    formInputs.forEach(input => {
        input.addEventListener('change', _captureFormState);
    });

    // Encryption: show/hide fields, live-validate password match
    const encryptCb = _modalEl.querySelector('#export-encrypt');
    const encryptFields = _modalEl.querySelector('#export-encryption-fields');
    const pwInput = _modalEl.querySelector('#export-password');
    const pwConfirm = _modalEl.querySelector('#export-password-confirm');
    const pwFeedback = _modalEl.querySelector('#export-password-feedback');

    const updateEncryptionUi = () => {
        if (!encryptFields) return;
        encryptFields.style.display = encryptCb?.checked ? '' : 'none';
        // When toggled off, clear the password fields so they don\'t silently
        // get included on next submit if the user re-enables.
        if (!encryptCb?.checked && pwInput && pwConfirm) {
            pwInput.value = '';
            pwConfirm.value = '';
            if (pwFeedback) pwFeedback.textContent = '';
        }
    };

    const validatePassword = () => {
        if (!encryptCb?.checked || !pwFeedback) return;
        const a = pwInput?.value || '';
        const b = pwConfirm?.value || '';
        if (!a) {
            pwFeedback.textContent = '';
            pwFeedback.className = 'export-password-feedback';
        } else if (a.length < 8) {
            pwFeedback.textContent = 'Password should be at least 8 characters.';
            pwFeedback.className = 'export-password-feedback export-password-feedback-warn';
        } else if (b && a !== b) {
            pwFeedback.textContent = 'Passwords don\u2019t match.';
            pwFeedback.className = 'export-password-feedback export-password-feedback-warn';
        } else if (b && a === b) {
            pwFeedback.textContent = 'Passwords match.';
            pwFeedback.className = 'export-password-feedback export-password-feedback-ok';
        } else {
            pwFeedback.textContent = '';
            pwFeedback.className = 'export-password-feedback';
        }
    };

    encryptCb?.addEventListener('change', updateEncryptionUi);
    pwInput?.addEventListener('input', validatePassword);
    pwConfirm?.addEventListener('input', validatePassword);
    updateEncryptionUi();
}

/**
 * Read the current form values into _exportPrefs so they survive any
 * subsequent _renderFormView() call. Called on every form input change
 * AND right before switching to the picker view, so coming back to the
 * form view never silently resets the user\'s choices.
 *
 * Safe to call when the form view isn\'t mounted: missing inputs simply
 * leave existing prefs untouched.
 */
function _captureFormState() {
    if (!_modalEl) return;
    const fmt = _modalEl.querySelector('input[name="export-format"]:checked')?.value;
    const sort = _modalEl.querySelector('input[name="export-sort"]:checked')?.value;
    const cover = _modalEl.querySelector('#export-include-cover');
    const subs = _modalEl.querySelector('#export-include-subfolders');
    const loadRemote = _modalEl.querySelector('#export-load-remote');

    if (fmt) _exportPrefs.format = fmt;
    if (sort) _exportPrefs.sort_order = sort;
    if (cover) _exportPrefs.include_cover = cover.checked;
    if (subs) _exportPrefs.include_subfolders = subs.checked;
    if (loadRemote) _exportPrefs.load_remote_content = loadRemote.checked;
}

function _scopeDescription(src) {
    if (src.source === 'folder') {
        const name = src.folder_name || 'Folder';
        return `Folder: ${name}`;
    }
    if (src.source === 'search') {
        const q = src.query || '';
        return `Search results: "${q}"${src.folder_name ? ` in ${src.folder_name}` : ''}`;
    }
    if (src.source === 'messages') {
        return src.label || `${(src.message_ids || []).length} selected emails`;
    }
    return 'Selection';
}

// ---------------------------------------------------------------------------
// Destination picker view
// ---------------------------------------------------------------------------

async function _openPickerView() {
    // Save current form state before re-rendering the modal as the picker.
    // Otherwise coming back via "Back" or "Choose this folder" would
    // re-render the form from stale prefs.
    _captureFormState();
    _pickerSelectedDir = null;
    _pickerCwd = _currentDir;
    _renderPickerShell();
    await _loadPickerDir(_pickerCwd);
}

function _renderPickerShell() {
    _modalEl.innerHTML = `
        <div class="modal-content export-modal export-picker-modal">
            <div class="modal-header">
                <h2>Choose folder</h2>
                <button class="btn-icon" id="exportPickerCloseBtn" title="Close">
                    <i data-lucide="x"></i>
                </button>
            </div>

            <div class="export-picker-toolbar">
                <button class="btn btn-secondary btn-small" id="exportPickerUpBtn" title="Parent folder">
                    <i data-lucide="arrow-up"></i>
                </button>
                <div class="export-picker-path" id="exportPickerPath">\u2014</div>
            </div>

            <div class="export-picker-list" id="exportPickerList">
                <div class="export-picker-empty">Loading\u2026</div>
            </div>

            <div class="modal-actions">
                <button class="btn btn-secondary" id="exportPickerBackBtn">Back</button>
                <button class="btn btn-primary" id="exportPickerConfirmBtn">Choose this folder</button>
            </div>
        </div>
    `;

    _modalEl.querySelector('#exportPickerCloseBtn').addEventListener('click', _closeModal);
    _modalEl.querySelector('#exportPickerBackBtn').addEventListener('click', _renderFormView);
    _modalEl.querySelector('#exportPickerUpBtn').addEventListener('click', _pickerNavigateUp);
    _modalEl.querySelector('#exportPickerConfirmBtn').addEventListener('click', _pickerConfirm);

    if (typeof lucide !== 'undefined') lucide.createIcons();
}

async function _loadPickerDir(path) {
    const list = _modalEl.querySelector('#exportPickerList');
    const pathEl = _modalEl.querySelector('#exportPickerPath');
    if (!list || !pathEl) return;

    list.innerHTML = '<div class="export-picker-empty">Loading\u2026</div>';

    try {
        const response = await fetch('/api/filesystem/browse', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                path: path || '',
                show_hidden: false,
                filter: 'dirs_only',
            }),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({error: 'Could not load'}));
            list.innerHTML = `<div class="export-picker-empty">${escapeHtml(err.error || 'Could not load')}</div>`;
            return;
        }
        const data = await response.json();
        _pickerCwd = data.path;
        pathEl.textContent = data.path;
        pathEl.title = data.path;

        const dirs = (data.items || []).filter(i => i.type === 'dir');
        if (!dirs.length) {
            list.innerHTML = '<div class="export-picker-empty">No subfolders here. Use \u201CChoose this folder\u201D to save here.</div>';
            return;
        }
        list.innerHTML = dirs.map(d => `
            <div class="export-picker-item" data-path="${escapeHtml(d.path)}">
                <i data-lucide="folder"></i>
                <span>${escapeHtml(d.name)}</span>
            </div>
        `).join('');

        list.querySelectorAll('.export-picker-item').forEach(el => {
            el.addEventListener('click', () => {
                list.querySelectorAll('.export-picker-item').forEach(x => x.classList.remove('selected'));
                el.classList.add('selected');
                _pickerSelectedDir = el.dataset.path;
            });
            el.addEventListener('dblclick', () => {
                _pickerSelectedDir = null;
                _loadPickerDir(el.dataset.path);
            });
        });

        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch (e) {
        list.innerHTML = `<div class="export-picker-empty">Could not load: ${escapeHtml(e.message)}</div>`;
    }
}

async function _pickerNavigateUp() {
    if (!_pickerCwd || _pickerCwd === '/') return;
    const parts = _pickerCwd.split('/').filter(p => p);
    parts.pop();
    const parent = '/' + parts.join('/');
    _pickerSelectedDir = null;
    await _loadPickerDir(parent || '/');
}

function _pickerConfirm() {
    // Prefer an explicit selection, otherwise use the current dir we\'re showing.
    const chosen = _pickerSelectedDir || _pickerCwd;
    if (!chosen) return;
    _currentDir = chosen;
    _saveDir(chosen);
    _renderFormView();
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// ---------------------------------------------------------------------------
// Start export + progress
// ---------------------------------------------------------------------------

async function _startExport() {
    const fmt = _modalEl.querySelector('input[name="export-format"]:checked')?.value || 'pdf';
    const sort = _modalEl.querySelector('input[name="export-sort"]:checked')?.value || 'chronological';
    const cover = _modalEl.querySelector('#export-include-cover')?.checked ?? true;
    const subs = _modalEl.querySelector('#export-include-subfolders')?.checked ?? true;
    const loadRemote = _modalEl.querySelector('#export-load-remote')?.checked ?? false;
    const encrypt = _modalEl.querySelector('#export-encrypt')?.checked ?? false;
    const password = _modalEl.querySelector('#export-password')?.value || '';
    const passwordConfirm = _modalEl.querySelector('#export-password-confirm')?.value || '';

    // Validate encryption inputs in-place \u2014 surface errors above the
    // submit button instead of dropping the user into the progress view.
    if (encrypt) {
        const fb = _modalEl.querySelector('#export-password-feedback');
        if (!password) {
            if (fb) {
                fb.textContent = 'Enter a password.';
                fb.className = 'export-password-feedback export-password-feedback-warn';
            }
            return;
        }
        if (password.length < 8) {
            if (fb) {
                fb.textContent = 'Password must be at least 8 characters.';
                fb.className = 'export-password-feedback export-password-feedback-warn';
            }
            return;
        }
        if (password !== passwordConfirm) {
            if (fb) {
                fb.textContent = 'Passwords don\u2019t match.';
                fb.className = 'export-password-feedback export-password-feedback-warn';
            }
            return;
        }
    }

    // Persist non-secret prefs only. Never persist the password.
    _exportPrefs = {
        format: fmt,
        sort_order: sort,
        include_subfolders: subs,
        include_cover: cover,
        load_remote_content: loadRemote,
    };

    const selection = _buildSelectionPayload(_currentSource, subs);
    if (!selection) {
        _renderErrorView('Could not determine what to export.');
        return;
    }

    _renderProgressView('Starting export\u2026');

    try {
        const body = {
            selection,
            format: fmt,
            sort_order: sort,
            include_cover: cover,
            load_remote_content: loadRemote,
            output_dir: _currentDir,
        };
        if (encrypt && password) {
            body.encryption_password = password;
        }
        const response = await fetch('/api/export/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(body),
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({error: 'Failed to start export'}));
            _renderErrorView(err.error || 'Failed to start export');
            return;
        }
        const data = await response.json();
        _currentJobId = data.job_id;
        _subscribeToProgress(_currentJobId);
    } catch (e) {
        _renderErrorView(`Network error: ${e.message}`);
    }
}

function _buildSelectionPayload(src, includeSubfolders) {
    if (src.source === 'folder') {
        return {
            source: 'folder',
            folder_id: src.folder_id,
            include_subfolders: !!includeSubfolders,
        };
    }
    if (src.source === 'search') {
        return {
            source: 'search',
            query: src.query,
            folder_id: src.folder_id || null,
            include_subfolders: src.include_subfolders ?? true,
        };
    }
    if (src.source === 'messages') {
        return {
            source: 'messages',
            message_ids: src.message_ids || [],
        };
    }
    return null;
}

function _subscribeToProgress(jobId) {
    if (_eventSource) _eventSource.close();
    _eventSource = new EventSource(`/api/export/progress/${jobId}`);

    _eventSource.addEventListener('status', (e) => {
        try {
            const d = JSON.parse(e.data);
            _updateStatus(d.message || '', d.percent, d.indeterminate);
        } catch {}
    });

    _eventSource.addEventListener('progress', (e) => {
        try {
            const d = JSON.parse(e.data);
            _updateStatus(null, d.percent, d.indeterminate);
        } catch {}
    });

    _eventSource.addEventListener('complete', (e) => {
        try {
            const d = JSON.parse(e.data);
            _eventSource.close();
            _eventSource = null;
            _renderCompleteView(jobId, d);
        } catch {
            _renderErrorView('Export finished but the response was malformed.');
        }
    });

    _eventSource.addEventListener('error', (e) => {
        let msg = 'Export failed.';
        try {
            const d = JSON.parse(e.data);
            if (d.error) msg = d.error;
        } catch {
            if (_eventSource && _eventSource.readyState === EventSource.CLOSED) {
                msg = 'Connection to server was lost.';
            }
        }
        if (_eventSource) {
            _eventSource.close();
            _eventSource = null;
        }
        _renderErrorView(msg);
    });
}

function _renderProgressView(initialMessage) {
    _modalEl.innerHTML = `
        <div class="modal-content export-modal">
            <div class="modal-header">
                <h2>Exporting\u2026</h2>
            </div>
            <div class="export-progress">
                <div class="export-progress-message" id="exportStatusMessage">${escapeHtml(initialMessage || 'Working\u2026')}</div>
                <div class="export-progress-bar">
                    <div class="export-progress-fill" id="exportProgressFill" style="width: 5%"></div>
                </div>
                <div class="export-progress-percent" id="exportProgressPercent">5%</div>
            </div>
            <div class="modal-actions">
                <button class="btn btn-secondary" id="exportAbortBtn">Cancel</button>
            </div>
        </div>
    `;
    _modalEl.querySelector('#exportAbortBtn').addEventListener('click', _abortExport);
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function _updateStatus(message, percent, indeterminate) {
    if (message != null) {
        const el = _modalEl.querySelector('#exportStatusMessage');
        if (el) el.textContent = message;
    }
    const bar = _modalEl.querySelector('.export-progress-bar');
    if (indeterminate === true && bar) {
        // Switch to indeterminate pulse — the bar fills the full width and
        // pulses in opacity to signal that work is happening but progress
        // can\'t be measured (this is the WeasyPrint phase).
        bar.classList.add('indeterminate');
        const fill = _modalEl.querySelector('#exportProgressFill');
        const txt = _modalEl.querySelector('#exportProgressPercent');
        if (fill) fill.style.width = '100%';
        if (txt) txt.textContent = 'Working\u2026';
    } else if (indeterminate === false && bar) {
        bar.classList.remove('indeterminate');
    }
    if (percent != null && !(indeterminate === true)) {
        const fill = _modalEl.querySelector('#exportProgressFill');
        const txt = _modalEl.querySelector('#exportProgressPercent');
        const pct = Math.max(0, Math.min(100, Math.round(percent)));
        if (fill) fill.style.width = `${pct}%`;
        if (txt) txt.textContent = `${pct}%`;
    }
}

// ---------------------------------------------------------------------------
// Complete / error views
// ---------------------------------------------------------------------------

function _renderCompleteView(jobId, data) {
    const filename = data.filename || 'export';
    const sizeStr = _formatSize(data.size);
    const savedPath = data.saved_path || null;
    const platform = navigator.platform || '';
    const isMac = /Mac/i.test(platform);
    const revealLabel = isMac ? 'Reveal in Finder' : 'Open folder';

    _modalEl.innerHTML = `
        <div class="modal-content export-modal">
            <div class="modal-header">
                <h2>Export ready</h2>
            </div>
            <div class="export-complete">
                <div class="export-complete-icon"><i data-lucide="check-circle"></i></div>
                <div class="export-complete-filename">${escapeHtml(filename)}</div>
                ${sizeStr ? `<div class="export-complete-size">${sizeStr}</div>` : ''}
                ${savedPath ? `
                    <div class="export-complete-path" title="${escapeHtml(savedPath)}">
                        <i data-lucide="folder"></i>
                        <span>${escapeHtml(savedPath)}</span>
                    </div>
                ` : ''}
            </div>
            <div class="modal-actions">
                <button class="btn btn-secondary" id="exportDoneBtn">Close</button>
                ${savedPath ? `
                    <button class="btn btn-primary" id="exportRevealBtn">
                        <i data-lucide="folder-open"></i>
                        ${escapeHtml(revealLabel)}
                    </button>
                ` : ''}
            </div>
        </div>
    `;
    _modalEl.querySelector('#exportDoneBtn').addEventListener('click', _closeModal);
    const revealBtn = _modalEl.querySelector('#exportRevealBtn');
    if (revealBtn) {
        revealBtn.addEventListener('click', async () => {
            try {
                await fetch('/api/export/reveal', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({path: savedPath}),
                });
            } catch {}
            _closeModal();
        });
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function _renderErrorView(message) {
    _currentJobId = null;
    _modalEl.innerHTML = `
        <div class="modal-content export-modal">
            <div class="modal-header">
                <h2>Export failed</h2>
            </div>
            <div class="export-error">
                <div class="export-error-icon"><i data-lucide="alert-circle"></i></div>
                <div class="export-error-message">${escapeHtml(message)}</div>
            </div>
            <div class="modal-actions">
                <button class="btn btn-secondary" id="exportCloseBtn2">Close</button>
                <button class="btn btn-primary" id="exportRetryBtn">Try again</button>
            </div>
        </div>
    `;
    _modalEl.querySelector('#exportCloseBtn2').addEventListener('click', _closeModal);
    _modalEl.querySelector('#exportRetryBtn').addEventListener('click', _renderFormView);
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function _formatSize(bytes) {
    if (bytes == null) return null;
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function _abortExport() {
    if (_eventSource) {
        _eventSource.close();
        _eventSource = null;
    }
    if (_currentJobId) {
        try {
            await fetch(`/api/export/cancel/${_currentJobId}`, {method: 'POST'});
        } catch {}
        _currentJobId = null;
    }
    _closeModal();
}

function _closeModal() {
    if (_eventSource) {
        _eventSource.close();
        _eventSource = null;
    }
    _currentJobId = null;
    _currentSource = null;
    if (_modalEl) {
        _modalEl.classList.remove('active');
    }
}
