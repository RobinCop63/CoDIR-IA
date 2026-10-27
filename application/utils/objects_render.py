"""v62.13.9.4.23 — PROJECTIONS DES OBJETS D'ANALYSE (contrat du 06/09/2026).

- ``synthesis_sections(objects, result, lang)`` : la synthèse — ce qu'il faut
  comprendre, les options, les décisions avec porteur et date, les risques,
  les arbitrages, les hypothèses à discuter, les prochaines actions. Rien
  d'inventé : chaque ligne vient d'un objet, avec sa référence.
- ``deck_plan(objects, result, lang)`` : la trame PPTX — 10 à 15 slides selon
  les sujets réellement traités, 1 à 5 points par slide, chaque point rattaché
  à un objet. Aucune slide pour un sujet absent ; aucun emplacement rempli par
  défaut ; aucun appel modèle nécessaire.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

_NUM = re.compile(r"\d")


_CUT_MARK45 = {"fr": " — CR", "en": " — report"}
_LANG45 = {"lang": "fr"}


def set_render_lang45(lang: str) -> None:
    _LANG45["lang"] = "en" if str(lang or "").lower().startswith("en") else "fr"


def _short(text: str, max_words: int = 32) -> str:
    # v62.13.9.4.37 — ASSOUPLISSEMENT DE MISE EN PAGE (décision de Robin, 18/09/2026) :
    # 30–35 mots sur les cartes de contenu, deux lignes quand il le faut ; les
    # troncatures à 12–18 mots coupaient des décisions réelles au milieu
    # (« Arbitrer entre Option 1 (spécialisation niches), Option 2 (partenariat OEM)
    # ou Option 3… » fait 18 mots). La mise en page n'est pas la doctrine : les
    # chiffres non étayés et les attributions restent protégés en amont.
    """Un point de trame : phrase entière, coupée à une frontière de mot ou de
    ponctuation, jamais au milieu d'un nombre ; les chiffres non étayés ont déjà
    été traités par la maintenance en amont (la trame lit le texte maintenu)."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    t = re.sub(r"\s*\[(?:ESTIM-HYPOTHÈSE|NON SOURCÉ|REF_SECT|SOURCÉ|À DÉFINIR)\]", "", t).strip()
    words = t.split()
    if len(words) <= max_words:
        return t.rstrip(" ,;:")
    cut = " ".join(words[:max_words])
    m = re.search(r"^(.*[.;:,—–)])\s[^.;:,—–)]*$", cut)
    # v62.13.9.4.45 — UNE COUPE PORTE SON RENVOI. Run réel du 26/09/2026 : onze lignes de
    # trame coupées sans « — report » ; le lecteur les prenait pour entières. Le renvoi
    # dit où se trouve l'objet complet, et le contrôle de livraison le reconnaît.
    return (m.group(1) if m and len(m.group(1)) > 30 else cut).rstrip(" ,;:—–-") + _CUT_MARK45[_LANG45["lang"]]


# v62.13.9.4.41 — TRACE DE SÉLECTION. Mesure du 23/09/2026 sur trois dossiers livrés :
# trente-huit objets sur cinquante-quatre manquaient dans au moins un rendu. Une synthèse
# choisit et un deck tient en quinze planches — c'est légitime — mais rien ne distinguait
# une sélection assumée d'une perte silencieuse. Le rendu inscrit désormais ce qu'il
# écarte et pourquoi ; le contrôle de livraison ne compte comme défaut que ce qui
# disparaît sans motif.
_SELECTION_TRACE41: list[dict] = []
_TRACE_RUN41: dict = {"token": ""}


def reset_selection_trace41(run_token: str = "") -> str:
    """v62.13.9.4.43 — la trace est LOCALE AU RUN : chaque remise à zéro ouvre un jeton,
    chaque entrée le porte, et la lecture ne rend que les entrées du jeton courant. Deux
    runs successifs dans la même session ne se prêtent plus leurs motifs."""
    import uuid as _uuid
    _TRACE_RUN41["token"] = str(run_token or _uuid.uuid4().hex[:12])
    _SELECTION_TRACE41[:] = [e for e in _SELECTION_TRACE41 if e.get("run") == _TRACE_RUN41["token"]]
    return _TRACE_RUN41["token"]


def selection_trace41(run_token: str = "") -> list[dict]:
    """Objets écartés par le rendu, avec leur motif — pour le run courant seulement."""
    tok = str(run_token or _TRACE_RUN41["token"])
    return [dict(e) for e in _SELECTION_TRACE41 if e.get("run") == tok]


