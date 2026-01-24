/**
 * MailRepo - Imports Component
 * 
 * Handles mounting/unmounting of .mbox and .eml files,
 * displaying them in the sidebar, and browsing their contents.
 * Uses custom file picker for filesystem navigation.
 */

import { escapeHtml } from '../utils.js';

// Mounted imports stored in memory (session-only)
const mountedImports = new Map();

// Callbacks
let onImportSelect = null;
let onImportFolderSelect = null;
let onImportUnmount = null;

// File picker state
let filePickerMode = null; // 'mbox' or 'eml'
let filePickerPath = null;
let filePickerSelected = null;
let filePickerResolve = null;

/**
 * Initialize the imports component.
 */
export function initImports(config = {}) {
    onImportSelect = config.onImportSelect;
    onImportFolderSelect = config.onImportFolderSelect;
    onImportUnmount = config.onImportUnmount;
    
    // Set up import button click
    const importBtn = document.getElementById('importRailBtn');
    if (importBtn) {
        importBtn.addEventListener('click', showImportModal);
    }
    
    // Set up modal buttons
    const mboxBtn = document.getElementById('importMboxBtn');
    const emlBtn = document.getElementById('importEmlBtn');
    
    if (mboxBtn) {
        mboxBtn.addEventListener('click', () => {
            closeModal('importModal');
            openFilePicker('mbox');
        });
    }
    
    if (emlBtn) {
        emlBtn.addEventListener('click', () => {
            closeModal('importModal');
            openFilePicker('eml');
        });
    }
    
    // Set up file picker handlers
    initFilePicker();
}

/**
 * Show the import type selection modal.
 */
function showImportModal() {
    // Switch to Mail view first
    const mailBtn = document.querySelector('.rail-btn[data-view="mail"]');
    if (mailBtn) mailBtn.click();
    
    const modal = document.getElementById('importModal');
    if (modal) {
        modal.classList.add('active');
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
}

/**
 * Close a modal by ID.
 */
function closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.classList.remove('active');
}

// Make closeModal available globally for onclick handlers
window.closeModal = closeModal;

// ============================================
// FILE PICKER
// ============================================

/**
 * Initialize file picker event handlers.
 */
function initFilePicker() {
    const upBtn = document.getElementById('filePickerUp');
    const refreshBtn = document.getElementById('filePickerRefresh');
    const confirmBtn = document.getElementById('filePickerConfirm');
    const showHidden = document.getElementById('filePickerShowHidden');
    const appleMode = document.getElementById('filePickerAppleMode');
    
    upBtn?.addEventListener('click', () => {
        navigateToParent();
    });
    
    refreshBtn?.addEventListener('click', () => {
        loadFilePickerDirectory(filePickerPath);
    });
    
    confirmBtn?.addEventListener('click', () => {
        confirmFilePicker();
    });
    
    showHidden?.addEventListener('change', () => {
        loadFilePickerDirectory(filePickerPath);
    });
    
    appleMode?.addEventListener('change', () => {
        // Clear selection and reload when mode changes
        clearSelection();
        loadFilePickerDirectory(filePickerPath);
    });
}

/**
 * Check if Apple Mail mode is enabled.
 */
function isAppleMailMode() {
    return document.getElementById('filePickerAppleMode')?.checked || false;
}

/**
 * Open the file picker modal.
 * @param {string} mode - 'mbox' or 'eml'
 */
async function openFilePicker(mode) {
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
    } else {
        title.textContent = 'Select Folder with .eml Files';
        confirmBtn.textContent = 'Import Folder';
        mboxOptions.style.display = 'none';
    }
    
    confirmBtn.disabled = true;
    selectedDiv.style.display = 'none';
    
    modal.classList.add('active');
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    // Start in home directory
    await loadFilePickerDirectory(null);
}

/**
 * Load directory contents into file picker.
 */
