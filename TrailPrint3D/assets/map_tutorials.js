// Tutorial content for the Map Generator pages (generators/map_generator.html
// and premium/generators/map_generator_pe.html), built on the engine in
// assets/tutorial.js. Both pages share every element id used here, so one
// set of steps covers both. Must be inlined *after* the page has created
// `map` and its own Draw/Send handlers, and requires a #tutorialBtn button
// in the page's own markup.

// Viewport (clientX/Y) position of a lat/lng on the page's Leaflet map --
// what the tutorial engine's `demo` cursor points are expressed in.
function tp3dMapToViewport(lat, lng) {
    var p = map.latLngToContainerPoint([lat, lng]);
    var box = map.getContainer().getBoundingClientRect();
    return { x: box.left + p.x, y: box.top + p.y };
}

// Demo for "draw your area": a drag across the middle of the map -- corner
// to corner, or from the center outward when the page is in 'center' draw
// mode (rect_editor.js's drawMode).
function tp3dDemoDrawArea() {
    var box = map.getContainer().getBoundingClientRect();
    var cx = box.left + box.width / 2, cy = box.top + box.height / 2;
    var dx = Math.min(130, box.width / 5), dy = Math.min(90, box.height / 5);
    if (typeof drawMode !== 'undefined' && drawMode === 'center') {
        return [{ x: cx, y: cy }, { x: cx + dx, y: cy + dy }];
    }
    return [{ x: cx - dx, y: cy - dy }, { x: cx + dx, y: cy + dy }];
}

// Leaflet-draw's default rectangle style while a corner-to-corner draw is in
// progress (the page passes no shapeOptions of its own), vs. the orange the
// page itself uses for center-mode drawing and every finished area.
var TP3D_DRAWING_BLUE = '#3388ff';
var TP3D_DRAWN_ORANGE = '#E97826';

// Screen rect of the drawn area's orange box (its bounding box for every
// shape, not the inscribed blue preview), or null when nothing is drawn.
// Read from the rendered element -- what's actually on screen -- rather
// than converting coords, so demos land exactly on it.
function tp3dDrawnBoxRect() {
    if (typeof coords === 'undefined' || !coords) return null;
    var el = typeof rectLayer !== 'undefined' && rectLayer && rectLayer.getElement && rectLayer.getElement();
    if (el && el.getBoundingClientRect) return el.getBoundingClientRect();
    var nw = tp3dMapToViewport(coords.north, coords.west), se = tp3dMapToViewport(coords.south, coords.east);
    return { left: nw.x, top: nw.y, right: se.x, bottom: se.y, width: se.x - nw.x, height: se.y - nw.y };
}

// Demo for "adjust your shape": grab the bottom-right corner exactly and
// drag it outward diagonally.
function tp3dDemoDragCorner() {
    var r = tp3dDrawnBoxRect();
    if (!r) return null;
    return [{ x: r.right, y: r.bottom }, { x: r.right + 70, y: r.bottom + 45 }];
}

// Demo for "move your shape": grab the move handle in the middle of the box
// (rect_editor.js's bindMoveHandle) and drag it; the ghost is the box itself
// riding along with the cursor.
function tp3dDemoMoveShape() {
    var r = tp3dDrawnBoxRect();
    if (!r) return null;
    var cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    return [{ x: cx, y: cy }, { x: cx + 90, y: cy + 40 }];
}
function tp3dDemoMoveGhost(start, current) {
    var r = tp3dDrawnBoxRect();
    if (!r) return null;
    return { left: r.left + current.x - start.x, top: r.top + current.y - start.y, width: r.width, height: r.height };
}

// Leaflet's layers control (map_init.js, bottom-left) only lists its layers
// while hovered and collapses again on mouseout. The tutorial's layer step
// keeps it open so the list itself can be highlighted -- re-applying the
// expanded class on a short timer undoes Leaflet's own collapse.
var tp3dLayersOpenTimer = null;
function tp3dHoldLayersOpen() {
    tp3dReleaseLayersOpen();
    function open() {
        var el = document.querySelector('.leaflet-control-layers');
        if (el) el.classList.add('leaflet-control-layers-expanded');
    }
    open();
    tp3dLayersOpenTimer = setInterval(open, 150);
}
function tp3dReleaseLayersOpen() {
    if (tp3dLayersOpenTimer) { clearInterval(tp3dLayersOpenTimer); tp3dLayersOpenTimer = null; }
    var el = document.querySelector('.leaflet-control-layers');
    if (el) el.classList.remove('leaflet-control-layers-expanded');
}

