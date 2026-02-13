/**
 * MailRepo - Folder Selection View
 * 
 * Handles bulk IMAP/Import folder staging:
 * - Folder selection view for IMAP accounts
 * - Folder selection view for imports
 * - Bulk staging operations
 */

import { escapeHtml, escapeForOnclick } from '../utils.js';
import { state, setSelectedFoldersGetter, setSelectedFoldersClearer, updateStagedBadge } from '../state.js';
import { showAlert } from '../modals.js';
import { buildImapFolderTree, getFolderIcon } from '../components/sidebar.js';
import { getMountedImports } from '../components/imports.js';

// Module state
let selectedFoldersForStaging = new Set();
let currentFolderSelectionAccountId = null;
let currentFolderSelectionImportId = null;
let folderSelectionTree = [];
let pendingFolderStaging = null;
let folderFilter = '';

// DOM references
let contextTitle = null;
let contextMeta = null;
let emailList = null;

/**
 * Initialize folder selection view.
 */
export function initFolderSelection(config) {
    contextTitle = config.contextTitle;
    contextMeta = config.contextMeta;
    emailList = config.emailList;
    
    // Register getter and clearer for selected folders (for navigation guard)
    setSelectedFoldersGetter(() => selectedFoldersForStaging.size);
    setSelectedFoldersClearer(() => selectedFoldersForStaging.clear());
}

/**
 * Clear folder filter (called when switching views).
 */
export function clearFolderFilter() {
    folderFilter = '';
}

/**
 * Count total folders in tree (recursive).
 */
function countFolders(nodes) {
    let count = 0;
    for (const node of nodes) {
        count++;
        if (node.children && node.children.length > 0) {
            count += countFolders(node.children);
        }
    }
    return count;
}

/**
 * Filter folder tree by name.
 */
function filterFolderTree(nodes, query) {
    if (!query) return nodes;
    const lowerQuery = query.toLowerCase();
    
    function filterNodes(nodes) {
        const result = [];
        for (const node of nodes) {
            const nameMatches = node.name.toLowerCase().includes(lowerQuery);
            const filteredChildren = node.children ? filterNodes(node.children) : [];
            
            if (nameMatches || filteredChildren.length > 0) {
                result.push({
                    ...node,
                    children: filteredChildren
                });
            }
        }
        return result;
    }
    
    return filterNodes(nodes);
}

/**
 * Show folder selection view for bulk IMAP folder staging.
 */
export async function showFolderSelectionView(accountId) {
    currentFolderSelectionAccountId = accountId;
    selectedFoldersForStaging.clear();
    folderFilter = '';
    
    // Track this view so it can be restored
    state.currentView = { type: 'accountFolders', id: accountId };
    
    const accountRow = document.querySelector(`.tree-item-row[data-type="account"][data-id="${accountId}"]`);
    const accountName = accountRow?.querySelector('.tree-label')?.textContent || 'Account';
    
    if (contextTitle) contextTitle.textContent = accountName;
    if (contextMeta) contextMeta.textContent = 'Select folders to archive';
    
    const toolbar = document.querySelector('.content-toolbar');
    if (toolbar) toolbar.style.display = 'none';
    
    const subfoldersBar = document.getElementById('subfoldersBar');
    if (subfoldersBar) subfoldersBar.style.display = 'none';
    
    const headerActions = document.querySelector('.header-actions');
    if (headerActions) {
        headerActions.innerHTML = '';
    }
    
    emailList.innerHTML = '<div class="loading-indicator">Loading folders...</div>';
    
    try {
        const response = await fetch(`/api/accounts/${accountId}/folders`);
        if (!response.ok) {
            const data = await response.json();
            emailList.innerHTML = `<div class="empty-state"><p>Error: ${data.error || 'Failed to load folders'}</p></div>`;
            return;
        }
        
        const data = await response.json();
        folderSelectionTree = buildImapFolderTree(data.folders || []);
        renderFolderSelectionView(folderSelectionTree, accountId);
    } catch (error) {
        console.error('Error loading folders:', error);
        emailList.innerHTML = '<div class="empty-state"><p>Error loading folders</p></div>';
    }
}

