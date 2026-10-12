"""Tests for Color by Height material, texture, and manifold behavior.

Run with:
  blender --background --factory-startup --python-exit-code 1 -P tests/test_color_by_height.py
  or as part of tests/run_all_tests.py.
"""

import ast
import math
import os
import sys
import traceback

import bmesh  # type: ignore
import bpy  # type: ignore
from mathutils import Matrix  # type: ignore

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

if "TrailPrint3D" not in bpy.context.preferences.addons:
    bpy.ops.preferences.addon_enable(module="TrailPrint3D")

from TrailPrint3D import operators
from TrailPrint3D.utils import texture

_passed = 0
_failed = 0


def _run(name, fn):
    global _passed, _failed
    try:
        fn()
        print(f"  PASS  {name}")
        _passed += 1
    except Exception as exc:  # noqa: BLE001 - keep the runner going
        print(f"  FAIL  {name} - exception occurred: {exc}")
        traceback.print_exc()
        _failed += 1


def _assert_all_passed():
    print(f"\n{'=' * 60}")
    print(f"  {_passed} passed, {_failed} failed")
    print(f"{'=' * 60}\n")
    if _failed:
        raise SystemExit(1)


def _clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def _material(name, color):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color = (*color, 1.0)
    return material


def _new_map(name="ColorByHeightMap", material_name="BASE"):
    bpy.ops.mesh.primitive_cube_add(size=2)
    obj = bpy.context.object
    obj.name = name
    obj["Object type"] = "MAP"
    obj["elementMode"] = "PAINT"
    obj["lowestZ"] = -1.0
    obj["highestZ"] = 1.0
    obj["minThickness"] = 0.0
    material = _material(material_name, (0.1, 0.7, 0.1))
    obj.data.materials.append(material)
    return obj


def _new_peak_map(name="ColorByHeightPeak"):
    bpy.ops.mesh.primitive_cone_add(
        vertices=32, radius1=2.0, radius2=0.25, depth=4.0
    )
    obj = bpy.context.object
    obj.name = name
    obj["Object type"] = "MAP"
    obj["elementMode"] = "PAINT"
    obj["lowestZ"] = -2.0
    obj["highestZ"] = 2.0
    obj["minThickness"] = 0.0
    obj.data.materials.append(_material("BASE", (0.1, 0.7, 0.1)))
    return obj


def _is_manifold(mesh):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        return bool(bm.faces) and all(edge.is_manifold for edge in bm.edges)
    finally:
        bm.free()


def test_operator_properties_registered():
    identifiers = {
        prop.identifier
        for prop in bpy.ops.tp3d.color_mountain.get_rna_type().properties
    }
    assert {
        "mountain_treshold",
        "mountain_color",
        "color_height_SEM",
        "mountain_noise",
        "mountain_noise_amplitude",
        "mountain_noise_scale",
    } <= identifiers


def test_blank_map_eligibility():
    _clear_scene()
    obj = _new_map()
    tp3d = bpy.context.scene.tp3d
    assert operators._mountain_split_ineligible_reason(obj, tp3d, True) is None

    obj["elementMode"] = "SINGLECOLORMODE_REMESH"
    assert operators._mountain_split_ineligible_reason(obj, tp3d)
    obj["elementMode"] = "PAINT"

    obj.data["3mf_is_paint_texture"] = True
    assert operators._mountain_split_ineligible_reason(obj, tp3d)
    del obj.data["3mf_is_paint_texture"]

    painted = _material("WATER", (0.0, 0.0, 0.8))
    obj.data.materials.append(painted)
    obj.data.polygons[0].material_index = 1
    assert operators._mountain_split_ineligible_reason(obj, tp3d)


def test_material_helper_is_per_color():
    for name in ("MOUNTAIN", "HEIGHT_FF0040"):
        material = bpy.data.materials.get(name)
        if material is not None:
            bpy.data.materials.remove(material)
    material = operators._height_color_material((1.0, 0.0, 0.25))
    assert material.name == "HEIGHT_FF0040"
    bsdf = next(
        node for node in material.node_tree.nodes if node.type == "BSDF_PRINCIPLED"
    )
    assert tuple(bsdf.inputs["Base Color"].default_value[:3]) == (1.0, 0.0, 0.25)
    # Default grey keeps the historical MOUNTAIN material, and a second colour
    # must never reuse (and therefore recolour) the first one.
    grey = operators._height_color_material((0.5, 0.5, 0.5))
    assert grey.name == "MOUNTAIN"
    assert grey is not material


