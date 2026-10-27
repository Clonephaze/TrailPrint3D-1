import json
import os
import re
import zlib

import bpy
from bpy.app.translations import pgettext_iface as _

from .. import constants as const
from .color import material_to_srgb

COLOR_ROLES = (
    ("BASE", "element_color_base", "Base Terrain"),
    ("WATER", "element_color_water", "Water"),
    ("FOREST", "element_color_forest", "Forest"),
    ("MOUNTAIN", "element_color_mountain", "Mountain / Scree"),
    ("CITY", "element_color_city", "City"),
    ("GREENSPACE", "element_color_greenspace", "Greenspace"),
    ("FARMLAND", "element_color_farmland", "Farmland"),
    ("GLACIER", "element_color_glacier", "Glacier"),
    ("BUILDINGS", "element_color_buildings", "Buildings"),
    ("ROADS", "element_color_roads", "Roads"),
    ("TRAIL", "element_color_trail", "Trail"),
    ("YELLOW", "element_color_secondary_trail", "Secondary Trail"),
)
ROLE_NAMES = tuple(role for role, _attr, _label in COLOR_ROLES)
ROLE_ATTRS = {role: attr for role, attr, _label in COLOR_ROLES}
COLOR_ROLES_PROP = "tp3d_color_roles"
USER_STYLE_PREFIX = "USER:"
STYLE_VERSION = 1

BUILT_IN_STYLES = {
    "DEFAULT": (
        "Default",
        {
            "BASE": "#0DB20D",
            "WATER": "#0000CC",
            "FOREST": "#0D400D",
            "MOUNTAIN": "#808080",
            "CITY": "#B2B21A",
            "GREENSPACE": "#29FF29",
            "FARMLAND": "#4D801A",
            "GLACIER": "#CCE5CC",
            "BUILDINGS": "#666666",
            "ROADS": "#000000",
            "TRAIL": "#FF0000",
            "YELLOW": "#FFFF00",
        },
    ),
    "DESERT": (
        "Desert",
        {
            "BASE": "#D2B078",
            "WATER": "#318BA3",
            "FOREST": "#667744",
            "MOUNTAIN": "#A66F49",
            "CITY": "#E1CDAA",
            "GREENSPACE": "#A4B477",
            "FARMLAND": "#B88E50",
            "GLACIER": "#F4E9D5",
            "BUILDINGS": "#80664F",
            "ROADS": "#514033",
            "TRAIL": "#C83F35",
            "YELLOW": "#F0C653",
        },
    ),
    "CITY": (
        "City",
        {
            "BASE": "#A7ADB2",
            "WATER": "#397FA5",
            "FOREST": "#496B52",
            "MOUNTAIN": "#777F86",
            "CITY": "#D1CEC5",
            "GREENSPACE": "#82A77B",
            "FARMLAND": "#B4AE83",
            "GLACIER": "#E7F0F3",
            "BUILDINGS": "#515B65",
            "ROADS": "#30363B",
            "TRAIL": "#D94A45",
            "YELLOW": "#E9B949",
        },
    ),
    "ARCTIC": (
        "Arctic",
        {
            "BASE": "#D5E3E9",
            "WATER": "#326FA0",
            "FOREST": "#476B61",
            "MOUNTAIN": "#9AAAB4",
            "CITY": "#B9C8D0",
            "GREENSPACE": "#A4C6B9",
            "FARMLAND": "#C3D2BB",
            "GLACIER": "#F2F8FA",
            "BUILDINGS": "#637582",
            "ROADS": "#344550",
            "TRAIL": "#D74440",
            "YELLOW": "#F0CB62",
        },
    ),
    "FOREST": (
        "Forest",
        {
            "BASE": "#688653",
            "WATER": "#327A96",
            "FOREST": "#244B35",
            "MOUNTAIN": "#82796A",
            "CITY": "#B0A47B",
            "GREENSPACE": "#96B96C",
            "FARMLAND": "#A3A45C",
            "GLACIER": "#DDEAE5",
            "BUILDINGS": "#695A49",
            "ROADS": "#40382F",
            "TRAIL": "#D65356",
            "YELLOW": "#EAB65A",
        },
    ),
    "ALPINE": (
        "Alpine",
        {
            "BASE": "#7EA66A",
            "WATER": "#377FA7",
            "FOREST": "#315C43",
            "MOUNTAIN": "#898B87",
            "CITY": "#BDB49E",
            "GREENSPACE": "#A9C97B",
            "FARMLAND": "#B7B66F",
            "GLACIER": "#F1F6F8",
            "BUILDINGS": "#6B6C67",
            "ROADS": "#393B39",
            "TRAIL": "#D94345",
            "YELLOW": "#F2C14E",
        },
    ),
}

