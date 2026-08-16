// Builds the "⚙️ Settings" button (appended into #elementStatus) and the
// popup it opens -- reused by every 2D-map picker page via
// __SETTINGS_MODAL_JS__ in picker_server.py. Requires PORT, SETTINGS_STATE
// (from __SETTINGS_STATE_JS__), ADVANCED_SETTINGS_STATE (from
// __ADVANCED_SETTINGS_STATE_JS__), ELEMENT_ICONS (from
// __ELEMENT_ICONS_JS__) and the shared toggle helpers TP3D_ELEMENT_STATE /
// tp3dToggleElement / tp3dRepaintElementToggle (from element_status.js,
// which must run first) to already be defined. Entirely self-contained --
// none of the 3 picker pages need any of this markup in their own HTML.
//
// Two tabs:
//  - Map: the handful of generation-wide fields that don't belong to any
//    one element category (Elevation Scale, Path Thickness, ...).
//  - Elements: every element category's individual sub-checkboxes and
//    per-category thresholds, grouped as cards -- the "much more detailed"
//    breakdown behind each #elementStatus chip's single on/off summary.
//    A simple category (Forest, Buildings, ...) is one card with its own
//    toggle icon and threshold field(s); Water and Roads are wider
//    composite cards with a checklist of sub-flags plus their own number
//    fields, alongside the same quick toggle icon.
//
// The right-hand panel shows a per-feature preview GIF/image when a field
// with a `preview` URL is clicked (tp3dShowPreview) -- most fields don't
// have one yet and stay plain text, not clickable.
//
// Which tab (Map/Elements) was last open is tracked in TP3D_SETTINGS_TAB and
// switchable from outside via tp3dActivateSettingsTab -- this file doesn't
// persist it anywhere itself (it's shared across all 3 pages and doesn't
// know their own saveState()/restoreState() shape), but each page's own
// saveState() can read TP3D_SETTINGS_TAB into its existing state blob, and
// its restoreState() can call tp3dActivateSettingsTab(s.settingsTab) once
// fetched, the same way it already restores the base layer, form fields, etc.
var TP3D_SETTINGS_TAB = 'elements';

// Resolution deliberately isn't in this list -- every picker page already
// has its own page-level #resolutionSlider (outside this modal), and that's
// the one the /confirm handler actually applies (see operators.py: it
// overwrites props.num_subdivisions from the payload's own 'resolution' at
// Send time regardless of anything pushed live via this modal). Having both
// meant two controls for one setting that could silently disagree.
var SETTINGS_MODAL_MAP_FIELDS = [
    { key: 'scaleElevation', source: 'SETTINGS_STATE', endpoint: 'update_setting',
      label: 'Elevation Scale', type: 'number', step: 0.1, min: 0,
      title: 'Multiplier to the Elevation',
      preview: 'https://trailprint3d.com/images/howto/installation/ElevationScaleGif.webp' },
    // Divider: spans both grid columns (see tp3dBuildMapTab/.map-tab-divider),
    // separating the map-wide fields above from the trail-specific ones below.
    { type: 'divider' },
    { key: 'pathThickness', source: 'SETTINGS_STATE', endpoint: 'update_setting',
      label: 'Trail Thickness', type: 'number', step: 0.01, min: 0.1, max: 5, decimals: 2,
      title: 'Thickness of the path in mm',
      preview: 'https://trailprint3d.com/images/howto/installation/PathThicknessGif.webp' },
    { key: 'overwritePathElevation', source: 'SETTINGS_STATE', endpoint: 'update_setting',
      label: 'Snap Trail to Terrain', type: 'checkbox',
      title: 'Cast each point of the trail onto the Terrain Mesh',
      preview: 'https://trailprint3d.com/images/AddonHowto/SnapTrailToTerrain.jpg',
      previewCaption: [
          'GPX files usually have their own elevation data.. But sometimes they dont and sometimes they have their values from diffrent datasets.',
          'To make sure the Trail and Terrain match perfectly, enable this to Snap each point of the Trail to the Terrain'
      ] },
    { key: 'singleColorMode', source: 'SETTINGS_STATE', endpoint: 'update_setting',
      label: 'SingleColorMode Trail', type: 'checkbox',
      title: 'Enable this if you don\'t have a Multicolor printer',
      preview: 'https://trailprint3d.com/images/howto/installation/SingleColorTrail.webp' },
    { key: 'singleColorModeTolerance', source: 'SETTINGS_STATE', endpoint: 'update_setting',
      label: 'SingleColorMode Tolerance', type: 'number', step: 0.05, min: 0,
      title: 'Tolerance of the Trail for the SingleColorMode' }
];

