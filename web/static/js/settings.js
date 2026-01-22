/* ============================================
   SETTINGS PAGE SCRIPTS
   ============================================ */

// ============================================
// ACCOUNT MANAGEMENT (IMAP)
// ============================================

document.getElementById('addAccountBtn')?.addEventListener('click', () => {
    // Clear form
    document.getElementById('accountName').value = '';
    document.getElementById('accountEmail').value = '';
    document.getElementById('accountPassword').value = '';
    document.getElementById('imapHost').value = '';
    document.getElementById('imapPort').value = '993';
    document.getElementById('imapSsl').checked = true;
    
    document.getElementById('addAccountModal').classList.add('active');
    document.getElementById('accountName').focus();
});

// Auto-detect IMAP server when email is entered
document.getElementById('accountEmail')?.addEventListener('blur', async (e) => {
    const email = e.target.value.trim();
    if (!email || !email.includes('@')) return;
    
    // Only auto-detect if host is empty
    const hostInput = document.getElementById('imapHost');
    if (hostInput.value.trim()) return;
    
    try {
        const response = await fetch('/api/accounts/detect-server', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email }),
        });
        
        const data = await response.json();
        
        if (data.detected) {
            hostInput.value = data.host;
            document.getElementById('imapPort').value = data.port;
        }
    } catch (error) {
        console.log('Server detection failed:', error);
    }
});

document.getElementById('createAccountBtn')?.addEventListener('click', async () => {
    const name = document.getElementById('accountName').value.trim();
    const email = document.getElementById('accountEmail').value.trim();
    const password = document.getElementById('accountPassword').value;
    const host = document.getElementById('imapHost').value.trim();
    const port = parseInt(document.getElementById('imapPort').value) || 993;
    const useSsl = document.getElementById('imapSsl').checked;
    
    if (!name) {
        showAlert('Missing Field', 'Please enter an account name.');
        return;
    }
    
    if (!email) {
        showAlert('Missing Field', 'Please enter an email address.');
        return;
    }
    
    if (!password) {
        showAlert('Missing Field', 'Please enter a password.');
        return;
    }
    
    const btn = document.getElementById('createAccountBtn');
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader"></i> Connecting...';
    lucide.createIcons();
    
    try {
        const response = await fetch('/api/accounts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                name, 
                email, 
                password,
                host: host || undefined,
                port,
                use_ssl: useSsl,
            }),
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showAlert('Connection Failed', data.error || 'Failed to add account');
            btn.disabled = false;
            btn.innerHTML = '<i data-lucide="plus"></i> Add Account';
            lucide.createIcons();
            return;
        }
        
        closeModal('addAccountModal');
        // Reload with hash to keep accounts section open
        window.location.href = window.location.pathname + '#emailAccountsSection';
        window.location.reload();
        
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error', 'Failed to add account. Check console for details.');
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="plus"></i> Add Account';
        lucide.createIcons();
    }
});

async function testAccount(accountId) {
    const btn = document.querySelector(`.account-card[data-id="${accountId}"] .btn-secondary`);
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i data-lucide="loader"></i>';
        lucide.createIcons();
    }
    
    try {
        const response = await fetch(`/api/accounts/${accountId}/test`, {
            method: 'POST',
        });
        
        const data = await response.json();
        
        if (data.success) {
            showAlert('Connection Successful', data.message);
        } else {
            showAlert('Connection Failed', data.error);
        }
        
    } catch (error) {
        console.error('Error:', error);
        showAlert('Error', 'Connection test failed. Check console for details.');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i data-lucide="wifi"></i>';
            lucide.createIcons();
        }
    }
}

async function deleteAccount(accountId) {
    showConfirm(
        'Remove Account',
        'Remove this account? This will not delete any archived emails.',
        async () => {
            try {
                const response = await fetch(`/api/accounts/${accountId}`, {
                    method: 'DELETE',
                });
                
                if (!response.ok) {
                    const data = await response.json();
                    showAlert('Error', data.error || 'Failed to remove account');
                    return;
                }
                
                document.querySelector(`.account-card[data-id="${accountId}"]`)?.remove();
                
                // Show empty state if no accounts left
                const list = document.getElementById('accountsList');
                if (list && !list.querySelector('.account-card')) {
                    list.innerHTML = '<div class="section-empty"><p>No email accounts connected yet.</p></div>';
                }
                
            } catch (error) {
                console.error('Error:', error);
                showAlert('Error', 'Failed to remove account');
            }
        }
    );
}

