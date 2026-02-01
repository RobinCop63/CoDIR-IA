# CoDIR IA v16.0 – CoDIR IA‑IA pour décideurs (open source)

**CoDIR IA** est un outil d'analyse et d'aide à la décision destiné aux dirigeants, managers de transition et consultants.  
Il simule un raisonnement collectif structuré, explicable et contextualisé — **sans automatiser la décision finale**.

- **Local** (Streamlit) : vous exécutez l'app sur votre machine
- **Multi‑fournisseurs** : OpenAI, Claude (Anthropic), Gemini (Google), Mistral
- **Architecture modulaire** (providers séparés) : simple à comprendre et à maintenir
- **Open source** (licence MIT)

---

> ⚠️ **IMPORTANT – Lisez avant utilisation**
> 
> **Coûts API** : CoDIR IA est gratuit et open source, mais l'utilisation des API IA (OpenAI, Anthropic, Google, Mistral) est **payante**. Chaque appel est facturé directement par le fournisseur sur votre compte personnel, selon ses tarifs.
> 
> **Confidentialité** : Vos prompts et données sont transmis aux serveurs des fournisseurs IA que vous utilisez. CoDIR IA ne stocke rien en ligne, mais les éditeurs d'IA peuvent conserver des logs selon leurs conditions d'utilisation.

---

## 🚀 Installation rapide (Windows)

### Méthode 1 : Installation automatique (recommandée)

1. Téléchargez et dézippez le projet
2. Double‑cliquez sur **`setup_windows.bat`**

Le script fait tout automatiquement :
- Crée l'environnement Python
- Installe les dépendances
- Crée le fichier `.env`
- Crée un raccourci sur le Bureau avec l'icône CoDIR IA

### Méthode 2 : Lancement direct

1. Double‑cliquez sur **`launch_codir.bat`**

Au premier lancement, le script crée automatiquement l'environnement et installe les dépendances.

### Créer le raccourci manuellement (si besoin)

Depuis le dossier du projet, exécutez dans PowerShell :

```powershell
powershell -ExecutionPolicy Bypass -File .\win\create_shortcut.ps1
```

---

## 🍎 Installation rapide (macOS)

Dans le dossier du projet :

```bash
chmod +x mac/launch_user.sh
./mac/launch_user.sh
```

Voir le manuel d'installation macOS pour plus de détails.

---

## 🔑 Configuration des clés API (.env)

Éditez le fichier `.env` (créé automatiquement). Sur Windows, si aucune clé n’est détectée, `.env` s’ouvre automatiquement dans le **Bloc-notes** au premier lancement.

Renseignez **uniquement** les clés des fournisseurs que vous utilisez :

| Fournisseur | Variable d'environnement |
|-------------|--------------------------|
| OpenAI | `OPENAI_API_KEY` |
| Anthropic (Claude) | `ANTHROPIC_API_KEY` |
| Google (Gemini) | `GEMINI_API_KEY` ou `GOOGLE_API_KEY` |
| Mistral | `MISTRAL_API_KEY` |

Vous pouvez aussi définir les modèles (ex. `GOOGLE_MODEL=gemini-2.5-flash`).

---

## 💸 Coûts & facturation des API

CoDIR IA est **gratuit et open source**. Cependant :

- **Les appels API sont payants** : chaque requête envoyée à OpenAI, Anthropic, Google ou Mistral est facturée par le fournisseur concerné
- **Facturation directe** : les coûts sont prélevés sur **votre compte personnel** auprès de chaque éditeur
- **Tarifs variables** : consultez les grilles tarifaires de chaque fournisseur avant utilisation
- **Pas de frais cachés** : CoDIR IA ne prélève aucune commission

**Conseil** : Commencez avec des quotas limités sur vos comptes API pour maîtriser vos dépenses.

---

## 🛡️ Confidentialité & traitement des données

### Ce que CoDIR IA fait

- Exécution **100% locale** sur votre machine
- Aucun serveur CoDIR IA distant
- Vos fichiers et historiques restent sur votre ordinateur

### Ce que les fournisseurs IA font

Lorsque vous utilisez un provider (OpenAI / Gemini / Claude / Mistral) :

- Vos **prompts** et le **contexte** sont **transmis à leurs serveurs**
- Chaque fournisseur applique sa propre politique de conservation
- Les données peuvent être utilisées selon leurs CGU (logs, amélioration des modèles, etc.)

### Pour un usage 100% confidentiel

Si vous avez des exigences strictes de confidentialité, utilisez des modèles locaux (non inclus par défaut dans cette version).

---

## 📁 Structure du projet

```
CoDIR-IA-main/
├── app.py                 # Interface Streamlit
├── codir_engine.py        # Moteur décisionnel
├── libre_engine.py        # Mode libre (comparaison IA)
├── providers/             # Connecteurs API par fournisseur
├── prompts/               # Prompts de rôles
├── outputs/               # Sorties locales
├── assets/                # Icônes et ressources
├── win/                   # Scripts Windows
├── mac/                   # Scripts macOS
├── setup_windows.bat      # Installation automatique Windows
├── launch_codir.bat       # Lanceur Windows
├── requirements.txt       # Dépendances Python
└── .env.template          # Template de configuration
```

---

## 📄 Licence

MIT – Voir le fichier `LICENSE` pour les détails.

---

## 👥 Auteurs

**Robin Sauzet** – SASU Hi! Gestion  
**ChatGPT (OpenAI)**  
**Claude (Anthropic)**

*Janvier 2026*
