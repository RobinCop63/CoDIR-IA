"""
utils/process_manager.py — v17.1.0-B2.3-F.6.7 (ticket Safe shutdown / no orphan Python)

Problème terrain (Robin, Windows) : on ferme l'onglet Streamlit dans Chrome, mais
le serveur Python continue de tourner en arrière-plan et VERROUILLE le dossier
CoDIR-IA (impossible de le déplacer/supprimer : « dossier en cours d'utilisation »).

Doctrine de sûreté (cf. audit) : on ne « tue JAMAIS tous les python.exe » de la
machine — Python peut servir à d'autres scripts/venvs/notebooks. On ne cible QUE
le process Python/Streamlit lié à CE dossier CoDIR-IA, via un fichier PID horodaté.

Module pur, sans dépendance externe (pas de psutil), multi-plateforme.
"""
from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path
from typing import Optional

_PID_DIRNAME = ".codir_runtime"
_PID_FILENAME = "streamlit.pid"


def runtime_pid_path(app_dir) -> Path:
    return Path(app_dir) / _PID_DIRNAME / _PID_FILENAME


def write_runtime_pid(app_dir, pid: Optional[int] = None) -> Optional[Path]:
    """Écrit le PID courant + le dossier d'ancrage (résolu) + l'horodatage."""
    pid = int(pid if pid is not None else os.getpid())
    p = runtime_pid_path(app_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "pid": pid,
            "app_dir": str(Path(app_dir).resolve()),
            "started_at": time.time(),
        }), encoding="utf-8")
        return p
    except Exception:
        return None


def read_runtime_pid(app_dir) -> Optional[dict]:
    try:
        return json.loads(runtime_pid_path(app_dir).read_text(encoding="utf-8"))
    except Exception:
        return None


def clear_runtime_pid(app_dir) -> bool:
    try:
        p = runtime_pid_path(app_dir)
        if p.exists():
            p.unlink()
            return True
    except Exception:
        pass
    return False


def is_pid_running(pid: Optional[int]) -> bool:
    """Vrai si le PID correspond à un process vivant. Multi-plateforme, sans psutil."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            k = ctypes.windll.kernel32
            h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            try:
                code = ctypes.c_ulong()
                if k.GetExitCodeProcess(h, ctypes.byref(code)):
                    return code.value == STILL_ACTIVE
                return True
            finally:
                k.CloseHandle(h)
        else:
            os.kill(pid, 0)
            return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # le process existe mais n'est pas à nous → vivant
        return True
    except Exception:
        return False
    return True


def detect_orphan(app_dir) -> Optional[int]:
    """PID d'un ANCIEN process CoDIR encore vivant pour CE dossier (≠ process courant).

    Renvoie None s'il n'y en a pas. Sert à proposer à l'utilisateur de l'arrêter
    au démarrage (évite le verrou de dossier sous Windows)."""
    rec = read_runtime_pid(app_dir)
    if not rec:
        return None
    pid = rec.get("pid")
    if not isinstance(pid, int) or pid == os.getpid():
        return None
    rec_dir = rec.get("app_dir")
    try:
        if rec_dir and Path(rec_dir) != Path(app_dir).resolve():
            return None  # PID d'une AUTRE instance/dossier → on n'y touche pas
    except Exception:
        return None
    return pid if is_pid_running(pid) else None


def pid_cmdline(pid: Optional[int]) -> Optional[str]:
    """Ligne de commande du process (best-effort, multi-plateforme). None si indéterminable."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    try:
        if os.name == "nt":
            import subprocess
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine"],
                capture_output=True, text=True, timeout=6)
            return (out.stdout or "").strip() or None
        proc_cmd = Path(f"/proc/{pid}/cmdline")
        if proc_cmd.exists():
            raw = proc_cmd.read_bytes().replace(b"\x00", b" ").decode("utf-8", "ignore").strip()
            return raw or None
        import subprocess  # macOS / BSD
        out = subprocess.run(["ps", "-p", str(pid), "-o", "command="],
                             capture_output=True, text=True, timeout=6)
        return (out.stdout or "").strip() or None
    except Exception:
        return None


def _pid_cwd(pid: int) -> Optional[str]:
    try:
        if os.name != "nt":
            return os.readlink(f"/proc/{pid}/cwd")
    except Exception:
        return None
    return None