async function loadFilePickerDirectory(path) {
    const list = document.getElementById('filePickerList');
    const pathInput = document.getElementById('filePickerPathInput');
    const showHidden = document.getElementById('filePickerShowHidden')?.checked || false;
    const appleMode = isAppleMailMode();
    
    list.innerHTML = '<div class="file-picker-empty">Loading...</div>';
    
    // Update title based on mode
    const title = document.getElementById('filePickerTitle');
    const confirmBtn = document.getElementById('filePickerConfirm');
    if (filePickerMode === 'mbox') {
        if (appleMode) {
            title.textContent = 'Select Apple Mail Export Folder';
            confirmBtn.textContent = 'Import Folder';
        } else {
            title.textContent = 'Select .mbox File';
            confirmBtn.textContent = 'Import';
        }
    }
    
    try {
        // In Apple mode, show all directories; otherwise filter for mbox
        const filter = (filePickerMode === 'mbox' && !appleMode) ? 'mbox' : null;
        
        const response = await fetch('/api/filesystem/browse', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                path: path || '',
                show_hidden: showHidden,
                filter: filter,
            }),
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            list.innerHTML = `<div class="file-picker-empty">${escapeHtml(data.error || 'Failed to load')}</div>`;
            return;
        }
        
        filePickerPath = data.path;
        pathInput.value = data.path;
        
        if (data.items.length === 0) {
            const msg = filePickerMode === 'mbox' 
                ? (appleMode ? 'No folders' : 'No folders or .mbox files')
                : 'No items in this folder';
            list.innerHTML = `<div class="file-picker-empty">${msg}</div>`;
            return;
        }
        
        let html = '';
        for (const item of data.items) {
            const icon = item.type === 'dir' ? 'folder' : 'file';
            const sizeStr = item.size != null ? formatFileSize(item.size) : '';
            const typeClass = item.type === 'dir' ? 'dir' : 'file';
            
            html += `
                <div class="file-picker-item ${typeClass}" 
                     data-path="${escapeHtml(item.path)}" 
                     data-type="${item.type}"
                     data-name="${escapeHtml(item.name)}">
                    <i data-lucide="${icon}"></i>
                    <span class="file-name">${escapeHtml(item.name)}</span>
                    <span class="file-size">${sizeStr}</span>
                </div>
            `;
        }
        
        list.innerHTML = html;
        if (typeof lucide !== 'undefined') lucide.createIcons();
        
        // Add click handlers
        list.querySelectorAll('.file-picker-item').forEach(item => {
            item.addEventListener('click', () => handleFilePickerClick(item));
            item.addEventListener('dblclick', () => handleFilePickerDblClick(item));
        });
        
        // In eml mode, auto-select current folder if it contains .eml files
        if (filePickerMode === 'eml') {
            checkCurrentFolderForEml(data.path);
        }
        
        // In Apple mode, check if current folder has .mbox packages
        if (filePickerMode === 'mbox' && appleMode) {
            checkCurrentFolderForAppleMbox(data.path);
        }
        
    } catch (error) {
        console.error('File picker error:', error);
        list.innerHTML = `<div class="file-picker-empty">Error: ${error.message}</div>`;
    }
}

/**
 * Check if current folder contains .eml files and auto-select if so.
 */
async function checkCurrentFolderForEml(path) {
    try {
        const response = await fetch('/api/filesystem/scan-eml', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });
        
        const data = await response.json();
        
        if (response.ok && data.count > 0) {
            selectFolder(path, data.folder_name, data.count);
        } else {
            clearSelection();
        }
    } catch (error) {
        console.error('Error scanning for eml:', error);
    }
}

/**
 * Check if current folder contains Apple Mail .mbox packages.
 */
async function checkCurrentFolderForAppleMbox(path) {
    try {
        const response = await fetch('/api/filesystem/scan-apple-mbox', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });
        
        const data = await response.json();
        
        if (response.ok && data.totalEmails > 0) {
            const folderName = path.split('/').pop() || path;
            selectAppleMboxFolder(path, folderName, data.totalEmails, data.tree);
        } else {
            clearSelection();
        }
    } catch (error) {
        console.error('Error scanning for Apple mbox:', error);
    }
}

/**
 * Select an Apple Mail export folder.
 */
function selectAppleMboxFolder(path, name, emailCount, tree) {
    filePickerSelected = { path, name, type: 'apple-mbox', emailCount, tree };
    
    const selectedDiv = document.getElementById('filePickerSelected');
    const selectedName = document.getElementById('filePickerSelectedName');
    const confirmBtn = document.getElementById('filePickerConfirm');
    
    // Count folders in tree
    function countFolders(node) {
        let count = (node.emails && node.emails.length > 0) ? 1 : 0;
        for (const child of node.children || []) {
            count += countFolders(child);
        }
        return count;
    }
    const folderCount = countFolders(tree);
    
    selectedDiv.style.display = 'block';
    selectedName.textContent = `${folderCount} folder${folderCount !== 1 ? 's' : ''}, ${emailCount} email${emailCount !== 1 ? 's' : ''}`;
    confirmBtn.disabled = false;
}

