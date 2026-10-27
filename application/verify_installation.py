"""
verify_installation.py — CoDIR-IA v16.5.76 Installation Self-Check

Exécute en 30 secondes toute la chaîne de vérification :
  1. Fichiers projet présents aux bons endroits
  2. Modules `patches/` importables
  3. Hooks `_USE_*`, `_run_briefcheck`, `_compute_confidence` chargés dans codir_engine
  4. Feature flags ON
  5. 125 tests unitaires patches passent
  6. Mini-run end-to-end : briefcheck + confidence_score s'exécutent vraiment
     et remontent dans le dict de retour

Retourne exit code 0 si tout va bien, 1 sinon.

USAGE
-----
    # Depuis la racine de CoDIR-IA-v16.5.76
    python verify_installation.py

Windows (depuis le venv Streamlit) :
    & "C:\\Users\\<user>\\AppData\\Local\\CoDIR-IA\\.venv\\Scripts\\python.exe" verify_installation.py
"""

from __future__ import annotations

import os
import sys
import types
import traceback
from pathlib import Path

# =============================================================================
# HELPERS
# =============================================================================

# Couleurs ANSI (fallback gracieux si Windows sans ANSI)
def _supports_color() -> bool:
    if os.getenv("NO_COLOR"):
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # Active ENABLE_VIRTUAL_TERMINAL_PROCESSING sur la sortie stdout
            return kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7) != 0
        except Exception:
            return False
    return sys.stdout.isatty()


_USE_COLOR = _supports_color()
GREEN = "\033[92m" if _USE_COLOR else ""
RED   = "\033[91m" if _USE_COLOR else ""
YEL   = "\033[93m" if _USE_COLOR else ""
BLUE  = "\033[94m" if _USE_COLOR else ""
BOLD  = "\033[1m"  if _USE_COLOR else ""
DIM   = "\033[2m"  if _USE_COLOR else ""
END   = "\033[0m"  if _USE_COLOR else ""

OK    = f"{GREEN}[ OK ]{END}"
FAIL  = f"{RED}[FAIL]{END}"
WARN  = f"{YEL}[WARN]{END}"
INFO  = f"{BLUE}[INFO]{END}"

# Résultats accumulés
_results: list[tuple[str, str, str]] = []   # (label, status, detail)
_failures: list[str] = []


def _record(label: str, status: str, detail: str = "") -> bool:
    _results.append((label, status, detail))
    if status == FAIL:
        _failures.append(f"{label} — {detail}")
    return status != FAIL


def _section(title: str):
    print(f"\n{BOLD}{BLUE}━━━ {title} ━━━{END}")


def _check(label: str, condition: bool, detail_ok: str = "", detail_fail: str = "") -> bool:
    status = OK if condition else FAIL
    detail = detail_ok if condition else detail_fail
    print(f"  {status} {label}" + (f" {DIM}— {detail}{END}" if detail else ""))
    return _record(label, status, detail if not condition else "")


# =============================================================================
# STEP 1 — Fichiers projet
# =============================================================================

def step1_files() -> bool:
    _section("1/6 — Arborescence projet")
    root = Path.cwd()
    print(f"  {INFO} Répertoire courant : {root}")
    
    # 9.4.51 — contre-recette du 03/10/2026 : l'archive PUBLIQUE ne contient pas la suite de développement (tests,
    # fixtures) et l'autocontrôle échouait sur sept fichiers volontairement absents, ce qui banalisait les vrais
    # incidents. Fichiers OPÉRATIONNELS exigés partout (dont les sondes appelées par les lanceurs) ; les fichiers de la
    # suite ne sont exigés que dans un paquet de développement (dossier tests présent).
    required_files = [
        "codir_engine.py",
        "app.py",
        "requirements.txt",
        "requirements.lock",
        "version.py",                                     # Since v16.5.67 — source unique
        "patches/__init__.py",
        "patches/briefcheck.py",
        "patches/confidence_scorer.py",
        "patches/agent_output_schema.py",
        "patches/lucidity_wording.py",                    # Since v16.5.67
        "scripts/python_runtime_probe.py",                # 9.4.51 — appelé par tous les lanceurs
        "scripts/python_runtime_select.sh",               # 9.4.51 — appelé par les lanceurs macOS
        "scripts/verify_zip_manifest.py",
    ]
    _dev_package = (root / "tests").is_dir()
    print(f"  {INFO} Paquet : {'développement (suite de tests présente)' if _dev_package else 'public (sans suite de tests)'}")
    if _dev_package:
        required_files += [
            "patches/tests/__init__.py",
            "patches/tests/test_briefcheck.py",
            "patches/tests/test_confidence_scorer.py",
            "patches/tests/test_agent_output_schema.py",
            "patches/tests/test_lucidity_wording.py",     # Since v16.5.67
            "tests/test_entity_validator_exclusions.py",  # Since v16.5.67
            "tests/test_version_drift.py",                # Since v16.5.67
        ]
    all_ok = True
    for rel in required_files:
        exists = (root / rel).is_file()
        all_ok &= _check(f"{rel}", exists,
                         detail_fail=f"absent sous {root}")
    return all_ok


