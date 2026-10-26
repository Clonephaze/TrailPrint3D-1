"""Element color preference tests.

Run with:
  blender --background --factory-startup --python-exit-code 1 -P tests/test_element_colors.py
"""

import os
import sys
import traceback

import bpy

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

if "TrailPrint3D" not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module="TrailPrint3D")

from TrailPrint3D import addon_preferences, constants
from TrailPrint3D.utils import primitives
from TrailPrint3D.utils.color import material_to_srgb

_passed = 0
_failed = 0


def _run(name, fn):
    global _passed, _failed
    try:
        fn()
        print(f"  PASS  {name}")
        _passed += 1
    except Exception:
        print(f"  FAIL  {name}")
        traceback.print_exc()
        _failed += 1


def _color(rgb):
    return tuple(channel / 255.0 for channel in rgb)


def test_preferences_drive_material_colors():
    prefs = addon_preferences.get_prefs()
    original = {
        attr: tuple(getattr(prefs, attr))
        for attr, _material, _label, _default in constants.ELEMENT_COLOR_DEFAULTS
    }
    try:
        prefs.element_color_base = _color((12, 34, 56))
        prefs.element_color_roads = _color((210, 90, 30))
        primitives.setupColors()

        assert material_to_srgb(bpy.data.materials["BASE"]) == (12, 34, 56)
        assert material_to_srgb(bpy.data.materials["ROADS"]) == (210, 90, 30)
        assert material_to_srgb(bpy.data.materials["BLACK"]) == (0, 0, 0)
        assert constants._KIND_MATERIAL_NAME["ROADS"] == "ROADS"
    finally:
        for attr, value in original.items():
            setattr(prefs, attr, value)


def test_reset_restores_default_colors():
    prefs = addon_preferences.get_prefs()
    original = {
        attr: tuple(getattr(prefs, attr))
        for attr, _material, _label, _default in constants.ELEMENT_COLOR_DEFAULTS
    }
    try:
        prefs.element_color_water = _color((1, 2, 3))
        assert bpy.ops.tp3d.reset_element_colors() == {"FINISHED"}
        colors = addon_preferences.element_material_colors()
        for _attr, material, _label, default in constants.ELEMENT_COLOR_DEFAULTS:
            assert colors[material] == default
    finally:
        for attr, value in original.items():
            setattr(prefs, attr, value)


for _test in (
    test_preferences_drive_material_colors,
    test_reset_restores_default_colors,
):
    _run(_test.__name__, _test)

print(f"\n{_passed} passed, {_failed} failed")
if _failed:
    raise SystemExit(1)