/**
 * Show folder selection view for bulk import folder staging.
 */
export function showImportFolderSelectionView(importId) {
    currentFolderSelectionImportId = importId;
    currentFolderSelectionAccountId = null;
    selectedFoldersForStaging.clear();
    folderFilter = '';
    
    state.currentView = { type: 'importFolders', id: importId };
    
    const imports = getMountedImports();
    const imp = imports.find(i => i.id === importId);
    
    if (!imp) {
        emailList.innerHTML = '<div class="empty-state"><p>Import not found</p></div>';
        return;
    }
    
    if (contextTitle) contextTitle.textContent = imp.name;
    if (contextMeta) contextMeta.textContent = 'Select folders to archive';
    
    const toolbar = document.querySelector('.content-toolbar');
    if (toolbar) toolbar.style.display = 'none';
    
    const subfoldersBar = document.getElementById('subfoldersBar');
    if (subfoldersBar) subfoldersBar.style.display = 'none';
    
    const headerActions = document.querySelector('.header-actions');
    if (headerActions) {
        headerActions.innerHTML = '';
    }
    
    // Build folder tree for import
    if (imp.type === 'eml') {
        folderSelectionTree = [{ name: imp.name, fullPath: '', children: [], emailCount: imp.emails.length }];
    } else if (imp.folders && imp.folders.length > 0) {
        folderSelectionTree = imp.folders;
    } else {
        folderSelectionTree = [{ name: imp.name, fullPath: '', children: [], emailCount: imp.emails.length }];
    }
    
    renderImportFolderSelectionView(folderSelectionTree, importId);
}

