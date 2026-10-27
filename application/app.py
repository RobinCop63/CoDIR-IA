import os
import json
import socket
import io
import copy
import re
import sys
import warnings
import logging as _logging_pdfminer_quiet

# v62.9 — pdfminer signale bruyamment des FontBBox absentes dans certains
# PDF scannés ou anciens. Le parseur retourne déjà un rectangle neutre ; ce
# warning répétitif est non bloquant et polluait le terminal Windows.
_logging_pdfminer_quiet.getLogger("pdfminer.pdffont").setLevel(
    _logging_pdfminer_quiet.ERROR)

# M.5.10.4 — silence le warning ScriptRunContext (workers spawn / bare mode).
# Importé tôt pour couvrir le process parent ; les modules worker l'importent
# aussi de leur côté (héritage spawn).
try:
    import patches.streamlit_quiet  # noqa: F401
except Exception:
    pass
from datetime import datetime
from pathlib import Path

# v16.5.67.11 — Option B — Silencer les UserWarnings d'openpyxl au démarrage.
# Fichiers Excel client (liasses, annexes légales) contiennent couramment des
# headers/footers personnalisés et des zones d'impression nommées qu'openpyxl
# ne sait pas parser. Il les ignore proprement mais émet UserWarning à chaque
# fois, polluant le terminal. Filtres ciblés par module + message précis :
# aucun autre warning n'est masqué.
warnings.filterwarnings(
    "ignore",
    message="Cannot parse header or footer so it will be ignored",
    category=UserWarning,
    module=r"openpyxl\.worksheet\.header_footer",
)
warnings.filterwarnings(
    "ignore",
    message=r"Print area cannot be set to Defined name:.*",
    category=UserWarning,
    module=r"openpyxl\.reader\.workbook",
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

import streamlit as st
import warnings as _warnings39
# v62.13.9.4.39 — un avertissement de bibliothèque n'a rien à faire dans le terminal de
# l'utilisateur : openpyxl prévient qu'un classeur porte une extension de format qu'il
# ignore (mise en forme conditionnelle avancée, validation de données…) ; les données
# sont lues normalement. L'avertissement est filtré ici et consigné au journal de
# préparation par le lecteur de pièces, où il a sa place.
_warnings39.filterwarnings("ignore", message="Unknown extension is not supported", category=UserWarning, module="openpyxl")
try:   # v62.13.9.4.34 (lot 1) — clé du champ « date d'analyse » (rang 1 de l'autorité temporelle)
    from patches.temporal_control_input import STRUCTURED_WIDGET_KEY as STRUCTURED_WIDGET_KEY34
except Exception:
    STRUCTURED_WIDGET_KEY34 = "codir_analysis_as_of_date"
from utils.v62136_fr_path_maintenance import (
    apply_v62136_maintenance,
    repair_docx_semantic_truth,
)
from utils.metadata_clock import (edition_datetime_str as _mc_edition,
                                  file_timestamp as _mc_stamp)
from dotenv import load_dotenv
from docx import Document

from codir_engine import run_codir_session
from libre_engine import run_free_mode

from utils.secrets_store import Secrets, load_secrets, save_secrets, apply_secrets_to_env, has_any_key, has_llm_key
from utils.settings_store import (Settings, load_settings, save_settings,
                                  update_last_target_entity)
from utils.config_paths import ensure_config_dir, get_secrets_path, get_settings_path
from utils.logger import get_logger, log_event
from utils.attachments import prepare_attachments, prepare_attachments_parallel, build_attachments_block, pdf_quick_native_check
from utils.financial_statement_extractor import (
    FS_PIPELINE_CACHE_SCHEMA, FS_PRIORITY_POLICY_VERSION,
)

# ════════════════════════════════════════════════════════════════════════════
# v16.5.75.5 — Wizard run trigger : préparation documentaire au clic "Lancer"
# ════════════════════════════════════════════════════════════════════════════
#
# Avant v75.4 : le parsing parallèle des PJ et le scan financier profond
# s'exécutaient dans le flux principal Streamlit, à chaque rerun (= chaque
# interaction utilisateur). Sur un dossier riche (cas FDE 20 PJ), cela
# représentait 30-60s perdues par interaction (saisie SIREN, modif brief,
# sélection option). Comportement signalé lors d'un test terrain du 13 mai 2026.
#
# Solution : on déplace tout le pipeline lourd (parse + scan FS + build blocks)
# dans cette fonction, appelée QU'AU CLIC "Lancer". Cache par hash MD5 des
# uploads dans st.session_state : si l'utilisateur reclique "Lancer" avec les
# mêmes PJ → 0 retraitement. Cache invalidé automatiquement dès qu'une PJ
# est ajoutée, retirée ou modifiée (hash change).
# ════════════════════════════════════════════════════════════════════════════


def _arrow_safe_df(rows):
    """B.1.3.50 — un tableau de DIAGNOSTICS ne tue jamais un livrable.
    pyarrow refuse les colonnes object melant dict/list et scalaires
    (crash terrain dossier agroalimentaire : colonne 'samples'). Stringification
    deterministe : dict/list -> JSON lisible, None -> '', reste -> str ;
    duration_s -> numerique. Retourne un DataFrame 100% Arrow-compatible."""
    import json as _json
    import pandas as _pd
    _df = _pd.DataFrame(rows)
    for _c in _df.columns:
        if _df[_c].dtype == object:
            _df[_c] = _df[_c].apply(
                lambda v: "" if v is None
                else _json.dumps(v, ensure_ascii=False, default=str)
                if isinstance(v, (dict, list, tuple, set))
                else str(v))
    if "duration_s" in _df.columns:
        _df["duration_s"] = _pd.to_numeric(_df["duration_s"], errors="coerce")
    return _df


def _is_likely_liasse_filename(filename: str) -> bool:
    """v62.11.2 — cible le parseur CERFA/plaquette sur ses vrais documents.

    Le parseur liasse lit toutes les pages avec pdfplumber. L'appliquer aussi
    aux Annual Reports UK dupliquait inutilement le deep scan et pouvait ajouter
    plusieurs minutes. La Financial Proof Layer couvre désormais les rapports
    annuels ; la Couche B liasse reste réservée aux fichiers FR explicites.
    """
    name = str(filename or "").lower()
    return bool(re.search(
        r"(?:liasse|cerfa|(?:^|[_ .-])205[0-9](?:[_ .-]|$)|plaquette|"
        r"comptes?[_ .-]?annuels?)",
        name, re.IGNORECASE))


def _compute_uploads_hash(uploads_list) -> str:
    """MD5 stable des bytes + filenames pour clé de cache de session."""
    import hashlib as _hl
    m = _hl.md5()
    for fname, mtype, data in uploads_list:
        m.update(fname.encode("utf-8", errors="ignore"))
        m.update(b"|")
        m.update(data if isinstance(data, bytes) else bytes(data))
        m.update(b"||")
    return m.hexdigest()


def _prepare_documents_for_run(uploads_list, settings_obj, lang: str,
                                 status_handle=None):
    """
    Pipeline complet de préparation documentaire :
      1. Parsing parallèle des PJ (prepare_attachments_parallel)
      2. Construction de attachments_block
      3. Scan financier profond sur PDFs candidats
      4. Construction de financial_statements_block

    Cache : hash MD5 stocké dans st.session_state — retour instantané si
    re-clic Lancer avec mêmes PJ.

    Returns:
        (attachments_block, attachments_meta, financial_statements_block,
         financial_statements_bundles)
    """
    import streamlit as _st

    if not uploads_list:
        return "", {"files": 0, "tokens_est": 0, "truncated": False}, "", []

    new_hash = _compute_uploads_hash(uploads_list)
    cached = _st.session_state.get("_prepared_docs_cache_v16_5_75_4")
    if (cached and cached.get("hash") == new_hash
            and cached.get("schema_version") == FS_PIPELINE_CACHE_SCHEMA):
        cached_meta = dict(cached.get("attachments_meta") or {})
        cached_diag = dict(cached_meta.get("financial_deep_scan") or {})
        cached_diag.update({
            "cache_hit": True,
            "cache_schema_version": FS_PIPELINE_CACHE_SCHEMA,
            "priority_policy_version": FS_PRIORITY_POLICY_VERSION,
        })
        cached_meta["financial_deep_scan"] = cached_diag
        return (
            cached["attachments_block"],
            cached_meta,
            cached["financial_statements_block"],
            cached["financial_statements_bundles"],
        )

    # ── Pipeline complet (cache miss) ──
    _parse_progress = _st.progress(0.0, text="Préparation du parsing…")

    def _on_parse_progress(done: int, total: int, current_filename: str) -> None:
        try:
            pct = float(done) / float(total) if total > 0 else 1.0
            _parse_progress.progress(
                min(1.0, max(0.0, pct)),
                text=f"📎 Parsing {done}/{total} — {current_filename[:60]}",
            )
        except Exception:
            pass

    items = prepare_attachments_parallel(
        uploads_list,
        max_files=settings_obj.attachments_max_files,
        max_total_mb=settings_obj.attachments_max_total_mb,
        progress_cb=_on_parse_progress,
        # v17.2-M.1 — moteur de parsing : « auto » bascule en multiprocess sur les
        # gros lots (≥ CODIR_PROCESS_MIN_FILES), repli thread/séquentiel garanti.
        # Surchargable via CODIR_PARSE_ENGINE (process|thread|sequential|auto).
        # M.5.10.12 — défaut « thread » et non « auto » : « auto » escaladait en
        # ProcessPoolExecutor (spawn Windows ARM), dont les sous-processus
        # réimportent Streamlit hors `streamlit run` → flood de warnings
        # « Session state does not function… » impossibles à filtrer depuis le
        # process parent. Thread = même process, runtime partagé, terminal propre.
        # Le mode process reste un opt-in volontaire (CODIR_PARSE_ENGINE=process).
        engine=os.environ.get("CODIR_PARSE_ENGINE", "thread"),
    )
    try:
        _parse_progress.progress(1.0, text=f"✅ {len(items)} pièce(s) jointe(s) parsée(s)")
    except Exception:
        pass

    attachments_block, attachments_meta = build_attachments_block(
        items, token_budget=settings_obj.attachments_doc_token_budget
    )
    attachments_meta = dict(attachments_meta or {})

    # v62.11.2 — observabilité du scan financier profond. Ce journal est
    # transmis au moteur via attachments_meta puis exporté dans diagnostics_ia.
    # Il distingue une absence normale de PDF d'une panne de plomberie.
    _deep_scan_stage = "initialization"
    _deep_scan_diag = {
        "status": "NOT_RUN",
        "stage": _deep_scan_stage,
        "files_considered": 0,
        "files_scanned": 0,
        "files_detected": 0,
        "files_failed": 0,
        "files_skipped_budget": 0,
        "files_skipped_limit": 0,
        "liasse_files_considered": 0,
        "liasse_files_failed": 0,
        "liasse_files_ocr_required": 0,
        "liasse_facts_extracted": 0,
        "liasse_documents": [],
        "financial_statements_block_chars": 0,
        "global_budget_tokens": None,
        "per_pdf_cap_tokens": None,
        "max_deep_scan_pdfs": None,
        "exception_type": "",
        "exception_message": "",
        "cache_hit": False,
        "cache_schema_version": FS_PIPELINE_CACHE_SCHEMA,
        "priority_policy_version": FS_PRIORITY_POLICY_VERSION,
        "pdf_priority": [],
    }
    attachments_meta["financial_deep_scan"] = dict(_deep_scan_diag)

    # Scan financier
    financial_statements_block = ""
    financial_statements_bundles = []
    pdf_uploads = []
    n_deep_scanned = 0
    _fs_done = 0
    _fs_failed = 0
    _fs_skipped_budget = 0
    _fs_skipped_limit = 0
    _st.session_state["_liasse_facts_v172"] = []   # v17.2 — défaut (écrasé si PDFs)
    try:
        _deep_scan_stage = "import_financial_statement_extractor"
        # Patch v16.5.70.2 P0-1 + P0-3 : import du budget global + priorisation par filename
        # Patch v16.5.70.3 P1 : limite nombre de PDFs scannés en profondeur
        from utils.financial_statement_extractor import (
            extract_financial_statements_from_pdf,
            build_financial_statements_block,
            rank_pdfs_for_fs_extraction,  # v62.11.3.2 — classement + trace en une passe
            plan_deep_scan,  # v62.12.1 — slots réservés + déduplication (spec §1)
            FS_MAX_DEEP_SCAN_PDFS,
            FS_PER_PDF_CAP,
            FS_GLOBAL_BUDGET,
            FinancialStatementsBundle,
            classify_liasse_or_cerfa_pdf,
        )
        _deep_scan_diag.update({
            "global_budget_tokens": int(FS_GLOBAL_BUDGET),
            "per_pdf_cap_tokens": int(FS_PER_PDF_CAP),
            "max_deep_scan_pdfs": int(FS_MAX_DEEP_SCAN_PDFS),
        })

        # Patch v16.5.70.3 P1 (audit ChatGPT round 7) — Mesure de durée du scan
        # renommée honnêtement (ce n'est pas un vrai timeout — pdfplumber bloque
        # le thread Python pendant le parsing C/Rust de la page, donc impossible
        # de l'interrompre proprement. On mesure et on warn si > 60s).
        # Bug v16.5.70.2 : la constante s'appelait FS_PER_PDF_TIMEOUT_SEC mais ne
        # bloquait jamais rien (renommage honnête en v70.3 pour ne pas mentir).
        # 1. Renommer en FS_DURATION_WARN_SEC (mesure honnête, pas timeout)
        # 2. Si > 60s on log un warning mais on ne kill pas le thread
        import time as _time
        FS_DURATION_WARN_SEC = 60       # log si > 60s (pas un vrai timeout)

        # Filtrer les PDFs uploadés — le scan FS ne s'applique qu'aux .pdf
        # (les autres formats sont déjà bien parsés par extract_text_from_upload)
        _deep_scan_stage = "select_pdf_candidates"
        pdf_uploads = [
            u for u in uploads_list
            if (u[0] or "").lower().rsplit(".", 1)[-1] == "pdf"
        ]

        _deep_scan_diag["files_considered"] = len(pdf_uploads)

        if pdf_uploads:
            _deep_scan_stage = "prioritize_pdf_candidates"
            _ranked_pdf_uploads = rank_pdfs_for_fs_extraction(pdf_uploads)
            _priority_details = [dict(_detail) for _upload, _detail in _ranked_pdf_uploads]
            # v62.12.2 — les slots critiques sont réellement exécutés AVANT
            # les archives. La v62.12.1 ne faisait que les étiqueter : un slot
            # « réservé » pouvait arriver après épuisement du budget et recevoir
            # 0 token. Ici, l'ordre de scan garantit un budget strictement
            # positif aux trois familles : états courants, review courante,
            # comparatif N-1. Le rang éditorial d'origine reste tracé.
            plan_deep_scan(_priority_details)
            _scan_pairs = [
                (_upload, _detail)
                for (_upload, _ignored), _detail in zip(_ranked_pdf_uploads, _priority_details)
            ]
            _slot_order = {
                "current_primary_statements": 0,
                "current_review_or_report": 1,
                "comparative_n_minus_1": 2,
                "": 3,
            }
            _scan_pairs.sort(key=lambda pair: (
                _slot_order.get(str(pair[1].get("reserved_slot") or ""), 3),
                int(pair[1].get("rank") or 9999),
            ))
            pdf_uploads_sorted = [_upload for _upload, _detail in _scan_pairs]
            _deep_scan_diag["pdf_priority"] = [_detail for _upload, _detail in _scan_pairs]
            _reserved_count = sum(
                bool(d.get("reserved_slot")) and not d.get("planned_skip_duplicate")
                for d in _deep_scan_diag["pdf_priority"]
            )
            for _scan_order62122, _d in enumerate(
                    _deep_scan_diag["pdf_priority"], start=1):
                _d["scan_order"] = int(_scan_order62122)
                _d["reserved_budget_tokens"] = (
                    int(FS_PER_PDF_CAP) if _d.get("reserved_slot")
                    and not _d.get("planned_skip_duplicate") else 0
                )
            _deep_scan_diag["reserved_slots_count"] = int(_reserved_count)
            _deep_scan_diag["reserved_budget_floor_tokens"] = int(
                _reserved_count * FS_PER_PDF_CAP)
            remaining_budget = FS_GLOBAL_BUDGET
            n_deep_scanned = 0
            _deep_scan_stage = "scan_pdf_candidates"

            _fs_total = len(pdf_uploads_sorted)
            _fs_progress = _st.progress(0.0, text=f"🔎 Scan financier — 0/{_fs_total} PDF(s)")
            _fs_done = 0

            for _priority_index, (filename, mimetype, data) in enumerate(pdf_uploads_sorted):
                _priority_entry = None
                try:
                    _priority_entry = _deep_scan_diag["pdf_priority"][_priority_index]
                    _priority_entry["outcome"] = "pending"
                except Exception:
                    _priority_entry = None
                if _priority_entry is not None and _priority_entry.get("planned_skip_duplicate"):
                    skipped_bundle = FinancialStatementsBundle(
                        filename=filename, total_pages=0,
                        financial_statements_detected=False,
                        notes=["Skipped — doublon du même (classe, exercice, empreinte) — dédup v62.12.1"]
                    )
                    financial_statements_bundles.append(skipped_bundle)
                    _priority_entry["outcome"] = "skipped_duplicate"
                    _fs_done += 1
                    try:
                        _fs_progress.progress(_fs_done / _fs_total,
                            text=f"🔎 Scan financier — {_fs_done}/{_fs_total} ({filename[:40]} : doublon)")
                    except Exception:
                        pass
                    continue

                _is_reserved = bool(_priority_entry and _priority_entry.get("reserved_slot"))
                if remaining_budget <= 1000 and not _is_reserved:
                    skipped_bundle = FinancialStatementsBundle(
                        filename=filename, total_pages=0,
                        financial_statements_detected=False,
                        notes=[f"Skipped — budget global épuisé "
                               f"(remaining_budget={remaining_budget} tokens)"]
                    )
                    financial_statements_bundles.append(skipped_bundle)
                    _fs_skipped_budget += 1
                    if _priority_entry is not None:
                        _priority_entry.update({"outcome": "skipped_budget",
                                                "remaining_budget_tokens": int(remaining_budget)})
                    _fs_done += 1
                    try:
                        _fs_progress.progress(_fs_done / _fs_total,
                            text=f"🔎 Scan financier — {_fs_done}/{_fs_total} ({filename[:40]} : skip budget)")
                    except Exception:
                        pass
                    continue

                if n_deep_scanned >= FS_MAX_DEEP_SCAN_PDFS:
                    skipped_bundle = FinancialStatementsBundle(
                        filename=filename, total_pages=0,
                        financial_statements_detected=False,
                        notes=[f"Skipped — limite {FS_MAX_DEEP_SCAN_PDFS} PDFs deep scan atteinte"]
                    )
                    financial_statements_bundles.append(skipped_bundle)
                    _fs_skipped_limit += 1
                    if _priority_entry is not None:
                        _priority_entry.update({"outcome": "skipped_limit"})
                    _fs_done += 1
                    try:
                        _fs_progress.progress(_fs_done / _fs_total,
                            text=f"🔎 Scan financier — {_fs_done}/{_fs_total} ({filename[:40]} : skip limite)")
                    except Exception:
                        pass
                    continue

                # Les slots réservés sont en tête de la boucle et disposent
                # donc toujours d'un budget positif. Une assertion explicite
                # transforme toute future régression d'ordre en erreur visible.
                token_budget_this_pdf = min(FS_PER_PDF_CAP, remaining_budget)
                if _is_reserved and token_budget_this_pdf <= 1000:
                    raise RuntimeError(
                        "reserved financial slot reached without positive token budget"
                    )

                t_start = _time.time()
                try:
                    bundle = extract_financial_statements_from_pdf(
                        data, filename=filename,
                        token_budget=token_budget_this_pdf,
                    )
                    elapsed = _time.time() - t_start
                    if elapsed > FS_DURATION_WARN_SEC:
                        # Patch v16.5.70.3 P1 — Warning mesure honnête (pas un kill)
                        try:
                            _st.warning(
                                f"⚠ Scan long ({elapsed:.0f}s > {FS_DURATION_WARN_SEC}s warning) — "
                                f"PDF '{filename}' a pris plus de temps que la cible."
                            )
                        except Exception:
                            pass
                    financial_statements_bundles.append(bundle)
                    n_deep_scanned += 1
                    remaining_budget -= bundle.tokens_estimate
                    if _priority_entry is not None:
                        _priority_entry.update({
                            "outcome": ("scanned_detected" if getattr(
                                bundle, "financial_statements_detected", False)
                                else "scanned_no_financial_section"),
                            "token_budget": int(token_budget_this_pdf),
                            "tokens_extracted": int(getattr(bundle, "tokens_estimate", 0) or 0),
                            "sections_detected": list(getattr(
                                bundle, "detected_section_names", lambda: [])()),
                        })
                    _fs_done += 1
                    try:
                        _fs_status = "✓" if getattr(bundle, "financial_statements_detected", False) else "○"
                        _fs_progress.progress(_fs_done / _fs_total,
                            text=f"🔎 Scan financier — {_fs_done}/{_fs_total} ({filename[:40]} {_fs_status})")
                    except Exception:
                        pass
                except Exception as e:
                    error_bundle = FinancialStatementsBundle(
                        filename=filename, total_pages=0,
                        financial_statements_detected=False,
                        notes=[f"Erreur extraction : {type(e).__name__}: {str(e)[:100]}"]
                    )
                    financial_statements_bundles.append(error_bundle)
                    _fs_failed += 1
                    if _priority_entry is not None:
                        _priority_entry.update({
                            "outcome": "scan_error",
                            "exception_type": type(e).__name__,
                            "exception_message": str(e)[:160],
                        })
                    _fs_done += 1
                    try:
                        _fs_progress.progress(_fs_done / _fs_total,
                            text=f"🔎 Scan financier — {_fs_done}/{_fs_total} ({filename[:40]} ✗)")
                    except Exception:
                        pass

            try:
                _fs_progress.progress(1.0, text=f"✅ Scan financier terminé — {_fs_done}/{_fs_total} PDF(s)")
            except Exception:
                pass

            if financial_statements_bundles:
                _deep_scan_stage = "build_financial_statements_block"
                financial_statements_block = build_financial_statements_block(
                    financial_statements_bundles, lang=lang
                )

            _deep_scan_stage = "extract_liasse_facts"
            # v17.2 — Couche B : faits page-cités lus dans les liasses (FAIT),
            # accumulés ici puis promus dans la table après le moteur.
            try:
                from patches.liasse_fact_extractor import extract_liasse_facts as _elf
                _lf_all = []
                _liasse_candidates = []
                _liasse_documents = []
                for _fn, _mt, _data in pdf_uploads_sorted:
                    _lc = classify_liasse_or_cerfa_pdf(_fn, _data)
                    if not _lc.get("detected"):
                        continue
                    _liasse_candidates.append((_fn, _mt, _data, _lc))
                    _liasse_documents.append(dict(_lc))
                _deep_scan_diag["liasse_files_considered"] = len(_liasse_candidates)
                _liasse_failed = 0
                _liasse_ocr = 0
                for _fn, _mt, _data, _lc in _liasse_candidates:
                    _entry = next((x for x in _liasse_documents
                                   if x.get("filename") == _fn), None)
                    if _lc.get("ocr_required"):
                        _liasse_ocr += 1
                        if isinstance(_entry, dict):
                            _entry["outcome"] = "OCR_REQUIRED"
                        continue
                    try:
                        _facts_one = _elf(_data, source_doc=_fn)
                        _lf_all.extend(_facts_one)
                        if isinstance(_entry, dict):
                            _entry["outcome"] = ("facts_extracted" if _facts_one
                                                 else "no_fact_extracted")
                            _entry["facts_extracted"] = len(_facts_one)
                    except Exception as _lf_exc:
                        _liasse_failed += 1
                        if isinstance(_entry, dict):
                            _entry["outcome"] = "extract_error"
                            _entry["error"] = f"{type(_lf_exc).__name__}: {str(_lf_exc)[:160]}"
                _deep_scan_diag["liasse_files_failed"] = _liasse_failed
                _deep_scan_diag["liasse_files_ocr_required"] = _liasse_ocr
                _deep_scan_diag["liasse_facts_extracted"] = len(_lf_all)
                _deep_scan_diag["liasse_documents"] = _liasse_documents
                _st.session_state["_liasse_facts_v172"] = _lf_all
                attachments_meta["liasse_facts"] = _lf_all
                attachments_meta["liasse_documents"] = _liasse_documents
            except Exception as _liasse_exc:
                _st.session_state["_liasse_facts_v172"] = []
                attachments_meta["liasse_facts"] = []
                try:
                    log_event(logger, "warning", "financial_deep_scan",
                              f"liasse extraction failed: {type(_liasse_exc).__name__}: {_liasse_exc}")
                except Exception:
                    pass

        _deep_scan_diag.update({
            "status": ("NO_PDF" if not pdf_uploads
                       else "PARTIAL" if _fs_failed
                       else "OK"),
            "stage": "completed",
            "files_scanned": int(n_deep_scanned),
            "files_detected": int(sum(
                1 for _b in financial_statements_bundles
                if getattr(_b, "financial_statements_detected", False))),
            "files_failed": int(_fs_failed),
            "files_skipped_budget": int(_fs_skipped_budget),
            "files_skipped_limit": int(_fs_skipped_limit),
            "financial_statements_block_chars": len(financial_statements_block or ""),
        })

    except Exception as _fs_outer_exc:
        # v62.11.2 — plus aucun fail-silent. Le run reste fail-closed (bloc
        # financier vide) mais l'erreur est visible à l'utilisateur et dans le CSV.
        _deep_scan_diag.update({
            "status": "ERROR",
            "stage": _deep_scan_stage,
            "files_considered": len(pdf_uploads),
            "files_scanned": int(n_deep_scanned),
            "files_detected": int(sum(
                1 for _b in financial_statements_bundles
                if getattr(_b, "financial_statements_detected", False))),
            "files_failed": int(_fs_failed),
            "files_skipped_budget": int(_fs_skipped_budget),
            "files_skipped_limit": int(_fs_skipped_limit),
            "financial_statements_block_chars": len(financial_statements_block or ""),
            "exception_type": type(_fs_outer_exc).__name__,
            "exception_message": str(_fs_outer_exc)[:500],
        })
        financial_statements_block = ""
        try:
            _st.warning(
                ("⚠ Le scan financier profond a échoué ; les chiffres des PDF ne "
                 "seront pas utilisés comme faits. Consultez diagnostics_ia.csv.")
                if lang == "fr" else
                ("⚠ Deep financial scan failed; PDF figures will not be used as "
                 "facts. See diagnostics_ia.csv."))
        except Exception:
            pass
        try:
            log_event(logger, "error", "financial_deep_scan",
                      f"stage={_deep_scan_stage} | {type(_fs_outer_exc).__name__}: {_fs_outer_exc}")
        except Exception:
            pass

    attachments_meta["financial_deep_scan"] = dict(_deep_scan_diag)
    _st.session_state["_financial_deep_scan_diag_v62112"] = dict(_deep_scan_diag)

    _st.session_state["_prepared_docs_cache_v16_5_75_4"] = {
        "schema_version": FS_PIPELINE_CACHE_SCHEMA,
        "hash": new_hash,
        "attachments_block": attachments_block,
        "attachments_meta": attachments_meta,
        "financial_statements_block": financial_statements_block,
        "financial_statements_bundles": financial_statements_bundles,
    }

    return attachments_block, attachments_meta, financial_statements_block, financial_statements_bundles



from utils.pptx_export import build_pptx_prompt, parse_json_strict, parse_json_relaxed, create_pptx_from_deck
import brief_ui  # v16.5.39 — Dual-mode brief: Terrain + Équipe

APP_VERSION = "v16.5.76"  # fallback (overridden by version.py import)
# v16.5.67 — source unique : version.py à la racine (tentative d'import)
# Fallback sur la constante littérale ci-dessus pour garder compat ancien code.
try:
    from version import APP_VERSION as _V
    APP_VERSION = _V
except Exception:
    pass
# v17.1-A4 (A4-05) — affichage du build à côté de l'ancre de version.
BUILD_VERSION = ""
try:
    from version import BUILD_VERSION as _BV
    BUILD_VERSION = _BV
except Exception:
    pass
# 9.4.65 — gel v17 (essai natif du 21/10) : le titre affichait « CoDIR IA v16.5.76 — build … », et les documents
# remis portaient le même libellé. L'interface affiche désormais « CoDIR IA » seul ; la version produit
# (« CoDIR IA v17.0 (build 9.4.65) ») figure dans les documents, leur marquage art. 50 et la page Aide.
try:
    from version import product_label as _product_label
    VERSION_LABEL = _product_label(with_build=True)
except Exception:
    VERSION_LABEL = "CoDIR IA v17.0"
TITLE = "CoDIR IA"

# ──────────────────────────────────────────────────────────────────────────────
# BILINGUAL DICTIONARIES — v16.5.38
# ──────────────────────────────────────────────────────────────────────────────
UI_LABELS = {
    "fr": {
        "config_btn":           "⚙️ Configuration",
        "config_btn_help":      "Configurer les clés API et les modèles",
        "first_launch_title":   "Configuration des clés API (premier lancement)",
        "no_api_key":           "Aucune clé API configurée. Renseigne au moins une clé pour démarrer.",
        "nav_header":           "Navigation",
        "nav_goto":             "Aller à",
        "nav_codir":            "Session CoDIR",
        "nav_free":             "Mode Libre",
        "nav_config":           "Configuration",
        "nav_help":             "Aide",
        "session_header":       "Session CoDIR IA — hebdomadaire",
        "new_session":          "Nouvelle session",
        "gen_pptx":             "Générer aussi la synthèse PowerPoint",
        "clean_run":            "Repartir de zéro — ignorer l'historique de ce dossier",
        "clean_run_help":       "Aucune action / décision des séances précédentes n'est réinjectée. Idéal pour un test de version isolé.",
        "attachment_limits":    "Limites pièces jointes",
        "brief_label":          "Brief du dirigeant",
        "attachments_label":    "Pièces jointes (pré-Christopher)...",
        "quota_warn_openai":    "⚠️ Quota OpenAI — réduire max_tokens ou attendre.",
        "quota_warn_google":    "⚠️ Quota Google — réduire max_tokens ou passer en mode équilibre.",
        "quota_warn_perplexity":"⚠️ Quota Perplexity — Synthèse des décisions indisponible.",
        "show_context":         "Voir le contexte extrait (aperçu)",
        "no_key_warning":       "⚠️ Aucune clé API détectée — configure au moins une clé.",
        "starting":             "Démarrage…",
        "gen_pptx_status":      "Génération PowerPoint…",
        "no_provider_pptx":     "Aucun provider disponible pour générer le PowerPoint.",
        "providers_used":       "Moteurs d'IA utilisés dans cette session",
        "save_keys":            "💾 Enregistrer les clés",
        "keys_saved":           "Clés enregistrées. Tu peux démarrer une Session CoDIR.",
        "test_key":             "Tester une clé",
        "models_section":       "Modèles (IDs configurables)",
        "sc_section":           "Supply Chain (option A — modèles dédiés)",
        "lang_section":         "Langue de sortie / Output language",
        "lang_label":           "Langue des analyses, DOCX et PPTX",
        "lang_help":            "FR : toutes les analyses et exports restent en français. EN : les modèles répondent exclusivement en anglais, même si les documents soumis sont dans une autre langue.",
        "sys_section":          "Paramètres système",
        "fallback_label":       "Fallback automatique activé",
        "attach_files_label":   "Pièces jointes — max fichiers",
        "attach_mb_label":      "Pièces jointes — max Mo (total)",
        "attach_tokens_label":  "Budget tokens pièces jointes (approx.)",
        "save_params":          "💾 Enregistrer les paramètres",
        "params_saved":         "Paramètres enregistrés — langue de sortie",
        "config_keys_section":  "Configuration — clés API & modèles",
        "help_title":           "Aide et dépannage",
        "models_caption":       "Modèles (IDs) – visibles/modifiables en page Configuration",
        "advanced_settings":    "Réglages avancés",
        "max_tokens_label":     "Longueur maximale des réponses (jetons)",
        "run_dossier_title":    "Détails techniques — dossier de run (pour le support)",
        "run_dossier_download": "Télécharger le dossier de run (JSON)",
        "fallback_max":         "Fallback max tentatives",
        "local_paths_section":  "### Emplacements locaux",
        "test_btn_label":        "Tester {label}",
        "grok_key_label":        "GROK_API_KEY / xAI (Direction Commerciale)",
        "openai_key_label":      "OPENAI_API_KEY (DG / Marketing / fallback)",
        "google_key_label":      "GOOGLE_API_KEY (Finance — Gemini primaire)",
        "free_file_name":        "Libre_Comparatif",

        "help_content":         "**Aide — CoDIR IA**\n\nCoDIR IA analyse vos documents (PDF, DOCX, XLSX…) et produit un compte rendu de comité de direction multi-agents : synthèses par direction, tableau des faits financiers sourcés, alertes et livrables Word / PowerPoint.\n\n**Démarrage rapide**\n1. Renseignez vos clés API dans Configuration.\n2. Déposez vos pièces jointes.\n3. Lancez la session CoDIR puis téléchargez le compte rendu (.docx) et la synthèse (.pptx).\n\n**Bonnes pratiques**\n- Fournissez des comptes récents et complets pour fiabiliser la couche de preuve.\n- Tout est livré : les chiffres et les points que les pièces n'étayent pas sont signalés en place, avec leur statut, pour que vous les vérifiiez à la source citée.\n- La revue humaine reste obligatoire avant toute diffusion.\n\nDétails et historique des versions : dossier « Documentation/4 - Notes de version » (CHANGELOG.md et notes de version).",
        "page_codir_id":        "codir",
        "page_free_id":         "free",
        "page_config_id":       "config",
        "page_help_id":         "help",
        "dialog_first_launch":  "Configuration des clés API (premier lancement)",
        "temperature_label":    "Température",
        "mode_balanced":        "Équilibré (recommandé)",
        "mode_eco":             "Économie",
        "mode_quality":         "Qualité",
        "files_processed":      "Fichiers pris en compte",
        "done_status":          "Terminé ✅",
        "ceo_synthesis_header": "## Synthèse — Direction Générale (CEO)",
        "download_docx":        "📄 Télécharger le compte-rendu (.docx)",
        "download_pptx":        "📊 Télécharger la synthèse (.pptx)",
        "free_run_btn":         "Interroger les IA sélectionnées",
        "free_running":         "Requêtes en cours…",
        "free_compare_header":  "# Comparatif des réponses – Mode Libre",
        "download_md":          "📝 Télécharger les réponses (.md)",
        "api_keys_section":     "### Clés API (stockées hors repo)",
        "anthropic_key_label":  "ANTHROPIC_API_KEY (Stratégie + challenge Finance)",
        "mistral_key_label":    "MISTRAL_API_KEY (fallback générique)",
        "perplexity_key_label": "PERPLEXITY_API_KEY (Synthèse des décisions)",
        "perplexity_key_help":  "Obtenez votre clé sur https://www.perplexity.ai/settings/api",
        "grok_key_help":        "Obtenez votre clé sur https://console.x.ai (compatible aussi XAI_API_KEY)",
        "pappers_key_label":    "PAPPERS_API_KEY (Enrichissement données entreprises — optionnel)",
        "pappers_key_help":     "Obtenez votre clé sur https://www.pappers.fr/api — adresse email professionnelle requise. 100 crédits gratuits à l'inscription.",
        "pappers_status_ok":    "✅ Pappers configuré — enrichissement automatique des données entreprises activé",
        "pappers_banner_siren": "🔍 Enrichissement Pappers — SIREN détecté : **{siren}** (confiance maximale)",
        # ── Since v16.5.69 — UI "Confirmer la cible cross-juridiction" ─────
        "target_entity_section_title": "🎯 Cible cross-juridiction détectée",
        "target_entity_intro_signals": "Signaux natifs détectés dans le brief :",
        "target_entity_no_signals": "ℹ️ Aucun identifiant cross-juridiction détecté dans le brief (pas de SIREN, LEI, CIK, ticker ni numéro Companies House). L'enrichissement multi-sources se fera uniquement sur entité confirmée par vous.",
        "target_entity_n_candidates": "**{n} candidat(s) trouvé(s)** parmi GLEIF / SEC EDGAR / Companies House.",
        "target_entity_select_label": "Confirmer la cible — l'enrichissement multi-sources sera effectué sur l'entité sélectionnée",
        # Patch v16.5.69 — Sentinel choix neutre (plus d'auto-confirm sur index=0)
        "target_entity_option_pending":  "— Sélectionner une cible —",
        "target_entity_pending_warning": "⚠️ Cible non confirmée — sélectionnez explicitement une option avant de lancer la session. Sinon le pipeline tournera en mode v16.5.68 (Pappers cascade) sans enrichissement cross-juridiction.",
        "target_entity_option_skip": "(ne pas utiliser de cible cross-juridiction — sources externes désactivées)",
        "target_entity_option_manual": "(saisir manuellement le nom — recherche par nom sur toutes les sources)",
        "target_entity_manual_label": "Nom de la cible (recherche libre)",
        "target_entity_confirmed_msg": "✅ Cible confirmée : {label}",
        "target_entity_remembered_caption": "🎯 Cible mémorisée : **{name}**",
        "target_entity_remembered_use": "Utiliser",
        "target_entity_remembered_forget": "Changer",
        "target_entity_skip_msg": "⏭ Sources cross-juridiction désactivées pour cette session",
        "target_entity_help_caption": "Pappers (FR) reste piloté indépendamment par son propre bandeau si un SIREN est détecté.",
        # Since v16.5.69 — Mise en garde fuzzy CH (pattern Pappers entity_validator étendu UK)
        "ch_fuzzy_warning_title":   "⚠️ Plusieurs sociétés UK correspondent à votre recherche",
        "ch_fuzzy_warning_caption": "Confirmation requise — sélectionnez la bonne société Companies House parmi les candidats ci-dessous, ou affinez votre recherche par numéro Companies House (CRN).",
        "ch_fuzzy_candidates_label":"Candidats Companies House — choisir avec précaution",
        "ch_fuzzy_card_format":     "**{title}** · CN {cn} · {status} · {address}",
        "ch_fuzzy_safe_caption":    "✅ Match Companies House non ambigu — confirmation automatique.",
        "ch_fuzzy_not_found":       "⚠️ Aucune société Companies House trouvée pour ce nom. Vérifiez l'orthographe ou saisissez un numéro Companies House (CRN) directement dans le brief.",
        "pappers_banner_name":  "🔍 Enrichissement Pappers — Société(s) détectée(s) : **{names}**",
        "pappers_banner_none":  "🔍 Enrichissement Pappers actif — aucune société détectée dans le brief (ajoutez un SIREN pour garantir le matching)",
        "pappers_banner_skip":  "Désactiver l'enrichissement pour cette session",
        "pappers_caption_siren":    "SIREN saisi directement — identification certaine, 0 ambiguïté",
        "pappers_caption_heuristic":"Pré-détection locale (heuristique) — Claude affinera la détection au lancement",
        "pappers_caption_fallback": "Pré-détection heuristique uniquement — configurez ANTHROPIC_API_KEY pour améliorer la précision",
        "pappers_caption_none":     "Saisissez un SIREN dans le brief ou dans les précisions pour une identification certaine",
        # Confirm entity UI
        "confirm_primary":      "Société principale analysée",
        "confirm_hint":         "Société détectée automatiquement — confirmez ou corrigez avant le lancement",
        "confirm_option_keep":  "✓ Confirmer : {name}",
        "confirm_option_manual":"Saisir un SIREN manuellement",
        "confirm_option_none":  "Désactiver l'enrichissement",
        "confirm_siren_label":  "SIREN de la société principale (9 chiffres)",
        "confirm_siren_ph":     "ex : 123456789",
        # Multi-entity
        "multi_primary_label":  "Société principale (reçoit la fiche complète)",
        "multi_secondary_note": "Entité(s) secondaire(s) détectée(s) : {names} — fiche résumée uniquement",
        "pappers_status_ko":    "ℹ️ Pappers non configuré — les agents fonctionneront sans enrichissement des données entreprises",
        # ── v16.5.68 — Sources de données / API externes additionnelles ─────
        "external_sources_section":   "### 🌐 Sources de données / API externes",
        "external_sources_intro":     "Enrichissement multi-juridictions des analyses agents. Toutes les sources sont **optionnelles** — les agents fonctionnent sans aucune source configurée.",
        "external_sources_security_notice": "🔒 **Sécurité** — Les clés API sont stockées localement dans le dossier de configuration de votre OS (chemin affiché dans Réglages), en clair et protégé par votre session. **Ne partagez jamais ce dossier**. Voir `Documentation/2 - Conditions et confidentialite/PRIVACY.md`.",
        "external_sources_pappers":   "**Pappers** (France) — INSEE / INPI / BODACC",
        "external_sources_gleif":     "🌍 **GLEIF / LEI** (mondial) — Identifiant d'entité juridique — *aucune clé requise*",
        "external_sources_sec_edgar": "🇺🇸 **SEC EDGAR** (États-Unis) — Sociétés cotées NYSE / NASDAQ — *User-Agent requis*",
        "external_sources_opensanctions": "🌍 **OpenSanctions** (mondial) — Sanctions, PEP, watchlists",
        "external_sources_companies_house": "**Companies House** *(Public Data)* — Royaume-Uni — Registre des sociétés UK",
        "external_sources_companies_house_document": "**Companies House** *(Document API)* — Royaume-Uni — Téléchargement des filings (PDF / XHTML)",
        "sec_edgar_ua_label":         "SEC_EDGAR_USER_AGENT (US — sociétés cotées)",
        "sec_edgar_ua_help":          "Format requis par SEC.gov : « Prénom Nom email@domaine.com ». Pas de clé API mais identification obligatoire pour rate-limiting (10 req/sec). Voir : https://www.sec.gov/os/accessing-edgar-data",
        "sec_edgar_ua_placeholder":   "Prénom Nom email@domaine.com",
        "opensanctions_label":        "OPENSANCTIONS_API_KEY (sanctions, PEP, watchlists)",
        "opensanctions_help":         "Obtenez votre clé sur https://www.opensanctions.org/api/ — plan gratuit limité, plans payants pour usage commercial. Optionnel — utilisé pour matcher société/dirigeants contre 200+ listes de sanctions internationales.",
        "companies_house_label":      "COMPANIES_HOUSE_API_KEY (Public Data — registre UK)",
        "companies_house_help":       "Obtenez votre clé sur https://developer.company-information.service.gov.uk/ — gratuit, 600 req/5min. Profil de société, statut, dirigeants, filing history.",
        "companies_house_doc_label":  "COMPANIES_HOUSE_DOCUMENT_API_KEY (Document API — téléchargement de filings)",
        "companies_house_doc_help":   "Clé séparée — créer une 2e application au Companies House Developer Hub avec type 'Document API'. Permet de télécharger les PDFs / XHTML des filings (annual return, accounts, etc.). Utilise un endpoint distinct (document-api.company-information.service.gov.uk).",
        # Patch v16.5.69 — Checkbox option avancée Document API
        "ch_doc_advanced_checkbox":   "Utiliser une clé Companies House Document API distincte (option avancée)",
        "ch_doc_advanced_help":       "Par défaut, la clé Public Data ci-dessus est aussi utilisée pour la Document API (fallback gracieux). Cocher cette case si vous avez créé une 2ᵉ application dédiée au Companies House Developer Hub avec type 'Document API' et souhaitez utiliser une clé distincte.",
        "ch_doc_fallback_caption":    "ℹ️ La clé Public Data ci-dessus est utilisée en fallback pour la Document API.",
        # ── Since v16.5.69 — Téléchargement filings UK ───────────────────────
        "ch_filings_dl_section":      "📄 **Téléchargement filings Companies House**",
        "ch_filings_dl_enable":       "Activer le téléchargement automatique des filings UK (PDFs / XHTML)",
        "ch_filings_dl_help":         "Si activé, lors d'une session sur une cible UK, CoDIR-IA téléchargera automatiquement les derniers filings et les ajoutera aux pièces jointes pour Finance / Stratégie. Limite par défaut : 10 documents par session, configurable via `CODIR_CH_DOC_MAX_PER_SESSION`. Cache local dans le dossier de configuration de votre OS.",
        "ch_filings_dl_status":       "Cache documents : **{count}** fichier(s), {size_mb} Mo · Session : {session_count}/{session_max} téléchargements",
        "ch_filings_dl_clear_btn":    "Vider le cache documents",
        "ch_filings_dl_cleared":      "✅ Cache vidé — {n} fichier(s) supprimé(s), {mb} Mo libérés",
        "ext_status_configured":      "✅ Configuré",
        "ext_status_not_configured":  "⚪ Non configuré",
        "ext_status_no_key_needed":   "🔓 Aucune clé requise",
        "ext_status_ua_set":          "✅ User-Agent renseigné",
        "ext_status_ua_missing":      "⚠ User-Agent manquant — saisir avant utilisation",
        "ext_test_btn":               "Tester {label}",
        "ext_test_pending":           "ℹ️ Boutons de test disponibles ci-dessous pour les 6 sources",
        "keys_saved_msg":       "Clés enregistrées (secrets.json).",
        "test_key_section":     "### Tester une clé (appel minimal)",
        "sc_prefilter_help":    "Provider : OpenAI uniquement. Défaut : gpt-5.4 · Alternative : gpt-5.4-mini",
        "sc_primary_help":      "Provider : OpenAI uniquement. Défaut : gpt-5.4 · Alternatives : gpt-5.4-mini, o3",
        "sc_challenge_help":    "Provider : Google uniquement. Défaut : gemini-3.6-flash",
        "lang_fr_label":        "Français",
        "lang_en_label":        "English",

        "params_section":       "Paramètres (session)",
        "mode_label":           "Mode",
        "mode_balanced":        "Équilibré (recommandé)",
        "mode_eco":             "Économie",
        "mode_quality":         "Qualité",
        "new_session_btn":      "🆕 Nouvelle session",
        "new_session_help":     "Réinitialise l'état (rapport + exports)",
        "launch_btn":           "🚀 Lancer la session CoDIR IA",
        "result_available":     "Résultat disponible (persisté dans la session).",
        "some_roles_failed":    "⚠️ Une ou plusieurs IA ont rencontré une erreur ; le détail figure dans « Détails techniques ».",
        "diag_summary":         "Détails techniques — résumé par IA (pour le support)",
        "diag_details":         "Détails techniques — tentatives et relais entre IA (pour le support)",
        "export_diag":          "⬇️ Export Diagnostics (CSV)",
        "no_key_runtime":       "Aucune clé API détectée. Allez dans **Configuration** pour enregistrer vos clés (secrets.json).",
        "no_key_first_run":     "Aucune clé API détectée : ouvre **Configuration** dans la barre latérale pour les saisir.",
        "attachments_full":     "Pièces jointes (pré-Christopher) — PDF/DOCX/PPTX/XLSX/CSV/TXT/MD",
        "attach_over_limit":    "fichier(s) dépassent la limite et seront ignorés.",
        "attach_over_size":     "Le poids total déposé dépasse la limite configurée ; seuls les premiers fichiers entrant dans le quota seront pris en compte.",
        "context_extract":      "Texte extrait (aperçu)",
        "free_mode_header":     "Mode Libre — tester et comparer les IA",
        "free_system_prompt":   "Contexte / System prompt (optionnel)",
        "free_message":         "Message",
        "providers_section":    "Providers principaux",
        "new_providers":        "Nouveaux providers",
        "result_strategy":      "### Stratégie",
        "result_brief_codir":   "### Brief CoDIR (redistribué)",
        "result_marketing":     "### Marketing & Communication",
        "result_finance":       "### Finance & Fiscalité",
        "result_sc":            "### Supply Chain & Performance Opérationnelle",
        "result_commercial":    "### Direction Commerciale",
        "result_synthesis":     "### Synthèse des décisions",
        "result_dg":            "### Direction Générale — Feuille de route T0→T+90j",
        "brief_placeholder":    "Contexte business, actualités internes/externes, objectifs, risques/opportunités, points pour décision.",
        "providers_caption":    "Moteurs d'IA utilisés dans cette session",
    },
    "en": {
        "config_btn":           "⚙️ Settings",
        "config_btn_help":      "Configure API keys and models",
        "first_launch_title":   "API key setup (first launch)",
        "no_api_key":           "No API key configured yet. Enter at least one key to get started.",
        "nav_header":           "Navigation",
        "nav_goto":             "Go to",
        "nav_codir":            "CoDIR Session",
        "nav_free":             "Free Mode",
        "nav_config":           "Settings",
        "nav_help":             "Help",
        "session_header":       "CoDIR IA Session — weekly",
        "new_session":          "New session",
        "gen_pptx":             "Also generate the PowerPoint summary",
        "clean_run":            "Start fresh — ignore this folder's history",
        "clean_run_help":       "No action / decision from previous sessions is reinjected. Ideal for an isolated version test.",
        "attachment_limits":    "Attachment limits",
        "brief_label":          "Executive brief",
        "attachments_label":    "Attachments (pre-Christopher)...",
        "quota_warn_openai":    "⚠️ OpenAI quota — reduce max_tokens or wait.",
        "quota_warn_google":    "⚠️ Google quota — reduce max_tokens or switch to balanced mode.",
        "quota_warn_perplexity":"⚠️ Perplexity quota — Decision Summary unavailable.",
        "show_context":         "Show extracted context (preview)",
        "no_key_warning":       "⚠️ No API key detected — configure at least one key.",
        "starting":             "Starting…",
        "gen_pptx_status":      "Generating PowerPoint…",
        "no_provider_pptx":     "No provider available to generate the PowerPoint.",
        "providers_used":       "AI engines used in this session",
        "save_keys":            "💾 Save keys",
        "keys_saved":           "Keys saved. You can now start a CoDIR session.",
        "test_key":             "Test a key",
        "models_section":       "Configurable model IDs",
        "sc_section":           "Supply Chain (Option A — dedicated models)",
        "lang_section":         "Output language",
        "lang_label":           "Language for analyses, DOCX and PPTX",
        "lang_help":            "FR: all analyses and exports remain in French. EN: models respond exclusively in English, even if submitted documents are in another language.",
        "sys_section":          "System settings",
        "fallback_label":       "Automatic fallback enabled",
        "attach_files_label":   "Attachments — max files",
        "attach_mb_label":      "Attachments — max MB (total)",
        "attach_tokens_label":  "Attachment token budget (approx.)",
        "save_params":          "💾 Save settings",
        "params_saved":         "Settings saved — output language",
        "config_keys_section":  "Settings — API keys & models",
        "help_title":           "Help and troubleshooting",
        "models_caption":       "Model IDs — visible/editable in Settings",
        "advanced_settings":    "Advanced settings",
        "max_tokens_label":     "Maximum response length (tokens)",
        "run_dossier_title":    "Technical details — run dossier (for support)",
        "run_dossier_download": "Download the run dossier (JSON)",
        "fallback_max":         "Fallback max attempts",
        "local_paths_section":  "### Local paths",
        "test_btn_label":        "Test {label}",
        "grok_key_label":        "GROK_API_KEY / xAI (Sales & Commercial)",
        "openai_key_label":      "OPENAI_API_KEY (CEO / Marketing / fallback)",
        "google_key_label":      "GOOGLE_API_KEY (Finance — Gemini primary)",
        "free_file_name":        "Free_Comparison",

        "help_content":         "**Help — CoDIR IA**\n\nCoDIR IA analyses your documents (PDF, DOCX, XLSX…) and produces a multi-agent executive-committee report: per-department syntheses, a sourced financial-facts table, alerts and Word / PowerPoint deliverables.\n\n**Quick start**\n1. Enter your API keys in Configuration.\n2. Drop your attachments.\n3. Run the CoDIR session, then download the report (.docx) and the deck (.pptx).\n\n**Good practice**\n- Provide recent, complete accounts to strengthen the proof layer.\n- Everything is delivered: figures and points that the documents do not support are flagged in place, with their status, so that you can check them at the cited source.\n- Human review remains mandatory before any distribution.\n\nDetails and version history: folder “Documentation/4 - Notes de version” (CHANGELOG.md and release notes).",
        "page_codir_id":        "codir",
        "page_free_id":         "free",
        "page_config_id":       "config",
        "page_help_id":         "help",
        "dialog_first_launch":  "API key setup (first launch)",
        "temperature_label":    "Temperature",
        "mode_balanced":        "Balanced (recommended)",
        "mode_eco":             "Economy",
        "mode_quality":         "Quality",
        "files_processed":      "Files processed",
        "done_status":          "Done ✅",
        "ceo_synthesis_header": "## Executive Summary — CEO",
        "download_docx":        "📄 Download session report (.docx)",
        "download_pptx":        "📊 Download synthesis (.pptx)",
        "free_run_btn":         "Query selected AI models",
        "free_running":         "Queries in progress…",
        "free_compare_header":  "# AI Comparison — Free Mode",
        "download_md":          "📝 Download responses (.md)",
        "api_keys_section":     "### API keys (stored off-repo)",
        "anthropic_key_label":  "ANTHROPIC_API_KEY (Strategy + Finance challenge)",
        "mistral_key_label":    "MISTRAL_API_KEY (generic fallback)",
        "perplexity_key_label": "PERPLEXITY_API_KEY (Decision Summary)",
        "perplexity_key_help":  "Get your key at https://www.perplexity.ai/settings/api",
        "grok_key_help":        "Get your key at https://console.x.ai (also accepts XAI_API_KEY)",
        "pappers_key_label":    "PAPPERS_API_KEY (Company data enrichment — optional)",
        "pappers_key_help":     "Get your key at https://www.pappers.fr/api — professional email required. 100 free credits on signup.",
        "pappers_status_ok":    "✅ Pappers configured — automatic company data enrichment enabled",
        "pappers_banner_siren": "🔍 Pappers enrichment — SIREN detected: **{siren}** (maximum confidence)",
        # ── Since v16.5.69 — UI "Confirm cross-jurisdiction target" ────────
        "target_entity_section_title": "🎯 Cross-jurisdiction target detected",
        "target_entity_intro_signals": "Native signals detected in the brief:",
        "target_entity_no_signals": "ℹ️ No cross-jurisdiction identifier detected in the brief (no SIREN, LEI, CIK, ticker nor Companies House number). Multi-source enrichment will only run on a target you confirm.",
        "target_entity_n_candidates": "**{n} candidate(s) found** across GLEIF / SEC EDGAR / Companies House.",
        "target_entity_select_label": "Confirm the target — multi-source enrichment will run on the selected entity",
        # Patch v16.5.69 — Neutral sentinel choice (no more auto-confirm on index=0)
        "target_entity_option_pending":  "— Select a target —",
        "target_entity_pending_warning": "⚠️ Target not confirmed — explicitly select an option before launching the session. Otherwise the pipeline will run in v16.5.68 mode (Pappers cascade) without cross-jurisdiction enrichment.",
        "target_entity_option_skip": "(do not use a cross-jurisdiction target — external sources disabled)",
        "target_entity_option_manual": "(enter name manually — name search across all sources)",
        "target_entity_manual_label": "Target name (free text search)",
        "target_entity_confirmed_msg": "✅ Target confirmed: {label}",
        "target_entity_remembered_caption": "🎯 Remembered target: **{name}**",
        "target_entity_remembered_use": "Use",
        "target_entity_remembered_forget": "Change",
        "target_entity_skip_msg": "⏭ Cross-jurisdiction sources disabled for this session",
        "target_entity_help_caption": "Pappers (FR) remains driven independently by its own banner if a SIREN is detected.",
        # Since v16.5.69 — Fuzzy CH warning
        "ch_fuzzy_warning_title":   "⚠️ Multiple UK companies match your search",
        "ch_fuzzy_warning_caption": "Confirmation required — pick the right Companies House entity from the candidates below, or refine your search with a Companies House number (CRN).",
        "ch_fuzzy_candidates_label":"Companies House candidates — choose with caution",
        "ch_fuzzy_card_format":     "**{title}** · CN {cn} · {status} · {address}",
        "ch_fuzzy_safe_caption":    "✅ Unambiguous Companies House match — auto-confirmed.",
        "ch_fuzzy_not_found":       "⚠️ No Companies House entity found for this name. Check spelling or provide a Companies House number (CRN) directly in the brief.",
        "pappers_banner_name":  "🔍 Pappers enrichment — Company/ies detected: **{names}**",
        "pappers_banner_none":  "🔍 Pappers enrichment active — no company detected in brief (add a SIREN for unambiguous matching)",
        "pappers_banner_skip":  "Disable enrichment for this session",
        "pappers_caption_siren":    "SIREN provided directly — certain identification, zero ambiguity",
        "pappers_caption_heuristic":"Local pre-detection (heuristic) — Claude will refine at launch if API key is set",
        "pappers_caption_fallback": "Local heuristic only — configure ANTHROPIC_API_KEY to improve accuracy",
        "pappers_caption_none":     "Add a SIREN to your brief or detail fields for certain identification",
        "confirm_primary":      "Primary company being analysed",
        "confirm_hint":         "Company detected automatically — confirm or correct before launch",
        "confirm_option_keep":  "✓ Confirm: {name}",
        "confirm_option_manual":"Enter a SIREN manually",
        "confirm_option_none":  "Disable enrichment",
        "confirm_siren_label":  "Primary company SIREN (9 digits)",
        "confirm_siren_ph":     "e.g. 123456789",
        "multi_primary_label":  "Primary company (receives full data)",
        "multi_secondary_note": "Secondary entity/ies detected: {names} — summary only",
        "pappers_status_ko":    "ℹ️ Pappers not configured — agents will run without company data enrichment",
        # ── v16.5.68 — Additional external data sources ─────────────────────
        "external_sources_section":   "### 🌐 Data sources / External APIs",
        "external_sources_intro":     "Multi-jurisdictional enrichment for agent analyses. All sources are **optional** — agents work without any source configured.",
        "external_sources_security_notice": "🔒 **Security** — API keys are stored locally in your OS configuration folder (the path is displayed in Settings), in plain text and protected by your OS session. **Never share this folder**. See `Documentation/2 - Conditions et confidentialite/PRIVACY.md`.",
        "external_sources_pappers":   "**Pappers** (France) — INSEE / INPI / BODACC",
        "external_sources_gleif":     "🌍 **GLEIF / LEI** (worldwide) — Legal Entity Identifier — *no key required*",
        "external_sources_sec_edgar": "🇺🇸 **SEC EDGAR** (United States) — NYSE / NASDAQ listed companies — *User-Agent required*",
        "external_sources_opensanctions": "🌍 **OpenSanctions** (worldwide) — Sanctions, PEP, watchlists",
        "external_sources_companies_house": "**Companies House** *(Public Data)* — United Kingdom — UK companies register",
        "external_sources_companies_house_document": "**Companies House** *(Document API)* — United Kingdom — Filing downloads (PDF / XHTML)",
        "sec_edgar_ua_label":         "SEC_EDGAR_USER_AGENT (US — listed companies)",
        "sec_edgar_ua_help":          "SEC.gov format requirement: \"FirstName LastName email@domain.com\". No API key but identification mandatory for rate limiting (10 req/sec). See: https://www.sec.gov/os/accessing-edgar-data",
        "sec_edgar_ua_placeholder":   "FirstName LastName email@domain.com",
        "opensanctions_label":        "OPENSANCTIONS_API_KEY (sanctions, PEP, watchlists)",
        "opensanctions_help":         "Get your key at https://www.opensanctions.org/api/ — limited free tier, paid plans for commercial use. Optional — used to match company/officers against 200+ international sanctions lists.",
        "companies_house_label":      "COMPANIES_HOUSE_API_KEY (Public Data — UK register)",
        "companies_house_help":       "Get your key at https://developer.company-information.service.gov.uk/ — free, 600 req/5min. Company profile, status, officers, filing history.",
        "companies_house_doc_label":  "COMPANIES_HOUSE_DOCUMENT_API_KEY (Document API — filing downloads)",
        "companies_house_doc_help":   "Separate key — register a 2nd application at the Companies House Developer Hub with type 'Document API'. Allows download of PDF / XHTML filings (annual return, accounts, etc.). Uses a distinct endpoint (document-api.company-information.service.gov.uk).",
        # Patch v16.5.69 — Advanced option checkbox for Document API
        "ch_doc_advanced_checkbox":   "Use a separate Companies House Document API key (advanced option)",
        "ch_doc_advanced_help":       "By default, the Public Data key above is also used for the Document API (graceful fallback). Check this box if you have registered a 2nd dedicated application at the Companies House Developer Hub with type 'Document API' and want to use a distinct key.",
        "ch_doc_fallback_caption":    "ℹ️ The Public Data key above is used as a fallback for the Document API.",
        # ── Since v16.5.69 — UK filings download ───────────────────────────
        "ch_filings_dl_section":      "📄 **Companies House filing downloads**",
        "ch_filings_dl_enable":       "Enable automatic UK filings download (PDFs / XHTML)",
        "ch_filings_dl_help":         "If enabled, during a session on a UK target, CoDIR-IA automatically downloads the latest filings and adds them to the Finance / Strategy attachments. Default limit: 10 documents per session, configurable through `CODIR_CH_DOC_MAX_PER_SESSION`. The cache is stored in the OS configuration folder.",
        "ch_filings_dl_status":       "Documents cache: **{count}** file(s), {size_mb} MB · Session: {session_count}/{session_max} downloads",
        "ch_filings_dl_clear_btn":    "Clear documents cache",
        "ch_filings_dl_cleared":      "✅ Cache cleared — {n} file(s) deleted, {mb} MB freed",
        "ext_status_configured":      "✅ Configured",
        "ext_status_not_configured":  "⚪ Not configured",
        "ext_status_no_key_needed":   "🔓 No key required",
        "ext_status_ua_set":          "✅ User-Agent set",
        "ext_status_ua_missing":      "⚠ User-Agent missing — set before use",
        "ext_test_btn":               "Test {label}",
        "ext_test_pending":           "ℹ️ Test buttons available below for the 6 sources",
        "keys_saved_msg":       "Keys saved (secrets.json).",
        "test_key_section":     "### Test a key (minimal call)",
        "sc_prefilter_help":    "Provider: OpenAI only. Default: gpt-5.4 · Alternative: gpt-5.4-mini",
        "sc_primary_help":      "Provider: OpenAI only. Default: gpt-5.4 · Alternatives: gpt-5.4-mini, o3",
        "sc_challenge_help":    "Provider: Google only. Default: gemini-3.6-flash",
        "lang_fr_label":        "Français",
        "lang_en_label":        "English",

        "params_section":       "Session settings",
        "mode_label":           "Mode",
        "mode_balanced":        "Balanced (recommended)",
        "mode_eco":             "Economy",
        "mode_quality":         "Quality",
        "new_session_btn":      "🆕 New session",
        "new_session_help":     "Resets state (report + exports)",
        "launch_btn":           "🚀 Launch CoDIR IA session",
        "result_available":     "Result available (persisted in session).",
        "some_roles_failed":    "⚠️ One or more AIs encountered an error; see « Technical details ».",
        "diag_summary":         "Technical details — summary per AI (for support)",
        "diag_details":         "Technical details — attempts and AI fallbacks (for support)",
        "export_diag":          "⬇️ Export Diagnostics (CSV)",
        "no_key_runtime":       "No API key detected. Go to **Settings** to save your keys (secrets.json).",
        "no_key_first_run":     "No API key detected: open **Settings** in the sidebar to enter them.",
        "attachments_full":     "Attachments (pre-Christopher) — PDF/DOCX/PPTX/XLSX/CSV/TXT/MD",
        "attach_over_limit":    "file(s) exceed the limit and will be ignored.",
        "attach_over_size":     "Total size exceeds the configured limit; only the first files within quota will be processed.",
        "context_extract":      "Extracted text (preview)",
        "free_mode_header":     "Free Mode — test and compare AI models",
        "free_system_prompt":   "Context / System prompt (optional)",
        "free_message":         "Message",
        "providers_section":    "Main providers",
        "new_providers":        "New providers",
        "result_strategy":      "### Strategy",
        "result_brief_codir":   "### Board Brief (redistributed)",
        "result_marketing":     "### Marketing & Communications",
        "result_finance":       "### Finance & Tax",
        "result_sc":            "### Supply Chain & Operational Performance",
        "result_commercial":    "### Sales & Commercial",
        "result_synthesis":     "### Decision Summary",
        "result_dg":            "### Executive Management — T0→T+90d Roadmap",
        "brief_placeholder":    "Business context, internal/external news, objectives, risks/opportunities, items for decision.",
        "providers_caption":    "AI engines used in this session",
    },
}

DOCX_LABELS = {
    "fr": {
        "title":            "CoDIR IA — Compte-rendu de session",
        "version":          "Version",
        "date":             "Date",
        "attachments":      "PJ",
        "no_attachment":    "Sans pièce jointe",
        "initial_brief":    "Brief initial",
        "exec_summary":     "SYNTHÈSE EXÉCUTIVE — POUR LE DIRECTEUR GÉNÉRAL",
        "details_below":    "Détail par direction — ci-dessous",
        "commercial_key":   "Préconisations commerciales clés",
        "strategy":         "Stratégie",
        "brief_codir":      "Brief CoDIR (redistribué)",
        "marketing":        "Marketing & Communication",
        "finance":          "Finance & Fiscalité — Analyse et challenges",
        "sc":               "Supply Chain & Performance Opérationnelle",
        "sc_note":          "ℹ️ Note : analyse Supply Chain non disponible pour ce run.",
        "commercial":       "Direction Commerciale",
        "synthesis":        "Synthèse des décisions",
        "dg":               "Direction Générale — Feuille de route T0→T+90j",
        "no_commercial":    "Pas de préconisation commerciale prioritaire à ce stade.",
        "integrity_title":  "⚠️  Note d'intégrité des données :",
        "integrity_body":   (
            "Ce document utilise les balises suivantes :\n"
            "[FAIT] = donnée extraite d'un document fourni et confirmée à la page (libellé, valeur, "
            "période, périmètre) ; un chiffre venu du brief est une déclaration de l'utilisateur "
            "et porte [À VÉRIFIER]\n"
            "[REF SECT.] = ordre de grandeur sectoriel issu d'un benchmark publié\n"
            "[ESTIM. IA] = inférence du modèle sans source vérifiable — à confirmer avant toute décision\n"
            "Les chiffres [ESTIM. IA] ne constituent PAS des données comptables, financières ou opérationnelles certifiées."
        ),
    },
    "en": {
        "title":            "CoDIR IA — Session Report",
        "version":          "Version",
        "date":             "Date",
        "attachments":      "Attachments",
        "no_attachment":    "No attachment",
        "initial_brief":    "Initial Brief",
        "exec_summary":     "EXECUTIVE SUMMARY — FOR THE CEO",
        "details_below":    "Detailed review by function — below",
        "commercial_key":   "Key Commercial Recommendations",
        "strategy":         "Strategy",
        "brief_codir":      "Board Brief (redistributed)",
        "marketing":        "Marketing & Communications",
        "finance":          "Finance & Tax — Analysis and Challenges",
        "sc":               "Supply Chain & Operational Performance",
        "sc_note":          "ℹ️ Note: Supply Chain analysis unavailable for this run.",
        "commercial":       "Sales & Commercial",
        "synthesis":        "Decision Summary",
        "dg":               "Executive Management — T0→T+90d Roadmap",
        "no_commercial":    "No priority commercial recommendation identified at this stage.",
        "integrity_title":  "⚠️  Data integrity note:",
        "integrity_body":   (
            "This document uses the following tags:\n"
            "[FACT] = data extracted from a provided document and confirmed on the page (label, value, "
            "period, scope); a figure coming from the brief is a user declaration and carries [TO VERIFY]\n"
            "[SECT. REF.] = industry order of magnitude from a published benchmark\n"
            "[AI EST.] = model inference without verifiable source — to be confirmed before any decision\n"
            "[AI EST.] figures are NOT certified accounting, financial, or operational data."
        ),
    },
}

REPORT_LABELS = {
    "fr": {
        "source_header":  "COMPTE RENDU CoDIR IA — SOURCE POUR SYNTHÈSE PPT",
        "initial_brief":  "BRIEF INITIAL",
        "strategy":       "STRATÉGIE",
        "brief_codir":    "BRIEF CODIR",
        "marketing":      "MARKETING & COMMUNICATION",
        "finance":        "FINANCE & FISCALITÉ",
        "sc":             "SUPPLY CHAIN & PERFORMANCE OPÉRATIONNELLE",
        "commercial":     "DIRECTION COMMERCIALE",
        "synthesis":      "SYNTHÈSE DES DÉCISIONS",
        "dg":             "DIRECTION GÉNÉRALE — SYNTHÈSE CEO",
        "sc_unavailable": "Rôle Supply Chain activé pour ce brief. Analyse non disponible pour ce run (provider indisponible ou JSON invalide). Statut : INDISPONIBLE — à compléter en séance.",
    },
    "en": {
        "source_header":  "BOARD REPORT SOURCE FOR PPT SYNTHESIS",
        "initial_brief":  "INITIAL BRIEF",
        "strategy":       "STRATEGY",
        "brief_codir":    "BOARD BRIEF",
        "marketing":      "MARKETING & COMMUNICATIONS",
        "finance":        "FINANCE & TAX",
        "sc":             "SUPPLY CHAIN & OPERATIONAL PERFORMANCE",
        "commercial":     "SALES & COMMERCIAL",
        "synthesis":      "DECISION SUMMARY",
        "dg":             "EXECUTIVE MANAGEMENT — CEO SUMMARY",
        "sc_unavailable": "Supply Chain role activated for this brief. Analysis unavailable for this run (provider unavailable or invalid JSON). Status: UNAVAILABLE — to be completed during the meeting.",
    },
}

def T(key: str, lang: str = "fr") -> str:
    """Return a UI label in the configured language."""
    return UI_LABELS.get(lang, UI_LABELS["fr"]).get(key, key)

def DL(key: str, lang: str = "fr") -> str:
    """Return a DOCX label in the configured language."""
    return DOCX_LABELS.get(lang, DOCX_LABELS["fr"]).get(key, key)

def RL(key: str, lang: str = "fr") -> str:
    """Return a report-text label in the configured language."""
    return REPORT_LABELS.get(lang, REPORT_LABELS["fr"]).get(key, key)



load_dotenv(override=True)  # allow local .env (never committed)
apply_secrets_to_env(load_secrets(), override=False)


_SECRET_WIDGET_KEYS = {
    "openai": "cfg_openai_api_key",
    "anthropic": "cfg_anthropic_api_key",
    "google": "cfg_google_api_key",
    "mistral": "cfg_mistral_api_key",
    "perplexity": "cfg_perplexity_api_key",
    "grok": "cfg_grok_api_key",
    "pappers": "cfg_pappers_api_key",
    # Since v16.5.68 — Sources de données / API externes additionnelles
    "opensanctions": "cfg_opensanctions_api_key",
    "companies_house": "cfg_companies_house_api_key",
    "companies_house_document": "cfg_companies_house_document_api_key",
    "sec_edgar_ua": "cfg_sec_edgar_user_agent",
}

def _seed_secret_widget_state(secrets, force: bool = False):
    mapping = {
        _SECRET_WIDGET_KEYS["openai"]: secrets.openai_api_key,
        _SECRET_WIDGET_KEYS["anthropic"]: secrets.anthropic_api_key,
        _SECRET_WIDGET_KEYS["google"]: secrets.google_api_key,
        _SECRET_WIDGET_KEYS["mistral"]: secrets.mistral_api_key,
        _SECRET_WIDGET_KEYS["perplexity"]: secrets.perplexity_api_key,
        _SECRET_WIDGET_KEYS["grok"]: secrets.grok_api_key,
        _SECRET_WIDGET_KEYS["pappers"]: secrets.pappers_api_key,
        # Since v16.5.68 — sources externes additionnelles
        _SECRET_WIDGET_KEYS["opensanctions"]: secrets.opensanctions_api_key,
        _SECRET_WIDGET_KEYS["companies_house"]: secrets.companies_house_api_key,
        _SECRET_WIDGET_KEYS["companies_house_document"]: secrets.companies_house_document_api_key,
        _SECRET_WIDGET_KEYS["sec_edgar_ua"]: secrets.sec_edgar_user_agent,
    }
    for k, v in mapping.items():
        if force or k not in st.session_state:
            st.session_state[k] = v

cfg_dir = ensure_config_dir()
log_dir = cfg_dir / "logs"
logger = get_logger(log_dir)
# v62.12.8 — le logger de crash de production est garanti dès le démarrage,
# même si un StreamHandler/NullHandler existe déjà sur ``codir_ia``.
from utils.logger import get_crash_logger, get_crash_log_path
crash_logger = get_crash_logger(log_dir)
crash_log_path = get_crash_log_path(log_dir)

settings = load_settings()   # v16.5.38 — doit être chargé avant tout appel à settings.*
# B.1.3.8 — le choix de langue fait DANS LE FORMULAIRE (radio Langue) pilote
# aussi l'interface : override de session appliqué à chaque rerun, sans
# écraser la préférence disque.
try:
    _ui_ovr_b138 = st.session_state.get("_ui_lang_override_b138")
    if _ui_ovr_b138 in ("fr", "en"):
        settings.output_language = _ui_ovr_b138
except Exception:
    pass
_lang = getattr(settings, "output_language", "fr")  # v16.5.38 — shortcut global

st.set_page_config(page_title=TITLE, layout="wide")
# 9.4.61 — écran d'accueil : choix de la langue de l'interface au lancement (jamais pendant les contrats automatisés)
if not os.getenv("PYTEST_CURRENT_TEST") or os.getenv("CODIR_FORCE_WELCOME61"):
    try:
        from utils.welcome61 import render_welcome61 as _rw61
        if _rw61(st, settings, save_settings):
            st.stop()
    except Exception as _we61:
        if type(_we61).__name__ in ("StopException", "RerunException", "RerunData"):
            raise
_lang = getattr(settings, "output_language", "fr")
st.markdown(f"#### {TITLE}", unsafe_allow_html=False)

# ── F.6.7.1 — Safe shutdown : détecte un process CoDIR-IA orphelin de CE dossier
# (verrou « dossier en cours d'utilisation » sous Windows) et propose de l'arrêter.
# On enregistre le PID courant UNE fois par session, après avoir lu l'ancien.
try:
    from utils.process_manager import (detect_orphan as _po_detect,
                                        write_runtime_pid as _po_write,
                                        terminate_pid as _po_term)
    if "_codir_pid_init" not in st.session_state:
        _orphan = _po_detect(BASE_DIR)
        st.session_state["_codir_orphan_pid"] = _orphan
        # F.6.7.1 (audit) — ne PAS écraser le PID d'un orphelin détecté : on
        # n'ancre le process courant que s'il n'y a pas d'ancien process vivant.
        if not _orphan:
            _po_write(BASE_DIR)
        st.session_state["_codir_pid_init"] = True
    _orphan_pid = st.session_state.get("_codir_orphan_pid")
    if _orphan_pid:
        _oc1, _oc2 = st.columns([4, 1])
        with _oc1:
            st.warning(
                (f"⚠️ Un ancien processus CoDIR-IA semble encore actif (PID {_orphan_pid}) "
                 f"pour ce dossier — il peut le verrouiller sous Windows."
                 if _lang == "fr" else
                 f"⚠️ A previous CoDIR-IA process still seems active (PID {_orphan_pid}) "
                 f"for this folder — it may lock it on Windows."))
        with _oc2:
            if st.button("Arrêter l'ancien" if _lang == "fr" else "Stop previous",
                         key="_codir_kill_orphan"):
                # F.6.7.1 (audit) — on ne ré-ancre / n'efface l'orphelin QUE si
                # l'arrêt a réussi (terminate_pid vérifie aussi l'identité du PID).
                if _po_term(_orphan_pid, BASE_DIR):
                    _po_write(BASE_DIR)
                    st.session_state["_codir_orphan_pid"] = None
                else:
                    st.error("Impossible d'arrêter l'ancien processus (déjà terminé, "
                             "ou PID non lié à CoDIR-IA)." if _lang == "fr" else
                             "Could not stop the previous process (already gone, or "
                             "PID not linked to CoDIR-IA).")
                st.rerun()
except Exception:
    pass

# ── v16.5.64 — Self-check au démarrage Streamlit ──────────────────────────────
# Vérifie que les patches v4+v5 (briefcheck + confidence_score) sont actifs et
# affiche le statut visible en tête de l'app. Si un module échoue à l'import
# ou qu'un flag est désactivé, on le signale immédiatement à l'utilisateur.
try:
    from utils.confidence_render import quick_health_check as _qhc
    _health = _qhc()
    if _health["all_ok"]:
        if _health["warnings"]:
            st.warning(
                "CoDIR-IA actif — certaines features désactivées : "
                + " ; ".join(_health["warnings"])
            )
        # Si tout OK sans warning, pas de message (évite la pollution UI). 9.4.65 : l'ancien encart
        # « Statut patches v4+v5 », libellé de développeur, n'est plus affiché à l'accueil.
    else:
        st.error(
            "⚠ Installation incomplète — certains contrôles de CoDIR IA ne s'exécuteront pas. "
            "Relancez CoDIR IA par DEMARRER_CODIR_IA.bat (Windows) ou Demarrer_Mac.command (Mac) ; "
            "si le message persiste, consultez la page Aide."
        )
        with st.expander("Détails erreurs", expanded=True):
            for err in _health.get("errors", []):
                st.code(err)
except Exception as _hc_err:
    # Si même le health check plante, on le signale clairement plutôt que de masquer
    st.warning(
        f"Contrôle de l'installation indisponible : {type(_hc_err).__name__}: {_hc_err} "
        "— relancez CoDIR IA par son lanceur."
    )
# ──────────────────────────────────────────────────────────────────────────────

# Quick access to Configuration (useful if sidebar is collapsed)
c_title = st.columns([1, 0.26])
with c_title[1]:
    # 9.4.64 — « Configuration » se coupait entre le o et le n selon la largeur de la fenêtre : colonne élargie, libellé
    # jamais coupé, bouton à la largeur de la colonne
    st.markdown("<style>.st-key-config_btn64 button, .st-key-config_btn64 button p {white-space:nowrap !important;"
                "word-break:keep-all !important;}</style>", unsafe_allow_html=True)
    if st.button(T("config_btn", _lang), help=T("config_btn_help", _lang), key="config_btn64", use_container_width=True):
        st.session_state["nav_page"] = "config"
        st.rerun()

# Detect first launch without API keys
_initial_secrets = load_secrets()
needs_config = not has_any_key(_initial_secrets)   # aucune clé (ni LLM, ni Pappers)
needs_llm    = not has_llm_key(_initial_secrets)   # aucune clé LLM (sessions CoDIR impossibles)
if needs_config and "nav_page" not in st.session_state:
    # Force navigation to Configuration on first launch
    st.session_state["nav_page"] = "config"

# Optional modal-like configuration dialog on first launch (Streamlit >= 1.30)
if needs_config and not st.session_state.get("config_dialog_shown", False):
    st.session_state["config_dialog_shown"] = True
    if hasattr(st, "dialog"):
        @st.dialog(T("dialog_first_launch", _lang))
        def _config_dialog():
            st.info(T("no_api_key", _lang)) # n'est configurée. Renseigne au moins **une** clé pour démarrer.")
            secrets = load_secrets()
            _seed_secret_widget_state(secrets)
            with st.form("config_dialog_form"):
                openai_api_key     = st.text_input("OPENAI_API_KEY", type="password", key="dlg_openai_api_key")
                anthropic_api_key  = st.text_input(T("anthropic_key_label",_lang), type="password", key="dlg_anthropic_api_key")
                google_api_key     = st.text_input("GOOGLE_API_KEY (Finance — Gemini)", type="password", key="dlg_google_api_key")
                mistral_api_key    = st.text_input("MISTRAL_API_KEY", type="password", key="dlg_mistral_api_key")
                perplexity_api_key = st.text_input(T("perplexity_key_label",_lang), type="password", key="dlg_perplexity_api_key")
                grok_api_key       = st.text_input(T("grok_key_label", _lang), type="password", key="dlg_grok_api_key")
                pappers_api_key    = st.text_input(T("pappers_key_label", _lang), type="password", key="dlg_pappers_api_key",
                                                   help=T("pappers_key_help", _lang))
                saved = st.form_submit_button(T("save_keys", _lang))
            if saved:
                new_s = Secrets(
                    openai_api_key=openai_api_key,
                    anthropic_api_key=anthropic_api_key,
                    google_api_key=google_api_key,
                    mistral_api_key=mistral_api_key,
                    perplexity_api_key=perplexity_api_key,
                    grok_api_key=grok_api_key,
                    pappers_api_key=pappers_api_key,
                )
                try:
                    save_secrets(new_s)
                    apply_secrets_to_env(load_secrets(), override=True)
                    st.session_state["config_dialog_shown"] = True
                    if has_llm_key(new_s):
                        # Premier lancement : on reste cohérent avec l'existant
                        # si une clé LLM est présente, on peut retourner au brief.
                        st.session_state["nav_page"] = "codir"
                        st.rerun()
                    else:
                        st.session_state["nav_page"] = "config"
                        st.rerun()
                except Exception as _e:
                    st.error(f"Erreur lors de la sauvegarde : {_e}")
        _config_dialog()
    else:
        st.warning(T("no_key_first_run", _lang))

# -------------------------
# Session state
# -------------------------
if "last_result" not in st.session_state:
    st.session_state["last_result"] = None
def _logo_b64_54() -> str:
    """9.4.54 — logo de l'application pour l'écran traitement (mis en cache dans la session)."""
    _k = "_logo_b64_54"
    if _k not in st.session_state:
        try:
            import base64 as _b64m
            _lp = Path(__file__).resolve().parent / "assets" / "CoDIR_IA.png"
            st.session_state[_k] = _b64m.b64encode(_lp.read_bytes()).decode("ascii") if _lp.exists() else ""
        except Exception:
            st.session_state[_k] = ""
    return st.session_state[_k]


if "last_docx" not in st.session_state:
    st.session_state["last_docx"] = None
if "last_synthese_docx" not in st.session_state:
    st.session_state["last_synthese_docx"] = None
if "last_pptx" not in st.session_state:
    st.session_state["last_pptx"] = None
    st.session_state["last_docx_error"] = None   # v62.13.9.4.31.1
if "last_pptx_debug" not in st.session_state:
    st.session_state["last_pptx_debug"] = None
if "last_pptx_layout_report" not in st.session_state:
    st.session_state["last_pptx_layout_report"] = None
if "last_meta" not in st.session_state:
    st.session_state["last_meta"] = {}

# v16.5.39 — Brief UI state (dual-mode)
if "bui_mode" not in st.session_state:
    brief_ui._init_state()

# settings already loaded above (before st.set_page_config)

# -------------------------
# Sidebar navigation
# -------------------------
# 9.4.57 — écran de fin dépouillé (demande du dirigeant du 09/10/2026) : quand un dossier vient d'être livré, la page
# entière est remplacée par l'écran de fin ; « Nouvelle séance » ramène au formulaire, brief et réglages conservés.
if st.session_state.get("end57_active") and st.session_state.get("last_result"):
    try:
        from utils.run_screen54 import render_end_page57 as _rep57
        _d57 = datetime.now().strftime('%Y-%m-%d')
        _rep57(st, _lang, st.session_state.get("last_result"), st.session_state.get("paquet54"),
               (st.session_state.get("last_docx"), f"CODIR_IA_CR_{_d57}.docx"),
               (st.session_state.get("last_synthese_docx"), f"CODIR_IA_SYNTHESE_{_d57}.docx"),
               (st.session_state.get("last_pptx"), f"CoDIR_IA_Synthese_{_d57}.pptx"),
               logo_b64=_logo_b64_54())
        st.stop()
    except Exception as _e57:
        if type(_e57).__name__ in ("StopException", "RerunException"):
            raise
        st.session_state["end57_active"] = False      # repli : l'interface habituelle, jamais une page vide

with st.sidebar:
    st.header(T("nav_header", _lang))
    _PAGE_IDS   = ["codir", "free", "config", "help"]
    _PAGE_LABELS = [T("nav_codir",_lang), T("nav_free",_lang), T("nav_config",_lang), T("nav_help",_lang)]
    # v16.5.59 — nav_page est la SEULE source de vérité.
    # Le radio n'a PAS de key= : il ne touche jamais session_state directement.
    # index= recalculé à chaque rerun depuis nav_page → affichage toujours cohérent.
    _cur_id = st.session_state.get("nav_page", "codir")
    if _cur_id not in _PAGE_IDS:
        _cur_id = "codir"
    _cur_idx = _PAGE_IDS.index(_cur_id)
    _selected_label = st.radio(T("nav_goto", _lang), _PAGE_LABELS, index=_cur_idx)
    page = _PAGE_IDS[_PAGE_LABELS.index(_selected_label)]
    st.session_state["nav_page"] = page

    # ── F.6.7.1 — Arrêt PROPRE du serveur (évite le process Python orphelin qui
    # verrouille le dossier). N'arrête QUE ce process CoDIR-IA, jamais tous les python.
    st.markdown("---")
    if st.session_state.get("_codir_confirm_stop"):
        st.warning("Arrêter le serveur CoDIR-IA ?" if _lang == "fr"
                   else "Stop the CoDIR-IA server?")
        _sc1, _sc2 = st.columns(2)
        with _sc1:
            if st.button("Oui, arrêter" if _lang == "fr" else "Yes, stop",
                         key="_codir_stop_yes", type="primary"):
                try:
                    from utils.process_manager import request_self_shutdown as _po_shutdown
                    _po_shutdown(BASE_DIR)
                except Exception:
                    pass
                st.info("Serveur arrêté — vous pouvez fermer l'onglet." if _lang == "fr"
                        else "Server stopped — you can close the tab.")
                st.stop()
        with _sc2:
            if st.button("Annuler" if _lang == "fr" else "Cancel", key="_codir_stop_no"):
                st.session_state["_codir_confirm_stop"] = False
                st.rerun()
    else:
        if st.button("🛑 Arrêter CoDIR-IA proprement" if _lang == "fr"
                     else "🛑 Stop CoDIR-IA cleanly", key="_codir_stop_btn"):
            st.session_state["_codir_confirm_stop"] = True
            st.rerun()

    st.markdown("---")
    st.header(T("params_section", _lang))
    mode_label = st.selectbox(
        "Mode",
        [T("mode_balanced",_lang), T("mode_eco",_lang), T("mode_quality",_lang)],
        index=0 if settings.mode_default == "equilibre" else (1 if settings.mode_default == "eco" else 2),
    )
    # Apply mode presets (light-touch)
    if mode_label == T("mode_eco",_lang):
        temperature_default = 0.3
        max_tokens_default = 1200
    elif mode_label == T("mode_quality",_lang):
        temperature_default = 0.5
        max_tokens_default = 2500
    else:
        temperature_default = settings.temperature
        max_tokens_default = settings.max_output_tokens

    # 9.4.65 — réglages techniques repliés (valeurs et effet inchangés)
    with st.expander(T("advanced_settings", _lang), expanded=False):
        temperature = st.slider(T("temperature_label",_lang), 0.0, 1.0, float(temperature_default))
        max_tokens = st.number_input(T("max_tokens_label", _lang), min_value=256, max_value=8000, value=int(max_tokens_default))
        st.caption(T("models_caption", _lang))

# -------------------------
# Helpers
# -------------------------
def _has_meaningful_text(text: str) -> bool:
    if not isinstance(text, str):
        return False
    t = text.strip()
    if not t:
        return False
    low = t.lower()
    return low not in {
        "n/a", "na", "aucun", "aucune", "ras", "none",
        "pas de préconisation commerciale prioritaire à ce stade",
        "pas de recommandation commerciale prioritaire à ce stade",
    }


def _extract_key_lines(text: str, max_items: int = 6) -> list[str]:
    if not isinstance(text, str) or not text.strip():
        return []
    out, seen = [], set()
    for raw in text.splitlines():
        line = re.sub(r"^[\s\-–•*✓]+", "", raw or "").strip()
        line = re.sub(r"^\d+[\.\)]\s*", "", line)
        if not line:
            continue
        low = line.lower()
        if any(tag in low for tag in ["diagnostic commercial", "opportunités commerciales", "préconisations commerciales", "plan d'action", "challenges marketing", "challenges finance", "arbitrages", "go / no-go"]):
            continue
        if len(line) < 12:
            continue
        key = low[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(line[:220])
        if len(out) >= max_items:
            break
    return out


def _strip_sc_json_blocks(text: str) -> str:
    """
    Supprime les blocs JSON et audit de la sortie SC pour le DOCX.
    Retire ---JSON_START--- ... ---JSON_END--- et ---AUDIT_START--- ... ---AUDIT_END---
    ainsi que les lignes vides consécutives laissées en place.
    """
    # Supprimer bloc JSON
    text = re.sub(
        r"---JSON_START---[\s\S]*?---JSON_END---",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Supprimer bloc audit
    text = re.sub(
        r"---AUDIT_START---[\s\S]*?---AUDIT_END---",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Nettoyer les lignes vides multiples
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()




def _get_sc_display_text(sc_output: str | None, sc_status: str | None = None) -> str:
    """Nettoie la sortie Supply Chain pour l'UI et le DOCX."""
    status = (sc_status or "").strip().lower()
    unavailable_msg = ("Supply Chain analysis unavailable for this run — partially covered in synthesis" if _lang=="en" else "Analyse Supply Chain indisponible sur ce run — points partiellement repris dans la synthèse")

    if status == "unavailable":
        return unavailable_msg

    if not isinstance(sc_output, str):
        return ""

    raw = sc_output.strip()
    if not raw:
        return unavailable_msg if status == "unavailable" else ""

    low = raw.lower()
    if low.startswith("{") and "'provider'" in raw and "'model'" in raw and "'output'" in raw:
        return unavailable_msg if status in {"narrative_fallback", "primary_fallback", "final", "unavailable"} else ""

    cleaned = _strip_sc_json_blocks(raw)
    cleaned = re.sub(r"^###\s*zone 1\s*[—-]?\s*note narrative\s*$", "", cleaned, flags=re.IGNORECASE | re.MULTILINE).strip()

    if not cleaned:
        return unavailable_msg if status in {"narrative_fallback", "primary_fallback", "final", "unavailable"} else ""

    return cleaned

def _strip_brief_ascii_banner(brief_text: str) -> str:
    """
    Since v16.5.67.9 — Strip ASCII banner ╔═╗║...║╚═╝ du brief avant rendu DOCX.

    La bannière est construite par brief_ui.py (mode Terrain/Équipe) et sert
    de repère visuel dans l'UI Streamlit. Mais elle pollue le livrable Word :
    ligne de ═ et caractères box-drawing ne rendent pas bien en Calibri/Arial.

    Supprime toute ligne du brief qui :
    - commence par ╔ ou ╚ ou ╠ (coin/séparateur de box)
    - commence par ║ (bord vertical de box)
    - contient uniquement des ═ ou des espaces

    Le reste du brief (▌ FIL ROUGE, ▌ CONTEXTE, etc.) est conservé tel quel.
    """
    if not brief_text:
        return ""
    kept_lines = []
    for line in brief_text.splitlines():
        stripped = line.strip()
        # Ligne box-drawing : coins, bords, séparateurs
        if stripped and stripped[0] in "╔╚╠╣╦╩":
            continue
        if stripped.startswith("║"):
            continue
        # Ligne composée uniquement de caractères ═ ─ ━ ou espaces
        if stripped and all(c in "═─━ \t" for c in stripped):
            continue
        kept_lines.append(line)
    # Collapser les lignes vides consécutives en une seule
    result = []
    prev_empty = False
    for line in kept_lines:
        is_empty = not line.strip()
        if is_empty and prev_empty:
            continue
        result.append(line)
        prev_empty = is_empty
    return "\n".join(result).strip()


def _finance_safe(_t, result=None, lang: str = "fr"):
    """Sécurité factuelle Finance fondée sur la preuve structurée du run."""
    try:
        from utils.finance_factual_safety import (
            has_primary_financial_evidence, sanitize_finance_output,
        )
        _r = result if isinstance(result, dict) else {}
        _has_primary = has_primary_financial_evidence(
            _r.get("financial_facts_table"),
            _r.get("financial_facts_table_status"))
        _cp = _r.get("company_profile") or {}
        _legal_form = (_cp.get("legal_form") if isinstance(_cp, dict) else "") or ""
        return sanitize_finance_output(
            _t, has_primary_financials=_has_primary, lang=lang,
            entity_form=_legal_form)[0]
    except Exception:
        return _t


_SECTION_INDEX_KEY = "_codir_section_index_62431"


def _docx_number_section(doc, heading: str, level: int) -> str:
    """v62.13.9.4.31 — demande de Robin (09/09) : les rubriques de niveau 1 des deux
    Word sont numérotées « §1, §2… » et collectées pour le sommaire et pour les
    renvois du deck. Un numéro de rubrique est exact à la génération, contrairement
    à un numéro de page qu'aucun moteur de rendu ne peut calculer ici."""
    if level != 1:
        return heading
    idx = getattr(doc, _SECTION_INDEX_KEY, None)
    if idx is None:
        idx = []
        setattr(doc, _SECTION_INDEX_KEY, idx)
    clean = re.sub(r"^\s*§\s*\d+\s*[—–-]\s*", "", str(heading or "")).strip()
    # v62.13.9.4.31 — un titre de rubrique n'est jamais un message de contrôle ni
    # un statut : le sommaire doit rester lisible pour un dirigeant.
    clean = re.sub(r"\s*⟨[^⟩]*⟩\s*", " ", clean).replace("\u2063", "").strip(" —–-:")
    try:
        from utils.analysis_objects import _is_product_marker as _ipm
        if _ipm(clean) or not re.search(r"[A-Za-zÀ-ÿ]{3}", clean):
            clean = ""
    except Exception:
        pass
    if not clean:
        clean = "Rubrique" if not str(getattr(doc, "_codir_lang_62431", "fr")).startswith("en") else "Section"
    idx.append(clean)
    return f"§{len(idx)} — {clean}"


def _docx_add_summary(doc, lang: str = "fr", *, title: str | None = None):
    """Sommaire en tête du document : les rubriques numérotées, puis un champ de
    pagination Word (PAGEREF) que Word résout à l'ouverture ou à l'impression —
    le numéro de page vient de Word, jamais d'une estimation de notre part."""
    en = str(lang or "fr").lower().startswith("en")
    head = title or ("Sommaire" if not en else "Contents")
    p0 = doc.add_paragraph()
    # v62.13.9.4.31 — le sommaire est écrit par le produit : il porte la marque
    # d'outil, pour qu'aucun contrôle ne le lise comme du contenu d'agent (un
    # renvoi vers l'annexe des scénarios n'ouvre pas l'annexe).
    from utils.quantity_ledger import TOOL_MARK as _TM31
    r0 = p0.add_run(_TM31 + head); r0.bold = True
    return {"paragraph_after": p0, "lang": lang, "doc": doc, "mark": _TM31}


def _docx_fill_summary(anchor: dict) -> None:      # noqa: C901
    """Écrit les rubriques collectées juste après le titre du sommaire, dans
    l'ordre du document, avec un point de conduite jusqu'au numéro de rubrique."""
    # v62.13.9.4.31 — le sommaire ne dépend d'aucun état partagé : si l'index n'a
    # pas pu être attaché au document (import optionnel, style absent), il est
    # reconstruit depuis les titres de niveau 1 réellement écrits. Un document
    # livré sans sommaire alors qu'il a des rubriques serait un défaut silencieux.
    if not anchor:
        return
    doc = anchor["doc"]
    idx = list(getattr(doc, _SECTION_INDEX_KEY, []) or [])
    if not idx:
        try:
            for para in doc.paragraphs:
                if str(getattr(para.style, "name", "") or "").lower().startswith(("heading 1", "titre 1")):
                    _t = re.sub(r"^\s*\u2063?\s*§\s*\d{1,3}\s*[—–-]\s*", "", (para.text or "")).strip()
                    if _t:
                        idx.append(_t)
        except Exception:
            idx = []
    if not idx:
        return
    from copy import deepcopy
    ref = anchor["paragraph_after"]
    prev = ref
    for i, name in enumerate(idx, start=1):
        para = deepcopy(ref._p)
        prev._p.addnext(para)
        from docx.text.paragraph import Paragraph
        np = Paragraph(para, ref._parent)
        for r in list(np.runs):
            r._r.getparent().remove(r._r)
        run = np.add_run(f"{anchor.get('mark', '')}§{i} — {name}")
        run.bold = False
        prev = np


def _docx_add_section(doc, heading: str, text: str, level: int = 1) -> None:
    """Ajoute un heading + paragraphes formatés dans le DOCX.
    Chaque ligne de texte devient un paragraphe distinct.
    Les lignes commençant par - • * ou un chiffre. sont rendues en List Bullet.

    La gouvernance temporelle est appliquée UNE FOIS en amont dans
    :func:`export_docx`, sur la map ``outputs`` gouvernée par la date du run.
    Ce helper de présentation ne doit jamais relire l'horloge système : sinon
    un document régénéré après la session peut transformer une action future au
    moment du run en action artificiellement « en retard ».
    """
    doc.add_heading(_docx_number_section(doc, heading, level), level=level)   # v62.13.9.4.31 — titre jamais neutralisé
    text = str(text or "").replace("\u2063", "")      # v62.13.9.4.21 — jamais de marqueur d'outil dans le texte d'agent
    if not text or not text.strip():
        doc.add_paragraph("(non disponible)")
        return
    # Chantier H1 (10/08/2026) — rendu markdown réel (titres relatifs, gras,
    # tables pipe → tables Word). FAIL-OPEN : le repli historique ci-dessous
    # reste le chemin de secours intégral.
    try:
        from utils.md_to_docx import add_markdown as _h1_md
        _h1_md(doc, text, base_level=level + 1)
        return
    except Exception:
        pass
    _BULLET_RE = re.compile(r"^[\-–•\*✓]\s+|^\d+[\.\)]\s+")
    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            continue
        if _BULLET_RE.match(line):
            clean = _BULLET_RE.sub("", line).strip()
            try:
                doc.add_paragraph(clean, style="List Bullet")
            except Exception:
                doc.add_paragraph(f"• {clean}")
        else:
            doc.add_paragraph(line)




def _rel_wording14(chosen: str, clicked: str, lang: str) -> str:
    """B.1.3.16 (dossier industriel (composants) run 1) — différencie l'AFFINEMENT d'identité
    (tokens du clic ⊂ tokens du choisi : <GROUPE> → <GROUPE> HYDRAULICS) de la
    vraie entité LIÉE divergente (dossier anglophone coté LIMITED vs dossier anglophone coté GROUP PLC).
    Les comptes sociaux d'une identité affinée ne sont pas « une autre
    entité » : ils sont non probants pour le périmètre groupe consolidé."""
    _ct = {t for t in str(clicked or "").upper().split() if len(t) > 1}
    _ch = {t for t in str(chosen or "").upper().split() if len(t) > 1}
    _refined = bool(_ct) and _ct.issubset(_ch)
    if lang == "en":
        return ("refined identity — standalone accounts not evidentiary "
                "for the consolidated group perimeter" if _refined
                else "related, not evidentiary")
    return ("identité affinée — comptes sociaux non probants pour le "
            "périmètre groupe consolidé" if _refined
            else "entité liée, non probante")


def _fp_root(result: dict) -> dict:
    """B.1.3.13 — lecture robuste du run_fingerprint : racine (export 3.13),
    sinon repli sur le sous-dict b1_proof_layer (défense en profondeur)."""
    _r = result.get("run_fingerprint")
    if isinstance(_r, dict) and _r:
        return _r
    _b1 = result.get("b1_proof_layer") or {}
    for k in ("run_fingerprint", "fingerprint"):
        _v = _b1.get(k)
        if isinstance(_v, dict) and _v:
            return _v
    return {}


def _loc_ctx_value(v: str, lang: str) -> str:
    """B.1.3.10 (audit #6) — les VALEURS du contexte B1 (groupe/consolide/
    social) restaient en français dans un CR anglais."""
    _k = str(v or "").strip().lower()
    if lang == "en":
        return {"groupe": "group", "consolide": "consolidated",
                "consolidé": "consolidated", "social": "standalone",
                "individuel": "standalone"}.get(_k, v)
    # B.1.3.16 (dossier industriel (composants) run 1 : « Périmètre cible : consolide ») — les
    # valeurs internes non accentuées sont localisées AUSSI en français.
    return {"consolide": "consolidé"}.get(_k, v)


class DocxSafetyBlock(RuntimeError):
    """Fail-closed DOCX guard with structured diagnostics already recorded."""



def _retrospective_line34(res, en: bool = False) -> str:
    """v62.13.9.4.34 (lot 1) — mention d'analyse rétrospective sur les livrables.

    Contre-audit du 14/09/2026 (run réel dossier réseau de soins 69ce0a) : le brief situait
    l'analyse début 2023, rien dans les documents ne le disait, et les
    échéances étaient datées 2026. Quand la date d'analyse diffère de la date
    du run, elle est écrite en tête du document et dans la trame : un lecteur
    doit savoir depuis quelle date le dossier a été lu. Chaîne vide sinon.
    """
    try:
        ad = str((res or {}).get("analysis_date") or "").strip()[:10]
        rd = str((res or {}).get("run_date") or "").strip()[:10]
        if not ad or not rd or ad == rd:
            return ""
        d, m, y = ad[8:10], ad[5:7], ad[0:4]
        return (f"Analyse rétrospective au {d}/{m}/{y} — les faits postérieurs à cette date sont écartés."
                if not en else
                f"Retrospective analysis as of {y}-{m}-{d} — facts later than this date are discarded.")
    except Exception:
        return ""


def export_synthese_docx(result: dict) -> bytes:
    """v62.13.9.4.21 — LE SYNTHÉTIQUE (décision Robin du 05/09/2026) : un
    second Word court, projection du document de travail — cadre de lecture,
    synthèse exécutive, décision, synthèse & décisions, direction générale,
    plan d'actions, prochaines étapes — même contrôle final que le document de
    travail. v62.13.9.4.49 : les chiffres non étayés ne sont plus neutralisés, ils
    sont signalés en place (doctrine du 28/09/2026)."""
    _raw = result
    try:
        _raw["_render_mode"] = "synthesis"
    except Exception:
        pass
    res = apply_v62136_maintenance(_raw)
    _dl = ((res.get("lang") or "").strip().lower() or getattr(load_settings(), "output_language", "fr"))
    _en = _dl == "en"
    outputs = res.get("outputs") or {}
    doc = Document()
    from utils.quantity_ledger import TOOL_MARK as _TM
    _sst = lambda _x: _x   # v62.13.9.4.49 — les étiquettes restent : le rendu les signale  # noqa: E731
    doc.add_heading(_TM + ("CoDIR IA — Synthèse de session" if not _en else "CoDIR IA — Session synthesis"), level=0)
    _cp = res.get("company_profile") or {}
    _name = str(_cp.get("name") or (res.get("inputs") or {}).get("company") or "").strip()
    if _name:
        doc.add_paragraph(_TM + (f"Entreprise : {_name}" if not _en else f"Company: {_name}"))
    doc.add_paragraph(_TM + (f"Date : {datetime.now().strftime('%d/%m/%Y')} — {VERSION_LABEL}"))
    _retro34 = _retrospective_line34(res, _en)                 # v62.13.9.4.34 (lot 1)
    if _retro34:
        doc.add_paragraph(_TM + _retro34)
    doc.add_paragraph(_TM + ("Projection du document de travail : chaque passage non étayé est conservé et signalé "
                             "en place (voir l'encadré) ; le détail est dans le compte rendu complet."
                             if not _en else
                             "Projection of the working document: every unsupported passage is kept and flagged in "
                             "place (see the box); details live in the full report."))
    _summary62431 = _docx_add_summary(doc, _dl)      # v62.13.9.4.31 — sommaire des rubriques
    try:
        from utils.confidence_render import docx_add_confidence_block
        _n0 = len(doc.paragraphs)
        docx_add_confidence_block(doc, briefcheck=res.get("briefcheck"),
                                  confidence_score=res.get("delivery_confidence_score"), lang=_dl)
        from utils.quantity_ledger import mark_tool_paragraphs as _mtp
        _mtp(doc, _n0)
        for _tbl in doc.tables:                       # v62.13.9.4.22 — cartes de score : texte de l'outil
            for _row in _tbl.rows:
                for _cell in _row.cells:
                    for _p in _cell.paragraphs:
                        if _p.text and _TM not in _p.text and _p.runs:
                            _p.runs[0].text = _TM + _p.runs[0].text
    except Exception:
        pass

    def _sec(title_fr, title_en, key_or_text, level=1, drop_tables=False):
        text = key_or_text if isinstance(key_or_text, str) and "\n" in key_or_text or (isinstance(key_or_text, str) and len(key_or_text) > 80) else str(outputs.get(key_or_text, "") or res.get(key_or_text, "") or "")
        text = _sst(text)
        # v62.13.9.4.26 — les tags d'agent (« [ESTIM-HYPOTHÈSE] », « [NON SOURCÉ] »)
        # restent dans le compte rendu de travail ; la synthèse est une projection
        # lisible par un dirigeant, elle n'en porte pas.
        text = re.sub(r"\s*\[(?:ESTIM(?:ATION)?|HYPOTH[ÈE]SE|FAIT|CIBLE|SC[ÉE]NARIO|SOURCE|CONTEXTE|NON\s+SOURC[ÉE]|D[ÉE]CLAR[ÉE]E?|A1)[^\]]{0,60}\]", "", text, flags=re.I)
        if drop_tables:
            # v62.13.9.4.24 — contre-audit v23 (§5) : dans la synthèse, les tableaux
            # narratifs (plan DG, options) ne sont plus recopiés puis neutralisés
            # avec pertes ; la sélection est celle des objets, explicite, et le
            # tableau complet reste dans le compte rendu de travail.
            # v62.13.9.4.25 — contre-audit v24 (§2) : une rangée dont la barre de
            # tête a disparu (« Formalisation… | Robin SAUZET | 2026-11-15 | … »)
            # est une rangée ; un titre dont le seul contenu était un tableau
            # (« DÉCISIONS PRIORITAIRES ») ne reste pas vide — il renvoie aux
            # décisions proposées ci-dessus, extraites du même tableau.
            _kept = [l for l in text.splitlines()
                     if not l.strip().startswith("|") and l.count(" | ") < 2
                     and not re.match(r"^\s*\|?\s*:?-{2,}", l.strip())]
            _lines = []
            _is_head = lambda l: bool(re.match(r"^\s*(?:#{1,6}\s+|\*\*[^*]{3,80}\*\*\s*$|[A-ZÀ-Ÿ][A-ZÀ-Ÿ '’/&\-]{6,60}\s*:?\s*$)", l.strip()))
            for _i, _l in enumerate(_kept):
                if _is_head(_l):
                    _nxt = next((x for x in _kept[_i + 1:] if x.strip()), "")
                    if not _nxt or _is_head(_nxt):
                        if re.search(r"d[ée]cisions?|actions?|plan|[ée]tapes?|feuille de route|roadmap|next steps", _l, re.I):
                            _lines.append(_l)
                            _lines.append("- " + _TM + ("Voir « Décisions proposées » et « Plan d'actions » ci-dessus (tableau complet dans le compte rendu de travail)."
                                                        if not _en else
                                                        "See “Proposed decisions” and “Action plan” above (full table in the working document)."))
                        continue
                _lines.append(_l)
            text = "\n".join(_lines)
        if text.strip():
            _docx_add_section(doc, (title_en if _en else title_fr), text, level=level)
    _exec = res.get("executive_synthesis")
    if isinstance(_exec, str) and _exec.strip():
        _sec("Synthèse exécutive", "Executive synthesis", _exec)
    _dec = res.get("decision_reconciled")
    if isinstance(_dec, dict) and str(_dec.get("note") or "").strip():
        _sec("Décision", "Decision", str(_dec.get("note")))
    # v62.13.9.4.23 — la synthèse est une PROJECTION DES OBJETS D'ANALYSE
    # extraits du document de travail (texte entier) : décisions avec porteur
    # et date, options, risques, arbitrages, plan d'actions, hypothèses à
    # discuter, questions ouvertes. Rien d'inventé, rien de perdu de ce qui
    # permet de décider ; les sections narratives d'origine suivent.
    try:
        from utils.analysis_objects import extract_objects as _eo
        from utils.objects_render import synthesis_sections as _ss
        _rw = copy.deepcopy(_raw); _rw["_render_mode"] = "work"
        _ob = _eo(apply_v62136_maintenance(_rw))
        _raw["analysis_objects"] = _ob
        for s in _ss(_ob, res, _dl):
            # v62.13.9.4.31 — le TITRE de rubrique n'est jamais neutralisé : il vient
            # des objets et sert de repère §N au lecteur et aux renvois du deck.
            _docx_add_section(doc, s["title"], "\n".join("- " + _sst(l) for l in s["lines"]), level=1)
    except Exception as _ob_exc:
        doc.add_paragraph(_TM + f"(objets d'analyse indisponibles : {type(_ob_exc).__name__})")
    _sec("Synthèse & décisions", "Synthesis & decisions", "synthese_decisions", drop_tables=True)
    _sec("Direction générale", "Executive management", "direction_generale", drop_tables=True)
    # v62.13.9.4.25 — contre-audit v24 (§2) : la conclusion de la synthèse est
    # rendue DEPUIS LES OBJETS (orientation, décisions à prendre, risque et
    # arbitrage n°1, prochaine échéance), jamais une réserve générique de marché.
    try:
        from utils.objects_render import conclusion_lines as _cln
        _ob_c = _raw.get("analysis_objects") if isinstance(_raw.get("analysis_objects"), dict) else None
        _cl_lines = _cln(_ob_c, _dl) if _ob_c else []
        if _cl_lines:
            _docx_add_section(doc, ("Conclusion" if not _en else "Conclusion"),
                              "\n".join("- " + _sst(l) for l in _cl_lines), level=1)
    except Exception:
        pass
    _docx_fill_summary(_summary62431)                 # v62.13.9.4.31
    try:                                              # carte rubrique → §N pour les renvois du deck
        res["synthesis_section_index"] = list(getattr(doc, _SECTION_INDEX_KEY, []) or [])
        if isinstance(_raw, dict):
            _raw["synthesis_section_index"] = res["synthesis_section_index"]
    except Exception:
        pass
    try:                                              # v62.13.9.4.23 — mise en page efficace
        from utils.docx_layout import compact_layout as _cl
        _cl(doc)
    except Exception:
        pass
    # v62.13.9.4.34 (lot 4) — AI Act art. 50(2) : la SYNTHÈSE est marquée comme le
    # compte rendu et la trame. Contre-audit de publication du 14/09/2026 : les six
    # synthèses des six dossiers ne portaient aucun marqueur — l'export isolé de la
    # 9.4.31.1 avait dupliqué le chemin sans reprendre le marquage. Posé juste avant
    # la sérialisation, absorbé en cas d'échec (ne peut pas faire échouer l'export).
    try:
        from utils.ai_content_marking import apply_marking as _mark50_syn
        from version import PUBLISHER as _PUB_syn
        _mark50_syn(doc, version=str(VERSION_LABEL or ""), provider=_PUB_syn)
    except Exception:
        pass
    payload_io = io.BytesIO()
    doc.save(payload_io)
    payload = payload_io.getvalue()
    out = apply_final_docx_control(payload, res, lang=_dl, raw_result=_raw)
    try:
        _raw["register_sidecar_synthesis"] = res.get("register_sidecar")   # v62.13.9.4.22 — pour le paquet complet
    except Exception:
        pass
    return out


def apply_final_docx_control(payload: bytes, result: dict,
                             lang: str | None = None,
                             raw_result: dict | None = None) -> bytes:
    """v62.13.9.4.10 — POINT DE MESURE UNIQUE de la sûreté DOCX.

    Réparation sémantique, pré-contrôle numérique (réservé au ton
    board-scrutiny), gate de surface, oracle de contenu et décision de
    blocage : toute la séquence que subit un livrable réel, dans une
    seule fonction.

    Extraite d'``export_docx`` au cycle 9.4.10 pour que les rejeux de
    campagne mesurent EXACTEMENT ce que la production applique. Le
    contre-audit du 31/08/2026 a montré le coût de l'écart : l'éditeur
    mesurait les résidus du gate, le contre-auditeur appelait l'oracle en
    isolation, et la production ne faisait ni l'un ni l'autre hors ton
    board-scrutiny. Un seul chemin de code, un seul verdict.

    Renvoie les octets contrôlés ; lève ``DocxSafetyBlock`` si un résidu
    non étayé subsiste.
    """
    _dl = lang or str(result.get("lang") or result.get("language") or "fr")
    # ``raw_result`` est le dictionnaire d'origine de l'appelant : les
    # diagnostics du post-contrôle y sont propagés quand il diffère du
    # ``result`` normalisé. En rejeu, les deux coïncident.
    _raw_result62138 = raw_result if raw_result is not None else result
    _docx_payload62122 = payload
    _docx_payload62122 = repair_docx_semantic_truth(_docx_payload62122, result)
    # v62.12.2 — post-contrôle du livrable réel, après sérialisation OOXML.
    # L'annexe de scénarios est explicitement exclue ; toute cible prospective
    # chiffrée restante dans le corps bloque l'export.
    #
    # v62.13.9.4.10 — LE CONTRÔLE FINAL N'EST PLUS CONDITIONNÉ AU TON.
    # Jusqu'ici tout ce bloc — pré-contrôle numérique, gate de surface, oracle
    # de contenu et décision de blocage — vivait sous
    # ``finance_tone == "BOARD_SCRUTINY"``. Conséquence mise au jour par le
    # harnais de chaîne réelle (contre-audit 31/08/2026) : un export en ton
    # ADVISORY, ou sans ton, ne passait AUCUN de ces contrôles — et les trois
    # dossiers de référence (dossier industriel et dossier anglophone coté sans ton, dossier de conseil en
    # ADVISORY) s'exportaient donc sans jamais solliciter la couche de sûreté
    # finale. Un document de travail supervisé n'a pas moins besoin d'être
    # exempt de chiffres non prouvés qu'un document de conseil.
    #
    # Le ton module désormais la SÉVÉRITÉ DE LA RÉPARATION (le pré-contrôle
    # board-scrutiny reste réservé à son ton), jamais l'EXISTENCE du contrôle :
    # gate, oracle et décision d'export s'appliquent à tout export.
    _board_tone62410 = str(result.get("finance_tone") or "").upper() == "BOARD_SCRUTINY"
    if True:
        from utils.board_scrutiny_guard import (
            audit_docx_executive_numbers_detailed,
            repair_docx_executive_numbers,
        )
        _allow_lbl_62130 = False  # v62.13.2 Option B — single active policy
        _support62131 = list(result.get("numeric_support_claims") or [])
        _before62128 = [] if not _board_tone62410 else audit_docx_executive_numbers_detailed(
            _docx_payload62122, lang=_dl, allow_labelled_estimates=_allow_lbl_62130,
            numeric_support_claims=_support62131,
            authoritative_horizon_values=__import__("utils.quantity_ledger", fromlist=["x"]).build_authority_items(result))
        # v62.13.9.4.49 — doctrine du 28/09 : le pré-contrôle exécutif ne réécrit plus le document ;
        # ses constats sont signalés en place avec ceux du contrôle final (plus bas).
        _repair_report62128 = {"before": len(_before62128), "repaired": 0, "after": len(_before62128),
                               "samples": [], "policy": "FLAG_IN_PLACE_V62139449"}
        _after62128 = list(_before62128)
        _post62128 = {
            "role": "docx_numeric_post_control",
            "provider": "internal",
            "model": ("board_scrutiny_docx_v62128" if _board_tone62410
                      else "final_surface_docx_v62410"),
            "tone_scoped_precontrol": _board_tone62410,
            "status": "OK" if not _after62128 else "BLOCKED",
            "claims_count": len(_before62128),
            "lines_rewritten": int(_repair_report62128.get("repaired", 0) or 0),
            "parse_errors_count": len(_after62128),
            "parse_errors_sample": _after62128[:5],
            "observability": _repair_report62128,
        }
        # v62.13.9.4.4 — gate indépendant sur le DOCX sérialisé (leçon n°16) :
        # détecteur cardinal-déclenché, distinct du pré-contrôle ; tout résidu
        # prospectif non étayé bascule le post-contrôle en BLOCKING fail-closed.
        try:
            from utils.final_surface_gate import audit_docx_bytes as _fsg_docx62139
            _fsg_res62139 = _fsg_docx62139(_docx_payload62122, result=result)
        except Exception as _fsg_exc62139:
            _fsg_res62139 = [{"where": "docx", "line": f"gate error: {type(_fsg_exc62139).__name__}: {_fsg_exc62139}", "reason": "gate_error"}]
        # v62.13.9.4.10 — le gate est filtré par le MÊME filtre de trace
        # produit que l'oracle : les deux juges doivent ignorer l'appareil de
        # sûreté et de notation de l'outil, sinon l'un bloque ce que l'autre
        # ignore (asymétrie corrigée au cycle 9.4.10).
        try:
            from utils.final_content_oracle import _is_product_trace as _ipt62410
            from utils.v62136_fr_path_maintenance import (
                _fact_row_in_engine_ledger as _frl62410)

            def _gate_exempt62410(entry) -> bool:
                line = str(entry.get("line") or entry.get("text") or "")
                if _ipt62410(line):
                    return True
                # parité avec la réparation : une rangée du registre du
                # moteur (zone A du proof layer, « brief non certifié ») est
                # exemptée par sa PROVENANCE des deux côtés, sinon le gate
                # bloque ce que la réparation conserve délibérément.
                if line.strip():
                    cells = ([c.strip() for c in line.split("|")] if "|" in line
                             else [line.strip()])
                    try:
                        if _frl62410(cells, line, result):
                            return True
                        from utils.v62136_fr_path_maintenance import (
                            _row_values_all_in_engine_ledger as _rvl62410)
                        return bool(_rvl62410(cells, result))
                    except Exception:
                        return False
                return False

            _fsg_res62139 = [r for r in _fsg_res62139 if not _gate_exempt62410(r)]
        except Exception:
            pass
        result["final_surface_gate_docx"] = {"status": "BLOCKING" if _fsg_res62139 else "OK", "residuals": _fsg_res62139[:20]}
        if _fsg_res62139:
            _post62128["status"] = "BLOCKING"
            _post62128["final_surface_residuals"] = _fsg_res62139[:20]
            _after62128 = list(_after62128) + [str(r.get("line") or r.get("text") or "")[:200] for r in _fsg_res62139[:5]]
        # v62.13.9.4.8 — second juge de production (contre-audit 30/08) :
        # l'oracle de contenu relit les octets finaux sur TOUTES les surfaces
        # OOXML, en appel séparé — un survivant bloque l'export même si le
        # gate ci-dessus est vide.
        try:
            from utils.final_content_oracle import runtime_audit as _fco62148
            _fco_res62148 = _fco62148(_docx_payload62122, result)
        except Exception as _fco_exc62148:
            _fco_res62148 = [{"part": "docx", "unit": f"oracle error: {type(_fco_exc62148).__name__}: {_fco_exc62148}", "pattern": "oracle_error"}]
        result["final_content_oracle_docx"] = {"status": "BLOCKING" if _fco_res62148 else "OK", "hits": _fco_res62148[:20]}
        if _fco_res62148:
            _post62128["status"] = "BLOCKING"
            _post62128["final_content_oracle_hits"] = _fco_res62148[:20]
            # v62.13.9.4.31.1 — le message nomme la grandeur qui a déclenché le
            # refus (contre-audit du 11/09/2026 : elle était au 640e caractère,
            # hors de l'aperçu) ; l'aperçu reste borné à 200 caractères.
            _after62128 = list(_after62128) + [
                (str(h.get("unit") or "")[:200]
                 + (f" [grandeur : {h.get('quantity')}]" if h.get("quantity") else ""))
                for h in _fco_res62148[:5]]
        # v62.13.9.4.17 — audit de qualité (point 9) : ce que l'oracle ne juge pas.
        try:
            from utils.final_surface_gate import quality_audit_docx as _qad62417
            _qa62417 = _qad62417(_docx_payload62122, result)
            _post62128["quality_audit"] = _qa62417
            if _qa62417.get("blocking"):
                _post62128["status"] = "BLOCKING"
                _after62128 = list(_after62128) + [f"[qualité] {x}" for x in _qa62417["blocking"][:3]]
        except Exception as _qa_exc62417:
            _post62128["quality_audit"] = {"error": f"{type(_qa_exc62417).__name__}: {_qa_exc62417}"}
        result.setdefault("diagnostics_attempts", []).append(_post62128)
        # v62.13.9.4.49 — DOCTRINE « TOUT LIVRER, TOUT SIGNALER EN PLACE » (décision de Robin Sauzet du
        # 28/09/2026, format validé le même jour). Le contrôle final ne neutralise plus et ne bloque plus sur
        # le contenu : pré-contrôle exécutif, porte de surface, oracle et audit de qualité produisent des
        # CONSTATS ; chaque passage concerné garde sa formulation, reçoit une étiquette, puis toutes les
        # étiquettes du document sont rendues (surlignage, « ⚠ à vérifier — motif », encadré de première
        # page, bandeau hors document de travail). Seule une panne technique empêche la livraison. Runs
        # réels du 28/09 : un identifiant LEI lu comme une grandeur retenait le CR entier ; l'oracle signale
        # désormais « nombre « … » non rattaché à une pièce » à côté de la ligne, et le consultant juge.
        from utils.flag_render49 import (flag_final_control_in_docx_bytes as _flag_final49,
                                         final_motif as _final_motif49)
        _units49: list = []
        for _it in (_before62128 or []):
            _tx = (str(_it.get("text") or _it.get("line") or _it.get("unit") or "") if isinstance(_it, dict) else str(_it))
            if _tx.strip():
                _units49.append((_tx, _final_motif49("board", _dl)))
        for _r in (_fsg_res62139 or []):
            _tx = str(_r.get("line_full") or _r.get("line") or _r.get("text") or "")
            if _tx.strip() and not _tx.startswith("gate error"):
                _units49.append((_tx, _final_motif49("gate", _dl)))
        for _h in (_fco_res62148 or []):
            _tx = str(_h.get("unit_full") or _h.get("unit") or "")
            if _tx.strip() and not _tx.startswith("oracle error"):
                _units49.append((_tx, _final_motif49(str(_h.get("reason") or _h.get("pattern") or ""), _dl,
                                                     str(_h.get("quantity") or ""))))
        # v62.13.9.4.50 — un constat du contrôle final qui REPRODUIT le brief du dirigeant (« Horizon : 30 jours »,
        # « enveloppe de 12 000 … ») n'est pas signalé : la mention unique des cibles du brief le couvre (tri du vrai
        # CR du 30/09 : deux faux signalements de ce type sur quarante)
        try:
            from utils.v62136_fr_path_maintenance import _is_brief_echo49 as _ibe50
            _units49 = [(u, m) for (u, m) in _units49 if not _ibe50(u, result)]
        except Exception:
            pass
        _quality49 = [str(x) for x in ((_post62128.get("quality_audit") or {}).get("blocking") or [])]
        if result.get("_temporal_ambiguity49"):
            _quality49.insert(0, str(result.get("_temporal_ambiguity49")))
        # v62.13.9.4.50 — situation financière courante non établie : dite UNE fois en tête (signalement de document)
        # au lieu de retirer les lignes chiffrées des sorties
        try:
            _cft50 = ((result.get("mission_gates") or {}).get("current_financial_truth") or {})
            if _cft50.get("applied") and not _cft50.get("current_financial_state_established") and _cft50.get("message"):
                _quality49.insert(0, str(_cft50.get("message")))
        except Exception:
            pass
        _mode49 = "work" if str(result.get("_render_mode") or "work") == "work" else "synthesis"
        _docx_payload62122, _flags49 = _flag_final49(_docx_payload62122, _units49, _quality49, _dl, _mode49)
        _post62128["flags"] = dict(_flags49)             # liste complète des passages signalés (diagnostic du paquet)
        _post62128["status"] = "DELIVERED_WITH_FLAGS" if _flags49.get("flagged") else "OK"
        if result.get("final_surface_gate_docx", {}).get("status") == "BLOCKING":
            result["final_surface_gate_docx"]["status"] = "FLAGGED"
        if result.get("final_content_oracle_docx", {}).get("status") == "BLOCKING":
            result["final_content_oracle_docx"]["status"] = "FLAGGED"
        _after62128 = []
        result["docx_numeric_post_control"] = _post62128
        if _raw_result62138 is not result:
            _raw_result62138.setdefault("diagnostics_attempts", []).append(dict(_post62128))
            _raw_result62138["docx_numeric_post_control"] = dict(_post62128)
            # v62.13.9.4.23 — contre-audit v22 (§7) : le registre du CR n'était
            # propagé qu'à la copie éditoriale ; le paquet ne contenait que celui
            # de la synthèse. Les deux références vivent dans le résultat brut.
            if result.get("register_sidecar") and str(result.get("_render_mode") or "work") == "work":
                _raw_result62138["register_sidecar"] = dict(result.get("register_sidecar"))
        # v62.13.9.4.49 — plus aucun blocage sur le contenu : ``_after62128`` est vide par construction
        # (les constats sont signalés en place). ``DocxSafetyBlock`` reste défini pour les appelants et
        # les pannes techniques qu'ils choisissent de lever.
    return _docx_payload62122

# ═══ v62.13.9.4.31.1 — ISOLATION DES EXPORTS (point 3 du contre-audit ChatGPT du 11/09/2026)
# Chemin nominal jusqu'ici : Word de travail → synthèse → PowerPoint, l'appel du
# premier Word NU dans le ``try`` du run. Un ``DocxSafetyBlock`` sur le CR filait
# jusqu'au ``except`` global : la synthèse et le deck n'étaient jamais atteints
# (run réel RUN-20260911T083601Z-b6ac97 : aucun des trois livrables dans
# le paquet pour UNE unité refusée). Règle : chaque livrable est tenté et
# contrôlé séparément ; un refus du CR laisse le résultat sauvegardé intact et
# nomme le document concerné ; un problème de fond COMMUN bloque toujours les
# trois, parce que la synthèse passe le même contrôle final
# (``apply_final_docx_control``) et le deck son propre oracle — l'isolation ne
# contourne rien, elle cesse seulement de priver l'utilisateur des documents
# qu'un défaut local n'affecte pas.
DELIVERY_STATUS_KEY = "delivery_status"


def _delivery_state_from_post_control(result: dict) -> str:
    pc = result.get("docx_numeric_post_control") or {}
    st_ = str(pc.get("status") or "")
    if st_ in ("DELIVERED_AFTER_RESIDUAL_NEUTRALIZATION", "DELIVERED_WITH_FLAGS"):
        return st_                                       # v62.13.9.4.49 — livré, passages signalés
    return "DELIVERED"


def run_document_exports(result: dict, lang: str = "fr", *,
                         export_docx_fn=None, export_synthese_fn=None) -> dict:
    """Tente le Word de travail PUIS la synthèse, chacun dans son propre garde-fou.

    Renvoie ``{"cr": bytes|None, "cr_error": str|None, "synthese": bytes|None,
    "synthese_error": str|None, "synthese_sidecar": ...}`` et écrit
    ``result["delivery_status"]`` (statut et raison par livrable — lu par le
    paquet, le diagnostic A1 et l'écran de fin). Fonction pure vis-à-vis de
    Streamlit : testable hors interface, injectable pour les contrats.
    """
    # v62.13.9.4.34 (lot 1) — FAIL-CLOSED AU BON ENDROIT : aucun livrable tant que
    # l'autorité temporelle est bloquée. Contre-audit de publication du 14/09/2026
    # (run réel du dossier réseau de soins) : le brief situait l'analyse début 2023,
    # le contexte l'avait détecté et bloqué (BLOCKED_AMBIGUOUS) — et les trois
    # livrables sont sortis quand même, avec des échéances 2026. Le run se fait,
    # se bloque proprement et propose l'adoption de la date ; il ne produit rien
    # d'antidaté en attendant. Le lancement, lui, reste ouvert : le blocage vit
    # dans le run, jamais dans une porte d'interface sans poignée.
    _pol34 = str((((result or {}).get("temporal_authority") or {}).get("policy") or {}).get("mode") or "")
    if _pol34.startswith("BLOCKED"):
        _en34 = str(lang or "fr").lower().startswith("en")
        _why34 = (("Autorité temporelle non établie (%s) : la date d'analyse doit être adoptée ou écartée "
                   "avant toute production de livrable." % _pol34)
                  if not _en34 else
                  ("Temporal authority not established (%s): the analysis date must be adopted or declined "
                   "before any deliverable is produced." % _pol34))
        # v62.13.9.4.49 — DOCTRINE DU 28/09/2026 (« seule une panne technique bloque », levée validée
        # par Robin Sauzet le même jour ; contre-recette ChatGPT §8 : demander à l'utilisateur plutôt
        # que trancher seul) : les livrables SORTENT, avec en première page un signalement de document
        # qui demande de confirmer ou de corriger la date ; rien n'est antidaté en silence.
        result["_temporal_ambiguity49"] = (
            ("Ambiguïté de date : l'autorité temporelle n'est pas établie (%s). Confirmez ou corrigez la date "
             "d'analyse ; relisez en conséquence les échéances et les périodes de ce document." % _pol34)
            if not _en34 else
            ("Date ambiguity: temporal authority is not established (%s). Confirm or correct the analysis "
             "date, then reread this document's deadlines and periods accordingly." % _pol34))
    _edx = export_docx_fn or export_docx
    _esx = export_synthese_fn or export_synthese_docx
    out: dict = {"cr": None, "cr_error": None, "synthese": None,
                 "synthese_error": None, "synthese_sidecar": None}
    ds = result.setdefault(DELIVERY_STATUS_KEY, {})
    ds["rule"] = ("chaque livrable est contrôlé et livré séparément ; un refus du compte rendu "
                  "ne retire ni la synthèse ni la trame, qui passent leur propre contrôle")
    # ── Word de travail (compte rendu) ──
    try:
        out["cr"] = _edx(result)
        ds["cr"] = {"status": _delivery_state_from_post_control(result), "reason": None}
    except DocxSafetyBlock as _blk:
        out["cr_error"] = str(_blk)
        ds["cr"] = {"status": "WITHHELD", "reason": str(_blk)[:600],
                    "document": "compte rendu (Word de travail)"}
    except Exception as _exc:                          # noqa: BLE001 — l'export ne doit jamais tuer le run
        out["cr_error"] = f"{type(_exc).__name__}: {_exc}"
        ds["cr"] = {"status": "ERROR", "reason": out["cr_error"][:600],
                    "document": "compte rendu (Word de travail)"}
    # ── Synthèse Word (même contrôle final, verdict propre) ──
    try:
        out["synthese"] = _esx(result)
        out["synthese_sidecar"] = (result.get("register_sidecar_synthesis") or None)
        ds["synthese"] = {"status": _delivery_state_from_post_control(result), "reason": None}
    except DocxSafetyBlock as _blk:
        out["synthese_error"] = str(_blk)
        ds["synthese"] = {"status": "WITHHELD", "reason": str(_blk)[:600], "document": "synthèse (Word)"}
    except Exception as _exc:                          # noqa: BLE001
        out["synthese_error"] = f"{type(_exc).__name__}: {_exc}"
        ds["synthese"] = {"status": "ERROR", "reason": out["synthese_error"][:600], "document": "synthèse (Word)"}
    return out


def record_pptx_delivery_status(result: dict, pptx_bytes, layout_report, requested: bool = True) -> dict:
    """Statut du troisième livrable, écrit au même endroit que les deux autres."""
    ds = result.setdefault(DELIVERY_STATUS_KEY, {})
    rep = layout_report if isinstance(layout_report, dict) else {}
    if not requested:
        ds["pptx"] = {"status": "NOT_REQUESTED", "reason": None}
    elif pptx_bytes:
        ds["pptx"] = {"status": ("DELIVERED_WITH_WARNING" if rep.get("quality_warning") else "DELIVERED"),
                      "reason": None}
    elif rep.get("analysis_blocked"):
        ds["pptx"] = {"status": "BLOCKED", "reason": "autorité temporelle bloquée — PPTX diagnostic local seulement",
                      "document": "trame (PowerPoint)"}
    else:
        _errs = rep.get("errors") or []
        ds["pptx"] = {"status": "WITHHELD", "document": "trame (PowerPoint)",
                      "reason": (str(_errs[0])[:600] if _errs else "retenue par le contrôle final du deck")}
    return ds["pptx"]


def withheld_deliverables_message(result: dict, lang: str = "fr") -> str | None:
    """Une phrase qui nomme les livrables non livrés et pourquoi — ou None."""
    ds = (result or {}).get(DELIVERY_STATUS_KEY) or {}
    _labels = {"cr": ("le compte rendu (Word de travail)", "the working report (Word)"),
               "synthese": ("la synthèse (Word)", "the synthesis (Word)"),
               "pptx": ("la trame (PowerPoint)", "the deck (PowerPoint)")}
    missing = [(k, v) for k, v in ds.items()
               if isinstance(v, dict) and str(v.get("status") or "") in ("WITHHELD", "ERROR", "BLOCKED")]
    if not missing:
        return None
    en = str(lang).lower().startswith("en")
    parts = []
    for k, v in missing:
        lab = _labels.get(k, (k, k))[1 if en else 0]
        why = str(v.get("reason") or "")
        if why.startswith("DOCX_SAFETY_BLOCK"):
            why = ("cibles numériques non étayées subsistant après la réparation automatique"
                   if not en else "unsupported quantified targets remain after automatic repair")
        parts.append(f"{lab} — {why[:220]}" if why else lab)
    head = ("Livrable(s) non livré(s) par le contrôle final : " if not en
            else "Deliverable(s) withheld by the final check: ")
    tail = (" Les autres livrables et le paquet (diagnostic, registres) restent disponibles."
            if not en else " The other deliverables and the package (diagnostic, registers) remain available.")
    return head + " ; ".join(parts) + "." + tail


def export_docx(result: dict, mode: str = "work") -> bytes:
    # v62.13.8 — build a delivery-only view; the evidence tree remains immutable.
    # v62.13.9.4.21 — ``mode="work"`` : document de travail, rien n'est retiré,
    # chaque chiffre non étayé porte son statut en marge (décision Robin du
    # 05/09/2026) ; ``mode="synthesis"`` : rendu dérivé, neutralisation comme avant.
    _raw_result62138 = result
    try:
        _raw_result62138["_render_mode"] = "work" if mode == "work" else "synthesis"
    except Exception:
        pass
    # v16.5.38 — bilingual DOCX
    # B.1.3.5 (run dossier anglophone coté EN) — la langue des BLOCS SYSTÈME du CR suit la
    # LANGUE DU RUN (result["lang"]) : le load_settings() disque perdait la
    # sélection écran → CR EN avec 🧭/Orientation/wrappers FR →
    # auto-plafonnement du language gate.
    result = apply_v62136_maintenance(_raw_result62138)
    _dl = ((result.get("lang") or "").strip().lower()
           or getattr(load_settings(), "output_language", "fr"))
    doc = Document()

    # ── En-tête ──────────────────────────────────────────────────────────────
    from utils.system_marks import snapshot as _sm_snap, mark_since as _sm_mark   # v62.13.9.4.21
    doc.add_heading(DL("title", _dl), level=0)
    _snap_hdr = _sm_snap(doc)
    hdr_table = doc.add_table(rows=1, cols=3)
    hdr_table.style = "Table Grid"
    hdr_table.cell(0, 0).text = "\u2063" + f"{DL('version', _dl)} : {VERSION_LABEL}"   # v62.13.9.4.21 — texte de l'outil
    hdr_table.cell(0, 1).text = f"{DL('date', _dl)} : {_mc_edition('%d/%m/%Y %H:%M')}"
    meta = result.get("inputs", {}).get("attachments_meta", {}) or {}
    hdr_table.cell(0, 2).text = (
        f"{DL('attachments', _dl)} : {meta.get('files', 0)} | ~{meta.get('tokens_est', 0)} tokens"
        if meta.get("files")
        else DL("no_attachment", _dl)
    )
    # ── Ligne Pappers (si enrichissement effectué) ────────────────────────────
    _retro34_cr = _retrospective_line34(result, str(_dl).lower().startswith("en"))   # v62.13.9.4.34 (lot 1)
    if _retro34_cr:
        doc.add_paragraph("\u2063" + _retro34_cr)
    _pap_log = result.get("pappers_resolution_log")
    if _pap_log and isinstance(_pap_log, dict) and _pap_log.get("primary_name"):
        _pap_cr  = _pap_log.get("pappers_credits_est", "?")
        _pap_tok = _pap_log.get("tokens_est_full", 0) + _pap_log.get("tokens_est_summary", 0)
        _pap_conf = _pap_log.get("path", "")
        # B.1.3.12 (run 6) — la résolution 3.10 VIDE override_conflict quand
        # elle réussit : l'information vit dans choice_reason. La première
        # ligne vue par le lecteur doit qualifier le clic (wording audit).
        _fp12 = _fp_root(result)
        _fp12_reason = str(_fp12.get("choice_reason") or "")
        _fp12_related = (str(_fp12.get("override_conflict") or "").strip() != ""
                         or ("related" in _fp12_reason.lower()
                             and _fp12_reason.upper().startswith("RESOLVED_")))
        if _fp12_related:
            import re as _re14
            _clicked14 = (_re14.search(r"«\s*(.+?)\s*»", _fp12_reason)
                          or _re14.search(r"\u2039\s*(.+?)\s*\u203a", _fp12_reason))
            _clicked14 = _clicked14.group(1) if _clicked14 else ""
            _rw14 = _rel_wording14(str(_fp12.get("chosen_entity") or ""),
                                   _clicked14, _dl)
            _pap_line = (
                (f"Pappers candidate: {_pap_log['primary_name']} — user-selected"
                 f" / {_rw14}"
                 if _dl == "en" else
                 f"Candidat Pappers : {_pap_log['primary_name']} — choisi par"
                 f" l'utilisateur / {_rw14}")
                + f" · ~{_pap_cr} "
                + ("credits" if _dl == "en" else "crédits")
                + f" · ~{_pap_tok} tokens"
            )
        else:
            # B.1.3.28-chatgpt — libellé utilisateur ET localisé : le correctif
            # officiel introduisait du français dans un run EN.
            _pap_path_labels = {
                "fr": {"SIREN_DIRECT": "SIREN du brief",
                       "USER_CONFIRMED": "identité confirmée",
                       "CLAUDE": "recherche nominale confirmée"},
                "en": {"SIREN_DIRECT": "SIREN from brief",
                       "USER_CONFIRMED": "identity confirmed",
                       "CLAUDE": "name search confirmed"},
            }
            _pap_path_label = _pap_path_labels.get(_dl, _pap_path_labels["fr"]).get(
                str(_pap_conf), str(_pap_conf))
            _pap_line = (
                f"Pappers : {_pap_log['primary_name']} ({_pap_path_label})"
                + f" · ~{_pap_cr} "
                + ("credits" if _dl == "en" else "crédits")
                + f" · ~{_pap_tok} tokens"
            )
        _pap_para = doc.add_paragraph()
        _pap_run  = _pap_para.add_run(_pap_line)
        _pap_run.italic = True
        _pap_run.font.size = __import__("docx").shared.Pt(8)
    _sm_mark(doc, _snap_hdr)                       # en-tête version/date = contenu de l'outil

    # ── Bandeau routing v16.5.62 — profile société + cohérence UI ↔ Pappers ───
    # Patch v16.5.72 (audit ChatGPT round 14) — Affichage international.
    # Bug : pour dossier anglophone coté plc le DOCX affichait "size=pme nature=services
    # APE=? forme=?" alors que c'est une UK plc cotée Luxury/Fashion.
    # Solution : utiliser to_user_facing_label() si champs internationaux
    # disponibles ; fallback legacy "size=...nature=...APE=..." sinon.
    _cp = result.get("company_profile")
    if _cp and isinstance(_cp, dict):
        # Détecter si on a un profil international enrichi
        _has_intl = bool(_cp.get("country") or _cp.get("company_number")
                         or _cp.get("lei"))
        if _has_intl:
            # Patch v16.5.72 — Construire un CompanyProfile temporaire pour
            # appeler to_user_facing_label(). Évite de répliquer la logique.
            try:
                from utils.company_profile import CompanyProfile
                _profile_obj = CompanyProfile(
                    size=_cp.get("size", "pme"),
                    nature=_cp.get("nature", "mixed"),
                    is_solo=_cp.get("is_solo", False),
                    is_services=_cp.get("is_services", False),
                    headcount=_cp.get("headcount"),
                    ca_eur=_cp.get("ca_eur"),
                    ape_code=_cp.get("ape_code", "") or "",
                    legal_form=_cp.get("legal_form", "") or "",
                    confidence=_cp.get("confidence", "low"),
                    source=_cp.get("source", "default"),
                    country=_cp.get("country"),
                    company_number=_cp.get("company_number"),
                    company_number_kind=_cp.get("company_number_kind", "") or "",
                    registry=_cp.get("registry"),
                    lei=_cp.get("lei"),
                    company_name_official=_cp.get("company_name_official"),
                    sector_label=_cp.get("sector_label", "") or "",
                )
                _profile_line = _profile_obj.to_user_facing_label(_dl)
                # Préfixer "Profile société :" pour cohérence visuelle
                # B.1.3.5 (dossier industriel (composants) P2-6) — un LEI seul n'identifie rien : préfixer
                # le NOM RÉSOLU quand la ligne ne porte que « LEI: … ».
                try:
                    _rgP = str((result.get("entity_scope", {}) or {}).get("registry_entity") or "").strip()
                    if (_rgP and str(_profile_line).strip().startswith("LEI:")
                            and _rgP.upper() not in str(_profile_line).upper()):
                        _profile_line = f"{_rgP} · {_profile_line}"
                except Exception:
                    pass
                _profile_line = (
                    f"Profile société : {_profile_line}" if _dl == "fr"
                    else f"Company profile: {_profile_line}"
                )
            except Exception:
                # Fallback legacy si erreur
                _has_intl = False
        if not _has_intl:
            # Fallback legacy v16.5.71.5 (cas FR sans champs internationaux)
            _size      = _cp.get("size", "?")
            _nature    = _cp.get("nature", "?")
            _is_solo   = _cp.get("is_solo", False)
            _src       = _cp.get("source", "?")
            _ape       = _cp.get("ape_code", "") or "?"
            _legal     = _cp.get("legal_form", "") or "?"
            _profile_line = (
                f"Profile société : source={_src} · size={_size} · nature={_nature}"
                f" · is_solo={_is_solo} · APE={_ape} · forme={_legal}"
            )
        # M6-A2 — en-tête périmètre entité : si l'entité d'analyse (groupe coté)
        # diffère de l'entité registre (filiale CH homonyme), on l'explicite AVANT
        # la ligne de profil, pour ne pas laisser croire que l'entité légale = sujet.
        _es = result.get("entity_scope") or {}
        if isinstance(_es, dict) and _es.get("entity_mismatch"):
            try:
                from patches.entity_scope import EntityScope as _ES, header_lines as _hls
                for _hl in _hls(_ES(**_es), _dl):
                    _hp = doc.add_paragraph()
                    _hr = _hp.add_run(_hl)
                    _hr.bold = True
                    _hr.font.size = __import__("docx").shared.Pt(8)
            except Exception:
                pass
        # M6-A3 — cadre temporel explicite : run / derniers comptes / scénario.
        # Empêche un lecteur de prendre une vue rétrospective (« T2 2025 ») pour
        # l'instant courant, et que la filing date passe pour la date d'analyse.
        _tf = result.get("temporal_frame") or {}
        if isinstance(_tf, dict) and (_tf.get("run_as_of_date") or _tf.get("scenario_date")):
            try:
                from patches.temporal_frame import TemporalFrame as _TF, header_lines as _tfl
                for _hl in _tfl(_TF(**_tf), _dl):
                    _hp = doc.add_paragraph()
                    _hr = _hp.add_run(_hl)
                    _hr.italic = True
                    _hr.font.size = __import__("docx").shared.Pt(8)
            except Exception:
                pass
        # Gate 17 (P1-UX16-01) — le MESSAGE DE POLITIQUE TEMPORELLE est
        # exposé de manière fiable dans le binaire : un run non-live
        # porte son bandeau read-only (le rendu enrichi = lot H).
        try:
            _pol17 = ((result.get("temporal_authority") or {})
                      .get("policy") or {})
            _pmode17 = _pol17.get("mode", "")
            if _pmode17 and _pmode17 != "LIVE_MUTATING":
                # Refactor — libellé par le TemporalStatusRenderer
                # (source unique) ; repli : policy sérialisée.
                try:
                    from patches.temporal_status_renderer import (
                        temporal_status as _ts17)
                    _pmsg17 = _ts17(result,
                                    (result.get("lang") or "fr"))["message"]
                except Exception:
                    _pmsg17 = (_pol17.get("user_message_fr")
                               if (result.get("lang") or "fr") == "fr"
                               else _pol17.get("user_message_en")) or ""
                if _pmsg17:
                    _pp17 = doc.add_paragraph()
                    _pr17 = _pp17.add_run(_pmsg17)
                    _pr17.bold = True
                    _pr17.font.size = __import__("docx").shared.Pt(9)
        except Exception:
            pass
        _prof_para = doc.add_paragraph()
        _prof_run  = _prof_para.add_run(_profile_line)
        _prof_run.italic = True
        _prof_run.font.size = __import__("docx").shared.Pt(8)

    doc.add_paragraph("")

    # ── v16.5.64 — Bandeau briefcheck + bloc confidence score ────────────────
    # Injection défensive : si briefcheck ou delivery_confidence_score est None,
    # la fonction ne fait rien. Aucune régression possible.
    try:
        from utils.confidence_render import docx_add_confidence_block
        _snap_conf = _sm_snap(doc)
        _n0_62421 = len(doc.paragraphs)
        docx_add_confidence_block(
            doc,
            briefcheck=result.get("briefcheck"),
            confidence_score=result.get("delivery_confidence_score"),
            lang=_dl,
            # B.1.3.23 P0-D — enforcement dur (conflit entité brief / contexte-faits)
            # B.1.3.56 — canal UNIQUE de blocage : conflits B23 OU verdict
            # mission dur (statut unique, raisons agrégées, pas de double bandeau).
            run_blocked=bool((result.get("b23_guards") or {}).get("run_not_validatable")
                             or (result.get("delivery_confidence_score") or {}).get("run_not_validatable")),
            run_block_reasons=(((result.get("b23_guards") or {}).get("run_block_reasons") or [])
                               + [r for r in ((result.get("delivery_confidence_score") or {}).get("run_block_reasons") or [])
                                  if r not in (((result.get("b23_guards") or {}).get("run_block_reasons")) or [])]),
        )
        _sm_mark(doc, _snap_conf)                   # bloc Confidence/briefcheck = contenu de l'outil
        try:                                        # v62.13.9.4.21 — marqueur d'outil structurel sur le bloc
            from utils.quantity_ledger import mark_tool_paragraphs as _mtp62421
            _mtp62421(doc, _n0_62421)
            for _tbl62421 in doc.tables[-3:]:
                for _row62421 in _tbl62421.rows:
                    for _cell62421 in _row62421.cells:
                        for _p62421 in _cell62421.paragraphs:
                            if _p62421.text and "\u2063" not in _p62421.text and any(ch.isdigit() for ch in _p62421.text):
                                if _p62421.runs:
                                    _p62421.runs[0].text = "\u2063" + _p62421.runs[0].text
        except Exception:
            pass
    except Exception as _cr_err:
        # Logger au lieu de silent swallow — l'erreur doit remonter dans le terminal Streamlit
        import logging as _lg
        _lg.getLogger("codir_ia").warning(
            f"docx_add_confidence_block failed: {type(_cr_err).__name__}: {_cr_err}"
        )

    # ── v17.1-B2.3-A — Décision réconciliée + alertes pipeline ──────────────
    try:
        _b23 = result.get("b23_guards") or {}
        _dec = (_b23.get("decision") or {}) if isinstance(_b23, dict) else {}
        _flags = (_b23.get("flags") or []) if isinstance(_b23, dict) else []
        if _dec.get("final") or _flags:
            from docx.shared import Pt as _Pt23, RGBColor as _RGB23
            _h = doc.add_paragraph().add_run(
                "⚖️ Décision réconciliée & alertes pipeline (B2.3)" if _dl == "fr"
                else "⚖️ Reconciled decision & pipeline alerts (B2.3)")
            _h.bold = True; _h.font.size = _Pt23(11); _h.font.color.rgb = _RGB23(0x1B, 0x2A, 0x4A)
            if _dec.get("final"):
                try:
                    from patches.pipeline_guards_b23 import localize_verdict as _lv23
                    # M.5.10.7 — final_en produit à la source (comme note_en) : on le
                    # privilégie en EN. localize_verdict (fragments) ratait certains
                    # finals contrôlés, p.ex. ALERTS_ONLY (audit ChatGPT).
                    _final_disp = ((_dec.get('final_en') or _lv23(_dec['final'], _dl))
                                   if _dl == 'en' else _dec['final'])
                    _note_disp = (_dec.get('note_en', '') if _dl == 'en'
                                  else _dec.get('note', ''))
                except Exception:
                    _final_disp = (_dec.get('final_en') if _dl == 'en' and _dec.get('final_en')
                                   else _dec['final'])
                    _note_disp = (_dec.get('note_en', '') if _dl == 'en' else _dec.get('note', ''))
                # B.1.3 (audit dossier industriel (composants)) — Grade D/E : un CR ne « décide »
                # pas sur une base non certifiée ; il ORIENTE le travail.
                _cs_gr = str((result.get("delivery_confidence_score") or {}).get(
                    "grade", "")).upper()
                if _cs_gr in ("D", "E"):
                    _dec_lbl = (
                        f"Orientation de travail (non certifiée — pièces "
                        f"financières requises) : {_final_disp}. {_note_disp}"
                        if _dl == "fr" else
                        f"Working orientation (not certified — financial "
                        f"documents required): {_final_disp}. {_note_disp}")
                else:
                    _dec_lbl = (
                        f"Décision finale (prudence par défaut) : "
                        f"{_final_disp}. {_note_disp}"
                        if _dl == "fr" else
                        f"Final decision (default prudence): "
                        f"{_final_disp}. {_note_disp}")
                _dr = doc.add_paragraph().add_run(_dec_lbl)
                _dr.font.size = _Pt23(9); _dr.italic = True
                if _dec.get("divergent"):
                    _dr.font.color.rgb = _RGB23(0xB0, 0x5A, 0x00)
            for _f in _flags[:8]:
                # M.5.10.6 — si le flag est la note de décision FR ré-injectée,
                # on rend sa version EN en run anglais (évite le doublon français).
                _ftxt = _f
                if _dl == "en" and _dec.get("note") and _f == _dec.get("note"):
                    _ftxt = _dec.get("note_en", _f)
                _fr = doc.add_paragraph(style=None).add_run(f"⚠ {_ftxt}")
                _fr.font.size = _Pt23(8); _fr.font.color.rgb = _RGB23(0xB0, 0x5A, 0x00)
    except Exception:
        pass

    # ── Patch v16.5.72 — Section "Faits financiers utilisés" (Source Traceability)
    # Apprentissage ChatGPT round 14 : le rapport doit montrer ce qu'il a lu,
    # ce qu'il infère, et d'où viennent les chiffres. Différenciant produit.
    try:
        from docx.shared import Pt, RGBColor
        _fft = result.get("financial_facts_table")
        _fdoc_msg = result.get("financial_documents_status_message")

        # ── B.1.3 — Bannière COMPLETION GATE : livrable non distribuable ──
        _cgi = result.get("completion_gate") or []
        if _cgi:
            _cg_para = doc.add_paragraph()
            _cg_run = _cg_para.add_run(
                (f"⛔ LIVRABLE NON DISTRIBUABLE EN L'ÉTAT — "
                 f"{len(_cgi)} section(s) incomplète(s) détectée(s) "
                 f"(sortie tronquée). Régénérer avant diffusion.")
                if _dl == "fr" else
                (f"⛔ RUN NOT VALIDATABLE — DELIVERABLE NOT DISTRIBUTABLE AS IS — "
                 f"{len(_cgi)} incomplete section(s) detected "
                 f"(truncated output). Regenerate before circulation."))
            _cg_run.bold = True
            _cg_run.font.size = Pt(10)
            _cg_run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)

        # ── B.1.3 — Conflit langue écran/brief (l'écran prime, contrat UI-1)
        _lc = result.get("language_conflict") or {}
        if _lc:
            _lc_para = doc.add_paragraph()
            _lc_run = _lc_para.add_run(
                (f"⚠ Langue : le brief indiquait "
                 f"« {'Français' if _lc.get('brief')=='fr' else 'English'} », "
                 f"la sélection écran "
                 f"({'Français' if _lc.get('active')=='fr' else 'English'}) "
                 f"a piloté ce run (contrat UI-1).")
                if _dl == "fr" else
                (f"⚠ Language: the brief stated "
                 f"“{'Français' if _lc.get('brief')=='fr' else 'English'}”, "
                 f"the screen selection "
                 f"({'Français' if _lc.get('active')=='fr' else 'English'}) "
                 f"drove this run (UI-1 contract)."))
            _lc_run.italic = True
            _lc_run.font.size = Pt(9)
            _lc_run.font.color.rgb = RGBColor(0xB0, 0x5A, 0x00)

        # ── B.1.3 — 🧭 CONTEXTE D'ANALYSE RETENU (couche de preuve B.1) ────
        # Le contexte existait au CSV (dossier industriel (composants) : groupe/consolidé/high) mais
        # JAMAIS dans le livrable : le writer reconstruisait sa table depuis
        # le dict et ignorait le rendu markdown E7. On consomme désormais le
        # bloc b1_proof_layer déjà exposé par le moteur.
        try:
            _b1pl = result.get("b1_proof_layer") or {}
            _b1ctx = _b1pl.get("analysis_context") or {}
            if _b1ctx:
                _cx_title = doc.add_paragraph()
                _cx_tr = _cx_title.add_run(
                    "🧭 Contexte d'analyse retenu" if _dl == "fr"
                    else "🧭 Analysis context retained")
                _cx_tr.bold = True
                _cx_tr.font.size = Pt(11)
                _cx_tr.font.color.rgb = RGBColor(0x1B, 0x2A, 0x4A)
                _cx_mode = str(_b1ctx.get("mode", "?"))
                _cx_tgt = str(_b1ctx.get("target_entity", "?"))
                _cx_lvl = str(_b1ctx.get("target_perimeter_level", "?"))
                _cx_from = str(_b1ctx.get("inferred_from", "?"))
                _cx_conf = str(_b1ctx.get("inference_confidence", "?"))
                _cx_ovr = bool(_b1ctx.get("user_override"))
                _n_fs = int(result.get("n_pdfs_with_fs") or 0)
                if _dl == "fr":
                    _cx_lines = [
                        f"Mode : {_loc_ctx_value(_cx_mode, 'fr')} · "
                        f"Périmètre cible : {_loc_ctx_value(_cx_lvl, 'fr')} · "
                        f"Entité cible : {_cx_tgt}"
                        # B.1.3.25 P1-C' — run bloqué ⇒ contexte visible requalifié
                        + (" · À REQUALIFIER (ambiguous_group)"
                           if (result.get("b23_guards") or {}).get("run_not_validatable")
                           else ""),
                        f"Inféré depuis : {_cx_from} · Confiance : {_cx_conf}"
                        + (" · Surcharge utilisateur active" if _cx_ovr else ""),
                        ("Comptes consolidés fournis : oui"
                         if _n_fs > 0 else
                         "Comptes consolidés fournis : non — les chiffres "
                         "hors faits sourcés restent des hypothèses "
                         "(jamais board-safe)."),
                    ]
                else:
                    _cx_lines = [
                        f"Mode: {_loc_ctx_value(_cx_mode, 'en')} · "
                        f"Target perimeter: {_loc_ctx_value(_cx_lvl, 'en')} · "
                        f"Target entity: {_cx_tgt}",
                        f"Inferred from: {_cx_from} · Confidence: {_cx_conf}"
                        + (" · User override active" if _cx_ovr else ""),
                        ("Consolidated accounts provided: yes"
                         if _n_fs > 0 else
                         "Consolidated accounts provided: no — figures "
                         "outside sourced facts remain hypotheses "
                         "(never board-safe)."),
                    ]
                for _cxl in _cx_lines:
                    _cxp = doc.add_paragraph()
                    _cxr = _cxp.add_run(_cxl)
                    _cxr.font.size = Pt(9)
        except Exception:
            pass

        # Toujours afficher le message de statut (résout contradiction dossier anglophone coté round 14)
        if _fdoc_msg:
            _fdoc_para = doc.add_paragraph()
            _fdoc_run = _fdoc_para.add_run(_fdoc_msg)
            _fdoc_run.italic = True
            _fdoc_run.font.size = Pt(9)

        # Section table de faits si présente et non vide
        if _fft and isinstance(_fft, dict) and _fft.get("facts"):
            _facts = _fft.get("facts", [])
            _diag = _fft.get("diag", {})
            # v17.1-B2.2.2 — mêmes invariants que le deck dans le CR Word :
            # cascade de présentation (social/weak relégués) + scorer_ok.
            _scorer_ok_docx = bool(_fft.get("scorer_ok", True))
            _all_facts_docx = list(_facts)
            _integrity_docx = ""
            try:
                from patches.finance_shaper import select_deck_primary, integrity_note
                _prim_docx, _dem_docx = select_deck_primary(_facts, demote_brief=False)  # B.1.3.5 — brief VISIBLE en A
                _facts = _prim_docx   # v17.1-B2.2.3 — accepte VIDE ; ne restaure pas les relégués
                _integrity_docx = integrity_note(_dem_docx, lang=_dl)
            except Exception:
                pass

            # Titre section
            _ft_title = doc.add_paragraph()
            _ft_run = _ft_title.add_run(
                "📋 Faits financiers utilisés — Traçabilité des sources"
                if _dl == "fr" else
                "📋 Financial facts used — Source traceability"
            )
            _ft_run.bold = True
            _ft_run.font.size = Pt(11)
            _ft_run.font.color.rgb = RGBColor(0x2E, 0x4A, 0x7F)

            # Score traçabilité
            _score_para = doc.add_paragraph()
            _score = _diag.get("traceability_score", 0)
            _solid = _diag.get("n_facts_solid", 0)
            _estim = _diag.get("n_facts_estimate", 0)
            _unsourced = _diag.get("n_facts_unsourced", 0)
            _total = _diag.get("n_facts_total", 0)
            if _dl == "fr":
                _score_text = (
                    f"Score traçabilité : {_score}/100 — "
                    f"{_solid} fait(s) sourcé(s), "
                    f"{_estim} estimation(s)/hypothèse(s), "
                    f"{_unsourced} non sourcé(s) (sur {_total} total)."
                )
            else:
                _score_text = (
                    f"Traceability score: {_score}/100 — "
                    f"{_solid} sourced fact(s), "
                    f"{_estim} estimate(s)/hypothesis, "
                    f"{_unsourced} unsourced (out of {_total} total)."
                )
            _score_run = _score_para.add_run(_score_text)
            _score_run.italic = True
            _score_run.font.size = Pt(9)

            # v17.1-B2.2.2 — INVARIANT D'HONNÊTETÉ dans le CR Word (parité deck).
            # Scorer KO → revue humaine ; scorer OK mais CA/RN consolidés
            # manquants → score INDICATIF (la table est incomplète).
            try:
                if not _scorer_ok_docx:
                    _score_run.text = (
                        "Score non calculé — revue humaine requise" if _dl == "fr"
                        else "Score not computed — human review required"
                    )
                else:
                    from patches.finance_shaper import traceability_label
                    _tl_docx = traceability_label(
                        {"traceability_score": _score, "facts": _all_facts_docx},
                        scorer_ok=True, lang=_dl,
                    )
                    if _tl_docx.get("guarded"):
                        _score_run.text = _tl_docx["label"]
            except Exception:
                pass

            # Note d'intégrité (faits social/weak relégués, conservés au ledger).
            if _integrity_docx:
                _intg_para = doc.add_paragraph()
                _intg_run = _intg_para.add_run(_integrity_docx)
                _intg_run.italic = True
                _intg_run.font.size = Pt(8)
                _intg_run.font.color.rgb = RGBColor(0xB0, 0x5A, 0x00)

            if not _facts:  # v17.1-B2.2.3 — primaire vide, sans restaurer les relégués
                _er = doc.add_paragraph().add_run(
                    "Aucun fait board-primary affichable — faits relégués (social/source faible). Voir note d'intégrité."
                    if _dl == "fr" else
                    "No board-primary fact — all demoted (social/weak source). See integrity note.")
                _er.italic = True; _er.font.size = Pt(9)
                _er.font.color.rgb = RGBColor(0xB0, 0x5A, 0x00)

            # ── Patch v16.5.72.5 (audit ChatGPT round 20 P1) ────────────────
            # Séparation Word en 2 zones : A. Faits financiers / B. Métadonnées
            # Avant v16.5.72.5 : la table Word mélangeait Revenue + UK Company
            # Number + LEI dans la même grille (illisible pour DG/DAF).
            # La séparation existait déjà dans to_markdown_table() depuis
            # v16.5.72.2 mais le rendu Word n'avait pas été aligné.
            #
            # On utilise FinancialFact.is_financial_value() pour partitionner :
            # - Section A : faits financiers (Revenue, EBIT, FCF, etc.)
            # - Section B : métadonnées (UK Company Number, LEI, sections détectées)
            from utils.financial_facts_table import FactStatus
            try:
                from utils.financial_facts_table import FinancialFact as _FF
                # Recharger les FinancialFact depuis _facts dict pour utiliser
                # is_financial_value(). Sinon on doit refaire la classification ici.
                # _facts est en dict — on classifie selon le label uniquement
                # (heuristique légère cohérente avec FinancialFact.is_financial_value)
                IDENTITY_LABELS_FRAGMENTS = (
                    "uk company number", "company number", "siren", "siret",
                    "lei", "ape", "company status", "statut société",
                    "dernière clôture comptable", "accounts made up to",
                    "sections financières détectées", "signal financier exploitable",
                )
                def _is_metadata(fact_dict):
                    label_lower = str(fact_dict.get("label", "")).lower()
                    return any(frag in label_lower for frag in IDENTITY_LABELS_FRAGMENTS)
                _financial_facts = [f for f in _facts if not _is_metadata(f)]
                _identity_facts = [f for f in _facts if _is_metadata(f)]
            except Exception:
                _financial_facts = _facts
                _identity_facts = []

            # B.1.3.5 (audit dossier industriel (composants) P1-3) — les montants issus du NARRATIF
            # des agents (« Narratif agents ») ne sont pas des faits de
            # preuve : Zone C dédiée ci-dessous, exclus de la Zone A.
            _narrative_facts = [f for f in _financial_facts
                                if str(f.get("source", "") or "").startswith("Narratif agents")]
            if _narrative_facts:
                _financial_facts = [f for f in _financial_facts
                                    if f not in _narrative_facts]

            # F.6.8 (audit dossier réseau de soins) — _headers défini AVANT les branches Zone A / Zone B :
            # un run sans fait financier structuré (Zone A sautée) mais avec un fait
            # identité/signal (Zone B) provoquait UnboundLocalError sur _headers → rendu
            # DOCX de la table cassé. Les deux zones partagent les mêmes en-têtes.
            _headers = (
                ["Statut", "Fait", "Valeur", "Source", "Page"]
                if _dl == "fr"
                else ["Status", "Fact", "Value", "Source", "Page"]
            )

            # ── Zone A — Faits financiers ────────────────────────────────────
            if _financial_facts:
                _zone_a_title = doc.add_paragraph()
                _zone_a_run = _zone_a_title.add_run(
                    "A. Faits financiers" if _dl == "fr" else "A. Financial facts"
                )
                _zone_a_run.bold = True
                _zone_a_run.italic = True
                _zone_a_run.font.size = Pt(10)

                _facts_table_a = doc.add_table(rows=1, cols=5)
                _facts_table_a.style = "Light Grid Accent 1"
                _hdr_a = _facts_table_a.rows[0].cells
                for i, h in enumerate(_headers):
                    _hdr_a[i].text = h
                for cell in _hdr_a:
                    for p in cell.paragraphs:
                        for r in p.runs:
                            r.bold = True
                            r.font.size = Pt(9)
                _n_mismatch_a = 0
                for fact in _financial_facts[:25]:
                    from utils.financial_facts_render import loc_scope_badge as _lsb, loc_fact_status as _lfs
                    from utils.financial_facts_table import _localize_metric_label as _lml, _localize_source as _lsrc
                    _row = _facts_table_a.add_row().cells
                    # B.1.3 — hors périmètre : VISIBLE (⛔) mais exclu du score
                    _pm_mis = (str(fact.get("perimeter_match", "")).upper()
                               == "MISMATCH")
                    if _pm_mis:
                        _n_mismatch_a += 1
                        # B.1.3.16 (dossier industriel (composants) run 1 : « ⛔ ✅ FAIT » juxtaposé)
                        # — statut UNIFIÉ : hors périmètre REMPLACE le statut.
                        _row[0].text = ("⛔ HORS PÉRIMÈTRE — exclu du score"
                                        if _dl == "fr" else
                                        "⛔ OUT OF PERIMETER — excluded from score")
                    else:
                        _row[0].text = f"{fact.get('icon', '')} {_lfs(fact.get('status', ''), _dl)}" + (
                            (" — brief non certifié" if _dl == "fr"
                             else " — brief, not certified")
                            if fact.get("brief_only") else "")
                    # v17.1-B2.2.2 — badge de périmètre obligatoire (parité deck)
                    _bdg = _lsb(str(fact.get("scope", "")), _dl)
                    _lbl = _lml(str(fact.get("label", "")), _dl)  # M.5.10.5 — label localisé
                    # B.1.3.14 — la PÉRIODE distingue deux mêmes métriques
                    # (FY25 vs H1 FY26) dans la table de preuve visible.
                    _per14 = str(fact.get("period") or "").strip()
                    if _per14:
                        _lbl = f"{_lbl} ({_per14})"
                    _row[1].text = ((f"[{_bdg}] {_lbl}" if _bdg else _lbl))[:60]
                    _row[2].text = str(fact.get("value", ""))[:35]
                    _row[3].text = _lsrc(str(fact.get("source", "")), _dl)[:50]  # M.5.10.5
                    _row[4].text = str(fact.get("page", "—"))
                    for cell in _row:
                        for p in cell.paragraphs:
                            for r in p.runs:
                                r.font.size = Pt(8)
                # B.1.3 — contrat E3 rendu lisible : le hors-périmètre est
                # MONTRÉ (⛔ ci-dessus) mais ne compte pas dans le signal.
                if _n_mismatch_a:
                    _pm_para = doc.add_paragraph()
                    _pm_run = _pm_para.add_run(
                        (f"⛔ Hors périmètre d'analyse : {_n_mismatch_a} "
                         f"fait(s) montré(s) mais exclu(s) du score et du "
                         f"signal financier.") if _dl == "fr" else
                        (f"⛔ Outside analysis perimeter: {_n_mismatch_a} "
                         f"fact(s) shown but excluded from score and "
                         f"financial signal."))
                    _pm_run.italic = True
                    _pm_run.font.size = Pt(8)
                    _pm_run.font.color.rgb = RGBColor(0xC0, 0x00, 0x00)

            if not _financial_facts:
                # B.1.3 — l'ABSENCE de faits financiers se DIT (audit
                # dossier industriel (composants) : seule la zone B rendait la table trompeuse).
                _za_para = doc.add_paragraph()
                _za_run = _za_para.add_run(
                    "A. Faits financiers — aucun fait financier consolidé "
                    "utilisé." if _dl == "fr" else
                    "A. Financial facts — no consolidated financial fact "
                    "used.")
                _za_run.bold = True
                _za_run.italic = True
                _za_run.font.size = Pt(10)

            # B.1.3.5 (run dossier anglophone coté) — REGISTRE ≠ ANALYSE : la zone B ne
            # présente plus Company Number / LEI comme faits de la CIBLE
            # sans le dire (dossier anglophone coté LIMITED ≠ dossier anglophone coté Group plc).
            try:
                from patches.entity_scope_utils import registry_related as _rr135
                _mm = _rr135(result.get("entity_scope"))
                _reg_mm135 = _mm is not None
                _rg135, _an135 = (_mm if _mm else ("", ""))
            except Exception:
                _reg_mm135, _rg135, _an135 = False, "", ""

            # ── Zone B — Métadonnées de traçabilité ────────────────────────
            if _identity_facts:
                doc.add_paragraph("")
                _zone_b_title = doc.add_paragraph()
                _zone_b_run = _zone_b_title.add_run(
                    "B. Métadonnées de traçabilité (identité société, sources)"
                    if _dl == "fr"
                    else "B. Traceability metadata (company identity, sources)"
                )
                _zone_b_run.bold = True
                _zone_b_run.italic = True
                _zone_b_run.font.size = Pt(10)
                if _reg_mm135:
                    _pmm = doc.add_paragraph()
                    _rmm = _pmm.add_run(
                        (f"⚠ Entité registre = {_rg135} — entité LIÉE : ne "
                         f"décrit pas l'entité d'analyse ({_an135}). "
                         f"Métadonnées non probantes pour le périmètre "
                         f"analysé.") if _dl == "fr" else
                        (f"⚠ Registry entity = {_rg135} — RELATED entity: "
                         f"does not describe the analysis entity "
                         f"({_an135}). Metadata not evidentiary for the "
                         f"analysed perimeter."))
                    _rmm.bold = True
                    _rmm.font.size = Pt(9)

                # B.1.3.10 (run 5 : override au CSV, ABSENT du CR) — le rendu
                # vivait DANS `if _reg_mm135:` ; quand le registre retenu = la
                # cible (cas SAIN post-3.9), le mismatch tombe et l'override
                # disparaissait avec lui. Le conflit porte sur le CLIC vs la
                # cible du brief : affiché dès que le fingerprint le porte.
                try:
                    _fpz = _fp_root(result)
                    _fp_oc = str(_fpz.get("override_conflict") or "")
                    _fpz_reason = str(_fpz.get("choice_reason") or "")
                    _fpz_related = ("related" in _fpz_reason.lower()
                                    and _fpz_reason.upper().startswith("RESOLVED_"))
                    _oc_txt = _fp_oc
                    if not _oc_txt and _fpz_related:
                        # B.1.3.12 — résolution réussie : rendre la trace lisible
                        # (candidat clic / cible registre / raison).
                        import re as _re16
                        _clk16 = (_re16.search(r"«\s*(.+?)\s*»", _fpz_reason))
                        _clk16 = _clk16.group(1) if _clk16 else ""
                        _rwz16 = _rel_wording14(
                            str(_fpz.get("chosen_entity") or ""), _clk16, _dl)
                        _oc_txt = (
                            (f"Registry target: {_fpz.get('chosen_entity','')}. "
                             f"Resolution: {_fpz_reason} · {_rwz16}.")
                            if _dl == "en" else
                            (f"Cible registre : {_fpz.get('chosen_entity','')}. "
                             f"Résolution : {_fpz_reason} · {_rwz16}.")
                        )
                    if _oc_txt:
                        _poc = doc.add_paragraph()
                        _roc = _poc.add_run(_oc_txt)
                        _roc.italic = True
                        _roc.font.size = Pt(9)
                except Exception:
                    pass

                _facts_table_b = doc.add_table(rows=1, cols=5)
                _facts_table_b.style = "Light Grid Accent 1"
                _hdr_b = _facts_table_b.rows[0].cells
                for i, h in enumerate(_headers):
                    _hdr_b[i].text = h
                for cell in _hdr_b:
                    for p in cell.paragraphs:
                        for r in p.runs:
                            r.bold = True
                            r.font.size = Pt(9)
                for fact in _identity_facts[:15]:
                    from utils.financial_facts_render import loc_fact_status as _lfs
                    from utils.financial_facts_table import _localize_metric_label as _lml, _localize_source as _lsrc
                    _row = _facts_table_b.add_row().cells
                    # M.5.10.5 — statut + label + source localisés (fuite « FAIT |
                    # Statut société (CH) » dans le CR EN, audit dossier anglophone coté M.5.10.4)
                    _row[0].text = (f"{'⚠ ' if _reg_mm135 else ''}"
                                    f"{fact.get('icon', '')} {_lfs(fact.get('status', ''), _dl)}"
                                    + ((" — entité liée" if _dl == "fr"
                                        else " — RELATED") if _reg_mm135 else ""))
                    _row[1].text = _lml(str(fact.get("label", "")), _dl)[:50]
                    _row[2].text = str(fact.get("value", ""))[:35]
                    _row[3].text = _lsrc(str(fact.get("source", "")), _dl)[:50]
                    _row[4].text = str(fact.get("page", "—"))
                    for cell in _row:
                        for p in cell.paragraphs:
                            for r in p.runs:
                                r.font.size = Pt(8)

            # B.1.3.8 — INSTRUMENTATION : le run 3.7 affichait 3 faits brief
            # sur 4 extraits (le H1 1.03bn absent de la table visible) sans
            # que la racine soit reproductible offline. Le CSV dira désormais
            # combien la table PORTE vs combien la Zone A REND.
            try:
                _n_brief_table = sum(
                    1 for f in _facts
                    if str((f.get("source") if isinstance(f, dict) else "") or "").strip().lower() == "brief"
                    or (f.get("brief_only") if isinstance(f, dict) else False))
                _n_brief_rendered = sum(
                    1 for f in _financial_facts[:25]
                    if str((f.get("source") if isinstance(f, dict) else "") or "").strip().lower() == "brief"
                    or (f.get("brief_only") if isinstance(f, dict) else False))
                result.setdefault("diagnostics_attempts", []).append({
                    "role": "brief_facts_render", "provider": "internal",
                    "model": "docx_zone_a_b138",
                    "status": ("OK" if _n_brief_rendered >= _n_brief_table else "PARTIAL"),
                    "error": (f"in_table={_n_brief_table} rendered={_n_brief_rendered}"
                              # B.1.3.12 — composition EXACTE des brief facts
                              # vus par la Zone A : le prochain CSV dira qui
                              # manque et pourquoi, au lieu de conjecturer.
                              + " · brief=[" + ";".join(
                                  f"{(f.get('label') if isinstance(f, dict) else '?')}"
                                  f"@{(f.get('period') if isinstance(f, dict) else '') or '—'}"
                                  for f in _financial_facts[:25]
                                  if isinstance(f, dict)
                                  and (str(f.get("source") or "").strip().lower() == "brief"
                                       or f.get("brief_only"))) + "]"),
                })
            except Exception:
                pass

            # ── Zone C — Hypothèses narratives (agents) — B.1.3.5 ──────
            # La frontière fait-de-preuve / hypothèse-d'analyse est rendue
            # VISIBLE : rien n'est supprimé, tout est étiqueté.
            if _narrative_facts:
                doc.add_paragraph("")
                _zone_c_title = doc.add_paragraph()
                _zone_c_run = _zone_c_title.add_run(
                    "C. Hypothèses narratives (agents) — à vérifier, non probantes"
                    if _dl == "fr"
                    else "C. Narrative hypotheses (agents) — to verify, non-evidentiary")
                _zone_c_run.bold = True
                _zone_c_run.italic = True
                _zone_c_run.font.size = Pt(10)

                _facts_table_c = doc.add_table(rows=1, cols=5)
                _facts_table_c.style = "Light Grid Accent 1"
                _hdr_c = _facts_table_c.rows[0].cells
                for i, h in enumerate(_headers):
                    _hdr_c[i].text = h
                for cell in _hdr_c:
                    for p in cell.paragraphs:
                        for r in p.runs:
                            r.bold = True
                            r.font.size = Pt(9)
                for fact in _narrative_facts[:10]:
                    from utils.financial_facts_render import loc_fact_status as _lfs
                    from utils.financial_facts_table import _localize_metric_label as _lml, _localize_source as _lsrc
                    _row = _facts_table_c.add_row().cells
                    _row[0].text = f"{fact.get('icon', '')} {_lfs(fact.get('status', ''), _dl)}"
                    _row[1].text = _lml(str(fact.get("label", "")), _dl)[:60]
                    _row[2].text = str(fact.get("value", ""))[:35]
                    _row[3].text = _lsrc(str(fact.get("source", "")), _dl)[:50]
                    _row[4].text = str(fact.get("page", "—"))
                    for cell in _row:
                        for p in cell.paragraphs:
                            for r in p.runs:
                                r.font.size = Pt(8)

            _total_displayed = (
                min(len(_financial_facts), 25) + min(len(_identity_facts), 15)
                + min(len(_narrative_facts), 10)
            )
            if len(_facts) > _total_displayed:
                _more_para = doc.add_paragraph()
                _more_run = _more_para.add_run(
                    f"… {len(_facts) - _total_displayed} fait(s) supplémentaire(s) non affiché(s)."
                    if _dl == "fr" else
                    f"… {len(_facts) - _total_displayed} additional fact(s) not shown."
                )
                _more_run.italic = True
                _more_run.font.size = Pt(8)

            # ── B.1.3 — ⚡ Tensions entre chiffres (conflits couche B.1) ───
            try:
                _b1cf = (result.get("b1_proof_layer") or {}).get("conflicts") or []
                _b1cf_msgs = []
                for _c in _b1cf[:6]:
                    _m = (_c.get("user_visible_message")
                          if isinstance(_c, dict) else str(_c))
                    if _m:
                        _b1cf_msgs.append(str(_m))
                if _b1cf_msgs:
                    _cf_title = doc.add_paragraph()
                    _cf_tr = _cf_title.add_run(
                        "⚡ Tensions entre chiffres (à arbitrer)"
                        if _dl == "fr" else
                        "⚡ Tensions between figures (to arbitrate)")
                    _cf_tr.bold = True
                    _cf_tr.font.size = Pt(10)
                    _cf_tr.font.color.rgb = RGBColor(0xB0, 0x5A, 0x00)
                    for _m in _b1cf_msgs:
                        _cfp = doc.add_paragraph()
                        _cfr = _cfp.add_run(f"• {_m}")
                        _cfr.font.size = Pt(8.5)
            except Exception:
                pass
            doc.add_paragraph("")
    except Exception as _ft_err:
        import logging as _lg
        _lg.getLogger("codir_ia").warning(
            f"docx financial_facts_table render failed: {type(_ft_err).__name__}: {_ft_err}"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Patch v16.5.72.9 (round 24 ChatGPT) — Section diagnostic Couche 1
    # Affiche dans le DOCX le statut de la table de faits financiers
    # (ok/failed/skipped), l'erreur métier éventuelle et les durées des
    # operations lourdes. L'opérateur peut maintenant voir D'UN COUP D'OEIL pourquoi
    # une session "réussie" produit une table vide (cas où une exception était
    # silencieusement masquee par un crash du logger en versions precedentes).
    # ─────────────────────────────────────────────────────────────────────────
    try:
        from docx.shared import Pt, RGBColor
        _fft_status = result.get("financial_facts_table_status", "skipped")
        _fft_error = result.get("financial_facts_table_error")
        _fft_n = result.get("financial_facts_table_n_facts")
        _fft_dur = result.get("financial_facts_table_duration_ms", 0)
        _fft_degraded = result.get("financial_facts_table_degraded")
        _fft_estim = result.get("financial_facts_table_estim_filings", 0)
        _perf = result.get("perf_timings_ms", {}) or {}
        _cache_stats = result.get("parse_cache_stats") or {}
        _ef_pp = ((result.get("extraction_fidelity") or {}).get("per_page")
                  if isinstance(result.get("extraction_fidelity"), dict) else None)

        # F.6.10 (audit dossier réseau de soins F.6.9) — GARDE DE PREUVE : le badge ne peut pas
        # afficher « OK » quand la fidélité per-page est faible. L'utilisateur cible
        # (consultant / DAF de transition) se fierait à un « OK » trompeur. On
        # bascule en DEGRADED dès que RIEN n'est confirmé à la page citée, ou que
        # ≥ 50 % des faits sont sans citation / page indispo / absents.
        _pp_ev = _ef_pp if isinstance(_ef_pp, dict) else {}
        _conf_pp = _pp_ev.get("verbatim_on_page", 0) + _pp_ev.get("normalized_on_page", 0)
        _weak_pp = (_pp_ev.get("page_unavailable", 0) + _pp_ev.get("no_citation", 0)
                    + _pp_ev.get("not_found_on_cited_page", 0))
        _tot_pp = _conf_pp + _weak_pp
        try:
            from patches.extraction_fidelity import is_evidence_weak as _is_ev_weak
            _evidence_weak = _is_ev_weak(_pp_ev)
        except Exception:
            _evidence_weak = bool(_tot_pp) and (_conf_pp == 0 or (_weak_pp / _tot_pp) >= 0.5)
        _is_degraded = bool(_fft_degraded) or _evidence_weak

        # N'afficher la section que si on a quelque chose à dire
        if _fft_status != "skipped" or _fft_error or _perf or _cache_stats or _ef_pp:
            _diag_title = doc.add_paragraph()
            _diag_run = _diag_title.add_run(
                "Diagnostic — Couche 1 (Source Traceability) & performance"
                if _dl == "fr"
                else "Diagnostic — Layer 1 (Source Traceability) & performance"
            )
            _diag_run.bold = True
            _diag_run.italic = True
            _diag_run.font.size = Pt(10)

            # Statut
            _status_para = doc.add_paragraph()
            _status_run = _status_para.add_run(
                f"Statut Couche 1 : "
                if _dl == "fr" else f"Layer 1 status: "
            )
            _status_run.bold = True
            _status_run.font.size = Pt(9)

            _status_value_text = ""
            if _fft_status == "ok" and _is_degraded:
                if _evidence_weak:
                    _status_value_text = (
                        f"⚠ DEGRADED ({_fft_n if _fft_n is not None else 0} faits — "
                        f"preuve faible : {_conf_pp} confirmé(s) à la page citée sur "
                        f"{_tot_pp} ({_weak_pp} sans citation / page indispo / absent) ; "
                        f"à fiabiliser avant tout usage, {_fft_dur} ms)"
                        if _dl == "fr" else
                        f"⚠ DEGRADED ({_fft_n if _fft_n is not None else 0} facts — "
                        f"weak evidence: {_conf_pp}/{_tot_pp} confirmed on cited page "
                        f"({_weak_pp} uncited / page n/a / absent); verify before any "
                        f"use, {_fft_dur} ms)"
                    )
                else:
                    _status_value_text = (
                        f"⚠ DEGRADED ({_fft_n if _fft_n is not None else 0} faits — "
                        f"0 métrique financière déterministe ; {_fft_estim} fait(s) "
                        f"ESTIM-FILINGS promus du narratif, à confirmer, {_fft_dur} ms)"
                        if _dl == "fr" else
                        f"⚠ DEGRADED ({_fft_n if _fft_n is not None else 0} facts — "
                        f"0 deterministic financial metric; {_fft_estim} ESTIM-FILINGS "
                        f"fact(s) promoted from narrative, to confirm, {_fft_dur} ms)"
                    )
            elif _fft_status == "ok":
                _status_value_text = (
                    f"✓ OK ({_fft_n if _fft_n is not None else 0} faits, {_fft_dur} ms)"
                    if _dl == "fr" else
                    f"✓ OK ({_fft_n if _fft_n is not None else 0} facts, {_fft_dur} ms)"
                )
            elif _fft_status == "failed":
                _status_value_text = (f"✗ ÉCHEC ({_fft_dur} ms)" if _dl == "fr"
                                      else f"✗ FAILED ({_fft_dur} ms)")
            else:
                _status_value_text = "— SKIPPED"
            _status_value_run = _status_para.add_run(_status_value_text)
            _status_value_run.font.size = Pt(9)
            if _fft_status == "failed":
                _status_value_run.font.color.rgb = RGBColor(0xCC, 0x00, 0x00)
            elif _fft_status == "ok" and _is_degraded:
                _status_value_run.font.color.rgb = RGBColor(0xB0, 0x5A, 0x00)  # orange
            elif _fft_status == "ok":
                _status_value_run.font.color.rgb = RGBColor(0x00, 0x88, 0x00)

            # F.6.6.1 — Fidélité PER-PAGE (rend VISIBLE le signal décisif du run).
            _ef = result.get("extraction_fidelity") or {}
            _pp = _ef.get("per_page") if isinstance(_ef, dict) else None
            if isinstance(_pp, dict) and _pp:
                _pp_para = doc.add_paragraph()
                _pp_lbl = _pp_para.add_run(
                    "Fidélité per-page (valeur à la page citée) : "
                    if _dl == "fr" else "Per-page fidelity (value on cited page): ")
                _pp_lbl.bold = True
                _pp_lbl.font.size = Pt(9)
                _ok_pp = _pp.get("verbatim_on_page", 0) + _pp.get("normalized_on_page", 0)
                _bad_pp = _pp.get("not_found_on_cited_page", 0)
                _txt = ((f"✓ {_ok_pp} à la page citée · "
                         f"{_pp.get('page_unavailable', 0)} page indispo · "
                         f"{_pp.get('no_citation', 0)} sans citation")
                        if _dl == "fr" else
                        (f"✓ {_ok_pp} on cited page · "
                         f"{_pp.get('page_unavailable', 0)} page unavailable · "
                         f"{_pp.get('no_citation', 0)} without citation"))
                _pp_run = _pp_para.add_run(_txt)
                _pp_run.font.size = Pt(9)
                # not_found_on_cited_page = signal fort → en rouge si présent
                _bad_run = _pp_para.add_run(
                    ((f" · ⚠ {_bad_pp} ABSENTE de la page citée" if _dl == "fr"
                      else f" · ⚠ {_bad_pp} MISSING from cited page") if _bad_pp else ""))
                _bad_run.font.size = Pt(9)
                _bad_run.bold = True
                if _bad_pp:
                    _bad_run.font.color.rgb = RGBColor(0xCC, 0x00, 0x00)

            # Erreur métier si applicable
            if _fft_error:
                _err_para = doc.add_paragraph()
                _err_run = _err_para.add_run(
                    f"Erreur métier : " if _dl == "fr" else f"Business error: "
                )
                _err_run.bold = True
                _err_run.font.size = Pt(9)
                _err_msg = _err_para.add_run(_fft_error[:300])
                _err_msg.font.size = Pt(9)
                _err_msg.italic = True
                _err_msg.font.color.rgb = RGBColor(0xCC, 0x00, 0x00)

            # Durées des opérations lourdes
            if _perf:
                _perf_para = doc.add_paragraph()
                _perf_run = _perf_para.add_run(
                    f"Durées (ms) : " if _dl == "fr" else f"Durations (ms): "
                )
                _perf_run.bold = True
                _perf_run.font.size = Pt(9)
                _perf_text = "  ".join(
                    f"{k}={v}" for k, v in _perf.items() if v is not None
                )
                _perf_value = _perf_para.add_run(_perf_text)
                _perf_value.font.size = Pt(9)

            # Stats cache parsing PJ
            if _cache_stats and isinstance(_cache_stats, dict):
                _cache_para = doc.add_paragraph()
                _cache_run = _cache_para.add_run(
                    f"Cache parsing PJ : " if _dl == "fr" else f"Attachment parse cache: "
                )
                _cache_run.bold = True
                _cache_run.font.size = Pt(9)
                _cache_text = (
                    f"hits={_cache_stats.get('hits', 0)}  "
                    f"misses={_cache_stats.get('misses', 0)}  "
                    f"size={_cache_stats.get('size', 0)}  "
                    f"evictions={_cache_stats.get('evictions', 0)}"
                )
                _cache_value = _cache_para.add_run(_cache_text)
                _cache_value.font.size = Pt(9)

            # F.6.8 (audit) — Mode source EXPLICITE (lève l'ambiguïté Pappers/GLEIF).
            _src_mode = str(result.get("source_mode", "OPEN") or "OPEN").upper()
            _sm_para = doc.add_paragraph()
            _sm_lbl = _sm_para.add_run("Mode source : " if _dl == "fr" else "Source mode: ")
            _sm_lbl.bold = True
            _sm_lbl.font.size = Pt(9)
            if _src_mode == "ATTACHMENTS_ONLY":
                _sm_txt = ("ATTACHMENTS_ONLY — sources externes désactivées "
                           "(Pappers / GLEIF / SEC / web non appelés)"
                           if _dl == "fr" else
                           "ATTACHMENTS_ONLY — external sources disabled "
                           "(Pappers / GLEIF / SEC / web not called)")
            else:
                # M6-A3.2 — label honnête : « OPEN » ≠ fetch web de résultats.
                # Identité registre + connaissance générale du modèle, mais AUCUN
                # rafraîchissement live de données financières / investor relations.
                _sm_txt = ("OPEN — registre d'identité interrogé (Companies House / "
                           "Pappers / GLEIF) + connaissance générale du modèle ; "
                           "AUCUN rafraîchissement live de résultats financiers / IR"
                           if _dl == "fr" else
                           "OPEN — identity registry queried (Companies House / "
                           "Pappers / GLEIF) + model general knowledge; NO live "
                           "financial-results / investor-relations refresh")
            _sm_run = _sm_para.add_run(_sm_txt)
            _sm_run.font.size = Pt(9)

            # Patch v16.5.72.10 (retex terrain) — Routage intelligent sources externes
            # F.6.8 — en ATTACHMENTS_ONLY, ne PAS afficher « Pappers+GLEIF » (trompeur) :
            # le routage est sans objet puisque les sources externes sont coupées.
            _routing_summary = result.get("id_routing_summary")
            if _routing_summary and _src_mode != "ATTACHMENTS_ONLY":
                _route_para = doc.add_paragraph()
                _route_run = _route_para.add_run(
                    f"Routage sources externes : " if _dl == "fr"
                    else f"External sources routing: "
                )
                _route_run.bold = True
                _route_run.font.size = Pt(9)
                _route_value = _route_para.add_run(str(_routing_summary))
                _route_value.font.size = Pt(9)

            doc.add_paragraph("")
    except Exception as _diag_err:
        import logging as _lg
        _lg.getLogger("codir_ia").warning(
            f"docx diagnostic section render failed: {type(_diag_err).__name__}: {_diag_err}"
        )
    # ─────────────────────────────────────────────────────────────────────────
    # ─────────────────────────────────────────────────────────────────────────

    # ── v16.5.67 L1 — Bloc Philosophie en tête du CR (avant integrity) ────────
    # Pivot Lucidité : rappeler explicitement que CoDIR-IA n'est pas un décideur.
    try:
        from docx.shared import Pt, RGBColor
        _philo_title = doc.add_paragraph()
        _philo_run = _philo_title.add_run(
            "🎯 CoDIR-IA — Accélérateur de lucidité, pas générateur de réponses"
            if _dl == "fr" else
            "🎯 CoDIR-IA — Lucidity Accelerator, not Answer Generator"
        )
        _philo_run.bold = True
        _philo_run.font.size = Pt(11)
        _philo_run.font.color.rgb = RGBColor(0x2E, 0x4A, 0x7F)  # bleu foncé

        _philo_body = doc.add_paragraph()
        _philo_body_run = _philo_body.add_run(
            "CoDIR-IA n'est pas un décideur. Il structure votre réflexion, "
            "produit des hypothèses qualifiées, rend visibles vos zones de doute, "
            "et propose des arbitrages à examiner. La décision reste humaine, "
            "responsable, contextualisée. Vous êtes le filtre.\n"
            "Vocabulaire du produit : RECOMMANDÉ · À ARBITRER · À INVESTIGUER · "
            "À VÉRIFIER. CoDIR-IA ne présente pas ses orientations comme des décisions humaines prises."
            if _dl == "fr" else
            "CoDIR-IA is not a decision-maker. It structures your thinking, "
            "produces qualified hypotheses, makes your zones of doubt visible, "
            "and proposes arbitrations to examine. The decision remains human, "
            "accountable, contextualized. You are the filter.\n"
            "Product vocabulary: RECOMMENDED · TO BE ARBITRATED · TO INVESTIGATE · "
            "TO VERIFY. CoDIR-IA does not present orientations as final human decisions."
        )
        _philo_body_run.italic = True
        _philo_body_run.font.size = Pt(9)
        doc.add_paragraph("")
    except Exception as _philo_err:
        _lg.getLogger("codir_ia").warning(
            f"Philosophy block insertion failed: {type(_philo_err).__name__}: {_philo_err}"
        )
    # ─────────────────────────────────────────────────────────────────────────

    # ── Note épistémique bilingue ─────────────────────────────────────────────
    _ep_note = doc.add_paragraph()
    _ep_note.style = doc.styles["Normal"]
    _ep_run = _ep_note.add_run(DL("integrity_title", _dl) + " " + DL("integrity_body", _dl))
    _ep_run.italic = True
    _ep_run.font.size = __import__("docx.shared", fromlist=["Pt"]).Pt(8)
    doc.add_paragraph("")

    # ── Brief initial ────────────────────────────────────────────────────────
    # v16.5.67.9 — strip ASCII banner du brief avant rendu DOCX
    # La bannière ╔══╗║ANALYSE - CoDIR IA║╚══╝ est utile côté UI Streamlit
    # mais pollue visuellement le livrable Word. On la retire uniquement pour
    # le rendu DOCX ; le brief reste intact dans result["inputs"]["brief"]
    # pour les logs, la trace audit et le prompt LLM.
    _raw_brief = result.get("inputs", {}).get("brief", "") or ""
    _brief_for_docx = _strip_brief_ascii_banner(_raw_brief)
    _summary62431_cr = _docx_add_summary(doc, _dl)     # v62.13.9.4.31 — sommaire du compte rendu
    _docx_add_section(doc, DL("initial_brief", _dl), _brief_for_docx)

    # B.1.3.56 Gate 11 — autorité temporelle unique des renderers DOCX.
    # Le résultat peut être régénéré plusieurs jours après la session : toutes
    # les surfaces narratives (y compris la synthèse exécutive) sont gouvernées
    # par la date d'ANALYSE demandée lorsqu'un scénario rétrospectif existe,
    # sinon par la date réelle du run — jamais par date.today(). Sans autorité
    # structurée, aucune notion de retard n'est fabriquée.
    try:
        from patches.cr_blocks_docx import _result_run_date as _result_run_date_docx
        _docx_run_date = _result_run_date_docx(result)
    except Exception:
        _docx_run_date = None
    outputs = dict(result.get("outputs", {}) or {})
    # B.1.3.61 — défense renderer pour les résultats anciens/importés : seules
    # les SORTIES agents sont assainies. Le brief utilisateur, rendu juste au-dessus,
    # reste strictement intact même s'il traite de prompt, JSON ou markdown.
    try:
        from utils.agent_leakage_gate import sanitize_agent_outputs as _sanitize_docx_outputs61
        outputs, _docx_leakage_report61 = _sanitize_docx_outputs61(outputs)
    except Exception:
        _docx_leakage_report61 = {"sentences_removed": 0, "fields_touched": 0}
    if _docx_run_date is not None:
        try:
            from patches.temporal_gate import flag_past_action_dates_in_text as _flag_docx_outputs
            for _out_key, _out_value in list(outputs.items()):
                if isinstance(_out_value, str) and _out_value:
                    outputs[_out_key] = _flag_docx_outputs(
                        _out_value, _docx_run_date, _dl)
        except Exception:
            # La sortie originale reste disponible ; le renderer ne doit pas
            # inventer un statut depuis l'horloge pour « compenser » l'échec.
            pass
    sc_meta = result.get("meta", {}) or {}
    commercial_txt = outputs.get("commercial", "") or ""

    # ── v16.5.28 — SYNTHÈSE EXÉCUTIVE DG (1 page) ────────────────────────────
    # Bloc en tête de document : construit depuis synthèse_décisions + CEO
    # Objectif : permettre au DG de lire 1 page max avant le détail
    synthese_dg_txt = outputs.get("synthese_decisions", "") or ""
    ceo_txt_for_dg  = outputs.get("direction_generale", "") or ""
    if _has_meaningful_text(synthese_dg_txt) or _has_meaningful_text(ceo_txt_for_dg):
        # v16.5.28 — rendu ligne par ligne avec strip markdown (fix affichage brut ### et **)
        def _strip_md(line: str) -> str:
            """Supprime les marqueurs markdown pour rendu DOCX propre."""
            import re as _re
            line = _re.sub(r"^#{1,4}\s*", "", line)          # ### titres
            line = _re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", line)  # **bold** ou *italic*
            line = _re.sub(r"\\([\[\]*_])", r"\1", line)      # échappements résiduels
            line = _re.sub(r"^[-–*]\s+", "", line)             # puces résiduelles
            return line.strip()

        doc.add_heading(_docx_number_section(doc, DL("exec_summary", _dl), 1), level=1)
        doc.add_paragraph("")

        _dg_lines_raw = []
        for _src in [synthese_dg_txt, ceo_txt_for_dg]:
            for _line in _src.splitlines():
                _l = _line.strip()
                if _l and len(_l) > 8:
                    _dg_lines_raw.append(_l)
                if len(_dg_lines_raw) >= 40:
                    break
            if len(_dg_lines_raw) >= 40:
                break

        # Rendu ligne par ligne : heading si commence par #, bullet si commence par - ou •
        _BULLET_PAT = __import__("re").compile(r"^[-–•*✓]\s+|^\d+[.)]\s+")
        for _raw_line in _dg_lines_raw[:35]:
            _clean = _strip_md(_raw_line)
            if not _clean:
                continue
            if _BULLET_PAT.match(_raw_line) or _BULLET_PAT.match(_clean):
                try:
                    doc.add_paragraph(_clean, style="List Bullet")
                except Exception:
                    doc.add_paragraph(f"• {_clean}")
            else:
                doc.add_paragraph(_clean)

        doc.add_paragraph("")
        doc.add_paragraph("─" * 80)
        doc.add_paragraph(DL("details_below", _dl))
        doc.add_paragraph("")

    # ── Synthèse commerciale en tête si pertinente ───────────────────────────
    if _has_meaningful_text(commercial_txt):
        doc.add_heading(_docx_number_section(doc, DL("commercial_key", _dl), 1), level=1)
        doc.add_paragraph(
            ("This section is included because CoDIR IA detected material commercial drivers." if _dl=="en" else "Ce volet est intégré car CoDIR IA a détecté des enjeux ou leviers commerciaux suffisamment matériels pour le dossier.")
        )
        for item in _extract_key_lines(commercial_txt, max_items=6):
            try:
                doc.add_paragraph(item, style="List Bullet")
            except Exception:
                doc.add_paragraph(f"• {item}")

    # ── 8 rôles du pipeline ──────────────────────────────────────────────────
    _docx_add_section(doc, DL("strategy", _dl), outputs.get("strategie", ""))
    _docx_add_section(doc, DL("brief_codir", _dl), outputs.get("brief_codir", ""))
    _docx_add_section(doc, DL("marketing", _dl), outputs.get("marketing", ""))
    _docx_add_section(
        doc,
        DL("finance", _dl),
        _finance_safe(outputs.get("finance", ""), result=result, lang=_dl),
    )

    # Supply Chain — nettoyage JSON/audit avant injection DOCX
    supply_chain_txt = outputs.get("supply_chain", "") or ""
    sc_status = sc_meta.get("supply_chain_status", "")
    sc_clean = _get_sc_display_text(supply_chain_txt, sc_status)
    if _has_meaningful_text(sc_clean) or sc_status == "unavailable":
        _docx_add_section(
            doc,
            DL("sc", _dl),
            sc_clean,
        )
        # Avertissement si Gemini challenge indisponible
        sc_warning = sc_meta.get("supply_chain_warning", "")
        if sc_warning and "gemini" in sc_warning.lower():
            doc.add_paragraph(
                f"ℹ️  Note : {sc_warning}",
            )

    # v16.5.28 — Nettoyer les marqueurs internes de prompt avant injection DOCX
    def _clean_commercial_for_docx(txt: str) -> str:
        import re as _re
        txt = _re.sub(r"^###?\s*ZONE\s*[12]\s*.*$", "", txt, flags=_re.IGNORECASE | _re.MULTILINE)
        txt = _re.sub(r"^###?\s*NOTE\s*NARRATIVE\s*.*$", "", txt, flags=_re.IGNORECASE | _re.MULTILINE)
        txt = _re.sub(r"^---JSON_START---.*?---JSON_END---", "", txt, flags=_re.DOTALL)
        txt = _re.sub(r"^---AUDIT_START---.*?---AUDIT_END---", "", txt, flags=_re.DOTALL)
        txt = _re.sub(r"\n{3,}", "\n\n", txt)
        return txt.strip()

    _commercial_clean = _clean_commercial_for_docx(commercial_txt) if _has_meaningful_text(commercial_txt) else ""
    _docx_add_section(
        doc,
        DL("commercial", _dl),
        _commercial_clean if _commercial_clean
        else DL("no_commercial", _dl),
    )
    _docx_add_section(
        doc,
        DL("synthesis", _dl),
        outputs.get("synthese_decisions", ""),
    )
    _docx_add_section(
        doc,
        DL("dg", _dl),
        outputs.get("direction_generale", ""),
    )

    # v62.12 — quantified scenarios are not executive claims.  They are kept
    # in an explicit Word-only appendix with the validation work required;
    # neither the Working Deck nor the executive summary consumes this block.
    _scenario_appendix6212 = result.get("scenario_appendix") or []
    # v62.13.9.4.50 — décision Robin du 30/09/2026 : sous la doctrine « tout livrer, tout signaler en place », rien
    # n'est plus écarté des surfaces exécutives ; cette annexe ne faisait plus que dupliquer des passages déjà
    # signalés dans le corps (« Remplacement exécutif : … » y devenait faux). Elle ne sort plus dans le Word ; les
    # scénarios restent au registre probatoire (JSON/CSV) et au diagnostic du paquet.
    try:
        from utils.v62136_fr_path_maintenance import _status_mode as _stm50
        if _stm50(result):
            _scenario_appendix6212 = []
    except Exception:
        pass
    if _scenario_appendix6212:
        _scn_title6212 = (
            "Annex — Unvalidated quantified working scenarios"
            if _dl == "en" else
            "Annexe — Scénarios chiffrés de travail non validés"
        )
        doc.add_heading(_docx_number_section(doc, _scn_title6212, 1), level=1)
        doc.add_paragraph(
            ("These hypotheses were withheld from executive surfaces. They are not part of the verified baseline and require the validation work stated below."
             if _dl == "en" else
             "Ces hypothèses ont été écartées des surfaces exécutives. Elles ne font pas partie de la baseline vérifiée et requièrent les travaux de validation indiqués ci-dessous."))
        for _scn6212 in _scenario_appendix6212:
            _sid6212 = str(_scn6212.get("scenario_id") or "SCN")
            _sec6212 = str(_scn6212.get("section") or "unknown")
            _orig6212 = str(_scn6212.get("original_hypothesis") or "")
            _repl6212 = str(_scn6212.get("qualitative_replacement") or "")
            _req6212 = str(_scn6212.get("required_validation") or "")
            _p6212 = doc.add_paragraph(style="List Bullet")
            _r6212 = _p6212.add_run(f"{_sid6212} · {_sec6212} — ")
            _r6212.bold = True
            _p6212.add_run(_orig6212)
            doc.add_paragraph(
                (("Executive replacement: " if _dl == "en" else "Remplacement exécutif : ")
                 + _repl6212))
            doc.add_paragraph(
                (("Validation required: " if _dl == "en" else "Validation requise : ")
                 + _req6212))

    # ─── v17.1.0-B2.3-F.3 — Rendu du registre d'actions + ledger marché ───────
    # Rend VISIBLES dans le CR les artefacts structurés de F.2 (auparavant
    # uniquement dans le dict résultat). Logique sortie dans un module dédié
    # (testable hors-ligne). Fail-open : aucun échec ne bloque l'export.
    try:
        from patches.cr_blocks_docx import render_register_and_ledger as _render_reg
        _render_reg(doc, result, lang=_dl)
    except Exception:
        pass

    # Cycle C — vue MULTI-SÉANCES (actions ouvertes + frise CoDIR→CoDIR + écarts
    # de décision) rendue dans le CR si un historique de dossier existe. Fail-open.
    try:
        from patches.cr_blocks_docx import render_codir_history as _render_hist
        _render_hist(doc, result, lang=_dl)
    except Exception:
        pass

    # ─── v16.5.75.5 — Footer AI Act article 50(4) ────────────────────────────
    # Article 50(4) du Règlement (UE) 2024/1689 : les sorties générées par un
    # système d'IA doivent être identifiées comme telles. Applicable au plus
    # tard le 2 août 2026 (article 113 + article 50). CoDIR IA implémente cette
    # obligation par anticipation.
    # ─────────────────────────────────────────────────────────────────────────
    try:
        from docx.shared import Pt as _Pt
        for section in doc.sections:
            footer = section.footer
            # Vide le footer existant pour éviter accumulation à chaque export
            for p in list(footer.paragraphs):
                p.clear()
            ftext_fr = (
                "Document de travail assisté par IA — revue humaine requise avant toute décision. "
                "Marquage de transparence au titre du Règlement (UE) 2024/1689 ; "
                "AI Act art. 50(4) si applicable à l’usage ou à la diffusion considérés."
            )
            ftext_en = (
                "AI-assisted working document — human review required before any decision. "
                "Transparency marking under Regulation (EU) 2024/1689; "
                "AI Act art. 50(4) where applicable to the intended use or publication."
            )
            ftext = ftext_fr if _dl == "fr" else ftext_en
            fp = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
            run = fp.add_run(ftext)
            run.italic = True
            run.font.size = _Pt(7)
    except Exception:
        # Tolérance : si la pose du footer échoue, on ne bloque pas l'export
        pass
    # ─────────────────────────────────────────────────────────────────────────

    # B.1.3.10 (audit #5) — la table BRUTE ouvrait le CR (p.1) :
    # déplacée en ANNEXE, après le corps exécutif. Rien n'est
    # supprimé — la preuve d'audit reste intégrale, à sa place.
    # ── M6-B couche 1 — table de faits financiers EXTRAITS (brut, non audité).
    # Rend visible ce que l'extracteur déterministe remonte réellement des pièces
    # (label/valeur/période/périmètre/source/page/confiance). NON couplée au score
    # à ce stade : preuve de terrain pour valider la qualité d'extraction.
    _ff = result.get("financial_facts") or []
    # B.1.3.14 (run 7 : annexe absente du binaire) — la clé racine est VIDE
    # selon les branches moteur ; l'annexe d'audit se replie sur les ROWS
    # de la table (toujours présentes).
    if not _ff:
        _ff = [dict(r) for r in (((result.get("financial_facts_table")
                                   or {}).get("facts")) or []) if r]
    _ffcov = result.get("financial_facts_coverage") or {}
    # B.1.3.18 (run 10 ; dette UX runs 8/9/10) — la validation des entités
    # est rendue en ANNEXE depuis sa clé dédiée : le diagnostic regroupé ne
    # coupe plus le corps métier du CR.
    _ev18 = str(outputs.get("entity_validation_annex", "") or "").strip()
    if _ev18:
        _snap_ev = _sm_snap(doc)
        doc.add_heading("Annexe — Validation des entités (diagnostic)"
                        if _dl == "fr" else
                        "Annex — Entity validation (diagnostic)", level=2)
        _evp = doc.add_paragraph()
        _evr = _evp.add_run(
            _ev18.lstrip("> ").replace("> ", "").replace("**", ""))
        _evr.font.size = Pt(9)
        _evr.font.italic = True
        _sm_mark(doc, _snap_ev)                     # annexe de validation d'entités = contenu de l'outil
    if _ff:
        _snap_ff = _sm_snap(doc)
        doc.add_heading("\u2063Faits financiers extraits (brut — M6-B couche 1)"
                        if _dl == "fr" else
                        ("Annex — Extracted financial facts (raw — M6-B layer 1)" if _dl == "en" else "Annexe — Faits financiers extraits (brut — couche 1 M6-B)"), level=2)
        try:
            from patches.financial_extractor import (facts_table_rows as _ftr,
                                                     FinancialFact as _FF)
            _rows = _ftr([_FF(**_d) for _d in _ff])
        except Exception:
            _rows = []
        if not _rows and _ff:
            # B.1.3.14 — repli : rows-DICTS construits directement depuis
            # les dicts de la table (la reconstruction _FF peut refuser des
            # clés de rows) — l'audit brut sort toujours, mêmes clés que le
            # rendu aval (label/kind/value/period/perimetre/source/
            # confidence/source_line).
            _rows = [{"label": str(_d.get("label", "")),
                      "kind": str(_d.get("status", "")),
                      "value": str(_d.get("value", "")),
                      "period": str(_d.get("period", "") or "—"),
                      "scope": str(_d.get("scope", "")),
                      "source": str(_d.get("source", "")),
                      "confidence": str(_d.get("confidence", "")),
                      "raw_line": ""}
                     for _d in _ff]
        if _rows:
            # ── B.1.3.20 (P2-H, runs dossier industriel + dossier agroalimentaire) — la couche BRUTE
            # s'aligne sur la couche gouvernée : enums de périmètre localisés
            # (plus de « CONSOLIDATED »/« UNKNOWN » dans un CR FR) et statut
            # ⛔ répercuté (l'annexe montrait « FAIT 95 % » là où la Zone A
            # disait ⛔ HORS PÉRIMÈTRE).
            _scope_fr20 = {
                "CONSOLIDATED": "Consolidé groupe",
                "SOCIAL_STANDALONE": "Social (standalone)",
                "HOLDING": "Holding (mère)",
                "SEGMENT": "Segment",
                "MARKET": "Marché (benchmark)",
                "UNKNOWN": "Indéterminé", "": "Indéterminé",
            }
            _pm_by_key20 = {}
            _blk_by_key42 = {}
            # _blockers_by_key41 compatibility marker (tests / audit lineage).
            try:
                for _d in (_ff or []):
                    _k42 = (str(_d.get("label", "")),
                            str(_d.get("value", "")),
                            str(_d.get("period", "") or "—"),
                            str(_d.get("source", "")))
                    _pm_by_key20[_k42] = str(
                        _d.get("perimeter_match", "") or "")
                    _blk_by_key42[_k42] = str(
                        _d.get("board_safe_blockers", "") or "")
            except Exception:
                _pm_by_key20 = {}
                _blk_by_key42 = {}
            _cols = (["Indicateur", "Type", "Valeur", "Période", "Périmètre", "Source", "Confiance", "Extrait"]
                     if _dl == "fr" else
                     ["Metric", "Type", "Value", "Period", "Scope", "Source", "Confidence", "Source line"])
            _t = doc.add_table(rows=1, cols=len(_cols))
            try:
                _t.style = "Light Grid Accent 1"
            except Exception:
                pass
            for _i, _c in enumerate(_cols):
                _t.rows[0].cells[_i].text = _c
            for _r in _rows[:60]:
                _cl = _t.add_row().cells
                _kind20 = _r.get("kind", "")
                _k42 = (str(_r.get("label", "")),
                        str(_r.get("value", "")),
                        str(_r.get("period", "") or "—"),
                        str(_r.get("source", "")))
                _pm20 = _pm_by_key20.get(_k42, "")
                _blk42 = _blk_by_key42.get(_k42, "").lower()
                if "pairing_suspect" in _blk42:
                    from patches.finance_shaper import pairing_suspect_status
                    _kind20 = pairing_suspect_status(_dl)
                    if _pm20 == "MISMATCH":
                        _kind20 += (" · HORS PÉRIMÈTRE" if _dl == "fr"
                                    else " · OUT OF PERIMETER")
                elif _pm20 == "MISMATCH":
                    _kind20 = ("⛔ HORS PÉRIMÈTRE — exclu du score"
                               if _dl == "fr" else
                               "⛔ OUT OF PERIMETER — excluded from score")
                _scope20 = str(_r.get("scope", "") or "")
                if _dl == "fr":
                    _scope20 = _scope_fr20.get(_scope20.upper(), _scope20)
                _cl[0].text = _r["label"];   _cl[1].text = _kind20
                _cl[2].text = _r["value"];   _cl[3].text = _r["period"]
                _cl[4].text = _scope20;      _cl[5].text = _r["source"]
                _cl[6].text = _r["confidence"]; _cl[7].text = _r.get("raw_line", "")
        _miss = _ffcov.get("core_missing") or []
        # B.1.3.8 (harmonisation l.44 vs l.112) — « missing IN ATTACHMENTS »
        # est vrai mais prête à confusion quand la métrique est couverte
        # par le BRIEF : on le dit dans la même phrase.
        _brief_cov_lbls = []
        try:
            _ffx = (result.get("financial_facts_table") or {}).get("facts") or []
            _blbls = {str((f.get("label") if isinstance(f, dict) else getattr(f, "label", "")) or "")
                      for f in _ffx
                      if str((f.get("source") if isinstance(f, dict) else getattr(f, "source_doc", "")) or "").strip().lower() == "brief"
                      or (f.get("brief_only") if isinstance(f, dict) else getattr(f, "brief_only", False))}
            _brief_cov_lbls = sorted(m for m in _miss
                                     if any(m.lower() in b.lower() or b.lower() in m.lower()
                                            for b in _blbls))
        except Exception:
            _brief_cov_lbls = []
        if _miss:
            _mp = doc.add_paragraph()
            _mr = _mp.add_run((("⚠ Faits cœur manquants dans les pièces : "
                                if _dl == "fr" else "⚠ Core facts missing in attachments: ")
            # (suffixe brief-only ajouté après composition — B.1.3.8)
                               + ", ".join(_miss)
                               + ((" — " + ", ".join(_brief_cov_lbls)
                                   + (" présents via le brief uniquement (non board-safe)"
                                      if _dl == "fr" else
                                      " present from brief only (not board-safe)"))
                                  if _brief_cov_lbls else "")))
            _mr.italic = True
            _mr.font.size = __import__("docx").shared.Pt(8)

        _sm_mark(doc, _snap_ff)                     # annexe des faits financiers extraits = contenu de l'outil
    # Cohérence UI (champ "Société analysée") ↔ Pappers (primary_name)
    # Si l'utilisateur a saisi un nom et que Pappers a résolu autre chose,
    # émettre une alerte visible en haut de page.
    # Patch v16.5.72.11 (retex terrain + ChatGPT round 25) — Utilise le module
    # name_matcher pour normalisation robuste : strip accents, articles,
    # formes juridiques. Avant : "Française de l'énergie" vs "LA FRANCAISE
    # DE L'ENERGIE" déclenchait FAUX flag (accents pas strippés).
    import re as _re_ui
    _brief_txt    = result.get("inputs", {}).get("brief", "") or ""
    _m_soc        = _re_ui.search(r"SOCI[ÉE]T[ÉE]\s*:\s*([^\n]+)", _brief_txt, _re_ui.IGNORECASE)
    _ui_soc_name  = (_m_soc.group(1).strip() if _m_soc else "")
    _pap_name     = (_pap_log or {}).get("primary_name", "") if _pap_log else ""
    if _ui_soc_name and _pap_name:
        try:
            from utils.name_matcher import is_match as _name_is_match
            _matches = _name_is_match(_ui_soc_name, _pap_name, threshold=0.5)
        except ImportError:
            # Fallback : ancienne logique si module pas chargé
            def _norm(s):
                s = _re_ui.sub(r"[^a-zA-Zà-ÿ0-9]+", " ", s).lower().strip()
                for _f in ("sasu ", "sas ", "sa ", "sarl ", "eurl ",
                           "sci ", "scp ", "selarl ", "selas ", "snc "):
                    if s.startswith(_f): s = s[len(_f):]
                return s
            _ui_n = _norm(_ui_soc_name)
            _pap_n = _norm(_pap_name)
            _ui_words = set(w for w in _ui_n.split() if len(w) >= 3)
            _pap_words = set(w for w in _pap_n.split() if len(w) >= 3)
            _matches = bool(_ui_words and _pap_words and (_ui_words & _pap_words))

        if not _matches:
            try:
                from utils.name_matcher import is_probable_typo as _is_typo
                _typo = _is_typo(_ui_soc_name, _pap_name)
            except Exception:
                _typo = False
            _warn_para = doc.add_paragraph()
            _siren_u = (_pap_log or {}).get('siren_used', '?')
            if _typo:
                # v17.1-B2.3-C — faute de frappe probable + SIREN résolu →
                # note légère, pas d'alerte lourde « mauvaise entité ».
                _warn_run = _warn_para.add_run(
                    f"⚠ Orthographe : champ UI « {_ui_soc_name} » ≈ fiche Pappers "
                    f"« {_pap_name} » (SIREN {_siren_u}) — faute de frappe probable ; "
                    "l'entité a été résolue correctement via le SIREN."
                    if _dl == "fr" else
                    f"⚠ Spelling: UI field \"{_ui_soc_name}\" ≈ Pappers card "
                    f"\"{_pap_name}\" (SIREN {_siren_u}) — likely typo; entity "
                    "correctly resolved via SIREN."
                )
                _warn_run.italic = True
                _warn_run.font.size = __import__("docx").shared.Pt(8)
            else:
                _warn_run  = _warn_para.add_run(
                    "⚠ CANDIDAT REGISTRE REJETÉ : "
                    f"fiche Pappers « {_pap_name} » (SIREN {_siren_u}) ≠ entité "
                    f"d'analyse « {_ui_soc_name} ». Les données de ce registre ont été "
                    "EXCLUES des analyses et de la table de faits (quarantine M6-A2.1). "
                    "Pour les inclure, confirmez le bon identifiant."
                    if _dl == "fr" else
                    "⚠ REGISTRY CANDIDATE REJECTED: "
                    f"Pappers card \"{_pap_name}\" (SIREN {_siren_u}) != analysis entity "
                    f"\"{_ui_soc_name}\". This registry data was EXCLUDED from the "
                    "analyses and the facts table (M6-A2.1 quarantine). "
                    "To include it, confirm the correct identifier."
                )
                _warn_run.bold = True
                _warn_run.font.size = __import__("docx").shared.Pt(9)

    bio = io.BytesIO()
    try:
        from patches.entity_scope import lock_entity_in_docx_headings as _lock_docx
        _es2 = result.get("entity_scope") or {}
        _an = (_es2.get("analysis_entity") or "").strip()
        _rg = (_es2.get("registry_entity") or "").strip()
        if _an and _rg:
            _lock_docx(doc, _an, _rg)   # titres métier → entité d'analyse (filet)
    except Exception:
        pass
    try:
        from patches.lexicon_gate import sanitize_docx as _san_docx, LEXICON_STATS as _lx
        _n = _san_docx(doc)   # neutralise tout résidu VALIDATED/DECIDED/BLOCKING
        _lx["status"] = "ok"
        import logging as _lg
        _lg.getLogger("codir.lexicon").info("lexicon gate (docx): %d remplacements", _n)
    except Exception as _e:
        try:
            from patches.lexicon_gate import LEXICON_STATS as _lx
            _lx["status"] = "failed"
        except Exception:
            pass
        import logging as _lg
        _lg.getLogger("codir.lexicon").warning("lexicon gate docx KO: %s", _e)
    # ── Lot CONFORMITÉ — AI Act art. 50(2) : marquage machine-readable
    # du contenu généré, posé JUSTE AVANT la sérialisation pour couvrir
    # tous les chemins d'export sans exception. Ne peut pas faire échouer
    # l'export (absorbé par le module).
    try:
        from utils.ai_content_marking import apply_marking as _mark50
        from version import PUBLISHER as _PUB
        _mark50(doc, version=str(VERSION_LABEL or ""),
                provider=_PUB)
    except Exception:
        pass
    _docx_fill_summary(_summary62431_cr)              # v62.13.9.4.31 — sommaire du compte rendu
    try:                                              # v62.13.9.4.33 — carte rubrique du CR → « CR §N — nom » pour les renvois du deck
        _cr_idx33 = list(getattr(doc, _SECTION_INDEX_KEY, []) or [])
        result["report_section_index"] = _cr_idx33
        if isinstance(_raw_result62138, dict):
            _raw_result62138["report_section_index"] = _cr_idx33
    except Exception:
        pass
    try:                                              # v62.13.9.4.23 — mise en page efficace (≤ 30 pages visées)
        from utils.docx_layout import compact_layout as _cl62423
        _cl62423(doc)
    except Exception:
        pass
    doc.save(bio)
    bio.seek(0)
    _docx_payload62122 = bio.read()
    # v62.13.7 (H2a) — la réparation sémantique court AVANT le contrôle numérique
    # final : les octets livrés sont EXACTEMENT ceux que le dernier audit a vus.
    # v62.13.9.4.10 — chemin unique : la production et les rejeux passent
    # par la même fonction de contrôle final.
    _docx_payload62122 = apply_final_docx_control(
        _docx_payload62122, result, lang=_dl, raw_result=_raw_result62138)
    return _docx_payload62122  # v62.13.7 (H2a) — aucun octet n'est modifié après le contrôle final

def _test_provider(provider: str, secrets: Secrets, settings: Settings):
    # Minimal "ping" test. max_output_tokens=1..5 (per bon de commande).
    prompt = "Ping"
    system = "Réponds uniquement par OK."
    kwargs = {"temperature": 0.0, "max_tokens": 5}
    apply_secrets_to_env(secrets, override=True)

    if provider == "openai":
        from providers.openai_provider import call_openai
        out = call_openai(prompt, system=system, model=settings.openai_model_id, **kwargs)
    elif provider == "anthropic":
        from providers.claude_provider import call_claude
        out = call_claude(prompt, system=system, model=settings.anthropic_model_id, **kwargs)
    elif provider == "google":
        from providers.gemini_provider import call_gemini
        out = call_gemini(prompt, system=system, model=settings.google_model_id, **kwargs)
    elif provider == "mistral":
        from providers.mistral_provider import call_mistral
        out = call_mistral(prompt, system=system, model=settings.mistral_model_id, **kwargs)
    elif provider == "perplexity":
        from providers.perplexity_provider import call_perplexity
        out = call_perplexity(prompt, system=system, model=settings.perplexity_model_id, **kwargs)
    elif provider == "grok":
        from providers.grok_provider import call_grok
        out = call_grok(prompt, system=system, model=settings.grok_model_id, **kwargs)
    else:
        raise ValueError("provider inconnu")

    if isinstance(out, dict) and out.get("error"):
        raise RuntimeError(out.get("output") or f"Test {provider} en erreur")
    return out


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
        resp = call_openai(prompt, system=system, model=settings.openai_model_id, temperature=0.0, max_tokens=6000)
        return resp.get("output","")
    if provider == "google":
        from providers.gemini_provider import call_gemini
        resp = call_gemini(prompt, system=system, model=settings.google_model_id, temperature=0.0, max_tokens=6000)
        return resp.get("output","")
    if provider == "anthropic":
        from providers.claude_provider import call_claude
        resp = call_claude(prompt, system=system, model=settings.anthropic_model_id, temperature=0.0, max_tokens=6000)
        return resp.get("output","")
    from providers.mistral_provider import call_mistral
    resp = call_mistral(prompt, system=system, model=settings.mistral_model_id, temperature=0.0, max_tokens=6000)
    return resp.get("output","")

def generate_pptx(report_text: str, settings: Settings,
                  prudence: "dict|None" = None) -> bytes:
    # B1.3.60-L1/S3 — le deck aussi part d'un texte sans dialogue interne.
    try:
        from utils.agent_leakage_gate import strip_agent_leakage as _sal2
        report_text, _ = _sal2(report_text)
    except Exception:
        pass
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
    ts = _mc_stamp("%Y%m%d-%H%M%S")
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
                resp = call_openai(prompt, system=system, model=settings.openai_model_id, temperature=0.0, max_tokens=6000)
                txt = resp.get("output", "")
            elif prov == "google":
                from providers.gemini_provider import call_gemini
                resp = call_gemini(prompt, system=system, model=settings.google_model_id, temperature=0.0, max_tokens=6000)
                txt = resp.get("output", "")
            elif prov == "anthropic":
                from providers.claude_provider import call_claude
                resp = call_claude(prompt, system=system, model=settings.anthropic_model_id, temperature=0.0, max_tokens=6000)
                txt = resp.get("output", "")
            else:
                from providers.mistral_provider import call_mistral
                resp = call_mistral(prompt, system=system, model=settings.mistral_model_id, temperature=0.0, max_tokens=6000)
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

            # v17.1-B2.3-C — deck scrub : marque « [À INSTRUIRE] » les chiffres
            # commerciaux/synergies non sourcés (présentation honnête, append-only).
            try:
                from patches.pipeline_guards_b23 import scrub_deck as _scrub_deck
                # v17.1.0-B2.3-F.3 — genre-aware : ne pas raboter un deck non-M&A.
                _deck_mode = "GO_NOGO"
                try:
                    from patches.agenda_genre import detect_agenda_genre as _dag
                    _deck_mode = _dag(report_text or "").decision_mode
                except Exception:
                    _deck_mode = "GO_NOGO"
                _scrub_deck(payload, decision_mode=_deck_mode)
            except Exception:
                pass

            out_path = str(Path("outputs") / f"CoDIR_IA_Synthese_{_mc_stamp('%Y-%m-%d')}.pptx")
            create_pptx_from_deck(payload, out_path,
                                  lang=getattr(settings, "output_language", "fr"),
                                  prudence=prudence)

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
        raise RuntimeError("Cannot generate PPTX: no API key available. Open ⚙️ Settings and enter at least one key (OpenAI, Anthropic, Google/Gemini or Mistral)." if _lang=="en" else "Impossible de générer le PPTX : aucune clé API disponible. Ouvre ⚙️ Configuration et saisis au moins une clé (OpenAI, Anthropic, Google/Gemini ou Mistral).")

    # Special handling for DNS errors
    msg = str(last_err)
    if "getaddrinfo failed" in msg or "Name or service not known" in msg:
        raise RuntimeError(
            ("Network/DNS error generating PPTX. Check connection and firewall. Details: outputs/pptx_attempts_{ts}.json. Last error: {last_err}" if _lang=="en" else f"Impossible de générer le PPTX : problème réseau/DNS. Détails : outputs/pptx_attempts_{ts}.json. Dernière erreur: {last_err}")
        )

    raise RuntimeError(f"Cannot generate PPTX. Details in outputs/pptx_attempts_{ts}.json. Last error: {last_err}" if _lang=="en" else f"Impossible de générer le PPTX. Détails dans outputs/pptx_attempts_{ts}.json. Dernière erreur: {last_err}")


# -------------------------
# Pages
# -------------------------
if page == "codir":
    st.subheader(T("session_header", _lang))

    # v16.5.74 — Item #2 : Reset des pièces jointes sur "Nouvelle session".
    # Bug observé v16.5.73 : st.file_uploader conservait les fichiers entre
    # sessions, obligeant l'utilisateur à les supprimer un par un (risque
    # d'oubli + inconfort). Solution standard Streamlit : passer une clé
    # dynamique au file_uploader et l'incrémenter au reset → Streamlit
    # re-instancie le widget en interne = fichiers vidés automatiquement.
    if "uploader_key" not in st.session_state:
        st.session_state["uploader_key"] = 0

    cols_top = st.columns([1,1,1])
    with cols_top[0]:
        if st.button(T("new_session_btn", _lang), help=T("new_session_help", _lang)):
            st.session_state["last_result"] = None
            st.session_state["last_docx"] = None
            st.session_state["last_pptx"] = None
            st.session_state["last_docx_error"] = None   # v62.13.9.4.31.1
            st.session_state["last_meta"] = {}
            # v16.5.74 — Vider les pièces jointes en incrémentant la clé.
            st.session_state["uploader_key"] = int(st.session_state.get("uploader_key", 0)) + 1
            # Correctif TCR (P1) — la date d'analyse structurée est un
            # réglage DE SESSION : « Nouvelle session » la remet à
            # vide/live (aucune ancienne date ne survit).
            try:
                settings.analysis_as_of_date = ""
            except Exception:
                pass
            st.session_state["codir_analysis_as_of_date"] = ""
            # Correctif TCR-v4 (P1) — « Nouvelle session » purge TOUT
            # l'état temporel transitoire : pending d'adoption A5,
            # message d'adoption — aucune ancienne date ne peut être
            # réinjectée par un rerun interrompu.
            for _tk in ("codir_analysis_as_of_date_pending",
                        "codir_analysis_as_of_adopted_msg",
                        "codir_temporal_candidate_declined_fp"):
                st.session_state.pop(_tk, None)
            brief_ui.reset_brief_state()  # v16.5.39
            st.toast("✅ Session réinitialisée — pièces jointes vidées", icon="🆕")
            st.rerun()
    with cols_top[1]:
        export_pptx = st.checkbox(T("gen_pptx", _lang), value=True, key="codir_export_pptx")   # 9.4.59 — clé : restituable
        # M.5.10.11 — case « run propre » : ignore l'historique multi-séances
        # pour ce run (équivalent UI de CODIR_IGNORE_HISTORY). Posée au render
        # afin d'être effective au lancement (Streamlit ré-exécute le script).
        _clean_run = st.checkbox(T("clean_run", _lang), value=False, key="codir_clean_run",
                                 help=T("clean_run_help", _lang))
        import os as _os_cr
        if _clean_run:
            _os_cr.environ["CODIR_IGNORE_HISTORY"] = "1"
        else:
            _os_cr.environ.pop("CODIR_IGNORE_HISTORY", None)
    with cols_top[2]:
        st.caption(f"{T('attachment_limits', _lang)}: {settings.attachments_max_files} / {settings.attachments_max_total_mb} Mo")

    # ═══ Correctif TCR-v8 (verdict v7, P0-3) — PRÉ-GATE TEMPOREL, avant
    # le RENDU du brief : le rendu peut enrichir depuis des registres
    # externes (auto-complétion Pappers d'un SIREN). Aucun effet externe
    # ne doit précéder l'autorité temporelle. On résout donc le contexte
    # sur l'ENTRÉE UTILISATEUR BRUTE (lecture pure, sans widget) et on
    # n'ouvre la porte que si la policy est ouverte. Panne ⇒ FERMÉ.
    # ═══ Correctif TCR-v10 (verdict v9, P0-3) — CAPTURE UNIQUE puis
    # RÉSOLUTION UNIQUE. `TemporalControlInput` est capturé ICI, une seule
    # fois, avant tout rendu ; il est résolu ICI, une seule fois, en UN
    # `TemporalContext` ; c'est ce même objet qui descend jusqu'au moteur.
    # Il n'existe plus de second call-site de `resolve_temporal_context`
    # dans l'application : le préflight final LIE le brief assemblé à ce
    # contexte (`bind_assembled_brief`) au lieu de le reconstruire.
    _tci19 = None
    _tctx19_app = None
    try:
        from patches.temporal_context import (resolve_temporal_context
                                              as _rtc_gate19)
        _tci19 = brief_ui.current_temporal_control_input(
            _lang, settings=settings)
        # L'entrée de la résolution est la PHOTOGRAPHIE COURANTE : zone de
        # contrôle en tête (règle A3, positionnelle) puis matière narrative
        # courante — la couverture de l'ancien préflight final, sans son
        # second passage. La date structurée vient du TCI, plus de Settings :
        # une seule autorité structurée par rerun.
        # Correctif TCR-v12 (verdict v11, P0-B1) — l'OBJET TYPÉ est
        # transmis tel quel : le runtime ne re-sérialise plus rien, donc
        # aucune frontière de canal n'est reconstituée à partir d'un
        # texte. La sérialisation ne subsiste que pour les appelants
        # historiques par chaîne.
        _tctx19_app = _rtc_gate19(
            temporal_input=_tci19,
            input_fingerprint=_tci19.input_fingerprint,
            declined_candidate_fingerprint=str(st.session_state.get(
                "codir_temporal_candidate_declined_fp") or ""))
        # Porte ouverte SEULEMENT sur autorité établie ET saisie réelle
        # (une entrée vide n'autorise aucun enrichissement externe).
        st.session_state["_temporal_gate_open"] = bool(
            not _tctx19_app.is_blocked and not _tci19.is_empty())
    except Exception:
        # FAIL-CLOSED : la panne du producteur ferme la porte ET produit un
        # contexte BLOCKED_ERROR réel — jamais un contexte absent.
        st.session_state["_temporal_gate_open"] = False
        try:
            from patches.temporal_context import (blocked_error_context
                                                  as _bec_gate19)
            _tctx19_app = _bec_gate19(
                "", str(getattr(settings, "analysis_as_of_date", "") or ""),
                reason="temporal control input capture failure")
        except Exception:
            _tctx19_app = None

    # v16.5.39 — Dual-mode brief: Terrain + Équipe
    # Correctif TCR-v10 — le brief est ASSEMBLÉ DEPUIS la photographie déjà
    # résolue (control_lines / business_text), jamais reparsé.
    brief = brief_ui.render(_lang, temporal_control_input=_tci19)
    try:   # 9.4.61 — recette 9.4.60 : brief collé dans le gabarit déjà présent (deux horizons, deux « Messages sensibles »)
        _b61 = str(brief or "")
        # 9.4.62 — alerte seulement pour une VRAIE imbrication (sections de l'ordre du jour en double) ; un brief
        # complet collé est désormais utilisé tel quel et ne la déclenche plus
        import re as _re62
        _sec62 = _re62.findall(r"(?im)^\s*▌?\s*([B-E])\s*·\s*\w", _b61)
        if any(_sec62.count(x) >= 2 for x in set(_sec62)):
            st.warning("Le brief contient deux fois le gabarit de l'ordre du jour : le texte a sans doute été collé sans "
                       "effacer le gabarit présent. Videz le champ (Ctrl+A puis Suppr) puis collez à nouveau."
                       if _lang != "en" else
                       "The brief contains the agenda template twice: the text was probably pasted without clearing the "
                       "template already present. Clear the field (Ctrl+A then Delete) and paste again.")
    except Exception:
        pass

    # v62.9 — CANONICALISATION AVANT LIAISON TEMPORELLE.
    # Le brief rendu peut contenir un horizon structuré trop court (ex. « + 1 an »)
    # alors que le texte utilisateur demande explicitement « plan stratégique à 2 ans ».
    # Cette réconciliation doit impérativement précéder bind_assembled_brief(), afin que
    # le TemporalContext soit signé sur le texte EXACT transmis au moteur. Le moteur
    # réapplique la même fonction de manière idempotente pour les appels bibliothèque.
    _horizon_reconciliation_app = None
    try:
        from patches.strategic_horizon import (
            reconcile_strategic_horizon as _rsh629_app)
        brief, _horizon_reconciliation_app = _rsh629_app(
            brief,
            # v62.13.9.4.40 — L'HORIZON PART DE LA DATE D'ANALYSE, PAS DE LA DATE DE GÉNÉRATION.
            # Dossier réel du 21/09/2026, en mode rétrospectif : « 24 mois » donnait une fin
            # comptée depuis la date de génération. La borne est analyse + 24 mois ; en mode
            # courant les deux dates coïncident et rien ne change.
            run_date=(getattr(getattr(_tctx19_app, "policy", None), "analysis_date", None)
                      or getattr(_tctx19_app, "analysis_date", None)
                      or getattr(_tctx19_app, "run_date", None)),
            lang=_lang,
        )
    except Exception as _horizon_app_err:
        # La canonicalisation d'horizon n'est pas une autorité de date : en cas
        # d'échec, on conserve le brief rendu et on laisse le diagnostic moteur
        # expliciter l'incident sans falsifier la date d'analyse.
        _horizon_reconciliation_app = None
        try:
            log_event(logger, "warning", "app",
                      f"strategic horizon canonicalization failed: "
                      f"{type(_horizon_app_err).__name__}: {_horizon_app_err}")
        except Exception:
            pass

    # F.5.2 (Cycle C) — champ « Libellé de dossier » : mode NORMAL de regroupement
    # multi-séances. Écrit dans settings.dossier_label avant le run ; vide → repli
    # société + genre. Fail-open (module isolé, Streamlit paresseux).
    try:
        from patches.codir_pilot_ui import render_dossier_label_field as _render_dlf
        _render_dlf(settings, _lang)
    except Exception:
        pass
    # Temporal Core Refactor (A5) — date d'analyse STRUCTURÉE (rang 1)
    # + rappel visible de la valeur active, avant le lancement du run.
    try:
        from patches.codir_pilot_ui import (render_analysis_date_field
                                            as _render_adf)
        _render_adf(settings, _lang)
    except Exception:
        pass

    # Fallback: si le brief est vide (mode selection affiché), bloquer le lancement
    _brief_ready = bool(brief and brief.strip())
    # F.6.7.1 (P1, audit ChatGPT) — doctrine « pièces jointes exclusivement » : ne
    # préparer AUCUNE résolution externe côté UI (preview Pappers, cible cross-
    # juridiction) quand le brief l'exige. Le moteur coupe déjà au run ; on aligne l'UI.
    try:
        from patches.mission_governance import detect_source_mode as _dsm_ui
        _attach_only_ui = bool(brief) and (_dsm_ui(brief) == "ATTACHMENTS_ONLY")
    except Exception:
        _attach_only_ui = False
    _attach_only_ui_msg = ("🔒 Mode pièces jointes uniquement — enrichissement externe "
                           "(Pappers / cross-juridiction) désactivé, aucun appel préparé."
                           if _lang == "fr" else
                           "🔒 Attachments-only mode — external enrichment "
                           "(Pappers / cross-jurisdiction) disabled, no call prepared.")

    uploaded = st.file_uploader(
        T("attachments_full", _lang),
        # M.5.8 (FIX1) — PAS de filtrage MIME frontend : sous Windows, Streamlit
        # rejette des .docx/.pptx VALIDES quand l'OS remonte les MIME hérités
        # (application/msword, application/vnd.ms-powerpoint). On accepte tout au
        # frontend et on valide par EXTENSION côté serveur (ci-dessous).
        accept_multiple_files=True,
        key=f"file_uploader_{st.session_state['uploader_key']}",  # v16.5.74 — reset
    )
    # M.5.9 (FIX A) — validation par le CONTENU (magic bytes), pas l'extension :
    # gère les noms courts Windows 8.3 (.docx→~1.DOC) qui faisaient rejeter à tort
    # des OOXML valides (run « Sans pièce jointe »). PK-zip = moderne (accepté,
    # nom normalisé) ; OLE2 = vrai legacy (rejeté).
    if uploaded:
        try:
            from patches.upload_format_guard import validate_uploads as _validate_uploads
            _accepted, _rejected = _validate_uploads(uploaded, _lang)
            for _nm, _why in _rejected:
                st.warning((f"« {_nm} » ignoré : {_why}." if _lang == "fr"
                            else f"'{_nm}' skipped: {_why}."))
            uploaded = _accepted
        except Exception:
            pass  # fail-open : en cas d'erreur du garde, on garde les fichiers tels quels


    attachments_block = ""
    attachments_meta = {"files": 0, "tokens_est": 0, "truncated": False}
    # Since v16.5.70 — Initialisation hors du if uploaded pour éviter NameError
    # quand aucun PDF n'est uploadé (run sans pièces jointes).
    financial_statements_block = ""
    financial_statements_bundles = []
    if uploaded:
        # v16.5.75.5 — Wizard run trigger : on n'exécute PLUS le parsing ni
        # le scan financier ici. Avant v75.4, chaque rerun Streamlit (touche
        # Entrée, modification de champ, etc.) re-déclenchait tout le pipeline
        # parsing + extraction FS, soit 30-60s perdues à chaque interaction
        # sur un dossier riche (cas FDE = 20 PJ). Depuis v75.4, le pipeline
        # ne se déclenche QU'AU CLIC sur "Lancer", via _prepare_documents_for_run().
        # Ici on se contente d'afficher des warnings volume et un compteur.
        total_uploaded_bytes = sum(len(f.getvalue()) for f in uploaded)
        if len(uploaded) > settings.attachments_max_files:
            st.warning(f"{len(uploaded) - settings.attachments_max_files} {T('attach_over_limit', _lang)}")
        if total_uploaded_bytes > int(settings.attachments_max_total_mb * 1024 * 1024):
            st.warning(T("attach_over_size", _lang))
        n_files = min(len(uploaded), settings.attachments_max_files)
        size_mb = total_uploaded_bytes / (1024 * 1024)
        st.caption(
            (f"📎 {n_files} pièce(s) jointe(s) chargée(s) — {size_mb:.1f} Mo "
             f"(le scan détaillé démarre au clic sur « Lancer »)")
            if _lang == "fr" else
            (f"📎 {n_files} attachment(s) loaded — {size_mb:.1f} MB "
             f"(detailed scan starts when you click 'Launch')")
        )

    # Si aucune clé LLM → avertissement bloquant (Pappers seul ne suffit pas)
    if not has_any_key():
        st.warning(T("no_key_runtime", _lang))
    elif needs_llm:
        st.warning(
            "⚠️ " + ("Aucune clé LLM configurée — configurez OpenAI, Claude ou Gemini pour lancer une session."
                     if _lang == "fr" else
                     "No LLM key configured — configure OpenAI, Claude or Gemini to run a session.")
        )

    # ── Bandeau pré-lancement Pappers — v16.5.52 ────────────────────────────────
    if _brief_ready:
        try:
            from utils.pappers_tool import preview_pappers_detection
            # Patch v16.5.72.11 (retex terrain sur lenteur saisie écran A) — Cache UI
            # mémoire pour preview_pappers_detection. Sans cache, Streamlit
            # ré-exécute tout le script à chaque keystroke → preview_pappers_detection
            # appelé 5-10 fois pour taper "dossier réseau de soins" complet → API Pappers
            # déclenchée à chaque caractère = bottleneck.
            # Solution : keyer par hash MD5 du brief, cache hit instantané sur
            # rerun avec brief identique.
            import hashlib as _hl
            _brief_hash = _hl.md5(brief.encode("utf-8", errors="ignore")).hexdigest()
            _cache_key = f"_pappers_preview_cache_{_brief_hash}"
            if _attach_only_ui:
                # F.6.7.1 (P1) — pas de preview Pappers (pas d'appel externe préparé).
                _pprev = {"active": False, "source_mode_skip": True}
                st.info(_attach_only_ui_msg)
            elif _cache_key in st.session_state:
                _pprev = st.session_state[_cache_key]
            else:
                _pprev = preview_pappers_detection(brief, _lang)
                st.session_state[_cache_key] = _pprev
                # Limite mémoire : ne pas garder plus de 20 entrées de cache
                _all_preview_keys = [
                    k for k in st.session_state.keys()
                    if k.startswith("_pappers_preview_cache_")
                ]
                if len(_all_preview_keys) > 20:
                    # Supprimer la plus ancienne (FIFO simple)
                    del st.session_state[_all_preview_keys[0]]
            if _pprev.get("active"):
                _skip_key    = "pappers_skip_session"
                _confirm_key = "pappers_confirmed_entity"
                if _skip_key    not in st.session_state: st.session_state[_skip_key]    = False
                if _confirm_key not in st.session_state: st.session_state[_confirm_key] = ""
                # ── B.1.3.20 (P1-D, run dossier industriel) — INVALIDATION du confirmé au
                # changement de brief. Racine reproduite : « Actionnariat »
                # confirmé sur un état de BROUILLON restait collé en session et
                # primait (999) sur le champ Société du brief FINAL — aucun
                # reset n'existait. Le confirmé est signé par la clé de preview
                # du brief courant ; brief différent → confirmé caduc.
                from patches.pappers_confirm_guard import confirm_is_stale as _cis20
                if _cis20(st.session_state.get(_confirm_key, ""),
                          st.session_state.get("_pappers_confirm_sig"), _cache_key):
                    st.session_state[_confirm_key] = ""
                    st.session_state.pop("_pappers_confirm_sig", None)

                _siren_d   = _pprev.get("siren_direct")
                _cands     = _pprev.get("candidates") or []
                _pmethod   = _pprev.get("preview_method", "local_heuristic")
                _has_claude= _pprev.get("has_claude", False)

                # ── Bandeau principal ─────────────────────────────────────────
                if _siren_d:
                    st.success(T("pappers_banner_siren", _lang).format(siren=_siren_d))
                    st.caption(T("pappers_caption_siren", _lang))
                elif _cands:
                    try:   # 9.4.61 — le bandeau nomme les registres officiels applicables (SEC EDGAR, GLEIF, Pappers…)
                        from utils.registry_sources61 import registry_banner as _rb61
                        st.info(_rb61(brief, ", ".join(_cands[:3]), _lang))
                    except Exception:
                        st.info(T("pappers_banner_name", _lang).format(names=", ".join(_cands[:3])))
                    st.caption(T("pappers_caption_heuristic", _lang) if _has_claude
                               else T("pappers_caption_fallback", _lang))
                else:
                    st.warning(T("pappers_banner_none", _lang))
                    st.caption(T("pappers_caption_none", _lang))

                # ── UI de confirmation — R1 : uniquement si confiance < SIREN_DIRECT ──
                if not _siren_d and not st.session_state[_skip_key]:
                    with st.expander(T("confirm_hint", _lang), expanded=bool(_cands)):
                        _primary_cand = _cands[0] if _cands else ""
                        _secondary_cands = _cands[1:] if len(_cands) > 1 else []

                        # Multi-entités : sélecteur entité principale — R2 Option C
                        if len(_cands) > 1:
                            st.caption(T("multi_secondary_note", _lang)
                                       .format(names=", ".join(_cands[1:])))
                            _prim_options = _cands + [T("confirm_option_manual", _lang)]
                            _prim_sel = st.selectbox(
                                T("multi_primary_label", _lang),
                                _prim_options,
                                index=0,
                                key="pappers_primary_sel"
                            )
                            if _prim_sel == T("confirm_option_manual", _lang):
                                _primary_cand = ""
                            else:
                                _primary_cand = _prim_sel

                        # Options : confirmer / saisir SIREN / désactiver
                        _opt_confirm = T("confirm_option_keep", _lang).format(
                            name=_primary_cand or "?")
                        _opt_manual  = T("confirm_option_manual", _lang)
                        _opt_none    = T("confirm_option_none", _lang)
                        _options     = ([_opt_confirm] if _primary_cand else []) + [_opt_manual, _opt_none]
                        # v16.5.62 — index=None : AUCUNE option n'est pré-sélectionnée
                        # au render. Correction d'un bug où la première option
                        # ("Garder <candidat bruité>") était silencieusement cochée
                        # et écrivait pappers_confirmed_entity sans action utilisateur,
                        # court-circuitant le SIREN du champ UI.
                        _choice = st.radio(
                            T("confirm_primary", _lang),
                            _options, horizontal=True,
                            index=None,
                            key="pappers_confirm_radio"
                        )
                        # N'écrire dans session_state QUE si l'utilisateur a cliqué
                        if _choice == _opt_confirm:
                            st.session_state[_confirm_key] = _primary_cand
                            st.session_state["_pappers_confirm_sig"] = _cache_key  # B.1.3.20 P1-D
                        elif _choice == _opt_manual:
                            _manual = st.text_input(
                                T("confirm_siren_label", _lang),
                                placeholder=T("confirm_siren_ph", _lang),
                                max_chars=9, key="pappers_manual_siren"
                            )
                            _siren_clean = "".join(x for x in (_manual or "") if x.isdigit())[:9]
                            if _siren_clean and len(_siren_clean) != 9:
                                st.error("⚠ SIREN invalide — exactement 9 chiffres requis"
                                         if _lang == "fr" else
                                         "⚠ Invalid SIREN — exactly 9 digits required")
                                _siren_clean = ""
                            st.session_state[_confirm_key] = _siren_clean
                            st.session_state["_pappers_confirm_sig"] = _cache_key  # B.1.3.20 P1-D
                        elif _choice == _opt_none:
                            st.session_state[_skip_key]    = True
                            st.session_state[_confirm_key] = ""
                        # else: _choice is None — utilisateur n'a pas cliqué,
                        # on laisse la priorité au SIREN extrait du brief (si présent)

                # ── Checkbox désactivation ────────────────────────────────────
                st.session_state[_skip_key] = st.checkbox(
                    T("pappers_banner_skip", _lang),
                    value=st.session_state[_skip_key],
                    key="pappers_skip_cb"
                )
        except Exception:
            pass
    # ─────────────────────────────────────────────────────────────────────────

    # ── Since v16.5.69 — UI "Confirmer la cible cross-juridiction" ─────────
    # Cette UI tourne IN-DÉPEN-DAM-MENT du bandeau Pappers ci-dessus.
    # Pappers reste piloté par sa propre UI si SIREN détecté.
    # Cette UI s'occupe de GLEIF / SEC EDGAR / Companies House (et activera
    # OpenSanctions au moment du run, sur l'entité confirmée).
    _tpre19_blocked = False  # préflight temporel — recalculé ci-dessous
    _tpre19_ctx = None       # instance UNIQUE transmise au moteur (TCR-v5)
    if _brief_ready:
        # ═══ Correctif TCR-v6 — PRÉFLIGHT TEMPOREL AUTONOME : ce bloc
        # ne dépend d'AUCUN import métier (résolveurs d'entité,
        # registres). Une panne d'un module non temporel ne peut plus
        # empêcher la construction du contexte, et une panne du
        # préflight lui-même produit un TemporalContext BLOCKED_ERROR
        # RÉEL transmis au moteur — jamais temporal_context=None après
        # une panne.
        try:
            # Correctif TCR-v10 (verdict v9, P0-3) — LIAISON, jamais
            # seconde résolution : le contexte du pré-gate est rattaché au
            # brief assemblé (empreinte du brief inscrite), après
            # vérification que l'entrée temporelle n'a pas dérivé pendant
            # le rendu (empreinte du TCI recapturée). Toute incohérence
            # devient BLOCKED_ERROR — jamais un contexte recalculé.
            from patches.temporal_context import (bind_assembled_brief
                                                  as _bind19)
            _fp19 = str(getattr(_tci19, "input_fingerprint", "") or "")
            _fp19_now = None
            if _tci19 is not None:
                try:
                    _fp19_now = str(
                        brief_ui.current_temporal_control_input(
                            _lang, settings=settings
                        ).input_fingerprint or "")
                except Exception:
                    _fp19_now = "__temporal_control_input_failure__"
            _tpre19 = _bind19(_tctx19_app, brief,
                              expected_fingerprint=_fp19,
                              current_fingerprint=_fp19_now)
            _tpre19_blocked = bool(_tpre19.is_blocked)
            _tpre19_ctx = _tpre19
            if _tpre19_blocked:
                # v62.13.9.4.34 (lot 1) — L'AUTORITÉ TEMPORELLE SE DEMANDE, ELLE NE
                # SE SIGNALE PAS EN NOTE DE BAS DE PAGE. Contre-audit du 14/09/2026
                # (run réel dossier réseau de soins 69ce0a) : le brief annonçait « Nous sommes début
                # 2023 », le contexte l'avait détecté (candidate 2023-02-15,
                # AMBIGUOUS, politique BLOCKED_AMBIGUOUS) — et le run est parti
                # quand même, produisant trois livrables datés 2026. Le rang 1 de
                # la hiérarchie (settings.analysis_as_of_date) existait sans champ
                # pour le saisir. Ici : exigence visible, candidate proposée,
                # lancement fermé tant que la date n'est pas posée ou écartée.
                # v62.13.9.4.34 (lot 1) — L'AUTORITÉ TEMPORELLE SE DEMANDE, ELLE NE
                # SE SIGNALE PAS EN NOTE DE BAS DE PAGE. Contre-audit du 14/09/2026
                # (run réel du dossier réseau de soins) : le brief annonçait « Nous
                # sommes début 2023 », le contexte l'avait détecté (candidate
                # 2023-02-15, AMBIGUOUS, politique BLOCKED_AMBIGUOUS) — et le run
                # est parti quand même, produisant trois livrables datés 2026.
                # Le bandeau d'adoption A5 (patches/codir_pilot_ui.py) existait déjà
                # et reste l'unique écrivain de la clé structurée : on ne duplique
                # pas son champ. Ici : l'exigence devient visible, et le lancement
                # est fermé tant que la date n'est ni adoptée ni refusée.
                _cand_raw34 = str(getattr(_tpre19, "candidate_raw", "") or "")
                _cand34 = str(getattr(_tpre19, "candidate_value", "") or "")
                st.warning(
                    (("⏸ **Date d'analyse à confirmer.** Le brief situe l'analyse à une autre date que "
                      "celle du jour" + (f" : « {_cand_raw34} »" if _cand_raw34 else "") + ". Adoptez la date "
                      "proposée, ou indiquez que l'analyse doit se faire à la date du jour : tant que ce choix "
                      "n'est pas fait, les résolutions externes sont suspendues et la session ne peut pas être lancée.")
                     if _lang == "fr" else
                     ("⏸ **Analysis date to confirm.** The brief places the analysis at a date other than "
                      "today" + (f": \u201c{_cand_raw34}\u201d" if _cand_raw34 else "") + ". Adopt the proposed date, "
                      "or state that the analysis must run as of today: until that choice is made, external "
                      "resolutions are suspended and the session cannot be launched.")))
                _decided34 = bool(
                    str(getattr(settings, "analysis_as_of_date", "") or "").strip()
                    or str(st.session_state.get(STRUCTURED_WIDGET_KEY34, "") or "").strip()
                    or str(st.session_state.get("codir_analysis_as_of_date_pending", "") or "").strip()
                    or str(st.session_state.get("codir_temporal_candidate_declined_fp", "") or "").strip())
                # UNE PORTE FERMÉE DOIT AVOIR UNE POIGNÉE : le lancement n'est fermé
                # que lorsqu'une décision est réellement offerte — une date candidate
                # lue dans le brief, adoptable ou refusable d'un clic. Sans candidate
                # (autorité absente, panne du producteur), le comportement antérieur
                # s'applique : suspension des résolutions externes, run possible en
                # connaissance de cause. Sinon on bloquerait sans issue (suite
                # complète 9.4.34 : le bouton de lancement disparaissait sur un brief
                # ordinaire).
                _decided34 = _decided34 or not _cand34
                # La légende historique est conservée (contrat AppTest : « résolutions
                # externes suspendues ») ; l'avertissement ci-dessus la rend visible.
                st.caption(
                    ("⏸ Autorité temporelle non établie — résolutions externes "
                     "suspendues pour ce run."
                     if _lang == "fr" else
                     "⏸ Temporal authority not established — external resolutions "
                     "suspended for this run."))
                st.session_state["_temporal_requires_decision"] = not _decided34
            else:
                st.session_state["_temporal_requires_decision"] = False
        except Exception:
            _tpre19_blocked = True
            # FAIL-CLOSED : la panne du producteur de vérité est un
            # BLOCKED_ERROR — et le contexte bloqué est CONSTRUIT puis
            # transmis (contrat « une session = un contexte »).
            try:
                from patches.temporal_context import (blocked_error_context
                                                      as _bec19)
                _tpre19_ctx = _bec19(
                    brief,
                    str(getattr(settings, "analysis_as_of_date", "") or ""))
            except Exception:
                _tpre19_ctx = None
            st.caption(
                ("⛔ Préflight temporel en erreur (BLOCKED_ERROR) — "
                 "résolutions externes suspendues pour ce run."
                 if _lang == "fr" else
                 "⛔ Temporal preflight error (BLOCKED_ERROR) — "
                 "external resolutions suspended for this run."))
    def _persist_last_target(entity) -> None:
        """Persist the complete canonical target, never the display name only."""
        try:
            from datetime import datetime as _dt62128, timezone as _tz62128
            payload = dict(entity.to_dict() if hasattr(entity, "to_dict") else {})
            _name = str(payload.get("name") or getattr(entity, "name", "") or "").strip()
            if not _name:
                return
            payload["name"] = _name
            payload["confirmed_at"] = _dt62128.now(_tz62128.utc).isoformat()
            payload["schema_version"] = "target_entity_v1"
            # Keep the active session in sync, but persist only target fields.
            # The session may carry a temporary analysis_as_of_date that must
            # never become durable merely because a target was confirmed.
            settings.last_target_entity = payload
            settings.last_target_entity_name = _name  # legacy compatibility
            update_last_target_entity(payload)
        except Exception:
            pass  # target persistence must never block the analysis

    if _brief_ready:
        try:
            from utils.target_entity_resolver import (
                extract_signals_from_brief, resolve_candidates,
                resolve_with_confirmed_name, TargetEntity,
            )

            _ext_skip_key      = "external_sources_skip_session"
            _confirmed_ent_key = "confirmed_target_entity"
            if _ext_skip_key      not in st.session_state: st.session_state[_ext_skip_key] = False
            if _confirmed_ent_key not in st.session_state: st.session_state[_confirmed_ent_key] = None

            # v62.12.8 — cible canonique mémorisée : un clic explicite
            # restaure le même objet (identifiants inclus), sans nouvelle
            # résolution nominale ni divergence entre écrans.
            _remembered_payload = (settings.last_target_entity
                                   if isinstance(getattr(settings, "last_target_entity", None), dict)
                                   else {})
            if (st.session_state[_confirmed_ent_key] is None
                    and not st.session_state[_ext_skip_key]
                    and str(_remembered_payload.get("name") or "").strip()):
                _remembered_entity = TargetEntity.from_dict(_remembered_payload)
                _remembered = _remembered_entity.name.strip()
                _rem_col1, _rem_col2, _rem_col3 = st.columns([3, 1, 1])
                with _rem_col1:
                    st.caption(T("target_entity_remembered_caption", _lang)
                               .format(name=_remembered_entity.display_label()))
                with _rem_col2:
                    if st.button(T("target_entity_remembered_use", _lang),
                                 key="target_entity_remembered_use_btn"):
                        st.session_state[_confirmed_ent_key] = _remembered_entity
                        st.session_state[_ext_skip_key] = False
                        st.rerun()
                with _rem_col3:
                    if st.button(T("target_entity_remembered_forget", _lang),
                                 key="target_entity_remembered_forget_btn"):
                        settings.last_target_entity = {}
                        settings.last_target_entity_name = ""
                        update_last_target_entity(None)
                        st.rerun()

            _signals = extract_signals_from_brief(brief)
            # F.6.7.1 (audit P1/P2) — le mode source du brief COURANT prime sur l'état UI
            # hérité : on lève automatiquement le skip si on revient à un brief ouvert.
            from patches.mission_governance import reconcile_external_skip as _recon_ext
            _ext_override, _ext_forced = _recon_ext(
                _attach_only_ui, st.session_state.get("_source_mode_forced_attach_only", False))
            if _ext_override is not None:
                st.session_state[_ext_skip_key] = _ext_override
            st.session_state["_source_mode_forced_attach_only"] = _ext_forced

            with st.expander(T("target_entity_section_title", _lang),
                             expanded=(_signals.has_any() and not _attach_only_ui)):
                _confirmed_now62128 = st.session_state.get(_confirmed_ent_key)
                if _confirmed_now62128 is not None and not _tpre19_blocked:
                    st.success(T("target_entity_confirmed_msg", _lang)
                               .format(label=_confirmed_now62128.display_label()))
                    if st.button(("Changer de cible" if _lang == "fr" else "Change target"),
                                 key="target_entity_change_confirmed_btn"):
                        st.session_state[_confirmed_ent_key] = None
                        st.session_state[_ext_skip_key] = False
                        st.rerun()
                elif _tpre19_blocked:
                    # Correctif TCR-v2 P0-1 — sous préflight bloqué,
                    # AUCUNE surface d'identification n'est rendue :
                    # ni candidats, ni previews, ni champ manuel (le
                    # chemin manuel pilote GLEIF/SEC/CH). Le moteur
                    # rendra le résultat minimal local.
                    pass
                elif _attach_only_ui:
                    st.info(_attach_only_ui_msg)
                elif _signals.has_any():
                    st.caption(T("target_entity_intro_signals", _lang))
                    st.code(_signals.summary_line(), language=None)

                    # ── Since v16.5.69 — Mise en garde fuzzy Companies House ─
                    # Si un signal CN_UK OU un nom est extrait, on appelle preview
                    # pour vérifier que le match est non ambigu. Si fuzzy → carte
                    # de mise en garde avant que l'utilisateur sélectionne la cible.
                    try:
                        from utils.companies_house_tool import preview_companies_house_detection
                        # Devine un nom probable depuis le brief si pas de confirmed_name
                        # On utilise le candidat top-1 comme proxy (s'il existe déjà)
                        _ch_prev = preview_companies_house_detection(
                            brief, lang=_lang,
                            confirmed_name="",  # CN_UK direct uniquement à ce stade
                        )
                        if _ch_prev.get("active"):
                            _hint = _ch_prev.get("confidence_hint", "")
                            _safe = _ch_prev.get("auto_confirm_safe", False)
                            if _hint == "NAME_FUZZY" or (_hint == "NAME_EXACT" and not _safe):
                                st.warning(T("ch_fuzzy_warning_title", _lang))
                                st.caption(T("ch_fuzzy_warning_caption", _lang))
                                st.markdown(f"**{T('ch_fuzzy_candidates_label', _lang)}**")
                                for _c in _ch_prev["candidates"][:5]:
                                    st.markdown(T("ch_fuzzy_card_format", _lang).format(
                                        title=_c.get("title", "—"),
                                        cn=_c.get("company_number", "—"),
                                        status=_c.get("status", "—"),
                                        address=(_c.get("address") or "—")[:80],
                                    ))
                            elif _hint == "NUMBER_DIRECT" or (_hint == "NAME_EXACT" and _safe):
                                # Match safe — pas de UI bloquante, juste petite confirmation
                                st.caption(T("ch_fuzzy_safe_caption", _lang))
                            elif _hint == "NOT_FOUND" and _ch_prev.get("preview_method") == "name_search":
                                st.caption(T("ch_fuzzy_not_found", _lang))
                    except Exception:
                        pass  # tolérance complète

                    # Résolution multi-sources (sans cascade Pappers)
                    try:
                        _candidates = resolve_candidates(brief, lang=_lang)
                    except Exception as _re:
                        _candidates = []
                        st.caption(f"_(resolve error: {str(_re)[:80]})_")

                    if _candidates:
                        st.markdown(T("target_entity_n_candidates", _lang)
                                    .format(n=len(_candidates)))
                        # Patch v16.5.69 — Sentinel choix neutre obligatoire :
                        # avant : index=0 → auto-confirm silencieux du 1er candidat (BUG identique
                        # à celui que nous avions corrigé sur Pappers Since v16.5.62).
                        # maintenant : sentinel "— Sélectionner une cible —" en première position,
                        # qui n'écrit RIEN dans session_state. L'utilisateur DOIT cliquer pour valider.
                        _opt_pending = T("target_entity_option_pending", _lang)
                        _opt_manual  = T("target_entity_option_manual", _lang)
                        _opt_skip    = T("target_entity_option_skip", _lang)
                        _opts: list = [_opt_pending]  # sentinel en index 0
                        _opts.extend([c.entity.display_label() for c in _candidates])
                        _opts.extend([_opt_manual, _opt_skip])

                        _sel = st.selectbox(
                            T("target_entity_select_label", _lang),
                            _opts,
                            index=0,  # sentinel par défaut → pas d'auto-confirm
                            key="target_entity_sel",
                        )

                        if _sel == _opt_pending:
                            # Aucune action utilisateur : on N'ÉCRIT PAS dans session_state.
                            # Le pipeline tournera avec confirmed_target_entity=None (mode v16.5.68).
                            # On garde toutefois l'éventuel état antérieur si déjà confirmé en
                            # session précédente — pas de reset destructif.
                            st.warning(T("target_entity_pending_warning", _lang))
                        elif _sel == _opt_manual:
                            _manual_name = st.text_input(
                                T("target_entity_manual_label", _lang),
                                key="target_entity_manual_input",
                                placeholder="e.g. the registered UK company name",
                            )
                            if not _tpre19_blocked and _manual_name \
                                    and len(_manual_name.strip()) >= 3:
                                _manual_cands = resolve_with_confirmed_name(
                                    brief, _manual_name.strip(), lang=_lang
                                )
                                if _manual_cands:
                                    _entity = _manual_cands[0].entity
                                    st.session_state[_confirmed_ent_key] = _entity
                                    st.session_state[_ext_skip_key] = False
                                    _persist_last_target(_entity)
                                    st.success(T("target_entity_confirmed_msg", _lang)
                                               .format(label=_entity.display_label()))
                                else:
                                    # Pas de match : on passe en TargetEntity name-only
                                    _entity = TargetEntity(
                                        name=_manual_name.strip(),
                                        source="manual", confidence="NAME_ONLY",
                                    )
                                    st.session_state[_confirmed_ent_key] = _entity
                                    st.session_state[_ext_skip_key] = False
                                    _persist_last_target(_entity)
                                    st.success(T("target_entity_confirmed_msg", _lang)
                                               .format(label=_entity.display_label()))
                        elif _sel == _opt_skip:
                            st.session_state[_confirmed_ent_key] = None
                            st.session_state[_ext_skip_key] = True
                            st.warning(T("target_entity_skip_msg", _lang))
                        else:
                            # Un candidat parmi les remontés (sélection EXPLICITE par l'utilisateur)
                            try:
                                _idx = _opts.index(_sel)
                                # Index 0 = sentinel (déjà géré au-dessus)
                                # Index 1..N = candidats (offset de 1 vs liste _candidates)
                                _cand_idx = _idx - 1
                                if 0 <= _cand_idx < len(_candidates):
                                    _entity = _candidates[_cand_idx].entity
                                    st.session_state[_confirmed_ent_key] = _entity
                                    st.session_state[_ext_skip_key] = False
                                    _persist_last_target(_entity)
                                    st.success(T("target_entity_confirmed_msg", _lang)
                                               .format(label=_entity.display_label()))
                            except (ValueError, IndexError):
                                pass
                    else:
                        # Signaux détectés mais pas de candidats résolus (API muettes)
                        st.caption(T("target_entity_no_signals", _lang))
                else:
                    # Aucun signal natif détecté
                    st.caption(T("target_entity_no_signals", _lang))
                    _manual_name = st.text_input(
                        T("target_entity_manual_label", _lang),
                        key="target_entity_manual_input_no_sig",
                        placeholder="e.g. the registered UK company name",
                    )
                    if not _tpre19_blocked and _manual_name \
                            and len(_manual_name.strip()) >= 3:
                        _manual_cands = resolve_with_confirmed_name(
                            brief, _manual_name.strip(), lang=_lang
                        )
                        if _manual_cands:
                            _entity = _manual_cands[0].entity
                        else:
                            _entity = TargetEntity(
                                name=_manual_name.strip(),
                                source="manual", confidence="NAME_ONLY",
                            )
                        st.session_state[_confirmed_ent_key] = _entity
                        st.session_state[_ext_skip_key] = False
                        _persist_last_target(_entity)
                        st.success(T("target_entity_confirmed_msg", _lang)
                                   .format(label=_entity.display_label()))

                st.caption(T("target_entity_help_caption", _lang))
        except Exception as _te:
            # Tolérance complète : si le module n'est pas dispo, on continue silencieusement
            pass
    # ─────────────────────────────────────────────────────────────────────────

    if not _brief_ready:
        st.info("👆 Composez votre brief ci-dessus avant de lancer la session." if _lang == "fr" else "👆 Compose your brief above before launching.")
        run_btn = False
    else:
        run_btn = st.button(T("launch_btn", _lang), type="primary")

    if run_btn:
        # Clear persisted artifacts for a clean run (avoid showing stale results if a role fails)
        st.session_state["last_result"] = None
        st.session_state["last_docx"] = None
        st.session_state["last_pptx"] = None
        st.session_state["last_docx_error"] = None   # v62.13.9.4.31.1
        st.session_state["last_pptx_debug"] = None
        st.session_state["last_pptx_layout_report"] = None
        # 9.4.54 — écran traitement (maquette validée le 08/09/2026, 12 étapes validées le 07/10/2026) : l'écran nu
        # (logo, « Étape x / 12 », barre des étapes accomplies, temps écoulé, durée habituelle) remplace l'affichage ;
        # le journal détaillé reste disponible, replié, sous l'écran.
        st.session_state["run_screen54_done"] = False
        try:   # 9.4.65 — le poste ne se met pas en veille pendant le run (recette du 15/10 : run perdu pendant une réunion)
            from utils import keep_awake65 as _ka65
            _ka65.start()
        except Exception:
            _ka65 = None
        _screen54 = st.empty()
        try:
            from utils.run_screen54 import RunProgress as _RP54, load_durations as _ld54
            _rp54 = _RP54(_lang, durations=_ld54())
        except Exception:
            _rp54 = None

        def _render54(final57: bool = False):
            if _rp54 is not None:
                try:   # 9.4.57 — écran dépouillé plein écran, temps en continu
                    from utils.run_screen54 import overlay_html57 as _ov57
                    _screen54.markdown(_ov57(_rp54, _logo_b64_54(), final=final57), unsafe_allow_html=True)
                except Exception:
                    pass
        if _rp54 is not None:
            _rp54.start(1)
            _render54()
        status = st.status(T("starting", _lang), state="running", expanded=False)
        def cb(step_id: str, label: str):
            status.update(label=label, state="running")
            if _rp54 is not None:
                _rp54.on_engine(step_id, label)
                _render54()

        # ─── v16.5.75.5 — Préparation documentaire au clic Lancer ─────────────
        # Avant v75.4 : parsing + scan FS exécutés à chaque rerun Streamlit
        #               (touche Entrée, modif champ) → 30-60s perdues par interaction.
        # Depuis v75.4 : pipeline lourd appelé ici, avec cache par hash session.
        # ──────────────────────────────────────────────────────────────────────
        # Correctif TCR-v2 P1 — un run temporellement bloqué ne parse ni
        # ne scanne AUCUNE pièce : résultat minimal immédiat.
        if not _tpre19_blocked and uploaded:
            _uploads_for_prep = []
            for f in uploaded[: settings.attachments_max_files]:
                _uploads_for_prep.append((f.name, f.type or "", f.getvalue()))
            (
                attachments_block,
                attachments_meta,
                financial_statements_block,
                financial_statements_bundles,
            ) = _prepare_documents_for_run(_uploads_for_prep, settings, _lang, status_handle=status)

            # Feedback utilisateur post-préparation
            n_detected = sum(
                1 for b in financial_statements_bundles
                if getattr(b, "financial_statements_detected", False)
            )
            if financial_statements_bundles:
                if n_detected > 0:
                    st.success(
                        (f"📊 États financiers détectés dans **{n_detected}/{len(financial_statements_bundles)}** PDF(s) — "
                         f"Finance / DG / Synthèse recevront les chiffres extraits.")
                        if _lang == "fr" else
                        (f"📊 Financial Statements detected in **{n_detected}/{len(financial_statements_bundles)}** PDF(s) — "
                         f"Finance / CEO / Synthesis will receive the extracted figures.")
                    )

        try:
            log_event(logger, "info", "app", "run_clicked")
            _pappers_skip      = st.session_state.get("pappers_skip_session", False)
            _pappers_confirmed = st.session_state.get("pappers_confirmed_entity", "")
            # Since v16.5.69 — Découplage : nouveaux flags indépendants
            _ext_sources_skip      = st.session_state.get("external_sources_skip_session", False)
            _confirmed_target_ent  = st.session_state.get("confirmed_target_entity", None)
            # UI-1 — la langue choisie à l'écran (brief, mode actif) l'emporte pour CE
            # run ; la configuration reste le défaut. Corrige aussi le risque de sortie
            # en langue mixte (l'ancien sélecteur du brief n'était qu'un écho décoratif).
            try:
                settings.output_language = brief_ui.active_output_language(
                    getattr(settings, "output_language", "fr"))
            except Exception:
                pass
            if _tpre19_blocked and _tpre19_ctx is None:
                # Panne TOTALE du préflight (même la fabrique a échoué) :
                # aucun moteur — jamais temporal_context=None après panne.
                st.error("Préflight temporel indisponible — run annulé."
                         if _lang == "fr" else
                         "Temporal preflight unavailable — run aborted.")
                st.stop()
            # v62.13.9.4.50 — INTÉGRITÉ DU BRIEF (recette du 02/10/2026) : un bloc de statuts collé dans le champ y était
            # entier (« … option 2 retenue. ») mais n'arrivait au moteur que coupé à 200 caractères. Avant tout lancement,
            # chaque passage saisi dans le champ principal doit se retrouver dans le brief transmis ; sinon le lancement
            # s'arrête et dit ce qui manque — jamais un run sur un texte tronqué en silence.
            _missing50 = []
            try:
                import re as _re50
                _raw50 = str(st.session_state.get("bui_e_fr") or st.session_state.get("bui_t_fr") or "")
                _norm50 = lambda x: _re50.sub(r"\s+", " ", str(x or "")).strip()
                _brief_n50 = _norm50(brief)
                for _l50 in _raw50.splitlines():
                    for _seg50 in _re50.split(r"(?<=[.;])\s+", _l50):
                        _s50 = _norm50(_seg50)
                        if len(_s50) >= 25 and _s50[-60:] not in _brief_n50:
                            _missing50.append(_s50)
            except Exception:
                _missing50 = []
            if _missing50:      # st.stop() hors du try : son exception de contrôle ne doit jamais être avalée
                st.error(("⛔ Une partie du brief saisi n'a pas été transmise à l'analyse : « " + _missing50[0][:160] + " ». "
                          "Le lancement est arrêté pour ne pas analyser un texte tronqué. Raccourcis la ligne ou "
                          "mets une déclaration par ligne, puis relance.") if _lang == "fr" else
                         ("⛔ Part of the brief you entered did not reach the analysis: “" + _missing50[0][:160] + "”. "
                          "Launch stopped so that a truncated text is never analysed. Shorten the line or put one "
                          "statement per line, then relaunch."))
                st.stop()
            result = run_codir_session(
                brief,
                # TCR-v5 — l'instance du préflight EST le contexte du
                # moteur (empreinte vérifiée côté moteur).
                temporal_context=_tpre19_ctx,
                # TCR-v10 — l'empreinte de l'ENTRÉE TEMPORELLE COURANTE
                # descend avec lui : le moteur prouve que le contexte
                # qu'il consomme a été résolu sur la photographie que
                # l'application lui déclare (P0-3, fingerprint consommé).
                temporal_input_fingerprint=str(
                    getattr(_tci19, "input_fingerprint", "") or ""),
                temperature=float(temperature),
                max_tokens=int(max_tokens),
                attachments_block=attachments_block,
                attachments_meta=attachments_meta,
                cb=cb,
                settings=settings,
                logger=logger,
                pappers_skip=_pappers_skip,
                pappers_confirmed_entity=_pappers_confirmed,
                external_sources_skip=_ext_sources_skip,
                confirmed_target_entity=_confirmed_target_ent,
                # Since v16.5.70 — Financial Statements extraits en amont
                financial_statements_block=financial_statements_block,
                financial_statements_bundles=financial_statements_bundles,
            )
            st.session_state["last_result"] = result
            # ── M.5.10.5 — Localisation EN des tags épistémiques inline ──────
            # Chokepoint unique : on localise [NON SOURCÉ]/[FAIT]/[ESTIM-HYPOTHÈSE]…
            # dans les sorties d'agents APRÈS le run (analyse de statut faite) et
            # AVANT tout rendu (DOCX export_docx, report_text→deck, language gate).
            try:
                if getattr(settings, "output_language", "fr") == "en" and isinstance(result, dict):
                    from patches.output_hygiene import localize_epistemic_tags_in_outputs
                    _outs = result.get("outputs")
                    if isinstance(_outs, dict):
                        localize_epistemic_tags_in_outputs(_outs, "en")
            except Exception:
                pass
            # v62.13.9.4.48 — LIBELLÉS MONOLINGUES : les agents recopient la table de faits ;
            # « Revenue / Chiffre d'affaires » sort dans la seule langue du run, dans toutes les
            # sorties, avant tout rendu (Word, deck, porte de langue).
            try:
                if isinstance(result, dict) and isinstance(result.get("outputs"), dict):
                    from utils.financial_facts_table import monolingualize_metric_labels as _mml48
                    _lng48 = getattr(settings, "output_language", "fr")
                    for _k48, _v48 in list(result["outputs"].items()):
                        if isinstance(_v48, str) and _v48:
                            result["outputs"][_k48] = _mml48(_v48, _lng48)
            except Exception:
                pass
            # v17.2 — promotion des faits liasse page-cités (FAIT) dans la table,
            # devant le narratif (supersède les estimations du même métrique/entité).
            try:
                _lfacts = st.session_state.get("_liasse_facts_v172", []) or []
                _liasse_preengine6212 = int(((result.get("liasse_cerfa_ingestion") or {}).get(
                    "facts_added", 0) or 0)) if isinstance(result, dict) else 0
                if _lfacts and isinstance(result, dict) and not _liasse_preengine6212:
                    _fft_pl = result.get("financial_facts_table")
                    if isinstance(_fft_pl, dict):
                        from patches.liasse_fact_extractor import promote_liasse_facts as _plf
                        _rows0 = _fft_pl.get("facts", []) or []
                        _rows1, _nadd, _nsup = _plf(_rows0, _lfacts)
                        _fft_pl["facts"] = _rows1
                        result["financial_facts_table"] = _fft_pl
                        if isinstance(result.get("financial_facts_table_n_facts"), int):
                            result["financial_facts_table_n_facts"] = len(_rows1)
                        st.session_state["last_result"] = result
                        try:
                            log_event(logger, "info", "app",
                                      f"v17.2 liasse promote: +{_nadd} FAIT page-cités, "
                                      f"{_nsup} narratifs supersédés")
                        except Exception:
                            pass
            except Exception as _e_pl:
                try:
                    log_event(logger, "warning", "app", f"v17.2 promote failed: {_e_pl}")
                except Exception:
                    pass
            # ── B.1.3.6-HYBRID (audit ChatGPT) — FIDELITY GATE TÔT et
            # indépendant de la langue. En 3.6 officiel, le gate tournait dans
            # le bloc language_gate EN, donc pas en FR, et trop tard pour le
            # DOCX/PPTX initial / slide cadre. Ici il tourne AVANT tout rendu.
            try:
                from patches.fidelity_gate import apply_fidelity_gate as _afg136_early
                # B.1.3.12 — le render doit connaître le completion gate
                # (usage client bloqué) et la richesse de signal (SQ split).
                try:
                    _cs12 = result.get("delivery_confidence_score") or {}
                    _cs12["completion_flagged"] = bool(result.get("completion_gate"))
                    if result.get("financial_signal_score") is not None:
                        _cs12.setdefault("signal_score", result.get("financial_signal_score"))
                except Exception:
                    pass
                _fg_cs = result.get("delivery_confidence_score") if isinstance(result, dict) else None
                _fg_pp = ((result.get("extraction_fidelity") or {}).get("per_page")
                          or {}) if isinstance(result, dict) else {}
                _fg_conf = (int(_fg_pp.get("verbatim_on_page", 0))
                            + int(_fg_pp.get("normalized_on_page", 0)))
                _fg_weak = (int(_fg_pp.get("page_unavailable", 0))
                            + int(_fg_pp.get("no_citation", 0))
                            + int(_fg_pp.get("not_found_on_cited_page", 0)))
                _fg_tot = _fg_conf + _fg_weak
                _fg_att = int(result.get("attachments_count") or (1 if _fg_tot else 0)) if isinstance(result, dict) else 0
                if isinstance(_fg_cs, dict):
                    _fginfo = _afg136_early(
                        _fg_cs, n_attachments=_fg_att, n_pj_facts=_fg_tot,
                        n_confirmed_on_page=_fg_conf,
                        lang=getattr(settings, "output_language", "fr"))
                    if (_fginfo.get("triggered")
                                        and not _fginfo.get("idempotent_skip")):  # B.1.3.8 — plus de double row
                        result["delivery_confidence_score"] = _fg_cs
                        try:
                            from patches.fidelity_gate import sync_confidence_diagnostics as _scd628
                            _scd628(result.get("diagnostics_attempts"), _fg_cs)
                        except Exception:
                            pass
                        result.setdefault("diagnostics_attempts", []).append({
                            "role": "fidelity_gate", "provider": "codir",
                            "model": "fidelity_gate_b136_hybrid", "status": "CAPPED",
                            "error": (f"early=True pj_facts={_fg_tot} "
                                      f"confirmed_on_page={_fg_conf} "
                                      f"raw_grade={_fginfo.get('raw_grade')} "
                                      f"capped={_fginfo.get('capped_grade')}")})
            except Exception:
                pass

            st.session_state["last_meta"] = attachments_meta
            # v62.13.9.4.31.1 — exports isolés : le CR puis la synthèse, chacun
            # dans son garde-fou ; un refus n'arrête plus la chaîne (le PPTX
            # suit, le paquet embarque ce qui est livré). Voir run_document_exports.
            # v62.13.9.4.40 — UN SEUL GRADE PAR SESSION : la porte de langue s'applique au texte du
            # compte rendu AVANT les exports Word (elle ne tournait qu'avec la trame, après la synthèse :
            # « Grade B » dans la synthèse, « Grade C » ailleurs, dossier réel du 21/09/2026).
            try:
                from patches.language_gate import apply_language_gate as _alg40
                _cs40 = result.get("delivery_confidence_score")
                if isinstance(_cs40, dict):
                    _cr_text40 = "\n".join(str(v) for v in (result.get("outputs") or {}).values() if isinstance(v, str))
                    _cs40, _ = _alg40(_cs40, _cr_text40, "", _lang)
                    result["delivery_confidence_score"] = _cs40
            except Exception:
                pass
            _dexp31 = run_document_exports(result, _lang)
            st.session_state["last_docx"] = _dexp31["cr"]
            st.session_state["last_docx_error"] = _dexp31["cr_error"]
            st.session_state["last_synthese_docx"] = _dexp31["synthese"]
            st.session_state["last_synthese_sidecar"] = _dexp31["synthese_sidecar"]
            st.session_state["last_synthese_error"] = _dexp31["synthese_error"]
            if _dexp31["cr_error"]:
                # trace de crash conservée (les lignes exactes restent dans
                # diagnostics_ia et dans le journal, comme avant) — sans tuer le run
                try:
                    from utils.logger import get_crash_logger, log_crash, flush_logger
                    _crash_logger31 = get_crash_logger(log_dir)
                    log_crash(_crash_logger31, "Working report withheld by final control (run continues)",
                              exc_info=False, exception_type="DocxSafetyBlock",
                              exception_message=str(_dexp31["cr_error"]),
                              run_id=str(result.get("run_id") or ""), build=BUILD_VERSION)
                    flush_logger(_crash_logger31)
                except Exception:
                    pass

            # ═══ Correctif TCR-C1 — EARLY-RETURN APPLICATIF : un run à
            # autorité temporelle bloquée (meta.temporal_early_return /
            # run_validatable False / policy BLOCKED_*) ne déclenche
            # AUCUN post-traitement provider-backed. Le PPTX bloqué est
            # généré LOCALEMENT (déterministe, zéro LLM, zéro coût) avec
            # le bandeau et la consigne de correction.
            if export_pptx and (result.get("meta", {}) or {}).get(
                    "temporal_early_return"):
                try:
                    from utils.pptx_from_cr import (generate_pptx_blocked_local
                                                    as _gpbl19)
                    from patches.temporal_status_renderer import (
                        temporal_status as _ts_pptx19)
                    _blocked_bytes_h2 = _gpbl19(
                        dossier_label=str(getattr(settings, "dossier_label",
                                                  "") or ""),
                        status_line=_ts_pptx19(
                            result, (result.get("lang") or _lang))["message"],
                        lang=(result.get("lang") or _lang))
                    from utils.pptx_delivery_finalizer import finalize_pptx_for_delivery as _finalize_h2
                    _blocked_path_h2 = str(Path("outputs") /
                        f"CoDIR_IA_RUN_BLOQUE_{datetime.now().strftime('%Y-%m-%d')}.pptx")
                    _blocked_final_h2 = _finalize_h2(
                        _blocked_bytes_h2, result=result, lang=(result.get("lang") or _lang),
                        output_path=_blocked_path_h2, delivery_mode="strict")
                    # v62.9 — une slide d'erreur techniquement valide n'est pas
                    # un Working Deck métier. Le rapport distingue désormais
                    # l'écriture du package de l'achèvement du run.
                    _blocked_report_h2 = dict(_blocked_final_h2.report or {})
                    _blocked_report_h2.update({
                        "delivery_mode": "error",
                        "working_deck_contract": False,
                        "technical_package_written": bool(
                            _blocked_final_h2.report.get("output_written")),
                        "business_deck_generated": False,
                        "run_completed": False,
                        "analysis_blocked": True,
                    })
                    st.session_state["last_pptx_layout_report"] = _blocked_report_h2
                    result.setdefault("meta", {})["deck_layout_gate"] = _blocked_report_h2
                    # La slide locale reste téléchargeable comme diagnostic,
                    # jamais sous le bouton « Synthèse ».
                    st.session_state["last_pptx"] = None
                    st.session_state["last_pptx_debug"] = _blocked_final_h2.pptx_bytes
                except Exception:
                    st.session_state["last_pptx"] = None
            elif not export_pptx:
                # 9.4.59 — recette 9.4.58 : une trame non produite ne laissait aucune trace ; la raison est consignée
                result.setdefault("meta", {})["deck_skipped59"] = "trame non demandée (case « Générer la trame » décochée)"
            elif export_pptx:
                status.update(label=T("gen_pptx_status", _lang), state="running")
                if _rp54 is not None:          # 9.4.54 — étape 12 : trame PowerPoint et dossier complet
                    _rp54.start(12)
                    _render54()
                # Construire le texte source complet (brief + toutes les directions)
                outputs = dict(result.get("outputs", {}) or {}) if isinstance(result, dict) else {}
                try:
                    from utils.agent_leakage_gate import sanitize_agent_outputs as _sanitize_ppt_outputs61
                    outputs, _ppt_leakage_report61 = _sanitize_ppt_outputs61(outputs)
                except Exception:
                    _ppt_leakage_report61 = {"sentences_removed": 0, "fields_touched": 0}
                meta = st.session_state.get("last_meta", {}) or {}
                # SC nettoyée des blocs JSON/audit pour le report_text
                _sc_for_report = ""
                _sc_raw = outputs.get("supply_chain", "") or ""
                _sc_bundle = result.get("raw", {}).get("supply_chain", {}) if isinstance(result, dict) else {}
                if _has_meaningful_text(_sc_raw):
                    _sc_for_report = "\n" + RL("sc", getattr(settings,"output_language","fr")) + "\n" + _strip_sc_json_blocks(_sc_raw)
                elif isinstance(_sc_bundle, dict) and _sc_bundle.get("triggered"):
                    # Chantier 1 — v16.5.28 : SC déclenchée mais output vide → fallback explicite
                    _sc_for_report = (
                        "\n" + RL("sc", getattr(settings,"output_language","fr")) + "\n"
                        + RL("sc_unavailable", getattr(settings, "output_language", "fr"))
                    )

                _rl = getattr(settings, "output_language", "fr")
                # ── v17.1-B2.3-A.1 — Parité CR↔deck : injecter la décision
                # réconciliée + alertes pipeline EN TÊTE du report_text, pour que
                # le deck reflète la MÊME décision finale unique que le CR Word
                # (évite CR=NO-GO réconcilié / deck=GO conditionnel divergent).
                _b23_block = ""
                try:
                    _b23g = result.get("b23_guards") if isinstance(result, dict) else None
                    if isinstance(_b23g, dict):
                        _dec = _b23g.get("decision") or {}
                        _flg = _b23g.get("flags") or []
                        if _dec.get("final") or _flg:
                            try:
                                from patches.pipeline_guards_b23 import localize_verdict as _lv23d
                            except Exception:
                                _lv23d = lambda t, l: t
                            _en = (_rl == "en")
                            _final_d = _lv23d(_dec.get('final', ''), _rl)
                            _note_d = _lv23d(_dec.get('note', ''), _rl)
                            if _en:
                                _ll = ["=== RECONCILED DECISION (FINAL — DEFAULT PRUDENCE) ==="]
                                if _dec.get("final"):
                                    _ll.append(f"Single final decision: {_final_d}. {_note_d}")
                                    _ll.append("The synthesis (decision slides / action plan) MUST reflect "
                                               "this single final decision, without reintroducing a divergent "
                                               "recommendation (e.g. do not show 'CONDITIONAL GO' if the "
                                               "reconciled final decision is NO-GO).")
                                if _flg:
                                    _ll.append("Pipeline alerts to reflect in the synthesis:")
                                    _ll += [f"- {_f}" for _f in _flg[:6]]
                            else:
                                _ll = ["=== DÉCISION RÉCONCILIÉE (FINALE — PRUDENCE PAR DÉFAUT) ==="]
                                if _dec.get("final"):
                                    _ll.append(f"Décision finale unique : {_final_d}. {_note_d}")
                                    _ll.append("La synthèse (slides décisions / plan d'action) DOIT refléter "
                                               "cette décision finale unique, sans réintroduire une recommandation "
                                               "divergente (ex. ne pas afficher « GO conditionnel » si la décision "
                                               "finale réconciliée est NO-GO).")
                                if _flg:
                                    _ll.append("Alertes pipeline à refléter dans la synthèse :")
                                    _ll += [f"- {_f}" for _f in _flg[:6]]
                            _b23_block = "\n".join(_ll)
                except Exception:
                    _b23_block = ""
                # v62.13.9.4.23 — les OBJETS D'ANALYSE (décisions, options, risques,
                # arbitrages, actions avec porteur/échéance, questions) ouvrent le
                # texte transmis au structurant : la décision DG n'est plus au
                # caractère 42 000 d'un rapport tronqué à 14 000.
                _objects_block62423 = ""
                try:
                    from utils.analysis_objects import extract_objects as _eo62423
                    from utils.objects_render import synthesis_sections as _ss62423
                    _res_w62423 = copy.deepcopy(result); _res_w62423["_render_mode"] = "work"
                    _ob62423 = _eo62423(apply_v62136_maintenance(_res_w62423))
                    result["analysis_objects"] = _ob62423
                    _secs62423 = _ss62423(_ob62423, result, _rl)
                    _objects_block62423 = "\n\n".join(
                        f"## {s['title']}\n" + "\n".join(f"- {l}" for l in s["lines"]) for s in _secs62423)
                    _objects_block62423 = _objects_block62423.replace("\u2063", "")
                    from utils.quantity_ledger import strip_status_tags as _sst62423
                    _objects_block62423 = _sst62423(_objects_block62423)
                except Exception as _oe62423:
                    _objects_block62423 = ""
                report_text = "\n\n".join(filter(bool, [
                    RL("source_header", _rl) + "\n",
                    _b23_block,
                    (("\n# ANALYSIS OBJECTS — DECISIONS, OPTIONS, RISKS, ACTIONS\n" if str(_lang).lower().startswith("en")
                      else "\n# OBJETS D'ANALYSE — DÉCISIONS, OPTIONS, RISQUES, ACTIONS\n") + _objects_block62423)
                    if _objects_block62423 else "",
                    # Correctif TCR-C1 — le brief BRUT ne part plus au
                    # provider PPTX : le deck se construit du compte
                    # rendu, jamais de l'entrée utilisateur brute.
                    "\n" + RL("strategy", _rl) + "\n" + (outputs.get("strategie", "") or ""),
                    "\n" + RL("brief_codir", _rl) + "\n" + (outputs.get("brief_codir", "") or ""),
                    "\n" + RL("marketing", _rl) + "\n" + (outputs.get("marketing", "") or ""),
                    "\n" + RL("finance", _rl) + "\n" + (_finance_safe(outputs.get("finance", ""), result=result, lang=_rl) or ""),
                    _sc_for_report,
                    "\n" + RL("commercial", _rl) + "\n" + (outputs.get("commercial", "") or ""),
                    "\n" + RL("synthesis", _rl) + "\n" + (outputs.get("synthese_decisions", "") or ""),
                    "\n" + RL("dg", _rl) + "\n" + (outputs.get("direction_generale", "") or ""),
                ]))
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
                    raise RuntimeError(T("no_provider_pptx", _lang))
                from utils.pptx_from_cr import generate_pptx_from_cr_with_provider
                _out_path = str(Path("outputs") / f"CoDIR_IA_Synthese_{datetime.now().strftime('%Y-%m-%d')}.pptx")
                # B.1.3.19 (run 11 ; racine PROUVÉE : la clé « cr » n'existe
                # nulle part dans result — grep exhaustif, 10e lecture morte,
                # flag False depuis 3.14) — on scanne report_text, LE texte
                # du CR passé au générateur trois lignes plus bas
                # (104 hits sur le CR run 11).
                _retail_kw14 = bool(__import__("re").search(
                    r"inventory|stock|store|DTC|e-?commerce|markdown",
                    str(report_text or ""), __import__("re").I))
                # B.1.3.28-chatgpt — Stability Guard : clé = entité + brief +
                # hash des pièces.  Jamais le hash des pièces seul (sinon tous
                # les runs sans PJ ou deux dossiers partageant les mêmes PJ se
                # contamineraient).
                try:
                    _prep28 = st.session_state.get("_prepared_docs_cache_v16_5_75_4") or {}
                    _uph28 = str(_prep28.get("hash") or "no-attachments")
                    _ent28 = str((result.get("entity_scope") or {}).get("analysis_entity") or "")
                    _raw28 = f"{_ent28}|{_uph28}|{brief}"
                    _stability_key28 = __import__("hashlib").sha256(
                        _raw28.encode("utf-8", errors="ignore")).hexdigest()
                    _runtime_dir28 = str(Path(".codir_runtime"))
                except Exception:
                    _stability_key28 = None
                    _runtime_dir28 = None
                # B.1.3.29-chatgpt — per-call diagnostics container.  Streamlit
                # sessions share module globals, so a substantive Usage Gate must
                # never read LAST_DECK_DIAG from another concurrent session.
                _deck_diag_local28 = {}
                # B.1.3.56 Gate 11 — l'autorité temporelle est une donnée de
                # session : date d'analyse simulée si le brief en impose une,
                # sinon date réelle du run. Jamais l'horloge de régénération.
                try:
                    from patches.cr_blocks_docx import _result_run_date as _result_run_date_pptx
                    _pptx_run_date_obj = _result_run_date_pptx(result)
                    _pptx_run_date = (_pptx_run_date_obj.isoformat()
                                      if _pptx_run_date_obj is not None else None)
                except Exception:
                    _pptx_run_date = None
                _pptx_mode = str(getattr(settings, "pptx_delivery_mode", "working") or "working").lower()
                if _pptx_mode not in {"working", "strict"}:
                    _pptx_mode = "working"
                _pptx_working_bytes = generate_pptx_from_cr_with_provider(
                    report_text,
                    _active_provider,
                    settings,
                    output_path=None,
                    extra_context={
                        # Refactor — bandeau temporel du deck rendu par
                        # le TemporalStatusRenderer (nouvelle surface).
                        "temporal_status_line": (lambda: (
                            __import__("patches.temporal_status_renderer",
                                       fromlist=["temporal_status"])
                            .temporal_status(result,
                                             (result.get("lang") or "fr"))
                            ["message"]))(),
                        "run_date": _pptx_run_date,
                        "strategic_target_end_date": str(
                            getattr(_horizon_reconciliation_app, "target_end_date", "") or
                            ((result.get("strategic_horizon") or {}).get("target_end_date") if isinstance(result.get("strategic_horizon"), dict) else "") or ""),
                        "pptx_delivery_mode": _pptx_mode,
                        "result": result,                    # v62.13.9.4.23 — objets d'analyse pour la trame
                        "_retail_kw14": _retail_kw14,
                        "supply_chain_json": (result.get("meta", {}) or {}).get("supply_chain_json"),
                        "supply_chain_slide_flag": (result.get("meta", {}) or {}).get("supply_chain_slide_flag"),
                        "supply_chain_warning": (result.get("meta", {}) or {}).get("supply_chain_warning"),
                        # v16.5.67 F3 — Propagation status SKIPPED → skip slide SC (fix bug v16.5.66 "SC fantôme")
                        "supply_chain_bundle_status":  (result.get("meta", {}) or {}).get("supply_chain_status"),
                        "supply_chain_bundle_warning": (result.get("meta", {}) or {}).get("supply_chain_warning"),
                        # B.1.3.26 — vrai flag moteur Supply Chain : sans cette
                        # clé, _extract_supply_chain_payload retombe sur NOT
                        # COVERED même quand sc_gate a décidé light_industrial.
                        "sc_decision": result.get("sc_decision"),
                        # B.1.3.28-chatgpt — structured evidence + stability wiring.
                        "financial_facts_table": result.get("financial_facts_table"),
                        "canonical_financial_claims": result.get("canonical_financial_claims") or [],
                        "numeric_support_claims": result.get("numeric_support_claims") or [],
                        "_deck_diag_out": _deck_diag_local28,
                        "runtime_state_dir": _runtime_dir28,
                        "att_hash": _stability_key28,
                        # Option B — v16.5.28 : JSON commercial direct depuis Grok
                        "commercial_json": (result.get("meta", {}) or {}).get("commercial_json"),
                        "finance_tone": result.get("finance_tone"),
                        # v16.5.67.9 — brief_mode propagé pour tagging visuel pastilles PPT GENERIC
                        "brief_mode": (result.get("meta", {}) or {}).get("brief_mode"),
                        # v17.1.0-B2.3-F.4 — artefacts CoDIR pour slides dédiées
                        "agenda_register": result.get("agenda_register"),
                        "web_facts_ledger": result.get("web_facts_ledger"),
                        # Cycle C — historique multi-séances pour le slide « Suivi
                        # multi-séances » (rendu seulement si un historique existe).
                        "codir_history": result.get("codir_history"),
                        "valuation": result.get("valuation"),
                        # M6-S.2.1.1 — verrou entité côté deck
                        "analysis_entity_display": (result.get("entity_scope", {}) or {}).get("analysis_entity"),
                        "registry_entity_display": (result.get("entity_scope", {}) or {}).get("registry_entity"),
                        # B.1.3 — cadre de lecture slide 2 (prudence) + garde
                        # de wording décision quand Grade D/E.
                        # B.1.3.6 (runs dossier anglophone coté ×2, slide cadre absente) — la clé
                        # réelle est delivery_confidence_score ; l'ancienne lecture
                        # "confidence_score" retournait {} → grade vide → need=False
                        # → slide jamais émise. Le test d'intégration fournissait les
                        # clés à la main et masquait le câblage mort.
                        "confidence_grade": (result.get("delivery_confidence_score", {}) or {}).get("grade"),
                        "source_quality": (result.get("delivery_confidence_score", {}) or {}).get("source_quality"),
                        "completion_issues": result.get("completion_gate") or [],
                        "n_pdfs_with_fs": result.get("n_pdfs_with_fs"),
                        "b1_analysis_context": (result.get("b1_proof_layer", {}) or {}).get("analysis_context"),
                    },
                    lang=getattr(settings, "output_language", "fr"),  # v16.5.38
                )

                # ── B.1.3.28-chatgpt — Usage gate wired to real deck outcome ──
                # The guard can only know that the headline KPIs are hypothesis-
                # driven after the deck payload has been structured.  If the
                # run also has zero page-confirmed evidence and no primary
                # financial fact, client presentation becomes non-recommended
                # in BOTH the regenerated DOCX and the final confidence slide.
                try:
                    from patches.executive_evidence_guard import apply_client_usage_gate as _auc28
                    _diag28 = dict(_deck_diag_local28 or {})
                    _ef28 = (result.get("extraction_fidelity") or {}).get("per_page") or {}
                    _confirmed28 = (int(_ef28.get("verbatim_on_page", 0) or 0)
                                    + int(_ef28.get("normalized_on_page", 0) or 0))
                    _cs28 = result.get("delivery_confidence_score") or {}
                    _usage_changed28 = _auc28(
                        _cs28, _confirmed28, result.get("financial_facts_table"),
                        bool(_diag28.get("executive_hypothesis_kpis")
                             or _diag28.get("numeric_instability")),
                        getattr(settings, "output_language", "fr"),
                    )
                    if _usage_changed28:
                        result["delivery_confidence_score"] = _cs28
                        st.session_state["last_docx"] = export_docx(result)
                        result.setdefault("diagnostics_attempts", []).append({
                            "role": "executive_evidence_gate",
                            "provider": "internal",
                            "model": "b1328_chatgpt_usage_wiring",
                            "status": "CLIENT_NOT_RECOMMENDED",
                            "error": (f"confirmed_on_page={_confirmed28} "
                                      f"hypothesis_kpis={_diag28.get('executive_hypothesis_kpis')} "
                                      f"numeric_instability={_diag28.get('numeric_instability')}"),
                        })
                except Exception as _usage28_err:
                    import logging as _lg28
                    _lg28.getLogger("codir_ia").warning(
                        "executive evidence usage gate failed: %s", _usage28_err)


                # ── B.1.3.6 — instrumentation deck_b13 (écho builder + scan bytes)
                try:
                    _dkd = dict(_deck_diag_local28 or {})
                    _dk_emit = bool(_dkd.get("slide_emitted"))
                    if not _dk_emit:
                        try:
                            from pptx import Presentation as _PrsScan
                            from io import BytesIO as _BIO
                            _prs_scan = _PrsScan(_BIO(_pptx_working_bytes))
                            for _si, _sl in enumerate(_prs_scan.slides, 1):
                                if _si > 3:
                                    break
                                _stxt = " ".join(sh.text_frame.text
                                                 for sh in _sl.shapes
                                                 if sh.has_text_frame)
                                if ("CADRE DE LECTURE" in _stxt
                                        or "READING FRAME" in _stxt):
                                    _dk_emit = True
                                    break
                        except Exception:
                            pass
                    result.setdefault("diagnostics_attempts", []).append({
                        "role": "deck_b13", "provider": "internal",
                        "model": "deck_prudence_b136",
                        "status": ("OK" if (_dk_emit or not _dkd.get("need"))
                                   else "MISSING"),
                        "error": (f"grade_read={_dkd.get('grade')} "
                                  f"need={_dkd.get('need')} "
                                  f"prudence_set={_dkd.get('prudence_set')} "
                                  f"slide_emitted={_dk_emit} b13ci={_dkd.get('b13ci_len')}"),
                    })
                except Exception:
                    pass

                # ── Patch v16.5.72.2 (audit ChatGPT round 17) — ORDRE INVERSÉ
                # Avant v16.5.72.2, le PPT plaçait :
                #   ... slides business ... → slide CONFIDENCE → slide FACTS
                # Or conceptuellement le bon ordre est :
                #   ... slides business ... → slide FACTS → slide CONFIDENCE
                # (les faits financiers viennent AVANT le score de confiance,
                # qui est la conclusion / l'avertissement final.)
                # Donc on enrichit d'abord avec les FACTS, puis avec CONFIDENCE.

                # ── 1. Slide Faits financiers utilisés (Source Traceability) ──
                # v62.7 — le deck de travail reste une surface orale 8-15 slides.
                # Les faits financiers détaillés demeurent dans le Word/JSON ; ils ne
                # deviennent une annexe PPTX qu'en mode QA stricte.
                if _pptx_mode == "strict":
                    try:
                        # B.1.3.6 — le DECK doit porter la même réserve que le CR : quand
                        # registre ≠ analyse, la slide facts marque les métadonnées RELATED.
                        try:
                            _es_d = result.get("entity_scope", {}) or {}
                            _an_d = str(_es_d.get("analysis_entity") or "").strip()
                            _rg_d = str(_es_d.get("registry_entity") or "").strip()
                            import re as _re_d
                            def _tk_d(s):
                                return {t for t in _re_d.split(r"[^A-Za-z0-9]+", s.upper()) if len(t) >= 3}
                            if (_an_d and _rg_d and _rg_d.upper() != _an_d.upper()
                                    and _tk_d(_rg_d) != _tk_d(_an_d)):
                                _fft_d = result.get("financial_facts_table")
                                if isinstance(_fft_d, dict):
                                    _fft_d["registry_related_only"] = True
                                    _fft_d["registry_related_name"] = _rg_d
                                    _fft_d["analysis_entity_name"] = _an_d
                        except Exception:
                            pass
                        from utils.financial_facts_render import (
                            enrich_pptx_bytes_with_financial_facts,
                        )
                        _enriched_facts = enrich_pptx_bytes_with_financial_facts(
                            _pptx_working_bytes,
                            financial_facts_table=result.get("financial_facts_table"),
                            lang=getattr(settings, "output_language", "fr"),
                        )
                        if _enriched_facts:
                            _pptx_working_bytes = _enriched_facts
                    except Exception as _ft_pptx_err:
                        import logging as _lg
                        _lg.getLogger("codir_ia").warning(
                            f"PPTX financial facts enrichment failed: "
                            f"{type(_ft_pptx_err).__name__}: {_ft_pptx_err}"
                        )
                else:
                    result.setdefault("meta", {})["pptx_appendices_in_word_only"] = True

                # ── M.5.10.2 (FIX D) — Output Language Gate AVANT la slide Confidence ──
                # Correctif audit ChatGPT : le cap doit être VISIBLE dans les
                # livrables. On scanne CR + (deck + faits) ici, on plafonne le
                # score, PUIS (a) on régénère le DOCX avec le score plafonné, et
                # (b) la slide Confidence (générée juste après) lit le score capé.
                # La slide Confidence est elle-même localisée → pas une source de
                # résidu FR, donc inutile de la scanner. Fail-open, no-op en FR.
                try:
                    from patches.language_gate import apply_language_gate
                    _lg_lang = getattr(settings, "output_language", "fr")
                    if _lg_lang == "en":
                        _deck_text = ""
                        try:
                            import io as _io
                            from pptx import Presentation as _LGPres
                            _scan_bytes = _pptx_working_bytes
                            _lgp = (_LGPres(_io.BytesIO(_scan_bytes))
                                    if _scan_bytes else _LGPres(_out_path))
                            _lgparts = []
                            for _lgsl in _lgp.slides:
                                for _lgsh in _lgsl.shapes:
                                    if _lgsh.has_text_frame:
                                        _lgparts.append(_lgsh.text_frame.text)
                                    if _lgsh.has_table:
                                        for _lgr in _lgsh.table.rows:
                                            _lgparts.append(" ".join(_c.text for _c in _lgr.cells))
                            _deck_text = "\n".join(_lgparts)
                        except Exception:
                            _deck_text = ""
                        # ── B.1.3.6 — FIDELITY GATE (« signal détecté ≠ fait exploitable ») :
                        # des PJ dont AUCUN fait n'est confirmé à la page citée ne peuvent pas
                        # porter le score. Même mécanique que le language gate, cap visible.
                        try:
                            from patches.fidelity_gate import apply_fidelity_gate as _afg136
                            _fg_cs = result.get("delivery_confidence_score")
                            _fg_pp = ((result.get("extraction_fidelity") or {}).get("per_page")
                                      or {}) if isinstance(result, dict) else {}
                            _fg_conf = int(_fg_pp.get("verbatim_on_page", 0)) + int(_fg_pp.get("normalized_on_page", 0))
                            _fg_weak = (int(_fg_pp.get("page_unavailable", 0)) + int(_fg_pp.get("no_citation", 0))
                                        + int(_fg_pp.get("not_found_on_cited_page", 0)))
                            _fg_tot = _fg_conf + _fg_weak
                            _fg_att = int(result.get("attachments_count") or (1 if _fg_tot else 0))
                            if isinstance(_fg_cs, dict):
                                _fginfo = _afg136(_fg_cs, n_attachments=_fg_att,
                                                  n_pj_facts=_fg_tot, n_confirmed_on_page=_fg_conf,
                                                  lang=_lg_lang)
                                if _fginfo.get("triggered"):
                                    result["delivery_confidence_score"] = _fg_cs
                                    try:
                                        from patches.fidelity_gate import sync_confidence_diagnostics as _scd628_late
                                        _scd628_late(result.get("diagnostics_attempts"), _fg_cs)
                                    except Exception:
                                        pass
                                    result.setdefault("diagnostics_attempts", []).append({
                                        "role": "fidelity_gate", "provider": "codir",
                                        "model": "fidelity_gate_b136",
                                        "status": ("SKIPPED_IDEMPOTENT"
                                                   if _fginfo.get("already_applied")
                                                   else "CAPPED"),
                                        "error": (f"pj_facts={_fg_tot} confirmed_on_page={_fg_conf} "
                                                  f"raw_grade={_fginfo.get('raw_grade')} "
                                                  f"capped={_fginfo.get('capped_grade')}"),
                                    })
                                    try:
                                        st.session_state["last_docx"] = export_docx(result)
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                        _lgcs = result.get("delivery_confidence_score")
                        if isinstance(_lgcs, dict):
                            _lgcs, _lginfo = apply_language_gate(
                                _lgcs, report_text, _deck_text, _lg_lang)
                            result["delivery_confidence_score"] = _lgcs
                            try:   # v62.13.9.4.40 — réaligner les Word déjà écrits sur le grade final
                                from utils.confidence_render import restamp_docx_score as _rds40
                                for _k40 in ("last_docx", "last_synthese_docx"):
                                    if st.session_state.get(_k40):
                                        st.session_state[_k40] = _rds40(st.session_state[_k40], _lgcs, _lg_lang)
                            except Exception:
                                pass
                            if _lginfo.get("triggered"):
                                st.session_state["last_language_gate"] = _lginfo
                                # M.5.10.4 — ligne diagnostics_ia.csv : status=CAPPED
                                try:
                                    _lg_block = (_lgcs.get("language_gate")
                                                 if isinstance(_lgcs, dict) else {}) or {}
                                    result.setdefault("diagnostics_attempts", []).append({
                                        "role": "language_gate",
                                        "provider": "codir",
                                        "model": "language_gate",
                                        "status": "CAPPED",
                                        "attempt": 1,
                                        "duration_s": 0,
                                        "error": (
                                            f"residue={_lginfo.get('residue')} "
                                            f"where={_lginfo.get('where')} "
                                            f"raw_grade={_lg_block.get('raw_grade')} "
                                            f"capped={_lg_block.get('capped_grade')} "
                                            f"samples={_lginfo.get('samples')}"
                                        ),
                                    })
                                except Exception:
                                    pass
                                # (a) Régénérer le DOCX pour qu'il reflète le score capé
                                try:
                                    st.session_state["last_docx"] = export_docx(result)
                                except Exception as _docx_re_err:
                                    import logging as _lg
                                    _lg.getLogger("codir_ia").warning(
                                        f"DOCX re-export after language cap failed: "
                                        f"{type(_docx_re_err).__name__}: {_docx_re_err}"
                                    )
                except Exception:
                    pass

                # ── 2. Slide CONFIDENCE SCORE (en dernier — c'est l'avertissement final) ──
                try:
                    from utils.confidence_render import enrich_pptx_bytes_with_confidence
                    _enriched = enrich_pptx_bytes_with_confidence(
                        _pptx_working_bytes,
                        confidence_score=result.get("delivery_confidence_score"),
                        briefcheck=result.get("briefcheck"),
                        lang=getattr(settings, "output_language", "fr"),
                        run_blocked=bool((result.get("b23_guards") or {}).get("run_not_validatable")
                                         or (result.get("delivery_confidence_score") or {}).get("run_not_validatable")),
                        run_block_reasons=(((result.get("b23_guards") or {}).get("run_block_reasons") or [])
                                           + [r for r in ((result.get("delivery_confidence_score") or {}).get("run_block_reasons") or [])
                                              if r not in (((result.get("b23_guards") or {}).get("run_block_reasons")) or [])]),
                        deck_mode=_pptx_mode,
                    )
                    if _enriched:
                        _pptx_working_bytes = _enriched
                except Exception as _cr_pptx_err:
                    import logging as _lg
                    _lg.getLogger("codir_ia").warning(
                        f"PPTX confidence enrichment failed: {type(_cr_pptx_err).__name__}: {_cr_pptx_err}"
                    )

                # v62.13.1 — repair the REAL serialized Working Deck before the
                # H-v2 finalizer. Canonical facts/derived claims lose false
                # estimate labels; unsupported commitments remain fail-closed
                # and are replaced by the qualitative guard message. Geometry
                # and the renderer are not touched.
                # v62.13.8 — delivery-only view; raw evidence/diagnostics/history stay immutable.
                _delivery_result62138 = apply_v62136_maintenance(result)
                # v62.13.9.4.49 — doctrine du 28/09/2026 : le deck n'est plus réparé (réécrit) ; ses constats
                # sont signalés en place par le contrôle final ci-dessous.
                from utils.board_scrutiny_guard import _FLAG_IN_PLACE49 as _fip49
                if (not _fip49) and str(_delivery_result62138.get("finance_tone") or "").upper() == "BOARD_SCRUTINY":
                    try:
                        from utils.board_scrutiny_guard import repair_pptx_executive_numbers
                        _allow_62131 = False  # v62.13.2 Option B — single active policy
                        _pptx_working_bytes, _pptx_numeric_repair62131 = (
                            repair_pptx_executive_numbers(
                                _pptx_working_bytes,
                                lang=_lg_lang if '_lg_lang' in locals() else _lang,
                                allow_labelled_estimates=_allow_62131,
                                numeric_support_claims=list(
                                    _delivery_result62138.get("numeric_support_claims") or []),
                                authoritative_horizon_values=__import__("utils.quantity_ledger", fromlist=["x"]).build_authority_items(result)))
                        result.setdefault("diagnostics_attempts", []).append({
                            "role": "pptx_numeric_repair",
                            "provider": "internal",
                            "model": "board_scrutiny_pptx_v62131",
                            "status": ("OK" if not int(
                                _pptx_numeric_repair62131.get("after", 0) or 0)
                                else "BLOCKED"),
                            "claims_count": int(
                                _pptx_numeric_repair62131.get("before", 0) or 0),
                            "claims_rewritten": int(
                                _pptx_numeric_repair62131.get("claims_rewritten", 0) or 0),
                            "lines_rewritten": int(
                                _pptx_numeric_repair62131.get("repaired", 0) or 0),
                            "parse_errors_count": int(
                                _pptx_numeric_repair62131.get("after", 0) or 0),
                            "parse_errors_sample": (
                                _pptx_numeric_repair62131.get("remaining") or [])[:5],
                            "observability": _pptx_numeric_repair62131,
                        })
                        result["pptx_numeric_post_control"] = _pptx_numeric_repair62131
                    except Exception as _pptx_repair_err62131:
                        import logging as _lg
                        _lg.getLogger("codir_ia").exception(
                            "PPTX numeric repair failed: %s", _pptx_repair_err62131)

                # ── H-v2 — unique application-level delivery choke point ─────
                try:
                    from utils.pptx_delivery_finalizer import (
                        finalize_pptx_for_delivery as _finalize_pptx_h2,
                        pptx_delivery_state as _pptx_delivery_state,
                        pptx_delivery_block_reason as _pptx_block_reason)
                    _final_h2 = _finalize_pptx_h2(
                        _pptx_working_bytes, result=_delivery_result62138, lang=_lg_lang if '_lg_lang' in locals() else _lang,
                        output_path=_out_path, delivery_mode=_pptx_mode)
                    st.session_state["last_pptx_layout_report"] = _final_h2.report
                    result.setdefault("meta", {})["deck_layout_gate"] = _final_h2.report
                    _pptx_state = _pptx_delivery_state(_final_h2.report)
                    result.setdefault("diagnostics_attempts", []).append({
                        "role": "deck_layout_gate", "provider": "internal",
                        "model": "h_v2_finalizer",
                        "status": ("OK" if _pptx_state == "ok" else
                                   "WARNING" if _pptx_state == "warning" else "BLOCKED"),
                        "error": (f"mode={_pptx_mode} sha256={_final_h2.sha256} "
                                  f"blocking={_final_h2.report.get('blocking')} "
                                  f"strict_qa_would_block={_final_h2.report.get('strict_qa_would_block')} "
                                  f"validation={_final_h2.report.get('serialized_validation')}")
                    })
                    _allow_lbl_62130 = False  # v62.13.2 Option B — single active policy
                    _numeric_pptx_block62122 = False
                    # v62.13.9.4.49 — contrôle du deck quel que soit le ton (comme le Word depuis la 9.4.10) :
                    # il ne retient plus, il signale.
                    if _final_h2.distributable:
                        try:
                            # v62.13.9.4.49 — détection de la garde ET du contrôle final (signalement en place)
                            from utils.board_scrutiny_guard import pptx_flag_units as _pfu49
                            _numeric_leaks62122 = _pfu49(
                                _final_h2.pptx_bytes,
                                lang=_lg_lang if '_lg_lang' in locals() else _lang,
                                numeric_support_claims=list(_delivery_result62138.get("numeric_support_claims") or []))
                        except Exception as _num_audit_exc62122:
                            _numeric_leaks62122 = [
                                f"post-control error: {type(_num_audit_exc62122).__name__}: {_num_audit_exc62122}"]
                        from utils.v62136_fr_path_maintenance import filter_numeric_leaks_dates_exempt as _flt62137
                        _dates_exempted62137 = len(_numeric_leaks62122 or [])
                        _numeric_leaks62122 = _flt62137(
                            _numeric_leaks62122, _delivery_result62138)
                        _dates_exempted62137 -= len(_numeric_leaks62122 or [])
                        if _dates_exempted62137:
                            _final_h2.report["date_only_lines_exempted_v62137"] = _dates_exempted62137
                        # v62.13.9.4.4 — gate indépendant sur le PPTX sérialisé (leçon n°16)
                        try:
                            from utils.final_surface_gate import audit_pptx_bytes as _fsg_pptx62139
                            _fsg_deck62139 = _fsg_pptx62139(_final_h2.pptx_bytes, result=_delivery_result62138)
                        except Exception as _fsg_deck_exc62139:
                            _fsg_deck62139 = [{"where": "pptx", "line": f"gate error: {type(_fsg_deck_exc62139).__name__}: {_fsg_deck_exc62139}", "reason": "gate_error"}]
                        if _fsg_deck62139:
                            _numeric_leaks62122 = list(_numeric_leaks62122 or []) + [
                                "FSG " + str(r.get("where", r.get("surface", ""))) + ": " + str(r.get("line") or r.get("text") or "")[:200]
                                for r in _fsg_deck62139[:10]]
                            _final_h2.report["final_surface_gate_residuals"] = _fsg_deck62139[:20]
                        # v62.13.9.4.49 — DOCTRINE « TOUT LIVRER, TOUT SIGNALER EN PLACE » (28/09/2026) : les
                        # constats du contrôle du deck deviennent des marqueurs « ⚠ à vérifier — motif » sur les
                        # diapositives, et la première porte le bandeau « À reprendre avant diffusion ».
                        try:
                            from utils.flag_render49 import (render_flags_in_pptx_bytes as _rfp49,
                                                             final_motif as _fm49)
                            import dataclasses as _dc49
                            _units_d49 = []
                            for _lk49 in (_numeric_leaks62122 or []):
                                _s49 = str(_lk49)
                                if _s49.startswith("post-control error") or "gate error" in _s49:
                                    continue
                                if _s49.startswith("FSG "):
                                    _s49 = _s49.split(": ", 1)[-1]
                                _units_d49.append((_s49, _fm49("board", _lang)))
                            _bytes49, _dflags49 = _rfp49(_final_h2.pptx_bytes, _units_d49, _lang)
                            _final_h2 = _dc49.replace(_final_h2, pptx_bytes=_bytes49)
                            _final_h2.report["flags"] = _dflags49
                            if _numeric_leaks62122:
                                _final_h2.report["unsupported_executive_numeric_hits"] = _numeric_leaks62122[:20]
                        except Exception as _dfl_exc49:
                            _final_h2.report["flags_error"] = f"{type(_dfl_exc49).__name__}: {_dfl_exc49}"
                    if _final_h2.distributable and not _numeric_pptx_block62122:
                        st.session_state["last_pptx"] = _final_h2.pptx_bytes
                        st.session_state["last_pptx_debug"] = None
                        if _pptx_state == "warning":
                            _layout_count = int(_final_h2.report.get("working_layout_warning_count") or 0)
                            _layout_label = (
                                f"{_layout_count} zone(s) peuvent nécessiter une reprise de mise en page"
                                if _layout_count else "des réserves éditoriales sont signalées"
                            ) if _lang == "fr" else (
                                f"{_layout_count} area(s) may need layout adjustment"
                                if _layout_count else "editorial warnings are reported"
                            )
                            st.warning(
                                (f"PPTX généré et téléchargeable — document de travail — {_layout_label}. "
                                 "Le fond et l'éditabilité priment ; le contrôle strict reste visible dans le rapport technique.")
                                if _lang == "fr" else
                                (f"Working PPTX generated and downloadable — {_layout_label}. "
                                 "Content and editability take priority; strict QA remains visible in the report.")
                            )
                    else:
                        st.session_state["last_pptx"] = None
                        st.session_state["last_pptx_debug"] = _final_h2.pptx_bytes
                        if not _numeric_pptx_block62122:
                            _block_reason621393 = _pptx_block_reason(_final_h2.report)
                            if _block_reason621393 == "package_corruption":
                                st.error(
                                    "PPTX indisponible — corruption du package détectée. Le rapport technique et un PPTX diagnostic sont disponibles plus bas."
                                    if _lang == "fr" else
                                    "PPTX unavailable — package corruption detected. The technical report and a diagnostic PPTX are available below.")
                            elif _block_reason621393 == "executive_title_truncated":
                                st.error(
                                    "PPTX retenu — un titre exécutif tronqué a été détecté. Le package OOXML est valide ; le rapport technique et un PPTX diagnostic sont disponibles plus bas."
                                    if _lang == "fr" else
                                    "PPTX withheld — a truncated executive title was detected. The OOXML package is valid; the technical report and a diagnostic PPTX are available below.")
                            else:
                                st.error(
                                    "PPTX indisponible — illisibilité majeure détectée sur un package valide. Le rapport technique et un PPTX diagnostic sont disponibles plus bas."
                                    if _lang == "fr" else
                                    "PPTX unavailable — major unreadability detected on a valid package. The technical report and a diagnostic PPTX are available below.")
                except Exception as _final_h2_err:
                    st.session_state["last_pptx"] = None
                    st.session_state["last_pptx_debug"] = _pptx_working_bytes
                    st.session_state["last_pptx_layout_report"] = {
                        "blocking": True,
                        "errors": [f"{type(_final_h2_err).__name__}:{_final_h2_err}"],
                    }
                    import logging as _lg
                    _lg.getLogger("codir_ia").exception("PPTX H-v2 finalization failed")
                # ───────────────────────────────────────────────────────────────

            # v62.13.9.4.31.1 — troisième livrable au même registre de statut
            try:
                record_pptx_delivery_status(result, st.session_state.get("last_pptx"),
                                            st.session_state.get("last_pptx_layout_report"),
                                            requested=bool(export_pptx))
            except Exception:
                pass
            if _rp54 is not None:              # 9.4.54 — fin du run : 100 %, durée mémorisée pour la durée habituelle
                try:
                    from utils.run_screen54 import record_duration as _rd54
                    _rp54.finish()
                    _rd54(_rp54.elapsed_s())
                    _render54(final57=True)            # 9.4.57 — pas de retour à l'interface avant l'écran de fin
                    st.session_state["run_screen54_done"] = True
                except Exception:
                    pass
            try:   # 9.4.65 — fin du traitement, livrables retenus ou non : le poste peut de nouveau se mettre en veille
                if _ka65 is not None:
                    _ka65.stop()
            except Exception:
                pass
            _wmsg31 = withheld_deliverables_message(result, _lang)
            if _wmsg31:
                status.update(label=(T("done_status", _lang) + (" — livrable(s) retenu(s)" if _lang == "fr" else " — deliverable(s) withheld")),
                              state="complete")
                st.warning(_wmsg31)
            else:
                status.update(label=T("done_status",_lang), state="complete")
        except Exception as e:
            try:
                if _ka65 is not None:
                    _ka65.stop()
            except Exception:
                pass
            try:
                _screen54.empty()              # 9.4.54 — l'erreur s'affiche telle quelle, sans écran figé
            except Exception:
                pass
            status.update(label=f"❌ {type(e).__name__}", state="error")
            # v16.5.76 Phase 7a (audit sécurité 25 mai 2026, VULN-6 validée
            # ChatGPT) : st.exception() expose la stack trace COMPLÈTE à
            # l'utilisateur Streamlit, ce qui peut leaker des chemins disque
            # locaux, noms de clients en mémoire, structure interne du projet,
            # parfois valeurs sensibles. On masque par défaut et on n'affiche
            # la stack qu'en mode debug explicite (CODIR_DEBUG=1) ; les détails
            # restent loggués dans codir-ia.log pour le debug post-mortem.
            try:
                from utils.logger import get_crash_logger, log_crash, flush_logger
                _crash_logger62128 = get_crash_logger(log_dir)
                log_crash(
                    _crash_logger62128,
                    "Run failed in app main",
                    exception_type=type(e).__name__,
                    exception_message=str(e),
                    run_id=str((st.session_state.get("last_result") or {}).get("run_id") or ""),
                    build=BUILD_VERSION,
                )
                flush_logger(_crash_logger62128)
            except Exception:
                pass
            if (os.environ.get("CODIR_DEBUG", "").strip().lower()
                    in ("1", "true", "yes", "on")):
                st.exception(e)
            else:
                _err_text62128 = str(e or "")
                if _err_text62128.startswith("DOCX_SAFETY_BLOCK"):
                    st.error(
                        ("❌ Word retenu : des cibles numériques non étayées subsistent après la réparation automatique. "
                         f"Les lignes exactes figurent dans diagnostics_ia et dans {crash_log_path}.")
                        if _lang == "fr" else
                        ("❌ Word withheld: unsupported quantified targets remain after automatic repair. "
                         f"The exact lines are available in diagnostics_ia and {crash_log_path}.")
                    )
                else:
                    st.error(
                        (f"❌ Erreur : {type(e).__name__}. Détails dans {crash_log_path}. "
                         "(Pour voir la stack trace immédiatement, relancer avec CODIR_DEBUG=1.)")
                        if _lang == "fr" else
                        (f"❌ Error: {type(e).__name__}. Details are available in {crash_log_path}. "
                         "(Restart with CODIR_DEBUG=1 to display the stack trace immediately.)")
                    )

    # Display last result (persisted)
    if st.session_state["last_result"]:
        r = st.session_state["last_result"]
        st.success(T("result_available", _lang))
        _end54 = st.container()          # 9.4.54 — écran de fin, rempli en bas de section (une fois le paquet construit)

        # F.5.2 (Cycle C) — UI de pilotage des actions du dossier (clôturer /
        # reporter / en cours / à arbitrer / rouvrir). Lit r["codir_history"].
        # Module isolé, fail-open : aucune erreur ne bloque l'affichage des résultats.
        try:
            from patches.codir_pilot_ui import render_action_pilot_ui as _render_pilot
            _render_pilot(r, _lang)
        except Exception:
            pass
        # Temporal Core Refactor (A5) — bandeau une-action : inférence
        # legacy VISIBLE et adoptable en réglage structuré d'un clic.
        try:
            from patches.codir_pilot_ui import (render_temporal_intent_banner
                                                as _render_tib)
            _render_tib(r, settings, _lang)
        except Exception:
            pass
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
                st.warning(T("some_roles_failed", _lang))
            with st.expander(T("diag_summary", _lang), expanded=False):
                try:
                    import pandas as _pd
                    _df_sum = _pd.DataFrame(diag_sum)
                    if "duration_s" in _df_sum.columns:
                        _df_sum["duration_s"] = _pd.to_numeric(_df_sum["duration_s"], errors="coerce")
                    st.dataframe(_df_sum, width="stretch")
                except Exception:
                    st.dataframe(diag_sum, width="stretch")
        # v62.13.9.4.12.4 — DOSSIER DE RUN, dans son PROPRE bloc.
        # Il était imbriqué dans le try du tableau de diagnostics : au rerun
        # Streamlit (déclenché par n'importe quel téléchargement), ``result``
        # sort de portée, le NameError remontait au try partagé et emportait
        # l'export CSV avec lui. Le dossier ne doit jamais pouvoir faire
        # tomber un autre export — et il doit survivre au rerun, donc il lit
        # la session quand la variable locale a disparu.
        try:
            _res62424 = None
            try:
                _res62424 = result
            except NameError:
                _res62424 = None
            if not isinstance(_res62424, dict):
                _res62424 = st.session_state.get("last_result")
            if isinstance(_res62424, dict):
                from utils.declared_quantities import export_run_dossier
                _dossier62424 = export_run_dossier(_res62424)
                with st.expander(T("run_dossier_title", _lang), expanded=False):
                    st.download_button(
                        T("run_dossier_download", _lang),
                        data=_dossier62424["payload"].encode("utf-8"),
                        file_name=_dossier62424["file_name"],
                        mime="application/json",
                        key="dl_dossier_a1_62424")
                    # v62.13.9.4.22 — PAQUET COMPLET (contre-audit v21, §10 / point 5) :
                    # les trois livrables, le dossier A1, le CSV de diagnostics, les
                    # registres exhaustifs annoncés et un manifeste SHA-256, en un zip.
                    try:
                        import zipfile as _zf62422, hashlib as _hl62422, glob as _gl62422, csv as _csv62422
                        _buf62422 = io.BytesIO()
                        _files62422: dict[str, bytes] = {}
                        _day62422 = datetime.now().strftime('%Y-%m-%d')
                        if st.session_state.get("last_docx"):
                            _files62422[f"CODIR_IA_CR_{_day62422}.docx"] = st.session_state["last_docx"]
                        if st.session_state.get("last_synthese_docx"):
                            _files62422[f"CODIR_IA_SYNTHESE_{_day62422}.docx"] = st.session_state["last_synthese_docx"]
                        if st.session_state.get("last_pptx"):
                            _files62422[f"CoDIR_IA_Synthese_{_day62422}.pptx"] = st.session_state["last_pptx"]
                        # v62.13.9.4.41 — CONTRÔLE APRÈS SÉRIALISATION. On rouvre les
                        # fichiers qui partent réellement et on compare, action par
                        # action, ce qu'ils portent à ce que l'objet portait. Un
                        # porteur ou une échéance perdus en route sont un défaut de
                        # livraison, pas un détail de mise en page.
                        try:
                            from utils.delivery_semantic_check41 import (
                                check_delivered_objects as _cdo41, empty_role_cards as _erc41)
                            _bk41 = ((_res62424.get("analysis_objects") or {}).get("by_kind") or {})
                            _docs41 = {k: v for k, v in _files62422.items()
                                       if str(k).lower().endswith((".docx", ".pptx"))}
                            try:
                                from utils.objects_render import selection_trace41 as _st41
                                _tr41 = _st41(str(_res62424.get("run_id") or ""))
                            except Exception:
                                _tr41 = []
                            _rep41 = _cdo41(_bk41, _docs41, traced=_tr41) if (_bk41 and _docs41) else {}
                            if _rep41:
                                for _n41, _b41 in _docs41.items():
                                    if str(_n41).lower().endswith(".pptx"):
                                        import io as _io41
                                        try:
                                            _rep41.setdefault("empty_role_cards", {})[_n41] = _erc41(_io41.BytesIO(_b41))
                                        except Exception:
                                            pass
                                # v62.13.9.4.48 — point 5 : les alertes portent sur les Word ; le deck
                                # (ébauche, décision du 26/09) est contrôlé et consigné, en information.
                                from utils.delivery_semantic_check41 import split_delivery_report48 as _sdr48
                                _rep41 = _sdr48(_rep41)
                                _files62422["CONTROLE_LIVRAISON.json"] = json.dumps(
                                    _rep41, ensure_ascii=False, indent=1).encode("utf-8")
                                _wa48 = _rep41.get("word_alerts") or {}
                                _lost41 = int(_wa48.get("n_lost", 0))
                                _miss41 = int(_wa48.get("n_missing", 0)) + int(_wa48.get("n_altered_or_cut", 0))
                                _deck48 = _rep41.get("deck_information") or {}
                                _empty41 = sum(len(v or []) for v in (_deck48.get("empty_role_cards") or {}).values())
                                if _rep41.get("control_failed"):
                                    st.error("Contrôle de livraison impossible : "
                                             + " ; ".join(str(x) for x in (_rep41.get("read_errors") or [])[:3]))
                                if _lost41 or _miss41:
                                    st.warning(
                                        f"Contrôle de livraison (Word) : {_miss41} objet(s) absent(s), altéré(s) ou coupé(s) sans renvoi, "
                                        f"{_lost41} attribut(s) perdu(s) entre l'analyse et les documents Word. "
                                        "Détail dans CONTROLE_LIVRAISON.json du paquet.")
                                if _empty41 or _deck48.get("n_findings"):
                                    st.info(
                                        f"Deck (ébauche, pour information) : {int(_deck48.get('n_findings', 0))} écart(s) "
                                        f"avec l'analyse, {_empty41} planche(s) de rôle sans contenu métier. "
                                        "À reprendre après lecture des Word ; détail dans CONTROLE_LIVRAISON.json.")
                        except Exception:
                            pass
                        _files62422[_dossier62424["file_name"]] = _dossier62424["payload"].encode("utf-8")
                        try:
                            _diag_rows62422 = _res62424.get("diagnostics_attempts") or []
                            _sio62422 = io.StringIO()
                            _keys62422 = sorted({k for r in _diag_rows62422 if isinstance(r, dict) for k in r.keys()})
                            _w62422 = _csv62422.DictWriter(_sio62422, fieldnames=_keys62422, extrasaction="ignore")
                            _w62422.writeheader()
                            for _r in _diag_rows62422:
                                if isinstance(_r, dict):
                                    _w62422.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v) for k, v in _r.items()})
                            _files62422["diagnostics_ia.csv"] = _sio62422.getvalue().encode("utf-8-sig")
                        except Exception:
                            pass
                        for _sc in (_res62424.get("register_sidecar"), (st.session_state.get("last_synthese_sidecar") or None)):
                            if isinstance(_sc, dict):
                                for _k in ("json", "csv"):
                                    _pth = os.path.join(str(_sc.get("dir") or "outputs"), str(_sc.get(_k) or ""))
                                    if _sc.get(_k) and os.path.isfile(_pth):
                                        with open(_pth, "rb") as _fh:
                                            _files62422["registres/" + str(_sc.get(_k))] = _fh.read()
                        if not any(k.startswith("registres/") for k in _files62422):
                            for _pth in sorted(_gl62422.glob(os.path.join("outputs", "registre_scenarios_*")))[-4:]:
                                with open(_pth, "rb") as _fh:
                                    _files62422["registres/" + os.path.basename(_pth)] = _fh.read()
                        # v62.13.9.4.23 — journal de préparation (à tenir par l'utilisateur,
                        # à la minute) : lecture, vérification, corrections dues à l'outil,
                        # préparation de la restitution. C'est la mesure du gain réel.
                        _files62422["journal_preparation.md"] = (
                            "# Journal de préparation — CoDIR IA\n\n"
                            f"Run : {_dossier62424['file_name']}\n\n"
                            "| Phase | Minutes | Notes |\n|---|---|---|\n"
                            "| Lecture du compte rendu de travail | | |\n"
                            "| Vérification (sources, chiffres) | | |\n"
                            "| Corrections dues à l'outil (phrases cassées, actions perdues — pas votre personnalisation) | | |\n"
                            "| Préparation de la restitution (synthèse, trame) | | |\n\n"
                            "Total avec CoDIR IA : ___ h — Estimation sans CoDIR IA : ___ h\n"
                        ).encode("utf-8")
                        try:
                            _ctrl62423 = (_res62424.get("meta") or {}).get("deck_layout_gate")
                            if isinstance(_ctrl62423, dict):
                                # 9.4.53 — contre-recette ChatGPT du 06/10 (T01) : les empreintes du contrôle ne
                                # correspondaient pas au PPTX livré. Le contrôle est désormais RATTACHÉ au fichier livré :
                                # empreinte finale, égalité ou non avec l'état contrôlé, et chaîne des empreintes connues.
                                _ctrl62423 = dict(_ctrl62423)
                                _pp53 = [b for n, b in _files62422.items() if str(n).lower().endswith(".pptx")]
                                if _pp53:
                                    _fin53 = _hl62422.sha256(_pp53[0]).hexdigest()
                                    _seen53 = sorted(set(__import__("re").findall(r"[0-9a-f]{64}", json.dumps(_ctrl62423))))
                                    _ctrl62423["final_pptx_sha256"] = _fin53
                                    _ctrl62423["final_equals_controlled_state"] = _fin53 in _seen53
                                    _ctrl62423["controlled_states_sha256"] = _seen53
                                    if _fin53 not in _seen53:
                                        _ctrl62423["post_control_note"] = (
                                            "Le PPTX livré diffère de l'état contrôlé : il a été retouché après le contrôle "
                                            "(signalements en place, finalisation). Contrôle à relancer sur ce fichier si un "
                                            "doute existe.")
                                _files62422[f"controle_pptx_{_day62422}.json"] = json.dumps(_ctrl62423, ensure_ascii=False, indent=2).encode("utf-8")
                        except Exception:
                            pass
                        _manifest62422 = "\n".join(f"{_hl62422.sha256(b).hexdigest()}  {n}" for n, b in sorted(_files62422.items())) + "\n"
                        with _zf62422.ZipFile(_buf62422, "w", _zf62422.ZIP_DEFLATED) as _z:
                            for _n, _b in _files62422.items():
                                _z.writestr(_n, _b)
                            _z.writestr("SHA256SUMS", _manifest62422)
                        st.download_button(
                            "Télécharger le paquet complet (3 livrables + dossier A1 + registres + manifeste, .zip)",
                            data=_buf62422.getvalue(),
                            file_name=f"CoDIR_IA_PAQUET_{_day62422}_{_dossier62424['sha256'][:8]}.zip",
                            mime="application/zip", key="dl_paquet_62422")
                        st.session_state["paquet54"] = (                     # 9.4.54 — mêmes octets pour l'écran de fin
                            _buf62422.getvalue(), f"CoDIR_IA_PAQUET_{_day62422}_{_dossier62424['sha256'][:8]}.zip")
                        _pk57 = st.session_state["paquet54"][1]
                        # 9.4.57 — seulement pour un run qui a livré au moins un document (un run bloqué ou non exécuté
                        # garde l'interface habituelle : bandeaux d'adoption, diagnostics)
                        _meta57 = ((st.session_state.get("last_result") or {}).get("meta") or {})
                        _deliv57 = bool((st.session_state.get("last_docx") or st.session_state.get("last_pptx")
                                         or st.session_state.get("last_synthese_docx"))
                                        and not _meta57.get("temporal_early_return")
                                        and _meta57.get("run_validatable", True) is not False)
                        try:   # 9.4.59 — le dossier complet est enregistré sur le disque à chaque fin de run
                            import os as _os59
                            # (jamais pendant les contrats : un paquet écrit dans l'arbre testé y serait un zip embarqué)
                            if not _os59.getenv("PYTEST_CURRENT_TEST"):
                                Path("outputs").mkdir(exist_ok=True)
                                _pp59 = Path("outputs") / _pk57
                                if not _pp59.exists():
                                    _pp59.write_bytes(st.session_state["paquet54"][0])
                                # 9.4.60 — contre-recette du 11/10 (§8.3) : le résultat de la sauvegarde est rendu visible
                                st.session_state["autosave60"] = {"ok": True, "path": str(_pp59.resolve())}
                        except Exception as _ex60:
                            st.session_state["autosave60"] = {"ok": False, "reason": f"{type(_ex60).__name__}: {_ex60}"[:200]}
                        if not _deliv57:
                            # 9.4.62 — recette du 14/10 : un run SANS livrable (bloqué, non validable, fournisseurs en échec)
                            # laissait l'écran de traitement « Dossier prêt » par-dessus l'interface, compteur en marche, et
                            # masquait la raison. L'écran est retiré : l'interface habituelle montre bandeaux et diagnostics.
                            try:
                                _screen54.empty()
                            except Exception:
                                pass
                            st.session_state["run_screen54_done"] = True
                        if _deliv57 and st.session_state.get("end57_for") != _pk57:     # 9.4.57 — écran de fin dépouillé, une fois
                            # 9.4.59 — recette 9.4.58 : l'écran de fin n'affiche pas le formulaire, et Streamlit efface la
                            # valeur d'un champ non affiché ; brief, libellé et cases sont mis de côté pour être restitués
                            # 9.4.61 — recette 9.4.60 : un BOUTON du brief (« bui_e_change ») était mis de côté puis réécrit,
                            # ce que Streamlit interdit (StreamlitValueAssignmentNotAllowedError au retour). Ne sont restitués
                            # que les champs de saisie (valeurs texte) et les deux cases du formulaire, jamais un bouton.
                            st.session_state["form59"] = {
                                k: v for k, v in st.session_state.items()
                                if isinstance(k, str) and (
                                    (k.startswith("bui_") and isinstance(v, str))
                                    or (k == "codir_dossier_label" and isinstance(v, str))
                                    or (k in ("codir_export_pptx", "codir_clean_run") and isinstance(v, bool)))}
                            st.session_state["end57_for"] = _pk57
                            st.session_state["end57_active"] = True
                            st.rerun()
                    except Exception as _pk_exc62422:
                        st.caption(f"Paquet complet indisponible : {type(_pk_exc62422).__name__}: {_pk_exc62422}")
                    _manq62424 = _dossier62424.get("pieces_manquantes") or []
                    st.caption(
                        f"SHA-256 {_dossier62424['sha256'][:16]}… · "
                        f"{_dossier62424['bytes'] // 1024} Ko"
                        + (f" · écrit dans {_dossier62424['path']}"
                           if _dossier62424.get("path") else "")
                        + (f" · pièces absentes : {', '.join(_manq62424)}"
                           if _manq62424 else " · toutes les pièces présentes"))
        except Exception as _e_dos62424:
            st.warning(
                f"Dossier de run non exporté ({type(_e_dos62424).__name__}) — "
                "le run, les livrables et l'export CSV ne sont pas affectés.")

        if diag_att:
            with st.expander(T("diag_details", _lang), expanded=False):
                try:
                    # v62.13.9.4.12.10 — le tableau et son export CSV ne
                    # dépendent plus de ``result``. Au rerun Streamlit —
                    # déclenché par n'importe quel téléchargement — cette
                    # variable locale sort de portée : le NameError faisait
                    # tomber l'affichage ET l'export CSV, alors que
                    # ``diag_att``, lu depuis la session, était disponible.
                    # Les diagnostics sont déjà dans ``diag_att`` : on ne
                    # recalcule rien pour les afficher.
                    _res62410 = None
                    try:
                        _res62410 = result
                    except NameError:
                        _res62410 = None
                    if not isinstance(_res62410, dict):
                        _res62410 = st.session_state.get("last_result")
                    if isinstance(_res62410, dict):
                        _delivery_result62138 = apply_v62136_maintenance(_res62410)
                        diag_att = (_res62410.get("diagnostics_attempts")
                                    or diag_att)
                    _df = _arrow_safe_df(diag_att)
                    st.dataframe(_df, width="stretch")
                    st.download_button(T("export_diag", _lang), data=_df.to_csv(index=False).encode("utf-8"), file_name="diagnostics_ia.csv", mime="text/csv")
                except Exception as _e_diag50:
                    # B.1.3.50 — le fallback n'affiche plus jamais le brut
                    # (le crash terrain etait DANS l'ancien except) : degrade
                    # honnete, le run et les livrables continuent.
                    st.warning(f"Table diagnostics non affichable ({type(_e_diag50).__name__}) — export CSV et livrables non affectes.")
            # Quick explanation of provider selection
            try:
                used = sorted({d.get("provider","") for d in diag_att if d.get("provider")})
                st.caption(T("providers_caption", _lang) + ": " + (", ".join(used) if used else "—"))
            except Exception:
                pass

        st.markdown(T("result_strategy", _lang))
        st.write(r["outputs"].get("strategie",""))

        st.markdown(T("result_brief_codir", _lang))
        st.write(r["outputs"].get("brief_codir",""))

        st.markdown(T("result_marketing", _lang))
        st.write(r["outputs"].get("marketing",""))

        st.markdown(T("result_finance", _lang))
        st.write(_finance_safe(r["outputs"].get("finance",""), result=r, lang=_lang))

        _sc_ui_txt = r["outputs"].get("supply_chain", "") or ""
        _sc_ui_status = (r.get("meta", {}) or {}).get("supply_chain_status", "")
        _sc_ui_clean = _get_sc_display_text(_sc_ui_txt, _sc_ui_status)
        if _sc_ui_clean:
            st.markdown(T("result_sc", _lang))
            st.write(_sc_ui_clean)

        st.markdown(T("result_commercial", _lang))
        st.write(r["outputs"].get("commercial",""))

        st.markdown(T("result_synthesis", _lang))
        st.write(r["outputs"].get("synthese_decisions",""))

        st.markdown(T("ceo_synthesis_header",_lang))
        st.write(r["outputs"].get("direction_generale",""))

        _wmsg31_ui = withheld_deliverables_message(r, _lang)       # v62.13.9.4.31.1
        if _wmsg31_ui:
            st.warning(_wmsg31_ui)
        c1, c2 = st.columns([1,1])
        with c1:
            if st.session_state["last_docx"]:
                st.download_button(
                    T("download_docx",_lang),
                    data=st.session_state["last_docx"],
                    file_name=f"CODIR_IA_CR_{datetime.now().strftime('%Y-%m-%d')}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            elif st.session_state.get("last_docx_error"):
                st.caption(("Compte rendu (Word de travail) non produit : retenu par le contrôle final — "
                            "les lignes exactes figurent dans diagnostics_ia et dans le journal de crash.")
                           if _lang == "fr" else
                           ("Working report (Word) not produced: withheld by the final check — "
                            "the exact lines are in diagnostics_ia and the crash log."))
            if st.session_state.get("last_synthese_docx"):          # v62.13.9.4.21
                st.download_button(
                    ("📄 Télécharger la synthèse (.docx)" if _lang != "en" else "📄 Download the synthesis (.docx)"),
                    data=st.session_state["last_synthese_docx"],
                    file_name=f"CODIR_IA_SYNTHESE_{datetime.now().strftime('%Y-%m-%d')}.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            elif st.session_state.get("last_synthese_error"):
                st.caption(f"Synthèse non produite : {st.session_state.get('last_synthese_error')}")
        with c2:
            if st.session_state["last_pptx"]:
                st.download_button(
                    T("download_pptx",_lang),
                    data=st.session_state["last_pptx"],
                    file_name=f"CoDIR_IA_Synthese_{datetime.now().strftime('%Y-%m-%d')}.pptx",
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )

        _pptx_report = st.session_state.get("last_pptx_layout_report")
        if isinstance(_pptx_report, dict) and _pptx_report:
            _pptx_state_ui = (
                "analysis_blocked" if _pptx_report.get("analysis_blocked") else
                "blocked" if _pptx_report.get("blocking") else
                "warning" if _pptx_report.get("quality_warning") else "ok")
            _label_report = (
                "🧪 Contrôle qualité PPTX — rapport technique" if _lang == "fr"
                else "🧪 PPTX quality control — technical report"
            )
            with st.expander(_label_report, expanded=(_pptx_state_ui == "blocked")):
                if _pptx_state_ui == "ok":
                    st.success("PPTX de travail prêt — ouvrable, éditable et sans anomalie majeure."
                               if _lang == "fr" else
                               "Working PPTX ready — openable, editable and free of major anomalies.")
                elif _pptx_state_ui == "analysis_blocked":
                    st.error("Run métier non exécuté — seule une slide locale de diagnostic a été générée. "
                             "Aucun Working Deck n'est disponible."
                             if _lang == "fr" else
                             "Business run not executed — only a local diagnostic slide was generated. "
                             "No Working Deck is available.")
                elif _pptx_state_ui == "warning":
                    st.warning("PPTX de travail disponible avec réserves de mise en page non bloquantes."
                               if _lang == "fr" else
                               "Working PPTX available with non-blocking layout findings.")
                else:
                    st.error("PPTX bloqué uniquement pour corruption ou illisibilité majeure."
                             if _lang == "fr" else
                             "PPTX blocked only for corruption or major unreadability.")
                st.json(_pptx_report)
                _report_bytes = json.dumps(
                    _pptx_report, ensure_ascii=False, indent=2, default=str
                ).encode("utf-8")
                st.download_button(
                    "Télécharger le rapport PPTX (JSON)" if _lang == "fr" else
                    "Download PPTX report (JSON)",
                    data=_report_bytes,
                    file_name=f"controle_pptx_{datetime.now().strftime('%Y-%m-%d')}.json",
                    mime="application/json",
                    key="download_pptx_layout_report",
                )
                _debug_pptx = st.session_state.get("last_pptx_debug")
                if _pptx_state_ui in ("blocked", "analysis_blocked") and _debug_pptx:
                    st.download_button(
                        ("Télécharger la slide de diagnostic — RUN NON EXÉCUTÉ"
                         if _pptx_state_ui == "analysis_blocked" else
                         "Télécharger le PPTX diagnostic — NON DISTRIBUABLE")
                        if _lang == "fr" else
                        ("Download diagnostic slide — RUN NOT EXECUTED"
                         if _pptx_state_ui == "analysis_blocked" else
                         "Download diagnostic PPTX — NOT DISTRIBUTABLE"),
                        data=_debug_pptx,
                        file_name=(f"CoDIR_IA_RUN_BLOQUE_{datetime.now().strftime('%Y-%m-%d')}.pptx"
                                   if _pptx_state_ui == "analysis_blocked" else
                                   f"CoDIR_IA_DIAGNOSTIC_NON_DISTRIBUABLE_{datetime.now().strftime('%Y-%m-%d')}.pptx"),
                        mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                        key="download_pptx_debug",
                    )

        # 9.4.54 — écran de fin (maquettes 2/3 et 3/3 validées le 08/09/2026), affiché en tête des résultats
        try:
            from utils.run_screen54 import render_end_screen as _res54
            _d54 = datetime.now().strftime('%Y-%m-%d')
            _res54(st, _lang, st.session_state.get("last_result"), st.session_state.get("paquet54"),
                   (st.session_state.get("last_docx"), f"CODIR_IA_CR_{_d54}.docx"),
                   (st.session_state.get("last_synthese_docx"), f"CODIR_IA_SYNTHESE_{_d54}.docx"),
                   (st.session_state.get("last_pptx"), f"CoDIR_IA_Synthese_{_d54}.pptx"),
                   logo_b64=_logo_b64_54(), container=_end54)
        except Exception as _e54:
            st.caption(f"Écran de fin indisponible : {type(_e54).__name__}")

elif page == "free":
    st.subheader(T("free_mode_header", _lang))

    system = st.text_area(T("free_system_prompt", _lang), height=120)
    user_prompt = st.text_area(T("free_message", _lang), height=200, value=("Hello everyone! Please give a brief introduction." if _lang=="en" else "Bonjour à tous ! Faites une courte présentation."))

    cols = st.columns(6)
    with cols[0]: chk_openai = st.checkbox("OpenAI", True)
    with cols[1]: chk_gemini = st.checkbox("Gemini", True)
    with cols[2]: chk_claude = st.checkbox("Claude", True)
    with cols[3]: chk_mistral = st.checkbox("Mistral", True)
    with cols[4]: chk_perplexity = st.checkbox("Perplexity", False)
    with cols[5]: chk_grok = st.checkbox("Grok", False)

    run_btn = st.button(T("free_run_btn",_lang), type="primary")
    if run_btn:
        providers = [p for p, b in [
            ("OpenAI", chk_openai), ("Gemini", chk_gemini), ("Claude", chk_claude),
            ("Mistral", chk_mistral), ("Perplexity", chk_perplexity), ("Grok", chk_grok),
        ] if b]
        with st.status(T("free_running",_lang), state="running") as status:
            res = run_free_mode(user_prompt, system=system, providers=providers, temperature=float(temperature), max_tokens=int(max_tokens))
            status.update(label=T("done_status",_lang), state="complete")

        for p, out in res.items():
            st.markdown(f"### {p}")
            st.write(out)

        md = [T("free_compare_header",_lang), f"_Date: {datetime.now().isoformat(timespec='seconds')}_", ""]
        for p, out in res.items():
            md.append(f"## {p}\n{out}\n")
        st.download_button(
            T("download_md",_lang),
            data="\n".join(md).encode("utf-8"),
            file_name=f"{T('free_file_name', _lang)}_{datetime.now().strftime('%Y-%m-%d')}.md",
            mime="text/markdown",
        )

elif page == "config":
    st.subheader(T("config_keys_section", _lang))

    # Feedback sauvegarde affiché directement dans le form (pas via session state)

    # ── Expander debug : résolution Pappers + historique + coûts ────────────
    _last_res = st.session_state.get("last_result")
    _pap_rlog = (_last_res.get("pappers_resolution_log") if isinstance(_last_res, dict) else None)

    try:
        from utils.pappers_sessions import load_recent_sessions, session_cost_summary
        _pap_history = load_recent_sessions(10)
        _pap_summary = session_cost_summary(10)
    except Exception:
        _pap_history, _pap_summary = [], {}

    _has_pap_data = bool((_pap_rlog and isinstance(_pap_rlog, dict) and _pap_rlog.get("path"))
                         or _pap_history)
    if _has_pap_data:
        with st.expander(
            "🔍 " + ("Résolution Pappers — audit & métriques" if _lang == "fr"
                     else "Pappers — audit & metrics"),
            expanded=False
        ):
            # ── Dernière session ──────────────────────────────────────────────
            if _pap_rlog and isinstance(_pap_rlog, dict) and _pap_rlog.get("path"):
                st.markdown("**" + ("Dernière session" if _lang=="fr" else "Last session") + "**")
                _col1, _col2, _col3 = st.columns(3)
                with _col1:
                    st.metric("Path",   _pap_rlog.get("path", "—"))
                    st.metric("Source", _pap_rlog.get("source", "—"))
                with _col2:
                    st.metric("SIREN", _pap_rlog.get("siren_used") or "—")
                    st.metric("Entité" if _lang=="fr" else "Entity",
                              _pap_rlog.get("primary_name") or "—")
                with _col3:
                    _cr = _pap_rlog.get("pappers_credits_est") or "—"
                    st.metric("Crédits Pappers ≈", _cr)
                    st.metric("Cache hit", "✅" if _pap_rlog.get("cache_hit") else "❌")
                _col4, _col5, _col6 = st.columns(3)
                with _col4:
                    st.metric("Tokens full ≈",    _pap_rlog.get("tokens_est_full", 0))
                with _col5:
                    st.metric("Tokens summary ≈", _pap_rlog.get("tokens_est_summary", 0))
                with _col6:
                    _age = _pap_rlog.get("cache_age_h")
                    st.metric("Âge cache" if _lang=="fr" else "Cache age",
                              f"{_age}h" if _age is not None else "—")
                if _pap_rlog.get("secondaries"):
                    st.caption(("Entités secondaires" if _lang == "fr" else "Secondary entities")
                               + " : " + ", ".join(_pap_rlog["secondaries"]))
                if _pap_rlog.get("entities_not_found"):
                    st.warning(("Non trouvées" if _lang == "fr" else "Not found")
                               + " : " + str(_pap_rlog["entities_not_found"]))
                st.caption(_pap_rlog.get("timestamp", ""))

            # ── Résumé coûts 10 dernières sessions ───────────────────────────
            if _pap_summary.get("sessions", 0) > 0:
                st.divider()
                st.markdown("**" + (f"Métriques — {_pap_summary['sessions']} dernières sessions"
                                    if _lang=="fr" else
                                    f"Metrics — last {_pap_summary['sessions']} sessions") + "**")
                _mc1, _mc2, _mc3, _mc4 = st.columns(4)
                with _mc1:
                    st.metric("Crédits total ≈", _pap_summary.get("total_credits_est", 0))
                with _mc2:
                    st.metric("Crédits / session ≈", _pap_summary.get("avg_credits", 0))
                with _mc3:
                    st.metric("Tokens full / session ≈", _pap_summary.get("avg_tokens_full", 0))
                with _mc4:
                    st.metric("Cache hit rate", f"{_pap_summary.get('cache_hit_rate', 0)} %")

            # ── Tableau historique ────────────────────────────────────────────
            if _pap_history:
                st.divider()
                st.markdown("**" + ("Historique récent" if _lang=="fr" else "Recent history") + "**")
                import pandas as _pd
                _rows = []
                for _e in _pap_history[:10]:
                    _rows.append({
                        ("Session" if _lang=="fr" else "Session"):   _e.get("timestamp", "")[:19],
                        "Path":       _e.get("path", ""),
                        ("Entité" if _lang=="fr" else "Entity"):     _e.get("primary_name", ""),
                        "SIREN":      _e.get("siren_used", ""),
                        "Cache":      "✅" if _e.get("cache_hit") else "❌",
                        ("Crédits ≈" if _lang=="fr" else "Credits ≈"): _e.get("pappers_credits_est", ""),
                        ("Tokens full" if _lang=="fr" else "Tokens full"): _e.get("tokens_est_full", 0),
                    })
                try:
                    st.dataframe(_pd.DataFrame(_rows), use_container_width=True, hide_index=True)
                except Exception:
                    for _r in _rows:
                        st.text(str(_r))

                _jpath = "outputs/pappers_sessions.jsonl"
                st.caption(f"Journal : `{_jpath}`")

    # ── Avertissement si seulement Pappers (pas de clé LLM) ─────────────────
    _cfg_secrets = load_secrets()
    if has_any_key(_cfg_secrets) and not has_llm_key(_cfg_secrets):
        st.warning(
            "⚠️ **" + ("Clé Pappers configurée" if _lang == "fr" else "Pappers key configured") + "** — "
            + ("Configurez au moins une clé LLM (OpenAI, Claude, Gemini…) pour lancer des sessions CoDIR."
               if _lang == "fr" else
               "Configure at least one LLM key (OpenAI, Claude, Gemini…) to run CoDIR sessions.")
        )

    st.markdown(T("local_paths_section", _lang))
    st.code(f"secrets.json: {get_secrets_path()}\nsettings.json: {get_settings_path()}\nlogs: {log_dir}\ncrash log: {crash_log_path}")

    secrets = load_secrets()
    _seed_secret_widget_state(secrets)
    settings = load_settings()

    st.markdown(T("api_keys_section",_lang))
    with st.form("secrets_form"):
        st.markdown(f"**{T('providers_section', _lang)}**")
        openai_api_key     = st.text_input(T("openai_key_label", _lang), type="password", key=_SECRET_WIDGET_KEYS["openai"])
        anthropic_api_key  = st.text_input(T("anthropic_key_label",_lang), type="password", key=_SECRET_WIDGET_KEYS["anthropic"])
        google_api_key     = st.text_input(T("google_key_label", _lang), type="password", key=_SECRET_WIDGET_KEYS["google"])
        mistral_api_key    = st.text_input(T("mistral_key_label",_lang), type="password", key=_SECRET_WIDGET_KEYS["mistral"])
        st.markdown(f"**{T('new_providers', _lang)}**")
        perplexity_api_key = st.text_input(T("perplexity_key_label",_lang), type="password", key=_SECRET_WIDGET_KEYS["perplexity"],
                                           help=T("perplexity_key_help",_lang))
        grok_api_key       = st.text_input(T("grok_key_label", _lang), type="password", key=_SECRET_WIDGET_KEYS["grok"],
                                           help=T("grok_key_help",_lang))
        st.markdown("---")
        st.markdown(f"**🏢 Pappers — {'Enrichissement données entreprises' if _lang == 'fr' else 'Company data enrichment'}**")
        pappers_api_key    = st.text_input(T("pappers_key_label", _lang), type="password", key=_SECRET_WIDGET_KEYS["pappers"],
                                           help=T("pappers_key_help", _lang))

        # ── Since v16.5.68 — Sources de données / API externes additionnelles ──
        st.markdown("---")
        st.markdown(T("external_sources_section", _lang))
        st.caption(T("external_sources_intro", _lang))
        # Since v16.5.69 — Message sécurité clés stockées localement
        st.info(T("external_sources_security_notice", _lang))
        # SEC EDGAR — pas de clé, juste un User-Agent
        sec_edgar_user_agent = st.text_input(
            T("sec_edgar_ua_label", _lang),
            key=_SECRET_WIDGET_KEYS["sec_edgar_ua"],
            help=T("sec_edgar_ua_help", _lang),
            placeholder=T("sec_edgar_ua_placeholder", _lang),
        )
        # OpenSanctions — clé requise
        opensanctions_api_key = st.text_input(
            T("opensanctions_label", _lang),
            type="password",
            key=_SECRET_WIDGET_KEYS["opensanctions"],
            help=T("opensanctions_help", _lang),
        )
        # Companies House — clé requise
        companies_house_api_key = st.text_input(
            T("companies_house_label", _lang),
            type="password",
            key=_SECRET_WIDGET_KEYS["companies_house"],
            help=T("companies_house_help", _lang),
        )
        # Companies House Document API — Patch v16.5.69 :
        # 1 clé par défaut (la Public Data ci-dessus est utilisée par fallback gracieux),
        # 2ᵉ clé en option avancée seulement (checkbox cachée par défaut).
        # Le pré-cochage de la checkbox dépend de l'existence d'une clé Document explicite.
        _ch_doc_pre_checked = bool(
            (st.session_state.get(_SECRET_WIDGET_KEYS["companies_house_document"]) or "").strip()
        )
        _use_separate_doc_key = st.checkbox(
            T("ch_doc_advanced_checkbox", _lang),
            value=_ch_doc_pre_checked,
            key="cfg_use_separate_ch_doc_key",
            help=T("ch_doc_advanced_help", _lang),
        )
        if _use_separate_doc_key:
            companies_house_document_api_key = st.text_input(
                T("companies_house_doc_label", _lang),
                type="password",
                key=_SECRET_WIDGET_KEYS["companies_house_document"],
                help=T("companies_house_doc_help", _lang),
            )
        else:
            # Patch v16.5.69.1 (audit ChatGPT) — Reset explicite de la clé Document.
            # Bug détecté en v16.5.69.1 : si l'utilisateur avait saisi une clé
            # Document API puis décochait la checkbox pour revenir au fallback,
            # l'ancienne valeur restait en session_state et donc en secrets.json.
            # Comme _document_api_key() priorise COMPANIES_HOUSE_DOCUMENT_API_KEY
            # sur COMPANIES_HOUSE_API_KEY, le fallback ne s'appliquait JAMAIS.
            # Conséquence : utilisateur croit utiliser le fallback Public Data,
            # mais utilise toujours l'ancienne clé Doc invalide.
            #
            # Correction : décocher la checkbox vide explicitement la clé Document.
            # L'utilisateur reprend ainsi le contrôle conscient.
            companies_house_document_api_key = ""
            # Effacer aussi du widget state pour cohérence visuelle au rerun
            st.session_state[_SECRET_WIDGET_KEYS["companies_house_document"]] = ""
            st.caption(T("ch_doc_fallback_caption", _lang))
        # GLEIF — pas de saisie (no key, no UA), juste mention
        st.caption(
            ("ℹ️ GLEIF / LEI ne nécessite aucune clé — accès direct aux données LEI mondiales."
             if _lang == "fr" else
             "ℹ️ GLEIF / LEI requires no key — direct access to worldwide LEI data.")
        )

        saved = st.form_submit_button(T("save_keys", _lang))
        if saved:
            new_s = Secrets(
                openai_api_key=openai_api_key,
                anthropic_api_key=anthropic_api_key,
                google_api_key=google_api_key,
                mistral_api_key=mistral_api_key,
                perplexity_api_key=perplexity_api_key,
                grok_api_key=grok_api_key,
                pappers_api_key=pappers_api_key,
                # Since v16.5.68 — sources externes additionnelles
                opensanctions_api_key=opensanctions_api_key,
                companies_house_api_key=companies_house_api_key,
                companies_house_document_api_key=companies_house_document_api_key,
                sec_edgar_user_agent=sec_edgar_user_agent,
            )
            try:
                save_secrets(new_s)
                apply_secrets_to_env(load_secrets(), override=True)
                # Les widgets seront re-seedés au prochain rerun via _seed_secret_widget_state(secrets)
                # appelé AVANT st.form(...) — c'est là que Streamlit permet la modification
                st.session_state["config_dialog_shown"] = True
                st.session_state["nav_page"] = "config"
                st.rerun()
            except Exception as _save_err:
                st.error(
                    f"{'Erreur lors de la sauvegarde' if _lang=='fr' else 'Error saving keys'} : {_save_err}\n"
                    f"Chemin cible : {get_secrets_path()}"
                )

    # Statut Pappers
    try:
        from utils.pappers_tool import get_pappers_status
        _pst = get_pappers_status()
        if _pst["configured"]:
            _mode = ("🧠 Pré-filtre Claude actif" if _lang == "fr" else "🧠 Claude pre-filter active") if _pst.get("has_claude") else ("⚠️ Mode fallback heuristique (ANTHROPIC_API_KEY absente)" if _lang == "fr" else "⚠️ Fallback mode (ANTHROPIC_API_KEY missing)")
            st.info(T("pappers_status_ok", _lang) + f"  `{_pst['key_preview']}`  —  {_mode}")
        else:
            st.caption(T("pappers_status_ko", _lang))
    except Exception:
        pass

    # ── Since v16.5.68 — Tableau de statut unifié des sources externes ────────
    try:
        from utils.external_sources_common import (
            EXTERNAL_SOURCES_CATALOG, make_key_preview, load_test_result,
        )
        _cfg_secrets_for_status = load_secrets()
        _source_keys = {
            "pappers":                  _cfg_secrets_for_status.pappers_api_key,
            "gleif":                    "",  # no key required
            "sec_edgar":                _cfg_secrets_for_status.sec_edgar_user_agent,
            "opensanctions":            _cfg_secrets_for_status.opensanctions_api_key,
            "companies_house":          _cfg_secrets_for_status.companies_house_api_key,
            "companies_house_document": _cfg_secrets_for_status.companies_house_document_api_key,
        }
        with st.expander(
            "🌐 " + ("Statut des sources de données externes" if _lang == "fr"
                     else "External data sources status"),
            expanded=False,
        ):
            _src_label_keys = {
                "pappers":                  "external_sources_pappers",
                "gleif":                    "external_sources_gleif",
                "sec_edgar":                "external_sources_sec_edgar",
                "opensanctions":            "external_sources_opensanctions",
                "companies_house":          "external_sources_companies_house",
                "companies_house_document": "external_sources_companies_house_document",
            }
            for _sid in ("pappers", "gleif", "sec_edgar", "opensanctions",
                         "companies_house", "companies_house_document"):
                _meta = EXTERNAL_SOURCES_CATALOG.get(_sid, {})
                _val  = (_source_keys.get(_sid) or "").strip()
                _col_a, _col_b = st.columns([3, 2])
                with _col_a:
                    st.markdown(T(_src_label_keys[_sid], _lang))
                with _col_b:
                    if not _meta.get("requires_key", True) and not _meta.get("requires_user_agent", False):
                        # GLEIF : ni clé ni UA requis
                        st.caption(T("ext_status_no_key_needed", _lang))
                    elif _meta.get("requires_user_agent", False):
                        # SEC EDGAR : User-Agent
                        if _val:
                            st.caption(T("ext_status_ua_set", _lang) + f"  `{_val[:30]}{'…' if len(_val) > 30 else ''}`")
                        else:
                            st.caption(T("ext_status_ua_missing", _lang))
                    else:
                        # Pappers, OpenSanctions, Companies House : clé
                        if _val:
                            st.caption(T("ext_status_configured", _lang) + f"  `{make_key_preview(_val)}`")
                        else:
                            st.caption(T("ext_status_not_configured", _lang))
                # Dernier test de connexion s'il existe
                _last = load_test_result(_sid)
                if _last:
                    _icon = "✅" if _last.get("ok") else "❌"
                    _ts   = (_last.get("at") or "")[:19].replace("T", " ")
                    st.caption(f"{_icon} {('Dernier test' if _lang=='fr' else 'Last test')} : {_ts} — {_last.get('message', '')[:120]}")

            # ── Since v16.5.68 — Boutons de test pour les sources externes ─────
            st.markdown("---")
            st.markdown(("**Tester la connexion**" if _lang == "fr" else "**Test connection**"))
            _ext_test_cols = st.columns(6)
            # Pappers (FR) — premier car c'est la source historique
            with _ext_test_cols[0]:
                if st.button(T("ext_test_btn", _lang).format(label="Pappers"), key="ext_testbtn_pappers"):
                    st.session_state["nav_page"] = "config"
                    try:
                        apply_secrets_to_env(load_secrets(), override=True)
                        from utils.pappers_tool import test_connection as _pap_test
                        _r = _pap_test()
                        st.session_state["_test_results"]["__pappers__"] = (
                            "ok" if _r.get("ok") else "err", _r.get("message", "")[:120],
                        )
                    except Exception as _e:
                        st.session_state["_test_results"]["__pappers__"] = ("err", str(_e)[:120])
                    st.rerun()
                if "__pappers__" in st.session_state.get("_test_results", {}):
                    _st, _msg = st.session_state["_test_results"]["__pappers__"]
                    (st.success if _st == "ok" else st.error)(_msg)
            # GLEIF
            with _ext_test_cols[1]:
                if st.button(T("ext_test_btn", _lang).format(label="GLEIF"), key="ext_testbtn_gleif"):
                    st.session_state["nav_page"] = "config"
                    try:
                        from utils.gleif_tool import test_connection as _gleif_test
                        _r = _gleif_test()
                        st.session_state["_test_results"]["__gleif__"] = (
                            "ok" if _r.get("ok") else "err", _r.get("message", "")[:120],
                        )
                    except Exception as _e:
                        st.session_state["_test_results"]["__gleif__"] = ("err", str(_e)[:120])
                    st.rerun()
                if "__gleif__" in st.session_state.get("_test_results", {}):
                    _st, _msg = st.session_state["_test_results"]["__gleif__"]
                    (st.success if _st == "ok" else st.error)(_msg)
            # SEC EDGAR
            with _ext_test_cols[2]:
                if st.button(T("ext_test_btn", _lang).format(label="SEC EDGAR"), key="ext_testbtn_sec"):
                    st.session_state["nav_page"] = "config"
                    try:
                        apply_secrets_to_env(load_secrets(), override=True)
                        from utils.sec_edgar_tool import test_connection as _sec_test
                        _r = _sec_test()
                        st.session_state["_test_results"]["__sec_edgar__"] = (
                            "ok" if _r.get("ok") else "err", _r.get("message", "")[:120],
                        )
                    except Exception as _e:
                        st.session_state["_test_results"]["__sec_edgar__"] = ("err", str(_e)[:120])
                    st.rerun()
                if "__sec_edgar__" in st.session_state.get("_test_results", {}):
                    _st, _msg = st.session_state["_test_results"]["__sec_edgar__"]
                    (st.success if _st == "ok" else st.error)(_msg)
            # OpenSanctions
            with _ext_test_cols[3]:
                if st.button(T("ext_test_btn", _lang).format(label="OpenSanctions"), key="ext_testbtn_os"):
                    st.session_state["nav_page"] = "config"
                    try:
                        apply_secrets_to_env(load_secrets(), override=True)
                        from utils.opensanctions_tool import test_connection as _os_test
                        _r = _os_test()
                        st.session_state["_test_results"]["__opensanctions__"] = (
                            "ok" if _r.get("ok") else "err", _r.get("message", "")[:120],
                        )
                    except Exception as _e:
                        st.session_state["_test_results"]["__opensanctions__"] = ("err", str(_e)[:120])
                    st.rerun()
                if "__opensanctions__" in st.session_state.get("_test_results", {}):
                    _st, _msg = st.session_state["_test_results"]["__opensanctions__"]
                    (st.success if _st == "ok" else st.error)(_msg)
            # Companies House (Public Data)
            with _ext_test_cols[4]:
                if st.button(T("ext_test_btn", _lang).format(label="CH Public Data"), key="ext_testbtn_ch"):
                    st.session_state["nav_page"] = "config"
                    try:
                        apply_secrets_to_env(load_secrets(), override=True)
                        from utils.companies_house_tool import test_connection as _ch_test
                        _r = _ch_test()
                        st.session_state["_test_results"]["__companies_house__"] = (
                            "ok" if _r.get("ok") else "err", _r.get("message", "")[:120],
                        )
                    except Exception as _e:
                        st.session_state["_test_results"]["__companies_house__"] = ("err", str(_e)[:120])
                    st.rerun()
                if "__companies_house__" in st.session_state.get("_test_results", {}):
                    _st, _msg = st.session_state["_test_results"]["__companies_house__"]
                    (st.success if _st == "ok" else st.error)(_msg)
            # Companies House (Document API) — clé séparée
            with _ext_test_cols[5]:
                if st.button(T("ext_test_btn", _lang).format(label="CH Document"), key="ext_testbtn_ch_doc"):
                    st.session_state["nav_page"] = "config"
                    try:
                        apply_secrets_to_env(load_secrets(), override=True)
                        from utils.companies_house_tool import test_connection_document as _ch_doc_test
                        _r = _ch_doc_test()
                        st.session_state["_test_results"]["__companies_house_document__"] = (
                            "ok" if _r.get("ok") else "err", _r.get("message", "")[:120],
                        )
                    except Exception as _e:
                        st.session_state["_test_results"]["__companies_house_document__"] = ("err", str(_e)[:120])
                    st.rerun()
                if "__companies_house_document__" in st.session_state.get("_test_results", {}):
                    _st, _msg = st.session_state["_test_results"]["__companies_house_document__"]
                    (st.success if _st == "ok" else st.error)(_msg)
            # v62.13.9.4.50 — TESTER LA LECTURE (décision Robin du 01/10/2026) : au-delà de l'accès, vérifie que les
            # lectures nouvelles rendent des faits datés sur un témoin public (rien n'est conservé)
            st.markdown(("**Tester la lecture des montants publiés**" if _lang == "fr" else "**Test reading published amounts**"))
            _rd_cols50 = st.columns(3)
            _ch_num50 = st.text_input(("Numéro Companies House pour le test (société britannique)" if _lang == "fr"
                                       else "Companies House number for the test (UK company)"),
                                      value=st.session_state.get("_ch_test_number50", ""), key="_ch_test_number50")
            for _col50, (_key50, _lbl50) in zip(_rd_cols50, (("sec", "SEC — 10-K"), ("pappers", "Pappers — finances"),
                                                           ("ch", "Companies House — iXBRL"))):
                with _col50:
                    if st.button(((f"Tester la lecture {_lbl50}") if _lang == "fr" else (f"Test reading {_lbl50}")),
                                 key=f"readtest50_{_key50}"):
                        st.session_state["nav_page"] = "config"
                        try:
                            apply_secrets_to_env(load_secrets(), override=True)
                            from utils import external_facts50 as _xf50
                            _r50 = (_xf50.test_reading_sec(lang=_lang) if _key50 == "sec" else
                                    _xf50.test_reading_pappers(lang=_lang) if _key50 == "pappers" else
                                    _xf50.test_reading_companies_house(_ch_num50, lang=_lang))
                            st.session_state["_test_results"][f"__read50_{_key50}__"] = (
                                "ok" if _r50.get("ok") else ("info" if _r50.get("ok") is None else "err"),
                                str(_r50.get("message", ""))[:200])
                        except Exception as _e50:
                            st.session_state["_test_results"][f"__read50_{_key50}__"] = ("err", str(_e50)[:160])
                        st.rerun()
                    if f"__read50_{_key50}__" in st.session_state.get("_test_results", {}):
                        _st50, _msg50 = st.session_state["_test_results"][f"__read50_{_key50}__"]
                        (st.success if _st50 == "ok" else st.info if _st50 == "info" else st.error)(_msg50)
    except Exception as _ext_e:
        st.caption(f"_(external sources status unavailable: {str(_ext_e)[:80]})_")
    # ──────────────────────────────────────────────────────────────────────────

    # ── Since v16.5.69 — Téléchargement filings UK (Companies House Document) ─
    try:
        from utils.companies_house_tool import (
            get_documents_cache_info, get_session_doc_counter, clear_documents_cache,
        )
        from utils.settings_store import save_settings
        st.markdown("---")
        st.markdown(T("ch_filings_dl_section", _lang))

        # Checkbox d'activation — persisté dans settings
        _ch_dl_enabled = st.checkbox(
            T("ch_filings_dl_enable", _lang),
            value=getattr(settings, "enable_uk_filings_download", False),
            key="cfg_enable_uk_filings_download",
            help=T("ch_filings_dl_help", _lang),
        )
        # Si la valeur a changé, persister
        if _ch_dl_enabled != getattr(settings, "enable_uk_filings_download", False):
            settings.enable_uk_filings_download = _ch_dl_enabled
            try:
                save_settings(settings)
            except Exception:
                pass

        # Statut du cache + compteur session
        _info = get_documents_cache_info()
        _sess = get_session_doc_counter()
        st.caption(T("ch_filings_dl_status", _lang).format(
            count=_info["count"],
            size_mb=_info["total_size_mb"],
            session_count=_sess["count"],
            session_max=_sess["max"],
        ))

        # Bouton clear cache
        if st.button(T("ch_filings_dl_clear_btn", _lang), key="ch_filings_clear_btn"):
            _cleared = clear_documents_cache()
            st.success(T("ch_filings_dl_cleared", _lang).format(
                n=_cleared["count_deleted"],
                mb=_cleared["total_size_freed_mb"],
            ))
    except Exception as _ch_dl_e:
        st.caption(f"_(UK filings download UI unavailable: {str(_ch_dl_e)[:80]})_")
    # ──────────────────────────────────────────────────────────────────────────

    st.markdown(T("test_key_section",_lang))

    # Initialiser le stockage des résultats de test dans session_state
    if "_test_results" not in st.session_state:
        st.session_state["_test_results"] = {}

    c1, c2, c3, c4, c5, c6 = st.columns(6)

    def test_btn(label, prov, col):
        with col:
            if st.button(T("test_btn_label", _lang).format(label=label), key=f"testbtn_{prov}"):
                # Rester sur la page config
                st.session_state["nav_page"] = "config"
                try:
                    apply_secrets_to_env(load_secrets(), override=True)
                    out = _test_provider(prov, load_secrets(), load_settings())
                    msg = out.get("output", "OK")[:80] if isinstance(out, dict) else str(out)[:80]
                    st.session_state["_test_results"][prov] = ("ok", msg or "OK ✓")
                except Exception as e:
                    from utils.provider_errors50 import explain_provider_error as _epe50
                    st.session_state["_test_results"][prov] = ("err", _epe50(prov, str(e), _lang)[:260])
                st.rerun()
            # Afficher le résultat persisté
            if prov in st.session_state["_test_results"]:
                status, msg = st.session_state["_test_results"][prov]
                if status == "ok":
                    st.success(msg)
                else:
                    st.error(msg)

    test_btn("OpenAI",      "openai",      c1)
    test_btn("Claude",      "anthropic",   c2)
    test_btn("Gemini",      "google",      c3)
    test_btn("Mistral",     "mistral",     c4)
    test_btn("Perplexity",  "perplexity",  c5)
    test_btn("Grok",        "grok",        c6)

    st.markdown("---")
    st.markdown(f"### {T('models_section', _lang)}")
    with st.form("models_form"):
        st.markdown(f"**{T('providers_section', _lang)}**")
        openai_model_id     = st.text_input("OpenAI model_id",          value=settings.openai_model_id)
        google_model_id     = st.text_input("Google/Gemini model_id",    value=settings.google_model_id)
        anthropic_model_id  = st.text_input("Anthropic model_id",        value=settings.anthropic_model_id)
        mistral_model_id    = st.text_input("Mistral model_id",          value=settings.mistral_model_id)
        st.markdown(f"**{T('new_providers', _lang)}**")
        perplexity_model_id = st.text_input("Perplexity model_id",       value=settings.perplexity_model_id,
                                            help="perplexity/sonar (API Agent)")
        grok_model_id       = st.text_input("Grok / xAI model_id",       value=settings.grok_model_id,
                                            help="grok-4.3")
        # v62.13.9.4.50 — une variable d'environnement remplace le réglage saisi ici : on le dit, avec le modèle
        # réellement appelé (après migration d'un éventuel modèle retiré)
        try:
            from utils.settings_store import env_model_override as _emo50
            for _prov50, _lbl50 in (("anthropic", "Anthropic"), ("openai", "OpenAI"), ("google", "Google/Gemini"),
                                    ("mistral", "Mistral"), ("perplexity", "Perplexity"), ("grok", "Grok / xAI")):
                _ov50 = _emo50(_prov50)
                if _ov50:
                    st.warning((f"{_lbl50} : a system environment variable overrides this setting — model actually called: "
                                f"{_ov50}.") if str(_lang).startswith("en") else
                               (f"{_lbl50} : une variable d'environnement du système remplace ce réglage — modèle réellement "
                                f"appelé : {_ov50}."))
        except Exception:
            pass

        st.markdown(f"**{T('sc_section', _lang)}**")
        sc_prefilter_model_id = st.text_input("Supply Chain — pre-filter model_id", value=settings.sc_prefilter_model_id,
                                              help=T("sc_prefilter_help",_lang))
        sc_primary_model_id   = st.text_input("Supply Chain — primary model_id", value=settings.sc_primary_model_id,
                                              help=T("sc_primary_help",_lang))
        sc_challenge_model_id = st.text_input("Supply Chain — challenge model_id", value=settings.sc_challenge_model_id,
                                              help=T("sc_challenge_help",_lang))

        st.markdown(f"**{T('lang_section', _lang)}**")
        output_language = st.radio(
            T("lang_label", _lang),
            options=["fr", "en"],
            index=0 if settings.output_language == "fr" else 1,
            format_func=lambda x: T("lang_fr_label",_lang) if x == "fr" else T("lang_en_label",_lang),
            horizontal=True,
            help=T("lang_help", _lang),
        )

        st.markdown("**PPTX — mode de livraison**" if _lang == "fr" else
                    "**PPTX — delivery mode**")
        _pptx_saved_mode = str(getattr(settings, "pptx_delivery_mode", "working") or "working").lower()
        if _pptx_saved_mode not in {"working", "strict"}:
            _pptx_saved_mode = "working"
        pptx_delivery_mode = st.radio(
            "Mode PPTX" if _lang == "fr" else "PPTX mode",
            options=["working", "strict"],
            index=0 if _pptx_saved_mode == "working" else 1,
            format_func=(lambda x: (
                "Document de travail — 8 à 15 slides, tolérance éditoriale"
                if x == "working" else
                "QA stricte — deck complet et contrôles bloquants"
            )) if _lang == "fr" else (lambda x: (
                "Working document — 8 to 15 slides, editorial tolerance"
                if x == "working" else
                "Strict QA — full deck and blocking controls"
            )),
            help=(
                "Le mode Document de travail livre le PPTX dès qu'il est ouvrable, éditable et globalement lisible. "
                "Les débordements locaux sont signalés, mais ne bloquent pas le fichier. Le mode QA stricte conserve "
                "le deck complet et les gates de publication historiques."
                if _lang == "fr" else
                "Working mode delivers an editable, readable deck and reports local layout findings without blocking. "
                "Strict QA keeps the full deck and historical publication gates."
            ),
        )

        st.markdown(f"**{T('sys_section', _lang)}**")
        fallback_enabled        = st.checkbox(T("fallback_label", _lang),         value=bool(settings.fallback_enabled))
        fallback_max_attempts   = st.number_input(T("fallback_max", _lang),          min_value=1, max_value=5, value=int(settings.fallback_max_attempts))
        attachments_max_files   = st.number_input(T("attach_files_label", _lang),    min_value=1, max_value=20, value=int(settings.attachments_max_files))
        attachments_max_total_mb = st.number_input(T("attach_mb_label", _lang), min_value=1, max_value=500, value=int(settings.attachments_max_total_mb))
        attachments_doc_token_budget = st.number_input(T("attach_tokens_label", _lang), min_value=2000, max_value=200000, value=int(settings.attachments_doc_token_budget))   # v62.13.9.4.39 — plafond 200 000, défaut 50 000

        saved2 = st.form_submit_button(T("save_params", _lang))
        if saved2:
            settings.openai_model_id       = openai_model_id.strip()
            settings.google_model_id       = google_model_id.strip()
            settings.anthropic_model_id    = anthropic_model_id.strip()
            settings.mistral_model_id      = mistral_model_id.strip()
            settings.perplexity_model_id   = perplexity_model_id.strip()
            settings.grok_model_id         = grok_model_id.strip()
            settings.sc_prefilter_model_id = sc_prefilter_model_id.strip()
            settings.sc_primary_model_id   = sc_primary_model_id.strip()
            settings.sc_challenge_model_id = sc_challenge_model_id.strip()
            settings.output_language       = output_language          # v16.5.38
            settings.pptx_delivery_mode     = pptx_delivery_mode         # v62.7
            settings.fallback_enabled      = bool(fallback_enabled)
            settings.fallback_max_attempts = int(fallback_max_attempts)
            settings.attachments_max_files      = int(attachments_max_files)
            settings.attachments_max_total_mb   = int(attachments_max_total_mb)
            settings.attachments_doc_token_budget = int(attachments_doc_token_budget)
            save_settings(settings)
            _lang_lbl = "English" if output_language == "en" else "Français"
            st.success(f'{T("params_saved", _lang)}: {_lang_lbl}.')

elif page == "help":
    st.subheader(T("help_title", _lang))
    st.caption(f"{VERSION_LABEL} · build {BUILD_VERSION}")   # 9.4.65 — version pour le support
    st.markdown(T("help_content", _lang))