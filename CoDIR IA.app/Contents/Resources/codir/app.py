import os
import json
import socket
import io
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

import streamlit as st
from dotenv import load_dotenv
from docx import Document

from codir_engine import run_codir_session
from libre_engine import run_free_mode

from utils.secrets_store import Secrets, load_secrets, save_secrets, apply_secrets_to_env, has_any_key
from utils.settings_store import Settings, load_settings, save_settings
from utils.config_paths import ensure_config_dir, get_secrets_path, get_settings_path
from utils.logger import get_logger, log_event
from utils.attachments import prepare_attachments, build_attachments_block
from utils.pptx_export import build_pptx_prompt, parse_json_strict, parse_json_relaxed, create_pptx_from_deck

APP_VERSION = "v16.3.3.22"
TITLE = f"CoDIR IA {APP_VERSION}"

load_dotenv(override=True)  # allow local .env (never committed)
apply_secrets_to_env(load_secrets(), override=False)

cfg_dir = ensure_config_dir()
log_dir = cfg_dir / "logs"
logger = get_logger(log_dir)

st.set_page_config(page_title=TITLE, layout="wide")
st.title(TITLE)
st.caption("Mode CoDIR / Mode Libre — OpenAI · Gemini · Claude · Mistral — (pré-Christopher)")

# Quick access to Configuration (useful if sidebar is collapsed)
c_title = st.columns([1, 0.18])
with c_title[1]:
    if st.button("⚙️ Configuration", help="Configurer les clés API et les modèles"):
        st.session_state["nav_page"] = "Configuration"
        st.rerun()

# Detect first launch without API keys
_initial_secrets = load_secrets()
needs_config = not has_any_key(_initial_secrets)
if needs_config and "nav_page" not in st.session_state:
    # Force navigation to Configuration on first launch
    st.session_state["nav_page"] = "Configuration"

# Optional modal-like configuration dialog on first launch (Streamlit >= 1.30)
if needs_config and not st.session_state.get("config_dialog_shown", False):
    st.session_state["config_dialog_shown"] = True
    if hasattr(st, "dialog"):
        @st.dialog("Configuration des clés API (premier lancement)")
        def _config_dialog():
            st.info("Aucune clé API n'est configurée. Renseigne au moins **une** clé pour démarrer.")
            secrets = load_secrets()
            with st.form("config_dialog_form"):
                openai_api_key = st.text_input("OPENAI_API_KEY", value=secrets.openai_api_key, type="password")
                anthropic_api_key = st.text_input("ANTHROPIC_API_KEY", value=secrets.anthropic_api_key, type="password")
                google_api_key = st.text_input("GOOGLE_API_KEY", value=secrets.google_api_key, type="password")
                mistral_api_key = st.text_input("MISTRAL_API_KEY", value=secrets.mistral_api_key, type="password")
                saved = st.form_submit_button("💾 Enregistrer")
            if saved:
                new_s = Secrets(
                    openai_api_key=openai_api_key,
                    anthropic_api_key=anthropic_api_key,
                    google_api_key=google_api_key,
                    mistral_api_key=mistral_api_key,
                )
                save_secrets(new_s)
                apply_secrets_to_env(new_s, override=True)
                st.success("Clés enregistrées. Tu peux démarrer une Session CoDIR.")
                st.session_state["nav_page"] = "Session CoDIR"
                st.rerun()
        _config_dialog()
    else:
        st.warning("Aucune clé API détectée : ouvre **Configuration** dans la barre latérale pour les saisir.")

# -------------------------
# Session state
# -------------------------
if "last_result" not in st.session_state:
    st.session_state["last_result"] = None
if "last_docx" not in st.session_state:
    st.session_state["last_docx"] = None
if "last_pptx" not in st.session_state:
    st.session_state["last_pptx"] = None
if "last_meta" not in st.session_state:
    st.session_state["last_meta"] = {}

settings = load_settings()

