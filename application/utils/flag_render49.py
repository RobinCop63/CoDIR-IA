"""v62.13.9.4.49 — RENDU DU SIGNALEMENT (doctrine « tout livrer, tout signaler en place », décision de
Robin Sauzet du 28/09/2026, format validé le même jour).

Les détecteurs du produit (registre, règle éditoriale, garde de rigueur, mainteneur, contrôle final,
rapprochement du réalisé) ne réécrivent plus rien : ils posent une étiquette de statut « ⟨statut : …⟩ »
sur le passage concerné. Ce module est le SEUL à transformer ces étiquettes en ce que voit le lecteur :

- le passage garde sa formulation et ses chiffres d'origine, il est SURLIGNÉ ;
- il est suivi d'un marqueur « ⚠ à vérifier — motif » (« ⚠ to verify — reason »), qui survit au
  copier-coller, contrairement au surlignage ;
- en PREMIÈRE PAGE, un encadré donne le nombre de passages à vérifier et la liste (section, extrait,
  motif) ; au-delà de 25, la liste complète est placée en fin de document ;
- sur la synthèse et le deck, un BANDEAU « À reprendre avant diffusion » précède l'encadré.

Les paragraphes écrits par ce module portent le marqueur produit U+2063 : les contrôles ne les
rejugent pas. Le rendu est idempotent (un document déjà rendu n'est pas rendu deux fois).
"""
from __future__ import annotations

import io
import re
from typing import Any

from docx import Document
from docx.enum.text import WD_COLOR_INDEX

PRODUCT_MARK = "\u2063"
_TAG_RE = re.compile(r"\s*⟨\s*(?:statut|status)\s*:\s*([^⟩]*)(?:⟩|$)", re.I)
BOX_MAX_ROWS = 25

_MOTIFS = {
    # libellé d'étiquette (FR ou EN)                 → (motif FR, motif EN)
    "cible déclarée — non étayée": ("cible sans pièce", "unsourced target"),
    "declared target — unsupported": ("cible sans pièce", "unsourced target"),
    "non étayé — à documenter": ("chiffre sans pièce", "unsourced figure"),
    "unsupported — to document": ("chiffre sans pièce", "unsourced figure"),
    "marché non sourcé": ("marché non sourcé", "unsourced market figure"),
    "unsourced market figure": ("marché non sourcé", "unsourced market figure"),
    "tendance non établie": ("tendance non établie", "trend not established"),
    "trend not established": ("tendance non établie", "trend not established"),
    "valeur non établie": ("valeur non établie", "value not established"),
    "value not established": ("valeur non établie", "value not established"),
}


def _en(lang: str) -> bool:
    return str(lang or "fr").lower().startswith("en")


def motif_for(label: str, lang: str) -> str:
    key = re.sub(r"\s+", " ", str(label or "")).strip().rstrip(";").strip()
    if key.lower() in {k.lower() for k in _MOTIFS}:
        fr, en = next(v for k, v in _MOTIFS.items() if k.lower() == key.lower())
        return en if _en(lang) else fr
    return key[:110] or ("unsourced figure" if _en(lang) else "chiffre sans pièce")


def marker_text(motif: str, lang: str) -> str:
    return (" ⚠ to verify — " if _en(lang) else " ⚠ à vérifier — ") + str(motif)


def _iter_paragraphs(doc):
    """Paragraphes du corps et des tableaux DANS L'ORDRE DU DOCUMENT (audit du 29/09/2026 : en parcourant
    d'abord tous les paragraphes puis tous les tableaux, chaque cellule héritait du DERNIER titre du document
    comme section ; l'encadré attribuait ainsi 106 passages à la dernière section)."""
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    for child in doc.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, doc), None
        elif tag == "tbl":
            tbl = Table(child, doc)
            seen = []                                   # éléments <w:tc> déjà vus (cellules fusionnées)
            for row in tbl.rows:
                for cell in row.cells:
                    # NE PAS comparer des id() : les mandataires python-docx sont recréés et un id libéré est
                    # réutilisé — des cellules distinctes étaient sautées (audit du 29/09/2026 : 85 rangées
                    # d'un vrai CR sorties avec leurs étiquettes brutes, sans marqueur)
                    if any(cell._tc is s for s in seen):
                        continue
                    seen.append(cell._tc)
                    for p in cell.paragraphs:
                        yield p, cell


