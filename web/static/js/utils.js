/**
 * MailRepo - Utility Functions
 */

/**
 * Escape HTML entities to prevent XSS.
 * @param {string} str - String to escape
 * @returns {string} Escaped string
 */
export function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
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
        const date = new Date(dateStr);
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
