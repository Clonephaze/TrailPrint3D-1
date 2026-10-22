// Shared dialog and form accessibility for map and 3D-preview generators.
function tp3dAlert(message, title) {
    var modal = document.getElementById('tp3dNotice');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'tp3dNotice';
        modal.className = 'tp3d-modal';
        modal.innerHTML = '<div class="tp3d-modal-box"><div class="modal-header">'
            + '<span id="tp3dNoticeTitle"></span><button type="button" class="tp3d-modal-close-btn" aria-label="Close notice">×</button>'
            + '</div><div class="notice-body"></div><button type="button" class="btn-send full-width">OK</button></div>';
        modal.querySelectorAll('button').forEach(function(button) {
            button.addEventListener('click', function() { modal.classList.remove('open'); });
        });
        modal.addEventListener('click', function(event) {
            if (event.target === modal) modal.classList.remove('open');
        });
        document.body.appendChild(modal);
    }
    modal.querySelector('#tp3dNoticeTitle').textContent = title || 'Notice';
    modal.querySelector('.notice-body').textContent = message;
    modal.classList.add('open');
}

// Small self-dismissing note -- for hints that shouldn't block the page the
// way tp3dAlert does (e.g. clicking a Premium-only option in the free
// version). Shown just below *anchor* when given (kept inside the window),
// else at the bottom centre; never takes clicks.
var tp3dToastTimer = null;
function tp3dToast(message, anchor) {
    var toast = document.getElementById('tp3dToast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'tp3dToast';
        toast.className = 'tp3d-toast';
        toast.setAttribute('role', 'status');
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.style.left = '';
    toast.style.top = '';
    toast.classList.toggle('anchored', !!anchor);
    toast.classList.add('show');
    if (anchor) {
        var rect = anchor.getBoundingClientRect();
        var width = toast.offsetWidth;
        var left = rect.left + rect.width / 2 - width / 2;
        left = Math.max(8, Math.min(left, window.innerWidth - width - 8));
        toast.style.left = left + 'px';
        toast.style.top = (rect.bottom + 6) + 'px';
    }
    clearTimeout(tp3dToastTimer);
    tp3dToastTimer = setTimeout(function() { toast.classList.remove('show'); }, 3000);
}

// Image hint for controls outside the Settings popup (which has its own
// preview panel) -- e.g. the sidebar's Resolution/Size. Any button with
// data-preview-img="url" (and optionally data-preview-caption) opens a small
// floating card next to it; a click anywhere else, Escape, or the same button
// again closes it.
function tp3dToggleImagePopover(anchor) {
    var pop = document.getElementById('tp3dImagePopover');
    if (pop && pop.classList.contains('open') && pop.tp3dAnchor === anchor) {
        tp3dCloseImagePopover();
        return;
    }
    if (!pop) {
        pop = document.createElement('div');
        pop.id = 'tp3dImagePopover';
        pop.className = 'tp3d-img-popover';
        pop.setAttribute('role', 'dialog');
        document.body.appendChild(pop);
    }
    pop.innerHTML = '';
    var img = document.createElement('img');
    img.src = anchor.dataset.previewImg;
    img.alt = 'Preview';
    pop.appendChild(img);
    if (anchor.dataset.previewCaption) {
        var caption = document.createElement('div');
        caption.className = 'tp3d-img-popover-caption';
        caption.textContent = anchor.dataset.previewCaption;
        pop.appendChild(caption);
    }
    pop.tp3dAnchor = anchor;
    pop.classList.add('open');
    // Right of the "?" (the sidebar sits on the left), kept inside the window;
    // re-placed once the image knows its height.
    function place() {
        var rect = anchor.getBoundingClientRect();
        var left = Math.min(rect.right + 12, window.innerWidth - pop.offsetWidth - 8);
        var top = Math.min(Math.max(8, rect.top - 12), window.innerHeight - pop.offsetHeight - 8);
        pop.style.left = Math.max(8, left) + 'px';
        pop.style.top = Math.max(8, top) + 'px';
    }
    place();
    img.addEventListener('load', place);
}
function tp3dCloseImagePopover() {
    var pop = document.getElementById('tp3dImagePopover');
    if (pop) pop.classList.remove('open');
}
document.addEventListener('click', function(event) {
    var btn = event.target.closest && event.target.closest('[data-preview-img]');
    if (btn) {
        event.preventDefault();
        event.stopPropagation();
        tp3dToggleImagePopover(btn);
    } else if (!(event.target.closest && event.target.closest('#tp3dImagePopover'))) {
        tp3dCloseImagePopover();
    }
});
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') tp3dCloseImagePopover();
});