def is_codir_process(pid: Optional[int], app_dir=None) -> Optional[bool]:
    """Le PID est-il un process Streamlit/app.py de CE dossier CoDIR-IA ?

    Renvoie True (oui), False (NON — autre process, ex. PID réutilisé), ou None
    (indéterminable — cmdline inaccessible : on ne tranche pas)."""
    cmd = pid_cmdline(pid)
    if not cmd:
        return None
    low = cmd.lower()
    looks_streamlit = ("streamlit" in low and "app.py" in low) or ("streamlit run" in low)
    if not looks_streamlit:
        return False
    # Bonus de précision : si le CWD est lisible (Linux), il doit pointer le dossier.
    if app_dir:
        cwd = _pid_cwd(int(pid))
        if cwd is not None:
            try:
                return Path(cwd).resolve() == Path(app_dir).resolve()
            except Exception:
                return True
    return True


def terminate_pid(pid: Optional[int], app_dir=None, verify: bool = True,
                  allow_unverified: bool = False) -> bool:
    """Arrête UNIQUEMENT le PID donné, et seulement s'il est CONFIRMÉ comme un process
    CoDIR-IA de ce dossier. Jamais tous les python.

    Politique fail-safe (audit) : quand verify=True et app_dir fourni, on n'arrête que si
    is_codir_process(...) is True. Si l'identité est False (autre process, ex. PID réutilisé)
    OU indéterminable (None, cmdline illisible), on REFUSE — sauf allow_unverified=True, mode
    volontairement assumé qui autorise l'arrêt quand l'identité est seulement indéterminable.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if verify and app_dir is not None:
        identity = is_codir_process(pid, app_dir)
        if identity is True:
            pass
        elif identity is None and allow_unverified:
            pass  # indéterminable + autorisation explicite
        else:
            return False  # False (pas notre process) ou None (inconnu) → on ne tue pas
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except Exception:
        return False


def codir_launch_chain61(rows, me: int) -> int:
    """9.4.61 — PID le plus haut de la CHAÎNE DE LANCEMENT de CoDIR IA, à partir du processus courant : sous Windows,
    « streamlit.exe » lance le python.exe du venv, qui lance l'interpréteur ; arrêter l'interpréteur seul pouvait
    laisser un Python ouvert (demande du dirigeant, 13/10/2026). On ne remonte que des lanceurs Python/Streamlit dont la
    ligne de commande porte « streamlit » ou « app.py » — jamais un autre programme, jamais tous les Python.
    rows : [{"ProcessId", "ParentProcessId", "Name", "CommandLine"}]."""
    by = {}
    for r in rows or []:
        try:
            by[int(r.get("ProcessId"))] = r
        except Exception:
            continue
    top, cur, seen = int(me), int(me), set()
    for _ in range(6):
        row = by.get(cur)
        if not row or cur in seen:
            break
        seen.add(cur)
        try:
            ppid = int(row.get("ParentProcessId") or 0)
        except Exception:
            break
        par = by.get(ppid)
        if not par:
            break
        name = str(par.get("Name") or "").lower()
        cmd = str(par.get("CommandLine") or "").lower()
        if name in ("python.exe", "pythonw.exe", "streamlit.exe", "py.exe") and ("streamlit" in cmd or "app.py" in cmd):
            top = cur = ppid
        else:
            break
    return top


def _windows_process_rows61(log=None) -> list:
    """Table des processus Python/Streamlit (Windows) : PowerShell en UTF-8, sinon WMIC ; [] si tout échoue."""
    import subprocess
    import json as _json
    cmd = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
           "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw|streamlit|py)[.]exe$' } | "
           "Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd],
                             capture_output=True, timeout=20, creationflags=0x08000000)
        raw = (out.stdout or b"").decode("utf-8", errors="replace").strip().lstrip("\ufeff")
        data = _json.loads(raw or "[]")
        rows = data if isinstance(data, list) else [data]
        if log is not None:
            log.append(f"powershell rc={out.returncode} lignes={len(rows)}")
        if rows:
            return rows
    except Exception as ex:
        if log is not None:
            log.append(f"powershell indisponible : {type(ex).__name__}: {ex}")
    try:   # repli : WMIC (encore présent sur la plupart des postes Windows 10/11)
        out = subprocess.run(["wmic", "process", "where", "name like 'python%' or name='streamlit.exe' or name='py.exe'",
                              "get", "CommandLine,Name,ParentProcessId,ProcessId", "/format:csv"],
                             capture_output=True, timeout=20, creationflags=0x08000000)
        txt = (out.stdout or b"").decode("utf-8", errors="replace")
        if "\x00" in txt:
            txt = (out.stdout or b"").decode("utf-16", errors="replace")
        rows = []
        for line in txt.splitlines():
            parts = [x.strip() for x in line.split(",")]
            if len(parts) >= 5 and parts[-1].isdigit():
                rows.append({"Node": parts[0], "CommandLine": ",".join(parts[1:-3]), "Name": parts[-3],
                             "ParentProcessId": parts[-2], "ProcessId": parts[-1]})
        if log is not None:
            log.append(f"wmic lignes={len(rows)}")
        return rows
    except Exception as ex:
        if log is not None:
            log.append(f"wmic indisponible : {type(ex).__name__}: {ex}")
    return []


def _shutdown_log61(lines) -> None:
    try:
        from utils.config_paths import get_config_dir
        import time as _t
        d = get_config_dir() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "arret_codir_ia.log").write_text("\n".join([_t.strftime("%Y-%m-%d %H:%M:%S")] + [str(x) for x in lines]) + "\n",
                                             encoding="utf-8")
    except Exception:
        pass


def shutdown_codir_tree61(app_dir=None) -> None:
    """9.4.61/9.4.62 — « Quitter CoDIR IA » arrête le serveur ET sa chaîne de lancement (Windows : streamlit.exe → python.exe
    du venv → interpréteur, et leurs enfants), sans toucher aux autres programmes Python. Recette 9.4.61 : un Python restait
    ouvert ; l'arrêt est désormais tracé (logs/arret_codir_ia.log du dossier de configuration) et a deux replis."""
    log = [f"pid={os.getpid()} ppid={getattr(os, 'getppid', lambda: 0)()} os={os.name}"]
    if app_dir is not None:
        try:
            clear_runtime_pid(app_dir)
        except Exception:
            pass
    if os.name == "nt":
        import subprocess
        # 9.4.65 — essai natif Windows du 20/10/2026 : l'arrêt forcé (taskkill /F) fait sortir Streamlit avec le
        # code 1, et le lanceur affichait « [ERREUR] CoDIR IA s'est arrete avec le code 1 » après un « Quitter »
        # normal. Le drapeau ci-dessous dit au lanceur que l'arrêt a été demandé.
        try:
            _lad = os.environ.get("LOCALAPPDATA") or ""
            if _lad:
                _flag_dir = os.path.join(_lad, "CoDIR-IA", "logs")
                os.makedirs(_flag_dir, exist_ok=True)
                with open(os.path.join(_flag_dir, "ARRET_DEMANDE.flag"), "w", encoding="ascii") as _flag:
                    _flag.write(str(os.getpid()))
        except Exception as ex:
            log.append(f"drapeau d'arrêt non écrit : {type(ex).__name__}")
        try:
            rows = _windows_process_rows61(log)
            top = codir_launch_chain61(rows, os.getpid()) if rows else 0
            if not top or top == os.getpid():
                # repli : le parent direct (relais python.exe du venv ou streamlit.exe), arbre compris
                top = os.getppid() if hasattr(os, "getppid") else 0
                log.append(f"chaîne non trouvée : repli sur le parent {top}")
            else:
                log.append(f"chaîne de lancement : sommet {top}")
            _shutdown_log61(log + [f"taskkill /F /T /PID {top}"])
            if top:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(top)], capture_output=True, timeout=20,
                               creationflags=0x08000000)
        except Exception as ex:
            log.append(f"échec : {type(ex).__name__}: {ex}")
            _shutdown_log61(log)
    try:
        os.kill(os.getpid(), signal.SIGTERM)
    except Exception:
        pass
    os._exit(0)


def request_self_shutdown(app_dir=None) -> None:
    """Arrêt PROPRE du serveur CoDIR courant et de sa chaîne de lancement (9.4.61), jamais d'un autre process Python.

    Nettoie le fichier PID puis termine. Branché sur le bouton « Arrêter CoDIR-IA proprement » de l'interface."""
    shutdown_codir_tree61(app_dir)
