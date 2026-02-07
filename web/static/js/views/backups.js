/**
 * Backups View
 * 
 * Renders backup & restore functionality as a view within the main app layout.
 * Follows the same collapsible section pattern as settings.js.
 */

import { initCustomSelects } from '../components/custom-select.js';
import { setBackupsUnsavedChecker, setBackupsUnsavedClearer } from '../state.js';

let contextTitle = null;
let contextMeta = null;
let emailList = null;

// State
let folderPickerCurrentPath = '';
let folderPickerParentPath = null;
let hasUnsavedChanges = false;
let initialSettings = {};
let settingsLoaded = false;

/**
 * Initialize the backups view.
 */
export function initBackupsView(config) {
    contextTitle = config.contextTitle;
    contextMeta = config.contextMeta;
    emailList = config.emailList;
    
    // Register with state.js for navigation guard
    setBackupsUnsavedChecker(() => hasUnsavedChanges);
    setBackupsUnsavedClearer(() => { hasUnsavedChanges = false; });
}

/**
 * Show the backups view in the main content area.
 */
export function showBackupsView() {
    const sidebar = document.getElementById('sidebar');
    const toolbar = document.querySelector('.content-toolbar');
    const headerActions = document.querySelector('.header-actions');
    const subfoldersBar = document.getElementById('subfoldersBar');
    
    // Hide sidebar, toolbar, and subfolders bar
    if (sidebar) sidebar.style.display = 'none';
    if (toolbar) toolbar.style.display = 'none';
    if (headerActions) headerActions.style.display = 'none';
    if (subfoldersBar) subfoldersBar.style.display = 'none';
    
    // Update header
    contextTitle.textContent = 'Backup & Restore';
    contextMeta.textContent = '';
    
    // Reset state
    hasUnsavedChanges = false;
    settingsLoaded = false;
    
    // Render the view
    renderBackupsView();
}

/**
 * Render the backups view content.
 */
