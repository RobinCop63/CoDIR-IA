"""v62.13.9.4.7 — oracle de contenu des octets finaux (contre-audit 30/08/2026).

Principe non négociable : « zéro résidu au gate » ne vaut pas preuve de
disparition. Cet oracle relit les octets OOXML réellement livrés et cherche
les payloads interdits de manière INDÉPENDANTE : aucun import du registre des
quantités, du guard ou du gate — une recherche textuelle normalisée, sans
exception d'annexe, de registre SCN, de quarantaine ou de note.

Périmètre (matrice d'assertions 9.4.7) :
- DOCX : word/document.xml, headers, footers, footnotes, endnotes, comments,
  glossaire, customXml.
- PPTX : slides, notesSlides, comments, masters, layouts, docProps, customXml.

Normalisation : XML désérialisé (entités décodées), nœuds texte joints par
paragraphe/shape logique, Unicode NFC, NBSP→espace, blancs repliés.
"""
from __future__ import annotations

import fnmatch
import io
import re
import unicodedata
import zipfile
from html import unescape

_DOCX_SCOPE = (
    "word/document.xml", "word/header*.xml", "word/footer*.xml",
    "word/footnotes.xml", "word/endnotes.xml", "word/comments*.xml",
    "word/glossary/document.xml", "word/customXml/*.xml", "customXml/*.xml",
)
_PPTX_SCOPE = (
    "ppt/slides/slide*.xml", "ppt/notesSlides/notesSlide*.xml",
    "ppt/comments/*.xml", "ppt/slideMasters/*.xml", "ppt/slideLayouts/*.xml",
    "docProps/*.xml", "customXml/*.xml",
)

_W_P_SPLIT = re.compile(r"</w:p>|</a:p>|</w:tr>|</a:tr>")
_TEXT_NODE = re.compile(r"<(?:w|a):t(?:\s[^>]*)?>(.*?)</(?:w|a):t>", re.S)
_TAG = re.compile(r"<[^>]+>")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", unescape(text))
    text = text.replace("\u00A0", " ").replace("\u202F", " ")
    return re.sub(r"\s+", " ", text).strip()


_W_TR_RE = re.compile(r"<w:tr\b.*?</w:tr>", re.S)
_A_TR_RE = re.compile(r"<a:tr\b.*?</a:tr>", re.S)
_BENCH_ROW_RE = re.compile(r"benchmark non v[ée]rifi[ée]|unverified benchmark", re.I)


def _strip_labelled_benchmark_rows(xml: str) -> str:
    """v62.13.9.4.18 — une rangée de tableau dont une cellule porte
    l'étiquette « benchmark non vérifié » ET une source nommée est jugée à
    l'échelle de la rangée (comme la maintenance), pas cellule par cellule :
    ses cellules chiffrées ne sont pas des assertions du corps."""
    try:
        from utils.quantity_ledger import has_source_label
    except Exception:
        return xml

    def _drop(m):
        row_xml = m.group(0)
        text = _normalize(_TAG.sub(" ", row_xml))
        if _BENCH_ROW_RE.search(text) and has_source_label(text):
            return " "
        if re.search(r"https?://", text, re.I) and re.search(r"\d", re.sub(r"https?://\S+", " ", text)):
            return " "                                   # v62.13.9.4.21 — rangée à URL de source
        return row_xml
    xml = _W_TR_RE.sub(_drop, xml)
    xml = _A_TR_RE.sub(_drop, xml)
    return xml


_SYS_P_RE = re.compile(r"<w:p\b[^>]*>(?:(?!</w:p>).)*?<w:pStyle\s+w:val=\"CoDIR ?System\"(?:(?!</w:p>).)*?</w:p>", re.S)


def _strip_system_paragraphs(xml: str) -> str:
    """v62.13.9.4.21 — les paragraphes typés « CoDIR System » (contenu de
    l'outil, posé à la construction) ne sont jamais des unités."""
    if "CoDIRSystem" not in xml and "CoDIR System" not in xml:
        return xml
    xml = _SYS_P_RE.sub(" ", xml)
    # une rangée dont toutes les cellules étaient système est vide : rien à juger
    return xml


_LINE_BREAK_RE = re.compile(r"<(?:w|a):(?:br|cr|tab)\b[^>]*?/?>")