def _remove_tags_from_runs(paragraph) -> list[str]:
    """Retire les étiquettes du texte des runs (même coupées entre runs) ; renvoie leurs libellés."""
    full = "".join(r.text for r in paragraph.runs)
    labels = [m.group(1) for m in _TAG_RE.finditer(full)]
    if not labels:
        return []
    spans = [(m.start(), m.end()) for m in _TAG_RE.finditer(full)]
    pos = 0
    for r in paragraph.runs:
        t = r.text
        keep = []
        for i, ch in enumerate(t):
            g = pos + i
            if not any(s <= g < e for s, e in spans):
                keep.append(ch)
        r.text = "".join(keep)
        pos += len(t)
    return labels


def _heading_text(p) -> str:
    try:
        name = str(p.style.name or "")
    except Exception:
        name = ""
    return p.text.strip() if (name.lower().startswith("heading") or name.lower().startswith("titre")) else ""


_CITED_SOURCE50 = re.compile(r"(?i)\bsource\s*:|\(source|\bp\.\s?\d+|\bpages?\s+\d+|\b10-K\b|\b20-F\b|rapport\s+(?:annuel|TCFD|RSE|ESG|"
                            r"de\s+gestion)|annual\s+report|document\s+d['’]enregistrement|TCFD\s+report")


def _cited_source_motif50(motif: str, text: str, lang: str) -> str:
    """v62.13.9.4.50 — « chiffre sans pièce » est faux quand la ligne CITE sa pièce (« source : rapport TCFD 2025 p.8 ») :
    la valeur n'a simplement pas été rapprochée des faits extraits. Échantillon du vrai CR du 30/09 : faits ESG sourcés
    signalés « sans pièce ». Le motif dit alors ce qui manque réellement."""
    if motif in ("chiffre sans pièce", "unsourced figure", "nombre sans pièce", "number without a source") and _CITED_SOURCE50.search(text or ""):
        return "source cited, not reconciled with the extracted facts" if _en(lang) else "source citée, non rapprochée des faits extraits"
    return motif


_ANNEX_HEADING50 = re.compile(
    r"(?i)(?:^|\s|—\s)(?:annexe|appendix|annex)\b.{0,60}(?:sc[ée]narios?|scenarios?|quantified|registre|register|m[ée]moire|memory|suivi)"
    r"|Registre des passages signalés|Register of flagged passages|Registre embarqué|Embedded register"
    r"|Registre exhaustif|Exhaustive register")


_TECH_LINE61 = re.compile(
    r"(?i)^\W*(?:score|indice\s+de\s+confiance|confiance|confidence|dur[ée]e|temps\s+(?:de\s+)?(?:traitement|g[ée]n[ée]ration)|"
    r"run\s*id|identifiant|version|build|tableau\s+\d|table\s+\d|figure\s+\d|annexe\s+\d|page\s+\d|source\s*:|sources\s*:)"
    r"|qualit[ée]\s+des?\s+sources?|richesse\s+du\s+signal|qualit[ée]\s+source\s+pour\s+le\s+score|preuve\s*:\s*\d+\s+confirm"
    r"|source\s+quality|signal\s+richness|evidence\s*:\s*\d+\s+confirm"
    r"|\b\d{1,3}\s?/\s?(?:10|20|100)\b|\b\d+(?:[.,]\d+)?\s?(?:s|ms|secondes?|seconds?|min(?:utes?)?)\b(?!\s*(?:de\s+)?(?:CA|ventes))")


