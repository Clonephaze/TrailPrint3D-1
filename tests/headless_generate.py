"""
TrailPrint3D headless generator with browser-based configuration UI.

Opens a local web page where you can set the GPX file, export folder,
shape, and all other options.  Click "Generate" to start; click "Quit"
to shut Blender down cleanly.

Usage:
    blender --background --python tests/headless_generate.py

The addon must already be installed in Blender (Edit > Preferences >
Add-ons > Install from zip).
"""

import bpy
import os

# ---------------------------------------------------------------------------
# Enable the addon
# ---------------------------------------------------------------------------

bpy.ops.preferences.addon_enable(module="TrailPrint3D")

# Import the headless UI server from the now-registered addon package
from TrailPrint3D.headless_ui import HeadlessConfigServer

# ---------------------------------------------------------------------------
# Apply a config dict to the scene properties
# ---------------------------------------------------------------------------

def apply_config(cfg: dict):
    tp3d = bpy.context.scene.tp3d

    tp3d.file_path          = cfg.get("gpx_file", "")
    tp3d.export_path        = cfg.get("export_path", "")
    tp3d.shape              = cfg.get("shape", "HEXAGON")
    tp3d.objSize            = int(cfg.get("obj_size", 100))
    tp3d.scaleElevation     = float(cfg.get("elev_scale", 1.0))
    tp3d.num_subdivisions   = int(cfg.get("resolution", 4))
    tp3d.minThickness       = float(cfg.get("min_thickness", 2.0))
    tp3d.api                = cfg.get("api", "TERRAIN-TILES")
    tp3d.elementMode        = cfg.get("element_mode", "PAINT")
    tp3d.singleColorMode    = bool(cfg.get("single_color_mode", False))

    # OSM elements
    tp3d.col_wPondsActive       = bool(cfg.get("water", False))
    tp3d.col_wBigRiversActive   = bool(cfg.get("rivers_big", False))
    tp3d.col_wSmallRiversActive = bool(cfg.get("rivers_small", False))
    tp3d.col_fActive            = bool(cfg.get("forest", False))
    tp3d.col_cActive            = bool(cfg.get("cities", False))
    tp3d.col_grActive           = bool(cfg.get("greenspace", False))
    tp3d.el_bActive             = bool(cfg.get("buildings", False))
    tp3d.el_sBigActive          = bool(cfg.get("roads_big", False))
    tp3d.el_sMedActive          = bool(cfg.get("roads_med", False))
    tp3d.el_sSmallActive        = bool(cfg.get("roads_small", False))

    tp3d.disable_auto_export = False

    # Ensure export folder exists
    export_path = tp3d.export_path
    if export_path:
        os.makedirs(export_path, exist_ok=True)

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

server = HeadlessConfigServer()
server.start()

print("TrailPrint3D: waiting for input in the browser…")

while True:
    config = server.wait_for_generate()

    if config is None:
        print("TrailPrint3D: quit requested — shutting down.")
        break

    print(f"TrailPrint3D: starting generation for {config.get('gpx_file', '?')}")
    apply_config(config)

    try:
        bpy.ops.tp3d.run_generation()
        export_path = bpy.context.scene.tp3d.export_path
        server.notify_done(export_path)
        print(f"TrailPrint3D: done — exported to {export_path}")
    except Exception as e:
        server.notify_error(str(e))
        print(f"TrailPrint3D: generation failed — {e}")

server.stop()
