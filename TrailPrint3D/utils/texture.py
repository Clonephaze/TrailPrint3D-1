"""
OSM element texture rasterization for CREATE_TEXTURE element mode.

Rasterizes Shapely polygons (OSM element areas) into a Blender Image,
sets up planar UV coordinates on the terrain mesh, creates a single
material referencing the image, and assigns the three mesh custom
properties expected by the 3MF addon's paint-segmentation export pipeline.

Coordinate conventions
----------------------
- Shapely polygon coordinates are in *world space* (Web Mercator, scaled by
  R * scaleHor).  The terrain object's vertex coords are in *local space*
  (world coords minus cursor location).
- UV (u, v) maps local X → u, local Y → v, both in [0, 1].
- The Blender image stores pixels row-0 = bottom (v = 0), matching Blender's
  UV convention and the layout expected by the 3MF addon's segmentation reader.
"""

import bpy
import numpy as np

# ── Palette definition ────────────────────────────────────────────────────────
# Each colour is expressed as sRGB uint8 (R, G, B).  These values are used
# for *both* the image pixels and the hex strings in 3mf_paint_extruder_colors,
# guaranteeing exact nearest-colour matching (Manhattan distance = 0) during
# the 3MF addon's segmentation export.

_BASE_SRGB   = (13,  179,  13)   # terrain background (BASE material)
_WATER_SRGB  = (0,    0,  200)
_FOREST_SRGB = (5,   64,    5)
_SCREE_SRGB  = (150, 150, 150)   # SCREE uses MOUNTAIN material
_CITY_SRGB   = (180, 180,  30)
_GS_SRGB     = (40,  255,  40)   # GREENSPACE
_FARM_SRGB   = (80,  130,  30)
_GLAC_SRGB   = (205, 220, 205)
_ROADS_SRGB  = (0,    0,   0)    # BLACK
_TRAIL_SRGB  = (255,  0,   0)    # TRAIL
_WHITE_SRGB  = (255, 255, 255)   # companion text objects

# OSM kind string (uppercase) → sRGB byte tuple.
# OCEAN shares WATER's slot; duplicates are merged in _build_palette().
_KIND_TO_SRGB = {
    "WATER":      _WATER_SRGB,
    "OCEAN":      _WATER_SRGB,
    "FOREST":     _FOREST_SRGB,
    "SCREE":      _SCREE_SRGB,
    "CITY":       _CITY_SRGB,
    "GREENSPACE": _GS_SRGB,
    "FARMLAND":   _FARM_SRGB,
    "GLACIER":    _GLAC_SRGB,
    "ROADS":      _ROADS_SRGB,
    "TRAIL":      _TRAIL_SRGB,
}

# Rasterization order: low-priority kinds first so high-priority kinds
# overwrite them in overlap areas.  Mirrors the inverse of
# TERRAIN_PRIORITY_ORDER in generation.py.
_RASTER_ORDER = [
    "GLACIER", "FARMLAND", "GREENSPACE", "SCREE", "CITY",
    "FOREST", "OCEAN", "WATER", "ROADS", "TRAIL",
]

UV_LAYER_NAME = "MMU_Paint"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _srgb_to_hex(r8, g8, b8):
    return f"#{int(r8):02X}{int(g8):02X}{int(b8):02X}"


def _build_palette(present_kinds):
    """Return (palette_dict, kind_to_index) for the kinds actually present.

    palette_dict: {0: "#RRGGBB", ...} where index 0 is the terrain background.
    kind_to_index: {KIND_STR_UPPER: int_palette_index}
    """
    palette = {0: _srgb_to_hex(*_BASE_SRGB)}
    kind_to_index = {}
    idx = 1
    water_idx = None
    for kind in _RASTER_ORDER:
        if kind not in present_kinds:
            continue
        if kind == "OCEAN" and water_idx is not None:
            kind_to_index["OCEAN"] = water_idx
            continue
        srgb = _KIND_TO_SRGB[kind]
        palette[idx] = _srgb_to_hex(*srgb)
        kind_to_index[kind] = idx
        if kind == "WATER":
            water_idx = idx
        idx += 1
    return palette, kind_to_index


