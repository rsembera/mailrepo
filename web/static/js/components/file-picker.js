/**
 * MailRepo - File Picker Component
 * 
 * Custom file picker for navigating the filesystem and selecting
 * .mbox files, .pst files, or folders containing .eml files.
 */

import { escapeHtml } from '../utils.js';

// File picker state
let filePickerMode = null; // 'mbox', 'pst', or 'eml'
let filePickerPath = null;
let filePickerSelected = null;

// Callbacks for mounting (set by imports.js)
let onMboxSelected = null;
let onAppleMboxSelected = null;
let onEmlFolderSelected = null;
let onPstSelected = null;

/**
 * Initialize file picker with mount callbacks.
 */
export function initFilePicker(config = {}) {
    onMboxSelected = config.onMboxSelected;
    onAppleMboxSelected = config.onAppleMboxSelected;
    onEmlFolderSelected = config.onEmlFolderSelected;
    onPstSelected = config.onPstSelected;
    
    setupFilePickerHandlers();
}

function setupFilePickerHandlers() {
    const upBtn = document.getElementById('filePickerUp');
    const refreshBtn = document.getElementById('filePickerRefresh');
    const confirmBtn = document.getElementById('filePickerConfirm');
    const showHidden = document.getElementById('filePickerShowHidden');
    const appleMode = document.getElementById('filePickerAppleMode');
    
    upBtn?.addEventListener('click', () => navigateToParent());
    refreshBtn?.addEventListener('click', () => loadFilePickerDirectory(filePickerPath));
    confirmBtn?.addEventListener('click', () => confirmFilePicker());
    showHidden?.addEventListener('change', () => loadFilePickerDirectory(filePickerPath));
    appleMode?.addEventListener('change', () => {
        clearSelection();
        loadFilePickerDirectory(filePickerPath);
    });
}

function isAppleMailMode() {
    return document.getElementById('filePickerAppleMode')?.checked || false;
}

/**
 * Open the file picker modal.
 */
export async function openFilePicker(mode) {
    filePickerMode = mode;
    filePickerSelected = null;
    
    const modal = document.getElementById('filePickerModal');
    const title = document.getElementById('filePickerTitle');
    const confirmBtn = document.getElementById('filePickerConfirm');
    const selectedDiv = document.getElementById('filePickerSelected');
    const mboxOptions = document.getElementById('filePickerMboxOptions');
    const appleMode = document.getElementById('filePickerAppleMode');
    
    if (mode === 'mbox') {
        title.textContent = 'Select .mbox File';
        confirmBtn.textContent = 'Import';
        mboxOptions.style.display = 'flex';
        appleMode.checked = false;
    } else if (mode === 'pst') {
        title.textContent = 'Select .pst File (Outlook)';
        confirmBtn.textContent = 'Import';
        mboxOptions.style.display = 'none';
    } else {
        title.textContent = 'Select Folder with .eml Files';
        confirmBtn.textContent = 'Import Folder';
        mboxOptions.style.display = 'none';
    }
    
    confirmBtn.disabled = true;
    selectedDiv.style.display = 'none';
    
    modal.classList.add('active');
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    await loadFilePickerDirectory(null);
}

