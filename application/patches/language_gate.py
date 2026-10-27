"""
patches/language_gate.py — M.5.10 (Language Closure)

Filet de sécurité P0-5 : si un run est en anglais (output_language="en") mais que
le livrable (CR / deck) contient encore des labels ou du contenu en français au-delà
d'un seuil, on PLAFONNE la note (max Grade C) et on lève un avertissement explicite.
Un livrable EN à moitié français donne une impression d'outil non fini — il ne doit
pas pouvoir afficher un Grade B « Board / client ».

Le gate ne RÉÉCRIT rien : il signale et plafonne (les correctifs de fond sont les
labels SL localisés + le verrou de langue du prompt deck).
"""
from __future__ import annotations

import re
from typing import Tuple

# Marqueurs français robustes (accents + mots fonctionnels/labels typiques). On évite
# les mots ambigus EN/FR (« table », « impact », « finance », « budget »…).
# Marqueurs FR par MOT (sans la classe d'accent nue, désormais traitée à part).
_FR_WORD_MARKERS = re.compile(
    r"\b(et|à|le|la|les|des|du|une|pour|sans|avec|sur|aux|leur|ses|"
    r"chiffre d'affaires|résultat net|trésorerie|société|secteur|géographie|"
    r"actionnariat|élevée|moyenne|faible|coûts|canaux|restructuration|"
    r"repositionnement|croissance|réduction|aucune|séance|langue|français|"
    r"opérationnelle|opérationnel|indisponible|analyse supply chain|sur ce run|"
    r"contexte|faiblesses|risques|précon|entités|vérifiées|détectées|"
    r"validation des entités)\b",
    re.IGNORECASE,
)
_ACCENT = re.compile(r"[àâäéèêëïîôöùûüç]")

# Conservé pour rétrocompat (anciens tests/imports) : matche mot OU accent.
_FR_MARKERS = re.compile(_FR_WORD_MARKERS.pattern + r"|[àâäéèêëïîôöùûüç]", re.IGNORECASE)


_FORM_ECHO = re.compile(
    r"[║╔╚╗╝═]|^\s*▌|^\s{0,6}(?:Société|Secteur|Actionnariat|Implantation|"
    r"Effectif|Chiffre d'affaires|Langue|Mode\(s\)[^:\n]{0,24}|Horizon|Format|Périmètre|"
    r"Enjeux|Questions|Contexte)\s*:")


def _is_form_echo_line(line: str) -> bool:
    """B.1.3.5 (run dossier anglophone coté EN) — l'ÉCHO DU FORMULAIRE (bannière ORDRE DU
    JOUR, sections ▌, labels « Société : / Langue : … ») est un gabarit
    légitimement bilingue : il reflète la saisie, il ne doit JAMAIS compter
    comme résidu hors langue cible. residue=11 sur dossier anglophone coté EN venait pour
    l'essentiel de là (+ des wrappers système, corrigés par ailleurs)."""
    return bool(_FORM_ECHO.search(line or ""))


def _line_is_fr(line: str) -> bool:
    """M.5.10.5 — une ligne est « résidu FR » si elle porte un MOT français, OU
    au moins DEUX caractères accentués (une phrase FR en a plusieurs). Un accent
    isolé (nom propre : « Hermès », « Moët ») ne suffit plus → fini les faux
    positifs sur de l'anglais légitime citant des marques accentuées."""
    if _FR_WORD_MARKERS.search(line):
        return True
    return len(_ACCENT.findall(line)) >= 2

# Seuil : en dessous, on tolère (un nom propre FR, un sigle). Au-dessus, on plafonne.
_RESIDUE_THRESHOLD = 6


def count_fr_residue(text: str) -> int:
    """Nombre de marqueurs français distincts (lignes) dans un texte."""
    return len(_fr_residue_samples(text))


def _fr_residue_samples(text: str, cap: int = 6) -> list:
    """Lignes distinctes portant un marqueur français (échantillon tronqué)."""
    if not text:
        return []
    hits = []
    seen = set()
    for line in str(text).splitlines():
        if _is_form_echo_line(line):
            continue
        line = line.strip()
        if line and _line_is_fr(line):
            key = line[:80]
            if key not in seen:
                seen.add(key)
                hits.append(key)
    return hits


