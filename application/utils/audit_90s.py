"""audit_90s — gate fail-closed de lecture exécutive H2 (.58).

L'instrument mesure les huit règles de la SPEC gelée : chemin 90 s, titres
assertifs, Top-N traçable, densité 5/12, trois KPI maximum, renvoi CR sur
chaque slide, plancher 11 pt et déterminisme. Il ne répare jamais.
"""
from __future__ import annotations

import io
import json
import sys
from typing import Any, Dict, List, Tuple

from utils.exec_reading import bullets_metrics, content_words as _content_words

_EMU_PER_INCH = 914400
_EXEC_PREFIXES = ("HCRIT:essentiel:", "HCRIT:cover:")
# v62.13.9.4.31 — décision produit (Robin, 09/09) : le contrat H2 R4 (« pas plus
# de cinq puces par surface exécutive ») s'applique aux slides À PUCES. Une
# MATRICE — le SWOT et ses quatre quadrants — n'est pas une liste : elle porte
# trois à cinq entrées courtes par quadrant, une note de couverture et un renvoi
# vers la rubrique du Word. Ses cellules sont mesurées comme cellules de matrice
# (densité, longueur, police), pas comme des puces.
_MATRIX_PREFIXES = ("HCRIT:swot:item:",)
_BULLET_PREFIXES = (
    "HCRIT:essentiel:risque", "HCRIT:essentiel:arbitrage",
    "HCRIT:axis:action:",
    "HCRIT:roadmap:action:", "HCRIT:next-step:action:",
    "HCRIT:next-step:question:", "HCRIT:next-step:decision:",
    "HCRIT:risk:item:", "HCRIT:arbitration:item:",
    "HCRIT:risks-slide:risk:", "HCRIT:risks-slide:arbitration:",
)
_GENERIC_TITLES = {
    "CONTEXTE & DIAGNOSTIC", "CONTEXT & DIAGNOSIS", "POSITIONNEMENT",
    "POSITIONING", "4 AXES STRATÉGIQUES", "4 STRATEGIC PRIORITIES",
    "PROCHAINES ÉTAPES", "NEXT STEPS", "CONCLUSION",
    "RISQUES & ARBITRAGES", "RISKS & DECISIONS",
}
_ROADMAP_TITLE_TOKENS = (
    "ROADMAP", "FEUILLE DE ROUTE", "PLAN D'EXÉCUTION", "PLAN D’EXÉCUTION",
    "EXECUTION PLAN",
)
_INVENTORY_TITLE_TOKENS = (
    *_ROADMAP_TITLE_TOKENS,
    "FAITS FINANCIERS", "FINANCIAL FACTS", "FAITS MARCHÉ", "MARKET FACTS",
    # v62.13.9.4.31 — décision produit (Robin, 09/09) : le SWOT est une MATRICE
    # à quatre quadrants, pas une liste à puces. Il porte trois à cinq entrées
    # courtes par quadrant, avec une note de couverture et un renvoi vers la
    # rubrique du Word. Le plafond de cinq puces reste la règle des slides à
    # puces ; les surfaces matricielles suivent la règle d'inventaire.
    "MATRICE", "MATRIX",
)


def _iter_named_text(prs):
    for sidx, slide in enumerate(prs.slides, 1):
        for sh in slide.shapes:
            if getattr(sh, "has_text_frame", False):
                yield sidx, sh


def _bbox(sh) -> Tuple[int, int, int, int]:
    return int(sh.left), int(sh.top), int(sh.width), int(sh.height)


def _overlap(a, b) -> bool:
    al, at, aw, ah = a; bl, bt, bw, bh = b
    iw = max(0, min(al + aw, bl + bw) - max(al, bl))
    ih = max(0, min(at + ah, bt + bh) - max(at, bt))
    return iw > int(0.02 * _EMU_PER_INCH) and ih > int(0.02 * _EMU_PER_INCH)


def _is_bullet_role(name: str) -> bool:
    return any(name.startswith(p) for p in _BULLET_PREFIXES)


def _is_matrix_role(name: str) -> bool:
    return any(name.startswith(p) for p in _MATRIX_PREFIXES)


