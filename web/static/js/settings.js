/* ============================================
   SETTINGS PAGE SCRIPTS
   ============================================ */

// ============================================
// ACCOUNT MANAGEMENT
// ============================================

document.getElementById('addAccountBtn')?.addEventListener('click', () => {
    document.getElementById('addAccountModal').classList.add('active');
    document.getElementById('accountName').focus();
});

document.getElementById('createAccountBtn')?.addEventListener('click', async () => {
    const name = document.getElementById('accountName').value.trim();
    
    if (!name) {
        alert('Please enter an account name');
        return;
    }
    
    try {
        const response = await fetch('/api/accounts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, provider: 'gmail' }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            alert(data.error || 'Failed to create account');
            return;
        }
        
        const data = await response.json();
        closeModal('addAccountModal');
        
        // Immediately authorize
        authorizeAccount(data.account.id);
        
    } catch (error) {
        console.error('Error:', error);
        alert('Failed to create account');
    }
});

async function authorizeAccount(accountId) {
    try {
        const btn = document.querySelector(`.account-card[data-id="${accountId}"] .btn-primary`);
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i data-lucide="loader"></i> Authorizing...';
            lucide.createIcons();
        }
        
        const response = await fetch(`/api/accounts/${accountId}/authorize`, {
            method: 'POST',
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            alert(data.error || 'Authorization failed');
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i data-lucide="key"></i> Authorize';
                lucide.createIcons();
            }
            return;
        }
        
        location.reload();
        
    } catch (error) {
        console.error('Error:', error);
        alert('Authorization failed. Check console for details.');
    }
}

async function deleteAccount(accountId) {
    if (!confirm('Remove this account? This will not delete any archived emails.')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/accounts/${accountId}`, {
            method: 'DELETE',
        });
        
        if (!response.ok) {
            const data = await response.json();
            alert(data.error || 'Failed to remove account');
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
        alert('Failed to remove account');
    }
}

// ============================================
// MODAL HELPERS
// ============================================

function closeModal(modalId) {
    document.getElementById(modalId)?.classList.remove('active');
}

function showAboutModal() {
    document.getElementById('aboutModal').classList.add('active');
}

// Close modal on backdrop click
document.getElementById('addAccountModal')?.addEventListener('click', (e) => {
    if (e.target.id === 'addAccountModal') {
        closeModal('addAccountModal');
    }
});

document.getElementById('aboutModal')?.addEventListener('click', (e) => {
    if (e.target.id === 'aboutModal') {
        closeModal('aboutModal');
    }
});

// Close modals on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeModal('addAccountModal');
        closeModal('aboutModal');
    }
});

// ============================================
// THEME SWITCHING
// ============================================

document.addEventListener('DOMContentLoaded', () => {
    const savedTheme = localStorage.getItem('mailrepo-theme') || 'teal';
    setTheme(savedTheme, false);
});

function setTheme(theme, save = true) {
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
