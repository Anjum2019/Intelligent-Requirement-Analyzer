"""Export analysed data to Excel (.xlsx) and CSV files.

Excel: one workbook with a Summary sheet plus one sheet per section
(User Stories, Acceptance Criteria, Test Cases), formatted headers, frozen
panes, auto-filters and readable column widths (openpyxl).

CSV: one file per section (stdlib csv module, UTF-8 with BOM so Excel opens
it cleanly). The UI returns all CSVs at once for download.
"""

import csv
import re
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

EXPORT_DIR = Path(__file__).resolve().parent / "exports"

HEADER_FILL = PatternFill("solid", fgColor="0EA5E9")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
TITLE_FONT = Font(bold=True, color="0F172A", size=14)
SUBTITLE_FONT = Font(color="475569", size=10)
WRAP = Alignment(wrap_text=True, vertical="top")

# section key -> (sheet title, [(column header, dict key), ...], column width)
SECTIONS = {
    "stories": (
        "User Stories",
        [("ID", "id"), ("Role", "role"), ("I want", "want"), ("So that", "benefit"), ("Full Story", "story")],
        [10, 22, 42, 42, 60],
    ),
    "acceptance": (
        "Acceptance Criteria",
        [("ID", "id"), ("Given", "given"), ("When", "when"), ("Then", "then"), ("Full Criterion", "criterion")],
        [10, 40, 40, 40, 60],
    ),
    "testcases": (
        "Test Cases",
        [("ID", "id"), ("Scenario", "scenario"), ("Steps", "steps"), ("Expected Result", "expected"), ("Priority", "priority")],
        [12, 45, 50, 45, 12],
    ),
}


def _slug(name, fallback="analysis"):
    slug = re.sub(r"[^A-Za-z0-9]+", "_", (name or "").strip()).strip("_")
    return slug or fallback


def _stamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ensure_dir():
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    return EXPORT_DIR


def _write_sheet(ws, title, columns, rows, widths):
    ws.title = title
    ws.append([label for label, _ in columns])
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for row in rows:
        ws.append([row.get(key, "") for _, key in columns])
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = WRAP
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.sheet_properties.pageSetUpPr.fitToPage = True


def build_excel(data, meta):
    """Build a formatted .xlsx workbook. Returns the file path as a string."""
    _ensure_dir()
    wb = Workbook()

    # --- Summary sheet -----------------------------------------------------
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = "Intelligent Requirement Analyzer — Analysis Report"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Project: {meta.get('project', 'Untitled')}   |   Source: {meta.get('source', '—')}"
    ws["A2"].font = SUBTITLE_FONT
    ws["A3"] = f"Generated: {meta.get('generated', datetime.now().strftime('%Y-%m-%d %H:%M'))}   |   Model: {meta.get('model', 'openai/gpt-oss-120b (Groq)')}"
    ws["A3"].font = SUBTITLE_FONT

    counts = {key: len(data.get(key, [])) for key in SECTIONS}
    summary_rows = [
        ("Document pages", meta.get("pages", "—")),
        ("Characters analysed", meta.get("characters", "—")),
        ("User stories", counts["stories"]),
        ("Acceptance criteria", counts["acceptance"]),
        ("Test cases", counts["testcases"]),
        ("Total items", sum(counts.values())),
    ]
    ws.append([])
    ws.append(["Metric", "Value"])
    for cell in ws[5]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
    for label, value in summary_rows:
        ws.append([label, value])
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 22
    ws.freeze_panes = "A6"

    # --- One sheet per section --------------------------------------------
    for key, (title, columns, widths) in SECTIONS.items():
        rows = data.get(key, [])
        if not rows:
            continue
        _write_sheet(wb.create_sheet(), title, columns, rows, widths)

    path = _ensure_dir() / f"{_slug(meta.get('project'))}_analysis_{_stamp()}.xlsx"
    wb.save(path)
    return str(path)


def build_csvs(data, meta):
    """Build one CSV per non-empty section. Returns a list of file paths."""
    _ensure_dir()
    stamp = _stamp()
    base = _slug(meta.get("project"))
    paths = []
    for key, (title, columns, _widths) in SECTIONS.items():
        rows = data.get(key, [])
        if not rows:
            continue
        filename = f"{base}_{title.lower().replace(' ', '_')}_{stamp}.csv"
        path = _ensure_dir() / filename
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.writer(fh)
            writer.writerow([label for label, _ in columns])
            for row in rows:
                writer.writerow([row.get(k, "") for _, k in columns])
        paths.append(str(path))
    return paths
