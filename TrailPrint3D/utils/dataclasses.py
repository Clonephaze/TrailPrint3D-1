import threading
import time
from dataclasses import dataclass, field
from typing import Any

from bpy.types import Object
from shapely.geometry import MultiPolygon, Polygon


@dataclass
class GPXStats:
    start_time: str | None = ""
    length: float = 0
    elevation: float = 0
    time: float = 0
    avg_speed: float = 0
    date: str | None = None


@dataclass
class GenerationContext:
    flags: frozenset[str]
    gpx_file_path: str
    gpx_chain_path: str
    exportPath: str
    exportFormat: str
    shape: str
    name: str
    modelname: str
    size: int
    autoExport: bool
    scaleElevation: float
    scalemode: str
    scaleLon1: float
    scaleLat1: float
    scaleLon2: float
    scaleLat2: float
    shapeRotation: int
    overwritePathElevation: bool
    api: str
    selfHosted: str
    fixedElevationScale: bool
    minThickness: float
    xTerrainOffset: float
    yTerrainOffset: float
    singleColorMode: bool
    elementMode: int
    disableCache: bool
    num_subdivisions: int
    textFont: str
    plateThickness: float
    col_wActive: bool
    col_fActive: bool
    col_cActive: bool
    col_grActive: bool
    col_glActive: bool
    el_bActive: bool
    el_sActive: bool
    jMapLat: float
    jMapLon: float
    jMapRadius: float
    jMapLat1: float
    jMapLon1: float
    jMapLat2: float
    jMapLon2: float
    genType: int = 0
    lockedScale: float | None = None
    mapObject: object | None = None
    mapOutline: Polygon | MultiPolygon | None = None
    tbMinLat: float = 0
    tbMaxLat: float = 0
    tbMinLon: float = 0
    tbMaxLon: float = 0
    mapKm: float | None = None
    pathCoordinates: list[tuple[float, float, float, float]] | None = None
    flatCoordinates: list[tuple[float, float, float, float]] | None = None
    pathSegs: list[list[tuple[float, float, float, float]]] | None = None
    pathSegsByFile: list[list[list[tuple[float, float, float, float]]]] | None = None
    blenderCoords: list[tuple[float, float, float]] | None = None
    blenderPathSegs: list[list[tuple[float, float, float]]] | None = None
    blenderPathSegsByFile: list[list[list[tuple[float, float, float]]]] | None = None
    gpx_stats: GPXStats = field(default_factory=GPXStats)
    start_time: float = field(default_factory=time.time)
    curveObj: object | None = None
    curveObjs: list[Object] | None = None
    sScaleHor: float | None = None
    centerX: float | None = None
    centerY: float | None = None
    tileVerts: list[float] | None = None
    elDiff: float | None = None
    buggyData: int = 0
    addExtrusion: float | None = None
    autoScale: float | None = None
    elements: list | None = None
    textObj: Object | None = None
    plateObj: Object | None = None
    shellObj: Object | None = None
    texTrail: bool = True
    fetchThread: threading.Thread | None = None
    fetchResult: dict[str, dict[Any, tuple[dict, bool]]] | None = None


class ValidationError(Exception):
    """Raised when input validation fails."""
