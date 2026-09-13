#!/usr/bin/env python3
"""Extract translatable strings from the TrailPrint3D addon and diff them
against translation.py's existing dictionaries. Also flags text that bypasses
Blender's translation system entirely (self.report / add_warning / raised
exceptions), and text that skips the _() wrapper but is passed to a
name=/text=/description=/bl_label/bl_description slot Blender translates
automatically.

Read-only: never modifies the addon source. Writes one .xlsx report.
"""

import ast
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ADDON_ROOT = Path("./TrailPrint3D")
TRANSLATION_FILE = ADDON_ROOT / "translation.py"
OUTPUT_XLSX = "./tp3d-translation-audit.xlsx"

# Directories/files not part of the addon's own translatable UI surface.
EXCLUDE_DIRS = {"tests", "__pycache__"}
EXCLUDE_FILES = {"translation.py"}  # the dictionary itself, not a source of strings

TRANSLATE_KWARGS = {"text", "name", "description"}
BL_CLASS_ATTRS = {"bl_label", "bl_description"}


def iter_py_files():
    for path in ADDON_ROOT.rglob("*.py"):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if path.name in EXCLUDE_FILES:
            continue
        yield path


def is_wrapped_in_gettext(node):
    """True if *node* is a call to _(...) (the pgettext_iface alias)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_"
    )


def const_str(node):
    return (
        node.value
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        else None
    )


class Extractor(ast.NodeVisitor):
    def __init__(self, filepath, rel):
        self.filepath = filepath
        self.rel = rel
        self.tracked = []
        self.bypasses = []
        self.unwrapped = []
        self.needs_review = []

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == "_" and node.args:
            arg = node.args[0]
            s = const_str(arg)
            if s is not None:
                self.tracked.append((s, self.rel, node.lineno))
            elif isinstance(arg, ast.JoinedStr):
                self.needs_review.append(
                    (
                        "f-string still inside _()",
                        self.rel,
                        node.lineno,
                        ast.unparse(arg)[:80],
                    )
                )
            else:
                self.needs_review.append(
                    (
                        "non-literal argument to _()",
                        self.rel,
                        node.lineno,
                        ast.unparse(arg)[:80],
                    )
                )

        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "report"
            and len(node.args) >= 2
        ):
            msg = node.args[1]
            s = const_str(msg)
            if s is not None:
                self.bypasses.append(("self.report", self.rel, node.lineno, s))
            elif isinstance(msg, ast.JoinedStr):
                self.bypasses.append(
                    (
                        "self.report (f-string)",
                        self.rel,
                        node.lineno,
                        ast.unparse(msg)[:100],
                    )
                )

        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_warning"
            and node.args
        ):
            msg = node.args[0]
            s = const_str(msg)
            if s is not None:
                self.bypasses.append(("add_warning", self.rel, node.lineno, s))
            elif isinstance(msg, ast.JoinedStr):
                self.bypasses.append(
                    (
                        "add_warning (f-string)",
                        self.rel,
                        node.lineno,
                        ast.unparse(msg)[:100],
                    )
                )

        for kw in node.keywords:
            if kw.arg in TRANSLATE_KWARGS and not is_wrapped_in_gettext(kw.value):
                s = const_str(kw.value)
                if s:
                    self.unwrapped.append((kw.arg, self.rel, node.lineno, s))

        self.generic_visit(node)

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in BL_CLASS_ATTRS:
                s = const_str(node.value)
                if s:
                    self.unwrapped.append((target.id, self.rel, node.lineno, s))
        self.generic_visit(node)

    def visit_Raise(self, node):
        exc = node.exc
        if isinstance(exc, ast.Call) and exc.args:
            arg = exc.args[0]
            s = const_str(arg)
            exc_name = ast.unparse(exc.func)
            if s is not None:
                self.needs_review.append(
                    ("raised exception", self.rel, node.lineno, f"{exc_name}: {s[:80]}")
                )
            elif isinstance(arg, ast.JoinedStr):
                self.needs_review.append(
                    (
                        "raised exception (f-string)",
                        self.rel,
                        node.lineno,
                        f"{exc_name}: {ast.unparse(arg)[:80]}",
                    )
                )
        self.generic_visit(node)


def extract_all():
    tracked, bypasses, unwrapped, needs_review = [], [], [], []
    for path in iter_py_files():
        rel = str(path.relative_to(ADDON_ROOT))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            needs_review.append(("FILE FAILED TO PARSE", rel, e.lineno or 0, str(e)))
            continue
        ex = Extractor(path, rel)
        ex.visit(tree)
        tracked.extend(ex.tracked)
        bypasses.extend(ex.bypasses)
        unwrapped.extend(ex.unwrapped)
        needs_review.extend(ex.needs_review)
    return tracked, bypasses, unwrapped, needs_review


def load_translation_dict():
    tree = ast.parse(TRANSLATION_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "translations_dict":
                    return ast.literal_eval(node.value)
    raise RuntimeError("translations_dict assignment not found in translation.py")


def style_worksheet(ws):
    """Applies professional styling to an openpyxl worksheet."""
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(
        start_color="3F4B5B", end_color="3F4B5B", fill_type="solid"
    )
    alt_fill = PatternFill(start_color="F5F7FA", end_color="F5F7FA", fill_type="solid")
    border_style = Side(border_style="thin", color="E0E0E0")
    border = Border(
        left=border_style, right=border_style, top=border_style, bottom=border_style
    )

    # Freeze top row
    ws.freeze_panes = "A2"

    # Style header row
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    # Apply alternating colors, borders, and auto-width
    for col in ws.iter_cols(
        min_row=1, max_row=ws.max_row, min_col=1, max_col=ws.max_column
    ):
        max_length = 0
        column_letter = get_column_letter(col[0].column)

        for idx, cell in enumerate(col):
            if cell.row > 1:
                cell.border = border
                if cell.row % 2 == 0:
                    cell.fill = alt_fill

            try:
                max_length = max(max_length, len(str(cell.value)))
            except Exception as e:  # noqa: BLE001
                print(f"Error calculating max length for cell {cell.coordinate}: {e}")

        # Set dynamic width (capped at 60 characters for readability)
        adjusted_width = min((max_length + 2), 60)
        ws.column_dimensions[column_letter].width = adjusted_width

    # Add auto-filters to the header
    ws.auto_filter.ref = ws.dimensions


def write_excel_report(data, out_path):
    wb = openpyxl.Workbook()

    # Overview Sheet
    ws_overview = wb.active
    ws_overview.title = "Overview"
    ws_overview.append(["Metric", "Count"])
    ws_overview.append(["Tracked Strings", len(data["master"])])

    for lang in data["languages"]:
        ws_overview.append([f"[{lang}] Missing", len(data["per_lang_missing"][lang])])
        ws_overview.append([f"[{lang}] Dead Keys", len(data["per_lang_dead"][lang])])

    ws_overview.append(["Bypasses", len(data["bypasses"])])
    ws_overview.append(["Unwrapped", len(data["unwrapped"])])
    ws_overview.append(["Needs Review", len(data["needs_review"])])
    style_worksheet(ws_overview)

    # Missing Strings Sheet
    ws_missing = wb.create_sheet("Missing Translations")
    ws_missing.append(["Language", "String", "File", "Line"])
    for lang in data["languages"]:
        for s in data["per_lang_missing"][lang]:
            info = data["master"].get(s, {})
            ws_missing.append([lang, s, info.get("file", ""), info.get("line", "")])
    style_worksheet(ws_missing)

    # Dead Keys Sheet
    ws_dead = wb.create_sheet("Dead Keys")
    ws_dead.append(["Language", "String"])
    for lang in data["languages"]:
        for s in data["per_lang_dead"][lang]:
            ws_dead.append([lang, s])
    style_worksheet(ws_dead)

    # Bypasses Sheet
    ws_bypass = wb.create_sheet("Bypasses")
    ws_bypass.append(["Kind", "File", "Line", "Message"])
    for b in data["bypasses"]:
        ws_bypass.append(b)
    style_worksheet(ws_bypass)

    # Unwrapped Sheet
    ws_unwrapped = wb.create_sheet("Unwrapped")
    ws_unwrapped.append(["Keyword", "File", "Line", "String"])
    for u in data["unwrapped"]:
        ws_unwrapped.append(u)
    style_worksheet(ws_unwrapped)

    # Needs Review Sheet
    ws_review = wb.create_sheet("Needs Review")
    ws_review.append(["Issue", "File", "Line", "Snippet"])
    for r in data["needs_review"]:
        ws_review.append(r)
    style_worksheet(ws_review)

    wb.save(out_path)


def main():
    tracked, bypasses, unwrapped, needs_review = extract_all()
    translations = load_translation_dict()
    languages = sorted(translations.keys())

    master = {}
    for s, rel, lineno in tracked:
        if s not in master:
            master[s] = {"file": rel, "line": lineno, "count": 0}
        master[s]["count"] += 1

    per_lang_missing = {lang: [] for lang in languages}
    per_lang_dead = {lang: [] for lang in languages}
    for lang in languages:
        lang_dict = translations[lang]
        keys = {k[1] for k in lang_dict}
        for s in master:
            if s not in keys:
                per_lang_missing[lang].append(s)
        for s in keys:
            if s not in master:
                per_lang_dead[lang].append(s)

    return {
        "master": master,
        "languages": languages,
        "translations": translations,
        "per_lang_missing": per_lang_missing,
        "per_lang_dead": per_lang_dead,
        "bypasses": bypasses,
        "unwrapped": unwrapped,
        "needs_review": needs_review,
    }


if __name__ == "__main__":
    result = main()

    print(f"Tracked (unique English strings): {len(result['master'])}")
    print(f"Languages found: {result['languages']}")
    for lang in result["languages"]:
        print(
            f"  {lang}: {len(result['per_lang_missing'][lang])} missing, "
            f"{len(result['per_lang_dead'][lang])} dead keys"
        )
    print(f"Bypasses translation entirely: {len(result['bypasses'])}")
    print(f"Unwrapped but likely fine: {len(result['unwrapped'])}")
    print(f"Needs manual review: {len(result['needs_review'])}")

    print(f"\nWriting styled report to {OUTPUT_XLSX}...")
    write_excel_report(result, OUTPUT_XLSX)
    print("Done.")
