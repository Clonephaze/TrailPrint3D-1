import math
import time
from dataclasses import dataclass, field

import bmesh  # type: ignore
import bpy  # type: ignore
import numpy as np  # type: ignore
from mathutils import Vector  # type: ignore

from ...progress import progress as _progress
from ..geometry2d import geometry2d as g2d
from ..mesh_ops import applyModifier, boolean_operation, is_mesh_manifold
from .fetch_solo import fetch_tier_polylines

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

TIER_TAGS: dict[str, set[str]] = {
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

ALLEY_SERVICE_TYPES: frozenset[str] = frozenset(
    {"alley", "driveway", "parking_aisle", "drive-through"}
)

_ROAD_SIMPLIFY_TOL = 0.5


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------


@dataclass
class RoadConfig:
    min_lat: float
    min_lon: float
    max_lat: float
    max_lon: float
    street_width_multiplier: float
    exclude_alleys: bool
    tier_active: dict[str, bool] = field(
        default_factory=lambda: {t: True for t in TIER_TAGS}
    )

    @classmethod
    def from_scene(cls, tp3d, full_depth: bool = False) -> "RoadConfig":
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

        return cls(
            min_lat=tp3d.minLat,
            min_lon=tp3d.minLon,
            max_lat=tp3d.maxLat,
            max_lon=tp3d.maxLon,
            street_width_multiplier=tp3d.el_sMultiplier,
            exclude_alleys=bool(tp3d.el_sExcludeAlleys),
            tier_active=tier_active,
        )


# ---------------------------------------------------------------------------
# Width helpers
# ---------------------------------------------------------------------------


def highway_default_width(highway: str) -> float:
    mapping = {
        "motorway": 6.0,
        "trunk": 6.0,
        "primary": 6.0,
        "secondary": 6.0,
        "footway": 6.0,
        "tertiary": 6.0,
        "residential": 6.0,
        "service": 6.0,
        "track": 6.0,
        "path": 6.0,
    }
    return mapping.get(highway, 6.0)


def _compute_half_width(scale_hor: float, multiplier: float) -> tuple[float, bool]:
    """Return ``(half_width, was_clamped)``.  The caller owns the warning side-effect."""
    width_m = highway_default_width("residential")
    half_width = (width_m * 0.5) * 0.2 * scale_hor * 0.02 * multiplier
    if half_width < 0.2:
        return 0.2, True
    return half_width, False


# ---------------------------------------------------------------------------
# Geometry helper
# ---------------------------------------------------------------------------


def _buffer_tiers_to_polygons(
    tier_polylines: dict[str, list],
    half_width: float,
) -> list[np.ndarray]:
    """Dissolve all tier polylines into a flat list of 2-D exterior-ring arrays."""
    poly_2d: list[np.ndarray] = []
    for polylines in tier_polylines.values():
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
    return poly_2d


# ---------------------------------------------------------------------------
# Mesh construction
# ---------------------------------------------------------------------------


def _build_extruded_mesh(
    poly_2d: list[np.ndarray],
    bottom_z: float,
    top_z: float,
) -> bpy.types.Object:
    """Build a tall extruded slab from a list of 2-D polygons and link it to the scene."""
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

    faces: list = []
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
    mesh.from_pydata(
        all_verts.tolist(), [], [tuple(int(idx) for idx in f) for f in faces]
    )
    mesh.update(calc_edges=True)
    mesh.validate(verbose=False)

    roads = bpy.data.objects.new("Roads", mesh)
    bpy.context.collection.objects.link(roads)
    return roads


# ---------------------------------------------------------------------------
# full_depth finishing pass
# ---------------------------------------------------------------------------


def _apply_full_depth_pass(
    roads: bpy.types.Object,
    bottom_z: float,
    default_height: float,
) -> None:
    """
    Merge a flat strip copy (bottom faces removed, re-extruded) into ``roads``,
    then voxel-remesh and dissolve to fuse everything into a single clean solid.
    Mutates ``roads`` in place.
    """
    strip_mesh = roads.data.copy()
    strip_obj = bpy.data.objects.new("_roads_strip_tmp", strip_mesh)
    bpy.context.collection.objects.link(strip_obj)

    bpy.ops.object.select_all(action="DESELECT")
    strip_obj.select_set(True)
    bpy.context.view_layer.objects.active = strip_obj

    bm_strip = bmesh.new()
    bm_strip.from_mesh(strip_mesh)

    eps = 0.01
    bottom_faces = [
        f for f in bm_strip.faces if all(abs(v.co.z - bottom_z) <= eps for v in f.verts)
    ]
    if bottom_faces:
        bmesh.ops.delete(bm_strip, geom=bottom_faces, context="FACES")

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
        f"[TP3D roads] verts pre-remesh: {verts_pre_remesh}, "
        f"post-remesh: {verts_post_remesh}, "
        f"post-cleanup: {verts_post_cleanup}"
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def create_roads(map, default_height=10, scaleHor=1.0, mapsize=1, full_depth=False):
    _t_setup = time.time()
    _ov = _progress.ProgressOverlay.get()
    if _ov.active:
        _ov.set_fetch_progress("roads", 0.0)

    # --- Config ---------------------------------------------------------
    config = RoadConfig.from_scene(bpy.context.scene.tp3d, full_depth=full_depth)

    # --- Fetch ----------------------------------------------------------
    tier_polylines = fetch_tier_polylines(
        config.min_lat,
        config.min_lon,
        config.max_lat,
        config.max_lon,
        TIER_TAGS,
        config.tier_active,
        config.exclude_alleys,
        ALLEY_SERVICE_TYPES,
        progress_overlay=_ov,
    )
    if tier_polylines is None:
        return None

    if _ov.active:
        _ov.set_fetch_progress("roads", 0.30)
        _ov.update(message="Roads: buffering each tier…")

    # --- Width ----------------------------------------------------------
    half_width, width_was_adjusted = _compute_half_width(
        scaleHor, config.street_width_multiplier
    )

    # --- Z bounds from terrain ------------------------------------------
    mc = [map.matrix_world @ Vector(c) for c in map.bound_box]
    bottom_z = min(v.z for v in mc) - 50.0
    top_z = max(v.z for v in mc) + 50.0

    # --- Buffer ---------------------------------------------------------
    poly_2d = _buffer_tiers_to_polygons(tier_polylines, half_width)
    if not poly_2d:
        print("No road data returned")
        return None

    # --- Mesh -----------------------------------------------------------
    roads = _build_extruded_mesh(poly_2d, bottom_z, top_z)

    if _ov.active:
        _ov.set_fetch_progress("roads", 0.75)
        _ov.update(message="Roads: clipping to terrain…")

    # --- Boolean clip ---------------------------------------------------
    solver = "MANIFOLD" if is_mesh_manifold(roads) else "EXACT"
    boolean_operation(roads, map, "INTERSECT", solver=solver)

    if len(roads.data.vertices) == 0:
        bpy.data.objects.remove(roads, do_unlink=True)
        print("No road data returned")
        return None

    if _ov.active:
        _ov.set_fetch_progress("roads", 0.90)
        _ov.update(message="Roads: raising above terrain…")

    # --- Extrude up (shared by both branches) ---------------------------
    bm = bmesh.new()
    bm.from_mesh(roads.data)
    all_faces = list(bm.faces)
    if all_faces:
        ret = bmesh.ops.extrude_face_region(bm, geom=all_faces)
        new_verts = [v for v in ret["geom"] if isinstance(v, bmesh.types.BMVert)]
        bmesh.ops.translate(bm, verts=new_verts, vec=(0, 0, default_height))
    bm.to_mesh(roads.data)
    bm.free()
    roads.data.update()

    # --- full_depth finishing pass --------------------------------------
    if full_depth:
        _apply_full_depth_pass(roads, bottom_z, default_height)

    # --- Finalise -------------------------------------------------------
    bpy.ops.object.select_all(action="DESELECT")
    roads.select_set(True)
    bpy.context.view_layer.objects.active = roads

    if _ov.active:
        _ov.set_fetch_progress("roads", 1.0)

    if width_was_adjusted:
        _progress.WarningsOverlay.add_warning(
            "Some roads were too thin and made thicker", "warn"
        )

    print(
        f"[TP3D roads] final mesh ({len(roads.data.vertices)} verts) took "
        f"{time.time() - _t_setup:.1f}s total"
    )
    return roads
