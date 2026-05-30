/**
 * MailRepo - Crypto migration UI (v1 -> v2).
 *
 * Driven entirely from the migration state returned by the backend:
 *   - "not_needed"           -> archive is already v2, hide everything
 *   - "fresh"                -> show banner + open modal that runs Phase 1
 *   - "phase_1_interrupted"  -> show banner + open modal that resumes Phase 1
 *   - "phase_2_pending"      -> show banner + open modal that runs Phase 2 only
 *
 * Phase 1 consumes /migration/api/phase-1-progress (SSE).
 * Phase 2 consumes /migration/api/phase-2-progress (SSE).
 *
 * Halts loud on errors. The 'corruption' error kind names the specific file.
 */

import { escapeHtml } from '../utils.js';

let _bannerInitialized = false;
let _currentState = null;
let _currentPreflight = null;
let _currentSSE = null;

// ============================================================
// PUBLIC: called from app.js on DOMContentLoaded
// ============================================================

export async function initMigrationBanner() {
    if (_bannerInitialized) return;
    _bannerInitialized = true;
    
    try {
        const r = await fetch('/migration/api/state');
        if (!r.ok) {
            // Unauthenticated / server issue — fail quiet (this is a passive check)
            return;
        }
        const data = await r.json();
        _currentState = data.state;
        _currentPreflight = data.preflight;
        
        if (data.state && data.state !== 'not_needed') {
            _renderBanner(data.state);
        }
    } catch (e) {
        console.warn('Migration state check failed:', e);
    }
}

// ============================================================
// BANNER
// ============================================================

function _renderBanner(state) {
    const banner = document.getElementById('migrationBanner');
    if (!banner) return;
    
    let title, subtitle, action;
    switch (state) {
        case 'fresh':
            title = 'Crypto upgrade available';
            subtitle = 'Upgrade your archive to AES-256-GCM + Argon2id. One-time, ~1-2 minutes.';
            action = 'Migrate';
            break;
        case 'phase_1_interrupted':
            title = 'Crypto migration interrupted';
            subtitle = 'A previous migration started but did not finish. Resume to complete.';
            action = 'Resume';
            break;
        case 'phase_2_pending':
            title = 'Crypto migration nearly complete';
            subtitle = 'File layer is migrated. Finalize the database layer to complete.';
            action = 'Finalize';
            break;
        default:
            return;
    }
    
    banner.querySelector('.migration-banner-title').textContent = title;
    banner.querySelector('.migration-banner-subtitle').textContent = subtitle;
    const actionBtn = banner.querySelector('.migration-banner-action');
    actionBtn.textContent = action;
    actionBtn.onclick = () => _openModal(state);
    
    banner.style.display = 'flex';
    
    // Re-render Lucide icons if available (banner uses one)
    if (window.lucide) window.lucide.createIcons();
}

function _hideBanner() {
    const banner = document.getElementById('migrationBanner');
    if (banner) banner.style.display = 'none';
}

// ============================================================
// MODAL — content depends on current state
// ============================================================

function _openModal(state) {
    const modal = document.getElementById('migrationModal');
    if (!modal) return;
    
    const body = document.getElementById('migrationModalBody');
    const actions = document.getElementById('migrationModalActions');
    
    if (state === 'fresh' || state === 'phase_1_interrupted') {
        _renderPhase1Intro(body, actions, state);
    } else if (state === 'phase_2_pending') {
        _renderPhase2Intro(body, actions);
    }
    
    modal.classList.add('active');
    if (window.lucide) window.lucide.createIcons();
}

export function closeMigrationModal() {
    const modal = document.getElementById('migrationModal');
    if (modal) modal.classList.remove('active');
    if (_currentSSE) {
        _currentSSE.close();
        _currentSSE = null;
    }
}

