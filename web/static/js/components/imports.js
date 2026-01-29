/**
 * MailRepo - Imports Component
 * 
 * Handles mounting/unmounting of .mbox and .eml files,
 * displaying them in the sidebar, and browsing their contents.
 */

import { escapeHtml } from '../utils.js';
import { confirmNavigation } from '../state.js';
import { initFilePicker, openFilePicker } from './file-picker.js';

// Mounted imports stored in memory (session-only)
const mountedImports = new Map();

// Callbacks
let onImportSelect = null;
let onImportFolderSelect = null;
let onImportUnmount = null;

/**
 * Initialize the imports component.
 */
export function initImports(config = {}) {
    onImportSelect = config.onImportSelect;
    onImportFolderSelect = config.onImportFolderSelect;
    onImportUnmount = config.onImportUnmount;
    
    // Initialize file picker with mount callbacks
    initFilePicker({
        onMboxSelected: mountMboxFromPath,
        onAppleMboxSelected: mountAppleMboxFolder,
        onEmlFolderSelected: mountEmlFolderFromPath,
        onPstSelected: mountPstFromPath,
    });
    
    // Set up import button click
    const importBtn = document.getElementById('importRailBtn');
    if (importBtn) {
        importBtn.addEventListener('click', showImportModal);
    }
    
    // Set up modal buttons
    const mboxBtn = document.getElementById('importMboxBtn');
    const emlBtn = document.getElementById('importEmlBtn');
    const pstBtn = document.getElementById('importPstBtn');
    
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
    
    if (pstBtn) {
        pstBtn.addEventListener('click', handlePstImport);
    }
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
window.openImportModal = showImportModal;

/**
 * Close a modal by ID.
 */
function closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.classList.remove('active');
}

// Make closeModal available globally for onclick handlers
window.closeModal = closeModal;
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
    
    renderImportsSection();
    if (onImportSelect) onImportSelect(importId);
    
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
    
    renderImportsSection();
    if (onImportSelect) onImportSelect(importId);
    
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
    
    renderImportsSection();
    if (onImportSelect) onImportSelect(importId);
    
    return importId;
}

/**
 * Handle PST import - check support, then open file picker.
 */
async function handlePstImport() {
    closeModal('importModal');
    
    // Check if PST support is available
    try {
        const response = await fetch('/api/filesystem/check-pst-support');
        const data = await response.json();
        
        if (!data.supported) {
            const { showAlert } = await import('../modals.js');
            showAlert('PST Import Not Available', data.message);
            return;
        }
        
        // Open file picker for PST files
        openFilePicker('pst');
        
    } catch (error) {
        console.error('Error checking PST support:', error);
        const { showAlert } = await import('../modals.js');
        showAlert('Error', 'Failed to check PST support');
    }
}

/**
 * Mount a PST file - converts to mbox first.
 */
async function mountPstFromPath(path, name) {
    const { showAlert } = await import('../modals.js');
    
    // Show converting status in header
    const contextTitle = document.getElementById('contextTitle');
    const contextMeta = document.getElementById('contextMeta');
    const originalTitle = contextTitle?.textContent;
    const originalMeta = contextMeta?.textContent;
    
    if (contextTitle) contextTitle.textContent = 'Converting PST...';
    if (contextMeta) contextMeta.textContent = `Converting ${name} to mbox format. This may take a moment...`;
    
    try {
        // Convert PST to mbox
        const convertResponse = await fetch('/api/filesystem/convert-pst', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });
        
        if (!convertResponse.ok) {
            const data = await convertResponse.json();
            throw new Error(data.error || 'Failed to convert PST file');
        }
        
        const convertData = await convertResponse.json();
        
        // Build folder structure from converted mbox files
        const folders = [];
        const allEmails = [];
        
        for (const mboxFile of convertData.mbox_files) {
            // Parse each mbox file
            const parseResponse = await fetch('/api/filesystem/parse-mbox', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: mboxFile.path }),
            });
            
            if (parseResponse.ok) {
                const parseData = await parseResponse.json();
                const emails = parseData.emails || [];
                
                // Tag emails with their source path
                emails.forEach(e => e.sourcePath = mboxFile.path);
                
                if (emails.length > 0) {
                    folders.push({
                        name: mboxFile.name,
                        fullPath: mboxFile.path,
                        emails: emails,
                        children: [],
                    });
                    allEmails.push(...emails);
                }
            }
        }
        
        if (allEmails.length === 0) {
            // Clean up temp files
            await fetch('/api/filesystem/cleanup-pst-temp', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ temp_dir: convertData.temp_dir }),
            });
            throw new Error('No emails found in PST file');
        }
        
        const importId = `pst-${Date.now()}`;
        mountedImports.set(importId, {
            type: 'pst',
            name: name.replace(/\.pst$/i, ''),
            path: path,
            tempDir: convertData.temp_dir,  // Keep track for cleanup
            folders: folders.length > 0 ? folders : null,
            emails: allEmails,
            mountedAt: Date.now(),
        });
        
        renderImportsSection();
        if (onImportSelect) onImportSelect(importId);
        
        return importId;
        
    } catch (error) {
        // Restore original header
        if (contextTitle) contextTitle.textContent = originalTitle || 'Welcome to MailRepo';
        if (contextMeta) contextMeta.textContent = originalMeta || '';
        
        console.error('PST import error:', error);
        showAlert('PST Import Failed', error.message);
        throw error;
    }
}

// ============================================
// IMPORT MANAGEMENT
// ============================================

/**
 * Unmount an import.
 */
export async function unmountImport(importId) {
    const imp = mountedImports.get(importId);
    
    // Clean up temp files for PST imports
    if (imp && imp.type === 'pst' && imp.tempDir) {
        try {
            await fetch('/api/filesystem/cleanup-pst-temp', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ temp_dir: imp.tempDir }),
            });
        } catch (error) {
            console.warn('Failed to clean up PST temp files:', error);
        }
    }
    
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
async function handleImportClick(e, row) {
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
    
    // Navigation guard - check for unsaved selections
    if (!await confirmNavigation()) return;
    
    // Select the import
    const importId = row.dataset.id;
    document.querySelectorAll('.tree-item-row').forEach(r => r.classList.remove('active'));
    row.classList.add('active');
    
    if (onImportSelect) onImportSelect(importId);
}

/**
 * Handle click on import folder.
 */
async function handleImportFolderClick(e, row) {
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
    
    // Navigation guard - check for unsaved selections
    if (!await confirmNavigation()) return;
    
    const importId = row.dataset.importId;
    const folder = row.dataset.folder;
    
    document.querySelectorAll('.tree-item-row').forEach(r => r.classList.remove('active'));
    row.classList.add('active');
    
    if (onImportFolderSelect) onImportFolderSelect(importId, folder);
}