def render_flags(doc, lang: str = "fr", mode: str = "work") -> dict:
    """Transforme les étiquettes en signalement visible, pose l'encadré (et le bandeau hors mode travail)."""
    if any(PRODUCT_MARK + "FLAGBOX" in p.text for p in doc.paragraphs):
        return {"flagged": 0, "entries": [], "already_rendered": True}
    entries: list[dict] = []
    section = ""
    in_annex = False
    for p, cell in _iter_paragraphs(doc):
        if cell is None:
            h = _TAG_RE.sub("", _heading_text(p)).strip()
            if h:
                section = h
                # v62.13.9.4.50 — contre-recette du 30/09 (A04) : les annexes (scénarios, registre, mémoire) recopient
                # des passages du corps ; elles ne sont plus RÉANNOTÉES (115 et 83 marqueurs d'annexe dans les deux CR)
                in_annex = bool(_ANNEX_HEADING50.search(h))
            elif cell is None and _ANNEX_HEADING50.search(p.text or ""):
                in_annex = True
        if "⟨" not in p.text:
            continue
        labels = _remove_tags_from_runs(p)
        if not labels:
            continue
        if in_annex or (p.text or "").lstrip().startswith(("SCN-", PRODUCT_MARK + "SCN-")):
            continue                                   # étiquette retirée, sans marqueur ni décompte
        if not re.sub(r"[\s|·—–-]+", "", p.text or ""):
            continue      # v62.13.9.4.50 — ligne de statut seule (sans contenu) : rien à signaler au lecteur
        motif = "; ".join(dict.fromkeys(_cited_source_motif50(motif_for(l, lang), p.text, lang) for l in labels))
        # 9.4.61 — l'exemption des lignes techniques (A60-02) s'applique À LA SOURCE (garde exécutive) : une étiquette
        # présente est toujours rendue, pour que le rendu reste idempotent d'une passe à l'autre
        for r in p.runs:
            if r.text.strip():
                r.font.highlight_color = WD_COLOR_INDEX.YELLOW
        mk = p.add_run(marker_text(motif, lang))
        mk.bold = True
        mk.font.highlight_color = WD_COLOR_INDEX.YELLOW
        excerpt = re.sub(r"\s+", " ", "".join(r.text for r in p.runs[:-1])).strip()
        entries.append({"section": section[:60], "excerpt": excerpt[:80], "motif": motif})
    _insert_box(doc, entries, lang, mode)
    return {"flagged": len(entries), "entries": entries, "already_rendered": False}


def _new_par_after(anchor_el, doc, text: str, bold: bool = False, highlight: bool = False):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    if highlight:
        run.font.highlight_color = WD_COLOR_INDEX.YELLOW
    el = p._p
    el.getparent().remove(el)
    anchor_el.addnext(el)
    return p


def _table_after(anchor_el, doc, rows: list[dict], lang: str):
    hdr = ("Section", "Excerpt", "Reason") if _en(lang) else ("Section", "Extrait", "Motif")
    t = doc.add_table(rows=1, cols=3)
    try:
        t.style = "Table Grid"
    except Exception:
        pass
    for i, h in enumerate(hdr):
        t.rows[0].cells[i].text = PRODUCT_MARK + h
    for e in rows:
        c = t.add_row().cells
        c[0].text = PRODUCT_MARK + (e["section"] or "—")
        c[1].text = PRODUCT_MARK + (e["excerpt"] or "—")
        c[2].text = PRODUCT_MARK + e["motif"]
    el = t._tbl
    el.getparent().remove(el)
    anchor_el.addnext(el)
    return t


