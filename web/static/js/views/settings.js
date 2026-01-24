/**
 * Settings View
 * 
 * Renders settings as a view within the main app layout,
 * following the same pattern as folder-mgmt.js and trash.js.
 */

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
    
    // Hide sidebar and toolbar (settings uses full width)
    if (sidebar) sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    if (headerActions) headerActions.innerHTML = '';
    
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
                        <p>Master password and encryption settings</p>
                    </div>
                </div>
                <div class="settings-section-body" id="securityBody" style="display: none;">
                    ${renderSecuritySection()}
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
    initAppearanceHandlers();
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
                <button class="theme-option" data-theme="lagoon" title="Lagoon">
                    <span class="theme-swatch" style="background: #1F8F74;"></span>
                    <span class="theme-name">Lagoon</span>
                </button>
                <button class="theme-option" data-theme="graphite" title="Graphite">
                    <span class="theme-swatch" style="background: #475569;"></span>
                    <span class="theme-name">Graphite</span>
                </button>
                <button class="theme-option" data-theme="bloom" title="Bloom">
                    <span class="theme-swatch" style="background: #3B6EA5;"></span>
                    <span class="theme-name">Bloom</span>
                </button>
                <button class="theme-option" data-theme="rose" title="Rose">
                    <span class="theme-swatch" style="background: #A65568;"></span>
                    <span class="theme-name">Rose</span>
                </button>
                <button class="theme-option" data-theme="midnight" title="Midnight">
                    <span class="theme-swatch" style="background: #1e1e2e; border: 2px solid #45475a;"></span>
                    <span class="theme-name">Midnight</span>
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
        <p style="color: var(--color-text-muted); margin-bottom: var(--space-lg);">
            Your master password protects your IMAP credentials and encrypted archives.
        </p>
        <button class="btn btn-secondary" disabled>
            <i data-lucide="key"></i>
            Change Master Password
        </button>
        <span style="margin-left: var(--space-sm); color: var(--color-text-muted); font-size: 0.875rem;">
            (Coming soon)
        </span>
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
function loadCurrentSettings() {
    // Get current theme
    const currentTheme = localStorage.getItem('theme') || 'lagoon';
    const themeBtn = document.querySelector(`.theme-option[data-theme="${currentTheme}"]`);
    if (themeBtn) themeBtn.classList.add('active');
    
    // Get current font
    const currentFont = localStorage.getItem('font') || 'lexend';
    const fontBtn = document.querySelector(`.font-option[data-font="${currentFont}"]`);
    if (fontBtn) fontBtn.classList.add('active');
    
    // Get current font size
    const currentSize = localStorage.getItem('fontSize') || 'm';
    const sizeBtn = document.querySelector(`.size-btn[data-size="${currentSize}"]`);
    if (sizeBtn) sizeBtn.classList.add('active');
}

/**
 * Set theme and persist.
 */
function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    document.body.dataset.theme = theme;
    localStorage.setItem('theme', theme);
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
    document.documentElement.dataset.font = font;
    localStorage.setItem('font', font);
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
    document.documentElement.dataset.fontSize = size;
    localStorage.setItem('fontSize', size);
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
