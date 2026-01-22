/**
 * MailRepo - Reusable Folder Tree Component
 * 
 * Renders hierarchical folder trees with configurable behavior:
 * - Sidebar archive folders (selectable, expandable)
 * - Folder selection view (checkboxes for bulk staging)
 * - Destination folder modal (selectable for staging target)
 */

import { escapeHtml } from './utils.js';
import { state } from './state.js';

/**
 * Configuration options for folder tree rendering.
 * @typedef {Object} FolderTreeConfig
 * @property {boolean} checkboxes - Show checkboxes for multi-select
 * @property {boolean} selectable - Allow single-selection (click to select)
 * @property {boolean} expandable - Show expand/collapse chevrons
 * @property {boolean} startExpanded - Start with children expanded
 * @property {boolean} showNewFolder - Show "New Folder" option at top
 * @property {Function} onSelect - Callback when folder is selected (id)
 * @property {Function} onCheck - Callback when checkbox changes (id, checked)
 * @property {Function} filter - Filter function for folders
 * @property {string} itemClass - Additional CSS class for items
 */

const defaultConfig = {
    checkboxes: false,
    selectable: true,
    expandable: true,
    startExpanded: false,
    showNewFolder: false,
    onSelect: null,
    onCheck: null,
    filter: (f) => !f.deleted_at,
    itemClass: '',
};

/**
 * Render a folder tree into a container element.
 * @param {HTMLElement} container - Container element to render into
 * @param {Object} config - Configuration options
 * @returns {Object} Controller with methods to interact with the tree
 */
export function renderFolderTree(container, config = {}) {
    const cfg = { ...defaultConfig, ...config };
    
    // Get and filter folders
    const visibleFolders = state.folders.filter(cfg.filter);
    const topLevel = visibleFolders.filter(f => !f.parent_id);
    
    // Sort alphabetically
    topLevel.sort((a, b) => a.name.localeCompare(b.name));
    
    // Track state
    let selectedId = null;
    const checkedIds = new Set();
    
    // Build HTML
    let html = '';
    
    if (cfg.showNewFolder) {
        html += `
            <div class="folder-tree-item folder-tree-new" data-action="new">
                <div class="folder-tree-row">
                    <span class="folder-tree-spacer"></span>
                    <i data-lucide="plus"></i>
                    <span class="folder-tree-label">New Folder</span>
                </div>
            </div>
        `;
    }
    
    topLevel.forEach(folder => {
        html += renderTreeItem(folder, visibleFolders, 0, cfg);
    });
    
    container.innerHTML = html;
    
    // Render Lucide icons
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    // Attach event listeners
    attachTreeListeners(container, cfg, { selectedId, checkedIds });
    
    // Return controller
    return {
        getSelected: () => selectedId,
        getChecked: () => Array.from(checkedIds),
        setSelected: (id) => {
            selectedId = id;
            container.querySelectorAll('.folder-tree-row').forEach(row => {
                row.classList.toggle('selected', row.closest('.folder-tree-item')?.dataset.id === String(id));
            });
        },
        refresh: () => renderFolderTree(container, config),
    };
}

/**
 * Render a single tree item with children.
 */
function renderTreeItem(folder, allFolders, depth, cfg) {
    const children = allFolders.filter(f => f.parent_id == folder.id);
    const hasChildren = children.length > 0;
    const indent = depth * 20;
    
    // Sort children
    children.sort((a, b) => a.name.localeCompare(b.name));
    
    const colorDot = folder.color ? 
        `<span class="folder-tree-color" style="background: ${folder.color}"></span>` : '';
    
    let html = `<div class="folder-tree-item ${cfg.itemClass}" data-id="${folder.id}">`;
    html += `<div class="folder-tree-row" style="padding-left: ${12 + indent}px">`;
    
    // Chevron or spacer
    if (cfg.expandable && hasChildren) {
        const rotated = cfg.startExpanded ? 'style="transform: rotate(90deg)"' : '';
        html += `<i data-lucide="chevron-right" class="folder-tree-chevron" ${rotated}></i>`;
    } else {
        html += `<span class="folder-tree-spacer"></span>`;
    }
    
    // Checkbox (if enabled)
    if (cfg.checkboxes) {
        html += `<label class="folder-tree-checkbox"><input type="checkbox" data-id="${folder.id}"></label>`;
    }
    
    // Color dot, icon, label
    html += colorDot;
    html += `<i data-lucide="folder" class="folder-tree-icon"></i>`;
    html += `<span class="folder-tree-label">${escapeHtml(folder.name)}</span>`;
    
    html += `</div>`;
    
    // Children container
    if (hasChildren) {
        const display = cfg.startExpanded ? 'block' : 'none';
        html += `<div class="folder-tree-children" style="display: ${display}">`;
        children.forEach(child => {
            html += renderTreeItem(child, allFolders, depth + 1, cfg);
        });
        html += `</div>`;
    }
    
    html += `</div>`;
    return html;
}

