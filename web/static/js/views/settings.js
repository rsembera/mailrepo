/**
 * Settings View
 * 
 * Renders settings as a view within the main app layout,
 * following the same pattern as folder-mgmt.js and trash.js.
 */

import { initCustomSelects, CustomSelect } from '../components/custom-select.js';
import { escapeHtml } from '../utils.js';
import { state } from '../state.js';
import { bindActions } from '../delegate.js';
import { closeModal, registerModalCloseHandler } from '../modals.js';

let contextTitle = null;
let contextMeta = null;
let emailList = null;

// Guard to prevent saving settings during initialization
let settingsLoaded = false;

/**
 * Initialize the settings view.
 */
export function initSettingsView(config) {
    contextTitle = config.contextTitle;
    contextMeta = config.contextMeta;
    emailList = config.emailList;
    // Register the addAccountModal cleanup so closing it (from anywhere --
    // inline onclick in template, internal call, etc.) resets the form
    // state. Previously this was done by shadowing window.closeModal with
    // a settings-specific version, which broke if any other module
    // assigned window.closeModal later.
    registerModalCloseHandler('addAccountModal', resetAccountModal);
}

/**
 * Show the settings view in the main content area.
 */
export function showSettingsView() {
    state.activeScreen = 'settings';
    // Reset guard flag
    settingsLoaded = false;
    
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    const subfoldersBar = document.getElementById('subfoldersBar');
    
    // Hide sidebar, toolbar, and subfolders bar (settings uses full width)
    if (sidebar) sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    if (headerActions) headerActions.innerHTML = '';
    if (subfoldersBar) subfoldersBar.style.display = 'none';
    
    if (contextTitle) contextTitle.textContent = 'Settings';
    if (contextMeta) contextMeta.textContent = '';
    
    renderSettingsView();
}

/**
 * Render the settings view content.
 */
function renderSettingsView() {
    const html = `
        <div class="settings-view settings-view-root">
            <!-- Appearance Section -->
            <section class="settings-section-inline">
                <div class="settings-section-header-inline" data-section="appearance">
                    <i data-lucide="chevron-right" class="section-chevron"></i>
                    <i data-lucide="palette" class="section-icon"></i>
                    <div class="section-text">
                        <h3>Appearance</h3>
                        <p>Theme and display</p>
                    </div>
                </div>
                <div class="settings-section-body" id="appearanceBody" style="display: none;">
                    ${renderAppearanceSection()}
                </div>
            </section>
            
            <!-- Email Accounts Section -->
            <section class="settings-section-inline">
                <div class="settings-section-header-inline" data-section="accounts">
                    <i data-lucide="chevron-right" class="section-chevron"></i>
                    <i data-lucide="mail" class="section-icon"></i>
                    <div class="section-text">
                        <h3>Email Accounts</h3>
                        <p>Connected email accounts</p>
                    </div>
                </div>
                <div class="settings-section-body" id="accountsBody" style="display: none;">
                    ${renderAccountsSection()}
                </div>
            </section>
            
            <!-- Security Section -->
            <section class="settings-section-inline">
                <div class="settings-section-header-inline" data-section="security">
                    <i data-lucide="chevron-right" class="section-chevron"></i>
                    <i data-lucide="shield" class="section-icon"></i>
                    <div class="section-text">
                        <h3>Security</h3>
                        <p>Session, password, and recovery key</p>
                    </div>
                </div>
                <div class="settings-section-body" id="securityBody" style="display: none;">
                    ${renderSecuritySection()}
                </div>
            </section>
            
            <!-- Trash Section -->
            <section class="settings-section-inline">
                <div class="settings-section-header-inline" data-section="trash">
                    <i data-lucide="chevron-right" class="section-chevron"></i>
                    <i data-lucide="trash-2" class="section-icon"></i>
                    <div class="section-text">
                        <h3>Trash</h3>
                        <p>Auto-delete trashed items</p>
                    </div>
                </div>
                <div class="settings-section-body" id="trashBody" style="display: none;">
                    ${renderTrashSection()}
                </div>
            </section>
            
            <!-- Danger Zone Section -->
            <section class="settings-section-inline danger-zone">
                <div class="settings-section-header-inline" data-section="dangerzone">
                    <i data-lucide="chevron-right" class="section-chevron"></i>
                    <i data-lucide="alert-triangle" class="section-icon"></i>
                    <div class="section-text">
                        <h3>Danger Zone</h3>
                        <p>Irreversible actions — proceed with caution</p>
                    </div>
                </div>
                <div class="settings-section-body" id="dangerzoneBody" style="display: none;">
                    ${renderDangerZoneSection()}
                </div>
            </section>
            
            <!-- About Link -->
            <div class="settings-about-link">
                <a href="javascript:void(0);" data-action="showAbout">About MailRepo</a>
            </div>
        </div>
    `;
    
    emailList.innerHTML = html;
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    initSettingsSectionToggles();
    initCustomSelects();
    initAppearanceHandlers();
    initSecurityHandlers();
    initTrashHandlers();
    initThreadStagingHandlers();
    loadCurrentSettings();

    // Bind delegated handlers on the settings-specific root, NOT on the
    // shared emailList container. Listener dies with the view when another
    // view's render replaces emailList. See delegate.js docs.
    const root = emailList.querySelector('.settings-view-root');
    if (root) {
        bindActions(root, {
            showAbout: () => showAboutModal(),
            openAddAccount: () => openAddAccountModal(),
            showAppPasswordInfo: () => showAppPasswordInfo(),
            showResetDatabase: () => showResetDatabaseModal(),
            editAccount: (el) => editAccount(
                Number(el.dataset.accountId),
                el.dataset.accountName,
                el.dataset.accountEmail,
            ),
            testAccount: (el) => testAccount(Number(el.dataset.accountId)),
            deleteAccount: (el) => deleteAccount(Number(el.dataset.accountId)),
        });
    }
}

/**
 * Render appearance section content.
 */
