import math
import time

import bpy  # type: ignore
from mathutils import Vector  # type: ignore

from ... import progress as _progress
from .elements import (
    _rg_apply_single_color_mode,
    _rg_build_terrain_elements,
)
from .output import _rg_assign_materials
from ..ui_state import build_fetch_items

# ---------------------------------------------------------------------------
# createTerrainFromSelected sub-phase helpers
#
# Builds terrain on already-placed tile objects (blanks dropped by the map
# picker / puzzle picker / Extend flows) rather than running runGeneration's
# own from-scratch GPX pipeline -- shares the same _rg_* building blocks
# above, just driven from a different entry point.
# ---------------------------------------------------------------------------


def _ctfs_load_props():
    """Load all settings needed by createTerrainFromSelected from the scene."""
    tp3d = bpy.context.scene.tp3d
    return {
        "scaleElevation": tp3d.scaleElevation,
        "api": tp3d.api,
        "minThickness": tp3d.minThickness,
        "autoScale": tp3d.sAutoScale,
        "singleColorMode": tp3d.singleColorMode,
        "elementMode": tp3d.elementMode,
        "selfHosted": tp3d.selfHosted,
        "indipendendTiles": tp3d.indipendendTiles,
        "additionalExtrusion": tp3d.sAdditionalExtrusion,
        "scaleHor": tp3d.get("sScaleHor", 1),
    }


def _ctfs_apply_elevation(zobj, props, progress_cb=None, skip_bottom_recess=False):
    """Fetch terrain elevation, apply to vertices, extrude bottom face, shift to z=0.

    Returns (lowestZ, highestZ, additionalExtrusion).
    The returned additionalExtrusion may differ from props['additionalExtrusion']
    when indipendendTiles is True.

    skip_bottom_recess: the recess-the-bottom-face safety net below exists to
    keep an EXTENDED tile's surface seamless with a neighbor it has to match
    baselines with -- additionalExtrusion is deliberately locked to that
    neighbor's own lowest point, so this tile's own terrain can legitimately
    dip below it. A fresh single tile with no neighbor to match (e.g. a
    puzzle blank) has additionalExtrusion set to ITS OWN lowest point, so
    clearance should always equal minThickness exactly -- any shortfall there
    is just float-precision noise between the caller's own preview lowestZ
    pass and this function's, not a real seam to protect, and the 1mm-step
    loop below would force at least a 1mm recess off that noise alone.
    """
    from ..elevation import (
        get_tile_elevation,  # deferred to avoid circular import at load time
    )
    from ..geo import (
        convert_to_geo,  # deferred to avoid circular import at load time
    )

    scaleElevation = props["scaleElevation"]
    autoScale = props["autoScale"]
    minThickness = props["minThickness"]
    additionalExtrusion = props["additionalExtrusion"]
    indipendendTiles = props["indipendendTiles"]

    print(f"additionalExtrusion: {additionalExtrusion}")

    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    tileVerts, _diff = get_tile_elevation(zobj, progress_cb=progress_cb)

    # Reset scene property to original value before this tile
    bpy.context.scene.tp3d.sAdditionalExtrusion = additionalExtrusion

    if len(tileVerts) < 500:
        _progress.WarningsOverlay.add_warning(
            f"Mesh has only {len(tileVerts)} Points. Increase Resolution for higher Quality",
            "warn",
        )

    # Find elevation range
    mesh = zobj.data
    lowestZ = 1000
    highestZ = 0
    _obj_matrix = zobj.matrix_world
    for i, vert in enumerate(mesh.vertices):
        _world_co = _obj_matrix @ vert.co
        _vert_lat, _unused_var = convert_to_geo(_world_co.x, _world_co.y)
        _merc = 1 / math.cos(math.radians(_vert_lat))
        val = tileVerts[i] / 1000 * scaleElevation * autoScale * _merc
        lowestZ = min(lowestZ, val)
        highestZ = max(highestZ, val)

    if indipendendTiles:
        additionalExtrusion = lowestZ

    # Apply elevation to vertices
    for i, vert in enumerate(mesh.vertices):
        _world_co = _obj_matrix @ vert.co
        _vert_lat, _unused_var = convert_to_geo(_world_co.x, _world_co.y)
        _merc = 1 / math.cos(math.radians(_vert_lat))
        vert.co.z = tileVerts[i] / 1000 * scaleElevation * autoScale * _merc
        lowestZ = min(lowestZ, vert.co.z)
        highestZ = max(highestZ, vert.co.z)

    # Extrude bottom face and set its z
    bpy.context.view_layer.objects.active = zobj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.extrude_region_move()
    bpy.ops.transform.translate(value=(0, 0, -8))
    bpy.ops.mesh.dissolve_faces()
    bpy.ops.object.mode_set(mode="OBJECT")

    mesh = zobj.data
    selected_faces = [face for face in mesh.polygons if face.select]
    if selected_faces:
        for face in selected_faces:
            for vert_idx in face.vertices:
                mesh.vertices[vert_idx].co.z = additionalExtrusion - minThickness
    else:
        print("No face selected.")

    # Shift geometry so bottom sits at correct z
    bpy.context.view_layer.objects.active = zobj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.transform.translate(value=(0, 0, -additionalExtrusion + minThickness))
    bpy.ops.object.mode_set(mode="OBJECT")

    # When extending, additionalExtrusion is locked to an older tile's own
    # lowest point so the terrain surface stays seamless across the join. If
    # this tile's own terrain dips lower than that, the bottom (always at
    # z=0 by construction above) leaves less than minThickness of material —
    # or goes negative — at the low point. Recess just the bottom face
    # further down in 1mm steps until clearance is restored.
    #
    # Only triggers below HALF of minThickness (not the full value) -- a
    # small shortfall here is normal/harmless (e.g. float-precision noise,
    # or genuinely just a bit thin) and forcing a 1mm recess for every minor
    # case was overzealous; this only steps in once it's actually thin
    # enough to matter structurally.
    if not skip_bottom_recess:
        min_clearance = minThickness / 2
        clearance = lowestZ - additionalExtrusion + minThickness
        bottom_drop = 0.0
        while clearance < min_clearance:
            bottom_drop += 1.0
            clearance += 1.0
        if bottom_drop > 0 and selected_faces:
            for face in selected_faces:
                for vert_idx in face.vertices:
                    mesh.vertices[vert_idx].co.z -= bottom_drop
            _progress.WarningsOverlay.add_warning(
                f"{zobj.name}: base recessed {bottom_drop:.0f}mm to keep the terrain seamless with the existing map",
                "warn",
            )

    return lowestZ, highestZ, additionalExtrusion, len(tileVerts)


