// Shape Extras button groups (Plate/Shell + Text Layout) and inline settings,
// shared by the map generator pages (map_generator.html,
// premium/map_generator_pe.html). Mirrors panels.py's own "Shape Extras" box
// and utils.shape_capabilities' PLATE_MODES_BY_SHAPE/TEXT_LAYOUTS_BY_SHAPE/
// valid_layouts -- which extras a shape offers, and which text layouts a
// given plate/shell mode can host, comes from those tables.
//
// The two selections are page state (saved with the page's own saveState
// snapshot and sent in the /confirm payload as 'plate_mode'/'text_layout',
// applied Blender-side only once props.shape is set -- both item lists
// depend on it, see operators.py's TP3D_OT_map_generator._apply_shape_extra).
// Every popup field is a plain scene property instead, pushed live through
// /update_setting (utils.ui_state._SETTINGS_ROW_FIELDS) and read back from
// SETTINGS_STATE, same as the Settings popup's Map tab.
//
// Expects the page to define currentShape, geojsonPaths, svgShapePath, PORT,
// SETTINGS_STATE, saveState(), clearSvgShapeImport() (rect_editor.js) and
// TP3D_SHAPE_EXTRAS_PREMIUM before this runs, plus an empty
// #shapeExtrasSection, #importGeojson, #clearGeojson and #importSvgShape in
// the sidebar. Call tp3dRefreshShapeExtras() whenever the shape or the
// GeoJSON/SVG import changes -- it also updates which shape is highlighted.

// Keyed by the page's own data-shape values ('rectangle'/'square' both map
// to SQUARE Blender-side, see TP3D_OT_map_generator._TYPE_MAP). An imported
// 'svg' / 'geojson' outline (see tp3dSelectedShape) has no entry, so the
// section hides for it: the text/plate extras are drawn for one specific
// regular shape, and Shell (utils_pe.build_map_shell) only supports convex
// outlines, which an imported one often isn't.
// Mirrors utils.shape_capabilities.PLATE_MODES_BY_SHAPE.
var PLATE_MODES_BY_SHAPE = {
    hexagon: ['NONE', 'SOLID_PLATE', 'SHELL'],
    octagon: ['NONE', 'SOLID_PLATE', 'SHELL'],
    circle: ['NONE', 'SOLID_PLATE', 'SHELL'],
    square: ['NONE', 'SOLID_PLATE', 'SHELL'],
    rectangle: ['NONE', 'SOLID_PLATE', 'SHELL']
};
// Mirrors utils.shape_capabilities.TEXT_LAYOUTS_BY_SHAPE.
var TEXT_LAYOUTS_BY_SHAPE = {
    hexagon: ['NONE', 'ON_MAP', 'OUTER_EDGE', 'FRONT_FACE'],
    octagon: ['NONE', 'OUTER_EDGE', 'FRONT_FACE'],
    circle: ['NONE', 'CURVED'],
    square: ['NONE', 'OUTER_EDGE', 'FRONT_FACE'],
    rectangle: ['NONE', 'OUTER_EDGE', 'FRONT_FACE']
};
// Mirrors utils.shape_capabilities._LAYOUTS_BY_PLATE_MODE.
var LAYOUTS_BY_PLATE_MODE = {
    NONE: { NONE: true, ON_MAP: true },
    SOLID_PLATE: { NONE: true, ON_MAP: true, OUTER_EDGE: true, FRONT_FACE: true, CURVED: true },
    SHELL: { NONE: true, ON_MAP: true, FRONT_FACE: true }
};
var LAYOUTS_REQUIRING_PLATE = { OUTER_EDGE: true, FRONT_FACE: true, CURVED: true };
var PLATE_LABELS = { NONE: 'None', SOLID_PLATE: 'Solid Plate', SHELL: 'Shell' };
var LAYOUT_LABELS = { NONE: 'None', ON_MAP: 'On Map', OUTER_EDGE: 'Outer Edge', FRONT_FACE: 'Front Face', CURVED: 'Curved' };