def _insert_box(doc, entries: list[dict], lang: str, mode: str) -> None:
    # après le titre du document s'il en a un (style Title / Heading 1 / Titre), sinon tout en haut
    first = None
    for p in doc.paragraphs[:12]:
        try:
            name = str(p.style.name or "").lower()
        except Exception:
            name = ""
        if p.text.strip() and (name in ("title", "titre") or name in ("heading 1", "titre 1")):
            first = p._p
            break
    if first is None and doc.paragraphs:
        first = doc.paragraphs[0]._p
    n = len(entries)
    en = _en(lang)
    if first is None:
        return
    anchor = first
    if mode != "work":
        anchor = _new_par_after(anchor, doc, PRODUCT_MARK + (
            f"TO BE REVISED BEFORE CIRCULATION — {n} passage(s) to verify (see the box below)." if en else
            f"À REPRENDRE AVANT DIFFUSION — {n} passage(s) à vérifier (voir l'encadré ci-dessous)."),
            bold=True, highlight=True)._p
    head = (f"⚠ {n} passage(s) to verify in this document — each is highlighted in place and followed by "
            "“⚠ to verify — reason”." if en else
            f"⚠ {n} passage(s) à vérifier dans ce document — chacun est surligné en place et suivi de "
            "« ⚠ à vérifier — motif ».") if n else (
            "No passage flagged for verification in this document." if en else
            "Aucun passage signalé à vérifier dans ce document.")
    box = _new_par_after(anchor, doc, PRODUCT_MARK + "FLAGBOX" + PRODUCT_MARK + head, bold=True, highlight=bool(n))
    if not n:
        return
    tbl = _table_after(box._p, doc, entries[:BOX_MAX_ROWS], lang)
    # v62.13.9.4.50 — décision Robin du 01/10/2026 : l'annexe du registre ayant quitté le Word, une seule ligne dit où
    # se trouve le registre complet (aucune annexe)
    _reg50 = _new_par_after(tbl._tbl, doc, PRODUCT_MARK + (
        "Full register of flagged passages: the package's evidence file (JSON and CSV)." if en else
        "Registre complet des passages signalés : fichier probatoire du paquet (JSON et CSV)."))
    tbl = type("T50", (), {"_tbl": _reg50._p})()
    if n > BOX_MAX_ROWS:
        # Au-delà de 25, pas de liste en fin de document : sur le run de campagne de référence, la liste
        # complète (281 rangées) ajoutait une dizaine de pages et portait le CR de 30 à 42 pages rendues,
        # pour répéter ce que le surlignage montre déjà en place. La liste complète est conservée dans le
        # diagnostic du paquet (post-contrôle, « flags.entries »).
        _new_par_after(tbl._tbl, doc, PRODUCT_MARK + (
            f"… and {n - BOX_MAX_ROWS} more, highlighted in the text (full list in the package diagnostic)." if en else
            f"… et {n - BOX_MAX_ROWS} autres, surlignés dans le texte (liste complète dans le diagnostic du paquet)."))


def render_flags_in_docx_bytes(payload: bytes, lang: str = "fr", mode: str = "work") -> tuple[bytes, dict]:
    doc = Document(io.BytesIO(payload))
    summary = render_flags(doc, lang, mode)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue(), summary


# ── Constats du contrôle final → étiquettes (doctrine : le contrôle final signale, il ne retire plus) ──
_FINAL_MOTIFS = {
    # raison ou motif du contrôle final           → (FR, EN) ; « {q} » = grandeur relevée
    "claimed_but_not_certifiable": ("nombre « {q} » sans pièce", "number “{q}” without a source"),
    "projection_with_uncertified_magnitude": ("projection sans pièce", "unsourced projection"),
    "declared_prospective_magnitude": ("cible sans pièce", "unsourced target"),
    "gate": ("projection sans pièce", "unsourced projection"),
    "board": ("chiffre sans pièce", "unsourced figure"),
    "quality": ("contrôle qualité", "quality check"),
}


def final_motif(kind: str, lang: str, quantity: str = "") -> str:
    fr, en = _FINAL_MOTIFS.get(str(kind or ""), _FINAL_MOTIFS["gate"])
    txt = en if _en(lang) else fr
    if "{q}" in txt:
        txt = txt.format(q=str(quantity or "?")) if quantity else (
            "number without a source" if _en(lang) else "nombre sans pièce")
    return txt


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace(PRODUCT_MARK, "")).strip().lower()