// Puts the page back to what a first launch of the generator shows, so a
// tutorial always starts from the same known state. Works by driving the
// page's own controls (delete / Clear buttons, shape and draw-mode buttons,
// layer radios) rather than poking its variables, so every side effect those
// handlers already take care of -- preview layers, sidebar lists, status
// text, saveState -- happens exactly as if the user had clicked them, on both
// the free and premium page. Leaves the map's position alone, and doesn't
// touch the Blender-side Settings popup (those are scene settings, not
// generator state).
function tp3dResetMapGenerator() {
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

    if (tp3dHasDrawnArea()) document.getElementById('deleteBtn').click();
    clickIfShown('clearGpx');
    clickIfShown('clearGeojson');
    clickIfShown('clearSvgShape');
    clickIfShown('clearPrefetch');

    var rectBtn = document.querySelector('.shape-btn[data-shape="rectangle"]');
    if (rectBtn && !rectBtn.classList.contains('active')) rectBtn.click();
    var cornerBtn = document.querySelector('.draw-mode-btn[data-mode="corner"]');
    if (cornerBtn && !cornerBtn.classList.contains('active')) cornerBtn.click();

    plateMode = 'NONE';
    textLayout = 'NONE';
    tp3dRefreshShapeExtras();
    saveState();

    // Same defaults the page itself starts with: the static HTML's slider
    // value, and Size from the scene's Object Size (OBJ_SIZE, as on load).
    setInput('resolutionSlider', document.getElementById('resolutionSlider').defaultValue || 8);
    setInput('objSizeInput', typeof OBJ_SIZE !== 'undefined' ? OBJ_SIZE : 100);

    // Base layer back to OpenStreetMap via the layers control's own radio,
    // so Leaflet's control and the page's activeBaseLayerName stay in sync.
    document.querySelectorAll('.leaflet-control-layers-base label').forEach(function(label) {
        var input = label.querySelector('input');
        if (input && !input.checked && label.textContent.trim() === 'OpenStreetMap') input.click();
    });
}

// waitFor for the "adjust" / "move" steps: snapshots the drawn area's
// bounds when the step opens, then re-checks after every mouse release
// (deferred a moment, so the page's own drag-end handlers have updated
// coords first). kind 'resize' advances once the area's size changed;
// 'move' once its center moved while its size stayed the same, so a resize
// during the move step doesn't count. Copies the values, since the move
// handle mutates coords in place.
function tp3dWaitForAreaChange(kind) {
    return function(done) {
        function snap() {
            if (!tp3dHasDrawnArea()) return null;
            return { n: coords.north, s: coords.south, e: coords.east, w: coords.west };
        }
        var start = snap();
        function onUp() {
            setTimeout(function() {
                var now = snap();
                if (!now) return;
                if (!start) { start = now; return; }
                var tol = 1e-9;
                var sizeChanged = Math.abs((now.n - now.s) - (start.n - start.s)) > tol ||
                    Math.abs((now.e - now.w) - (start.e - start.w)) > tol;
                var moved = Math.abs((now.n + now.s) - (start.n + start.s)) > tol ||
                    Math.abs((now.e + now.w) - (start.e + start.w)) > tol;
                if (kind === 'move' ? (moved && !sizeChanged) : sizeChanged) done();
                else start = now;
            }, 60);
        }
        document.addEventListener('pointerup', onUp, true);
        return function() { document.removeEventListener('pointerup', onUp, true); };
    };
}

function tp3dHasDrawnArea() {
    return typeof coords !== 'undefined' && !!coords;
}

// Bundled sample files (sample_files/ in the addon, served by
// picker_server.py's /get_sample_file) for users without a file of their
// own. Returns a popup-button onClick that hands the sample to one of the
// page's own file inputs (#gpxInput, #geojsonInput, #svgShapeInput) and
// fires 'change', so it goes through exactly the same import code as a
// file picked by hand, on both the free and premium page.
function tp3dSampleFileLoader(fileName, inputId, mimeType, what) {
    return function(button) {
        var label = button.textContent;
        button.disabled = true;
        button.textContent = 'Loading…';
        fetch('http://127.0.0.1:' + PORT + '/get_sample_file?name=' + encodeURIComponent(fileName))
            .then(function(r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.text();
            })
            .then(function(text) {
                var transfer = new DataTransfer();
                transfer.items.add(new File([text], fileName, { type: mimeType }));
                var input = document.getElementById(inputId);
                input.files = transfer.files;
                input.dispatchEvent(new Event('change', { bubbles: true }));
            })
            .catch(function() {
                button.disabled = false;
                button.textContent = label;
                tp3dAlert('Could not load the sample ' + what + '.');
            });
    };
}

var tp3dLoadSampleGpx = tp3dSampleFileLoader('BetweenLakes.gpx', 'gpxInput', 'application/gpx+xml', 'GPX file');
var tp3dLoadSampleGeojson = tp3dSampleFileLoader('germany.json', 'geojsonInput', 'application/geo+json', 'GeoJSON file');
var tp3dLoadSampleSvg = tp3dSampleFileLoader('star.svg', 'svgShapeInput', 'image/svg+xml', 'SVG file');

function tp3dHasGpx() {
    return typeof gpxPaths !== 'undefined' && gpxPaths.length > 0;
}

function tp3dMapTutorialNoGpx() { return tp3dMapGenerateSteps(false); }
function tp3dMapTutorialGpx() { return tp3dMapGenerateSteps(true); }