# -------------------------
# Sidebar navigation
# -------------------------
with st.sidebar:
    st.header("Navigation")
    page = st.radio("Aller à", ["Session CoDIR", "Mode Libre", "Configuration", "Aide"], index=0, key="nav_page")

    st.markdown("---")
    st.header("Paramètres (session)")
    mode_label = st.selectbox(
        "Mode",
        ["Équilibré (recommandé)", "Économie", "Qualité"],
        index=0 if settings.mode_default == "equilibre" else (1 if settings.mode_default == "eco" else 2),
    )
    # Apply mode presets (light-touch)
    if mode_label.startswith("Économie"):
        temperature_default = 0.3
        max_tokens_default = 1200
    elif mode_label.startswith("Qualité"):
        temperature_default = 0.5
        max_tokens_default = 2500
    else:
        temperature_default = settings.temperature
        max_tokens_default = settings.max_output_tokens

    temperature = st.slider("Température", 0.0, 1.0, float(temperature_default))
    max_tokens = st.number_input("Max output tokens", min_value=256, max_value=8000, value=int(max_tokens_default))

    st.markdown("---")
    st.caption("Modèles (IDs) – visibles/modifiables en page Configuration")

# -------------------------
# Helpers
# -------------------------
def export_docx(result: dict) -> bytes:
    doc = Document()
    doc.add_heading("CoDIR IA – Compte-rendu", level=0)
    doc.add_paragraph(f"Version : {APP_VERSION}")
    doc.add_paragraph(f"Date : {datetime.now().strftime('%d/%m/%Y')}")
    meta = result.get("inputs", {}).get("attachments_meta", {}) or {}
    if meta:
        doc.add_paragraph(f"Pièces jointes : {meta.get('files',0)} fichier(s) | tokens_est ~{meta.get('tokens_est',0)} | tronqué={meta.get('truncated',False)}")
    doc.add_paragraph("")
    doc.add_heading("Brief initial", level=1)
    doc.add_paragraph(result.get("inputs", {}).get("brief", ""))

    outputs = result.get("outputs", {})
    doc.add_heading("Stratégie", level=1); doc.add_paragraph(outputs.get("strategie",""))
    doc.add_heading("Brief CoDIR (redistribué)", level=1); doc.add_paragraph(outputs.get("brief_codir",""))
    doc.add_heading("Marketing & Communication", level=1); doc.add_paragraph(outputs.get("marketing",""))
    doc.add_heading("Finance & Fiscalité (FR)", level=1); doc.add_paragraph(outputs.get("finance",""))
    doc.add_heading("Direction Générale – Synthèse", level=1); doc.add_paragraph(outputs.get("direction_generale",""))

    bio = io.BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio.read()

def _test_provider(provider: str, secrets: Secrets, settings: Settings):
    # Minimal "ping" test. max_output_tokens=1..5 (per bon de commande).
    prompt = "Ping"
    system = "Réponds uniquement par OK."
    kwargs = {"temperature": 0.0, "max_tokens": 5}
    apply_secrets_to_env(secrets, override=True)

    if provider == "openai":
        from providers.openai_provider import call_openai
        return call_openai(prompt, system=system, model=settings.openai_model_id, **kwargs)
    if provider == "anthropic":
        from providers.claude_provider import call_claude
        return call_claude(prompt, system=system, model=settings.anthropic_model_id, **kwargs)
    if provider == "google":
        from providers.gemini_provider import call_gemini
        return call_gemini(prompt, system=system, model=settings.google_model_id, **kwargs)
    if provider == "mistral":
        from providers.mistral_provider import call_mistral
        return call_mistral(prompt, system=system, model=settings.mistral_model_id, **kwargs)
    raise ValueError("provider inconnu")


