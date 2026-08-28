import math
import os
import platform
import threading
import time
from typing import Any

import bpy  # type: ignore
import numpy as np  # type: ignore
from bpy.app.translations import pgettext as _
from bpy.types import Object
from mathutils import Vector  # type: ignore

from .. import addon_preferences
from .. import constants as const
from .. import progress as _progress
from .dataclasses import GenerationContext, GenerationError, ValidationError
from .elevation import compute_and_store_tile_bounds
from .terrain import _ColoringTextureResult

# Set after each road-enabled generation; read by the puzzle flow to clip road
# geometry per piece without re-running the road pipeline.
_puzzle_roads_data: tuple | None = None

# ---------------------------------------------------------------------------
# runGeneration sub-phase helpers
# ---------------------------------------------------------------------------


def _rg_validate_inputs(flags, gen_type: int = 0, locked_scale: float | None = None):
    """Load all scene properties, and validate the inputs for the requested generation type.

    Returns a GenerationContext on success, or None if validation fails.
    """
    from bpy.types import Scene

    from ..props import (
        get_effective_shape,  # deferred to avoid circular import at load time
    )

    start_time = time.time()
    print("\n" * 30, end="")
    print(
        "------------------------------------------------",
        "SCRIPT STARTED",
        "------------------------------------------------",
        " ",
    )

    tp3d: Scene = bpy.context.scene.tp3d
    gpx_file_path: str = tp3d.get("file_path", None)
    gpx_chain_path: str = tp3d.get("chain_path", None)
    exportPath: str = tp3d.get("export_path", None)
    shape: str = get_effective_shape(tp3d)
    name: str = tp3d.get("trailName", "")
    size: int = tp3d.get("objSize", 100)
    autoExport: bool = tp3d.get("disable_auto_export", False)
    scaleElevation: float = tp3d.get("scaleElevation", 1)
    scalemode: str = tp3d.get("scaleMode", "FACTOR")
    scaleLon1: float = tp3d.get("scaleLon1", 0)
    scaleLat1: float = tp3d.get("scaleLat1", 0)
    scaleLon2: float = tp3d.get("scaleLon2", 0)
    scaleLat2: float = tp3d.get("scaleLat2", 0)
    shapeRotation: int = tp3d.get("shapeRotation", 0)
    overwritePathElev: bool = tp3d.get("overwritePathElevation", True)
    api: str = tp3d.get("api", "MAPTERHORN")
    selfHosted: str = tp3d.get("selfHosted", "")
    fixedElevScale: bool = tp3d.get("fixedElevationScale", False)
    minThickness: float = tp3d.get("minThickness", 2)
    xTerrainOffset: float = tp3d.get("xTerrainOffset", 0)
    yTerrainOffset: float = tp3d.get("yTerrainOffset", 0)
    singleColorMode: bool = tp3d.get("singleColorMode", 0)
    elementMode: str = tp3d.get("elementMode", "PAINT")
    disableCache: bool = tp3d.get("disableCache", "False")
    num_subdivisions: int = tp3d.get("num_subdivisions", 8)
    textFont: str = tp3d.get("textFont", "")
    plateThickness: float = tp3d.get("plateThickness", 5)
    col_wActive: bool = any(
        [tp3d.col_wPondsActive, tp3d.col_wSmallRiversActive, tp3d.col_wBigRiversActive]
    )
    col_fActive: bool = tp3d.col_fActive
    col_cActive: bool = tp3d.col_cActive
    col_grActive: bool = tp3d.col_grActive
    col_glActive: bool = tp3d.col_glActive
    el_bActive: bool = tp3d.el_bActive
    el_sActive: bool = any(
        [
            tp3d.el_sBigActive,
            tp3d.el_sMedActive,
            tp3d.el_sSmallActive,
            tp3d.el_sServiceActive,
            tp3d.el_sFootwaysActive,
        ]
    )
    el_sHeight: float = tp3d.get("el_sHeight", 1.0)
    jMapLat: float = tp3d.get("jMapLat", 49)
    jMapLon: float = tp3d.get("jMapLon", 9)
    jMapRadius: float = tp3d.get("jMapRadius", 200)
    jMapLat1: float = tp3d.get("jMapLat1", 48)
    jMapLon1: float = tp3d.get("jMapLon1", 8)
    jMapLat2: float = tp3d.get("jMapLat2", 49)
    jMapLon2: float = tp3d.get("jMapLon2", 9)

    opentopoAdress: str = "https://api.opentopodata.org/v1/"
    if selfHosted != "" and selfHosted is not None and api == "OPENTOPODATA":
        opentopoAdress = selfHosted
        print(f"!!using {opentopoAdress} instead of Opentopodata!!")
    tp3d.opentopoAdress = opentopoAdress

    # --- Input validation ---
    from ..addon_preferences import get_prefs

    _ot_api_key = get_prefs().openTopographyApiKey

    if elementMode and el_sActive and el_sHeight == 0:
        raise ValidationError(
            "Road Height is 0 in Paint mode — this produces degenerate geometry. "
            "Set Road Height above 0 or disable roads."
        )

    if api == "OPENTOPOGRAPHY" and not _ot_api_key:
        print("No OPENTOPOGRAPHY API key entered")
        raise ValidationError(
            "OpenTopography requires an API key. "
            "Get a free key at portal.opentopography.org and set it in the addon preferences."
        )

    if "gpx_file" in flags:
        if not gpx_file_path or gpx_file_path == "":
            raise ValidationError("File path is empty! Please select a valid file.")
        if not os.path.isfile(gpx_file_path):
            raise ValidationError(
                f"Invalid file path: {gpx_file_path}. Please select a valid file."
            )
        gpx_file_path = bpy.path.abspath(gpx_file_path)
        file_extension = os.path.splitext(gpx_file_path)[1].lower()
        if file_extension != ".gpx" and file_extension != ".igc":
            raise ValidationError("Invalid file format. Please Use a .GPX file")
    if "gpx_chain" in flags:
        if not gpx_chain_path or gpx_chain_path == "":
            raise ValidationError("CHAIN path is empty! Please select a valid folder.")
        gpx_chain_path = bpy.path.abspath(gpx_chain_path)
    if not exportPath:
        exportPath = addon_preferences.get_prefs().default_export_folder
    if not exportPath:
        raise ValidationError("Export path cant be empty")
    exportPath = bpy.path.abspath(exportPath)
    if not exportPath or exportPath == "":
        raise ValidationError("Export path is empty! Please select a valid folder.")
    if not os.path.isdir(exportPath):
        raise ValidationError(
            f"Invalid export Directory: {exportPath}. Please select a valid Directory."
        )
    try:
        test_path = os.path.join(exportPath, ".tp3d_write_test")
        with open(test_path, "w") as f:
            f.write("")
        os.remove(test_path)
    except OSError:
        raise ValidationError(
            f"No write permission for export folder: {exportPath}. Please select a different folder."
        )

    # --- Default font ---
    if textFont == "":
        if platform.system() == "Windows":
            textFont = "C:/WINDOWS/FONTS/ariblk.ttf"
        elif platform.system() == "Darwin":
            textFont = "/System/Library/Fonts/Supplemental/Arial Black.ttf"

    # --- Default model name from file/folder ---
    if name == "":
        if "gpx_file" in flags:
            name_with_ext = os.path.basename(gpx_file_path)
            name = os.path.splitext(name_with_ext)[0]
        if "gpx_chain" in flags and "append_collection" not in flags:
            name_with_ext = os.path.basename(os.path.normpath(gpx_chain_path))
            name = os.path.splitext(name_with_ext)[0]
        if "gpx_file" not in flags and "gpx_chain" not in flags:
            name = "Terrain"

    modelname: str = name
    tp3d.modelname = modelname

    texTrail: bool = tp3d.tex_include_trail
    exportFormat: str = tp3d.exportformat
    return GenerationContext(
        flags=flags,
        genType=gen_type,
        lockedScale=locked_scale,
        start_time=start_time,
        gpx_file_path=gpx_file_path,
        gpx_chain_path=gpx_chain_path,
        exportPath=exportPath,
        exportFormat=exportFormat,
        shape=shape,
        name=name,
        modelname=modelname,
        size=size,
        autoExport=autoExport,
        scaleElevation=scaleElevation,
        scalemode=scalemode,
        scaleLon1=scaleLon1,
        scaleLat1=scaleLat1,
        scaleLon2=scaleLon2,
        scaleLat2=scaleLat2,
        shapeRotation=shapeRotation,
        overwritePathElevation=overwritePathElev,
        api=api,
        selfHosted=selfHosted,
        fixedElevationScale=fixedElevScale,
        minThickness=minThickness,
        xTerrainOffset=xTerrainOffset,
        yTerrainOffset=yTerrainOffset,
        singleColorMode=singleColorMode,
        elementMode=elementMode,
        disableCache=disableCache,
        num_subdivisions=num_subdivisions,
        textFont=textFont,
        plateThickness=plateThickness,
        col_wActive=col_wActive,
        col_fActive=col_fActive,
        col_cActive=col_cActive,
        col_grActive=col_grActive,
        col_glActive=col_glActive,
        el_bActive=el_bActive,
        el_sActive=el_sActive,
        el_sHeight=el_sHeight,
        jMapLat=jMapLat,
        jMapLon=jMapLon,
        jMapRadius=jMapRadius,
        jMapLat1=jMapLat1,
        jMapLon1=jMapLon1,
        jMapLat2=jMapLat2,
        jMapLon2=jMapLon2,
        texTrail=texTrail,
    )


def _rg_load_coordinates(gen: GenerationContext):
    """Load GPX / synthetic coordinate data based on generation type.

    Returns (coordinates, separate_paths, coordinates2) or None on error.
    """
    from .geo import move_coordinates  # deferred to avoid circular import at load time
    from .io_gpx import (  # deferred to avoid circular import at load time
        read_gpx_directory,
        read_gpx_file,
    )
    from .primitives import (
        setupColors,  # deferred to avoid circular import at load time
    )

    setupColors()

    if gen.disableCache == 1:
        print("INFO: Cache Disabled (in Advanced Settings)")
    if not gen.overwritePathElevation and not gen.singleColorMode:
        print(
            "INFO: Overwrite Path Elevation disabled: Path Elevation wont be Adjusted to Map elevation"
        )
    if "gpx_file" in gen.flags or (
        "gpx_chain" in gen.flags and "append_collection" not in gen.flags
    ):
        if gen.xTerrainOffset > 0:
            print(
                f"INFO: Map will be moved in X by {gen.xTerrainOffset} (Advanced Settings -> Map -> xTerrainOffset)"
            )
        if gen.yTerrainOffset > 0:
            print(
                f"INFO: Map will be moved in Y by {gen.yTerrainOffset} (Advanced Settings -> Map -> yTerrainOffset)"
            )

    if bpy.context.object and bpy.context.object.mode == "EDIT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.scene.tool_settings.use_mesh_automerge = False

    coordinates2 = []
    separate_paths = []
    separate_paths_by_file = []  # segments grouped by source file (gpx_chain only)
    try:
        if "gpx_file" in gen.flags and "trail_map" not in gen.flags:
            separate_paths = read_gpx_file()
        if "gpx_chain" in gen.flags:
            separate_paths_by_file = read_gpx_directory(gen.gpx_chain_path)
            separate_paths = [
                seg for file_segs in separate_paths_by_file for seg in file_segs
            ]
        if "jmap" in gen.flags:
            nlat, nlon = move_coordinates(gen.jMapLat, gen.jMapLon, gen.jMapRadius, "e")
            separate_paths.append([(nlat, nlon, 0, 0)])
            nlat, nlon = move_coordinates(gen.jMapLat, gen.jMapLon, gen.jMapRadius, "s")
            separate_paths.append([(nlat, nlon, 0, 0)])
            nlat, nlon = move_coordinates(gen.jMapLat, gen.jMapLon, gen.jMapRadius, "w")
            separate_paths.append([(nlat, nlon, 0, 0)])
            nlat, nlon = move_coordinates(gen.jMapLat, gen.jMapLon, gen.jMapRadius, "n")
            separate_paths.append([(nlat, nlon, 0, 0)])
            if "trail_map" in gen.flags:
                tempcoordinates = read_gpx_file()
                coordinates2 = [item for sublist in tempcoordinates for item in sublist]
        if "jmap_bbox" in gen.flags:
            separate_paths.append([(gen.jMapLat1, gen.jMapLon1, 0, 0)])
            separate_paths.append([(gen.jMapLat2, gen.jMapLon2, 0, 0)])
    except Exception:  # noqa: BLE001 — GPX/IGC parsing can raise many unpredictable types
        # show_message_box(f"Something went Wrong reading the GPX. Type {type}")
        _progress.WarningsOverlay.add_warning(
            "Something went Wrong reading the GPX file", "error"
        )

    coordinates = [item for sublist in separate_paths for item in sublist]

    gen.pathCoordinates = coordinates
    gen.flatCoordinates = coordinates2
    gen.pathSegs = separate_paths
    gen.pathSegsByFile = separate_paths_by_file


def _rg_compute_trail_stats(gen: GenerationContext):
    """Calculate trail statistics and store them in scene properties."""
    from .geo import (  # deferred to avoid circular import at load time
        calculate_date,
        calculate_total_elevation,
        calculate_total_length,
        calculate_total_time,
    )

    if "stats" not in gen.flags:
        return

    stats = gen.gpx_stats
    stats.length = calculate_total_length(gen.pathCoordinates)
    stats.elevation = calculate_total_elevation(gen.pathCoordinates)
    stats.time = calculate_total_time(gen.pathCoordinates)
    stats.date = calculate_date(gen.pathCoordinates)

    if stats.time is not None and stats.time > 0:
        stats.avg_speed = stats.length / stats.time

        # TODO: Remove this block, blender context should not be the source of truth for stats, but rather the GPXStats object itself. This is a temporary measure to maintain compatibility with existing code that relies on scene properties.
        hours = int(stats.time)
        minutes = int((stats.time - hours) * 60)
        time_str = f"{hours}h {minutes}m"
        tp3d = bpy.context.scene.tp3d
        tp3d.sTime_str = time_str
        tp3d.total_length = stats.length
        tp3d.total_elevation = stats.elevation
        tp3d.total_time = stats.time
        tp3d.average_speed = stats.avg_speed
        tp3d.trail_date = stats.date


