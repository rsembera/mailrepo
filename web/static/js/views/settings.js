/**
 * Settings View
 * 
 * Renders settings as a view within the main app layout,
 * following the same pattern as folder-mgmt.js and trash.js.
 */

import { initCustomSelects, CustomSelect } from '../components/custom-select.js';

let contextTitle = null;
let contextMeta = null;
let emailList = null;

/**
 * Initialize the settings view.
 */
export function initSettingsView(config) {
    contextTitle = config.contextTitle;
    contextMeta = config.contextMeta;
    emailList = config.emailList;
}

/**
 * Show the settings view in the main content area.
 */
export function showSettingsView() {
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
        <div class="settings-view">
            <!-- Appearance Section -->
            <section class="settings-section-inline">
                <div class="settings-section-header-inline" data-section="appearance">
                    <i data-lucide="chevron-right" class="section-chevron"></i>
                    <i data-lucide="palette" class="section-icon"></i>
                    <div class="section-text">
                        <h3>Appearance</h3>
                        <p>Customize the look and feel of MailRepo</p>
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
                        <p>Connect IMAP email accounts to archive from</p>
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
                        <p>Change your password</p>
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
                        <p>Automatic cleanup of deleted items</p>
                    </div>
                </div>
                <div class="settings-section-body" id="trashBody" style="display: none;">
                    ${renderTrashSection()}
                </div>
            </section>
            
            <!-- About Link -->
            <div class="settings-about-link">
                <a href="javascript:void(0);" onclick="showAboutModal()">About MailRepo</a>
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
    loadCurrentSettings();
}

/**
 * Render appearance section content.
 */
function renderAppearanceSection() {
    return `
        <div class="appearance-group">
            <label class="appearance-label">Theme</label>
            <div class="theme-grid" id="themeGrid">
                <button class="theme-option" data-theme="graphite" title="Graphite">
                    <span class="theme-swatch" style="background: #475569;"></span>
                    <span class="theme-name">Graphite</span>
                </button>
                <button class="theme-option" data-theme="pine" title="Pine">
                    <span class="theme-swatch" style="background: #1F8F74;"></span>
                    <span class="theme-name">Pine</span>
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
            <button class="btn btn-primary" id="addAccountBtn" onclick="openAddAccountModal()">
                <i data-lucide="plus"></i>
                Add Email Account
            </button>
        </div>
        
        <div class="helper-box">
            <strong>Note:</strong> For Gmail, iCloud, and other providers with 2FA, 
            you'll need to use an <strong>app-specific password</strong> instead of your regular password.
            <a href="javascript:void(0);" onclick="showAppPasswordInfo()">What's this?</a>
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
            <p class="setting-hint">Shorter timeouts recommended for shared spaces</p>
        </div>
        
        <hr class="settings-divider">
        
        <div class="form-group">
            <label>Password</label>
            <p class="setting-hint" style="margin-bottom: var(--space-md);">
                Your password protects your IMAP credentials and encrypted archives.
            </p>
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
                <small class="setting-hint">Minimum 8 characters</small>
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
    `;
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
        
        // Connect to SSE for progress
        const eventSource = new EventSource('/auth/api/change-password-progress');
        
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
                    eventSource.close();
                    // Success - show modal and redirect on confirm
                    setTimeout(async () => {
                        const { showAlert } = await import('../modals.js');
                        await showAlert('Password Changed', 'Your password has been changed. Please log in with your new password.');
                        window.location.href = '/auth/logout';
                    }, 500);
                    break;
            }
        };
        
        eventSource.onerror = () => {
            eventSource.close();
            errorEl.textContent = 'Connection lost during password change. Please check if the change completed.';
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
            <p class="setting-hint">Deleted folders and their emails will be permanently removed after this period.</p>
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
    const currentTheme = localStorage.getItem('mailrepo-theme') || 'graphite';
    const themeBtn = document.querySelector(`.theme-option[data-theme="${currentTheme}"]`);
    if (themeBtn) themeBtn.classList.add('active');
    
    // Get current font
    const currentFont = localStorage.getItem('mailrepo-font') || 'lexend';
    const fontBtn = document.querySelector(`.font-option[data-font="${currentFont}"]`);
    if (fontBtn) fontBtn.classList.add('active');
    
    // Get current font size
    const currentSize = localStorage.getItem('mailrepo-font-size') || 'm';
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
}

/**
 * Initialize trash settings handlers.
 */
function initTrashHandlers() {
    const select = document.getElementById('trashRetentionSelect');
    if (select) {
        select.addEventListener('change', async (e) => {
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
                        <button class="btn btn-secondary btn-sm" onclick="testAccount(${account.id})" title="Test connection">
                            <i data-lucide="wifi"></i>
                        </button>
                        <button class="btn btn-danger btn-sm" onclick="deleteAccount(${account.id})">
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

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ============================================
// GLOBAL FUNCTIONS FOR SETTINGS MODALS
// ============================================

/**
 * Open the Add Account modal.
 */
window.openAddAccountModal = function() {
    const modal = document.getElementById('addAccountModal');
    if (modal) {
        // Clear form
        document.getElementById('accountName').value = '';
        document.getElementById('accountEmail').value = '';
        document.getElementById('accountPassword').value = '';
        document.getElementById('imapHost').value = '';
        document.getElementById('imapPort').value = '993';
        document.getElementById('imapSsl').checked = true;
        
        modal.classList.add('active');
        document.getElementById('accountName').focus();
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
};

/**
 * Show app password info modal.
 */
window.showAppPasswordInfo = function() {
    const modal = document.getElementById('appPasswordModal');
    if (modal) modal.classList.add('active');
};

/**
 * Show about modal.
 */
window.showAboutModal = function() {
    const modal = document.getElementById('aboutModal');
    if (modal) modal.classList.add('active');
};

/**
 * Test account connection.
 */
window.testAccount = async function(accountId) {
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
window.deleteAccount = async function(accountId) {
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

// Set up Create Account button handler
document.addEventListener('DOMContentLoaded', () => {
    const createBtn = document.getElementById('createAccountBtn');
    if (createBtn) {
        createBtn.addEventListener('click', createAccount);
    }
});

/**
 * Create a new account from the modal form.
 */
async function createAccount() {
    const { showAlert } = await import('../modals.js');
    const name = document.getElementById('accountName').value.trim();
    const email = document.getElementById('accountEmail').value.trim();
    const password = document.getElementById('accountPassword').value;
    const host = document.getElementById('imapHost').value.trim();
    const port = document.getElementById('imapPort').value;
    const ssl = document.getElementById('imapSsl').checked;
    
    if (!name || !email || !password) {
        showAlert('Missing Fields', 'Please fill in all required fields');
        return;
    }
    
    try {
        const response = await fetch('/api/accounts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, email, password, host, port: parseInt(port), ssl })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            closeModal('addAccountModal');
            loadAccounts();
            // Refresh sidebar
            const event = new CustomEvent('accountsChanged');
            window.dispatchEvent(event);
        } else {
            showAlert('Error', data.error || 'Failed to create account');
        }
    } catch (e) {
        showAlert('Error', 'Failed to create account');
    }
}

/**
 * Close a modal by ID.
 */
function closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.classList.remove('active');
}

// Make closeModal available globally
window.closeModal = closeModal;