function renderAppearanceSection() {
    return `
        <div class="appearance-group">
            <label class="appearance-label">Theme</label>
            <div class="theme-grid" id="themeGrid">
                <button class="theme-option" data-theme="pine" title="Pine">
                    <span class="theme-swatch" style="background: #1F8F74;"></span>
                    <span class="theme-name">Pine</span>
                </button>
                <button class="theme-option" data-theme="graphite" title="Graphite">
                    <span class="theme-swatch" style="background: #475569;"></span>
                    <span class="theme-name">Graphite</span>
                </button>
                <button class="theme-option" data-theme="atlantic" title="Atlantic">
                    <span class="theme-swatch" style="background: #3B6EA5;"></span>
                    <span class="theme-name">Atlantic</span>
                </button>
                <button class="theme-option" data-theme="ember" title="Ember">
                    <span class="theme-swatch" style="background: #A65568;"></span>
                    <span class="theme-name">Ember</span>
                </button>
                <button class="theme-option" data-theme="obsidian" title="Obsidian">
                    <span class="theme-swatch" style="background: #1e1e2e; border: 2px solid #45475a;"></span>
                    <span class="theme-name">Obsidian</span>
                </button>
            </div>
        </div>
        
        <div class="appearance-group">
            <label class="appearance-label">Font</label>
            <div class="font-controls">
                <div class="font-select-grid" id="fontGrid">
                    <button class="font-option" data-font="lexend" style="font-family: 'Lexend', sans-serif;">
                        <span class="font-preview">Aa</span>
                        <span class="font-name">Lexend</span>
                    </button>
                    <button class="font-option" data-font="libre-baskerville" style="font-family: 'Libre Baskerville', serif;">
                        <span class="font-preview">Aa</span>
                        <span class="font-name">Libre Baskerville</span>
                    </button>
                    <button class="font-option" data-font="source-sans" style="font-family: 'Source Sans 3', sans-serif;">
                        <span class="font-preview">Aa</span>
                        <span class="font-name">Source Sans</span>
                    </button>
                </div>
                <div class="font-size-controls">
                    <span class="size-label">Size</span>
                    <div class="size-toggle" id="sizeToggle">
                        <button class="size-btn" data-size="s">S</button>
                        <button class="size-btn" data-size="m">M</button>
                        <button class="size-btn" data-size="l">L</button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

/**
 * Render accounts section content.
 */
function renderAccountsSection() {
    // We'll fetch accounts dynamically
    return `
        <div class="accounts-list" id="accountsList">
            <div class="loading-indicator">Loading accounts...</div>
        </div>
        
        <div style="margin-top: var(--space-lg);">
            <button class="btn btn-primary" id="addAccountBtn" data-action="openAddAccount">
                <i data-lucide="plus"></i>
                Add Email Account
            </button>
        </div>
        
        <div class="helper-box">
            <strong>Note:</strong> For Gmail, iCloud, and other providers with 2FA, 
            you'll need to use an <strong>app-specific password</strong> instead of your regular password.
            <a href="javascript:void(0);" data-action="showAppPasswordInfo">What's this?</a>
        </div>

        <hr class="settings-divider">

        <div class="form-group">
            <label class="setting-label">Maximum thread size when staging</label>
            <div class="custom-select" id="threadMaxMessagesSelect" data-name="threadMaxMessages" data-value="500">
                <div class="custom-select-option" data-value="100">100 messages</div>
                <div class="custom-select-option" data-value="250">250 messages</div>
                <div class="custom-select-option" data-value="500">500 messages (default)</div>
                <div class="custom-select-option" data-value="1000">1,000 messages</div>
                <div class="custom-select-option" data-value="2000">2,000 messages</div>
            </div>
            <p class="setting-hint">Limits how many messages "Stage thread" will gather from a conversation. Most threads are well under 500.</p>
        </div>
    `;
}

/**
 * Render security section content.
 */
function renderSecuritySection() {
    return `
        <div class="form-group">
            <label class="setting-label">Auto-Logout After Inactivity</label>
            <div class="custom-select" id="sessionTimeoutSelect" data-name="sessionTimeout" data-value="30">
                <div class="custom-select-option" data-value="15">15 minutes</div>
                <div class="custom-select-option" data-value="30">30 minutes (default)</div>
                <div class="custom-select-option" data-value="60">1 hour</div>
                <div class="custom-select-option" data-value="120">2 hours</div>
                <div class="custom-select-option" data-value="0">Never (not recommended)</div>
            </div>
            <p class="setting-hint">Use a shorter timeout on shared or public machines.</p>
        </div>
        
        <hr class="settings-divider">
        
        <div class="form-group">
            <label>Password</label>
            <button class="btn btn-primary" id="changePasswordBtn">
                <i data-lucide="key"></i>
                Change Password
            </button>
        </div>
        
        <div id="changePasswordForm" class="password-change-form">
            <div class="form-group">
                <label for="currentPassword">Current Password</label>
                <div class="password-input-wrapper">
                    <input type="password" id="currentPassword" class="form-input" autocomplete="current-password">
                    <button type="button" class="password-toggle" data-target="currentPassword" title="Show password">
                        <i data-lucide="eye"></i>
                    </button>
                </div>
            </div>
            <div class="form-group">
                <label for="newPassword">New Password</label>
                <div class="password-input-wrapper">
                    <input type="password" id="newPassword" class="form-input" autocomplete="new-password">
                    <button type="button" class="password-toggle" data-target="newPassword" title="Show password">
                        <i data-lucide="eye"></i>
                    </button>
                </div>
                <small class="setting-hint">Minimum 12 characters</small>
            </div>
            <div class="form-group">
                <label for="confirmPassword">Confirm New Password</label>
                <div class="password-input-wrapper">
                    <input type="password" id="confirmPassword" class="form-input" autocomplete="new-password">
                    <button type="button" class="password-toggle" data-target="confirmPassword" title="Show password">
                        <i data-lucide="eye"></i>
                    </button>
                </div>
            </div>
            <div id="passwordChangeProgress" class="password-progress">
                <div class="progress-bar-container">
                    <div id="passwordProgressBar" class="progress-bar-fill"></div>
                </div>
                <p id="passwordProgressMessage" class="setting-hint"></p>
            </div>
            <div id="passwordChangeError" class="password-error"></div>
            <div class="password-actions">
                <button class="btn btn-primary" id="confirmChangePasswordBtn">Change Password</button>
                <button class="btn btn-secondary" id="cancelChangePasswordBtn">Cancel</button>
            </div>
        </div>

        <hr class="settings-divider">

        <div class="form-group" id="recoveryKeySection">
            <label>Recovery Key</label>
            <p class="setting-hint" id="recoveryKeyStatus" style="margin-bottom: var(--space-md);">
                Checking...
            </p>
            <button class="btn btn-secondary" id="checkRecoveryKeyBtn" hidden>
                <i data-lucide="shield-check"></i>
                Check Recovery Key
            </button>
            <button class="btn btn-secondary" id="rotateRecoveryKeyBtn" hidden>
                <i data-lucide="rotate-ccw"></i>
                Generate New Recovery Key
            </button>
            <a class="btn btn-primary" href="/auth/upgrade" id="upgradeRecoveryKeyBtn" hidden>
                <i data-lucide="shield-plus"></i>
                Add a Recovery Key
            </a>
            <a class="btn btn-secondary" href="/auth/rotate-master-key" id="rotateMasterKeyBtn" hidden>
                <i data-lucide="key-round"></i>
                Rotate Master Key
            </a>
            <p class="setting-hint" id="rotateMasterKeyHint" hidden style="margin-top: var(--space-sm);">
                If your password has been compromised and you believe others may have access to your
                backups, you should also rotate the master key. This re-encrypts your whole archive and
                may take several minutes or longer depending on its size.
            </p>
        </div>

        <div id="checkRecoveryKeyForm" class="password-change-form">
            <p class="setting-hint">
                Checks whether your saved key opens this archive. Nothing is changed.
            </p>
            <div class="form-group">
                <label for="checkKeyValue">Recovery Key</label>
                <input type="text" id="checkKeyValue" class="form-input recovery-key-input"
                       placeholder="XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX"
                       autocomplete="off" spellcheck="false">
            </div>
            <div id="checkRecoveryKeyResult" class="password-error"></div>
            <div class="password-actions">
                <button class="btn btn-primary" id="confirmCheckRecoveryKeyBtn">Check Key</button>
                <button class="btn btn-secondary" id="cancelCheckRecoveryKeyBtn">Done</button>
            </div>
        </div>

        <div id="rotateRecoveryKeyForm" class="password-change-form">
            <p class="setting-hint">
                This revokes your current key immediately. The old key stops working.
            </p>
            <div class="form-group">
                <label for="rotateKeyPassword">Current Password</label>
                <div class="password-input-wrapper">
                    <input type="password" id="rotateKeyPassword" class="form-input" autocomplete="current-password">
                    <button type="button" class="password-toggle" data-target="rotateKeyPassword" title="Show password">
                        <i data-lucide="eye"></i>
                    </button>
                </div>
            </div>
            <div id="rotateRecoveryKeyError" class="password-error"></div>
            <div class="password-actions">
                <button class="btn btn-primary" id="confirmRotateRecoveryKeyBtn">Generate New Key</button>
                <button class="btn btn-secondary" id="cancelRotateRecoveryKeyBtn">Cancel</button>
            </div>
        </div>

        <div id="newRecoveryKeyDisplay" class="password-change-form">
            <p class="setting-hint">
                <strong>Save this now</strong> — it's shown once and not stored.
                Your old key no longer works.
            </p>
            <div class="recovery-key-display">
                <code id="newRecoveryKeyValue"></code>
            </div>
            <div class="password-actions">
                <button class="btn btn-secondary" id="copyNewRecoveryKeyBtn">Copy</button>
                <button class="btn btn-primary" id="doneNewRecoveryKeyBtn">I've saved it</button>
            </div>
        </div>
    `;
}

/**
 * Recovery key: status, rotation, and the one-time display of a new key.
 *
 * Rotation is deliberately gated on the current password rather than just
 * an unlocked session — a recovery key is a durable second credential and
 * minting one should require the same proof as changing the password.
 */
function initRecoveryKeyHandlers() {
    const statusEl = document.getElementById('recoveryKeyStatus');
    const rotateBtn = document.getElementById('rotateRecoveryKeyBtn');
    const upgradeBtn = document.getElementById('upgradeRecoveryKeyBtn');
    const rotateForm = document.getElementById('rotateRecoveryKeyForm');
    const confirmBtn = document.getElementById('confirmRotateRecoveryKeyBtn');
    const cancelBtn = document.getElementById('cancelRotateRecoveryKeyBtn');
    const errorEl = document.getElementById('rotateRecoveryKeyError');
    const displayEl = document.getElementById('newRecoveryKeyDisplay');
    const valueEl = document.getElementById('newRecoveryKeyValue');
    const copyBtn = document.getElementById('copyNewRecoveryKeyBtn');
    const doneBtn = document.getElementById('doneNewRecoveryKeyBtn');
    const passwordEl = document.getElementById('rotateKeyPassword');
    const checkBtn = document.getElementById('checkRecoveryKeyBtn');
    const checkForm = document.getElementById('checkRecoveryKeyForm');
    const checkInput = document.getElementById('checkKeyValue');
    const checkResultEl = document.getElementById('checkRecoveryKeyResult');
    const confirmCheckBtn = document.getElementById('confirmCheckRecoveryKeyBtn');
    const cancelCheckBtn = document.getElementById('cancelCheckRecoveryKeyBtn');

    if (!statusEl) return;

    fetch('/auth/api/recovery-key-status')
        .then((r) => r.json())
        .then((data) => {
            if (data.has_recovery_key) {
                statusEl.textContent =
                    'This archive has a recovery key. You can check it or generate a new one below.';
                if (rotateBtn) rotateBtn.hidden = false;
                if (checkBtn) checkBtn.hidden = false;
                const rmk = document.getElementById('rotateMasterKeyBtn');
                const rmkHint = document.getElementById('rotateMasterKeyHint');
                if (rmk) rmk.hidden = false;
                if (rmkHint) rmkHint.hidden = false;
            } else {
                statusEl.textContent =
                    'No recovery key. Without one, a forgotten password locks the archive permanently.';
                if (upgradeBtn) upgradeBtn.hidden = false;
            }
        })
        .catch(() => {
            statusEl.textContent = 'Could not check recovery key status.';
        });

    if (rotateBtn && rotateForm) {
        rotateBtn.addEventListener('click', () => {
            rotateBtn.hidden = true;
            rotateForm.style.display = 'block';
            if (passwordEl) passwordEl.focus();
        });
    }

    if (checkBtn && checkForm) {
        checkBtn.addEventListener('click', () => {
            checkBtn.hidden = true;
            checkForm.style.display = 'block';
            if (checkResultEl) checkResultEl.style.display = 'none';
            if (checkInput) {
                checkInput.value = '';
                checkInput.focus();
            }
        });
    }

    if (cancelCheckBtn && checkForm) {
        cancelCheckBtn.addEventListener('click', () => {
            checkForm.style.display = 'none';
            if (checkBtn) checkBtn.hidden = false;
            // Don't leave the key sitting in the field for the next
            // person to walk past the screen.
            if (checkInput) checkInput.value = '';
            if (checkResultEl) checkResultEl.style.display = 'none';
        });
    }

    if (confirmCheckBtn) {
        confirmCheckBtn.addEventListener('click', async () => {
            const key = checkInput ? checkInput.value : '';
            if (!key.trim()) {
                checkResultEl.textContent = 'Enter the recovery key to check.';
                checkResultEl.className = 'password-error';
                checkResultEl.style.display = 'block';
                return;
            }

            confirmCheckBtn.disabled = true;
            try {
                const response = await fetch('/auth/api/verify-recovery-key', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ recovery_key: key }),
                });
                const data = await response.json();

                if (data.verified) {
                    checkResultEl.textContent = 'This key is valid.';
                    checkResultEl.className = 'password-success';
                } else {
                    checkResultEl.textContent =
                        data.error || 'That key does not open this archive.';
                    checkResultEl.className = 'password-error';
                }
                checkResultEl.style.display = 'block';
            } catch (err) {
                checkResultEl.textContent = 'Could not check the key: ' + err.message;
                checkResultEl.className = 'password-error';
                checkResultEl.style.display = 'block';
            } finally {
                confirmCheckBtn.disabled = false;
            }
        });
    }

    if (cancelBtn && rotateForm) {
        cancelBtn.addEventListener('click', () => {
            rotateForm.style.display = 'none';
            if (rotateBtn) rotateBtn.hidden = false;
            if (passwordEl) passwordEl.value = '';
            if (errorEl) errorEl.style.display = 'none';
        });
    }

    if (confirmBtn) {
        confirmBtn.addEventListener('click', async () => {
            const password = passwordEl ? passwordEl.value : '';
            if (!password) {
                errorEl.textContent = 'Enter your current password.';
                errorEl.style.display = 'block';
                return;
            }

            confirmBtn.disabled = true;
            errorEl.style.display = 'none';

            try {
                const response = await fetch('/auth/api/rotate-recovery-key', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password }),
                });
                const data = await response.json();
                if (!response.ok || data.error) {
                    throw new Error(data.error || 'Could not rotate the recovery key.');
                }

                if (passwordEl) passwordEl.value = '';
                rotateForm.style.display = 'none';
                valueEl.textContent = data.recovery_key;
                displayEl.style.display = 'block';
            } catch (err) {
                errorEl.textContent = err.message;
                errorEl.style.display = 'block';
            } finally {
                confirmBtn.disabled = false;
            }
        });
    }

    if (copyBtn) {
        copyBtn.addEventListener('click', () => {
            const key = valueEl.textContent.trim();
            if (navigator.clipboard && window.isSecureContext) {
                navigator.clipboard.writeText(key).then(() => {
                    copyBtn.textContent = 'Copied';
                    setTimeout(() => { copyBtn.textContent = 'Copy'; }, 2000);
                });
            }
        });
    }

    if (doneBtn) {
        doneBtn.addEventListener('click', () => {
            // Clear the key from the DOM once acknowledged. It is already
            // unrecoverable from the server; leaving it rendered just keeps
            // it on screen for whoever walks past next.
            valueEl.textContent = '';
            displayEl.style.display = 'none';
            if (rotateBtn) rotateBtn.hidden = false;
        });
    }
}

/**
 * Initialize security section handlers.
 */
function initSecurityHandlers() {
    const changeBtn = document.getElementById('changePasswordBtn');
    const form = document.getElementById('changePasswordForm');
    const confirmBtn = document.getElementById('confirmChangePasswordBtn');
    const cancelBtn = document.getElementById('cancelChangePasswordBtn');
    const sessionTimeoutSelect = document.getElementById('sessionTimeoutSelect');
    
    // Session timeout handler (custom select)
    if (sessionTimeoutSelect) {
        sessionTimeoutSelect.addEventListener('change', async (e) => {
            if (!settingsLoaded) return; // Skip during initialization
            const value = e.detail.value;
            try {
                const response = await fetch('/api/settings/session-timeout', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ value })
                });
                if (!response.ok) {
                    console.error('Failed to save session timeout setting');
                }
            } catch (err) {
                console.error('Error saving session timeout:', err);
            }
        });
    }
    
    if (changeBtn && form) {
        changeBtn.addEventListener('click', () => {
            changeBtn.style.display = 'none';
            form.style.display = 'block';
            document.getElementById('currentPassword').focus();
        });
    }

    initRecoveryKeyHandlers();
    
    if (cancelBtn && form) {
        cancelBtn.addEventListener('click', () => {
            form.style.display = 'none';
            changeBtn.style.display = 'inline-flex';
            // Clear form and reset toggles
            document.getElementById('currentPassword').value = '';
            document.getElementById('newPassword').value = '';
            document.getElementById('confirmPassword').value = '';
            document.getElementById('passwordChangeError').style.display = 'none';
            document.getElementById('passwordChangeProgress').style.display = 'none';
            // Reset all password fields to hidden
            document.querySelectorAll('.password-toggle').forEach(btn => {
                const input = document.getElementById(btn.dataset.target);
                if (input) input.type = 'password';
            });
        });
    }
    
    if (confirmBtn) {
        confirmBtn.addEventListener('click', handleChangePassword);
    }
    
    // Password visibility toggles
    document.querySelectorAll('.password-toggle').forEach(btn => {
        btn.addEventListener('click', () => {
            const input = document.getElementById(btn.dataset.target);
            if (input) {
                const isPassword = input.type === 'password';
                input.type = isPassword ? 'text' : 'password';
                // Update icon
                const icon = btn.querySelector('i, svg');
                if (icon) {
                    icon.setAttribute('data-lucide', isPassword ? 'eye-off' : 'eye');
                    if (typeof lucide !== 'undefined') lucide.createIcons();
                }
            }
        });
    });
}

/**
 * Handle the password change process.
 */
async function handleChangePassword() {
    const currentPassword = document.getElementById('currentPassword').value;
    const newPassword = document.getElementById('newPassword').value;
    const confirmPassword = document.getElementById('confirmPassword').value;
    const errorEl = document.getElementById('passwordChangeError');
    const progressEl = document.getElementById('passwordChangeProgress');
    const progressBar = document.getElementById('passwordProgressBar');
    const progressMsg = document.getElementById('passwordProgressMessage');
    const confirmBtn = document.getElementById('confirmChangePasswordBtn');
    const cancelBtn = document.getElementById('cancelChangePasswordBtn');
    
    // Validate
    errorEl.style.display = 'none';
    
    if (!currentPassword) {
        errorEl.textContent = 'Please enter your current password.';
        errorEl.style.display = 'block';
        return;
    }
    
    if (newPassword.length < 8) {
        errorEl.textContent = 'New password must be at least 8 characters.';
        errorEl.style.display = 'block';
        return;
    }
    
    if (newPassword !== confirmPassword) {
        errorEl.textContent = 'New passwords do not match.';
        errorEl.style.display = 'block';
        return;
    }
    
    // Disable buttons
    confirmBtn.disabled = true;
    cancelBtn.disabled = true;
    
    try {
        // Start password change on server
        const response = await fetch('/auth/api/change-password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
        });
        
        const data = await response.json();
        if (!response.ok || data.error) {
            throw new Error(data.error || 'Failed to start password change');
        }
        
        // Show progress
        progressEl.style.display = 'block';
        progressBar.style.width = '0%';
        progressMsg.textContent = 'Starting...';
        
        // Connect to SSE for progress. The job id keeps the passwords
        // server-side; they are never stored in the session cookie.
        const eventSource = new EventSource(`/auth/api/change-password-progress/${data.job_id}`);
        
        eventSource.onmessage = (event) => {
            const progress = JSON.parse(event.data);
            
            if (progress.status === 'error') {
                eventSource.close();
                errorEl.textContent = progress.message;
                errorEl.style.display = 'block';
                progressEl.style.display = 'none';
                confirmBtn.disabled = false;
                cancelBtn.disabled = false;
                return;
            }
            
            progressMsg.textContent = progress.message || '';
            
            // Update progress bar based on status
            switch (progress.status) {
                case 'counting':
                    progressBar.style.width = '5%';
                    break;
                case 'counted':
                    progressBar.style.width = '10%';
                    break;
                case 'encrypting':
                    if (progress.total > 0) {
                        const pct = 10 + (progress.current / progress.total) * 70;
                        progressBar.style.width = pct + '%';
                    }
                    break;
                case 'credentials':
                    progressBar.style.width = '85%';
                    break;
                case 'database':
                    progressBar.style.width = '90%';
                    break;
                case 'finalizing':
                    progressBar.style.width = '95%';
                    break;
                case 'complete':
                    progressBar.style.width = '100%';
                    progressMsg.textContent = 'Password changed. Saving backup…';
                    eventSource.close();
                    // Skip the click-to-dismiss alert and go straight into the
                    // logout flow. The auto-backup at logout runs against
                    // every-file-modified, which can take 30-60 seconds with
                    // no feedback otherwise. The existing logoutModal gives
                    // the user something to look at during the wait.
                    setTimeout(async () => {
                        const modal = document.getElementById('logoutModal');
                        const status = document.getElementById('logoutStatus');
                        if (modal) modal.classList.add('active');
                        if (status) status.textContent = 'Saving backup… this may take a minute.';
                        if (typeof lucide !== 'undefined') lucide.createIcons();
                        try {
                            const response = await fetch('/auth/logout', { method: 'POST' });
                            if (response.redirected) {
                                window.location.href = response.url;
                            } else {
                                window.location.href = '/auth/login';
                            }
                        } catch (e) {
                            window.location.href = '/auth/login';
                        }
                    }, 500);
                    break;
            }
        };
        
        eventSource.onerror = () => {
            eventSource.close();
            errorEl.textContent = 'Connection lost. Check whether the password change completed.';
            errorEl.style.display = 'block';
            confirmBtn.disabled = false;
            cancelBtn.disabled = false;
        };
        
    } catch (error) {
        errorEl.textContent = error.message;
        errorEl.style.display = 'block';
        confirmBtn.disabled = false;
        cancelBtn.disabled = false;
    }
}

/**
 * Render trash section content.
 */
function renderTrashSection() {
    return `
        <div class="trash-setting-group">
            <label class="setting-label">Automatically delete items in Trash after:</label>
            <div class="custom-select" id="trashRetentionSelect" data-name="trashRetention" data-value="7">
                <div class="custom-select-option" data-value="0">Never</div>
                <div class="custom-select-option" data-value="7">7 days</div>
                <div class="custom-select-option" data-value="30">30 days</div>
                <div class="custom-select-option" data-value="90">90 days</div>
                <div class="custom-select-option" data-value="365">1 year</div>
            </div>
            <p class="setting-hint">Trashed items are permanently removed after this period.</p>
        </div>
    `;
}

/**
 * Render danger zone section content.
 */
function renderDangerZoneSection() {
    return `
        <div class="danger-zone-box">
            <h4><i data-lucide="alert-triangle" class="icon-inline"></i> Reset Database</h4>
            <p>This will permanently delete all data including:</p>
            <ul>
                <li>All archived emails and folders</li>
                <li>All email account configurations</li>
                <li>All settings and preferences</li>
                <li>All backups</li>
            </ul>
            <p><strong>This action cannot be undone.</strong></p>
            
            <button data-action="showResetDatabase" class="btn btn-danger">
                <i data-lucide="trash-2" class="icon-inline"></i>
                Reset Database
            </button>
        </div>
    `;
}

/**
 * Initialize section toggle behavior.
 */
function initSettingsSectionToggles() {
    document.querySelectorAll('.settings-section-header-inline').forEach(header => {
        header.addEventListener('click', () => {
            const section = header.dataset.section;
            const body = document.getElementById(`${section}Body`);
            const chevron = header.querySelector('.section-chevron');
            
            if (body) {
                const isOpen = body.style.display !== 'none';
                body.style.display = isOpen ? 'none' : 'block';
                if (chevron) {
                    chevron.style.transform = isOpen ? 'rotate(0deg)' : 'rotate(90deg)';
                }
                
                // Load accounts when opening that section
                if (section === 'accounts' && !isOpen) {
                    loadAccounts();
                }
            }
        });
    });
}

/**
 * Initialize appearance option handlers.
 */
function initAppearanceHandlers() {
    // Theme selection
    document.querySelectorAll('.theme-option').forEach(btn => {
        btn.addEventListener('click', () => {
            const theme = btn.dataset.theme;
            setTheme(theme);
            document.querySelectorAll('.theme-option').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        });
    });
    
    // Font selection
    document.querySelectorAll('.font-option').forEach(btn => {
        btn.addEventListener('click', () => {
            const font = btn.dataset.font;
            setFont(font);
            document.querySelectorAll('.font-option').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        });
    });
    
    // Font size selection
    document.querySelectorAll('.size-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const size = btn.dataset.size;
            setFontSize(size);
            document.querySelectorAll('.size-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        });
    });
}

/**
 * Load current settings and mark active options.
 */
async function loadCurrentSettings() {
    // Get current theme
    const currentTheme = localStorage.getItem('mailrepo-theme') || 'pine';
    const themeBtn = document.querySelector(`.theme-option[data-theme="${currentTheme}"]`);
    if (themeBtn) themeBtn.classList.add('active');
    
    // Get current font
    const currentFont = localStorage.getItem('mailrepo-font') || 'lexend';
    const fontBtn = document.querySelector(`.font-option[data-font="${currentFont}"]`);
    if (fontBtn) fontBtn.classList.add('active');
    
    // Get current font size
    const currentSize = localStorage.getItem('mailrepo-font-size') || 's';
    const sizeBtn = document.querySelector(`.size-btn[data-size="${currentSize}"]`);
    if (sizeBtn) sizeBtn.classList.add('active');
    
    // Load trash retention setting from server
    try {
        const response = await fetch('/api/settings/trash-retention');
        if (response.ok) {
            const data = await response.json();
            const selectEl = document.getElementById('trashRetentionSelect');
            if (selectEl && selectEl._customSelect) {
                selectEl._customSelect.setValue(data.value || '7');
            }
        }
    } catch (err) {
        console.error('Failed to load trash retention setting:', err);
    }
    
    // Load session timeout setting from server
    try {
        const response = await fetch('/api/settings/session-timeout');
        if (response.ok) {
            const data = await response.json();
            const selectEl = document.getElementById('sessionTimeoutSelect');
            if (selectEl && selectEl._customSelect) {
                selectEl._customSelect.setValue(data.value || '30');
            }
        }
    } catch (err) {
        console.error('Failed to load session timeout setting:', err);
    }

    // Load thread-max-messages setting from server
    try {
        const response = await fetch('/api/settings/thread-max-messages');
        if (response.ok) {
            const data = await response.json();
            const selectEl = document.getElementById('threadMaxMessagesSelect');
            if (selectEl && selectEl._customSelect) {
                selectEl._customSelect.setValue(data.value || '500');
            }
        }
    } catch (err) {
        console.error('Failed to load thread max messages setting:', err);
    }
    
    // Mark settings as loaded - changes after this are user-initiated
    // Use setTimeout to ensure change events from setValue() have been processed
    setTimeout(() => { settingsLoaded = true; }, 50);
}

/**
 * Initialize trash settings handlers.
 */
function initTrashHandlers() {
    const select = document.getElementById('trashRetentionSelect');
    if (select) {
        select.addEventListener('change', async (e) => {
            if (!settingsLoaded) return; // Skip during initialization
            try {
                await fetch('/api/settings/trash-retention', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ value: e.detail.value }),
                });
            } catch (err) {
                console.error('Failed to save trash retention setting:', err);
            }
        });
    }
}

/**
 * Initialize the thread-staging settings handler (maximum thread size).
 */
function initThreadStagingHandlers() {
    const select = document.getElementById('threadMaxMessagesSelect');
    if (select) {
        select.addEventListener('change', async (e) => {
            if (!settingsLoaded) return; // Skip during initialization
            try {
                await fetch('/api/settings/thread-max-messages', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ value: e.detail.value }),
                });
            } catch (err) {
                console.error('Failed to save thread max messages setting:', err);
            }
        });
    }
}

/**
 * Set theme and persist.
 */
function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    document.body.dataset.theme = theme;
    localStorage.setItem('mailrepo-theme', theme);
    fetch('/api/settings/theme', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ theme })
    }).catch(() => {});
}

/**
 * Set font and persist.
 */
function setFont(font) {
    const fontFamilies = {
        'lexend': 'var(--font-lexend)',
        'libre-baskerville': 'var(--font-libre)',
        'source-sans': 'var(--font-source-sans)'
    };
    const fontFamily = fontFamilies[font] || fontFamilies['lexend'];
    document.documentElement.style.setProperty('--font-ui', fontFamily);
    document.documentElement.style.setProperty('--font-body', fontFamily);
    localStorage.setItem('mailrepo-font', font);
    fetch('/api/settings/font', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ font })
    }).catch(() => {});
}

/**
 * Set font size and persist.
 */
function setFontSize(size) {
    document.documentElement.classList.remove('font-size-s', 'font-size-m', 'font-size-l');
    document.documentElement.classList.add(`font-size-${size}`);
    localStorage.setItem('mailrepo-font-size', size);
    fetch('/api/settings/fontSize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fontSize: size })
    }).catch(() => {});
}

/**
 * Load accounts from API.
 */
async function loadAccounts() {
    const container = document.getElementById('accountsList');
    if (!container) return;
    
    try {
        const response = await fetch('/api/accounts');
        const data = await response.json();
        
        if (data.accounts && data.accounts.length > 0) {
            container.innerHTML = data.accounts.map(account => `
                <div class="account-card" data-id="${account.id}">
                    <div class="account-info">
                        <div class="account-icon">
                            <i data-lucide="mail"></i>
                        </div>
                        <div class="account-details">
                            <span class="account-name">${escapeHtml(account.name)}</span>
                            ${account.email ? `
                                <span class="account-email">${escapeHtml(account.email)}</span>
                                <span class="account-status connected">Connected</span>
                            ` : `
                                <span class="account-status pending">Not configured</span>
                            `}
                        </div>
                    </div>
                    <div class="account-actions">
                        <button class="btn btn-secondary btn-sm" data-action="editAccount" data-account-id="${account.id}" data-account-name="${escapeHtml(account.name)}" data-account-email="${escapeHtml(account.email || '')}" title="Edit account">
                            <i data-lucide="pencil"></i>
                        </button>
                        <button class="btn btn-secondary btn-sm" data-action="testAccount" data-account-id="${account.id}" title="Test connection">
                            <i data-lucide="wifi"></i>
                        </button>
                        <button class="btn btn-danger btn-sm" data-action="deleteAccount" data-account-id="${account.id}" title="Delete account">
                            <i data-lucide="trash-2"></i>
                        </button>
                    </div>
                </div>
            `).join('');
        } else {
            container.innerHTML = `
                <div class="section-empty">
                    <p>No email accounts connected yet.</p>
                </div>
            `;
        }
        
        if (typeof lucide !== 'undefined') lucide.createIcons();
    } catch (e) {
        container.innerHTML = `<p class="error">Failed to load accounts</p>`;
    }
}


// ============================================
// GLOBAL FUNCTIONS FOR SETTINGS MODALS
// ============================================

/**
 * Open the Add Account modal.
 */
function openAddAccountModal() {
    editingAccountId = null;  // Ensure we're in "add" mode
    const modal = document.getElementById('addAccountModal');
    if (modal) {
        // Reset modal title and button
        const title = modal.querySelector('.modal-header h3');
        if (title) title.textContent = 'Add Email Account';
        
        const btn = document.getElementById('createAccountBtn');
        if (btn) btn.textContent = 'Add Account';
        
        // Clear form
        document.getElementById('accountName').value = '';
        document.getElementById('accountEmail').value = '';
        document.getElementById('accountPassword').value = '';
        document.getElementById('accountPassword').placeholder = '';
        document.getElementById('imapHost').value = '';
        document.getElementById('imapPort').value = '993';
        document.getElementById('imapSsl').checked = true;
        
        // Collapse advanced settings
        const details = modal.querySelector('.advanced-settings');
        if (details) details.removeAttribute('open');
        
        modal.classList.add('active');
        document.getElementById('accountName').focus();
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
};

/**
 * Show app password info modal.
 */
function showAppPasswordInfo() {
    const modal = document.getElementById('appPasswordModal');
    if (modal) modal.classList.add('active');
};

/**
 * Show about modal.
 */
function showAboutModal() {
    const modal = document.getElementById('aboutModal');
    if (modal) modal.classList.add('active');
};

/**
 * Test account connection.
 */
async function testAccount(accountId) {
    const { showAlert } = await import('../modals.js');
    try {
        const response = await fetch(`/api/accounts/${accountId}/test`, { method: 'POST' });
        const data = await response.json();
        if (data.success) {
            showAlert('Connection Test', 'Connection successful!');
        } else {
            showAlert('Connection Test', `Connection failed: ${data.error}`);
        }
    } catch (e) {
        showAlert('Error', 'Connection test failed');
    }
};

/**
 * Delete an account.
 */
async function deleteAccount(accountId) {
    const { showConfirm, showAlert } = await import('../modals.js');
    const confirmed = await showConfirm('Delete Account', 'Are you sure you want to remove this account?', {
        confirmText: 'Delete',
        confirmClass: 'btn-danger'
    });
    if (!confirmed) return;
    
    try {
        const response = await fetch(`/api/accounts/${accountId}`, { method: 'DELETE' });
        if (response.ok) {
            loadAccounts();
            // Also refresh sidebar
            const event = new CustomEvent('accountsChanged');
            window.dispatchEvent(event);
        } else {
            const data = await response.json();
            showAlert('Error', data.error || 'Failed to delete account');
        }
    } catch (e) {
        showAlert('Error', 'Failed to delete account');
    }
};

/**
 * Edit an existing account.
 */
let editingAccountId = null;

function editAccount(accountId, name, email) {
    editingAccountId = accountId;
    const modal = document.getElementById('addAccountModal');
    if (modal) {
        // Update modal title
        const title = modal.querySelector('.modal-header h3');
        if (title) title.textContent = 'Edit Email Account';
        
        // Update button text
        const btn = document.getElementById('createAccountBtn');
        if (btn) btn.textContent = 'Save Changes';
        
        // Fill in existing values
        document.getElementById('accountName').value = name;
        document.getElementById('accountEmail').value = email;
        document.getElementById('accountPassword').value = '';  // Don't show password
        document.getElementById('accountPassword').placeholder = 'Leave blank to keep current';
        document.getElementById('imapHost').value = '';
        document.getElementById('imapPort').value = '993';
        document.getElementById('imapSsl').checked = true;
        
        // Collapse advanced settings
        const details = modal.querySelector('.advanced-settings');
        if (details) details.removeAttribute('open');
        
        modal.classList.add('active');
        document.getElementById('accountName').focus();
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
};

/**
 * Reset modal to "Add" mode when closing.
 */
function resetAccountModal() {
    editingAccountId = null;
    const modal = document.getElementById('addAccountModal');
    if (modal) {
        const title = modal.querySelector('.modal-header h3');
        if (title) title.textContent = 'Add Email Account';
        
        const btn = document.getElementById('createAccountBtn');
        if (btn) btn.textContent = 'Add Account';
        
        document.getElementById('accountPassword').placeholder = '';
    }
}

// Set up Create Account button handler
document.addEventListener('DOMContentLoaded', () => {
    const createBtn = document.getElementById('createAccountBtn');
    if (createBtn) {
        createBtn.addEventListener('click', saveAccount);
    }
});

/**
 * Create or update an account from the modal form.
 */
async function saveAccount() {
    const { showAlert } = await import('../modals.js');
    const name = document.getElementById('accountName').value.trim();
    const email = document.getElementById('accountEmail').value.trim();
    const password = document.getElementById('accountPassword').value;
    const host = document.getElementById('imapHost').value.trim();
    const port = document.getElementById('imapPort').value;
    const ssl = document.getElementById('imapSsl').checked;
    
    // For new accounts, password is required; for edits, it's optional
    if (!name || !email || (!editingAccountId && !password)) {
        showAlert('Missing Fields', 'Please fill in all required fields');
        return;
    }
    
    try {
        const isEdit = !!editingAccountId;
        const url = isEdit ? `/api/accounts/${editingAccountId}` : '/api/accounts';
        const method = isEdit ? 'PATCH' : 'POST';
        
        const response = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, email, password, host, port: parseInt(port), use_ssl: ssl })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            closeModal('addAccountModal');
            resetAccountModal();
            loadAccounts();
            // Refresh sidebar
            const event = new CustomEvent('accountsChanged');
            window.dispatchEvent(event);
        } else {
            showAlert('Error', data.error || `Failed to ${isEdit ? 'update' : 'create'} account`);
        }
    } catch (e) {
        showAlert('Error', `Failed to ${editingAccountId ? 'update' : 'create'} account`);
    }
}

/**
 * Close a modal by ID. NOTE: This local definition has been REMOVED.
 * closeModal is now imported from ../modals.js (canonical version),
 * and the addAccountModal cleanup is registered via
 * registerModalCloseHandler() in initSettingsView. The template still
 * uses inline onclicks via window.closeModal -- modals.js owns that.
 */

// ============================================
// RESET DATABASE
// ============================================

/**
 * Show the reset database confirmation modal.
 */
function showResetDatabaseModal() {
    const modal = document.getElementById('resetDatabaseModal');
    if (modal) {
        document.getElementById('resetPassword').value = '';
        document.getElementById('resetConfirmation').value = '';
        const errorEl = document.getElementById('resetError');
        if (errorEl) errorEl.style.display = 'none';
        modal.classList.add('active');
        document.getElementById('resetPassword').focus();
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
};

/**
 * Close the reset database modal.
 */
export function closeResetDatabaseModal() {
    const modal = document.getElementById('resetDatabaseModal');
    if (modal) modal.classList.remove('active');
}

/**
 * Execute the database reset.
 */
export async function executeResetDatabase() {
    const password = document.getElementById('resetPassword').value;
    const confirmation = document.getElementById('resetConfirmation').value;
    const errorEl = document.getElementById('resetError');
    const btn = document.getElementById('resetExecuteBtn');
    
    // Client-side validation
    if (!password) {
        errorEl.textContent = 'Please enter your password';
        errorEl.style.display = 'block';
        return;
    }
    
    if (confirmation !== 'RESET') {
        errorEl.textContent = 'Please type RESET exactly to confirm';
        errorEl.style.display = 'block';
        return;
    }
    
    // Disable button and show loading state
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader" class="icon-inline btn-spinner"></i> Resetting...';
    if (typeof lucide !== 'undefined') lucide.createIcons();
    errorEl.style.display = 'none';
    
    try {
        const response = await fetch('/api/reset_database', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                password: password,
                confirmation: confirmation
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Redirect to login page
            window.location.href = '/auth/login?reset=1';
        } else {
            errorEl.textContent = data.error || 'Reset failed';
            errorEl.style.display = 'block';
            btn.disabled = false;
            btn.innerHTML = '<i data-lucide="trash-2" class="icon-inline"></i> Reset Everything';
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    } catch (error) {
        errorEl.textContent = 'Network error. Please try again.';
        errorEl.style.display = 'block';
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="trash-2" class="icon-inline"></i> Reset Everything';
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}

// Close modal on escape key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeResetDatabaseModal();
    }
});

// Close modal when clicking outside
document.getElementById('resetDatabaseModal')?.addEventListener('click', function(e) {
    if (e.target === this) {
        closeResetDatabaseModal();
    }
});