// ============================================
// IMPORT FUNCTIONALITY
// ============================================

let currentImportType = null;

document.getElementById('importMboxBtn')?.addEventListener('click', () => {
    currentImportType = 'mbox';
    document.getElementById('importModalTitle').textContent = 'Import .mbox File';
    document.getElementById('importPath').placeholder = '/path/to/archive.mbox';
    document.getElementById('importPreview').style.display = 'none';
    document.getElementById('importModal').classList.add('active');
    document.getElementById('importPath').focus();
});

document.getElementById('importEmlBtn')?.addEventListener('click', () => {
    currentImportType = 'eml';
    document.getElementById('importModalTitle').textContent = 'Import .eml File';
    document.getElementById('importPath').placeholder = '/path/to/email.eml';
    document.getElementById('importPreview').style.display = 'none';
    document.getElementById('importModal').classList.add('active');
    document.getElementById('importPath').focus();
});

// Scan mbox on path blur
document.getElementById('importPath')?.addEventListener('blur', async (e) => {
    if (currentImportType !== 'mbox') return;
    
    const path = e.target.value.trim();
    if (!path) return;
    
    const preview = document.getElementById('importPreview');
    preview.innerHTML = '<p>Scanning...</p>';
    preview.style.display = 'block';
    
    try {
        const response = await fetch('/api/import/mbox/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            preview.innerHTML = `<p class="error">Error: ${data.error}</p>`;
            return;
        }
        
        let html = `<p><strong>${data.message_count}</strong> emails found</p>`;
        if (data.samples && data.samples.length > 0) {
            html += '<p class="preview-label">Sample emails:</p><ul>';
            for (const sample of data.samples) {
                html += `<li><strong>${escapeHtml(sample.subject)}</strong><br>
                         <small>${escapeHtml(sample.sender)}</small></li>`;
            }
            html += '</ul>';
        }
        preview.innerHTML = html;
        
    } catch (error) {
        console.error('Error:', error);
        preview.innerHTML = '<p class="error">Failed to scan file</p>';
    }
});

document.getElementById('runImportBtn')?.addEventListener('click', async () => {
    const path = document.getElementById('importPath').value.trim();
    const folderId = document.getElementById('importFolder').value;
    
    if (!path) {
        showAlert('Missing Field', 'Please enter a file path.');
        return;
    }
    
    if (!folderId) {
        showAlert('Missing Field', 'Please select a destination folder.');
        return;
    }
    
    const btn = document.getElementById('runImportBtn');
    btn.disabled = true;
    btn.innerHTML = '<i data-lucide="loader"></i> Importing...';
    lucide.createIcons();
    
    try {
        const endpoint = currentImportType === 'mbox' ? '/api/import/mbox' : '/api/import/eml';
        
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path, folder_id: parseInt(folderId) }),
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            showAlert('Import Failed', data.error || 'Unknown error');
            btn.disabled = false;
            btn.innerHTML = '<i data-lucide="upload"></i> Import';
            lucide.createIcons();
            return;
        }
        
        if (currentImportType === 'mbox') {
            showAlert('Import Complete', `${data.imported} of ${data.total} emails imported. ${data.failed} failed.`);
        } else {
            showAlert('Import Complete', 'Email imported successfully!');
        }
        
        closeModal('importModal');
        
    } catch (error) {
        console.error('Error:', error);
        showAlert('Import Failed', 'Import failed. Check console for details.');
        btn.disabled = false;
        btn.innerHTML = '<i data-lucide="upload"></i> Import';
        lucide.createIcons();
    }
});

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ============================================
// MODAL HELPERS
// ============================================

let confirmCallback = null;

function closeModal(modalId) {
    document.getElementById(modalId)?.classList.remove('active');
}

function showAboutModal() {
    document.getElementById('aboutModal').classList.add('active');
}

