// Shared base-map setup -- reused by every 2D-map picker page via
// __MAP_INIT_JS__ in picker_server.py. Requires `saveState` to be defined
// later in the including page's own <script> block (only referenced from
// the 'baselayerchange' handler below, which fires on user interaction
// well after the whole page has finished loading, so declaration order
// doesn't matter).
var map = L.map('map').setView([46.57, 7.98], 11);

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
