#!/usr/bin/env python3
"""Extract translatable strings from the TrailPrint3D addon and diff them
against translation.py's existing dictionaries. Also flags text that bypasses
Blender's translation system entirely.

Read-only: never modifies the addon source. Writes one .ods report.

Requires odfpy (for writing the .ods report)
`pip install odfpy`
"""

import ast
from pathlib import Path

from odf.opendocument import OpenDocumentSpreadsheet
from odf.style import Style, TableCellProperties, TableColumnProperties, TextProperties
from odf.table import Table, TableCell, TableColumn, TableRow
from odf.text import P

ADDON_ROOT = Path("./TrailPrint3D")
TRANSLATION_FILE = ADDON_ROOT / "translation.py"
OUTPUT_ODS = "./tp3d-translation-audit.ods"

# Directories/files not part of the addon's own translatable UI surface.
EXCLUDE_DIRS = {"tests", "__pycache__"}
EXCLUDE_FILES = {"translation.py","headless_ui.py", "picker_server.py", "puzzleGenerator.html", "map_generator.html", "map_generator_pe.html","multitile_generator.html","puzzleGenerator_pe.html","slidingPUzzleGenerator.html"} 

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
                    ("f-string still inside _()", self.rel, node.lineno, ast.unparse(arg)[:80])
                )
            else:
                self.needs_review.append(
                    ("non-literal argument to _()", self.rel, node.lineno, ast.unparse(arg)[:80])
                )

        if isinstance(node.func, ast.Attribute) and node.func.attr == "report" and len(node.args) >= 2:
            msg = node.args[1]
            s = const_str(msg)
            if s is not None:
                self.bypasses.append(("self.report", self.rel, node.lineno, s))
            elif isinstance(msg, ast.JoinedStr):
                self.bypasses.append(
                    ("self.report (f-string)", self.rel, node.lineno, ast.unparse(msg)[:100])
                )

        if isinstance(node.func, ast.Attribute) and node.func.attr == "add_warning" and node.args:
            msg = node.args[0]
            s = const_str(msg)
            if s is not None:
                self.bypasses.append(("add_warning", self.rel, node.lineno, s))
            elif isinstance(msg, ast.JoinedStr):
                self.bypasses.append(
                    ("add_warning (f-string)", self.rel, node.lineno, ast.unparse(msg)[:100])
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
                if const_str(node.value) == "TrailPrint3D":
                    continue
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
                    ("raised exception (f-string)", self.rel, node.lineno, f"{exc_name}: {ast.unparse(arg)[:80]}")
                )
        self.generic_visit(node)


