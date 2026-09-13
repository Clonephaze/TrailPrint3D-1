# Guides for the TrailPrint3D UI panels.
import textwrap

import bpy  # type: ignore
from bpy.app.translations import (  # type: ignore
    pgettext_iface as _,  # For Translation of Text Required
)


def draw_wrapped_text(layout, text):
    wrapper = textwrap.TextWrapper(width=50)
    # Split on single newlines to catch any manual line breaks
    lines = text.split("\n")

    for line in lines:
        if not line.strip():
            # If it's an empty line (like from a \n\n), just add a blank label
            layout.label(text="")
            continue

        wrapped_lines = wrapper.wrap(text=line)
        for w_line in wrapped_lines:
            layout.label(text=w_line)


def make_help_panel(
    panel_id,
    label,
    text_content,
    doc_url=None,
):
    def draw(self, context):
        layout = self.layout

        # The main tutorial text
        draw_wrapped_text(layout, _(text_content))

        # Optional Link to full documentation/video
        if doc_url:
            layout.separator()
            op = layout.operator("wm.url_open", text="Read More", icon="URL")
            op.url = doc_url

    return type(
        panel_id,
        (bpy.types.Panel,),
        {
            "bl_idname": panel_id,
            "bl_label": _(label),
            "bl_space_type": "VIEW_3D",
            "bl_region_type": "UI",
            "bl_ui_units_x": 14,
            "draw": draw,
        },
    )


classes = [
    make_help_panel(
        "TP3D_PT_help_source",
        "About: Source",
        "Start here. \n\nPick your GPX file, give the trail a name (or leave it blank to reuse the filename), and set where your generated objects should be exported.",
    ),
    make_help_panel(
        "TP3D_PT_help_shape",
        "About: Shape",
        "Choose your shape from a list of available shapes, such as Circle, Hexagon, Square, Ellipse, and custom file-based shapes like SVG and GeoJSON. Some shapes have extra customization options.\n\nSet the shape dimensions you want your final print to have.\n\nThe resolution slider controls the level of detail your shape will have, which affects how much detail your final object will have. Larger values result in higher detail but increase processing time.",
    ),
    make_help_panel(
        "TP3D_PT_help_shape_extras",
        "About: Shape Extras",
        "Here you can adjust fonts, text sizes, symbols where applicable, and other shape-specific extras.\n\nThe text fields go in counter-clockwise order on your shape. You can enter anything you want, or use the special formatting tokens:\n- {name} uses the trail name entered in step 1\n- {length} uses the trail length\n- {elevation} uses the trail elevation\n- {date} uses the trail date\n- {speed} uses the trail speed\n- {scale} uses the trail scale.\nNote: These values are derived from your GPX trail data.",
    ),
    make_help_panel(
        "TP3D_PT_help_scale",
        "About: Scale",
        "Decides how much real-world ground your print represents.\n\nTwo modes: \n- Map Scale: sets the maps to scale itself so the trail fits this percentage of the print area.\n- Coordinates: Calculates the maps scale from two exact latitude/longitude points you enter."
    ),
    make_help_panel(
        "TP3D_PT_help_trail",
        "About: Trail",
        "Settings for the printed trail line.\n\nSet your desired width in mm.\n\nIf you don't have a multicolor printer, you'll want to turn on 'Single Extruder Mode' which will generate the trail as a seperate printable object. You can adjust the trails height, how far it extends above the terrain, and the trails clearance to help fit the pieces together after printing."
    ),
    make_help_panel(
        "TP3D_PT_help_terrain",
        "About: Terrain",
        "Set how you want the surrounding terrain to be represented in your print.\nChoose between:\n- Proportional elevation: Just a scaled version of the real-world terrain\n- Fixed height: Sets the terrain to a specific height, with the highest point of the terrain being exactly this high above the lowest point.\n\nExtra map height allows you to add additional height below the terrain, effectively raising the entire print.\n\nShape Rotation allows you to rotate the shape around the trail/map area\nX and Y offsets let you shift the map within the print area.\n\nSmooth Terrain applies a smoothing algorithm to the terrain surface, reducing blockiness and grid lines or letting lower resolution terrain appear smoother.",
    ),
    make_help_panel(
        "TP3D_PT_help_elements",
        "About: Map Elements",
        "Elements are used when you want to represent specific features on the map, such as roads and buildings, water bodies, forests, and other geographical elements. You can toggle each element on or off depending on what you want to include in your print. Each also comes with a threshold slider, smaller values remove smaller areas.\n\nElement Source:\n- OSM: Open Street Map data, which provides detailed information about roads, buildings, and other man-made features. Recommended most of the time, especially for close up and urban areas.\n- WorldCover: Satellite land-cover data that colors the terrain based on real-world land cover types.\n\n OSM also includes shape smoothing, rounds off the sharp points of the element shapes, and offers a Single Extruder mode which generates each element as individually printable objects.\nRoads in this mode will get their own tolerance slider, and a special depth slider. The depth is to help not cut through every other element unintentionally.",
    ),
    make_help_panel(
        "TP3D_PT_help_appearance",
        "About: Appearance",
        "Changes how included elements get drawn, wether they are formed with a texture or as flat per-face colors. A texture gives a more accurate representation of the element data, regardless of the resolution of the underlying mesh.\nYou can increase the texture resolution to get finer details, but this will increase export and slicing times.\n\nYou can optionally set your trail and road objects to be included in the texture, which will stop them from being seperate objects.",
    ),
]