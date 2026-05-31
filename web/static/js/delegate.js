/**
 * MailRepo - Event delegation helper.
 *
 * Replaces the legacy inline-onclick + window.X-export pattern with a
 * single delegated listener per container. One module-local handler map,
 * no globals, dependencies are grep-able.
 *
 * IMPORTANT — bind on a view-specific child, not a shared parent:
 *
 * Views share the same outer container (the main emailList element). If
 * two views both call bindActions(emailList, ...), both listeners attach
 * to the same node, and both fire on every event with a matching
 * data-action / data-input. The previous view's listener will dispatch
 * to the new view's elements if the action names collide -- which they
 * commonly do (e.g. searchInput, openEmail).
 *
 * The fix: each view's renderShell should wrap its content in a
 * view-specific element (e.g. <div class="trash-view-root">) and bind
 * on THAT element. When the next view's render replaces emailList's
 * inner HTML, the view-specific root is destroyed and its listener
 * goes with it. No leftover listeners, no cross-talk.
 *
 * Usage:
 *
 *   import { bindActions } from '../delegate.js';
 *
 *   bindActions(container, {
 *       openEmail: (el) => openEmail(el.dataset.emailId),
 *       deleteEmail: (el) => deleteEmail(el.dataset.emailId),
 *   });
 *
 * Then in templates:
 *
 *   <button data-action="openEmail" data-email-id="${id}">Open</button>
 *
 * For non-click events, pass the event list as the third argument and use
 * the matching data-* attribute on the element:
 *
 *   bindActions(container, {
 *       searchInput: (el) => filter(el.value),
 *       clearSearch: () => clearFilter(),
 *   }, ['click', 'input']);
 *
 *   <input data-input="searchInput">
 *   <button data-action="clearSearch">x</button>
 *
 * Each event type maps to its own data-* attribute:
 *
 *   click  -> data-action
 *   input  -> data-input
 *   change -> data-change
 *   submit -> data-submit
 *
 * Resolution uses closest(`[data-${attr}]`) so a clickable button inside
 * a clickable row dispatches to the button (the nearest action), not the
 * row. This is the natural replacement for the legacy
 * `event.stopPropagation(); doThing()` inline pattern.
 *
 * Returns a teardown function that unbinds all listeners, for cases
 * where the container is replaced or the view is destroyed.
 */

const EVENT_TO_ATTR = {
    click: 'action',
    input: 'input',
    change: 'change',
    submit: 'submit',
    keydown: 'keydown',
};

export function bindActions(container, handlers, eventTypes = ['click']) {
    if (!container) {
        console.warn('bindActions: container is null, skipping');
        return () => {};
    }

    const listeners = [];

    eventTypes.forEach(eventType => {
        const attr = EVENT_TO_ATTR[eventType];
        if (!attr) {
            console.warn(`bindActions: no data-* mapping for event "${eventType}"`);
            return;
        }

        const listener = (e) => {
            const el = e.target.closest(`[data-${attr}]`);
            if (!el || !container.contains(el)) return;

            // Camel-case access: data-email-id -> dataset.emailId, but the
            // attribute itself stays as data-action (-> dataset.action).
            // For "data-input", JS access is dataset.input.
            const camelAttr = attr.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
            const actionName = el.dataset[camelAttr];

            const handler = handlers[actionName];
            if (handler) {
                handler(el, e);
            } else if (actionName) {
                console.warn(
                    `bindActions: no handler for "${actionName}" ` +
                    `(event=${eventType}, container=${container.id || container.className})`
                );
            }
        };

        container.addEventListener(eventType, listener);
        listeners.push({ eventType, listener });
    });

    return function teardown() {
        listeners.forEach(({ eventType, listener }) => {
            container.removeEventListener(eventType, listener);
        });
    };
}
