import math
import os
import platform
from typing import cast

import bmesh  # type: ignore
import bpy  # type: ignore
from bpy.app.translations import pgettext as _
from mathutils import Vector  # type: ignore

from .. import temp
from .mesh_ops import recalculateNormals

try:
    from ..premium.utils_pe import textIcon  # type: ignore[import]
except ImportError:

    def textIcon(*_):
        return None


try:
    from ..premium.utils_pe import add_medal_handle  # type: ignore[import]
except ImportError:

    def add_medal_handle(*_args, **_kwargs):
        return None

# Per base shape: which text layouts are defined. "NONE" is always first so
# it becomes the EnumProperty default when the items list is rebuilt.
TEXT_LAYOUTS_BY_SHAPE = {
    "HEXAGON": ("NONE", "ON_MAP", "OUTER_EDGE", "FRONT_FACE"),
    "OCTAGON": ("NONE", "OUTER_EDGE", "FRONT_FACE"),
    "CIRCLE": ("NONE", "CURVED"),
    "SQUARE": ("NONE",),
    "ELLIPSE": ("NONE",),
    "HEART": ("NONE",),
    "GEOJSON": ("NONE",),
    "SVG": ("NONE",),
}

# Layouts that require a physical plate to sit on. Selecting one of these
# auto-upgrades plateMode from NONE to SOLID_PLATE.
LAYOUTS_REQUIRING_PLATE = frozenset({"OUTER_EDGE", "FRONT_FACE", "CURVED"})

# Per base shape: which plate/shell modes are offered.
PLATE_MODES_BY_SHAPE = {
    "HEXAGON": ("NONE", "SOLID_PLATE", "SHELL"),
    "OCTAGON": ("NONE", "SOLID_PLATE", "SHELL"),
    "CIRCLE": ("NONE", "SOLID_PLATE", "SHELL"),
    "SQUARE": ("NONE", "SOLID_PLATE", "SHELL"),
    "ELLIPSE": ("NONE", "SOLID_PLATE", "SHELL"),
    "HEART": ("NONE", "SOLID_PLATE", "SHELL"),
    "GEOJSON": ("NONE", "SOLID_PLATE"),
    "SVG": ("NONE", "SOLID_PLATE"),
}

_LAYOUT_LABELS = {
    "NONE": (_("None"), _("No text overlay")),
    "ON_MAP": (_("On Map"), _("Text carved into the map surface itself")),
    "OUTER_EDGE": (_("On Plate Surface"), _("Text lies flat on the plate's top ring")),
    "FRONT_FACE": (_("On Plate Sides"), _("Text on the plate's vertical side wall")),
    "CURVED": (_("Curved"), _("Text arced around the plate's ring")),
}

_PLATE_LABELS = {
    "NONE": (_("None"), _("No plate or shell")),
    "SOLID_PLATE": (_("Solid Plate"), _("Solid backplate under the map")),
    "SHELL": (_("Shell"), _("Protective shell around the map")),
}


def text_layout_items(self, context):
    """EnumProperty items callback — depends on self.shape."""
    shape = self.shape or "HEXAGON"
    valid = TEXT_LAYOUTS_BY_SHAPE.get(shape, ("NONE",))
    return [
        (ident, _LAYOUT_LABELS[ident][0], _LAYOUT_LABELS[ident][1]) for ident in valid
    ]


def plate_mode_items(self, context):
    """EnumProperty items callback — depends on self.shape and Premium state."""
    shape = self.shape or "HEXAGON"
    valid = PLATE_MODES_BY_SHAPE.get(shape, ("NONE",))
    items = []
    for i, ident in enumerate(valid):
        label, desc = _PLATE_LABELS[ident]
        if ident == "SHELL" and not temp.PREMIUMVERSION:
            items.append((ident, _("%s (Premium)") % label, desc, "LOCKED", i))
        else:
            items.append((ident, label, desc, "NONE", i))
    return items