def _rg_interpolate_path_curve(gen: GenerationContext):
    if gen.pathCoordinates is None:
        return
    while (
        len(gen.pathCoordinates) < 300
        and len(gen.pathCoordinates) > 1
        and "trail" in gen.flags
    ):
        n = len(gen.pathCoordinates)
        xyz = np.array(
            [(c[0], c[1], c[2]) for c in gen.pathCoordinates], dtype=np.float64
        )
        mids = (xyz[:-1] + xyz[1:]) / 2.0
        # Interleave originals and midpoints: [orig0, mid0, orig1, mid1, ..., origN]
        interleaved: list[tuple[float, float, float, float]] = []
        for i in range(n - 1):
            interleaved.append(gen.pathCoordinates[i])
            interleaved.append(
                (mids[i, 0], mids[i, 1], mids[i, 2], gen.pathCoordinates[i][3])
            )
        interleaved.append(gen.pathCoordinates[-1])
        gen.pathCoordinates = interleaved


def _rg_calculate_horizontal_scale(gen: GenerationContext):
    from .geo import calculate_scale

    if gen.lockedScale is not None:
        gen.sScaleHor = gen.lockedScale
        bpy.context.scene.tp3d["sScaleHor"] = gen.lockedScale
        return

    scalecoords = gen.pathCoordinates
    if gen.scalemode == "COORDINATES" and "gpx_scale" in gen.flags:
        scalecoords = (
            (gen.scaleLon1, gen.scaleLat1),
            (gen.scaleLon2, gen.scaleLat2),
        )
    scaleHor = calculate_scale(gen.size, scalecoords, gen.genType, diagonal=True)
    bpy.context.scene.tp3d["sScaleHor"] = scaleHor
    gen.sScaleHor = scaleHor


def _rg_convert_then_center_coordinates(gen: GenerationContext):
    from .geo import convert_to_blender_coordinates_batch

    blender_coords = convert_to_blender_coordinates_batch(gen.pathCoordinates)
    if "separate_paths" in gen.flags or len(gen.pathSegs or []) > 1:
        gen.blenderPathSegs = [
            convert_to_blender_coordinates_batch(path) for path in gen.pathSegs or []
        ]
    if gen.pathSegsByFile:
        gen.blenderPathSegsByFile = [
            [convert_to_blender_coordinates_batch(seg) for seg in file_segs]
            for file_segs in (gen.pathSegsByFile or [])
        ]
    min_x = min(p[0] for p in blender_coords)
    max_x = max(p[0] for p in blender_coords)
    min_y = min(p[1] for p in blender_coords)
    max_y = max(p[1] for p in blender_coords)
    centerx = (max_x - min_x) / 2 + min_x
    centery = (max_y - min_y) / 2 + min_y
    bpy.context.scene.tp3d["o_centerx"] = centerx
    bpy.context.scene.tp3d["o_centery"] = centery
    gen.centerX = centerx
    gen.centerY = centery


def _cleanup_build_area(gen: GenerationContext):
    """Remove any existing objects in the build area before generating new geometry."""
    xOff = gen.xTerrainOffset
    yOff = gen.yTerrainOffset
    target_2d = Vector((gen.centerX or 0.0, gen.centerY or 0.0))
    target_2d_offset = Vector((gen.centerX or 0.0 + xOff, gen.centerY or 0.0 + yOff))
    for obs in bpy.data.objects:
        obj_2d = Vector((obs.location.x, obs.location.y))
        obj_2d_offset = obj_2d
        if "xTerrainOffset" in obs or "yTerrainOffset" in obs:
            obj_2d_offset = Vector(
                (
                    obs.location.x - obs["xTerrainOffset"],
                    obs.location.y - obs["yTerrainOffset"],
                )
            )
        if (
            (obj_2d - target_2d).length <= 0.2
            or (obj_2d - target_2d_offset).length <= 0.2
            or (obj_2d_offset - target_2d).length <= 0.2
            or (obj_2d_offset - target_2d_offset).length <= 0.2
        ):
            bpy.data.objects.remove(obs, do_unlink=True)
    bpy.ops.object.select_all(action="DESELECT")


def _rg_create_map_object(gen: GenerationContext):
    """Create, rotate, and position the base map shape object."""
    from shapely.wkt import loads

    from .geo import (  # deferred to avoid circular import at load time
        convert_to_blender_coordinates,
        midpoint_spherical,
    )
    from .mesh_ops import (
        recalculateNormals,  # deferred to avoid circular import at load time
    )
    from .presets import (
        appendCollection,  # deferred to avoid circular import at load time
    )
    from .primitives import (  # deferred to avoid circular import at load time
        create_circle,
        create_custom_geojson,
        create_custom_svg,
        create_ellipse,
        create_heart,
        create_hexagon,
        create_octagon,
        create_rectangle,
    )
    from .scene import (
        transform_MapObject,  # deferred to avoid circular import at load time
        zoom_camera_to_selected,
    )

    MapObject = None

    if "append_collection" not in gen.flags and "use_active_object" not in gen.flags:
        print(
            f"[map_object] creating '{gen.shape}' N={gen.num_subdivisions} size={gen.size:.1f}…"
        )
        _t_shape = time.time()
        if gen.shape in {"SQUARE", "SQUARE SHELL"}:
            rHeight = bpy.context.scene.tp3d.rectangleHeight
            MapObject = create_rectangle(
                gen.size, rHeight, gen.num_subdivisions, gen.modelname
            )
        elif gen.shape in {
            "HEXAGON",
            "HEXAGON SHELL",
            "HEXAGON INNER TEXT",
            "HEXAGON OUTER TEXT",
            "HEXAGON FRONT TEXT",
        }:
            MapObject = create_hexagon(
                gen.size / 2, gen.num_subdivisions, gen.modelname
            )
        elif gen.shape == "HEART":
            MapObject = create_heart(gen.size / 2, gen.num_subdivisions, gen.modelname)
        elif gen.shape in {"OCTAGON", "OCTAGON SHELL", "OCTAGON OUTER TEXT"}:
            MapObject = create_octagon(
                gen.size / 2, gen.num_subdivisions, gen.modelname
            )
        elif gen.shape in {"CIRCLE", "CIRCLE SHELL", "CIRCLE OUTER TEXT"}:
            MapObject = create_circle(gen.size / 2, gen.num_subdivisions, gen.modelname)
        elif gen.shape in {"ELLIPSE", "ELLIPSE SHELL"}:
            ratio = bpy.context.scene.tp3d.ellipseRatio
            MapObject = create_ellipse(
                gen.size / 2, gen.num_subdivisions, gen.modelname, ratio
            )
        elif gen.shape == "GEOJSON":
            filepath = bpy.path.abspath(bpy.context.scene.tp3d.customFilePath)
            MapObject = create_custom_geojson(
                filepath, gen.size / 2, gen.num_subdivisions, gen.modelname
            )
        elif gen.shape == "SVG":
            filepath = bpy.path.abspath(bpy.context.scene.tp3d.customFilePath)
            MapObject = create_custom_svg(
                filepath, gen.size / 2, gen.num_subdivisions, gen.modelname
            )
        else:
            MapObject = create_hexagon(
                gen.size / 2, gen.num_subdivisions, gen.modelname
            )
        print(f"[map_object] shape created in {time.time() - _t_shape:.3f}s")
    if "append_collection" in gen.flags:
        appendCollection()
        MapObject = bpy.context.view_layer.objects.active
        MapObject.location = Vector((0, 0, 0))
    if "use_active_object" in gen.flags:
        MapObject = bpy.context.view_layer.objects.active
        return MapObject

    recalculateNormals(MapObject)

    MapObject.rotation_euler[2] += gen.shapeRotation * (3.14159265 / 180)
    MapObject.select_set(True)
    bpy.context.view_layer.objects.active = MapObject
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)

    targetx = (gen.centerX or 0.0) + gen.xTerrainOffset
    targety = (gen.centerY or 0.0) + gen.yTerrainOffset
    if gen.scalemode == "COORDINATES" and "chain_coords_center" in gen.flags:
        midLat, midLon = midpoint_spherical(
            gen.scaleLat1,
            gen.scaleLon1,
            gen.scaleLat2,
            gen.scaleLon2,
        )
        targetx, targety, _el = convert_to_blender_coordinates(midLat, midLon, 0, 0)

    transform_MapObject(MapObject, targetx, targety)
    if MapObject and "map_polygon_wkt" in MapObject:
        outline = loads(MapObject["map_polygon_wkt"])
        gen.mapOutline = outline
        gen.mapObject = MapObject
        bpy.context.scene.tp3d.currentMap = MapObject

    zoom_camera_to_selected(MapObject)
    compute_and_store_tile_bounds(gen)
    return MapObject


def _rg_start_osm_prefetch(gen: GenerationContext):
    """Snapshot all bpy values on the main thread and launch a daemon thread
    that pre-fetches every active OSM coloring kind before mesh-building begins.

    The caller must call thread.join() before consuming the result dict.
    Returns (None, {}) immediately if no coloring elements are active.
    """
    from .osm.fetch_utils import (
        OsmFetchSettings,  # deferred to avoid circular import at load time
    )
    from .terrain import (
        _fetch_all_kinds_parallel,  # deferred to avoid circular import at load time
    )

    _lat_span = gen.tbMaxLat - gen.tbMinLat
    _lon_span = gen.tbMaxLon - gen.tbMinLon
    if _lat_span <= 0 or _lon_span <= 0:
        return None, {}
    _lat_step = min(2.0, _lat_span)
    _lon_step = min(2.0, _lon_span)
    _tile_lats = math.ceil(_lat_span / _lat_step)
    _tile_lons = math.ceil(_lon_span / _lon_step)
    _tile_tasks = [
        (
            gen.tbMinLat + k * _lat_step,
            gen.tbMinLon + l * _lon_step,
            gen.tbMinLat + k * _lat_step + _lat_step,
            gen.tbMinLon + l * _lon_step + _lon_step,
        )
        for k in range(_tile_lats)
        for l in range(_tile_lons)
    ]
    _semaphore = threading.Semaphore(
        1
    )  # max 1 concurrent live Overpass request (avoid 429s on the public instance)
    tp3d = bpy.context.scene.tp3d
    _fetch_settings = OsmFetchSettings(
        disable_cache=tp3d.disableCache,
        api_retries=tp3d.apiRetries,
        mapsize=tp3d.sMapInKm,
        road_big=bool(tp3d.el_sBigActive),
        road_med=bool(tp3d.el_sMedActive),
        road_small=bool(tp3d.el_sSmallActive),
        water_ponds=bool(tp3d.col_wPondsActive),
        water_small_rivers=bool(tp3d.col_wSmallRiversActive),
        water_big_rivers=bool(tp3d.col_wBigRiversActive),
        exclude_alleys=bool(tp3d.el_sExcludeAlleys),
        road_footways=bool(tp3d.el_sFootwaysActive),
        road_service=bool(tp3d.el_sServiceActive),
    )
    map_km = gen.mapKm if gen.mapKm is not None else tp3d.sMapInKm
    _active_kind_tasks = [
        (key.upper(), _tile_tasks)
        for key, flag_attr, max_size, _, _ in COLORING_ELEMENTS
        if (flag_attr(tp3d) if callable(flag_attr) else getattr(tp3d, flag_attr) == 1)
        and map_km <= max_size
    ]
    if tp3d.el_bActive == 1 and map_km <= const.BUILDINGS_MAXSIZE:
        _active_kind_tasks.append(("BUILDINGS", _tile_tasks))
    if (
        any(
            [
                tp3d.el_sBigActive,
                tp3d.el_sMedActive,
                tp3d.el_sSmallActive,
                tp3d.el_sServiceActive,
                tp3d.el_sFootwaysActive,
            ]
        )
        and map_km <= const.ROADS_MAXSIZE
    ):
        _active_kind_tasks.append(("STREETS", _tile_tasks))
    if tp3d.el_oActive == 1 and map_km <= const.COASTLINE_MAXSIZE:
        _active_kind_tasks.append(("COASTLINE", _tile_tasks))
    if not _active_kind_tasks:
        return None, {}

    result = {}

    def _run():
        fetched = _fetch_all_kinds_parallel(
            _active_kind_tasks, _semaphore, settings=_fetch_settings
        )
        result.update(fetched)

    t = threading.Thread(target=_run, daemon=True, name="osm-prefetch")
    t.start()
    gen.fetchThread = t
    gen.fetchResult = result


def _rg_fetch_elevation(gen: GenerationContext):
    from ..progress import ProgressOverlay, WarningsOverlay
    from .elevation import get_tile_elevation

    overlay = ProgressOverlay.get()
    warning = WarningsOverlay.get()

    def _elevation_progress(pct):
        t = pct / 100.0
        overlay.set_fetch_progress("elevation", t)
        overlay.update(
            0.38 + t * (0.65 - 0.38),
            "Fetching Elevation Data",
            "Querying elevation API…",
            sub_percent=t,
            sub_label="Tiles processed",
        )

    print(
        "------------------------------------------------",
        "FETCHING ELEVATION DATA FOR THE MAP",
        "------------------------------------------------",
    )

    get_tile_elevation(gen, progress_cb=_elevation_progress)

    if gen.elDiff is None:
        raise GenerationError(
            "Elevation fetch returned no data — check your API settings and connection"
        )
    if gen.fixedElevationScale:
        autoScale = 10 / (gen.elDiff / 1000) if gen.elDiff > 0 else 10
    else:
        autoScale = gen.sScaleHor
    bpy.context.scene.tp3d.sAutoScale = autoScale
    gen.autoScale = autoScale

    if gen.tileVerts and len(gen.tileVerts) < 1000:
        warning.add_warning(
            f"Mesh has only {len(gen.tileVerts)} Points. Increase Resolution for higher Quality",
            "warn",
        )
    if not gen.fixedElevationScale and (
        gen.elDiff == 0 or (gen.elDiff / 1000) * autoScale * gen.scaleElevation < 2
    ):
        warning.add_warning(
            "Terrain seems to be really flat. If not intended, increase Elevation scale",
            icon="warn",
        )


