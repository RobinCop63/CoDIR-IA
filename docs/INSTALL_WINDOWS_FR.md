# 🪟 Guide d'installation Windows — CoDIR IA v16.3.3.22

---

## 📋 Prérequis

- Windows 10 ou Windows 11
- Connexion Internet
- Droits administrateur (pour l'installation de Python)
- Au moins **une clé API** (OpenAI, Anthropic, Google ou Mistral)

---

## Étape 1 — Installer Python

### Vérifier si Python est déjà installé

Ouvrez le Terminal (Win + R, tapez `cmd`, Entrée) et tapez :

```batch
python --version
```

Si vous voyez `Python 3.10.x` ou supérieur → passez à l'étape 2.

### Installer Python

1. Téléchargez Python depuis [python.org/downloads](https://www.python.org/downloads/windows/)
2. Choisissez la version **3.11.x** ou **3.12.x**
3. Lancez l'installateur
4. ⚠️ **Cochez absolument** : `Add Python to PATH`
5. Cliquez **Install Now**
6. Redémarrez votre terminal

---

## Étape 2 — Télécharger CoDIR IA

1. Téléchargez le ZIP depuis [GitHub Releases](https://github.com/robinsauzet/codir-ia/releases)
2. Extrayez dans un dossier de votre choix (ex : `C:\CoDIR-IA`)

---

## Étape 3 — Installation automatique

Double-cliquez sur **`setup_windows.bat`**

Le script effectue automatiquement (progression [1/5]…[5/5]) :
1. Vérification de Python
2. Création de l'environnement virtuel `.venv`
3. Installation des dépendances
4. Création du raccourci sur le Bureau
5. Lancement de l'application

Le log complet est disponible dans `outputs\setup_windows.log`.

### Installation manuelle (si le script échoue)

```batch
cd C:\CoDIR-IA
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

---

## Étape 4 — Lancer CoDIR IA

### Depuis le Bureau
Double-cliquez sur le raccourci **CoDIR IA** créé pendant l'installation.

### Depuis l'explorateur
Double-cliquez sur `launch_codir.bat`

### En ligne de commande
```batch
win\launch_user.bat
```

L'application s'ouvre automatiquement dans votre navigateur par défaut
(généralement `http://localhost:8501`).

---

## Étape 5 — Configuration des clés API

Au premier lancement, une boîte de dialogue apparaît pour saisir vos clés.

Vous pouvez également :
1. Cliquer sur **⚙️ Configuration** en haut à droite
2. Saisir vos clés (OpenAI, Anthropic, Google, Mistral)
3. Cliquer **💾 Enregistrer les clés**
4. Tester chaque clé avec le bouton **Tester**

---

## Dépannage Windows

| Problème | Solution |
|----------|----------|
| "python n'est pas reconnu" | Réinstaller Python en cochant "Add to PATH" |
| "Port 8501 déjà utilisé" | Changer le port : `streamlit run app.py --server.port 8502` |
| L'app ne s'ouvre pas | Lancer manuellement : `win\launch_user.bat` |
| Erreur pip | `python -m pip install --upgrade pip` puis réessayer |
| Fenêtre qui clignote | Utiliser `launch_codir.bat` (lancement discret via VBS) |

Consultez `outputs\setup_windows.log` pour le détail des erreurs.

---

*CoDIR IA v16.3.3.22 — Windows Installation Guide*
