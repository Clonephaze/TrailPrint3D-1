// Renders the element enabled/disabled status strip above the map, and
// establishes the shared toggle state + repaint mechanism the Settings
// modal's Elements tab (settings_modal.js) also plugs into -- reused by
// every 2D-map picker page via __ELEMENT_STATUS_JS__ in picker_server.py.
// Requires PORT, ELEMENT_ICONS (key -> recolored SVG markup, from
// __ELEMENT_ICONS_JS__) and ELEMENT_STATES (key -> bool, from
// __ELEMENT_STATES_JS__) to already be defined -- both are per-request
// snapshots the server inlines earlier in the same <script> block.
//
// 'elevation' is deliberately left out of this row -- it has no toggle of
// its own (the base terrain height is always fetched), so there was
// nothing meaningful to show/click; its own quick setting (Elevation
// Scale) lives in the Settings modal's Map tab instead.
var ELEMENT_STATUS_ORDER = [
    ['water', 'Water'],
    ['forest', 'Forest'],
    ['scree', 'Scree'],
    ['city', 'City Boundaries'],
    ['greenspace', 'Greenspace'],
    ['farmland', 'Farmland'],
    ['glacier', 'Glacier'],
    ['buildings', 'Buildings'],
    ['roads', 'Roads']
];

// Shared mutable copy of ELEMENT_STATES so a click anywhere (this strip, or
// a card in the Settings modal's Elements tab) can repaint every element
// showing that key at once, not just the control that was clicked. Fire-
// and-forget/optimistic like the rest of this page's Blender round-trips:
// the actual scene property change happens on Blender's main thread the
// next time the picker's modal timer ticks (TP3D_OT_*.modal's
// drain_pending_toggles poll / utils.apply_element_toggle), which this
// page has no way to await -- but since a toggle only ever flips the same
// bit this page already computed ELEMENT_STATES from, the optimistic
// guess always matches what Blender ends up doing.
var TP3D_ELEMENT_STATE = {};
ELEMENT_STATUS_ORDER.forEach(function(entry) { TP3D_ELEMENT_STATE[entry[0]] = !!ELEMENT_STATES[entry[0]]; });

// Mirrors utils.generation._ELEMENT_COMPOSITE_FLAGS -- 'water' and 'roads'
// are each an OR of several independent sub-checkboxes with no single
// master flag on the scene PropertyGroup, so a chip/card-icon click needs
// to pick a sub-flag to actually turn on/off. Kept in sync with that Python
// dict by hand (it's small and rarely changes); ADVANCED_SETTINGS_STATE
// keys here are the camelCase versions of its snake_case attr names, same
// convention as COMPOSITE_ELEMENTS in settings_modal.js.
var TP3D_COMPOSITE_FLAGS = {
    water: { subflags: ['colWPondsActive', 'colWSmallRiversActive', 'colWBigRiversActive', 'elOActive'], bootstrap: 'colWPondsActive' },
    roads: { subflags: ['elSBigActive', 'elSMedActive', 'elSSmallActive', 'elSServiceActive', 'elSFootwaysActive'], bootstrap: 'elSSmallActive' }
};

function tp3dCompositeIsActive(key) {
    var def = TP3D_COMPOSITE_FLAGS[key];
    return !!def && typeof ADVANCED_SETTINGS_STATE !== 'undefined'
        && def.subflags.some(function(f) { return !!ADVANCED_SETTINGS_STATE[f]; });
}

// Repaints every element with data-element-toggle="key" (this strip's chip
// and/or the modal's card icon, whichever are currently in the DOM).
function tp3dRepaintElementToggle(key) {
    var enabled = !!TP3D_ELEMENT_STATE[key];
    document.querySelectorAll('[data-element-toggle="' + key + '"]').forEach(function(el) {
        el.classList.toggle('enabled', enabled);
        el.classList.toggle('disabled', !enabled);
    });
}

