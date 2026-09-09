// Shared rectangle draw/edit interaction -- reused by every picker page that
// lets the user draw and reshape a single rectangle (puzzleGenerator.html,
// premium/puzzleGenerator_pe.html, premium/slidingPuzzleGenerator.html,
// map_generator.html, premium/map_generator_pe.html,
// premium/multitile_generator.html) via __RECT_EDITOR_JS__ in
// picker_server.py. Covers both 'corner' draw mode (leaflet-draw's own
// corner-to-corner rectangle tool, edited via its native L.Edit.Rectangle
// handles) and 'center' draw mode (click-to-place-center, drag outward,
// edited via this file's own NE/NW/SE/SW marker handles that mirror the
// opposite edge around the fixed center) -- see armCenterDraw/bindCenterEdit.
//
// Expects the including page's own <script> block to already declare (order
// doesn't matter -- these functions only ever run later, in response to user
// interaction, well after the whole page has finished loading):
//   Globals:    map, drawnItems, moveHandleLayer, editHandles, rectLayer,
//               drawControl, coords, currentShape, shapeCenter, drawMode
//   Functions:  saveState, updateSendState, updateStatus, bindLiveEdit
//               (the 'corner' mode counterpart to this file's bindCenterEdit
//               -- enables leaflet-draw's own corner-handle editing on a
//               layer and wires its 'edit' event back into `coords`)
// and to define two small page-specific hooks used by this shared code:
//   function tp3dOnShapeChanged() { ... }
//       Called after any drag/resize of the shape (corner drag, edge-handle
//       drag, move) so the page can recompute whatever it derives from
//       `coords` -- e.g. renderShapePreview()/regeneratePuzzle()/
//       drawSubdivisionGrid() depending on the page.
//   function tp3dRectStyle() { return { weight, fill, fillOpacity }; }
//       The Leaflet style used for the drawn/previewed rectangle -- varies
//       per page (e.g. a lighter fillOpacity on puzzle pages so piece cuts
//       stay visible, or a weight/fill that depends on `currentShape` on
//       pages with more than one selectable shape).
function boundsCenter(b) {
    return { lat: (b.north + b.south) / 2, lng: (b.east + b.west) / 2 };
}

function previewDrawnRect(bounds) {
    drawnItems.clearLayers();
    var style = tp3dRectStyle();
    var rect = L.rectangle([[bounds.south, bounds.west], [bounds.north, bounds.east]], {
        color: '#E97826', weight: style.weight, opacity: 1,
        fill: style.fill, fillOpacity: style.fillOpacity
    });
    drawnItems.addLayer(rect);
    rectLayer = rect;
    return rect;
}

// Picks whichever of the shape's 4 corners is visually closest (in
// screen pixels, so it works the same at any zoom level/latitude) to
// a click -- lets the user grab the border itself to resize, not
// just the small handle markers.
function nearestCorner(latlng, b) {
    var p = map.latLngToLayerPoint(latlng);
    var corners = {
        NE: map.latLngToLayerPoint([b.north, b.east]),
        NW: map.latLngToLayerPoint([b.north, b.west]),
        SE: map.latLngToLayerPoint([b.south, b.east]),
        SW: map.latLngToLayerPoint([b.south, b.west])
    };
    var best = 'NE', bestDist = Infinity;
    Object.keys(corners).forEach(function(k) {
        var dx = p.x - corners[k].x, dy = p.y - corners[k].y;
        var d = dx * dx + dy * dy;
        if (d < bestDist) { bestDist = d; best = k; }
    });
    return best;
}

// Applies a dragged edge's new lat/lng, mirroring the opposite edge
// around shapeCenter in 'center' mode (so the center never moves) or
// leaving it fixed in 'corner' mode -- the same rule applyCornerDrag
// (each axis independently) and bindCenterEdit's handle markers use.
// Clamped so an edge can never get dragged past its own opposite (or,
// in 'center' mode, past the center point itself), which would
// otherwise invert the box.
var MIN_DEG = 1e-6;