// { label, preview? } per element card -- preview is optional, add a URL
// here to make that card's title clickable too, same as any other field.
var ELEMENT_CARD_LABELS = {
    water: { label: 'Water' },
    forest: { label: 'Forest' },
    scree: { label: 'Scree' },
    city: { label: 'City Boundaries' },
    greenspace: { label: 'Greenspace' },
    farmland: { label: 'Farmland' },
    glacier: { label: 'Glacier' },
    buildings: { label: 'Buildings' },
    roads: { label: 'Roads' }
};

// 'buildings' is deliberately left out -- it's rendered as a simple card
// too (see tp3dBuildSimpleElementCard), just appended to the composite row
// instead (tp3dBuildElementsTab), sitting to the right of Roads rather
// than crowding the small single-field cards up top.
var SIMPLE_ELEMENT_ORDER = ['forest', 'scree', 'city', 'greenspace', 'farmland', 'glacier'];
var SIMPLE_ELEMENT_FIELDS = {
    forest: [{ key: 'colFArea', label: 'Area Threshold', step: 0.5, min: 0 }],
    scree: [{ key: 'colScrArea', label: 'Area Threshold', step: 0.5, min: 0 }],
    city: [{ key: 'colCArea', label: 'Area Threshold', step: 0.5, min: 0 }],
    greenspace: [{ key: 'colGrArea', label: 'Area Threshold', step: 0.5, min: 0 }],
    farmland: [{ key: 'colFaArea', label: 'Area Threshold', step: 0.5, min: 0 }],
    glacier: [{ key: 'colGlArea', label: 'Area Threshold', step: 0.5, min: 0 }],
    buildings: [
        { key: 'elBHeightMultiplier', label: 'Height Multiplier', step: 0.1, min: 0.01 },
        { key: 'elBMinPrintMM', label: 'Min Footprint (mm)', step: 0.01, min: 0 }
    ]
};

var COMPOSITE_ELEMENT_ORDER = ['water', 'roads'];
var COMPOSITE_ELEMENTS = {
    water: {
        checkboxes: [
            { key: 'colWPondsActive', label: 'Ponds & Lakes' },
            { key: 'colWSmallRiversActive', label: 'Small Rivers' },
            { key: 'colWBigRiversActive', label: 'Big Rivers' },
            { key: 'elOActive', label: 'Ocean' }
        ],
        numberFields: [
            { key: 'colWArea', label: 'Lake/Pond Threshold', step: 0.1, min: 0 },
            { key: 'colWStreamWidth', label: 'River Width', step: 0.1, min: 0.1, max: 10 },
            { key: 'elOMinIslandArea', label: 'Min Island Area', step: 0.5, min: 0 },
            { key: 'elORdpEpsilon', label: 'Coastline Simplify', step: 0.01, min: 0, max: 2 }
        ]
    },
    roads: {
        checkboxes: [
            { key: 'elSBigActive', label: 'Big Roads' },
            { key: 'elSMedActive', label: 'Medium Roads' },
            { key: 'elSSmallActive', label: 'Small Roads' },
            { key: 'elSServiceActive', label: 'Service Roads' },
            { key: 'elSFootwaysActive', label: 'Footways/Sidewalks' }
        ],
        numberFields: [
            { key: 'elSMultiplier', label: 'Width Multiplier', step: 0.1, min: 0 },
            { key: 'elSHeight', label: 'Height', step: 0.05, min: 0 },
            { key: 'elSCutTolerance', label: 'Cut Tolerance', step: 0.05, min: 0 }
        ]
    }
};

function tp3dSendAdvancedUpdate(key, value) {
    fetch('http://127.0.0.1:' + PORT + '/update_advanced_setting', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: key, value: value })
    }).catch(function() {});
}

