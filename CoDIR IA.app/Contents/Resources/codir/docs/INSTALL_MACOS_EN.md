# 🍎 macOS Installation Guide — CoDIR IA v16.3.3.22

---

## 📋 Requirements

- macOS 12 (Monterey) or higher
- Internet connection
- At least **one API key** (OpenAI, Anthropic, Google or Mistral)

---

## Method 1 — macOS Application (recommended)

### Installation

1. Download the ZIP from [GitHub Releases](https://github.com/robinsauzet/codir-ia/releases)
2. Extract the ZIP (double-click)

### First launch

Double-click **`CoDIR IA.app`**

If macOS shows *"Cannot open application"*:
1. Go to **System Settings** > **Privacy & Security**
2. Scroll to the **Security** section
3. Click **Open Anyway**

*or* right-click the app > **Open** > **Open**

### Subsequent launches

Simply double-click **`CoDIR IA.app`**

The application automatically opens a Terminal, installs dependencies if needed, then launches the interface in your browser.

---

## Method 2 — Terminal (alternative)

Double-click **`CoDIR-IA.command`**

This opens a Terminal and automatically runs the installation + application.

If macOS blocks it:
```bash
chmod +x CoDIR-IA.command
```

---

## Method 3 — Manual Installation

```bash
# In the CoDIR-IA folder
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

**Python required**: 3.10 or higher.

Check: `python3 --version`

Install if missing: [python.org/downloads/macos](https://www.python.org/downloads/macos/)
*or* via Homebrew: `brew install python@3.11`

---

## API Key Configuration

On first launch, a dialog box appears to enter your keys.

You can also access the **Configuration** page from the sidebar:

| Provider | Variable |
|----------|----------|
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Google/Gemini | `GOOGLE_API_KEY` |
| Mistral | `MISTRAL_API_KEY` |

---

## macOS Troubleshooting

| Problem | Solution |
|---------|----------|
| App blocked by Gatekeeper | System Settings > Privacy > Open Anyway |
| "command not found: python3" | Install Python via [python.org](https://www.python.org) or `brew install python@3.11` |
| "Port 8501 already in use" | `streamlit run app.py --server.port 8502` |
| Permission denied on .command | `chmod +x CoDIR-IA.command` |
| App starts but browser doesn't open | Manually open [http://localhost:8501](http://localhost:8501) |

Check `outputs/setup_macos.log` for detailed error information.

---

*CoDIR IA v16.3.3.22 — macOS Installation Guide*
