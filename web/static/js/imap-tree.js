/**
 * MailRepo - IMAP folder tree
 *
 * Turns the flat list of mailboxes a server reports into the tree shown
 * in the sidebar and the folder picker.
 *
 * No DOM and no imports, so this can be exercised from Node.
 */

/**
 * Build a tree structure from flat IMAP folder list.
 * @param {Array<{name: string, delimiter?: string, noselect?: boolean}>} folders
 * @returns {Array} nodes: { name, fullPath, noselect, listed, children }
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
                    noselect: false,
                    listed: false,
                    children: {}
                };
            }
            // The final node is the folder the server listed.
            if (idx === parts.length - 1) {
                current.children[part].listed = true;
                if (folder.noselect) current.children[part].noselect = true;
            }
            current = current.children[part];
        });
    });
    
    function toArray(node) {
        return Object.values(node.children)
            // A level that only appears inside other folders' paths
            // ("a" when the server lists just "a/b") is not a mailbox:
            // it can hold folders but cannot be opened or staged.
            .map(child => ({ ...child, noselect: child.noselect || !child.listed, children: toArray(child) }))
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
