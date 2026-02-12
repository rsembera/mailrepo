/**
 * MailRepo - Date Picker Component
 * Grid-based date picker for selecting retention dates
 * Adapted from EdgeCase's pickers.js
 */

const PICKER_CONFIG = {
    months: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
    monthsFull: ['January', 'February', 'March', 'April', 'May', 'June', 
                 'July', 'August', 'September', 'October', 'November', 'December'],
    daysOfWeek: ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'],
    yearRangeStart: 2025,
    yearRangeEnd: 2045
};

export class DatePicker {
    /**
     * Create a date picker
     * @param {HTMLElement} container - Container element
     * @param {Object} options - Configuration options
     */
    constructor(container, options = {}) {
        this.container = container;
        this.options = {
            onSelect: options.onSelect || (() => {}),
            initialDate: options.initialDate || null,
            minDate: options.minDate || null
        };

        this.selectedDate = this.options.initialDate;
        this.viewYear = this.selectedDate ? this.selectedDate.getFullYear() : new Date().getFullYear();
        this.viewMonth = this.selectedDate ? this.selectedDate.getMonth() : new Date().getMonth();
        this.currentView = 'days'; // 'years', 'months', 'days'
        this.yearsPageStart = Math.floor(this.viewYear / 16) * 16;
        
        this.render();
        this.attachEvents();
    }

