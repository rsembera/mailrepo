/**
 * Custom Select Component
 * A styled dropdown that uses app fonts and is fully customizable.
 * 
 * Usage:
 *   <div class="custom-select" data-name="myField" data-value="30">
 *       <div class="custom-select-option" data-value="15">15 minutes</div>
 *       <div class="custom-select-option" data-value="30">30 minutes (default)</div>
 *       <div class="custom-select-option" data-value="60">1 hour</div>
 *   </div>
 * 
 * Then call: initCustomSelects() or new CustomSelect(element)
 * 
 * Events: Dispatches 'change' event on the container with detail.value
 */

export class CustomSelect {
    constructor(container) {
        this.container = container;
        this.name = container.dataset.name || '';
        this.options = [];
        this.selectedValue = container.dataset.value || '';
        this.isOpen = false;
        
        this.parseOptions();
        this.render();
        this.bindEvents();
    }
    
    parseOptions() {
        const optionEls = this.container.querySelectorAll('.custom-select-option');
        optionEls.forEach(el => {
            this.options.push({
                value: el.dataset.value,
                label: el.textContent.trim()
            });
        });
    }
    
    getSelectedLabel() {
        const selected = this.options.find(o => o.value === this.selectedValue);
        return selected ? selected.label : (this.options[0]?.label || '');
    }
    
    render() {
        const selectedLabel = this.getSelectedLabel();
        
        this.container.innerHTML = `
            <button type="button" class="custom-select-trigger" aria-haspopup="listbox" aria-expanded="false">
                <span class="custom-select-value">${selectedLabel}</span>
                <svg class="custom-select-chevron" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="m6 9 6 6 6-6"/>
                </svg>
            </button>
            <div class="custom-select-dropdown" role="listbox">
                ${this.options.map(opt => `
                    <div class="custom-select-item ${opt.value === this.selectedValue ? 'selected' : ''}" 
                         role="option" 
                         data-value="${opt.value}"
                         aria-selected="${opt.value === this.selectedValue}">
                        ${opt.label}
                    </div>
                `).join('')}
            </div>
        `;
        
        this.trigger = this.container.querySelector('.custom-select-trigger');
        this.dropdown = this.container.querySelector('.custom-select-dropdown');
        this.valueDisplay = this.container.querySelector('.custom-select-value');
    }
    
    bindEvents() {
        // Toggle dropdown on trigger click
        this.trigger.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.toggle();
        });
        
        // Select option on click
        this.dropdown.addEventListener('click', (e) => {
            const item = e.target.closest('.custom-select-item');
            if (item) {
                this.select(item.dataset.value);
            }
        });
        
        // Close on outside click
        document.addEventListener('click', (e) => {
            if (!this.container.contains(e.target)) {
                this.close();
            }
        });
        
        // Keyboard navigation
        this.container.addEventListener('keydown', (e) => {
            this.handleKeydown(e);
        });
    }
    
    toggle() {
        if (this.isOpen) {
            this.close();
        } else {
            this.open();
        }
    }
    
    open() {
        // Close any other open custom selects first
        document.querySelectorAll('.custom-select.open').forEach(el => {
            if (el !== this.container) {
                el.classList.remove('open');
            }
        });
        
        this.isOpen = true;
        this.container.classList.add('open');
        this.trigger.setAttribute('aria-expanded', 'true');
        
        // Flip dropdown direction if not enough space below
        const triggerRect = this.trigger.getBoundingClientRect();
        const dropdownHeight = Math.min(this.dropdown.scrollHeight, 240);
        const spaceBelow = window.innerHeight - triggerRect.bottom;
        
        if (spaceBelow < dropdownHeight + 8 && triggerRect.top > dropdownHeight + 8) {
            this.container.classList.add('drop-up');
        } else {
            this.container.classList.remove('drop-up');
        }
        
        // Scroll selected item into view
        const selectedItem = this.dropdown.querySelector('.custom-select-item.selected');
        if (selectedItem) {
            selectedItem.scrollIntoView({ block: 'nearest' });
        }
    }
    
    close() {
        this.isOpen = false;
        this.container.classList.remove('open');
        this.trigger.setAttribute('aria-expanded', 'false');
    }
    
    select(value) {
        const option = this.options.find(o => o.value === value);
        if (!option) return;
        
        this.selectedValue = value;
        this.valueDisplay.textContent = option.label;
        
        // Update selected state in dropdown
        this.dropdown.querySelectorAll('.custom-select-item').forEach(item => {
            const isSelected = item.dataset.value === value;
            item.classList.toggle('selected', isSelected);
            item.setAttribute('aria-selected', isSelected);
        });
        
        this.close();
        
        // Dispatch change event
        this.container.dispatchEvent(new CustomEvent('change', {
            detail: { value: this.selectedValue, label: option.label },
            bubbles: true
        }));
    }
    
    handleKeydown(e) {
        const currentIndex = this.options.findIndex(o => o.value === this.selectedValue);
        
        switch (e.key) {
            case 'Enter':
            case ' ':
                e.preventDefault();
                if (this.isOpen) {
                    // Select focused item if any, otherwise close
                    this.close();
                } else {
                    this.open();
                }
                break;
            case 'Escape':
                this.close();
                break;
            case 'ArrowDown':
                e.preventDefault();
                if (!this.isOpen) {
                    this.open();
                } else if (currentIndex < this.options.length - 1) {
                    this.select(this.options[currentIndex + 1].value);
                }
                break;
            case 'ArrowUp':
                e.preventDefault();
                if (!this.isOpen) {
                    this.open();
                } else if (currentIndex > 0) {
                    this.select(this.options[currentIndex - 1].value);
                }
                break;
        }
    }
    
    getValue() {
        return this.selectedValue;
    }
    
    setValue(value) {
        this.select(value);
    }
}

/**
 * Initialize all custom selects on the page.
 */
export function initCustomSelects(container = document) {
    const selects = container.querySelectorAll('.custom-select:not(.initialized)');
    selects.forEach(el => {
        const instance = new CustomSelect(el);
        el._customSelect = instance;  // Store instance for later access
        el.classList.add('initialized');
    });
}
