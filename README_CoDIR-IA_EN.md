# CoDIR IA — Virtual Executive Committee • Open-Source  
### *Artificial intelligence for executive‑level decision making.*

---

![Status](https://img.shields.io/badge/Status-Active-brightgreen)
![License](https://img.shields.io/badge/License-MIT-blue)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Streamlit](https://img.shields.io/badge/Framework-Streamlit-red)
![Multi‑AI](https://img.shields.io/badge/AI-Orchestrator-purple)

---

## 🧭 Overview

**CoDIR IA** is a local multi‑AI orchestrator designed to generate, in seconds,  
**a fully structured Virtual Executive Committee**, powered by 4 complementary LLMs:

- **OpenAI**
- **Anthropic**
- **Google Gemini**
- **Mistral**

Runs **100% locally** for **full confidentiality**.  
Your machine ■ Your data ■ Your strategic decisions.

---

## 🚀 Key Features

- Simultaneous orchestration of **4 advanced AI models**
- **"Executive Committee Meeting" mode**: structured insights, risks, decisions
- Strategic, financial, operational and transformation analysis
- Clean and fast UI powered by **Streamlit**
- Fully **open‑source**, modular and extensible
- Zero cloud exposure — **local only**

---

## 🎯 Who is it for?

- SME / Mid‑cap executives  
- Interim & fractional CFOs  
- Finance / ERP / transformation consultants  
- Independent professionals  
- Anyone needing **immediate multi‑disciplinary strategic intelligence**

---

## 📦 Quick installation

```bash
git clone https://github.com/RobinCop63/CoDIR-IA.git
cd CoDIR-IA
pip install -r requirements.txt
streamlit run app.py
```

---

## 🔐 API Keys Setup

Create a `.env` file (or copy `.env.template`):

```
OPENAI_API_KEY=xxxx
ANTHROPIC_API_KEY=xxxx
GOOGLE_API_KEY=xxxx
MISTRAL_API_KEY=xxxx
```

---

## 📚 Documentation included

- Windows & macOS installation manual (DOCX, Windows PDF based on same content)  
- README (FR & EN)  
- Release notes  
- Coming soon: Docker, NAS execution

---

## 🧩 Project architecture

```
CoDIR-IA/
│ app.py
│ codir_engine.py
│ libre_engine.py
│ providers/
│   ├── openai_provider.py
│   ├── claude_provider.py
│   ├── mistral_provider.py
│   └── gemini_provider.py
│ .env.template
│ README.md
│ manuel_installation/
│   ├── PDF
│   └── DOCX
```

---

## 🪟 Windows installation

### 1. Prerequisites

- Windows 10 or 11 (64-bit)  
- Python 3.10+ installed (`python --version` in PowerShell)  
- Git installed (`git --version`)  

### 2. Clone the CoDIR IA repository

```bash
git clone https://github.com/RobinCop63/CoDIR-IA.git
cd CoDIR-IA
```

### 3. Start CoDIR IA using the Windows script

Double-click on `launch.bat` or `launch_codir.bat`.

This script will automatically:

- create (if needed) a `venv\` virtual environment  
- install all dependencies via `pip install -r requirements.txt`  
- copy `.env.template` to `.env` if no `.env` exists yet  
- launch the Streamlit UI in your default browser  

👉 **Don't forget to fill in your API keys** in the `.env` file before heavy use.

---

## 🍏 macOS installation (standard)

### 1. Prerequisites

- macOS 13 or newer recommended  
- Python 3.10+ installed (`python3 --version` in Terminal)  
- Git installed (`git --version`)  

If Python or Git are missing, you can install them via **Homebrew**:

```bash
brew install python git
```

### 2. Clone the CoDIR IA repository

```bash
git clone https://github.com/RobinCop63/CoDIR-IA.git
cd CoDIR-IA
```

### 3. Start CoDIR IA using the macOS script

Make the script executable (one time only):

```bash
chmod +x launch.sh
```

Then run the orchestrator:

```bash
./launch.sh
```

This script will automatically:

- create (if needed) a `venv/` virtual environment  
- install all dependencies via `pip install -r requirements.txt`  
- copy `.env.template` to `.env` if no `.env` exists yet  
- launch the Streamlit UI in your default browser  

👉 **Don't forget to fill in your API keys** in the `.env` file before heavy use (OpenAI, Anthropic, Gemini, Mistral, etc.).

---

## 🗺️ Roadmap

### v15 — November 2025  
Stable Windows & macOS release  

### v16 — December 2025  
Improved UX, orchestration refinements  

### v17 — 2026  
Docker, NAS version, advanced dashboard

---

## 🤝 Contributing

1. Open an *issue*  
2. Submit a *pull request*  
3. Suggest tests or enhancements  

---

## 👤 Authors

**Robin Sauzet — SASU Hi! Gestion**  
**ChatGPT — Co-author (OpenAI)**

---

## 📄 License

Released under the MIT License.

---

## 💡 CoDIR IA  
### *Your structured, powerful, 24/7 Virtual Executive Committee.*
