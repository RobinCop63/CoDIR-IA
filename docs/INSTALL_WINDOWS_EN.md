# Windows install (CoDIR IA v16.0)

## Requirements
- Windows 10/11
- **Python 3.10+** installed (from python.org), ideally with **"Add Python to PATH"** enabled
- Internet connection (deps install + API calls)

## Install (recommended)
1. Download the repo (or archive) and unzip.
2. In the project folder, **double-click**: `setup_windows.bat`

The script:
- creates the `.venv` virtual environment
- installs dependencies
- creates `.env` from `.env.template` (if missing)
- **automatically opens `.env` in Notepad** if no API key is detected
- creates a **Desktop shortcut** (CoDIR IA icon)

## First run
- Start using the Desktop icon (or `launch_codir.bat`).
- If no API key is detected, the script will open `.env` automatically.
- Otherwise, you can open `.env` and paste your API keys (OpenAI, Anthropic, Google, Mistral).

## Quick troubleshooting
- **Python not detected**: reinstall Python and enable "Add Python to PATH".
- **Shortcut PowerShell error**: use `launch_codir.bat` (shortcut is optional).
- **Dependencies**: delete `.venv` and run `setup_windows.bat` again.
