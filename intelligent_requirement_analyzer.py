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

from exporters import build_section_csv, build_section_excel
from parsers import parse_acceptance_criteria, parse_test_cases, parse_user_stories

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
# still opens and the Status box says what is missing.
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

PLACEHOLDER = "_No data yet — please upload a PDF and run an analysis._"


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
2. Download each section as Excel or CSV using the buttons in its tab.
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
        msg = "⚠️ Please upload a file (PDF) before starting an analysis."
        return _render_outputs(state, msg) if state else _empty_outputs(msg)

    if not sections:
        return _render_outputs(state, "⚠️ Select at least one section to generate.") if state else _empty_outputs("⚠️ Select at least one section to generate.")

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
                markdowns[key] = ""
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



# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

def export_section(state, section, file_format):
    """Prepare a download for exactly one section, using all its rows."""
    rows = (state or {}).get("rows", {}).get(section, [])
    if not rows:
        gr.Warning("No data in this section. Upload a PDF and generate it first.")
        return gr.update(value=None, visible=False)
    try:
        builder = build_section_excel if file_format == "excel" else build_section_csv
        path = builder(section, rows, state.get("meta", {}))
        return gr.update(value=path, visible=True)
    except Exception as error:
        traceback.print_exc()
        gr.Warning(f"Export failed: {error}")
        return gr.update(value=None, visible=False)


# ---------------------------------------------------------------------------
# Each browser session starts empty; Gradio State holds results only in-session.
# ---------------------------------------------------------------------------

initial_state = _empty_state()
_initial = _render_outputs(
    initial_state,
    "Please upload a PDF and press Analyze Requirement to get started."
    + ("" if llm else "  ·  " + MISSING_KEY_MESSAGE),
)
(_init_status, _init_kpi, _init_docinfo, _init_overview,
 _init_stories_df, _init_stories_md,
 _init_acceptance_df, _init_acceptance_md,
 _init_testcases_df, _init_testcases_md,
 _init_state) = _initial

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
    background: var(--block-background-fill) !important;
    border-radius: 16px !important;
    border: 1px solid var(--border-color-primary) !important;
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
table td { color: var(--body-text-color) !important; background: var(--block-background-fill) !important; }
.markdown { background: var(--block-background-fill) !important; border-radius: 12px; padding: 14px; }
.markdown :is(p, li, h1, h2, h3, h4, strong, small),
.prose :is(p, li, h1, h2, h3, h4, strong, small) {
    color: var(--body-text-color) !important;
}

/* ---------- Status ---------- */
textarea[readonly] {
    background: var(--input-background-fill) !important; color: var(--body-text-color) !important;
    font-weight: 600 !important; border: 1px solid var(--border-color-primary) !important;
}

/* Match custom surfaces to Gradio's dark mode instead of mixing dark text
   with light panels (Gradio applies .dark to an ancestor). */
