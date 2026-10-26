import json
import os
import re

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
    "DEFAULT": ("Default", {
        "BASE": "#0DB20D", "WATER": "#0000CC", "FOREST": "#0D400D",
        "MOUNTAIN": "#808080", "CITY": "#B2B21A", "GREENSPACE": "#29FF29",
        "FARMLAND": "#4D801A", "GLACIER": "#CCE5CC", "BUILDINGS": "#666666",
        "ROADS": "#000000", "TRAIL": "#FF0000", "YELLOW": "#FFFF00",
    }),
    "DESERT": ("Desert", {
        "BASE": "#C9A66B", "WATER": "#2F7F9F", "FOREST": "#6B7F3A",
        "MOUNTAIN": "#9C6B43", "CITY": "#D8C3A5", "GREENSPACE": "#A3A85A",
        "FARMLAND": "#B98B4E", "GLACIER": "#F2E7D0", "BUILDINGS": "#8A6F55",
        "ROADS": "#4A3B2E", "TRAIL": "#C0392B", "YELLOW": "#F2C14E",
    }),
    "CITY": ("City", {
        "BASE": "#9EA3A8", "WATER": "#3E6F99", "FOREST": "#4E6B4A",
        "MOUNTAIN": "#7A7A7A", "CITY": "#C8C2B5", "GREENSPACE": "#7FA36B",
        "FARMLAND": "#A7A47A", "GLACIER": "#E6EEF2", "BUILDINGS": "#5C6168",
        "ROADS": "#2B2B2B", "TRAIL": "#E63946", "YELLOW": "#FFD166",
    }),
    "ARCTIC": ("Arctic", {
        "BASE": "#E8F1F5", "WATER": "#2B6CB0", "FOREST": "#4B6E63",
        "MOUNTAIN": "#9AA7B0", "CITY": "#B7C3CC", "GREENSPACE": "#A9C9C0",
        "FARMLAND": "#C9D6C8", "GLACIER": "#FFFFFF", "BUILDINGS": "#6E7C87",
        "ROADS": "#33414D", "TRAIL": "#D62828", "YELLOW": "#F4D35E",
    }),
    "FOREST": ("Forest", {
        "BASE": "#4F7D3A", "WATER": "#2C6E91", "FOREST": "#1F4D2B",
        "MOUNTAIN": "#7C7467", "CITY": "#A49A6A", "GREENSPACE": "#78A85A",
        "FARMLAND": "#8C9A4B", "GLACIER": "#DDE8E1", "BUILDINGS": "#6D5D4B",
        "ROADS": "#3B3227", "TRAIL": "#D1495B", "YELLOW": "#EDAE49",
    }),
    "ALPINE": ("Alpine", {
        "BASE": "#6E9F5B", "WATER": "#3A7CA5", "FOREST": "#2E5E3E",
        "MOUNTAIN": "#8B8680", "CITY": "#B9A98A", "GREENSPACE": "#9BC56E",
        "FARMLAND": "#A8B66B", "GLACIER": "#F4F8FA", "BUILDINGS": "#6F6A64",
        "ROADS": "#2F2F2F", "TRAIL": "#E63946", "YELLOW": "#FFC300",
    }),
}

_STYLE_ITEMS_CACHE = []


def hex_to_srgb(value):
    if not isinstance(value, str) or not re.fullmatch(r"#?[0-9A-Fa-f]{6}", value):
        raise ValueError(f"Invalid color: {value!r}")
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


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
        raise ValueError(_("Use 1-64 characters without < > : \" / \\ | ? *."))
    if name.rstrip(" .") != name or name.upper() in {"CON", "PRN", "AUX", "NUL"}:
        raise ValueError(_("Use a regular file-safe style name."))
    return name


def _style_path(name):
    return os.path.join(const.color_style_dir, _safe_style_name(name) + ".json")


def list_user_styles():
    if not os.path.isdir(const.color_style_dir):
        return []
    styles = []
    for filename in sorted(os.listdir(const.color_style_dir), key=str.lower):
        name, ext = os.path.splitext(filename)
        if ext.lower() != ".json":
            continue
        try:
            styles.append(_safe_style_name(name))
        except ValueError:
            continue
    return styles


def load_user_style(name):
    with open(_style_path(name), "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or data.get("version") != STYLE_VERSION:
        raise ValueError("Unsupported color style version")
    return normalize_colors(data.get("colors"))


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
    os.remove(_style_path(identifier[len(USER_STYLE_PREFIX):]))


def style_colors(identifier):
    if identifier in BUILT_IN_STYLES:
        return normalize_colors(BUILT_IN_STYLES[identifier][1])
    if identifier.startswith(USER_STYLE_PREFIX):
        return load_user_style(identifier[len(USER_STYLE_PREFIX):])
    raise ValueError(f"Unknown color style: {identifier}")


def color_style_items(_self, _context):
    items = [
        (key, _(label), _("Built-in color style"), index)
        for index, (key, (label, _colors)) in enumerate(BUILT_IN_STYLES.items())
    ]
    offset = len(items)
    for index, name in enumerate(list_user_styles(), start=offset):
        items.append((USER_STYLE_PREFIX + name, name, _("Saved color style"), index))
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
    mesh[COLOR_ROLES_PROP] = json.dumps(role_hex_map(colors or scene_colors()), sort_keys=True)


def read_mesh_color_roles(mesh, fallback):
    raw = mesh.get(COLOR_ROLES_PROP)
    if not raw:
        return dict(fallback)
    try:
        return normalize_colors(json.loads(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        print(f"[TP3D colors] Invalid {COLOR_ROLES_PROP} on {mesh.name}; using current materials")
        return dict(fallback)
