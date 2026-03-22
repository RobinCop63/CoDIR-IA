# 🍎 Guide d'installation macOS — CoDIR IA v16.3.3.22

---

## 📋 Prérequis

- macOS 12 (Monterey) ou supérieur
- Connexion Internet
- Au moins **une clé API** (OpenAI, Anthropic, Google ou Mistral)

---

## Méthode 1 — Application macOS (recommandé)

### Installation

1. Téléchargez le ZIP depuis [GitHub Releases](https://github.com/robinsauzet/codir-ia/releases)
2. Extrayez le ZIP (double-clic)

### Premier lancement

Double-cliquez sur **`CoDIR IA.app`**

Si macOS affiche *"Impossible d'ouvrir l'application"* :
1. Allez dans **Réglages Système** > **Confidentialité & sécurité**
2. Faites défiler jusqu'à la section **Sécurité**
3. Cliquez **Ouvrir quand même**

*ou* clic droit sur l'app > **Ouvrir** > **Ouvrir**

### Lancements suivants

Double-cliquez simplement sur **`CoDIR IA.app`**

L'application ouvre automatiquement un Terminal, installe les dépendances si nécessaire, puis lance l'interface dans votre navigateur.

---

## Méthode 2 — Terminal (alternative)

Double-cliquez sur **`CoDIR-IA.command`**

Cela ouvre un Terminal et lance automatiquement l'installation + l'application.

Si macOS bloque :
```bash
chmod +x CoDIR-IA.command
```

---

## Méthode 3 — Installation manuelle

```bash
# Dans le dossier CoDIR-IA
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

**Python requis** : 3.10 ou supérieur.

Vérifier : `python3 --version`

Installer si absent : [python.org/downloads/macos](https://www.python.org/downloads/macos/)
*ou* via Homebrew : `brew install python@3.11`

---

## Configuration des clés API

Au premier lancement, une boîte de dialogue apparaît pour saisir vos clés.

Vous pouvez également accéder à la page **Configuration** via la barre latérale :

| Provider | Variable |
|----------|----------|
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Google/Gemini | `GOOGLE_API_KEY` |
| Mistral | `MISTRAL_API_KEY` |

---

## Dépannage macOS

| Problème | Solution |
|----------|----------|
| App bloquée par Gatekeeper | Réglages Système > Confidentialité > Ouvrir quand même |
| "command not found: python3" | Installer Python via [python.org](https://www.python.org) ou `brew install python@3.11` |
| "Port 8501 déjà utilisé" | `streamlit run app.py --server.port 8502` |
| Permissions refusées sur .command | `chmod +x CoDIR-IA.command` |
| L'app se lance mais le navigateur ne s'ouvre pas | Ouvrir manuellement [http://localhost:8501](http://localhost:8501) |

Consultez `outputs/setup_macos.log` pour le détail des erreurs.

---

*CoDIR IA v16.3.3.22 — macOS Installation Guide*
