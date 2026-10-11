// Tutorial content for the Multi-Tile Generator page
// (premium/generators/multitile_generator.html), built on the engine in
// assets/tutorial.js -- same structure as assets/map_tutorials.js for the
// map generators. Must be inlined *after* the page has created `map` and its
// own Draw/Extend/Send handlers, and requires a #tutorialBtn button in the
// page's own markup.

// Leaflet-draw's default rectangle style while a corner-to-corner draw is in
// progress, vs. the orange the page uses for the finished area.
var TP3D_MT_DRAWING_BLUE = '#3388ff';

// Zermatt and the Matterhorn in the Swiss Alps -- the tutorial's example area.
var TP3D_MT_MATTERHORN_BOUNDS = [[45.94, 7.60], [46.05, 7.80]];

// The grid the tutorial asks for: 3 x 3 hexagons, 5 mm apart.
var TP3D_MT_SEGMENTS = 3;
var TP3D_MT_SPACING = 5;
// Lower than the page's default 8 so the example generates quickly.
var TP3D_MT_RESOLUTION = 6;

function tp3dMtHasDrawnArea() {
    return typeof coords !== 'undefined' && !!coords;
}

function tp3dMtSegmentsValue() {
    return parseInt(document.getElementById('subdivisionSlider').value) || 1;
}
function tp3dMtSpacingValue() {
    return parseFloat(document.getElementById('tileSpacingValue').value) || 0;
}

// The drawn area is split into exactly 3 rows of 3 hexagons. With 3
// segments, buildHexGridSegments only produces 9 tiles for a 3 x 3 layout
// (fewer rows give 6-7, more give 12+), so the count alone is enough.
function tp3dMtIs3x3() {
    return typeof currentShape !== 'undefined' && currentShape === 'hexagon' &&
        tp3dMtSegmentsValue() === TP3D_MT_SEGMENTS && segments.length === 9;
}

function tp3dMtSelectedSlotCount() {
    return typeof selectedSlots !== 'undefined' ? Object.keys(selectedSlots).length : 0;
}

// Screen height a drawn box *widthPx* wide needs for 3 rows of hexagons --
// buildHexGridSegments' own layout, solved for the height. Its (mx, my)
// space is a linear rescale of screen pixels at a fixed zoom, so the ratio
// carries over directly. 3 rows come out for a height of 2..2.5 row steps;
// 2.25 aims at the middle so the demo's box lands safely inside. Uses the
// tutorial's target spacing, not the slider's: the area is drawn before the
// spacing step, and the grid has to come out right once it's set.
function tp3dMtHexBoxHeight(widthPx) {
    var n = TP3D_MT_SEGMENTS;
    var objSize = parseFloat(document.getElementById('objSizeInput').value) || OBJ_SIZE;
    var spacingRatio = objSize > 0 ? 2 * TP3D_MT_SPACING / objSize : 0;
    var R = 2 * widthPx / ((3 * n - 1) + 2 * spacingRatio * (n - 1));
    return 2.25 * (Math.sqrt(3) + spacingRatio) * R;
}

// Screen rect of the drawn area's orange box, or null when nothing is drawn.
function tp3dMtDrawnBoxRect() {
    if (!tp3dMtHasDrawnArea()) return null;
    var el = typeof rectLayer !== 'undefined' && rectLayer && rectLayer.getElement && rectLayer.getElement();
    return el && el.getBoundingClientRect ? el.getBoundingClientRect() : null;
}

// Demo for "draw your area": a drag across the middle of the map, shaped
// so the grid comes out as 3 x 3 hexagons once the following steps have set
// the shape, segments and spacing.
function tp3dMtDemoDrawArea() {
    var box = map.getContainer().getBoundingClientRect();
    var cx = box.left + box.width / 2, cy = box.top + box.height / 2;
    var dx = Math.min(140, box.width / 5);
    var dy = Math.min(tp3dMtHexBoxHeight(2 * dx), box.height - 40) / 2;
    return [{ x: cx - dx, y: cy - dy }, { x: cx + dx, y: cy + dy }];
}