// Repaints a composite category's own sub-checkbox inputs (in the Settings
// modal's Elements tab, if currently built) to match ADVANCED_SETTINGS_STATE
// -- live + editable while the category is on, or showing its remembered
// combo greyed out + locked while it's off. That tab is built once and
// never re-rendered (see tp3dBuildElementsTab), so this has to reach into
// the DOM directly rather than relying on a rebuild.
function tp3dRepaintCompositeCheckboxes(key) {
    var def = TP3D_COMPOSITE_FLAGS[key];
    if (!def || typeof ADVANCED_SETTINGS_STATE === 'undefined') return;
    var active = tp3dCompositeIsActive(key);
    var remembered = (ADVANCED_SETTINGS_STATE._compositeRemembered || {})[key] || {};
    def.subflags.forEach(function(f) {
        var checked = active ? !!ADVANCED_SETTINGS_STATE[f] : !!remembered[f];
        document.querySelectorAll('[data-advanced-checkbox="' + f + '"]').forEach(function(el) {
            el.checked = checked;
            el.disabled = !active;
            if (el.closest('label')) el.closest('label').classList.toggle('locked', !active);
        });
    });
}

// Predicts what utils.apply_element_toggle will do server-side for a
// composite category -- same remember-on-off / restore-on-on logic, kept
// in ADVANCED_SETTINGS_STATE._compositeRemembered so a fresh page load and
// a same-session chip click agree -- and applies it optimistically to
// ADVANCED_SETTINGS_STATE + the modal's checkboxes.
function tp3dToggleElement(key) {
    TP3D_ELEMENT_STATE[key] = !TP3D_ELEMENT_STATE[key];
    tp3dRepaintElementToggle(key);

    var def = TP3D_COMPOSITE_FLAGS[key];
    if (def && typeof ADVANCED_SETTINGS_STATE !== 'undefined') {
        ADVANCED_SETTINGS_STATE._compositeRemembered = ADVANCED_SETTINGS_STATE._compositeRemembered || {};
        if (tp3dCompositeIsActive(key)) {
            var snapshot = {};
            def.subflags.forEach(function(f) { snapshot[f] = !!ADVANCED_SETTINGS_STATE[f]; });
            ADVANCED_SETTINGS_STATE._compositeRemembered[key] = snapshot;
            def.subflags.forEach(function(f) { ADVANCED_SETTINGS_STATE[f] = false; });
        } else {
            var remembered = ADVANCED_SETTINGS_STATE._compositeRemembered[key] || {};
            var hasRemembered = def.subflags.some(function(f) { return !!remembered[f]; });
            if (hasRemembered) {
                def.subflags.forEach(function(f) { ADVANCED_SETTINGS_STATE[f] = !!remembered[f]; });
            } else {
                ADVANCED_SETTINGS_STATE[def.bootstrap] = true;
            }
        }
        tp3dRepaintCompositeCheckboxes(key);
    }

    fetch('http://127.0.0.1:' + PORT + '/toggle_element', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: key })
    }).catch(function() {});
}

(function renderElementStatus() {
    var container = document.getElementById('elementStatus');
    if (!container) return;

    ELEMENT_STATUS_ORDER.forEach(function(entry) {
        var key = entry[0], label = entry[1];
        var svg = ELEMENT_ICONS[key];
        if (!svg) return;
        var chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'element-chip';
        chip.setAttribute('data-element-toggle', key);
        var iconWrap = document.createElement('span');
        iconWrap.className = 'element-icon';
        iconWrap.innerHTML = svg;
        chip.appendChild(iconWrap);
        var labelEl = document.createElement('span');
        labelEl.className = 'element-label';
        labelEl.textContent = label;
        chip.appendChild(labelEl);
        chip.title = label + ' (click to toggle)';

        chip.addEventListener('click', function() { tp3dToggleElement(key); });
        container.appendChild(chip);
        tp3dRepaintElementToggle(key);
    });
})();