function _renderPhase1Intro(body, actions, state) {
    const pre = _currentPreflight || { checks: {} };
    const c = pre.checks || {};
    
    const items = [
        { ok: c.unlocked, label: 'Encryption unlocked' },
        { ok: c.v1_decrypt_sample, label: 'Current encryption verified' },
        { ok: c.argon2_works, label: 'New encryption (Argon2id) available' },
        { ok: c.disk_space_ok, label: 'Sufficient disk space' },
    ];
    
    const ageHrs = c.backup_age_hours;
    const backupLabel = ageHrs === null || ageHrs === undefined
        ? 'No backup found'
        : (ageHrs <= 24 ? `Recent backup (${ageHrs.toFixed(1)}h old)` : `Backup is ${ageHrs.toFixed(1)}h old`);
    items.push({ ok: ageHrs !== null && ageHrs !== undefined && ageHrs <= 24, label: backupLabel, warning: true });
    
    const intro = state === 'phase_1_interrupted'
        ? '<p>A previous migration was interrupted. Re-entering your password will resume the file walk from where it left off.</p>'
        : '<p>This will re-encrypt every email file in your archive with AES-256-GCM and derive your master keys via Argon2id. The file layer migration is interruption-safe — if anything happens partway, re-running the migration resumes cleanly.</p>';
    
    body.innerHTML = `
        ${intro}
        <h3 class="migration-section-title">Pre-flight checks</h3>
        <ul class="migration-checklist">
            ${items.map(i => `
                <li class="${i.ok ? 'ok' : 'fail'}">
                    <i data-lucide="${i.ok ? 'check-circle-2' : 'alert-triangle'}"></i>
                    <span>${escapeHtml(i.label)}</span>
                </li>
            `).join('')}
        </ul>
        <div class="form-group" style="margin-top: var(--space-lg);">
            <label for="migrationPassword">Enter your master password to confirm:</label>
            <input type="password" id="migrationPassword" class="form-input" autocomplete="current-password" placeholder="Master password">
        </div>
        <div id="migrationModalError" class="text-danger" style="display: none; margin-top: var(--space-sm);"></div>
        <div id="migrationModalProgress" style="display: none; margin-top: var(--space-md);">
            <div class="migration-stage" id="migrationStage">Preparing...</div>
            <div class="migration-progress-bar"><div class="migration-progress-fill" id="migrationProgressFill" style="width: 0%;"></div></div>
            <div class="migration-progress-detail" id="migrationProgressDetail"></div>
        </div>
    `;
    
    actions.innerHTML = `
        <button class="btn btn-secondary" onclick="window.__migrationCancel()">Cancel</button>
        <button class="btn btn-primary" id="migrationConfirmBtn" onclick="window.__migrationConfirmPhase1()">
            <i data-lucide="shield-check" class="icon-inline"></i>
            ${state === 'phase_1_interrupted' ? 'Resume migration' : 'Start migration'}
        </button>
    `;
    
    // Focus password input
    setTimeout(() => document.getElementById('migrationPassword')?.focus(), 50);
}

