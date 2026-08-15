/**
 * Disaster recovery screen.
 *
 * Runs when there is no archive on this machine: no session, no
 * database, no settings. Everything it needs comes from the folder the
 * user names, so this file deliberately talks to nothing else.
 */

const folderInput = document.getElementById('recover-folder');
const scanButton = document.getElementById('recover-scan');
const results = document.getElementById('recover-results');
const sourceLine = document.getElementById('recover-source');
const pointsBox = document.getElementById('recover-points');
const errorBox = document.getElementById('recover-error');
const errorText = document.getElementById('recover-error-text');

let currentFolder = '';

// base.html's fetch wrapper injects this header too. Sent explicitly as
// well because this screen has to work on the worst day this archive
// ever has, and it should not fail because a wrapper somewhere else
// changed shape.
const CSRF_TOKEN =
    document.querySelector('meta[name="csrf-token"]')?.content || '';

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

const SOURCE_TEXT = {
    manifest: 'Found a backup record in this folder.',
    reconstructed:
        'No backup record in this folder — this list was worked out from ' +
        'the backup filenames. Check the dates look right before restoring.',
    empty: 'No backups in this folder.',
};

function pointCard(point) {
    const card = document.createElement('div');
    card.className = 'recover-point';

    const heading = document.createElement('div');
    heading.className = 'recover-point-name';
    heading.textContent = point.display_name;
    card.appendChild(heading);

    if (point.credential_note) {
        const note = document.createElement('p');
        note.className = 'helper-text';
        note.textContent = point.credential_note;
        card.appendChild(note);
    }

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn btn-secondary';
    button.textContent = 'Restore this';
    button.addEventListener('click', () => confirmRestore(point, button));
    card.appendChild(button);

    return card;
}

function renderPoints(points, source) {
    pointsBox.replaceChildren();
    sourceLine.textContent = SOURCE_TEXT[source] || '';

    points.forEach((point) => pointsBox.appendChild(pointCard(point)));

    results.hidden = false;
}

async function scan() {
    clearError();
    scanButton.disabled = true;
    scanButton.textContent = 'Looking…';

    try {
        const data = await postJson('/auth/restore/scan', {
            folder: folderInput.value,
        });

        if (!data.success) {
            results.hidden = true;
            showError(data.error || 'Could not read that folder.');
            return;
        }

        currentFolder = data.folder;
        renderPoints(data.restore_points, data.source);
    } catch (err) {
        showError(`Could not read that folder: ${err.message}`);
    } finally {
        scanButton.disabled = false;
        scanButton.textContent = 'Look for backups';
    }
}

async function confirmRestore(point, button) {
    const warning =
        `Restore the backup from ${point.display_name}?\n\n` +
        'This replaces everything currently on this machine, and brings ' +
        'back the master password and recovery key that were in use when ' +
        'the backup was made.';

    if (!window.confirm(warning)) {
        return;
    }

    clearError();
    button.disabled = true;
    button.textContent = 'Restoring…';

    try {
        const data = await postJson('/auth/restore/prepare', {
            folder: currentFolder,
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
        results.hidden = true;
        sourceLine.textContent = '';
        scanButton.disabled = true;

        const done = document.createElement('div');
        done.className = 'success-box';
        done.textContent = data.message;
        errorBox.parentNode.insertBefore(done, errorBox);
    } catch (err) {
        showError(`Restore could not be staged: ${err.message}`);
        button.disabled = false;
        button.textContent = 'Restore this';
    }
}

scanButton.addEventListener('click', scan);

// Scan the default location on arrival. If backups are where MailRepo
// put them, the user should not have to type a path to find that out.
scan();
