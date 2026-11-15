"""Intelligent Requirement Analyzer — AI-powered BA workbench.

Upload a requirements PDF and get three structured drafts back (User Stories,
Acceptance Criteria, Test Cases), each shown as a searchable table plus the
raw AI text, and downloadable as Excel (.xlsx) or CSV files.

Run:  python intelligent_requirement_analyzer.py
"""

import os
import traceback
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import gradio as gr

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_community.document_loaders import PyPDFLoader

from exporters import build_csvs, build_excel
from parsers import parse_acceptance_criteria, parse_test_cases, parse_user_stories
import sample_data

# Folder this script lives in, so the assets folder is found no matter which
# directory the app is started from.
BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"

# Load environment variables (GROQ_API_KEY comes from the .env file next to this script)
load_dotenv()

GROQ_API_KEY = (os.getenv("GROQ_API_KEY") or "").strip()
MODEL_NAME = "openai/gpt-oss-120b"

MISSING_KEY_MESSAGE = (
    "GROQ_API_KEY is not set. Copy .env.example to .env, put your Groq API key "
    "in it, then restart the app."
)

# ChatGroq() raises an error when there is no API key, which stops the whole app
# from starting. So it is only created when a key is present; without one the page
# still opens (with sample data) and the Status box says what is missing.
llm = None
if GROQ_API_KEY:
    llm = ChatGroq(api_key=GROQ_API_KEY, model=MODEL_NAME, temperature=0)

# ---------------------------------------------------------------------------
# Section definitions: key -> (tab label, DataFrame headers, dict keys)
# ---------------------------------------------------------------------------

SECTIONS = {
    "stories": ("📖 User Stories", ["ID", "Role", "I want", "So that", "Full Story"],
                ["id", "role", "want", "benefit", "story"]),
    "acceptance": ("✅ Acceptance Criteria", ["ID", "Given", "When", "Then", "Full Criterion"],
                   ["id", "given", "when", "then", "criterion"]),
    "testcases": ("🧪 Test Cases", ["ID", "Scenario", "Steps", "Expected Result", "Priority"],
                  ["id", "scenario", "steps", "expected", "priority"]),
}

PARSERS = {
    "stories": parse_user_stories,
    "acceptance": parse_acceptance_criteria,
    "testcases": parse_test_cases,
}

PLACEHOLDER = "_No data yet — upload a PDF and run an analysis, or load the sample._"


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _rows_to_lists(rows, keys):
    return [[row.get(k, "") for k in keys] for row in rows]


def _build_state(meta, markdowns):
    """Parse Markdown outputs into structured rows and bundle everything."""
    rows = {key: PARSERS[key](markdowns.get(key, "")) for key in SECTIONS}
    return {"meta": meta, "markdown": dict(markdowns), "rows": rows}


def _empty_state():
    return {"meta": {}, "markdown": {k: "" for k in SECTIONS},
            "rows": {k: [] for k in SECTIONS}}


def _kpi_html(state):
    meta = state.get("meta", {})
    rows = state.get("rows", {})
    total_items = sum(len(rows.get(k, [])) for k in SECTIONS)
    cards = [
        ("📄", "Pages", meta.get("pages", "—"), "in source document"),
        ("📖", "User Stories", len(rows.get("stories", [])), "generated"),
        ("✅", "Acceptance Criteria", len(rows.get("acceptance", [])), "generated"),
        ("🧪", "Test Cases", len(rows.get("testcases", [])), "generated"),
        ("📋", "Total Items", total_items or "—", "across all sections"),
    ]
    html = '<div class="kpi-strip">'
    for icon, label, value, sub in cards:
        html += (
            f'<div class="kpi-card"><div class="kpi-icon">{icon}</div>'
            f'<div class="kpi-value">{value}</div>'
            f'<div class="kpi-label">{label}</div>'
            f'<div class="kpi-sub">{sub}</div></div>'
        )
    return html + "</div>"


def _overview_md(state):
    meta = state.get("meta", {})
    rows = state.get("rows", {})
    if not meta:
        return "## Overview\n\n" + PLACEHOLDER
    return f"""## Overview

| | |
| --- | --- |
| **Project** | {meta.get('project', '—')} |
| **Source document** | {meta.get('source', '—')} |
| **Pages / characters analysed** | {meta.get('pages', '—')} / {meta.get('characters', '—')} |
| **Generated** | {meta.get('generated', '—')} |
| **Model** | {meta.get('model', MODEL_NAME + ' (Groq)')} |

### What was generated

| Section | Items |
| --- | --- |
| 📖 User Stories | {len(rows.get('stories', []))} |
| ✅ Acceptance Criteria | {len(rows.get('acceptance', []))} |
| 🧪 Test Cases | {len(rows.get('testcases', []))} |

### Next steps
1. Review each tab — tables are searchable, raw AI text is in the collapsible panel.
2. Download the results with **Export to Excel** (Summary sheet + one sheet per section) or **Export to CSV** (one file per section).
"""