def update_text_object(obj_name, new_text):
    """Updates the text of a Blender text object."""
    text_obj = bpy.data.objects.get(obj_name)
    if text_obj and text_obj.type == "FONT":
        text_obj.data.body = new_text


def create_text(
    name,
    text,
    position,
    scale_multiplier,
    rotation=(0, 0, 0),
    extrude=20,
    font_path=None,
):
    txt_data = bpy.data.curves.new(name=name, type="FONT")
    txt_obj = bpy.data.objects.new(name=name, object_data=txt_data)
    bpy.context.collection.objects.link(txt_obj)

    textFont = font_path or bpy.context.scene.tp3d.textFont

    if textFont == "":
        if platform.system() == "Windows":
            textFont = "C:/WINDOWS/FONTS/ariblk.ttf"
        elif platform.system() == "Darwin":
            textFont = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
        else:
            textFont = ""

    txt_data.body = text
    txt_data.extrude = extrude
    # txt_data.font = bpy.data.fonts.load("C:/Windows/Fonts/ariblk.ttf")  # Adjust path if needed
    txt_data.font = bpy.data.fonts.load(textFont)
    txt_data.align_x = "CENTER"
    txt_data.align_y = "CENTER"

    txt_obj.scale = (scale_multiplier, scale_multiplier, 1)
    txt_obj.location = position
    txt_obj.rotation_euler = rotation

    txt_obj.location.z -= 1

    return txt_obj


def appendTextIcon(textobject, icon, scaleM=1):

    addon_dir = os.path.dirname(os.path.dirname(__file__))
    filepath = os.path.join(addon_dir, "assets", "other.blend")

    object_name = icon
    unique_name = f"{object_name}_{textobject.name}"

    # Remove existing objects with the same unique name (from a previous run)
    # and the base name, to ensure a clean append
    for name_to_remove in [unique_name, object_name]:
        old_obj = bpy.data.objects.get(name_to_remove)
        if old_obj:
            bpy.data.objects.remove(old_obj, do_unlink=True)

    # Append the object from the blend file
    with bpy.data.libraries.load(filepath, link=False) as (data_from, data_to): # type: ignore
        if object_name in data_from.objects:
            data_to.objects.append(object_name)
        else:
            print(f"Object '{object_name}' not found in file.")
            return None

    # Get the appended object and rename it to avoid conflicts when
    # multiple slots use the same icon asset
    obj = bpy.data.objects.get(object_name)
    if not obj:
        return None
    obj.name = unique_name

    # Link object to the scene collection
    bpy.context.scene.collection.objects.link(obj)

    # Move object to cursor
    obj.location = textobject.location.copy()
    obj.rotation_euler = textobject.rotation_euler.copy()
    obj.scale.x = scaleM / 5
    obj.scale.y = scaleM / 5

    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval: bpy.types.Object = cast(bpy.types.Object, obj.evaluated_get(depsgraph))
    bbox = [Vector(corner) for corner in obj_eval.bound_box]
    icon_xSize = max(v.x for v in bbox) - min(v.x for v in bbox)

    icon_xSize = icon_xSize * obj.scale.x

    depsgraph = bpy.context.evaluated_depsgraph_get()
    obj_eval = textobject.evaluated_get(depsgraph)
    bbox = [Vector(corner) for corner in obj_eval.bound_box]
    text_xSize = max(v.x for v in bbox) - min(v.x for v in bbox)

    text_xSize = text_xSize / obj.scale.x

    obj.location -= obj.matrix_world.to_3x3() @ Vector((text_xSize / 2 + 0.5, 0, 0))
    textobject.location += textobject.matrix_world.to_3x3() @ Vector(
        (icon_xSize / 2 + 0.5, 0, 0)
    )

    # Make the object active and selected
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    textobject.select_set(True)
    bpy.context.view_layer.objects.active = obj

    return obj