/**
 * Handle single click on file picker item.
 */
function handleFilePickerClick(item) {
    const type = item.dataset.type;
    const path = item.dataset.path;
    const name = item.dataset.name;
    const appleMode = isAppleMailMode();
    
    // Clear previous selection highlight
    document.querySelectorAll('.file-picker-item.selected').forEach(el => {
        el.classList.remove('selected');
    });
    
    if (filePickerMode === 'mbox') {
        if (appleMode) {
            // Apple mode - clicking a folder scans it for .mbox packages
            item.classList.add('selected');
            if (type === 'dir') {
                checkFolderForAppleMbox(path);
            }
        } else {
            // Standard mode
            if (type === 'file') {
                // Select the mbox file
                item.classList.add('selected');
                selectFile(path, name);
            } else {
                // Single click on dir in mbox mode - just highlight, dblclick to enter
                item.classList.add('selected');
                clearSelection();
            }
        }
    } else {
        // eml mode - single click highlights, we scan for eml
        item.classList.add('selected');
        if (type === 'dir') {
            // Preview what's in this folder
            checkFolderForEml(path);
        }
    }
}

/**
 * Check a specific folder for Apple mbox packages.
 */
async function checkFolderForAppleMbox(path) {
    try {
        const response = await fetch('/api/filesystem/scan-apple-mbox', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });
        
        const data = await response.json();
        
        if (response.ok && data.totalEmails > 0) {
            selectAppleMboxFolder(path, data.tree.name, data.totalEmails, data.tree);
        } else {
            clearSelection();
            showPickerMessage('No Apple Mail .mbox packages found');
        }
    } catch (error) {
        console.error('Error checking folder:', error);
    }
}

/**
 * Handle double click on file picker item.
 */
function handleFilePickerDblClick(item) {
    const type = item.dataset.type;
    const path = item.dataset.path;
    
    if (type === 'dir') {
        loadFilePickerDirectory(path);
    } else if (filePickerMode === 'mbox' && !isAppleMailMode()) {
        // Double-click on mbox file = select and confirm
        selectFile(path, item.dataset.name);
        confirmFilePicker();
    }
}

/**
 * Check a specific folder for .eml files.
 */
async function checkFolderForEml(path) {
    try {
        const response = await fetch('/api/filesystem/scan-eml', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });
        
        const data = await response.json();
        
        if (response.ok && data.count > 0) {
            selectFolder(path, data.folder_name, data.count);
        } else {
            clearSelection();
            showPickerMessage('No .eml files in this folder');
        }
    } catch (error) {
        console.error('Error checking folder:', error);
    }
}

/**
 * Select a file (mbox mode).
 */
function selectFile(path, name) {
    filePickerSelected = { path, name, type: 'file' };
    
    const selectedDiv = document.getElementById('filePickerSelected');
    const selectedName = document.getElementById('filePickerSelectedName');
    const confirmBtn = document.getElementById('filePickerConfirm');
    
    selectedDiv.style.display = 'block';
    selectedName.textContent = name;
    confirmBtn.disabled = false;
}

/**
 * Select a folder (eml mode).
 */
function selectFolder(path, name, emlCount) {
    filePickerSelected = { path, name, type: 'folder', emlCount };
    
    const selectedDiv = document.getElementById('filePickerSelected');
    const selectedName = document.getElementById('filePickerSelectedName');
    const confirmBtn = document.getElementById('filePickerConfirm');
    
    selectedDiv.style.display = 'block';
    selectedName.textContent = `${name} (${emlCount} .eml file${emlCount !== 1 ? 's' : ''})`;
    confirmBtn.disabled = false;
}

/**
 * Clear selection.
 */
function clearSelection() {
    filePickerSelected = null;
    
    const selectedDiv = document.getElementById('filePickerSelected');
    const confirmBtn = document.getElementById('filePickerConfirm');
    
    selectedDiv.style.display = 'none';
    confirmBtn.disabled = true;
}