function renderBackupsView() {
    const html = `
        <div class="backups-view">
            <!-- Status Card -->
            <section class="backup-card">
                <div class="backup-status-header">
                    <div class="backup-status-info">
                        <div class="status-item">
                            <span class="status-label">Last Backup</span>
                            <span class="status-value" id="last-backup-display">Loading...</span>
                        </div>
                        <div class="status-item">
                            <span class="status-label">Total Backups</span>
                            <span class="status-value" id="backup-count">-</span>
                        </div>
                    </div>
                    <button class="btn btn-primary" id="backup-now-btn">
                        <span class="btn-text">Backup Now</span>
                        <span class="btn-spinner hidden"></span>
                    </button>
                </div>
            </section>
            
            <!-- Message area -->
            <div id="backup-message" class="backup-message hidden"></div>
            
            <!-- Restore pending alert -->
            <div id="restore-pending-alert" class="backup-alert-warning hidden">
                <div class="alert-warning-content">
                    <i data-lucide="alert-triangle" class="alert-icon"></i>
                    <span>Restore pending: <strong id="pending-restore-point"></strong> will be restored on next restart.</span>
                </div>
                <button class="btn btn-secondary btn-sm" id="cancel-restore-btn">Cancel Restore</button>
            </div>
            
            <!-- Settings Section -->
            <section class="backup-card">
                <div class="backup-card-header">
                    <h3>Backup Settings</h3>
                </div>
                <div class="backup-card-body">
                    <div class="backup-settings-grid">
                        <div class="form-group">
                            <label class="setting-label">Automatic Backups</label>
                            <div class="custom-select" id="backup-frequency-select" data-name="backup-frequency" data-value="daily">
                                <div class="custom-select-option" data-value="session">Every Session</div>
                                <div class="custom-select-option" data-value="daily">Daily</div>
                                <div class="custom-select-option" data-value="weekly">Weekly</div>
                                <div class="custom-select-option" data-value="manual">Manual Only</div>
                            </div>
                        </div>
                        <div class="form-group">
                            <label class="setting-label">Keep Backups For</label>
                            <div class="custom-select" id="backup-retention-select" data-name="backup-retention" data-value="forever">
                                <div class="custom-select-option" data-value="1_month">1 Month</div>
                                <div class="custom-select-option" data-value="6_months">6 Months</div>
                                <div class="custom-select-option" data-value="1_year">1 Year</div>
                                <div class="custom-select-option" data-value="forever">Forever</div>
                            </div>
                        </div>
                    </div>
                    <div class="backup-settings-grid">
                        <div class="form-group">
                            <label class="setting-label">Backup Location</label>
                            <div class="custom-select" id="backup-location-select" data-name="backup-location" data-value="default">
                                <div class="custom-select-option" data-value="default">Default (app folder)</div>
                            </div>
                            <div id="location-path" class="location-path"></div>
                        </div>
                        <div class="form-group"></div>
                    </div>
                    <div id="custom-location-wrapper" class="custom-location-wrapper form-group hidden">
                        <input type="text" id="custom-location-input" class="form-input" placeholder="Enter full path">
                        <button type="button" class="btn btn-secondary btn-sm" id="browse-folder-btn">
                            <i data-lucide="folder"></i>
                        </button>
                    </div>
                    <div class="form-group">
                        <label class="setting-label">Post-Backup Command (optional)</label>
                        <input type="text" id="post-backup-command" class="form-input" placeholder="e.g., rsync -av ~/mailrepo/backups/ user@server:~/backups/">
                        <p class="setting-hint">Command to run after each backup, such as an rsync script for remote sync. Runs with your system user privileges.</p>
                    </div>
                    <div class="backup-settings-actions">
                        <button class="btn btn-primary" id="save-settings-btn" disabled>Save Settings</button>
                    </div>
                </div>
            </section>
            
            <!-- Backup History Section -->
            <section class="backup-card">
                <div class="backup-card-header">
                    <h3>Backup History</h3>
                </div>
                <div class="backup-card-body">
                    <p class="backup-legend">
                        <span class="legend-item"><span class="backup-type-badge badge-full">Full</span> Complete backup</span>
                        <span class="legend-item"><span class="backup-type-badge badge-incr">Incr</span> Changes only</span>
                        <span class="legend-item"><span class="backup-type-badge badge-safety">Safety</span> Pre-restore backup</span>
                    </p>
                    <div id="backup-list" class="backup-list">
                        <div class="backup-list-empty">Loading backups...</div>
                    </div>
                </div>
            </section>
            
            <!-- Restore Section -->
            <section class="backup-card">
                <div class="backup-card-header">
                    <h3>Restore from Backup</h3>
                </div>
                <div class="backup-card-body">
                    <p class="setting-hint" style="margin-bottom: var(--space-md);">Select a backup to restore. A safety backup will be created automatically before restoring.</p>
                    <div class="restore-row">
                        <div class="custom-select restore-select" id="restore-point-select" data-name="restore-point" data-value="">
                            <div class="custom-select-option" data-value="">Select a backup...</div>
                        </div>
                        <button id="prepare-restore-btn" class="btn btn-primary" disabled>Restore</button>
                    </div>
                </div>
            </section>
        </div>
        
        <!-- Restore Confirmation Modal -->
        <div id="restore-modal" class="modal-overlay hidden">
            <div class="modal-content">
                <h3>Confirm Restore</h3>
                <p>You are about to restore from:</p>
                <div id="modal-restore-point" class="restore-point-name"></div>
                <div class="warning-text">
                    <i data-lucide="alert-triangle" class="warning-icon"></i>
                    <span>Your current data will be replaced with the backup data. A safety backup will be created first.</span>
                </div>
                <div class="modal-buttons">
                    <button class="btn btn-secondary" id="cancel-restore-modal-btn">Cancel</button>
                    <button class="btn btn-primary" id="confirm-restore-btn">Restore</button>
                </div>
            </div>
        </div>
        
        <!-- Folder Picker Modal -->
        <div id="folder-picker-modal" class="modal-overlay">
            <div class="modal-content folder-picker-modal">
                <div class="folder-picker-header">
                    <h3>Select Backup Folder</h3>
                    <button class="btn-icon" id="close-folder-picker-btn" title="Close">
                        <i data-lucide="x"></i>
                    </button>
                </div>
                <div class="folder-picker-path">
                    <button class="btn-icon" id="folder-up-btn" title="Go up">
                        <i data-lucide="arrow-up"></i>
                    </button>
                    <span id="current-path-display" class="current-path">Loading...</span>
                </div>
                <div class="folder-list" id="folder-list">
                    <div class="folder-list-loading">Loading...</div>
                </div>
                <div class="folder-picker-actions">
                    <button class="btn btn-secondary" id="cancel-folder-picker-btn">Cancel</button>
                    <button class="btn btn-primary" id="select-folder-btn">Select This Folder</button>
                </div>
            </div>
        </div>
    `;
    
    emailList.innerHTML = html;
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
    
    initCustomSelects();
    initBackupHandlers();
    loadBackupStatus();
    loadRestorePoints();
}