def _ctfs_handle_trail(zobj, duplicate, singleColorMode):
    """Intersect or project trail curves onto this tile.

    In normal mode (singleColorMode=False): creates one extruded duplicate per
    _Trail curve and intersects each individually, returning a list of results.
    In single-color mode (singleColorMode=True): copies each trail curve for later
    processing by _rg_apply_single_color_mode.

    Returns curveObjs list (may be empty).
    """
    from ..mesh_ops import (
        intersect_trail_with_existing_box,  # deferred to avoid circular import at load time
    )

    def _xy_extents(obj):
        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        return min(xs), max(xs), min(ys), max(ys)

    tx_min, tx_max, ty_min, ty_max = _xy_extents(zobj)

    def _near_tile(ob):
        cx_min, cx_max, cy_min, cy_max = _xy_extents(ob)
        return (
            cx_min <= tx_max
            and cx_max >= tx_min
            and cy_min <= ty_max
            and cy_max >= ty_min
        )

    search_str = "_Trail"
    matches = [
        ob
        for ob in bpy.context.view_layer.objects
        if search_str in ob.name and _near_tile(ob)
    ]
    curveObjs = []

    print(f"matches: {matches}")

    if singleColorMode and matches:
        for c in matches:
            if c.type == "CURVE":
                cd = c.copy()
                cd.data = c.data.copy()
                bpy.context.collection.objects.link(cd)
                curveObjs.append(cd)

    elif not singleColorMode and matches:
        trail_matches = [
            ob
            for ob in matches
            if ob.type in {"CURVE", "MESH"}
            and not ob.hide_get()
            and ob.name in bpy.context.view_layer.objects
        ]
        for i, trail in enumerate(trail_matches):
            if i == 0 and duplicate is not None:
                dup = duplicate
            else:
                dup = zobj.copy()
                dup.data = zobj.data.copy()
                bpy.context.collection.objects.link(dup)
                for col in zobj.users_collection:
                    if dup.name not in col.objects:
                        col.objects.link(dup)

            bpy.ops.object.select_all(action="DESELECT")
            dup.select_set(True)
            zobj.select_set(False)
            bpy.context.view_layer.objects.active = dup
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.extrude_region_move()
            bpy.ops.transform.translate(value=(0, 0, 1))
            bpy.ops.object.mode_set(mode="OBJECT")
            dup.name = f"{zobj.name}_TRAIL_{i}"
            dup_name = dup.name
            intersect_trail_with_existing_box(dup, trail)
            if dup_name in bpy.data.objects:
                curveObjs.append(bpy.data.objects[dup_name])

    return curveObjs