function _renderPhase2Intro(body, actions) {
    const pre = _currentPreflight || { checks: {} };
    const ageHrs = pre.checks?.backup_age_hours;
    const backupOk = ageHrs !== null && ageHrs !== undefined && ageHrs <= 24;
    
    body.innerHTML = `
        <p>Phase 1 is complete — every archive file has been re-encrypted with AES-256-GCM. The final step rekeys the encrypted database itself.</p>
        <p style="margin-top: var(--space-md);"><strong>Phase 2 is not resumable</strong>. If something fails partway through, the recovery path is restoring the database from backup. The backup check below must pass.</p>
        <div class="migration-backup-status ${backupOk ? 'ok' : 'fail'}" style="margin-top: var(--space-md);">
            <i data-lucide="${backupOk ? 'check-circle-2' : 'alert-triangle'}"></i>
            <span>
                ${backupOk
                    ? `Recent backup found (${ageHrs.toFixed(1)} hours old). Ready to proceed.`
                    : (ageHrs === null || ageHrs === undefined
                        ? 'No recent backup found. Take a fresh backup from Backup & Restore, then return here.'
                        : `Backup is ${ageHrs.toFixed(1)} hours old. The 24-hour limit is non-overridable. Take a fresh backup from Backup & Restore, then return here.`)}
            </span>
        </div>
        <div id="migrationModalError" class="text-danger" style="display: none; margin-top: var(--space-sm);"></div>
        <div id="migrationModalProgress" style="display: none; margin-top: var(--space-md);">
            <div class="migration-stage" id="migrationStage">Preparing...</div>
            <div class="migration-progress-bar"><div class="migration-progress-fill" id="migrationProgressFill" style="width: 0%;"></div></div>
            <div class="migration-progress-detail" id="migrationProgressDetail"></div>
        </div>
    `;
    
    actions.innerHTML = `
        <button class="btn btn-secondary" onclick="window.__migrationCancel()">Cancel</button>
        <button class="btn btn-primary" id="migrationConfirmBtn" onclick="window.__migrationConfirmPhase2()" ${backupOk ? '' : 'disabled'}>
            <i data-lucide="check" class="icon-inline"></i>
            Finalize migration
        </button>
    `;
}

// ============================================================
// PHASE 1 EXECUTION
// ============================================================

async function _confirmPhase1() {
    const pwInput = document.getElementById('migrationPassword');
    const password = pwInput?.value || '';
    const errEl = document.getElementById('migrationModalError');
    const confirmBtn = document.getElementById('migrationConfirmBtn');
    
    errEl.style.display = 'none';
    errEl.textContent = '';
    
    if (!password) {
        errEl.textContent = 'Password required.';
        errEl.style.display = 'block';
        return;
    }
    
    confirmBtn.disabled = true;
    
    try {
        const r = await fetch('/migration/api/start-phase-1', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password }),
        });
        const data = await r.json();
        if (!r.ok || data.error) {
            throw new Error(data.error || 'Failed to authorize Phase 1.');
        }
        
        // Clear the password from the DOM as soon as it's transmitted
        pwInput.value = '';
        
        _showProgressUI();
        _streamPhase1();
    } catch (e) {
        errEl.textContent = e.message;
        errEl.style.display = 'block';
        confirmBtn.disabled = false;
    }
}

function _streamPhase1() {
    if (_currentSSE) _currentSSE.close();
    const es = new EventSource('/migration/api/phase-1-progress');
    _currentSSE = es;
    
    es.onmessage = (event) => {
        let ev;
        try { ev = JSON.parse(event.data); } catch (e) { return; }
        
        if (ev.status === 'error') {
            es.close();
            _currentSSE = null;
            _showPhase1Error(ev);
            return;
        }
        if (ev.status === 'success') {
            es.close();
            _currentSSE = null;
            _onPhase1Complete(ev.result);
            return;
        }
        _updatePhase1Progress(ev);
    };
    
    es.onerror = () => {
        es.close();
        _currentSSE = null;
        const errEl = document.getElementById('migrationModalError');
        if (errEl) {
            errEl.textContent = 'Connection lost during migration. Check the server log; if Phase 1 had time to complete, re-opening this dialog will show the next step.';
            errEl.style.display = 'block';
        }
    };
}