_STYLE_ITEMS_CACHE = []

# Blender stores a callback EnumProperty as the integer from the item tuple, not the
# identifier. User styles therefore need a value that depends only on the style's
# name; a positional index shifts whenever another style is saved or deleted, and
# a saved .blend then reopens on the wrong style. Built-ins keep their small
# indices; user styles hash into a range that cannot overlap them.
_USER_STYLE_VALUE_BASE = 1 << 16
_USER_STYLE_VALUE_SPAN = 1 << 24

# Redraws call list_user_styles/style_is_modified, so avoid file reads there. The
# listing is keyed on the style folder's mtime and each parsed style on its own
# file's (mtime, size); both are a single stat() to validate.
_user_styles_cache = {"signature": None, "names": []}
_user_style_colors_cache = {}


def hex_to_srgb(value):
    if not isinstance(value, str) or not re.fullmatch(r"#?[0-9A-Fa-f]{6}", value):
        raise ValueError(f"Invalid color: {value!r}")
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def srgb_to_hex(rgb):
    return "#{:02X}{:02X}{:02X}".format(*rgb[:3])


def color_to_srgb(color):
    return tuple(round(max(0.0, min(1.0, channel)) * 255.0) for channel in color[:3])


def srgb_to_color(rgb):
    return tuple(channel / 255.0 for channel in rgb[:3])


def default_colors():
    return normalize_colors(BUILT_IN_STYLES["DEFAULT"][1])


def normalize_colors(colors):
    normalized = {
        role: hex_to_srgb(value)
        for role, value in BUILT_IN_STYLES["DEFAULT"][1].items()
    }
    if not isinstance(colors, dict):
        return normalized
    for role in ROLE_NAMES:
        if role in colors:
            normalized[role] = hex_to_srgb(colors[role])
    return normalized


def scene_colors(tp3d=None):
    if tp3d is None:
        scene = getattr(bpy.context, "scene", None)
        tp3d = getattr(scene, "tp3d", None)
    colors = default_colors()
    if tp3d is None:
        return colors
    for role, attr in ROLE_ATTRS.items():
        value = getattr(tp3d, attr, None)
        if value is not None:
            colors[role] = color_to_srgb(value)
    return colors


def set_scene_colors(tp3d, colors):
    for role in ROLE_NAMES:
        if role in colors:
            setattr(tp3d, ROLE_ATTRS[role], srgb_to_color(colors[role]))


def _safe_style_name(name):
    name = " ".join(str(name).split())
    if not name or len(name) > 64 or re.search(r'[<>:"/\\|?*]', name):
        raise ValueError(_('Use 1-64 characters without < > : " / \\ | ? *.'))
    if name.rstrip(" .") != name or name.upper() in {"CON", "PRN", "AUX", "NUL"}:
        raise ValueError(_("Use a regular file-safe style name."))
    return name


def _style_path(name):
    return os.path.join(const.color_style_dir, _safe_style_name(name) + ".json")


def list_user_styles():
    try:
        signature = (const.color_style_dir, os.stat(const.color_style_dir).st_mtime_ns)
    except OSError:
        _user_styles_cache.update(signature=None, names=[])
        return []
    if _user_styles_cache["signature"] == signature:
        return list(_user_styles_cache["names"])
    styles = []
    for filename in sorted(os.listdir(const.color_style_dir), key=str.lower):
        name, ext = os.path.splitext(filename)
        if ext.lower() != ".json":
            continue
        try:
            styles.append(_safe_style_name(name))
        except ValueError:
            continue
    _user_styles_cache.update(signature=signature, names=styles)
    return list(styles)


