# 🪟 Windows Installation Guide — CoDIR IA v16.3.3.22

---

## 📋 Requirements

- Windows 10 or Windows 11
- Internet connection
- Administrator rights (for Python installation)
- At least **one API key** (OpenAI, Anthropic, Google or Mistral)

---

## Step 1 — Install Python

### Check if Python is already installed

Open Terminal (Win + R, type `cmd`, Enter) and type:

```batch
python --version
```

If you see `Python 3.10.x` or higher → go to step 2.

### Install Python

1. Download Python from [python.org/downloads](https://www.python.org/downloads/windows/)
2. Choose version **3.11.x** or **3.12.x**
3. Run the installer
4. ⚠️ **Make sure to check**: `Add Python to PATH`
5. Click **Install Now**
6. Restart your terminal

---

## Step 2 — Download CoDIR IA

1. Download the ZIP from [GitHub Releases](https://github.com/robinsauzet/codir-ia/releases)
2. Extract to a folder of your choice (e.g. `C:\CoDIR-IA`)

---

## Step 3 — Automatic Installation

Double-click **`setup_windows.bat`**

The script automatically performs (progress [1/5]…[5/5]):
1. Python verification
2. Virtual environment `.venv` creation
3. Dependency installation
4. Desktop shortcut creation
5. Application launch

Full log available at `outputs\setup_windows.log`.

### Manual installation (if script fails)

```batch
cd C:\CoDIR-IA
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

---

## Step 4 — Launch CoDIR IA

### From the Desktop
Double-click the **CoDIR IA** shortcut created during installation.

### From Explorer
Double-click `launch_codir.bat`

### From command line
```batch
win\launch_user.bat
```

The application opens automatically in your default browser
(usually `http://localhost:8501`).

---

## Step 5 — Configure API Keys

On first launch, a dialog box appears to enter your keys.

You can also:
1. Click **⚙️ Configuration** in the top right
2. Enter your keys (OpenAI, Anthropic, Google, Mistral)
3. Click **💾 Save keys**
4. Test each key with the **Test** button

---

## Windows Troubleshooting

| Problem | Solution |
|---------|----------|
| "python is not recognized" | Reinstall Python and check "Add to PATH" |
| "Port 8501 already in use" | Change port: `streamlit run app.py --server.port 8502` |
| App doesn't open | Launch manually: `win\launch_user.bat` |
| pip error | `python -m pip install --upgrade pip` then retry |
| Blinking window | Use `launch_codir.bat` (silent launch via VBS) |

Check `outputs\setup_windows.log` for detailed error information.

---

*CoDIR IA v16.3.3.22 — Windows Installation Guide*