// Mirrors utils.text_layouts' *_FIELDS tables + _FIELD_TO_PROP/fields_for_layout,
// in the same physical (counter-clockwise) order.
var TEXT_FIELDS_BY_LAYOUT_SHAPE = {
    OUTER_EDGE: {
        HEXAGON: ['titlefield', 'textfield5', 'textfield1', 'textfield2', 'textfield3', 'textfield4'],
        OCTAGON: ['titlefield', 'textfield5', 'textfield6', 'textfield1', 'textfield2', 'textfield3', 'textfield7', 'textfield4'],
        SQUARE: ['titlefield', 'textfield1', 'textfield2', 'textfield3']
    },
    FRONT_FACE: {
        HEXAGON: ['titlefield', 'textfield1', 'textfield2', 'textfield3'],
        OCTAGON: ['titlefield', 'textfield1', 'textfield2', 'textfield3'],
        SQUARE: ['titlefield', 'textfield1', 'textfield2', 'textfield3']
    },
    CURVED: {
        CIRCLE: ['titlefield', 'textfield1', 'textfield2', 'textfield3']
    },
    ON_MAP: {
        HEXAGON: ['titlefield', 'textfield1', 'textfield2', 'textfield3']
    }
};
var FIELD_TO_ICON = {
    titlefield: 'titleIcon', textfield1: 'iconText1', textfield2: 'iconText2',
    textfield3: 'iconText3', textfield4: 'iconText4', textfield5: 'iconText5',
    textfield6: 'iconText6', textfield7: 'iconText7'
};

var SHAPE_EXTRA_TITLE_ICONS = [
    ['cycling', 'Cycling'], ['hiking', 'Hiking'], ['running', 'Running'], ['swimming', 'Swimming'],
    ['skiing', 'Skiing'], ['snowboarding', 'Snowboarding'], ['kajak', 'Kayak'], ['no', 'No Icon']
];
var SHAPE_EXTRA_TEXT_ICONS = [
    ['distance', 'Distance'], ['elevation', 'Elevation'], ['time', 'Time'],
    ['speed', 'Speed'], ['date', 'Date'], ['no', 'No Icon']
];

var plateMode = 'NONE';
var textLayout = 'NONE';

// What's actually selected: an imported GeoJSON boundary replaces the drawn
// shape outright (operators.py builds the tile from it whenever one is
// loaded), otherwise the current shape -- 'svg' after an SVG import.
function tp3dSelectedShape() {
    return (geojsonPaths && geojsonPaths.length) ? 'geojson' : currentShape;
}

function tp3dShapeExtraBase() {
    var s = tp3dSelectedShape();
    if (s === 'rectangle') s = 'square';
    return String(s || '').toUpperCase();
}

// Mirrors utils.shape_capabilities.valid_layouts.
function tp3dValidLayouts(shape, mode) {
    var shapeLayouts = TEXT_LAYOUTS_BY_SHAPE[String(shape).toLowerCase()] || ['NONE'];
    var allowed = LAYOUTS_BY_PLATE_MODE[mode] || LAYOUTS_BY_PLATE_MODE.NONE;
    return shapeLayouts.filter(function(layout) { return allowed[layout]; });
}

// Highlights whichever of the shape buttons / Import GeoJSON / Import SVG
// Shape is the current selection -- only one at a time, like the shape row.
function tp3dSyncShapeSelection() {
    var sel = tp3dSelectedShape();
    document.querySelectorAll('.shape-btn[data-shape]').forEach(function(b) {
        b.classList.toggle('active', b.getAttribute('data-shape') === sel);
    });
    document.getElementById('importGeojson').classList.toggle('import-shape-active', sel === 'geojson');
    document.getElementById('importSvgShape').classList.toggle('import-shape-active', sel === 'svg');
}

