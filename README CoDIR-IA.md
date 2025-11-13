# CoDIR IA — Comité de Direction Virtuel • Open-Source  
### *L’intelligence artificielle au service des dirigeants.*

---

## 🔍 Présentation

**CoDIR IA** est un orchestrateur local multi-IA permettant d’obtenir, en quelques secondes,  
**un comité de direction virtuel complet**, fondé sur les modèles avancés de :

- OpenAI  
- Anthropic  
- Google Gemini  
- Mistral  
- LiberAI  

Le projet est **100 % open source**, fonctionnant en local (version Windows).  
Toutes vos données restent **chez vous**, sans aucun envoi vers un cloud externe.

---

## 🎯 Pour qui ?

- Dirigeants de PME / ETI  
- Managers de transition  
- Consultants (finance, ERP, transformation)  
- Professions indépendantes  
- Toute personne souhaitant un **espace stratégique multidisciplinaire supervisé par 4 IA différentes**

---

## ⚙️ Fonctionnalités principales

- Interface simple via **Streamlit**  
- Orchestration simultanée de **4 IA**  
- Analyse stratégique, financière, risques & décisions  
- Mode “réunion CoDIR”  
- Fonctionnement local pour une confidentialité maximale  
- Architecture reproductible et documentée  

---

## 📥 Installation

📘 **Manuel d’installation complet (Windows)**  
➡️ Disponible dans le dossier `Manuel_Installation/` (PDF + DOCX)

### Installation rapide

```bash
git clone https://github.com/RobinCop63/CoDIR-IA.git
cd CoDIR-IA
pip install -r requirements.txt
streamlit run app_streamlit.py
```

---

## 🔐 Configuration des clés API

Créez un fichier nommé **`.env`** à la racine du projet :

```
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
GEMINI_API_KEY=...
MISTRAL_API_KEY=...
LIBERAI_API_KEY=...
```

👉 L’ensemble du processus est détaillé dans le manuel d’installation.

---

## 📚 Documentation

- Manuel d’installation Windows (PDF + DOCX)  
- README.md  
- Notes de version  
- À venir :  
  - Manuel macOS  
  - Version Docker  
  - Version réseau local (NAS)

---

## 🧩 Structure du projet

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

## 🔁 Mises à jour

- **Version actuelle : v15 — Novembre 2025**  
- **Prochaine release : v16 — Décembre 2025**

➡️ Consulter l’onglet **Releases** pour les évolutions.

---

## 🤝 Contribution

Les contributions sont les bienvenues.  
Pour participer :

1. Ouvrir une *issue* (bug, suggestion)  
2. Soumettre une *pull request*  
3. Ajouter tests et commentaires si pertinent  

---

## 👤 Auteurs

**Robin Sauzet — SASU Hi! Gestion**  
**ChatGPT — Co-auteur IA**

---

## 📄 Licence

Projet publié sous licence **MIT** (incluse dans le dépôt).

---

## 🚀 CoDIR IA  
### *Votre comité de direction virtuel, toujours disponible.*