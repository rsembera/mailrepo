/**
 * MailRepo - Utility Functions
 */

/**
 * Escape HTML entities to prevent XSS.
 * @param {string} str - String to escape
 * @returns {string} Escaped string
 */
export function escapeHtml(str) {
    if (str === null || str === undefined || str === '') return '';
    // Quotes too: this is used inside attr="${...}" as well as in text,
    // and an IMAP folder or mbox label named `x" onmouseover="..."` must
    // not be able to close the attribute. textContent/innerHTML only
    // escapes & < >, so do it by hand.
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * Escape a string for use in an onclick attribute.
 * Handles backslashes, single quotes, and double quotes.
 * @param {string} str - String to escape
 * @returns {string} Escaped string
 */
export function escapeForOnclick(str) {
    if (!str) return '';
    return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

/**
 * Extract name from email address format "Name <email>".
 * @param {string} sender - Sender string
 * @returns {string} Extracted name or original string
 */
export function extractName(sender) {
    if (!sender) return '';
    const match = sender.match(/^([^<]+)</);
    return match ? match[1].trim() : sender;
}

/**
 * Format a date for display.
 * @param {string|Date} dateStr - Date to format
 * @returns {string} Formatted date string
 */
export function formatDate(dateStr) {
    if (!dateStr) return '';
    
    try {
        // Handle Unix timestamps (integers or numeric strings)
        let date;
        const numVal = Number(dateStr);
        if (!isNaN(numVal) && numVal > 946684800 && numVal < 32503680000) {
            // Looks like a Unix timestamp in seconds (year 2000-3000 range)
            date = new Date(numVal * 1000);
        } else {
            date = new Date(dateStr);
        }
        const now = new Date();
        
        if (isNaN(date.getTime())) return dateStr;
        
        // Same day
        if (date.toDateString() === now.toDateString()) {
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }
        
        // This year
        if (date.getFullYear() === now.getFullYear()) {
            return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
        }
        
        // Other
        return date.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' });
    } catch {
        return dateStr;
    }
}

/**
 * Create a debounced version of a function.
 * @param {Function} fn - Function to debounce
 * @param {number} delay - Delay in milliseconds
 * @returns {Function} Debounced function
 */
export function debounce(fn, delay) {
    let timeout;
    return function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => fn.apply(this, args), delay);
    };
}