function applyEdgeDrag(edge, value) {
    if (drawMode === 'center' && shapeCenter) {
        if (edge === 'north') {
            coords.north = Math.max(value, shapeCenter.lat + MIN_DEG);
            coords.south = 2 * shapeCenter.lat - coords.north;
        } else if (edge === 'south') {
            coords.south = Math.min(value, shapeCenter.lat - MIN_DEG);
            coords.north = 2 * shapeCenter.lat - coords.south;
        } else if (edge === 'east') {
            coords.east = Math.max(value, shapeCenter.lng + MIN_DEG);
            coords.west = 2 * shapeCenter.lng - coords.east;
        } else {
            coords.west = Math.min(value, shapeCenter.lng - MIN_DEG);
            coords.east = 2 * shapeCenter.lng - coords.west;
        }
    } else if (edge === 'north') {
        coords.north = Math.max(value, coords.south + MIN_DEG);
    } else if (edge === 'south') {
        coords.south = Math.min(value, coords.north - MIN_DEG);
    } else if (edge === 'east') {
        coords.east = Math.max(value, coords.west + MIN_DEG);
    } else {
        coords.west = Math.min(value, coords.east - MIN_DEG);
    }
}

// A corner drag moves both of its axes at once -- e.g. dragging the
// NE corner sets north from the new lat AND east from the new lng,
// each going through applyEdgeDrag above so 'center' mode still
// mirrors both the opposite lat edge and the opposite lng edge
// around shapeCenter.
function applyCornerDrag(corner, latlng) {
    applyEdgeDrag(corner[0] === 'N' ? 'north' : 'south', latlng.lat);
    applyEdgeDrag(corner[1] === 'E' ? 'east' : 'west', latlng.lng);
}

// Set by bindCenterEdit() while its handle markers exist, so a
// border-drag (bindCornerDrag below) can keep them in sync too
// without needing to know anything about them directly.
var syncCenterHandles = null;

function syncShapeAfterEdgeChange() {
    if (rectLayer) rectLayer.setBounds([[coords.south, coords.west], [coords.north, coords.east]]);
    if (syncCenterHandles) syncCenterHandles();
    syncMoveHandlePosition();
    tp3dOnShapeChanged();
}

// Repositions the move handle onto the shape's current center without
// recreating it -- called after any resize (corner drag, edge-handle
// drag, leaflet-draw's own editing) so it doesn't drift off-center.
// bindMoveHandle() itself only runs when the shape is (re)created.
function syncMoveHandlePosition() {
    if (!coords) return;
    moveHandleLayer.eachLayer(function(m) { m.setLatLng(boundsCenter(coords)); });
}

function moveHandleIcon() {
    return L.divIcon({
        className: 'move-handle', iconSize: [22, 22], iconAnchor: [11, 11],
        html: '<svg viewBox="0 0 20 20" width="14" height="14" fill="#fff"><path d="M10 1l-3 3h2v4H5V6l-3 3 3 3v-2h4v4H7l3 3 3-3h-2v-4h4v2l3-3-3-3v2h-4V4h2z"/></svg>'
    });
}

// A single draggable marker at the shape's center that translates the
// whole rectangle (and shapeCenter, in 'center' mode) without resizing
// it -- unlike bindCornerDrag, which always resizes from the nearest
// corner no matter where on the shape you grab it. In 'corner' mode,
// leaflet-draw's own corner-handle editing is disabled for the drag's
// duration and re-enabled after, same reasoning as bindCornerDrag: its
// markers only reposition themselves via their own drag handlers, so
// they'd otherwise go stale while this moves the layer's bounds
// directly.
function bindMoveHandle() {
    moveHandleLayer.clearLayers();
    if (!coords) return;
    var wasCornerEditing = false;
    var dragStart = null, startCoords = null, startCenter = null;
    var marker = L.marker(boundsCenter(coords), { draggable: true, icon: moveHandleIcon() });
    marker.on('dragstart', function(e) {
        wasCornerEditing = drawMode === 'corner' && rectLayer.editing && rectLayer.editing.enabled();
        if (wasCornerEditing) rectLayer.editing.disable();
        dragStart = e.target.getLatLng();
        startCoords = { north: coords.north, south: coords.south, east: coords.east, west: coords.west };
        startCenter = shapeCenter ? { lat: shapeCenter.lat, lng: shapeCenter.lng } : null;
    });
    marker.on('drag', function(e) {
        var cur = e.target.getLatLng();
        var dLat = cur.lat - dragStart.lat, dLng = cur.lng - dragStart.lng;
        coords.north = startCoords.north + dLat;
        coords.south = startCoords.south + dLat;
        coords.east = startCoords.east + dLng;
        coords.west = startCoords.west + dLng;
        if (startCenter) shapeCenter = { lat: startCenter.lat + dLat, lng: startCenter.lng + dLng };
        rectLayer.setBounds([[coords.south, coords.west], [coords.north, coords.east]]);
        if (syncCenterHandles) syncCenterHandles();
        tp3dOnShapeChanged();
    });
    marker.on('dragend', function() {
        if (wasCornerEditing) bindLiveEdit(rectLayer);
        saveState();
    });
    moveHandleLayer.addLayer(marker);
}