/**
 * Show a message in the picker selection area.
 */
function showPickerMessage(msg) {
    const selectedDiv = document.getElementById('filePickerSelected');
    const selectedName = document.getElementById('filePickerSelectedName');
    
    selectedDiv.style.display = 'block';
    selectedName.textContent = msg;
}

/**
 * Navigate to parent directory.
 */
async function navigateToParent() {
    if (!filePickerPath) return;
    
    // Get parent from server
    try {
        const response = await fetch('/api/filesystem/browse', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: filePickerPath }),
        });
        
        const data = await response.json();
        if (data.parent) {
            await loadFilePickerDirectory(data.parent);
        }
    } catch (error) {
        console.error('Error navigating up:', error);
    }
}

/**
 * Confirm file picker selection and mount the import.
 */
async function confirmFilePicker() {
    if (!filePickerSelected) return;
    
    closeModal('filePickerModal');
    
    try {
        let importId;
        
        if (filePickerMode === 'mbox') {
            if (filePickerSelected.type === 'apple-mbox') {
                // Apple Mail folder export
                importId = await mountAppleMboxFolder(filePickerSelected.path, filePickerSelected.name, filePickerSelected.tree);
            } else {
                // Standard mbox file
                importId = await mountMboxFromPath(filePickerSelected.path, filePickerSelected.name);
            }
        } else {
            importId = await mountEmlFolderFromPath(filePickerSelected.path, filePickerSelected.name);
        }
        
        renderImportsSection();
        
        // Auto-select the newly mounted import to show its contents
        if (importId && onImportSelect) {
            onImportSelect(importId);
        }
    } catch (error) {
        console.error('Failed to mount import:', error);
        alert('Failed to import: ' + error.message);
    }
}

/**
 * Format file size for display.
 */
function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// ============================================
// MOUNTING IMPORTS
// ============================================

/**
 * Mount an mbox file from filesystem path.
 * Uses server-side parsing for proper encoding support.
 */
async function mountMboxFromPath(path, name) {
    const response = await fetch('/api/filesystem/parse-mbox', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
    });
    
    if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || 'Failed to parse mbox');
    }
    
    const data = await response.json();
    const emails = data.emails;
    
    // Store path with each email for later retrieval
    emails.forEach(e => e.sourcePath = path);
    
    // Use server-detected folders, or null if none
    const folders = data.folders ? data.folders.map(f => ({
        ...f,
        emails: emails.filter(e => f.emailUids.includes(e.uid)),
        children: [],
    })) : null;
    
    const importId = `mbox-${Date.now()}`;
    mountedImports.set(importId, {
        type: 'mbox',
        name: name,
        path: path,
        folders: folders,
        emails: emails,
        mountedAt: Date.now(),
    });
    
    return importId;
}

/**
 * Mount an Apple Mail folder export.
 * The tree structure comes from the server scan.
 */
async function mountAppleMboxFolder(path, name, tree) {
    // Convert tree to our folder structure
    function convertTree(node, depth = 0) {
        const result = {
            name: node.name.replace(/\.mbox$/, ''),
            fullPath: node.path,
            emails: node.emails || [],
            children: [],
        };
        
        for (const child of node.children || []) {
            result.children.push(convertTree(child, depth + 1));
        }
        
        return result;
    }
    
    const folders = [];
    
    // If root has emails, add it as a folder
    if (tree.emails && tree.emails.length > 0) {
        folders.push(convertTree(tree));
    } else {
        // Just add the children
        for (const child of tree.children || []) {
            folders.push(convertTree(child));
        }
    }
    
    // Collect all emails from tree
    function collectEmails(node) {
        let all = [...(node.emails || [])];
        for (const child of node.children || []) {
            all = all.concat(collectEmails(child));
        }
        return all;
    }
    const allEmails = collectEmails(tree);
    
    const importId = `apple-${Date.now()}`;
    mountedImports.set(importId, {
        type: 'apple-mbox',
        name: name.replace(/\.mbox$/, ''),
        path: path,
        folders: folders.length > 0 ? folders : null,
        emails: allEmails,
        mountedAt: Date.now(),
    });
    
    return importId;
}

/**
 * Mount a folder of .eml files from filesystem path.
 * Uses server-side parsing for proper encoding support.
 */