/**
 * Initialize event handlers.
 */
function initBackupHandlers() {
    // Backup now button
    document.getElementById('backup-now-btn').addEventListener('click', performBackup);
    
    // Cancel restore button (in alert)
    const cancelRestoreBtn = document.getElementById('cancel-restore-btn');
    if (cancelRestoreBtn) {
        cancelRestoreBtn.addEventListener('click', cancelRestore);
    }
    
    // Save settings button
    document.getElementById('save-settings-btn').addEventListener('click', saveSettings);
    
    // Restore button
    document.getElementById('prepare-restore-btn').addEventListener('click', showRestoreModal);
    
    // Restore modal buttons
    document.getElementById('cancel-restore-modal-btn').addEventListener('click', hideRestoreModal);
    document.getElementById('confirm-restore-btn').addEventListener('click', confirmRestore);
    
    // Restore point select
    document.getElementById('restore-point-select').addEventListener('change', (e) => {
        document.getElementById('prepare-restore-btn').disabled = !e.detail.value;
    });
    
    // Track changes to settings - only after settings are loaded
    document.getElementById('backup-frequency-select').addEventListener('change', onSettingChange);
    document.getElementById('backup-retention-select').addEventListener('change', onSettingChange);
    document.getElementById('backup-location-select').addEventListener('change', (e) => {
        handleLocationChange(e);
        onSettingChange();
    });
    
    // Custom location input
    document.getElementById('custom-location-input').addEventListener('input', onSettingChange);
    
    // Post-backup command
    document.getElementById('post-backup-command').addEventListener('input', onSettingChange);
    
    // Folder picker
    document.getElementById('browse-folder-btn').addEventListener('click', openFolderPicker);
    document.getElementById('close-folder-picker-btn').addEventListener('click', closeFolderPicker);
    document.getElementById('cancel-folder-picker-btn').addEventListener('click', closeFolderPicker);
    document.getElementById('select-folder-btn').addEventListener('click', selectCurrentFolder);
    document.getElementById('folder-up-btn').addEventListener('click', navigateToParent);
}

/**
 * Called when a setting changes - only mark as changed if settings have loaded.
 */
function onSettingChange() {
    if (settingsLoaded) {
        hasUnsavedChanges = true;
        document.getElementById('save-settings-btn').disabled = false;
    }
}

/**
 * Load backup status and settings from server.
 */
async function loadBackupStatus() {
    try {
        const response = await fetch('/api/backup/status');
        const data = await response.json();
        
        // Update status display
        document.getElementById('last-backup-display').textContent = data.last_backup_display || 'Never';
        document.getElementById('backup-count').textContent = data.backup_count || 0;
        
        // Store initial settings
        initialSettings = {
            frequency: data.frequency || 'daily',
            retention: data.retention || 'forever',
            location: data.location || '',
            post_backup_command: data.post_backup_command || ''
        };
        
        // Set post-backup command value
        document.getElementById('post-backup-command').value = data.post_backup_command || '';
        
        // Populate location dropdown with cloud folders, then set all values
        populateLocationDropdown(data.cloud_folders || [], data.location || '');
        
        // Set dropdown values after a short delay to ensure custom selects are ready
        setTimeout(() => {
            const freqSelect = document.getElementById('backup-frequency-select');
            if (freqSelect && freqSelect._customSelect) {
                freqSelect._customSelect.setValue(initialSettings.frequency);
            }
            
            const retSelect = document.getElementById('backup-retention-select');
            if (retSelect && retSelect._customSelect) {
                retSelect._customSelect.setValue(initialSettings.retention);
            }
            
            // Mark settings as loaded - changes after this point are user-initiated
            settingsLoaded = true;
        }, 100);
        
        // Check for pending restore
        if (data.restore_pending) {
            document.getElementById('pending-restore-point').textContent = data.restore_point || 'Unknown';
            document.getElementById('restore-pending-alert').classList.remove('hidden');
        }
        
    } catch (error) {
        console.error('Error loading backup status:', error);
        document.getElementById('last-backup-display').textContent = 'Error loading';
        settingsLoaded = true; // Allow changes even on error
    }
}