def createTerrainFromSelected(manage_overlay=True, skip_bottom_recess=False):
    """Apply terrain elevation and overlays to already-placed tile objects.

    manage_overlay: when False the caller owns the ProgressOverlay lifecycle
    (start/finish).  All internal update/step calls still run normally so the
    caller's overlay reflects terrain progress.

    skip_bottom_recess: forwarded to _ctfs_apply_elevation -- see its
    docstring. Pass True for fresh single-tile callers with no neighbor
    baseline to protect (e.g. the puzzle generator).
    """
    from ..mesh_ops import (
        recalculateNormals,  # deferred to avoid circular import at load time
    )
    from ..metadata import (
        writeMetadata,  # deferred to avoid circular import at load time
    )
    from ..primitives import (
        setupColors,  # deferred to avoid circular import at load time
    )

    props = _ctfs_load_props()
    start_time = time.time()

    overlay = _progress.ProgressOverlay.get()
    if manage_overlay:
        overlay.start()
        _progress.WarningsOverlay.clear()

    print("------------------------------------------------")
    print("SCRIPT STARTED - createTerrainFromSelected")
    print("------------------------------------------------")

    if (
        props["selfHosted"] != ""
        and props["selfHosted"] is not None
        and props["api"] == 1
    ):
        print(f"!!using {props['selfHosted']} instead of Opentopodata!!")

    setupColors()

    overlay.update(0.02, "Initializing", "Validating selection…")

    selected_objects = bpy.context.selected_objects
    if not selected_objects:
        from ..scene import (
            show_message_box,  # deferred to avoid circular import at load time
        )

        show_message_box("No objects selected")
        if manage_overlay:
            overlay.finish()
        return {"FINISHED"}

    bpy.ops.object.select_all(action="DESELECT")

    lowestZ = 0
    highestZ = 0
    additionalExtrusion = props["additionalExtrusion"]

    _map_km = round(bpy.context.scene.tp3d.get("sMapInKm", 0), 1)
    _fetch_items = build_fetch_items(_map_km)
    overlay.set_fetch_items(_fetch_items)

    # Build multi-tile map preview (only when 2+ valid tiles)
    # Mirror the loop's own skip conditions exactly:
    #   - must be MESH
    #   - objType absent OR == "MAP"  (objects without objType are valid map tiles)
    #   - not already processed (highestZ and lowestZ both non-zero)
    _mp_valid = [
        obj
        for obj in selected_objects
        if obj.type == "MESH"
        and obj.get("objType", "MAP") == "MAP"
        and not (obj.get("highestZ", 0) != 0 and obj.get("lowestZ", 0) != 0)
    ]
    _mp_tiles_info = []
    _mp_tile_size = float(_mp_valid[0].get("objSize", 1.0)) if _mp_valid else 1.0
    if len(_mp_valid) >= 2:
        for obj in _mp_valid:
            _mp_tiles_info.append(
                {
                    "bx": round(float(obj.location.x), 3),
                    "by": round(float(obj.location.y), 3),
                    "status": "pending",
                    "shape": obj.get("Shape", "square").lower().split()[0],
                }
            )
        overlay.set_map_preview(
            {"tiles": _mp_tiles_info, "tile_size": round(_mp_tile_size, 3)}
        )

    n_tiles = len(selected_objects)
    for tile_idx, zobj in enumerate(selected_objects):
        tile_label = f"Tile {tile_idx + 1}/{n_tiles}"
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.scene.cursor.location = zobj.location

        if zobj.type != "MESH":
            continue
        if "objType" in zobj and zobj["objType"] != "MAP":
            continue
        if (
            "highestZ" in zobj
            and "lowestZ" in zobj
            and zobj["highestZ"] != 0
            and zobj["lowestZ"] != 0
        ):
            continue

        if _mp_tiles_info and _progress.SubprocessProgress.get().is_cancel_requested():
            break

        base_pct = tile_idx / n_tiles
        step = 1.0 / n_tiles

        # Update tile statuses in map preview
        if _mp_tiles_info and zobj in _mp_valid:
            _mp_idx = _mp_valid.index(zobj)
            for k in range(_mp_idx):
                _mp_tiles_info[k]["status"] = "done"
            _mp_tiles_info[_mp_idx]["status"] = "active"
            overlay.set_map_preview(
                {"tiles": _mp_tiles_info, "tile_size": round(_mp_tile_size, 3)}
            )

        # Reset chip strip for this tile
        overlay.set_fetch_items(build_fetch_items(_map_km))

        # Create flat duplicate for trail boolean (normal mode only)
        duplicate = None
        if not props["singleColorMode"]:
            pass
            # COMMENTED OUT FOR NOW, NOT SURE IF NEEDED CURRENTLY (MAYBE FOR SINGLE COLOR MODE)
            # duplicate = zobj.copy()
            # duplicate.data = zobj.data.copy()
            # bpy.context.collection.objects.link(duplicate)
            # for col in zobj.users_collection:
            #    if duplicate.name not in col.objects:
            #        col.objects.link(duplicate)
            # duplicate.name = "Bool"
            # duplicate.select_set(False)

        # Apply terrain elevation + extrude bottom face (0% → 50% of this tile)
        overlay.update(
            base_pct + step * 0.00,
            "Fetching Elevation",
            f"{tile_label} — querying elevation API…",
        )
        overlay.set_fetch_progress("elevation", 0.0)

        def _elev_progress(pct, _base_pct=base_pct, _step=step, _tile_label=tile_label):
            t = pct / 100.0
            overlay.update(
                _base_pct + _step * t * 0.50,
                "Fetching Elevation",
                f"{_tile_label} — {pct}% complete…",
                sub_percent=t,
                sub_label="Elevation tiles",
            )
            overlay.set_fetch_progress("elevation", t)

        props["additionalExtrusion"] = additionalExtrusion
        lowestZ, highestZ, additionalExtrusion, n_elev_pts = _ctfs_apply_elevation(
            zobj,
            props,
            progress_cb=_elev_progress,
            skip_bottom_recess=skip_bottom_recess,
        )
        props["additionalExtrusion"] = additionalExtrusion
        overlay.sub_percent = None
        overlay.set_fetch_done("elevation", success=True)
        overlay.update(
            base_pct + step * 0.50,
            "Elevation Ready",
            f"{tile_label} — {n_elev_pts} pts, z {lowestZ:.1f}–{highestZ:.1f}",
        )
        overlay.add_completed_step(
            f"{tile_label} — elevation fetched ({n_elev_pts} pts, z {lowestZ:.1f}–{highestZ:.1f})"
        )

        # Handle trail projection / intersection
        overlay.update(
            base_pct + step * 0.60,
            "Building Trail",
            f"{tile_label} — projecting trail onto terrain…",
        )
        print(f"duplicate: {duplicate}")
        curveObjs = _ctfs_handle_trail(zobj, duplicate, props["singleColorMode"])
        _n_trails = len(curveObjs)
        print(f"_n_trails: {_n_trails}")
        overlay.add_completed_step(
            f"{tile_label} — trail built ({_n_trails} seg{'s' if _n_trails != 1 else ''})"
            if _n_trails
            else f"{tile_label} — no trail"
        )

        # Base material
        mat = bpy.data.materials.get("BASE")
        zobj.data.materials.clear()
        zobj.data.materials.append(mat)

        # Terrain overlay elements (water, forest, city, glacier, buildings, roads)
        _elem_start = base_pct + step * 0.70
        _elem_end = base_pct + step * 0.93
        overlay.update(
            _elem_start, "Terrain Elements", f"{tile_label} — building overlay layers…"
        )
        terrain = _rg_build_terrain_elements(
            zobj,
            props["scaleHor"],
            phase_start=_elem_start,
            phase_end=_elem_end,
            tile_label=tile_label,
        )
        if terrain["roads"]:
            terrain["roads"].location.z += 0.4
        _found = [k for k, v in terrain.items() if v is not None]
        overlay.add_completed_step(
            f"{tile_label} — elements: {', '.join(_found)}"
            if _found
            else f"{tile_label} — no elements"
        )

        recalculateNormals(zobj)

        # Single color mode processing
        overlay.update(
            base_pct + step * 0.85,
            "Coloring",
            f"{tile_label} — applying single-color mode…",
        )
        print(f"curveObjs: {curveObjs} ")
        _rg_apply_single_color_mode(zobj, curveObjs, terrain, props)

        # Create a texture: rasterise OSM polygons into a UV paint texture.
        # _rg_build_terrain_elements already populated terrain['_osm_polygons']
        # and discarded the road mesh; we just need to bake the texture here.
        if props["elementMode"] == "CREATE_TEXTURE":
            from ..texture import setup_paint_texture

            overlay.update(
                base_pct + step * 0.89,
                "Texture",
                f"{tile_label} — rasterising OSM texture…",
            )
            setup_paint_texture(zobj, terrain.get("_osm_polygons", {}))
            # Trail curves are encoded in the texture; 3D objects not needed.
            if curveObjs and not props["singleColorMode"]:
                for _tcrv in list(curveObjs):
                    if _tcrv and _tcrv.name in bpy.data.objects:
                        bpy.data.objects.remove(_tcrv, do_unlink=True)
                curveObjs.clear()

        # Finalize tile
        overlay.update(
            base_pct + step * 0.93, "Finalizing", f"{tile_label} — writing metadata…"
        )
        writeMetadata(zobj)
        bpy.ops.object.select_all(action="DESELECT")
        zobj.select_set(False)
        zobj["lowestZ"] += additionalExtrusion
        zobj["highestZ"] += additionalExtrusion

        _rg_assign_materials(zobj, curveObjs, None, None, props)

    # Mark all tiles done in the preview
    if _mp_tiles_info:
        for _info in _mp_tiles_info:
            _info["status"] = "done"
        overlay.set_map_preview(
            {"tiles": _mp_tiles_info, "tile_size": round(_mp_tile_size, 3)}
        )

    bpy.context.view_layer.objects.active = selected_objects[0]
    for zobj in selected_objects:
        zobj.select_set(True)

    end_time = time.time()
    duration = end_time - start_time

    bpy.context.scene.tp3d.lowestZ = lowestZ
    bpy.context.scene.tp3d.highestZ = highestZ
    bpy.context.scene.tp3d["o_time"] = f"Script ran for {duration:.0f} seconds"

    from ..elevation import load_generation_counter, save_generation_counter

    _total_maps = load_generation_counter() + 1
    save_generation_counter(_total_maps)
    bpy.context.scene.tp3d["o_mapsGenerated"] = f"Maps Generated: {_total_maps}"

    _elapsed = int(time.time() - overlay._start_time) if overlay._start_time else 0
    _m, _s = divmod(_elapsed, 60)
    overlay.add_completed_step(f"Done  —  {_m:02d}:{_s:02d} total")
    _progress.WarningsOverlay.add_warning(
        "Multi-tile maps are not exported automatically — please use the Export buttons to export your tiles manually.",
        "warn",
    )
    if manage_overlay:
        overlay.finish()
        _progress.WarningsOverlay.get().show()