async function loadFilePickerDirectory(path) {
    const list = document.getElementById('filePickerList');
    const pathInput = document.getElementById('filePickerPathInput');
    const showHidden = document.getElementById('filePickerShowHidden')?.checked || false;
    const appleMode = isAppleMailMode();
    
    list.innerHTML = '<div class="file-picker-empty">Loading...</div>';
    
    const title = document.getElementById('filePickerTitle');
    const confirmBtn = document.getElementById('filePickerConfirm');
    if (filePickerMode === 'mbox') {
        if (appleMode) {
            title.textContent = 'Select Apple Mail Folder';
            confirmBtn.textContent = 'Import Folder';
        } else {
            title.textContent = 'Select .mbox File';
            confirmBtn.textContent = 'Import';
        }
    }
    
    try {
        // Filter: mbox mode shows only mbox files, apple mode shows only directories
        let filter = null;
        if (filePickerMode === 'mbox') {
            filter = appleMode ? 'dirs_only' : 'mbox';
        }
        
        const response = await fetch('/api/filesystem/browse', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                path: path || '',
                show_hidden: showHidden,
                filter: filter
            }),
        });
        
        if (!response.ok) {
            const data = await response.json();
            list.innerHTML = `<div class="file-picker-empty">${data.error || 'Failed to load'}</div>`;
            return;
        }
        
        const data = await response.json();
        filePickerPath = data.path;
        pathInput.value = data.path;
        
        if (data.items.length === 0) {
            const msg = filePickerMode === 'mbox' 
                ? (appleMode ? 'No folders here' : 'No .mbox files or folders here')
                : 'No files or folders here';
            list.innerHTML = `<div class="file-picker-empty">${msg}</div>`;
            return;
        }
        
        let html = '';
        for (const item of data.items) {
            const isDir = item.type === 'dir';
            const icon = isDir ? 'folder' : 'file';
            const sizeStr = item.size != null ? formatFileSize(item.size) : '';
            
            html += `
                <div class="file-picker-item" 
                     data-path="${escapeHtml(item.path)}"
                     data-name="${escapeHtml(item.name)}"
                     data-type="${item.type}"
                     data-is-mbox="${item.is_mbox || false}">
                    <i data-lucide="${icon}"></i>
                    <span class="file-name">${escapeHtml(item.name)}</span>
                    <span class="file-size">${sizeStr}</span>
                </div>
            `;
        }
        list.innerHTML = html;
        
        if (typeof lucide !== 'undefined') lucide.createIcons();
        
        list.querySelectorAll('.file-picker-item').forEach(item => {
            item.addEventListener('click', () => handleFilePickerClick(item));
            item.addEventListener('dblclick', () => handleFilePickerDblClick(item));
        });
        
        clearSelection();
        
        if (filePickerMode === 'eml') {
            await checkCurrentFolderForEml(data.path);
        }
        
        if (filePickerMode === 'mbox' && appleMode) {
            await checkCurrentFolderForAppleMbox(data.path);
        }
        
    } catch (error) {
        console.error('Failed to load directory:', error);
        list.innerHTML = '<div class="file-picker-empty">Failed to load directory</div>';
    }
}

async function checkCurrentFolderForEml(path) {
    try {
        const response = await fetch('/api/filesystem/scan-eml', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });
        
        if (response.ok) {
            const data = await response.json();
            if (data.count > 0) {
                selectFolder(path, path.split('/').pop() || 'Folder', data.count);
            }
        }
    } catch (error) {
        console.error('Failed to scan for EML:', error);
    }
}

async function checkCurrentFolderForAppleMbox(path) {
    try {
        const response = await fetch('/api/filesystem/scan-apple-mbox', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });
        
        if (response.ok) {
            const data = await response.json();
            if (data.tree && (data.tree.emails?.length > 0 || data.tree.children?.length > 0)) {
                selectAppleMboxFolder(path, path.split('/').pop() || 'Folder', data.totalEmails || 0, data.tree);
            }
        }
    } catch (error) {
        console.error('Failed to scan for Apple mbox:', error);
    }
}

function selectAppleMboxFolder(path, name, emailCount, tree) {
    filePickerSelected = { path, name, type: 'apple-mbox', emailCount, tree };
    
    const selectedDiv = document.getElementById('filePickerSelected');
    const selectedName = document.getElementById('filePickerSelectedName');
    const confirmBtn = document.getElementById('filePickerConfirm');
    
    selectedName.innerHTML = `
        <i data-lucide="folder"></i>
        <strong>${escapeHtml(name)}</strong>
        <span class="file-picker-info">(Apple Mail, ${emailCount} email${emailCount !== 1 ? 's' : ''})</span>
    `;
    selectedDiv.style.display = 'flex';
    confirmBtn.disabled = false;
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function handleFilePickerClick(item) {
    const path = item.dataset.path;
    const name = item.dataset.name;
    const isDir = item.dataset.type === 'dir';
    const isMbox = item.dataset.isMbox === 'true';
    const isPst = name.toLowerCase().endsWith('.pst');
    
    document.querySelectorAll('.file-picker-item').forEach(i => i.classList.remove('selected'));
    item.classList.add('selected');
    
    if (filePickerMode === 'mbox') {
        if (isMbox && !isAppleMailMode()) {
            selectFile(path, name);
        } else if (isDir && isAppleMailMode()) {
            checkFolderForAppleMbox(path);
        } else {
            clearSelection();
        }
    } else if (filePickerMode === 'pst') {
        if (isPst) {
            selectFile(path, name);
        } else {
            clearSelection();
        }
    } else if (filePickerMode === 'eml') {
        if (isDir) {
            checkFolderForEml(path);
        } else {
            clearSelection();
        }
    }
}

async function checkFolderForAppleMbox(path) {
    try {
        const response = await fetch('/api/filesystem/scan-apple-mbox', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });
        
        if (response.ok) {
            const data = await response.json();
            if (data.tree && (data.tree.emails?.length > 0 || data.tree.children?.length > 0)) {
                selectAppleMboxFolder(path, path.split('/').pop(), data.totalEmails || 0, data.tree);
            } else {
                clearSelection();
            }
        }
    } catch (error) {
        console.error('Failed to check for Apple mbox:', error);
        clearSelection();
    }
}