// Steps shared by both "Generate Map" tutorials. The GPX one assumes the
// first was done: it starts at the GPX import (no size/shape/layer steps)
// and adds center mode instead. Importing a trail auto-places a shape
// around it (the page's gpxInput handler), so the two "Draw your area"
// steps then skip themselves.
function tp3dMapGenerateSteps(withGpx) {
    var intro = [
        {
            target: function() { return document.getElementById('objSizeInput').closest('.field-row'); },
            interactive: true,
            placement: 'right',
            title: 'Set the size',
            text: 'Set the size of the finished map in <b>mm</b>.<br><br>' +
                  'You can exit this tutorial at any time with <b>✕</b> or <b>Esc</b>.'
        },
        {
            target: '#shapeToggle',
            interactive: true,
            placement: 'right',
            title: 'Select a shape'
        }
    ];
    var gpx = [
        {
            target: '#importGpx',
            placement: 'right',
            title: 'Import a GPX file',
            text: 'Click <b>Import GPX</b> and pick the GPX file of your route.<br><br>' +
                  'No GPX file at hand? Use our sample route instead.<br><br>' +
                  'We picked the <b>hexagon</b> shape for this tutorial.',
            buttons: [{ label: 'Use sample GPX file', onClick: tp3dLoadSampleGpx }],
            waitFor: tp3dTutorial.waitUntil(tp3dHasGpx),
            waitText: 'Import a GPX file'
        }
    ];
    var rest = [
        // Draw an area -- skipped when one already exists, since the steps
        // after it adjust that area.
        {
            target: '#drawBtn',
            placement: 'right',
            title: 'Draw your area',
            text: 'Move the map to the place you want to print, then click the <b>pencil</b> to start drawing.',
            waitFor: tp3dTutorial.waitForClick('#drawBtn'),
            waitText: 'Click the pencil',
            skipIf: tp3dHasDrawnArea
        },
        {
            target: '#map',
            title: 'Draw your area',
            text: 'Click and drag on the map to draw your area, then let go of the mouse.<br><br>' +
                  'If nothing happens, click the pencil again.',
            demo: tp3dDemoDrawArea,
            demoShape: function() {
                return typeof drawMode !== 'undefined' && drawMode === 'center' ? 'rect-center' : 'rect';
            },
            demoGhostColor: function() {
                return typeof drawMode !== 'undefined' && drawMode === 'center' ? TP3D_DRAWN_ORANGE : TP3D_DRAWING_BLUE;
            },
            waitFor: tp3dTutorial.waitForEvent(map, L.Draw.Event.CREATED),
            waitText: 'Draw on the map',
            skipIf: tp3dHasDrawnArea
        },
        // This and the move step below are left out of the GPX tutorial --
        // the import already sized and placed the shape around the trail.
        withGpx ? null : {
            target: '#map',
            title: 'Adjust your shape',
            text: 'Drag a corner of the orange box to adjust your shape.',
            demo: tp3dDemoDragCorner,
            waitFor: tp3dWaitForAreaChange('resize'),
            waitText: 'Drag a corner',
            skippable: true
        },
        withGpx ? null : {
            target: '#map',
            title: 'Move your shape',
            text: 'Drag the handle in the middle of the box to move the whole shape without changing its size.',
            demo: tp3dDemoMoveShape,
            waitFor: tp3dWaitForAreaChange('move'),
            waitText: 'Drag the middle handle',
            skippable: true,
            demoGhost: tp3dDemoMoveGhost,
            demoGhostColor: TP3D_DRAWN_ORANGE
        },
        // Center mode is only taught in the GPX tutorial: resizing around the
        // center keeps the trail centered in the shape the import placed.
        withGpx ? {
            target: '.draw-mode-btn[data-mode="center"]',
            placement: 'right',
            title: 'Switch to center mode',
            text: 'Click <b>Draw from a center point</b>. In this mode the center of your shape stays fixed.',
            waitFor: tp3dTutorial.waitForClick('.draw-mode-btn[data-mode="center"]'),
            waitText: 'Click the center button',
            skipIf: function() { return typeof drawMode !== 'undefined' && drawMode === 'center'; }
        } : null,
        withGpx ? {
            target: '#map',
            title: 'Adjust your shape',
            text: 'Drag a corner. The opposite side moves with it, so the shape grows or shrinks ' +
                  'around its center and your trail stays in the middle.',
            demo: tp3dDemoDragCorner,
            waitFor: tp3dWaitForAreaChange('resize'),
            waitText: 'Drag a corner',
            skippable: true
        } : null,
        // Already explained in the first tutorial -- left out of the GPX one.
        withGpx ? null : {
            target: '.leaflet-control-layers',
            interactive: true,
            title: 'Select a different layer',
            text: 'Pick a different map background, like <b>Satellite</b> or <b>Topographic</b>, to see ' +
                  'your area better.',
            onEnter: tp3dHoldLayersOpen,
            onExit: tp3dReleaseLayersOpen
        },
        // Already shown at the end of the first tutorial -- left out of the GPX one.
        withGpx ? null : {
            target: '#send',
            placement: 'right',
            title: 'Generate your map',
            text: 'Once you\'re happy, click <b>Send to Blender</b> to generate the map.',
            waitFor: tp3dTutorial.waitForClick('#send'),
            waitText: 'Click Send to Blender',
            skippable: true
        }
    ];
    // The GPX tutorial skips size and shape too -- the first tutorial
    // already covers them.
    return (withGpx ? gpx : intro).concat(rest).filter(Boolean);
}