def replaceShapeText(textfield, textobj):

    total_elevation = bpy.context.scene.tp3d.total_elevation
    total_length = bpy.context.scene.tp3d.total_length
    time_str = bpy.context.scene.tp3d.sTime_str
    average_speed = bpy.context.scene.tp3d.average_speed
    trail_date = bpy.context.scene.tp3d.trail_date

    if "{length}" in textfield:
        textfield = textfield.replace("{length}", f"{total_length:.2f}km")
        update_text_object(textobj.name, textfield)
    elif "{elevation}" in textfield:
        textfield = textfield.replace("{elevation}", f"{total_elevation:.2f}m")
        update_text_object(textobj.name, textfield)
    elif "{duration}" in textfield:
        textfield = textfield.replace("{duration}", f"{time_str}")
        update_text_object(textobj.name, textfield)
    elif "{date}" in textfield:
        textfield = textfield.replace("{date}", trail_date)
        update_text_object(textobj.name, textfield)
    elif "{speed}" in textfield:
        textfield = textfield.replace("{speed}", f"{average_speed:.2f} km/h")
        update_text_object(textobj.name, textfield)
    elif "{scale}" in textfield:
        obj_size_mm = bpy.context.scene.tp3d.objSize
        map_scale_ratio = (
            f"1:{round(bpy.context.scene.tp3d.sMapInKm * 1_000_000 / obj_size_mm)}"
            if obj_size_mm != 0
            else ""
        )
        textfield = textfield.replace("{scale}", map_scale_ratio)
        update_text_object(textobj.name, textfield)
    elif "{name}" in textfield:
        nm = bpy.context.scene.tp3d.modelname
        print(f"Name: {nm}")
        textfield = textfield.replace("{name}", f"{nm}")
        update_text_object(textobj.name, textfield)
    else:
        update_text_object(textobj.name, textfield)

    return textfield


def convert_text_to_mesh(text_obj_name, mesh_obj_name, merge=True):
    # Get the text and mesh objects
    text_obj = bpy.data.objects.get(text_obj_name)
    mesh_obj = bpy.data.objects.get(mesh_obj_name)

    if not text_obj or not mesh_obj:
        print("One or both objects not found")
        return

    # Ensure the text object is selected and active
    bpy.ops.object.select_all(action="DESELECT")
    text_obj.select_set(True)
    bpy.context.view_layer.objects.active = text_obj

    # Convert text to mesh
    bpy.ops.object.convert(target="MESH")

    # Enter edit mode
    bpy.ops.object.mode_set(mode="EDIT")

    # Enable auto-merge vertices
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=0.002)
    # bpy.context.tool_settings.use_mesh_automerge = True

    # Switch back to object mode to move it
    bpy.ops.object.mode_set(mode="OBJECT")

    recalculateNormals(text_obj)

    # Move the text object up by 1
    text_obj.location.z += 1

    # Move the text object down by 1 (merging overlapping vertices)
    text_obj.location.z -= 1

    # Disable auto-merge vertices
    bpy.context.tool_settings.use_mesh_automerge = False

    if merge == True:
        # Add boolean modifier
        bool_mod = text_obj.modifiers.new(name="Boolean", type="BOOLEAN")
        bool_mod.object = mesh_obj
        bool_mod.operation = "INTERSECT"
        bool_mod.solver = "MANIFOLD"

        # Apply the boolean modifier
        bpy.ops.object.select_all(action="DESELECT")
        text_obj.select_set(True)
        bpy.context.view_layer.objects.active = text_obj
        bpy.ops.object.modifier_apply(modifier=bool_mod.name)

        # Move the text object up by 1
        text_obj.location.z += 0.4


def convert_text_to_mesh_obj(text_obj, merge=False):
    """Object-based equivalent of convert_text_to_mesh — no name lookup.

    The name-based version does `bpy.data.objects.get(name)` and breaks
    when Blender has suffixed the actual object (e.g. 't_name.003' after
    a prior run left a 't_name' in the scene): it converts the stale
    object instead, leaving the caller's freshly-created font un-meshed.
    Passing the object directly sidesteps all of that.
    """
    from .mesh_ops import recalculateNormals  # cycle-safe

    if text_obj is None or text_obj.type != 'FONT':
        return text_obj

    bpy.ops.object.select_all(action='DESELECT')
    text_obj.select_set(True)
    bpy.context.view_layer.objects.active = text_obj
    bpy.ops.object.convert(target='MESH')

    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles()
    bpy.ops.object.mode_set(mode='OBJECT')

    recalculateNormals(text_obj)
    return text_obj


