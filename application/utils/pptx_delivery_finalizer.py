"""Single application-level choke point for CoDIR-IA PPTX delivery (H-v2).

Only this component is allowed to turn the fully enriched working deck into
bytes exposed to the user.  It re-applies machine-readable AI marking, performs
bounded repair, validates the serialized object, and writes the output path
only when the deck is distributable.
"""
from __future__ import annotations

from utils.v62136_fr_path_maintenance import repair_pptx_semantic_truth
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import tempfile
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class PptxFinalizationResult:
    pptx_bytes: bytes
    report: Dict[str, Any]
    distributable: bool
    sha256: str


def pptx_delivery_state(report: Optional[dict]) -> str:
    """Return the user-facing delivery state: ``ok``, ``warning`` or ``blocked``.

    v62.7 distinguishes the normal Working Deck contract from Strict QA.
    Working Deck warnings remain visible without hiding an editable file.
    """
    data = report if isinstance(report, dict) else {}
    if bool(data.get("blocking")):
        return "blocked"
    if bool(data.get("quality_warning") or data.get("h2_gate_warning")):
        return "warning"
    return "ok"


def pptx_delivery_block_reason(report: Optional[dict]) -> str:
    """Classify a blocked PPTX without confusing layout with corruption."""
    data = report if isinstance(report, dict) else {}
    package = data.get("package_validation") if isinstance(data.get("package_validation"), dict) else {}
    if package and not bool(package.get("ok", False)):
        return "package_corruption"
    serialized = data.get("serialized_validation") if isinstance(data.get("serialized_validation"), dict) else {}
    ellipses = serialized.get("critical_ellipses") or []
    if any(
        isinstance(item, dict)
        and "HCRIT:slide:title" in str(item.get("shape") or item.get("shape_key") or "")
        for item in ellipses
    ):
        return "executive_title_truncated"
    return "major_unreadability"


def _serialize(prs: Any) -> bytes:
    out = BytesIO()
    prs.save(out)
    return out.getvalue()