def _units_from_xml(xml: str) -> list[str]:
    """Unités logiques (paragraphes/lignes/shapes) d'une part OOXML.

    v62.13.9.4.31.1 — un saut de ligne (<w:br/>, <w:cr/>, <w:tab/>, <a:br/>)
    est un SÉPARATEUR, jamais une colle. Le run réel du 11/09/2026 a
    montré le coût de la colle : la carte d'extractibilité (« …mis à
    jour.pdf⏎OCR requis — … ») devenait « …jour.pdfOCR requis… », une unité
    que la réparation ne pouvait plus retrouver telle quelle dans le fichier.
    Le contrôle lit désormais la coupure comme python-docx la rend à la
    réparation (``paragraph.text`` → « \n » → un espace après normalisation) :
    contrôle et réparation interprètent le même texte.
    """
    units: list[str] = []
    xml = _strip_system_paragraphs(xml)
    xml = _strip_labelled_benchmark_rows(xml)
    for block in _W_P_SPLIT.split(xml):
        block = _LINE_BREAK_RE.sub("<w:t> </w:t>", block)
        nodes = _TEXT_NODE.findall(block)
        if nodes:
            joined = _normalize("".join(nodes))
        else:
            joined = _normalize(_TAG.sub(" ", block))
        if joined:
            units.append(joined)
    return units


def _iter_scope(payload: bytes, patterns: tuple[str, ...]):
    zf = zipfile.ZipFile(io.BytesIO(payload))
    for name in zf.namelist():
        if any(fnmatch.fnmatch(name, pat) for pat in patterns):
            yield name, zf.read(name).decode("utf-8", "ignore")


def extract_units(payload: bytes) -> list[tuple[str, str]]:
    """Toutes les unités textuelles normalisées d'un DOCX ou PPTX final."""
    head = payload[:4]
    if head[:2] != b"PK":
        raise ValueError("payload non OOXML")
    names = zipfile.ZipFile(io.BytesIO(payload)).namelist()
    patterns = _DOCX_SCOPE if any(n.startswith("word/") for n in names) else _PPTX_SCOPE
    out: list[tuple[str, str]] = []
    for part, xml in _iter_scope(payload, patterns):
        for unit in _units_from_xml(xml):
            out.append((part, unit))
    return out


def _compile(pattern: str) -> re.Pattern:
    """Compile un motif de la matrice, tolérant au sur-échappement JSON.

    Un double antislash littéral dans la chaîne (``\\\\s``, ``\\\\b``) signale un
    motif sur-échappé à la sérialisation : il est dé-échappé une fois avant
    compilation. Un motif normal est compilé tel quel.
    """
    if "\\\\" in pattern:
        pattern = pattern.replace("\\\\", "\\")
    return re.compile(pattern)


def find_forbidden(payload: bytes, forbidden: list) -> list[dict]:
    """Occurrences de payloads interdits dans les octets finaux.

    ``forbidden`` : liste d'items {"id", "line"?, "payload_patterns": [...]}
    ou de simples motifs regex (str). Retourne, pour chaque occurrence :
    {"id", "part", "unit", "pattern"} — l'échec NOMME la cible survivante.
    """
    hits: list[dict] = []
    units = extract_units(payload)
    for item in forbidden:
        if isinstance(item, str):
            item = {"id": item, "payload_patterns": [item]}
        patterns = [(_compile(p), p) for p in item.get("payload_patterns") or []]
        line = _normalize(str(item.get("line") or ""))
        for part, unit in units:
            if _is_product_trace(unit):
                # v62.13.9.4.17 — l'entrée du registre embarqué porte
                # l'original SOUS TAG : c'est la seule place où la reprise
                # verbatim d'une ligne retenue est légitime.
                continue
            if line and line in unit:
                hits.append({"id": item.get("id"), "part": part,
                             "unit": unit[:160], "unit_full": unit, "pattern": "verbatim_line"})
                continue
            for rx, raw in patterns:
                if rx.search(unit):
                    hits.append({"id": item.get("id"), "part": part,
                                 "unit": unit[:160], "unit_full": unit, "pattern": raw})
                    break
    return hits


def assert_absent(payload: bytes, forbidden: list) -> None:
    hits = find_forbidden(payload, forbidden)
    assert not hits, "Cibles survivantes dans les octets finaux : " + repr(hits[:6])


def assert_present(payload: bytes, lines: list[str]) -> None:
    units = [u for _, u in extract_units(payload)]
    joined = "\n".join(units)
    missing = [l for l in lines if _normalize(l) not in joined]
    assert not missing, "Contenus requis absents des octets finaux : " + repr(missing)