function _updatePhase1Progress(ev) {
    const stageEl = document.getElementById('migrationStage');
    const fillEl = document.getElementById('migrationProgressFill');
    const detailEl = document.getElementById('migrationProgressDetail');
    if (!stageEl || !fillEl) return;
    
    let pct = 0;
    let stageText = ev.stage || '';
    let detailText = '';
    
    switch (ev.stage) {
        case 'cleanup':
            pct = 2;
            stageText = 'Cleaning up...';
            detailText = ev.stray_removed ? `Removed ${ev.stray_removed} stale temp file(s)` : '';
            break;
        case 'keys_derived':
            pct = 5;
            stageText = 'Deriving new encryption keys (Argon2id, ~1s)...';
            break;
        case 'walking':
            if (ev.files_total > 0) {
                pct = 5 + (ev.files_done / ev.files_total) * 75;
                stageText = 'Re-encrypting archive files...';
                detailText = `${ev.files_done} of ${ev.files_total} files`;
            }
            break;
        case 'credentials_done':
            pct = 82;
            stageText = 'Account credentials re-encrypted';
            detailText = `${ev.count} account(s)`;
            break;
        case 'verifying':
            pct = 85 + (ev.samples_done / ev.samples_total) * 10;
            stageText = 'Verifying...';
            detailText = `${ev.samples_done} of ${ev.samples_total} sample decrypts`;
            break;
        case 'complete':
            pct = 100;
            stageText = 'Phase 1 complete';
            break;
    }
    
    fillEl.style.width = pct + '%';
    stageEl.textContent = stageText;
    if (detailEl) detailEl.textContent = detailText;
}

function _showPhase1Error(ev) {
    const errEl = document.getElementById('migrationModalError');
    const stageEl = document.getElementById('migrationStage');
    const confirmBtn = document.getElementById('migrationConfirmBtn');
    
    if (stageEl) stageEl.textContent = 'Migration halted';
    
    if (errEl) {
        let html = '';
        if (ev.kind === 'corruption') {
            html = `<strong>Corruption detected:</strong> ${escapeHtml(ev.filepath || '')}<br><span style="font-size: 0.875rem;">${escapeHtml(ev.message || '')}</span><br><br>The migration halted on this file rather than silently skipping. Investigate the file or restore from backup.`;
        } else {
            html = escapeHtml(ev.message || 'Unknown error');
        }
        errEl.innerHTML = html;
        errEl.style.display = 'block';
    }
    if (confirmBtn) confirmBtn.disabled = false;
}

async function _onPhase1Complete(result) {
    const stageEl = document.getElementById('migrationStage');
    const fillEl = document.getElementById('migrationProgressFill');
    if (stageEl) stageEl.textContent = `Phase 1 complete — ${result?.files || 0} files migrated`;
    if (fillEl) fillEl.style.width = '100%';
    
    // Re-check state from server (marker is now present, backup age is recomputed)
    try {
        const r = await fetch('/migration/api/state');
        if (r.ok) {
            const data = await r.json();
            _currentState = data.state;
            _currentPreflight = data.preflight;
        }
    } catch (e) {}
    
    // Swap the modal body to the Phase 2 intro
    const body = document.getElementById('migrationModalBody');
    const actions = document.getElementById('migrationModalActions');
    _renderPhase2Intro(body, actions);
    if (window.lucide) window.lucide.createIcons();
    
    // Update banner state too
    _renderBanner('phase_2_pending');
}

// ============================================================
// PHASE 2 EXECUTION
// ============================================================