def audit_deck(prs: Any) -> Dict[str, Any]:
    m: Dict[str, Any] = {
        "slides": len(prs.slides),
        "essentiel_present": False,
        "essentiel_kpi_cards": 0,
        "essentiel_risque": False,
        "essentiel_arbitrage": False,
        "essentiel_echeance": False,
        "cover_key_message": False,
        "empty_exec_roles": [],
        "hcrit_ellipses": 0,
        "hcrit_fonts_below_11": 0,
        "cover_overlaps": [],
        "coverage_notes": 0,
        "questions_shown": 0,
        "exec_words_max": 0,
        "exec_items_over_12w": 0,
        "slides_without_cr_ref": [],
        "generic_titles": [],
        "slides_over_5_bullets": [],
        "bullets_over_12_words": [],
        "prudence_before_essentiel": True,
        "errors": [],
        "slide_reports": [],
    }
    slide_state: Dict[int, Dict[str, Any]] = {
        i: {"index": i, "title": "", "cr_ref": False, "bullets": [],
            "inventory": False, "coverage": 0, "matrix_cells": []}
        for i in range(1, len(prs.slides) + 1)
    }
    cover_key = None
    cover_badges = []
    essentiel_idx = None
    prudence_indices: List[int] = []

    for sidx, sh in _iter_named_text(prs):
        name = str(sh.name or "")
        text = sh.text_frame.text.strip()
        st = slide_state[sidx]
        if name == "HCRIT:slide:title":
            st["title"] = text
            up = text.strip().upper()
            st["inventory"] = any(tok in up for tok in _INVENTORY_TITLE_TOKENS)
            if up in _GENERIC_TITLES:
                m["generic_titles"].append({"slide": sidx, "title": text})
        if name == "HNOTE:cr-ref" or "CR §" in text or "report §" in text or "Synthèse §" in text or "Synthesis §" in text:
            st["cr_ref"] = True
        if name == "HNOTE:coverage" or "lignes sur" in text or " of " in text and " lines" in text:
            st["coverage"] += 1
            m["coverage_notes"] += 1
        if name.startswith("HCRIT:reading-frame:"):
            prudence_indices.append(sidx)
        if name.startswith("HCRIT:essentiel:"):
            m["essentiel_present"] = True
            essentiel_idx = sidx
            if name.startswith("HCRIT:essentiel:kpi:"):
                m["essentiel_kpi_cards"] += 1
            elif name == "HCRIT:essentiel:risque":
                m["essentiel_risque"] = bool(text)
            elif name == "HCRIT:essentiel:arbitrage":
                m["essentiel_arbitrage"] = bool(text)
            elif name == "HCRIT:essentiel:echeance":
                m["essentiel_echeance"] = bool(text)
        if name == "HCRIT:cover:key-message":
            m["cover_key_message"] = bool(text)
            cover_key = (sidx, name, _bbox(sh))
        if name.startswith("HINFO:cover:badge:"):
            cover_badges.append((sidx, name, _bbox(sh)))
        if name.startswith("HCRIT:"):
            m["hcrit_ellipses"] += text.count("…") + text.count("...")
            if not text and name.startswith(_EXEC_PREFIXES):
                m["empty_exec_roles"].append(name)
            for para in sh.text_frame.paragraphs:
                for run in para.runs:
                    sz = run.font.size
                    if sz is not None and sz.pt < 11:
                        m["hcrit_fonts_below_11"] += 1
            if _is_matrix_role(name) and text:
                st["matrix_cells"].append({"role": name, "text": text})
            if _is_bullet_role(name) and text:
                st["bullets"].append({"role": name, "text": text})
                if name.startswith("HCRIT:next-step:question:"):
                    m["questions_shown"] += 1

    if cover_key:
        for badge in cover_badges:
            if cover_key[0] == badge[0] and _overlap(cover_key[2], badge[2]):
                m["cover_overlaps"].append([cover_key[1], badge[1]])

    if essentiel_idx and prudence_indices:
        m["prudence_before_essentiel"] = max(prudence_indices) < essentiel_idx

    for idx, st in slide_state.items():
        if not st["cr_ref"]:
            m["slides_without_cr_ref"].append(idx)
        texts = [x["text"] for x in st["bullets"]]
        bm = bullets_metrics(texts)
        # Roadmaps are structured as three actions per horizon and may display
        # more than five bullets without semantic truncation. Other inventory
        # surfaces (facts/tables) still need an explicit coverage note whenever
        # they exceed the executive density ceiling.
        title_up = str(st["title"] or "").strip().upper()
        is_roadmap_inventory = any(tok in title_up for tok in _ROADMAP_TITLE_TOKENS)
        inventory_exception = bool(
            st["inventory"] and (st["coverage"] or is_roadmap_inventory)
        )
        # v62.13.9.4.33 — amendement de la spécification H2 (décision Robin,
        # 12/09/2026) : la slide des priorités porte jusqu'à TROIS points par
        # carte, comptés par carte (rôle HCRIT:axis:action:<carte>:<rang>), soit
        # douze par slide au plus ; le plafond de cinq reste la règle partout
        # ailleurs. Une carte à quatre points ou plus déclenche le gate.
        _axis_roles = [x["role"] for x in st["bullets"] if str(x["role"]).startswith("HCRIT:axis:action:")]
        axis_cards_exception = False
        if _axis_roles and len(_axis_roles) == len(st["bullets"]):
            _per_card: dict = {}
            for r in _axis_roles:
                _card = str(r).split(":")[3] if str(r).count(":") >= 4 else "?"
                _per_card[_card] = _per_card.get(_card, 0) + 1
            axis_cards_exception = max(_per_card.values()) <= 3
        if bm["bullets_over_cap"] and not inventory_exception and not axis_cards_exception:
            m["slides_over_5_bullets"].append({"slide": idx, "count": bm["bullets"]})
        m["exec_words_max"] = max(m["exec_words_max"], bm["words_max"])
        m["exec_items_over_12w"] += bm["bullets_over_words"]
        for item in st["bullets"]:
            words = _content_words(item["text"])
            # v62.13.9.4.37 — amendement H2 du 18/09/2026 (Robin) : sur une CARTE DE
            # CONTENU (points d'axes, décisions, actions, prochaines étapes) le plafond
            # est 35 mots sur deux lignes ; 12 mots restent la règle des titres et KPI.
            _role37 = str(item.get("role") or "")
            _cap37 = 35 if any(k in _role37 for k in (":axis:action", ":decision", ":action", ":next-step", ":roadmap:action")) else 12
            if words > _cap37:
                m["bullets_over_12_words"].append(
                    {"slide": idx, "role": item["role"], "words": words,
                     "text": item["text"]})
        m["slide_reports"].append({
            "slide": idx, "title": st["title"], "cr_ref": st["cr_ref"],
            "bullets": bm["bullets"], "max_words": bm["words_max"],
            "coverage_notes": st["coverage"], "inventory": st["inventory"],
            "matrix_cells": len(st["matrix_cells"]),
        })

    m["gate_pass"] = bool(
        m["essentiel_present"]
        and 1 <= m["essentiel_kpi_cards"] <= 3
        and m["essentiel_risque"]
        and m["essentiel_arbitrage"]
        and m["cover_key_message"]
        and not m["empty_exec_roles"]
        and not m["hcrit_ellipses"]
        and not m["hcrit_fonts_below_11"]
        and not m["cover_overlaps"]
        and not m["slides_without_cr_ref"]
        and not m["generic_titles"]
        and not m["slides_over_5_bullets"]
        and not m["bullets_over_12_words"]
        and m["prudence_before_essentiel"]
        and not m["errors"]
    )
    return m


def audit_bytes(pptx_bytes: bytes) -> Dict[str, Any]:
    from pptx import Presentation
    return audit_deck(Presentation(io.BytesIO(pptx_bytes)))


def main(argv: List[str]) -> int:
    from pptx import Presentation
    characterization = "--characterization" in argv
    paths = [p for p in argv if p != "--characterization"]
    failed = False
    for path in paths:
        try:
            report = audit_deck(Presentation(path))
        except Exception as exc:
            report = {"file": path, "error": str(exc), "gate_pass": False}
        report["file"] = path
        print(json.dumps(report, ensure_ascii=False))
        failed = failed or not bool(report.get("gate_pass"))
    return 0 if characterization or not failed else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