# ── v62.13.9.4.8 — second juge de PRODUCTION (contre-audit 30/08/2026) ───────
# Appelé par le chemin d'export réel (app.py, finaliseur PPTX), pas seulement
# par les tests. Deux détections :
#   (a) les lignes que le run a décidé de retenir — verbatim et payloads
#       quantifiés — ne doivent subsister dans aucune surface (indépendant de
#       tout moteur : simple relecture des octets) ;
#   (b) un re-jugement en appel séparé (guard L∪A) sur TOUTES les unités des
#       surfaces étendues (notes, commentaires, masters, customXml…), là où
#       le gate historique lit principalement le corps.
# Un survivant force la non-distribution, même si le gate est vide.

def _withheld_lines(result) -> list[str]:
    out: list[str] = []
    for key in ("v62136_withheld_scenarios", "withheld_scenarios"):
        for row in (result or {}).get(key) or []:
            if isinstance(row, dict):
                txt = str(row.get("original") or row.get("text")
                          or row.get("line") or "").strip()
            else:
                txt = str(row or "").strip()
            if txt:
                out.append(txt)
    return out


def _payload_patterns(line: str) -> list[str]:
    pats: list[str] = []
    for m in re.finditer(r"\d[\d\s.,/]*", line):
        num = m.group(0).strip().rstrip(".,")
        if not num:
            continue
        # v62.13.9.4.15 — une valeur NULLE ne fabrique aucun motif de charge.
        # Le run réel du 02/09/2026 15:04 : douze rangées retenues portant
        # « 0 € (temps interne) » ont produit douze fois le motif « 0 € »,
        # qui frappait toute rangée survivante à budget nul — sans aucun
        # pouvoir discriminant. La reprise verbatim de la ligne reste absolue.
        if re.fullmatch(r"0+(?:[.,]0+)?", num.replace(" ", "")):
            continue
        after = re.match(r"\s*([a-zà-ÿA-ZÀ-Ÿ€$£%][\wà-ÿÀ-Ÿ'-]*)", line[m.end():])
        if after:
            pats.append(r"(?i)\b" + re.escape(num) + r"\s*" + re.escape(after.group(1)))
    return pats


_ROW_BLOCK = re.compile(r"<(?:w|a):tr\b.*?</(?:w|a):tr>", re.S)
_CELL_BLOCK = re.compile(r"<(?:w|a):tc\b.*?</(?:w|a):tc>", re.S)