def _compute_local_bbox(terrain_obj):
    """Return (min_x, min_y, width, height) in the object's local space."""
    verts = terrain_obj.data.vertices
    co = np.empty(len(verts) * 3, dtype=np.float32)
    verts.foreach_get("co", co)
    co = co.reshape(-1, 3)
    min_x = float(co[:, 0].min())
    max_x = float(co[:, 0].max())
    min_y = float(co[:, 1].min())
    max_y = float(co[:, 1].max())
    return min_x, min_y, max_x - min_x, max_y - min_y


def _rasterize_polygon_even_odd(rings_px, arr, color_float, resolution):
    """Paint a polygon using the even-odd fill rule across all rings combined.

    rings_px : list of (xs, ys) float32 arrays — exterior first, then interiors.
    Pixels inside an odd number of ring boundaries are painted; hole pixels
    (inside an even number) are left untouched, preserving earlier layers.
    """
    all_y = np.concatenate([py for _, py in rings_px])
    row_min = max(0, int(np.floor(all_y.min())))
    row_max = min(resolution - 1, int(np.ceil(all_y.max())))

    edges = []
    for xs, ys in rings_px:
        if len(xs) < 3:
            continue
        edges.append((xs[:-1], ys[:-1], xs[1:], ys[1:]))

    if not edges:
        return

    for row in range(row_min, row_max + 1):
        y = row + 0.5
        xi_parts = []
        for x0, y0, x1, y1 in edges:
            cross = ((y0 < y) & (y <= y1)) | ((y1 < y) & (y <= y0))
            if not cross.any():
                continue
            dy = y1[cross] - y0[cross]
            t = (y - y0[cross]) / dy
            xi_parts.append(x0[cross] + t * (x1[cross] - x0[cross]))
        if not xi_parts:
            continue
        xi_sorted = np.sort(np.concatenate(xi_parts))
        for k in range(0, len(xi_sorted) - 1, 2):
            col_s = max(0, int(np.ceil(xi_sorted[k])))
            col_e = min(resolution, int(np.floor(xi_sorted[k + 1])) + 1)
            if col_s < col_e:
                arr[row, col_s:col_e] = color_float


def _rasterize_geometry(geom, arr, color_float, bg_float,
                        cursor_x, cursor_y, min_x, min_y, width, height, resolution):
    """Rasterize a Shapely Polygon or MultiPolygon into arr."""
    if geom is None or geom.is_empty:
        return

    try:
        from shapely.geometry import Polygon, MultiPolygon, GeometryCollection
    except ImportError:
        print("[TP3D texture] Shapely not available — skipping rasterization")
        return

    if isinstance(geom, (MultiPolygon, GeometryCollection)):
        polys = list(geom.geoms)
    else:
        polys = [geom]

    def _to_px(ring):
        """Convert a Shapely ring's world-space coords to pixel floats."""
        coords = np.array(list(ring.coords), dtype=np.float64)
        px = (coords[:, 0] - cursor_x - min_x) / width  * resolution
        py = (coords[:, 1] - cursor_y - min_y) / height * resolution
        return px.astype(np.float32), py.astype(np.float32)

    for poly in polys:
        if not hasattr(poly, 'exterior') or poly.is_empty:
            continue
        # Combine exterior + all interior rings so the even-odd rule
        # naturally skips holes without overwriting earlier-painted layers.
        rings_px = [_to_px(poly.exterior)]
        for interior in poly.interiors:
            rings_px.append(_to_px(interior))
        _rasterize_polygon_even_odd(rings_px, arr, color_float, resolution)


# ── Public entry point ────────────────────────────────────────────────────────