def _user_style_enum_values(names):
    """Map each user style name to a stable enum value (see _USER_STYLE_VALUE_BASE)."""
    values = {}
    used = set()
    for name in names:
        value = (
            _USER_STYLE_VALUE_BASE
            + zlib.crc32(name.casefold().encode("utf-8")) % _USER_STYLE_VALUE_SPAN
        )
        while value in used:  # astronomically rare; stays deterministic for a given set
            value += 1
        used.add(value)
        values[name] = value
    return values


def load_user_style(name):
    path = _style_path(name)
    stat = os.stat(path)  # raises OSError when missing, like open() would
    signature = (stat.st_mtime_ns, stat.st_size)
    cached = _user_style_colors_cache.get(path)
    if cached is not None and cached[0] == signature:
        return dict(cached[1])
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or data.get("version") != STYLE_VERSION:
        raise ValueError("Unsupported color style version")
    colors = normalize_colors(data.get("colors"))
    _user_style_colors_cache[path] = (signature, colors)
    return dict(colors)


def save_user_style(name, colors):
    name = _safe_style_name(name)
    if name.upper() in BUILT_IN_STYLES or name.lower() in {
        label.lower() for label, _colors in BUILT_IN_STYLES.values()
    }:
        raise ValueError(_("Built-in style names are reserved."))
    os.makedirs(const.color_style_dir, exist_ok=True)
    data = {
        "version": STYLE_VERSION,
        "name": name,
        "colors": role_hex_map(normalize_colors(role_hex_map(colors))),
    }
    path = _style_path(name)
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    os.replace(temp_path, path)
    return USER_STYLE_PREFIX + name


def delete_user_style(identifier):
    if not identifier.startswith(USER_STYLE_PREFIX):
        raise ValueError(_("Only saved styles can be deleted."))
    path = _style_path(identifier[len(USER_STYLE_PREFIX) :])
    os.remove(path)
    _user_style_colors_cache.pop(path, None)


def style_colors(identifier):
    if identifier in BUILT_IN_STYLES:
        return normalize_colors(BUILT_IN_STYLES[identifier][1])
    if identifier.startswith(USER_STYLE_PREFIX):
        return load_user_style(identifier[len(USER_STYLE_PREFIX) :])
    raise ValueError(f"Unknown color style: {identifier}")


def color_style_items(_self, _context):
    items = [
        (key, _(label), _("Built-in color style"), index)
        for index, (key, (label, _colors)) in enumerate(BUILT_IN_STYLES.items())
    ]
    names = list_user_styles()
    for name, value in _user_style_enum_values(names).items():
        items.append((USER_STYLE_PREFIX + name, name, _("Saved color style"), value))
    _STYLE_ITEMS_CACHE[:] = items
    return _STYLE_ITEMS_CACHE


def style_is_modified(tp3d):
    try:
        return scene_colors(tp3d) != style_colors(tp3d.color_style)
    except (OSError, ValueError, json.JSONDecodeError):
        return True


def material_role_colors():
    colors = default_colors()
    for role in ROLE_NAMES:
        material = bpy.data.materials.get(role)
        if material is not None:
            colors[role] = material_to_srgb(material, colors[role])
    return colors


def role_hex_map(colors):
    return {role: srgb_to_hex(rgb) for role, rgb in colors.items()}


def write_mesh_color_roles(mesh, colors=None):
    mesh[COLOR_ROLES_PROP] = json.dumps(
        role_hex_map(colors or scene_colors()), sort_keys=True
    )


def read_mesh_color_roles(mesh, fallback):
    raw = mesh.get(COLOR_ROLES_PROP)
    if not raw:
        return dict(fallback)
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("color roles must be an object")
        # Roles missing from an older snapshot take the caller's fallback (the
        # current material color), not DEFAULT, which would recolor the wrong pixels.
        roles = dict(fallback)
        for role in ROLE_NAMES:
            if role in parsed:
                roles[role] = hex_to_srgb(parsed[role])
        return roles
    except (TypeError, ValueError, json.JSONDecodeError):
        print(
            f"[TP3D colors] Invalid {COLOR_ROLES_PROP} on {mesh.name}; using current materials"
        )
        return dict(fallback)