function tp3dShowPreview(url, caption) {
    var panel = document.getElementById('settingsPreviewPanel');
    if (!panel) return;
    // Grows the whole box open (see .settings-modal-box.preview-active) the
    // first time this runs -- harmless to call again on later clicks, the
    // class is already there and classList.add is a no-op.
    var box = panel.closest('.settings-modal-box');
    if (box) box.classList.add('preview-active');
    panel.innerHTML = '';
    var img = document.createElement('img');
    img.src = url;
    img.alt = 'Preview';
    panel.appendChild(img);

    // caption is optional -- a single string or an array of lines, shown
    // stacked below the image.
    if (caption) {
        var lines = Array.isArray(caption) ? caption : [caption];
        var captionEl = document.createElement('div');
        captionEl.className = 'preview-caption';
        lines.forEach(function(line) {
            var lineEl = document.createElement('div');
            lineEl.textContent = line;
            captionEl.appendChild(lineEl);
        });
        panel.appendChild(captionEl);
    }

    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'preview-close-btn';
    closeBtn.title = 'Close preview';
    closeBtn.textContent = '✕';
    closeBtn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        tp3dHidePreview();
    });
    panel.appendChild(closeBtn);
}

function tp3dHidePreview() {
    var panel = document.getElementById('settingsPreviewPanel');
    if (!panel) return;
    var box = panel.closest('.settings-modal-box');
    if (box) box.classList.remove('preview-active');
    panel.innerHTML = '';
    panel.textContent = 'Click a highlighted setting to preview it here';
}

// A standalone icon button that shows *url* in the preview panel --
// standalone (never nested inside a <label>) so it's safe to drop next to
// ANY control, including a checkbox's own label, without its click also
// forwarding to that control.
function tp3dMakePreviewButton(url, caption) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'preview-btn';
    btn.title = 'Click to preview';
    btn.textContent = '?';
    btn.addEventListener('click', function(e) {
        e.preventDefault();
        e.stopPropagation();
        tp3dShowPreview(url, caption);
    });
    return btn;
}

// The one reusable building block behind "make X clickable to preview a
// GIF": wraps *el* together with a preview button when *url* is set, or
// just returns *el* unchanged otherwise. Every field builder below calls
// this on its label/title element -- so adding a preview to any field,
// checkbox, or card title anywhere in this modal is just adding a
// `preview: 'url'` property (plus an optional `previewCaption`, a string
// or array of lines shown below the image) to its definition, nothing
// else changes.
function tp3dWithPreview(el, url, caption) {
    if (!url) return el;
    var wrap = document.createElement('span');
    wrap.className = 'preview-wrap';
    wrap.appendChild(el);
    wrap.appendChild(tp3dMakePreviewButton(url, caption));
    return wrap;
}

// Blender's FloatProperty is a 32-bit float internally, so a clean value
// like 1.3 can round-trip back as 1.2999999523... -- shown raw in a number
// input, a string that long can force its CSS grid cell to grow past its
// column (that's what "the box sticks out past the border" actually was).
// Rounds to *decimals* (falling back to a generous default that trims
// float32 noise without eating real precision) any time a value from
// SETTINGS_STATE/ADVANCED_SETTINGS_STATE is used to populate a field, so
// this can't recur on any numeric field, not just ones with an explicit
// `decimals` set.
function tp3dRoundForDisplay(value, decimals) {
    if (typeof value !== 'number' || isNaN(value)) return value;
    return parseFloat(value.toFixed(decimals != null ? decimals : 4));
}

function tp3dBuildNumberField(field) {
    var wrap = document.createElement('div');
    wrap.className = 'card-field';
    wrap.title = field.title || '';
    var label = document.createElement('label');
    label.textContent = field.label;
    var input = document.createElement('input');
    input.type = 'number';
    if (field.step != null) input.step = field.step;
    if (field.min != null) input.min = field.min;
    if (field.max != null) input.max = field.max;
    input.value = tp3dRoundForDisplay(ADVANCED_SETTINGS_STATE[field.key], field.decimals);
    input.addEventListener('change', function() {
        tp3dSendAdvancedUpdate(field.key, parseFloat(input.value));
    });
    wrap.appendChild(tp3dWithPreview(label, field.preview, field.previewCaption));
    wrap.appendChild(input);
    return wrap;
}

