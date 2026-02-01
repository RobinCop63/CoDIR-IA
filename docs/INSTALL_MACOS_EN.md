# macOS Installation (CoDIR IA v16.0)

## Two ways to launch CoDIR IA

### Option A — macOS Application (.app) (recommended for releases)
If you use the **macOS release** (distributed archive), you will see `CoDIR-IA.app`.

✅ **You can move the app to Applications and/or pin it to the Dock**: it will still work.

**Important (working folder)**
- On first launch, the app creates (or updates) a writable working folder at:
  - `~/CoDIR-IA/CoDIR-IA-main`
- This is where `.venv`, `.env` and `outputs/` are created.
- Configure your API keys in: `~/CoDIR-IA/CoDIR-IA-main/.env`

On first launch, macOS Gatekeeper may block the app:
1. Double-click `CoDIR-IA.app`
2. If blocked: **Right click → Open → Open**
   - Alternative: **System Settings → Privacy & Security → Open Anyway**

After that: just double-click `CoDIR-IA.app`.

### Option B — Script launch (.command or bash)
From the unzipped release folder:
- Double-click `CoDIR-IA.command` (once allowed by macOS)

Or from the project folder (source):
```bash
chmod +x mac/launch_user.sh
./mac/launch_user.sh
```

## API keys configuration
On first launch, a `.env` file is created automatically (copied from `.env.template`).
Edit `.env` and paste only the keys you need.

👉 If you launch via the `.app`, the file is here: `~/CoDIR-IA/CoDIR-IA-main/.env`

💡 `.env` is hidden on macOS. In Finder: `Cmd + Shift + .`

On first launch via the `.app`, CoDIR IA also opens `.env` in TextEdit and creates a visible helper file `ENV_LOCATION.txt` in the same folder.

## Quick troubleshooting
- **python3 not found**: install Python 3.10+ (python.org) and relaunch.
- **Permission denied**: run `chmod +x mac/launch_user.sh` and retry.
- **Blocked by macOS**: Right click → Open (one time).