def evaluate(cr_text: str, deck_text: str, lang: str, strict: bool = False) -> dict:
    """Évalue la conformité linguistique. Renvoie {triggered, residue, where, samples}.

    M.5.10.6 — `strict=True` (mode validation/clôture P0-5) : tout résidu FR
    déterministe (≥1 ligne) déclenche. Le seuil de production `_RESIDUE_THRESHOLD`
    (tolérance anti faux-positifs) ne s'applique qu'en mode non strict. `strict_pass`
    expose le verdict binaire « zéro résidu » pour les tests de clôture."""
    if (lang or "fr").lower() != "en":
        return {"target_lang": lang, "triggered": False, "residue": 0, "where": "", "samples": [],
                "strict": strict, "strict_pass": True}
    s_cr = _fr_residue_samples(cr_text)
    s_deck = _fr_residue_samples(deck_text)
    n_cr, n_deck = len(s_cr), len(s_deck)
    total = n_cr + n_deck
    _thr = 1 if strict else _RESIDUE_THRESHOLD
    return {"target_lang": lang, 
        "triggered": total >= _thr,
        "residue": total,
        "where": (f"CR:{n_cr} / deck:{n_deck}"),
        "samples": (s_cr + s_deck)[:6],
        "strict": strict,
        "strict_pass": total == 0,
    }


_GRADE_ORDER = ["A", "B", "C", "D", "E"]


def apply_cap(grade: str, max_grade: str = "C") -> str:
    """Plafonne un grade (A/B → max_grade). Ne remonte jamais un grade."""
    try:
        gi = _GRADE_ORDER.index(str(grade).strip().upper())
        mi = _GRADE_ORDER.index(max_grade)
    except ValueError:
        return grade
    return _GRADE_ORDER[max(gi, mi)]


def apply_language_gate(score_result: dict, cr_text: str, deck_text: str,
                        lang: str) -> Tuple[dict, dict]:
    """Applique le gate au résultat de score. Renvoie (score_result modifié, info).
    Si déclenché : grade plafonné à C, usage = revue interne, warning ajouté.
    Le warning est localisé dans la langue du run (FR/EN) — un warning français
    dans un run EN serait lui-même une fuite de langue."""
    info = evaluate(cr_text, deck_text, lang)
    if not info["triggered"]:
        return score_result, info
    g = score_result.get("grade", "")
    raw_score = score_result.get("score")
    capped = apply_cap(g, "C")
    if capped != g:
        score_result["grade"] = capped
        score_result["grade_capped_by_language"] = True
    # B.1.3 (run dossier anglophone coté, requalifié) — le message NOMME la cible mesurée et
    # sa source : le gate mesurait juste (cible = écran, contrat UI-1) mais
    # son libellé laissait croire à une inversion (« English output contains
    # French » lu comme si FR était demandé). Désormais explicite.
    if (lang or "fr").lower() == "en":
        warn = ("English run (target set by screen selection, UI-1 contract): "
                "French labels/content detected in the deliverable "
                f"({info['where']}) — score capped to Grade {capped}, "
                "client presentation not recommended before language cleanup.")
    else:
        warn = ("Cible du run = Français (sélection écran, contrat UI-1) : "
                "labels/contenu anglais résiduels détectés dans le livrable "
                f"({info['where']}) — note plafonnée à Grade {capped}, "
                "présentation client non recommandée avant nettoyage langue.")
    score_result.setdefault("warnings", []).append(warn)
    score_result["language_quality"] = "FR_RESIDUE_IN_EN_RUN"
    # M.5.10.4 — bloc d'observabilité structuré (lu par CR/slide/CSV) :
    # raw grade/score conservés, grade plafonné explicité, raison + échantillons.
    score_result["language_gate"] = {
        "status": "CAPPED",
        "raw_grade": str(g).upper(),
        "capped_grade": capped,
        "raw_score": raw_score,
        "residue": info.get("residue", 0),
        "where": info.get("where", ""),
        "samples": info.get("samples", []),
        "reason": ("English output contains French labels/content"
                   if (lang or "fr").lower() == "en"
                   else "Sortie EN contenant des labels/contenu français"),
        "message": warn,
    }
    return score_result, info
