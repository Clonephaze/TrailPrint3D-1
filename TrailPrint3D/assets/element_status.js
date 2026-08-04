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

// Repaints every element with data-element-toggle="key" (this strip's chip
// and/or the modal's card icon, whichever are currently in the DOM).
function tp3dRepaintElementToggle(key) {
    var enabled = !!TP3D_ELEMENT_STATE[key];
    document.querySelectorAll('[data-element-toggle="' + key + '"]').forEach(function(el) {
        el.classList.toggle('enabled', enabled);
        el.classList.toggle('disabled', !enabled);
    });
}

function tp3dToggleElement(key) {
    TP3D_ELEMENT_STATE[key] = !TP3D_ELEMENT_STATE[key];
    tp3dRepaintElementToggle(key);
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