function handleFilePickerDblClick(item) {
    const path = item.dataset.path;
    const isDir = item.dataset.type === 'dir';
    const isMbox = item.dataset.isMbox === 'true';
    
    if (isDir && !isMbox) {
        loadFilePickerDirectory(path);
    } else if (filePickerMode === 'mbox' && !isAppleMailMode()) {
        if (isMbox) {
            confirmFilePicker();
        }
    }
}

async function checkFolderForEml(path) {
    try {
        const response = await fetch('/api/filesystem/scan-eml', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });
        
        if (response.ok) {
            const data = await response.json();
            if (data.count > 0) {
                selectFolder(path, path.split('/').pop(), data.count);
            } else {
                clearSelection();
            }
        }
    } catch (error) {
        console.error('Failed to check for EML:', error);
        clearSelection();
    }
}

function selectFile(path, name) {
    filePickerSelected = { path, name, type: 'file' };
    
    const selectedDiv = document.getElementById('filePickerSelected');
    const selectedName = document.getElementById('filePickerSelectedName');
    const confirmBtn = document.getElementById('filePickerConfirm');
    
    selectedName.innerHTML = `<i data-lucide="file"></i> <strong>${escapeHtml(name)}</strong>`;
    selectedDiv.style.display = 'flex';
    confirmBtn.disabled = false;
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function selectFolder(path, name, emlCount) {
    filePickerSelected = { path, name, type: 'folder', emlCount };
    
    const selectedDiv = document.getElementById('filePickerSelected');
    const selectedName = document.getElementById('filePickerSelectedName');
    const confirmBtn = document.getElementById('filePickerConfirm');
    
    selectedName.innerHTML = `
        <i data-lucide="folder"></i>
        <strong>${escapeHtml(name)}</strong>
        <span class="file-picker-info">(${emlCount} .eml file${emlCount !== 1 ? 's' : ''})</span>
    `;
    selectedDiv.style.display = 'flex';
    confirmBtn.disabled = false;
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function clearSelection() {
    filePickerSelected = null;
    
    const selectedDiv = document.getElementById('filePickerSelected');
    const confirmBtn = document.getElementById('filePickerConfirm');
    
    if (selectedDiv) selectedDiv.style.display = 'none';
    if (confirmBtn) confirmBtn.disabled = true;
}

function showPickerMessage(msg) {
    const list = document.getElementById('filePickerList');
    if (list) {
        list.innerHTML = `<div class="file-picker-empty">${msg}</div>`;
    }
}

async function navigateToParent() {
    if (!filePickerPath || filePickerPath === '/') return;
    
    const parts = filePickerPath.split('/').filter(p => p);
    parts.pop();
    const parentPath = '/' + parts.join('/');
    
    await loadFilePickerDirectory(parentPath || '/');
}

async function confirmFilePicker() {
    if (!filePickerSelected) return;
    
    closeModal('filePickerModal');
    
    try {
        if (filePickerMode === 'mbox') {
            if (filePickerSelected.type === 'apple-mbox') {
                if (onAppleMboxSelected) {
                    await onAppleMboxSelected(filePickerSelected.path, filePickerSelected.name, filePickerSelected.tree);
                }
            } else {
                if (onMboxSelected) {
                    await onMboxSelected(filePickerSelected.path, filePickerSelected.name);
                }
            }
        } else if (filePickerMode === 'pst') {
            if (onPstSelected) {
                await onPstSelected(filePickerSelected.path, filePickerSelected.name);
            }
        } else {
            if (onEmlFolderSelected) {
                await onEmlFolderSelected(filePickerSelected.path, filePickerSelected.name);
            }
        }
    } catch (error) {
        console.error('Failed to mount import:', error);
        alert('Failed to import: ' + error.message);
    }
}

function closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.classList.remove('active');
}

function formatFileSize(bytes) {
    if (bytes == null) return '';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}