    render() {
        this.container.innerHTML = `
            <div class="date-picker-wrapper">
                <div class="date-picker-display" tabindex="0">
                    <span class="date-picker-value"></span>
                    <i data-lucide="calendar" class="date-picker-icon"></i>
                </div>
                <div class="date-picker-dropdown"></div>
            </div>
        `;
        
        this.display = this.container.querySelector('.date-picker-display');
        this.displayValue = this.container.querySelector('.date-picker-value');
        this.dropdown = this.container.querySelector('.date-picker-dropdown');
        
        this.updateDisplay();
        this.renderView();
        
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
    
    updateDisplay() {
        if (this.selectedDate) {
            const month = PICKER_CONFIG.monthsFull[this.selectedDate.getMonth()];
            const day = this.selectedDate.getDate();
            const year = this.selectedDate.getFullYear();
            this.displayValue.textContent = `${month} ${day}, ${year}`;
            this.displayValue.classList.remove('date-picker-placeholder');
        } else {
            this.displayValue.textContent = 'Select date';
            this.displayValue.classList.add('date-picker-placeholder');
        }
    }

    
    setDate(date, triggerCallback = true) {
        this.selectedDate = date;
        this.viewYear = date.getFullYear();
        this.viewMonth = date.getMonth();
        this.updateDisplay();
        this.renderView();
        
        if (triggerCallback) {
            this.options.onSelect(date);
        }
    }
    
    renderView() {
        switch (this.currentView) {
            case 'years':
                this.renderYearsView();
                break;
            case 'months':
                this.renderMonthsView();
                break;
            case 'days':
            default:
                this.renderDaysView();
                break;
        }
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }
    
    renderYearsView() {
        let html = `
            <div class="picker-header">
                <button type="button" class="picker-nav-btn" data-action="prev-years">
                    <i data-lucide="chevron-left"></i>
                </button>
                <span class="picker-title">${this.yearsPageStart} - ${this.yearsPageStart + 15}</span>
                <button type="button" class="picker-nav-btn" data-action="next-years">
                    <i data-lucide="chevron-right"></i>
                </button>
            </div>
            <div class="picker-grid picker-grid-years">
        `;
        
        const currentYear = new Date().getFullYear();
        for (let i = 0; i < 16; i++) {
            const year = this.yearsPageStart + i;
            const isSelected = this.selectedDate && this.selectedDate.getFullYear() === year;
            const isCurrentYear = year === currentYear;
            
            let classes = 'picker-cell';
            if (isSelected) classes += ' selected';
            if (isCurrentYear) classes += ' today';
            
            html += `<div class="${classes}" data-year="${year}">${year}</div>`;
        }
        
        html += '</div>';
        this.dropdown.innerHTML = html;
    }


    renderMonthsView() {
        let html = `
            <div class="picker-header">
                <button type="button" class="picker-back-btn" data-action="back-to-years">
                    <i data-lucide="arrow-left"></i> Years
                </button>
                <span class="picker-title">${this.viewYear}</span>
                <div></div>
            </div>
            <div class="picker-grid picker-grid-months">
        `;
        
        const currentDate = new Date();
        const isCurrentYear = this.viewYear === currentDate.getFullYear();
        
        for (let i = 0; i < 12; i++) {
            const isSelected = this.selectedDate && 
                               this.selectedDate.getFullYear() === this.viewYear && 
                               this.selectedDate.getMonth() === i;
            const isCurrentMonth = isCurrentYear && i === currentDate.getMonth();
            
            let classes = 'picker-cell';
            if (isSelected) classes += ' selected';
            if (isCurrentMonth) classes += ' today';
            
            html += `<div class="${classes}" data-month="${i}">${PICKER_CONFIG.months[i]}</div>`;
        }
        
        html += '</div>';
        this.dropdown.innerHTML = html;
    }

    
    renderDaysView() {
        const firstDay = new Date(this.viewYear, this.viewMonth, 1);
        const lastDay = new Date(this.viewYear, this.viewMonth + 1, 0);
        const startDayOfWeek = firstDay.getDay();
        const daysInMonth = lastDay.getDate();
        const prevMonthLastDay = new Date(this.viewYear, this.viewMonth, 0).getDate();
        
        let html = `
            <div class="picker-header">
                <button type="button" class="picker-back-btn" data-action="back-to-months">
                    <i data-lucide="arrow-left"></i> ${this.viewYear}
                </button>
                <span class="picker-title">${PICKER_CONFIG.monthsFull[this.viewMonth]}</span>
                <div class="picker-nav-group">
                    <button type="button" class="picker-nav-btn" data-action="prev-month">
                        <i data-lucide="chevron-left"></i>
                    </button>
                    <button type="button" class="picker-nav-btn" data-action="next-month">
                        <i data-lucide="chevron-right"></i>
                    </button>
                </div>
            </div>
        `;
        
        // Day of week headers
        html += '<div class="picker-grid picker-grid-days">';
        for (const dow of PICKER_CONFIG.daysOfWeek) {
            html += `<div class="picker-dow">${dow}</div>`;
        }
        
        const today = new Date();
        const todayStr = `${today.getFullYear()}-${today.getMonth()}-${today.getDate()}`;
        const selectedStr = this.selectedDate ? 
            `${this.selectedDate.getFullYear()}-${this.selectedDate.getMonth()}-${this.selectedDate.getDate()}` : '';

        
        // Previous month's trailing days
        for (let i = startDayOfWeek - 1; i >= 0; i--) {
            const day = prevMonthLastDay - i;
            html += `<div class="picker-cell other-month" data-day="${day}" data-month-offset="-1">${day}</div>`;
        }
        
        // Current month days
        for (let day = 1; day <= daysInMonth; day++) {
            const dateStr = `${this.viewYear}-${this.viewMonth}-${day}`;
            let classes = 'picker-cell';
            if (dateStr === selectedStr) classes += ' selected';
            if (dateStr === todayStr) classes += ' today';
            
            html += `<div class="${classes}" data-day="${day}">${day}</div>`;
        }
        
        // Next month's leading days
        const totalCells = startDayOfWeek + daysInMonth;
        const remainingCells = totalCells <= 35 ? 35 - totalCells : 42 - totalCells;
        for (let day = 1; day <= remainingCells; day++) {
            html += `<div class="picker-cell other-month" data-day="${day}" data-month-offset="1">${day}</div>`;
        }
        
        html += '</div>';
        this.dropdown.innerHTML = html;
    }


    attachEvents() {
        this.display.addEventListener('click', (e) => {
            e.stopPropagation();
            this.toggle();
        });
        
        this.display.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                this.toggle();
            }
        });
        
        this.dropdown.addEventListener('click', (e) => {
            e.stopPropagation();
            const target = e.target.closest('[data-action], [data-year], [data-month], [data-day]');
            if (!target) return;
            
            const action = target.dataset.action;
            if (action) {
                this.handleAction(action);
                return;
            }
            
            if (target.dataset.year) {
                this.viewYear = parseInt(target.dataset.year);
                this.currentView = 'months';
                this.renderView();
                return;
            }

            
            if (target.dataset.month !== undefined) {
                this.viewMonth = parseInt(target.dataset.month);
                this.currentView = 'days';
                this.renderView();
                return;
            }
            
            if (target.dataset.day) {
                let year = this.viewYear;
                let month = this.viewMonth;
                
                const monthOffset = parseInt(target.dataset.monthOffset || 0);
                if (monthOffset !== 0) {
                    month += monthOffset;
                    if (month < 0) { month = 11; year--; }
                    if (month > 11) { month = 0; year++; }
                }
                
                const day = parseInt(target.dataset.day);
                this.selectedDate = new Date(year, month, day);
                this.viewYear = year;
                this.viewMonth = month;
                
                this.updateDisplay();
                this.close();
                this.options.onSelect(this.selectedDate);
            }
        });
        
        document.addEventListener('click', () => this.close());
    }

    
    handleAction(action) {
        switch (action) {
            case 'prev-years':
                this.yearsPageStart -= 16;
                this.renderView();
                break;
            case 'next-years':
                this.yearsPageStart += 16;
                this.renderView();
                break;
            case 'back-to-years':
                this.yearsPageStart = Math.floor(this.viewYear / 16) * 16;
                this.currentView = 'years';
                this.renderView();
                break;
            case 'back-to-months':
                this.currentView = 'months';
                this.renderView();
                break;
            case 'prev-month':
                this.viewMonth--;
                if (this.viewMonth < 0) {
                    this.viewMonth = 11;
                    this.viewYear--;
                }
                this.renderView();
                break;
            case 'next-month':
                this.viewMonth++;
                if (this.viewMonth > 11) {
                    this.viewMonth = 0;
                    this.viewYear++;
                }
                this.renderView();
                break;
        }
    }

    
    toggle() {
        if (this.dropdown.classList.contains('show')) {
            this.close();
        } else {
            this.open();
        }
    }
    
    open() {
        document.querySelectorAll('.date-picker-dropdown.show').forEach(d => d.classList.remove('show'));
        this.dropdown.classList.add('show');
        this.renderView();
    }
    
    close() {
        this.dropdown.classList.remove('show');
    }
    
    getDate() {
        return this.selectedDate;
    }
    
    getTimestamp() {
        return this.selectedDate ? Math.floor(this.selectedDate.getTime() / 1000) : null;
    }
}

/**
 * Format a Unix timestamp as a readable date string
 */
export function formatDate(timestamp) {
    if (!timestamp) return '';
    const date = new Date(timestamp * 1000);
    const months = ['January', 'February', 'March', 'April', 'May', 'June',
                    'July', 'August', 'September', 'October', 'November', 'December'];
    return `${months[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()}`;
}

/**
 * Calculate days until a timestamp (negative if past)
 */
export function daysUntil(timestamp) {
    if (!timestamp) return null;
    const now = Math.floor(Date.now() / 1000);
    const diffSeconds = timestamp - now;
    return Math.ceil(diffSeconds / 86400);
}