_PRODUCT_HEADERS50 = ({"topic", "action", "owner", "deadline"}, {"sujet", "action", "porteur", "échéance"},
                      {"date", "new", "carried"}, {"date", "nouvelles", "reconduites"}, {"date", "nouvelles", "reprises"})


def _product_table50(cells) -> bool:
    names = {re.sub(r"[^\wéèêàç ]", "", str(c or "").replace(PRODUCT_MARK, "")).strip().lower() for c in cells}
    return any(h <= names for h in _PRODUCT_HEADERS50)


def tag_units(doc, units: list[tuple[str, str]], lang: str = "fr") -> tuple[int, list[str]]:
    """Pose une étiquette « ⟨statut : motif⟩ » sur chaque paragraphe qui contient une unité signalée par le
    contrôle final (comparaison sur les 80 premiers caractères normalisés). Un paragraphe déjà étiqueté
    reçoit le motif supplémentaire. Renvoie (nombre d'unités localisées, unités introuvables)."""
    word = "status" if _en(lang) else "statut"
    placed, missing = 0, []
    # v62.13.9.4.50 — les constats de la porte et de l'oracle ne se posent jamais dans un tableau ÉCRIT PAR LE PRODUIT
    # (registre des actions, chronologie) : échantillon du vrai CR du 30/09, 14 rangées de ces tableaux signalées
    _prod_tc50 = []
    for _tb50 in doc.tables:
        if _tb50.rows and _product_table50([c.text for c in _tb50.rows[0].cells]):
            _prod_tc50.extend(c._tc for r in _tb50.rows for c in r.cells)
    paras = [p for p, cell in _iter_paragraphs(doc) if cell is None or not any(cell._tc is x for x in _prod_tc50)]
    # texte des rangées du produit, cellules jointes comme le contrôle final les cite (« Sujet | Action | … »)
    _prod_texts50 = []
    for _tb50 in doc.tables:
        if _tb50.rows and _product_table50([c.text for c in _tb50.rows[0].cells]):
            for _r50 in _tb50.rows:
                _cells50 = [c.text for c in _r50.cells]
                _prod_texts50.append(_norm(" | ".join(_cells50)))
                _prod_texts50.extend(_norm(c) for c in _cells50 if c.strip())
    for unit, motif in units:
        # 9.4.61 — contre-recette du 12/10 (A60-02) : une ligne technique écrite par CoDIR IA (score, qualité des sources,
        # durée, référence) n'est pas un chiffre métier ; même exemption qu'à la source, sans la compter introuvable
        if _TECH_LINE61.search(str(unit or "")) and not re.search(r"(?:M|k|Md|bn|m)\s?[$€£]|[$€£]\s?\d|\d\s?%", str(unit or "")):
            continue
        # Une unité peut couvrir plusieurs lignes : on signale la ou les lignes qui portent un chiffre, pas la
        # première ligne par défaut (audit du 29/09/2026 : « Action: Designate senior executive… scenarios. »,
        # sans aucun chiffre, portait le signalement de la ligne chiffrée qui la suivait).
        lines = [l for l in str(unit or "").splitlines() if l.strip()]
        targets = [l for l in lines if re.search(r"\d", l)] or lines[:1]
        done = False
        for line in targets:
            key = _norm(line)[:80]
            if not key:
                continue
            hit = next((p for p in paras if key in _norm(p.text)), None)
            if hit is None:
                continue
            tag = f" ⟨{word} : {motif}⟩"
            if motif not in hit.text:
                hit.add_run(tag)
            done = True
        if done:
            placed += 1
        elif _prod_texts50 and any(_norm(l)[:80] and _norm(l)[:80] in pt for l in (targets or lines) for pt in _prod_texts50):
            continue      # constat sur une rangée d'un tableau du PRODUIT : exempté, ni posé ni « non localisé »
        else:
            missing.append(str(unit)[:120])
    return placed, missing