def repair_pptx_json(
    provider: str,
    bad_json_text: str,
    settings: Settings,
    parse_error: str | None = None,
    attempt: int = 1,
) -> str:
    """Ask the same provider to repair JSON and output ONLY valid, contentful JSON."""
    err = (parse_error or "").strip()
    prompt = (
        "Tu es un correcteur JSON. Répare le JSON ci-dessous pour qu'il soit STRICTEMENT valide.\n"
        "Contexte: ce JSON sert à générer un PowerPoint de synthèse du compte rendu CoDIR.\n"
        "Règles:\n"
        "- Réponds UNIQUEMENT avec du JSON (aucun Markdown, aucun texte).\n"
	        "- Entre 4 et 9 slides de contenu (pas la page de titre).\n"
	        "- Chaque slide a title (non vide) + bullets (liste de strings).\n"
	        "- Chaque slide doit être business-grade, sans bruit technique.\n"
        "- Interdit: bullets vides, 'N/A', '...', placeholders.\n"
	        "- Si le JSON est vide ou pauvre, RECONSTRUIS un JSON complet et utile (toujours 4-9 slides).\n"
        + (f"Erreur de parsing/validation observée: {err}\n" if err else "")
        + f"Tentative: {attempt}\n"
        "JSON à réparer (ou à reconstruire si nécessaire):\n---\n"
        + (bad_json_text or "")
        + "\n---"
    )
    system = "Tu génères uniquement un JSON strict et valide."
    if provider == "openai":
        from providers.openai_provider import call_openai
        resp = call_openai(prompt, system=system, model=settings.openai_model_id, temperature=0.0, max_tokens=1400)
        return resp.get("output","")
    if provider == "google":
        from providers.gemini_provider import call_gemini
        resp = call_gemini(prompt, system=system, model=settings.google_model_id, temperature=0.0, max_tokens=1400)
        return resp.get("output","")
    if provider == "anthropic":
        from providers.claude_provider import call_claude
        resp = call_claude(prompt, system=system, model=settings.anthropic_model_id, temperature=0.0, max_tokens=1400)
        return resp.get("output","")
    from providers.mistral_provider import call_mistral
    resp = call_mistral(prompt, system=system, model=settings.mistral_model_id, temperature=0.0, max_tokens=1400)
    return resp.get("output","")