# =============================================================================
# STEP 2 — Imports patches
# =============================================================================

def step2_imports() -> bool:
    _section("2/6 — Imports des modules patches")
    ok_all = True
    try:
        from patches.briefcheck import run_briefcheck
        ok_all &= _check("import patches.briefcheck.run_briefcheck", True,
                         detail_ok=f"module chargé")
    except Exception as e:
        ok_all &= _check("import patches.briefcheck.run_briefcheck", False,
                         detail_fail=f"{type(e).__name__}: {e}")
    try:
        from patches.confidence_scorer import compute_delivery_confidence_score
        ok_all &= _check("import patches.confidence_scorer.compute_delivery_confidence_score",
                         True, detail_ok="module chargé")
    except Exception as e:
        ok_all &= _check("import patches.confidence_scorer.compute_delivery_confidence_score",
                         False, detail_fail=f"{type(e).__name__}: {e}")
    return ok_all


# =============================================================================
# STEP 3 — Module codir_engine chargé avec hooks
# =============================================================================

def step3_engine_hooks() -> bool:
    _section("3/6 — Hooks dans codir_engine (chargé)")
    # On mocke claude_provider (seul import non-optionnel dans codir_engine)
    for mod_name in ("providers.claude_provider",):
        if mod_name not in sys.modules:
            fake = types.ModuleType(mod_name)
            fake.call_claude = lambda *a, **k: {"output": "mock", "error": False}
            sys.modules[mod_name] = fake
    
    try:
        import codir_engine
    except Exception as e:
        print(f"    {DIM}Trace:{END}")
        traceback.print_exc()
        return _check("import codir_engine", False,
                      detail_fail=f"{type(e).__name__}: {e}")
    
    _check("import codir_engine", True,
           detail_ok=(codir_engine.__doc__ or "").split("\n")[1].strip() if codir_engine.__doc__ else "")
    
    ok_all = True
    expected_attrs = [
        ("_USE_BRIEFCHECK",     True,  "feature flag briefcheck"),
        ("_USE_CONFIDENCE",     True,  "feature flag confidence"),
        ("_USE_AGENT_JSON",     True,  "feature flag agent JSON (Since v16.5.66)"),
        ("_run_briefcheck",     "not_none",  "référence fonction briefcheck"),
        ("_compute_confidence", "not_none",  "référence fonction scorer"),
        ("_parse_agent_output", "not_none",  "référence fonction parse JSON agent (Since v16.5.66)"),
    ]
    for attr, expected, label in expected_attrs:
        has = hasattr(codir_engine, attr)
        if not has:
            ok_all &= _check(f"{attr} présent", False,
                             detail_fail=f"attribut {attr} absent de codir_engine")
            continue
        value = getattr(codir_engine, attr)
        if expected is True:
            ok_all &= _check(f"{attr} = True ({label})", value is True,
                             detail_ok=f"valeur: {value}",
                             detail_fail=f"valeur inattendue: {value!r}")
        elif expected == "not_none":
            ok_all &= _check(f"{attr} chargé ({label})", value is not None,
                             detail_ok=f"callable prêt",
                             detail_fail=f"{attr} vaut None — import patches/ a échoué dans codir_engine")
    return ok_all


# =============================================================================
# STEP 4 — Feature flags environnement
# =============================================================================

