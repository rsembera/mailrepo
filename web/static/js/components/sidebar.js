/**
 * MailRepo - Sidebar Component
 * 
 * Handles:
 * - Section collapse/expand
 * - Archive folder tree rendering
 * - IMAP folder loading and tree building
 * - Sidebar resize
 * - Tree item click handling
 */

import { escapeHtml } from '../utils.js';
import { state } from '../state.js';

// Callbacks set via init
let onFolderSelect = null;
let onAccountSelect = null;
let onImapFolderSelect = null;

/**
 * Initialize the sidebar component.
 * @param {Object} config
 * @param {Function} config.onFolderSelect - Called when archive folder clicked
 * @param {Function} config.onAccountSelect - Called when account clicked (shows folder selection)
 * @param {Function} config.onImapFolderSelect - Called when IMAP folder clicked
 */
export function initSidebar(config = {}) {
    onFolderSelect = config.onFolderSelect;
    onAccountSelect = config.onAccountSelect;
    onImapFolderSelect = config.onImapFolderSelect;
    
    initSidebarResize();
}

/**
 * Toggle a sidebar section's collapse state.
 * @param {HTMLElement} header - Section header element
 */
export function toggleSection(header) {
    const section = header.dataset.section;
    const content = document.getElementById(section + 'Section') || 
                    document.getElementById(section === 'accounts' ? 'accountsSection' : 'archiveSection');
    
    header.classList.toggle('collapsed');
    content?.classList.toggle('expanded');
}

/**
 * Handle tree item click (accounts, IMAP folders, archive folders).
 * @param {Event} e - Click event
 * @param {HTMLElement} row - Clicked row element
 */
export function handleTreeItemClick(e, row) {
    const type = row.dataset.type;
    const id = row.dataset.id;
    
    // Handle account click
    if (type === 'account') {
        const clickedChevron = e.target.closest('.chevron');
        if (clickedChevron) {
            // Toggle sidebar expansion only when clicking chevron
            row.classList.toggle('expanded');
            const children = row.nextElementSibling;
            if (children?.classList.contains('tree-children')) {
                children.style.display = row.classList.contains('expanded') ? 'block' : 'none';
            }
            return;
        }
        
        // Clicking account name loads folder selection in main pane (doesn't expand sidebar)
        document.querySelectorAll('.tree-item-row').forEach(r => r.classList.remove('active'));
        row.classList.add('active');
        
        if (onAccountSelect) onAccountSelect(id);
        return;
    }
    
    // Handle IMAP folder click
    if (type === 'label' || type === 'imap-folder') {
        const accountId = row.dataset.accountId;
        const folder = row.dataset.label || row.dataset.folder;
        if (onImapFolderSelect) onImapFolderSelect(accountId, folder);
    }
    
    // Handle archive folder click
    if (type === 'folder') {
        if (onFolderSelect) onFolderSelect(id);
    }
    
    // Update active state
    document.querySelectorAll('.tree-item-row').forEach(r => r.classList.remove('active'));
    row.classList.add('active');
}

/**
 * Add a new folder to the sidebar.
 * @param {Object} newFolder - Folder object with id, name, color
 */