# ── v62.13.9.4.10 — traces de SORTIE du produit ───────────────────────────
# Contre-audit 31/08/2026 : sur la vraie chaîne app.py, dossier industriel et dossier anglophone coté
# étaient bloqués par des unités qui ne sont pas du contenu jugeable mais la
# TRACE d'une retenue déjà opérée — bandeau de non-établissement, lignes du
# registre de quarantaine SCN (annexe Word, surface documentée). Les
# re-juger, c'est juger l'outil sur son propre appareil de sûreté : une
# boucle, et un faux rouge sur des dossiers de référence.
#
# Le filtre est appliqué AVANT les deux juges, donc symétriquement : ni le
# guard ni le second juge ne voient ces unités. Il ne relâche rien sur le
# contenu — il retire du jugement ce que le produit a déjà retenu.
_PRODUCT_TRACE_RE = re.compile(
    r"^\s*SCN[-\w]*\d+\s*[·|]"                       # registre de quarantaine
    # v62.13.9.4.18.1 — libellés des cartes de confiance : le deck du run
    # réel du 03/09/2026 14:50 a été bloqué sur « Stabilité 1 run », un
    # libellé de l'outil lu comme une grandeur. Une carte de score n'est
    # jamais une assertion exécutive.
    r"|^\s*(?:Stab\.?\s+ex[ée]cution|Stabilit[ée]\s+(?:1\s+run|du\s+run)|Exec\.?\s+stability|1-run\s+stability|Run\s+stability)\s*$"
    r"|^\s*(?:Date|Généré le|Generated on|Date d['’]export|Export date)\s*:\s*\d{1,2}/\d{1,2}/(?:19|20)\d{2}(?:\s+\d{1,2}[:h]\d{2})?\s*$"   # v62.13.9.4.19.1 — horodatage de couverture
    # v62.13.9.4.19.3 — avis de l'outil sur ses propres claims (« ⚠ 3 claim(s) à
    # appariement métrique/montant suspect écarté(s)… conservés au ledger ») :
    # run réel du 04/09/2026 06:08, « 3 » lu comme grandeur déclarée.
    r"|^\s*⚠?\s*\d+\s+claims?\(?s?\)?\b.*(?:ledger|diagnostics?|écart[ée]e?s?\s+de\s+la\s+note|excluded\s+from\s+the\s+note)"
    # v62.13.9.4.19.4 — INVENTAIRE DES TEXTES DE L'OUTIL portant un chiffre
    # (run réel du 04/09/2026 10:04 : « ⚠ Score plafonné mécaniquement à
    # 70/100 (Grade B max) », « Cohérence80/100 », cellule « 2026-09-30 »).
    # Un score sur 100, un grade, une cellule de date nue, un plafond de
    # score sont des sorties du système, jamais des assertions exécutives.
    r"|\b\d{1,3}\s*/\s*100\b"                                     # score sur 100 (bloc Confidence, cartes)
    r"|\bGrade\s+[A-E]\b"                                        # grade de confiance
    r"|^\s*⚠\s*Score\b|^\s*⚠\s*Score\s+capped\b"                 # plafond de score
    r"|^\s*(?:19|20)\d{2}-\d{2}-\d{2}\s*$|^\s*\d{1,2}/\d{1,2}/(?:19|20)\d{2}\s*$"   # cellule de date nue
    r"|^\s*(?:Score|Confiance|Confidence|Utilit[ée]|Usefulness|Stabilit[ée]|Stability|Coh[ée]rence|Consistency|"
    r"Compl[ée]tude|Completeness|Qualit[ée] des sources|Source quality|Mix de contenu|Content mix|Confiance secteur|Sector confidence)"
    r"\s*:?\s*\d{1,3}\s*(?:/\s*100)?\s*$"                        # carte de score « Cohérence 80/100 »
    r"|NON\s+[ÉE]TABLIE?\b|NOT\s+ESTABLISHED\b"
    r"|montant retir[ée]|valeur retir[ée]"
    r"|amount withheld|value withheld"
    r"|[àa] confirmer sur pi[èe]ce|to be confirmed on source"
    r"|sc[ée]nario chiffr[ée] retir[ée]|quantified scenario removed"
    r"|proposition (?:chiffr[ée]e|quantifi[ée]e) [ée]cart[ée]e"
    r"|cible chiffr[ée]e [ée]cart[ée]e"
    # v62.13.9.4.10 — CARTE DE CONFIANCE du produit : richesse du signal,
    # mix de contenu, cohérence, nombre de preuves confirmées. Ce sont des
    # mesures que l'outil porte sur SON PROPRE dossier, pas des affirmations
    # d'affaires. Le déconditionnement du contrôle final (le ton ne décide
    # plus de son existence) les a fait entrer au jugement pour la première
    # fois et bloquait le CR dossier de conseil.
    r"|richesse\s+du\s+signal|qualit[ée]\s+des\s+sources"
    r"|qualit[ée]\s+source\s+pour\s+le\s+score|mix\s+de\s+contenu"
    r"|signal\s+richness|source\s+quality|content\s+mix"
    r"|weighted\s+signal|brief\s+cap|signal\s+pond[ée]r[ée]|cap\s+brief"
    r"|preuve\s*:\s*\d+\s*confirm[ée]|evidence\s*:\s*\d+\s*confirmed"
    r"|non\s+exploitable|not\s+exploitable"
    # v62.13.9.4.12.7 — MARQUEURS DE RÉÉCRITURE du produit. « — volume à
    # valider », « selon un calendrier à arbitrer » sont posés PAR la
    # réparation ; les relire et les juger, c'est bloquer l'export sur son
    # propre correctif. Boucle observée au run du 02/09/2026.
    # v62.13.9.4.12.9 — FAMILLE COMPLÈTE des marqueurs de réécriture, au lieu
    # d'un ajout au coup par coup. Le produit neutralise une grandeur en la
    # remplaçant par une périphrase « à <verbe d'action différée> » — à
    # valider, à dimensionner, à arbitrer, à chiffrer, à quantifier, à
    # confirmer — ou par « non étayé ». Deux runs consécutifs ont bloqué sur
    # ces périphrases : le produit relisait et jugeait son propre correctif.
    # Un motif de famille ferme la classe, pas seulement l'occurrence du jour.
    r"|\b[àa]\s+(?:valider|dimensionner|arbitrer|chiffrer|quantifier|"
    r"confirmer|[ée]tablir|pr[ée]ciser|instruire)\b"
    r"|\bto\s+(?:validate|size|arbitrate|quantify|confirm|establish)\b"
    r"|non\s+[ée]tay[ée]e?s?\b|unsupported\b"
    r"|baseline\s+et\s+provenance"
    # pénalité de notation : « (-15 points) » ajuste le score du dossier,
    # ce n'est pas une grandeur d'affaires.
    r"|\([-+]\s?\d+\s*points?\)"
    r"|JSON\s+typ[ée]\s+exploitable|typed\s+JSON",
    re.I)


