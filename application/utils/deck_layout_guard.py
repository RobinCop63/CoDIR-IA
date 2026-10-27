"""Deterministic PPTX repair and validation for chantier H-v2.

The module deliberately separates *repair* from *validation*:

- :func:`repair_deck_layout` performs bounded, idempotent mutations.
- :func:`validate_deck_layout` is read-only and produces the release verdict.
- :func:`apply_deck_layout_guard` remains as a backward-compatible facade for
  builder-level best-effort repair.  It is **not** the release gate.

The application-level release gate lives in ``pptx_delivery_finalizer.py`` and
runs after every enrichment (facts, language/fidelity, confidence, marking).
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple

_FLOOR_PT = 8.0
_EMU_PER_PT = 12700
_EMU_PER_INCH = 914400
_GROUP_TYPE = 6
_CRITICAL_PREFIX = "HCRIT:"
_TEMPORAL_BANNER_PREFIX = "HCRIT:cover:temporal-banner"
_TEMPORAL_BANNER_TOKENS = (
    "analyse rétrospective", "analysis retrospective",
    "retrospective analysis", "retrospective — read only",
    "rétrospective — lecture seule",
)

# Footer lane shared by the H-v2 renderer.  The last 0.305" contains the
# ``Détail : CR §n`` reference; enriched slides must therefore finish their
# body content before this reserved strip.  Keeping the contract here allows
# the repair pass to fix legacy enrichment slides produced before v62.
_FOOTER_BODY_GAP_IN = 0.42

_CONFIDENCE_TITLE_TOKENS = (
    "score de confiance du livrable",
    "delivery confidence score",
)
_MODE_TITLE_TOKENS = (
    "mode partiel",
    "mode générique",
    "partial brief",
    "generic brief",
)
_CONFIDENCE_CARD_LABELS = (
    "qualité des sources", "source quality",
    "mix de contenu", "content mix",
    "cohérence", "consistency",
    "complétude", "completeness",
    "stabilité du run", "run stability",
    "stabilité 1 run", "1-run stability", "stab. exécution", "exec. stability",   # v62.13.9.4.16/18.1 — libellés corrigés
    "confiance secteur", "sector confidence",
)


def _safe_name(shape: Any) -> str:
    try:
        return str(getattr(shape, "name", "") or "")
    except Exception:
        return ""


def _is_group(shape: Any) -> bool:
    try:
        return int(getattr(shape, "shape_type", -1)) == _GROUP_TYPE and hasattr(shape, "shapes")
    except Exception:
        return False


def _shape_text(shape: Any) -> str:
    parts: List[str] = []
    try:
        if getattr(shape, "has_text_frame", False):
            parts.append(str(shape.text_frame.text or ""))
    except Exception:
        pass
    try:
        if getattr(shape, "has_table", False):
            for row in shape.table.rows:
                for cell in row.cells:
                    parts.append(str(cell.text or ""))
    except Exception:
        pass
    if _is_group(shape):
        try:
            for child in shape.shapes:
                txt = _shape_text(child)
                if txt:
                    parts.append(txt)
        except Exception:
            pass
    return "\n".join(x for x in parts if x).strip()


def _has_visible_text_recursive(shape: Any) -> bool:
    return bool(_shape_text(shape))


def _bbox(shape: Any) -> Optional[Tuple[int, int, int, int]]:
    try:
        vals = (shape.left, shape.top, shape.width, shape.height)
        if None in vals:
            return None
        return tuple(int(v) for v in vals)  # type: ignore[return-value]
    except Exception:
        return None


def _outside_canvas(box: Tuple[int, int, int, int], sw: int, sh: int) -> bool:
    l, t, w, h = box
    return l < 0 or t < 0 or l + w > sw or t + h > sh


def _shape_key(slide_idx: int, shape: Any, path: Tuple[int, ...]) -> str:
    try:
        sid = int(getattr(shape, "shape_id", -1))
    except Exception:
        sid = -1
    return f"s{slide_idx}:p{'.'.join(map(str, path))}:id{sid}:n{_safe_name(shape)}"


def iter_shapes_recursive(shapes: Iterable[Any], *, slide_idx: int,
                          path: Tuple[int, ...] = ()) -> Iterator[Tuple[str, Any, int]]:
    """Yield ``(key, shape, depth)`` including children of grouped shapes."""
    for idx, shape in enumerate(shapes):
        child_path = path + (idx,)
        key = _shape_key(slide_idx, shape, child_path)
        yield key, shape, len(path)
        if _is_group(shape):
            try:
                yield from iter_shapes_recursive(shape.shapes, slide_idx=slide_idx,
                                                 path=child_path)
            except Exception:
                continue


def snapshot_layout(prs: Any) -> Dict[str, Tuple[int, int, int, int]]:
    out: Dict[str, Tuple[int, int, int, int]] = {}
    for sidx, slide in enumerate(prs.slides, 1):
        for key, shape, depth in iter_shapes_recursive(slide.shapes, slide_idx=sidx):
            if depth != 0:
                continue
            if getattr(shape, "has_table", False) or _has_visible_text_recursive(shape):
                box = _bbox(shape)
                if box is not None:
                    out[key] = box
    return out


def _clamp_box(shape: Any, sw: int, sh: int) -> bool:
    box = _bbox(shape)
    if box is None:
        return False
    l, t, w, h = box
    nw = max(1, min(w, sw))
    nh = max(1, min(h, sh))
    nl = max(0, min(l, sw - nw))
    nt = max(0, min(t, sh - nh))
    if (nl, nt, nw, nh) == box:
        return False
    shape.width, shape.height = nw, nh
    shape.left, shape.top = nl, nt
    return True


def _iter_text_frames(shape: Any) -> Iterator[Any]:
    try:
        if getattr(shape, "has_text_frame", False):
            yield shape.text_frame
    except Exception:
        pass
    try:
        if getattr(shape, "has_table", False):
            for row in shape.table.rows:
                for cell in row.cells:
                    yield cell.text_frame
    except Exception:
        pass
    if _is_group(shape):
        try:
            for child in shape.shapes:
                yield from _iter_text_frames(child)
        except Exception:
            pass


def _floor_fonts(shape: Any, floor_pt: float = _FLOOR_PT) -> Tuple[int, int]:
    changed = 0
    visited_cells = 0
    try:
        if getattr(shape, "has_table", False):
            visited_cells = sum(len(row.cells) for row in shape.table.rows)
    except Exception:
        pass
    threshold = int(floor_pt * _EMU_PER_PT)
    for tf in _iter_text_frames(shape):
        try:
            for para in tf.paragraphs:
                for run in para.runs:
                    size = run.font.size
                    if size is not None and int(size) < threshold:
                        from pptx.util import Pt
                        run.font.size = Pt(floor_pt)
                        changed += 1
        except Exception:
            continue
    return changed, visited_cells


def _rescale_table(shape: Any, sw: int, sh: int) -> bool:
    changed = _clamp_box(shape, sw, sh)
    try:
        cols = list(shape.table.columns)
        total = sum(int(c.width) for c in cols)
        left = int(shape.left or 0)
        avail = max(1, sw - left)
        if total > avail and total > 0:
            widths = [int(c.width) for c in cols]
            scaled = [max(1, int(w * avail / total)) for w in widths]
            # Keep exact total deterministic by assigning rounding residue to last col.
            residue = avail - sum(scaled)
            scaled[-1] += residue
            for col, width in zip(cols, scaled):
                col.width = width
            try:
                shape.width = sum(scaled)
            except Exception:
                pass
            changed = True
    except Exception:
        pass
    return changed


def _rgb_tuple(value: Any) -> Optional[Tuple[int, int, int]]:
    if value is None:
        return None
    try:
        raw = str(value)
        if len(raw) == 6:
            return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    except Exception:
        pass
    return None


def _relative_luminance(rgb: Tuple[int, int, int]) -> float:
    def chan(v: int) -> float:
        x = v / 255.0
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: Tuple[int, int, int], bg: Tuple[int, int, int]) -> float:
    a, b = _relative_luminance(fg), _relative_luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _is_temporal_banner(shape: Any) -> bool:
    """Identifie un vrai bandeau, jamais un titre qui mentionne le rétrospectif.

    Les anciens decks n'avaient pas toujours le nom HCRIT. Le fallback textuel
    reste donc accepté, mais uniquement pour une forme basse, horizontale et
    située dans la zone de bandeau de couverture.
    """
    if _safe_name(shape).startswith(_TEMPORAL_BANNER_PREFIX):
        return True
    text = _shape_text(shape).lower()
    if not any(token in text for token in _TEMPORAL_BANNER_TOKENS):
        return False
    try:
        top = int(shape.top) / _EMU_PER_INCH
        height = int(shape.height) / _EMU_PER_INCH
        width = int(shape.width) / _EMU_PER_INCH
        return top >= 3.8 and height <= 0.85 and width >= 4.0
    except Exception:
        return False


def _style_temporal_banner(shape: Any) -> bool:
    """Style contractuel du bandeau temporel. Retourne True SEULEMENT si un
    attribut a réellement changé — le compteur du rapport reste à zéro sur un
    bandeau déjà conforme (finition H-v2, 10/08/2026)."""
    if not _is_temporal_banner(shape):
        return False
    changed = False
    try:
        from pptx.dml.color import RGBColor
        from pptx.util import Pt
        _BG = RGBColor(0xE8, 0xB8, 0x4B)
        _FG = RGBColor(0x0D, 0x14, 0x3D)
        try:
            _prev_bg = shape.fill.fore_color.rgb
        except Exception:
            _prev_bg = None
        shape.fill.solid()
        shape.fill.fore_color.rgb = _BG
        if _prev_bg != _BG:
            changed = True
        shape.line.fill.background()
        tf = shape.text_frame
        if tf.word_wrap is not True:
            changed = True
        tf.word_wrap = True
        for _attr, _val in (("margin_left", 91440), ("margin_right", 91440),
                            ("margin_top", 45720), ("margin_bottom", 45720)):
            if getattr(tf, _attr, None) != _val:
                changed = True
            setattr(tf, _attr, _val)
        for para in tf.paragraphs:
            for run in para.runs:
                try:
                    _prev_fg = run.font.color.rgb
                except Exception:
                    _prev_fg = None
                if _prev_fg != _FG or run.font.bold is not True:
                    changed = True
                run.font.color.rgb = _FG
                run.font.bold = True
                if run.font.size is None or int(run.font.size) < int(8.5 * _EMU_PER_PT):
                    run.font.size = Pt(8.5)
                    changed = True
    except Exception:
        pass
    return changed


def _intersection(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> Tuple[int, int, int]:
    al, at, aw, ah = a; bl, bt, bw, bh = b
    iw = max(0, min(al + aw, bl + bw) - max(al, bl))
    ih = max(0, min(at + ah, bt + bh) - max(at, bt))
    return iw, ih, iw * ih


def _significant_overlap(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> bool:
    iw, ih, area = _intersection(a, b)
    if iw <= 0 or ih <= 0:
        return False
    min_area = max(1, min(a[2] * a[3], b[2] * b[3]))
    axis_threshold = int(0.03 * _EMU_PER_INCH)
    return (iw > axis_threshold and ih > axis_threshold and area / min_area >= 0.03)


def _overlap_pairs(snapshot: Mapping[str, Tuple[int, int, int, int]]) -> set[Tuple[str, str]]:
    keys = sorted(snapshot)
    out: set[Tuple[str, str]] = set()
    for i, ka in enumerate(keys):
        sa = ka.split(":", 1)[0]
        for kb in keys[i + 1:]:
            if kb.split(":", 1)[0] != sa:
                continue
            if _significant_overlap(snapshot[ka], snapshot[kb]):
                out.add((ka, kb))
    return out


def _slide_text(slide: Any) -> str:
    """Return all visible slide text, lower-cased for bounded recognisers."""
    parts: List[str] = []
    try:
        for shape in slide.shapes:
            txt = _shape_text(shape)
            if txt:
                parts.append(txt)
    except Exception:
        pass
    return "\n".join(parts).lower()


def _set_box_inches(shape: Any, *, left: float | None = None,
                     top: float | None = None, width: float | None = None,
                     height: float | None = None) -> int:
    """Set a shape box in inches and return the number of changed attributes."""
    changed = 0
    values = {
        "left": left, "top": top, "width": width, "height": height,
    }
    for attr, value in values.items():
        if value is None:
            continue
        target = int(round(float(value) * _EMU_PER_INCH))
        try:
            current = int(getattr(shape, attr))
        except Exception:
            continue
        if current != target:
            try:
                setattr(shape, attr, target)
                changed += 1
            except Exception:
                pass
    return changed


def _set_shape_name(shape: Any, name: str) -> int:
    try:
        if _safe_name(shape) != name:
            shape.name = name
            return 1
    except Exception:
        pass
    return 0


def _cap_explicit_fonts(shape: Any, max_pt: float) -> int:
    """Cap explicit font sizes without touching runs that inherit a theme size."""
    changed = 0
    try:
        from pptx.util import Pt
        for tf in _iter_text_frames(shape):
            for para in tf.paragraphs:
                for run in para.runs:
                    size = run.font.size
                    if size is not None and float(size) / _EMU_PER_PT > max_pt + 1e-6:
                        run.font.size = Pt(max_pt)
                        changed += 1
    except Exception:
        pass
    return changed


def _floor_explicit_fonts(shape: Any, min_pt: float) -> int:
    """Raise explicit font sizes while preserving theme-inherited runs."""
    changed = 0
    try:
        from pptx.util import Pt
        for tf in _iter_text_frames(shape):
            for para in tf.paragraphs:
                for run in para.runs:
                    size = run.font.size
                    if size is not None and float(size) / _EMU_PER_PT < min_pt - 1e-6:
                        run.font.size = Pt(min_pt)
                        changed += 1
    except Exception:
        pass
    return changed


# v62.13.9.4.17 — FRAGMENTS GRAMMATICAUX (contre-audit ChatGPT du 03/09/2026,
# P1-06 / point 8). Le deck réel portait « Définir des expertises cibles
# d'ici fin », « avant oct », « dès . », « -6h/sem », « -un niveau à
# dimensionner/sem » : une compaction ou une réécriture avait coupé DANS un
# groupe date / fourchette. Contrat : aucune puce ne se termine sur une
# préposition temporelle orpheline, aucun fragment « -N unité » ne subsiste.
_DANGLING_TAIL_RE = re.compile(
    r"\s+(?:d['’]ici(?:\s+(?:fin|d[ée]but|mi))?|avant(?:\s+(?:fin|d[ée]but|mi))?|d[èe]s|apr[èe]s|"
    r"à\s+partir\s+d[eu]|depuis|pour|vers|jusqu['’](?:à|en)|au\s+plus\s+tard|"
    r"by|before|from|until|after|since|as\s+of|starting)"
    r"(?:\s+(?:le|la|les|l['’]|the|end\s+of|early|mid))?"
    r"(?:\s+(?:jan|f[ée]v|mars?|avr|mai|juin|juil|ao[uû]t?|sept?|oct|nov|d[ée]c)\.?)?"
    r"\s*[.:;,]?\s*$", re.IGNORECASE)
_DANGLING_RANGE_RE = re.compile(
    r"(?<![\w\d])[-–]\s*(?:\d+(?:[.,]\d+)?\s*(?:h|heures?|hours?|j|jours?|days?|%|€|k€|M€)?|un\s+niveau|une\s+enveloppe|un\s+volume)"
    r"(?:\s+à\s+(?:dimensionner|arbitrer|valider))?\s*/\s*(?:sem|semaine|week|mois|month|an|year|j|jour|day)\b\.?",
    re.IGNORECASE)


def repair_dangling_fragments_text(text: str, lang: str = "fr") -> str:
    """Répare une puce : queue prépositionnelle orpheline retirée, fragment
    « -N unité/période » remplacé par une cadence à arbitrer. Idempotent."""
    out = re.sub(r"\s+", " ", str(text or "")).strip()
    if not out:
        return out
    en = str(lang or "fr").lower().startswith("en")
    out = _DANGLING_RANGE_RE.sub(" — cadence à arbitrer" if not en else " — cadence to arbitrate", out)
    # v62.13.9.4.19.2 — connecteurs de fourchette vidés (« entre et », « de à ») :
    # le chiffre est parti, le connecteur ne doit pas rester.
    out = re.sub(r"\b(?:entre|between)\s+(?:et|and)\b", "", out, flags=re.I)
    out = re.sub(r"\b(?:de|from)\s+(?:à|to)\b", "", out, flags=re.I)
    out = re.sub(r"\s{2,}", " ", out).replace(" —", " —")
    out = re.sub(r"\s+—\s+cadence (?:à arbitrer|to arbitrate)(?:\s+—\s+cadence (?:à arbitrer|to arbitrate))+",
                 " — cadence à arbitrer" if not en else " — cadence to arbitrate", out)
    prev = None
    while prev != out:
        prev = out
        out = _DANGLING_TAIL_RE.sub("", out).rstrip(" ,;:–—-")
    out = re.sub(r"\s+\.$", ".", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


# v62.13.9.4.22 — STATUT DES INFORMATIONS (contre-audit v21, §8) : le CR dit
# « visibilité digitale à investiguer », le deck écrivait « faible visibilité
# digitale » et en faisait le risque principal. Les sujets que le CR marque
# incertains sont relevés ; dans le deck, un adjectif assertif appliqué à ces
# sujets devient « à évaluer ».
_UNCERTAIN_MARK_RE = re.compile(
    r"([a-zà-ÿ][a-zà-ÿ'’ \-]{3,40}?)\s+(?:est\s+|reste\s+|:\s*)?(?:à\s+(?:investiguer|confirmer|v[ée]rifier|[ée]valuer|mesurer|documenter)|non\s+(?:mesur[ée]e?|[ée]tabli[e]?|document[ée]e?|connu[e]?)|inconnu[e]?s?)\b", re.I)
_ASSERTIVE_RE = r"(?:faible|insuffisant[e]?|absence\s+d[e'’]\s*|aucun[e]?\s+|manque\s+d[e'’]\s*|d[ée]faut\s+d[e'’]\s*)"


_SUBJ_STOP = {"la", "le", "les", "l'", "l’", "un", "une", "des", "du", "de", "d'", "d’", "et", "est", "reste", "restent",
              "sont", "son", "sa", "ses", "leur", "leurs", "notre", "nos", "votre", "vos", "ce", "cet", "cette", "ces", "en", "à", "au", "aux"}


def uncertain_subjects(cr_text: str) -> list[str]:
    subjects: list[str] = []
    for m in _UNCERTAIN_MARK_RE.finditer(str(cr_text or "")):
        words = [w for w in re.sub(r"\s+", " ", m.group(1)).strip(" ,;:-").split()]
        # retire les mots vides en tête et en queue (« la », « restent »)
        while words and words[0].lower() in _SUBJ_STOP:
            words.pop(0)
        while words and words[-1].lower() in _SUBJ_STOP:
            words.pop()
        words = words[-3:]
        subj = " ".join(words).lower()
        if len(subj) >= 6 and subj not in subjects:
            subjects.append(subj)
    return subjects


def preserve_uncertainty_text(text: str, subjects: list[str], lang: str = "fr") -> str:
    out = str(text or "")
    if not out or not subjects:
        return out
    en = str(lang or "fr").lower().startswith("en")
    for subj in subjects:
        pat = re.compile(_ASSERTIVE_RE + r"\s*(" + re.escape(subj) + r")\b|\b(" + re.escape(subj) + r")\s+(?:faible|insuffisant[e]?|inexistant[e]?|absent[e]?)\b", re.I)
        out = pat.sub(lambda m: (m.group(1) or m.group(2)) + (" à évaluer" if not en else " to be assessed"), out)
    return out


def _preserve_uncertainty(shape: Any, subjects: list[str], lang: str = "fr") -> int:
    if not getattr(shape, "has_text_frame", False) or not subjects:
        return 0
    n = 0
    try:
        for para in shape.text_frame.paragraphs:
            fixed = preserve_uncertainty_text(para.text, subjects, lang)
            if fixed != para.text:
                if para.runs:
                    para.runs[0].text = fixed
                    for run in para.runs[1:]:
                        run.text = ""
                else:
                    para.text = fixed
                n += 1
    except Exception:
        return n
    return n


def _repair_dangling_fragments(shape: Any, lang: str = "fr") -> int:
    if not getattr(shape, "has_text_frame", False):
        return 0
    count = 0
    try:
        for para in shape.text_frame.paragraphs:
            text = para.text
            fixed = repair_dangling_fragments_text(text, lang)
            if fixed != re.sub(r"\s+", " ", text).strip() and fixed:
                if para.runs:
                    para.runs[0].text = fixed
                    for run in para.runs[1:]:
                        run.text = ""
                else:
                    para.text = fixed
                count += 1
    except Exception:
        return count
    return count


def _repair_dangling_abbreviation(shape: Any) -> int:
    """Remove the v61 orphan ``(ex.`` / ``(e.g.`` from legacy decks.

    v62 fixes sentence compaction at generation time.  Existing diagnostic
    decks have already lost the example after the abbreviation; the safest
    repair is therefore to remove only the dangling fragment.
    """
    if not getattr(shape, "has_text_frame", False):
        return 0
    text = _shape_text(shape).strip()
    cleaned = re.sub(
        r"\s*\((?:ex|e\.g)\.\s*$", "", text, flags=re.IGNORECASE
    ).rstrip()
    if cleaned == text or not cleaned:
        return 0
    try:
        tf = shape.text_frame
        para = tf.paragraphs[0]
        if para.runs:
            para.runs[0].text = cleaned
            for run in para.runs[1:]:
                run.text = ""
        else:
            para.text = cleaned
        # Remove any additional paragraphs in the unlikely event the legacy
        # box contained line breaks after the orphan fragment.
        for extra in tf.paragraphs[1:]:
            for run in extra.runs:
                run.text = ""
        return 1
    except Exception:
        return 0


def _replace_shape_text(shape: Any, text: str) -> int:
    """Replace text while preserving the first run's formatting.

    The delivery finalizer repairs already-generated diagnostic decks.  Using
    ``shape.text = ...`` would reset formatting; this bounded helper only
    updates the existing first run and clears the remaining runs/paragraphs.
    """
    try:
        tf = shape.text_frame
        para = tf.paragraphs[0]
        if para.runs:
            para.runs[0].text = str(text)
            for run in para.runs[1:]:
                run.text = ""
        else:
            para.text = str(text)
        for extra in tf.paragraphs[1:]:
            for run in extra.runs:
                run.text = ""
        return 1
    except Exception:
        return 0


def _infer_slide_lang(slide: Any) -> str:
    text = " ".join(_shape_text(sh) for sh in getattr(slide, "shapes", [])).lower()
    english_markers = (
        "detail: report", "decision usefulness", "source quality",
        "execution plan", "next action", "key question", "to verify",
    )
    return "en" if any(marker in text for marker in english_markers) else "fr"


def _repair_market_facts_table(slide: Any, lang: str) -> int:
    """Bounded migration of the malformed v62.3 market-facts table.

    Future decks are built from the structured v62.4 ledger.  This migration
    only makes an already-generated diagnostic deck honest and readable: raw
    markdown markers are removed and values contaminated by a period are
    replaced by ``À réconcilier — CR`` rather than silently kept.
    """
    try:
        slide_text = " ".join(_shape_text(sh) for sh in slide.shapes).lower()
    except Exception:
        return 0
    if not any(marker in slide_text for marker in (
            "faits marché", "faits marche", "market facts")):
        return 0
    en = str(lang or "fr").lower().startswith("en")
    changed = 0

    def _cell_set(cell: Any, value: str) -> int:
        old = str(getattr(cell, "text", "") or "")
        if old == value:
            return 0
        try:
            cell.text = value
            from pptx.util import Pt
            for para in cell.text_frame.paragraphs:
                for run in para.runs:
                    run.font.size = Pt(8)
            return 1
        except Exception:
            return 0

    def _compact_number(value: str) -> str:
        value = str(value or "").strip().replace(".0–", "–")
        value = re.sub(r"(?<=\d)\.0(?=\D|$)", "", value)
        return value

    for shape in getattr(slide, "shapes", []):
        if not getattr(shape, "has_table", False):
            continue
        table = shape.table
        if not table.rows or len(table.columns) < 5:
            continue
        head = " ".join(str(c.text or "") for c in table.rows[0].cells).lower()
        if not ("métrique" in head or "metric" in head):
            continue
        for row in list(table.rows)[1:]:
            cells = row.cells
            raw_metric = str(cells[0].text or "").replace("**", " ").replace("|", " ")
            blob = " ".join(raw_metric.split()).strip(" -–—")
            low = blob.lower()
            metric = blob[:42] or ("Metric" if en else "Métrique")
            kind = "OTHER"
            if "taille du marché" in low or "market size" in low or "marché français" in low:
                kind = "SIZE"; metric = "Market size" if en else "Taille du marché"
            elif "croissance" in low or "dynamique" in low or "growth" in low:
                kind = "GROWTH"; metric = "Growth / dynamics" if en else "Croissance / dynamique"
            elif "tjm" in low or "niveau de prix" in low or "pricing" in low:
                kind = "PRICING"; metric = "Pricing / daily rate" if en else "Prix / TJM"
            elif "acteurs" in low or "parts" in low or "players" in low:
                kind = "PLAYERS"; metric = "Players / shares" if en else "Acteurs / parts"
            elif "segments" in low or "différenciation" in low or "segments" in low:
                kind = "SEGMENT"; metric = "Segments / trends" if en else "Segments / tendances"
            elif "même base" in low or "same source" in low:
                kind = "SIZE"; metric = "Other scope estimate" if en else "Autre estimation de périmètre"
            elif "missions annuelles" in low or "annual missions" in low:
                kind = "MISSIONS"; metric = "Annual missions" if en else "Nombre de missions / an"
            changed += _cell_set(cells[0], metric)

            raw_value = str(cells[1].text or "").strip()
            value = _compact_number(raw_value)
            if kind == "PRICING" and re.search(r"20\d{2}", raw_value):
                value = "Reconcile — report" if en else "À réconcilier — CR"
            elif kind == "PLAYERS" and re.search(r"20\d{2}.*20\d{2}", raw_value):
                value = "Reconcile — report" if en else "À réconcilier — CR"
            elif kind == "SIZE" and re.fullmatch(r"\d+(?:[.,]\d+)?", value):
                value += " M€"
            elif kind in {"GROWTH", "SEGMENT"} and re.fullmatch(r"[+\-]?\d+(?:[.,]\d+)?(?:–[+\-]?\d+(?:[.,]\d+)?)?", value):
                value += " %"
            elif kind == "MISSIONS" and re.fullmatch(r"\d+(?:–\d+)?", value):
                nums = [f"{int(x):,}".replace(",", " ") for x in value.split("–")]
                value = "–".join(nums) + (" missions" if not en else " missions")
            changed += _cell_set(cells[1], value)
        break
    return changed


def _repair_roadmap_coverage_notes(slide: Any) -> int:
    """Remove obsolete roadmap coverage notes from legacy diagnostic decks.

    The roadmap already displays three explicit actions per horizon and links to
    the Word report.  In v62.3 the generic grey coverage note was placed in the
    same lane as the KPI card and could remain visible behind it after repair.
    New decks no longer create the note unless more than three actions exist;
    for already-generated decks the safest deterministic migration is to clear
    this redundant note rather than move it into another crowded lane.
    """
    try:
        slide_text = " ".join(_shape_text(sh) for sh in slide.shapes).lower()
    except Exception:
        return 0
    if not any(marker in slide_text for marker in (
            "plan d'exécution", "plan d’exécution", "execution plan")):
        return 0
    changed = 0
    for shape in slide.shapes:
        name = _safe_name(shape)
        txt = _shape_text(shape).strip().lower()
        if name.startswith("HNOTE:coverage") or re.search(
                r"\b(?:lignes? sur|of \d+ lines|full detail in the word report)\b", txt):
            if txt:
                changed += _replace_shape_text(shape, "")
    return changed


def _repair_exec_box(shape: Any, lang: str) -> tuple[int, int]:
    """Repair every overflowing ``HCRIT:*`` box deterministically (v62.6).

    Earlier terrain patches listed a few known shape families.  Variable LLM
    wording then exposed a new family at each rerun.  The release contract is
    now generic: known families receive a semantic policy; every other HCRIT
    box is compacted *only if the same validator that gates distribution says
    it overflows*.  Full detail remains in the CR and no font is reduced below
    the 11 pt floor.

    Returns ``(text_changes, geometry_changes)``.
    """
    name = _safe_name(shape)
    if not getattr(shape, "has_text_frame", False) or not name.startswith("HCRIT:"):
        return 0, 0
    try:
        from pptx.util import Inches
        from utils.exec_reading import compact_exec_text

        raw = _shape_text(shape).strip()
        if not raw:
            return 0, 0
        compacted = raw
        text_changes = 0
        geom_changes = 0

        # Semantic policies for narrow, high-impact families.
        if name.startswith("HCRIT:axis:action:"):
            # v62.13.9.4.33 — trois points par carte (décision du 12/09/2026) :
            # un point tient sur une ligne à 11 pt dans une bande de 0,36 po ; le
            # garde ne l'agrandit plus à 0,62 po (ce qui créait des chevauchements
            # entre points d'une même carte). Il ne compacte qu'à la largeur de la bande.
            # v62.13.9.4.37 — amendement H2 du 18/09/2026 : 35 mots / 150 caractères sur
            # deux lignes ; la bande passe à 0,62 po (trois points par carte au plus, pas
            # de 0,66 entre points : pas de chevauchement).
            compacted, _ = compact_exec_text(
                raw, max_words=35, max_chars=350, lang=lang,
                drop_trailing_deadline=True)
            target_h = int(Inches(0.46))
            if int(getattr(shape, "height", 0) or 0) < target_h:
                shape.height = target_h
                geom_changes += 1
        elif name.startswith("HCRIT:roadmap:action:"):
            compacted, _ = compact_exec_text(
                raw, max_words=7, max_chars=44, lang=lang,
                drop_trailing_deadline=True)
        elif name.startswith("HCRIT:roadmap:kpi:"):
            prefix = "KPI : " if raw.lower().startswith("kpi") else ""
            body = re.sub(r"^KPI\s*:\s*", "", raw, flags=re.IGNORECASE)
            short, _ = compact_exec_text(
                body, max_words=6, max_chars=36, lang=lang)
            compacted = prefix + short
        elif (name.startswith("HCRIT:essentiel:kpi:") or
              name.startswith("HCRIT:context:kpi:")) and not (
                  ":kpi-label:" in name or ":kpi-sub:" in name):
            # Migrate a legacy illustrative value that had been promoted to an
            # enterprise KPI. The new builder filters it before construction.
            from utils.exec_reading import is_executive_kpi_value
            if not is_executive_kpi_value(raw):
                compacted = ("Not disclosed" if str(lang).lower().startswith("en")
                             else "Non communiqué")
        elif (name.startswith("HCRIT:essentiel:kpi-sub:") or
              name.startswith("HCRIT:context:kpi-sub:")) and re.search(
                  r"croissance|growth|S[12]\s*20\d{2}|forecast|pr[ée]vision|estim\.",
                  raw, re.IGNORECASE):
            # A market narrative must not be the sub-title of enterprise CA.
            compacted = ("Not available — collect" if str(lang).lower().startswith("en")
                         else "Non disponible — à collecter")

        if compacted and compacted != raw:
            text_changes += _replace_shape_text(shape, compacted)

        # Universal safety net.  Reuse the exact release validator, then reduce
        # the content budget until it fits.  This prevents new HCRIT families
        # from becoming the next terrain blocker without making the gate lax.
        for max_words in (10, 8, 6, 4, 2):
            overflow = _estimated_text_overflow(shape)
            if not overflow:
                break
            current = _shape_text(shape).strip()
            capacity_lines = max(1, int(float(overflow.get("line_capacity") or 1)))
            chars_per_line = max(8, int(overflow.get("chars_per_line") or 20))
            max_chars = max(12, chars_per_line * capacity_lines - 2)
            candidate, _ = compact_exec_text(
                current, max_words=max_words, max_chars=max_chars,
                lang=lang, drop_trailing_deadline=True)
            if candidate and candidate != current:
                text_changes += _replace_shape_text(shape, candidate)
            else:
                break

        # Absolute last resort for a still-overflowing critical box.  The deck
        # remains honest and legible because the complete content and a CR link
        # are preserved elsewhere on the slide.
        if _estimated_text_overflow(shape):
            fallback = "See report" if str(lang).lower().startswith("en") else "Voir CR"
            if _shape_text(shape).strip() != fallback:
                text_changes += _replace_shape_text(shape, fallback)
        return text_changes, geom_changes
    except Exception:
        return 0, 0


def _set_text_margins_inches(shape: Any, *, left: float, right: float,
                             top: float, bottom: float) -> int:
    changed = 0
    try:
        tf = shape.text_frame
        for attr, value in (("margin_left", left), ("margin_right", right),
                            ("margin_top", top), ("margin_bottom", bottom)):
            target = int(round(value * _EMU_PER_INCH))
            if int(getattr(tf, attr) or 0) != target:
                setattr(tf, attr, target)
                changed += 1
    except Exception:
        pass
    return changed


def _rewrite_confidence_source_card(shape: Any, lang: str) -> int:
    """Repair the v61 source-quality card that embedded three evidence lines.

    The evidence already has its dedicated FIDELITY GATE banner.  Repeating it
    in a 1.45" mini-card caused the visible slide-20 collision in the first v61
    terrain rerun.  This migration is deliberately content preserving: only the
    signal score is retained in the card, while the banner remains untouched.
    """
    text = _shape_text(shape)
    low = text.lower()
    if not ("richesse du signal" in low or "signal richness" in low):
        return 0
    match = re.search(
        r"(?:richesse\s+du\s+signal|signal\s+richness)\s*:\s*(\d{1,3})\s*/\s*100",
        text, re.IGNORECASE,
    )
    if not match:
        return 0
    score = match.group(1)
    title = "Source quality" if lang == "en" else "Qualité des sources"
    try:
        from pptx.util import Inches, Pt
        from pptx.enum.text import PP_ALIGN, MSO_VERTICAL_ANCHOR
        from pptx.dml.color import RGBColor
        tf = shape.text_frame
        tf.clear()
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = Inches(0.08)
        tf.margin_top = tf.margin_bottom = Inches(0.04)
        tf.vertical_anchor = MSO_VERTICAL_ANCHOR.MIDDLE
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        p.text = title
        for run in p.runs:
            run.font.size = Pt(11)
            run.font.bold = True
            run.font.color.rgb = RGBColor(255, 255, 255)
        vp = tf.add_paragraph()
        vp.alignment = PP_ALIGN.CENTER
        vp.text = f"{score}/100"
        for run in vp.runs:
            run.font.size = Pt(14)
            run.font.bold = True
            run.font.color.rgb = RGBColor(255, 255, 255)
        return 1
    except Exception:
        return 0


def _repair_mode_slide(slide: Any, slide_height: int) -> int:
    """Move legacy mode-slide disclaimer into the reserved body/footer lane."""
    text = _slide_text(slide)
    if not any(token in text for token in _MODE_TITLE_TOKENS):
        return 0
    changed = 0
    disclaimer_tokens = (
        "livrable exploitable en codir interne",
        "usable in internal codir",
        "le système a produit un livrable démonstratif",
        "the system produced a demonstrative deliverable",
    )
    footer_top_in = slide_height / _EMU_PER_INCH - _FOOTER_BODY_GAP_IN
    for shape in slide.shapes:
        low = _shape_text(shape).lower()
        if not any(token in low for token in disclaimer_tokens):
            continue
        # 0.28" is enough for the one-line disclaimer and leaves a clean
        # 0.12" gap before the CR reference lane.
        changed += _set_box_inches(
            shape, left=0.50, top=max(0.0, footer_top_in - 0.37),
            width=9.00, height=0.26,
        )
        changed += _set_shape_name(shape, "HNOTE:mode:disclaimer")
        changed += _cap_explicit_fonts(shape, 9.0)
    return changed


def _repair_confidence_slide(slide: Any, slide_width: int,
                             slide_height: int) -> Tuple[int, int]:
    """Normalize legacy confidence slides to the v62 10×5.625 layout.

    Returns ``(layout_changes, source_card_rewrites)``.  The function is
    idempotent and only runs on slides carrying the confidence title.
    """
    all_text = _slide_text(slide)
    if not any(token in all_text for token in _CONFIDENCE_TITLE_TOKENS):
        return 0, 0

    changed = 0
    rewrites = 0
    warning_shapes: List[Any] = []
    cards: List[Any] = []
    usage_body: Any = None
    legacy_signal_score: Optional[str] = None
    legacy_signal_lang = "fr"
    existing_evidence_summary: Any = None
    actions_body: Any = None

    for shape in slide.shapes:
        raw = _shape_text(shape).strip()
        low = raw.lower()
        name = _safe_name(shape)
        if not raw:
            continue
        if any(token in low for token in ("fidelity gate", "language gate",
                                          "run à clarifier", "run to clarify")):
            warning_shapes.append(shape)
        if any(low.startswith(label) for label in _CONFIDENCE_CARD_LABELS):
            cards.append(shape)
        if (name == "HCRIT:confidence:usage" or
                low.startswith("• codir interne") or low.startswith("• internal codir") or
                low.startswith("• consultant / manager") or low.startswith("• consultant / transition")):
            usage_body = shape
        if (name == "HINFO:confidence:evidence-summary" or
                ("signal richness:" in low or "richesse du signal :" in low)
                and not any(low.startswith(label) for label in _CONFIDENCE_CARD_LABELS)):
            existing_evidence_summary = shape
        if (name == "HCRIT:confidence:actions" or
                (re.match(r"^1\.\s+", raw) and ("2." in raw or "\x0b2." in raw))):
            actions_body = shape

    # Header / score / label / trend / v62.3 decision usefulness.
    for shape in slide.shapes:
        raw = _shape_text(shape).strip()
        low = raw.lower()
        name = _safe_name(shape)
        if not raw:
            continue
        if name == "HCRIT:confidence:utility-title":
            changed += _set_box_inches(shape, left=3.85, top=0.76, width=2.25, height=0.25)
            changed += _floor_explicit_fonts(shape, 11.0)
        elif name == "HCRIT:confidence:utility-score":
            changed += _set_box_inches(shape, left=3.85, top=1.02, width=1.45, height=0.42)
            changed += _floor_explicit_fonts(shape, 11.0)
        elif name == "HCRIT:confidence:utility-label":
            changed += _set_box_inches(shape, left=5.25, top=0.94, width=4.35, height=0.58)
            changed += _floor_explicit_fonts(shape, 11.0)
        elif name == "HINFO:confidence:evidence-label":
            changed += _set_box_inches(shape, left=3.85, top=1.48, width=5.75, height=0.18)
        elif "/100" in raw and "grade" in low and "\n" in raw:
            changed += _set_box_inches(shape, left=0.40, top=0.72,
                                       width=3.10, height=1.38)
            changed += _set_shape_name(shape, "HCRIT:confidence:score")
            _cap_explicit_fonts(shape, 38.0)
        elif ("premier run" in low or "first run" in low or
              "tendance non calculée" in low or "trend not calculated" in low or
              "vs" in low and "run" in low):
            changed += _set_box_inches(shape, left=3.85, top=1.40,
                                       width=5.75, height=0.25)
            changed += _set_shape_name(shape, "HINFO:confidence:trend")
        elif (low.startswith("score de confiance du livrable") or
              low.startswith("delivery confidence score")):
            changed += _set_box_inches(shape, left=0.40, top=0.20,
                                       width=9.20, height=0.42)
            changed += _set_shape_name(shape, "HCRIT:confidence:title")
        elif (not any(token in low for token in ("gate", "run à clarifier", "run to clarify"))
              and not name.startswith("HCRIT:confidence:utility")
              and name != "HINFO:confidence:evidence-label"
              and float(getattr(shape, "left", 0) or 0) / _EMU_PER_INCH >= 3.5
              and float(getattr(shape, "top", 0) or 0) / _EMU_PER_INCH < 1.5
              and not any(low.startswith(label) for label in _CONFIDENCE_CARD_LABELS)):
            # Descriptive label to the right of the score pill (legacy v62).
            changed += _set_box_inches(shape, left=3.85, top=0.82,
                                       width=5.75, height=0.50)
            changed += _set_shape_name(shape, "HCRIT:confidence:label")
            changed += _cap_explicit_fonts(shape, 13.0)

    # Gate messages share one bounded strip above the score cards. The v62
    # generator already combines all lines in one 0.54" box; legacy decks may
    # carry up to three independent boxes, which are stacked with zero margins.
    if len(warning_shapes) == 1:
        shape = warning_shapes[0]
        changed += _set_box_inches(shape, left=3.85, top=1.68,
                                   width=5.75, height=0.54)
        changed += _set_shape_name(shape, "HCRIT:confidence:gates")
        changed += _floor_explicit_fonts(shape, 11.0)
        changed += _set_text_margins_inches(
            shape, left=0.03, right=0.03, top=0.01, bottom=0.01)
    else:
        for idx, shape in enumerate(warning_shapes[:3]):
            changed += _set_box_inches(shape, left=3.85,
                                       top=1.68 + idx * 0.18,
                                       width=5.75, height=0.18)
            changed += _set_shape_name(shape, f"HCRIT:confidence:gate:{idx}")
            changed += _floor_explicit_fonts(shape, 11.0)
            changed += _set_text_margins_inches(
                shape, left=0.03, right=0.03, top=0.0, bottom=0.0)

    # Normalize the six sub-score cards and repair the legacy first card.
    card_w = 1.45
    for idx, shape in enumerate(cards[:6]):
        changed += _set_box_inches(shape, left=0.40 + idx * 1.50,
                                   top=2.48, width=card_w, height=0.82)
        changed += _set_shape_name(shape, f"HCRIT:confidence:card:{idx}")
        changed += _set_text_margins_inches(
            shape, left=0.08, right=0.08, top=0.04, bottom=0.04)
        if idx == 0:
            _legacy_text = _shape_text(shape)
            _legacy_match = re.search(
                r"(?:richesse\s+du\s+signal|signal\s+richness)\s*:\s*(\d{1,3})\s*/\s*100",
                _legacy_text, re.IGNORECASE,
            )
            if _legacy_match:
                legacy_signal_score = _legacy_match.group(1)
                legacy_signal_lang = (
                    "en" if "signal richness" in _legacy_text.lower() else "fr"
                )
            rewrites += _rewrite_confidence_source_card(
                shape, "en" if "source quality" in _shape_text(shape).lower() else "fr")
        changed += _floor_explicit_fonts(shape, 11.0)

    if legacy_signal_score is not None and existing_evidence_summary is None:
        try:
            from pptx.util import Inches, Pt
            from pptx.enum.text import PP_ALIGN
            from pptx.dml.color import RGBColor
            summary = (
                (f"Signal richness: {legacy_signal_score}/100 · Evidence: 0 page-confirmed — "
                 f"not exploitable · Source quality for score: capped")
                if legacy_signal_lang == "en" else
                (f"Richesse du signal : {legacy_signal_score}/100 · Preuve : 0 confirmé page — "
                 f"non exploitable · Qualité source pour le score : plafonnée")
            )
            box = slide.shapes.add_textbox(
                Inches(0.40), Inches(3.31), Inches(9.20), Inches(0.19)
            )
            box.name = "HINFO:confidence:evidence-summary"
            tf = box.text_frame
            tf.clear(); tf.word_wrap = True
            tf.margin_left = tf.margin_right = Inches(0.02)
            tf.margin_top = tf.margin_bottom = 0
            para = tf.paragraphs[0]
            para.alignment = PP_ALIGN.CENTER
            para.text = summary
            for run in para.runs:
                run.font.size = Pt(9)
                run.font.italic = True
                run.font.color.rgb = RGBColor(88, 96, 112)
            changed += 1
        except Exception:
            pass

    if existing_evidence_summary is not None:
        changed += _set_box_inches(
            existing_evidence_summary, left=0.40, top=3.31, width=9.20, height=0.19
        )
        changed += _set_shape_name(
            existing_evidence_summary, "HINFO:confidence:evidence-summary"
        )
        changed += _set_text_margins_inches(
            existing_evidence_summary, left=0.02, right=0.02, top=0.0, bottom=0.0
        )

    # Titles and bodies below the cards.  Body boxes stop before the CR lane.
    for shape in slide.shapes:
        raw = _shape_text(shape).strip()
        low = raw.lower()
        if low in ("usage recommandé", "recommended use",
                    "usage du document de travail", "work-product use"):
            changed += _set_box_inches(shape, left=0.40, top=3.52,
                                       width=4.70, height=0.25)
            changed += _set_shape_name(shape, "HCRIT:confidence:usage-title")
        elif low in ("actions prioritaires", "priority actions"):
            changed += _set_box_inches(shape, left=5.20, top=3.52,
                                       width=4.40, height=0.25)
            changed += _set_shape_name(shape, "HCRIT:confidence:actions-title")

    if usage_body is not None:
        changed += _set_box_inches(usage_body, left=0.40, top=3.82,
                                   width=4.70, height=1.28)
        changed += _set_shape_name(usage_body, "HCRIT:confidence:usage")
        changed += _floor_explicit_fonts(usage_body, 11.0)
    if actions_body is not None:
        changed += _set_box_inches(actions_body, left=5.20, top=3.82,
                                   width=4.40, height=1.28)
        changed += _set_shape_name(actions_body, "HCRIT:confidence:actions")
        changed += _floor_explicit_fonts(actions_body, 11.0)

    # Defensive final clamp for any non-footer text remaining below the body
    # lane on a confidence slide.
    footer_top = slide_height - int(round(_FOOTER_BODY_GAP_IN * _EMU_PER_INCH))
    for shape in slide.shapes:
        if _safe_name(shape).startswith("HNOTE:cr-ref"):
            continue
        box = _bbox(shape)
        if box is None or not _has_visible_text_recursive(shape):
            continue
        if box[1] < footer_top < box[1] + box[3]:
            try:
                new_h = max(1, footer_top - box[1])
                if int(shape.height) != new_h:
                    shape.height = new_h
                    changed += 1
            except Exception:
                pass

    return changed, rewrites


def repair_deck_layout(prs: Any, result: Any = None) -> Dict[str, Any]:
    """Apply deterministic bounded repairs. Never raises."""
    # v62.13.9.4.22 — sujets incertains du CR (statut à préserver dans le deck)
    _uncertain62422: list[str] = []
    try:
        if isinstance(result, dict):
            _cr62422 = "\n".join(v for v in (result.get("outputs") or {}).values() if isinstance(v, str))
            _uncertain62422 = uncertain_subjects(_cr62422)
    except Exception:
        _uncertain62422 = []
    report: Dict[str, Any] = {
        "phase": "repair", "text_clamped": 0, "tables_rescaled": 0,
        "fonts_floored": 0, "groups_visited": 0, "table_cells_visited": 0,
        "vtabs_seen": 0, "temporal_banners_styled": 0,
        "decorative_bleed_kept": 0,
        "mode_footer_repairs": 0,
        "confidence_layout_repairs": 0,
        "confidence_source_cards_rewritten": 0,
        "dangling_abbreviations_repaired": 0,
        "dangling_fragments_repaired": 0,
        "uncertainty_preserved": 0,
        "exec_boxes_compacted": 0,
        "exec_box_geometry_repairs": 0,
        "roadmap_coverage_notes_removed": 0,
        "market_fact_cells_repaired": 0,
        "errors": [],
    }
    try:
        sw, sh = int(prs.slide_width), int(prs.slide_height)
    except Exception as exc:
        report["errors"].append(f"presentation_geometry:{type(exc).__name__}:{exc}")
        return report

    for sidx, slide in enumerate(prs.slides, 1):
        try:
            _slide_lang = _infer_slide_lang(slide)
            report["roadmap_coverage_notes_removed"] += (
                _repair_roadmap_coverage_notes(slide)
            )
            report["market_fact_cells_repaired"] += (
                _repair_market_facts_table(slide, _slide_lang)
            )
            report["mode_footer_repairs"] += _repair_mode_slide(slide, sh)
            _conf_changes, _conf_rewrites = _repair_confidence_slide(slide, sw, sh)
            report["confidence_layout_repairs"] += _conf_changes
            report["confidence_source_cards_rewritten"] += _conf_rewrites
        except Exception as exc:
            report["errors"].append(
                f"slide={sidx};enrichment_repair:{type(exc).__name__}:{exc}")
        for idx, shape in enumerate(slide.shapes):
            try:
                report["dangling_abbreviations_repaired"] += (
                    _repair_dangling_abbreviation(shape)
                )
                report["dangling_fragments_repaired"] = report.get("dangling_fragments_repaired", 0) + (
                    _repair_dangling_fragments(shape, _slide_lang))   # v62.13.9.4.17
                report["uncertainty_preserved"] = report.get("uncertainty_preserved", 0) + (
                    _preserve_uncertainty(shape, _uncertain62422, _slide_lang))   # v62.13.9.4.22
                _exec_text, _exec_geom = _repair_exec_box(
                    shape, _slide_lang)
                report["exec_boxes_compacted"] += _exec_text
                report["exec_box_geometry_repairs"] += _exec_geom
                if getattr(shape, "has_text_frame", False):
                    try:
                        _ = shape.text_frame
                    except Exception as exc:
                        report["errors"].append(
                            f"slide={sidx};shape={idx};name={_safe_name(shape)};"
                            f"text_frame:{type(exc).__name__}:{exc}")
                        continue
                if _is_group(shape):
                    report["groups_visited"] += 1
                porteur = bool(getattr(shape, "has_table", False)) or _has_visible_text_recursive(shape)
                if getattr(shape, "has_table", False):
                    if _rescale_table(shape, sw, sh):
                        report["tables_rescaled"] += 1
                elif porteur:
                    if _clamp_box(shape, sw, sh):
                        report["text_clamped"] += 1
                else:
                    box = _bbox(shape)
                    if box is not None and _outside_canvas(box, sw, sh):
                        report["decorative_bleed_kept"] += 1
                floors, cells = _floor_fonts(shape)
                report["fonts_floored"] += floors
                report["table_cells_visited"] += cells
                try:
                    report["vtabs_seen"] += _shape_text(shape).count("\x0b")
                except Exception:
                    pass
                if _style_temporal_banner(shape):
                    report["temporal_banners_styled"] += 1
            except Exception as exc:
                report["errors"].append(
                    f"slide={sidx};shape={idx};name={_safe_name(shape)};"
                    f"{type(exc).__name__}:{exc}")
    return report


def _explicit_font_sizes(shape: Any) -> Iterator[float]:
    for tf in _iter_text_frames(shape):
        try:
            for para in tf.paragraphs:
                for run in para.runs:
                    if run.font.size is not None:
                        yield int(run.font.size) / _EMU_PER_PT
        except Exception:
            continue


def _temporal_banner_contrast(shape: Any) -> Optional[float]:
    if not _is_temporal_banner(shape):
        return None
    bg = None
    fg = None
    try:
        bg = _rgb_tuple(shape.fill.fore_color.rgb)
    except Exception:
        pass
    try:
        for para in shape.text_frame.paragraphs:
            for run in para.runs:
                fg = _rgb_tuple(run.font.color.rgb)
                if fg:
                    break
            if fg:
                break
    except Exception:
        pass
    if bg is None or fg is None:
        return 0.0
    return contrast_ratio(fg, bg)


def _glyph_width_em(ch: str) -> float:
    """Deterministic Calibri/Aptos-like advance-width approximation.

    A raw character count over-estimated ordinary French text by 20–30 % and
    blocked the v61 terrain deck although LibreOffice and PowerPoint rendered
    the same HCRIT strings on one or two lines.  Character classes provide a
    much closer, platform-independent estimate without depending on local font
    files or an external renderer.
    """
    if not ch:
        return 0.0
    if ch.isspace():
        return 0.25
    if ch in "ilIjtfr.,:;!'`|()[]{}":
        return 0.28
    if ch in "MWmw@#%&QO0":
        return 0.72
    if ch.isupper():
        return 0.56
    if ch.isdigit():
        return 0.50
    if ch in "-/\\_+=><?":
        return 0.35
    return 0.43


def _text_width_em(text: str) -> float:
    return sum(_glyph_width_em(ch) for ch in str(text or ""))


def _wrapped_line_count(text: str, max_width_em: float) -> int:
    """Greedy word-wrap estimate honoring explicit paragraph/line breaks."""
    if max_width_em <= 0:
        return max(1, len(str(text or "")))
    total = 0
    logical_lines = str(text or "").splitlines() or [str(text or "")]
    for raw in logical_lines:
        words = raw.split()
        if not words:
            total += 1
            continue
        current = 0.0
        lines = 1
        for word in words:
            width = _text_width_em(word)
            sep = _glyph_width_em(" ") if current > 0 else 0.0
            if current + sep + width <= max_width_em + 1e-9:
                current += sep + width
                continue
            if width <= max_width_em:
                lines += 1
                current = width
                continue
            # A single overlong token wraps inside the word.
            chunks = max(1, int(math.ceil(width / max_width_em)))
            lines += chunks if current > 0 else chunks - 1
            remainder = width - (chunks - 1) * max_width_em
            current = max(0.0, remainder)
        total += lines
    return max(1, total)


def _text_frame_margin_pt(shape: Any, attr: str, default_in: float) -> float:
    try:
        tf = shape.text_frame
        value = getattr(tf, attr, None)
        if value is not None:
            return int(value) / _EMU_PER_PT
    except Exception:
        pass
    return default_in * 72.0


def _estimated_text_overflow(shape: Any) -> Optional[Dict[str, Any]]:
    """Deterministic fit estimate for HCRIT text boxes.

    python-pptx does not expose PowerPoint's rendered text-fit result.  This
    estimate is only applied to explicitly tagged critical boxes.  It uses the
    actual text-frame margins, explicit font sizes, paragraph breaks and a
    character-class width model calibrated against the terrain render.  The
    previous 0.52-em raw-character approximation falsely counted the v61 axis
    labels as two lines and roadmap labels as three.
    """
    name = _safe_name(shape)
    if not name.startswith(_CRITICAL_PREFIX) or getattr(shape, "has_table", False):
        return None
    try:
        if not getattr(shape, "has_text_frame", False):
            return None
        box = _bbox(shape)
        if box is None:
            return None
        text = str(shape.text_frame.text or "")
        if not text.strip():
            return None
        sizes = list(_explicit_font_sizes(shape))
        font_pt = max(sizes) if sizes else 12.0
        width_pt = max(
            1.0,
            box[2] / _EMU_PER_PT
            - _text_frame_margin_pt(shape, "margin_left", 0.10)
            - _text_frame_margin_pt(shape, "margin_right", 0.10),
        )
        height_pt = max(
            1.0,
            box[3] / _EMU_PER_PT
            - _text_frame_margin_pt(shape, "margin_top", 0.05)
            - _text_frame_margin_pt(shape, "margin_bottom", 0.05),
        )
        max_width_em = width_pt / max(1.0, font_pt)
        needed = _wrapped_line_count(text, max_width_em)
        # Calibri/Aptos default line spacing is close to 1.0× for the compact
        # executive boxes.  1.02 retains a small safety margin while allowing
        # the two-line roadmap labels verified in the rendered terrain deck.
        line_capacity = height_pt / max(1.0, font_pt * 1.02)
        chars_per_line = max(1, int(max_width_em / 0.43))
        if needed > line_capacity + 0.12:
            return {
                "shape": name, "needed_lines": needed,
                "line_capacity": round(line_capacity, 2), "font_pt": round(font_pt, 2),
                "chars_per_line": chars_per_line, "text": text[:240],
            }
    except Exception:
        return None
    return None


def validate_deck_layout(prs: Any,
                         before_snapshot: Optional[Mapping[str, Tuple[int, int, int, int]]] = None,
                         *, min_contrast: float = 4.5) -> Dict[str, Any]:
    """Read-only release validation. Never mutates ``prs`` and never raises."""
    report: Dict[str, Any] = {
        "phase": "validation", "out_of_canvas_text": [],
        "out_of_canvas_tables": [], "created_overlaps": [],
        "critical_ellipses": [], "critical_text_overflow": [],
        "contrast_failures": [], "font_below_floor": [],
        "group_child_outside": [], "errors": [],
        "blocking": False,
    }
    try:
        sw, sh = int(prs.slide_width), int(prs.slide_height)
    except Exception as exc:
        report["errors"].append(f"presentation_geometry:{type(exc).__name__}:{exc}")
        report["blocking"] = True
        return report

    after = snapshot_layout(prs)
    for sidx, slide in enumerate(prs.slides, 1):
        for key, shape, depth in iter_shapes_recursive(slide.shapes, slide_idx=sidx):
            try:
                box = _bbox(shape)
                is_table = bool(getattr(shape, "has_table", False))
                visible = _has_visible_text_recursive(shape)
                if depth == 0 and box is not None and _outside_canvas(box, sw, sh):
                    if is_table:
                        report["out_of_canvas_tables"].append({"shape": key, "box": box})
                    elif visible:
                        report["out_of_canvas_text"].append({"shape": key, "box": box})
                    # Text-free decorative bleed is intentional and was already
                    # counted by the repair report; it is never a delivery blocker.
                if is_table:
                    try:
                        total = sum(int(c.width) for c in shape.table.columns)
                        if depth == 0 and int(shape.left or 0) + total > sw:
                            report["out_of_canvas_tables"].append(
                                {"shape": key, "column_total": total, "left": int(shape.left or 0)})
                    except Exception as exc:
                        report["errors"].append(f"{key}:table:{type(exc).__name__}:{exc}")
                for size in _explicit_font_sizes(shape):
                    if size + 1e-6 < _FLOOR_PT:
                        report["font_below_floor"].append({"shape": key, "pt": round(size, 2)})
                name = _safe_name(shape)
                txt = _shape_text(shape)
                if name.startswith(_CRITICAL_PREFIX) and ("…" in txt or "..." in txt):
                    report["critical_ellipses"].append({"shape": key, "text": txt[:240]})
                overflow = _estimated_text_overflow(shape)
                if overflow is not None:
                    overflow["shape_key"] = key
                    report["critical_text_overflow"].append(overflow)
                ratio = _temporal_banner_contrast(shape)
                if ratio is not None and ratio < min_contrast:
                    report["contrast_failures"].append({"shape": key, "ratio": round(ratio, 3)})
                if depth > 0 and box is not None:
                    # Group child coordinates are group-local in OOXML. A negative
                    # child position is always invalid; positive overflow is checked
                    # conservatively when parent extents are available.
                    if box[0] < 0 or box[1] < 0:
                        report["group_child_outside"].append({"shape": key, "box": box})
            except Exception as exc:
                report["errors"].append(f"{key}:{type(exc).__name__}:{exc}")

    if before_snapshot is not None:
        before_pairs = _overlap_pairs(before_snapshot)
        after_pairs = _overlap_pairs(after)
        report["created_overlaps"] = [list(p) for p in sorted(after_pairs - before_pairs)]

    blocking_keys = (
        "out_of_canvas_text", "out_of_canvas_tables", "created_overlaps",
        "critical_ellipses", "critical_text_overflow", "contrast_failures",
        "font_below_floor", "errors",
    )
    report["blocking"] = any(bool(report[k]) for k in blocking_keys)
    return report


def apply_deck_layout_guard(prs: Any) -> Dict[str, Any]:
    """Backward-compatible builder facade: repair + validation report.

    This function remains fail-open for legacy callers.  The application-level
    finalizer decides whether the deck is distributable.
    """
    before = snapshot_layout(prs)
    repair = repair_deck_layout(prs)
    validation = validate_deck_layout(prs, before)
    merged = dict(repair)
    merged.update({
        "blocking": validation.get("blocking", False),
        "out_of_canvas_text": validation.get("out_of_canvas_text", []),
        "out_of_canvas_tables": validation.get("out_of_canvas_tables", []),
        "created_overlaps": validation.get("created_overlaps", []),
        "critical_ellipses": validation.get("critical_ellipses", []),
        "critical_text_overflow": validation.get("critical_text_overflow", []),
        "contrast_failures": validation.get("contrast_failures", []),
        "font_below_floor": validation.get("font_below_floor", []),
        "validation_errors": validation.get("errors", []),
    })
    # Historical contract expects an integer ``errors`` counter.
    merged["errors"] = len(repair.get("errors", [])) + len(validation.get("errors", []))
    return merged


__all__ = [
    "apply_deck_layout_guard", "repair_deck_layout", "validate_deck_layout",
    "snapshot_layout", "iter_shapes_recursive", "contrast_ratio",
]