// ---- "Add Colors to the map" ----

// OSM vs ESA example pictures, hosted on trailprint3d.com rather than
// bundled (keeps the addon small). An image that fails to load just
// removes itself, so the step still reads fine before they're uploaded.
var TP3D_TUTORIAL_IMG_OSM = 'https://trailprint3d.com/images/howto/TutorialOSM.webp';
var TP3D_TUTORIAL_IMG_ESA = 'https://trailprint3d.com/images/howto/TutorialESA.webp';

// The sample track's extent (sample_files/BetweenLakes.gpx) -- lakes,
// rivers, towns and roads in one small area, good for showing elements.
// Only the area is placed; the trail itself isn't imported.
var TP3D_SAMPLE_AREA_BOUNDS = [[45.94103, 9.069148], [46.042722, 9.239247]];

function tp3dPlaceSampleArea() {
    placeShapeAroundBounds(L.latLngBounds(TP3D_SAMPLE_AREA_BOUNDS), 0.8);
    if (typeof rectLayer !== 'undefined' && rectLayer) map.fitBounds(rectLayer.getBounds(), { padding: [50, 50] });
}

function tp3dSettingsModal() { return document.getElementById('settingsModal'); }
function tp3dSettingsOpen() {
    var m = tp3dSettingsModal();
    return !!m && m.classList.contains('open');
}
function tp3dInSettings(selector) {
    return function() {
        var m = tp3dSettingsModal();
        return m ? m.querySelector(selector) : null;
    };
}
// The Elements tab card whose toggle icon is *key* ('water', 'roads', ...).
function tp3dSettingsCard(key) {
    return function() {
        var m = tp3dSettingsModal();
        var icon = m && m.querySelector('.card-icon[data-element-toggle="' + key + '"]');
        return icon ? icon.closest('.element-card') : null;
    };
}

function tp3dIsOsm() {
    return typeof ELEMENT_SOURCE === 'undefined' || ELEMENT_SOURCE !== 'WORLDCOVER';
}

// Same reset as the other tutorials, plus: Settings popup closed, element
// source on OSM (the steps explain OSM's Water/Roads options), and the
// sample area placed as a hexagon.
function tp3dPrepareColorTutorial() {
    var m = tp3dSettingsModal();
    if (m) m.classList.remove('open');
    tp3dResetMapGenerator();
    if (!tp3dIsOsm() && typeof tp3dSwitchElementSource === 'function') tp3dSwitchElementSource('OSM');
    // Hexagon sample shape -- picked through its own button (like a user
    // would) before placing, since placeShapeAroundBounds uses the current shape.
    var hexBtn = document.querySelector('.shape-btn[data-shape="hexagon"]');
    if (hexBtn) hexBtn.click();
    tp3dPlaceSampleArea();
}

// Advances once any element is switched on or off (chip, card or flyout).
function tp3dWaitForElementToggle() {
    return function(done) {
        var start = JSON.stringify(TP3D_ELEMENT_STATE);
        var id = setInterval(function() {
            if (JSON.stringify(TP3D_ELEMENT_STATE) !== start) done();
        }, 200);
        return function() { clearInterval(id); };
    };
}

function tp3dElementChipWrap(key) {
    var chip = document.querySelector('#elementStatus .element-chip[data-element-toggle="' + key + '"]');
    return chip ? chip.closest('.element-chip-wrap') : null;
}

// Center of the Water chip -- where the sample cursor clicks.
function tp3dDemoClickWater() {
    var chip = document.querySelector('#elementStatus .element-chip[data-element-toggle="water"]');
    if (!chip) return null;
    var r = chip.getBoundingClientRect();
    return [{ x: r.left + 18, y: r.top + r.height / 2 }];
}

function tp3dCompareHtml() {
    function col(img, name, lines) {
        return '<div class="tp3d-tut-compare-col">' +
            '<img src="' + img + '" alt="" onerror="this.remove()">' +
            '<b>' + name + '</b><br>' + lines + '</div>';
    }
    return '<div class="tp3d-tut-compare">' +
        col(TP3D_TUTORIAL_IMG_OSM, 'OSM', 'More functionality.<br>Sharp shapes, includes roads &amp; buildings.<br>Best for smaller maps; gets slower the larger the map.') +
        col(TP3D_TUTORIAL_IMG_ESA, 'ESA', 'Made from satellite images.<br>Softer shapes, no roads or buildings.<br>No map size limit.') +
        '</div>';
}

