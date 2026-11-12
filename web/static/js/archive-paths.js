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
 * Where a folder of a converted PST sits in the mailbox, from the path
 * of its file relative to the conversion directory. readpst writes each
 * folder as "<its path>/mbox".
 * @param {string} relativePath - e.g. "Personal Folders/Inbox/mbox"
 * @param {string} fallback - name to use for a file at the top level
 * @returns {string} e.g. "Personal Folders/Inbox"
 */
export function pstLogicalPath(relativePath, fallback) {
    const parts = relativePath.split('/').filter(Boolean);
    if (parts.length && parts[parts.length - 1] === 'mbox') parts.pop();
    if (parts.length) parts[parts.length - 1] = parts[parts.length - 1].replace(/\.mbox$/, '');
    return parts.join('/') || fallback;
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
 * @param {(path: string) => string} [logicalOf] - where a folder's path
 *   on disk is not its place in the mailbox (a converted PST: every
 *   folder is a file called "mbox" in a directory of its own), the path
 *   to name and nest it by. The result is still keyed by the path given.
 * @returns {Object} Map of fullPath -> archivePath
 */
export function computeArchivePaths(folderPaths, delimiter = '/', logicalOf = null) {
    if (logicalOf) {
        const original = new Map(folderPaths.map(p => [logicalOf(p) || p, p]));
        const logical = computeArchivePaths([...original.keys()], delimiter);
        return Object.fromEntries(Object.entries(logical).map(([l, a]) => [original.get(l), a]));
    }

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
