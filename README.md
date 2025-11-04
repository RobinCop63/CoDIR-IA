# 🧭 Orchestrateur multi-IA – Version 15
### *OpenAI · Gemini · Claude · Mistral*

## 🎯 Objectif du projet
L’orchestrateur multi-IA v15 est une application **Streamlit** qui permet de :
- comparer les réponses de plusieurs intelligences artificielles (Mode Libre),
- ou simuler un **Comité de Direction IA (CODIR IA)** où chaque modèle joue un rôle défini :
  - **Stratégie :** Claude (prospective et innovation)
  - **Marketing :** Gemini (communication et influence)
  - **Finance/Fiscalité :** Mistral (analyse réglementaire française)
  - **Direction Générale :** OpenAI GPT-4o (synthèse et arbitrage)

Le projet est conçu pour aider le dirigeant à **prendre des décisions stratégiques éclairées** grâce à une synthèse multi-IA hebdomadaire.

---

## ⚙️ Installation et lancement

### 1. Prérequis
- Python 3.10 ou supérieur
- Connexion Internet
- Clés API valides pour :
  - OpenAI
  - Google Gemini
  - Anthropic Claude
  - Mistral AI

### 2. Installation
```bash
unzip orchestrateur_multi_IA_streamlit_v15.zip
cd orchestrateur_multi_IA_streamlit_v15
python -m venv venv
source venv/bin/activate         # sous Windows : venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # puis renseignez vos clés API
```

### 3. Lancement
```bash
streamlit run app.py
```

---

## 🧩 Structure du projet

```
orchestrateur_multi_IA_streamlit_v15/
│
├── app.py                        ← Interface principale Streamlit
│                                   (menu : Mode Libre / Mode CODIR IA)
│
├── codir_engine.py               ← Logique séquentielle du CODIR IA
├── libre_engine.py               ← Moteur du mode Libre (multi-prompts)
│
├── providers/                    ← Connecteurs API
│   ├── openai_provider.py
│   ├── gemini_provider.py
│   ├── claude_provider.py
│   └── mistral_provider.py
│
├── prompts/
│   └── role_prompts.md           ← Trames de rôle du CODIR IA
│
├── outputs/                      ← Répertoire de sortie (archives futures)
│
├── .env.example                  ← Exemple de configuration
├── requirements.txt              ← Dépendances Python
└── README.md                     ← Ce document
```

---

## 🚀 Modes de fonctionnement

### **1️⃣ Mode CODIR IA**
- Saisir le **brief** (résumé des actions et priorités de la semaine).
- Cliquer sur **« Lancer la session CODIR IA »**.
- L’application exécute automatiquement :
  1. Claude → analyse stratégique,
  2. Gemini → analyse marketing et influence,
  3. Mistral → analyse financière et fiscale,
  4. OpenAI → synthèse finale.
- Un bouton permet de **télécharger le compte-rendu en .docx**.

### **2️⃣ Mode Libre**
- Rédiger un **prompt libre** et sélectionner les IA à interroger.
- Comparer les réponses de chaque modèle.
- Télécharger le résultat au format **Markdown (.md)**.

---

## 🧠 Comment fonctionne le code

`app.py` agit comme **chef d’orchestre** :
- il lit les paramètres de configuration (.env),
- gère l’interface Streamlit,
- et appelle les moteurs :
  - `codir_engine.py` → pour le mode CODIR,
  - `libre_engine.py` → pour le mode Libre.

Ces moteurs font ensuite appel aux connecteurs de `/providers/` pour exécuter les requêtes API.
Ainsi, l’interface reste légère et le code plus simple à maintenir.

---

## 📦 Exemples de commandes utiles

Mettre à jour les dépendances :
```bash
pip install -U -r requirements.txt
```

Nettoyer le cache Streamlit :
```bash
streamlit cache clear
```

Exécuter dans le navigateur par défaut :
```bash
streamlit run app.py --server.headless false
```

---

## 🔐 Bonnes pratiques de sécurité

- Ne jamais publier vos clés API.
- Restreindre les droits d’accès du fichier `.env`.
- Utiliser un environnement virtuel distinct pour le projet.
- Sauvegarder régulièrement les sorties du dossier `outputs/`.

---

## 🧰 Personnalisation

- Modifier les prompts dans `prompts/role_prompts.md`.
- Changer les modèles par défaut dans `.env`.
- Ajouter un nouveau rôle (ex. : « Juridique », « RSE »…) en dupliquant la logique de `codir_engine.py`.
- Intégrer un suivi historique (SQLite, CSV ou NAS Synology).

---

## 👤 Auteur
**Robin SAUZET** – Créateur du projet CODIR IA  
*Co-auteur : ChatGPT (OpenAI)*

Octobre 2025