function tp3dMapTutorialColors() {
    return [
        {
            target: '#elementStatus',
            placement: 'bottom',
            title: 'Map elements',
            text: 'These are the parts of your map that get their own color, like water, forest or roads.<br><br>' +
                  'We placed a sample area for you to try them on.'
        },
        {
            target: '.element-source-switch-compact',
            placement: 'bottom',
            width: 380,
            title: 'OSM or ESA',
            text: tp3dCompareHtml() + '<div class="tp3d-tut-note">This tutorial uses OSM.</div>'
        },
        {
            target: function() { return Array.prototype.slice.call(document.querySelectorAll('#elementStatus .element-chip-wrap')); },
            placement: 'bottom',
            title: 'Turn elements on or off',
            text: 'Click an element to switch it on or off. Green means on.',
            demo: tp3dDemoClickWater,
            waitFor: tp3dWaitForElementToggle(),
            waitText: 'Click an element',
            skippable: true
        },
        {
            target: function() {
                var wrap = tp3dElementChipWrap('water');
                return wrap ? [wrap, wrap.querySelector('.element-flyout')] : null;
            },
            interactive: true,
            placement: 'right',
            title: 'Pick the kind of water',
            text: 'Hover over <b>Water</b> to choose which kinds to include.<br><br>' +
                  '<b>Small Rivers</b> and <b>Big Rivers</b> are only needed if one of your rivers is missing.',
            // Opens the flyout as if hovered, and closes it again after.
            onEnter: function() {
                var wrap = tp3dElementChipWrap('water');
                if (wrap) wrap.dispatchEvent(new MouseEvent('mouseenter'));
            },
            onExit: function() {
                var wrap = tp3dElementChipWrap('water');
                if (wrap) wrap.dispatchEvent(new MouseEvent('mouseleave'));
            },
            skipIf: function() { return !tp3dIsOsm(); }
        },
        {
            target: '.settings-gear-btn',
            placement: 'bottom',
            title: 'All element options',
            text: 'Click <b>Settings</b> to see every option for each element.',
            waitFor: tp3dTutorial.waitForClick('.settings-gear-btn'),
            waitText: 'Click Settings',
            skipIf: tp3dSettingsOpen
        },
        {
            target: tp3dSettingsCard('water'),
            interactive: true,
            title: 'Water settings',
            text: '<ul class="tp3d-tut-list">' +
                  '<li><b>Checkboxes:</b> which water to include</li>' +
                  '<li><b>Lake/Pond Threshold:</b> filters out elements with a surface area smaller than the value</li>' +
                  '<li><b>River Width:</b> thicker or thinner rivers (only for <b>Small Rivers</b>)</li>' +
                  '<li><b>Flatten Water Surface:</b> keeps the water flat instead of following the terrain</li>' +
                  '<li><b>Insert:</b> sinks the water a bit lower</li>' +
                  '</ul>',
            onEnter: function() { if (window.tp3dActivateSettingsTab) window.tp3dActivateSettingsTab('elements'); },
            skipIf: function() { return !tp3dIsOsm(); }
        },
        {
            target: tp3dSettingsCard('roads'),
            interactive: true,
            title: 'Road settings',
            text: '<ul class="tp3d-tut-list">' +
                  '<li><b>Checkboxes:</b> which road types to include</li>' +
                  '<li><b>Width Multiplier:</b> thicker or thinner roads</li>' +
                  '<li><b>Height:</b> how far the roads stick out</li>' +
                  '<li><b>Cut Tolerance:</b> small gap around roads in Single Extruder mode, so the pieces fit</li>' +
                  '</ul>',
            skipIf: function() { return !tp3dIsOsm(); }
        },
        {
            target: tp3dInSettings('.tp3d-modal-close-btn'),
            title: 'Close the settings',
            text: 'Your changes are saved right away. Close the settings to continue.',
            waitFor: tp3dTutorial.waitUntil(function() { return !tp3dSettingsOpen(); }),
            waitText: 'Close the settings',
            skipIf: function() { return !tp3dSettingsOpen(); }
        },
        {
            target: '#send',
            placement: 'right',
            title: 'Generate your map',
            text: 'Click <b>Send to Blender</b> to generate your colored map.',
            waitFor: tp3dTutorial.waitForClick('#send'),
            waitText: 'Click Send to Blender',
            skippable: true
        }
    ];
}

// ---- "Use GeoJSON and SVG shapes" ----

function tp3dHasGeojson() {
    return typeof geojsonPaths !== 'undefined' && geojsonPaths.length > 0;
}
function tp3dHasSvgShape() {
    return typeof svgShapePath !== 'undefined' && !!svgShapePath;
}