async function _confirmPhase2() {
    const errEl = document.getElementById('migrationModalError');
    const confirmBtn = document.getElementById('migrationConfirmBtn');
    
    errEl.style.display = 'none';
    errEl.textContent = '';
    confirmBtn.disabled = true;
    
    try {
        const r = await fetch('/migration/api/start-phase-2', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        const data = await r.json();
        if (!r.ok || data.error) {
            throw new Error(data.error || 'Failed to authorize Phase 2.');
        }
        
        _showProgressUI();
        _streamPhase2();
    } catch (e) {
        errEl.textContent = e.message;
        errEl.style.display = 'block';
        confirmBtn.disabled = false;
    }
}

function _streamPhase2() {
    if (_currentSSE) _currentSSE.close();
    const es = new EventSource('/migration/api/phase-2-progress');
    _currentSSE = es;
    
    es.onmessage = (event) => {
        let ev;
        try { ev = JSON.parse(event.data); } catch (e) { return; }
        
        if (ev.status === 'error') {
            es.close();
            _currentSSE = null;
            _showPhase2Error(ev);
            return;
        }
        if (ev.status === 'success') {
            es.close();
            _currentSSE = null;
            _onPhase2Complete(ev.result);
            return;
        }
        _updatePhase2Progress(ev);
    };
    
    es.onerror = () => {
        es.close();
        _currentSSE = null;
        const errEl = document.getElementById('migrationModalError');
        if (errEl) {
            errEl.textContent = 'Connection lost during Phase 2. Check the server log carefully — Phase 2 is not resumable. If the rekey was interrupted, restore the database from your most recent backup.';
            errEl.style.display = 'block';
        }
    };
}

function _updatePhase2Progress(ev) {
    const stageEl = document.getElementById('migrationStage');
    const fillEl = document.getElementById('migrationProgressFill');
    if (!stageEl || !fillEl) return;
    
    const stages = {
        backup_check: { pct: 10, label: 'Backup verified' },
        acquiring: { pct: 20, label: 'Acquiring exclusive database access...' },
        wal_checkpoint: { pct: 35, label: 'Flushing pending writes (WAL checkpoint)...' },
        rekey: { pct: 60, label: 'Rekeying database (PRAGMA rekey)...' },
        salt_file: { pct: 85, label: 'Writing new salt file...' },
        swap_keys: { pct: 95, label: 'Swapping to new keys in memory...' },
        complete: { pct: 100, label: 'Phase 2 complete' },
    };
    
    const s = stages[ev.stage];
    if (s) {
        fillEl.style.width = s.pct + '%';
        stageEl.textContent = s.label;
    }
}

function _showPhase2Error(ev) {
    const errEl = document.getElementById('migrationModalError');
    const stageEl = document.getElementById('migrationStage');
    const confirmBtn = document.getElementById('migrationConfirmBtn');
    
    if (stageEl) stageEl.textContent = 'Phase 2 halted';
    if (errEl) {
        errEl.innerHTML = `<strong>Phase 2 error:</strong> ${escapeHtml(ev.message || 'Unknown')}<br><br>Phase 2 is not resumable. If the rekey was interrupted, restore the database from your most recent backup.`;
        errEl.style.display = 'block';
    }
    if (confirmBtn) confirmBtn.disabled = false;
}

function _onPhase2Complete(result) {
    const stageEl = document.getElementById('migrationStage');
    const fillEl = document.getElementById('migrationProgressFill');
    if (fillEl) fillEl.style.width = '100%';
    if (stageEl) stageEl.textContent = 'Migration complete';
    
    const body = document.getElementById('migrationModalBody');
    const actions = document.getElementById('migrationModalActions');
    
    body.innerHTML = `
        <div style="text-align: center; padding: var(--space-lg) 0;">
            <i data-lucide="shield-check" style="width: 64px; height: 64px; color: var(--color-success, #2ecc71);"></i>
            <h3 style="margin: var(--space-md) 0 var(--space-sm);">Migration complete</h3>
            <p>Your archive is now on AES-256-GCM + Argon2id (crypto version ${escapeHtml(String(result?.crypto_version || 2))}).</p>
            <p style="margin-top: var(--space-sm); color: var(--color-text-muted);">Log out and back in to start using the new crypto.</p>
        </div>
    `;
    actions.innerHTML = `
        <button class="btn btn-primary" onclick="window.location.href = '/auth/logout'">Log out</button>
    `;
    if (window.lucide) window.lucide.createIcons();
    
    _hideBanner();
}

// ============================================================
// HELPERS
// ============================================================

function _showProgressUI() {
    const progEl = document.getElementById('migrationModalProgress');
    if (progEl) progEl.style.display = 'block';
}

// Wire global callbacks for inline onclick handlers in dynamically-rendered HTML
window.__migrationCancel = () => closeMigrationModal();
window.__migrationConfirmPhase1 = () => _confirmPhase1();
window.__migrationConfirmPhase2 = () => _confirmPhase2();