/**
 * Populate location dropdown with cloud folders.
 */
function populateLocationDropdown(cloudFolders, savedLocation) {
    const selectEl = document.getElementById('backup-location-select');
    const isCustomLocation = savedLocation && 
        savedLocation !== 'default' && 
        !cloudFolders.some(f => f.path === savedLocation);
    
    // Build options HTML
    let optionsHtml = '<div class="custom-select-option" data-value="default">Default (app folder)</div>';
    
    cloudFolders.forEach(folder => {
        optionsHtml += `<div class="custom-select-option" data-value="${escapeHtml(folder.path)}">${escapeHtml(folder.name)}</div>`;
    });
    
    optionsHtml += '<div class="custom-select-option" data-value="custom">Custom...</div>';
    
    // Update the select element
    selectEl.innerHTML = optionsHtml;
    
    // Determine initial value
    let initialValue = 'default';
    if (savedLocation) {
        if (isCustomLocation) {
            initialValue = 'custom';
            document.getElementById('custom-location-input').value = savedLocation;
            document.getElementById('custom-location-wrapper').classList.remove('hidden');
        } else if (savedLocation !== '' && savedLocation !== 'default') {
            initialValue = savedLocation;
        }
    }
    
    selectEl.dataset.value = initialValue;
    selectEl.classList.remove('initialized');
    initCustomSelects(selectEl.parentElement);
    
    // Set value after initialization
    setTimeout(() => {
        if (selectEl._customSelect) {
            selectEl._customSelect.setValue(initialValue);
        }
        updateLocationPath();
    }, 50);
}

/**
 * Handle location dropdown change.
 */
function handleLocationChange(e) {
    updateLocationPath();
    if (e.detail && e.detail.value === 'custom') {
        document.getElementById('custom-location-wrapper').classList.remove('hidden');
    } else {
        document.getElementById('custom-location-wrapper').classList.add('hidden');
    }
}

/**
 * Update location path display.
 */
function updateLocationPath() {
    const selectEl = document.getElementById('backup-location-select');
    const pathDisplay = document.getElementById('location-path');
    const customWrapper = document.getElementById('custom-location-wrapper');
    const customInput = document.getElementById('custom-location-input');
    
    const value = selectEl._customSelect ? selectEl._customSelect.getValue() : selectEl.dataset.value;
    
    if (value === 'default') {
        pathDisplay.textContent = '';
        customWrapper.classList.add('hidden');
    } else if (value === 'custom') {
        customWrapper.classList.remove('hidden');
        pathDisplay.textContent = customInput.value || '';
    } else {
        pathDisplay.textContent = value;
        customWrapper.classList.add('hidden');
    }
}

/**
 * Load restore points and build backup list.
 */