def test_palette_slots_stack_and_prune():
    import numpy as np

    mesh = bpy.data.meshes.new("PaletteMesh")
    palette = {0: "#0DB30D"}

    def _arr(*hexes):
        colors = [
            (int(h[1:3], 16) / 255.0, int(h[3:5], 16) / 255.0, int(h[5:7], 16) / 255.0, 1.0)
            for h in hexes
        ]
        return np.array([colors], dtype=np.float32)

    texture._sync_height_bake_palette(
        mesh, palette, _arr("#0DB30D", "#FF0000"), "#FF0000"
    )
    assert sorted(palette.values()) == sorted(["#0DB30D", "#FF0000"])

    # Stacking a second colour keeps the first one.
    texture._sync_height_bake_palette(
        mesh, palette, _arr("#0DB30D", "#FF0000", "#0000FF"), "#0000FF"
    )
    assert sorted(palette.values()) == sorted(["#0DB30D", "#FF0000", "#0000FF"])
    assert len(texture._height_palette_keys(mesh)) == 2

    # A colour that is no longer visible loses its slot.
    texture._sync_height_bake_palette(
        mesh, palette, _arr("#0DB30D", "#0000FF"), "#0000FF"
    )
    assert sorted(palette.values()) == sorted(["#0DB30D", "#0000FF"])
    assert len(texture._height_palette_keys(mesh)) == 1


def test_palette_ownership_restored_with_undo():
    mesh = bpy.data.meshes.new("UndoPaletteMesh")
    obj = bpy.data.objects.new("UndoPaletteObject", mesh)
    bpy.context.collection.objects.link(obj)
    image = bpy.data.images.new(f"{mesh.name}_MMU_Paint", width=1, height=1)
    image.pixels.foreach_set((1.0, 0.0, 0.0, 1.0))
    mesh["3mf_paint_extruder_colors"] = str({0: "#0DB30D", 1: "#FF0000"})
    mesh[texture._HEIGHT_BAKE_PALETTE_KEY_PROP] = 1
    texture.save_height_bake_state(image, mesh)

    image.pixels.foreach_set((0.0, 0.0, 1.0, 1.0))
    mesh["3mf_paint_extruder_colors"] = str({0: "#0DB30D", 1: "#0000FF"})
    mesh[texture._HEIGHT_BAKE_PALETTE_KEY_PROP] = 1
    assert texture.restore_last_height_bake(obj)
    assert ast.literal_eval(mesh["3mf_paint_extruder_colors"])[1] == "#FF0000"
    assert list(mesh[texture._HEIGHT_BAKE_PALETTE_KEY_PROP]) == [1]
    pixels = tuple(image.pixels[:])
    assert pixels[:3] == (1.0, 0.0, 0.0)