def setup_paint_texture(terrain_obj, polygons_by_kind, resolution=2048):
    """Rasterize OSM polygons into a texture and configure terrain_obj for 3MF paint export.

    Parameters
    ----------
    terrain_obj      : bpy.types.Object — the terrain mesh object
    polygons_by_kind : dict[str, shapely_geometry] — {KIND_UPPER: Shapely polygon}
                       Coordinates are in world space (Web Mercator, same system
                       used by convert_to_blender_coordinates).
    resolution       : int — image width and height in pixels (default 2048)

    Side effects
    ------------
    - Creates / replaces UV layer "MMU_Paint" on terrain_obj.data
    - Creates / replaces Blender Image "{mesh.name}_MMU_Paint"
    - Creates / replaces material "{mesh.name}_MMU_Paint" with a TEX_IMAGE node
    - Sets mesh custom properties: 3mf_is_paint_texture, 3mf_paint_default_extruder,
      3mf_paint_extruder_colors — triggering the 3MF addon's paint-segmentation
      export when use_orca_format="AUTO" or "PAINT".
    """
    mesh = terrain_obj.data
    cursor = bpy.context.scene.cursor.location
    cursor_x = float(cursor.x)
    cursor_y = float(cursor.y)

    min_x, min_y, width, height = _compute_local_bbox(terrain_obj)
    if width <= 0 or height <= 0:
        print("[TP3D texture] degenerate terrain bbox — skipping texture setup")
        return

    present_kinds = {k.upper() for k, v in polygons_by_kind.items() if v is not None}
    palette, _kind_to_index = _build_palette(present_kinds)

    # Always add WHITE and BLACK so companion text/plate objects have exact
    # palette matches regardless of which OSM element kinds are present.
    for _csrgb in (_WHITE_SRGB, _ROADS_SRGB):
        _chex = _srgb_to_hex(*_csrgb)
        if _chex not in palette.values():
            palette[max(palette.keys()) + 1] = _chex

    # ── UV layer ──────────────────────────────────────────────────────────────
    if UV_LAYER_NAME in mesh.uv_layers:
        mesh.uv_layers.remove(mesh.uv_layers[UV_LAYER_NAME])
    uv_layer = mesh.uv_layers.new(name=UV_LAYER_NAME)
    mesh.uv_layers.active = uv_layer

    # Vectorised planar projection: local X → U, local Y → V
    co_flat = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co_flat)
    co = co_flat.reshape(-1, 3)

    v_idx = np.empty(len(mesh.loops), dtype=np.int32)
    mesh.loops.foreach_get("vertex_index", v_idx)

    uv_u = np.clip((co[v_idx, 0] - min_x) / width,  0.0, 1.0)
    uv_v = np.clip((co[v_idx, 1] - min_y) / height, 0.0, 1.0)

    # Pin side/bottom face loops to the base-colour anchor pixel so they
    # never accidentally pick up an element colour from their XY position.
    _ANCHOR_U = 2.0 / resolution
    _ANCHOR_V = 2.0 / resolution
    n_polys = len(mesh.polygons)
    loop_totals = np.empty(n_polys, dtype=np.int32)
    mesh.polygons.foreach_get("loop_total", loop_totals)
    loop_face = np.repeat(np.arange(n_polys, dtype=np.int32), loop_totals)
    face_normals_flat = np.empty(n_polys * 3, dtype=np.float32)
    mesh.polygons.foreach_get("normal", face_normals_flat)
    face_nz = face_normals_flat.reshape(-1, 3)[:, 2]
    non_top = face_nz[loop_face] < 0.5
    uv_u[non_top] = _ANCHOR_U
    uv_v[non_top] = _ANCHOR_V

    uv_flat = np.empty(len(mesh.loops) * 2, dtype=np.float32)
    uv_flat[0::2] = uv_u
    uv_flat[1::2] = uv_v
    uv_layer.data.foreach_set("uv", uv_flat)
    mesh.update()

    # ── Rasterize ─────────────────────────────────────────────────────────────
    base_f = (_BASE_SRGB[0] / 255.0, _BASE_SRGB[1] / 255.0, _BASE_SRGB[2] / 255.0, 1.0)
    arr = np.full((resolution, resolution, 4), base_f, dtype=np.float32)

    for kind in _RASTER_ORDER:
        geom = polygons_by_kind.get(kind) or polygons_by_kind.get(kind.lower())
        if geom is None:
            continue
        srgb = _KIND_TO_SRGB[kind]
        c_f = (srgb[0] / 255.0, srgb[1] / 255.0, srgb[2] / 255.0, 1.0)
        _rasterize_geometry(geom, arr, c_f, None,
                            cursor_x, cursor_y, min_x, min_y, width, height, resolution)

    # Re-paint anchor block after all element rasterization so no polygon
    # that happens to touch the corner can overwrite it with an element colour.
    arr[0:4, 0:4] = base_f

    # ── Blender Image ─────────────────────────────────────────────────────────
    img_name = f"{mesh.name}_MMU_Paint"
    if img_name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[img_name])
    image = bpy.data.images.new(img_name, width=resolution, height=resolution, alpha=True)
    image.colorspace_settings.name = 'sRGB'
    image.pixels.foreach_set(arr.ravel())
    image.pack()

    # ── Material ──────────────────────────────────────────────────────────────
    mat_name = img_name
    if mat_name in bpy.data.materials:
        bpy.data.materials.remove(bpy.data.materials[mat_name])
    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    tex_node = nodes.new(type="ShaderNodeTexImage")
    tex_node.image = image
    tex_node.location = (-300, 0)

    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)

    out_node = nodes.new(type="ShaderNodeOutputMaterial")
    out_node.location = (300, 0)

    links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])

    mesh.materials.clear()
    mesh.materials.append(mat)

    # ── 3MF paint metadata ────────────────────────────────────────────────────
    mesh["3mf_is_paint_texture"]      = True
    mesh["3mf_paint_default_extruder"] = 1
    mesh["3mf_paint_extruder_colors"]  = str(palette)

    print(f"[TP3D texture] {resolution}x{resolution}px | {len(palette)} filaments | "
          f"kinds: {sorted(present_kinds)}")
    return palette