def generateJustTrail(material="TRAIL"):
    from ..geo import (  # deferred to avoid circular import at load time
        convert_to_blender_coordinates,
        separate_duplicate_xy,
    )
    from ..io_gpx import read_gpx_file  # deferred to avoid circular import at load time
    from ..mesh_ops import (
        RaycastCurveToAnyMesh,  # deferred to avoid circular import at load time
    )
    from ..primitives import (  # deferred to avoid circular import at load time
        create_curve_from_coordinates,
        simplify_curve,
    )
    from ..scene import (
        show_message_box,  # deferred to avoid circular import at load time
    )

    props = bpy.context.scene.tp3d

    minThickness = props.minThickness
    additionalExtrusion = props.sAdditionalExtrusion

    overwritePathElevation = props.overwritePathElevation

    coordinates = []
    separate_paths = []
    blender_coords = []
    blender_coords_separate = []
    type = 0

    bpy.ops.object.select_all(action="DESELECT")

    try:
        separate_paths = read_gpx_file()
    except Exception:  # noqa: BLE001 — GPX/IGC parsing can raise many unpredictable types
        show_message_box(f"Something went Wrong reading the GPX. Type {type}")
    coordinates = [item for sublist in separate_paths for item in sublist]

    # RECALCULATE THE COORDS WITH AUTOSCALE APPLIED
    blender_coords = [
        convert_to_blender_coordinates(lat, lon, ele, timestamp)
        for lat, lon, ele, timestamp in coordinates
    ]

    if type == 1 or len(separate_paths) > 1:
        blender_coords_separate = [
            separate_duplicate_xy(
                [
                    convert_to_blender_coordinates(lat, lon, ele, timestamp)
                    for lat, lon, ele, timestamp in path
                ],
                0.05,
            )
            for path in separate_paths
        ]

    blender_coords = simplify_curve(blender_coords, 0.12)

    # PREVENT CLIPPING OF IDENTICAL COORDINATES
    blender_coords = separate_duplicate_xy(blender_coords, 0.05)

    if separate_paths is None:
        return
    print(len(separate_paths))

    if (type == 1 or len(separate_paths) > 1) and type != 4:
        blender_coords_separate = [
            separate_duplicate_xy(
                [
                    convert_to_blender_coordinates(lat, lon, ele, timestamp)
                    for lat, lon, ele, timestamp in path
                ],
                0.05,
            )
            for path in separate_paths
        ]

    curveObj = None
    try:
        if (type == 0 and len(blender_coords_separate) <= 1) and type != 2 or type == 4:
            if not blender_coords:
                return None
            create_curve_from_coordinates(blender_coords)
            curveObj = bpy.context.view_layer.objects.active
        elif (type == 1 or len(blender_coords_separate) > 1) and type != 4:
            for crds in blender_coords_separate:
                create_curve_from_coordinates(crds)

                bpy.ops.object.join()
                curveObj = bpy.context.view_layer.objects.active
    except RuntimeError as e:
        show_message_box(e)

    if curveObj:
        bpy.context.view_layer.objects.active = curveObj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.curve.select_all(action="SELECT")
        bpy.ops.transform.translate(
            value=(0, 0, -additionalExtrusion + minThickness)
        )  # bpy.ops.mesh.select_all(action='DESELECT')
        bpy.ops.object.mode_set(mode="OBJECT")

    # sets 3D cursor to origin of tile
    if curveObj:
        curveObj.select_set(True)
        bpy.ops.object.origin_set(type="ORIGIN_CURSOR")

    # Raycast the curve points onto the Mesh surface
    if overwritePathElevation == True:
        # pass
        RaycastCurveToAnyMesh(curveObj, 1000, True)

    if curveObj:
        mat = bpy.data.materials.get(material)
        curveObj.data.materials.clear()
        curveObj.data.materials.append(mat)

    return curveObj