def _rg_prepare_trail_coords(gen: GenerationContext):
    """Convert GPX coordinates to Blender space and prepare all trail geometry arrays.

    Selects the correct coordinate set for the generation type, converts to Blender
    coordinates, simplifies, removes duplicates, and subdivides long segments to
    prevent trail clipping through terrain.  Stores results back into gen:
      gen.blenderCoords         — processed main path
      gen.blenderPathSegs       — processed per-segment paths (replaces Phase-6 raw version)
      gen.blenderPathSegsByFile — processed per-file paths   (replaces Phase-6 raw version)
    Also writes the real-world map scale to the scene property store.
    """
    from .geo import (
        convert_to_blender_coordinates_batch,
        haversine,
        separate_duplicate_xy,
    )
    from .primitives import simplify_curve

    _MAX_TRAIL_SEG_BU = 0.25
    _depsgraph = bpy.context.evaluated_depsgraph_get()

    # Select coordinate set: trail_map uses the flat/synthetic path, not the GPX trail
    coordinates = (
        gen.flatCoordinates if "trail_map" in gen.flags else gen.pathCoordinates
    ) or []

    # --- Main path: convert → simplify → deduplicate → subdivide ---
    blender_coords = convert_to_blender_coordinates_batch(coordinates)

    if bpy.app.debug:
        # Log average slope using the pre-processed per-segment coords when available
        _pre_segs = gen.blenderPathSegs or [blender_coords]
        _g_slopes = []
        for _seg in _pre_segs:
            for _i in range(len(_seg) - 1):
                x1, y1, z1 = _seg[_i]
                x2, y2, z2 = _seg[_i + 1]
                _h = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
                if _h > 0:
                    _g_slopes.append(abs(z2 - z1) / _h)
        if _g_slopes:
            _avg_g = sum(_g_slopes) / len(_g_slopes)
            print(
                f"[DEBUG] GPX avg slope:     {_avg_g:.4f}  ({math.degrees(math.atan(_avg_g)):.2f}°)"
            )

    blender_coords = simplify_curve(blender_coords, 0.12)
    print("Removing duplicates")
    blender_coords = separate_duplicate_xy(blender_coords, 0.05)
    gen.blenderCoords = _subdivide_long_segments(
        blender_coords, _MAX_TRAIL_SEG_BU, _depsgraph
    )

    # --- Per-segment paths ---
    if (
        "separate_paths" in gen.flags or len(gen.pathSegs or []) > 1
    ) and "trail_map" not in gen.flags:
        gen.blenderPathSegs = [
            _subdivide_long_segments(
                separate_duplicate_xy(
                    simplify_curve(convert_to_blender_coordinates_batch(path), 0.12),
                    0.05,
                ),
                _MAX_TRAIL_SEG_BU,
                _depsgraph,
            )
            for path in (gen.pathSegs or [])
        ]
    else:
        gen.blenderPathSegs = None

    # --- Per-file paths ---
    if gen.pathSegsByFile and "trail_map" not in gen.flags:
        gen.blenderPathSegsByFile = [
            [
                _subdivide_long_segments(
                    separate_duplicate_xy(
                        simplify_curve(convert_to_blender_coordinates_batch(seg), 0.12),
                        0.05,
                    ),
                    _MAX_TRAIL_SEG_BU,
                    _depsgraph,
                )
                for seg in file_segs
            ]
            for file_segs in gen.pathSegsByFile
        ]
    else:
        gen.blenderPathSegsByFile = None

    # --- Store real-world map scale ---
    if len(coordinates) >= 2:
        lat1, lon1 = coordinates[0][0], coordinates[0][1]
        lat2, lon2 = coordinates[-1][0], coordinates[-1][1]
        tdist = haversine(lat1, lon1, lat2, lon2)
        mscale = (tdist / gen.size) * 1_000_000
        bpy.context.scene.tp3d["o_mapScale"] = f"{mscale:.0f}"


def _rg_build_trail_curves(gen: GenerationContext):
    """Create Blender curve objects from the processed trail coordinate arrays.

    Uses gen.blenderCoords, gen.blenderPathSegs, and gen.blenderPathSegsByFile
    (populated by _rg_prepare_trail_coords) and gen.flags to pick the right
    curve-creation strategy.

    Raises Exception on Runtime error
    """
    from .mesh_ops import splitCurves
    from .primitives import create_curve_from_coordinates

    blender_coords = gen.blenderCoords or []
    blender_coords_separate = gen.blenderPathSegs or []
    blender_coords_by_file = gen.blenderPathSegsByFile or []
    flags = gen.flags

    curveObj = None
    curveObjs = None
    print("Building trail curve(s)")
    try:
        if (
            "gpx_file" in flags
            and "trail_map" not in flags
            and len(blender_coords_separate) <= 1
        ) or "trail_map" in flags:
            # Single segment or trail_map: one curve directly
            curveObj = create_curve_from_coordinates(gen, blender_coords)
        elif (
            "gpx_chain" in flags
            and blender_coords_by_file
            and "trail_map" not in flags
            and "trail" in flags
        ):
            # Multi-file: one object per file, joining its segments as separate splines
            curveObjs = []
            for file_segs in blender_coords_by_file:
                bpy.ops.object.select_all(action="DESELECT")
                for crds in file_segs:
                    create_curve_from_coordinates(gen, crds)
                if len(file_segs) > 1:
                    bpy.ops.object.join()
                curveObjs.append(bpy.context.view_layer.objects.active)
                gen.curveObjs = curveObjs
        elif (
            ("separate_paths" in flags or len(blender_coords_separate) > 1)
            and "trail_map" not in flags
            and "trail" in flags
        ):
            # Single file with multiple segments: join all into one object
            bpy.ops.object.select_all(action="DESELECT")
            for crds in blender_coords_separate:
                create_curve_from_coordinates(gen, crds)
            bpy.ops.object.join()
            curveObjs = [bpy.context.view_layer.objects.active]
    except RuntimeError:
        raise GenerationError(
            "Bad Response from API while creating the curve. If this happens everytime contact dev"
        )

    if curveObj is None and curveObjs is None:
        raise GenerationError("No trail curves created")

    if curveObj is not None and curveObjs is None:
        curveObjs = splitCurves(curveObj)

    if curveObjs is None:
        raise GenerationError("Failed to split curveObj")

    gen.curveObjs = curveObjs
    print(f"Curve objects created: {len(curveObjs) or 'unknown'}")

    bpy.ops.object.select_all(action="DESELECT")


def _rg_displace_terrain_with_curve(gen: GenerationContext):
    """Displace terrain mesh vertices using Mercator‑corrected elevation data,
    then snap trail curves onto the displaced surface.

    Raises GenerationError if input data is missing or invalid.
    """
    import math

    import numpy as np

    from ..utils.mesh_ops import RaycastCurveToMesh

    # --- Validate input ---
    if gen.mapObject is None:
        raise GenerationError("No map object assigned; cannot displace terrain.")
    if gen.mapObject.type != "MESH":
        raise GenerationError(f"Map object '{gen.mapObject.name}' is not a mesh.")
    if (
        not hasattr(gen, "tileVerts")
        or gen.tileVerts is None
        or len(gen.tileVerts) == 0
    ):
        raise GenerationError(
            "Missing or empty 'tileVerts' – elevation data not available."
        )

    mesh = gen.mapObject.data
    _total_verts = len(mesh.vertices)
    if _total_verts == 0:
        raise GenerationError("Map object has no vertices.")

    print(f"Displacing terrain: {mesh.name} ({_total_verts} vertices)")

    # --- Bulk read vertex coordinates ---
    co_flat = np.empty(_total_verts * 3, dtype=np.float64)
    mesh.vertices.foreach_get("co", co_flat)
    co = co_flat.reshape((_total_verts, 3))

    # --- World‑space Y for Mercator correction ---
    try:
        m = np.array(gen.mapObject.matrix_world, dtype=np.float64)
        co_h = np.hstack([co, np.ones((_total_verts, 1), dtype=np.float64)])
        world_y = (m @ co_h.T).T[:, 1]
    except Exception as e:  # noqa: BLE001
        raise GenerationError(f"Failed to transform vertex coordinates: {e}")

    # --- Mercator latitude correction ---
    try:
        lat_rad = 2.0 * np.arctan(np.exp(world_y / (const.R * gen.sScaleHor))) - (
            np.pi / 2.0
        )
        merc = 1.0 / np.cos(lat_rad)
    except Exception as e:  # noqa: BLE001
        raise GenerationError(f"Mercator correction failed: {e}")

    # --- Compute new Z for all vertices ---
    try:
        tile_verts = np.array(gen.tileVerts, dtype=np.float64)
        if tile_verts.shape != (_total_verts,):
            # if tileVerts is a list of lists? adapt as needed – here assume flat array
            raise ValueError(
                f"tileVerts length {len(tile_verts)} doesn't match vertices {_total_verts}"
            )
        new_z = (tile_verts / 1000.0) * gen.scaleElevation * gen.autoScale * merc
        co[:, 2] = new_z
        mesh.vertices.foreach_set("co", co.ravel())
        mesh.update()
    except Exception as e:  # noqa: BLE001
        raise GenerationError(f"Failed to apply elevation displacement: {e}")

    # --- Store min/max and extrusion offset ---
    lowestZ = float(new_z.min())
    highestZ = float(new_z.max())
    additionalExtrusion = lowestZ
    gen.addExtrusion = additionalExtrusion

    # Update scene properties if they exist (with fallback)
    try:
        bpy.context.scene.tp3d.sAdditionalExtrusion = additionalExtrusion
        bpy.context.scene.tp3d.lowestZ = lowestZ
        bpy.context.scene.tp3d.highestZ = highestZ
    except AttributeError:
        # Property group may not be registered yet; warn but continue
        print(
            "Warning: tp3d property group not found; elevation stats not saved to scene."
        )

    print(f"additionalExtrusion: {additionalExtrusion}")
    print(f"Lowest Z: {lowestZ}")
    print(f"Highest Z: {highestZ}")

    # --- Optional debug: slope statistics ---
    if bpy.app.debug:
        try:
            _t_slopes = []
            for edge in mesh.edges:
                v1 = mesh.vertices[edge.vertices[0]].co
                v2 = mesh.vertices[edge.vertices[1]].co
                _h = math.sqrt((v2.x - v1.x) ** 2 + (v2.y - v1.y) ** 2)
                if _h > 0:
                    _t_slopes.append(abs(v2.z - v1.z) / _h)
            if _t_slopes:
                _avg_t = sum(_t_slopes) / len(_t_slopes)
                print(
                    f"[DEBUG] Terrain avg slope: {_avg_t:.4f}  ({math.degrees(math.atan(_avg_t)):.2f}°)"
                )
        except Exception as e:  # noqa: BLE001
            raise GenerationError(f"[DEBUG] Slope computation failed: {e}")

    # --- Snap trail curves to the displaced surface ---
    if gen.overwritePathElevation:
        curves_to_snap = []
        if gen.curveObj is not None:
            curves_to_snap.append(gen.curveObj)
        if gen.curveObjs is not None:
            curves_to_snap.extend(gen.curveObjs)

        if not curves_to_snap:
            print(
                "No trail curves to snap (overwritePathElevation is True but no curves found)."
            )
        else:
            for curve in curves_to_snap:
                if curve is not None and curve.type == "CURVE":
                    try:
                        RaycastCurveToMesh(curve, gen.mapObject)
                    except Exception as e:  # noqa: BLE001
                        raise GenerationError(
                            f"Failed to snap curve '{curve.name}' to terrain: {e}"
                        )
                else:
                    print(f"Skipping invalid curve object: {curve}")


def _rg_extrude_terrain(gen: GenerationContext):
    # Extrude ONLY outer boundary down to form walls + single bottom cap
    import bmesh
    import shapely.geometry as sg
    import shapely.ops as so
    from shapely.ops import polygonize

    from . import geometry2d as g2d

    obj = gen.mapObject
    if obj.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    bm = bmesh.new()
    bm.from_mesh(obj.data)

    if gen.addExtrusion is None:
        return
    target_bottom_z = gen.addExtrusion - gen.minThickness
    shift_z = -gen.addExtrusion + gen.minThickness

    # Extrude boundary edges downward
    top_boundary_edges = [e for e in bm.edges if e.is_boundary]
    extrude_res = bmesh.ops.extrude_edge_only(bm, edges=top_boundary_edges)

    extruded_verts = [
        elem for elem in extrude_res["geom"] if isinstance(elem, bmesh.types.BMVert)
    ]
    extruded_edges = [
        elem for elem in extrude_res["geom"] if isinstance(elem, bmesh.types.BMEdge)
    ]

    # 1. Flatten all bottom vertices
    for v in extruded_verts:
        v.co.z = target_bottom_z

    # 2. Build direct 2D coordinate lookup for extruded bottom vertices
    bottom_boundary_edges = [e for e in extruded_edges if e.is_boundary]
    loops = g2d.group_boundary_loops(bottom_boundary_edges)

    rings = []
    if loops:
        # 3. Convert mesh boundary loops into 2D Shapely LinearRings (contains ALL lattice verts)
        for loop in loops:
            if len(loop) >= 3:
                pts = [(v.co.x, v.co.y) for v in loop]
                if pts[0] != pts[-1]:
                    pts.append(pts[0])
                rings.append(sg.LinearRing(pts))

    # 4. Automatically reconstruct shell & hole hierarchy from the mesh boundary rings
    mesh_polygons = list(polygonize(rings))

    # Filter out empty space voids using original vector outline
    map_polygon = g2d.get_map_polygon(obj)
    if map_polygon:
        mesh_polygons = [
            p for p in mesh_polygons if map_polygon.covers(p.representative_point())
        ]

    # Lookup mapping 2D coords back to the exact bottom BMVerts
    vert_lookup = {
        (round(v.co.x, 6), round(v.co.y, 6)): v for loop in loops for v in loop
    }

    for poly in mesh_polygons:
        if poly.is_empty:
            continue

        if not poly.is_valid:
            poly = poly.buffer(0)

        exterior_ring = list(poly.exterior.coords)[:-1]
        interior_rings = [list(h.coords)[:-1] for h in poly.interiors]

        # Triangulate using the mesh-derived boundary vertices
        cdt_res = g2d._cdt_triangulate(poly, exterior_ring, interior_rings)

        if cdt_res is None:
            # Fallback
            delaunay_tris = [t for t in so.triangulate(poly) if poly.covers(t.centroid)]
            for tri in delaunay_tris:
                tri_coords = list(tri.exterior.coords)[:3]
                bm_verts = [
                    vert_lookup.get((round(pt[0], 6), round(pt[1], 6)))
                    for pt in tri_coords
                ]

                if None not in bm_verts and len(set(bm_verts)) == 3:
                    v1, v2, v3 = bm_verts
                    assert v1 is not None and v2 is not None and v3 is not None
                    normal = (v2.co - v1.co).cross(v3.co - v1.co)
                    if normal.z > 0:
                        bm.faces.new((v1, v3, v2))
                    else:
                        bm.faces.new((v1, v2, v3))
        else:
            verts2d, tris = cdt_res
            bm_vert_list = []

            for x, y in verts2d:
                key = (round(x, 6), round(y, 6))
                if key in vert_lookup:
                    bm_vert_list.append(vert_lookup[key])
                else:
                    new_v = bm.verts.new((x, y, target_bottom_z))
                    bm_vert_list.append(new_v)
                    vert_lookup[key] = new_v

            for ia, ib, ic in tris:
                v1, v2, v3 = bm_vert_list[ia], bm_vert_list[ib], bm_vert_list[ic]
                if len({v1, v2, v3}) == 3:
                    normal = (v2.co - v1.co).cross(v3.co - v1.co)
                    if normal.z > 0:
                        bm.faces.new((v1, v3, v2))
                    else:
                        bm.faces.new((v1, v2, v3))

    for v in bm.verts:
        v.co.z += shift_z

    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()

    # Apply BASE material to the map mesh
    mat = bpy.data.materials.get("BASE")
    obj.data.materials.clear()
    obj.data.materials.append(mat)

    # Shift curve objects in Python space
    if gen.curveObjs:
        for tcrv in gen.curveObjs:
            tcrv.location.z += shift_z

    # Set object origin to cursor position
    location = obj.location
    bpy.context.scene.cursor.location = location
    if gen.curveObjs:
        for tcrv in gen.curveObjs:
            tcrv.select_set(True)
            bpy.ops.object.origin_set(type="ORIGIN_CURSOR")