def step4_flags() -> bool:
    _section("4/6 — Variables d'environnement")
    bc = os.getenv("CODIR_USE_BRIEFCHECK")
    cs = os.getenv("CODIR_USE_CONFIDENCE")
    aj = os.getenv("CODIR_USE_AGENT_JSON")
    _check(
        f"CODIR_USE_BRIEFCHECK = {bc if bc is not None else '(non définie, défaut ON)'}",
        bc is None or bc.lower() in ("1", "true", "yes", "on"),
        detail_fail=f"flag désactivé (valeur '{bc}')",
    )
    _check(
        f"CODIR_USE_CONFIDENCE = {cs if cs is not None else '(non définie, défaut ON)'}",
        cs is None or cs.lower() in ("1", "true", "yes", "on"),
        detail_fail=f"flag désactivé (valeur '{cs}')",
    )
    _check(
        f"CODIR_USE_AGENT_JSON = {aj if aj is not None else '(non définie, défaut ON)'}",
        aj is None or aj.lower() in ("1", "true", "yes", "on"),
        detail_fail=f"flag désactivé (valeur '{aj}')",
    )
    return True  # non bloquant


# =============================================================================
# STEP 5 — 54 tests unitaires
# =============================================================================

def step5_unit_tests() -> bool:
    _section("5/6 — Tests unitaires patches (354 tests) + pytest discovery")
    import subprocess
    ok_all = True

    # 9.4.65 — essai natif macOS du 19/10/2026 : l'archive PUBLIQUE ne distribue pas la suite de développement
    # (tests/, patches/tests/). Les exécuter produisait six « FAIL » et le message « Installation incomplète »
    # alors que l'installation était complète. Paquet public : étape sans objet, signalée comme telle ;
    # le fonctionnement du moteur reste contrôlé par le mini-run de l'étape 6.
    _root5 = Path(__file__).resolve().parent
    if not (_root5 / "tests").is_dir() or not (_root5 / "patches" / "tests").is_dir():
        print(f"  {INFO} Paquet public : la suite de tests de développement n'est pas distribuée — étape sans objet.")
        print(f"    {DIM}Le fonctionnement du moteur est contrôlé par le mini-run de l'étape 6.{END}")
        return True

    # 5a) Runner custom (compat avec l'historique, + lucidity_wording v67)
    for test_module in ("patches.tests.test_agent_output_schema",
                        "patches.tests.test_confidence_scorer",
                        "patches.tests.test_briefcheck",
                        "patches.tests.test_lucidity_wording"):   # Since v16.5.67
        print(f"  {INFO} Exécution: python -m {test_module}")
        try:
            result = subprocess.run(
                [sys.executable, "-m", test_module],
                capture_output=True, text=True, timeout=60,
            )
            last_line = result.stdout.strip().split("\n")[-1] if result.stdout else ""
            # Parse "N passed, M failed / T total"
            import re as _re
            m = _re.search(r"(\d+)\s+passed,\s+(\d+)\s+failed", last_line)
            n_passed = int(m.group(1)) if m else 0
            n_failed = int(m.group(2)) if m else -1
            if result.returncode == 0 and n_failed == 0 and n_passed > 0:
                ok_all &= _check(f"{test_module}", True,
                                 detail_ok=last_line)
            else:
                ok_all &= _check(f"{test_module}", False,
                                 detail_fail=f"exit={result.returncode} | {last_line}")
                if result.stderr:
                    print(f"    {DIM}stderr: {result.stderr[:400]}{END}")
        except subprocess.TimeoutExpired:
            ok_all &= _check(f"{test_module}", False,
                             detail_fail="timeout (>60s)")
        except Exception as e:
            ok_all &= _check(f"{test_module}", False,
                             detail_fail=f"{type(e).__name__}: {e}")

    # 5b) Since v16.5.67 — pytest compat check (réponse audit point #1, Since v16.5.67)
    # Les tests doivent aussi passer avec `pytest -q`, pas seulement avec le
    # runner custom. Si pytest est installé, on le lance. Sinon on signale.
    # v17.1.0-B2.3-F.6.6.2 — Fiabilisation du self-check : on NETTOIE les bytecodes
    # (__pycache__) laissés par les runners custom ci-dessus AVANT pytest, et on
    # DÉSACTIVE le cacheprovider pytest — la séquence « runners custom puis pytest
    # patches/tests » pouvait se bloquer sur des __pycache__/.pytest_cache obsolètes.
    print(f"  {INFO} Exécution : pytest -q patches/tests/ (réponse audit Since v16.5.67)")
    try:
        import shutil as _shutil
        for _root, _dirs, _ in os.walk("patches"):
            for _d in list(_dirs):
                if _d in ("__pycache__", ".pytest_cache"):
                    _shutil.rmtree(os.path.join(_root, _d), ignore_errors=True)
    except Exception:
        pass
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
             "patches/tests/"],
            capture_output=True, text=True, timeout=120,
            # F.6.7.1 (P2) — isole les plugins pytest externes : évite les blocages
            # de subprocess liés à l'autoload de plugins tiers (xdist, etc.).
            env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        )
        last = result.stdout.strip().split("\n")[-1] if result.stdout else ""
        if result.returncode == 0 and "passed" in last:
            ok_all &= _check(f"pytest patches/tests/", True, detail_ok=last)
        elif "No module named pytest" in (result.stderr or ""):
            # Non bloquant si pytest n'est pas installé — c'est optionnel
            print(f"    {DIM}pytest non installé — skip (pip install pytest){END}")
        else:
            ok_all &= _check(f"pytest patches/tests/", False,
                             detail_fail=f"exit={result.returncode} | {last}")
    except subprocess.TimeoutExpired:
        ok_all &= _check("pytest patches/tests/", False, detail_fail="timeout")
    except FileNotFoundError:
        print(f"    {DIM}pytest non disponible — skip{END}")
    except Exception as e:
        print(f"    {DIM}pytest check exception: {type(e).__name__}: {e}{END}")

    # 5c) Since v16.5.67 — Anti-drift de version
    # Patch v16.5.75.5 patch — Robustesse Robin :
    # 1. Nettoyer .pytest_cache avant exécution (caches résiduels = faux positifs)
    # 2. Exécution -v pour voir CHAQUE test individuellement (pas juste "violations détectées")
    # 3. Tolérance graduée : fail anti-drift = WARNING pas bloquant (l'installation
    #    fonctionne quand même, juste un drift de version dans la doc à corriger)
    print(f"  {INFO} Exécution : pytest -v tests/test_version_drift.py (anti-drift release)")

    # Nettoyage .pytest_cache pour éviter caches résiduels de releases précédentes
    try:
        import shutil
        for cache_dir in [".pytest_cache", "tests/.pytest_cache"]:
            if os.path.isdir(cache_dir):
                shutil.rmtree(cache_dir, ignore_errors=True)
    except Exception:
        pass  # non-critique

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-v", "--tb=short",
             "tests/test_version_drift.py"],
            capture_output=True, text=True, timeout=60,
            encoding="utf-8", errors="replace",
        )
        output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
        last = output.strip().split("\n")[-1] if output.strip() else ""
        if result.returncode == 0:
            ok_all &= _check("anti-drift version", True,
                             detail_ok=last or "aucune version obsolète dans le repo")
        else:
            # Patch v16.5.75.5 patch — Tolérance graduée : drift = warning pas bloquant
            # (l'installation fonctionne quand même, c'est juste un drift de doc).
            # Ne PAS faire `ok_all &= False` — utiliser un flag "drift_warning"
            # qui produit un message clair mais n'empêche pas l'install.
            print(f"    {DIM}⚠ anti-drift : violations détectées (non bloquant){END}")
            print(f"\n--- Sortie pytest -v anti-drift ---")
            # Afficher TOUTE la sortie (-v fait que c'est plus lisible)
            print(output[-3000:])
            print(f"--- Fin sortie ---")
            print(f"    {DIM}→ Note : anti-drift = check qualité doc, n'empêche pas le run.{END}")
            print(f"    {DIM}→ Pour debugger : cd dans le dossier puis 'pytest -v tests/test_version_drift.py'{END}")
    except Exception as e:
        print(f"    {DIM}anti-drift check exception: {type(e).__name__}: {e}{END}")

    # 5d) Since v16.5.67 — Tests entity exclusions
    print(f"  {INFO} Exécution : tests/test_entity_validator_exclusions.py")
    try:
        result = subprocess.run(
            [sys.executable, "tests/test_entity_validator_exclusions.py"],
            capture_output=True, text=True, timeout=30,
        )
        last = result.stdout.strip().split("\n")[-1] if result.stdout else ""
        if result.returncode == 0:
            ok_all &= _check("entity validator exclusions", True, detail_ok=last)
        else:
            ok_all &= _check("entity validator exclusions", False,
                             detail_fail=f"exit={result.returncode} | {last}")
    except Exception as e:
        print(f"    {DIM}entity_validator_exclusions check: {type(e).__name__}: {e}{END}")

    return ok_all


