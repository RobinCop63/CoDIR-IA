"""9.4.65 — recette de la 9.4.64 (séance 3, 15/10/2026) : le CR et la synthèse disaient « orientation ADOPTÉE par le
conseil : option 2 », le deck affichait « Décision : Option 1 » (couverture et diapositive 2) — la génération prenait la
première option listée. Ce contrôle, appliqué au deck livré :
  1. aligne toute « Décision : Option X » (et la mention de couverture) sur l'option ADOPTÉE quand le conseil a tranché ;
  2. retire les lignes d'engagement qui ne sont pas des actions (une date seule, un mot seul, un fragment sans verbe) ;
  3. remplace une carte restée sur son gabarit (« Description. ») par « Voir le compte rendu » ;
  4. ne présente jamais la date de la séance, ou une date passée, comme « prochaine échéance ».
"""
from __future__ import annotations

import re
from datetime import date

_OPT = re.compile(r"(?i)\b(d[ée]cision|decision)\s*:\s*option\s*(\d)\b")
_COVER_OPT = re.compile(r"(?i)^\s*option\s*(\d)\b")
_DATE_ONLY = re.compile(r"^\s*(?:\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})(?:\s*\([^)]{0,30}\))?\s*\.?\s*$")
_VERB = re.compile(r"(?i)\b\w+(?:er|ir|re|oir)\b|\b(?:revue|lancement|mise|cadrage|suivi|point|validation|"
                   r"arbitrage|plan|audit|signature|publication)\b")


def _set_text(shape, text: str) -> None:
    tf = shape.text_frame
    runs = [r for p in tf.paragraphs for r in p.runs]
    if not runs:
        tf.text = text
        return
    runs[0].text = text
    for r in runs[1:]:
        r.text = ""


_NOUN = re.compile(r"(?i)^(?:revue|lancement|mise|cadrage|suivi|point|validation|arbitrage|audit|signature|publication|"
                   r"pr[ée]sentation|r[ée]union|comit[ée]|review|launch|kick-?off)\b")


def _is_action(text: str) -> bool:
    """Une action commence par un verbe à l'infinitif, ou par un nom d'action suivi d'au moins trois mots."""
    t = str(text or "").strip()
    if not t or _DATE_ONLY.match(t):
        return False
    words = re.findall(r"[A-Za-zÀ-ÿ]{2,}", t)
    first = words[0].lower() if words else ""
    if len(words) >= 3 and re.search(r"(?:er|ir|re|oir)$", first) and first not in ("entre", "autre", "notre", "votre", "titre", "contre"):
        return True
    return len(words) >= 4 and bool(_NOUN.match(t))


def _qualified_headcount65(claims) -> dict:
    """{valeur: libellé qualifié} pour les effectifs d'un AUTRE périmètre (« Entité — Effectif : 114 (2024, comptes sociaux) »),
    seulement si aucun effectif du périmètre de la cible (ligne non qualifiée) n'existe pour la même valeur."""
    q, plain = {}, set()
    for c in claims or ():
        if not isinstance(c, dict) or str(c.get("metric_id") or "").upper() != "HEADCOUNT":
            continue
        line = str(c.get("executive_line") or "")
        m = re.match(r"^\s*(.+?)\s+—\s+[^:]{1,30}:\s*([\d\s.,]+)\s*\(([^)]*)\)", line)
        if m:
            val = re.sub(r"\D", "", m.group(2))
            if val:
                q[val] = (m.group(1).strip(), m.group(3).strip())
        else:
            mv = re.search(r":\s*([\d\s.,]+)", line)
            if mv:
                plain.add(re.sub(r"\D", "", mv.group(1)))
    return {k: v for k, v in q.items() if k not in plain}