def _doc_info_md(state):
    meta = state.get("meta", {})
    if not meta:
        return "No document loaded yet."
    return (
        f"**File:** {meta.get('source', '—')}  \n"
        f"**Pages:** {meta.get('pages', '—')}  ·  "
        f"**Characters analysed:** {meta.get('characters', '—')}  \n"
        f"**Analysed:** {meta.get('generated', '—')}"
    )


def _render_outputs(state, status_msg):
    """Map a state dict to the full tuple of UI outputs (order matters)."""
    markdowns = state.get("markdown", {})
    rows = state.get("rows", {})
    outputs = [
        status_msg,
        _kpi_html(state),
        _doc_info_md(state),
        _overview_md(state),
    ]
    for key in SECTIONS:
        _label, headers, keys = SECTIONS[key]
        outputs.append(_rows_to_lists(rows.get(key, []), keys))
        outputs.append(markdowns.get(key, "") or PLACEHOLDER)
    outputs.append(state)
    outputs.append("Exports are ready — files appear below after you click an export button.")
    return tuple(outputs)


def _empty_outputs(status_msg):
    return _render_outputs(_empty_state(), status_msg)


def _filter_rows(section, query, state):
    """Search-filter one section's table."""
    if not state:
        return []
    _label, _headers, keys = SECTIONS[section]
    rows = state.get("rows", {}).get(section, [])
    q = (query or "").strip().lower()
    if q:
        rows = [r for r in rows
                if any(q in str(r.get(k, "")).lower() for k in keys)]
    return _rows_to_lists(rows, keys)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

PROMPTS = {
    "stories": (
        "You are a Senior Business Analyst. From the requirement document below, "
        "generate detailed User Stories. Return ONLY a Markdown list, one story per line, "
        "in exactly this format, with no introduction or conclusion:\n"
        "- **US-01** As a <role>, I want <action>, so that <benefit>\n\n"
        "Document:\n{text}"
    ),
    "acceptance": (
        "Generate Acceptance Criteria in Given/When/Then format. Return ONLY a Markdown "
        "list, one criterion per line, in exactly this format, with no introduction:\n"
        "- **AC-01** Given <context>, When <action>, Then <result>\n\n"
        "Document:\n{text}"
    ),
    "testcases": (
        "Generate Functional Test Cases. Return ONLY a Markdown table with exactly these "
        "columns: ID | Scenario | Steps | Expected Result | Priority. No introduction.\n\n"
        "Document:\n{text}"
    ),
}


def analyze_document(pdf_file, project_name, sections, state):
    print("Button Clicked")

    if pdf_file is None:
        msg = "⚠️ No file uploaded — choose a PDF first."
        return _render_outputs(state, msg) if state else _empty_outputs(msg)

    if llm is None:
        msg = "⚠️ " + MISSING_KEY_MESSAGE
        return _render_outputs(state, msg) if state else _empty_outputs(msg)

    try:
        loader = PyPDFLoader(pdf_file.name)
        pages = loader.load()
        document_text = "\n\n".join(page.page_content for page in pages)[:15000]

        if len(document_text.strip()) < 100:
            msg = ("⚠️ No selectable text found in this PDF (it may be a scanned/image PDF). "
                   "Run OCR first, or upload a PDF with real text.")
            return _render_outputs(state, msg) if state else _empty_outputs(msg)

        selected = set(sections or [])
        markdowns = {}
        for key in SECTIONS:
            if key not in selected:
                markdowns[key] = "_Not generated — this section was not selected._"
                continue
            markdowns[key] = llm.invoke(PROMPTS[key].format(text=document_text)).content

    except Exception as error:
        # Without this, Gradio only shows a generic "Error" and the real reason
        # (rejected API key, rate limit, no connection, unreadable PDF, ...) is
        # visible only in the terminal. Show it in the Status box as well.
        traceback.print_exc()
        msg = f"❌ Analysis failed - {type(error).__name__}: {error}"
        return _render_outputs(state, msg) if state else _empty_outputs(msg)

    meta = {
        "project": (project_name or "").strip() or "Untitled Project",
        "source": Path(pdf_file.name).name,
        "pages": len(pages),
        "characters": len(document_text),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "model": MODEL_NAME + " (Groq)",
    }
    new_state = _build_state(meta, markdowns)
    status_msg = f"✅ Analysis complete — {meta['source']} ({len(pages)} pages). Review the tabs or export the results."
    return _render_outputs(new_state, status_msg)