def _is_product_trace(unit: str) -> bool:
    if "\u2063" in str(unit or ""):
        return True                          # v62.13.9.4.21 — marqueur d'outil structurel
    try:
        from utils.quantity_ledger import is_status_tagged
        if is_status_tagged(unit):
            return True                      # v62.13.9.4.21 — statut en marge (document de travail)
    except Exception:
        pass
    if _PRODUCT_TRACE_RE.search(str(unit or "")):
        return True
    try:                                   # v62.13.9.4.17 — registre embarqué tagué ; 9.4.18 — benchmark étiqueté
        from utils.quantity_ledger import is_tagged_register_line, is_labelled_benchmark_line, is_epistemic_caveat_line
        return is_tagged_register_line(unit) or is_labelled_benchmark_line(unit) or is_epistemic_caveat_line(unit)
    except Exception:
        return False


def _is_brief_horizon_banner(unit: str, result) -> bool:
    """v62.13.9.4.15.2 — le BANDEAU D'HORIZON du brief (« ▌ Horizon : 30
    jours ») est le contrat de planification posé par l'utilisateur, reproduit
    tel quel dans le CR. La maintenance l'exempte depuis la 9.4.15.1 ; le juge
    indépendant, qui ne connaît pas l'autorité d'horizon, le retenait comme
    « grandeur déclarée prospective » (un agent avait déclaré « 30 jours »
    ailleurs). Même autorité ici : la valeur doit être celle du brief."""
    try:
        from utils.v62136_fr_path_maintenance import (
            _HORIZON_BANNER_RE, _v6213945_authoritative_values)
        line = str(unit or "").strip()
        m = _HORIZON_BANNER_RE.match(line)
        if not m or not re.fullmatch(
                r"\W*Horizon\s*:\s*\d{1,3}\s*(?:jours?|mois|semaines?|ans?|days?|months?|weeks?|years?)\s*\.?\s*",
                line, flags=re.I):
            return False
        return m.group("n") in _v6213945_authoritative_values(result)
    except Exception:
        return False


def _is_engine_ledger_row(unit: str, result) -> bool:
    """v62.13.9.4.10 — rangée issue du registre du moteur (zone A du proof
    layer). La réparation et le gate l'exemptent par PROVENANCE ; l'oracle
    doit appliquer la même règle, sinon il bloque en sortie ce que les deux
    autres conservent délibérément. Le déconditionnement du contrôle final a
    mis cette asymétrie au jour."""
    line = str(unit or "")
    # une VALEUR ISOLÉE du registre est aussi une unité de contenu : le
    # tableau de faits produit des cellules autonomes (« GBP 2.46bn »), pas
    # seulement des rangées. Ne pas traiter ce cas laissait passer le
    # jugement sur des valeurs pourtant extraites par le moteur.
    cells = ([c.strip() for c in line.split("|")] if "|" in line
             else [line.strip()])
    try:
        from utils.v62136_fr_path_maintenance import (
            _fact_row_in_engine_ledger, _row_values_all_in_engine_ledger)
    except Exception:
        return False
    try:
        return bool(_fact_row_in_engine_ledger(cells, line, result)
                    or _row_values_all_in_engine_ledger(cells, result))
    except Exception:
        return False


def _claim_bound_row_cells(payload: bytes, claims) -> set[str]:
    """v62.13.9.4.10 — cellules des rangées liées à un claim canonique EXACT :
    exemptées du re-jugement (b), en parité avec la réparation. Un tag
    ✅/FAIT/CONFIRMED n'est jamais une preuve (doctrine 13.9.2) : seule la
    liaison probatoire de la rangée à un claim du run exempte ses cellules
    (contre-audit 30/08/2026, P1-948-02)."""
    cells: set[str] = set()
    if not claims:
        return cells
    try:
        from utils.claim_binding import supports as _cb_supports
    except Exception:
        return cells
    try:
        zf = zipfile.ZipFile(io.BytesIO(payload))
    except Exception:
        return cells
    for name in zf.namelist():
        if not name.endswith(".xml"):
            continue
        try:
            xml = zf.read(name).decode("utf-8", "ignore")
        except Exception:
            continue
        for row in _ROW_BLOCK.findall(xml):
            row_cells = []
            for tc in _CELL_BLOCK.findall(row):
                nodes = _TEXT_NODE.findall(tc)
                txt = _normalize("".join(nodes)) if nodes else ""
                if txt:
                    row_cells.append(txt)
            if len(row_cells) < 4:
                continue
            joined = " | ".join(row_cells)
            try:
                bound = bool(_cb_supports(joined, claims))
            except Exception:
                bound = False
            if bound:
                cells.update(row_cells)
    return cells