function tp3dMapTutorialShapes() {
    return [
        {
            target: '#importGeojson',
            placement: 'right',
            title: 'Import a GeoJSON boundary',
            text: 'A GeoJSON file holds a real outline, like a country, region or park border. ' +
                  'Your map takes exactly that shape.<br><br>' +
                  'Click <b>GeoJSON</b> to pick a file, or try our sample of Germany.',
            buttons: [{ label: 'Use sample GeoJSON', onClick: tp3dLoadSampleGeojson }],
            waitFor: tp3dTutorial.waitUntil(tp3dHasGeojson),
            waitText: 'Import a GeoJSON file'
        },
        {
            target: '#map',
            title: 'Your GeoJSON map',
            text: 'The blue outline is your map.<br><br>' +
                  '<b>A GeoJSON area can\'t be moved or resized</b>. It always sits exactly where the file puts it.'
        },
        {
            target: '#importSvgShape',
            placement: 'right',
            title: 'Import an SVG shape',
            text: 'An SVG file can be any outline you like, like a logo, an animal or a star. ' +
                  'It replaces the GeoJSON boundary.<br><br>' +
                  'Click <b>SVG</b> to pick a file, or try our sample star.',
            buttons: [{ label: 'Use sample SVG', onClick: tp3dLoadSampleSvg }],
            waitFor: tp3dTutorial.waitUntil(tp3dHasSvgShape),
            waitText: 'Import an SVG file'
        },
        {
            target: '#map',
            title: 'Place your shape',
            text: 'Unlike a GeoJSON boundary, an SVG shape can be placed anywhere. ' +
                  'Drag the handle in the middle to move it, or a corner to resize it.',
            demo: tp3dDemoMoveShape,
            demoGhost: tp3dDemoMoveGhost,
            demoGhostColor: TP3D_DRAWN_ORANGE,
            waitFor: tp3dWaitForAreaChange('move'),
            waitText: 'Move the shape',
            skippable: true
        },
        {
            target: function() {
                return [document.getElementById('svgShapeList'), document.getElementById('clearSvgShape')];
            },
            placement: 'right',
            title: 'Remove an imported file',
            text: 'To go back to a normal shape, click <b>Clear SVG Shape</b> or pick another shape. ' +
                  'An imported GeoJSON has a <b>Clear GeoJSON</b> button in the same place.'
        }
    ];
}

// ---- "Prefetch elements" ----

// Munich's old town just south-east of Marienplatz, reaching over to the Isar
// -- dense roads and buildings plus the river in a small area, so a prefetch
// is quick and has lots to click.
var TP3D_MUNICH_ALTSTADT_BOUNDS = [[48.1308, 11.5785], [48.1368, 11.5875]];

// Exactly which sub-categories the tutorial asks for (ADVANCED_SETTINGS_STATE
// keys, see COMPOSITE_ELEMENTS in settings_modal.js) -- true = ticked, every
// other one unticked, so the prefetch stays small.
var TP3D_PREFETCH_WATER = { colWPondsActive: true, colWSmallRiversActive: false, colWBigRiversActive: false, elOActive: false };
var TP3D_PREFETCH_ROADS = {
    elSHighwaysActive: false, elSMajorActive: false, elSMinorActive: false, elSResidentialActive: true,
    elSServiceActive: false, elSFootwayActive: false, elSPedestrianActive: true, elSCycleBridleActive: false,
    elSTrackActive: false, elSPathActive: false
};

function tp3dZoomToMunich() {
    placeShapeAroundBounds(L.latLngBounds(TP3D_MUNICH_ALTSTADT_BOUNDS), 0.8);
    if (typeof rectLayer !== 'undefined' && rectLayer) map.fitBounds(rectLayer.getBounds(), { padding: [40, 40] });
}

// Zooms onto the drawn area's top-left quarter, so single prefetched
// elements are big enough to click.
function tp3dZoomToTopLeftQuarter() {
    var b = typeof rectLayer !== 'undefined' && rectLayer ? rectLayer.getBounds()
        : L.latLngBounds(TP3D_MUNICH_ALTSTADT_BOUNDS);
    var c = b.getCenter();
    map.fitBounds(L.latLngBounds([c.lat, b.getWest()], [b.getNorth(), c.lng]), { padding: [20, 20] });
}

// Switches every OSM element off (through the chips' own toggle, so Blender
// gets the same /toggle_element calls a click sends), so the "Turn on some
// elements" step starts from nothing. Only for OSM -- WorldCover's chips are
// a different set, so this runs again once the tutorial has switched to OSM.
function tp3dAllElementsOff() {
    if (!tp3dIsOsm() || typeof TP3D_ELEMENT_STATE === 'undefined') return;
    Object.keys(TP3D_ELEMENT_STATE).forEach(function(key) {
        if (key !== 'elevation' && TP3D_ELEMENT_STATE[key]) tp3dToggleElement(key);
    });
}

// Forgets every prefetch choice, even when no prefetch is drawn (the reset's
// Clear click only fires while that button is showing).
function tp3dResetPrefetch() {
    if (typeof prefetchExcluded === 'undefined') return;
    prefetchExcluded = {};
    prefetchWanted = false;
    clearPrefetch();
    prefetchPersist();
}

function tp3dHasPrefetch() {
    return typeof prefetchFeatures !== 'undefined' && Object.keys(prefetchFeatures).length > 0;
}

