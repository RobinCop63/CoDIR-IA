# 🏛️ CoDIR IA v16.3.3.22

**Your Board of Directors, augmented by Artificial Intelligence**

CoDIR IA simulates a complete board of directors with 4 specialized functions, each driven by a different AI model:

- 🎯 **Strategy** — Strategic analysis and recommendations
- 📢 **Marketing** — Operational marketing plan and KPIs
- 💰 **Finance** — Financial projections and French tax considerations
- 👔 **General Management** — Synthesis, decisions, T0→T+90d roadmap

---

## 📋 Table of Contents

1. [Quick Start](#-quick-start)
2. [API Key Configuration](#-api-key-configuration)
3. [Usage](#-usage)
4. [PowerPoint Export](#-powerpoint-export)
5. [File Attachments](#-file-attachments)
6. [Troubleshooting](#-troubleshooting)
7. [Security & Privacy](#-security--privacy)

---

## 🚀 Quick Start

### Windows

1. Download and extract the ZIP
2. Double-click `setup_windows.bat`
3. The application opens automatically in your browser

### macOS

1. Download and extract the ZIP
2. Double-click `CoDIR IA.app` *(recommended)*
3. If macOS blocks it: System Settings > Privacy & Security > **Open Anyway**

Alternative (opens Terminal): double-click `CoDIR-IA.command`

### Manual Installation

```bash
python -m venv .venv
source .venv/bin/activate      # macOS/Linux
# or: .venv\Scripts\activate   # Windows
pip install -r requirements.txt
streamlit run app.py
```

**Requirements**: Python 3.10 or higher · At least one API key

---

## 🔑 API Key Configuration

On first launch, a dialog box prompts you to enter your keys.

You can also access the **Configuration** page from the sidebar:

| Provider | Variable | Get a key |
|----------|----------|-----------|
| OpenAI   | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| Anthropic | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| Google | `GOOGLE_API_KEY` | [aistudio.google.com](https://aistudio.google.com) |
| Mistral | `MISTRAL_API_KEY` | [console.mistral.ai](https://console.mistral.ai) |

> ⚠️ **Security**: keys are stored in `secrets.json` *outside the repo*. Never share them.

---

## 🖥️ Usage

### CoDIR Session (main mode)

1. Click **Session CoDIR** in the sidebar
2. Write your **executive brief** (context, stakes, decisions expected)
3. Add optional **attachments** (PDF, DOCX, XLSX, CSV…)
4. Check **Generate PowerPoint** if you want a PPT export
5. Click **🚀 Launch CoDIR IA session**
6. Download the **meeting report (.docx)** and/or **summary (.pptx)**

### Free Mode

Compare responses from multiple AIs on the same prompt — useful for benchmarking models or exploring creative angles.

### Session Parameters

| Parameter | Values | Usage |
|-----------|--------|-------|
| Mode | Economy / Balanced / Quality | Adjusts temperature and tokens |
| Temperature | 0.0 → 1.0 | Response creativity |
| Max tokens | 256 → 8000 | Response length |

---

## 📊 PowerPoint Export

### How to get it

Check **"Generate PowerPoint"** before launching the session.

### Module architecture (`utils/pptx_export.py`)

This is the **core module** called by `app.py`. It works in 3 steps:

1. **Cleaning** the meeting report text (technical noise removal)
2. **AI call** (active provider) → structured strict JSON generation
3. **python-pptx rendering** → professional `.pptx` file

The module includes a robustness mechanism: if the AI JSON is invalid, it attempts up to 3 automatic repairs, then falls back to a local heuristic extraction of the report.

### Format v16.3.3.22

The generated PowerPoint contains **5 to 10 slides** (adaptive based on report richness):

| # | Slide | Content |
|---|-------|---------|
| 1 | **Title** | Deck name · Topic · Date · Version |
| 2 | **Context & objectives** | Brief summary + key recommendation |
| 3–8 | **Topic slides** | 1 theme per slide, 3–5 bullets |
| Last | **Action plan** | 1 decision per function: Strategy · Marketing · Finance · CEO |

**Design**:
- **Navy / Gold** palette (#1E2761 / #E8B84B)
- Title and action plan slides: dark Navy background
- Content slides: light gray background, Navy header, white card
- Numbered bullets, color accents per theme (Teal · Blue · Green · Orange · Red · Gold)
- **No technical noise** (tokens, provider, diagnostics automatically filtered)

> **Note**: an experimental module `pptx_from_cr.py` (specialized market/SWOT/roadmap schema)
> is available in `experimental/` for future advanced use. It is not used by the application.
## 📎 File Attachments

**Supported formats**: PDF · DOCX · PPTX · XLSX · XLSM · CSV · TXT · MD

**Limits**: 5 files max · 25 MB total

Content is extracted, cleaned and injected into the **Strategy** prompt as factual context.

---

## 🔧 Troubleshooting

### App won't start (Windows)

```batch
.venv\Scripts\activate
python -m streamlit run app.py
```

Check the log: `outputs\setup_windows.log`

### App won't start (macOS)

```bash
source .venv/bin/activate
python -m streamlit run app.py
```

Check the log: `outputs/setup_macos.log`

### "No API key" error

Go to **Configuration**, enter at least one key and click **Test**.

### PPT is empty or contains technical noise

- Ensure the meeting report was generated before the PPT export
- Increase **Max output tokens** (2000+) in session settings
- Check `outputs/pptx_attempts_<date>.json` for detailed error info

### Rate limit / provider timeout

The system automatically switches to the next available provider.
Check **AI Diagnostics** in the interface for details.

---

## 🔒 Security & Privacy

- API keys are stored in `~/.codir_ia/secrets.json` (outside repo, ignored by `.gitignore`)
- The application runs **locally** — no data transmitted except to selected AI APIs
- Attachments are **not saved** to disk
- See [PRIVACY.md](PRIVACY.md) for the full privacy policy

---

*CoDIR IA v16.3.3.22 — © 2025-2026 Robin Sauzet / HiGestion*