def _norm41(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def trace_template_cut41(items, reason: str) -> None:
    """v62.13.9.4.41 — coupe du gabarit : ce que les planches n'écrivent pas.
    Les capacités des planches sont légitimes — trois actions à l'écran exécutif, trois
    éléments par phase, huit lignes de table — mais aucune ne disait ce qu'elle laissait
    dehors. Le gabarit inscrit désormais ses coupes dans la même trace que la structure.
    """
    for it in items or []:
        if not isinstance(it, dict):
            continue
        _SELECTION_TRACE41.append({
            "ref": str(it.get("ref") or ""), "kind": str(it.get("kind") or "action"),
            "text": str(it.get("text") or it.get("action") or "")[:120], "reason": reason,
            "run": _TRACE_RUN41["token"]})


def _trace_drop41(objs: list[dict], kept: list[dict], reason: str) -> None:
    kept_ids = {id(o) for o in kept}
    for o in objs or []:
        if id(o) in kept_ids or not isinstance(o, dict):
            continue
        _SELECTION_TRACE41.append({
            "ref": str(o.get("ref") or ""), "kind": str(o.get("kind") or ""),
            "text": str(o.get("text") or "")[:120], "reason": reason,
            "run": _TRACE_RUN41["token"]})


def _pick(objs: list[dict], n: int, *, kinds: tuple[str, ...] = (), topics: tuple[str, ...] = (),
          certainty: tuple[str, ...] = ()) -> list[dict]:
    out = []
    eligible = []
    for o in objs:
        if kinds and o["kind"] not in kinds:
            continue
        if topics and not (set(o.get("topics") or []) & set(topics)):
            continue
        if certainty and o.get("certainty") not in certainty:
            continue
        eligible.append(o)
        if len(out) < n:
            out.append(o)
    if len(eligible) > len(out):
        _trace_drop41(eligible, out, f"place limitée ({n} retenus sur {len(eligible)} éligibles)")
    return out


def _owner_or_todo35(o, en: bool = False) -> str:
    """v62.13.9.4.35 (C3) — porteur d'une décision : celui que le texte donne, ou
    « porteur à désigner ».

    Contre-audit du run réel du 16/09/2026 : les décisions sortaient avec une
    case vide. Les phrases de décision, telles que les agents les écrivent, ne
    portent pas toujours de responsable ; le produit ne l'invente pas et ne le
    déduit pas d'une action voisine — il dit qu'il reste à désigner, ce qui est
    une consigne au lecteur, pas une donnée fabriquée.
    """
    own = str((o or {}).get("owner") or "").strip()
    # v62.13.9.4.41 — « Owner to assign », « TBD », « à désigner » ne sont pas des
    # porteurs : ce sont des absences, et elles s'affichent comme telles.
    try:
        from utils.analysis_objects import _PLACEHOLDER41 as _PH41
        if own and _PH41.match(own):
            own = ""
    except Exception:
        pass
    if own:
        return own
    return "owner to be designated" if en else "porteur à désigner"


def synthesis_sections(objects: Mapping[str, Any], result: Mapping[str, Any] | None, lang: str = "fr") -> list[dict]:
    en = str(lang or "fr").lower().startswith("en")
    set_render_lang45(lang)
    bk = objects.get("by_kind") or {}
    sections: list[dict] = []
    # v62.13.9.4.34 (lot 2) — UN MESSAGE DE CONTRÔLE N'EST PAS UNE PROPOSITION.
    # Contre-audit de publication du 14/09/2026 : « Tendance du chiffre d'affaires
    # non établie dans le ledger — rapprocher les sources » figurait trois fois
    # comme décision ou action (dossier de conseil), en tête des décisions (dossier industriel), et
    # « Unsupported quantified target (dividend) — TO ARBITRATE » comme action du
    # plan (dossier anglophone coté). Le filtre existait pour les objets ; il manquait au rendu.
    from utils.analysis_objects import (_is_product_marker as _ipm34,
                                        _is_template_instruction as _iti34,
                                        is_engine_control_line as _iecl36)

    def _keep34(o) -> bool:
        # v62.13.9.4.36 — un CONSTAT DU MOTEUR sur une grandeur qu'il n'a pas pu
        # établir n'est ni une décision, ni un arbitrage, ni une action : il a sa
        # place dans les réserves, pas dans les rubriques où le lecteur cherche ce
        # qu'il doit décider (runs réels du 17/09/2026).
        t = str((o or {}).get("text") or "")
        return bool(t.strip()) and not _ipm34(t) and not _iti34(t) and not _iecl36(t)

    def sec(title_fr, title_en, items, fmt):
        items = [o for o in (items or []) if _keep34(o)]
        if items:
            sections.append({"title": title_en if en else title_fr, "lines": [fmt(o) for o in items],
                             "refs": [o["ref"] for o in items]})

    def _line_action(o):
        # v62.13.9.4.25 — contre-audit v24 (§2, P1) : la colonne « Impact :
        # viser +1 à +2 pts… TJM 1 100–1 300 € » collée à la décision faisait
        # retirer la décision ENTIÈRE par la neutralisation (5 → 3). La synthèse
        # porte le texte utile, le porteur et la date ; un statut n'y figure
        # que court et sans chiffre (« À lancer ») ; l'impact chiffré reste dans
        # le compte rendu de travail, avec son statut.
        text = o["text"]
        sta = str(o.get("status") or "").strip()
        if _NUM.search(sta) or len(sta) > 40 or re.match(r"(?i)impact|kpi|objectif|cible", sta):
            sta = ""
        when = o.get("deadline") or ""
        if o.get("start") and o.get("start") != when:          # v62.13.9.4.27 — période début/fin conservée
            when = (f"du {o['start']} au {when}" if not en else f"from {o['start']} to {when}")
        # v62.13.9.4.41 — un porteur absent s'écrit, il ne se tait pas : le lecteur doit
        # voir qu'une action datée n'a personne, au lieu de croire que le champ n'existe pas.
        _own41 = _owner_or_todo35(o, en)
        meta = " · ".join(x for x in (_own41, when, sta) if x and x not in text)
        return text + (f" — {meta}" if meta else "")
    # v62.13.9.4.40 — SANS DÉCISION EXTRAITE, L'OPTION RECOMMANDÉE EST LA DÉCISION PROPOSÉE.
    # Dossier anglais réel du 21/09/2026 : trois options dont une marquée « RECOMMENDED »,
    # aucune décision extraite — la rubrique décisions et §8 restaient vides alors que le
    # dossier proposait bien un choix. On présente l'option recommandée comme orientation à
    # valider, jamais comme décision prise.
    _decs40 = list(bk.get("decision", []) or [])
    if not _decs40:
        _reco40 = next((o for o in (bk.get("option") or [])
                        if re.search(r"(?i)\b(?:recommend(?:ed|ation)?|recommand[ée]e?|pr[ée]conis[ée]e?|preferred)\b",
                                     str(o.get("text") or "") + " " + str(o.get("status") or ""))), None)
        if _reco40:
            _name40 = re.sub(r"\s*\((?:RECOMM\w*|recomm\w*)[^)]*\)?\s*$", "", str(_reco40.get("text") or "")).strip()
            _decs40 = [{**_reco40, "kind": "decision",
                        "text": (f"Adopt {_name40} as the strategic orientation — recommended, to be validated by the Board"
                                 if en else f"Retenir {_name40} comme orientation stratégique — recommandée, à valider par le conseil"),
                        "owner": _reco40.get("owner") or "", "deadline": _reco40.get("deadline") or ""}]
    sec("Décisions proposées", "Proposed decisions", _decs40[:8], _line_action)
    _opts, _seen_opt = [], set()
    for o in bk.get("option", []):
        _num = re.match(r"Option\s+(\w+)", o["text"])
        _key = _num.group(1) if _num else o["text"][:30]
        if _key not in _seen_opt:
            _seen_opt.add(_key); _opts.append(o)
    _trace_drop41(_opts, _opts[:5], "place limitée dans la section options")
    sec("Options examinées", "Options examined", _opts[:5], lambda o: o["text"])
    sec("Risques et points de vigilance", "Risks and watch points", bk.get("risk", [])[:8],
        lambda o: o["text"] + (f" — {o['status']}" if o.get("status") else ""))
    _trace_drop41(bk.get("arbitration", []), bk.get("arbitration", [])[:6], "place limitée dans la section arbitrages")
    sec("Arbitrages ouverts", "Open arbitrations", bk.get("arbitration", [])[:6], lambda o: o["text"])
    acts = bk.get("action", [])
    dated = [a for a in acts if a.get("deadline")]
    sec("Plan d'actions (porteur · échéance)", "Action plan (owner · deadline)", (dated or acts)[:15], _line_action)
    hyp = [h for h in bk.get("hypothesis", []) if h.get("certainty") in ("proposed", "uncertain")]
    sec("Hypothèses de travail à discuter", "Working hypotheses to discuss", hyp[:8],
        lambda o: o["text"] + (f" ⟨{o['status']}⟩" if o.get("status") and "⟨" not in o["text"] else ""))
    _trace_drop41(bk.get("question", []), bk.get("question", [])[:6], "place limitée dans la section questions")
    sec("Questions ouvertes", "Open questions", bk.get("question", [])[:6], lambda o: o["text"])
    return sections


def conclusion_lines(objects: Mapping[str, Any], lang: str = "fr") -> list[str]:
    """v62.13.9.4.25 — contre-audit v24 (§2) : la conclusion de la synthèse ne
    peut pas se réduire à une réserve générique sur la dynamique de marché.
    Elle est rendue DEPUIS LES OBJETS : l'orientation (première décision), les
    décisions à prendre avec porteur et date, le risque et l'arbitrage n°1, la
    prochaine échéance. Rien d'inventé, aucun chiffre non statué."""
    en = str(lang or "fr").lower().startswith("en")
    bk = objects.get("by_kind") or {}
    decs = bk.get("decision", []); risks = bk.get("risk", []); arbs = bk.get("arbitration", [])
    acts = sorted([a for a in bk.get("action", []) if re.search(r"20\d{2}-\d{2}", a.get("deadline") or "")],
                  key=lambda a: a["deadline"])
    out: list[str] = []
    if decs:
        out.append(("Orientation proposée : " if not en else "Proposed direction: ") + _short(decs[0]["text"], 35))
        if len(decs) > 1:
            out.append(("Décisions à prendre : " if not en else "Decisions to take: ") + " ; ".join(
                _short(d["text"], 32) + (f" ({d['owner']}, {d['deadline']})" if d.get("owner") and d.get("deadline")
                                         else f" ({d['deadline']})" if d.get("deadline") else "")
                for d in decs[1:5]))
    if risks:
        out.append(("Risque principal : " if not en else "Main risk: ") + _short(_threats_first(risks)[0]["text"], 32))
    if arbs:
        out.append(("Arbitrage principal : " if not en else "Main arbitration: ") + _short(arbs[0]["text"], 34))
    if acts:
        a = acts[0]
        out.append(("Prochaine échéance : " if not en else "Next deadline: ") + f"{a['deadline']} — " + _short(a["text"], 30)
                   + (f" ({a['owner']})" if a.get("owner") else ""))
    return out


# Rubriques d'une étude de marché : le titre porte le marché, la demande, l'offre,
# les segments, les clients, les canaux ou la concurrence.
_MARKET_HEAD = re.compile(
    r"(?im)^#{1,6}\s*(?:\d+[.)]\s*)?\**\s*[^\n]{0,60}\b(?:march[ée]s?|market|segments?|typologies?|"
    r"profils?\s+(?:des\s+)?clients?|clients?|demande|offre|acteurs?|concurrence|competitors?|"
    r"canaux|channels?|dur[ée]e\s+moyenne|tarification|tjm)\b[^\n]{0,60}\**\s*$")
_SEGMENT_HEAD = re.compile(r"(?i)segments?|typologies?|clients?|demande|profils?")


def _marche_from_outputs(result, objects, en: bool) -> dict:
    """v62.13.9.4.31 — demande de Robin (09/09), confirmée par le contre-audit v30 :
    quand le brief demande une étude de marché, le deck doit la restituer AVANT les
    préconisations. La slide marché n'était jamais construite depuis les objets (ses
    champs restaient vides, la condition d'inclusion tombait). Tout vient des sorties
    agents : segments et facteurs de marché, sans chiffre inventé — un chiffre non
    statué reste au document de travail."""
    out = {"taille": "", "croissance": "", "missions": "", "duree_moy": "", "tjm_moy": "", "tjm_detail": "",
           "drivers": [], "segments": []}
    from utils.analysis_objects import _is_product_marker as _ipm
    outputs = (result or {}).get("outputs") if isinstance(result, dict) else None
    _skip_head = re.compile(r"(?i)r[ée]conciliation|preuves?|prudence|avertissement|annexe|m[ée]thodologie")
    def _bullets(block: str) -> list:
        res = []
        for b in re.findall(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+(.+)$", block):
            b = re.sub(r"\*\*|__", "", re.sub(r"\s+", " ", b)).strip(" -*•\t|")
            if 12 <= len(b) <= 240 and "⟨" not in b and "\u2063" not in b and not _ipm(b):
                res.append(b)
        return res

    seg_b, drv_b = [], []
    for role in ("strategie", "marketing", "commercial", "direction_generale"):
        v = (outputs or {}).get(role)
        if not isinstance(v, str) or not v.strip():
            continue
        for m in _MARKET_HEAD.finditer(v):
            head = m.group(0)
            if _skip_head.search(head):
                continue
            body = v[m.end():]
            nxt = re.search(r"(?m)^#{1,6}\s", body)
            block = body[:nxt.start()] if nxt else body[:4000]
            (seg_b if _SEGMENT_HEAD.search(head) else drv_b).extend(_bullets(block))
        if seg_b or drv_b:
            break
    # contrat de la slide : drivers = [{pct, label}], segments = [{nom, pct, etoiles}].
    # Aucun pourcentage n'est inventé : il n'est repris que s'il figure dans la ligne.
    def _pct(s: str) -> str:
        m = re.search(r"(\d{1,3}(?:[.,]\d+)?\s*%)", s)
        return m.group(1).replace(" ", "") if m else ""

    def _label(s: str) -> str:
        return _short(re.sub(r"\s*\(source[^)]*\)", "", s), 12)

    out["segments"] = [{"nom": _label(b), "pct": _pct(b), "etoiles": 3}
                       for b in dict.fromkeys(seg_b)][:4]
    out["drivers"] = [{"label": _label(b), "pct": _pct(b)}
                      for b in dict.fromkeys(drv_b) if b not in seg_b][:4]
    bk = (objects or {}).get("by_kind") or {}
    if not out["drivers"]:          # à défaut de rubrique marché : la matière externe des objets
        out["drivers"] = [{"label": _short(o["text"], 24), "pct": ""} for o in (bk.get("opportunity") or [])[:3]]
    return out


def _contexte_from_objects(bk: Mapping[str, list], arbs: list, risks: list, result: Mapping[str, Any] | None) -> dict:
    """v62.13.9.4.27 — contre-audit v25 (§4, slide Situation) : zones situation et
    risques vides, effectif « Non communiqué » alors que le registre dit zéro.
    Tout vient du dossier : l'effectif du CLAIM de registre, la situation de la
    première phrase de contexte de la DG, les risques des objets risque
    (substantiels d'abord), les arbitrages des objets arbitrage. Une zone sans
    matière reste vide — jamais remplie artificiellement."""
    cc: dict = {"arbitrages": [_short(a["text"], 30) for a in arbs[:3]]}
    try:
        from utils.v62136_fr_path_maintenance import _registry_support62427 as _reg
        for c in _reg(result or {}):
            if str(c.get("metric_id") or "").upper() == "EFFECTIF" and str(c.get("display_value") or "").strip():
                cc["effectif"] = str(c.get("display_value")).strip()
                break
    except Exception:
        pass
    # v62.13.9.4.29 — audit du dossier industriel v28 : « Effectif déclaré : Entre 500 et 999
    # salariés » (K-bis) devenait « 999 » sur les cartes — la borne haute d'une
    # tranche n'est pas un dénombrement. Le fait documentaire est lu avec son
    # extrait source : une tranche reste une tranche jusqu'à la carte.
    try:
        _facts = ((result or {}).get("financial_facts_table") or {}).get("facts") or []
        for f in _facts:
            if str(f.get("metric_canonical_id") or "").upper() != "HEADCOUNT":
                continue
            src = " ".join(str(f.get(k) or "") for k in ("source_excerpt", "source_value_text", "value"))
            mb = re.search(r"(?i)(?:entre|de)\s+(\d[\d\s\u00a0]*)\s+(?:et|à)\s+(\d[\d\s\u00a0]*)\s*(?:salari|employ|personnes|collaborat)|(\d[\d\s\u00a0]*)\s*[-–]\s*(\d[\d\s\u00a0]*)\s*(?:salari|employ|personnes|collaborat)", src)
            if mb:
                lo = re.sub(r"\s", "", mb.group(1) or mb.group(3)); hi = re.sub(r"\s", "", mb.group(2) or mb.group(4))
                cc["effectif"] = f"{lo}–{hi} salariés (tranche)"
                break
            if not cc.get("effectif") and str(f.get("value") or "").strip():
                cc["effectif"] = str(f.get("value")).strip()
                break
    except Exception:
        pass
    try:
        dg = str(((result or {}).get("outputs") or {}).get("direction_generale") or "")
        m = re.search(r"(?im)^#{1,6}\s*(?:\d+[.)]\s*)?\**\s*contexte[^\n]*\n((?:(?!#)[^\n]*\n?){1,8})", dg)
        if m:
            para = re.sub(r"\s+", " ", m.group(1)).strip(" -*")
            sents = [s for s in re.split(r"(?<=[.?])\s+(?=[A-ZÀ-Ÿ«])|(?<=!)\s+(?=[A-ZÀ-Ÿ][a-zà-ÿ])", para)   # « dossier de conseil » n'est pas une fin de phrase
                     # une bannière de maintenance (« Aucun dimensionnement… voir l'annexe »)
                     # ou une ligne statuée n'est pas la situation de l'entreprise
                     if not re.search(r"(?i)annexe|dimensionnement|⟨|\u2063|non établi|à établir|reporting consolidé|avant usage|ordres? de grandeur|non disponible|à collecter avant|réserve générique|vérifier et parser|dernier dépôt|preuve financière", s)
                     and 8 <= len(s.split()) and 20 <= len(s) <= 400]      # v62.13.9.4.29 — jamais une réserve générique en « situation »
            # une phrase sans chiffre non statué d'abord : elle survit à la maintenance du deck
            sents = [s for s in sents[:6] if not _NUM.search(s)] + [s for s in sents[:6] if _NUM.search(s)]
            if sents:
                s0 = sents[0]
                # « Pour dossier de conseil, dirigée par… » : la lecture exécutive coupe
                # à « HI! » ; l'apostrophe d'entité en tête de phrase est retirée
                # (l'entité est déjà sur la couverture), le reste est capitalisé.
                s0 = re.sub(r"^(?:Pour|Chez|Concernant|Au sein d[e'’]|For|At)\s+[^,]{3,60},\s+", "", s0)
                s0 = s0[:1].upper() + s0[1:]
                cc["situation"] = _short(s0, 26)
    except Exception:
        pass
    top = _substantive_first(_threats_first(risks))[:3]
    if top:
        cc["risques_top"] = [{"label": _short(r["text"], 30),
                              "probabilite": "élevée" if re.search(r"(?i)élev|fort|critique", r.get("status") or "") else "moyenne",
                              "impact": "élevé" if re.search(r"(?i)élev|fort|critique", r.get("status") or "") else "moyen"} for r in top]
    return cc


_MITIGATION_SHAPE = re.compile(r"(?i)^(?:validation|v[ée]rification|pilotage|mise\s+en\s+place|suivi|s[ée]curisation|formalisation|structuration|"
                               r"mise\s+à\s+jour|constitution|r[ée]alisation|collecte|cartographie|lancement|r[ée]daction|d[ée]finition|"
                               r"valider|v[ée]rifier|piloter|mettre\s+en\s+place|suivre|s[ée]curiser|formaliser|structurer|constituer|collecter)\b")


def _threats_first(risks: list[dict]) -> list[dict]:
    """v62.13.9.4.28 — run 08/09 : « Validation urgente des données financières »
    est une action de maîtrise listée parmi les risques ; elle ne peut pas être le
    risque principal. Un risque formulé comme une action passe après les risques
    formulés comme des menaces ; l'ordre du Word est conservé dans chaque rang."""
    return [r for r in risks if not _MITIGATION_SHAPE.match(r.get("text") or "")] + \
           [r for r in risks if _MITIGATION_SHAPE.match(r.get("text") or "")]


_ARBITRATION_SHAPE = re.compile(r"(?i)\barbitr|\bvs\b|\bversus\b|^\s*(?:choix|dilemme|trade[- ]?off)\b|\bou\s+(?:rester|maintenir|continuer)\b")
_EXTERNAL_SHAPE = re.compile(
    r"(?i)\b(?:concurrence|concurrents?|march[ée]|clients?|prospects?|fournisseurs?|"
    r"r[ée]glementa|l[ée]gislat|norme|conjoncture|cycles?\s+[ée]conomiques?|inflation|"
    r"plateformes?\s+(?:digitales?|en\s+ligne)|pression\s+tarifaire|"
    r"competition|competitors?|market|customers?|suppliers?|regulat)")


def _swot_label(text: str) -> str:
    """v62.13.9.4.31 — une entrée SWOT tient en 3 à 5 mots : la tête de l'entrée
    (avant « : », « — » ou la première virgule) ; le développement reste dans le
    document de travail, que le renvoi de la slide permet de retrouver."""
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    head = re.split(r"\s*[:—–]\s+|,\s+", s, maxsplit=1)[0].strip(" .;")
    words = head.split()
    if len(words) > 5:
        head = " ".join(words[:5])
    return head or _short(s, 5)


def _substantive_first(items: list[dict]) -> list[dict]:
    """v62.13.9.4.25 — contre-audit v24 (§3, SWOT) : le slide n'affiche qu'une
    entrée par quadrant ; elle doit être substantielle. Une entrée sans chiffre
    non statué passe devant une entrée chiffrée (qui serait neutralisée en
    « Dynamique de marché non établie ») ; un titre en capitales n'est jamais
    une entrée. L'ordre du Word est conservé à l'intérieur de chaque rang."""
    def _rank(o):
        txt = str(o.get("text") or "")
        letters = [c for c in txt if c.isalpha()]
        if letters and sum(1 for c in letters if c.isupper()) >= 0.8 * len(letters):
            return 3
        if o.get("certainty") == "uncertain":
            return 2
        return 1 if (_NUM.search(txt) or "%" in txt) else 0
    ranked = [o for o in items if _rank(o) < 3]
    return sorted(ranked, key=_rank)


_TOPIC_TITLES = {
    "marche": ("Marché et dynamique", "Market and dynamics"),
    "positionnement": ("Positionnement et différenciation", "Positioning and differentiation"),
    "commercial": ("Développement commercial", "Business development"),
    "marketing": ("Visibilité et marketing", "Visibility and marketing"),
    "finance": ("Finance et trésorerie", "Finance and cash"),
    "rh_organisation": ("Organisation et capacité", "Organisation and capacity"),
    "supply_chain": ("Stocks et logistique", "Inventory and logistics"),
    "juridique": ("Cadre juridique et conformité", "Legal and compliance"),
    "rse": ("RSE et climat", "ESG and climate"),                    # 9.4.52
}


def deck_plan(objects: Mapping[str, Any], result: Mapping[str, Any] | None, lang: str = "fr") -> list[dict]:
    """Trame : liste de slides {title, bullets[(text, ref)], kind}. 10 à 15 slides."""
    en = str(lang or "fr").lower().startswith("en")
    bk = objects.get("by_kind") or {}
    objs = objects.get("objects") or []
    topics = objects.get("topics_present") or []
    slides: list[dict] = []

    def slide(title_fr, title_en, items, kind, fmt=lambda o: _short(o["text"])):
        bullets = [(fmt(o), o["ref"]) for o in items[:5]]
        if bullets:
            slides.append({"title": title_en if en else title_fr, "bullets": bullets, "kind": kind})

    cp = (result or {}).get("company_profile") or {}
    name = str(cp.get("name") or ((result or {}).get("inputs") or {}).get("company") or "").strip()
    slides.append({"title": (f"{name} — trame de restitution" if name else "Trame de restitution") if not en else
                   (f"{name} — presentation outline" if name else "Presentation outline"), "bullets": [], "kind": "cover"})
    # l'essentiel : décisions
    slide("Décisions proposées", "Proposed decisions", bk.get("decision", []), "decisions")
    # une slide par sujet réellement traité (points = objets du sujet, décisions et actions d'abord)
    order = ["marche", "positionnement", "commercial", "marketing", "finance", "rh_organisation", "supply_chain", "juridique"]
    for tp in order:
        if tp not in topics:
            continue
        items = (_pick(objs, 5, kinds=("decision", "action"), topics=(tp,)) +
                 _pick(objs, 5, kinds=("risk", "arbitration"), topics=(tp,)))
        # dédoublonnage par référence, 5 au plus
        seen, picked = set(), []
        for o in items:
            if o["ref"] not in seen:
                seen.add(o["ref"]); picked.append(o)
        if picked:
            fr, en_ = _TOPIC_TITLES[tp]
            slide(fr, en_, picked, f"topic:{tp}")
    slide("Options examinées", "Options examined", bk.get("option", []), "options")
    slide("Risques et points de vigilance", "Risks and watch points", bk.get("risk", []), "risks")
    slide("Arbitrages à trancher", "Arbitrations to settle", bk.get("arbitration", []), "arbitrations")
    acts = [a for a in bk.get("action", []) if a.get("deadline")] or bk.get("action", [])
    slide("Prochaines actions", "Next actions", acts,
          "actions", fmt=lambda o: _short(o["text"], 30) + (f" — {o['owner']}" if o.get("owner") else "") + (f", {o['deadline']}" if o.get("deadline") else ""))
    slide("Questions ouvertes", "Open questions", bk.get("question", []), "questions")
    hyp = [h for h in bk.get("hypothesis", []) if h.get("certainty") == "proposed"]
    slide("Hypothèses à arbitrer", "Hypotheses to arbitrate", hyp, "hypotheses")
    # bornes 10-15 : compléter avec un second lot d'actions / risques si trop court, tronquer si trop long
    if len(slides) < 10:
        more = acts[5:10]
        if more:
            slide("Prochaines actions (suite)", "Next actions (continued)", more, "actions2",
                  fmt=lambda o: _short(o["text"], 30) + (f" — {o['owner']}" if o.get("owner") else ""))
    if len(slides) < 10 and len(bk.get("risk", [])) > 5:
        slide("Points de vigilance (suite)", "Watch points (continued)", bk["risk"][5:10], "risks2")
    return slides[:15]


# ── v62.13.9.4.23 — TRAME PPTX DEPUIS LES OBJETS, dans le schéma du renderer ──
# Le renderer (pptx_from_cr) dessine un dictionnaire « data » : couverture,
# axes (priorités), SWOT, roadmap, next_steps, commercial, questions. Ce
# constructeur le remplit UNIQUEMENT depuis les objets d'analyse — aucune
# valeur par défaut inventée (« Fondations posées », « Consolider
# l'existant ») : un emplacement sans objet reste vide et le renderer l'omet
# ou l'affiche vide, ce qui est le contrat (« pas de slide pour un sujet
# absent, pas de case remplie parce que le gabarit a un emplacement »).

def _month_label(deadline: str, lang: str) -> str:
    m = re.search(r"(20\d{2})-(\d{2})", str(deadline or ""))
    if not m:
        return str(deadline or "")
    # v62.13.9.4.25 — contre-audit v24 (§3, P2) : « sept. 2026 » devenait
    # « . 2026 » — « sept » est un mot-nombre (7) pour le réécriveur. Mois en
    # toutes lettres, jamais une abréviation homographe d'un nombre.
    months_fr = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    months_en = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    i = int(m.group(2)) - 1
    return (months_en if str(lang).lower().startswith("en") else months_fr)[i % 12] + " " + m.group(1)


_RECOMMENDED_RE = re.compile(r"\b(?:recommand[ée]e?s?|pr[ée]conis[ée]e?s?|privil[ée]gi[ée]e?s?|retenue?s?|recommended|preferred)\b", re.I)


def _recommended_option(opts) -> dict | None:
    """L'option que la provenance marque recommandée (texte ou drapeau) — None sinon."""
    for o in (opts or []):
        if not isinstance(o, dict):
            continue
        if o.get("recommended") is True:
            return o
        t = str(o.get("text") or "")
        if _RECOMMENDED_RE.search(t) and not re.search(r"\b(?:non|not)\s+(?:recommand|pr[ée]conis|recommended)", t, re.I):
            return o
    return None


def _analysis_dates34(result) -> tuple[str, str]:
    try:
        ad = str((result or {}).get("analysis_date") or "").strip()[:10]
        rd = str((result or {}).get("run_date") or "").strip()[:10]
        return (ad, rd) if (ad and rd and ad != rd) else ("", "")
    except Exception:
        return ("", "")


def _retrospective_note34(result, en: bool = False) -> str:
    """v62.13.9.4.34 (lot 1) — mention d'analyse rétrospective en couverture de trame."""
    ad, _ = _analysis_dates34(result)
    if not ad:
        return ""
    return (f"Analyse rétrospective au {ad[8:10]}/{ad[5:7]}/{ad[0:4]} — faits postérieurs écartés"
            if not en else f"Retrospective analysis as of {ad} — later facts discarded")


def _analysis_date_label34(result) -> str:
    ad, _ = _analysis_dates34(result)
    return f"{ad[8:10]}/{ad[5:7]}/{ad[0:4]}" if ad else ""


def deck_data_from_objects(objects: Mapping[str, Any], result: Mapping[str, Any] | None, lang: str = "fr") -> dict:
    """Construit le « data » du renderer depuis les objets. Renvoie {} si les
    objets sont insuffisants (moins de deux décisions/actions), pour que
    l'appelant décide d'un autre chemin."""
    set_render_lang45(lang)
    en = str(lang or "fr").lower().startswith("en")
    bk = objects.get("by_kind") or {}
    decs = bk.get("decision", []); acts = bk.get("action", []); risks = bk.get("risk", [])
    arbs = bk.get("arbitration", []); opts = bk.get("option", []); qs = bk.get("question", [])
    hyps = [h for h in bk.get("hypothesis", []) if h.get("certainty") == "proposed"]
    if len(decs) + len(acts) < 2:
        return {}
    cp = (result or {}).get("company_profile") or {}
    name = str(cp.get("name") or ((result or {}).get("inputs") or {}).get("company") or "").strip()
    plan = deck_plan(objects, result, lang)
    topic_slides = [s for s in plan if s["kind"].startswith("topic:")]

    # axes = priorités : une par sujet traité (titre + 1-5 points), 4 au plus
    axes = []
    for i, s in enumerate(topic_slides[:4], 1):
        axes.append({"num": str(i), "titre": s["title"], "points": [b for b, _ in s["bullets"][:5]]})
    if not axes:                      # pas de sujet identifié : les décisions font les priorités
        for i, d in enumerate(decs[:4], 1):
            axes.append({"num": str(i), "titre": _short(d["text"], 8), "points": [_short(d["text"])]})

    # roadmap : phases par échéance (mois), depuis les actions datées ; sinon une seule phase
    dated = [a for a in acts if re.search(r"20\d{2}-\d{2}", a.get("deadline") or "")]
    phases: dict[str, list[dict]] = {}
    for a in sorted(dated, key=lambda x: x["deadline"]):
        phases.setdefault(_month_label(a["deadline"], lang), []).append(a)
    roadmap = []
    for i, (lab, items) in enumerate(list(phases.items())[:4], 1):
        roadmap.append({"phase": f"P{i}", "date": lab, "titre": (f"Échéance {lab}" if not en else f"Due {lab}"),
                        "items": [_short(a["text"], 30) for a in items[:3]], "kpi": "", "budget": "", "extra": ""})
    if not roadmap and acts:
        roadmap.append({"phase": "P1", "date": "", "titre": ("Actions" if not en else "Actions"),
                        "items": [_short(a["text"], 30) for a in acts[:3]], "kpi": "", "budget": "", "extra": ""})

    _ns_src41 = (dated or acts)
    next_steps = [{"date": a.get("deadline") or "", "action": _short(a["text"], 30), "owner": a.get("owner") or ""}
                  for a in _ns_src41[:5]]
    _trace_drop41(_ns_src41, _ns_src41[:5], "place limitée dans les prochaines étapes (5 retenues)")
    # v62.13.9.4.24 — SWOT depuis les objets SWOT du Word (forces, faiblesses,
    # opportunités, menaces) ; à défaut d'opportunités : les options ; à défaut
    # de menaces : les risques. Jamais vide quand le Word a la matière.
    # v62.13.9.4.31 — demande de Robin (09/09) et contre-audit v30 : le SWOT du deck
    # n'affichait qu'une entrée par quadrant alors que les objets en portent quatre
    # à six, et le classement mélangeait interne et externe (« concurrence accrue »
    # en faiblesse, un arbitrage en menace). Les quadrants reçoivent des libellés
    # courts (la tête de l'entrée, 3 à 5 mots), un arbitrage n'y entre jamais, et
    # ce qui relève de l'environnement bascule du côté externe.
    _swot_src = {k: list(_substantive_first(bk.get(k, []))) for k in ("strength", "weakness", "opportunity", "threat")}
    _swot_src = {k: [o for o in v if not _ARBITRATION_SHAPE.search(o["text"])] for k, v in _swot_src.items()}
    for _int, _ext in (("strength", "opportunity"), ("weakness", "threat")):
        _moved = [o for o in _swot_src[_int] if _EXTERNAL_SHAPE.search(o["text"])]
        if _moved:
            _swot_src[_int] = [o for o in _swot_src[_int] if o not in _moved]
            _swot_src[_ext] = _swot_src[_ext] + [o for o in _moved if o not in _swot_src[_ext]]
    swot = {"forces": [_swot_label(o["text"]) for o in _swot_src["strength"][:5]],
            "faiblesses": [_swot_label(o["text"]) for o in _swot_src["weakness"][:5]],
            "opportunites": ([_swot_label(o["text"]) for o in _swot_src["opportunity"][:5]]
                             or [_swot_label(o["text"]) for o in opts[:5]]),
            "risques": ([_swot_label(o["text"]) for o in _swot_src["threat"][:5]]
                        or [_swot_label(r["text"]) for r in risks[:5]])}
    commercial_objs = [o for o in objects.get("objects") or [] if "commercial" in (o.get("topics") or [])]
    # v62.13.9.4.25 — contre-audit v24 (§3, P2) : le titre-message de la slide
    # commerciale prenait la première « opportunité », qui était « Option 2 —
    # … » (titre : « Commercial : Option 2 »). Décisions et actions d'abord,
    # options ensuite sans leur numéro : une option est un message par son
    # intitulé, pas par son rang.
    # v62.13.9.4.26 — run 13:10 : le titre-message prenait une décision chiffrée
    # (« … (≈50 cibles) »), neutralisée ensuite avec sa marque ; une décision
    # sans chiffre non statué passe devant, sans sa parenthèse.
    def _msg(txt: str) -> str:
        return _short(re.sub(r"\s*\([^()]{0,80}\)", "", txt), 14)
    _comm_dec = [o for o in commercial_objs if o["kind"] == "decision"]
    _comm_dec = [o for o in _comm_dec if not _NUM.search(o["text"])] + [o for o in _comm_dec if _NUM.search(o["text"])]
    _comm_lines = ([_msg(o["text"]) for o in _comm_dec]
                   + [_msg(o["text"]) for o in commercial_objs if o["kind"] == "action"]
                   + [_msg(re.sub(r"^Option\s+\w+\s*[—–-]\s*", "", o["text"])) for o in commercial_objs if o["kind"] == "option"])
    commercial = {
        "titre": ("Développement commercial" if not en else "Business development") if commercial_objs else "",
        "opportunites": _comm_lines[:4],
        "plan_actions": [{"action": _short(o["text"], 30), "kpi": "", "delai": o.get("deadline") or ""}
                         for o in commercial_objs if o["kind"] == "action"][:4],
        "challenges_marketing": [_short(o["text"]) for o in objects.get("objects") or []
                                 if o["kind"] == "risk" and "marketing" in (o.get("topics") or [])][:3],
        "challenges_finance": [_short(o["text"]) for o in objects.get("objects") or []
                               if o["kind"] == "risk" and "finance" in (o.get("topics") or [])][:3],
    }
    questions = [_short(q["text"], 34) for q in qs[:4]] or [_short(a["text"], 34) for a in arbs[:4]]   # v62.13.9.4.29 — l'alternative d'une question survit à la coupe
    data = {
        "titre": (f"{name} — trame de restitution" if name else "Trame de restitution") if not en else
                 (f"{name} — presentation outline" if name else "Presentation outline"),
        "sous_titre": ((_recommended_option(opts) or {}).get("text", "")[:120]
                       or (decs[0]["text"][:120] if decs else (opts[0]["text"][:120] if opts else ""))),   # v62.13.9.4.32 (B) — l'option recommandée d'abord
        "entreprise": name, "date": "",
        "marche": _marche_from_outputs(result, objects, en),
        "swot": swot, "axes": axes,
        "modele_eco": {"tjm_actuel": "", "tjm_marche": "", "tjm_cible": "", "temps_partage": [], "reseau": []},
        "roadmap": roadmap, "next_steps": next_steps, "commercial": commercial,
        # v62.13.9.4.41 — le registre d'agenda du run atteint la trame : neuf actions
        # suivies, avec porteurs et échéances, n'arrivaient jamais au deck parce que
        # l'annexe qui sait les écrire ne recevait pas sa source.
        "agenda_register": list((result or {}).get("agenda_register") or []) if isinstance(result, dict) else [],
        "questions_ouvertes": questions,
        # v62.13.9.4.31 — demande de Robin (09/09) : chaque slide de contenu renvoie
        # à la rubrique de la synthèse Word (« Synthèse §3 — Décisions proposées »).
        # Le numéro vient du document réellement généré, jamais d'une estimation.
        "synthesis_index": list((result or {}).get("synthesis_section_index") or []) if isinstance(result, dict) else [],
        "report_index": list((result or {}).get("report_section_index") or []) if isinstance(result, dict) else [],   # v62.13.9.4.33
        "retrospective_note": _retrospective_note34(result, en),                                                     # v62.13.9.4.34 (lot 1)
        "analysis_date_label": _analysis_date_label34(result),
        # v62.13.9.4.24 — contrat commun aux deux extrémités : le renderer lit
        # « decisions_codir » et « conclusion » (contre-audit v23, §4).
        "decisions_codir": [_short(d["text"], 32) + f" — {_owner_or_todo35(d, en)}" + (f", {d['deadline']}" if d.get("deadline") else "")
                            for d in decs[:4]],
        "decisions": [{"text": _short(d["text"], 32), "owner": _owner_or_todo35(d, en), "date": d.get("deadline") or ""} for d in decs[:5]],
        # v62.13.9.4.32 (B) — LA RECOMMANDATION DE PROVENANCE FAIT FOI : quand une
        # option est marquée recommandée par les agents (« — RECOMMANDÉ »), c'est
        # elle qui titre la couverture, avant la première décision et avant la
        # première option de la liste (run réel ee08f0 : « Décision : Option 1 »
        # alors que la DG recommande l'option 2). Jamais « toujours l'option 2 ».
        "conclusion": {"headline": (_short(_recommended_option(opts)["text"], 8) if _recommended_option(opts)
                                    else (_short(decs[0]["text"], 8) if decs else (_short(opts[0]["text"], 8) if opts else ""))),
                       "points": [_short(d["text"], 30) for d in decs[:3]] or [_short(a["text"], 30) for a in acts[:3]],
                       "contact": ""},
        "hypotheses": [_short(h["text"]) for h in hyps[:5]],
        # v62.13.9.4.25 — contre-audit v24 (§3) : le bloc « Arbitrage n°1 » de
        # l'essentiel exécutif lit contexte_corporate.arbitrages ; trois
        # arbitrages existaient dans les objets et le bloc restait vide.
        "contexte_corporate": _contexte_from_objects(bk, arbs, risks, result),
        "_built_from": "analysis_objects", "_topics": objects.get("topics_present") or [],
        "_object_refs": {s["title"]: [r for _, r in s["bullets"]] for s in plan},
    }
    # v62.13.9.4.41 — CASE PAR DÉFAUT DU DECK. Le deck répartit les objets dans des cases
    # fixes ; celui qui n'en trouve aucune n'était écarté par personne — il n'était appelé
    # nulle part. Mesure du 23/09/2026 sur trois dossiers livrés : neuf actions et
    # décisions sur dix-sept disparaissaient ainsi entre les objets et la structure du
    # deck. Tout objet non couvert rejoint les prochaines étapes ; au-delà de la capacité,
    # il est inscrit dans la trace de sélection avec son motif, jamais perdu en silence.
    try:
        import json as _json41
        # v62.13.9.4.41 — un objet rangé dans une case que le gabarit n'écrit pas est
        # invisible pour le lecteur : la couverture se mesure sur les cases RENDUES.
        _RENDERED41 = ("axes", "roadmap", "next_steps", "decisions_codir", "decisions",
                       "conclusion", "questions_ouvertes", "commercial", "agenda_register")
        _blob41 = _norm41(_json41.dumps({k: data.get(k) for k in _RENDERED41},
                                        ensure_ascii=False, default=str))
        _unc41 = [o for o in (list(decs) + list(acts))
                  if _norm41(str(o.get("text") or ""))[:40]
                  and _norm41(str(o.get("text") or ""))[:40] not in _blob41]
        # v62.13.9.4.41 — plus de plafond ici : la structure porte tout, c'est le gabarit
        # qui arbitre ce qu'il écrit, et ce qu'il n'écrit pas passe dans la trace.
        _room41 = len(_unc41)
        for o in _unc41[:_room41]:
            data.setdefault("next_steps", []).append({
                "date": o.get("deadline") or "", "action": _short(o["text"], 30),
                "owner": _owner_or_todo35(o, en)})
        if len(_unc41) > _room41:
            _trace_drop41(_unc41, _unc41[:_room41],
                          "au-delà de la capacité du deck, non repris dans les planches")
    except Exception:
        pass
    return data