def _rg_create_text_and_overlays(gen: GenerationContext):
    from math import pi

    from .scene import set_origin_to_3d_cursor, transform_MapObject

    try:
        from ..premium.utils_pe import (
            build_map_shell,  # Premium-only: Shell shape extra
        )
    except ImportError:

        def build_map_shell(*_args, **_kwargs):
            return None

    from .terrain import plateInsert  # deferred to avoid circular import at load time
    from .text_objects import (  # deferred to avoid circular import at load time
        HexagonFrontText,
        HexagonInnerText,
        HexagonOuterText,
        MedalText,
        OctagonOuterText,
    )

    textobj = None
    plateobj = None
    shellobj = None
    bpy.ops.object.select_all(action="DESELECT")

    if "append_collection" not in gen.flags:
        if gen.shape == "HEXAGON INNER TEXT":
            textobj = HexagonInnerText(gen.mapObject)
        elif gen.shape == "HEXAGON OUTER TEXT":
            textobj, plateobj = HexagonOuterText()
            gen.mapObject.location.z += gen.plateThickness
        elif gen.shape == "OCTAGON OUTER TEXT":
            textobj, plateobj = OctagonOuterText()
            gen.mapObject.location.z += gen.plateThickness
        elif gen.shape == "HEXAGON FRONT TEXT":
            textobj, plateobj = HexagonFrontText()
            gen.mapObject.location.z += gen.plateThickness
        elif gen.shape == "CIRCLE OUTER TEXT":
            textobj, plateobj = MedalText()
            gen.mapObject.location.z += gen.plateThickness
        elif gen.shape.endswith(" SHELL"):
            shellobj = build_map_shell(
                gen.mapObject,
                bpy.context.scene.tp3d.tolerance,
                wall=bpy.context.scene.tp3d.shellWallThickness,
                bottom_wall=1.0,
            )

            if shellobj:
                set_origin_to_3d_cursor(shellobj)
        else:
            pass  # BottomText() — currently disabled

    if (
        "TEXT" in gen.shape
        and gen.curveObjs is not None
        and "INNER TEXT" not in gen.shape
    ) or (gen.shape == "CIRCLE OUTER TEXT" and gen.curveObjs is not None):
        for tcrv in gen.curveObjs:
            tcrv.location.z += gen.plateThickness

    # Plate insert
    bpy.ops.object.select_all(action="DESELECT")
    dist = bpy.context.scene.tp3d.plateInsertValue
    if (
        gen.shape
        in {
            "HEXAGON OUTER TEXT",
            "OCTAGON OUTER TEXT",
            "HEXAGON FRONT TEXT",
            "CIRCLE OUTER TEXT",
        }
        and plateobj
        and textobj
    ):
        transform_MapObject(plateobj, gen.xTerrainOffset, gen.yTerrainOffset)
        transform_MapObject(textobj, gen.xTerrainOffset, gen.yTerrainOffset)
        set_origin_to_3d_cursor(plateobj)
        set_origin_to_3d_cursor(textobj)
        if dist > 0:
            plateInsert(plateobj, gen.mapObject)
            textobj.location.z += dist
        if gen.shapeRotation != 0:
            textobj.rotation_euler[2] += gen.shapeRotation * (pi / 180)

    gen.textObj = textobj
    gen.plateObj = plateobj
    gen.shellObj = shellobj

    # --- Material preview mode ---
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            for space in area.spaces:
                if space.type == "VIEW_3D":
                    space.shading.type = "MATERIAL"


def _rg_build_terrain_elements(
    gen: GenerationContext,
    phase_start=0.83,
    phase_end=0.95,
    prefetched_osm=None,
    tile_label=None,
) -> dict[str, Any]:
    """Create water, forest, city, glacier, building and road overlay meshes.

    Reads all flags directly from bpy.context.scene.tp3d.
    Returns a dict keyed by element name; values may be None if disabled.
    phase_start/phase_end control the overlay progress range for multi-tile callers.
    prefetched_osm: result dict from _rg_start_osm_prefetch; if provided the
    per-kind OSM fetch is skipped (data was already downloaded in the background).
    tile_label: optional prefix for progress messages (e.g. "Tile 2/6") used by
    multi-tile callers so element messages keep their tile context visible.
    """
    from .metadata import (
        writeMetadata,  # deferred to avoid circular import at load time
    )
    from .osm.buildings import create_buildings
    from .osm.fetch_utils import OsmFetchSettings
    from .osm.roads import create_roads
    from .scene import set_origin_to_3d_cursor
    from .terrain import (  # deferred to avoid circular import at load time
        _COLORING_EMPTY,
        _COLORING_FILTERED,
        _COLORING_PAINTED,
        _fetch_all_kinds_parallel,
        coloring_main,
        createOcean,
    )

    tp3d = bpy.context.scene.tp3d
    map_km: float | None = gen.mapKm
    _ov = _progress.ProgressOverlay.get()

    # --------------------------------------------------
    # Standard coloring elements (all share the same pattern).
    # To add a new layer: append one tuple here and nothing else.
    #   (result_key, active_flag_attr, max_size_const, phase_label, fetch_message)
    # --------------------------------------------------
    COLORING_ELEMENTS = [
        (
            "forest",
            "col_fActive",
            const.FOREST_MAXSIZE,
            "Forest",
            "Fetching forest data…",
        ),
        (
            "water",
            lambda t: (
                t.col_wPondsActive or t.col_wSmallRiversActive or t.col_wBigRiversActive
            ),
            const.WATER_MAXSIZE,
            "Water",
            "Fetching water data…",
        ),
        (
            "scree",
            "col_scrActive",
            const.SCREE_MAXSIZE,
            "Scree",
            "Fetching scree data…",
        ),
        ("city", "col_cActive", const.CITY_MAXSIZE, "City", "Fetching city data…"),
        (
            "greenspace",
            "col_grActive",
            const.GREENSPACE_MAXSIZE,
            "Greenspace",
            "Fetching greenspace data…",
        ),
        (
            "farmland",
            "col_faActive",
            const.FARMLAND_MAXSIZE,
            "Farmland",
            "Fetching farmland data…",
        ),
        (
            "glacier",
            "col_glActive",
            const.GLACIER_MAXSIZE,
            "Glacier",
            "Fetching glacier data…",
        ),
    ]

    # Count total active elements (coloring + optional ocean/buildings/roads) for progress spread
    _ELEM_PHASE_START = phase_start
    _ELEM_PHASE_END = phase_end
    if map_km is None:
        raise GenerationError("map_km value not set properly.")
    _active_elem_flags = (
        [
            flag
            for _, flag, size, _, _ in COLORING_ELEMENTS
            if (flag(tp3d) if callable(flag) else getattr(tp3d, flag) == 1)
            and map_km <= size
        ]
        + (
            ["_ocean"]
            if tp3d.el_oActive == 1 and map_km <= const.COASTLINE_MAXSIZE
            else []
        )
        + (
            ["_buildings"]
            if tp3d.el_bActive == 1 and map_km <= const.BUILDINGS_MAXSIZE
            else []
        )
        + (
            ["_roads"]
            if any(
                [
                    tp3d.el_sBigActive,
                    tp3d.el_sMedActive,
                    tp3d.el_sSmallActive,
                    tp3d.el_sServiceActive,
                    tp3d.el_sFootwaysActive,
                ]
            )
            and map_km <= const.ROADS_MAXSIZE
            else []
        )
    )
    obj = gen.mapObject
    scaleHor = gen.sScaleHor
    _total_active = max(len(_active_elem_flags), 1)
    _elem_step = (_ELEM_PHASE_END - _ELEM_PHASE_START) / _total_active
    _elem_idx = [0]  # mutable counter

    def _advance_elem_progress(phase_label, msg):
        if _ov.active:
            pct = _ELEM_PHASE_START + _elem_idx[0] * _elem_step
            full_msg = f"{tile_label} — {msg}" if tile_label else msg
            _ov.update(percent=pct, phase=phase_label, message=full_msg)
        _elem_idx[0] += 1

    _water_feat_active = (
        tp3d.col_wPondsActive
        or tp3d.col_wSmallRiversActive
        or tp3d.col_wBigRiversActive
    ) and map_km <= const.WATER_MAXSIZE
    _ocean_active = tp3d.el_oActive == 1 and map_km <= const.COASTLINE_MAXSIZE
    _water_ocean_combined = _water_feat_active and _ocean_active

    # --------------------------------------------------
    # Fetch all active OSM kinds unless already done by the background thread
    # started before elevation (prefetched_osm != None means data is ready).
    # --------------------------------------------------
    if prefetched_osm is None:
        _lat_step = min(2.0, gen.tbMaxLat - gen.tbMinLat)
        _lon_step = min(2.0, gen.tbMaxLon - gen.tbMinLon)
        _tile_lats = math.ceil((gen.tbMaxLat - gen.tbMinLat) / _lat_step)
        _tile_lons = math.ceil((gen.tbMaxLon - gen.tbMinLon) / _lon_step)
        _tile_tasks = [
            (
                gen.tbMaxLat + k * _lat_step,
                gen.tbMinLon + l * _lon_step,
                gen.tbMinLat + k * _lat_step + _lat_step,
                gen.tbMinLon + l * _lon_step + _lon_step,
            )
            for k in range(_tile_lats)
            for l in range(_tile_lons)
        ]
        _overpass_semaphore = threading.Semaphore(
            1
        )  # max 1 concurrent live Overpass request (avoid 429s on the public instance)
        _fetch_settings = OsmFetchSettings(
            disable_cache=tp3d.disableCache,
            api_retries=tp3d.apiRetries,
            mapsize=tp3d.sMapInKm,
            road_big=bool(tp3d.el_sBigActive),
            road_med=bool(tp3d.el_sMedActive),
            road_small=bool(tp3d.el_sSmallActive),
            water_ponds=bool(tp3d.col_wPondsActive),
            water_small_rivers=bool(tp3d.col_wSmallRiversActive),
            water_big_rivers=bool(tp3d.col_wBigRiversActive),
            exclude_alleys=bool(tp3d.el_sExcludeAlleys),
            road_footways=bool(tp3d.el_sFootwaysActive),
            road_service=bool(tp3d.el_sServiceActive),
        )
        _active_kind_tasks = [
            (key.upper(), _tile_tasks)
            for key, flag_attr, max_size, _, _ in COLORING_ELEMENTS
            if (
                flag_attr(tp3d)
                if callable(flag_attr)
                else getattr(tp3d, flag_attr) == 1
            )
            and map_km <= max_size
        ]
        _all_prefetched = _fetch_all_kinds_parallel(
            _active_kind_tasks, _overpass_semaphore, settings=_fetch_settings
        )
    else:
        _all_prefetched = prefetched_osm

    # After batch download completes, show 100% for all fetched kinds so the
    # strip indicates the download is done while mesh building is still pending.
    # The final set_fetch_done/empty/filtered below flips each badge to ✓ once
    # the mesh operations for that kind are complete.
    if _ov.active:
        for key, flag_attr, max_size, _, _ in COLORING_ELEMENTS:
            if (
                (
                    flag_attr(tp3d)
                    if callable(flag_attr)
                    else getattr(tp3d, flag_attr) == 1
                )
                and map_km <= max_size
                and _all_prefetched.get(key.upper())
            ):
                _ov.set_fetch_ready(key)
        # Buildings, roads, and ocean are pre-fetched in the same batch but aren't
        # in COLORING_ELEMENTS, so mark them ready here too.
        if (
            tp3d.el_bActive == 1
            and map_km <= const.BUILDINGS_MAXSIZE
            and _all_prefetched.get("BUILDINGS")
        ):
            _ov.set_fetch_ready("buildings")
        if (
            any(
                [
                    tp3d.el_sBigActive,
                    tp3d.el_sMedActive,
                    tp3d.el_sSmallActive,
                    tp3d.el_sServiceActive,
                    tp3d.el_sFootwaysActive,
                ]
            )
            and map_km <= const.ROADS_MAXSIZE
            and _all_prefetched.get("STREETS")
        ):
            _ov.set_fetch_ready("roads")
        if (
            tp3d.el_oActive == 1
            and map_km <= const.COASTLINE_MAXSIZE
            and _all_prefetched.get("COASTLINE")
        ):
            _ov.set_fetch_ready("water")

    terrain: dict[str, Any] = {}
    terrain["_osm_polygons"] = {}  # populated only in CREATE_TEXTURE mode
    _water_result = None  # raw coloring_main() result for 'water' -- replayed below if ocean finds nothing
    for key, flag_attr, max_size, phase, msg in COLORING_ELEMENTS:
        terrain[key] = None
        if flag_attr(tp3d) if callable(flag_attr) else getattr(tp3d, flag_attr) == 1:
            if map_km <= max_size:
                _advance_elem_progress(phase, msg)
                _result = coloring_main(
                    gen,
                    key.upper(),
                    prefetched_tiles=_all_prefetched.get(key.upper(), {}),
                )
                if key == "water":
                    _water_result = _result
                if _result is _COLORING_EMPTY:
                    terrain[key] = None
                    _ov.set_fetch_empty(key)
                elif _result is _COLORING_FILTERED:
                    terrain[key] = None
                    _ov.set_fetch_filtered(key)
                elif _result is _COLORING_PAINTED:
                    terrain[key] = None  # object was deleted after painting
                    _ov.set_fetch_done(key, success=True)
                elif isinstance(_result, _ColoringTextureResult):
                    terrain["_osm_polygons"][_result.kind] = _result.polygon
                    terrain[key] = None
                    _ov.set_fetch_done(key, success=True)
                elif _result is None:
                    terrain[key] = None
                    _ov.set_fetch_done(key, success=False)
                else:
                    terrain[key] = _result
                    _ov.set_fetch_done(key, success=True)
                if key == "water" and _water_ocean_combined:
                    # Ocean will complete this chip; hold at 50%
                    _ov.set_fetch_progress("water", 0.5)
            else:
                print(
                    f"INFO: MAP IS TOO BIG FOR {key.upper()} (< {max_size} km required)"
                )
                _progress.WarningsOverlay.add_warning(
                    f"Map too big for {phase} layer.", "warn"
                )

    # --------------------------------------------------
    # Ocean — unique creation logic.
    # --------------------------------------------------
    terrain["ocean"] = None
    if tp3d.el_oActive == 1:
        if map_km <= const.COASTLINE_MAXSIZE:
            _advance_elem_progress("Ocean", "Creating ocean…")
            _ov.set_fetch_progress("water", 0.5 if _water_feat_active else 0.0)
            print("Create Ocean")
            _coastline_tiles = _all_prefetched.get("COASTLINE", {})
            terrain["ocean"] = createOcean(_coastline_tiles, scaleHor, obj)
            if isinstance(terrain["ocean"], _ColoringTextureResult):
                terrain["_osm_polygons"][terrain["ocean"].kind] = terrain[
                    "ocean"
                ].polygon
                terrain["ocean"] = None
                _ov.set_fetch_done("water", success=True)
            elif terrain["ocean"] is not None:
                _ov.set_fetch_done("water", success=True)
            elif _water_ocean_combined:
                # No coastline nearby (or it failed to build) -- that's normal for
                # an inland map, not a failure. Fall back to the water-features
                # chip's own result instead of marking the combined chip red just
                # because there's no ocean in this area.
                if _water_result is _COLORING_EMPTY:
                    _ov.set_fetch_empty("water")
                elif _water_result is _COLORING_FILTERED:
                    _ov.set_fetch_filtered("water")
                else:
                    _ov.set_fetch_done("water", success=_water_result is not None)
            else:
                _ov.set_fetch_done("water", success=False)
        else:
            print(
                f"INFO: MAP IS TOO BIG FOR COASTLINE (< {const.COASTLINE_MAXSIZE}km required)"
            )
            _progress.WarningsOverlay.add_warning(
                "Map too big for Ocean/Coastline layer.", "warn"
            )

    print("Base elements Created")

    # --------------------------------------------------
    # Buildings — own creation function + intersection post-processing.
    # --------------------------------------------------
    terrain["buildings"] = None
    if tp3d.el_bActive == 1:
        if map_km <= const.BUILDINGS_MAXSIZE:
            _advance_elem_progress("Buildings", "Fetching building data…")
            _ov.set_fetch_progress("buildings", 0.0)
            _ov.set_fetch_ready("buildings")
            buildings = create_buildings(gen, 10, gen.sScaleHor or 1)

            if buildings is not None:
                # Buildings are already clipped to the map shape in 2D inside
                # create_buildings, so no 3D boolean clip is needed here.
                set_origin_to_3d_cursor(buildings)
                buildings.name = obj.name + "_" + "BUILDINGS"
                terrain["buildings"] = buildings
                writeMetadata(buildings, type="BUILDINGS")
            _ov.set_fetch_done("buildings", success=buildings is not None)
        else:
            print("INFO: MAP IS TOO BIG FOR BUILDINGS (< 10Km Map size Required)")
            _progress.WarningsOverlay.add_warning("Map too big for Buildings.", "warn")

    # --------------------------------------------------
    # Roads — own creation function + clipping + material post-processing.
    # --------------------------------------------------
    terrain["roads"] = None
    if any(
        [
            tp3d.el_sBigActive,
            tp3d.el_sMedActive,
            tp3d.el_sSmallActive,
            tp3d.el_sServiceActive,
            tp3d.el_sFootwaysActive,
        ]
    ):
        if map_km <= const.ROADS_MAXSIZE:
            _advance_elem_progress("Roads", "Fetching road data…")
            _ov.set_fetch_progress("roads", 0.0)
            _ov.set_fetch_ready("roads")
            if gen.sScaleHor is None:
                raise GenerationError("ScaleHor not Set")
            # PAINT mode: roads is fused visually onto a single-piece terrain,
            # never printed standalone -- a thin raised strip is fine. Every
            # other mode (SEPARATE / SINGLECOLORMODE*) needs roads to stand on
            # its own as a base-to-top piece, like the coloring elements and
            # the SCM trail groove insert, so it can be printed/assembled
            # separately instead of being a sliver with nothing to sit on.
            result = create_roads(
                gen,
                gen.el_sHeight,
                gen.sScaleHor,
            )
            if result is not None:
                roads, roads_polygon = result
                # Cache the terrain's own triangulated grid + the road footprint
                # NOW, while terrain is still pristine (no boolean cuts yet) --
                # finalize_roads() (called later, after roads is used as the
                # cheap boolean cutter) needs the original height data under
                # the road footprint, which a cut would otherwise destroy.
                from .mesh_ops import recalculateNormals as _rg_recalc_normals
                from .osm.roads import (
                    _triangulated_terrain_faces,
                    compute_full_depth_bottom_z,
                )

                _rg_recalc_normals(obj)
                terrain["roads_polygon"] = roads_polygon
                terrain["_terrain_tris_cache"] = _triangulated_terrain_faces(obj)
                global _puzzle_roads_data
                _puzzle_roads_data = (
                    roads_polygon,
                    terrain["_terrain_tris_cache"],
                    gen.el_sHeight,
                )
                terrain["roads_bottom_z"] = None
                if (
                    tp3d.elementMode not in ("PAINT", "CREATE_TEXTURE")
                    and roads_polygon is not None
                ):
                    terrain["roads_bottom_z"] = compute_full_depth_bottom_z(
                        terrain["_terrain_tris_cache"], roads_polygon, gen.el_sHeight
                    )
                if (
                    tp3d.elementMode == "CREATE_TEXTURE"
                    and roads_polygon is not None
                    and tp3d.tex_include_roads
                ):
                    terrain["_osm_polygons"]["ROADS"] = roads_polygon
                if tp3d.elementMode == "CREATE_TEXTURE" and tp3d.tex_include_roads:
                    # tex_include_roads on — polygon stored above; discard the mesh.
                    bpy.data.objects.remove(roads, do_unlink=True)
                    roads = None
                # tex_include_roads off — fall through so roads is stored as a PAINT-style overlay
                if roads is not None:
                    set_origin_to_3d_cursor(roads)
                    roads.data.materials.clear()
                    roads.data.materials.append(bpy.data.materials.get("BLACK"))
                    terrain["roads"] = roads
                    roads.name = obj.name + "_" + "ROADS"
                    writeMetadata(roads, type="ROADS")
                _ov.set_fetch_done("roads", success=True)
            else:
                print("INFO: No road data returned, skipping road processing.")
                _progress.WarningsOverlay.add_warning("No road data returned.", "warn")
                _ov.set_fetch_done("roads", success=False)
        else:
            print("INFO: MAP IS TOO BIG FOR STREETS (< 100Km Map size Required)")
            _progress.WarningsOverlay.add_warning("Map too big for Roads.", "warn")

    gen.elements = terrain

    return terrain