// *key* is on and, if *wanted* is given, its sub-checkboxes match it exactly.
function tp3dElementMatches(key, wanted) {
    if (typeof TP3D_ELEMENT_STATE === 'undefined' || !TP3D_ELEMENT_STATE[key]) return false;
    return !wanted || Object.keys(wanted).every(function(f) {
        return !!ADVANCED_SETTINGS_STATE[f] === wanted[f];
    });
}

// Sample cursor for one element step: the chip while the element is off,
// then each sub-checkbox (in the chip's hover list) that still differs from
// *wanted*, one at a time.
function tp3dDemoSetupElement(key, wanted) {
    return function() {
        var wrap = tp3dElementChipWrap(key);
        if (!wrap) return null;
        var el = null;
        if (!TP3D_ELEMENT_STATE[key]) {
            el = wrap.querySelector('.element-chip');
        } else if (wanted) {
            var f = Object.keys(wanted).filter(function(k) { return !!ADVANCED_SETTINGS_STATE[k] !== wanted[k]; })[0];
            if (f) el = wrap.querySelector('.element-flyout input[data-advanced-checkbox="' + f + '"]');
        }
        if (!el) return null;
        var r = el.getBoundingClientRect();
        return [{ x: r.left + Math.min(18, r.width / 2), y: r.top + r.height / 2 }];
    };
}

// Keeps a chip's hover list (element_status.js's tp3dAttachSubFlyout) open
// for the step, reopening it whenever the real mouse leaves and it closes.
var tp3dFlyoutHoldTimer = null;
function tp3dHoldFlyoutOpen(key) {
    tp3dReleaseFlyout(null);
    function open() {
        var wrap = tp3dElementChipWrap(key);
        if (wrap && !wrap.querySelector('.element-flyout')) wrap.dispatchEvent(new MouseEvent('mouseenter'));
    }
    open();
    tp3dFlyoutHoldTimer = setInterval(open, 250);
}
function tp3dReleaseFlyout(key) {
    if (tp3dFlyoutHoldTimer) { clearInterval(tp3dFlyoutHoldTimer); tp3dFlyoutHoldTimer = null; }
    var wrap = key && tp3dElementChipWrap(key);
    if (wrap) wrap.dispatchEvent(new MouseEvent('mouseleave'));
}

// Chip plus its hover list (when open) -- the focus box for an element step.
function tp3dChipAndFlyout(key) {
    return function() {
        var wrap = tp3dElementChipWrap(key);
        return wrap ? [wrap, wrap.querySelector('.element-flyout')].filter(Boolean) : null;
    };
}

// One "turn this element on" action step for the prefetch tutorial.
function tp3dPrefetchElementStep(key, title, text, waitText, wanted) {
    return {
        target: tp3dChipAndFlyout(key),
        placement: 'bottom',
        title: title,
        text: text,
        demo: tp3dDemoSetupElement(key, wanted),
        waitFor: tp3dTutorial.waitUntil(function() { return tp3dElementMatches(key, wanted); }),
        waitText: waitText,
        skippable: true,
        onEnter: wanted ? function() { tp3dHoldFlyoutOpen(key); } : undefined,
        onExit: wanted ? function() { tp3dReleaseFlyout(key); } : undefined
    };
}

// Sample cursor clicks the prefetched building nearest the map's center
// (any element if there are no buildings).
function tp3dDemoClickPrefetched() {
    if (!tp3dHasPrefetch()) return null;
    var box = map.getContainer().getBoundingClientRect();
    var center = { x: box.width / 2, y: box.height / 2 };
    var ids = Object.keys(prefetchFeatures);
    var buildings = ids.filter(function(id) { return prefetchFeatures[id].kind === 'BUILDINGS'; });
    if (buildings.length) ids = buildings;
    var best = null, bestDist = Infinity;
    ids.forEach(function(id) {
        var p = map.latLngToContainerPoint(prefetchFeatures[id].layer.getBounds().getCenter());
        var d = Math.hypot(p.x - center.x, p.y - center.y);
        if (d < bestDist) { best = p; bestDist = d; }
    });
    return best ? [{ x: box.left + best.x, y: box.top + best.y }] : null;
}