// Lets the user grab the rectangle's own border (not just a handle
// marker) to resize it by whichever corner is nearest -- works in
// both draw modes, mirroring in 'center' mode via applyCornerDrag
// above. In 'corner' mode, leaflet-draw's own corner-handle editing
// is disabled for the duration of the drag and cleanly re-enabled
// after (which re-reads the layer's bounds fresh) rather than left
// running alongside this -- leaflet-draw only repositions its corner
// markers from their OWN drag handlers, so this layer's bounds
// changing externally would otherwise leave them silently out of
// sync with the shape.
function bindCornerDrag(layer) {
    layer.off('mousedown', layer._tp3dCornerDown);
    layer._tp3dCornerDown = function(e) {
        L.DomEvent.stopPropagation(e);
        var wasCornerEditing = drawMode === 'corner' && layer.editing && layer.editing.enabled();
        if (wasCornerEditing) layer.editing.disable();
        var corner = nearestCorner(e.latlng, coords);
        map.dragging.disable();
        function onMove(e2) {
            applyCornerDrag(corner, e2.latlng);
            syncShapeAfterEdgeChange();
        }
        function onUp() {
            map.off('mousemove', onMove);
            map.off('mouseup', onUp);
            map.dragging.enable();
            if (wasCornerEditing) bindLiveEdit(layer);
            saveState();
        }
        map.on('mousemove', onMove);
        map.on('mouseup', onUp);
    };
    layer.on('mousedown', layer._tp3dCornerDown);
}

// Tracks whether a draw tool is currently armed -- i.e. the Draw
// button was clicked and the map is waiting for the user to place a
// shape, but nothing has been finalized yet. Needed so switching the
// corner/center mode mid-arm can cancel the OLD mode's still-active
// handler and re-arm the NEW one -- otherwise the stale handler (e.g.
// leaflet-draw's corner-to-corner rectangle tool) silently completes
// in the wrong mode on the next click/drag, ignoring the mode switch.
var drawArmed = false;
var cancelCenterDraw = null; // set while armCenterDraw's mousedown listener is pending

function armDraw() {
    disarmDraw();
    drawArmed = true;
    if (drawMode === 'center') {
        armCenterDraw();
    } else {
        map.removeControl(drawControl);
        drawControl = makeDrawControl();
        map.addControl(drawControl);
        setTimeout(function() {
            var rb = document.querySelector('.leaflet-draw-draw-rectangle');
            if (rb) rb.click();
        }, 50);
    }
}

function disarmDraw() {
    if (!drawArmed) return;
    drawArmed = false;
    if (cancelCenterDraw) {
        cancelCenterDraw();
        cancelCenterDraw = null;
    }
    var handler = drawControl._toolbars && drawControl._toolbars.draw &&
        drawControl._toolbars.draw._modes.rectangle && drawControl._toolbars.draw._modes.rectangle.handler;
    if (handler && handler.enabled()) handler.disable();
}

// 'Center' draw mode: click sets the center point, dragging outward
// grows the box symmetrically around it (mirrors bindCenterEdit's own
// "opposite edge moves too" editing behavior for the initial draw).
// Bypasses leaflet-draw's own rectangle tool entirely -- that tool is
// inherently corner-to-corner, with no supported way to redefine it
// as center-out.
function armCenterDraw() {
    map.dragging.disable();
    map.getContainer().style.cursor = 'crosshair';
    function onFirstMouseDown(e) {
        cancelCenterDraw = null;
        drawArmed = false;
        var center = e.latlng;
        function onMove(e2) {
            var dLat = Math.abs(e2.latlng.lat - center.lat);
            var dLng = Math.abs(e2.latlng.lng - center.lng);
            previewDrawnRect({
                north: center.lat + dLat, south: center.lat - dLat,
                east: center.lng + dLng, west: center.lng - dLng
            });
        }
        function onUp(e3) {
            map.off('mousemove', onMove);
            map.off('mouseup', onUp);
            map.dragging.enable();
            map.getContainer().style.cursor = '';
            var dLat = Math.abs(e3.latlng.lat - center.lat);
            var dLng = Math.abs(e3.latlng.lng - center.lng);
            finalizeCenterShape({
                north: center.lat + dLat, south: center.lat - dLat,
                east: center.lng + dLng, west: center.lng - dLng
            }, center);
        }
        map.on('mousemove', onMove);
        map.on('mouseup', onUp);
    }
    map.once('mousedown', onFirstMouseDown);
    cancelCenterDraw = function() {
        map.off('mousedown', onFirstMouseDown);
        map.dragging.enable();
        map.getContainer().style.cursor = '';
    };
}