// Demo for "3 rows of 3": drags the bottom-right corner up or down to the
// height that gives 3 rows -- nothing once the grid is already right.
function tp3dMtDemoFixRows() {
    if (tp3dMtIs3x3()) return null;
    var r = tp3dMtDrawnBoxRect();
    if (!r) return null;
    var targetBottom = r.top + tp3dMtHexBoxHeight(r.width);
    if (Math.abs(targetBottom - r.bottom) < 4) return null;
    return [{ x: r.right, y: r.bottom }, { x: r.right, y: targetBottom }];
}

// Demo for a slider step: drags the slider's thumb from its current value
// to *value*. The thumb's center runs from half a thumb in from either end.
function tp3dMtDemoSlider(id, value) {
    return function() {
        var el = document.getElementById(id);
        if (!el || parseFloat(el.value) === value) return null;
        var r = el.getBoundingClientRect();
        var min = parseFloat(el.min) || 0, max = parseFloat(el.max) || 100, thumb = 16;
        function x(v) {
            var f = (Math.min(Math.max(v, min), max) - min) / (max - min);
            return r.left + thumb / 2 + f * (r.width - thumb);
        }
        var y = r.top + r.height / 2;
        return [{ x: x(parseFloat(el.value)), y: y }, { x: x(value), y: y }];
    };
}

// Demo for "add a tile": clicks the + slot nearest the map's center.
function tp3dMtDemoClickPlus() {
    var box = map.getContainer().getBoundingClientRect();
    var cx = box.left + box.width / 2, cy = box.top + box.height / 2;
    var best = null, bestDist = Infinity;
    document.querySelectorAll('#map .expand-plus').forEach(function(el) {
        var r = el.getBoundingClientRect();
        if (!r.width) return;
        var p = { x: r.left + r.width / 2, y: r.top + r.height / 2 };
        var d = Math.hypot(p.x - cx, p.y - cy);
        if (d < bestDist) { best = p; bestDist = d; }
    });
    return best ? [best] : null;
}

// Puts the page back to what a first launch of the generator shows, so the
// tutorial always starts from the same known state. Same approach as
// map_tutorials.js's tp3dResetMapGenerator: drives the page's own controls
// (mode / delete / Clear buttons, shape and draw-mode buttons, sliders,
// layer radios) so every side effect their handlers take care of happens
// exactly as if the user had clicked them. Extend-mode selections have no
// control of their own to clear them, so those are dropped directly.
function tp3dResetMultitileGenerator() {
    function clickIfShown(id) {
        var el = document.getElementById(id);
        if (el && el.style.display !== 'none') el.click();
    }
    function setInput(id, value) {
        var el = document.getElementById(id);
        if (!el || String(el.value) === String(value)) return;
        el.value = value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
    }

    if (typeof drawArmed !== 'undefined' && drawArmed) disarmDraw();
    if (mode !== 'draw') document.getElementById('modeDrawBtn').click();
    selectedSlots = {};
    if (tp3dMtHasDrawnArea()) document.getElementById('deleteBtn').click();
    clickIfShown('clearGpx');
    clickIfShown('clearGeojson');
    clickIfShown('clearPrefetch');

    var rectBtn = document.querySelector('.shape-btn[data-shape="rectangle"]');
    if (rectBtn && !rectBtn.classList.contains('active')) rectBtn.click();
    var cornerBtn = document.querySelector('.draw-mode-btn[data-mode="corner"]');
    if (cornerBtn && !cornerBtn.classList.contains('active')) cornerBtn.click();
    var dovetailBtn = document.getElementById('dovetailToggle');
    if (dovetailBtn.classList.contains('active')) dovetailBtn.click();

    // Same defaults the page itself starts with: the static HTML's slider
    // values, and Size from the scene's Object Size (OBJ_SIZE, as on load).
    setInput('subdivisionSlider', document.getElementById('subdivisionSlider').defaultValue || 1);
    setInput('tileSpacing', document.getElementById('tileSpacing').defaultValue || 0);
    setInput('resolutionSlider', document.getElementById('resolutionSlider').defaultValue || 8);
    setInput('objSizeInput', typeof OBJ_SIZE !== 'undefined' ? OBJ_SIZE : 100);

    // Base layer back to OpenStreetMap via the layers control's own radio,
    // so Leaflet's control and the page's activeBaseLayerName stay in sync.
    document.querySelectorAll('.leaflet-control-layers-base label').forEach(function(label) {
        var input = label.querySelector('input');
        if (input && !input.checked && label.textContent.trim() === 'OpenStreetMap') input.click();
    });
}