(function() {
    var dialogSelector = '.tp3d-modal';
    var toggleSelector = 'button.shape-btn, button.shape-toggle-btn, button.element-mode-btn, button.source-switch-btn, button[data-element-toggle]';
    var stack = [];
    var inertElements = new Map();
    var nextId = 0;
    var scheduled = false;

    function visible(element) {
        return !element.disabled && !element.closest('[inert]') && element.getClientRects().length > 0;
    }

    function focusable(dialog) {
        return Array.from(dialog.querySelectorAll('button, input, select, textarea, a[href], summary, [tabindex]'))
            .filter(function(element) { return element.tabIndex >= 0 && visible(element); });
    }

    function prepare(root) {
        if (!(root instanceof Element)) return;
        var elements = [root].concat(Array.from(root.querySelectorAll('button, input, select, ' + dialogSelector)));
        elements.forEach(function(element) {
            if (element.matches(dialogSelector)) {
                element.setAttribute('role', 'dialog');
                element.setAttribute('aria-modal', 'true');
                element.tabIndex = -1;
                var title = element.querySelector('.modal-header span');
                if (title && !element.hasAttribute('aria-labelledby')) {
                    if (!title.id) title.id = 'tp3dDialogTitle' + (++nextId);
                    element.setAttribute('aria-labelledby', title.id);
                }
            }
            if (element.matches('button') && !element.hasAttribute('aria-label')
                && (!element.textContent.trim() || element.matches('.shape-toggle-btn')) && element.title) {
                element.setAttribute('aria-label', element.title);
            }
            if (element.matches('button.tp3d-modal-close-btn')) {
                element.setAttribute('aria-label', element.title || 'Close');
            }
            if (element.matches('input:not([type=hidden]):not([type=file]), select') && !element.hasAttribute('aria-label')) {
                var row = element.closest('.field-row, .adv-field-row, .card-field');
                var label = row && row.querySelector('label');
                if (element.id && label && !label.htmlFor && row.querySelectorAll('input, select').length === 1) {
                    label.htmlFor = element.id;
                } else if (!element.labels || !element.labels.length) {
                    var name = element.id === 'resolutionSlider' ? 'Terrain mesh resolution'
                        : element.id === 'subdivisionSlider' ? 'Segments'
                        : element.id === 'tileSpacing' ? 'Tile spacing'
                        : element.id === 'latInput' ? 'Latitude'
                        : element.id === 'lonInput' ? 'Longitude'
                        : element.id === 'citySearchInput' ? 'City or place name'
                        : element.id === 'textValue' ? 'Text'
                        : null;
                    element.setAttribute('aria-label', name || element.title || (label && label.textContent.trim()) || element.placeholder || 'Value');
                }
            }
            if (element.matches(toggleSelector)) {
                element.setAttribute('aria-pressed', String(element.classList.contains('active') || element.classList.contains('enabled')));
            }
        });
    }

    function restoreBackground() {
        inertElements.forEach(function(value, element) { element.inert = value; });
        inertElements.clear();
    }

    function syncDialogs() {
        scheduled = false;
        restoreBackground();
        var closed = stack.filter(function(entry) { return !entry.modal.isConnected || !entry.modal.classList.contains('open'); });
        stack = stack.filter(function(entry) { return entry.modal.isConnected && entry.modal.classList.contains('open'); });
        if (closed.length) {
            var returnTo = closed[closed.length - 1].returnTo;
            if (returnTo && returnTo.isConnected && visible(returnTo)) returnTo.focus();
        }
        document.querySelectorAll(dialogSelector).forEach(function(modal) {
            if (modal.classList.contains('open') && !stack.some(function(entry) { return entry.modal === modal; })) {
                prepare(modal);
                stack.push({ modal: modal, returnTo: document.activeElement });
                if (!modal.contains(document.activeElement)) (focusable(modal)[0] || modal).focus();
            }
        });
        if (!stack.length || document.querySelector('#tp3dTutorial.active')) return;
        var top = stack[stack.length - 1].modal;
        // A text dialog lives inside the 3D workspace; inert only siblings
        // along its ancestor chain, never an ancestor of the dialog itself.
        var branch = top;
        while (branch.parentElement) {
            Array.from(branch.parentElement.children).forEach(function(sibling) {
                if (sibling === branch || sibling.matches('script, style, #tp3dTutorial')) return;
                inertElements.set(sibling, sibling.inert);
                sibling.inert = true;
            });
            if (branch.parentElement === document.body) break;
            branch = branch.parentElement;
        }
    }

    function scheduleDialogs() {
        if (scheduled) return;
        scheduled = true;
        queueMicrotask(syncDialogs);
    }

    document.addEventListener('keydown', function(event) {
        if (!stack.length || document.querySelector('#tp3dTutorial.active')) return;
        var top = stack[stack.length - 1].modal;
        if (event.key === 'Escape') {
            event.preventDefault();
            event.stopImmediatePropagation();
            top.classList.remove('open');
        } else if (event.key === 'Tab') {
            var items = focusable(top);
            var first = items[0] || top;
            var last = items[items.length - 1] || top;
            if (!items.length || !top.contains(document.activeElement) || (event.shiftKey && document.activeElement === first)) {
                event.preventDefault();
                (event.shiftKey ? last : first).focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        }
    }, true);

    function init() {
        prepare(document.body);
        var observer = new MutationObserver(function(records) {
            records.forEach(function(record) {
                if (record.type === 'childList') {
                    record.addedNodes.forEach(prepare);
                    if (Array.from(record.addedNodes).concat(Array.from(record.removedNodes)).some(function(node) {
                        return node instanceof Element && (node.matches(dialogSelector) || node.querySelector(dialogSelector));
                    })) scheduleDialogs();
                } else if (record.target.matches(dialogSelector + ', #tp3dTutorial')) {
                    scheduleDialogs();
                } else if (record.target.matches(toggleSelector)) {
                    record.target.setAttribute('aria-pressed', String(record.target.classList.contains('active') || record.target.classList.contains('enabled')));
                }
            });
        });
        observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['class'] });
        syncDialogs();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