def tag_solid_color_for_paint_export(obj, srgb, palette):
    """Give a companion mesh a 1×1 solid-colour paint texture.

    Without this the Orca exporter sees no paint data on the object and the
    slicer defaults it to extruder 1 regardless of material colour.
    srgb must be a colour already present in palette for an exact extruder match.
    """
    if obj is None or not hasattr(obj, 'type') or obj.type != 'MESH':
        return
    mesh = obj.data

    img_name = str(mesh.name) + "_MMU_Solid"
    if img_name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[img_name])
    image = bpy.data.images.new(img_name, width=1, height=1, alpha=True)
    image.colorspace_settings.name = 'sRGB'
    image.pixels.foreach_set([srgb[0] / 255.0, srgb[1] / 255.0, srgb[2] / 255.0, 1.0])
    image.pack()

    if UV_LAYER_NAME in mesh.uv_layers:
        mesh.uv_layers.remove(mesh.uv_layers[UV_LAYER_NAME])
    uv_layer = mesh.uv_layers.new(name=UV_LAYER_NAME)
    mesh.uv_layers.active = uv_layer
    uv_flat = np.full(len(mesh.loops) * 2, 0.5, dtype=np.float32)
    uv_layer.data.foreach_set("uv", uv_flat)

    mat_name = img_name
    if mat_name in bpy.data.materials:
        bpy.data.materials.remove(bpy.data.materials[mat_name])
    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    _nodes = mat.node_tree.nodes
    _links = mat.node_tree.links
    _nodes.clear()
    _tex = _nodes.new(type="ShaderNodeTexImage")
    _tex.image = image
    _tex.location = (-300, 0)
    _bsdf = _nodes.new(type="ShaderNodeBsdfPrincipled")
    _bsdf.location = (0, 0)
    _out = _nodes.new(type="ShaderNodeOutputMaterial")
    _out.location = (300, 0)
    _links.new(_tex.outputs["Color"], _bsdf.inputs["Base Color"])
    _links.new(_bsdf.outputs["BSDF"], _out.inputs["Surface"])
    mesh.materials.clear()
    mesh.materials.append(mat)

    mesh["3mf_is_paint_texture"]       = True
    mesh["3mf_paint_default_extruder"] = 1
    mesh["3mf_paint_extruder_colors"]  = str(palette)