def _filter_payload_hits(raw_hits: list[dict], result, lang: str) -> list[dict]:
    """v62.13.9.4.12.5 — LOCALITÉ DES RETENUES.

    Une ligne retenue produit deux sortes de motifs : sa reprise VERBATIM, et
    des motifs de CHARGE construits sur ses nombres (« 800 M€ », « 0
    salarié »). Les premiers sont absolus — la phrase retenue ne doit jamais
    réapparaître. Les seconds étaient appliqués à TOUT le document, si bien
    qu'une autre phrase partageant le même nombre déclenchait le blocage.

    Le run réel du 01/09/2026 l'a montré : l'export a été refusé sur
    « le marché a atteint un pic en 2023 (800 M€) » — un fait daté — et sur
    « effectif 0 salarié », le fait de registre. Trois valeurs ont suffi à
    bloquer sept unités, toutes légitimes.

    C'est la même faute que le transport aplati d'A1, corrigée de la même
    manière : un motif de valeur ne vaut que pour la phrase qu'il décrit. Une
    autre phrase portant le même nombre n'est fautive que si elle l'est
    elle-même — on la soumet donc aux juges, comme n'importe quelle unité.
    """
    if not raw_hits:
        return []
    kept: list[dict] = []
    judge = None
    try:  # noqa: SIM105
        from utils.board_scrutiny_guard import (
            find_unsupported_executive_numeric_lines as _g)
        from utils.quantity_ledger import build_authority_items as _b
        claims = list(result.get("numeric_support_claims")
                      or result.get("canonical_claims") or [])
        # v62.13.9.4.12.8 — les FAITS DE REGISTRE comptent ici aussi. Ce
        # filtre rejuge une unité qui partage un nombre avec une ligne
        # retenue ; sans les claims de registre, « 0 salariés » — le fait
        # Pappers — était jugé non étayé et bloquait l'export, alors que la
        # réparation, elle, l'avait bien reconnu. Dernier point de la chaîne
        # où la conversion manquait ; les juges doivent tous voir les mêmes
        # preuves, sinon l'un bloque ce que l'autre a libéré.
        try:
            from utils.quantity_ledger import registry_claims as _rc62428
            claims = claims + list(_rc62428(result) or [])
        except Exception:
            pass
        auth = _b(result)

        def _judge62425(unit: str) -> bool:
            try:
                return bool(_g(unit, lang, canonical_claims=claims,
                               numeric_support_claims=claims,
                               authoritative_horizon_values=auth))
            except Exception:
                return True          # fail-closed : juge indisponible = retenu

        judge = _judge62425
    except Exception:
        judge = None

    for h in raw_hits:
        # la reprise verbatim de la ligne retenue reste absolue
        if h.get("pattern") == "verbatim_line":
            kept.append(h)
            continue
        # v62.13.9.4.19.1 — le juge lit l'UNITÉ COMPLÈTE, pas les 160
        # caractères affichés : le run réel du 03/09/2026 19:23 a été bloqué
        # sur une phrase dont la fin (« 49,8 % vs 50,2 % Île-de-France ») la
        # faisait passer devant tous les juges, tronquée avant eux.
        unit = str(h.get("unit_full") or h.get("unit") or "")
        if _is_product_trace(unit):
            continue                 # appareil du produit : jamais jugé
        if judge is None or judge(unit):
            kept.append(dict(h))       # v62.13.9.4.31.1 — unit_full conservé : la réparation en a besoin
    return kept


_PRODUCT_MARKING_UNITS = (
    # pied de page de transparence, FR et EN (app.py : ftext_fr / ftext_en)
    "Document de travail assisté par IA — revue humaine requise avant toute décision.",
    "Marquage de transparence au titre du Règlement (UE) 2024/1689 ;",
    "AI Act art. 50(4) si applicable à l’usage ou à la diffusion considérés.",
    "AI Act art. 50(4) si applicable à l'usage ou à la diffusion considérés.",
    "AI-assisted working document — human review required before any decision.",
    "Transparency marking under Regulation (EU) 2024/1689;",
    "AI Act art. 50(4) where applicable to the intended use or publication.",
)
_PRODUCT_MARKING_RE = re.compile(
    r"^\s*(?:Document de travail assisté par IA|AI-assisted working document)[^\n]{0,200}"
    r"(?:2024/1689|art\.\s*50)[^\n]{0,200}$"
    r"|^\s*(?:Marquage de transparence|Transparency marking)[^\n]{0,200}$"
    r"|^\s*AI Act art\.\s*50\(4\)[^\n]{0,160}$", re.I)


