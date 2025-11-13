# CoDIR IA — Virtual Executive Committee • Open-Source  
### *Artificial intelligence at the service of leadership.*

---

## 🔍 Overview

**CoDIR IA** is a local multi-AI orchestrator designed to generate, in seconds,  
**a complete virtual Executive Committee**, powered by advanced LLMs:

- OpenAI  
- Anthropic  
- Google Gemini  
- Mistral  
- LiberAI  

The project is **100% open source** and runs fully **locally** (Windows version).  
Your data remains **on your machine**, with no cloud transmission.

---

## 🎯 Who is it for?

- SME / mid-cap leaders  
- Interim & fractional executives  
- Consultants (finance, ERP, transformation)  
- Independent professionals  
- Anyone needing a **strategic, multidisciplinary AI council powered by 4 different models**

---

## ⚙️ Key Features

- Simple interface using **Streamlit**  
- Simultaneous orchestration of **four AI models**  
- Strategic, financial, risk & decision analysis  
- “Executive Committee meeting” interaction mode  
- Local execution for maximum confidentiality  
- Reproducible, documented architecture  

---

## 📥 Installation

📘 **Full installation guide (Windows)**  
➡️ Available in `Manuel_Installation/` (PDF + DOCX)

### Quick install

```bash
git clone https://github.com/RobinCop63/CoDIR-IA.git
cd CoDIR-IA
pip install -r requirements.txt
streamlit run app_streamlit.py
```

---

## 🔐 API Key Configuration

Create a `.env` file at the project root:

```
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
GEMINI_API_KEY=...
MISTRAL_API_KEY=...
LIBERAI_API_KEY=...
```

Full details in the installation manual.

---

## 📚 Documentation

- Windows installation manual (PDF + DOCX)  
- README.md  
- Release notes  
- Coming soon: macOS version, Docker version, NAS-based local network version

---

## 🧩 Project Structure

```
CoDIR-IA/
│ app_streamlit.py
│ codir_engine.py
│ libre_engine.py
│ providers/
│   ├── openai_provider.py
│   ├── anthropic_provider.py
│   ├── mistral_provider.py
│   └── gemini_provider.py
│ .env.example
│ README.md
│ Manuel_Installation/
│   ├── PDF
│   └── DOCX
```

---

## 🔁 Versioning

- **Current version: v15 — November 2025**  
- **Next release: v16 — December 2025**

Check the **Releases** section for details.

---

## 🤝 Contributing

Contributions are welcome.  
You can:

1. Open an *issue*  
2. Submit a *pull request*  
3. Provide tests or comments if relevant  

---

## 👤 Authors

**Robin Sauzet — SASU Hi! Gestion**  
**ChatGPT — Co-author**

---

## 📄 License

Licensed under the **MIT License** (included in the repository).

---

## 🚀 CoDIR IA  
### *Your virtual Executive Committee, always available.*