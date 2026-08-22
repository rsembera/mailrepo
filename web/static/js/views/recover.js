/**
 * Disaster recovery screen.
 *
 * Runs when there is no archive on this machine: no session, no
 * database, no settings. Everything it needs comes from the server's
 * own record of where backups were sent, so this file deliberately
 * talks to nothing else in the app.
 *
 * The user is never asked to type a path. MailRepo knows where it put
 * its backups; failing that it searches; failing that there is a
 * folder picker. Typing is not one of the options.
 */

const subtitle = document.getElementById('recover-subtitle');
const locationsBox = document.getElementById('recover-locations');
const actions = document.getElementById('recover-actions');
const browseButton = document.getElementById('recover-browse');
const rescanButton = document.getElementById('recover-rescan');
const errorBox = document.getElementById('recover-error');
const errorText = document.getElementById('recover-error-text');

const picker = document.getElementById('recover-picker');
const pickerPath = document.getElementById('recover-picker-path');
const pickerList = document.getElementById('recover-picker-list');
const pickerUse = document.getElementById('recover-picker-use');
const pickerCancel = document.getElementById('recover-picker-cancel');

// base.html's fetch wrapper injects this header too. Sent explicitly as
// well because this screen has to work on the worst day this archive
// ever has, and it should not fail because a wrapper somewhere else
// changed shape.
const CSRF_TOKEN =
    document.querySelector('meta[name="csrf-token"]')?.content || '';

let pickerCurrent = '';

async function postJson(url, payload) {
    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRF-Token': CSRF_TOKEN,
        },
        body: JSON.stringify({ ...payload, csrf_token: CSRF_TOKEN }),
    });
    return response.json();
}

function showError(message) {
    errorText.textContent = message;
    errorBox.hidden = false;
}

function clearError() {
    errorBox.hidden = true;
    errorText.textContent = '';
}

function plural(count, word) {
    return `${count} ${word}${count === 1 ? '' : 's'}`;
}

// ---------------------------------------------------------------
// Restore points
// ---------------------------------------------------------------

function pointRow(point, folder) {
    const row = document.createElement('div');
    row.className = 'recover-point';

    const heading = document.createElement('div');
    heading.className = 'recover-point-name';
    heading.textContent = point.display_name;
    row.appendChild(heading);

    if (point.credential_note) {
        const note = document.createElement('p');
        note.className = 'helper-text';
        note.textContent = point.credential_note;
        row.appendChild(note);
    }

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-secondary';
    button.textContent = 'Restore this';
    button.addEventListener('click', () => confirmRestore(point, folder, button));
    row.appendChild(button);

    return row;
}

function locationCard(location) {
    const card = document.createElement('div');
    card.className = 'recover-location';

    const title = document.createElement('div');
    title.className = 'recover-location-name';
    title.textContent = location.label || location.path;
    card.appendChild(title);

    const meta = document.createElement('p');
    meta.className = 'helper-text';
    const bits = [plural(location.restore_point_count, 'restore point')];
    if (location.newest_display) {
        bits.push(`newest ${location.newest_display}`);
    }
    meta.textContent = bits.join(' · ');
    card.appendChild(meta);

    const path = document.createElement('p');
    path.className = 'recover-location-path';
    path.textContent = location.path;
    card.appendChild(path);

    if (location.source === 'reconstructed') {
        const warn = document.createElement('p');
        warn.className = 'helper-text';
        warn.textContent =
            'No backup record in this folder — this list was worked out ' +
            'from the backup filenames. Check the dates look right before ' +
            'restoring.';
        card.appendChild(warn);
    }

    const points = document.createElement('div');
    points.className = 'recover-points';
    (location.restore_points || []).forEach((point) =>
        points.appendChild(pointRow(point, location.path))
    );
    card.appendChild(points);

    return card;
}

function renderLocations(locations) {
    locationsBox.replaceChildren();
    actions.hidden = false;

    if (!locations.length) {
        subtitle.textContent =
            'MailRepo has no record of backups on this machine. If you ' +
            'kept backups, choose their folder below. If they are on ' +
            'another computer, a network drive, or an external disk, ' +
            'connect it or copy the folder onto this machine first, then ' +
            'choose it.';
        return;
    }

    const known = locations.some((location) => location.known);
    subtitle.textContent = known
        ? 'These are the backup folders MailRepo has been writing to.'
        : 'MailRepo found these backups in its own backups folder.';

    locations.forEach((location) => locationsBox.appendChild(locationCard(location)));
}