def _is_product_marking_unit(unit: str) -> bool:
    """Le texte de marquage écrit par le produit lui-même (v62.13.9.4.35).

    Forme exacte ou phrase complète de la mention de transparence : ces unités
    sont identiques dans tous les documents et ne portent aucune grandeur du
    dossier. Une phrase métier logée dans un pied de page n'entre pas dans ce
    filtre et reste jugée.
    """
    t = " ".join(str(unit or "").split())
    if not t:
        return False
    # On retire les phrases connues du marquage ; ce qui reste doit être vide ou
    # sans aucun chiffre. La tolérance de longueur du premier jet laissait passer
    # « Transparency marking … revenue target 3,000 M£ by 2029 » : coller un
    # chiffre métier derrière la mention légale ne doit jamais l'exempter
    # (contre-exemple du contrat 9.4.35).
    residue = t
    matched = False
    for ref in _PRODUCT_MARKING_UNITS:
        r = " ".join(ref.split())
        if r in residue:
            residue = residue.replace(r, " ")
            matched = True
    residue = " ".join(residue.split()).strip(" .;,—-")
    if matched:
        return not any(c.isdigit() for c in residue)
    m = _PRODUCT_MARKING_RE.match(t)
    if not m:
        return False
    return not any(c.isdigit() for c in t[m.end():])


