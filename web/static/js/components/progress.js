/**
 * MailRepo - Progress Component
 * 
 * Reusable progress bar with status messaging for long-running operations.
 * Uses Server-Sent Events for real-time updates.
 */

/**
 * Create and manage a progress display.
 * @param {HTMLElement} container - Container element to render into
 * @returns {Object} Progress controller
 */
export function createProgress(container) {
    let eventSource = null;
    let onComplete = null;
    let onError = null;
    
    /**
     * Render the progress UI.
     */
    function render(state = {}) {
        const {
            phase = 'idle',
            message = '',
            current = 0,
            total = 0,
            percent = 0,
            subject = '',
        } = state;
        
        const showBar = total > 0;
        
        container.innerHTML = `
            <div class="progress-display">
                <div class="progress-status">
                    <i data-lucide="${getPhaseIcon(phase)}" class="progress-icon ${phase === 'connecting' || phase === 'searching' ? 'spin' : ''}"></i>
                    <span class="progress-message">${escapeHtml(message)}</span>
                </div>
                ${showBar ? `
                    <div class="progress-bar-container">
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${percent}%"></div>
                        </div>
                        <span class="progress-count">${current} of ${total}</span>
                    </div>
                ` : ''}
                ${subject ? `
                    <div class="progress-detail">
                        <span class="progress-subject">${escapeHtml(subject)}</span>
                    </div>
                ` : ''}
            </div>
        `;
        
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
    
    /**
     * Start streaming from an SSE endpoint.
     */
    function startStream(url, options = {}) {
        onComplete = options.onComplete || null;
        onError = options.onError || null;
        
        // Close any existing connection
        if (eventSource) {
            eventSource.close();
        }
        
        render({ phase: 'connecting', message: 'Connecting...' });
        
        eventSource = new EventSource(url);
        
        eventSource.addEventListener('status', (e) => {
            const data = JSON.parse(e.data);
            render({
                phase: data.phase || 'status',
                message: data.message,
                current: data.current || 0,
                total: data.total || 0,
            });
        });
        
        eventSource.addEventListener('start', (e) => {
            const data = JSON.parse(e.data);
            render({
                phase: 'loading',
                message: `Loading ${data.total} emails...`,
                current: 0,
                total: data.total,
                percent: 0,
            });
        });
        
        eventSource.addEventListener('progress', (e) => {
            const data = JSON.parse(e.data);
            render({
                phase: 'loading',
                message: `Fetching emails...`,
                current: data.current,
                total: data.total,
                percent: data.percent,
                subject: data.subject,
            });
        });
        
        eventSource.addEventListener('complete', (e) => {
            const data = JSON.parse(e.data);
            eventSource.close();
            eventSource = null;
            
            if (onComplete) {
                onComplete(data);
            }
        });
        
        eventSource.addEventListener('error', (e) => {
            let errorData = { error: 'Connection lost' };
            try {
                if (e.data) {
                    errorData = JSON.parse(e.data);
                }
            } catch {}
            
            eventSource.close();
            eventSource = null;
            
            render({
                phase: 'error',
                message: errorData.error || 'An error occurred',
            });
            
            if (onError) {
                onError(errorData);
            }
        });
        
        eventSource.onerror = () => {
            // Handle connection errors
            if (eventSource && eventSource.readyState === EventSource.CLOSED) {
                render({
                    phase: 'error',
                    message: 'Connection closed unexpectedly',
                });
                if (onError) {
                    onError({ error: 'Connection closed' });
                }
            }
        };
    }
    
    /**
     * Start a POST-based stream (for commit operations).
     */
    async function startPostStream(url, body, options = {}) {
        onComplete = options.onComplete || null;
        onError = options.onError || null;
        
        render({ phase: 'connecting', message: 'Starting...' });
        
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            
            while (true) {
                const { done, value } = await reader.read();
                
                if (done) break;
                
                buffer += decoder.decode(value, { stream: true });
                
                // Parse SSE events from buffer
                const lines = buffer.split('\n');
                buffer = lines.pop() || ''; // Keep incomplete line in buffer
                
                let currentEvent = null;
                for (const line of lines) {
                    if (line.startsWith('event: ')) {
                        currentEvent = line.slice(7);
                    } else if (line.startsWith('data: ') && currentEvent) {
                        const data = JSON.parse(line.slice(6));
                        handleEvent(currentEvent, data);
                        currentEvent = null;
                    }
                }
            }
        } catch (error) {
            render({
                phase: 'error',
                message: error.message || 'An error occurred',
            });
            if (onError) {
                onError({ error: error.message });
            }
        }
    }
    
    function handleEvent(event, data) {
        switch (event) {
            case 'status':
                render({
                    phase: data.phase || 'status',
                    message: data.message,
                    current: data.current || 0,
                    total: data.total || 0,
                });
                break;
            case 'start':
                render({
                    phase: 'loading',
                    message: `Processing ${data.total} ${data.type || 'items'}...`,
                    current: 0,
                    total: data.total,
                    percent: 0,
                });
                break;
            case 'progress':
                const statusMsg = data.status === 'skipped' ? 'Skipped (duplicate)' :
                                  data.status === 'failed' ? 'Failed' : 'Archiving...';
                render({
                    phase: 'loading',
                    message: statusMsg,
                    current: data.current,
                    total: data.total,
                    percent: data.percent,
                    subject: data.subject,
                });
                break;
            case 'complete':
                if (onComplete) {
                    onComplete(data);
                }
                break;
            case 'error':
                render({
                    phase: 'error',
                    message: data.error || 'An error occurred',
                });
                if (onError) {
                    onError(data);
                }
                break;
        }
    }
    
    /**
     * Cancel the current operation.
     */
    function cancel() {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
    }
    
    /**
     * Clear the progress display.
     */
    function clear() {
        cancel();
        container.innerHTML = '';
    }
    
    return {
        render,
        startStream,
        startPostStream,
        cancel,
        clear,
    };
}

function getPhaseIcon(phase) {
    switch (phase) {
        case 'connecting':
        case 'selecting':
        case 'searching':
            return 'loader';
        case 'loading':
            return 'download';
        case 'error':
            return 'alert-triangle';
        case 'complete':
            return 'check-circle';
        default:
            return 'loader';
    }
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