/**
 * Attach event listeners to tree items.
 */
function attachTreeListeners(container, cfg, trackingState) {
    // Handle row clicks
    container.querySelectorAll('.folder-tree-row').forEach(row => {
        row.addEventListener('click', (e) => {
            const item = row.closest('.folder-tree-item');
            
            // Handle "New Folder" action
            if (item?.dataset.action === 'new') {
                if (cfg.onNewFolder) cfg.onNewFolder();
                return;
            }
            
            // Handle chevron click (expand/collapse only)
            if (e.target.closest('.folder-tree-chevron')) {
                e.stopPropagation();
                toggleExpand(row);
                return;
            }
            
            // Handle checkbox click
            if (e.target.closest('.folder-tree-checkbox')) {
                return; // Let the checkbox handler deal with it
            }
            
            // Handle selection
            if (cfg.selectable && item?.dataset.id) {
                const id = item.dataset.id;
                trackingState.selectedId = id;
                
                container.querySelectorAll('.folder-tree-row').forEach(r => {
                    r.classList.remove('selected');
                });
                row.classList.add('selected');
                
                if (cfg.onSelect) cfg.onSelect(id);
            }
        });
    });
    
    // Handle checkbox changes
    if (cfg.checkboxes) {
        container.querySelectorAll('.folder-tree-checkbox input').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const id = checkbox.dataset.id;
                const checked = checkbox.checked;
                
                if (checked) {
                    trackingState.checkedIds.add(id);
                } else {
                    trackingState.checkedIds.delete(id);
                }
                
                // Cascade to children
                const item = checkbox.closest('.folder-tree-item');
                const childCheckboxes = item.querySelectorAll('.folder-tree-children input[type="checkbox"]');
                childCheckboxes.forEach(child => {
                    child.checked = checked;
                    if (checked) {
                        trackingState.checkedIds.add(child.dataset.id);
                    } else {
                        trackingState.checkedIds.delete(child.dataset.id);
                    }
                });
                
                if (cfg.onCheck) cfg.onCheck(id, checked, trackingState.checkedIds);
            });
        });
    }
}

/**
 * Toggle expand/collapse of a tree item.
 */
function toggleExpand(row) {
    const chevron = row.querySelector('.folder-tree-chevron');
    const item = row.closest('.folder-tree-item');
    const children = item?.querySelector('.folder-tree-children');
    
    if (!children) return;
    
    const isExpanded = children.style.display !== 'none';
    children.style.display = isExpanded ? 'none' : 'block';
    
    if (chevron) {
        chevron.style.transform = isExpanded ? 'rotate(0deg)' : 'rotate(90deg)';
    }
}

/**
 * Get folder icon based on name.
 * @param {string} name - Folder name
 * @returns {string} Lucide icon name
 */
export function getFolderIcon(name) {
    const upper = name.toUpperCase();
    if (upper === 'INBOX') return 'inbox';
    if (upper.includes('SENT')) return 'send';
    if (upper.includes('DRAFT')) return 'file-edit';
    if (upper.includes('SPAM') || upper.includes('JUNK')) return 'alert-triangle';
    if (upper.includes('TRASH') || upper.includes('DELETED')) return 'trash-2';
    if (upper.includes('ARCHIVE')) return 'archive';
    if (upper.includes('STAR') || upper.includes('FLAG')) return 'star';
    return 'folder';
}