async function loadLocations(force) {
    clearError();
    subtitle.textContent = force ? 'Looking again…' : 'Looking for your backups…';
    rescanButton.disabled = true;

    try {
        const data = await postJson('/auth/restore/search', { force: !!force });
        if (!data.success) {
            showError(data.error || 'Could not look for backups.');
            actions.hidden = false;
            return;
        }
        renderLocations(data.locations || []);
    } catch (err) {
        showError(`Could not look for backups: ${err.message}`);
        actions.hidden = false;
    } finally {
        rescanButton.disabled = false;
    }
}

// ---------------------------------------------------------------
// Folder picker
// ---------------------------------------------------------------

async function openPicker(path) {
    clearError();

    try {
        const data = await postJson('/auth/restore/browse', { path: path || '' });
        if (!data.success) {
            showError(data.error || 'Could not open that folder.');
            return;
        }

        picker.hidden = false;
        pickerCurrent = data.current_path;
        pickerPath.textContent = data.current_path;
        pickerUse.disabled = !data.current_has_backups;
        pickerUse.textContent = data.current_has_backups
            ? 'Use this folder'
            : 'No backups in this folder';

        pickerList.replaceChildren();

        if (data.parent_path) {
            pickerList.appendChild(
                pickerRow('..', data.parent_path, false, false)
            );
        }

        data.folders.forEach((folder) =>
            pickerList.appendChild(
                pickerRow(
                    folder.name,
                    folder.path,
                    folder.has_backups,
                    folder.other_app_backups
                )
            )
        );
    } catch (err) {
        showError(`Could not open that folder: ${err.message}`);
    }
}

function pickerRow(name, path, hasBackups, otherApp) {
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'recover-picker-row';
    row.addEventListener('click', () => openPicker(path));

    const label = document.createElement('span');
    label.textContent = name;
    row.appendChild(label);

    if (hasBackups) {
        const tag = document.createElement('span');
        tag.className = 'recover-picker-tag';
        tag.textContent = 'backups';
        row.appendChild(tag);
    } else if (otherApp) {
        // Named plainly rather than hidden. A folder of EdgeCase backups
        // looks exactly like a folder of MailRepo backups from outside,
        // and silently omitting it would read as MailRepo failing to see
        // a folder the user can plainly see.
        const tag = document.createElement('span');
        tag.className = 'recover-picker-tag recover-picker-tag-muted';
        tag.textContent = 'another app';
        row.appendChild(tag);
    }

    return row;
}

async function usePickedFolder() {
    clearError();
    pickerUse.disabled = true;

    try {
        const data = await postJson('/auth/restore/scan', { folder: pickerCurrent });
        if (!data.success) {
            showError(data.error || 'Could not read that folder.');
            pickerUse.disabled = false;
            return;
        }

        picker.hidden = true;
        renderLocations([
            {
                path: data.folder,
                label: data.folder,
                source: data.source,
                known: false,
                restore_point_count: data.restore_points.length,
                newest_display: data.restore_points[0]?.display_name,
                restore_points: data.restore_points,
            },
        ]);
    } catch (err) {
        showError(`Could not read that folder: ${err.message}`);
        pickerUse.disabled = false;
    }
}

// ---------------------------------------------------------------
// Restoring
// ---------------------------------------------------------------

async function confirmRestore(point, folder, button) {
    const warning =
        `Restore the backup from ${point.display_name}?\n\n` +
        'This replaces all data on this machine with the backup, ' +
        'including its original password and recovery key.';

    if (!window.confirm(warning)) {
        return;
    }

    clearError();
    button.disabled = true;
    button.textContent = 'Restoring…';

    try {
        const data = await postJson('/auth/restore/prepare', {
            folder,
            restore_point_id: point.id,
        });

        if (!data.success) {
            showError(data.error || 'Restore could not be staged.');
            button.disabled = false;
            button.textContent = 'Restore this';
            return;
        }

        // Deliberately terminal. The restore finishes on next startup,
        // so there is nothing useful to do in this page afterwards, and
        // offering a second Restore button would invite a second staging
        // run over the first.
        locationsBox.replaceChildren();
        actions.hidden = true;
        picker.hidden = true;
        subtitle.textContent = data.message;
    } catch (err) {
        showError(`Restore could not be staged: ${err.message}`);
        button.disabled = false;
        button.textContent = 'Restore this';
    }
}

browseButton.addEventListener('click', () => openPicker(''));
rescanButton.addEventListener('click', () => loadLocations(true));
pickerUse.addEventListener('click', usePickedFolder);
pickerCancel.addEventListener('click', () => {
    picker.hidden = true;
});

loadLocations(false);