async function mountEmlFolderFromPath(path, name) {
    // Scan folder for .eml files
    const scanResponse = await fetch('/api/filesystem/scan-eml', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
    });
    
    if (!scanResponse.ok) {
        const data = await scanResponse.json();
        throw new Error(data.error || 'Failed to scan folder');
    }
    
    const scanData = await scanResponse.json();
    
    if (scanData.count === 0) {
        throw new Error('No .eml files found in folder');
    }
    
    // Parse each .eml file using server-side parser
    const emails = [];
    for (const file of scanData.files) {
        try {
            const response = await fetch('/api/filesystem/parse-eml', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: file.path }),
            });
            
            if (response.ok) {
                const data = await response.json();
                emails.push(data.email);
            }
        } catch (error) {
            console.warn(`Failed to parse ${file.name}:`, error);
        }
    }
    
    const importId = `eml-${Date.now()}`;
    mountedImports.set(importId, {
        type: 'eml',
        name: name,
        path: path,
        emails: emails,
        mountedAt: Date.now(),
    });
    
    return importId;
}

// ============================================
// IMPORT MANAGEMENT
// ============================================

/**
 * Unmount an import.
 */
export function unmountImport(importId) {
    mountedImports.delete(importId);
    renderImportsSection();
    
    // Notify app to clear main pane if needed
    if (onImportUnmount) onImportUnmount(importId);
}

/**
 * Get all mounted imports.
 */
export function getMountedImports() {
    return Array.from(mountedImports.entries()).map(([id, data]) => ({
        id,
        ...data,
    }));
}
window.getMountedImports = getMountedImports;

/**
 * Get emails from a mounted import.
 */
export function getImportEmails(importId, folderPath = null) {
    const imp = mountedImports.get(importId);
    if (!imp) return [];
    
    if (imp.type === 'eml') {
        return imp.emails;
    }
    
    // For mbox or apple-mbox, find the folder
    if (folderPath && imp.folders) {
        const folder = findFolder(imp.folders, folderPath);
        return folder ? folder.emails : [];
    }
    
    // If no folder specified, return all emails for flat imports
    // or empty for tree imports (user should select a subfolder)
    if (imp.folders && imp.folders.length > 0) {
        // Has folder structure - if root has emails return those, otherwise empty
        return imp.emails.length > 0 && !imp.folders.some(f => f.fullPath === imp.path) 
            ? imp.emails 
            : [];
    }
    
    return imp.emails;
}

/**
 * Find a folder in the folder tree.
 */
function findFolder(folders, path) {
    for (const folder of folders) {
        if (folder.fullPath === path) return folder;
        if (folder.children) {
            const found = findFolder(folder.children, path);
            if (found) return found;
        }
    }
    return null;
}

// ============================================
// SIDEBAR RENDERING
// ============================================

/**
 * Render the imports section in the sidebar.
 */
export function renderImportsSection() {
    const section = document.getElementById('importsSection');
    const list = document.getElementById('importsList');
    const count = document.getElementById('importCount');
    
    if (!section || !list) return;
    
    const imports = getMountedImports();
    
    if (imports.length === 0) {
        section.style.display = 'none';
        return;
    }
    
    section.style.display = 'block';
    count.textContent = imports.length;
    
    let html = '';
    
    for (const imp of imports) {
        const icon = (imp.type === 'mbox' || imp.type === 'apple-mbox') ? 'archive' : 'folder-open';
        const hasChildren = (imp.type === 'mbox' || imp.type === 'apple-mbox') && imp.folders && imp.folders.length > 0;
        
        html += `
            <div class="tree-item import-item" data-import-id="${imp.id}">
                <div class="tree-item-row" data-type="import" data-id="${imp.id}">
                    ${hasChildren ? '<i data-lucide="chevron-right" class="chevron"></i>' : '<span class="chevron-spacer"></span>'}
                    <i data-lucide="${icon}" class="tree-icon"></i>
                    <span class="tree-label">${escapeHtml(imp.name)}</span>
                    <button class="unmount-btn" data-import-id="${imp.id}" title="Unmount">
                        <i data-lucide="x"></i>
                    </button>
                </div>
        `;
        
        if (hasChildren) {
            html += `<div class="tree-children" style="display: none;">`;
            html += renderImportFolders(imp.folders, imp.id, 0);
            html += `</div>`;
        }
        
        html += `</div>`;
    }
    
    list.innerHTML = html;
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    // Add click handlers
    list.querySelectorAll('.tree-item-row[data-type="import"]').forEach(row => {
        row.addEventListener('click', (e) => handleImportClick(e, row));
    });
    
    list.querySelectorAll('.tree-item-row[data-type="import-folder"]').forEach(row => {
        row.addEventListener('click', (e) => handleImportFolderClick(e, row));
    });
    
    list.querySelectorAll('.unmount-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const importId = btn.dataset.importId;
            unmountImport(importId);
        });
    });
}