function tp3dMapTutorialPrefetch() {
    return [
        {
            target: '.element-source-switch-compact',
            placement: 'bottom',
            title: 'Prefetch elements',
            text: 'Prefetching shows the map elements on the map before you generate, ' +
                  'so you can pick which ones to keep.<br><br>' +
                  '<b>It only works with OSM selected.</b>'
        },
        {
            target: '.element-source-switch-compact',
            placement: 'bottom',
            title: 'Select OSM',
            text: 'Click <b>OSM</b> to switch the element source.',
            waitFor: tp3dTutorial.waitUntil(tp3dIsOsm),
            waitText: 'Click OSM',
            skipIf: tp3dIsOsm
        },
        {
            target: '#map',
            title: 'Munich old town',
            text: 'We zoomed into Munich\'s old town, right next to the river Isar. ' +
                  'The orange box is the area whose elements get prefetched.',
            onEnter: function() {
                tp3dAllElementsOff();
                tp3dZoomToMunich();
            }
        },
        tp3dPrefetchElementStep('buildings', 'Turn on Buildings',
            'Click <b>Buildings</b> to switch it on. Green means on.',
            'Turn on Buildings'),
        tp3dPrefetchElementStep('water', 'Turn on Water',
            'Click <b>Water</b> to switch it on, then tick only <b>Ponds &amp; Lakes</b> in its list.<br><br>' +
            'It also includes wide rivers drawn as water areas, like the Isar.',
            'Water: only Ponds & Lakes', TP3D_PREFETCH_WATER),
        tp3dPrefetchElementStep('roads', 'Turn on Roads',
            'Click <b>Roads</b> to switch it on, then tick only <b>Residential Roads</b> and ' +
            '<b>Pedestrian Streets</b> in its list.',
            'Roads: Residential + Pedestrian', TP3D_PREFETCH_ROADS),
        {
            target: '#prefetchBtn',
            placement: 'bottom',
            title: 'Prefetch',
            text: 'Click <b>Prefetch Elements</b> to load them for your area.',
            waitFor: tp3dTutorial.waitForClick('#prefetchBtn'),
            waitText: 'Click Prefetch Elements'
        },
        {
            target: '#prefetchBtn',
            placement: 'bottom',
            title: 'Loading…',
            text: 'This can take a moment. The elements appear on the map once they are loaded.',
            waitFor: tp3dTutorial.waitUntil(tp3dHasPrefetch),
            waitText: 'Loading elements',
            skippable: true,
            skipIf: tp3dHasPrefetch
        },
        {
            target: '#map',
            title: 'Turn single elements off',
            text: 'Click an element on the map to leave it out. Its fill disappears and only a ' +
                  '<b>dashed outline</b> is left. Click it again to bring it back.',
            // Not an action step: the user can try it as often as they like
            // and moves on with Next.
            interactive: true,
            onEnter: tp3dZoomToTopLeftQuarter,
            demo: tp3dDemoClickPrefetched
        },
        {
            target: '#prefetchInfo',
            interactive: true,
            placement: 'right',
            title: 'The element list',
            text: 'Click a <b>name</b> to hide it on the map. Hidden elements are still generated, ' +
                  'they just aren\'t shown here.<br>' +
                  'Click a <b>number</b> to switch all of that kind off or on.',
            skipIf: function() { return !tp3dHasPrefetch(); }
        },
        {
            target: '#map',
            interactive: true,
            title: 'Shortcuts',
            text: '<ul class="tp3d-tut-list">' +
                  '<li><b>Shift + drag</b> (or <b>Alt + drag</b>): draw a box to switch every element in it off. ' +
                  'If they are all off already, they are switched back on.</li>' +
                  '<li><b>Alt + click</b> on a road: switches the whole road off, not just the clicked segment. ' +
                  'It follows the road through junctions as long as it keeps going straight.</li>' +
                  '</ul>' +
                  'Elements hidden in the list are not affected by the box.',
            skipIf: function() { return !tp3dHasPrefetch(); }
        }
    ];
}

tp3dTutorialMenu({
    button: '#tutorialBtn',
    title: 'Map Generator Tutorials',
    tutorials: [
        {
            id: 'map-generate',
            title: 'Generate Map without GPX file',
            description: 'Pick any place in the world and turn it into a 3D map.',
            prepare: tp3dResetMapGenerator,
            steps: tp3dMapTutorialNoGpx
        },
        {
            id: 'map-generate-gpx',
            title: 'Generate Map with GPX file',
            description: 'Import a recorded route and print it on the terrain.',
            // Hexagon picked before the import, so the shape the import
            // places around the trail is already a hexagon.
            prepare: function() {
                tp3dResetMapGenerator();
                var hexBtn = document.querySelector('.shape-btn[data-shape="hexagon"]');
                if (hexBtn) hexBtn.click();
            },
            steps: tp3dMapTutorialGpx
        },
        {
            id: 'map-colors',
            title: 'Add Colors to the map',
            description: 'Color water, roads and other elements for multi-color printing.',
            prepare: tp3dPrepareColorTutorial,
            steps: tp3dMapTutorialColors
        },
        {
            id: 'map-shapes',
            title: 'Use GeoJSON and SVG shapes',
            description: 'Shape your map like a country border, or any outline from a file.',
            prepare: tp3dResetMapGenerator,
            steps: tp3dMapTutorialShapes
        },
        {
            id: 'map-prefetch',
            title: 'Prefetch elements',
            description: 'Preview roads, buildings and water on the map and leave single ones out.',
            prepare: function() {
                var m = tp3dSettingsModal();
                if (m) m.classList.remove('open');
                tp3dResetMapGenerator();
                tp3dResetPrefetch();
                tp3dAllElementsOff();
            },
            steps: tp3dMapTutorialPrefetch
        }
    ]
});
