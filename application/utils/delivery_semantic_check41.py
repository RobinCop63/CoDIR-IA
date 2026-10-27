"""v62.13.9.4.41 — CONTRÔLE SÉMANTIQUE APRÈS SÉRIALISATION.

Les contrôles de livraison regardaient les objets d'analyse avant export. Le 23/09/2026,
en mesurant un dossier réel, je me suis trompé en faisant la même chose : j'ai lu les
objets, conclu que les porteurs étaient présents, alors que sept d'entre eux étaient la
chaîne « Owner to assign » et que les deux porteurs réels n'arrivaient pas dans le
compte rendu. La leçon vaut règle : **le livrable, c'est le fichier écrit**. Ce module
rouvre les DOCX et PPTX produits et compare, objet par objet, ce que le fichier porte à
ce que l'objet portait.

Il ne réécrit rien. Il produit un constat : action absente, porteur perdu, échéance
perdue, carte de rôle vide. C'est ce constat qui doit alimenter la qualification du run —
une action amputée n'est pas un détail de mise en page, c'est un engagement qui disparaît.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence

__all__ = ["document_fragments", "check_delivered_objects", "empty_role_cards", "split_delivery_report48"]

_WS = re.compile(r"[\s\u00a0\u202f]+")


# v62.13.9.4.41 — Les marqueurs de tête (« À SOUMETTRE AU DG — », « RECOMMANDÉ : »…) sont
# retirés par la mise en forme exécutive. Les comparer d'un côté et pas de l'autre ferait
# déclarer manquant un engagement bel et bien écrit : le contrôle normalise les DEUX côtés.
_MARKER_HEAD41 = re.compile(
    r"^\s*(?:\[\d+\]\s*)?(?:[àa]\s+soumettre(?:\s+au\s+dg)?|bloquante?|blocking|"
    r"recommand[ée]e?|recommended|priorit[ée]\s*\d*|[àa]\s+(?:investiguer|arbitrer|"
    r"d[ée]cider|valider|confirmer|trancher)|"
    # v62.13.9.4.41b — mêmes marqueurs en anglais, y compris à la forme passive et au
    # tiret long : « TO BE ARBITRATED — … » n'était pas reconnu et faisait déclarer
    # altéré un texte identique au mot près.
    r"to\s+be\s+(?:submitted|arbitrated|investigated|decided|validated|confirmed|reviewed)|"
    r"to\s+(?:submit|arbitrate|investigate|decide|validate|confirm|review))"
    r"\s*[–—\-:]+\s*", re.IGNORECASE)


def _norm(text: Any) -> str:
    t = _WS.sub(" ", str(text or "")).strip()
    t = _MARKER_HEAD41.sub("", t)
    return t.strip().lower()


def _docx_fragments(path: str) -> List[tuple]:
    """Fragments (texte, contenant). v62.13.9.4.41b — une CELLULE est un fragment ; sa
    LIGNE est son contenant. Concaténer la ligne faisait entrer le texte des colonnes
    voisines dans l'objet comparé et fabriquait des mots étrangers : sept fausses
    altérations sur huit, mesurées le 24/09/2026, venaient de là."""
    from docx import Document
    doc = Document(path)
    out = [(p.text, p.text) for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            joined = " | ".join(c.text for c in row.cells)
            out.extend((c.text, joined) for c in row.cells)
            out.append((joined, joined))
    return out


def _pptx_fragments(path: str) -> List[tuple]:
    from pptx import Presentation
    out: List[tuple] = []
    for slide in Presentation(path).slides:
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                txt = shape.text_frame.text
                out.append((txt, txt))
                for para in txt.split("\n"):
                    if para.strip():
                        out.append((para, txt))
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    joined = " | ".join(c.text for c in row.cells)
                    out.extend((c.text, joined) for c in row.cells)
                    out.append((joined, joined))
    return out


def document_fragments(sources) -> Dict[str, List[str]]:
    """Fragments de texte réellement écrits dans chaque fichier livré.

    ``sources`` accepte des chemins ou, en production, le paquet tel qu'il part chez
    l'utilisateur : un dictionnaire ``nom de fichier -> octets``. On lit ce qui est
    livré, pas ce qui a servi à le fabriquer.
    """
    import io
    items = (sources.items() if isinstance(sources, dict)
             else ((str(x), None) for x in (sources or [])))
    frags: Dict[str, List[str]] = {}
    # v62.13.9.4.41b — un fichier qu'on n'a pas su ouvrir n'est pas un fichier sans
    # défaut : le contre-audit du 24/09 montrait un contrôle « propre » sur un document
    # illisible. L'échec de lecture est retourné, jamais avalé.
    errors: Dict[str, str] = {}
    for name, blob in items:
        low = str(name).lower()
        if not low.endswith((".docx", ".pptx")):
            continue
        try:
            src = io.BytesIO(blob) if isinstance(blob, (bytes, bytearray)) else name
            frags[str(name)] = _docx_fragments(src) if low.endswith(".docx") else _pptx_fragments(src)
        except Exception as exc:
            errors[str(name)] = f"{type(exc).__name__}: {str(exc)[:120]}"
    if errors:
        frags["__errors__"] = [f"{k} — {v}" for k, v in errors.items()]
    return frags


_MONTHS41 = {m: i + 1 for i, names in enumerate([
    ("january", "janvier", "jan"), ("february", "février", "fevrier", "feb", "fév", "fev"),
    ("march", "mars", "mar"), ("april", "avril", "apr", "avr"), ("may", "mai"),
    ("june", "juin", "jun"), ("july", "juillet", "jul", "juil"),
    ("august", "août", "aout", "aug"), ("september", "septembre", "sep", "sept"),
    ("october", "octobre", "oct"), ("november", "novembre", "nov"),
    ("december", "décembre", "decembre", "dec", "déc")]) for m in names}


def _day_keys41(text: str) -> set:
    """Dates complètes d'un texte : (année, mois, jour). Le jour n'est pas négociable —
    « 15 décembre 2026 » ne devient pas « 31 décembre 2026 » au nom d'une normalisation."""
    t = _norm(text)
    keys = set()
    for m in re.finditer(r"(\d{4})-(\d{1,2})-(\d{1,2})", t):
        keys.add((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in re.finditer(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", t):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # v62.13.9.4.43 — « 15/12/2026 » est français, « 12/15/2026 » est américain :
        # on retient chaque lecture valide (mois ≤ 12), et la comparaison exige que le
        # JOUR de la lecture retenue soit celui de l'échéance.
        if 1 <= b <= 12:
            keys.add((y, b, a))
        if 1 <= a <= 12 and a != b:
            keys.add((y, a, b))
    for name, num in _MONTHS41.items():
        for m in re.finditer(r"\b(\d{1,2})\s+" + re.escape(name) + r"\.?\s+(\d{4})\b", t):
            keys.add((int(m.group(2)), num, int(m.group(1))))
        for m in re.finditer(r"\b" + re.escape(name) + r"\.?\s+(\d{1,2}),?\s+(\d{4})\b", t):
            keys.add((int(m.group(2)), num, int(m.group(1))))
    return keys


def _date_key41(text: str) -> set:
    """Repères de date d'un texte : (année, mois) et dates ISO, quelle que soit l'écriture.

    « December 2027 », « Dec 2027 » et « 31 December 2027 » désignent la même échéance :
    comparer les chaînes ferait croire à une perte là où il n'y en a pas.
    """
    t = _norm(text)
    keys = set()
    for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", t):
        keys.add((int(m.group(1)), int(m.group(2))))
    for m in re.finditer(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", t):
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= b <= 12:
            keys.add((y, b))
        if 1 <= a <= 12:
            keys.add((y, a))
    for name, num in _MONTHS41.items():
        for m in re.finditer(r"\b" + re.escape(name) + r"\.?\s+(?:\d{1,2},?\s+)?(\d{4})\b", t):
            keys.add((int(m.group(1)), num))
    if not keys:
        for m in re.finditer(r"\b(?:19|20)\d{2}\b", t):
            keys.add((int(m.group(0)), 0))
    return keys


_STOP41 = {"les", "des", "dans", "pour", "avec", "sans", "leur", "cette", "cet", "aux",
           "the", "and", "for", "with", "from", "that", "this", "their", "into", "of"}


def _content_words41(text: str) -> set:
    return {w for w in re.split(r"[^\w’'-]+", _norm(text)) if len(w) >= 4 and w not in _STOP41}


def _verb_stem41(text: str) -> str:
    """Radical du verbe d'action ouvrant l'objet, s'il est reconnu."""
    try:
        from patches.agenda_register import _ACTION_VERB_ANY41 as _AV
        m = _AV.search(_norm(text))
        return m.group(0).strip().lower() if m else ""
    except Exception:
        return ""


_NEG41 = re.compile(r"\b(?:ne|n['’]|pas|sans|aucun\w*|jamais|not|no|never|without)\b", re.IGNORECASE)
# v62.13.9.4.41b — « — report » / « — CR » est la MARQUE DE COUPE du produit : elle dit au
# lecteur que la suite est dans le compte rendu. C'est une omission déclarée avec sa
# destination, pas un mot étranger. Le contrôle la reconnaît au lieu de crier à
# l'altération — et la compte comme troncature déclarée.
_CUT_MARK41 = re.compile(r"\s*[—–-]\s*(?:report|CR)\b", re.IGNORECASE)
_ATTR_NOISE41 = re.compile(
    r"[✓✔●•▪◦‣·»«]|(?<![\w])\d{1,2}[.)](?=\s)|"     # puces, coches et numéros de liste
    r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4}|\b(?:19|20)\d{2}\b|"
    r"porteur\s+[àa]\s+d[ée]signer|owner\s+to\s+be\s+designated|to\s+start|à\s+lancer|"
    r"propos[ée]e?|proposed|approuv[ée]e?|approved|recommand[ée]e?|recommended|en\s+cours|ongoing",
    re.IGNORECASE)


def _compare_object41(obj_text: str, line: str, extras: Sequence[str] = ()) -> str:
    """v62.13.9.4.41b — « exact », « tronqué » ou « altéré », curseur arrêté avec Robin :
    STRICT sur le verbe et l'objet de l'action, SOUPLE sur le reste.

    Un rendu abrège — le deck compacte à douze mots, la synthèse raccourcit — et c'est
    légitime. Ce qui ne l'est pas, c'est qu'un engagement change de sens : « résilier les
    contrats déficitaires » écrit « renouveler les contrats déficitaires » passait,
    parce que le début commun suffisait (contre-audit du 24/09/2026). Un objet reste
    lui-même quand son verbe, ses mots porteurs de tête et ses négations sont conservés ;
    il est tronqué quand la fin manque sans que rien d'étranger n'apparaisse ; il est
    altéré dès qu'un mot porteur est remplacé.
    """
    # v62.13.9.4.41b — LES DEUX CÔTÉS SE NORMALISENT PAREIL. Mesuré le 24/09/2026 : un
    # texte identique au mot près — « Implement new pricing architecture by 28 February
    # 2027 » — était déclaré altéré, parce que je retirais l'échéance de la LIGNE sans la
    # retirer de l'OBJET. Un comparateur qui traite ses deux entrées différemment mesure
    # sa propre asymétrie, pas l'écart entre les textes.
    def _strip41(txt: str) -> str:
        z = _norm(txt)
        for extra in extras:
            e = _norm(extra)
            if e:
                z = z.replace(e, " ")
        return _ATTR_NOISE41.sub(" ", _CUT_MARK41.sub("", z))

    o = _strip41(obj_text)
    if not o:
        return "altered"
    l = _strip41(line)
    # v62.13.9.4.44 — L'ORDRE DES TESTS. 1) Une ligne qui est un DÉBUT exact de l'objet est
    # une troncature, avant tout autre jugement — sinon une coupe tombée avant la négation
    # ou avant un chiffre passerait pour une inversion de sens. 2) La négation se juge
    # avant la contenance : « Ne pas résilier… » contient « résilier… » et passerait pour
    # exact. 3) La contenance, ensuite seulement.
    _l_core = l.rstrip(" .…-–—|").rstrip()
    _o_core = o.rstrip(" .…-–—|").rstrip()
    if _l_core == _o_core:
        return "exact"
    if len(_l_core) >= 24 and _o_core.startswith(_l_core) and len(_l_core) < len(_o_core):
        return "truncated"
    if bool(_NEG41.search(o)) != bool(_NEG41.search(l)):
        return "altered"
    if o in l:
        return "exact"
    # un paramètre chiffré est un mot porteur : « réduire le budget de 10 % » n'est pas
    # « … de 15 % », même si le filtre de mots ignore les petits nombres.
    _nums_o = re.findall(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?\s*%?", o)
    _nums_l = re.findall(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?\s*%?", l)
    if _nums_o and _nums_l and any(n.replace(" ", "") not in [m.replace(" ", "") for m in _nums_l] for n in _nums_o):
        return "altered"
    ow = [w for w in re.split(r"[^\w’'-]+", o) if len(w) >= 4 and w not in _STOP41]
    lw = {w for w in re.split(r"[^\w’'-]+", l) if len(w) >= 4 and w not in _STOP41}
    if not ow:
        return "exact" if o[:20] in l else "altered"
    verb = _verb_stem41(obj_text)
    if verb and verb[:6] not in l:
        return "altered"                      # le verbe de l'engagement a disparu
    if bool(_NEG41.search(o)) != bool(_NEG41.search(l)):
        return "altered"                      # une négation inversée change tout
    extra_words = [w for w in lw if w not in ow and not any(w[:6] == x[:6] for x in ow)]
    if extra_words:
        return "altered"                      # un mot porteur étranger : ce n'est plus l'objet
    head = ow[:6]
    missing_head = [w for w in head if w not in lw and not any(w[:6] == x[:6] for x in lw)]
    if len(missing_head) > max(1, int(0.3 * len(head))):
        return "altered"
    # v62.13.9.4.44 (M3-01, M3-02) — les RELATIONS se conservent, pas seulement les mots :
    # chaque nombre reste attaché au même mot porteur qui le précède (« Lyon 60 % / Nantes
    # 40 % » inversé est une altération), une négation reste devant le même verbe, et une
    # conjonction ne change pas (« ou » → « et » change l'engagement).
    def _pairs(txt):
        out = []
        for m in re.finditer(r"([\w’'-]{4,})\s*[:\-–—]?\s*([-+]?\d+(?:[.,]\d+)?\s*%?)", txt):
            if m.group(1) not in _STOP41:
                out.append((m.group(1), m.group(2).replace(" ", "")))
        return out
    if _pairs(o) and set(_pairs(o)) != set(_pairs(l)) and len(_pairs(l)) >= len(_pairs(o)):
        return "altered"
    _conj = lambda txt: [c.lower() for c in re.findall(r"\b(et|ou|and|or|mais|but|sauf|except)\b", txt)]
    if _conj(o) and _conj(l) and _conj(o) != _conj(l)[:len(_conj(o))] and o[:24] in l:
        return "altered"
    _negpos = lambda txt: [m.end() for m in _NEG41.finditer(txt)]
    if _negpos(o) and _negpos(l):
        _after = lambda txt, pos: re.split(r"\W+", txt[pos:].strip())[0] if txt[pos:].strip() else ""
        if {_after(o, p) for p in _negpos(o)} != {_after(l, p) for p in _negpos(l)}:
            return "altered"
    # une inversion de sens à vocabulaire identique — « de A vers B » / « de B vers A »
    # — ne se voit qu'à l'ORDRE des mots porteurs : ils doivent apparaître dans le même
    # ordre, comme une sous-suite.
    _lw_seq = [w for w in re.split(r"[^\w’'-]+", l) if len(w) >= 4 and w not in _STOP41]
    _it = iter(_lw_seq)
    _present = [w for w in ow if w in lw]
    if _present and not all(any(w == x for x in _it) for w in _present):
        return "altered"
    tail_missing = [w for w in ow[len(head):] if w not in lw]
    return "truncated" if (tail_missing or missing_head) else "exact"


# v62.13.9.4.43 — « non approuvé », « not approved », « unapproved » ne sont pas des
# approbations : le motif exigeait « approuv » sans regarder le mot qui précède.
_APPROVED41 = re.compile(
    r"(?<!non )(?<!not )(?<!pas )(?<!un)(?<!non-)(?<!not-)\b(?:approuv|valid[ée]|approved|ratifi)",
    re.IGNORECASE)
_NOT_APPROVED41 = re.compile(r"\b(?:non|not|pas)[\s-]+(?:approuv|valid[ée]|approved)|\bunapproved\b", re.IGNORECASE)
_PROPOSED41 = re.compile(r"\bpropos|\brecommand|\bproposed|\bsuggest|\bà\s+valider|\bto\s+be\s+validated",
                         re.IGNORECASE)


def _find_fragment(frags: Sequence[str], needle: str, min_len: int = 40) -> str:
    """Le paragraphe du fichier qui porte ce texte d'objet, s'il y est.

    On retient la MEILLEURE correspondance, pas la première : deux actions voisines
    peuvent commencer par les mêmes mots, et comparer les attributs de l'une à la ligne
    de l'autre fabriquerait une perte imaginaire.
    """
    n = _norm(needle)
    if len(n) < 12:
        return ""
    best, best_len = ("", ""), 0
    for item in frags:
        frag, holder = item if isinstance(item, tuple) else (item, item)
        f = _norm(frag)
        common = 0
        for a, b in zip(n, f[f.find(n[:12]):] if n[:12] in f else ""):
            if a != b:
                break
            common += 1
        if common > best_len:
            best, best_len = (frag, holder), common
    if best_len >= min(min_len, len(n)):
        return best
    # v62.13.9.4.43 — une altération TÔT dans la phrase (« de 10 % » → « de 15 % ») casse
    # le préfixe commun et faisait passer l'objet pour absent. À défaut de préfixe, on
    # retient la ligne qui partage le plus de mots porteurs, si elle en partage assez :
    # le comparateur dira ensuite si elle est exacte, tronquée ou altérée.
    ow = _content_words41(needle)
    if len(ow) >= 3:
        best2, score2 = ("", ""), 0.0
        for item in frags:
            frag, holder = item if isinstance(item, tuple) else (item, item)
            lw = _content_words41(frag)
            if not lw:
                continue
            j = len(ow & lw) / len(ow | lw)
            if j > score2:
                best2, score2 = (frag, holder), j
        if score2 >= 0.6:
            return best2
    return ("", "")


# v62.13.9.4.41 — LES TROIS LIVRABLES N'ONT PAS LE MÊME CONTRAT.
# Le compte rendu est la PROSE des agents : les objets structurés en sont extraits, ils
# n'y sont pas réinjectés. Y exiger le porteur reviendrait à reprocher à un texte de ne
# pas être un tableau. La synthèse et le deck, eux, RENDENT les objets : c'est là que le
# porteur, l'échéance et le statut doivent figurer, ou que l'absence doit s'écrire.
_PROSE_FILE41 = re.compile(r"(?i)_cr_|compte[\s_-]?rendu|minutes|_report_")


def _is_prose41(name: str) -> bool:
    return bool(_PROSE_FILE41.search(str(name or "")))


def check_delivered_objects(
    objects_by_kind: Mapping[str, Sequence[Mapping[str, Any]]],
    paths,
    kinds: Sequence[str] = ("action", "decision", "question"),
    traced: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    """Compare, dans les fichiers écrits, ce que chaque objet devait y porter.

    Trois écarts sont distingués, parce qu'ils n'ont pas la même gravité :
    ``missing`` l'objet n'apparaît nulle part ; ``owner_lost`` et ``deadline_lost``
    l'objet est là, amputé d'un attribut qu'il portait.
    """
    frags = document_fragments(paths)
    # v62.13.9.4.41b — l'échec de lecture remonte comme un ÉTAT DE CONTRÔLE.
    read_errors = frags.pop("__errors__", [])
    # v62.13.9.4.41 — COMPTE COMPLET. Un objet doit être soit ÉCRIT dans un rendu, soit
    # INSCRIT dans la trace avec son motif. Celui qui n'est ni l'un ni l'autre est un
    # engagement qui s'est évaporé : c'est ce compte-là, et non le nombre brut d'objets
    # écrits, qui dit si le deck est honnête. Un deck de direction n'affichera jamais
    # cinquante lignes ; il doit pouvoir dire où sont passées celles qu'il n'affiche pas.
    _traced41 = {_norm(t.get("text"))[:40] for t in (traced or []) if _norm(t.get("text"))}
    # v62.13.9.4.41b — Une ligne peut légitimement servir deux fois : un même engagement
    # figure à la planche exécutive, à la feuille de route et à l'annexe. On ne réserve
    # donc PAS les lignes. En revanche, quand la meilleure ligne d'un objet colle
    # STRICTEMENT MIEUX à un autre objet — deux actions qui commencent pareil — elle
    # appartient à l'autre : cet objet-ci est ABSENT, pas altéré.
    _objs41 = [o for k in kinds for o in (objects_by_kind.get(k) or [])
               if len(_norm(o.get("text"))) >= 12]

    def _belongs_to_other41(piece: str, obj) -> bool:
        me = _norm(obj.get("text"))
        mine = len(os.path.commonprefix([me, _norm(piece)]))
        for other in _objs41:
            if other is obj:
                continue
            if len(os.path.commonprefix([_norm(other.get("text")), _norm(piece)])) > mine:
                return True
        return False

    findings: List[Dict[str, Any]] = []
    n_checked = 0
    n_written = 0
    n_traced = 0
    for kind in kinds:
        for obj in (objects_by_kind.get(kind) or []):
            text = str(obj.get("text") or "").strip()
            if len(_norm(text)) < 12:
                continue
            n_checked += 1
            owner = str(obj.get("owner") or "").strip()
            deadline = str(obj.get("deadline") or "").strip()
            seen_anywhere = False
            for path, lines in frags.items():
                line, holder = _find_fragment(lines, text)
                if line and _belongs_to_other41(line, obj):
                    line, holder = "", ""      # cette ligne est celle d'un autre objet
                if not line:
                    if not _is_prose41(path):
                        findings.append({"kind": kind, "issue": "missing_in_rendered",
                                         "file": path, "text": text[:90], "expected": ""})
                    continue
                seen_anywhere = True
                if _is_prose41(path):
                    continue        # prose : on y vérifie la présence, pas les attributs
                # v62.13.9.4.41b — identité opérationnelle de l'objet, pas ressemblance
                # de début de phrase : une action inversée n'est pas l'action.
                _cmp41 = _compare_object41(text, line, extras=(owner, deadline,
                                                                  str(obj.get("status") or "")))
                if _cmp41 == "altered":
                    findings.append({"kind": kind, "issue": "altered", "file": path,
                                     "text": text[:90], "expected": line.strip()[:90]})
                elif _cmp41 == "truncated":
                    # v62.13.9.4.43 — une troncature admise porte un renvoi vers l'objet
                    # complet (« — report », « — CR », « … ») ; sans renvoi, c'est une
                    # phrase coupée que le lecteur prend pour entière.
                    # v62.13.9.4.44 (M3-03) — une ellipse « … » n'est pas une destination
                    # vérifiable : seul un renvoi explicite vers l'objet complet compte.
                    _has_ptr = bool(_CUT_MARK41.search(line) or re.search(r"voir\s+(?:le\s+)?(?:compte\s+rendu|CR)\b|see\s+(?:the\s+)?(?:full\s+)?report\b|cf\.?\s+(?:CR|compte\s+rendu)", line, re.I))
                    findings.append({"kind": kind, "issue": "truncated" if _has_ptr else "truncated_without_pointer",
                                     "file": path, "text": text[:90], "expected": line.strip()[:90]})
                # statut d'approbation : une proposition ne devient pas une décision
                _st41 = str(obj.get("status") or "").strip().lower()
                _h41 = _norm(holder)
                if _st41.startswith(("propos", "recommand", "suggest")) and _APPROVED41.search(_h41):
                    findings.append({"kind": kind, "issue": "status_changed", "file": path,
                                     "text": text[:90], "expected": _st41})
                elif _st41.startswith(("approuv", "approved", "valid")) and (
                        _PROPOSED41.search(_h41) or _NOT_APPROVED41.search(_h41)):
                    findings.append({"kind": kind, "issue": "status_changed", "file": path,
                                     "text": text[:90], "expected": _st41})
                elif _st41 and not (_APPROVED41.search(_h41) or _PROPOSED41.search(_h41)
                                    or _NOT_APPROVED41.search(_h41) or _st41[:6] in _h41):
                    # v62.13.9.4.43 — un statut que l'objet porte et que le rendu tait est
                    # un attribut perdu, au même titre qu'un porteur ou une échéance.
                    findings.append({"kind": kind, "issue": "status_lost", "file": path,
                                     "text": text[:90], "expected": _st41})
                if owner and _norm(owner) not in _norm(holder):
                    findings.append({"kind": kind, "issue": "owner_lost", "file": path,
                                     "text": text[:90], "expected": owner})
                # le jour exact prime : si l'échéance porte un jour, il doit être écrit.
                _dd41 = _day_keys41(deadline)
                _day_mismatch41 = bool(_dd41) and not (_dd41 & _day_keys41(holder))
                if deadline and (_day_mismatch41 or (
                        _norm(deadline) not in _norm(holder)
                        and not (_date_key41(deadline) & _date_key41(holder)))):
                    findings.append({"kind": kind, "issue": "deadline_lost", "file": path,
                                     "text": text[:90], "expected": deadline})
            _rendered41 = False
            for path, lines in frags.items():
                if _is_prose41(path):
                    continue
                _piece41 = _find_fragment(lines, text)[0]
                if not _piece41 or _belongs_to_other41(_piece41, obj):
                    continue
                _c = _compare_object41(text, _piece41, extras=(owner, deadline, str(obj.get("status") or "")))
                if _c == "exact" or (_c == "truncated" and (_CUT_MARK41.search(_piece41) or re.search(r"voir\s+(?:le\s+)?(?:compte\s+rendu|CR)\b|see\s+(?:the\s+)?(?:full\s+)?report\b", _piece41, re.I))):
                    _rendered41 = True
                    break
            if _rendered41:
                n_written += 1
            elif _norm(text)[:40] in _traced41:
                n_traced += 1
            elif frags:
                findings.append({"kind": kind, "issue": "unaccounted", "file": "",
                                 "text": text[:90], "expected": ""})
            if not seen_anywhere and frags:
                findings.append({"kind": kind, "issue": "missing", "file": "",
                                 "text": text[:90], "expected": ""})
    return {
        "checked": n_checked,
        "files": sorted(frags),
        "findings": findings,
        "read_errors": read_errors,
        "control_failed": bool(read_errors),
        "errors": read_errors,
        "n_altered": sum(1 for f in findings if f["issue"] == "altered"),
        "n_status_lost": sum(1 for f in findings if f["issue"] == "status_lost"),
        "n_truncated_without_pointer": sum(1 for f in findings if f["issue"] == "truncated_without_pointer"),
        "n_truncated": sum(1 for f in findings if f["issue"] == "truncated"),
        "n_status_changed": sum(1 for f in findings if f["issue"] == "status_changed"),
        "written": n_written,
        "traced": n_traced,
        "n_unaccounted": sum(1 for f in findings if f["issue"] == "unaccounted"),
        "n_missing": sum(1 for f in findings if f["issue"] == "missing"),
        "n_missing_in_rendered": sum(1 for f in findings if f["issue"] == "missing_in_rendered"),
        "n_owner_lost": sum(1 for f in findings if f["issue"] == "owner_lost"),
        "n_deadline_lost": sum(1 for f in findings if f["issue"] == "deadline_lost"),
    }


def empty_role_cards(path: str, min_chars: int = 25) -> List[str]:
    """Titres de planches dont le corps écrit est vide ou réduit à son intitulé.

    Une planche de rôle sans contenu n'est pas une mise en page perfectible : c'est un
    rôle qui n'a rien dit, et le fichier ne le dit pas au lecteur.
    """
    from pptx import Presentation
    # v62.13.9.4.43 — un pied de page, un bandeau de version, un numéro de page, une
    # mention de source ou un avertissement ne sont pas du contenu métier : une carte
    # qui n'a que cela est vide, quoi qu'en dise le compte de caractères.
    # Une ligne n'est un pied de page que si elle N'EST QUE cela : « page 49 » cité dans
    # une phrase de fond n'est pas un pied de page.
    _footer = re.compile(
        r"(?i)^\s*(?:page\s*\d+|\d{1,3}|version\b.*|build\b.*|codir[\s-]*ia\b.*|"
        r"g[ée]n[ée]r[ée]\s+(?:par|le)\b.*|generated\s+(?:by|on)\b.*|source\s*:.*|©.*|"
        r"confidenti.*|\d{1,2}/\d{1,2}/\d{2,4}.*|avertissement\b.*|disclaimer\b.*|"
        r"usage\s+interne.*|internal\s+use.*|non[\s-]board[\s-]safe.*)\s*$")
    empties: List[str] = []
    for slide in Presentation(path).slides:
        title, body, cards = "", [], []
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            txt = shape.text_frame.text.strip()
            if not title and txt and len(txt) <= 90 and "\n" not in txt:
                title = txt
                continue
            if not txt:
                continue
            content = "\n".join(l for l in txt.split("\n") if l.strip() and not _footer.search(l))
            # v62.13.9.4.44 (M3-04) — CHAQUE CARTE est contrôlée : un cadre dont la première
            # ligne est un intitulé de rôle et dont le corps est vide est une sous-carte vide,
            # même si le reste de la planche est rempli.
            lines = [l for l in txt.split("\n") if l.strip()]
            # v62.13.9.4.47 — un cadre d'UNE ligne, bas (moins de 0,7 pouce), est un intitulé
            # de section dont le corps vit dans le cadre voisin : ce n'est pas une carte vide.
            # Troisième run réel de référence : dix intitulés (« RISK #1 », « MAJOR RISKS ») signalés
            # à tort. Une carte vide est un cadre assez haut pour porter un corps et qui n'en a pas.
            _h = int(getattr(shape, "height", 0) or 0)
            _is_label = len(lines) == 1 and 0 < _h < 640080
            if not _is_label and len(lines) >= 1 and len(lines[0]) <= 60 and len(_norm("\n".join(lines[1:]))) < min_chars \
                    and re.match(r"(?i)^(?:finance|commercial|strat[ée]gie|strategy|rh|hr|ops|op[ée]rations|"
                                 r"supply|juridique|legal|ceo|dg|direction|synth[èe]se|risques?|risks?|marketing|it|dsi)\b", lines[0]):
                cards.append(lines[0])
            if content:
                body.append(content)
        if title and len(_norm(" ".join(body))) < min_chars:
            empties.append(title)
        for c in cards:
            empties.append(f"{title} › {c}" if title else c)
    return empties


# ── v62.13.9.4.48 — point 5 : le contrôle du DECK devient une INFORMATION ─────────────────────────
# Décision du 26/09/2026 : les Word sont le livrable ; le PPTX est une ébauche à reprendre après
# lecture des Word. CONTROLE_LIVRAISON.json garde tout ce que le contrôle a vu, deck compris, mais
# les ALERTES ne portent plus que sur les Word : un objet absent de tous les documents, ou altéré,
# coupé sans renvoi, amputé de son porteur, de son échéance ou de son statut dans un Word. Le compte
# des objets « non rendus » (qui mesurait l'honnêteté du deck) et les planches vides passent en
# information.
_WORD_ISSUES48 = {"altered", "truncated_without_pointer", "owner_lost", "deadline_lost",
                  "status_lost", "status_changed"}


def split_delivery_report48(rep: Mapping[str, Any], empty_cards: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    out = dict(rep or {})
    findings = list(out.get("findings") or [])

    def _is_word(f) -> bool:
        return str(f.get("file") or "").lower().endswith(".docx")

    def _is_deck(f) -> bool:
        return str(f.get("file") or "").lower().endswith(".pptx")

    word = [f for f in findings if f.get("issue") == "missing" or (_is_word(f) and f.get("issue") in _WORD_ISSUES48)]
    deck = [f for f in findings if _is_deck(f) or f.get("issue") == "unaccounted"]
    out["policy"] = "WORD_ALERTS_DECK_INFORMATION"
    out["word_alerts"] = {
        "findings": word,
        "n_missing": sum(1 for f in word if f["issue"] == "missing"),
        "n_lost": sum(1 for f in word if f["issue"] in ("owner_lost", "deadline_lost", "status_lost", "status_changed")),
        "n_altered_or_cut": sum(1 for f in word if f["issue"] in ("altered", "truncated_without_pointer")),
    }
    out["deck_information"] = {
        "findings": deck,
        "n_findings": len(deck),
        "n_unaccounted": sum(1 for f in deck if f.get("issue") == "unaccounted"),
        "empty_role_cards": dict(empty_cards or out.get("empty_role_cards") or {}),
    }
    return out
