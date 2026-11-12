/**
 * MailRepo - Archive paths for staged folders
 *
 * Staging whole folders keeps their arrangement: if "Clients" and
 * "Clients/Smith" are staged together, "Smith" is archived inside
 * "Clients". The archive path is always written with "/" between levels,
 * which is what the server splits on.
 *
 * The source's own separator is not always "/". Gmail uses it; Dovecot
 * and Courier commonly use "." ("INBOX.Clients.Smith"). The separator
 * the server reported is passed in, so those hierarchies are kept too
 * instead of being flattened into folders named by their whole path.
 *
 * No DOM and no imports, so this can be exercised from Node.
 */

/**
 * The hierarchy separator an account's server reported, or "/".
 * @param {Map} imapFolders - state.imapFolders
 * @param {number|string} accountId
 * @returns {string}
 */
export function imapDelimiter(imapFolders, accountId) {
    const data = imapFolders.get(accountId)
        || imapFolders.get(String(accountId))
        || imapFolders.get(Number(accountId));
    const found = data && (data.folders || []).find(f => f.delimiter);
    return found ? found.delimiter : '/';
}

/**
 * Last level of a folder path, as the name of an archive folder.
 * @param {string} fullPath
 * @param {string} [delimiter='/'] - the source's hierarchy separator
 * @returns {string}
 */
export function getFolderName(fullPath, delimiter = '/') {
    const parts = fullPath.split(delimiter);
    let name = parts[parts.length - 1];
    // Apple Mail exports name each folder "<name>.mbox".
    name = name.replace(/\.mbox$/, '');
    // "/" separates levels in an archive path. Where it is not the
    // source's separator it can be part of a folder's name, and would
    // otherwise split that folder in two.
    if (delimiter !== '/') name = name.replace(/\//g, '-');
    return name;
}

/**
 * Compute archive paths for staged folders.
 *
 * For each folder: if an ancestor is staged with it, the path continues
 * from the ancestor's (Parent/Child); otherwise it is the folder's own
 * name.
 *
 * @param {string[]} folderPaths - All folder paths being staged
 * @param {string} [delimiter='/'] - the source's hierarchy separator
 * @returns {Object} Map of fullPath -> archivePath
 */
export function computeArchivePaths(folderPaths, delimiter = '/') {
    const archivePaths = {};

    // Shortest first, so ancestors are done before descendants.
    const sorted = [...folderPaths].sort((a, b) => a.length - b.length);

    for (const path of sorted) {
        const folderName = getFolderName(path, delimiter);

        // The nearest ancestor that is also being staged.
        let ancestorPath = null;
        for (const otherPath of sorted) {
            if (otherPath === path) continue;

            if (path.startsWith(otherPath + delimiter)) {
                if (!ancestorPath || otherPath.length > ancestorPath.length) {
                    ancestorPath = otherPath;
                }
            }

            // Apple Mail: Parent.mbox sits beside the Parent/ directory
            // that holds its subfolders.
            if (otherPath.endsWith('.mbox')) {
                const parentDir = otherPath.slice(0, -5);
                if (path.startsWith(parentDir + delimiter)) {
                    if (!ancestorPath || otherPath.length > ancestorPath.length) {
                        ancestorPath = otherPath;
                    }
                }
            }
        }

        if (ancestorPath && archivePaths[ancestorPath]) {
            archivePaths[path] = archivePaths[ancestorPath] + '/' + folderName;
        } else {
            archivePaths[path] = folderName;
        }
    }

    return archivePaths;
}