// *compositeKey*, when given, marks this checkbox as one of a composite
// category's own sub-flags (see TP3D_COMPOSITE_FLAGS in element_status.js)
// -- while that category is off, the checkbox shows its remembered value
// (ADVANCED_SETTINGS_STATE._compositeRemembered, from
// utils.build_composite_remembered_state) instead of the live False, and
// is locked (disabled) rather than editable. A field not present in that
// category's remembered map is never locked, same as a plain checkbox.
function tp3dBuildCheckboxField(field, compositeKey) {
    var label = document.createElement('label');
    label.title = field.title || '';
    var input = document.createElement('input');
    input.type = 'checkbox';
    input.setAttribute('data-advanced-checkbox', field.key);
    var remembered = compositeKey ? ((ADVANCED_SETTINGS_STATE._compositeRemembered || {})[compositeKey] || {}) : {};
    var locked = compositeKey && !tp3dCompositeIsActive(compositeKey) && remembered.hasOwnProperty(field.key);
    input.checked = locked ? !!remembered[field.key] : !!ADVANCED_SETTINGS_STATE[field.key];
    input.disabled = locked;
    if (locked) label.classList.add('locked');
    input.addEventListener('change', function() {
        tp3dSendAdvancedUpdate(field.key, input.checked);
    });
    label.appendChild(input);
    label.appendChild(document.createTextNode(field.label));
    return tp3dWithPreview(label, field.preview, field.previewCaption);
}

function tp3dBuildSimpleElementCard(key) {
    var meta = ELEMENT_CARD_LABELS[key] || { label: key };
    var card = document.createElement('div');
    card.className = 'element-card';

    var icon = document.createElement('span');
    icon.className = 'card-icon';
    icon.setAttribute('data-element-toggle', key);
    icon.innerHTML = ELEMENT_ICONS[key] || '';
    icon.title = meta.label + ' (click to toggle)';
    icon.addEventListener('click', function() { tp3dToggleElement(key); });
    card.appendChild(icon);

    var label = document.createElement('div');
    label.className = 'card-label';
    label.textContent = meta.label;
    card.appendChild(tp3dWithPreview(label, meta.preview, meta.previewCaption));

    (SIMPLE_ELEMENT_FIELDS[key] || []).forEach(function(field) {
        card.appendChild(tp3dBuildNumberField(field));
    });

    tp3dRepaintElementToggle(key);
    return card;
}

function tp3dBuildCompositeElementCard(key) {
    var def = COMPOSITE_ELEMENTS[key];
    var meta = ELEMENT_CARD_LABELS[key] || { label: key };
    var card = document.createElement('div');
    card.className = 'element-card composite';

    var head = document.createElement('div');
    head.className = 'card-head';
    var icon = document.createElement('span');
    icon.className = 'card-icon';
    icon.setAttribute('data-element-toggle', key);
    icon.innerHTML = ELEMENT_ICONS[key] || '';
    icon.title = meta.label + ' (click to toggle all)';
    icon.addEventListener('click', function() { tp3dToggleElement(key); });
    var label = document.createElement('div');
    label.className = 'card-label';
    label.textContent = meta.label;
    head.appendChild(icon);
    head.appendChild(tp3dWithPreview(label, meta.preview, meta.previewCaption));
    card.appendChild(head);

    var checklist = document.createElement('div');
    checklist.className = 'card-checklist';
    def.checkboxes.forEach(function(field) { checklist.appendChild(tp3dBuildCheckboxField(field, key)); });
    card.appendChild(checklist);

    def.numberFields.forEach(function(field) { card.appendChild(tp3dBuildNumberField(field)); });

    tp3dRepaintElementToggle(key);
    return card;
}

function tp3dSendMapField(field, value) {
    fetch('http://127.0.0.1:' + PORT + '/' + field.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: field.key, value: value })
    }).catch(function() {});
}

