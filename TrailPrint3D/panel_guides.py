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
        "Decides how much real-world ground your print represents. "
        "Two modes: Map Scale sets it based on your GPX trail's own "
        "size; Coordinates instead calculates it from two exact "
        "latitude/longitude points you enter.\n\n"
        "This section comes after Shape on purpose — the "
        "calculation needs the object size you set there.\n\n"
        "[YOUR CALL: when you'd reach for Coordinates over Map "
        "Scale in practice.]",
    ),
    make_help_panel(
        "TP3D_PT_help_trail",
        "About: Trail",
        "Settings for the printed trail line itself.  \n\nSet the mm width of the trail, choose if you want it to be made in Single-color mode, and adjust its height from the terrain if applicable.",
    ),
    make_help_panel(
        "TP3D_PT_help_terrain",
        "About: Terrain",
        "Controls for the terrain surrounding the trail. \n\nAdjust the height, smoothing, and other terrain-specific settings to achieve the desired topography.",
    ),
    make_help_panel(
        "TP3D_PT_help_elements",
        "About: Elements",
        "Settings for the various map elements such as roads, buildings, and vegetation. \n\nAdjust their visibility, height, and other properties to customize the map's appearance.",
    ),
    make_help_panel(
        "TP3D_PT_help_appearance",
        "About: Appearance",
        "Settings for the visual appearance of the map. \n\nColors, textures, and other aesthetic options to enhance the overall look of the printed map.",
    ),
    make_help_panel(
        "TP3D_PT_help_elementSource",
        "About: Element Sources",
        "Choose the source of map elements \n\nOSM: OpenStreetMap, good for maps less than 500km (310 miles) in size",
    ),
]