def add_document_flags(doc, messages: list[str], lang: str = "fr") -> int:
    """Constats qui portent sur le document entier (audit de qualité) : un paragraphe signalé sous le titre."""
    if not messages or not doc.paragraphs:
        return 0
    word = "status" if _en(lang) else "statut"
    anchor = doc.paragraphs[0]._p
    for m in messages:
        p = _new_par_after(anchor, doc, (("Quality check: " if _en(lang) else "Contrôle qualité : ") + str(m)
                                          + f" ⟨{word} : {final_motif('quality', lang)}⟩"))
        anchor = p._p
    return len(messages)


def flag_final_control_in_docx_bytes(payload: bytes, units: list[tuple[str, str]], quality: list[str],
                                     lang: str = "fr", mode: str = "work") -> tuple[bytes, dict]:
    """Doctrine du 28/09 : les constats du contrôle final deviennent des signalements, puis toutes les
    étiquettes du document sont rendues (surlignage, marqueur, encadré, bandeau). Rien n'est retiré."""
    doc = Document(io.BytesIO(payload))
    placed, missing = tag_units(doc, units, lang)
    add_document_flags(doc, quality, lang)
    summary = render_flags(doc, lang, mode)
    out = io.BytesIO()
    doc.save(out)
    summary.update({"final_control_units": len(units), "final_control_placed": placed,
                    "final_control_not_located": missing[:10], "quality_flags": len(quality)})
    return out.getvalue(), summary


# ── Deck (ébauche) : même doctrine — marqueur en place, bandeau sur la première diapositive ──────────
def _deck_motif50(motif: str) -> str:
    """v62.13.9.4.50 — sur une diapositive, le motif est court (contre-recette du 30/09, D02 : deux annotations de la
    diapositive 7 débordaient sous la carte) ; la formulation complète reste dans le Word."""
    m = re.sub(r"\s+", " ", str(motif or "")).strip()
    return m if len(m) <= 42 else m[:40].rstrip(" ;:,—-") + "…"


def _is_product_kpi_card51(shape) -> bool:
    """9.4.51 — carte de chiffre clé COMPOSÉE PAR LE PRODUIT à partir des faits confirmés (forme nommée « …:kpi:… ») :
    le contrôle final ne l'étiquette pas « projection sans pièce » (recette du 02/10/2026 : « 620 M$ », « 103,8 M$ » et
    « 58,1 M$ », confirmés à la page, sortaient signalés sur la diapositive des chiffres clés). Seule une valeur courte
    (une grandeur, pas une phrase) est exemptée ; une phrase d'agent placée dans une carte reste contrôlée."""
    try:
        name = str(getattr(shape, "name", "") or "")
        if not re.search(r"(?i):kpi(?::|$)", name):
            return False
        txt = shape.text_frame.text.strip()
        return bool(txt) and len(txt) <= 40 and not re.search(r"[.;:]\s+\w", txt)
    except Exception:
        return False


def tag_units_in_pptx_bytes(payload: bytes, units: list[tuple[str, str]], lang: str = "fr") -> tuple[bytes, int]:
    """v62.13.9.4.50 — pose une étiquette « ⟨statut : motif⟩ » sur chaque paragraphe de diapositive qui contient une unité
    signalée, SANS la rendre : le rendu unique du deck (application) la convertit en marqueur et compte le bandeau."""
    from pptx import Presentation
    prs = Presentation(io.BytesIO(payload))
    word = "status" if _en(lang) else "statut"
    keys = [(_norm(u)[:80], m) for u, m in units if _norm(u)]
    tagged = 0
    for slide in prs.slides:
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False) or not shape.has_text_frame:
                continue
            if _is_product_kpi_card51(shape):
                continue
            for para in shape.text_frame.paragraphs:
                txt = "".join(r.text for r in para.runs)
                if not txt.strip() or PRODUCT_MARK in txt or "⟨" in txt or "⚠ " in txt:
                    continue
                n = _norm(txt)
                hit = next((m for k, m in keys if k and (k in n or (len(n) >= 25 and n[:80] in k))), None)
                if hit is None:
                    continue
                para.add_run().text = f" ⟨{word} : {hit}⟩"
                tagged += 1
    out = io.BytesIO(); prs.save(out)
    return out.getvalue(), tagged


