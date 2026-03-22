# 🏛️ CoDIR IA v16.3.3.22

**Votre Comité de Direction augmenté par l'Intelligence Artificielle**

CoDIR IA simule un comité de direction complet avec 4 directions spécialisées, chacune pilotée par un modèle d'IA différent :

- 🎯 **Stratégie** — Analyse et recommandations stratégiques
- 📢 **Marketing** — Plan marketing opérationnel et KPIs
- 💰 **Finance** — Projections financières et fiscalité FR
- 👔 **Direction Générale** — Synthèse, décisions, feuille de route T0→T+90j

---

## 📋 Table des matières

1. [Installation rapide](#-installation-rapide)
2. [Configuration des clés API](#-configuration-des-clés-api)
3. [Utilisation](#-utilisation)
4. [Export PowerPoint](#-export-powerpoint)
5. [Pièces jointes](#-pièces-jointes)
6. [Dépannage](#-dépannage)
7. [Sécurité & confidentialité](#-sécurité--confidentialité)

---

## 🚀 Installation rapide

### Windows

1. Téléchargez et extrayez le ZIP
2. Double-cliquez sur `setup_windows.bat`
3. L'application s'ouvre automatiquement dans votre navigateur

### macOS

1. Téléchargez et extrayez le ZIP
2. Double-cliquez sur `CoDIR IA.app` *(recommandé)*
3. Si macOS bloque : Réglages Système > Confidentialité & sécurité > **Ouvrir quand même**

Alternative (ouvre le Terminal) : double-cliquez sur `CoDIR-IA.command`

### Installation manuelle

```bash
python -m venv .venv
source .venv/bin/activate      # macOS/Linux
# ou : .venv\Scripts\activate  # Windows
pip install -r requirements.txt
streamlit run app.py
```

**Prérequis** : Python 3.10 ou supérieur · Au moins une clé API

---

## 🔑 Configuration des clés API

Au premier lancement, une boîte de dialogue vous invite à saisir vos clés.

Vous pouvez également accéder à la page **Configuration** via la barre latérale :

| Provider | Variable | Obtenir une clé |
|----------|----------|-----------------|
| OpenAI   | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| Anthropic | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| Google | `GOOGLE_API_KEY` | [aistudio.google.com](https://aistudio.google.com) |
| Mistral | `MISTRAL_API_KEY` | [console.mistral.ai](https://console.mistral.ai) |

> ⚠️ **Sécurité** : les clés sont stockées dans `secrets.json` *hors du repo*. Ne les partagez jamais.

---

## 🖥️ Utilisation

### Session CoDIR (mode principal)

1. Cliquez sur **Session CoDIR** dans la barre latérale
2. Rédigez votre **brief dirigeant** (contexte, enjeux, décisions attendues)
3. Ajoutez des **pièces jointes** optionnelles (PDF, DOCX, XLSX, CSV…)
4. Cochez **Générer aussi un PowerPoint** si vous souhaitez un export PPT
5. Cliquez sur **🚀 Lancer la session CoDIR IA**
6. Téléchargez le **compte-rendu (.docx)** et/ou la **synthèse (.pptx)**

### Mode Libre

Comparez les réponses de plusieurs IA sur un même prompt — utile pour benchmarker les modèles ou explorer des angles créatifs.

### Paramètres de session

| Paramètre | Valeurs | Usage |
|-----------|---------|-------|
| Mode | Économie / Équilibré / Qualité | Ajuste température et tokens |
| Température | 0.0 → 1.0 | Créativité des réponses |
| Max tokens | 256 → 8000 | Longueur des réponses |

---

## 📊 Export PowerPoint

### Comment l'obtenir

Cochez **"Générer aussi un PowerPoint"** avant de lancer la session.

### Architecture du module (`utils/pptx_export.py`)

C'est le **module central** appelé par `app.py`. Il fonctionne en 3 étapes :

1. **Nettoyage** du texte du compte-rendu (suppression du bruit technique)
2. **Appel IA** (provider actif) → génération d'un JSON structuré strict
3. **Rendu python-pptx** → fichier `.pptx` professionnel

Le module intègre un mécanisme de robustesse : si le JSON IA est invalide, il tente jusqu'à 3 réparations automatiques, puis bascule sur un fallback local (extraction heuristique du CR).

### Format v16.3.3.22

Le PowerPoint généré comporte **5 à 10 slides** (adaptatif selon la richesse du compte-rendu) :

| # | Slide | Contenu |
|---|-------|---------|
| 1 | **Titre** | Nom du deck · Sujet · Date · Version |
| 2 | **Contexte & objectifs** | Résumé du brief + recommandation clé |
| 3–8 | **Slides sujets** | 1 thème par slide, 3–5 bullets |
| Dernière | **Plan d'action** | 1 décision par direction : Stratégie · Marketing · Finance · DG |

**Design** :
- Palette **Navy / Or** (#1E2761 / #E8B84B)
- Slide titre et plan d'action : fond Navy foncé
- Slides contenu : fond gris clair, header Navy, carte blanche
- Bullets numérotés, accents couleurs par thème (Teal · Bleu · Vert · Orange · Rouge · Or)
- **Aucun bruit technique** (tokens, provider, diagnostics filtrés automatiquement)

> **Note** : un module expérimental `pptx_from_cr.py` (schéma spécialisé marché/SWOT/roadmap)
> est disponible dans `experimental/` pour usage avancé futur. Il n'est pas utilisé par l'application.
## 📎 Pièces jointes

**Formats supportés** : PDF · DOCX · PPTX · XLSX · XLSM · CSV · TXT · MD

**Limites** : 5 fichiers max · 25 Mo total

Le contenu est extrait, nettoyé et injecté dans le prompt de la direction **Stratégie** comme contexte factuel.

---

## 🔧 Dépannage

### L'application ne se lance pas (Windows)

```batch
.venv\Scripts\activate
python -m streamlit run app.py
```

Vérifiez le log : `outputs\setup_windows.log`

### L'application ne se lance pas (macOS)

```bash
source .venv/bin/activate
python -m streamlit run app.py
```

Vérifiez le log : `outputs/setup_macos.log`

### Erreur "Aucune clé API"

Allez dans **Configuration**, saisissez au moins une clé et cliquez **Tester**.

### Le PPT est vide ou contient du bruit technique

- Vérifiez que le compte-rendu a bien été généré avant l'export PPT
- Augmentez les **Max output tokens** (2000+) dans les paramètres
- Consultez `outputs/pptx_attempts_<date>.json` pour le détail des erreurs

### Rate limit / timeout provider

Le système bascule automatiquement sur le provider suivant disponible.
Consultez **Diagnostics IA** dans l'interface pour le détail.

---

## 🔒 Sécurité & confidentialité

- Les clés API sont stockées dans `~/.codir_ia/secrets.json` (hors repo, ignoré par `.gitignore`)
- L'application tourne **localement** — aucune donnée transmise sauf aux APIs IA sélectionnées
- Les pièces jointes ne sont **pas sauvegardées** sur disque
- Consultez [PRIVACY.md](PRIVACY.md) pour la politique complète

---

*CoDIR IA v16.3.3.22 — © 2025-2026 Robin Sauzet / HiGestion*