def generate_pptx(report_text: str, settings: Settings) -> bytes:
    """
    Generate a PPTX via a strict JSON contract.

    Robustness:
      1) Ensure keys from secrets.json are applied to env (so providers are available)
      2) DNS preflight per provider host (skip providers that cannot be resolved)
      3) Save raw model output to outputs/
      4) Parse with conservative cleanup (extract JSON object, normalize quotes, remove trailing commas)
      5) If invalid JSON, ask SAME provider to repair JSON (2nd pass) and retry parsing
      6) Persist attempts/errors to outputs/pptx_attempts_<ts>.json
    """
    # Make sure secrets.json overrides any blank env values
    try:
        apply_secrets_to_env(load_secrets(), override=True)
    except Exception:
        pass

    # PPTX helpers (validation / normalization / fallback)
    from utils.pptx_export import coerce_deck, fallback_deck_from_report, validate_deck, _extract_json_object

    order = ["openai", "google", "anthropic", "mistral"]
    prompt = build_pptx_prompt(report_text)
    system = "Tu génères un JSON strict et valide. Réponds uniquement en JSON."

    Path("outputs").mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    attempts_log = []

    # DNS preflight: if a provider host cannot be resolved, skip it and report clearly
    host_map = {
        "openai": "api.openai.com",
        "anthropic": "api.anthropic.com",
        "google": "generativelanguage.googleapis.com",
        "mistral": "api.mistral.ai",
    }

    def has_key(prov: str) -> bool:
        if prov == "openai":
            return bool((os.getenv("OPENAI_API_KEY") or "").strip())
        if prov == "google":
            return bool((os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip())
        if prov == "anthropic":
            return bool((os.getenv("ANTHROPIC_API_KEY") or "").strip())
        if prov == "mistral":
            return bool((os.getenv("MISTRAL_API_KEY") or "").strip())
        return False

    def dns_ok(prov: str) -> bool:
        host = host_map.get(prov)
        if not host:
            return True
        try:
            socket.getaddrinfo(host, 443)
            return True
        except Exception as e:
            attempts_log.append({"provider": prov, "stage": "dns_preflight", "error": str(e), "host": host})
            return False

    last_err = None
    any_tried = False

    for prov in order:
        if not has_key(prov):
            attempts_log.append({"provider": prov, "stage": "skip_no_key"})
            continue
        if not dns_ok(prov):
            continue

        any_tried = True
        try:
            # 1) generate JSON (first pass)
            if prov == "openai":
                from providers.openai_provider import call_openai
                resp = call_openai(prompt, system=system, model=settings.openai_model_id, temperature=0.0, max_tokens=1400)
                txt = resp.get("output", "")
            elif prov == "google":
                from providers.gemini_provider import call_gemini
                resp = call_gemini(prompt, system=system, model=settings.google_model_id, temperature=0.0, max_tokens=1400)
                txt = resp.get("output", "")
            elif prov == "anthropic":
                from providers.claude_provider import call_claude
                resp = call_claude(prompt, system=system, model=settings.anthropic_model_id, temperature=0.0, max_tokens=1400)
                txt = resp.get("output", "")
            else:
                from providers.mistral_provider import call_mistral
                resp = call_mistral(prompt, system=system, model=settings.mistral_model_id, temperature=0.0, max_tokens=1400)
                txt = resp.get("output", "")

            attempts_log.append({"provider": prov, "stage": "generation_ok", "chars": len(txt or "")})

            raw_path = Path("outputs") / f"pptx_json_raw_{prov}_{ts}.txt"
            raw_path.write_text(txt or "", encoding="utf-8", errors="ignore")

            # 2) parse (relaxed) + 3) repair (up to 2 passes) if needed
            payload = None
            try:
                payload = parse_json_relaxed(txt)
            except Exception as e_parse:
                attempts_log.append({"provider": prov, "stage": "parse_failed", "error": str(e_parse)})
                repaired1 = repair_pptx_json(prov, _extract_json_object(txt), settings, parse_error=str(e_parse), attempt=1)
                rep_path = Path("outputs") / f"pptx_json_repaired_{prov}_{ts}.txt"
                rep_path.write_text(repaired1 or "", encoding="utf-8", errors="ignore")
                try:
                    payload = parse_json_relaxed(repaired1)
                except Exception as e_parse2:
                    attempts_log.append({"provider": prov, "stage": "repair_parse_failed", "error": str(e_parse2)})
                    repaired2 = repair_pptx_json(prov, _extract_json_object(repaired1), settings, parse_error=str(e_parse2), attempt=2)
                    rep2_path = Path("outputs") / f"pptx_json_repaired2_{prov}_{ts}.txt"
                    rep2_path.write_text(repaired2 or "", encoding="utf-8", errors="ignore")
                    try:
                        payload = parse_json_relaxed(repaired2)
                    except Exception as e_parse3:
                        attempts_log.append({"provider": prov, "stage": "repair2_parse_failed", "error": str(e_parse3)})
                        # Local fallback: guarantee a non-empty PPTX summarizing the report.
                        from utils.pptx_export import fallback_deck_from_report
                        payload = fallback_deck_from_report(report_text)
                        attempts_log.append({"provider": prov, "stage": "fallback_local_after_repair2", "bullets": sum(len(s.get('bullets',[])) for s in payload.get('slides',[]))})

            # 4) Normalize + validate contentfulness; if still invalid, try a schema/content repair once.
            from utils.pptx_export import coerce_deck, fallback_deck_from_report, validate_deck

            payload = coerce_deck(payload)
            ok, msg = validate_deck(payload)
            if not ok:
                attempts_log.append({"provider": prov, "stage": "schema_or_content_invalid", "error": msg})
                normalized = repair_pptx_json(
                    prov,
                    _extract_json_object(json.dumps(payload, ensure_ascii=False)),
                    settings,
                    parse_error=msg,
                    attempt=3,
                )
                norm_path = Path("outputs") / f"pptx_json_normalized_{prov}_{ts}.txt"
                norm_path.write_text(normalized or "", encoding="utf-8", errors="ignore")
                try:
                    payload = coerce_deck(parse_json_relaxed(normalized))
                    ok2, msg2 = validate_deck(payload)
                    if not ok2:
                        raise ValueError(msg2)
                except Exception as e_norm:
                    attempts_log.append({"provider": prov, "stage": "normalize_failed", "error": str(e_norm)})
                    # Local fallback: guarantee a non-empty PPTX summarizing the report.
                    payload = fallback_deck_from_report(report_text)
                    attempts_log.append({"provider": prov, "stage": "fallback_local", "bullets": sum(len(s.get('bullets',[])) for s in payload.get('slides',[]))})

            out_path = str(Path("outputs") / f"CoDIR_IA_Synthese_{datetime.now().strftime('%Y-%m-%d')}.pptx")
            create_pptx_from_deck(payload, out_path)

            # persist attempts log on success too (useful for audit)
            Path("outputs").mkdir(exist_ok=True)
            (Path("outputs") / f"pptx_attempts_{ts}.json").write_text(
                json.dumps(attempts_log, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return Path(out_path).read_bytes()

        except Exception as e:
            last_err = e
            attempts_log.append({"provider": prov, "stage": "exception", "error": str(e)})
            continue

    # Persist attempts log on failure
    (Path("outputs") / f"pptx_attempts_{ts}.json").write_text(
        json.dumps(attempts_log, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    if not any_tried:
        raise RuntimeError("Impossible de générer le PPTX : aucune clé API disponible. Ouvre ⚙️ Configuration et saisis au moins une clé (OpenAI, Anthropic, Google/Gemini ou Mistral).")

    # Special handling for DNS errors
    msg = str(last_err)
    if "getaddrinfo failed" in msg or "Name or service not known" in msg:
        raise RuntimeError(
            "Impossible de générer le PPTX : problème réseau/DNS (résolution de nom). "
            f"Vérifie ta connexion, ton proxy/pare-feu, et tes DNS. Détails dans outputs/pptx_attempts_{ts}.json. "
            f"Dernière erreur: {last_err}"
        )

    raise RuntimeError(f"Impossible de générer le PPTX. Détails dans outputs/pptx_attempts_{ts}.json. Dernière erreur: {last_err}")


# -------------------------
# Pages
# -------------------------
if page == "Session CoDIR":
    st.subheader("Session CoDIR IA — hebdomadaire")

    cols_top = st.columns([1,1,1])
    with cols_top[0]:
        if st.button("🆕 Nouvelle session", help="Réinitialise l'état (rapport + exports)"):
            st.session_state["last_result"] = None
            st.session_state["last_docx"] = None
            st.session_state["last_pptx"] = None
            st.session_state["last_meta"] = {}
            st.rerun()
    with cols_top[1]:
        export_pptx = st.checkbox("📊 Générer aussi un PowerPoint executive (8 slides)", value=False)
    with cols_top[2]:
        st.caption("Limites pièces jointes : 5 fichiers / 25 Mo (total)")

    brief = st.text_area(
        "Brief du dirigeant",
        height=220,
        value="Contexte business, actualités internes/externes, objectifs, risques/opportunités, points pour décision.",
    )

    uploaded = st.file_uploader(
        "Pièces jointes (pré-Christopher) — PDF/DOCX/PPTX/XLSX/CSV/TXT/MD",
        type=["pdf","docx","pptx","xlsx","xlsm","csv","txt","md"],
        accept_multiple_files=True,
    )

    attachments_block = ""
    attachments_meta = {"files": 0, "tokens_est": 0, "truncated": False}
    if uploaded:
        # Build uploads list with bytes
        uploads = []
        for f in uploaded[: settings.attachments_max_files]:
            data = f.getvalue()
            uploads.append((f.name, f.type or "", data))

        items = prepare_attachments(
            uploads,
            max_files=settings.attachments_max_files,
            max_total_mb=settings.attachments_max_total_mb,
        )
        attachments_block, attachments_meta = build_attachments_block(items, token_budget=settings.attachments_doc_token_budget)

        with st.expander("Voir le contexte extrait (aperçu)", expanded=False):
            st.write(f"Fichiers pris en compte: {attachments_meta['files']} | tokens_est ~{attachments_meta['tokens_est']} | tronqué={attachments_meta['truncated']}")
            st.text_area("Texte extrait (aperçu)", value=attachments_block[:8000], height=220)

    # If no key configured, show warning but allow run (will error gracefully per role)
    if not has_any_key():
        st.warning("Aucune clé API détectée. Allez dans **Configuration** pour enregistrer vos clés (secrets.json).")

    run_btn = st.button("🚀 Lancer la session CoDIR IA", type="primary")

    if run_btn:
        # Clear persisted artifacts for a clean run (avoid showing stale results if a role fails)
        st.session_state["last_result"] = None
        st.session_state["last_docx"] = None
        st.session_state["last_pptx"] = None
        status = st.status("Démarrage…", state="running")
        def cb(step_id: str, label: str):
            status.update(label=label, state="running")

        try:
            log_event(logger, "info", "app", "run_clicked")
            result = run_codir_session(
                brief,
                temperature=float(temperature),
                max_tokens=int(max_tokens),
                attachments_block=attachments_block,
                attachments_meta=attachments_meta,
                cb=cb,
                settings=settings,
                logger=logger,
            )
            st.session_state["last_result"] = result
            st.session_state["last_meta"] = attachments_meta
            st.session_state["last_docx"] = export_docx(result)

            if export_pptx:
                status.update(label="Génération PowerPoint…", state="running")
                # Construire le texte source complet (brief + toutes les directions)
                outputs = result.get("outputs", {}) if isinstance(result, dict) else {}
                meta = st.session_state.get("last_meta", {}) or {}
                report_text = "\n\n".join([
                    "COMPTE RENDU CoDIR IA — SOURCE POUR SYNTHÈSE PPT\n",
                    f"Pièces jointes : {meta.get('files',0)} fichier(s) | tokens_est ~{meta.get('tokens_est',0)} | tronqué={meta.get('truncated',False)}",
                    "\nBRIEF INITIAL (dirigeant)\n" + (result.get("inputs", {}).get("brief", "") if isinstance(result, dict) else ""),
                    "\nSTRATÉGIE\n" + (outputs.get("strategie", "") or ""),
                    "\nBRIEF CODIR (redistribué)\n" + (outputs.get("brief_codir", "") or ""),
                    "\nMARKETING & COMMUNICATION\n" + (outputs.get("marketing", "") or ""),
                    "\nFINANCE & FISCALITÉ (FR)\n" + (outputs.get("finance", "") or ""),
                    "\nDIRECTION GÉNÉRALE — SYNTHÈSE\n" + (outputs.get("direction_generale", "") or ""),
                ])
                # Utiliser le module executive-grade pptx_from_cr
                # Détecter le premier provider disponible (même ordre que generate_pptx)
                import socket as _socket
                _host_map = {
                    "openai": "api.openai.com",
                    "anthropic": "api.anthropic.com",
                    "google": "generativelanguage.googleapis.com",
                    "mistral": "api.mistral.ai",
                }
                def _has_key_pptx(prov):
                    if prov == "openai":    return bool((os.getenv("OPENAI_API_KEY") or "").strip())
                    if prov == "google":    return bool((os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip())
                    if prov == "anthropic": return bool((os.getenv("ANTHROPIC_API_KEY") or "").strip())
                    if prov == "mistral":   return bool((os.getenv("MISTRAL_API_KEY") or "").strip())
                    return False
                def _dns_ok_pptx(prov):
                    host = _host_map.get(prov)
                    if not host: return True
                    try: _socket.getaddrinfo(host, 443); return True
                    except: return False
                _active_provider = None
                for _prov in ["openai", "google", "anthropic", "mistral"]:
                    if _has_key_pptx(_prov) and _dns_ok_pptx(_prov):
                        _active_provider = _prov; break
                if _active_provider is None:
                    raise RuntimeError("Aucun provider disponible pour générer le PowerPoint.")
                from utils.pptx_from_cr import generate_pptx_from_cr_with_provider
                _out_path = str(Path("outputs") / f"CoDIR_IA_Synthese_{datetime.now().strftime('%Y-%m-%d')}.pptx")
                st.session_state["last_pptx"] = generate_pptx_from_cr_with_provider(
                    report_text, _active_provider, settings, output_path=_out_path
                )

            status.update(label="Terminé ✅", state="complete")
        except Exception as e:
            status.update(label=f"Erreur ❌ {e}", state="error")
            st.exception(e)

    # Display last result (persisted)
    if st.session_state["last_result"]:
        r = st.session_state["last_result"]
        st.success("Résultat disponible (persisté dans la session).")
        # Diagnostics IA (par rôle)
        # Diagnostics IA (résumé + tentatives)
        diag_sum = r.get("diagnostics_summary") if isinstance(r, dict) else None
        diag_att = r.get("diagnostics_attempts") if isinstance(r, dict) else None
        if diag_sum:
            # Warning if any role failed
            try:
                failed = [d for d in diag_sum if str(d.get("status","")) == "ERROR"]
            except Exception:
                failed = []
            if failed:
                st.warning("⚠️ Certaines IA/roles ont rencontré une erreur. Voir le détail ci-dessous (Diagnostics).")
            with st.expander("Diagnostics IA — Résumé (1 ligne par rôle)", expanded=False):
                st.dataframe(diag_sum, width="stretch")
        if diag_att:
            with st.expander("Diagnostics IA — Détail des tentatives (fallbacks)", expanded=False):
                st.dataframe(diag_att, width="stretch")
                try:
                    import pandas as _pd
                    _df = _pd.DataFrame(diag_att)
                    st.download_button("⬇️ Export Diagnostics (CSV)", data=_df.to_csv(index=False).encode("utf-8"), file_name="diagnostics_ia.csv", mime="text/csv")
                except Exception:
                    pass
            # Quick explanation of provider selection
            try:
                used = sorted({d.get("provider","") for d in diag_att if d.get("provider")})
                st.caption("Providers utilisés dans cette session : " + (", ".join(used) if used else "aucun"))
            except Exception:
                pass

        st.markdown("### Stratégie")
        st.write(r["outputs"].get("strategie",""))

        st.markdown("### Brief CoDIR (redistribué)")
        st.write(r["outputs"].get("brief_codir",""))

        st.markdown("### Marketing & Communication")
        st.write(r["outputs"].get("marketing",""))

        st.markdown("### Finance & Fiscalité (FR)")
        st.write(r["outputs"].get("finance",""))

        st.markdown("## Synthèse — Direction Générale")
        st.write(r["outputs"].get("direction_generale",""))

        c1, c2 = st.columns([1,1])
        with c1:
            if st.session_state["last_docx"]:
                st.download_button(
                    "📄 Télécharger le compte-rendu (.docx)",
                    data=st.session_state["last_docx"],
                    file_name=f"CODIR_IA_CR_{datetime.now().strftime('%Y-%m-%d')}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
        with c2:
            if st.session_state["last_pptx"]:
                st.download_button(
                    "📊 Télécharger la synthèse (.pptx)",
                    data=st.session_state["last_pptx"],
                    file_name=f"CoDIR_IA_Synthese_{datetime.now().strftime('%Y-%m-%d')}.pptx",
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )

elif page == "Mode Libre":
    st.subheader("Mode Libre — tester et comparer les IA")

    system = st.text_area("Contexte / System prompt (optionnel)", height=120)
    user_prompt = st.text_area("Message", height=200, value="Bonjour à tous ! Faites une courte présentation.")

    cols = st.columns(4)
    with cols[0]: chk_openai = st.checkbox("OpenAI", True)
    with cols[1]: chk_gemini = st.checkbox("Gemini", True)
    with cols[2]: chk_claude = st.checkbox("Claude", True)
    with cols[3]: chk_mistral = st.checkbox("Mistral", True)

    run_btn = st.button("Interroger les IA sélectionnées", type="primary")
    if run_btn:
        providers = [p for p, b in [("OpenAI", chk_openai), ("Gemini", chk_gemini), ("Claude", chk_claude), ("Mistral", chk_mistral)] if b]
        with st.status("Requêtes en cours…", state="running") as status:
            res = run_free_mode(user_prompt, system=system, providers=providers, temperature=float(temperature), max_tokens=int(max_tokens))
            status.update(label="Terminé ✅", state="complete")

        for p, out in res.items():
            st.markdown(f"### {p}")
            st.write(out)

        md = ["# Comparatif des réponses – Mode Libre", f"_Date: {datetime.now().isoformat(timespec='seconds')}_", ""]
        for p, out in res.items():
            md.append(f"## {p}\n{out}\n")
        st.download_button(
            "📝 Télécharger les réponses (.md)",
            data="\n".join(md).encode("utf-8"),
            file_name=f"Libre_Comparatif_{datetime.now().strftime('%Y-%m-%d')}.md",
            mime="text/markdown",
        )

elif page == "Configuration":
    st.subheader("Configuration — clés API & modèles (v16.1.3)")

    st.markdown("### Emplacements locaux")
    st.code(f"secrets.json: {get_secrets_path()}\nsettings.json: {get_settings_path()}\nlogs: {log_dir}")

    secrets = load_secrets()
    settings = load_settings()

    st.markdown("### Clés API (stockées hors repo)")
    with st.form("secrets_form"):
        openai_api_key = st.text_input("OPENAI_API_KEY", value=secrets.openai_api_key, type="password")
        anthropic_api_key = st.text_input("ANTHROPIC_API_KEY", value=secrets.anthropic_api_key, type="password")
        google_api_key = st.text_input("GOOGLE_API_KEY", value=secrets.google_api_key, type="password")
        mistral_api_key = st.text_input("MISTRAL_API_KEY", value=secrets.mistral_api_key, type="password")

        saved = st.form_submit_button("💾 Enregistrer les clés")
        if saved:
            new_s = Secrets(
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
                google_api_key=google_api_key,
                mistral_api_key=mistral_api_key,
            )
            save_secrets(new_s)
            apply_secrets_to_env(new_s, override=True)
            st.success("Clés enregistrées (secrets.json).")

    st.markdown("### Tester une clé (appel minimal)")
    c1, c2, c3, c4 = st.columns(4)
    def test_btn(label, prov, col):
        with col:
            if st.button(f"Tester {label}"):
                try:
                    apply_secrets_to_env(load_secrets(), override=True)
                    out = _test_provider(prov, load_secrets(), load_settings())
                    st.success(out.get("output","OK")[:80] or "OK")
                except Exception as e:
                    st.error(str(e))
    test_btn("OpenAI", "openai", c1)
    test_btn("Claude", "anthropic", c2)
    test_btn("Gemini", "google", c3)
    test_btn("Mistral", "mistral", c4)

    st.markdown("---")
    st.markdown("### Modèles (IDs configurables)")
    with st.form("models_form"):
        openai_model_id = st.text_input("OpenAI model_id", value=settings.openai_model_id)
        google_model_id = st.text_input("Google/Gemini model_id", value=settings.google_model_id)
        anthropic_model_id = st.text_input("Anthropic model_id", value=settings.anthropic_model_id)
        mistral_model_id = st.text_input("Mistral model_id", value=settings.mistral_model_id)

        fallback_enabled = st.checkbox("Fallback automatique activé", value=bool(settings.fallback_enabled))
        fallback_max_attempts = st.number_input("Fallback max tentatives", min_value=1, max_value=5, value=int(settings.fallback_max_attempts))

        attachments_doc_token_budget = st.number_input("Budget tokens pièces jointes (approx.)", min_value=2000, max_value=20000, value=int(settings.attachments_doc_token_budget))

        saved2 = st.form_submit_button("💾 Enregistrer les paramètres")
        if saved2:
            settings.openai_model_id = openai_model_id.strip()
            settings.google_model_id = google_model_id.strip()
            settings.anthropic_model_id = anthropic_model_id.strip()
            settings.mistral_model_id = mistral_model_id.strip()
            settings.fallback_enabled = bool(fallback_enabled)
            settings.fallback_max_attempts = int(fallback_max_attempts)
            settings.attachments_doc_token_budget = int(attachments_doc_token_budget)
            save_settings(settings)
            st.success("Paramètres enregistrés (settings.json).")

elif page == "Aide":
    st.subheader("Aide & troubleshooting")
    st.markdown("""
**Ce qui change en v16.1.3 (résumé)**  
- Clés API : stockées **hors repo** (secrets.json), via l'écran **Configuration**  
- Pièces jointes : MVP pré-Christopher (5 fichiers / 25 Mo) injectées en **Stratégie**  
- UX : statuts visibles pendant l'exécution  
- Export : DOCX + option PPTX (5–10 slides max)

**Si une IA ne répond pas**  
- Vérifie la clé dans Configuration et clique **Tester**  
- Vérifie ton réseau / proxy  
- Certains providers peuvent limiter le débit (rate limit) : le fallback tente un autre provider si disponible.

**Sécurité**  
- Ne commite jamais secrets.json ni .env (le repo les ignore par défaut).
""")