function renderImportFolderSelectionView(tree, importId) {
    const selectedCount = selectedFoldersForStaging.size;
    const filteredTree = filterFolderTree(tree, folderFilter);
    const totalCount = countFolders(tree);
    const filteredCount = countFolders(filteredTree);
    
    // Update context meta
    if (contextMeta) {
        if (folderFilter && filteredCount !== totalCount) {
            contextMeta.textContent = `${filteredCount} of ${totalCount} folders`;
        } else {
            contextMeta.textContent = `${totalCount} folders to archive`;
        }
    }
    
    let html = `
        <div class="folder-management-list">
            <div class="folder-selection-toolbar">
                <div class="folder-filter">
                    <i data-lucide="search" class="search-icon"></i>
                    <input type="text" 
                           id="folderFilterInput" 
                           placeholder="Filter folders..." 
                           value="${escapeHtml(folderFilter)}"
                           oninput="handleFolderFilter(this.value)">
                    ${folderFilter ? '<button class="search-clear" onclick="clearFolderFilterInput()"><i data-lucide="x"></i></button>' : ''}
                </div>
                <div class="toolbar-actions">
                    <button class="btn btn-secondary" onclick="selectAllFolders()">
                        <i data-lucide="check-square"></i>
                        Select All
                    </button>
                    <button class="btn btn-secondary" onclick="clearAllSelected()" ${selectedCount === 0 ? 'disabled' : ''}>
                        <i data-lucide="x"></i>
                        Clear
                    </button>
                    <button class="btn btn-primary" id="stageSelectedBtn" onclick="stageSelectedFoldersFromSelection()" ${selectedCount === 0 ? 'disabled' : ''}>
                        <i data-lucide="archive"></i>
                        Stage${selectedCount > 0 ? ` (${selectedCount})` : ''}
                    </button>
                </div>
            </div>
            <div class="folder-management-header folder-selection-header">
                <span>Folder</span>
                <span>Actions</span>
            </div>
    `;
    
    if (filteredCount === 0 && folderFilter) {
        html += `
            <div class="empty-state" style="padding: var(--space-xl);">
                <p>No folders match "${escapeHtml(folderFilter)}"</p>
            </div>
        `;
    } else {
        html += renderImportFolderSelectionTree(filteredTree, importId, 0, []);
    }
    
    html += `</div>`;
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderImportFolderSelectionTree(nodes, importId, depth, ancestry = []) {
    let html = '';
    
    nodes.forEach((node, index) => {
        const hasChildren = node.children && node.children.length > 0;
        const folderPath = node.fullPath;
        const isLast = index === nodes.length - 1;
        
        const isStaged = state.stagedFolders.some(
            sf => sf.sourceType === 'import' && sf.importId == importId && sf.folder === folderPath
        );
        const isSelected = selectedFoldersForStaging.has(folderPath);
        
        let rowClass = 'folder-management-item folder-selection-item';
        if (isStaged) rowClass += ' staged';
        if (isSelected) rowClass += ' selected';
        if (node.noselect) rowClass += ' noselect';
        
        const escapedPath = escapeForOnclick(folderPath);
        let actionsHtml = '';
        
        if (node.noselect) {
            // Non-selectable container folders (e.g. [Gmail]) get no actions
            actionsHtml = '';
        } else if (isStaged) {
            actionsHtml = `
                <button class="btn btn-sm btn-icon" disabled title="Already staged">
                    <i data-lucide="circle"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="clearFolder('${escapedPath}')" title="Unstage">
                    <i data-lucide="x"></i>
                </button>
            `;
        } else if (isSelected) {
            actionsHtml = `
                <button class="btn btn-sm btn-icon btn-selected" disabled title="Selected">
                    <i data-lucide="check"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="clearFolder('${escapedPath}')" title="Deselect">
                    <i data-lucide="x"></i>
                </button>
            `;
        } else {
            actionsHtml = `
                <button class="btn btn-sm btn-icon" onclick="selectFolder('${escapedPath}')" title="Select">
                    <i data-lucide="circle"></i>
                </button>
                <button class="btn btn-sm btn-icon" disabled title="Not selected">
                    <i data-lucide="x"></i>
                </button>
            `;
        }
        
        // Build tree lines
        let treePrefix = '';
        if (depth > 0) {
            for (let i = 0; i < ancestry.length; i++) {
                treePrefix += ancestry[i] 
                    ? '<span class="tree-spacer"></span>' 
                    : '<span class="tree-line-vertical"></span>';
            }
            treePrefix += isLast 
                ? '<span class="tree-line-last"></span>' 
                : '<span class="tree-line-branch"></span>';
        }
        
        html += `
            <div class="${rowClass}" data-folder="${escapeHtml(folderPath)}">
                <div class="folder-management-name">
                    ${treePrefix}
                    <i data-lucide="${getFolderIcon(node.name)}" class="folder-icon"></i>
                    <span class="folder-label">${escapeHtml(node.name)}</span>
                </div>
                <div class="folder-management-actions">
                    ${actionsHtml}
                </div>
            </div>
        `;
        
        if (hasChildren) {
            html += renderImportFolderSelectionTree(node.children, importId, depth + 1, [...ancestry, isLast]);
        }
    });
    
    return html;
}

function renderFolderSelectionView(tree, accountId) {
    const selectedCount = selectedFoldersForStaging.size;
    const filteredTree = filterFolderTree(tree, folderFilter);
    const totalCount = countFolders(tree);
    const filteredCount = countFolders(filteredTree);
    
    // Update context meta
    if (contextMeta) {
        if (folderFilter && filteredCount !== totalCount) {
            contextMeta.textContent = `${filteredCount} of ${totalCount} folders`;
        } else {
            contextMeta.textContent = `${totalCount} folders to archive`;
        }
    }
    
    let html = `
        <div class="folder-management-list">
            <div class="folder-selection-toolbar">
                <div class="folder-filter">
                    <i data-lucide="search" class="search-icon"></i>
                    <input type="text" 
                           id="folderFilterInput" 
                           placeholder="Filter folders..." 
                           value="${escapeHtml(folderFilter)}"
                           oninput="handleFolderFilter(this.value)">
                    ${folderFilter ? '<button class="search-clear" onclick="clearFolderFilterInput()"><i data-lucide="x"></i></button>' : ''}
                </div>
                <div class="toolbar-actions">
                    <button class="btn btn-secondary" onclick="selectAllFolders()">
                        <i data-lucide="check-square"></i>
                        Select All
                    </button>
                    <button class="btn btn-secondary" onclick="clearAllSelected()" ${selectedCount === 0 ? 'disabled' : ''}>
                        <i data-lucide="x"></i>
                        Clear
                    </button>
                    <button class="btn btn-primary" id="stageSelectedBtn" onclick="stageSelectedFoldersFromSelection()" ${selectedCount === 0 ? 'disabled' : ''}>
                        <i data-lucide="archive"></i>
                        Stage${selectedCount > 0 ? ` (${selectedCount})` : ''}
                    </button>
                </div>
            </div>
            <div class="folder-management-header folder-selection-header">
                <span>Folder</span>
                <span>Actions</span>
            </div>
    `;
    
    if (filteredCount === 0 && folderFilter) {
        html += `
            <div class="empty-state" style="padding: var(--space-xl);">
                <p>No folders match "${escapeHtml(folderFilter)}"</p>
            </div>
        `;
    } else {
        html += renderFolderSelectionTree(filteredTree, accountId, 0, []);
    }
    
    html += `</div>`;
    
    emailList.innerHTML = html;
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function renderFolderSelectionTree(nodes, accountId, depth, ancestry = []) {
    let html = '';
    
    nodes.forEach((node, index) => {
        const hasChildren = node.children && node.children.length > 0;
        const folderPath = node.fullPath;
        const isLast = index === nodes.length - 1;
        
        const isStaged = state.stagedFolders.some(
            sf => sf.sourceType === 'account' && sf.accountId == accountId && sf.folder === folderPath
        );
        const isSelected = selectedFoldersForStaging.has(folderPath);
        
        let rowClass = 'folder-management-item folder-selection-item';
        if (isStaged) rowClass += ' staged';
        if (isSelected) rowClass += ' selected';
        if (node.noselect) rowClass += ' noselect';
        
        let actionsHtml = '';
        const escapedPath = escapeForOnclick(folderPath);
        
        if (node.noselect) {
            // Non-selectable container folders (e.g. [Gmail]) get no actions
            actionsHtml = '';
        } else if (isStaged) {
            actionsHtml = `
                <button class="btn btn-sm btn-icon" disabled title="Already staged">
                    <i data-lucide="circle"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="clearFolder('${escapedPath}')" title="Unstage">
                    <i data-lucide="x"></i>
                </button>
            `;
        } else if (isSelected) {
            actionsHtml = `
                <button class="btn btn-sm btn-icon btn-selected" disabled title="Selected">
                    <i data-lucide="check"></i>
                </button>
                <button class="btn btn-sm btn-icon" onclick="clearFolder('${escapedPath}')" title="Deselect">
                    <i data-lucide="x"></i>
                </button>
            `;
        } else {
            actionsHtml = `
                <button class="btn btn-sm btn-icon" onclick="selectFolder('${escapedPath}')" title="Select">
                    <i data-lucide="circle"></i>
                </button>
                <button class="btn btn-sm btn-icon" disabled title="Not selected">
                    <i data-lucide="x"></i>
                </button>
            `;
        }
        
        // Build tree lines
        let treePrefix = '';
        if (depth > 0) {
            for (let i = 0; i < ancestry.length; i++) {
                treePrefix += ancestry[i] 
                    ? '<span class="tree-spacer"></span>' 
                    : '<span class="tree-line-vertical"></span>';
            }
            treePrefix += isLast 
                ? '<span class="tree-line-last"></span>' 
                : '<span class="tree-line-branch"></span>';
        }
        
        html += `
            <div class="${rowClass}" data-folder="${escapeHtml(folderPath)}">
                <div class="folder-management-name">
                    ${treePrefix}
                    <i data-lucide="${getFolderIcon(node.name)}" class="folder-icon"></i>
                    <span class="folder-label">${escapeHtml(node.name)}</span>
                </div>
                <div class="folder-management-actions">
                    ${actionsHtml}
                </div>
            </div>
        `;
        
        if (hasChildren) {
            html += renderFolderSelectionTree(node.children, accountId, depth + 1, [...ancestry, isLast]);
        }
    });
    
    return html;
}

/**
 * Refresh the current folder selection view.
 */
export function refreshFolderSelectionView() {
    const scrollTop = emailList?.scrollTop || 0;
    
    if (currentFolderSelectionAccountId && folderSelectionTree) {
        renderFolderSelectionView(folderSelectionTree, currentFolderSelectionAccountId);
    } else if (currentFolderSelectionImportId && folderSelectionTree) {
        renderImportFolderSelectionView(folderSelectionTree, currentFolderSelectionImportId);
    }
    
    requestAnimationFrame(() => {
        if (emailList) emailList.scrollTop = scrollTop;
    });
}

/**
 * Find all descendant folder paths from a tree by traversing the tree structure.
 */
function findAllDescendants(tree, folderPath) {
    let descendants = [];
    
    function findNodeAndCollectChildren(nodes) {
        for (const node of nodes) {
            if (node.fullPath === folderPath) {
                // Found the target node - collect all its children recursively
                collectChildren(node.children || []);
                return true;
            }
            if (node.children && node.children.length > 0) {
                if (findNodeAndCollectChildren(node.children)) return true;
            }
        }
        return false;
    }
    
    function collectChildren(nodes) {
        for (const node of nodes) {
            if (node.fullPath && !node.noselect) {
                descendants.push(node.fullPath);
            }
            if (node.children && node.children.length > 0) {
                collectChildren(node.children);
            }
        }
    }
    
    findNodeAndCollectChildren(tree);
    return descendants;
}

/**
 * Collect all selectable folder paths from a tree structure.
 */
function collectAllFolderPaths(nodes, paths = []) {
    nodes.forEach(node => {
        if (!node.noselect) {
            paths.push(node.fullPath);
        }
        if (node.children && node.children.length > 0) {
            collectAllFolderPaths(node.children, paths);
        }
    });
    return paths;
}

/**
 * Select a folder and all its children.
 */
export function selectFolder(folderPath) {
    selectedFoldersForStaging.add(folderPath);
    
    const descendants = findAllDescendants(folderSelectionTree, folderPath);
    descendants.forEach(path => selectedFoldersForStaging.add(path));
    
    refreshFolderSelectionView();
}
window.selectFolder = selectFolder;

/**
 * Clear a folder - deselects if selected, unstages if staged.
 */
export function clearFolder(folderPath) {
    const descendants = findAllDescendants(folderSelectionTree, folderPath);
    const allPathsToClear = [folderPath, ...descendants];
    
    let clearedSelected = false;
    allPathsToClear.forEach(path => {
        if (selectedFoldersForStaging.has(path)) {
            selectedFoldersForStaging.delete(path);
            clearedSelected = true;
        }
    });
    
    if (clearedSelected) {
        refreshFolderSelectionView();
        return;
    }
    
    let clearedStaged = false;
    allPathsToClear.forEach(path => {
        const index = state.stagedFolders.findIndex(sf => {
            if (currentFolderSelectionAccountId) {
                return sf.sourceType === 'account' && sf.accountId == currentFolderSelectionAccountId && sf.folder === path;
            } else if (currentFolderSelectionImportId) {
                return sf.sourceType === 'import' && sf.importId == currentFolderSelectionImportId && sf.folder === path;
            }
            return false;
        });
        
        if (index !== -1) {
            state.stagedFolders.splice(index, 1);
            clearedStaged = true;
        }
    });
    
    if (clearedStaged) {
        sessionStorage.setItem('stagedFolders', JSON.stringify(state.stagedFolders));
        updateStagedBadge();
        refreshFolderSelectionView();
    }
}
window.clearFolder = clearFolder;

/**
 * Select all unstaged folders.
 */
export function selectAllFolders() {
    const allFolderPaths = collectAllFolderPaths(folderSelectionTree);
    
    allFolderPaths.forEach(path => {
        const isStaged = state.stagedFolders.some(sf => {
            if (currentFolderSelectionAccountId) {
                return sf.sourceType === 'account' && sf.accountId == currentFolderSelectionAccountId && sf.folder === path;
            } else if (currentFolderSelectionImportId) {
                return sf.sourceType === 'import' && sf.importId == currentFolderSelectionImportId && sf.folder === path;
            }
            return false;
        });
        
        if (!isStaged) {
            selectedFoldersForStaging.add(path);
        }
    });
    
    refreshFolderSelectionView();
}
window.selectAllFolders = selectAllFolders;

/**
 * Clear all selected folders.
 */
export function clearAllSelected() {
    selectedFoldersForStaging.clear();
    refreshFolderSelectionView();
}
window.clearAllSelected = clearAllSelected;

/**
 * Stage all currently selected folders.
 */
export function stageSelectedFoldersFromSelection() {
    if (selectedFoldersForStaging.size === 0) return;
    
    const folderPaths = Array.from(selectedFoldersForStaging);
    
    if (currentFolderSelectionAccountId) {
        pendingFolderStaging = {
            sourceType: 'account',
            accountId: currentFolderSelectionAccountId,
            folders: folderPaths
        };
    } else if (currentFolderSelectionImportId) {
        const imports = getMountedImports();
        const imp = imports.find(i => i.id === currentFolderSelectionImportId);
        
        pendingFolderStaging = {
            sourceType: 'import',
            importId: currentFolderSelectionImportId,
            importPath: imp?.path || '',
            importType: imp?.type || 'mbox',
            folders: folderPaths
        };
    } else {
        console.error('No account or import selected for folder staging');
        return;
    }
    
    // Don't clear selectedFoldersForStaging here - wait until confirm
    // so user can cancel and try again
    openStageFoldersModal();
}
window.stageSelectedFoldersFromSelection = stageSelectedFoldersFromSelection;

/**
 * Stage a single folder.
 */
export function stageSingleFolder(folderPath) {
    if (currentFolderSelectionAccountId) {
        pendingFolderStaging = {
            sourceType: 'account',
            accountId: currentFolderSelectionAccountId,
            folders: [folderPath]
        };
    } else if (currentFolderSelectionImportId) {
        const imports = getMountedImports();
        const imp = imports.find(i => i.id === currentFolderSelectionImportId);
        
        pendingFolderStaging = {
            sourceType: 'import',
            importId: currentFolderSelectionImportId,
            importPath: imp?.path || '',
            importType: imp?.type || 'mbox',
            folders: [folderPath]
        };
    } else {
        console.error('No account or import selected for folder staging');
        return;
    }
    
    openStageFoldersModal();
}
window.stageSingleFolder = stageSingleFolder;

/**
 * Stage all folders in the current view.
 */
export function stageAllFolders() {
    const allFolderPaths = collectAllFolderPaths(folderSelectionTree);
    
    const unstagedPaths = allFolderPaths.filter(path => {
        if (currentFolderSelectionAccountId) {
            return !state.stagedFolders.some(
                sf => sf.sourceType === 'account' && sf.accountId == currentFolderSelectionAccountId && sf.folder === path
            );
        } else if (currentFolderSelectionImportId) {
            return !state.stagedFolders.some(
                sf => sf.sourceType === 'import' && sf.importId == currentFolderSelectionImportId && sf.folder === path
            );
        }
        return true;
    });
    
    if (unstagedPaths.length === 0) {
        showAlert('All Staged', 'All folders are already staged.');
        return;
    }
    
    if (currentFolderSelectionAccountId) {
        pendingFolderStaging = {
            sourceType: 'account',
            accountId: currentFolderSelectionAccountId,
            folders: unstagedPaths
        };
    } else if (currentFolderSelectionImportId) {
        const imports = getMountedImports();
        const imp = imports.find(i => i.id === currentFolderSelectionImportId);
        
        pendingFolderStaging = {
            sourceType: 'import',
            importId: currentFolderSelectionImportId,
            importPath: imp?.path || '',
            importType: imp?.type || 'mbox',
            folders: unstagedPaths
        };
    }
    
    openStageFoldersModal();
}
window.stageAllFolders = stageAllFolders;

/**
 * Unstage a single folder.
 */
export function unstageSingleFolder(folderPath) {
    const index = state.stagedFolders.findIndex(sf => {
        if (currentFolderSelectionAccountId) {
            return sf.sourceType === 'account' && sf.accountId == currentFolderSelectionAccountId && sf.folder === folderPath;
        } else if (currentFolderSelectionImportId) {
            return sf.sourceType === 'import' && sf.importId == currentFolderSelectionImportId && sf.folder === folderPath;
        }
        return false;
    });
    
    if (index !== -1) {
        state.stagedFolders.splice(index, 1);
        sessionStorage.setItem('stagedFolders', JSON.stringify(state.stagedFolders));
        updateStagedBadge();
        refreshFolderSelectionView();
    }
}
window.unstageSingleFolder = unstageSingleFolder;

export function stageSelectedFolders() {
    if (selectedFoldersForStaging.size === 0) return;
    
    if (currentFolderSelectionAccountId) {
        pendingFolderStaging = {
            sourceType: 'account',
            accountId: currentFolderSelectionAccountId,
            folders: Array.from(selectedFoldersForStaging)
        };
    } else if (currentFolderSelectionImportId) {
        const imports = getMountedImports();
        const imp = imports.find(i => i.id === currentFolderSelectionImportId);
        
        pendingFolderStaging = {
            sourceType: 'import',
            importId: currentFolderSelectionImportId,
            importPath: imp?.path || '',
            importType: imp?.type || 'mbox',
            folders: Array.from(selectedFoldersForStaging)
        };
    } else {
        console.error('No account or import selected for folder staging');
        return;
    }
    
    openStageFoldersModal();
}
window.stageSelectedFolders = stageSelectedFolders;

export function getPendingFolderStaging() {
    return pendingFolderStaging;
}

export function clearPendingFolderStaging() {
    pendingFolderStaging = null;
}

function openStageFoldersModal() {
    const modal = document.getElementById('stageModal');
    if (!modal || !pendingFolderStaging) return;
    
    const count = pendingFolderStaging.folders.length;
    
    const title = document.getElementById('stageModalTitle');
    if (title) {
        title.textContent = `Stage ${count} Folder${count > 1 ? 's' : ''} to...`;
    }
    
    const desc = document.getElementById('stageModalDesc');
    if (desc) {
        desc.innerHTML = `Select destination for <strong>${count}</strong> folder${count > 1 ? 's' : ''} (folder structure will be preserved)`;
    }
    
    // Import renderFolderSelectTree dynamically to avoid circular dependency
    import('../components/staging.js').then(staging => {
        staging.resetDestinationSelection();  // Clear any previous selection
        staging.renderFolderSelectTree();
    });
    
    document.getElementById('confirmStageBtn').disabled = true;
    modal.dataset.stagingMode = 'folders';
    modal.classList.add('active');
}

/**
 * Handle folder filter input.
 */
function handleFolderFilter(query) {
    folderFilter = query;
    
    // Re-render the appropriate view
    if (currentFolderSelectionAccountId) {
        renderFolderSelectionView(folderSelectionTree, currentFolderSelectionAccountId);
    } else if (currentFolderSelectionImportId) {
        renderImportFolderSelectionView(folderSelectionTree, currentFolderSelectionImportId);
    }
    
    // Refocus the input and restore cursor position
    const input = document.getElementById('folderFilterInput');
    if (input) {
        input.focus();
        input.setSelectionRange(query.length, query.length);
    }
}
window.handleFolderFilter = handleFolderFilter;

/**
 * Clear folder filter.
 */
function clearFolderFilterInput() {
    folderFilter = '';
    
    if (currentFolderSelectionAccountId) {
        renderFolderSelectionView(folderSelectionTree, currentFolderSelectionAccountId);
    } else if (currentFolderSelectionImportId) {
        renderImportFolderSelectionView(folderSelectionTree, currentFolderSelectionImportId);
    }
    
    const input = document.getElementById('folderFilterInput');
    if (input) input.focus();
}
window.clearFolderFilterInput = clearFolderFilterInput;