def guard_deck65(prs, board_option: str = "", run_date: str = "", lang: str = "fr", claims=None) -> dict:
    rep = {"decision_fixed": 0, "rows_removed": 0, "placeholders": 0, "deadline_fixed": 0, "headcount_qualified": 0}
    en = str(lang).lower().startswith("en")
    _hq65 = _qualified_headcount65(claims)
    if _hq65:
        # 9.4.65 — essai natif Mac du 17/10 (LM01) : CR et synthèse disaient « <Filiale> — Effectif : <n> (<année>, comptes
        # sociaux) », la carte du deck n'affichait que « 114 / Effectif », lu comme l'effectif du groupe. La carte reprend
        # l'entité et la nature du fait ; rien n'est additionné, aucun effectif de groupe n'est inventé.
        for slide in prs.slides:
            shapes = [sh for sh in slide.shapes if getattr(sh, "has_text_frame", False)]
            vals = {re.sub(r"\D", "", sh.text_frame.text): sh for sh in shapes
                    if re.fullmatch(r"\s*[\d\s.,]{1,9}\s*", sh.text_frame.text or "")}
            hit = [v for v in vals if v in _hq65]
            if not hit:
                continue
            ent, nat = _hq65[hit[0]]
            for sh in shapes:
                if re.fullmatch(r"(?i)\s*(effectif|headcount|employees)\s*", sh.text_frame.text or ""):
                    _set_text(sh, (f"Headcount {ent} ({nat})" if en else f"Effectif {ent} ({nat})"))
                    rep["headcount_qualified"] += 1
    bo = str(board_option or "").strip()
    en = str(lang).lower().startswith("en")
    try:
        rd = date.fromisoformat(str(run_date)[:10]) if run_date else None
    except Exception:
        rd = None
    for slide in prs.slides:
        for sh in list(slide.shapes):
            if getattr(sh, "has_text_frame", False):
                txt = sh.text_frame.text or ""
                m = _OPT.search(txt)
                # 9.4.65 (contre-recette du 17/10) — sans décision du conseil, « Décision : … » désigne une recommandation
                _md65 = re.match(r"(?i)^\s*(d[ée]cision|decision)\s*:\s*(.+)$", txt.strip(), re.S)
                if not bo and _md65:
                    _set_text(sh, ("Recommendation: " if en else "Recommandation : ") + _md65.group(2).strip())
                    rep["decision_fixed"] += 1
                    continue
                if bo and m and m.group(2) != bo:
                    _set_text(sh, (f"Decision: Option {bo} (adopted by the Board)" if en else
                                   f"Décision : Option {bo} (adoptée par le conseil)"))
                    rep["decision_fixed"] += 1
                    continue
                mc = _COVER_OPT.match(txt)
                if bo and mc and mc.group(1) != bo and len(txt) < 400 and re.search(r"(?i)non retenue|not (?:selected|retained)", txt):
                    _set_text(sh, (f"Option {bo} — adopted by the Board" if en else f"Option {bo} — adoptée par le conseil"))
                    rep["decision_fixed"] += 1
                    continue
                if bo and txt.strip() in ("Option 1", "Option 2", "Option 3") and txt.strip() != f"Option {bo}":
                    _set_text(sh, f"Option {bo}")
                    rep["decision_fixed"] += 1
                    continue
                _ph65 = txt.strip() in ("Description.", "Description")
                try:   # revue de publication du 16/10 (F03) : intertitre seul (« Constat. », « Parades. », « Horizon. »)
                    from utils.analysis_objects import is_subheading65 as _sh65
                    _ph65 = _ph65 or _sh65(txt)
                    _mt65 = re.match(r"^(.{1,40}?:\s*)(\S.{0,20})$", txt.strip())
                    if not _ph65 and _mt65 and _sh65(_mt65.group(2)):
                        _set_text(sh, _mt65.group(1) + ("see the minutes" if en else "voir le compte rendu"))
                        rep["placeholders"] += 1
                        continue
                except Exception:
                    pass
                if _ph65:
                    _set_text(sh, "See the minutes" if en else "Voir le compte rendu")
                    rep["placeholders"] += 1
                    continue
                md = re.search(r"(PROCHAINE ÉCHÉANCE|NEXT DEADLINE)\s*:\s*(\d{1,2})/(\d{1,2})/(\d{4})", txt)
                if md and rd:
                    try:
                        d = date(int(md.group(4)), int(md.group(3)), int(md.group(2)))
                        if d <= rd:
                            _set_text(sh, ("NEXT DEADLINE: see the action plan" if en else "PROCHAINE ÉCHÉANCE : voir le plan d'action"))
                            rep["deadline_fixed"] += 1
                    except Exception:
                        pass
            if getattr(sh, "has_table", False):
                tbl = sh.table
                if len(tbl.columns) >= 2 and re.search(r"(?i)^(action|engagement|commitment)", tbl.cell(0, 0).text.strip()):
                    rows = list(tbl._tbl.tr_lst)
                    drop = []
                    for tr in rows[1:]:                       # textes lus AVANT toute suppression
                        tcs = tr.tc_lst
                        first = "".join(tcs[0].itertext()) if tcs else ""
                        if not _is_action(first):
                            drop.append(tr)
                    if drop and len(drop) == len(rows) - 1:     # aucune vraie action : une ligne de renvoi au CR
                        keep = drop.pop(0)
                        for tc in keep.tc_lst:
                            for tnode in tc.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t"):
                                tnode.text = ""
                        _t0 = list(keep.tc_lst[0].iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t"))
                        if _t0:
                            _t0[0].text = "See the action plan in the minutes" if en else "Voir le plan d'action du compte rendu"
                    for tr in drop:
                        tbl._tbl.remove(tr)
                        rep["rows_removed"] += 1
    return rep
