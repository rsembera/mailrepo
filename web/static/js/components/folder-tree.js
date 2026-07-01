/**
 * MailRepo - Unified Folder Tree Component
 * 
 * Renders folder trees for:
 * - Sidebar archive folders
 * - Stage modal destination picker
 * - Folder management view
 * 
 * All use the same nested structure:
 *   .folder-tree-item (block container)
 *     .folder-tree-row (flex row with content)
 *     .folder-tree-children (block container for nested items)
 */

import { escapeHtml } from '../utils.js';
import { state } from '../state.js';

/**
 * Render a folder tree into a container.
 * 
 * @param {HTMLElement} container - Container to render into
 * @param {Object} options - Configuration options
 * @param {Function} options.filter - Filter function for folders (default: non-deleted)
 * @param {boolean} options.showChevrons - Show expand/collapse chevrons (default: true)
 * @param {boolean} options.showColorDots - Show color dots (default: true)
 * @param {boolean} options.showAddButtons - Show "add subfolder" buttons (default: false)
 * @param {boolean} options.selectable - Enable click-to-select mode (default: false)
 * @param {number} options.selectedId - Currently selected folder ID
 * @param {string} options.rowClass - Additional class for rows
 * @param {string} options.itemDataAttr - Data attribute name for item (default: 'id')
 * @param {Function} options.onSelect - Callback when folder selected: (folderId) => void
 * @param {Function} options.onToggle - Callback when folder toggled: (folderId, isExpanded) => void
 * @param {Function} options.onAddFolder - Callback when add clicked: (parentId) => void
 * @param {Function} options.onClick - Callback for row click: (folderId, event) => void
 * @param {Function} options.renderActions - Custom action renderer: (folder) => HTML string
 * @returns {Object} Controller with refresh(), setSelected(), expand(), collapse()
 */