def extract_all():
    tracked, bypasses, unwrapped, needs_review = [], [], [], []
    for path in iter_py_files():
        rel = str(path.relative_to(ADDON_ROOT))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
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
    tree = ast.parse(TRANSLATION_FILE.read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "translations_dict":
                    return ast.literal_eval(node.value)
    raise RuntimeError("translations_dict assignment not found in translation.py")


def add_ods_sheet(doc, title, rows, header_style, alt_style):
    table = Table(name=title)
    
    # Pre-calculate column widths based on content
    col_widths = [0] * (len(rows[0]) if rows else 0)
    for row in rows:
        for col_idx, cell_data in enumerate(row):
            col_widths[col_idx] = max(col_widths[col_idx], len(str(cell_data)))
            
    # Add width-styled columns before rows
    for col_idx, char_count in enumerate(col_widths):
        # Roughly 0.25cm per character, cap max width at 15cm for readability
        width_cm = max(2.5, min((char_count + 2) * 0.25, 15.0))
        
        col_style = Style(name=f"{title}_Col_{col_idx}", family="table-column")
        col_style.addElement(TableColumnProperties(columnwidth=f"{width_cm}cm"))
        doc.automaticstyles.addElement(col_style)
        
        table.addElement(TableColumn(stylename=col_style))

    # Populate rows and cells
    for row_idx, row_data in enumerate(rows):
        tr = TableRow()
        for cell_data in row_data:
            if isinstance(cell_data, (int, float)):
                tc = TableCell(valuetype="float", value=str(cell_data))
            else:
                tc = TableCell(valuetype="string")
                
            tc.addElement(P(text=str(cell_data)))
            
            if row_idx == 0:
                tc.setAttribute("stylename", header_style)
            elif row_idx % 2 == 0:
                tc.setAttribute("stylename", alt_style)
                
            tr.addElement(tc)
        table.addElement(tr)
        
    doc.spreadsheet.addElement(table)


def write_ods_report(data, out_path):
    doc = OpenDocumentSpreadsheet()

    # Define Header Style
    header_style = Style(name="HeaderStyle", family="table-cell")
    header_style.addElement(TableCellProperties(backgroundcolor="#3F4B5B"))
    header_style.addElement(TextProperties(fontweight="bold", color="#FFFFFF"))
    doc.automaticstyles.addElement(header_style)

    # Define Alternating Row Style
    alt_style = Style(name="AltStyle", family="table-cell")
    alt_style.addElement(TableCellProperties(backgroundcolor="#F5F7FA"))
    doc.automaticstyles.addElement(alt_style)

    # 1. Overview Sheet
    overview_data = [
        ["Metric", "Count"],
        ["Tracked Strings", len(data["master"])]
    ]
    for lang in data["languages"]:
        overview_data.append([f"[{lang}] Missing", len(data["per_lang_missing"][lang])])
        overview_data.append([f"[{lang}] Dead Keys", len(data["per_lang_dead"][lang])])
    overview_data.extend([
        ["Bypasses", len(data["bypasses"])],
        ["Unwrapped", len(data["unwrapped"])],
        ["Needs Review", len(data["needs_review"])]
    ])
    add_ods_sheet(doc, "Overview", overview_data, header_style, alt_style)

    # 2. Missing Strings Sheet
    missing_data = [["Language", "String", "File", "Line"]]
    for lang in data["languages"]:
        for s in data["per_lang_missing"][lang]:
            info = data["master"].get(s, {})
            missing_data.append([lang, s, info.get("file", ""), info.get("line", "")])
    if len(missing_data) == 1: missing_data.append(["", "None", "", ""])
    add_ods_sheet(doc, "Missing Translations", missing_data, header_style, alt_style)

    # 3. Dead Keys Sheet
    dead_data = [["Language", "String"]]
    for lang in data["languages"]:
        for s in data["per_lang_dead"][lang]:
            dead_data.append([lang, s])
    if len(dead_data) == 1: dead_data.append(["", "None"])
    add_ods_sheet(doc, "Dead Keys", dead_data, header_style, alt_style)

    # 4. Bypasses Sheet
    bypass_data = [["Kind", "File", "Line", "Message"]] + data["bypasses"]
    if len(bypass_data) == 1: bypass_data.append(["", "None", "", ""])
    add_ods_sheet(doc, "Bypasses", bypass_data, header_style, alt_style)

    # 5. Unwrapped Sheet
    unwrapped_data = [["Keyword", "File", "Line", "String"]] + data["unwrapped"]
    if len(unwrapped_data) == 1: unwrapped_data.append(["", "None", "", ""])
    add_ods_sheet(doc, "Unwrapped", unwrapped_data, header_style, alt_style)

    # 6. Needs Review Sheet
    review_data = [["Issue", "File", "Line", "Snippet"]] + data["needs_review"]
    if len(review_data) == 1: review_data.append(["", "None", "", ""])
    add_ods_sheet(doc, "Needs Review", review_data, header_style, alt_style)

    doc.save(out_path)


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

    print(f"\nWriting styled report to {OUTPUT_ODS}...")
    write_ods_report(result, OUTPUT_ODS)
    print("Done.")