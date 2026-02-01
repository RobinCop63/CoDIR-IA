# CoDIR IA v16.0

**🇫🇷 [Documentation française](README_FR.md)** | **🇬🇧 [English documentation](README_EN.md)**

---

## Quick Start / Démarrage rapide

### Windows
```
Double-click: setup_windows.bat
```

### macOS
```
Double-click: CoDIR-IA.app
```

**Alternative (command line)**:
```bash
chmod +x mac/launch_user.sh && ./mac/launch_user.sh
```

---

## ✨ What's new in v16.0

- 🖱️ **Double-click launcher** for Windows and macOS
- 🍎 **Native macOS application** with Dock icon
- 🔧 **Google Gemini SDK migration** to official `google-genai`
- 📦 **No heavy installer** (scripts + Python)
- 🎯 **Setup in ~5 minutes** on both platforms (Python required)

---

> ⚠️ **Important**
> 
> 🇫🇷 L'utilisation des API IA est **payante** (facturée par chaque fournisseur). Vos données sont transmises aux serveurs des éditeurs IA.
> 
> 🇬🇧 Using AI APIs is **paid** (billed by each provider). Your data is transmitted to AI vendors' servers.

---

## 🏗️ Architecture

- **Multi-provider**: OpenAI, Claude, Gemini, Mistral
- **Two modes**: CoDIR (committee simulation) & Libre (individual AI)
- **Local execution**: No data stored in cloud
- **Modular design**: Easy to extend with new providers

---

## 📖 Documentation

- **Installation**: See platform-specific guides in `/win` and `/mac` folders
- **Release notes**: [RELEASE_v16.0.md](RELEASE_v16.0.md)
- **Configuration**: Create `.env` file with your API keys (see `.env.template`)

---

## 🛠️ Requirements

- **Python 3.10+**
- **Internet connection** (for API calls and initial setup)
- **API keys** for the AI providers you want to use

---

## 📂 Project structure

```
CoDIR-IA/
├── app.py                    # Main application
├── codir_engine.py           # CoDIR mode logic
├── libre_engine.py           # Libre mode logic
├── providers/                # AI provider integrations
│   ├── openai_provider.py
│   ├── claude_provider.py
│   ├── gemini_provider.py
│   └── mistral_provider.py
├── prompts/                  # Role definitions
├── win/                      # Windows launcher & docs
├── mac/                      # macOS launcher & docs
└── outputs/                  # Conversation exports
```

---

## 🤝 Contributing

CoDIR IA is **100% open source** under MIT license. Contributions, feedback, and feature requests are welcome.

---

## 📄 License

MIT - See [LICENSE](LICENSE) file for details.

---

**Developed by**: HiGestion  
**Version**: 16.0  
**© 2024-2026**