def crop_paint_texture_to_piece(piece_obj, source_image):
    """Crop the shared terrain paint image down to this piece's UV footprint.

    For a 6×6 puzzle this turns 36 full 2K textures into 36 ~340px crops,
    cutting per-piece segmentation work by ~36×.
    """
    mesh = piece_obj.data
    uv_layer = mesh.uv_layers.get(UV_LAYER_NAME)
    if uv_layer is None:
        return

    W, H = source_image.size

    # Identify top-face loops (face normal z ≥ 0.5).
    n_polys = len(mesh.polygons)
    loop_totals = np.empty(n_polys, dtype=np.int32)
    mesh.polygons.foreach_get("loop_total", loop_totals)
    normals_flat = np.empty(n_polys * 3, dtype=np.float32)
    mesh.polygons.foreach_get("normal", normals_flat)
    face_nz = normals_flat.reshape(-1, 3)[:, 2]
    loop_face_idx = np.repeat(np.arange(n_polys, dtype=np.int32), loop_totals)
    top_loop_mask = face_nz[loop_face_idx] >= 0.5

    uv_flat = np.empty(len(mesh.loops) * 2, dtype=np.float32)
    uv_layer.data.foreach_get("uv", uv_flat)
    uv_u = uv_flat[0::2]
    uv_v = uv_flat[1::2]

    if not top_loop_mask.any():
        return

    u_min = float(uv_u[top_loop_mask].min())
    u_max = float(uv_u[top_loop_mask].max())
    v_min = float(uv_v[top_loop_mask].min())
    v_max = float(uv_v[top_loop_mask].max())

    # 2-pixel border so edge triangles don't land on exact pixel boundaries.
    u_min = max(0.0, u_min - 2.0 / W)
    u_max = min(1.0, u_max + 2.0 / W)
    v_min = max(0.0, v_min - 2.0 / H)
    v_max = min(1.0, v_max + 2.0 / H)

    px_x0 = int(u_min * W)
    px_x1 = min(W, int(u_max * W) + 1)
    py_y0 = int(v_min * H)
    py_y1 = min(H, int(v_max * H) + 1)
    crop_w = max(4, px_x1 - px_x0)
    crop_h = max(4, py_y1 - py_y0)

    src_px = np.empty(W * H * 4, dtype=np.float32)
    source_image.pixels.foreach_get(src_px)
    crop_arr = np.ascontiguousarray(
        src_px.reshape(H, W, 4)[py_y0:py_y0 + crop_h, px_x0:px_x0 + crop_w]
    )

    # Re-paint the base-colour anchor block at (0,0)–(4,4) in the crop.
    base_f = (_BASE_SRGB[0] / 255.0, _BASE_SRGB[1] / 255.0, _BASE_SRGB[2] / 255.0, 1.0)
    crop_arr[0:4, 0:4] = base_f

    img_name = str(mesh.name) + "_MMU_Paint"
    if img_name in bpy.data.images:
        bpy.data.images.remove(bpy.data.images[img_name])
    new_img = bpy.data.images.new(img_name, width=crop_w, height=crop_h, alpha=True)
    new_img.colorspace_settings.name = 'sRGB'
    new_img.pixels.foreach_set(crop_arr.ravel())
    new_img.pack()

    # Remap top-face UVs into the new [0, 1] crop space.
    u_range = (u_max - u_min) or 1.0
    v_range = (v_max - v_min) or 1.0
    new_u = uv_u.copy()
    new_v = uv_v.copy()
    new_u[top_loop_mask] = (uv_u[top_loop_mask] - u_min) / u_range
    new_v[top_loop_mask] = (uv_v[top_loop_mask] - v_min) / v_range

    # Pin non-top (side/bottom) loops to the anchor pixel in the cropped space.
    new_u[~top_loop_mask] = 2.0 / crop_w
    new_v[~top_loop_mask] = 2.0 / crop_h

    new_uv_flat = np.empty(len(mesh.loops) * 2, dtype=np.float32)
    new_uv_flat[0::2] = new_u
    new_uv_flat[1::2] = new_v
    uv_layer.data.foreach_set("uv", new_uv_flat)
    mesh.update()

    mat_name = img_name
    if mat_name in bpy.data.materials:
        bpy.data.materials.remove(bpy.data.materials[mat_name])
    mat = bpy.data.materials.new(name=mat_name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    tex_node = nodes.new(type="ShaderNodeTexImage")
    tex_node.image = new_img
    tex_node.location = (-300, 0)
    bsdf = nodes.new(type="ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    out_node = nodes.new(type="ShaderNodeOutputMaterial")
    out_node.location = (300, 0)
    links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])
    mesh.materials.clear()
    mesh.materials.append(mat)