.dark .gradio-container {
    background: linear-gradient(rgba(15,23,42,0.94), rgba(15,23,42,0.94)),
                url("BACKGROUND_IMAGE_URL");
    background-size: cover; background-position: center; background-attachment: fixed;
}
.dark .block, .dark .markdown {
    background: #1e293b !important; border-color: #475569 !important;
    color: #f1f5f9 !important;
}
.dark .markdown p, .dark .markdown li, .dark .markdown h1,
.dark .markdown h2, .dark .markdown h3, .dark .markdown h4,
.dark .markdown strong, .dark .markdown small,
.dark .prose :is(p, li, h1, h2, h3, h4, strong, small),
.dark label, .dark label span, .dark .block-title,
.dark .file-preview, .dark .upload-container { color: #f1f5f9 !important; }
.dark .gradio-container { color: #f1f5f9; }
.dark input:not([type="checkbox"]):not([type="radio"]),
.dark textarea, .dark select {
    background: #0f172a !important; color: #f8fafc !important;
    border-color: #64748b !important;
}
.dark input::placeholder, .dark textarea::placeholder { color: #cbd5e1 !important; opacity: 1; }
.dark .upload-container, .dark .file-preview { background: #1e293b !important; border-color: #64748b !important; }
.dark button.secondary { background: #334155 !important; color: #f8fafc !important; border-color: #64748b !important; }
.dark .kpi-card { background: #1e293b; border-color: #475569; }
.dark .kpi-value, .dark .kpi-label { color: #f1f5f9; }
.dark .kpi-sub { color: #cbd5e1; }
.dark [role="tab"] { background: #334155 !important; color: #f1f5f9 !important; }
.dark [role="tab"][aria-selected="true"] { background: #0284c7 !important; color: #fff !important; }
.dark table td { color: #f1f5f9 !important; background: #1e293b !important; }
.gradio-container table th :is(strong, span) { color: #fff !important; }
.dark textarea[readonly] { background: #1e3a5f !important; color: #f1f5f9 !important; border-color: #475569 !important; }

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
        # ---------------- Left: input + options ----------------
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
                        ("📖 User Stories", "stories"),
                        ("✅ Acceptance Criteria", "acceptance"),
                        ("🧪 Test Cases", "testcases"),
                    ],
                    value=["stories", "acceptance", "testcases"],
                )

            analyze_btn = gr.Button("🚀 Analyze Requirement", variant="primary")
            clear_btn = gr.Button("🗑️ Clear results & upload a new file", variant="secondary")

            status_output = gr.Textbox(
                value=_init_status, label="Status", interactive=False, lines=3,
            )

        # ---------------- Right: results ----------------
        with gr.Column(scale=3):
            with gr.Tabs():
                with gr.Tab("📋 Overview"):
                    overview_md = gr.Markdown(_init_overview)

                with gr.Tab("📖 User Stories"):
                    with gr.Row():
                        stories_excel_btn = gr.Button("📗 Export to Excel (.xlsx)", variant="secondary")
                        stories_csv_btn = gr.Button("📘 Export to CSV", variant="secondary")
                    stories_download = gr.File(label="Download User Stories export", visible=False, interactive=False)
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
                    with gr.Row():
                        acceptance_excel_btn = gr.Button("📗 Export to Excel (.xlsx)", variant="secondary")
                        acceptance_csv_btn = gr.Button("📘 Export to CSV", variant="secondary")
                    acceptance_download = gr.File(label="Download Acceptance Criteria export", visible=False, interactive=False)
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
                    with gr.Row():
                        testcases_excel_btn = gr.Button("📗 Export to Excel (.xlsx)", variant="secondary")
                        testcases_csv_btn = gr.Button("📘 Export to CSV", variant="secondary")
                    testcases_download = gr.File(label="Download Test Cases export", visible=False, interactive=False)
                    testcases_search = gr.Textbox(
                        label="🔍 Search test cases", placeholder="Filter rows…",
                    )
                    testcases_df = gr.Dataframe(
                        headers=SECTIONS["testcases"][1], value=_init_testcases_df,
                        interactive=False, wrap=True, label="Test Cases",
                    )
                    with gr.Accordion("View raw AI output", open=False):
                        testcases_md = gr.Markdown(_init_testcases_md)

    analysis_state = gr.State(value=_init_state)

    outputs = [
        status_output, kpi_html, doc_info, overview_md,
        stories_df, stories_md,
        acceptance_df, acceptance_md,
        testcases_df, testcases_md,
        analysis_state,
    ]

    def analyze_and_reset_downloads(pdf_file, project_name, sections, state):
        return (*analyze_document(pdf_file, project_name, sections, state),
                *(gr.update(value=None, visible=False) for _ in SECTIONS), "", "", "")

    analyze_btn.click(
        fn=analyze_and_reset_downloads,
        inputs=[pdf_input, project_input, sections_input, analysis_state],
        outputs=outputs + [stories_download, acceptance_download, testcases_download, stories_search,
                           acceptance_search, testcases_search],
        show_progress="full",
    )
    def clear_session():
        # Clear visible downloads and filters as well as the per-session state.
        return (*_empty_outputs("Results cleared. Please upload a file to begin."),
                None, "", *(gr.update(value=None, visible=False) for _ in SECTIONS), "", "", "")

    clear_btn.click(
        fn=clear_session,
        inputs=[],
        outputs=outputs + [pdf_input, project_input, stories_download, acceptance_download, testcases_download,
                           stories_search, acceptance_search, testcases_search],
        show_progress="minimal",
    )

    for section, excel_button, csv_button, download in (
        ("stories", stories_excel_btn, stories_csv_btn, stories_download),
        ("acceptance", acceptance_excel_btn, acceptance_csv_btn, acceptance_download),
        ("testcases", testcases_excel_btn, testcases_csv_btn, testcases_download),
    ):
        excel_button.click(
            fn=lambda state, k=section: export_section(state, k, "excel"),
            inputs=[analysis_state], outputs=[download], show_progress="minimal",
        )
        csv_button.click(
            fn=lambda state, k=section: export_section(state, k, "csv"),
            inputs=[analysis_state], outputs=[download], show_progress="minimal",
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