function tp3dPushShapeSetting(key, value) {
    SETTINGS_STATE[key] = value;
    fetch('http://127.0.0.1:' + PORT + '/update_setting', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: key, value: value })
    }).catch(function() {});
}

// Installed fonts ([{name, path}]) from /list_fonts, fetched once per page
// (the first scan of the system font folders takes a moment).
var _tp3dFontList = null;
function tp3dLoadFontList() {
    if (!_tp3dFontList) {
        _tp3dFontList = fetch('http://127.0.0.1:' + PORT + '/list_fonts', { cache: 'no-store' })
            .then(function(r) { if (!r.ok) throw new Error(r.status); return r.json(); })
            .catch(function(err) { _tp3dFontList = null; throw err; });
    }
    return _tp3dFontList;
}

function tp3dBuildShapeExtrasSection() {
    var section = document.getElementById('shapeExtrasSection');
    section.innerHTML = '';

    var plateLabel = document.createElement('div');
    plateLabel.className = 'section-label';
    plateLabel.textContent = 'Plate / Shell';
    section.appendChild(plateLabel);

    var plateOptions = document.createElement('div');
    plateOptions.id = 'plateModeOptions';
    plateOptions.className = 'shape-extra-switch';
    plateOptions.setAttribute('role', 'group');
    plateOptions.setAttribute('aria-label', 'Plate or shell');
    section.appendChild(plateOptions);

    var plateSettings = document.createElement('div');
    plateSettings.id = 'plateModeSettings';
    plateSettings.className = 'shape-extra-settings';
    section.appendChild(plateSettings);

    var layoutLabel = document.createElement('div');
    layoutLabel.className = 'section-label';
    layoutLabel.textContent = 'Text Layout';
    section.appendChild(layoutLabel);

    var layoutOptions = document.createElement('div');
    layoutOptions.id = 'textLayoutOptions';
    layoutOptions.className = 'shape-extra-switch';
    layoutOptions.setAttribute('role', 'group');
    layoutOptions.setAttribute('aria-label', 'Text layout');
    section.appendChild(layoutOptions);

    var textSettings = document.createElement('div');
    textSettings.id = 'textLayoutSettings';
    textSettings.className = 'shape-extra-settings';
    section.appendChild(textSettings);

    var handleSettings = document.createElement('div');
    handleSettings.id = 'handleSettings';
    handleSettings.className = 'shape-extra-settings';
    section.appendChild(handleSettings);
}

// Rebuilds both option groups for the current shape, keeping each selection if
// still valid (else None -- same rule as props.shape_update/plate_mode_update),
// and shows the Text Settings button only when a text layout is active.
function tp3dRefreshShapeExtras() {
    tp3dSyncShapeSelection();
    var section = document.getElementById('shapeExtrasSection');
    if (!section) return;
    if (!document.getElementById('plateModeOptions')) tp3dBuildShapeExtrasSection();

    var shape = tp3dShapeExtraBase();
    var validPlates = PLATE_MODES_BY_SHAPE[tp3dSelectedShape()];
    section.style.display = validPlates ? 'flex' : 'none';
    if (!validPlates) return;

    if (validPlates.indexOf(plateMode) === -1 || (plateMode === 'SHELL' && !TP3D_SHAPE_EXTRAS_PREMIUM)) {
        plateMode = 'NONE';
    }
    var validLayouts = tp3dValidLayouts(shape, plateMode);
    if (validLayouts.indexOf(textLayout) === -1) textLayout = 'NONE';

    function renderOptions(container, options, selected, labels, onSelect, disabledOptions) {
        container.innerHTML = '';
        container.classList.toggle('shape-extra-grid', options.length === 4);
        options.forEach(function(ident) {
            var button = document.createElement('button');
            button.type = 'button';
            button.className = 'element-mode-btn' + (ident === selected ? ' active' : '');
            button.textContent = labels[ident];
            button.setAttribute('aria-pressed', ident === selected ? 'true' : 'false');
            button.title = ident === 'SHELL' ? 'Protective shell around the map' : labels[ident];
            if (disabledOptions && disabledOptions[ident]) {
                button.disabled = true;
                button.textContent = '🔒 ' + labels[ident];
                button.title = labels[ident] + ' is a Premium feature';
            }
            button.addEventListener('click', function() { onSelect(ident); });
            container.appendChild(button);
        });
    }

    renderOptions(document.getElementById('plateModeOptions'), validPlates, plateMode, PLATE_LABELS, function(value) {
        plateMode = value;
        tp3dRefreshShapeExtras();
        saveState();
    }, TP3D_SHAPE_EXTRAS_PREMIUM ? null : { SHELL: true });

    renderOptions(document.getElementById('textLayoutOptions'), validLayouts, textLayout, LAYOUT_LABELS, function(value) {
        textLayout = value;
        // Auto-upgrade only for layouts that need a plate to sit on.
        if (LAYOUTS_REQUIRING_PLATE[textLayout] && plateMode === 'NONE') plateMode = 'SOLID_PLATE';
        tp3dRefreshShapeExtras();
        saveState();
    });

    tp3dRenderPlateSettings(document.getElementById('plateModeSettings'));
    tp3dRenderTextSettings(document.getElementById('textLayoutSettings'));
    tp3dRenderHandleSettings(document.getElementById('handleSettings'));
}

