/**
 * MailRepo - Context Menu Component
 * 
 * Right-click menu for folder actions in the sidebar.
 */

import { escapeHtml } from '../utils.js';

let menuElement = null;
let currentFolderId = null;

/**
 * Initialize the context menu (create DOM element).
 */
export function initContextMenu() {
    if (menuElement) return;
    
    menuElement = document.createElement('div');
    menuElement.className = 'context-menu';
    menuElement.id = 'folderContextMenu';
    document.body.appendChild(menuElement);
    
    // Close on click outside
    document.addEventListener('click', hideContextMenu);
    document.addEventListener('contextmenu', (e) => {
        // Hide if right-clicking elsewhere
        if (!e.target.closest('.tree-item-row[data-folder-id]')) {
            hideContextMenu();
        }
    });
    
    // Close on scroll
    document.addEventListener('scroll', hideContextMenu, true);
    
    // Close on escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') hideContextMenu();
    });
}

/**
 * Show context menu for a folder.
 * @param {Event} e - The contextmenu event
 * @param {number} folderId - The folder ID
 * @param {Object} folder - The folder object from state
 */
export function showFolderContextMenu(e, folderId, folder) {
    e.preventDefault();
    e.stopPropagation();
    
    if (!menuElement) initContextMenu();
    
    currentFolderId = folderId;
    
    // Build menu items
    const items = [
        { icon: 'folder-plus', label: 'New Subfolder', action: 'subfolder' },
        { icon: 'pencil', label: 'Rename', action: 'rename' },
        { icon: 'palette', label: 'Change Color', action: 'color' },
        { icon: 'folder-output', label: 'Move', action: 'move' },
        { divider: true },
        { icon: 'archive', label: 'Move to Retention Vault', action: 'vault' },
        { icon: 'download', label: 'Export as ZIP', action: 'export' },
        { divider: true },
        { icon: 'trash-2', label: 'Delete', action: 'delete', danger: true },
    ];
    
    let html = '';
    for (const item of items) {
        if (item.divider) {
            html += '<div class="context-menu-divider"></div>';
        } else {
            html += `
                <div class="context-menu-item${item.danger ? ' danger' : ''}" data-action="${item.action}">
                    <i data-lucide="${item.icon}"></i>
                    <span>${item.label}</span>
                </div>
            `;
        }
    }
    
    menuElement.innerHTML = html;
    
    // Add click handlers
    menuElement.querySelectorAll('.context-menu-item').forEach(el => {
        el.addEventListener('click', () => {
            const action = el.dataset.action;
            hideContextMenu();
            handleAction(action, folderId, folder);
        });
    });
    
    // Render icons
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    // Position menu with edge detection
    positionMenu(e.clientX, e.clientY);
    
    // Show menu
    menuElement.classList.add('visible');
}

/**
 * Position the context menu with edge detection.
 */
function positionMenu(x, y) {
    // Get menu dimensions (need to make visible briefly to measure)
    menuElement.style.left = '-9999px';
    menuElement.style.top = '-9999px';
    menuElement.classList.add('visible');
    
    const menuRect = menuElement.getBoundingClientRect();
    const menuWidth = menuRect.width;
    const menuHeight = menuRect.height;
    
    menuElement.classList.remove('visible');
    
    // Viewport dimensions
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const padding = 8;
    
    // Adjust X if menu would overflow right edge
    if (x + menuWidth + padding > viewportWidth) {
        x = viewportWidth - menuWidth - padding;
    }
    
    // Adjust Y if menu would overflow bottom edge
    if (y + menuHeight + padding > viewportHeight) {
        y = viewportHeight - menuHeight - padding;
    }
    
    // Ensure not off left or top edge
    x = Math.max(padding, x);
    y = Math.max(padding, y);
    
    menuElement.style.left = x + 'px';
    menuElement.style.top = y + 'px';
}

/**
 * Hide the context menu.
 */
export function hideContextMenu() {
    if (menuElement) {
        menuElement.classList.remove('visible');
    }
    currentFolderId = null;
}

/**
 * Handle a context menu action.
 */
async function handleAction(action, folderId, folder) {
    switch (action) {
        case 'subfolder':
            if (typeof window.createSubfolder === 'function') {
                window.createSubfolder(folderId);
            } else {
                const { createSubfolder } = await import('../views/folder-mgmt.js');
                createSubfolder(folderId);
            }
            break;
            
        case 'rename':
            if (typeof window.renameFolder === 'function') {
                window.renameFolder(folderId);
            } else {
                // Import and call if not on window
                const { renameFolder } = await import('../views/folder-mgmt.js');
                renameFolder(folderId);
            }
            break;
            
        case 'color':
            if (typeof window.showColorPickerForFolder === 'function') {
                window.showColorPickerForFolder(folderId);
            } else {
                const { showColorPickerForFolder } = await import('../views/folder-mgmt.js');
                showColorPickerForFolder(folderId);
            }
            break;
            
        case 'move':
            if (typeof window.openMoveFolder === 'function') {
                window.openMoveFolder(folderId);
            } else {
                const { openMoveFolder } = await import('../views/folder-mgmt.js');
                openMoveFolder(folderId);
            }
            break;
            
        case 'vault':
            if (typeof window.openMoveToVault === 'function') {
                window.openMoveToVault(folderId);
            } else {
                // Function might not be exported, show error
                console.error('openMoveToVault not available');
            }
            break;
            
        case 'export':
            if (typeof window.exportFolder === 'function') {
                window.exportFolder(folderId);
            } else {
                const { exportFolder } = await import('../views/folder-mgmt.js');
                exportFolder(folderId);
            }
            break;
            
        case 'delete':
            if (typeof window.deleteFolder === 'function') {
                window.deleteFolder(folderId);
            } else {
                const { deleteFolder } = await import('../views/folder-mgmt.js');
                deleteFolder(folderId);
            }
            break;
    }
}


/**
 * Show context menu for the Archive section header.
 * @param {Event} e - The contextmenu event
 */
export function showArchiveHeaderContextMenu(e) {
    e.preventDefault();
    e.stopPropagation();
    
    if (!menuElement) initContextMenu();
    
    currentFolderId = null;
    
    const items = [
        { icon: 'folder-plus', label: 'New Folder', action: 'newfolder' },
    ];
    
    let html = '';
    for (const item of items) {
        html += `
            <div class="context-menu-item" data-action="${item.action}">
                <i data-lucide="${item.icon}"></i>
                <span>${item.label}</span>
            </div>
        `;
    }
    
    menuElement.innerHTML = html;
    
    // Add click handlers
    menuElement.querySelectorAll('.context-menu-item').forEach(el => {
        el.addEventListener('click', async () => {
            const action = el.dataset.action;
            hideContextMenu();
            if (action === 'newfolder') {
                if (typeof window.createSubfolder === 'function') {
                    window.createSubfolder(null);
                } else {
                    const { createSubfolder } = await import('../views/folder-mgmt.js');
                    createSubfolder(null);
                }
            }
        });
    });
    
    // Render icons
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    // Position menu with edge detection
    positionMenu(e.clientX, e.clientY);
    
    // Show menu
    menuElement.classList.add('visible');
}
