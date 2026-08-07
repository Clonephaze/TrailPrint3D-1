// Shared base-map setup -- reused by every 2D-map picker page via
// __MAP_INIT_JS__ in picker_server.py. Requires `saveState` to be defined
// later in the including page's own <script> block (only referenced from
// the 'baselayerchange' handler below, which fires on user interaction
// well after the whole page has finished loading, so declaration order
// doesn't matter).
var map = L.map('map').setView([46.57, 7.98], 11);

// The draw/shape/mode toggle panels, coord search box and legend are plain
// DOM children of the #map container (positioned absolutely on top of it)
// rather than L.Control instances, so Leaflet never got a chance to wire up
// its usual click-propagation guard for them. Without it, a mousedown on one
// of these buttons also reaches the map underneath -- e.g. clicking a draw
// mode button while a rectangle draw is armed (waiting for the next map
// mousedown to place the first corner/center) starts drawing right behind
// the button instead of just switching modes. Skip Leaflet's own panes so
// map panning/zooming behavior is untouched.
Array.prototype.forEach.call(document.getElementById('map').children, function (el) {
    if (el.classList.contains('leaflet-pane') || el.classList.contains('leaflet-control-container')) return;
    L.DomEvent.disableClickPropagation(el);
    L.DomEvent.disableScrollPropagation(el);
});

var baseLayers = {
    'Voyager': L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
    }),
    'Satellite': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri'
    }),
    'OpenStreetMap': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors'
    })
};
var activeBaseLayerName = 'OpenStreetMap';
baseLayers[activeBaseLayerName].addTo(map);
L.control.layers(baseLayers, null, { position: 'bottomleft' }).addTo(map);
map.on('baselayerchange', function (e) {
    activeBaseLayerName = e.name;
    saveState();
});