def test_texture_recolor_removes_previous_pixels():
    mesh = bpy.data.meshes.new("TextureRecolorMesh")
    mesh.from_pydata(
        [(-1.0, -1.0, 1.0), (1.0, -1.0, 1.0), (1.0, 1.0, 1.0), (-1.0, 1.0, 1.0)],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()
    obj = bpy.data.objects.new("TextureRecolorObject", mesh)
    bpy.context.collection.objects.link(obj)
    image = bpy.data.images.new(f"{mesh.name}_MMU_Paint", width=8, height=8)
    image.pixels.foreach_set((0.0, 1.0, 0.0, 1.0) * 64)
    mesh["3mf_paint_extruder_colors"] = str({0: "#00FF00"})

    red = operators._height_color_material((1.0, 0.0, 0.0))
    assert texture.bake_height_layer_into_texture(
        obj, 0.0, red, noise_amplitude=0.0
    )
    palette = ast.literal_eval(mesh["3mf_paint_extruder_colors"])
    assert "#FF0000" in palette.values()

    blue = operators._height_color_material((0.0, 0.0, 1.0))
    assert texture.bake_height_layer_into_texture(
        obj, 0.0, blue, noise_amplitude=0.0
    )
    palette = ast.literal_eval(mesh["3mf_paint_extruder_colors"])
    assert "#0000FF" in palette.values()
    assert "#FF0000" not in palette.values()
    assert len(texture._height_palette_keys(mesh)) == 1

    pixels = [round(value * 255) for value in image.pixels[:]]
    rgb = list(zip(pixels[0::4], pixels[1::4], pixels[2::4]))
    assert (255, 0, 0) not in rgb
    assert (0, 0, 255) in rgb


def test_texture_layers_stack():
    mesh = bpy.data.meshes.new("TextureStackMesh")
    mesh.from_pydata(
        [(-1.0, -1.0, 0.0), (1.0, -1.0, 2.0), (1.0, 1.0, 2.0), (-1.0, 1.0, 0.0)],
        [],
        [(0, 1, 2, 3)],
    )
    mesh.update()
    obj = bpy.data.objects.new("TextureStackObject", mesh)
    bpy.context.collection.objects.link(obj)
    image = bpy.data.images.new(f"{mesh.name}_MMU_Paint", width=32, height=32)
    image.pixels.foreach_set((0.0, 1.0, 0.0, 1.0) * 32 * 32)
    mesh["3mf_paint_extruder_colors"] = str({0: "#00FF00"})

    grey = operators._height_color_material((0.5, 0.5, 0.5))
    white = operators._height_color_material((1.0, 1.0, 1.0))
    assert texture.bake_height_layer_into_texture(obj, 0.6, grey, noise_amplitude=0.0)
    assert texture.bake_height_layer_into_texture(obj, 1.4, white, noise_amplitude=0.0)

    palette = ast.literal_eval(mesh["3mf_paint_extruder_colors"])
    assert "#808080" in palette.values()
    assert "#FFFFFF" in palette.values()
    assert len(texture._height_palette_keys(mesh)) == 2

    pixels = [round(value * 255) for value in image.pixels[:]]
    rgb = set(zip(pixels[0::4], pixels[1::4], pixels[2::4]))
    assert (128, 128, 128) in rgb
    assert (255, 255, 255) in rgb


def test_flat_and_noisy_elements_are_manifold_and_sunk():
    _clear_scene()
    obj = _new_peak_map()
    for amplitude in (0.0, 0.2):
        mountain, bottom_world_z = operators._build_mountain_element(
            obj, 0.0, amplitude, 0.5
        )
        assert mountain is not None
        assert all(edge.is_manifold for edge in mountain.edges)
        assert abs(min(vertex.co.z for vertex in mountain.verts) - bottom_world_z) < 1e-6
        assert bottom_world_z < 0.0
        mountain.free()


def test_degenerate_split_leaves_source_unchanged():
    _clear_scene()
    obj = _new_map()
    original = [tuple(vertex.co) for vertex in obj.data.vertices]
    mountain, bottom_world_z = operators._build_mountain_element(
        obj, 5.0, 0.0, 0.5
    )
    assert mountain is None and bottom_world_z is None
    assert [tuple(vertex.co) for vertex in obj.data.vertices] == original


def test_disconnected_peaks_stay_in_one_object():
    mesh = bpy.data.meshes.new("DisconnectedPeaks")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=2.0)
    second = bmesh.ops.create_cube(
        bm, size=2.0, matrix=Matrix.Translation((4.0, 0.0, 0.0))
    )
    assert second["verts"]
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new("DisconnectedPeaks", mesh)
    bpy.context.collection.objects.link(obj)
    mountain, _bottom_world_z = operators._build_mountain_element(
        obj, 0.0, 0.0, 0.5
    )
    assert mountain is not None
    assert all(edge.is_manifold for edge in mountain.edges)
    mountain.free()