// A range slider paired with a number input that shares its value --
// dragging the slider can't exceed field.max, but typing into the number
// box can, for fields (like Resolution) where the common range fits a
// slider but an occasional larger value should still be reachable without
// raising the slider's own max (which would make every-day dragging less
// precise).
function tp3dBuildRangeField(field, stateObj) {
    var controls = document.createElement('div');
    controls.className = 'range-with-number';

    var initial = tp3dRoundForDisplay(stateObj[field.key], field.decimals);

    var range = document.createElement('input');
    range.type = 'range';
    range.min = field.min;
    range.max = field.max;
    range.step = field.step || 1;
    range.value = Math.min(initial, field.max);

    var number = document.createElement('input');
    number.type = 'number';
    number.min = field.min;
    number.step = field.step || 1;
    number.value = initial;

    range.addEventListener('input', function() {
        number.value = range.value;
        tp3dSendMapField(field, parseFloat(range.value));
    });
    number.addEventListener('change', function() {
        var value = parseFloat(number.value);
        if (isNaN(value)) return;
        range.value = Math.min(Math.max(value, field.min), field.max);
        tp3dSendMapField(field, value);
    });

    controls.appendChild(range);
    controls.appendChild(number);
    return controls;
}

function tp3dBuildMapTab() {
    var wrap = document.createElement('div');
    wrap.className = 'map-tab-fields';
    SETTINGS_MODAL_MAP_FIELDS.forEach(function(field) {
        if (field.type === 'divider') {
            var hr = document.createElement('hr');
            hr.className = 'map-tab-divider';
            wrap.appendChild(hr);
            return;
        }

        var row = document.createElement('div');
        row.className = 'adv-field-row';
        row.title = field.title || '';

        var label = document.createElement('label');
        label.textContent = field.label;
        var stateObj = field.source === 'SETTINGS_STATE' ? SETTINGS_STATE : ADVANCED_SETTINGS_STATE;

        if (field.type === 'range') {
            row.appendChild(tp3dWithPreview(label, field.preview, field.previewCaption));
            row.appendChild(tp3dBuildRangeField(field, stateObj));
            wrap.appendChild(row);
            return;
        }

        var input = document.createElement('input');
        input.type = field.type;
        if (field.type === 'number') {
            if (field.step != null) input.step = field.step;
            if (field.min != null) input.min = field.min;
            if (field.max != null) input.max = field.max;
            input.value = tp3dRoundForDisplay(stateObj[field.key], field.decimals);
        } else {
            input.checked = !!stateObj[field.key];
        }
        input.addEventListener('change', function() {
            var value = field.type === 'checkbox' ? input.checked : parseFloat(input.value);
            if (field.decimals != null && typeof value === 'number') {
                value = parseFloat(value.toFixed(field.decimals));
                input.value = value;
            }
            tp3dSendMapField(field, value);
        });

        row.appendChild(tp3dWithPreview(label, field.preview, field.previewCaption));
        row.appendChild(input);
        wrap.appendChild(row);
    });
    return wrap;
}

function tp3dBuildElementsTab() {
    var wrap = document.createElement('div');
    wrap.className = 'elements-grid';

    var simpleRow = document.createElement('div');
    simpleRow.className = 'elements-row';
    SIMPLE_ELEMENT_ORDER.forEach(function(key) { simpleRow.appendChild(tp3dBuildSimpleElementCard(key)); });
    wrap.appendChild(simpleRow);

    var compositeRow = document.createElement('div');
    compositeRow.className = 'elements-row';
    COMPOSITE_ELEMENT_ORDER.forEach(function(key) { compositeRow.appendChild(tp3dBuildCompositeElementCard(key)); });
    compositeRow.appendChild(tp3dBuildSimpleElementCard('buildings'));
    wrap.appendChild(compositeRow);

    return wrap;
}

// Relocates the puzzle-cut field-rows (Tab Size, Jitter, Seed, Corner Radius)
// out of their hidden sidebar container into this tab -- same elements, same
// ids, so the page's own saveState/restoreState/regeneratePuzzle listeners
// keep working unchanged regardless of where they end up living in the DOM.
function tp3dBuildPuzzleTab() {
    var wrap = document.createElement('div');
    wrap.className = 'map-tab-fields';
    var source = document.getElementById('puzzleTabFieldsSource');
    if (source) {
        while (source.firstElementChild) {
            wrap.appendChild(source.firstElementChild);
        }
    }
    return wrap;
}