function tp3dShapeExtraNumberRow(parent, key, labelText, opts) {
    var row = document.createElement('div');
    row.className = 'field-row';
    var label = document.createElement('label');
    label.textContent = labelText;
    if (opts.title) label.title = opts.title;
    var input = document.createElement('input');
    input.type = 'number';
    input.step = opts.step;
    if (opts.min != null) input.min = opts.min;
    if (opts.max != null) input.max = opts.max;
    if (SETTINGS_STATE[key] != null) input.value = SETTINGS_STATE[key];
    input.addEventListener('change', function() {
        var v = opts.integer ? parseInt(this.value, 10) : parseFloat(this.value);
        if (isNaN(v)) { this.value = SETTINGS_STATE[key]; return; }
        if (opts.min != null) v = Math.max(opts.min, v);
        if (opts.max != null) v = Math.min(opts.max, v);
        this.value = v;
        tp3dPushShapeSetting(key, v);
    });
    row.appendChild(label);
    row.appendChild(input);
    parent.appendChild(row);
}

function tp3dRenderTextSettings(body) {
    body.innerHTML = '';
    var shape = tp3dShapeExtraBase();
    var fields = ((TEXT_FIELDS_BY_LAYOUT_SHAPE[textLayout] || {})[shape]) || [];
    body.style.display = fields.length ? 'flex' : 'none';

    if (fields.length) {
        // Font -- a dropdown of the installed fonts (picker_server.py's
        // /list_fonts; a browser file dialog can't browse the Windows Fonts
        // folder -- it's a shell virtual folder that shows up empty there).
        var fontRow = document.createElement('div');
        fontRow.className = 'field-row';
        var fontLabel = document.createElement('label');
        fontLabel.textContent = 'Font';
        var fontSelect = document.createElement('select');
        fontSelect.className = 'se-font-select';
        function fontOption(name, path) {
            var opt = document.createElement('option');
            opt.value = path;
            opt.textContent = name;
            opt.title = path || 'Default font';
            return opt;
        }
        // Keeps the current font selectable even before/without the list (or
        // when it isn't an installed one), under its file name.
        function ensureFontOption(path) {
            if (!path) return;
            for (var i = 0; i < fontSelect.options.length; i++) {
                if (fontSelect.options[i].value === path) return;
            }
            var label = path.split(/[\\/]/).pop().replace(/\.[^.]+$/, '');
            fontSelect.insertBefore(fontOption(label, path), fontSelect.options[1] || null);
        }
        function syncFontSelect() {
            var current = SETTINGS_STATE.textFont || '';
            ensureFontOption(current);
            fontSelect.value = current;
            fontSelect.title = current || 'Default font';
        }
        fontSelect.appendChild(fontOption('Default font', ''));
        syncFontSelect();
        tp3dLoadFontList().then(function(fonts) {
            var current = SETTINGS_STATE.textFont || '';
            fonts.forEach(function(f) {
                if (f.path !== current) fontSelect.appendChild(fontOption(f.name, f.path));
                else fontSelect.options[1].textContent = f.name;  // real name for the current one
            });
            syncFontSelect();
        }).catch(function() {});
        fontSelect.addEventListener('change', function() {
            tp3dPushShapeSetting('textFont', this.value);
            this.title = this.value || 'Default font';
        });
        fontRow.appendChild(fontLabel);
        fontRow.appendChild(fontSelect);
        body.appendChild(fontRow);

        tp3dShapeExtraNumberRow(body, 'textSizeTitle', 'Title Text Size',
            { step: 1, min: 0, max: 1000, integer: true, title: "Keep 0 to use value from 'Text Size'" });
        tp3dShapeExtraNumberRow(body, 'textSize', 'Text Size', { step: 1, min: 0, max: 1000, integer: true });

        if (textLayout === 'OUTER_EDGE' || textLayout === 'CURVED' || textLayout === 'FRONT_FACE') {
            var insetRow = document.createElement('div');
            insetRow.className = 'field-row';
            var insetLabel = document.createElement('label');
            insetLabel.textContent = 'Inset Text';
            insetLabel.title = 'Carve text into the plate surface instead of raising it';
            var insetInput = document.createElement('input');
            insetInput.type = 'checkbox';
            insetInput.checked = !!SETTINGS_STATE.textPlacement;
            insetInput.addEventListener('change', function() { tp3dPushShapeSetting('textPlacement', this.checked); });
            insetRow.appendChild(insetLabel);
            insetRow.appendChild(insetInput);
            body.appendChild(insetRow);
        }

        var textLabel = document.createElement('div');
        textLabel.className = 'se-section-label';
        textLabel.textContent = 'Text (Goes Counter-Clockwise) ↺';
        body.appendChild(textLabel);

        fields.forEach(function(textProp) {
            var iconProp = FIELD_TO_ICON[textProp];
            var icons = textProp === 'titlefield' ? SHAPE_EXTRA_TITLE_ICONS : SHAPE_EXTRA_TEXT_ICONS;
            var row = document.createElement('div');
            row.className = 'se-text-row';
            if (TP3D_SHAPE_EXTRAS_PREMIUM) {
                var iconSel = document.createElement('select');
                icons.forEach(function(ic) {
                    var opt = document.createElement('option');
                    opt.value = ic[0];
                    opt.textContent = ic[1];
                    iconSel.appendChild(opt);
                });
                iconSel.value = SETTINGS_STATE[iconProp] || 'no';
                iconSel.addEventListener('change', function() { tp3dPushShapeSetting(iconProp, this.value); });
                row.appendChild(iconSel);
            } else {
                var locked = document.createElement('button');
                locked.type = 'button';
                locked.className = 'se-icon-locked';
                locked.disabled = true;
                locked.title = 'Text icons are a Premium feature';
                locked.textContent = '🔒 Icon';
                row.appendChild(locked);
            }
            var textInput = document.createElement('input');
            textInput.type = 'text';
            textInput.value = SETTINGS_STATE[textProp] != null ? SETTINGS_STATE[textProp] : '';
            textInput.title = 'Codes = {name} | {length} | {elevation} | {duration} | {date} | {speed} | {scale}';
            textInput.addEventListener('change', function() { tp3dPushShapeSetting(textProp, this.value); });
            row.appendChild(textInput);
            body.appendChild(row);
        });

        var hint = document.createElement('div');
        hint.className = 'se-hint';
        hint.textContent = 'Codes: {name} {length} {elevation} {duration} {date} {speed} {scale}';
        body.appendChild(hint);
    }

}