def test_split_commit_marks_both_pieces():
    _clear_scene()
    obj = _new_peak_map()
    obj.data.materials.clear()
    obj.data.materials.append(_material("UNUSED", (0.2, 0.2, 0.2)))
    obj.data.materials.append(_material("BASE", (0.1, 0.7, 0.1)))
    for polygon in obj.data.polygons:
        polygon.material_index = 1
    mountain = operators._height_color_material((0.5, 0.5, 0.5))
    mountain_obj = operators._apply_mountain_manifold(
        obj, 0.0, mountain, 0.0, 0.5, 0.12
    )
    assert mountain_obj is not None
    assert obj["lastMountianManifold"] is True
    assert mountain_obj["lastMountianManifold"] is True
    assert obj["mountain_obj_name"] == mountain_obj.name
    assert mountain_obj["mountain_base_name"] == obj.name
    assert obj["ExportGroup"] == 1
    assert mountain_obj["ExportGroup"] == 0
    assert _is_manifold(obj.data)
    assert _is_manifold(mountain_obj.data)
    assert [mat.name for mat in obj.data.materials] == ["BASE"]
    assert [mat.name for mat in mountain_obj.data.materials] == ["MOUNTAIN"]
    assert all(polygon.material_index == 0 for polygon in obj.data.polygons)
    assert all(polygon.material_index == 0 for polygon in mountain_obj.data.polygons)
    mountain_bottom = min(vertex.co.z for vertex in mountain_obj.data.vertices)
    assert abs(mountain_bottom - (-1.0)) < 1e-4
    mountain_bottom_radius = max(
        math.hypot(vertex.co.x, vertex.co.y)
        for vertex in mountain_obj.data.vertices
        if abs(vertex.co.z - mountain_bottom) < 1e-4
    )
    cavity_radius = min(
        math.hypot(vertex.co.x, vertex.co.y)
        for vertex in obj.data.vertices
        if abs(vertex.co.z - mountain_bottom) < 1e-4
    )
    assert cavity_radius > mountain_bottom_radius


def test_manifold_pieces_stack():
    _clear_scene()
    obj = _new_peak_map("StackedPeak")
    tp3d = bpy.context.scene.tp3d
    grey = operators._height_color_material((0.5, 0.5, 0.5))
    white = operators._height_color_material((1.0, 1.0, 1.0))

    mountain = operators._apply_mountain_manifold(obj, -0.5, grey, 0.0, 0.5, 0.12)
    assert mountain is not None
    assert mountain["heightLayerLevel"] == 1

    # The freshly produced piece must itself qualify for another split.
    assert operators._mountain_split_ineligible_reason(mountain, tp3d, True) is None

    cap = operators._apply_mountain_manifold(mountain, 0.8, white, 0.0, 0.5, 0.12)
    assert cap is not None
    assert cap["heightLayerLevel"] == 2
    assert cap["mountain_base_name"] == mountain.name
    # The middle piece keeps its own grey; only the cap is white.
    assert [mat.name for mat in mountain.data.materials] == ["MOUNTAIN"]
    assert [mat.name for mat in cap.data.materials] == ["HEIGHT_FFFFFF"]
    assert [mat.name for mat in obj.data.materials] == ["BASE"]
    assert _is_manifold(obj.data)
    assert _is_manifold(mountain.data)
    assert _is_manifold(cap.data)
    # A re-split piece keeps its separate-piece export grouping.
    assert mountain["ExportGroup"] == 0
    assert cap["ExportGroup"] == 0


def test_manifold_operator_stacks_three_colors():
    _clear_scene()
    base = _new_peak_map("OperatorStackPeak")

    def _apply(selected, threshold, color):
        bpy.ops.object.select_all(action="DESELECT")
        selected.select_set(True)
        bpy.context.view_layer.objects.active = selected
        before = set(bpy.data.objects)
        result = bpy.ops.tp3d.color_mountain(
            mountain_treshold=threshold,
            mountain_color=color,
            color_height_SEM=True,
            mountain_noise=False,
            mountain_noise_amplitude=1.0,
            mountain_noise_scale=0.5,
        )
        assert "FINISHED" in result
        created = [
            obj
            for obj in set(bpy.data.objects) - before
            if obj.get("IsMountainPiece")
        ]
        assert len(created) == 1
        return created[0]

    green = _apply(base, 20, (0.0, 1.0, 0.0))
    grey = _apply(green, 50, (0.5, 0.5, 0.5))
    white = _apply(grey, 80, (1.0, 1.0, 1.0))

    assert [material.name for material in base.data.materials] == ["BASE"]
    assert [material.name for material in green.data.materials] == ["HEIGHT_00FF00"]
    assert [material.name for material in grey.data.materials] == ["MOUNTAIN"]
    assert [material.name for material in white.data.materials] == ["HEIGHT_FFFFFF"]
    assert grey["mountain_base_name"] == green.name
    assert white["mountain_base_name"] == grey.name
    assert [green["heightLayerLevel"], grey["heightLayerLevel"], white["heightLayerLevel"]] == [
        1,
        2,
        3,
    ]
    assert all(_is_manifold(obj.data) for obj in (base, green, grey, white))