def _rg_apply_single_color_mode(gen: GenerationContext):
    """Apply single-color-mode boolean projection between terrain layers and curves.

    Terrain elements are processed in priority order: each element subtracts
    thicker versions of all higher-priority elements that were already processed.
    To add a new terrain layer, append its key to TERRAIN_PRIORITY_ORDER and make
    sure it is populated in the terrain dict passed by the caller.
    """
    from . import geometry2d as _g2d
    from .mesh_ops import (  # deferred to avoid circular import at load time
        boolean_operation,
        is_mesh_manifold,
        recalculateNormals,
        selectBottomFaces,
        single_color_mode_curve,
        single_color_mode_mesh_remesh,
        single_color_mode_mesh_wireframe,
    )
    from .scene import remove_objects  # deferred to avoid circular import at load time

    # Priority order: index 0 = highest priority (subtracted from everything below it).
    # Add new terrain keys here to include them automatically.
    TERRAIN_PRIORITY_ORDER = [
        "water",
        "forest",
        "scree",
        "city",
        "greenspace",
        "farmland",
        "glacier",
        "ocean",
    ]

    _effective_scm_trail = gen.singleColorMode or gen.elementMode in (
        "SINGLECOLORMODE",
        "SINGLECOLORMODE_REMESH",
    )
    obj = gen.mapObject
    terrain = gen.elements
    assert terrain is not None
    thickerCurves = []
    trail_thick_ribbons = []
    if _effective_scm_trail and gen.curveObjs:
        dpt = 1
        dup = obj.copy()
        dup.data = obj.data.copy()
        dup.name = f"{obj.name}_dup_for_projection"
        if obj.users_collection:
            for coll in obj.users_collection:
                coll.objects.link(dup)
        survivingCurveObjs = []
        for tcrv in gen.curveObjs:
            result = single_color_mode_curve(tcrv, obj, True, dpt, dup)
            if result is not None:
                if result[1] is not None:
                    survivingCurveObjs.append(result[0])
                    thickerCurves.append(result[1])
                if result[2] is not None and not result[2].is_empty:
                    trail_thick_ribbons.append(result[2])
        remove_objects(dup)
        for tcrv in thickerCurves:
            bpy.ops.object.select_all(action="DESELECT")
            tcrv.select_set(True)
            bpy.context.view_layer.objects.active = tcrv
        for i in range(len(thickerCurves)):
            recalculateNormals(thickerCurves[i])
            thickerCurves[i].location.z -= 0.001
            for j in range(i + 1, len(survivingCurveObjs)):
                recalculateNormals(survivingCurveObjs[j])
                boolean_operation(survivingCurveObjs[j], thickerCurves[i])

    else:
        # PAINT mode: original _Trail curve objects are still in the scene; derive
        # their 2D ribbon footprints to subtract from roads_polygon before finalize_roads.
        _tol = bpy.context.scene.tp3d.tolerance
        _pt = bpy.context.scene.tp3d.pathThickness

        def _tile_extents(o):
            cs = [o.matrix_world @ Vector(c) for c in o.bound_box]
            return (
                min(c.x for c in cs),
                max(c.x for c in cs),
                min(c.y for c in cs),
                max(c.y for c in cs),
            )

        tx0, tx1, ty0, ty1 = _tile_extents(obj)
        for _ob in bpy.context.view_layer.objects:
            if _ob is None or "_Trail" not in _ob.name or _ob.type != "CURVE":
                continue
            cx0, cx1, cy0, cy1 = _tile_extents(_ob)
            if cx0 > tx1 or cx1 < tx0 or cy0 > ty1 or cy1 < ty0:
                continue
            _mw = _ob.matrix_world
            _coords = []
            for _sp in _ob.data.splines:
                _pts = _sp.points if len(_sp.points) > 0 else _sp.bezier_points
                if len(_pts) >= 2:
                    _coords.append(
                        [(_mw @ Vector((_p.co.x, _p.co.y, _p.co.z)))[:2] for _p in _pts]
                    )
            if not _coords:
                continue
            _r = _g2d.polylines_to_ribbon(_coords, _pt / 2 + _tol, quad_segs=4)
            if _r and not _r.is_empty:
                trail_thick_ribbons.append(_r)

    # In CREATE_TEXTURE mode, store trail ribbon union for texture rasterisation.
    if (
        gen.elementMode == "CREATE_TEXTURE"
        and bpy.context.scene.tp3d.tex_include_trail
        and trail_thick_ribbons
    ):
        osm_polygons: dict[str, Any] = terrain.get("_osm_polygons")
        osm_polygons["TRAIL"] = _g2d.union(trail_thick_ribbons)

    # TODO: clean this out when separate mode is gone
    if gen.elementMode == "SEPARATE" and False:  # noqa: SIM223
        for i, key in enumerate(TERRAIN_PRIORITY_ORDER):
            elem_obj = terrain.get(key)

            if not elem_obj:
                continue
            _ov = _progress.ProgressOverlay.get()
            if _ov.active:
                _ov.update(message=f"Processing {key.capitalize()}…")

            recalculateNormals(elem_obj)

            selectBottomFaces(elem_obj)
            bpy.ops.mesh.select_more()
            bpy.ops.mesh.delete(type="FACE")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.extrude_region_move(
                TRANSFORM_OT_translate={"value": (0, 0, -1)}
            )
            bpy.ops.object.mode_set(mode="OBJECT")

            if _effective_scm_trail:
                for tcrv in gen.curveObjs:
                    boolean_operation(elem_obj, tcrv)

    if gen.elementMode in ("SINGLECOLORMODE", "SINGLECOLORMODE_REMESH"):
        _ov = _progress.ProgressOverlay.get()
        if _ov.active:
            _ov.update(message="Applying Single-color Mode…")
        # Maps key -> thicker mesh object, filled as each element is processed.
        thicker_by_key = {}

        _scm_fn = (
            single_color_mode_mesh_remesh
            if gen.elementMode == "SINGLECOLORMODE_REMESH"
            else single_color_mode_mesh_wireframe
        )

        _active_scm_keys = [k for k in TERRAIN_PRIORITY_ORDER if terrain.get(k)]
        _n_scm = max(1, len(_active_scm_keys))
        _scm_done = 0

        for i, key in enumerate(TERRAIN_PRIORITY_ORDER):
            elem_obj = terrain.get(key)
            if not elem_obj:
                continue
            _ov = _progress.ProgressOverlay.get()
            if _ov.active:
                _ov.update(
                    percent=0.95 + 0.02 * (_scm_done / _n_scm),
                    message=f"Single-color: remeshing {key.capitalize()} ({_scm_done + 1}/{_n_scm})…",
                )

            thicker = _scm_fn(elem_obj, obj)
            thicker_by_key[key] = thicker

            if _ov.active:
                _ov.update(
                    percent=0.95 + 0.02 * ((_scm_done + 0.5) / _n_scm),
                    message=f"Single-color: subtracting from {key.capitalize()}…",
                )

            # Subtract all curve thicker-bodies
            for tcrv in thickerCurves:
                boolean_operation(elem_obj, tcrv)

            # Subtract every higher-priority element that was already processed
            for prev_key in TERRAIN_PRIORITY_ORDER[:i]:
                if prev_key in thicker_by_key:
                    boolean_operation(elem_obj, thicker_by_key[prev_key])

            _scm_done += 1

        if bpy.app.debug:
            obj_size = gen.size
            for thicker in thicker_by_key.values():
                thicker.location.x += obj_size
        else:
            for thicker in thicker_by_key.values():
                remove_objects(thicker)

    if gen.elementMode == "SEPARATE" and thickerCurves:
        for key in TERRAIN_PRIORITY_ORDER:
            elem_obj = terrain.get(key)
            if not elem_obj:
                continue
            _ov = _progress.ProgressOverlay.get()
            if _ov.active:
                _ov.update(message=f"Cutting trail from {key.capitalize()}…")
            for tcrv in thickerCurves:
                boolean_operation(elem_obj, tcrv)

    # Cut roads out of every finalized terrain element (element = element -
    # road), so a road crossing water/forest/city/etc. leaves a continuous
    # raised strip with the element notched around it instead of the two
    # objects silently overlapping. Only meaningful once elements exist as
    # real separate solids (SEPARATE / SINGLECOLORMODE / SINGLECOLORMODE_
    # REMESH) -- in PAINT mode elements are baked as terrain face materials,
    # there's no separate mesh to cut. Buildings are intentionally excluded
    # -- they sit on top of both terrain and elements untouched. This must
    # run AFTER every element's own cross-element cuts above are finished,
    # and BEFORE the trail-groove step below, which stays the true last
    # boolean of the whole pipeline.
    roads_obj = terrain.get("roads")
    if roads_obj is not None and gen.elementMode in (
        "SEPARATE",
        "SINGLECOLORMODE",
        "SINGLECOLORMODE_REMESH",
    ):
        # MANIFOLD requires BOTH operands to be watertight -- roads is the
        # known carrier of a small residual non-manifold defect (see osm.py's
        # create_roads notes), so it must be checked here too, not just the
        # element being cut. Checking only elem_obj (as an earlier version of
        # this fix did) let the solver stay MANIFOLD and silently no-op on
        # every single cut whenever roads itself was the non-manifold side.
        roads_manifold = is_mesh_manifold(
            roads_obj
        )  # For the boolean cuts, build a cutter from the Shapely road polygon
        # (optionally buffered outward by el_sCutTolerance for a clean,
        # uniform XY expansion -- vertex-normal dilation is unreliable on
        # slab geometry with walls), extruded only from this road's own
        # flush-bottom depth (see compute_full_depth_bottom_z) up past the
        # terrain top. Falling back to raw roads_obj here would cut all the
        # way down to the map floor, leaving no matching recess for the
        # element to actually sit flush in -- always build the properly
        # bounded cutter instead, regardless of the tolerance setting.
        cut_tolerance = bpy.context.scene.tp3d.el_sCutTolerance
        roads_cutter = roads_obj
        _cutter_tmp = None
        _road_poly = terrain.get("roads_polygon")
        _roads_bz = terrain.get("roads_bottom_z")
        if _road_poly is not None and not _road_poly.is_empty and _roads_bz is not None:
            from .osm.roads import _build_extruded_mesh

            _buffered = (
                _road_poly.buffer(cut_tolerance, join_style="mitre")
                if cut_tolerance > 0
                else _road_poly
            )
            if _buffered and not _buffered.is_empty:
                _all_v2d, _all_tris = [], []
                for _part in _g2d.iter_polygons(_buffered):
                    _part = _g2d.orient(_part)
                    _ext = list(_part.exterior.coords)[:-1]
                    _holes = [
                        list(r.coords)[:-1]
                        for r in _part.interiors
                        if len(r.coords) >= 4
                    ]
                    _ec = _g2d._cdt_triangulate(_part, _ext, _holes)
                    if _ec:
                        _v2, _t2 = _ec
                        _base = len(_all_v2d)
                        _all_v2d.extend(_v2)
                        _all_tris += [
                            (a + _base, b + _base, c + _base) for a, b, c in _t2
                        ]
                if _all_v2d and _all_tris:
                    _mc = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
                    # Small safety margin below the road's own flush depth, purely
                    # to guarantee boolean overlap -- not a return to map-floor depth.
                    _bz = _roads_bz - 0.05
                    _tz = max(v.z for v in _mc) + 20.0
                    _cutter_tmp = _build_extruded_mesh(_all_v2d, _all_tris, _bz, _tz)
                    recalculateNormals(_cutter_tmp)
                    roads_cutter = _cutter_tmp

        # Cut roads out of the main terrain object too, not just the
        # coloring elements -- otherwise the terrain piece and the roads
        # piece occupy the same 3D space wherever a road runs, leaving no
        # matching recess for the roads piece to sit in when assembled.
        _ov = _progress.ProgressOverlay.get()
        if _ov.active:
            _ov.update(message="Cutting road from Terrain…")
        solver = "MANIFOLD" if (roads_manifold and is_mesh_manifold(obj)) else "EXACT"
        boolean_operation(obj, roads_cutter, solver=solver)

        for key in TERRAIN_PRIORITY_ORDER:
            elem_obj = terrain.get(key)
            if not elem_obj:
                continue
            _ov = _progress.ProgressOverlay.get()
            if _ov.active:
                _ov.update(message=f"Cutting road from {key.capitalize()}…")
            solver = (
                "MANIFOLD"
                if (roads_manifold and is_mesh_manifold(elem_obj))
                else "EXACT"
            )
            boolean_operation(elem_obj, roads_cutter, solver=solver)

        if _cutter_tmp is not None:
            remove_objects(_cutter_tmp)

    # Subtract the trail groove from buildings so it isn't blocked by 3D geometry.
    # Roads are handled separately AFTER finalize_roads (which rebuilds roads.data
    # from terrain cache -- any cut made here would be overwritten).
    if thickerCurves:
        elem_obj = terrain.get("buildings")
        if elem_obj is not None:
            _ov = _progress.ProgressOverlay.get()
            if _ov.active:
                _ov.update(message="Subtracting trail from Buildings…")
            for tcrv in thickerCurves:
                solver = (
                    "MANIFOLD"
                    if (is_mesh_manifold(elem_obj) and is_mesh_manifold(tcrv))
                    else "EXACT"
                )
                boolean_operation(elem_obj, tcrv, solver=solver)

    # Rebuild the road top surface from the terrain-grid cache captured before
    # any of the cuts above, so it shares the exact terrain/element resolution.
    roads_obj = gen.roadObj
    if roads_obj is not None:
        _ov = _progress.ProgressOverlay.get()
        if _ov.active:
            _ov.update(message="Roads: adding terrain detail…")
        from .osm.roads import finalize_roads  # deferred — only needed here

        el_sHeight = gen.el_sHeight
        full_depth = gen.elementMode not in ("PAINT", "CREATE_TEXTURE")
        # Subtract the trail 2D footprint from roads_polygon before finalize_roads
        # builds the mesh -- avoids a post-build 3D boolean on a non-manifold mesh.
        _roads_poly = gen.roadUnion
        if trail_thick_ribbons and _roads_poly is not None:
            _trail_union = _g2d.union(trail_thick_ribbons)
            _roads_poly = _roads_poly.difference(_trail_union)
            print(
                f"[TP3D roads] subtracted {len(trail_thick_ribbons)} trail ribbon(s) from roads_polygon in 2D"
            )
        print(f"Full depth value before finallizing roads: {full_depth}")
        finalize_roads(
            roads_obj,
            terrain.get("_terrain_tris_cache"),
            _roads_poly,
            el_sHeight,
            full_depth,
            map_polygon=_g2d.get_map_polygon(obj),
        )

        # Repair non-manifold boundary edges left by the terrain-grid clip and
        # trail subtraction: select boundaries → limited dissolve → merge by
        # distance → fill holes.  The four remaining "multiple face" issues are
        # structural and ignored here.
        bpy.ops.object.select_all(action="DESELECT")
        roads_obj.select_set(True)
        bpy.context.view_layer.objects.active = roads_obj
        bpy.ops.object.mode_set(mode="EDIT")
        # select_non_manifold's poll() requires vertex or edge select mode --
        # fails silently as a Report: Error if mode was left on face-select
        # (e.g. by a prior operator) instead of raising an exception.
        bpy.context.tool_settings.mesh_select_mode = (True, False, False)
        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.mesh.select_non_manifold(
            extend=False,
            use_wire=False,
            use_boundary=True,
            use_multi_face=False,
            use_non_contiguous=False,
            use_verts=False,
        )
        bpy.ops.mesh.dissolve_limited(angle_limit=0.0872665)  # 5°
        bpy.ops.mesh.remove_doubles(threshold=0.001)
        bpy.ops.mesh.select_non_manifold(
            extend=False,
            use_wire=False,
            use_boundary=True,
            use_multi_face=False,
            use_non_contiguous=False,
            use_verts=False,
        )
        bpy.ops.mesh.fill_holes(sides=0)
        bpy.ops.object.mode_set(mode="OBJECT")

    if thickerCurves:
        if bpy.app.debug:
            obj_size = gen.size
            for tcrv in thickerCurves:
                tcrv.location.x += obj_size
        else:
            remove_objects(thickerCurves)