/**
 * Render import folder tree.
 */
function renderImportFolders(folders, importId, depth) {
    let html = '';
    
    for (const folder of folders) {
        const hasChildren = folder.children && folder.children.length > 0;
        // Start with base indent for first level, increase for nested folders
        const indent = 16 + (depth * 16);
        
        html += `<div class="import-tree-item">`;
        html += `<div class="tree-item-row" data-type="import-folder" data-import-id="${importId}" data-folder="${escapeHtml(folder.fullPath)}" style="padding-left: ${indent}px">`;
        
        if (hasChildren) {
            html += `<i data-lucide="chevron-right" class="import-folder-chevron"></i>`;
        } else {
            html += `<span class="chevron-spacer"></span>`;
        }
        
        html += `<i data-lucide="folder" class="tree-icon"></i>`;
        html += `<span class="tree-label">${escapeHtml(folder.name)}</span>`;
        html += `</div>`;
        
        if (hasChildren) {
            html += `<div class="import-tree-children" style="display: none;">`;
            html += renderImportFolders(folder.children, importId, depth + 1);
            html += `</div>`;
        }
        
        html += `</div>`;
    }
    
    return html;
}

/**
 * Handle click on import item.
 */
function handleImportClick(e, row) {
    const clickedChevron = e.target.closest('.chevron');
    const clickedUnmount = e.target.closest('.unmount-btn');
    
    if (clickedUnmount) return;
    
    if (clickedChevron) {
        // Toggle expansion
        const isExpanding = !row.classList.contains('expanded');
        row.classList.toggle('expanded');
        const children = row.nextElementSibling;
        if (children?.classList.contains('tree-children')) {
            children.style.display = isExpanding ? 'block' : 'none';
            
            // When collapsing, also collapse all descendant folders
            if (!isExpanding) {
                children.querySelectorAll('.tree-item-row.expanded').forEach(expandedRow => {
                    expandedRow.classList.remove('expanded');
                });
                children.querySelectorAll('.tree-children').forEach(nested => {
                    nested.style.display = 'none';
                });
                children.querySelectorAll('.import-folder-chevron').forEach(chevron => {
                    chevron.style.transform = 'rotate(0deg)';
                });
            }
        }
        return;
    }
    
    // Select the import
    const importId = row.dataset.id;
    document.querySelectorAll('.tree-item-row').forEach(r => r.classList.remove('active'));
    row.classList.add('active');
    
    if (onImportSelect) onImportSelect(importId);
}

/**
 * Handle click on import folder.
 */
function handleImportFolderClick(e, row) {
    const clickedChevron = e.target.closest('.import-folder-chevron');
    
    if (clickedChevron) {
        const treeItem = row.closest('.import-tree-item');
        const children = treeItem?.querySelector('.import-tree-children');
        if (children) {
            const isExpanded = children.style.display !== 'none';
            children.style.display = isExpanded ? 'none' : 'block';
            clickedChevron.style.transform = isExpanded ? 'rotate(0deg)' : 'rotate(90deg)';
            
            // When collapsing, also collapse all descendant folders
            if (isExpanded) {
                children.querySelectorAll('.import-tree-children').forEach(nested => {
                    nested.style.display = 'none';
                });
                children.querySelectorAll('.import-folder-chevron').forEach(chevron => {
                    chevron.style.transform = 'rotate(0deg)';
                });
            }
        }
        return;
    }
    
    const importId = row.dataset.importId;
    const folder = row.dataset.folder;
    
    document.querySelectorAll('.tree-item-row').forEach(r => r.classList.remove('active'));
    row.classList.add('active');
    
    if (onImportFolderSelect) onImportFolderSelect(importId, folder);
}
