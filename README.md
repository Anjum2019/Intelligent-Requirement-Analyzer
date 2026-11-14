# Intelligent Requirement Analyzer

Upload a requirements document (PDF) and get five drafts back, each in its own tab:

| Tab | What you get |
| --- | --- |
| User Stories | "As a … I want … so that …" stories |
| Acceptance Criteria | Given / When / Then criteria |
| Test Cases | ID, scenario, steps, expected result |
| Risks | Functional, technical, dependency and security risks |
| AI Effort Estimate | Modules with complexity, story points and effort |

It is a [Gradio](https://www.gradio.app/) web app. It reads the PDF with LangChain's
`PyPDFLoader` and sends the text to the `openai/gpt-oss-120b` model on
[Groq](https://groq.com/).

## Setup

You need Python 3.11 or newer and a Groq API key
(create one at <https://console.groq.com/keys>).

Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

(If PowerShell refuses to run the activate script, run the same commands in
Command Prompt instead.)

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Then open `.env` and replace `gsk_your_key_here` with your real key.
`.env` is listed in `.gitignore`, so your key is never committed.

## Run

```bash
python intelligent_requirement_analyzer.py
```

Open the address printed in the terminal (normally <http://127.0.0.1:7860>),
upload a PDF and press **Analyze Requirement**.

If something goes wrong, the **Status** box says why:

| Status box shows | What to do |
| --- | --- |
| `GROQ_API_KEY is not set …` | Create `.env` as described above, then restart the app. |
| `Analysis failed - AuthenticationError …` | Groq rejected the key in `.env`: it is wrong, or it has been revoked. Create a new one. |
| `Analysis failed - RateLimitError …` | You reached a limit of your Groq plan. Wait a minute and try again. |
| `Analysis failed - APIConnectionError …` | The app could not reach `api.groq.com`. Check your internet connection. |
| `Analysis failed - PdfStreamError …` (or another PDF error) | The file is not a readable PDF. |

The full error is also printed in the terminal.

## Good to know

- Only the first 15,000 characters of the PDF's text are analysed.
- Each analysis sends five requests to Groq, one per tab, one after the other,
  and each request contains the document text. Groq limits how much you can send
  per minute, and the limit depends on your plan
  (<https://console.groq.com/docs/rate-limits>). If a long document goes over
  it, the Status box shows `RateLimitError`.
- A scanned PDF (pictures of pages, no selectable text) gives the app nothing to
  read. It still reports success, but the results are not based on your
  document. Use a PDF with real text, or run OCR on it first.
- To change the page background, replace `assets/office_background.jpg`.

## What is in this repository

| File | Purpose |
| --- | --- |
| `intelligent_requirement_analyzer.py` | The app: user interface and analysis. This is the file you run. |
| `assets/office_background.jpg` | Background picture of the page. |
| `requirements.txt` | Packages the app needs. |
| `.env.example` | Template for your `.env` file. |
| `.github/workflows/run-app.yml` | Manual GitHub Actions check that the app starts. |

### Helper modules (not used by the app)

These files are building blocks for a retrieval pipeline: split the document
into chunks, store them in a vector database, and send only the relevant chunks
to the model. The app above does not import them; it sends the document text
directly.

| File | Function |
| --- | --- |
| `document_loader.py` | `load_document(file_path)` reads a PDF into LangChain documents |
| `splitter.py` | `create_chunks(documents)` splits them into 1,000-character chunks |
| `vector_store.py` | `create_vector_db(chunks)` embeds the chunks into a Chroma database in `./chroma_db` |
| `retriever.py` | `retrieve_context(question, db)` returns the 5 most relevant chunks as text |
| `llm.py` | `get_llm()` creates the Groq chat model |
| `user_story_generator.py` | `generate_user_stories(context, llm)` |
| `acceptance.py` | `generate_acceptance(context, llm)` |
| `testcases.py` | `generate_test_cases(context, llm)` |
| `risk_generator.py` | `generate_risks(context, llm)` |
| `estimation.py` | `estimate_effort(context, llm)` |

`vector_store.py` needs extra packages (including PyTorch, a download of
several GB). The other helper modules work with `requirements.txt` alone.

```bash
pip install -r requirements.txt -r requirements-rag.txt
```

They fit together like this:

```python
from document_loader import load_document
from splitter import create_chunks
from vector_store import create_vector_db
from retriever import retrieve_context
from llm import get_llm
from user_story_generator import generate_user_stories

chunks = create_chunks(load_document("requirements.pdf"))
db = create_vector_db(chunks)
context = retrieve_context("What must the system do?", db)
print(generate_user_stories(context, get_llm()))
```

## GitHub Actions

`.github/workflows/run-app.yml` installs the requirements, starts the app on a
GitHub runner and checks that it answers. It does not analyse a document. Run it
from the **Actions** tab → **Run Requirement Analyzer** → **Run workflow**.

It needs a repository secret named `GROQ_API_KEY`
(**Settings** → **Secrets and variables** → **Actions**).
