"""Parsers that turn the LLM's Markdown output into structured rows.

The app asks the model for Markdown (lists and tables). These helpers convert
that text into lists of dicts so the UI can show DataFrames and the exporters
can write clean Excel/CSV files. Every parser degrades gracefully: if the
model returns plain text instead of a table, each non-empty line becomes a row.
"""

import re

# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def _clean(text):
    """Strip Markdown decoration from a cell/line."""
    text = (text or "").strip()
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # **bold**
    text = re.sub(r"`(.+?)`", r"\1", text)        # `code`
    text = text.strip(" -*•\t")
    return text.strip()


def _split_table_row(line):
    """Split one Markdown table row into cells. Handles leading/trailing |."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _is_separator_row(cells):
    """True for the |---|---| row under a Markdown table header."""
    return all(re.fullmatch(r":?-{2,}:?", c or "-") for c in cells) if cells else False


def parse_markdown_table(text):
    """Return (headers, rows) for the first Markdown table in *text*.

    headers is a list of lower-cased header names, rows a list of lists.
    Returns ([], []) when no table is found.
    """
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        if "|" not in line:
            continue
        headers = [_clean(c).lower() for c in _split_table_row(line)]
        # The next non-empty line should be the separator row.
        rows = []
        j = i + 1
        if j < len(lines) and _is_separator_row(_split_table_row(lines[j])):
            j += 1
        while j < len(lines) and "|" in lines[j]:
            cells = _split_table_row(lines[j])
            if not _is_separator_row(cells):
                # Pad / trim to header width.
                cells = (cells + [""] * len(headers))[: len(headers)]
                if any(cells):
                    rows.append(cells)
            j += 1
        if rows:
            return headers, rows
    return [], []


def _find_column(headers, *keywords):
    """Index of the first header containing any keyword, else -1."""
    for idx, header in enumerate(headers):
        for kw in keywords:
            if kw in header:
                return idx
    return -1


def _lines(text):
    """Non-empty, cleaned lines with list markers removed."""
    out = []
    for raw in (text or "").splitlines():
        line = _clean(raw)
        if line and not line.startswith("#"):
            out.append(line)
    return out


# ---------------------------------------------------------------------------
# User stories
# ---------------------------------------------------------------------------

_STORY_RE = re.compile(
    r"(?:(US[-\s]?\d+)\s*[:\-–]?\s*)?"
    r"As a\s+(?P<role>.+?)\s*,?\s*I want\s+(?P<want>.+?)\s*,?\s*"
    r"(?:so that|in order to)\s+(?P<benefit>.+)$",
    re.IGNORECASE,
)


def parse_user_stories(text):
    """Parse user stories into [{id, role, want, benefit, story}]."""
    rows = []
    for line in _lines(text):
        if "|" in line:
            continue  # table rows handled below
        m = _STORY_RE.search(line)
        if m:
            rows.append(
                {
                    "id": (m.group(1) or f"US-{len(rows) + 1:02d}").replace(" ", "-").upper(),
                    "role": _clean(m.group("role")),
                    "want": _clean(m.group("want")),
                    "benefit": _clean(m.group("benefit")),
                    "story": line,
                }
            )
        elif len(line) > 12:
            rows.append(
                {
                    "id": f"US-{len(rows) + 1:02d}",
                    "role": "",
                    "want": "",
                    "benefit": "",
                    "story": line,
                }
            )
    if rows:
        return rows

    # Fallback: Markdown table with story text in some column.
    headers, table = parse_markdown_table(text)
    if table:
        id_i = _find_column(headers, "id")
        story_i = _find_column(headers, "story", "user story", "description", "text")
        if story_i < 0:
            story_i = 0
        for n, cells in enumerate(table, start=1):
            rows.append(
                {
                    "id": cells[id_i] if id_i >= 0 and cells[id_i] else f"US-{n:02d}",
                    "role": "",
                    "want": "",
                    "benefit": "",
                    "story": cells[story_i],
                }
            )
    return rows


# ---------------------------------------------------------------------------
# Acceptance criteria (Given / When / Then)
# ---------------------------------------------------------------------------

_GWT_RE = re.compile(
    r"(?:(AC[-\s]?\d+)\s*[:\-–]?\s*)?"
    r"Given\s+(?P<given>.+?)\s*,?\s*When\s+(?P<when>.+?)\s*,?\s*Then\s+(?P<then>.+)$",
    re.IGNORECASE,
)


def parse_acceptance_criteria(text):
    """Parse GWT criteria into [{id, given, when, then, criterion}]."""
    rows = []
    for line in _lines(text):
        if "|" in line:
            continue
        m = _GWT_RE.search(line)
        if m:
            rows.append(
                {
                    "id": (m.group(1) or f"AC-{len(rows) + 1:02d}").replace(" ", "-").upper(),
                    "given": _clean(m.group("given")),
                    "when": _clean(m.group("when")),
                    "then": _clean(m.group("then")),
                    "criterion": line,
                }
            )
        elif len(line) > 12:
            rows.append(
                {
                    "id": f"AC-{len(rows) + 1:02d}",
                    "given": "",
                    "when": "",
                    "then": "",
                    "criterion": line,
                }
            )
    if rows:
        return rows

    headers, table = parse_markdown_table(text)
    if table:
        id_i = _find_column(headers, "id")
        g_i = _find_column(headers, "given")
        w_i = _find_column(headers, "when")
        t_i = _find_column(headers, "then")
        c_i = _find_column(headers, "criterion", "criteria", "description")
        for n, cells in enumerate(table, start=1):
            rows.append(
                {
                    "id": cells[id_i] if id_i >= 0 and cells[id_i] else f"AC-{n:02d}",
                    "given": cells[g_i] if g_i >= 0 else "",
                    "when": cells[w_i] if w_i >= 0 else "",
                    "then": cells[t_i] if t_i >= 0 else "",
                    "criterion": cells[c_i] if c_i >= 0 else " | ".join(cells),
                }
            )
    return rows


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

def parse_test_cases(text):
    """Parse test cases into [{id, scenario, steps, expected, priority}]."""
    headers, table = parse_markdown_table(text)
    rows = []
    if table:
        id_i = _find_column(headers, "id", "tc", "test case")
        scen_i = _find_column(headers, "scenario", "title", "name", "description")
        steps_i = _find_column(headers, "step")
        exp_i = _find_column(headers, "expected", "result")
        pri_i = _find_column(headers, "priority", "severity")
        for n, cells in enumerate(table, start=1):
            rows.append(
                {
                    "id": cells[id_i] if id_i >= 0 and cells[id_i] else f"TC-{n:03d}",
                    "scenario": cells[scen_i] if scen_i >= 0 else "",
                    "steps": cells[steps_i] if steps_i >= 0 else "",
                    "expected": cells[exp_i] if exp_i >= 0 else "",
                    "priority": cells[pri_i] if pri_i >= 0 else "",
                }
            )
        return rows

    for line in _lines(text):
        if len(line) > 12:
            rows.append(
                {
                    "id": f"TC-{len(rows) + 1:03d}",
                    "scenario": line,
                    "steps": "",
                    "expected": "",
                    "priority": "",
                }
            )
    return rows