def _rg_apply_texture(gen: GenerationContext):
    from .mesh_ops import (  # deferred to avoid circular import at load time
        merge_with_map,
    )
    from .scene import (  # deferred to avoid circular import at load time
        remove_objects,
    )
    from .texture import setup_paint_texture

    elements: dict[str, Any] = gen.elements
    _mmu_palette = setup_paint_texture(gen)
    elements["_mmu_palette"] = _mmu_palette
    # When SCM trail is on, curveObjs hold the converted trail-strip meshes
    # (single_color_mode_curve converts in-place); keep them as 3D geometry.
    # When tex_include_trail is off, keep curveObjs as PAINT-style overlay objects.
    _tex_trail = bpy.context.scene.tp3d.tex_include_trail
    if gen.curveObjs and not gen.singleColorMode and _tex_trail:
        for tcrv in list(gen.curveObjs):
            if tcrv and tcrv.name in bpy.data.objects:
                bpy.data.objects.remove(tcrv, do_unlink=True)
        gen.curveObjs.clear()

    if gen.curveObjs and type == 20:
        for i, crv in enumerate(gen.curveObjs):
            tmp: Object = merge_with_map(gen.mapObject, crv)
            remove_objects(crv)
            gen.curveObjs[i] = tmp
    # --- Phase 15c: Tag companion objects with solid-colour paint textures ---
    # Without this the Orca exporter sees no paint data on these objects and
    # the slicer defaults them to extruder 1 regardless of material colour.
    if gen.elementMode == "CREATE_TEXTURE":
        _mmu_palette = gen.elements.get("_mmu_palette")
        if _mmu_palette:
            from .texture import (
                _ROADS_SRGB,
                _WHITE_SRGB,
                tag_solid_color_for_paint_export,
            )

            for _cobj, _ccol in [
                (gen.textObj, _WHITE_SRGB),
                (gen.plateObj, _ROADS_SRGB),
                (gen.shellObj, _ROADS_SRGB),
            ]:
                tag_solid_color_for_paint_export(_cobj, _ccol, _mmu_palette)


def _rg_assign_materials(gen: GenerationContext):
    """Write metadata and assign materials to all generated objects."""
    from .metadata import (
        writeMetadata,  # deferred to avoid circular import at load time
    )

    obj = gen.mapObject
    curveObjs = gen.curveObjs
    textobj = gen.textObj
    plateobj = gen.plateObj
    shellobj = gen.shellObj
    shape = gen.shape

    bpy.ops.object.select_all(action="DESELECT")

    writeMetadata(obj, "MAP")
    if curveObjs:
        for tcrv in curveObjs:
            try:
                if tcrv and tcrv.name in bpy.data.objects:
                    writeMetadata(tcrv, "TRAIL")
            except ReferenceError:
                pass

    if curveObjs:
        mats = "TRAIL"
        for tcrv in curveObjs:
            try:
                if tcrv and tcrv.name in bpy.data.objects:
                    mat = bpy.data.materials.get(mats)
                    tcrv.data.materials.clear()
                    tcrv.data.materials.append(mat)
                    mats = "YELLOW" if mats == "TRAIL" else "TRAIL"
            except ReferenceError:
                pass

    if (
        shape
        in {
            "HEXAGON INNER TEXT",
            "HEXAGON OUTER TEXT",
            "OCTAGON OUTER TEXT",
            "HEXAGON FRONT TEXT",
            "CIRCLE OUTER TEXT",
        }
        and textobj
    ):
        mat_name = "TRAIL" if shape == "HEXAGON INNER TEXT" else "WHITE"
        mat = bpy.data.materials.get(mat_name)
        textobj.data.materials.clear()
        textobj.data.materials.append(mat)
        writeMetadata(textobj, type="TEXT")

    if (
        shape
        in {
            "HEXAGON OUTER TEXT",
            "OCTAGON OUTER TEXT",
            "HEXAGON FRONT TEXT",
            "CIRCLE OUTER TEXT",
        }
        and plateobj
    ):
        mat = bpy.data.materials.get("BLACK")
        plateobj.data.materials.clear()
        plateobj.data.materials.append(mat)
        writeMetadata(plateobj, type="PLATE")

    if shellobj:
        mat = bpy.data.materials.get("BLACK")
        shellobj.data.materials.clear()
        if mat:
            shellobj.data.materials.append(mat)
        writeMetadata(shellobj, type="SHELL")