# =============================================================================
# STEP 6 — Mini-run end-to-end avec providers mockés
# =============================================================================

def step6_runtime() -> bool:
    """Mini-run étanche (9.4.65 — essai natif Windows du 20/10/2026).

    Le mini-run appelait run_codir_session(settings=None) : le moteur chargeait alors les réglages RÉELS de
    l'utilisateur (langue de sortie, par exemple anglaise) et sa mémoire entre CoDIR (historique des séances,
    injecté en tête du brief). Sur le PC de l'éditeur, l'horizon du brief de test n'était plus reconnu :
    1 FAIL et « Installation incomplète » alors que l'installation était complète. Il pouvait aussi écrire dans
    ces dossiers. Il tourne désormais dans des dossiers de configuration, de cache et de données temporaires,
    avec les réglages par défaut, puis les variables d'environnement sont restaurées et le dossier supprimé.
    """
    import tempfile
    import shutil
    keys = ("CODIR_CONFIG_DIR", "CODIR_CACHE_DIR", "CODIR_DATA_DIR")
    saved = {k: os.environ.get(k) for k in keys}
    tmp = tempfile.mkdtemp(prefix="codir_selfcheck_")
    try:
        for k, sub in zip(keys, ("config", "cache", "data")):
            d = os.path.join(tmp, sub)
            os.makedirs(d, exist_ok=True)
            os.environ[k] = d
        return _step6_runtime_isolated()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)


