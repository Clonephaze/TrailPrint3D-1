import math
import time

import bmesh  # type: ignore
import bpy  # type: ignore
import numpy as np  # type: ignore
from mathutils import Vector  # type: ignore

from ...progress import progress as _progress
from ..geo import convert_to_blender_coordinates_batch
from ..geometry2d import geometry2d as g2d
from ..mesh_ops import (
    applyModifier,
    boolean_operation,
    is_mesh_manifold,
)
from .fetch_utils import fetch_osm_data


def highway_default_width(highway):
    mapping = {
        "motorway": 6.0,
        "trunk": 6.0,
        "primary": 6.0,
        "secondary": 6.0,
        "footway": 6,
        "tertiary": 6.0,
        "residential": 6.0,
        "service": 6.0,
        "track": 6.0,
        "path": 6,
    }
    return mapping.get(highway, 6.0)


def create_roads(map, default_height=10, scaleHor=1.0, mapsize=1, full_depth=False):

    _t_setup = time.time()
    _ov = _progress.ProgressOverlay.get()
    if _ov.active:
        _ov.set_fetch_progress("roads", 0.0)

    tp3d = bpy.context.scene.tp3d
    TIER_TAGS = {
        "big": {"motorway", "primary", "motorway_link", "primary_link"},
        "medium": {
            "secondary",
            "tertiary",
            "secondary_link",
            "tertiary_link",
            "unclassified",
            "trunk",
            "trunk_link",
        },
        "small": {"residential", "living_street"},
        "service": {"service"},
        "footway": {"footway"},
    }
    tier_active = {
        "big": bool(tp3d.el_sBigActive),
        "medium": bool(tp3d.el_sMedActive),
        "small": bool(tp3d.el_sSmallActive),
        "service": bool(tp3d.el_sServiceActive),
        "footway": bool(tp3d.el_sFootwaysActive),
    }
    if full_depth:
        if tier_active["service"] or tier_active["footway"]:
            print(
                "[TP3D roads] full_depth mode: excluding service/footway tiers "
                "(too dense to remesh cleanly as a standalone piece)"
            )
        tier_active["service"] = False
        tier_active["footway"] = False
    exclude_alleys = bool(tp3d.el_sExcludeAlleys)
    ALLEY_SERVICE_TYPES = {"alley", "driveway", "parking_aisle", "drive-through"}

    minLat = tp3d.minLat
    minLon = tp3d.minLon
    maxLat = tp3d.maxLat
    maxLon = tp3d.maxLon
    streetwidthMultiplier = tp3d.el_sMultiplier

    lat_step = 2
    lon_step = 2
    lat_step = min(lat_step, maxLat - minLat)
    lon_step = min(lon_step, maxLon - minLon)
    lats = math.ceil((maxLat - minLat) / lat_step)
    lons = math.ceil((maxLon - minLon) / lon_step)

    tier_polylines = {tier: [] for tier in TIER_TAGS}

    # --- Tile fetching ------------------------------------------
    if lats * lons < 20:
        for k in range(lats):
            for l in range(lons):
                _cntr = k * lons + l + 1
                _maxcntr = lats * lons
                print(f"Roads loop: {_cntr}/{_maxcntr}")
                if _ov.active:
                    _ov.update(message=f"Roads: tile {_cntr}/{_maxcntr} — fetching…")

                south = minLat + k * lat_step
                north = south + lat_step
                west = minLon + l * lon_step
                east = west + lon_step
                bbox = (south, west, north, east)

                data = fetch_osm_data(bbox, "STREETS")
                if not data or "elements" not in data:
                    print("No Road data returned")
                    return None

                assert isinstance(data, dict)
                n_roads = len([e for e in data["elements"] if e["type"] == "way"])
                if _ov.active:
                    _ov.update(
                        message=f"Roads: tile {_cntr}/{_maxcntr} — bucketing {n_roads} ways…"
                    )

                nodes = {
                    el["id"]: (el["lat"], el["lon"], 0.0, None)
                    for el in data["elements"]
                    if el["type"] == "node"
                }
                node_ids = list(nodes.keys())
                coord_cache = {}
                if node_ids:
                    xyz = convert_to_blender_coordinates_batch(
                        [nodes[nid] for nid in node_ids]
                    )
                    coord_cache = {
                        nid: (x, y) for nid, (x, y, _z) in zip(node_ids, xyz)
                    }

                for el in data["elements"]:
                    if el["type"] != "way":
                        continue
                    tags = el.get("tags", {}) or {}
                    highway = tags.get("highway", "")
                    if (
                        highway == "service"
                        and exclude_alleys
                        and tags.get("service") in ALLEY_SERVICE_TYPES
                    ):
                        continue
                    tier = next(
                        (t for t, tagset in TIER_TAGS.items() if highway in tagset),
                        None,
                    )
                    if tier is None or not tier_active[tier]:
                        continue
                    pts = [
                        coord_cache[nid]
                        for nid in el.get("nodes", [])
                        if nid in coord_cache
                    ]
                    if len(pts) >= 2:
                        tier_polylines[tier].append(pts)

    if _ov.active:
        _ov.set_fetch_progress("roads", 0.30)
        _ov.update(message="Roads: buffering each tier…")

    width_m = highway_default_width("residential")
    half_width = (width_m * 0.5) * 0.2 * scaleHor * 0.02 * streetwidthMultiplier
    any_adjusted = False
    if half_width < 0.2:
        half_width = 0.2
        any_adjusted = True

    # Same as original - create tall extrusion to ensure it fully intersects terrain
    mc = [map.matrix_world @ Vector(c) for c in map.bound_box]
    bottom_z = min(v.z for v in mc) - 50.0
    top_z = max(v.z for v in mc) + 50.0

    # --- Buffer polylines, collect 2D polygons --------------------------------
    _ROAD_SIMPLIFY_TOL = 0.5
    poly_2d = []
    for tier, polylines in tier_polylines.items():
        if not polylines:
            continue
        buffered = g2d.polylines_to_ribbon(
            polylines, half_width, quad_segs=2, simplify_tol=_ROAD_SIMPLIFY_TOL
        )
        if buffered is None or buffered.is_empty:
            continue
        if not buffered.is_valid:
            buffered = g2d.validate(buffered)
            if buffered is None or buffered.is_empty:
                continue
        for part in g2d.iter_polygons(buffered):
            exterior_coords = list(part.exterior.coords)[:-1]
            if len(exterior_coords) < 3:
                continue
            poly_2d.append(np.array(exterior_coords, dtype=np.float32))

    if not poly_2d:
        print("No road data returned")
        return None

    # --- Build extruded mesh with NumPy (same as original working version) ----
    vert_counts = [p.shape[0] for p in poly_2d]
    total_verts = sum(vert_counts)
    offsets = np.cumsum([0] + vert_counts[:-1])

    bottom_verts = np.zeros((total_verts, 3), dtype=np.float32)
    top_verts = np.zeros((total_verts, 3), dtype=np.float32)

    for i, poly in enumerate(poly_2d):
        n = vert_counts[i]
        o = offsets[i]
        bottom_verts[o : o + n, :2] = poly
        bottom_verts[o : o + n, 2] = bottom_z
        top_verts[o : o + n, :2] = poly
        top_verts[o : o + n, 2] = top_z

    faces = []
    for o, n in zip(offsets, vert_counts):
        faces.append(np.arange(o, o + n)[::-1])
    for o, n in zip(offsets, vert_counts):
        faces.append(np.arange(o, o + n) + total_verts)
    for o, n in zip(offsets, vert_counts):
        idx_bottom = np.arange(o, o + n)
        idx_top = idx_bottom + total_verts
        for i in range(n):
            j = (i + 1) % n
            faces.append([idx_bottom[i], idx_bottom[j], idx_top[j], idx_top[i]])

    all_verts = np.vstack([bottom_verts, top_verts])

    mesh = bpy.data.meshes.new("road_mesh")
    face_tuples = [tuple(int(idx) for idx in f) for f in faces]
    mesh.from_pydata(all_verts.tolist(), [], face_tuples)
    mesh.update(calc_edges=True)
    mesh.validate(verbose=False)

    roads = bpy.data.objects.new("Roads", mesh)
    bpy.context.collection.objects.link(roads)

    if _ov.active:
        _ov.set_fetch_progress("roads", 0.75)
        _ov.update(message="Roads: clipping to terrain…")

    # Boolean intersection - same as original
    solver = "MANIFOLD" if is_mesh_manifold(roads) else "EXACT"
    boolean_operation(roads, map, "INTERSECT", solver=solver)

    if len(roads.data.vertices) == 0:
        bpy.data.objects.remove(roads, do_unlink=True)
        print("No road data returned")
        return None

    if _ov.active:
        _ov.set_fetch_progress("roads", 0.90)
        _ov.update(message="Roads: raising above terrain…")

    # Now just extrude EVERYTHING up - no bottom face detection needed
    bm = bmesh.new()
    bm.from_mesh(roads.data)

    # Get all faces and extrude them up
    all_faces = list(bm.faces)
    if all_faces:
        ret = bmesh.ops.extrude_face_region(bm, geom=all_faces)
        new_verts = [v for v in ret["geom"] if isinstance(v, bmesh.types.BMVert)]
        bmesh.ops.translate(bm, verts=new_verts, vec=(0, 0, default_height))

    if full_depth:
        # Keep the full_depth logic using operators as in original
        bm.to_mesh(roads.data)
        bm.free()
        roads.data.update()

        # Use original approach for full_depth since it works
        strip_mesh = roads.data.copy()
        strip_obj = bpy.data.objects.new("_roads_strip_tmp", strip_mesh)
        bpy.context.collection.objects.link(strip_obj)

        bpy.ops.object.select_all(action="DESELECT")
        strip_obj.select_set(True)
        bpy.context.view_layer.objects.active = strip_obj

        # Find and delete bottom faces using BMesh
        bm_strip = bmesh.new()
        bm_strip.from_mesh(strip_mesh)

        # After boolean with terrain, bottom faces will be at bottom_z
        eps = 0.01
        bottom_faces = [
            f
            for f in bm_strip.faces
            if all(abs(v.co.z - bottom_z) <= eps for v in f.verts)
        ]

        if bottom_faces:
            bmesh.ops.delete(bm_strip, geom=bottom_faces, context="FACES")

        # Extrude remaining faces up
        remaining_faces = list(bm_strip.faces)
        if remaining_faces:
            ret = bmesh.ops.extrude_face_region(bm_strip, geom=remaining_faces)
            new_verts = [v for v in ret["geom"] if isinstance(v, bmesh.types.BMVert)]
            bmesh.ops.translate(bm_strip, verts=new_verts, vec=(0, 0, default_height))

        bm_strip.to_mesh(strip_mesh)
        bm_strip.free()
        strip_mesh.update()

        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.ops.object.select_all(action="DESELECT")
        strip_obj.select_set(True)
        roads.select_set(True)
        bpy.context.view_layer.objects.active = roads
        bpy.ops.object.join()

        verts_pre_remesh = len(roads.data.vertices)
        remesh_mod = roads.modifiers.new(name="RoadsFuse", type="REMESH")
        remesh_mod.mode = "VOXEL"
        remesh_mod.voxel_size = 0.1
        remesh_mod.use_smooth_shade = False
        applyModifier(roads, remesh_mod)
        verts_post_remesh = len(roads.data.vertices)

        bm2 = bmesh.new()
        bm2.from_mesh(roads.data)
        bmesh.ops.remove_doubles(bm2, verts=bm2.verts, dist=0.001)
        bmesh.ops.dissolve_limit(
            bm2, angle_limit=math.radians(0.5), verts=bm2.verts, edges=bm2.edges
        )
        bm2.to_mesh(roads.data)
        bm2.free()
        verts_post_cleanup = len(roads.data.vertices)
        roads.data.update()
        print(
            f"[TP3D roads] verts pre-remesh: {verts_pre_remesh}, post-remesh: {verts_post_remesh}, post-cleanup: {verts_post_cleanup}"
        )

    else:
        bm.to_mesh(roads.data)
        bm.free()
        roads.data.update()

    bpy.ops.object.select_all(action="DESELECT")
    roads.select_set(True)
    bpy.context.view_layer.objects.active = roads

    if _ov.active:
        _ov.set_fetch_progress("roads", 1.0)

    if any_adjusted:
        _progress.WarningsOverlay.add_warning(
            "Some roads were too thin and made thicker", "warn"
        )

    print(
        f"[TP3D roads] final mesh ({len(roads.data.vertices)} verts) took "
        f"{time.time() - _t_setup:.1f}s total"
    )
    return roads