def _ensure_cr_references(prs: Any, lang: str) -> int:
    """Add the R6 report reference without colliding with editable content.

    Enrichment slides are authored by several historical renderers. Some of
    them use a 7.5-inch vertical grid even when the executive deck is 5.625
    inches high; the layout repair therefore moves their footer before this
    function runs.  A fixed bottom-right reference would then overlap that
    repaired footer and falsely block the deck.  The placement below searches
    deterministic free slots against visible text/table geometry.
    """
    from pptx.util import Inches, Pt
    from pptx.enum.text import PP_ALIGN
    from pptx.dml.color import RGBColor

    def _bbox(shape: Any):
        try:
            vals = (shape.left, shape.top, shape.width, shape.height)
            if None in vals:
                return None
            x, y, w, h = (int(v) for v in vals)
            return (x, y, x + w, y + h)
        except Exception:
            return None

    def _visible(shape: Any) -> bool:
        try:
            if getattr(shape, "has_text_frame", False):
                if str(shape.text_frame.text or "").strip():
                    return True
        except Exception:
            pass
        try:
            if getattr(shape, "has_table", False):
                return True
        except Exception:
            pass
        return False

    def _overlaps(a, b, pad: int = 0) -> bool:
        return not (
            a[2] + pad <= b[0] or b[2] + pad <= a[0]
            or a[3] + pad <= b[1] or b[3] + pad <= a[1]
        )

    def _free_slot(slide: Any, sw: int, sh: int, w: int, h: int):
        occupied = []
        for shape in slide.shapes:
            if str(getattr(shape, "name", "") or "") == "HNOTE:cr-ref":
                continue
            if not _visible(shape):
                continue
            box = _bbox(shape)
            if box is not None:
                # Intersect with the canvas; fully external legacy boxes are
                # repaired before this placement stage.
                occupied.append(box)

        margin_x = int(Inches(0.30))
        margin_y = int(Inches(0.08))
        pad = int(Inches(0.025))
        right = max(margin_x, sw - int(Inches(0.80)) - w)
        left = margin_x
        center = max(margin_x, (sw - w) // 2)
        bottom = max(margin_y, sh - int(Inches(0.085)) - h)

        # First try visually stable anchors, then scan a small deterministic
        # grid from the bottom upwards and from right to left.
        candidates = [
            (right, bottom),
            (right, int(Inches(1.02))),
            (right, int(Inches(1.58))),
            (right, int(Inches(2.12))),
            (left, bottom),
            (left, int(Inches(1.02))),
            (center, bottom),
        ]
        y = max(margin_y, sh - h - margin_y)
        while y >= margin_y:
            x = max(margin_x, sw - w - margin_x)
            while x >= margin_x:
                candidates.append((x, y))
                x -= int(Inches(0.35))
            y -= int(Inches(0.24))

        seen = set()
        best = None
        best_overlap = None
        for x, y in candidates:
            x = max(0, min(int(x), max(0, sw - w)))
            y = max(0, min(int(y), max(0, sh - h)))
            if (x, y) in seen:
                continue
            seen.add((x, y))
            candidate = (x, y, x + w, y + h)
            overlaps = [box for box in occupied if _overlaps(candidate, box, pad)]
            if not overlaps:
                return x, y
            # Fail-safe fallback: smallest intersection area, deterministic.
            area = 0
            for box in overlaps:
                area += max(0, min(candidate[2], box[2]) - max(candidate[0], box[0])) * \
                        max(0, min(candidate[3], box[3]) - max(candidate[1], box[1]))
            if best_overlap is None or area < best_overlap:
                best_overlap = area
                best = (x, y)
        return best or (right, bottom)

    added = 0
    for idx, slide in enumerate(prs.slides, 1):
        present = False
        for shape in slide.shapes:
            name = str(getattr(shape, "name", "") or "")
            text = str(getattr(shape, "text", "") or "")
            if (name == "HNOTE:cr-ref" or "CR §" in text or "report §" in text
                    or "voir le compte rendu" in text or "see the report" in text):   # v62.13.9.4.33 — un renvoi générique compte
                present = True
                break
        if present:
            continue
        sw = int(prs.slide_width)
        sh = int(prs.slide_height)
        width = int(Inches(1.65))
        height = int(Inches(0.22))
        x, y = _free_slot(slide, sw, sh, width, height)
        box = slide.shapes.add_textbox(x, y, width, height)
        box.name = "HNOTE:cr-ref"
        tf = box.text_frame
        tf.clear()
        tf.margin_left = tf.margin_right = 0
        tf.margin_top = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.RIGHT
        run = p.add_run()
        # v62.13.9.4.33 (lot 1) — le rang d'une slide n'est pas un numéro de
        # rubrique : « Détail : CR §15 » sur la slide 15 (onze rubriques) —
        # contre-audit du 12/09/2026. Sans rubrique connue ici, le renvoi
        # reste générique ; les renvois de rubrique réels sont posés par le
        # constructeur (_pgnum) et ne sont jamais réécrits par ce filet.
        run.text = ("Detail: see the report" if (lang or "fr").lower() == "en"
                    else "Détail : voir le compte rendu")
        run.font.size = Pt(8)
        run.font.italic = True
        run.font.color.rgb = RGBColor(0x88, 0x96, 0xB0)
        added += 1
    return added


def _has_h2_surface(prs: Any) -> bool:
    for slide in prs.slides:
        for sh in slide.shapes:
            name = str(getattr(sh, "name", "") or "")
            if name.startswith("HCRIT:essentiel:") or name == "HCRIT:cover:key-message":
                return True
    return False

def finalize_pptx_for_delivery(
    pptx_bytes: bytes,
    *,
    result: Optional[dict] = None,
    lang: str = "fr",
    output_path: str | Path | None = None,
    provider: str | None = None,
    delivery_mode: str = "strict",
) -> PptxFinalizationResult:
    pptx_bytes = repair_pptx_semantic_truth(pptx_bytes, result or {}, lang)
    if provider is None:
        from version import PUBLISHER as _PUB
        provider = _PUB
    """Finalize the exact deck delivered by the application.

    ``working`` is the normal product surface: the exact serialized deck is
    delivered when it is openable, editable and readable; local editorial
    defects remain visible as warnings. ``strict`` keeps the historical
    over-quality QA gate. Package corruption, final-file geometry failures and
    finalizer errors remain fail-closed in both modes. No exception escapes to
    the Streamlit UI.
    """
    _mode = str(delivery_mode or "strict").strip().lower()
    if _mode not in {"working", "strict"}:
        _mode = "working"
    report: Dict[str, Any] = {
        "phase": "final", "lang": lang, "delivery_mode": _mode,
        "working_deck_contract": (_mode == "working"),
        "repair": {}, "validation": {},
        "serialized_validation": {}, "marking_applied": False,
        "output_written": False, "errors": [],
        "cr_refs_added": 0, "h2_applicable": False, "h2_audit": {},
        "package_validation": {}, "quality_warning": False,
        "hcrit_title_repairs": [],
    }
    raw = bytes(pptx_bytes or b"")
    if not raw:
        report["errors"].append("empty_pptx_bytes")
        return PptxFinalizationResult(raw, report, False, sha256(raw).hexdigest())

    try:
        from pptx import Presentation
        from utils.ai_content_marking import apply_marking
        from utils.deck_layout_guard import (
            repair_deck_layout, snapshot_layout, validate_deck_layout,
        )

        prs = Presentation(BytesIO(raw))
        version = ""
        try:
            from version import product_label   # 9.4.65 — libellé produit (« CoDIR IA v17.0 (build 9.4.65) »)
            version = product_label(with_build=True)
        except Exception:
            pass
        report["marking_applied"] = bool(
            apply_marking(prs, version=version, provider=provider,
                          title="CoDIR IA — Executive synthesis"))
        from utils.pptx_title_safety import repair_hcrit_title_ellipses
        report["hcrit_title_repairs"] = repair_hcrit_title_ellipses(prs, lang)
        try:   # 9.4.65 — décision affichée = décision adoptée ; pas de fragment, de gabarit ni d'échéance passée
            from utils.deck_decision_guard65 import guard_deck65
            _m65 = (result or {}).get("meta") or {} if isinstance(result, dict) else {}
            report["deck_guard65"] = guard_deck65(prs, board_option=str(_m65.get("board_option65") or ""),
                                                  run_date=str((result or {}).get("temporal_authority_date") or "")
                                                  if isinstance(result, dict) else "", lang=lang,
                                                  claims=((result or {}).get("canonical_financial_claims")
                                                          if isinstance(result, dict) else None))
        except Exception as _e65:
            report.setdefault("errors", []).append(f"deck_guard65: {type(_e65).__name__}")
        # Snapshot after metadata marking/title repair, then normalize every legacy/enriched
        # geometry before choosing a collision-free location for R6 references.
        before = snapshot_layout(prs)
        try:
            report["repair"] = repair_deck_layout(prs, result)   # v62.13.9.4.22 — statut des informations
        except TypeError:
            report["repair"] = repair_deck_layout(prs)           # signature historique (tests, patches)
        report["cr_refs_added"] = _ensure_cr_references(prs, lang)
        report["h2_applicable"] = _has_h2_surface(prs)
        report["validation"] = validate_deck_layout(prs, before)

        # Serialize once, then reload and validate the exact byte stream that
        # will be stored, written and downloaded.
        final_bytes = _serialize(prs)
        reloaded = Presentation(BytesIO(final_bytes))
        report["serialized_validation"] = validate_deck_layout(reloaded, before)
        from utils.pptx_package_guard import validate_pptx_package
        report["package_validation"] = validate_pptx_package(final_bytes)
        if report["h2_applicable"]:
            from utils.audit_90s import audit_deck
            report["h2_audit"] = audit_deck(reloaded)

        repair_errors = report["repair"].get("errors", [])
        h2_audit_warning = bool(
            report["h2_applicable"]
            and not report.get("h2_audit", {}).get("gate_pass")
        )
        warning_reasons = []
        if h2_audit_warning:
            warning_reasons.append("h2_90s_editorial_gate")

        # v62.7 — deux contrats explicites.
        # Working Deck : les débordements locaux et le contraste éditorial sont
        # signalés mais ne cachent pas un fichier ouvrable/éditable.
        # Strict QA : le comportement historique reste fail-closed.
        diagnostic_keys = ("group_child_outside",)
        working_warning_keys = ("critical_text_overflow", "contrast_failures")
        major_unreadability_keys = (
            "out_of_canvas_text", "out_of_canvas_tables", "created_overlaps",
            "critical_ellipses", "font_below_floor", "errors",
        )
        strict_hard_keys = major_unreadability_keys + working_warning_keys
        working_hard_reasons = []
        strict_hard_reasons = []

        def _is_working_cosmetic(key: str, item: Any) -> bool:
            # Footer/reference artefacts are useful diagnostics but do not make
            # a working deck unusable. The exact final file remains inspected.
            marker = repr(item).lower()
            if key in {"created_overlaps", "out_of_canvas_text"}:
                return any(token in marker for token in (
                    "hnote:cr-ref", "footer", "slide-number", "page-number",
                    "document généré", "generated by",
                ))
            return False

        for phase in ("validation", "serialized_validation"):
            layer = report.get(phase) or {}
            for key in diagnostic_keys:
                if layer.get(key):
                    warning_reasons.append(f"{phase}:{key}")
            for key in working_warning_keys:
                if layer.get(key):
                    warning_reasons.append(f"{phase}:{key}")
            for key in major_unreadability_keys:
                items = layer.get(key) or []
                if not items:
                    continue
                # The product promise concerns the bytes actually delivered. A
                # transient pre-serialization defect that is absent after reload
                # is a QA warning, not a reason to hide the working document.
                if phase != "serialized_validation":
                    warning_reasons.append(f"{phase}:preflight:{key}")
                    continue
                if key in {"created_overlaps", "out_of_canvas_text"}:
                    major_items = [item for item in items
                                   if not _is_working_cosmetic(key, item)]
                    cosmetic_items = [item for item in items
                                      if _is_working_cosmetic(key, item)]
                    if cosmetic_items:
                        warning_reasons.append(f"{phase}:cosmetic:{key}")
                    if major_items:
                        working_hard_reasons.append(f"{phase}:{key}")
                else:
                    working_hard_reasons.append(f"{phase}:{key}")
            for key in strict_hard_keys:
                if layer.get(key):
                    strict_hard_reasons.append(f"{phase}:{key}")

        package_report = report.get("package_validation") or {}
        if not package_report.get("ok", False):
            for key in (
                "required_parts_missing", "duplicate_zip_entries", "bad_xml_parts",
                "missing_relationship_targets", "unresolved_presentation_slide_ids",
                "duplicate_shape_ids", "negative_extents", "errors",
            ):
                if package_report.get(key):
                    working_hard_reasons.append(f"package_validation:{key}")
                    strict_hard_reasons.append(f"package_validation:{key}")
        for warning in package_report.get("warnings", []) or []:
            warning_reasons.append(f"package_validation:warning:{warning}")

        if repair_errors:
            working_hard_reasons.append("repair:errors")
            strict_hard_reasons.append("repair:errors")

        # 8-15 slides is the Working Deck product envelope. A deviation is
        # visible, but it does not destroy an otherwise editable file.
        _slide_count = int((report.get("package_validation") or {}).get("slide_count") or 0)
        report["slide_count"] = _slide_count
        # v62.13.9.4.37 — ENVELOPPE ÉLARGIE (décision de Robin, 18/09/2026) : 10 à 15
        # slides restent la cible, 16 à 18 sont admises quand la matière l'exige ; le
        # nombre de slides n'est pas une note de qualité. Au-delà de 18 ou en deçà de 8,
        # l'avertissement reste.
        report["working_slide_target"] = {"min": 8, "max": 18, "target": "10-15"}
        if _mode == "working" and _slide_count and not (8 <= _slide_count <= 18):
            warning_reasons.append("working_deck:slide_count_outside_8_18")

        # Stable ordering prevents report drift and makes the UI/test fixtures
        # deterministic across Python versions.
        warning_reasons = list(dict.fromkeys(warning_reasons))
        working_hard_reasons = list(dict.fromkeys(working_hard_reasons))
        strict_hard_reasons = list(dict.fromkeys(strict_hard_reasons))
        hard_reasons = strict_hard_reasons if _mode == "strict" else working_hard_reasons
        report["quality_warning"] = bool(warning_reasons)
        report["h2_gate_warning"] = bool(h2_audit_warning)
        report["warning_reasons"] = warning_reasons
        _warning_items = set()
        for _phase in ("validation", "serialized_validation"):
            _layer = report.get(_phase) or {}
            for _key in working_warning_keys + ("created_overlaps", "out_of_canvas_text"):
                for _item in (_layer.get(_key) or []):
                    if isinstance(_item, dict):
                        _warning_items.add(str(_item.get("shape_key") or _item.get("shape") or repr(_item)))
                    else:
                        _warning_items.add(repr(_item))
        report["working_layout_warning_count"] = len(_warning_items)
        report["strict_qa_blocking_reasons"] = strict_hard_reasons
        report["strict_qa_would_block"] = bool(strict_hard_reasons)
        report["blocking_reasons"] = hard_reasons
        blocking = bool(hard_reasons)
        report["blocking"] = blocking
        digest = sha256(final_bytes).hexdigest()
        report["sha256"] = digest
        report["size_bytes"] = len(final_bytes)

        if not blocking and output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path: Path | None = None
            try:
                # One atomic publication: write and fsync a sibling temporary
                # file, then replace the target in a single filesystem step.
                with tempfile.NamedTemporaryFile(
                    mode="wb", prefix=f".{path.name}.", suffix=".tmp",
                    dir=path.parent, delete=False
                ) as tmp:
                    tmp.write(final_bytes)
                    tmp.flush()
                    os.fsync(tmp.fileno())
                    tmp_path = Path(tmp.name)
                os.replace(tmp_path, path)
                tmp_path = None
                report["output_written"] = True
                report["output_path"] = str(path)
                report["output_sha256"] = sha256(path.read_bytes()).hexdigest()
            finally:
                if tmp_path is not None:
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass
            if report["output_sha256"] != digest:
                report["errors"].append("output_sha_mismatch")
                report["blocking"] = True
                try:
                    path.unlink()
                except Exception:
                    pass
                return PptxFinalizationResult(final_bytes, report, False, digest)

        # v62.13.9.4.8 — second juge de production : l'oracle relit les
        # octets finaux ; un survivant force distributable=False,
        # indépendamment du verdict du gate ci-dessus.
        # v62.13.9.4.9 — FAIL-CLOSED intégral (contre-audit 30/08/2026,
        # P1-948-04) : toute indisponibilité de l'oracle — import, extraction
        # OOXML, autorité, juge — bloque la distribution. L'ancien repli
        # « _oh = [] » transformait une panne du contrôle en autorisation de
        # diffuser : un juge muet n'est pas un juge favorable.
        _oracle_unavailable62149 = None
        try:
            from utils.final_content_oracle import runtime_audit as _rt62148
            _oh62148 = _rt62148(final_bytes, result) if result is not None else []
        except Exception as _rt_exc62148:
            _oh62148 = []
            _oracle_unavailable62149 = f"{type(_rt_exc62148).__name__}: {_rt_exc62148}"
            report["final_content_oracle_error"] = _oracle_unavailable62149
        if _oracle_unavailable62149:
            report["final_content_oracle_unavailable"] = True
            report["blocking"] = (report["blocking"] + ["final_content_oracle_unavailable"]
                                  if isinstance(report.get("blocking"), list)
                                  else True)
        # v62.13.9.4.20 — neutralisation de dernier recours (au plus
        # RESIDUAL_TOLERANCE unités), contrôle rejoué une fois.
        # v62.13.9.4.50 — doctrine « tout livrer, tout signaler en place » : plus de neutralisation de dernier recours
        # (contre-recette du 30/09 : une phrase de la diapositive 7 remplacée par « (phrase chiffrée retirée du
        # corps…) ») ; les constats de l'oracle sont ÉTIQUETÉS en place, le rendu unique du deck les signale.
        try:
            from utils.v62136_fr_path_maintenance import _status_mode as _stm50
            _flag50 = bool(result is not None and _stm50(result))
        except Exception:
            _flag50 = True
        if _oh62148 and result is not None and _flag50:
            try:
                from utils.flag_render49 import tag_units_in_pptx_bytes as _tup50, final_motif as _fm50
                _u50 = list(dict.fromkeys(str(h.get("unit_full") or h.get("unit") or "") for h in _oh62148
                                          if str(h.get("unit_full") or h.get("unit") or "").strip()))
                final_bytes, _n50 = _tup50(final_bytes, [(u, _fm50("oracle", str(result.get("lang") or lang))) for u in _u50],
                                           str(result.get("lang") or lang))
                digest = sha256(final_bytes).hexdigest()
                report["sha256"] = digest
                report["size_bytes"] = len(final_bytes)
                report["residual_flagged"] = {"units": len(_u50), "tagged": _n50}
                _oh62148 = []                      # constats signalés en place : plus de résidu non traité
            except Exception as _rf_exc50:
                report["residual_flagged"] = {"error": f"{type(_rf_exc50).__name__}: {_rf_exc50}"}
        elif _oh62148 and result is not None:
            try:
                from utils.residual_neutralizer import neutralize_pptx_residuals as _npr62420, RESIDUAL_TOLERANCE as _RT62420
                _units62420 = [str(h.get("unit_full") or h.get("unit") or "") for h in _oh62148   # v62.13.9.4.31.1 — unité entière
                               if str(h.get("unit_full") or h.get("unit") or "").strip()]
                _units62420 = list(dict.fromkeys(_units62420))
                if 0 < len(_units62420) and (_RT62420 is None or len(_units62420) <= _RT62420):
                    _parts62423 = [str(h.get("part") or "") for h in _oh62148]
                    _b2, _done62420 = _npr62420(final_bytes, _units62420, str(result.get("lang") or "fr"), parts=_parts62423)
                    _o2 = _rt62148(_b2, result) if _done62420 else _oh62148
                    report["residual_neutralization"] = {"attempted": True, "units": _units62420[:5],
                                                         "neutralized": _done62420[:5], "recheck_oracle": len(_o2)}
                    if _done62420 and not _o2:
                        final_bytes, _oh62148 = _b2, []
                        digest = sha256(final_bytes).hexdigest()
                        report["sha256"] = digest
                        report["size_bytes"] = len(final_bytes)
                else:
                    report["residual_neutralization"] = {"attempted": False, "units": len(_units62420), "tolerance": _RT62420}
            except Exception as _rn_exc62420:
                report["residual_neutralization"] = {"error": f"{type(_rn_exc62420).__name__}: {_rn_exc62420}"}
        report["final_content_oracle"] = {"hits": len(_oh62148), "sample": _oh62148[:5]}
        if _oh62148:
            report["blocking"] = (report["blocking"] + ["final_content_oracle"]
                                  if isinstance(report.get("blocking"), list)
                                  else True)
        return PptxFinalizationResult(final_bytes, report, not report["blocking"], digest)
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}:{exc}")
        report["blocking"] = True
        return PptxFinalizationResult(raw, report, False, sha256(raw).hexdigest())


__all__ = ["PptxFinalizationResult", "finalize_pptx_for_delivery", "pptx_delivery_state"]