def _step6_runtime_isolated() -> bool:
    _section("6/6 — Mini-run end-to-end (providers mockés)")
    
    # Mocks complets des providers
    def _mock_call(*args, **kwargs):
        return {
            "output": "[MOCK] Analyse factice — test de plomberie.",
            "error": False, "attempt": 1, "duration_s": 0.01,
            "tokens": {"input": 10, "output": 10},
            "provider": "mock", "model": "mock_model",
        }
    
    for provider_mod, fn_name in [
        ("providers.claude_provider",     "call_claude"),
        ("providers.openai_provider",     "call_openai"),
        ("providers.gemini_provider",     "call_gemini"),
        ("providers.mistral_provider",    "call_mistral"),
        ("providers.perplexity_provider", "call_perplexity"),
        ("providers.grok_provider",       "call_grok"),
    ]:
        fake = types.ModuleType(provider_mod)
        setattr(fake, fn_name, _mock_call)
        sys.modules[provider_mod] = fake
    
    # Re-importer codir_engine depuis zéro pour prendre les mocks
    if "codir_engine" in sys.modules:
        del sys.modules["codir_engine"]
    
    try:
        import codir_engine
    except Exception as e:
        print(f"    {DIM}Trace:{END}")
        traceback.print_exc()
        return _check("re-import codir_engine avec mocks", False,
                      detail_fail=f"{type(e).__name__}: {e}")
    
    # Brief de test minimaliste. Mention d'un document pour déclencher briefcheck WARN.
    brief_test = (
        "Test diagnostic Since v16.5.67. Sur la base des documents définitifs de "
        "l'exercice 2022, analyse rapide. Horizon plus d'un an."
    )
    
    print(f"  {INFO} Lancement run_codir_session (pappers_skip=True, brief minimaliste)…")
    
    try:
        result = codir_engine.run_codir_session(
            brief=brief_test,
            temperature=0.4,
            max_tokens=100,
            attachments_block="",
            attachments_meta={},
            cb=None,
            settings=None,
            logger=None,
            pappers_skip=True,
            pappers_confirmed_entity="",
        )
    except Exception as e:
        print(f"    {DIM}Trace:{END}")
        traceback.print_exc()
        return _check("run_codir_session exécuté", False,
                      detail_fail=f"{type(e).__name__}: {e}")
    
    ok_all = _check("run_codir_session exécuté", True,
                    detail_ok="retour dict")
    
    # Vérif 1 : briefcheck dans le dict
    bc = result.get("briefcheck")
    ok_all &= _check("result['briefcheck'] présent et non-null",
                     bc is not None,
                     detail_ok=f"severity={bc.get('doc_check', {}).get('severity') if bc else '?'}, horizon={bc.get('horizon') if bc else '?'}",
                     detail_fail="clé absente ou à None — hook briefcheck ne s'est pas exécuté")
    
    # Vérif 2 : briefcheck a détecté le WARN (brief mentionne docs sans attachment)
    if bc and isinstance(bc, dict):
        sev = bc.get("doc_check", {}).get("severity")
        ok_all &= _check("briefcheck a détecté WARN_BANNER (brief → docs non attachés)",
                         sev == "WARN_BANNER",
                         detail_ok=f"severity={sev}",
                         detail_fail=f"severity={sev} inattendue")
        hor = bc.get("horizon")
        ok_all &= _check("briefcheck a résolu horizon = FY_N1_N3",
                         hor == "FY_N1_N3",
                         detail_ok=f"horizon={hor}",
                         detail_fail=f"horizon={hor} inattendu")
    
    # Vérif 3 : confidence_score dans le dict
    cs = result.get("delivery_confidence_score")
    ok_all &= _check("result['delivery_confidence_score'] présent et non-null",
                     cs is not None,
                     detail_ok=f"score={cs.get('score') if cs else '?'}, grade={cs.get('grade') if cs else '?'}",
                     detail_fail="clé absente ou à None — hook confidence_score ne s'est pas exécuté")
    
    # Vérif 4 : le score a bien la structure attendue
    if cs and isinstance(cs, dict):
        required_keys = {"score", "grade", "component_scores", "penalties",
                         "usage_recommendation", "next_best_actions"}
        missing = required_keys - set(cs.keys())
        ok_all &= _check("structure du score conforme",
                         not missing,
                         detail_ok=f"grade={cs.get('grade')}, score={cs.get('score')}, sous-scores={list(cs.get('component_scores', {}).keys())}",
                         detail_fail=f"clés manquantes: {missing}")
    
    # Vérif 5 : traces présentes dans diag_list
    diag = result.get("diagnostics_attempts", [])
    bc_diag = any(d.get("role") == "briefcheck" for d in diag)
    cs_diag = any(d.get("role") == "confidence_score" for d in diag)
    ok_all &= _check("role=briefcheck présent dans diagnostics_attempts",
                     bc_diag,
                     detail_fail="aucune trace — le CSV exporté n'aura pas la ligne briefcheck")
    ok_all &= _check("role=confidence_score présent dans diagnostics_attempts",
                     cs_diag,
                     detail_fail="aucune trace — le CSV exporté n'aura pas la ligne confidence_score")
    
    return ok_all


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:
    try:
        import version as _ver
        _vlabel = f"v17.0 — build 9.4.65 ({_ver.BUILD_VERSION})"   # 9.4.65 — vérification du 18/10 (P08, C07) : libellé affiché
    except Exception:
        _vlabel = "v17.0 — build 9.4.65"
    print(f"\n{BOLD}CoDIR-IA {_vlabel} — Installation Self-Check{END}")
    print(f"{DIM}Python {sys.version.split()[0]} | Platform {sys.platform}{END}")
    print(f"{DIM}Working dir: {Path.cwd()}{END}")
    
    steps = [
        ("Arborescence",       step1_files),
        ("Imports",            step2_imports),
        ("Hooks moteur",       step3_engine_hooks),
        ("Flags env",          step4_flags),
        ("Tests unitaires",    step5_unit_tests),
        ("Runtime end-to-end", step6_runtime),
    ]
    
    overall = True
    for name, fn in steps:
        try:
            overall &= fn()
        except Exception as e:
            print(f"\n  {FAIL} Étape '{name}' a planté: {type(e).__name__}: {e}")
            traceback.print_exc()
            overall = False
    
    # ─── RÉCAPITULATIF ────────────────────────────────────────────────────────
    _section("RÉCAPITULATIF")
    n_ok   = sum(1 for _, s, _ in _results if s == OK)
    n_fail = sum(1 for _, s, _ in _results if s == FAIL)
    n_warn = sum(1 for _, s, _ in _results if s == WARN)
    print(f"  {GREEN}{n_ok} OK{END}   {RED}{n_fail} FAIL{END}   {YEL}{n_warn} WARN{END}")
    
    if _failures:
        print(f"\n{BOLD}{RED}Échecs détaillés :{END}")
        for f in _failures:
            print(f"  • {f}")
    
    print()
    if overall and n_fail == 0:
        print(f"{BOLD}{GREEN}✓ Installation validée — {_vlabel} opérationnelle.{END}")
        print(f"{DIM}Les hooks briefcheck et confidence_score s'exécuteront à chaque run Streamlit.{END}\n")
        return 0
    else:
        print(f"{BOLD}{RED}✗ Installation incomplète.{END}")
        print(f"{DIM}Lire les échecs ci-dessus. Pour aide :{END}")
        print(f"{DIM}  1. Remonter la sortie complète{END}")
        print(f"{DIM}  2. Vérifier que le ZIP CoDIR IA v17.0 — build 9.4.65 est extrait à la racine de ce dossier{END}")
        print(f"{DIM}  3. Désactiver temporairement : set CODIR_USE_BRIEFCHECK=0 && set CODIR_USE_CONFIDENCE=0 && set CODIR_USE_AGENT_JSON=0{END}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
