# CoDIR IA — Comité de Direction Virtuel • Open-Source  
### *L'intelligence artificielle au service de la décision exécutive.*

---

![Status](https://img.shields.io/badge/Status-Active-brightgreen)
![License](https://img.shields.io/badge/License-MIT-blue)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Streamlit](https://img.shields.io/badge/Framework-Streamlit-red)
![Multi‑AI](https://img.shields.io/badge/AI-Orchestrator-purple)

---

## 🧭 Vue d'ensemble

**CoDIR IA** est un orchestrateur local multi‑IA conçu pour fournir en quelques secondes  
**un Comité de Direction virtuel complet**, structuré et alimenté par 4 IA complémentaires :

- **OpenAI**
- **Anthropic**
- **Google Gemini**
- **Mistral**

Le tout fonctionne **entièrement en local**, en garantissant une **confidentialité totale**.  
Votre machine ■ Vos données ■ Vos décisions.

---

## 🚀 Fonctionnalités clés

- Orchestration simultanée de **4 modèles IA avancés**
- Mode **"Réunion CoDIR"** : sortie structurée, décisions, risques, synthèse exécutive
- Analyse **stratégique**, **financière**, **organisationnelle**, **risques**
- Interface simple & rapide basée sur **Streamlit**
- Architecture entièrement **open-source**, modulable et extensible
- Zéro cloud, zéro trace : **local only**

---

## 🎯 À qui s'adresse CoDIR IA ?

- Dirigeants de PME / ETI  
- DAF / CFO de transition  
- Consultants finance / ERP / transformation  
- Indépendants  
- Experts ayant besoin d'une **vision pluridisciplinaire immédiate**

---

## 📦 Installation rapide

```bash
git clone https://github.com/RobinCop63/CoDIR-IA.git
cd CoDIR-IA
pip install -r requirements.txt
streamlit run app.py
```

---

## 🔐 Configuration des clés API

Créer un fichier `.env` à la racine (ou copier `.env.template`) :

```
OPENAI_API_KEY=xxxx
ANTHROPIC_API_KEY=xxxx
GOOGLE_API_KEY=xxxx
MISTRAL_API_KEY=xxxx
```

---

## 📚 Documentation fournie

- 📘 Manuel d'installation Windows & macOS (DOCX, PDF Windows basé sur le même contenu)  
- README (FR & EN)  
- Notes de version  
- À venir : Docker, exécution sur NAS

---

## 🧩 Architecture du projet

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

## 🪟 Installation Windows

### 1. Pré-requis

- Windows 10 ou 11 (64 bits)  
- Python 3.10+ installé (`python --version` dans PowerShell)  
- Git installé (`git --version`)  

### 2. Récupérer le dépôt CoDIR IA

```bash
git clone https://github.com/RobinCop63/CoDIR-IA.git
cd CoDIR-IA
```

### 3. Lancer CoDIR IA via le script Windows

Double-cliquez sur `launch.bat` ou `launch_codir.bat`.

Ce script va automatiquement :

- créer (si besoin) un environnement virtuel `venv\`  
- installer les dépendances `pip install -r requirements.txt`  
- copier `.env.template` vers `.env` si aucun fichier `.env` n'existe encore  
- lancer l'interface Streamlit dans ton navigateur par défaut  

👉 **N'oublie pas ensuite de renseigner tes clés API** dans le fichier `.env` avant une utilisation intensive.

---

## 🍏 Installation macOS (version standard)

### 1. Pré-requis

- macOS 13 ou plus récent recommandé  
- Python 3.10+ installé (`python3 --version` dans le Terminal)  
- Git installé (`git --version`)  

Si Python ou Git ne sont pas installés, tu peux les ajouter via **Homebrew** :

```bash
brew install python git
```

### 2. Récupérer le dépôt CoDIR IA

```bash
git clone https://github.com/RobinCop63/CoDIR-IA.git
cd CoDIR-IA
```

### 3. Lancer CoDIR IA via le script macOS

Rends le script exécutable une seule fois :

```bash
chmod +x launch.sh
```

Puis lance l'orchestrateur :

```bash
./launch.sh
```

Ce script va automatiquement :

- créer (si besoin) un environnement virtuel `venv/`  
- installer les dépendances `pip install -r requirements.txt`  
- copier `.env.template` vers `.env` si aucun fichier `.env` n'existe encore  
- lancer l'interface Streamlit dans ton navigateur par défaut  

👉 **N'oublie pas ensuite de renseigner tes clés API** dans le fichier `.env` avant une utilisation intensive (OpenAI, Anthropic, Gemini, Mistral, etc.).

---

## 🗺️ Roadmap

### v15 — Novembre 2025  
- Version Windows & macOS stable  

### v16 — Décembre 2025  
- Amélioration UI  
- Nouvelle logique d'orchestration  

### v17 — 2026  
- Version NAS  
- Version Docker  
- Dashboard avancé

---

## 🤝 Contribuer

1. Ouvrir une *issue*  
2. Soumettre une *pull request*  
3. Proposer des tests ou améliorations  

---

## 👤 Auteurs

**Robin Sauzet — SASU Hi! Gestion**  
**ChatGPT — Co-auteur (OpenAI)**

---

## 📄 Licence

MIT — libre, ouverte, professionnelle.

---

## 💡 CoDIR IA  
### *Votre comité de direction virtuel. Structuré. Puissant. Disponible 24/7.*