def render_flags_in_pptx_bytes(payload: bytes, units: list[tuple[str, str]], lang: str = "fr") -> tuple[bytes, dict]:
    """Chaque paragraphe de diapositive qui contient une unité signalée reçoit « ⚠ à vérifier — motif »
    (gras, couleur d'alerte ; le PowerPoint n'a pas de surlignage portable) ; la première diapositive
    reçoit le bandeau « À reprendre avant diffusion — N passages à vérifier ». Rien n'est retiré."""
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Pt, Emu
    prs = Presentation(io.BytesIO(payload))
    en = _en(lang)
    keys = [(_norm(u)[:80], m) for u, m in units if _norm(u)]
    flagged = 0
    entries: list[dict] = []
    for si, slide in enumerate(prs.slides, start=1):
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False) or not shape.has_text_frame:
                continue
            if _is_product_kpi_card51(shape):
                continue
            for para in shape.text_frame.paragraphs:
                txt = "".join(r.text for r in para.runs)
                if not txt.strip() or PRODUCT_MARK in txt or "⚠ " in txt:
                    continue
                # v62.13.9.4.50 — étiquettes posées par la réparation du deck (le finaliseur ne réécrit plus) :
                # elles deviennent des marqueurs, comme dans le Word
                _labels50 = _remove_tags_from_runs(para) if "⟨" in txt else []
                if _labels50:
                    _mot50 = "; ".join(dict.fromkeys(motif_for(l, lang) for l in _labels50))
                    run = para.add_run()
                    run.text = marker_text(_deck_motif50(_mot50), lang)
                    run.font.bold = True
                    run.font.size = Pt(8)          # v62.13.9.4.50 — marqueur compact : il ne déborde plus de la carte
                    run.font.color.rgb = RGBColor(0xB4, 0x3C, 0x00)
                    flagged += 1
                    entries.append({"slide": si, "excerpt": re.sub(r"\s+", " ", "".join(r.text for r in para.runs))[:120],
                                    "motif": _mot50})
                    continue
                n = _norm(txt)
                hit = next((m for k, m in keys if k and (k in n or (len(n) >= 25 and n[:80] in k))), None)
                if hit is None:
                    continue
                run = para.add_run()
                run.text = marker_text(_deck_motif50(hit), lang)
                run.font.bold = True
                run.font.size = Pt(8)
                run.font.color.rgb = RGBColor(0xB4, 0x3C, 0x00)
                flagged += 1
                entries.append({"slide": si, "excerpt": re.sub(r"\s+", " ", txt)[:120], "motif": hit})
    if prs.slides:
        s1 = prs.slides[0]
        width = prs.slide_width or Emu(9144000)
        box = s1.shapes.add_textbox(Emu(int(width * 0.03)), Emu(int(Pt(4))), Emu(int(width * 0.94)), Emu(int(Pt(22))))
        p = box.text_frame.paragraphs[0]
        r = p.add_run()
        r.text = PRODUCT_MARK + ((f"TO BE REVISED BEFORE CIRCULATION — {flagged} passage(s) to verify, each followed by "
                                  "“⚠ to verify — reason”." if flagged else "No passage flagged for verification in this deck.")
                                 if en else
                                 (f"À REPRENDRE AVANT DIFFUSION — {flagged} passage(s) à vérifier, chacun suivi de "
                                  "« ⚠ à vérifier — motif »." if flagged else "Aucun passage signalé à vérifier dans ce deck."))
        r.font.bold = bool(flagged)
        r.font.size = Pt(11)
        if flagged:
            r.font.color.rgb = RGBColor(0xB4, 0x3C, 0x00)
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue(), {"flagged": flagged, "entries": entries[:50], "units": len(units)}