function showAppPasswordInfo() {
    document.getElementById('appPasswordModal').classList.add('active');
}

function showAlert(title, message) {
    document.getElementById('alertTitle').textContent = title;
    document.getElementById('alertMessage').textContent = message;
    document.getElementById('alertModal').classList.add('active');
}

function showConfirm(title, message, onConfirm) {
    document.getElementById('confirmTitle').textContent = title;
    document.getElementById('confirmMessage').textContent = message;
    confirmCallback = onConfirm;
    document.getElementById('confirmModal').classList.add('active');
}

document.getElementById('confirmBtn')?.addEventListener('click', () => {
    closeModal('confirmModal');
    if (confirmCallback) {
        confirmCallback();
        confirmCallback = null;
    }
});

// Close modal on backdrop click
document.querySelectorAll('.modal-overlay').forEach(modal => {
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.remove('active');
        }
    });
});

// Close modals on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.active').forEach(modal => {
            modal.classList.remove('active');
        });
    }
});

// ============================================
// THEME SWITCHING
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    const savedTheme = localStorage.getItem('mailrepo-theme') || 'lagoon';
    setTheme(savedTheme, false);
    
    // Auto-expand Email Accounts section if URL has ?accounts or #accounts
    const params = new URLSearchParams(window.location.search);
    if (params.has('accounts') || window.location.hash === '#accounts') {
        const section = document.getElementById('emailAccountsSection');
        if (section) {
            section.setAttribute('open', '');
            section.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }
});

function setTheme(theme, save = true) {
    // Set on both html and body to ensure all CSS selectors work
    document.documentElement.setAttribute('data-theme', theme);
    document.body.setAttribute('data-theme', theme);
    
    document.querySelectorAll('.theme-option').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.theme === theme);
    });
    
    if (save) {
        localStorage.setItem('mailrepo-theme', theme);
    }
}

document.getElementById('themeGrid')?.addEventListener('click', (e) => {
    const btn = e.target.closest('.theme-option');
    if (btn) {
        setTheme(btn.dataset.theme);
    }
});

// ============================================
// FONT SWITCHING
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    const savedFont = localStorage.getItem('mailrepo-font') || 'lexend';
    const savedSize = localStorage.getItem('mailrepo-font-size') || 'm';
    setFont(savedFont, false);
    setFontSize(savedSize, false);
    
    // Open section if hash is present (e.g., #accounts)
    if (window.location.hash) {
        const sectionId = window.location.hash.slice(1);
        const section = document.getElementById(sectionId);
        if (section && section.tagName === 'DETAILS') {
            section.setAttribute('open', '');
        }
    }
});

function setFont(font, save = true) {
    const fontFamilies = {
        'lexend': "var(--font-lexend)",
        'libre-baskerville': "var(--font-libre)",
        'source-sans': "var(--font-source-sans)"
    };
    const fontFamily = fontFamilies[font] || fontFamilies['lexend'];
    document.documentElement.style.setProperty('--font-ui', fontFamily);
    document.documentElement.style.setProperty('--font-body', fontFamily);
    
    // Update theme names to use selected font
    document.querySelectorAll('.theme-name').forEach(el => {
        el.style.fontFamily = fontFamily;
    });
    
    document.querySelectorAll('.font-option').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.font === font);
    });
    
    if (save) {
        localStorage.setItem('mailrepo-font', font);
    }
}

function setFontSize(size, save = true) {
    document.documentElement.classList.remove('font-size-s', 'font-size-m', 'font-size-l');
    document.documentElement.classList.add(`font-size-${size}`);
    
    document.querySelectorAll('.size-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.size === size);
    });
    
    if (save) {
        localStorage.setItem('mailrepo-font-size', size);
    }
}

document.getElementById('fontGrid')?.addEventListener('click', (e) => {
    const btn = e.target.closest('.font-option');
    if (btn) {
        setFont(btn.dataset.font);
    }
});

document.getElementById('sizeToggle')?.addEventListener('click', (e) => {
    const btn = e.target.closest('.size-btn');
    if (btn) {
        setFontSize(btn.dataset.size);
    }
});