def _rg_export(gen: GenerationContext):
    """Export all geometry, update API counters, and zoom camera."""
    from ..export import (  # deferred to avoid circular import at load time
        export_selected_to_3mf,
        export_to_STL,
        is_3mf_extension_installed,
    )
    from .elevation import (
        load_counter,  # deferred to avoid circular import at load time
    )
    from .scene import (
        zoom_camera_to_selected,  # deferred to avoid circular import at load time
    )

    shape = gen.shape
    elements = gen.elements
    curveObjs = gen.curveObjs
    textobj = gen.textObj
    shellobj = gen.shellObj
    plateobj = gen.plateObj
    exportformat = gen.exportFormat

    # PAINT mode bakes terrain-element colors as per-face materials on a single
    # mesh; STL cannot store material data at all, so PAINT-mode maps must be
    # exported as OBJ to keep the colors. Mirrors the equivalent computation in
    # terrain.coloring_main().
    # CREATE_TEXTURE: 3MF is the primary export; STL serves as no-addon fallback.
    if gen.elementMode == "PAINT":
        exportformat = "OBJ"
    elif gen.elementMode == "CREATE_TEXTURE":
        exportformat = "STL"  # fallback only; 3MF addon handles the real export
    else:
        exportformat = "STL"

    if gen.autoExport:
        print("Auto export disabled, skipping export")
        return

    if is_3mf_extension_installed() and not gen.autoExport:
        print("Exporting to 3mf")
        if gen.curveObjs and (gen.elementMode != "CREATE_TEXTURE" or not gen.texTrail):
            for tcrv in curveObjs:
                try:
                    if tcrv and tcrv.name in bpy.data.objects:
                        tcrv.select_set(True)
                except ReferenceError:
                    pass
        gen.mapObject.select_set(True)

        if elements and (
            gen.elementMode == "SEPARATE" or "SINGLECOLORMODE" in gen.elementMode
        ):
            for elem_obj in elements.values():
                if (
                    elem_obj
                    and isinstance(elem_obj, bpy.types.Object)
                    and elem_obj.name in bpy.data.objects
                ):
                    elem_obj.select_set(True)
        elif elements and gen.elementMode in ("PAINT", "CREATE_TEXTURE"):
            for key in ("roads", "buildings"):
                elem_obj = elements.get(key)
                if elem_obj and elem_obj.name in bpy.data.objects:
                    elem_obj.select_set(True)

        if (
            shape
            in {
                "HEXAGON INNER TEXT",
                "HEXAGON OUTER TEXT",
                "OCTAGON OUTER TEXT",
                "HEXAGON FRONT TEXT",
                "CIRCLE OUTER TEXT",
            }
            and textobj
        ):
            textobj.select_set(True)

        if (
            shape
            in {
                "HEXAGON OUTER TEXT",
                "OCTAGON OUTER TEXT",
                "HEXAGON FRONT TEXT",
                "CIRCLE OUTER TEXT",
            }
            and plateobj
        ):
            plateobj.select_set(True)

        if shellobj:
            shellobj.select_set(True)

        export_selected_to_3mf(is_auto=True)
    else:
        print("exporting as STL/OBJ")
        if curveObjs and (gen.elementMode != "CREATE_TEXTURE" or not gen.texTrail):
            for tcrv in curveObjs:
                export_to_STL(tcrv, exportformat)
        export_to_STL(gen.mapObject, exportformat)

        if elements and (
            gen.elementMode == "SEPARATE" or "SINGLECOLORMODE" in gen.elementMode
        ):
            for elem_obj in elements.values():
                if (
                    elem_obj
                    and isinstance(elem_obj, bpy.types.Object)
                    and elem_obj.name in bpy.data.objects
                ):
                    export_to_STL(elem_obj, exportformat)

        if (
            shape
            in {
                "HEXAGON INNER TEXT",
                "HEXAGON OUTER TEXT",
                "OCTAGON OUTER TEXT",
                "HEXAGON FRONT TEXT",
                "CIRCLE OUTER TEXT",
            }
            and textobj
        ):
            export_to_STL(textobj, exportformat)

        if (
            shape
            in {
                "HEXAGON OUTER TEXT",
                "OCTAGON OUTER TEXT",
                "HEXAGON FRONT TEXT",
                "CIRCLE OUTER TEXT",
            }
            and plateobj
        ):
            export_to_STL(plateobj, exportformat)

        if shellobj:
            export_to_STL(shellobj, exportformat)

    count_openTopoData, _dt1, count_openElevation, _dt2 = load_counter()
    tp3d = bpy.context.scene.tp3d
    tp3d["o_apiCounter_OpenTopoData"] = (
        f"API Limit: {count_openTopoData:.0f}/1000 daily"
        if count_openTopoData < 1000
        else f"API Limit: {count_openTopoData:.0f}/1000 (daily limit reached. might cause problems)"
    )
    tp3d["o_apiCounter_OpenElevation"] = (
        f"API Limit: {count_openElevation:.0f}/1000 Monthly"
        if count_openElevation < 1000
        else f"API Limit: {count_openElevation:.0f}/1000 (Monthly limit reached. might cause problems)"
    )

    if gen.buggyData != 0:
        _progress.WarningsOverlay.add_warning(
            "API might have faulty DATA. Maybe try diffrent Resolution or API", "warn"
        )

    zoom_camera_to_selected(gen.mapObject)


# ---------------------------------------------------------------------------
# Coloring-element definitions — used by both the OSM prefetch helper and the
# main terrain-element builder.  Tuple layout:
#   (result_key, active_flag_attr, max_size_const, phase_label, fetch_message)
# ---------------------------------------------------------------------------
COLORING_ELEMENTS = [
    (
        "forest",
        "col_fActive",
        const.FOREST_MAXSIZE,
        "Forest",
        "Fetching forest data\u2026",
    ),
    (
        "water",
        lambda t: (
            t.col_wPondsActive or t.col_wSmallRiversActive or t.col_wBigRiversActive
        ),
        const.WATER_MAXSIZE,
        "Water",
        "Fetching water data\u2026",
    ),
    (
        "scree",
        "col_scrActive",
        const.SCREE_MAXSIZE,
        "Scree",
        "Fetching scree data\u2026",
    ),
    ("city", "col_cActive", const.CITY_MAXSIZE, "City", "Fetching city data\u2026"),
    (
        "greenspace",
        "col_grActive",
        const.GREENSPACE_MAXSIZE,
        "Greenspace",
        "Fetching greenspace data\u2026",
    ),
    (
        "farmland",
        "col_faActive",
        const.FARMLAND_MAXSIZE,
        "Farmland",
        "Fetching farmland data\u2026",
    ),
    (
        "glacier",
        "col_glActive",
        const.GLACIER_MAXSIZE,
        "Glacier",
        "Fetching glacier data\u2026",
    ),
]

# ---------------------------------------------------------------------------
# Generation feature flags
# Each type integer maps to a frozenset of capability strings used throughout
# the pipeline instead of scattered `if type == X` comparisons.
# ---------------------------------------------------------------------------

_GEN_FLAGS = {
    0: frozenset({"gpx_file", "trail", "stats", "gpx_scale"}),
    1: frozenset(
        {
            "gpx_chain",
            "trail",
            "stats",
            "gpx_scale",
            "separate_paths",
            "chain_coords_center",
        }
    ),
    2: frozenset({"jmap"}),
    3: frozenset({"jmap_bbox"}),
    4: frozenset({"gpx_file", "jmap", "trail", "trail_map"}),
    10: frozenset({"gpx_file", "stats", "gpx_scale"}),
    11: frozenset(
        {"gpx_chain", "stats", "gpx_scale", "separate_paths", "chain_coords_center"}
    ),
    20: frozenset({"gpx_file", "trail", "stats", "gpx_scale", "append_collection"}),
    21: frozenset(
        {
            "gpx_chain",
            "trail",
            "stats",
            "gpx_scale",
            "separate_paths",
            "chain_coords_center",
            "append_collection",
        }
    ),
}

# ---------------------------------------------------------------------------
# Shared helper: build the fetch-item list for the progress chip strip
# ---------------------------------------------------------------------------


def build_fetch_items(map_km=None):
    """Return the list of fetch-item dicts for the active scene settings."""
    tp3d = bpy.context.scene.tp3d
    if map_km is None:
        map_km = round(tp3d.get("sMapInKm", 0), 1)
    items = [{"key": "elevation", "icon": "E", "label": "Elevation"}]
    defs = [
        ("forest", "col_fActive", const.FOREST_MAXSIZE, "F", "Forest"),
        ("water", None, const.WATER_MAXSIZE, "W", "Water"),
        ("scree", "col_scrActive", const.SCREE_MAXSIZE, "S", "Scree"),
        ("city", "col_cActive", const.CITY_MAXSIZE, "C", "City"),
        ("greenspace", "col_grActive", const.GREENSPACE_MAXSIZE, "G", "Green"),
        ("farmland", "col_faActive", const.FARMLAND_MAXSIZE, "A", "Farm"),
        ("glacier", "col_glActive", const.GLACIER_MAXSIZE, "I", "Glacr"),
        ("buildings", "el_bActive", const.BUILDINGS_MAXSIZE, "B", "Build"),
        ("roads", None, const.ROADS_MAXSIZE, "R", "Roads"),
    ]
    for key, flag, max_size, icon, label in defs:
        if key == "water":
            water_feats = (
                tp3d.col_wPondsActive
                or tp3d.col_wSmallRiversActive
                or tp3d.col_wBigRiversActive
            ) and map_km <= const.WATER_MAXSIZE
            active = water_feats or (
                tp3d.el_oActive == 1 and map_km <= const.COASTLINE_MAXSIZE
            )
            max_size = None
        elif key == "roads":
            active = any(
                [
                    tp3d.el_sBigActive,
                    tp3d.el_sMedActive,
                    tp3d.el_sSmallActive,
                    tp3d.el_sServiceActive,
                    tp3d.el_sFootwaysActive,
                ]
            )
        else:
            active = bool(flag and getattr(tp3d, flag, 0) == 1)
        if active and (max_size is None or map_km <= max_size):
            items.append({"key": key, "icon": icon, "label": label})
    return items


# 'water' and 'roads' are each an OR of several independent sub-checkboxes
# with no single master flag on the PropertyGroup; 'elevation' has no
# toggle at all (the base terrain height is always fetched). Shared by
# build_element_toggle_states and apply_element_toggle below so the two
# stay in sync by construction rather than by convention.
_ELEMENT_SINGLE_FLAGS = {
    "forest": "col_fActive",
    "scree": "col_scrActive",
    "city": "col_cActive",
    "greenspace": "col_grActive",
    "farmland": "col_faActive",
    "glacier": "col_glActive",
    "buildings": "el_bActive",
}
_ELEMENT_COMPOSITE_FLAGS = {
    "water": (
        (
            "col_wPondsActive",
            "col_wSmallRiversActive",
            "col_wBigRiversActive",
            "el_oActive",
        ),
        "col_wPondsActive",
    ),
    "roads": (
        (
            "el_sBigActive",
            "el_sMedActive",
            "el_sSmallActive",
            "el_sServiceActive",
            "el_sFootwaysActive",
        ),
        "el_sSmallActive",
    ),
}


def build_element_toggle_states(tp3d=None):
    """Which of the 10 progress-icon element categories are currently
    toggled on in the scene settings, keyed the same as build_fetch_items /
    progress_win._ICON_MAP.

    Unlike build_fetch_items, this ignores per-category map-size cutoffs
    (const.FOREST_MAXSIZE etc.) -- those only matter once a map_km is known,
    but this is read by the picker pages *before* an area has been drawn, to
    show which elements the current settings would include.
    """
    if tp3d is None:
        tp3d = bpy.context.scene.tp3d
    states = {"elevation": True}
    for key, attr in _ELEMENT_SINGLE_FLAGS.items():
        states[key] = bool(getattr(tp3d, attr))
    for key, (subflags, _) in _ELEMENT_COMPOSITE_FLAGS.items():
        states[key] = any(getattr(tp3d, f) for f in subflags)
    return states


def apply_element_toggle(tp3d, key):
    """Flip one element category's enabled state -- applied on Blender's
    main thread from a picker page's element-status chip click (queued by
    picker_server.py's /toggle_element, drained via drain_pending_toggles
    from the calling operator's modal() timer tick; the HTTP server itself
    runs on a background thread and can't safely touch scene data).

    'elevation' has no toggle and is ignored. For the single-flag
    categories this just inverts the one BoolProperty. For the two
    composites (water, roads), toggling OFF remembers the exact sub-flag
    combination in a scene custom property before zeroing them, and
    toggling back ON restores that same combination -- so a mix fine-tuned
    in the N-panel (e.g. only Small Roads) survives a quick off/on from the
    picker instead of resetting to some fixed default. First-ever
    toggle-ON with nothing remembered (and nothing already set) falls back
    to enabling just the category's single most common sub-flag.
    """
    if key in _ELEMENT_SINGLE_FLAGS:
        attr = _ELEMENT_SINGLE_FLAGS[key]
        setattr(tp3d, attr, not getattr(tp3d, attr))
        return
    if key not in _ELEMENT_COMPOSITE_FLAGS:
        return  # 'elevation' or an unrecognized key -- nothing to toggle

    subflags, bootstrap = _ELEMENT_COMPOSITE_FLAGS[key]
    remember_key = f"_toggle_remember_{key}"
    if any(getattr(tp3d, f) for f in subflags):
        tp3d[remember_key] = [bool(getattr(tp3d, f)) for f in subflags]
        for f in subflags:
            setattr(tp3d, f, False)
    else:
        remembered = tp3d.get(remember_key)
        if remembered and any(remembered):
            for f, v in zip(subflags, remembered):
                setattr(tp3d, f, bool(v))
        else:
            setattr(tp3d, bootstrap, True)


# The Settings popup's Map tab -- a small, fixed whitelist of scene fields
# exposed for direct editing from the picker pages (see picker_server.py's
# /update_setting). Keyed by the same name on both sides so
# build_settings_row_state / apply_setting_update stay in sync by
# construction.
_SETTINGS_ROW_FIELDS = {
    "scaleElevation": ("scaleElevation", float),
    "fixedElevationScale": ("fixedElevationScale", bool),
    "pathThickness": ("pathThickness", float),
    "overwritePathElevation": ("overwritePathElevation", bool),
    "objSize": ("objSize", int),
    "resolution": ("num_subdivisions", int),
    "singleColorMode": ("singleColorMode", bool),
    "singleColorModeTolerance": ("tolerance", float),
}


def build_settings_row_state(tp3d=None):
    """Current values of the Settings popup's Map tab fields, for the
    picker pages' SETTINGS_STATE snapshot."""
    if tp3d is None:
        tp3d = bpy.context.scene.tp3d
    return {key: getattr(tp3d, attr) for key, (attr, _) in _SETTINGS_ROW_FIELDS.items()}


def apply_setting_update(tp3d, key, value):
    """Apply one Settings popup Map-tab field update -- applied on Blender's
    main thread from a picker page's field edit, queued by
    picker_server.py's /update_setting and drained via
    drain_pending_settings from the calling operator's modal() timer tick
    (see apply_element_toggle's docstring for why this can't happen
    directly on the HTTP server's own background thread).

    *key* is checked against the _SETTINGS_ROW_FIELDS whitelist -- silently
    ignored if unrecognized -- rather than setattr'ing whatever name the
    page sent, since the request body is client-controlled.
    """
    field = _SETTINGS_ROW_FIELDS.get(key)
    if not field:
        return
    attr, caster = field
    try:
        setattr(tp3d, attr, caster(value))
    except (TypeError, ValueError):
        pass


