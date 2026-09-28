import platform
import random
import webbrowser

import bmesh  # type: ignore
import bpy  # type: ignore
from mathutils import Vector, bvhtree  # type: ignore


def open_website(self, context, url="https://patreon.com/EmGi3D?utm_source=Blender"):
    print(url)
    webbrowser.open(url)


def transform_MapObject(obj, newX, newY):
    obj.location.x += newX
    obj.location.y += newY


def zoom_camera_to_objects(objs):
    """Select every object in *objs* and zoom the 3D viewport to fit all of
    them. Pass a one-item list for a single object; for results made of
    several separate objects (e.g. puzzle pieces) pass them all, since
    fitting to just one would zoom in too far and miss the rest."""
    objs = [o for o in (objs or []) if o is not None]
    if not objs:
        return
    try:
        _ = objs[0].select_set  # raises ReferenceError if the object was freed
    except ReferenceError:
        return

    bpy.ops.object.select_all(action='DESELECT')
    for o in objs:
        try:
            o.select_set(True)
        except ReferenceError:
            continue
    bpy.context.view_layer.objects.active = objs[0]

    area = next(area for area in bpy.context.screen.areas if area.type == "VIEW_3D")
    region = area.regions[-1]

    with bpy.context.temp_override(area=area, region=region):
        bpy.ops.view3d.view_selected(use_all_regions=False)


def set_origin_to_3d_cursor(tobj=None):
    if tobj is None:
        tobj = bpy.context.active_object

    bpy.ops.object.select_all(action='DESELECT')

    bpy.context.view_layer.objects.active = tobj
    tobj.select_set(True)
    bpy.ops.object.origin_set(type='ORIGIN_CURSOR')


def remove_objects(objects):
    """
    Remove a single object or a list of objects efficiently (script-friendly).
    """
    if not objects:
        return

    # Ensure it's always a list
    if not isinstance(objects, (list, tuple)):
        objects = [objects]

    objects = [obj for obj in objects if obj is not None]
    if not objects:
        return

    try:
        # Fast path: select all and delete in one operator call, triggering only
        # a single depsgraph update instead of one per object. Requires a valid
        # viewport context, so it will raise RuntimeError in background/headless mode.
        bpy.ops.object.select_all(action='DESELECT')
        for obj in objects:
            # select_set() is a no-op on a hidden object -- it never reaches
            # context.selected_objects, so bpy.ops.object.delete() silently
            # skips it. Unhide right before deleting to avoid that.
            if obj.hide_get():
                obj.hide_set(False)
            obj.select_set(True)
        bpy.ops.object.delete()
    except RuntimeError:
        # Fallback for background, headless, or modal contexts where bpy.ops is
        # unavailable. Slower for large lists due to per-object depsgraph updates.
        for obj in objects:
            for col in obj.users_collection:
                col.objects.unlink(obj)
            bpy.data.objects.remove(obj)


def getHighestLowest(obj):

    # Get the bounding box corners in world space
    world_matrix = obj.matrix_world
    corners = [world_matrix @ Vector(corner) for corner in obj.bound_box]

    # Extract the Z values
    z_values = [c.z for c in corners]

    highest_z = max(z_values)
    lowest_z = min(z_values)

    return lowest_z, highest_z

def show_message_box(message, ic = "ERROR", ti = "ERROR"):
    def draw(self, context):
        self.layout.label(text=message)
    print(message)
    if not bpy.app.background:
        bpy.context.window_manager.popup_menu(draw, title=ti, icon=ic)


def importSVGtoMerge(Mapobject):
    from .mesh_ops import (
        merge_objects,  # deferred to avoid circular import at load time
    )

    svg_path = bpy.context.scene.tp3d.svg_path
    extrude_depth = 0.01
    scale_factor = 100.0

    # -----------------------
    # 1. Import SVG
    # -----------------------

    # Objects before import
    before = set(bpy.data.objects)
    before_collections = set(bpy.data.collections)

    bpy.ops.import_curve.svg(filepath=svg_path)

    # Objects after import
    after = set(bpy.data.objects)

    # Move SVG objects from the auto-created collection to Scene Collection and remove it
    scene_col = bpy.context.scene.collection
    for new_col in set(bpy.data.collections) - before_collections:
        for obj in list(new_col.all_objects):
            if not scene_col.objects.get(obj.name):
                scene_col.objects.link(obj)
        bpy.data.collections.remove(new_col, do_unlink=True)

    # Newly created objects
    svg_objs = [obj for obj in after - before if obj.type == 'CURVE']



    for obj in svg_objs:
        curve = obj.data

        # Curve setup (preserve holes)
        curve.dimensions = '2D'
        curve.fill_mode = 'BOTH'
        curve.use_fill_caps = True

        curve.bevel_depth = 0
        curve.bevel_resolution = 0

        curve.extrude = extrude_depth


        # Scale SVG
        obj.scale *= scale_factor


        # Convert to mesh
        bpy.ops.object.select_all(action='DESELECT')

        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        bpy.ops.object.convert(target='MESH')

        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)


        bpy.ops.object.mode_set(mode='EDIT')

        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.remove_doubles(threshold=0.0001)  # Works in all 2.8+ versions

        bpy.ops.object.mode_set(mode='OBJECT')

    bpy.ops.object.select_all(action='DESELECT')
    svg = merge_objects(svg_objs)

    svg.select_set(True)
    bpy.context.view_layer.objects.active = svg

    bpy.ops.object.origin_set(
        type='ORIGIN_GEOMETRY',
        center='BOUNDS'
    )

    # Move object so origin is at world center
    svg.location = bpy.context.scene.cursor.location

    return svg