def load_sample():
    meta = dict(sample_data.SAMPLE_META)
    meta["generated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    markdowns = {
        "stories": sample_data.SAMPLE_STORIES,
        "acceptance": sample_data.SAMPLE_ACCEPTANCE,
        "testcases": sample_data.SAMPLE_TESTCASES,
    }
    state = _build_state(meta, markdowns)
    return _render_outputs(state, "👋 Sample analysis loaded (Loan Management System). Upload your own PDF to analyse it for real.")


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

def export_excel(state):
    if not state or not any(state.get("rows", {}).values()):
        return None, "⚠️ Nothing to export yet — run an analysis or load the sample first."
    try:
        path = build_excel(state["rows"], state.get("meta", {}))
        return path, f"✅ Excel workbook ready: {Path(path).name} (Summary + User Stories, Acceptance Criteria, Test Cases)."
    except Exception as error:
        traceback.print_exc()
        return None, f"❌ Excel export failed - {type(error).__name__}: {error}"


def export_csv(state):
    if not state or not any(state.get("rows", {}).values()):
        return None, "⚠️ Nothing to export yet — run an analysis or load the sample first."
    try:
        paths = build_csvs(state["rows"], state.get("meta", {}))
        if not paths:
            return None, "⚠️ No data to export."
        return paths, f"✅ {len(paths)} CSV file(s) ready — one per section. Click a file below to download."
    except Exception as error:
        traceback.print_exc()
        return None, f"❌ CSV export failed - {type(error).__name__}: {error}"


# ---------------------------------------------------------------------------
# Initial state: sample data so the workbench is realistic on first open
# ---------------------------------------------------------------------------