# The Settings popup's Elements tab -- a much larger whitelist than
# _SETTINGS_ROW_FIELDS/_ELEMENT_SINGLE_FLAGS/_ELEMENT_COMPOSITE_FLAGS,
# exposing the individual sub-checkboxes and per-category thresholds those
# only summarize as a single on/off chip. 'group' matches the
# element-status row's own category labels (informational here -- the
# actual per-card grouping/layout is driven by settings_modal.js's own
# SIMPLE_ELEMENT_FIELDS/COMPOSITE_ELEMENTS tables, keyed the same way so
# the two stay in sync by construction); 'Elevation' covers the one deeper
# option that doesn't fit the Map tab's own fixed set. Field
# labels/min/max/step for rendering live in settings_modal.js (static, so
# no need to round-trip them through Python) -- this table is only the
# key -> attr/type mapping needed to read current values and
# validate+apply incoming updates.
_ADVANCED_SETTINGS_FIELDS = [
    {
        "key": "disableElevationOutlierFix",
        "attr": "disableElevationOutlierFix",
        "type": bool,
        "group": "Elevation",
    },
    {
        "key": "colWPondsActive",
        "attr": "col_wPondsActive",
        "type": bool,
        "group": "Water",
    },
    {
        "key": "colWSmallRiversActive",
        "attr": "col_wSmallRiversActive",
        "type": bool,
        "group": "Water",
    },
    {
        "key": "colWBigRiversActive",
        "attr": "col_wBigRiversActive",
        "type": bool,
        "group": "Water",
    },
    {"key": "elOActive", "attr": "el_oActive", "type": bool, "group": "Water"},
    {"key": "colWArea", "attr": "col_wArea", "type": float, "group": "Water"},
    {
        "key": "colWStreamWidth",
        "attr": "col_wStreamWidth",
        "type": float,
        "group": "Water",
    },
    {
        "key": "elOMinIslandArea",
        "attr": "el_oMinIslandArea",
        "type": float,
        "group": "Water",
    },
    {"key": "elORdpEpsilon", "attr": "el_oRdpEpsilon", "type": float, "group": "Water"},
    {"key": "colFArea", "attr": "col_fArea", "type": float, "group": "Forest"},
    {"key": "colScrArea", "attr": "col_scrArea", "type": float, "group": "Scree"},
    {"key": "colCArea", "attr": "col_cArea", "type": float, "group": "City Boundaries"},
    {"key": "colGrArea", "attr": "col_grArea", "type": float, "group": "Greenspace"},
    {"key": "colFaArea", "attr": "col_faArea", "type": float, "group": "Farmland"},
    {"key": "colGlArea", "attr": "col_glArea", "type": float, "group": "Glacier"},
    {
        "key": "elBHeightMultiplier",
        "attr": "el_bHeightMultiplier",
        "type": float,
        "group": "Buildings",
    },
    {
        "key": "elBMinPrintMM",
        "attr": "el_bMinPrintMM",
        "type": float,
        "group": "Buildings",
    },
    {"key": "elSBigActive", "attr": "el_sBigActive", "type": bool, "group": "Roads"},
    {"key": "elSMedActive", "attr": "el_sMedActive", "type": bool, "group": "Roads"},
    {
        "key": "elSSmallActive",
        "attr": "el_sSmallActive",
        "type": bool,
        "group": "Roads",
    },
    {
        "key": "elSServiceActive",
        "attr": "el_sServiceActive",
        "type": bool,
        "group": "Roads",
    },
    {
        "key": "elSFootwaysActive",
        "attr": "el_sFootwaysActive",
        "type": bool,
        "group": "Roads",
    },
    {"key": "elSMultiplier", "attr": "el_sMultiplier", "type": float, "group": "Roads"},
    {"key": "elSHeight", "attr": "el_sHeight", "type": float, "group": "Roads"},
    {
        "key": "elSCutTolerance",
        "attr": "el_sCutTolerance",
        "type": float,
        "group": "Roads",
    },
    {
        "key": "elSExcludeAlleys",
        "attr": "el_sExcludeAlleys",
        "type": bool,
        "group": "Roads",
    },
]
_ADVANCED_SETTINGS_BY_KEY = {f["key"]: f for f in _ADVANCED_SETTINGS_FIELDS}


def build_advanced_settings_state(tp3d=None):
    """Current values for every Advanced Settings popup field, for the
    picker pages' ADVANCED_SETTINGS_STATE snapshot."""
    if tp3d is None:
        tp3d = bpy.context.scene.tp3d
    return {f["key"]: getattr(tp3d, f["attr"]) for f in _ADVANCED_SETTINGS_FIELDS}


def apply_advanced_setting_update(tp3d, key, value):
    """Apply one Advanced Settings popup field update -- same main-thread-only
    rationale as apply_setting_update (see its docstring), queued by
    picker_server.py's /update_advanced_setting and drained via
    drain_pending_advanced_settings. *key* is checked against
    _ADVANCED_SETTINGS_FIELDS -- silently ignored if unrecognized.
    """
    field = _ADVANCED_SETTINGS_BY_KEY.get(key)
    if not field:
        return
    try:
        setattr(tp3d, field["attr"], field["type"](value))
    except (TypeError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Trail segment subdivision helper
# ---------------------------------------------------------------------------


def _subdivide_long_segments(coords, max_xy_dist, depsgraph=None):
    """Split trail segments longer than max_xy_dist Blender units to prevent clipping through hills.

    Inserts linearly-spaced intermediate points and raycasts downward against the
    terrain mesh to get the correct Z for each one.  Falls back to linear Z if the
    ray misses (e.g. point outside map bounds).
    """
    if len(coords) < 2:
        return coords
    result = [coords[0]]
    for i in range(1, len(coords)):
        x1, y1, z1 = result[-1]
        x2, y2, z2 = coords[i]
        dx, dy = x2 - x1, y2 - y1
        dist_xy = math.sqrt(dx * dx + dy * dy)
        if dist_xy > max_xy_dist:
            n = math.ceil(dist_xy / max_xy_dist)
            for j in range(1, n):
                t = j / n
                xi, yi = x1 + t * dx, y1 + t * dy
                zi = z1 + t * (z2 - z1)
                if depsgraph is not None:
                    hit, loc, _, _, _, _ = bpy.context.scene.ray_cast(
                        depsgraph, (xi, yi, zi + 500.0), (0.0, 0.0, -1.0)
                    )
                    if hit:
                        zi = loc.z
                result.append((xi, yi, zi))
        result.append(coords[i])
    return result


# ---------------------------------------------------------------------------
# Main generation orchestrator
# ---------------------------------------------------------------------------


def runGeneration(type, locked_scale=None):
    """Orchestrate the full 3D map generation pipeline."""

    flags = _GEN_FLAGS[type]
    overlay = _progress.ProgressOverlay.get()

    try:
        _progress.WarningsOverlay.clear()
        # --- Phase 1: Validate inputs and load all scene settings ---
        gen: GenerationContext = _rg_validate_inputs(
            flags, gen_type=type, locked_scale=locked_scale
        )
        overlay.start()
        overlay.update(0.03, "Initializing", "Validating inputs…")

        start_time = gen.start_time

        overlay.add_completed_step("Inputs validated")

        # --- Phase 2: Load coordinate data from GPX / synthetic source ---
        overlay.update(0.08, "Loading Data", "Reading GPX file…")
        _rg_load_coordinates(gen)

        # --- Phase 3: Calculate and store trail statistics ---
        overlay.update(
            0.12, "Trail Statistics", "Computing distances & elevation gain…"
        )
        _rg_compute_trail_stats(gen)

        # --- Phase 4: Interpolate path to at least 300 points for a smooth curve ---
        overlay.update(0.16, "Path Interpolation", "Smoothing trail curve…")
        _rg_interpolate_path_curve(gen)

        # --- Phase 5: Calculate horizontal scale factor ---
        overlay.update(0.20, "Scale Calculation", "Computing horizontal scale…")
        _rg_calculate_horizontal_scale(gen)

        # --- Phase 6: Convert to Blender coordinates and find map center ---
        overlay.update(0.24, "Coordinate Conversion", "Converting to Blender space…")
        _rg_convert_then_center_coordinates(gen)

        # --- Phase 7: Remove previously generated objects at the same location ---
        overlay.update(0.28, "Scene Cleanup", "Removing previous objects…")
        _cleanup_build_area(gen)

        overlay.add_completed_step(
            f"GPX loaded  —  {gen.gpx_stats.length:.1f} km, {int(gen.gpx_stats.elevation)} m gain"
            if "stats" in flags and gen.gpx_stats.length > 0
            else "GPX data loaded"
        )

        # --- Phase 8: Create base map shape ---
        overlay.update(0.33, "Building Map Shape", "Creating base mesh…")

        _rg_create_map_object(gen)

        overlay.add_completed_step(
            f"Map shape created  ({gen.shape.capitalize()}, {round(gen.mapKm or 0, 1)} km)"
        )
        overlay.set_fetch_items(build_fetch_items(gen.mapKm))

        # --- OSM background prefetch: start now so Overpass requests overlap with elevation download ---
        _rg_start_osm_prefetch(gen)

        if gen.fetchThread is not None:
            print("OSM prefetch started (overlapping elevation download)")

        # --- Phase 9: Fetch terrain elevation data ---
        overlay.update(
            0.38, "Fetching Elevation Data", "Querying API — this may take a moment…"
        )

        _rg_fetch_elevation(gen)

        print("Elevation Data fetched")
        overlay.sub_percent = None  # hide sub-bar now that elevation is done
        overlay.set_fetch_done("elevation", success=True)
        overlay.add_completed_step(
            f"Elevation fetched  ({len(gen.tileVerts or [])} pts)"
        )
        overlay.update(
            0.65, "Elevation Data Ready", f"{len(gen.tileVerts or [])} points fetched"
        )

        # --- Phase 10a: Prepare trail Blender coordinates ---
        overlay.update(
            0.67, "Preparing Trail", "Converting and simplifying coordinates…"
        )
        _rg_prepare_trail_coords(gen)

        # --- Phase 10b: Build trail curves ---
        overlay.update(0.70, "Building Trail", "Creating curve objects…")
        _rg_build_trail_curves(gen)

        curveObjs = gen.curveObjs
        if curveObjs:
            bpy.context.scene.tp3d.currentTrail = curveObjs[0]

        _n_segs = len(curveObjs) if curveObjs else 0
        _n_pts = len(gen.blenderCoords) if gen.blenderCoords else 0
        overlay.add_completed_step(
            f"Trail built  —  {_n_segs} seg{'s' if _n_segs != 1 else ''}, {_n_pts} pts"
        )

        # --- Phase 11: Apply terrain elevation to mesh vertices ---
        overlay.update(0.75, "Applying Terrain", "Displacing mesh vertices…")

        _rg_displace_terrain_with_curve(gen)

        overlay.update(0.80, "Terrain Ready", "Vertices displaced…")
        overlay.sub_percent = None

        _rg_extrude_terrain(gen)

        # --- Phase 12-13: Create text / plate overlays for text-based shapes ---
        overlay.update(0.82, "Shape Overlays", "Adding text and plate elements…")

        _rg_create_text_and_overlays(gen)

        # --- Phase 14: Create terrain overlay elements ---
        overlay.update(0.83, "Terrain Elements", "Adding elements…")
        if gen.fetchThread is not None:
            gen.fetchThread.join()
        _rg_build_terrain_elements(gen, prefetched_osm=gen.fetchResult)

        # --- Phase 15: Single color mode processing ---
        overlay.update(0.95, "Coloring", "Applying single-color mode…")
        _rg_apply_single_color_mode(gen)

        # --- Phase 15b: CREATE_TEXTURE — rasterise OSM polygons into UV texture ---
        if gen.elementMode == "CREATE_TEXTURE":
            _rg_apply_texture(gen)
            _lo = bpy.context.scene.tp3d.lowestZ
            _hi = bpy.context.scene.tp3d.highestZ
            overlay.add_completed_step(f"Terrain applied  —  z {_lo:.1f} to {_hi:.1f}")
            overlay.update(0.96, "Texture", "Rasterising OSM texture…")
        # --- Phases 16-18: Assign materials, export, and finalize ---
        overlay.update(0.97, "Finalizing", "Exporting files...")
        _rg_assign_materials(gen)

        # Finish and Export
        _rg_export(gen)

        # Calculate script durations for prints and overlay updates
        end_time = time.time()
        duration = end_time - start_time
        bpy.context.scene.tp3d.sRunDuration = round(duration)
        bpy.context.scene.tp3d["o_time"] = _("Script ran for {} seconds").format(
            round(duration)
        )

        from .elevation import load_generation_counter, save_generation_counter

        _total_maps = load_generation_counter() + 1
        save_generation_counter(_total_maps)
        bpy.context.scene.tp3d["o_mapsGenerated"] = f"Maps Generated: {_total_maps}"

        if gen.mapObject:
            gen.mapObject["GenerationTime"] = round(duration)

        print(
            f"Finished. Generating Map took {duration:.0f} seconds",
            "----------------------------------------------------------------",
            " ",
        )

        _elapsed = int(time.time() - overlay._start_time) if overlay._start_time else 0
        _m, _s = divmod(_elapsed, 60)
        overlay.update(1.0, "Done", "")
        overlay.add_completed_step(f"Done  —  {_m:02d}:{_s:02d} total")
    except ValidationError as e:
        print(f"Validation Failed: {e}")
        _progress.WarningsOverlay.add_warning(f"Error: {e}")

    except GenerationError as e:
        print(f"Generation phase failed: {e}")
        _progress.WarningsOverlay.add_warning(str(e), icon="error")

    except Exception as e:  # noqa: BLE001 - runGeneration could raise many kinds of errors, for now I don't have a concrete list so.. bare exception.
        import traceback

        traceback.print_exc()
        print(f"Generation failed: {e}")
        _progress.WarningsOverlay.add_warning(
            "Generation failed, check console for details"
        )

    finally:
        overlay.finish()
        _progress.WarningsOverlay.get().show()


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
    from .elevation import (
        get_tile_elevation,  # deferred to avoid circular import at load time
    )
    from .geo import convert_to_geo  # deferred to avoid circular import at load time

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
    from .mesh_ops import (
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
    from .mesh_ops import (
        recalculateNormals,  # deferred to avoid circular import at load time
    )
    from .metadata import (
        writeMetadata,  # deferred to avoid circular import at load time
    )
    from .primitives import (
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
        from .scene import (
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

        # CREATE_TEXTURE: rasterise OSM polygons into a UV paint texture.
        # _rg_build_terrain_elements already populated terrain['_osm_polygons']
        # and discarded the road mesh; we just need to bake the texture here.
        if props["elementMode"] == "CREATE_TEXTURE":
            from .texture import setup_paint_texture

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

    from .elevation import load_generation_counter, save_generation_counter

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
    from .geo import (  # deferred to avoid circular import at load time
        convert_to_blender_coordinates,
        separate_duplicate_xy,
    )
    from .io_gpx import read_gpx_file  # deferred to avoid circular import at load time
    from .mesh_ops import (
        RaycastCurveToAnyMesh,  # deferred to avoid circular import at load time
    )
    from .primitives import (  # deferred to avoid circular import at load time
        create_curve_from_coordinates,
        simplify_curve,
    )
    from .scene import (
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
