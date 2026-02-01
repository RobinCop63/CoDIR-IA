# CoDIR IA v16.0 – Multi‑AI decision support orchestrator (open source)

**CoDIR IA** is an analysis and decision‑support tool for executives, interim managers and consultants.  
It simulates a structured, explainable "collective" reasoning — **without automating the final decision**.

- **Runs locally** (Streamlit)
- **Multi‑provider**: OpenAI, Anthropic (Claude), Google (Gemini), Mistral
- **Modular architecture** (separate providers)
- **Open source** (MIT)

---

> ⚠️ **IMPORTANT – Read before using**
> 
> **API Costs**: CoDIR IA is free and open source, but using AI APIs (OpenAI, Anthropic, Google, Mistral) is **paid**. Each call is billed directly by the provider to your personal account, according to their pricing.
> 
> **Privacy**: Your prompts and data are transmitted to the AI providers' servers. CoDIR IA does not store anything online, but AI vendors may retain logs according to their terms of service.

---

## 🚀 Quick start (Windows)

### Method 1: Automatic installation (recommended)

1. Download and unzip the project
2. Double‑click **`setup_windows.bat`**

The script does everything automatically:
- Creates the Python environment
- Installs dependencies
- Creates the `.env` file
- Creates a Desktop shortcut with the CoDIR IA icon

### Method 2: Direct launch

1. Double‑click **`launch_codir.bat`**

On first run, the launcher automatically creates the environment and installs dependencies.

### Create the shortcut manually (if needed)

From the project folder, run in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\win\create_shortcut.ps1
```

---

## 🍎 Quick start (macOS)

In the project folder:

```bash
chmod +x mac/launch_user.sh
./mac/launch_user.sh
```

See the macOS installation manual for more details.

---

## 🔑 API keys configuration (.env)

Edit the `.env` file (auto-created). On Windows, if no API key is detected, `.env` is automatically opened in **Notepad** on first run.

Fill in **only** the keys for providers you use:

| Provider | Environment variable |
|----------|---------------------|
| OpenAI | `OPENAI_API_KEY` |
| Anthropic (Claude) | `ANTHROPIC_API_KEY` |
| Google (Gemini) | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| Mistral | `MISTRAL_API_KEY` |

You can also set models (e.g. `GOOGLE_MODEL=gemini-2.5-flash`).

---

## 💸 API costs & billing

CoDIR IA is **free and open source**. However:

- **API calls are paid**: each request sent to OpenAI, Anthropic, Google or Mistral is billed by that provider
- **Direct billing**: costs are charged to **your personal account** with each vendor
- **Variable pricing**: check each provider's pricing before use
- **No hidden fees**: CoDIR IA takes no commission

**Tip**: Start with limited quotas on your API accounts to control your spending.

---

## 🛡️ Privacy & data handling

### What CoDIR IA does

- **100% local execution** on your machine
- No remote CoDIR IA server
- Your files and history stay on your computer

### What AI providers do

When you use a provider (OpenAI / Gemini / Claude / Mistral):

- Your **prompts** and **context** are **transmitted to their servers**
- Each provider applies its own retention policy
- Data may be used according to their ToS (logs, model improvement, etc.)

### For 100% confidential usage

If you have strict confidentiality requirements, use local models (not included by default in this version).

---

## 📁 Project structure

```
CoDIR-IA-main/
├── app.py                 # Streamlit interface
├── codir_engine.py        # Decision engine
├── libre_engine.py        # Free mode (AI comparison)
├── providers/             # API connectors by provider
├── prompts/               # Role prompts
├── outputs/               # Local outputs
├── assets/                # Icons and resources
├── win/                   # Windows scripts
├── mac/                   # macOS scripts
├── setup_windows.bat      # Automatic Windows installation
├── launch_codir.bat       # Windows launcher
├── requirements.txt       # Python dependencies
└── .env.template          # Configuration template
```

---

## 📄 License

MIT – See the `LICENSE` file for details.

---

## 👥 Authors

**Robin Sauzet** – SASU Hi! Gestion  
**ChatGPT (OpenAI)**  
**Claude (Anthropic)**

*January 2026*