_initial_meta = dict(sample_data.SAMPLE_META)
_initial_meta["generated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
initial_state = _build_state(_initial_meta, {
    "stories": sample_data.SAMPLE_STORIES,
    "acceptance": sample_data.SAMPLE_ACCEPTANCE,
    "testcases": sample_data.SAMPLE_TESTCASES,
})
_initial = _render_outputs(
    initial_state,
    "👋 Showing sample analysis (Loan Management System). Upload a PDF and press "
    "Analyze Requirement to analyse your own document."
    + ("" if llm else "  ·  " + MISSING_KEY_MESSAGE),
)
(_init_status, _init_kpi, _init_docinfo, _init_overview,
 _init_stories_df, _init_stories_md,
 _init_acceptance_df, _init_acceptance_md,
 _init_testcases_df, _init_testcases_md,
 _init_state, _init_export_status) = _initial

_api_pill = ('<span class="pill pill-ok">● API connected</span>' if llm
             else '<span class="pill pill-warn">● API key not configured</span>')

header_html = f"""
<div class="ira-header">
  <div class="ira-header-left">
    <div class="ira-logo">📋</div>
    <div>
      <div class="ira-title">Intelligent Requirement Analyzer</div>
      <div class="ira-subtitle">AI-powered BA workbench — User Stories · Acceptance Criteria · Test Cases</div>
    </div>
  </div>
  <div class="ira-header-right">
    <span class="pill pill-model">Model: {MODEL_NAME} · Groq</span>
    {_api_pill}
  </div>
</div>
"""

# ---------------------------------------------------------------------------
# Custom CSS — professional light theme, no global colour overrides
# ---------------------------------------------------------------------------

custom_css = """
.gradio-container {
    background:
        linear-gradient(rgba(248,250,252,0.88), rgba(248,250,252,0.88)),
        url("BACKGROUND_IMAGE_URL");
    background-size: cover;
    background-position: center;
    background-attachment: fixed;
    min-height: 100vh;
    font-family: "Segoe UI", system-ui, -apple-system, sans-serif;
}

/* ---------- Header banner ---------- */
.ira-header {
    display: flex; justify-content: space-between; align-items: center;
    flex-wrap: wrap; gap: 12px;
    background: linear-gradient(135deg, #0369a1, #0ea5e9);
    color: #fff; border-radius: 16px; padding: 18px 22px;
    box-shadow: 0 8px 24px rgba(2,132,199,0.25);
    margin-bottom: 14px;
}
.ira-header-left { display: flex; align-items: center; gap: 14px; }
.ira-logo {
    font-size: 30px; background: rgba(255,255,255,0.18);
    border-radius: 12px; padding: 8px 12px;
}
.ira-title { font-size: 24px; font-weight: 800; letter-spacing: 0.2px; }
.ira-subtitle { font-size: 13px; opacity: 0.92; margin-top: 2px; }
.ira-header-right { display: flex; gap: 8px; flex-wrap: wrap; }
.pill {
    font-size: 12px; font-weight: 700; border-radius: 999px; padding: 5px 12px;
}
.pill-model { background: rgba(255,255,255,0.18); color: #fff; }
.pill-ok { background: #dcfce7; color: #166534; }
.pill-warn { background: #fef3c7; color: #92400e; }

/* ---------- KPI cards ---------- */
.kpi-strip { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.kpi-card {
    flex: 1 1 150px; background: rgba(255,255,255,0.95);
    border: 1px solid #e2e8f0; border-radius: 14px; padding: 14px 16px;
    box-shadow: 0 4px 14px rgba(15,23,42,0.06); position: relative;
}
.kpi-icon { position: absolute; top: 12px; right: 14px; font-size: 20px; opacity: 0.85; }
.kpi-value { font-size: 28px; font-weight: 800; color: #0f172a; }
.kpi-label { font-size: 13px; font-weight: 700; color: #334155; margin-top: 2px; }
.kpi-sub { font-size: 11px; color: #64748b; }

/* ---------- Panels ---------- */
.block {
    background: rgba(255,255,255,0.94) !important;
    border-radius: 16px !important;
    border: 1px solid #e2e8f0 !important;
    box-shadow: 0 4px 16px rgba(15,23,42,0.06) !important;
}

/* ---------- Buttons ---------- */
button.primary {
    background: linear-gradient(135deg, #0284c7, #0ea5e9) !important;
    color: #fff !important; font-weight: 800 !important;
    border-radius: 12px !important; padding: 12px !important;
    transition: transform 0.15s ease, box-shadow 0.15s ease;
}
button.primary:hover { transform: translateY(-1px); box-shadow: 0 6px 16px rgba(2,132,199,0.35); }
button.secondary { border-radius: 12px !important; font-weight: 700 !important; }

/* ---------- Tabs ---------- */
[role="tab"] {
    border-radius: 10px !important; font-weight: 700 !important;
    color: #334155 !important; background: #f1f5f9 !important;
}
[role="tab"][aria-selected="true"] {
    background: #0ea5e9 !important; color: #fff !important;
}

/* ---------- Tables & markdown ---------- */
table { font-size: 13px; }
table th { background: #0ea5e9 !important; color: #fff !important; font-weight: 700 !important; }
table td { color: #1e293b !important; }
.markdown { background: #fff !important; border-radius: 12px; padding: 14px; }
.markdown p, .markdown li { color: #1e293b !important; }

/* ---------- Status ---------- */
textarea[readonly] {
    background: #f0f9ff !important; color: #0f172a !important;
    font-weight: 600 !important; border: 1px solid #bae6fd !important;
}

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: #7dd3fc; border-radius: 10px; }

@media (max-width: 768px) {
    .ira-title { font-size: 19px; }
}
"""

custom_css = custom_css.replace(
    "BACKGROUND_IMAGE_URL",
    "/gradio_api/file=" + quote((ASSETS_DIR / "office_background.jpg").as_posix()),
)

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

with gr.Blocks(
    title="Intelligent Requirement Analyzer",
    theme=gr.themes.Soft(primary_hue="sky", secondary_hue="blue", neutral_hue="slate"),
    css=custom_css,
) as demo:

    gr.HTML(header_html)
    kpi_html = gr.HTML(_init_kpi)

    with gr.Row():
        # ---------------- Left: input + options + export ----------------
        with gr.Column(scale=1, min_width=300):
            with gr.Group():
                gr.Markdown("### 1 · Upload Document")
                pdf_input = gr.File(
                    label="Requirement PDF (.pdf)",
                    file_types=[".pdf"],
                    type="filepath",
                )
                project_input = gr.Textbox(
                    label="Project name (used in exports)",
                    placeholder="e.g. Loan Management System",
                )
                doc_info = gr.Markdown(_init_docinfo)

            with gr.Group():
                gr.Markdown("### 2 · Analysis Options")
                sections_input = gr.CheckboxGroup(
                    label="Sections to generate",
                    choices=[
                        ("stories", "📖 User Stories"),
                        ("acceptance", "✅ Acceptance Criteria"),
                        ("testcases", "🧪 Test Cases"),
                    ],
                    value=["stories", "acceptance", "testcases"],
                )

            analyze_btn = gr.Button("🚀 Analyze Requirement", variant="primary")
            sample_btn = gr.Button("📋 Load Sample Analysis", variant="secondary")

            status_output = gr.Textbox(
                value=_init_status, label="Status", interactive=False, lines=3,
            )

            with gr.Group():
                gr.Markdown("### 3 · Export Results")
                excel_btn = gr.Button("📗 Export to Excel (.xlsx)", variant="primary")
                excel_output = gr.File(label="Excel workbook", file_count="single")
                csv_btn = gr.Button("📘 Export to CSV", variant="secondary")
                csv_output = gr.File(label="CSV files (one per section)", file_count="multiple")
                export_status = gr.Textbox(
                    value=_init_export_status, label="Export status",
                    interactive=False, lines=2,
                )
                gr.Markdown(
                    "Excel = Summary sheet + User Stories, Acceptance Criteria and "
                    "Test Cases sheets (formatted, filters on). "
                    "CSV = one file per section, ready for Excel / Jira / TestRail."
                )

        # ---------------- Right: results ----------------
        with gr.Column(scale=3):
            with gr.Tabs():
                with gr.Tab("📋 Overview"):
                    overview_md = gr.Markdown(_init_overview)

                with gr.Tab("📖 User Stories"):
                    stories_search = gr.Textbox(
                        label="🔍 Search stories", placeholder="Filter rows…",
                    )
                    stories_df = gr.Dataframe(
                        headers=SECTIONS["stories"][1], value=_init_stories_df,
                        interactive=False, wrap=True, label="User Stories",
                    )
                    with gr.Accordion("View raw AI output", open=False):
                        stories_md = gr.Markdown(_init_stories_md)

                with gr.Tab("✅ Acceptance Criteria"):
                    acceptance_search = gr.Textbox(
                        label="🔍 Search criteria", placeholder="Filter rows…",
                    )
                    acceptance_df = gr.Dataframe(
                        headers=SECTIONS["acceptance"][1], value=_init_acceptance_df,
                        interactive=False, wrap=True, label="Acceptance Criteria",
                    )
                    with gr.Accordion("View raw AI output", open=False):
                        acceptance_md = gr.Markdown(_init_acceptance_md)

                with gr.Tab("🧪 Test Cases"):
                    testcases_search = gr.Textbox(
                        label="🔍 Search test cases", placeholder="Filter rows…",
                    )
                    testcases_df = gr.Dataframe(
                        headers=SECTIONS["testcases"][1], value=_init_testcases_df,
                        interactive=False, wrap=True, label="Test Cases",
                    )
                    with gr.Accordion("View raw AI output", open=False):
                        testcases_md = gr.Markdown(_init_testcases_md)

    gr.Markdown(
        "<small>Built with Gradio · Model: openai/gpt-oss-120b on Groq · "
        "Only the first 15,000 characters of the PDF are analysed · "
        "Exports are generated locally in the <code>exports/</code> folder.</small>"
    )

    analysis_state = gr.State(value=_init_state)

    outputs = [
        status_output, kpi_html, doc_info, overview_md,
        stories_df, stories_md,
        acceptance_df, acceptance_md,
        testcases_df, testcases_md,
        analysis_state, export_status,
    ]

    analyze_btn.click(
        fn=analyze_document,
        inputs=[pdf_input, project_input, sections_input, analysis_state],
        outputs=outputs,
        show_progress="full",
    )
    sample_btn.click(
        fn=load_sample,
        inputs=[],
        outputs=outputs,
        show_progress="minimal",
    )

    excel_btn.click(
        fn=export_excel,
        inputs=[analysis_state],
        outputs=[excel_output, export_status],
        show_progress="minimal",
    )
    csv_btn.click(
        fn=export_csv,
        inputs=[analysis_state],
        outputs=[csv_output, export_status],
        show_progress="minimal",
    )

    # Per-tab search filters.
    for search, df, key in (
        (stories_search, stories_df, "stories"),
        (acceptance_search, acceptance_df, "acceptance"),
        (testcases_search, testcases_df, "testcases"),
    ):
        search.change(
            fn=lambda q, s, k=key: _filter_rows(k, q, s),
            inputs=[search, analysis_state],
            outputs=[df],
        )


if __name__ == "__main__":
    if llm is None:
        print("WARNING: " + MISSING_KEY_MESSAGE)

    # allowed_paths lets Gradio serve the background picture from the assets folder.
    demo.launch(
        server_name=os.getenv("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.getenv("GRADIO_SERVER_PORT", "7860")),
        allowed_paths=[str(ASSETS_DIR)],
    )