function tp3dRenderPlateSettings(body) {
    body.innerHTML = '';
    body.style.display = plateMode === 'NONE' ? 'none' : 'flex';
    if (plateMode === 'NONE') return;

    if (plateMode === 'SOLID_PLATE') {
        tp3dShapeExtraNumberRow(body, 'plateThickness', 'Plate Height (mm)', { step: 0.5 });
        tp3dShapeExtraNumberRow(body, 'outerBorderSize', 'Border Thickness (%)',
            { step: 1, min: 0, max: 1000, integer: true, title: 'How thick the border is, as a percentage of the plate size' });
        tp3dShapeExtraNumberRow(body, 'plateInsertValue', 'Map Inset Depth (mm)',
            { step: 0.5, title: 'How far down the map object should be in the plate' });
        tp3dShapeExtraNumberRow(body, 'plateBevel', 'Plate Bevel',
            { step: 0.1, min: 0, max: 50, title: 'Bevel the top and bottom edges of the plate (0 to disable)' });
    } else {
        tp3dShapeExtraNumberRow(body, 'plateThickness', 'Shell Extra Height', { step: 0.5 });
        tp3dShapeExtraNumberRow(body, 'shellWallThickness', 'Shell Width', { step: 0.1, min: 0.1 });
    }

}

function tp3dRenderHandleSettings(body) {
    body.innerHTML = '';
    body.style.display = plateMode === 'NONE' ? 'none' : 'flex';
    if (plateMode === 'NONE') return;

    var handleLabel = document.createElement('div');
    handleLabel.className = 'se-section-label';
    handleLabel.textContent = 'Medal Handle';
    body.appendChild(handleLabel);

    var handleRow = document.createElement('div');
    handleRow.className = 'field-row';
    var handleSwitch = document.createElement('div');
    handleSwitch.className = 'se-handle-switch';
    var current = TP3D_SHAPE_EXTRAS_PREMIUM ? (SETTINGS_STATE.handleStyle || 'NONE') : 'NONE';
    [['NONE', 'None'], ['ROUND', 'Round'], ['FLAT', 'Flat']].forEach(function(h) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'element-mode-btn' + (current === h[0] ? ' active' : '');
        b.textContent = h[1];
        if (h[0] !== 'NONE' && !TP3D_SHAPE_EXTRAS_PREMIUM) {
            b.disabled = true;
            b.textContent = '🔒 ' + h[1];
            b.title = 'Medal handles are a Premium feature';
        }
        b.addEventListener('click', function() {
            tp3dPushShapeSetting('handleStyle', h[0]);
            handleSwitch.querySelectorAll('button').forEach(function(x) { x.classList.toggle('active', x === b); });
        });
        handleSwitch.appendChild(b);
    });
    handleRow.appendChild(handleSwitch);
    body.appendChild(handleRow);
}

// The page's own shape-button handlers change currentShape first; refresh
// right after them. Registered here so the pages don't each need a hook.
// Picking a shape drops any imported GeoJSON boundary / SVG shape, since
// only one shape is selected at a time: the boundary would otherwise keep
// winning over the picked shape at Send time, and the SVG would stay listed
// in the sidebar after its outline already left the map. Both clears
// refresh on their own (via updateStatus); clearSvgShapeImport
// (rect_editor.js) leaves currentShape alone since it's no longer 'svg'.
document.querySelectorAll('.shape-btn[data-shape]').forEach(function(btn) {
    btn.addEventListener('click', function() {
        setTimeout(function() {
            if (svgShapePath && currentShape !== 'svg') clearSvgShapeImport();
            if (geojsonPaths && geojsonPaths.length) document.getElementById('clearGeojson').click();
            tp3dRefreshShapeExtras();
        }, 0);
    });
});