async function loadRestorePoints() {
    try {
        const response = await fetch('/api/backup/restore-points');
        const data = await response.json();
        
        const listEl = document.getElementById('backup-list');
        const restoreSelectEl = document.getElementById('restore-point-select');
        
        if (!data.restore_points || data.restore_points.length === 0) {
            listEl.innerHTML = '<div class="backup-list-empty">No backups yet. Click "Backup Now" to create your first backup.</div>';
            restoreSelectEl.innerHTML = '<div class="custom-select-option" data-value="">No backups available</div>';
            restoreSelectEl.dataset.value = '';
            restoreSelectEl.classList.remove('initialized');
            initCustomSelects(restoreSelectEl.parentElement);
            return;
        }
        
        // Group by chain for visual hierarchy
        const chains = groupByChain(data.restore_points);
        
        // Build backup list HTML
        let listHtml = '';
        const sortedChainIds = Object.keys(chains).sort((a, b) => {
            const aDate = chains[a].full ? chains[a].full.created_at : (chains[a].safety ? chains[a].safety.created_at : '');
            const bDate = chains[b].full ? chains[b].full.created_at : (chains[b].safety ? chains[b].safety.created_at : '');
            return bDate.localeCompare(aDate);
        });
        
        for (const chainId of sortedChainIds) {
            const chain = chains[chainId];
            
            if (chain.safety) {
                listHtml += renderSafetyBackup(chain.safety);
                continue;
            }
            
            if (chain.full) {
                listHtml += renderFullBackup(chain.full);
                
                if (chain.incrementals && chain.incrementals.length > 0) {
                    chain.incrementals.sort((a, b) => a.created_at.localeCompare(b.created_at));
                    
                    for (let i = 0; i < chain.incrementals.length; i++) {
                        const incr = chain.incrementals[i];
                        const isLast = (i === chain.incrementals.length - 1);
                        listHtml += renderIncrementalBackup(incr, isLast);
                    }
                }
                
                listHtml += '</div>';
            }
        }
        
        listEl.innerHTML = listHtml;
        
        // Build restore dropdown options
        let optionsHtml = '<div class="custom-select-option" data-value="">Select a backup...</div>';
        const allPoints = [...data.restore_points].sort((a, b) => b.created_at.localeCompare(a.created_at));
        
        for (const point of allPoints) {
            let typeLabel = '';
            if (point.type === 'full') typeLabel = '[Full] ';
            else if (point.type === 'incremental') typeLabel = '[Incr] ';
            else if (point.type === 'pre_restore') typeLabel = '[Safety] ';
            
            optionsHtml += `<div class="custom-select-option" data-value="${point.id}">${typeLabel}${escapeHtml(point.display_name)}</div>`;
        }
        
        restoreSelectEl.innerHTML = optionsHtml;
        restoreSelectEl.dataset.value = '';
        restoreSelectEl.classList.remove('initialized');
        initCustomSelects(restoreSelectEl.parentElement);
        
    } catch (error) {
        console.error('Error loading restore points:', error);
        document.getElementById('backup-list').innerHTML = '<div class="backup-list-empty">Error loading backups</div>';
    }
}

/**
 * Group restore points by chain_id.
 */
function groupByChain(points) {
    const chains = {};
    
    for (const point of points) {
        const chainId = point.chain_id;
        
        if (!chains[chainId]) {
            chains[chainId] = { full: null, incrementals: [], safety: null };
        }
        
        if (point.type === 'full') {
            chains[chainId].full = point;
        } else if (point.type === 'incremental') {
            chains[chainId].incrementals.push(point);
        } else if (point.type === 'pre_restore') {
            chains[chainId].safety = point;
        }
    }
    
    return chains;
}

/**
 * Render a full backup item.
 */
function renderFullBackup(point) {
    const dependentText = point.dependent_count > 0 
        ? `<span class="dependent-count">${point.dependent_count} dependent</span>` 
        : '';
    
    return `
        <div class="backup-chain">
            <div class="backup-item backup-full">
                <div class="backup-item-info">
                    <span class="backup-type-badge badge-full">Full</span>
                    <span class="backup-item-name">${escapeHtml(point.display_name)}</span>
                    ${dependentText}
                </div>
            </div>
    `;
}

/**
 * Render an incremental backup item.
 */
function renderIncrementalBackup(point, isLast) {
    const connectorClass = isLast ? 'connector-last' : 'connector-mid';
    
    return `
        <div class="backup-item backup-incremental">
            <div class="backup-connector ${connectorClass}"></div>
            <div class="backup-item-info">
                <span class="backup-type-badge badge-incr">Incr</span>
                <span class="backup-item-name">${escapeHtml(point.display_name)}</span>
            </div>
        </div>
    `;
}

/**
 * Render a safety backup.
 */
function renderSafetyBackup(point) {
    return `
        <div class="backup-chain">
            <div class="backup-item backup-safety">
                <div class="backup-item-info">
                    <span class="backup-type-badge badge-safety">Safety</span>
                    <span class="backup-item-name">${escapeHtml(point.display_name)}</span>
                </div>
            </div>
        </div>
    `;
}

/**
 * Perform backup.
 */