def _apply_plate_bevel(obj, bevel_amount, thickness):
    """Bevel the top and bottom perimeter edges of a plate object."""
    if bevel_amount <= 0:
        return
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bevel_edges = []
    for edge in bm.edges:
        v0_z = edge.verts[0].co.z
        v1_z = edge.verts[1].co.z
        same_top = abs(v0_z) < 0.01 and abs(v1_z) < 0.01
        same_bottom = abs(v0_z + thickness) < 0.01 and abs(v1_z + thickness) < 0.01
        if same_top or same_bottom:
            for face in edge.link_faces:
                face_z_vals = [v.co.z for v in face.verts]
                if min(face_z_vals) < -0.01 and max(face_z_vals) > -0.01:
                    bevel_edges.append(edge)
                    break
    if bevel_edges:
        bmesh.ops.bevel(
            bm,
            geom=bevel_edges,
            offset=bevel_amount,
            segments=1,
            affect="EDGES",
            profile=0.5,
        )
        bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def wrap_mesh_around_circle(
    obj, radius, base_angle_rad, upper, anchor_x=0.0, anchor_y=0.0
):
    """Bend a flat mesh into an arc of the given radius, centered on base_angle_rad.

    Local X (the flat reading direction) becomes angle around the circle;
    local Y (the flat "up" direction) becomes radial offset from `radius`.
    Local Z (extrusion depth) is left untouched.

    The math treats local (anchor_x, anchor_y) as the piece's own visual
    center, i.e. local coordinates ARE the final world-space position
    (obj.location must be (0, 0, 0) — see caller). Callers with an icon
    joined onto the text should pass the anchor measured from the *text
    alone*, before the icon was joined in: the icon's own bounding box
    rarely matches the text's, so folding it into the center-of-mass would
    drag the text off both its target angle and its target radius by
    however lopsided that particular icon happens to be.

    Upper-half placements keep their "up" pointing outward and read
    clockwise (angle decreases as X increases); lower-half placements read
    counter-clockwise with "up" pointing inward. That split is what makes
    text sitting anywhere on the ring come out right-side up and left-to-
    right readable to a viewer looking straight down at the medal, matching
    how text is conventionally arced on a coin/medal.
    """
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    for v in bm.verts:
        x, y, z = v.co.x - anchor_x, v.co.y - anchor_y, v.co.z
        if upper:
            theta = base_angle_rad - x / radius
            r = radius + y
        else:
            theta = base_angle_rad + x / radius
            r = radius - y
        v.co.x = r * math.cos(theta)
        v.co.y = r * math.sin(theta)
        v.co.z = z
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def BottomText(obj):

    from . import transform_MapObject  # deferred to avoid circular import at load time

    name = obj.name
    if "objSize" in obj:
        size = obj["objSize"]
    else:
        return

        # Place text objects
    text_size = size / 10

    tName = create_text("t_name", "Name", (0, 0, 1.1), text_size)

    cx = obj.location.x
    cy = obj.location.y

    transform_MapObject(tName, cx, cy)

    tName.location.z = obj.location.z + 0.1
    tName.data.extrude = 0.1

    tName.scale.x *= -1

    update_text_object("t_name", name)

    convert_text_to_mesh("t_name", obj.name, False)

    tName.name = name + "_Mark"

    bpy.ops.object.select_all(action="DESELECT")

    tName.select_set(True)

    bpy.context.view_layer.objects.active = tName

    mat = bpy.data.materials.get("TRAIL")
    tName.data.materials.clear()
    tName.data.materials.append(mat)

    return tName
