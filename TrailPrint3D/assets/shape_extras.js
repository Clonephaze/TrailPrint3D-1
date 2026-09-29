// Shape Extras dropdown + "Text Settings" popup, shared by the map generator
// pages (map_generator.html, premium/map_generator_pe.html). Mirrors
// panels.py's own "2. Shape" section: which extras a shape offers comes from
// props.py's SHAPE_TEXT_STYLES, and the popup's fields are the ones its
// Shape Extras box shows for the same effective shape.
//
// The selected extra itself is page state (saved with the page's own
// saveState snapshot and sent in the /confirm payload as 'shape_extra',
// applied Blender-side only once props.shape is set -- shapeTextStyle's item
// list depends on it). Every popup field is a plain scene property instead,
// pushed live through /update_setting (utils.ui_state._SETTINGS_ROW_FIELDS)
// and read back from SETTINGS_STATE, same as the Settings popup's Map tab.
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
var SHAPE_EXTRA_OPTIONS = {
    hexagon: [
        ['NONE', 'None'],
        ['INNER TEXT', 'Text on Map Object'],
        ['OUTER TEXT', 'Plate With Text on Top'],
        ['FRONT TEXT', 'Plate With Text on Front'],
        ['SHELL', 'Shell']
    ],
    octagon: [['NONE', 'None'], ['OUTER TEXT', 'Plate With Text on Front'], ['SHELL', 'Shell']],
    circle: [['NONE', 'None'], ['OUTER TEXT', 'Plate With Text on Front'], ['SHELL', 'Shell']],
    square: [['NONE', 'None'], ['SHELL', 'Shell']],
    rectangle: [['NONE', 'None'], ['SHELL', 'Shell']]
};
var SHAPE_EXTRA_TEXT_STYLES = { 'INNER TEXT': true, 'OUTER TEXT': true, 'FRONT TEXT': true };

var SHAPE_EXTRA_TITLE_ICONS = [
    ['cycling', 'Cycling'], ['hiking', 'Hiking'], ['running', 'Running'], ['swimming', 'Swimming'],
    ['skiing', 'Skiing'], ['snowboarding', 'Snowboarding'], ['kajak', 'Kayak'], ['no', 'No Icon']
];
var SHAPE_EXTRA_TEXT_ICONS = [
    ['distance', 'Distance'], ['elevation', 'Elevation'], ['time', 'Time'],
    ['speed', 'Speed'], ['date', 'Date'], ['no', 'No Icon']
];
// Same order as panels.py's text_fields list; hexOuterOnly rows only exist
// on HEXAGON OUTER TEXT.
var SHAPE_EXTRA_TEXT_FIELDS = [
    { icon: 'titleIcon', text: 'titlefield', icons: SHAPE_EXTRA_TITLE_ICONS, hexOuterOnly: false },
    { icon: 'iconText5', text: 'textfield5', icons: SHAPE_EXTRA_TEXT_ICONS, hexOuterOnly: true },
    { icon: 'iconText1', text: 'textfield1', icons: SHAPE_EXTRA_TEXT_ICONS, hexOuterOnly: false },
    { icon: 'iconText2', text: 'textfield2', icons: SHAPE_EXTRA_TEXT_ICONS, hexOuterOnly: false },
    { icon: 'iconText3', text: 'textfield3', icons: SHAPE_EXTRA_TEXT_ICONS, hexOuterOnly: false },
    { icon: 'iconText4', text: 'textfield4', icons: SHAPE_EXTRA_TEXT_ICONS, hexOuterOnly: true }
];
// Effective shapes with a backplate (props.py's PLATE_SHAPES).
var SHAPE_EXTRA_PLATE_SHAPES = {
    'HEXAGON OUTER TEXT': true, 'HEXAGON FRONT TEXT': true,
    'OCTAGON OUTER TEXT': true, 'CIRCLE OUTER TEXT': true
};

var shapeExtra = 'NONE';

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

function tp3dEffectiveShapeExtra() {
    return shapeExtra === 'NONE' ? tp3dShapeExtraBase() : tp3dShapeExtraBase() + ' ' + shapeExtra;
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

    var label = document.createElement('div');
    label.style.cssText = 'font-size:12px; color:#aaa;';
    label.textContent = 'Shape Extras';
    section.appendChild(label);

    var select = document.createElement('select');
    select.id = 'shapeExtraSelect';
    select.title = 'Add an extra (text/plate overlay or shell) to the selected shape';
    select.addEventListener('change', function() {
        shapeExtra = this.value;
        tp3dRefreshShapeExtras();
        saveState();
    });
    section.appendChild(select);

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.id = 'shapeExtrasBtn';
    btn.className = 'btn-shape-extras';
    btn.textContent = 'Text Settings…';
    btn.addEventListener('click', tp3dOpenShapeExtrasModal);
    section.appendChild(btn);
}