def test_material_layers_stack_and_preserve_elements():
    _clear_scene()
    obj = _new_peak_map("MaterialStackPeak")
    water = _material("WATER", (0.0, 0.0, 0.8))
    obj.data.materials.append(water)
    water_index = obj.data.materials.find("WATER")
    bottom_polygon = min(
        obj.data.polygons,
        key=lambda p: sum(obj.data.vertices[v].co.z for v in p.vertices),
    )
    bottom_polygon.material_index = water_index

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    def _apply(threshold, color):
        assert "FINISHED" in bpy.ops.tp3d.color_mountain(
            mountain_treshold=threshold,
            mountain_color=color,
            color_height_SEM=False,
            mountain_noise=False,
            mountain_noise_amplitude=1.0,
            mountain_noise_scale=0.5,
        )

    _apply(30, (0.0, 1.0, 0.0))
    _apply(60, (0.5, 0.5, 0.5))
    _apply(85, (1.0, 1.0, 1.0))

    names = [mat.name for mat in obj.data.materials]
    for expected in ("HEIGHT_00FF00", "MOUNTAIN", "HEIGHT_FFFFFF"):
        assert expected in names, names
    used = {obj.data.materials[p.material_index].name for p in obj.data.polygons}
    assert {"HEIGHT_00FF00", "MOUNTAIN", "HEIGHT_FFFFFF"} <= used, used
    # The painted element colour survives every stacked layer.
    assert "WATER" in used
    assert list(obj[operators._HEIGHT_COLOR_MATERIALS_PROP]) == [
        "HEIGHT_00FF00",
        "MOUNTAIN",
        "HEIGHT_FFFFFF",
    ]


def test_already_applied_map_does_not_abort_selection():
    _clear_scene()
    first = _new_map("AlreadyApplied")
    second = _new_map("NeedsColor")
    threshold = 0.8
    first["lastMountianCut"] = threshold
    first["lastMountianNoiseAmp"] = 0.0
    first["lastMountianNoiseScale"] = 0.5
    first["lastMountianColor"] = (0.5, 0.5, 0.5)

    bpy.ops.object.select_all(action="DESELECT")
    first.select_set(True)
    second.select_set(True)
    bpy.context.view_layer.objects.active = second
    result = bpy.ops.tp3d.color_mountain(
        mountain_treshold=60,
        mountain_color=(0.5, 0.5, 0.5),
        color_height_SEM=False,
        mountain_noise=False,
        mountain_noise_amplitude=1.0,
        mountain_noise_scale=0.5,
    )
    assert "FINISHED" in result
    assert second.get("lastMountianCut") == threshold


_run("operator properties are registered", test_operator_properties_registered)
_run("blank-map eligibility is conservative", test_blank_map_eligibility)
_run("material helper is per color", test_material_helper_is_per_color)
_run("palette slots stack and prune", test_palette_slots_stack_and_prune)
_run("palette ownership restores with undo", test_palette_ownership_restored_with_undo)
_run("texture recolor removes previous pixels", test_texture_recolor_removes_previous_pixels)
_run("texture layers stack", test_texture_layers_stack)
_run(
    "flat and noisy elements are manifold and sunk",
    test_flat_and_noisy_elements_are_manifold_and_sunk,
)
_run("degenerate split is non-destructive", test_degenerate_split_leaves_source_unchanged)
_run("disconnected peaks remain one object", test_disconnected_peaks_stay_in_one_object)
_run("split commit marks both pieces", test_split_commit_marks_both_pieces)
_run("manifold pieces stack", test_manifold_pieces_stack)
_run(
    "manifold operator stacks three colors",
    test_manifold_operator_stacks_three_colors,
)
_run("material layers stack and preserve elements", test_material_layers_stack_and_preserve_elements)
_run("already-applied map does not abort selection", test_already_applied_map_does_not_abort_selection)

_assert_all_passed()
