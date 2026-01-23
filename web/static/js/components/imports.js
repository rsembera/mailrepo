/**
 * MailRepo - Imports Component
 * 
 * Handles mounting/unmounting of .mbox and .eml files,
 * displaying them in the sidebar, and browsing their contents.
 */

import { escapeHtml } from '../utils.js';
import { buildImapFolderTree, getFolderIcon } from './sidebar.js';

// Mounted imports stored in memory (session-only)
const mountedImports = new Map();

// Callbacks
let onImportSelect = null;
let onImportFolderSelect = null;

/**
 * Initialize the imports component.
 */
export function initImports(config = {}) {
    onImportSelect = config.onImportSelect;
    onImportFolderSelect = config.onImportFolderSelect;
    
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
            document.getElementById('mboxFileInput')?.click();
        });
    }
    
    if (emlBtn) {
        emlBtn.addEventListener('click', () => {
            closeModal('importModal');
            document.getElementById('emlFileInput')?.click();
        });
    }
    
    // Set up file input handlers
    const mboxInput = document.getElementById('mboxFileInput');
    const emlInput = document.getElementById('emlFileInput');
    
    if (mboxInput) {
        mboxInput.addEventListener('change', handleMboxSelect);
    }
    
    if (emlInput) {
        emlInput.addEventListener('change', handleEmlSelect);
    }
}

/**
 * Show the import type selection modal.
 */
function showImportModal() {
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

/**
 * Handle .mbox file selection.
 */
async function handleMboxSelect(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    
    // Reset input for re-selection
    e.target.value = '';
    
    try {
        // Get file path - for Electron/desktop this would be file.path
        // For web, we need to use the File API and send the content
        const importId = `mbox-${Date.now()}`;
        
        // Mount the mbox
        const result = await mountMbox(file, importId);
        if (result.success) {
            renderImportsSection();
        }
    } catch (error) {
        console.error('Failed to mount mbox:', error);
        alert('Failed to import mbox file: ' + error.message);
    }
}

/**
 * Handle .eml file selection.
 */
async function handleEmlSelect(e) {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    
    // Reset input for re-selection
    e.target.value = '';
    
    try {
        for (const file of files) {
            const importId = `eml-${Date.now()}-${file.name}`;
            await mountEml(file, importId);
        }
        renderImportsSection();
    } catch (error) {
        console.error('Failed to mount eml:', error);
        alert('Failed to import eml file(s): ' + error.message);
    }
}

/**
 * Mount an mbox file.
 */
async function mountMbox(file, importId) {
    // Read and parse the mbox file
    const content = await file.text();
    const emails = parseMbox(content);
    
    // Detect folder structure (if any)
    const folders = detectMboxFolders(emails);
    
    mountedImports.set(importId, {
        type: 'mbox',
        name: file.name,
        path: file.name,
        folders: folders,
        emails: emails,
        mountedAt: Date.now(),
    });
    
    return { success: true, emailCount: emails.length };
}

/**
 * Mount an eml file.
 */
async function mountEml(file, importId) {
    const content = await file.text();
    const email = parseEml(content);
    
    mountedImports.set(importId, {
        type: 'eml',
        name: file.name,
        path: file.name,
        emails: [email],
        mountedAt: Date.now(),
    });
    
    return { success: true };
}

/**
 * Parse an mbox file into individual emails.
 */
function parseMbox(content) {
    const emails = [];
    // Split on "From " at start of line (mbox format)
    const parts = content.split(/^From /m);
    
    for (let i = 1; i < parts.length; i++) {
        const rawEmail = 'From ' + parts[i];
        const email = parseEmailHeaders(rawEmail);
        email.uid = `import-${i}`;
        email.raw = rawEmail;
        emails.push(email);
    }
    
    return emails;
}

/**
 * Parse an eml file.
 */
function parseEml(content) {
    const email = parseEmailHeaders(content);
    email.uid = `import-${Date.now()}`;
    email.raw = content;
    return email;
}

/**
 * Parse email headers from raw email content.
 */
function parseEmailHeaders(raw) {
    const lines = raw.split(/\r?\n/);
    const headers = {};
    let currentHeader = '';
    let headersDone = false;
    let bodyStart = 0;
    
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        
        // Empty line marks end of headers
        if (!headersDone && line === '') {
            headersDone = true;
            bodyStart = i + 1;
            continue;
        }
        
        if (headersDone) break;
        
        // Continuation of previous header (starts with whitespace)
        if (/^\s/.test(line) && currentHeader) {
            headers[currentHeader] += ' ' + line.trim();
            continue;
        }
        
        // New header
        const match = line.match(/^([^:]+):\s*(.*)$/);
        if (match) {
            currentHeader = match[1].toLowerCase();
            headers[currentHeader] = match[2];
        }
    }
    
    return {
        subject: decodeHeader(headers['subject'] || '(no subject)'),
        from: decodeHeader(headers['from'] || ''),
        to: decodeHeader(headers['to'] || ''),
        date: headers['date'] || '',
        message_id: headers['message-id'] || '',
    };
}

/**
 * Decode RFC 2047 encoded header (basic implementation).
 */
function decodeHeader(header) {
    if (!header) return '';
    
    // Handle =?charset?encoding?text?= format
    return header.replace(/=\?([^?]+)\?([BQ])\?([^?]+)\?=/gi, (match, charset, encoding, text) => {
        try {
            if (encoding.toUpperCase() === 'B') {
                return atob(text);
            } else if (encoding.toUpperCase() === 'Q') {
                return text.replace(/_/g, ' ').replace(/=([0-9A-F]{2})/gi, (m, hex) => 
                    String.fromCharCode(parseInt(hex, 16))
                );
            }
        } catch {
            return text;
        }
        return text;
    });
}

/**
 * Detect folder structure in mbox emails (based on X-Folder header or similar).
 */
function detectMboxFolders(emails) {
    // For now, just return a flat structure
    // Could be enhanced to detect folders from headers
    return [{
        name: 'All Mail',
        fullPath: 'All Mail',
        emails: emails,
        children: [],
    }];
}

/**
 * Unmount an import.
 */
export function unmountImport(importId) {
    mountedImports.delete(importId);
    renderImportsSection();
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

/**
 * Get emails from a mounted import.
 */
export function getImportEmails(importId, folderPath = null) {
    const imp = mountedImports.get(importId);
    if (!imp) return [];
    
    if (imp.type === 'eml') {
        return imp.emails;
    }
    
    // For mbox, find the folder
    if (folderPath && imp.folders) {
        const folder = findFolder(imp.folders, folderPath);
        return folder ? folder.emails : imp.emails;
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
        const icon = imp.type === 'mbox' ? 'archive' : 'file-text';
        const hasChildren = imp.type === 'mbox' && imp.folders && imp.folders.length > 0;
        
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
        const indent = depth * 16;
        
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
        row.classList.toggle('expanded');
        const children = row.nextElementSibling;
        if (children?.classList.contains('tree-children')) {
            children.style.display = row.classList.contains('expanded') ? 'block' : 'none';
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
        }
        return;
    }
    
    const importId = row.dataset.importId;
    const folder = row.dataset.folder;
    
    document.querySelectorAll('.tree-item-row').forEach(r => r.classList.remove('active'));
    row.classList.add('active');
    
    if (onImportFolderSelect) onImportFolderSelect(importId, folder);
}