export function updateSidebarFolders(newFolder) {
    const archiveSection = document.getElementById('archiveSection');
    if (!archiveSection) return;
    
    const addBtn = archiveSection.querySelector('.add-folder-btn');
    
    const folderItem = document.createElement('div');
    folderItem.className = 'tree-item folder-item';
    
    const colorDot = newFolder.color ? 
        `<span class="color-dot" style="background: ${newFolder.color}"></span>` : '';
    
    folderItem.innerHTML = `
        <div class="tree-item-row" data-type="folder" data-id="${newFolder.id}" data-color="${newFolder.color || ''}">
            ${colorDot}
            <i data-lucide="folder" class="tree-icon"></i>
            <span class="tree-label">${escapeHtml(newFolder.name)}</span>
        </div>
    `;
    
    if (addBtn) {
        archiveSection.insertBefore(folderItem, addBtn);
    } else {
        archiveSection.appendChild(folderItem);
    }
    
    const row = folderItem.querySelector('.tree-item-row');
    row.addEventListener('click', (e) => handleTreeItemClick(e, row));
    
    const countEl = document.getElementById('folderCount');
    if (countEl) countEl.textContent = state.folders.length;
    
    archiveSection.querySelector('.sidebar-empty')?.remove();
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Refresh the entire sidebar folder list from state.
 */
export function refreshSidebarFolders() {
    const archiveSection = document.getElementById('archiveSection');
    if (!archiveSection) return;
    
    archiveSection.querySelectorAll('.folder-item').forEach(el => el.remove());
    archiveSection.querySelector('.sidebar-empty')?.remove();
    
    const visibleFolders = state.folders.filter(f => !f.deleted_at);
    const topLevel = visibleFolders.filter(f => !f.parent_id);
    const addBtn = archiveSection.querySelector('.add-folder-btn');
    
    if (topLevel.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'sidebar-empty';
        empty.innerHTML = '<p>No archive folders</p>';
        if (addBtn) {
            archiveSection.insertBefore(empty, addBtn);
        } else {
            archiveSection.appendChild(empty);
        }
    } else {
        topLevel.forEach(folder => {
            const children = visibleFolders.filter(f => f.parent_id == folder.id);
            const folderEl = createFolderTreeItem(folder, children, 0);
            if (addBtn) {
                archiveSection.insertBefore(folderEl, addBtn);
            } else {
                archiveSection.appendChild(folderEl);
            }
        });
    }
    
    const countEl = document.getElementById('folderCount');
    if (countEl) countEl.textContent = topLevel.length;
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Create a folder tree item element with children.
 */
function createFolderTreeItem(folder, children, depth) {
    const folderItem = document.createElement('div');
    folderItem.className = 'tree-item folder-item';
    folderItem.dataset.folderId = folder.id;
    
    const hasChildren = children && children.length > 0;
    const colorDot = folder.color ? 
        `<span class="color-dot" style="background: ${folder.color}"></span>` : '';
    const chevron = hasChildren ? 
        `<i data-lucide="chevron-right" class="chevron"></i>` : '';
    const indent = depth > 0 ? `style="padding-left: ${12 + depth * 20}px"` : '';
    
    folderItem.innerHTML = `
        <div class="tree-item-row ${hasChildren ? 'has-children' : ''}" data-type="folder" data-id="${folder.id}" data-color="${folder.color || ''}" ${indent}>
            ${chevron}
            ${colorDot}
            <i data-lucide="folder" class="tree-icon"></i>
            <span class="tree-label">${escapeHtml(folder.name)}</span>
        </div>
    `;
    
    if (hasChildren) {
        const childrenContainer = document.createElement('div');
        childrenContainer.className = 'tree-children';
        childrenContainer.style.display = 'none';
        
        children.forEach(child => {
            const grandchildren = state.folders.filter(f => f.parent_id == child.id && !f.deleted_at);
            const childEl = createFolderTreeItem(child, grandchildren, depth + 1);
            childrenContainer.appendChild(childEl);
        });
        
        folderItem.appendChild(childrenContainer);
    }
    
    const row = folderItem.querySelector('.tree-item-row');
    row.addEventListener('click', (e) => {
        if (hasChildren && (e.target.closest('.chevron') || e.target.classList.contains('chevron'))) {
            e.stopPropagation();
            row.classList.toggle('expanded');
            const childContainer = folderItem.querySelector('.tree-children');
            if (childContainer) {
                childContainer.style.display = row.classList.contains('expanded') ? 'block' : 'none';
            }
            return;
        }
        handleTreeItemClick(e, row);
    });
    
    return folderItem;
}

/**
 * Load IMAP folders for an account.
 * @param {string} accountId - Account ID
 */
export async function loadAccountLabels(accountId) {
    const container = document.getElementById(`labels-${accountId}`);
    if (!container) return;
    
    try {
        const response = await fetch(`/api/accounts/${accountId}/folders`);
        
        if (!response.ok) {
            const data = await response.json();
            container.innerHTML = `<div class="tree-loading">${data.error || 'Failed to load'}</div>`;
            return;
        }
        
        const data = await response.json();
        const folders = data.folders || [];
        const tree = buildImapFolderTree(folders);
        const html = renderImapFolderTree(tree, accountId, 0);
        container.innerHTML = html || '<div class="tree-loading">No folders</div>';
        
        if (typeof lucide !== 'undefined') lucide.createIcons();
        
        // Add click handlers
        container.querySelectorAll('.tree-item-row[data-type="imap-folder"]').forEach(row => {
            row.addEventListener('click', (e) => {
                e.stopPropagation();
                handleTreeItemClick(e, row);
            });
        });
        
        container.querySelectorAll('.imap-folder-chevron').forEach(chevron => {
            chevron.addEventListener('click', (e) => {
                e.stopPropagation();
                const treeItem = chevron.closest('.imap-tree-item');
                const children = treeItem.querySelector('.imap-tree-children');
                if (children) {
                    const isExpanded = children.style.display !== 'none';
                    children.style.display = isExpanded ? 'none' : 'block';
                    chevron.style.transform = isExpanded ? 'rotate(0deg)' : 'rotate(90deg)';
                }
            });
        });
        
    } catch (error) {
        console.error('Error loading folders:', error);
        container.innerHTML = '<div class="tree-loading">Error loading folders</div>';
    }
}

/**
 * Build a tree structure from flat IMAP folder list.
 */
export function buildImapFolderTree(folders) {
    let delimiter = null;
    for (const folder of folders) {
        if (folder.delimiter) {
            delimiter = folder.delimiter;
            break;
        }
    }
    
    if (!delimiter) {
        const hasSlashPaths = folders.some(f => f.name.includes('/') && !f.name.startsWith('['));
        delimiter = hasSlashPaths ? '/' : null;
    }
    
    const priorityFolders = ['INBOX', 'Sent', 'Sent Messages', 'Drafts', 'Trash', 'Junk', 'Spam', 'Archive'];
    const root = { children: {} };
    
    folders.forEach(folder => {
        const parts = delimiter ? folder.name.split(delimiter) : [folder.name];
        let current = root;
        
        parts.forEach((part, idx) => {
            if (!current.children[part]) {
                current.children[part] = {
                    name: part,
                    fullPath: delimiter ? parts.slice(0, idx + 1).join(delimiter) : folder.name,
                    children: {}
                };
            }
            current = current.children[part];
        });
    });
    
    function toArray(node) {
        return Object.values(node.children)
            .map(child => ({ ...child, children: toArray(child) }))
            .sort((a, b) => {
                const aIdx = priorityFolders.findIndex(p => a.name.toUpperCase().includes(p.toUpperCase()));
                const bIdx = priorityFolders.findIndex(p => b.name.toUpperCase().includes(p.toUpperCase()));
                if (aIdx !== -1 && bIdx === -1) return -1;
                if (aIdx === -1 && bIdx !== -1) return 1;
                if (aIdx !== -1 && bIdx !== -1) return aIdx - bIdx;
                return a.name.localeCompare(b.name);
            });
    }
    
    return toArray(root);
}

/**
 * Render IMAP folder tree as HTML.
 */
function renderImapFolderTree(nodes, accountId, depth) {
    let html = '';
    
    nodes.forEach(node => {
        const hasChildren = node.children && node.children.length > 0;
        const indent = depth * 16;
        
        html += `<div class="imap-tree-item">`;
        html += `<div class="tree-item-row" data-type="imap-folder" data-account-id="${accountId}" data-folder="${escapeHtml(node.fullPath)}" style="padding-left: ${indent}px">`;
        
        if (hasChildren) {
            html += `<i data-lucide="chevron-right" class="imap-folder-chevron"></i>`;
        } else {
            html += `<span class="chevron-spacer"></span>`;
        }
        
        html += `<i data-lucide="${getFolderIcon(node.name)}" class="tree-icon"></i>`;
        html += `<span class="tree-label">${escapeHtml(node.name)}</span>`;
        html += `</div>`;
        
        if (hasChildren) {
            html += `<div class="imap-tree-children" style="display: none;">`;
            html += renderImapFolderTree(node.children, accountId, depth + 1);
            html += `</div>`;
        }
        
        html += `</div>`;
    });
    
    return html;
}

/**
 * Get folder icon based on name.
 */
export function getFolderIcon(folderName) {
    const name = folderName.toUpperCase();
    if (name === 'INBOX') return 'inbox';
    if (name.includes('SENT')) return 'send';
    if (name.includes('DRAFT')) return 'file-edit';
    if (name.includes('SPAM') || name.includes('JUNK')) return 'alert-triangle';
    if (name.includes('TRASH') || name.includes('DELETED')) return 'trash-2';
    if (name.includes('ARCHIVE')) return 'archive';
    if (name.includes('STAR') || name.includes('FLAG')) return 'star';
    return 'folder';
}

/**
 * Initialize sidebar resize functionality.
 */
function initSidebarResize() {
    const sidebar = document.getElementById('sidebar');
    const handle = document.getElementById('sidebarResizeHandle');
    if (!sidebar || !handle) return;
    
    const MIN_WIDTH = 280;
    const MAX_WIDTH = 420;
    let isResizing = false;
    let startX, startWidth;
    
    // Load saved width
    const savedWidth = localStorage.getItem('mailrepo-sidebar-width');
    if (savedWidth) {
        const width = parseInt(savedWidth, 10);
        if (width >= MIN_WIDTH && width <= MAX_WIDTH) {
            sidebar.style.width = width + 'px';
        }
    }
    
    handle.addEventListener('mousedown', (e) => {
        isResizing = true;
        startX = e.clientX;
        startWidth = sidebar.offsetWidth;
        handle.classList.add('dragging');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });
    
    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        const delta = e.clientX - startX;
        let newWidth = startWidth + delta;
        newWidth = Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, newWidth));
        sidebar.style.width = newWidth + 'px';
    });
    
    document.addEventListener('mouseup', () => {
        if (!isResizing) return;
        isResizing = false;
        handle.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        localStorage.setItem('mailrepo-sidebar-width', sidebar.offsetWidth);
    });
}