function finalizeCenterShape(bounds, center) {
    if (bounds.north === bounds.south || bounds.east === bounds.west) {
        drawnItems.clearLayers();
        return; // Zero-size click-without-dragging -- nothing to keep.
    }
    coords = { north: bounds.north, south: bounds.south, east: bounds.east, west: bounds.west, type: currentShape };
    shapeCenter = { lat: center.lat, lng: center.lng };
    var rect = previewDrawnRect(coords);
    bindCornerDrag(rect);
    bindCenterEdit();
    bindMoveHandle();
    tp3dOnShapeChanged();
    updateSendState();
    updateStatus();
    saveState();
}

// Custom edit handles for 'center' mode -- NE/NW/SE/SW corner markers
// that, when dragged, move both of that corner's edges AND mirror
// both opposite edges the same distance the other way so shapeCenter
// never moves. Deliberately not leaflet-draw's own L.Edit.Rectangle
// corner handles (used in 'corner' mode via bindLiveEdit) -- those
// are hardcoded to keep the OPPOSITE corner fixed, the opposite of
// what 'center' mode needs, and aren't designed to be reprogrammed
// to mirror instead.
function bindCenterEdit() {
    editHandles.clearLayers();
    syncCenterHandles = null;
    if (!coords || !shapeCenter) return;

    function handleIcon() {
        return L.divIcon({ className: 'edge-handle', iconSize: [10, 10], iconAnchor: [5, 5] });
    }

    var neHandle = L.marker([coords.north, coords.east], { draggable: true, icon: handleIcon() });
    var nwHandle = L.marker([coords.north, coords.west], { draggable: true, icon: handleIcon() });
    var seHandle = L.marker([coords.south, coords.east], { draggable: true, icon: handleIcon() });
    var swHandle = L.marker([coords.south, coords.west], { draggable: true, icon: handleIcon() });

    syncCenterHandles = function() {
        neHandle.setLatLng([coords.north, coords.east]);
        nwHandle.setLatLng([coords.north, coords.west]);
        seHandle.setLatLng([coords.south, coords.east]);
        swHandle.setLatLng([coords.south, coords.west]);
    };

    neHandle.on('drag', function(e) { applyCornerDrag('NE', e.target.getLatLng()); syncShapeAfterEdgeChange(); });
    nwHandle.on('drag', function(e) { applyCornerDrag('NW', e.target.getLatLng()); syncShapeAfterEdgeChange(); });
    seHandle.on('drag', function(e) { applyCornerDrag('SE', e.target.getLatLng()); syncShapeAfterEdgeChange(); });
    swHandle.on('drag', function(e) { applyCornerDrag('SW', e.target.getLatLng()); syncShapeAfterEdgeChange(); });
    [neHandle, nwHandle, seHandle, swHandle].forEach(function(h) {
        h.on('dragend', saveState);
        editHandles.addLayer(h);
    });
}

// Switching modes applies immediately to whatever's currently drawn,
// not just the next draw action -- corner-to-center adopts the
// current bounding box's own center as the new fixed shapeCenter;
// center-to-corner just drops back to leaflet-draw's own handles.
function setDrawMode(mode) {
    var wasArmed = drawArmed;
    drawMode = mode;
    document.querySelectorAll('.draw-mode-btn').forEach(function(b) {
        b.classList.toggle('active', b.getAttribute('data-mode') === mode);
    });
    if (wasArmed) {
        // Draw button was already clicked and the map is still waiting
        // for the user to place a shape -- re-arm with the newly
        // selected mode instead of leaving the old mode's handler
        // active underneath.
        armDraw();
    } else if (coords && rectLayer) {
        if (mode === 'center') {
            shapeCenter = boundsCenter(coords);
            if (rectLayer.editing) rectLayer.editing.disable();
            bindCenterEdit();
        } else {
            editHandles.clearLayers();
            syncCenterHandles = null;
            shapeCenter = null;
            bindLiveEdit(rectLayer);
        }
        bindCornerDrag(rectLayer);
        bindMoveHandle();
    }
    saveState();
}

function makeDrawControl() {
    return new L.Control.Draw({
        draw: { polyline: false, polygon: false, circle: false, marker: false, circlemarker: false, rectangle: true },
        // No edit toolbar — the rectangle is already always draggable via
        // bindLiveEdit(), and drawing a new one clears the old via
        // drawnItems.clearLayers(), so the separate Edit/Delete buttons
        // would just be redundant UI.
        edit: false
    });
}