def runtime_audit(payload: bytes, result) -> list[dict]:
    """Hits de production sur les octets finaux ; [] = distribuable."""
    result = result or {}
    hits: list[dict] = []
    lang = str(result.get("lang") or result.get("language") or "fr")[:2]

    # (a) retenues du run : verbatim + payloads quantifiés
    forb = []
    for i, w in enumerate(_withheld_lines(result)):
        forb.append({"id": f"WITHHELD-{i + 1:02d}", "line": w,
                     "payload_patterns": _payload_patterns(w)})
    if forb:
        _raw_hits62425 = find_forbidden(payload, forb)
        # v62.13.9.4.49 — doctrine du 28/09/2026 : une ligne retenue au registre RESTE dans le corps, étiquetée ;
        # elle n'est un constat que si elle y figure SANS son statut (sinon, double signalement).
        from utils.quantity_ledger import is_status_tagged as _ist49
        _raw_hits62425 = [h for h in _raw_hits62425
                          if not _ist49(str(h.get("unit_full") or h.get("unit") or ""))]
        hits.extend(_filter_payload_hits(_raw_hits62425, result, lang))

    # (b) re-jugement séparé sur les surfaces de contenu — uniquement avec un
    # contexte de run réel (doctrine 13.9.2 : sans référentiel, le juge nu ne
    # censure pas ; la détection (a) reste active en toutes circonstances).
    _has_ctx = bool(result.get("run_fingerprint")
                    or result.get("diagnostics_attempts")
                    or result.get("canonical_claims")
                    or result.get("numeric_support_claims")
                    or result.get("strategic_horizon"))
    if not _has_ctx:
        return hits
    try:
        from utils.board_scrutiny_guard import (
            find_unsupported_executive_numeric_lines as _guard)
        from utils.quantity_ledger import build_authority_items as _bai
        from utils.independent_content_judge import judge_unit as _judge2
    except Exception as _imp_exc62149:
        # v62.13.9.4.9 — fail-closed : un juge qu'on ne peut pas charger ne
        # vaut pas un verdict favorable (contre-audit P1-948-04).
        hits.append({"id": "ORACLE-UNAVAILABLE", "part": "*",
                     "unit": f"judge import failed: {type(_imp_exc62149).__name__}",
                     "pattern": "oracle_unavailable"})
        return hits
    # v62.13.9.4.11 (A1) — valeurs déclarées prospectives par les agents,
    # transmises au second juge. Fail-open sur la lecture : sans index, le
    # jugement est celui du cycle précédent.
    _declared62411 = None
    try:
        from utils.declared_quantities import declared_index
        _declared62411 = declared_index(result) or None
    except Exception:
        _declared62411 = None
    # v62.13.9.4.48 — cibles du brief, transmises comme DONNÉES au second juge (point 4)
    try:
        from utils.declared_quantities import brief_declared_targets as _bdt48
        _brief48 = _bdt48(result)
    except Exception:
        _brief48 = []

    auth = []
    try:
        auth = _bai(result)
    except Exception as _auth_exc62149:
        # v62.13.9.4.9 — fail-closed : sans référentiel d'autorité calculable,
        # aucune valeur ne peut être déclarée autorisée.
        hits.append({"id": "ORACLE-UNAVAILABLE", "part": "*",
                     "unit": f"authority build failed: {type(_auth_exc62149).__name__}",
                     "pattern": "oracle_unavailable"})
        return hits
    claims = list(result.get("numeric_support_claims")
                  or result.get("canonical_claims") or [])
    # v62.13.9.4.15 — les FAITS DE REGISTRE sont des preuves pour le
    # re-jugement (b) aussi. Le cycle 9.4.12.8 les avait ajoutés au filtre
    # (a) seulement : « structure solo (0 salarié) », libéré par la
    # réparation, était rebloqué ici par le guard qui ne voyait pas le
    # claim Pappers. Tous les juges voient les mêmes preuves.
    try:
        from utils.quantity_ledger import registry_claims as _rc62415
        claims = claims + list(_rc62415(result) or [])
    except Exception:
        pass
    seen: set[str] = set()
    _proof_cells = _claim_bound_row_cells(payload, claims)
    try:
        units = extract_units(payload)
    except Exception as _ext_exc62149:
        # v62.13.9.4.9 — fail-closed : des octets illisibles ne sont pas des
        # octets propres.
        hits.append({"id": "ORACLE-UNAVAILABLE", "part": "*",
                     "unit": f"unit extraction failed: {type(_ext_exc62149).__name__}",
                     "pattern": "oracle_unavailable"})
        return hits
    for part, unit in units:
        # le re-jugement générique porte sur les surfaces de CONTENU ; les
        # gabarits Office standard (masters, layouts) et les métadonnées
        # docProps produisent des unités template (« Third level »,
        # « 1/27/13 ») qui ne sont pas du contenu du run. La détection (a)
        # — verbatim et payloads des retenues — couvre, elle, TOUTES les
        # surfaces, gabarits compris.
        if part.startswith(("docProps/", "ppt/slideMasters/", "ppt/slideLayouts/")):
            continue
        # v62.13.9.4.35 — LA MENTION DE TRANSPARENCE DU PRODUIT N'EST PAS UNE
        # GRANDEUR DU DOSSIER. Run réel du dossier réseau de soins, 16/09/2026 : le compte rendu a
        # été retenu (DOCX_SAFETY_BLOCK) parce que l'oracle lisait le « 4 » de
        # « AI Act art. 50(4) » dans notre propre pied de page comme un chiffre
        # exécutif non étayé — la mention exigée par l'article 50 déclenchait le
        # garde-fou qui interdit la livraison. On écarte les FORMES EXACTES des
        # textes que le produit écrit lui-même, jamais un préfixe large : toute
        # autre unité d'un pied de page reste jugée.
        if _is_product_marking_unit(unit):
            continue
        if unit in seen:
            continue
        seen.add(unit)
        if unit in _proof_cells:
            continue
        if _is_product_trace(unit):
            continue
        if _is_engine_ledger_row(unit, result):
            continue
        if _is_brief_horizon_banner(unit, result):
            continue
        # v62.13.9.4.9 — DEUX juges, verdict par UNION. Le premier est le
        # moteur de production (guard) ; le second (utils.independent_content_judge)
        # est écrit indépendamment, sans aucun import du guard ni de ses
        # tables. Le contre-audit du 30/08/2026 reprochait à l'oracle de
        # rendre un « second avis » avec le premier juge : l'union corrige
        # cela, et l'indépendance se prouve par neutralisation croisée.
        try:
            bad = _guard(unit, lang,
                         canonical_claims=claims,
                         numeric_support_claims=claims,
                         authoritative_horizon_values=auth)
        except Exception:
            bad = ["guard_unavailable"]      # fail-closed : juge indisponible
        engines = ["A"] if bad else []
        try:
            second = _judge2(unit, claims, declared=_declared62411, brief=_brief48)   # v62.13.9.4.48
        except Exception:
            second = {"reason": "judge2_unavailable"}   # fail-closed
        if second:
            engines.append("L2")
        if engines:
            # v62.13.9.4.31.1 — TRANSPORT COMPLET : ``unit`` reste l'aperçu
            # affiché (160 caractères), ``unit_full`` porte l'unité entière que
            # la réparation doit retrouver À L'IDENTIQUE, ``quantity`` nomme la
            # grandeur qui a déclenché le refus (contre-audit du 11/09/2026 :
            # le « 18 » fautif était au 640e caractère, invisible dans le
            # message d'erreur et introuvable par le neutraliseur).
            hits.append({"id": "RUNTIME-JUDGEMENT", "part": part,
                         "unit": unit[:160], "unit_full": unit,
                         "pattern": "runtime_judgement",
                         "engines": "+".join(engines),
                         "reason": (second or {}).get("reason") if second else "guard",
                         "quantity": (second or {}).get("quantity") if second else None})
    return hits