export function renderFolderTree(container, options = {}) {
    const opts = {
        filter: f => !f.deleted_at && !f.retention_date,
        showChevrons: true,
        showColorDots: true,
        showAddButtons: false,
        selectable: false,
        selectedId: null,
        rowClass: '',
        itemDataAttr: 'id',
        onSelect: null,
        onToggle: null,
        onAddFolder: null,
        onClick: null,
        renderActions: null,
        // (folder) => boolean. When it returns false the row is still shown and
        // its chevron still expands (so children stay reachable), but the row
        // itself can't be selected. Default: everything selectable.
        isSelectable: null,
        ...options
    };
    
    // Get visible folders
    const visibleFolders = state.folders.filter(opts.filter);
    const rootFolders = visibleFolders.filter(f => !f.parent_id);
    rootFolders.sort((a, b) => a.name.localeCompare(b.name));
    
    // Track expanded state
    const expandedIds = new Set();
    // Folders shown but not selectable (recomputed each render).
    let disabledIds = new Set();
    let selectedId = opts.selectedId;
    
    // Render the tree
    function render() {
        if (rootFolders.length === 0) {
            container.innerHTML = '<div class="folder-tree-empty">No folders</div>';
            return;
        }
        
        let html = '';
        disabledIds = new Set();
        rootFolders.forEach(folder => {
            html += renderItem(folder, visibleFolders, 0);
        });
        container.innerHTML = html;
        
        if (typeof lucide !== 'undefined') lucide.createIcons();
        attachEventListeners();
    }
    
    // Render a single item with children
    function renderItem(folder, allFolders, depth) {
        const children = allFolders.filter(f => f.parent_id == folder.id);
        children.sort((a, b) => a.name.localeCompare(b.name));
        const hasChildren = children.length > 0;
        const isExpanded = expandedIds.has(folder.id);
        const isSelected = selectedId === folder.id;
        const selectable = !opts.isSelectable || opts.isSelectable(folder);
        if (!selectable) disabledIds.add(folder.id);
        const indent = depth * 20;
        
        let html = `<div class="folder-tree-item" data-${opts.itemDataAttr}="${folder.id}">`;
        
        // Row
        const rowClasses = ['folder-tree-row', opts.rowClass, isSelected ? 'selected' : '', selectable ? '' : 'disabled'].filter(Boolean).join(' ');
        html += `<div class="${rowClasses}" style="padding-left: ${12 + indent}px">`;
        
        // Chevron
        if (opts.showChevrons) {
            if (hasChildren) {
                const rotation = isExpanded ? 'style="transform: rotate(90deg)"' : '';
                html += `<span class="folder-tree-toggle"><i data-lucide="chevron-right" class="folder-tree-chevron" data-folder-id="${folder.id}" ${rotation}></i></span>`;
            } else {
                html += `<span class="folder-tree-toggle-spacer"></span>`;
            }
        }
        
        // Color dot
        if (opts.showColorDots) {
            if (folder.color) {
                html += `<span class="folder-tree-color" style="background: ${folder.color}"></span>`;
            } else {
                html += `<span class="folder-tree-color folder-tree-color-empty"></span>`;
            }
        }
        
        // Icon and label
        html += `<i data-lucide="folder" class="folder-tree-icon"></i>`;
        html += `<span class="folder-tree-label">${escapeHtml(folder.name)}</span>`;
        
        // Add button
        if (opts.showAddButtons) {
            html += `<button class="folder-tree-add-btn" data-parent-id="${folder.id}" title="Add subfolder"><i data-lucide="plus"></i></button>`;
        }
        
        // Custom actions
        if (opts.renderActions) {
            html += opts.renderActions(folder);
        }
        
        html += `</div>`; // Close row
        
        // Children
        if (hasChildren) {
            const display = isExpanded ? 'block' : 'none';
            html += `<div class="folder-tree-children" data-parent-id="${folder.id}" style="display: ${display}">`;
            children.forEach(child => {
                html += renderItem(child, allFolders, depth + 1);
            });
            html += `</div>`;
        }
        
        html += `</div>`; // Close item
        return html;
    }
    
    // Attach event listeners
    function attachEventListeners() {
        // Row clicks
        container.querySelectorAll('.folder-tree-row').forEach(row => {
            row.addEventListener('click', (e) => {
                const item = row.closest('.folder-tree-item');
                const folderId = parseInt(item.dataset[opts.itemDataAttr]);
                
                // Chevron click - toggle only
                if (e.target.closest('.folder-tree-toggle')) {
                    e.stopPropagation();
                    toggleFolder(folderId);
                    return;
                }
                
                // Add button click
                if (e.target.closest('.folder-tree-add-btn')) {
                    e.stopPropagation();
                    if (opts.onAddFolder) opts.onAddFolder(folderId);
                    return;
                }
                
                // Selection (disabled rows still expand via the chevron
                // handled above, but can't be chosen as a target)
                if (opts.selectable && !disabledIds.has(folderId)) {
                    selectedId = folderId;
                    container.querySelectorAll('.folder-tree-row').forEach(r => r.classList.remove('selected'));
                    row.classList.add('selected');
                    if (opts.onSelect) opts.onSelect(folderId);
                }
                
                // General click callback
                if (opts.onClick) opts.onClick(folderId, e);
            });
        });
    }
    
    // Toggle folder expansion
    function toggleFolder(folderId) {
        const children = container.querySelector(`.folder-tree-children[data-parent-id="${folderId}"]`);
        const chevron = container.querySelector(`.folder-tree-chevron[data-folder-id="${folderId}"]`);
        
        if (!children) return;
        
        const isExpanded = expandedIds.has(folderId);
        
        if (isExpanded) {
            expandedIds.delete(folderId);
            children.style.display = 'none';
            if (chevron) chevron.style.transform = 'rotate(0deg)';
            
            // Collapse all descendants
            collapseDescendants(folderId);
        } else {
            expandedIds.add(folderId);
            children.style.display = 'block';
            if (chevron) chevron.style.transform = 'rotate(90deg)';
        }
        
        if (opts.onToggle) opts.onToggle(folderId, !isExpanded);
    }
    
    // Collapse all descendants
    function collapseDescendants(parentId) {
        const childContainers = container.querySelectorAll(`.folder-tree-children[data-parent-id="${parentId}"] .folder-tree-children`);
        childContainers.forEach(child => {
            child.style.display = 'none';
            const childId = parseInt(child.dataset.parentId);
            expandedIds.delete(childId);
            const chevron = container.querySelector(`.folder-tree-chevron[data-folder-id="${childId}"]`);
            if (chevron) chevron.style.transform = 'rotate(0deg)';
        });
    }
    
    // Initial render
    render();
    
    // Return controller
    return {
        refresh: () => render(),
        getSelected: () => selectedId,
        setSelected: (id) => {
            selectedId = id;
            container.querySelectorAll('.folder-tree-row').forEach(row => {
                const item = row.closest('.folder-tree-item');
                row.classList.toggle('selected', parseInt(item.dataset[opts.itemDataAttr]) === id);
            });
        },
        expand: (folderId) => {
            if (!expandedIds.has(folderId)) toggleFolder(folderId);
        },
        collapse: (folderId) => {
            if (expandedIds.has(folderId)) toggleFolder(folderId);
        },
        isExpanded: (folderId) => expandedIds.has(folderId)
    };
}

/**
 * Get folder icon name based on folder name.
 */
export function getFolderIcon(name) {
    const upper = (name || '').toUpperCase();
    if (upper === 'INBOX') return 'inbox';
    if (upper.includes('SENT')) return 'send';
    if (upper.includes('DRAFT')) return 'file-edit';
    if (upper.includes('SPAM') || upper.includes('JUNK')) return 'alert-triangle';
    if (upper.includes('TRASH') || upper.includes('DELETED')) return 'trash-2';
    if (upper.includes('ARCHIVE')) return 'archive';
    return 'folder';
}