// ---- "Create a multi-tile map" ----

function tp3dMultitileTutorialCreate() {
    return [
        {
            target: '#map',
            title: 'Create a multi-tile map',
            text: 'A multi-tile map is one big map split into several tiles. Each tile is printed on its own, ' +
                  'and together they show the whole area.<br><br>' +
                  'We moved the map to <b>Zermatt and the Matterhorn</b> in the Swiss Alps.<br><br>' +
                  'You can exit this tutorial at any time with <b>✕</b> or <b>Esc</b>.'
        },
        {
            target: '#drawBtn',
            placement: 'right',
            title: 'Draw your area',
            text: 'Draw your area first, so you can see every setting change on the map right away.<br><br>' +
                  'Click the <b>pencil</b> to start drawing.',
            waitFor: tp3dTutorial.waitForClick('#drawBtn'),
            waitText: 'Click the pencil',
            skipIf: tp3dMtHasDrawnArea
        },
        {
            target: '#map',
            title: 'Draw your area',
            text: 'Click and drag over the Matterhorn to draw your area, then let go of the mouse.<br><br>' +
                  'Draw it <b>about as tall as it is wide</b>.<br><br>' +
                  'If nothing happens, click the pencil again.',
            demo: tp3dMtDemoDrawArea,
            demoShape: 'rect',
            demoGhostColor: TP3D_MT_DRAWING_BLUE,
            waitFor: tp3dTutorial.waitForEvent(map, L.Draw.Event.CREATED),
            waitText: 'Draw on the map',
            skipIf: tp3dMtHasDrawnArea
        },
        {
            target: '.shape-btn[data-shape="hexagon"]',
            placement: 'right',
            title: 'Select the hexagon',
            text: 'Click the <b>hexagon</b> to split your map into hexagon tiles. The blue shapes on the map ' +
                  'are your tiles.',
            waitFor: tp3dTutorial.waitUntil(function() { return currentShape === 'hexagon'; }),
            waitText: 'Click the hexagon',
            skipIf: function() { return currentShape === 'hexagon'; }
        },
        {
            target: function() { return document.getElementById('subdivisionSlider').parentElement; },
            placement: 'right',
            title: 'Set the segments',
            text: '<b>Segments</b> is the number of tiles across your map.<br><br>' +
                  'Drag the slider to <b>3</b>.',
            demo: tp3dMtDemoSlider('subdivisionSlider', TP3D_MT_SEGMENTS),
            waitFor: tp3dTutorial.waitUntil(function() { return tp3dMtSegmentsValue() === TP3D_MT_SEGMENTS; }),
            waitText: 'Set Segments to 3',
            skipIf: function() { return tp3dMtSegmentsValue() === TP3D_MT_SEGMENTS; }
        },
        {
            target: function() { return document.getElementById('tileSpacing').parentElement; },
            placement: 'right',
            title: 'Set the tile spacing',
            text: '<b>Tile Spacing</b> leaves a gap between neighboring tiles. The map skips the part in ' +
                  'between, so everything still lines up when you mount the tiles with that gap.<br><br>' +
                  'Set it to <b>5 mm</b>.',
            demo: tp3dMtDemoSlider('tileSpacing', TP3D_MT_SPACING),
            waitFor: tp3dTutorial.waitUntil(function() { return tp3dMtSpacingValue() === TP3D_MT_SPACING; }),
            waitText: 'Set Tile Spacing to 5',
            skipIf: function() { return tp3dMtSpacingValue() === TP3D_MT_SPACING; }
        },
        {
            target: function() { return document.getElementById('objSizeInput').closest('.field-row'); },
            interactive: true,
            placement: 'right',
            title: 'Set the tile size',
            text: 'This is the size of <b>each tile</b> in <b>mm</b>, not of the whole map.<br><br>' +
                  'The size of the whole map is shown at the bottom of the sidebar.'
        },
        {
            target: '#map',
            title: 'Get 3 rows of 3 hexagons',
            text: 'Drag a corner of the orange box up or down until you see <b>3 rows of 3 hexagons</b>, ' +
                  '9 tiles in total.<br><br>' +
                  'Drag the handle in the middle to move the whole area.',
            demo: tp3dMtDemoFixRows,
            waitFor: tp3dTutorial.waitUntil(tp3dMtIs3x3),
            waitText: 'Make it 3 x 3',
            skippable: true,
            skipIf: tp3dMtIs3x3
        },
        {
            target: '#totalSizeInfo',
            placement: 'right',
            title: 'Size of the whole map',
            text: 'Here you can see how big the finished map is, with all tiles and the gaps between them.'
        },
        {
            target: '#modeExtendBtn',
            placement: 'right',
            title: 'Extend your map',
            text: 'You can add single tiles next to your map, to grow it in any direction.<br><br>' +
                  'Click <b>Extend</b>.',
            waitFor: tp3dTutorial.waitUntil(function() { return mode === 'extend'; }),
            waitText: 'Click Extend',
            skipIf: function() { return mode === 'extend'; }
        },
        {
            target: '#map',
            title: 'Add a tile',
            text: 'Your 9 tiles are shown in blue. Every dashed hexagon with a <b>+</b> is a free spot ' +
                  'next to them.<br><br>' +
                  'Click a <b>+</b> to add a tile there.',
            demo: tp3dMtDemoClickPlus,
            waitFor: tp3dTutorial.waitUntil(function() { return tp3dMtSelectedSlotCount() > 0; }),
            waitText: 'Click a +',
            skippable: true
        },
        {
            target: '#map',
            interactive: true,
            title: 'Keep growing',
            text: 'The new tile is shown in orange, and new <b>+</b> spots appear around it, so you can keep ' +
                  'adding tiles. Click an orange tile to remove it again.<br><br>' +
                  'Extend also works for maps you already generated in Blender. Their free spots show up here ' +
                  'once nothing is drawn in <b>Draw</b> mode.'
        },
        {
            target: function() { return document.getElementById('resolutionSlider').parentElement; },
            placement: 'right',
            title: 'Set the resolution',
            text: '<b>Resolution</b> sets how much terrain detail each tile gets. Higher values look sharper ' +
                  'but take longer to generate.<br><br>' +
                  'Set it to <b>6</b> so this example generates quickly.',
            demo: tp3dMtDemoSlider('resolutionSlider', TP3D_MT_RESOLUTION),
            waitFor: tp3dTutorial.waitUntil(function() {
                return parseInt(document.getElementById('resolutionSlider').value) === TP3D_MT_RESOLUTION;
            }),
            waitText: 'Set Resolution to 6',
            skipIf: function() {
                return parseInt(document.getElementById('resolutionSlider').value) === TP3D_MT_RESOLUTION;
            }
        },
        {
            target: '#send',
            placement: 'right',
            title: 'Generate your map',
            text: 'Click <b>Send to Blender</b> to generate all tiles.',
            waitFor: tp3dTutorial.waitForClick('#send'),
            waitText: 'Click Send to Blender',
            skippable: true
        }
    ];
}

tp3dTutorialMenu({
    button: '#tutorialBtn',
    title: 'Multi-Tile Generator Tutorials',
    tutorials: [
        {
            id: 'multitile-create',
            title: 'Create a multi-tile map',
            description: 'Split a map of the Alps into 3 x 3 hexagon tiles and extend it with more.',
            prepare: function() {
                tp3dResetMultitileGenerator();
                map.fitBounds(TP3D_MT_MATTERHORN_BOUNDS);
            },
            steps: tp3dMultitileTutorialCreate
        }
    ]
});