async function performBackup() {
    const btn = document.getElementById('backup-now-btn');
    const btnText = btn.querySelector('.btn-text');
    const spinner = btn.querySelector('.btn-spinner');
    
    btn.disabled = true;
    btnText.textContent = 'Backing up...';
    spinner.classList.remove('hidden');
    
    try {
        const response = await fetch('/api/backup/now', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        
        if (data.success) {
            if (data.backup) {
                showMessage(`Backup created: ${data.backup.type}`, 'success');
            } else {
                showMessage('No changes since last backup', 'info');
            }
            loadBackupStatus();
            loadRestorePoints();
        } else {
            showMessage('Backup failed: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        console.error('Backup error:', error);
        showMessage('Backup failed: ' + error.message, 'error');
    } finally {
        btn.disabled = false;
        btnText.textContent = 'Backup Now';
        spinner.classList.add('hidden');
    }
}

/**
 * Save all settings.
 */
async function saveSettings() {
    const freqSelect = document.getElementById('backup-frequency-select');
    const retSelect = document.getElementById('backup-retention-select');
    const locSelect = document.getElementById('backup-location-select');
    const postCmd = document.getElementById('post-backup-command');
    
    const frequency = freqSelect._customSelect ? freqSelect._customSelect.getValue() : freqSelect.dataset.value;
    const retention = retSelect._customSelect ? retSelect._customSelect.getValue() : retSelect.dataset.value;
    let location = locSelect._customSelect ? locSelect._customSelect.getValue() : locSelect.dataset.value;
    const postBackupCommand = postCmd.value;
    
    if (location === 'custom') {
        location = document.getElementById('custom-location-input').value.trim();
        if (!location) {
            showMessage('Please enter a custom backup path', 'error');
            return;
        }
    }
    
    const saveBtn = document.getElementById('save-settings-btn');
    saveBtn.disabled = true;
    saveBtn.textContent = 'Saving...';
    
    try {
        const response = await fetch('/api/backup/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                frequency: frequency,
                retention: retention,
                location: location === 'default' ? '' : location,
                post_backup_command: postBackupCommand
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showMessage('Settings saved', 'success');
            hasUnsavedChanges = false;
            
            // Update initial settings
            initialSettings = {
                frequency,
                retention,
                location: location === 'default' ? '' : location,
                post_backup_command: postBackupCommand
            };
            
            setTimeout(() => {
                const msgEl = document.getElementById('backup-message');
                if (msgEl && msgEl.classList.contains('success')) {
                    msgEl.classList.add('hidden');
                }
            }, 3000);
        } else {
            showMessage('Failed to save: ' + (data.error || 'Unknown error'), 'error');
            saveBtn.disabled = false;
        }
    } catch (error) {
        console.error('Save settings error:', error);
        showMessage('Failed to save settings', 'error');
        saveBtn.disabled = false;
    } finally {
        saveBtn.textContent = 'Save Settings';
    }
}

/**
 * Show restore confirmation modal.
 */
function showRestoreModal() {
    const selectEl = document.getElementById('restore-point-select');
    const selectedValue = selectEl._customSelect ? selectEl._customSelect.getValue() : '';
    
    if (!selectedValue) return;
    
    // Get selected label
    const selectedItem = selectEl.querySelector('.custom-select-item.selected');
    const selectedText = selectedItem ? selectedItem.textContent : 'Unknown backup';
    
    document.getElementById('modal-restore-point').textContent = selectedText;
    document.getElementById('restore-modal').classList.remove('hidden');
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Hide restore confirmation modal.
 */
function hideRestoreModal() {
    document.getElementById('restore-modal').classList.add('hidden');
}

/**
 * Confirm and prepare restore.
 */
async function confirmRestore() {
    const selectEl = document.getElementById('restore-point-select');
    const restorePointId = selectEl._customSelect ? selectEl._customSelect.getValue() : '';
    
    hideRestoreModal();
    
    try {
        const response = await fetch('/api/backup/prepare-restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ restore_point: restorePointId })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showMessage('Restore prepared. Please restart MailRepo to complete the restore.', 'info');
            loadBackupStatus();
        } else {
            showMessage('Failed to prepare restore: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        console.error('Restore error:', error);
        showMessage('Failed to prepare restore', 'error');
    }
}

/**
 * Cancel pending restore.
 */
async function cancelRestore() {
    try {
        const response = await fetch('/api/backup/cancel-restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        
        const data = await response.json();
        
        if (data.success) {
            showMessage('Restore cancelled.', 'info');
            document.getElementById('restore-pending-alert').classList.add('hidden');
            loadBackupStatus();
        } else {
            showMessage('Failed to cancel restore: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        console.error('Cancel restore error:', error);
        showMessage('Failed to cancel restore', 'error');
    }
}

/**
 * Show a message.
 */
function showMessage(text, type) {
    const messageEl = document.getElementById('backup-message');
    messageEl.textContent = text;
    messageEl.className = `backup-message ${type}`;
    messageEl.classList.remove('hidden');
    
    if (type !== 'error') {
        setTimeout(() => {
            messageEl.classList.add('hidden');
        }, 5000);
    }
}

// ============================================
// FOLDER PICKER
// ============================================

/**
 * Open folder picker modal.
 */
function openFolderPicker() {
    document.getElementById('folder-picker-modal').classList.add('active');
    
    const customInput = document.getElementById('custom-location-input');
    const startPath = customInput.value.trim() || '';
    
    loadFolderContents(startPath);
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

/**
 * Close folder picker modal.
 */
function closeFolderPicker() {
    document.getElementById('folder-picker-modal').classList.remove('active');
}

/**
 * Load folder contents.
 */
async function loadFolderContents(path) {
    const listEl = document.getElementById('folder-list');
    const pathDisplay = document.getElementById('current-path-display');
    const upBtn = document.getElementById('folder-up-btn');
    
    listEl.innerHTML = '<div class="folder-list-loading">Loading...</div>';
    
    try {
        const url = '/api/backup/list-folders' + (path ? `?path=${encodeURIComponent(path)}` : '');
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.error) {
            listEl.innerHTML = `<div class="folder-list-error">${escapeHtml(data.error)}</div>`;
            return;
        }
        
        folderPickerCurrentPath = data.current_path;
        folderPickerParentPath = data.parent_path;
        
        pathDisplay.textContent = data.current_path;
        upBtn.disabled = !data.parent_path;
        
        if (data.folders.length === 0) {
            listEl.innerHTML = '<div class="folder-list-empty">No subfolders</div>';
        } else {
            listEl.innerHTML = data.folders.map(folder => {
                const inaccessible = folder.inaccessible ? ' inaccessible' : '';
                const lockIcon = folder.inaccessible 
                    ? '<i data-lucide="lock" class="folder-item-locked"></i>' 
                    : '';
                return `
                    <div class="folder-item${inaccessible}" 
                         data-path="${escapeHtml(folder.path)}"
                         title="${folder.inaccessible ? 'Permission denied' : escapeHtml(folder.path)}">
                        <i data-lucide="folder" class="folder-item-icon"></i>
                        <span class="folder-item-name">${escapeHtml(folder.name)}</span>
                        ${lockIcon}
                    </div>
                `;
            }).join('');
            
            // Add click handlers for accessible folders
            listEl.querySelectorAll('.folder-item:not(.inaccessible)').forEach(item => {
                item.addEventListener('click', () => {
                    loadFolderContents(item.dataset.path);
                });
            });
            
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    } catch (error) {
        console.error('Error loading folders:', error);
        listEl.innerHTML = '<div class="folder-list-error">Error loading folders</div>';
    }
}

/**
 * Navigate to parent folder.
 */
function navigateToParent() {
    if (folderPickerParentPath) {
        loadFolderContents(folderPickerParentPath);
    }
}

/**
 * Select current folder.
 */
function selectCurrentFolder() {
    if (folderPickerCurrentPath) {
        document.getElementById('custom-location-input').value = folderPickerCurrentPath;
        
        const locSelect = document.getElementById('backup-location-select');
        if (locSelect._customSelect) locSelect._customSelect.setValue('custom');
        
        document.getElementById('custom-location-wrapper').classList.remove('hidden');
        updateLocationPath();
        onSettingChange();
    }
    
    closeFolderPicker();
}

/**
 * Escape HTML.
 */
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