// Rebuilds the dropdown for the current shape, keeping the selection if the
// new shape still offers it (else None -- same rule as props.shape_update),
// and shows the Text Settings button only for a text extra.
function tp3dRefreshShapeExtras() {
    tp3dSyncShapeSelection();
    var section = document.getElementById('shapeExtrasSection');
    if (!section) return;
    if (!document.getElementById('shapeExtraSelect')) tp3dBuildShapeExtrasSection();

    var options = SHAPE_EXTRA_OPTIONS[tp3dSelectedShape()];
    section.style.display = options ? 'flex' : 'none';
    if (!options) return;

    var valid = options.some(function(o) {
        return o[0] === shapeExtra && (o[0] !== 'SHELL' || TP3D_SHAPE_EXTRAS_PREMIUM);
    });
    if (!valid) shapeExtra = 'NONE';

    var select = document.getElementById('shapeExtraSelect');
    select.innerHTML = '';
    options.forEach(function(o) {
        var opt = document.createElement('option');
        opt.value = o[0];
        opt.textContent = o[1];
        if (o[0] === 'SHELL' && !TP3D_SHAPE_EXTRAS_PREMIUM) {
            opt.textContent = '🔒 ' + o[1] + ' (Premium)';
            opt.disabled = true;
        }
        select.appendChild(opt);
    });
    select.value = shapeExtra;

    document.getElementById('shapeExtrasBtn').style.display = SHAPE_EXTRA_TEXT_STYLES[shapeExtra] ? 'block' : 'none';
    var modal = document.getElementById('shapeExtrasModal');
    if (modal && modal.classList.contains('open')) {
        if (SHAPE_EXTRA_TEXT_STYLES[shapeExtra]) tp3dRenderShapeExtrasModal();
        else modal.classList.remove('open');
    }
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

function tp3dRenderShapeExtrasModal() {
    var body = document.getElementById('shapeExtrasModalBody');
    body.innerHTML = '';
    var effective = tp3dEffectiveShapeExtra();

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

    var textLabel = document.createElement('div');
    textLabel.className = 'se-section-label';
    textLabel.textContent = 'Text (Goes Counter-Clockwise) ↺';
    body.appendChild(textLabel);

    SHAPE_EXTRA_TEXT_FIELDS.forEach(function(f) {
        if (f.hexOuterOnly && effective !== 'HEXAGON OUTER TEXT') return;
        var row = document.createElement('div');
        row.className = 'se-text-row';
        if (TP3D_SHAPE_EXTRAS_PREMIUM) {
            var iconSel = document.createElement('select');
            f.icons.forEach(function(ic) {
                var opt = document.createElement('option');
                opt.value = ic[0];
                opt.textContent = ic[1];
                iconSel.appendChild(opt);
            });
            iconSel.value = SETTINGS_STATE[f.icon] || 'no';
            iconSel.addEventListener('change', function() { tp3dPushShapeSetting(f.icon, this.value); });
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
        textInput.value = SETTINGS_STATE[f.text] != null ? SETTINGS_STATE[f.text] : '';
        textInput.title = 'Codes = {name} | {length} | {elevation} | {duration} | {date} | {speed} | {scale}';
        textInput.addEventListener('change', function() { tp3dPushShapeSetting(f.text, this.value); });
        row.appendChild(textInput);
        body.appendChild(row);
    });

    var hint = document.createElement('div');
    hint.className = 'se-hint';
    hint.textContent = 'Codes: {name} {length} {elevation} {duration} {date} {speed} {scale}';
    body.appendChild(hint);

    if (!SHAPE_EXTRA_PLATE_SHAPES[effective]) return;

    var plateLabel = document.createElement('div');
    plateLabel.className = 'se-section-label';
    plateLabel.textContent = 'Plate';
    body.appendChild(plateLabel);
    tp3dShapeExtraNumberRow(body, 'plateThickness', 'Plate Height (mm)', { step: 0.5 });
    tp3dShapeExtraNumberRow(body, 'outerBorderSize', 'Border Thickness (%)',
        { step: 1, min: 0, max: 1000, integer: true, title: 'How thick the border is, as a percentage of the plate size' });
    tp3dShapeExtraNumberRow(body, 'plateInsertValue', 'Map Inset Depth (mm)',
        { step: 0.5, title: 'How far down the map object should be in the plate' });
    tp3dShapeExtraNumberRow(body, 'plateBevel', 'Plate Bevel',
        { step: 0.1, min: 0, max: 50, title: 'Bevel the top and bottom edges of the plate (0 to disable)' });

    var handleRow = document.createElement('div');
    handleRow.className = 'field-row';
    var handleLabel = document.createElement('label');
    handleLabel.textContent = 'Medal Handle';
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
    handleRow.appendChild(handleLabel);
    handleRow.appendChild(handleSwitch);
    body.appendChild(handleRow);
}

function tp3dOpenShapeExtrasModal() {
    var modal = document.getElementById('shapeExtrasModal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'shapeExtrasModal';
        modal.className = 'tp3d-modal';
        var box = document.createElement('div');
        box.className = 'tp3d-modal-box';
        var header = document.createElement('div');
        header.className = 'modal-header';
        var title = document.createElement('span');
        title.textContent = 'Text Settings';
        var closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'tp3d-modal-close-btn';
        closeBtn.title = 'Close';
        closeBtn.textContent = '✕';
        header.appendChild(title);
        header.appendChild(closeBtn);
        box.appendChild(header);
        var body = document.createElement('div');
        body.id = 'shapeExtrasModalBody';
        body.style.cssText = 'display:flex; flex-direction:column; gap:10px;';
        box.appendChild(body);
        modal.appendChild(box);
        function close() { modal.classList.remove('open'); }
        closeBtn.addEventListener('click', close);
        modal.addEventListener('click', function(e) { if (e.target === modal) close(); });
        document.body.appendChild(modal);
    }
    tp3dRenderShapeExtrasModal();
    modal.classList.add('open');
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