(function renderSettingsModal() {
    var elementStatus = document.getElementById('elementStatus');
    if (!elementStatus) return;

    var modal = document.createElement('div');
    modal.className = 'tp3d-modal';
    modal.id = 'settingsModal';

    var box = document.createElement('div');
    box.className = 'tp3d-modal-box settings-modal-box';
    modal.appendChild(box);

    var header = document.createElement('div');
    header.className = 'modal-header';
    var title = document.createElement('span');
    title.textContent = 'Advanced Settings';
    var closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'tp3d-modal-close-btn';
    closeBtn.title = 'Close';
    closeBtn.textContent = '✕';
    header.appendChild(title);
    header.appendChild(closeBtn);
    box.appendChild(header);

    var body = document.createElement('div');
    body.className = 'settings-modal-body';
    box.appendChild(body);

    var left = document.createElement('div');
    left.className = 'settings-modal-left';
    var tabBar = document.createElement('div');
    tabBar.className = 'settings-modal-tabs';
    var panelHost = document.createElement('div');
    panelHost.style.flex = '1';
    panelHost.style.minHeight = '0';
    panelHost.style.display = 'flex';
    left.appendChild(tabBar);
    left.appendChild(panelHost);
    body.appendChild(left);

    // Shows a per-feature preview GIF/image once a field with a `preview`
    // URL is clicked (tp3dShowPreview) -- most fields don't have one yet
    // and this just stays on its placeholder text.
    var right = document.createElement('div');
    right.className = 'settings-modal-right';
    right.id = 'settingsPreviewPanel';
    right.textContent = 'Click a highlighted setting to preview it here';
    body.appendChild(right);

    var TABS = [
        { id: 'elements', label: 'Elements', build: tp3dBuildElementsTab },
        { id: 'map', label: 'Map', build: tp3dBuildMapTab }
    ];
    if (typeof TP3D_IS_PUZZLE_PAGE !== 'undefined' && TP3D_IS_PUZZLE_PAGE) {
        TABS.push({ id: 'puzzle', label: 'Puzzle', build: tp3dBuildPuzzleTab });
    }
    var panels = {};
    var tabBtns = {};

    function activateTab(id) {
        if (!tabBtns[id]) return;
        TP3D_SETTINGS_TAB = id;
        TABS.forEach(function(tab) {
            tabBtns[tab.id].classList.toggle('active', tab.id === id);
            panels[tab.id].classList.toggle('active', tab.id === id);
        });
    }
    // Global hook so each page's own restoreState() can put the popup back
    // on whichever tab was last open, once it fetches the saved state.
    window.tp3dActivateSettingsTab = activateTab;

    TABS.forEach(function(tab) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'settings-modal-tab-btn';
        var arrow = document.createElement('span');
        arrow.className = 'tab-arrow';
        arrow.textContent = '▶';
        btn.appendChild(arrow);
        btn.appendChild(document.createTextNode(' ' + tab.label));
        btn.addEventListener('click', function() {
            activateTab(tab.id);
            saveState(); // persists TP3D_SETTINGS_TAB via the page's own state blob
        });
        tabBar.appendChild(btn);
        tabBtns[tab.id] = btn;

        var panel = document.createElement('div');
        panel.className = 'settings-modal-tab-panel';
        panel.style.width = '100%';
        panel.appendChild(tab.build());
        panelHost.appendChild(panel);
        panels[tab.id] = panel;
    });
    activateTab('elements');

    document.body.appendChild(modal);

    function openModal() { modal.classList.add('open'); }
    function closeModal() { modal.classList.remove('open'); }
    closeBtn.addEventListener('click', closeModal);
    modal.addEventListener('click', function(e) { if (e.target === modal) closeModal(); });

    var gearBtn = document.createElement('button');
    gearBtn.type = 'button';
    gearBtn.className = 'settings-gear-btn';
    gearBtn.title = 'More generation settings';
    gearBtn.innerHTML = '⚙️ <span>Settings</span>';
    gearBtn.addEventListener('click', openModal);
    elementStatus.insertBefore(gearBtn, elementStatus.firstChild);
})();
