"""
utils/pptx_from_cr.py  —  CoDIR IA v16.5.67
================================================
Génère un PowerPoint executive-grade (9 slides spécialisées)
à partir d'un compte-rendu CoDIR IA.

Version : 4.3.0 — SC isolation complète | KPI SC obligatoires | contamination inter-dossiers supprimée
"""
from __future__ import annotations
import io, json, re, textwrap, warnings, unicodedata
from pathlib import Path
from typing import Optional

# v16.5.67.2 — source unique de version pour les métadonnées generated_by
# v17.1-B2.2 — afficher le build complet (APP_VERSION — build BUILD_VERSION)
try:
    from version import APP_VERSION, product_label   # 9.4.65 — libellé produit
    _GEN_VERSION = product_label(with_build=True).replace("CoDIR IA ", "", 1)
except ImportError:
    APP_VERSION = "v16.5.76"  # fallback si version.py absent en environnement de test
    _GEN_VERSION = "v17.0"

try:
    from docx import Document
except ImportError:
    Document = None

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
except ImportError:
    raise ImportError("python-pptx manquant : pip install python-pptx")


# ───────────────────────────────────────────────────────────────────────────────
# NETTOYAGE TEXTE — filtres anti-bruit CR
# ───────────────────────────────────────────────────────────────────────────────

_NOISE_PATTERNS = [
    r"COMPTE\s+RENDU\s+CoDIR",
    r"SOURCE\s+POUR\s+SYNTH[ÈE]SE",
    # v16.5.28 — placeholders vides à filtrer partout dans les slides
    r"^non\s+sp[eé]cifi[eé]$",
    r"^non\s+pr[eé]cis[eé]$",
    r"^[àa]\s+pr[eé]ciser$",
    r"^[àa]\s+d[eé]finir$",
    r"^[àa]\s+confirmer$",
    r"^[àa]\s+renseigner$",
    r"^n/a$",
    r"^–$",
    r"^\.$",
    r"^\.\.\.$",
    r"Pièces\s+jointes\s*:",
    r"tokens_est\s*~",
    r"tronqu[eé]=",
    r"BRIEF\s+INITIAL\s*\(dirigeant\)",
    r"BRIEF\s+CODIR\s*\(redistribu[eé]\)",
    r"\{['\"]provider['\"]",
    r"'provider'\s*:",
    r"'model'\s*:",
    r"'output'\s*:",
    r"prompt_tokens",
    r"completion_tokens",
    r"fichier\(s\)\s*\|",
    r"^Version\s*:\s*v\d",
    r"^Date\s*:\s*\d",
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE)

# Marqueurs markdown à nettoyer dans les bullets
_MD_CLEAN_RE = re.compile(r"\*\*([^*]+)\*\*|\*([^*]+)\*|__([^_]+)__|`([^`]+)`")
# Headers markdown (### titre, ## titre, # titre) — Fix v16.5.28
_MD_HEADER_RE = re.compile(r"^#{1,6}\s+")

def _strip_md(t: str) -> str:
    t = _MD_HEADER_RE.sub("", t)          # supprimer "### ", "## ", "# " en début
    t = _MD_CLEAN_RE.sub(lambda m: next(g for g in m.groups() if g is not None), t)
    return re.sub(r"\s+", " ", t).strip()

def _is_noise(line: str) -> bool:
    return bool(_NOISE_RE.search(line))

def _clean_bullet(b: str, maxlen: int = 80, *, truncate: bool = True) -> str:
    """Nettoie un bullet.  H-v2 peut désactiver la troncature sur les zones critiques."""
    b = _strip_md(b.strip())
    if _is_noise(b): return ""
    # Supprimer préfixes liste (* - • ✓ ✗ [ ] 1. etc.)
    b = re.sub(r"^[\s\-–•\*✓✗\[\]]+\s*", "", b)
    # B.1.3.16 (run 8 : « 67.9% gross margin » → « 9% gross margin ») —
    # une numérotation de liste a TOUJOURS un espace après le point ;
    # « 67.9% » n'en a jamais : l'espace devient obligatoire.
    b = re.sub(r"^\d+[\.\)]\s+", "", b)
    b = b.strip()
    if len(b) < 5: return ""
    if not truncate:
        return b
    return b[:maxlen] + ("…" if len(b) > maxlen else "")

def _clean_bullet_full(b: str) -> str:
    """Nettoyage sans perte sémantique, réservé aux zones HCRIT."""
    return _clean_bullet(b, 100000, truncate=False)

def _sanitize_slide_text(text: str, maxlen: int = 80, placeholder: str = "—") -> str:
    """v16.5.28 — Nettoie un texte pour affichage slide.
    Remplace placeholders vides par placeholder, tronque proprement.
    À utiliser sur tous les champs critiques de slides.
    """
    if not text:
        return placeholder
    t = str(text).strip()
    # Placeholders vides → tiret neutre
    _EMPTY_PLACEHOLDER = re.compile(
        r"^(non\s+sp[eé]cifi[eé]|non\s+pr[eé]cis[eé]|[àa]\s+pr[eé]ciser|"
        r"[àa]\s+d[eé]finir|[àa]\s+confirmer|[àa]\s+renseigner|n/a|–|—|\.|\.\.\.)$",
        re.IGNORECASE
    )
    if _EMPTY_PLACEHOLDER.match(t):
        return placeholder
    # 9.4.61 — contre-recette du 12/10 (§14) : « Parades. » (en-tête de sous-liste) devenait un risque autonome
    if re.match(r"(?i)^(?:parades?|contre-mesures?|mitigations?|risques?|actions?|opportunit[ée]s?|points?\s+de\s+vigilance)\s*[.:]?$", t):
        return placeholder
    # Phrase déjà tronquée par IA dans le JSON (se termine par "…" ou "...")
    # → on ne rajoute pas de "…" supplémentaire, on raccourcit proprement
    if t.endswith("…") or t.endswith("..."):
        t = t.rstrip(".…").strip()
        if len(t) < 8:
            return placeholder
    if len(t) > maxlen:
        t = t[:maxlen].rstrip() + "…"
    return t


def _clean_lines(text: str, maxlen: int = 80) -> list[str]:
    """Retourne les lignes propres d'un bloc de texte."""
    out = []
    for ln in text.splitlines():
        b = _clean_bullet(ln, maxlen)
        if b and not _is_noise(b):
            out.append(b)
    return out


def _clean_lines_full(text: str) -> list[str]:
    """Lignes nettoyées sans perte sémantique pour les payloads HCRIT."""
    out = []
    for ln in str(text or "").splitlines():
        b = _clean_bullet_full(ln)
        if b and not _is_noise(b):
            out.append(b)
    return out

def _pick_bullets(lines: list[str], n: int, filler: str | None = None, lang: str = "fr") -> list[str]:
    if filler is None: filler = "To be completed" if lang == "en" else "À compléter"
    seen, out = set(), []
    for l in lines:
        key = l[:40].lower()
        if key not in seen:
            seen.add(key); out.append(l)
        if len(out) >= n: break
    while len(out) < n:
        out.append(filler)
    return out


def _line_matches_heading(raw: str, headings: list[str]) -> bool:
    line = re.sub(r"^[\s#\-–•*]+", "", raw or "").strip()
    if not line:
        return False
    norm = re.sub(r"\s+", " ", line).upper()
    is_heading_like = (line == line.upper()) or norm.startswith(tuple(h.upper() for h in headings))
    if not is_heading_like:
        return False
    return any(norm == h.upper() or norm.startswith(h.upper()) for h in headings)


def _extract_section(text: str, headings: list[str], stop_headings: list[str]) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    start_idx = None
    for i, raw in enumerate(lines):
        if _line_matches_heading(raw, headings):
            start_idx = i + 1
            break
    if start_idx is None:
        return ""
    out = []
    for raw in lines[start_idx:]:
        if _line_matches_heading(raw, stop_headings):
            break
        out.append(raw)
    return "\n".join(out).strip()


def _has_meaningful_section(text: str) -> bool:
    return any(len(x) >= 12 for x in _clean_lines(text or "", 120))


def _filter_section_labels(lines: list[str]) -> list[str]:
    # Fix v16.5.28 — matching startswith pour variantes :
    # "CHALLENGES MARKETING (2 points)", "4. CHALLENGES FINANCE", etc.
    _BANNED_PREFIXES = [
        "diagnostic commercial", "opportunités commerciales", "opportunites commerciales",
        "préconisations commerciales", "preconisations commerciales",
        "plan d'action", "plan d\u2019action",
        "challenges marketing", "challenges finance",
        "arbitrages", "go / no-go",
    ]
    out = []
    for line in lines:
        # Supprimer numéros de section et ## avant comparaison
        low = re.sub(r"^[\d\.\s#]+", "", (line or "").strip()).lower()
        if not low:
            continue
        if any(low == b or low.startswith(b) for b in _BANNED_PREFIXES):
            continue
        out.append(line)
    return out


_SOLO_TEMPLATE_TERMS = re.compile(
    r"(prescriber\s+network|r[ée]seau\s+prescripteur|part[- ]time\s+(ceo|cfo|dg|daf|offer)|"
    r"temps\s+partag[ée]|offre\s+temps\s+partag[ée]|\bTJM\b|day[- ]rate)", re.I)
# Note S.2.2.1 : « subcontracting » / « co-traitance » volontairement EXCLUS — ce sont
# des sujets opérationnels corporate légitimes (PME industrielle, BTP, logistique).
# On ne bloque que le vocabulaire SOLO non ambigu (management de transition).


def _scrub_solo_opportunities(items, lang):
    """En deck corporate : retire toute opportunité au vocabulaire SOLO (management
    de transition). Si tout est retiré, renvoie un fallback neutre honnête."""
    neutral = ("Commercial analysis not available in this run — refer to the CR section."
               if lang == "en" else
               "Analyse commerciale non disponible dans cette exécution — voir la section CR.")
    kept = [it for it in (items or []) if not _SOLO_TEMPLATE_TERMS.search(str(it))]
    return kept or [neutral]


def _scrub_solo_actions(actions, lang):
    neutral = ("Commercial analysis not available in this run — refer to the CR section."
               if lang == "en" else
               "Analyse commerciale non disponible dans cette exécution — voir la section CR.")
    kept = [a for a in (actions or [])
            if not _SOLO_TEMPLATE_TERMS.search(str(a.get("action", "") if isinstance(a, dict) else a))]
    return kept or [{"action": neutral, "kpi": "—", "delai": "—"}]


def _commercial_display_text(comm) -> str:
    """S.2.2.3 — concatène TOUTES les valeurs string du bloc commercial, quel que
    soit le champ (récursif sur listes/dicts). Ferme la CLASSE de bug : aucun champ
    affiché (kpi, délai, titre, ou futur champ) ne peut échapper au scan anti-template,
    contrairement à une énumération de champs qui doit être maintenue à la main."""
    parts: list = []

    def _walk(v):
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                _walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                _walk(x)

    _walk(comm)
    return " ".join(parts)


def _scrub_commercial_for_deck_type(data: dict, lang: str = "fr") -> None:
    """S.2.2.x — garde post-enrichissement, INDÉPENDANTE de la source. En deck
    CORPORATE, si un marqueur SOLO non ambigu (prescriber network, part-time CEO/CFO,
    temps partagé, TJM, day-rate) apparaît dans N'IMPORTE QUEL champ affiché du bloc
    commercial, le bloc est identifié comme template SOLO et neutralisé ENTIÈREMENT.
    Le corporate légitime (subcontractors, DTC, margin…) n'a aucun marqueur dur →
    jamais touché. Mutation in-place sur data['commercial']."""
    if str(data.get("deck_type", "")).strip().lower() != "corporate":
        return
    # B1.3.60-L1/S4 (premier test terrain, 11/08) : quand le DOSSIER lui-même est
    # de profil solo/services (supply chain SKIPPED amont), le vocabulaire solo
    # du bloc commercial (TJM, mono-mission…) est LÉGITIME — ce n'est pas un
    # résidu de template. La garde anti-template ne s'applique qu'aux dossiers
    # corporate pleins ; sinon elle masquait l'analyse la plus demandée du run.
    if str(data.get("supply_chain_bundle_status", "")).strip().upper().startswith("SKIP"):
        return
    comm = data.get("commercial")
    if not isinstance(comm, dict):
        return
    # Scan générique de tous les champs affichés (opportunités, actions + kpi/délai,
    # challenges mkt/finance, titre, et tout futur champ).
    if _SOLO_TEMPLATE_TERMS.search(_commercial_display_text(comm)):
        neutral = ("Commercial analysis not available in this run — refer to the CR section."
                   if lang == "en" else
                   "Analyse commerciale non disponible dans cette exécution — voir la section CR.")
        # S.2.2.4 — REMPLACEMENT INTÉGRAL du bloc (pas une mutation des seuls champs
        # connus) : la détection est générique, le nettoyage doit l'être aussi. Tout
        # champ inconnu/futur porteur d'un résidu solo disparaît avec le bloc.
        data["commercial"] = {
            "titre": comm.get("titre") if not _SOLO_TEMPLATE_TERMS.search(str(comm.get("titre", ""))) else "",
            "opportunites": [neutral],
            "plan_actions": [{"action": neutral, "kpi": "—", "delai": "—"}],
            "challenges_marketing": [],
            "challenges_finance": [],
        }


def _extract_commercial_payload(cr_text: str, extra_context: dict | None = None, lang: str = "fr", deck_type: str = "") -> dict:
    """
    Option B — v16.5.28.
    Source prioritaire : commercial_json extrait directement depuis Grok (extra_context).
    Fallback 1 : parsing heuristique de la section DIRECTION COMMERCIALE du CR.
    Fallback 2 : valeurs génériques.
    Exactement la même architecture que _extract_supply_chain_payload.
    """
    extra_context = extra_context or {}

    # ── Priorité 1 : JSON commercial direct depuis Grok ───────────────────────
    comm_json = extra_context.get("commercial_json") \
        if isinstance(extra_context.get("commercial_json"), dict) else None

    if comm_json is None:
        # Tentative de parsing depuis le CR (cas fallback ou DOCX seul)
        comm_json = _parse_json_between_tags(cr_text)
        if isinstance(comm_json, dict) and "plan_actions" not in comm_json:
            comm_json = None  # JSON du CR mais pas commercial

    if isinstance(comm_json, dict):
        # Nettoyer et valider chaque champ
        opps = [
            _clean_bullet_full(str(x))
            for x in (comm_json.get("opportunites") or [])
            if str(x).strip() and len(str(x).strip()) >= 5
        ]
        pa_raw = comm_json.get("plan_actions") or []
        plan_actions = []
        for item in pa_raw[:3]:
            if not isinstance(item, dict):
                continue
            action = _clean_bullet_full(str(item.get("action", "")))
            kpi    = _clean_bullet_full(str(item.get("kpi",    ""))) or ""
            delai  = str(item.get("delai", "")).strip()
            if not action:
                continue
            plan_actions.append({"action": action, "kpi": kpi, "delai": delai})
        # Garantir 3 items avec délais progressifs
        progressive = ["T1", "T2", "T3"]
        for i in range(len(plan_actions)):
            if not plan_actions[i]["delai"] or plan_actions[i]["delai"] in {"…", "None", "."}:
                plan_actions[i]["delai"] = progressive[i]
        # Vérifier délais tous identiques → forcer progression
        delais = [a["delai"] for a in plan_actions]
        if len(set(delais)) <= 1 and plan_actions:
            for i, a in enumerate(plan_actions):
                a["delai"] = progressive[i]

        ch_mkt = [
            _clean_bullet_full(str(x))
            for x in (comm_json.get("challenges_marketing") or [])
            if str(x).strip() and len(str(x).strip()) >= 5
        ][:2]
        ch_fin = [
            _clean_bullet_full(str(x))
            for x in (comm_json.get("challenges_finance") or [])
            if str(x).strip() and len(str(x).strip()) >= 5
        ][:2]

        if opps and plan_actions:
            return {
                "titre": ("Commercial Development" if lang=="en" else "Développement commercial"),
                "opportunites":          _pick_bullets(opps, 4, lang=lang),
                "plan_actions":          plan_actions,
                "challenges_marketing":  _pick_bullets(ch_mkt, 2, filler=("Align marketing channels with commercial priorities" if lang=="en" else "Aligner marketing sur priorités commerciales")),
                "challenges_finance":    _pick_bullets(ch_fin, 2, filler=("Secure financial assumptions of the commercial plan" if lang=="en" else "Sécuriser hypothèses financières du plan commercial")),
            }

    # ── Priorité 2 : extraction heuristique du CR ─────────────────────────────
    commercial_block = _extract_section(
        cr_text,
        ["DIRECTION COMMERCIALE", "COMMERCIAL DIRECTION", "COMMERCIAL", "VOLET COMMERCIAL", "PRÉCONISATIONS COMMERCIALES", "COMMERCIAL DIAGNOSIS"],
        ["SYNTHÈSE DES DÉCISIONS", "DECISION SYNTHESIS", "DIRECTION GÉNÉRALE", "GENERAL MANAGEMENT", "CEO", "DG / CEO"],
    )
    marketing_block = _extract_section(
        cr_text,
        ["MARKETING & COMMUNICATION", "MARKETING & COMMUNICATIONS", "MARKETING"],
        ["FINANCE", "DIRECTION COMMERCIALE", "COMMERCIAL", "SYNTHÈSE DES DÉCISIONS"],
    )
    finance_block = _extract_section(
        cr_text,
        ["FINANCE & FISCALITÉ", "FINANCE & TAX", "FINANCE"],
        ["DIRECTION COMMERCIALE", "COMMERCIAL", "SYNTHÈSE DES DÉCISIONS", "DIRECTION GÉNÉRALE"],
    )

    cleaned_commercial = _filter_section_labels(_clean_lines_full(commercial_block))

    # Détection format pipe structuré dans le CR
    pipe_actions = []
    for line in cleaned_commercial:
        if " | " in line and any(kw in line.upper() for kw in ["ACTION :", "KPI :", "DÉLAI :", "DELAI :"]):
            parts = {p.split(":", 1)[0].strip().upper(): p.split(":", 1)[1].strip()
                     for p in line.split(" | ") if ":" in p}
            action = parts.get("ACTION", "")
            kpi    = parts.get("KPI", SL("to_confirm", lang))
            delai  = parts.get("DÉLAI", parts.get("DELAI", "T1"))
            if action:
                pipe_actions.append({"action": _clean_bullet_full(action), "kpi": _clean_bullet_full(kpi), "delai": _t(delai, 8)})

    action_candidates = []
    if not pipe_actions:
        for line in cleaned_commercial:
            low = line.lower()
            if any(v in low for v in ["prioriser", "repackager", "lancer", "activer", "cibler",
                                       "mettre en place", "déployer", "developper", "développer",
                                       "renforcer", "ouvrir", "formaliser", "qualifier"]):
                action_candidates.append(line)
        if not action_candidates:
            action_candidates = cleaned_commercial[:3]

    _is_corporate = str(deck_type).strip().lower() == "corporate"
    _neutral_opp = ("Commercial analysis not available in this run — refer to the CR section."
                    if lang == "en" else
                    "Analyse commerciale non disponible dans cette exécution — voir la section CR.")
    opportunities = cleaned_commercial[:4] if cleaned_commercial else (
        # M6-S.2.2 — anti-template : en deck CORPORATE, ne JAMAIS retomber sur le
        # template SOLO (management de transition). Fallback neutre honnête.
        [_neutral_opp] if _is_corporate else [
            # Fallback SOLO — management de transition / cabinet indépendant
            ("Prospect identified sector niches" if lang=="en" else "Prospecter niches sectorielles identifiées"),
            ("Develop regional prescriber network" if lang=="en" else "Développer réseau prescripteurs régionaux"),
            ("Activate subcontracting to expand capacity" if lang=="en" else "Activer co-traitance pour élargir capacité"),
            ("Propose part-time CEO/CFO offering" if lang=="en" else "Proposer offres temps partagé DG/DAF"),
        ]
    )

    if pipe_actions:
        plan_actions = pipe_actions[:3]
    else:
        plan_actions = [
            {"action": item, "kpi": SL("to_confirm", lang), "delai": f"T{i+1}"}
            for i, item in enumerate(action_candidates[:3])
        ] or (
            [{"action": _neutral_opp, "kpi": "—", "delai": "—"}] if _is_corporate else [
                # Fallback SOLO — management de transition (jamais en deck CORPORATE)
                {"action": ("Qualify 5 priority prospects" if lang=="en" else "Qualifier 5 prospects prioritaires"), "kpi": ("1 engagement signed" if lang=="en" else "1 mission signée"), "delai": "T1"},
                {"action": ("Activate prescriber network (30 contacts)" if lang=="en" else "Activer réseau prescripteurs (30 contacts)"), "kpi": "10 meetings", "delai": "T2"},
                {"action": ("Launch part-time offering" if lang=="en" else "Mettre en place offre temps partagé"), "kpi": ("2 recurring clients" if lang=="en" else "2 clients récurrents"), "delai": "T3"},
            ]
        )

    # Détection préfixes challenges dans le bloc commercial
    ch_mkt_from_block = [
        line.split(":", 1)[1].strip() if ":" in line else line
        for line in cleaned_commercial
        if "CHALLENGE MKT" in line.upper() or "CHALLENGES MARKETING" in line.upper()
    ]
    ch_fin_from_block = [
        line.split(":", 1)[1].strip() if ":" in line else line
        for line in cleaned_commercial
        if "CHALLENGE FIN" in line.upper() or "CHALLENGES FINANCE" in line.upper()
    ]

    challenges_marketing = (ch_mkt_from_block or _filter_section_labels(_clean_lines_full(marketing_block)))[:2] or [
        ("Align marketing channels with commercial priorities" if lang=="en" else "Aligner canaux marketing sur priorités commerciales"),
        ("Strengthen social proof and case studies" if lang=="en" else "Renforcer preuve sociale et cas clients"),
    ]
    challenges_finance = (ch_fin_from_block or _filter_section_labels(_clean_lines_full(finance_block)))[:2] or [
        ("Re-verify revenue assumptions against real pipeline" if lang=="en" else "Revérifier hypothèses CA avec pipeline réel"),
        ("Secure margins and offer pricing" if lang=="en" else "Sécuriser marges et pricing des offres"),
    ]

    # M6-S.2.2 — filet anti-template : en deck CORPORATE, aucune opportunité/action
    # ne doit porter de vocabulaire SOLO (couvre aussi une génération LLM, pas que
    # le fallback). Sectoriel-agnostique, pas de mots-clés métier hardcodés.
    if _is_corporate:
        opportunities = _scrub_solo_opportunities(opportunities, lang)
        plan_actions = _scrub_solo_actions(plan_actions, lang)

    return {
        "titre": ("Commercial Development" if lang=="en" else "Développement commercial"),
        "opportunites":         _pick_bullets(opportunities, 4, lang=lang),
        "plan_actions":         plan_actions,
        "challenges_marketing": _pick_bullets(challenges_marketing, 2, filler=("Align marketing channels with commercial priorities" if lang=="en" else "Aligner marketing sur priorités commerciales"))[:2],
        "challenges_finance":   _pick_bullets(challenges_finance, 2, filler=("Secure financial assumptions of the commercial plan" if lang=="en" else "Sécuriser hypothèses financières du plan commercial"))[:2],
    }



def _parse_json_between_tags(text: str, start_tag: str = "---JSON_START---", end_tag: str = "---JSON_END---") -> dict | None:
    if not text:
        return None
    start = text.find(start_tag)
    end = text.find(end_tag)
    if start == -1 or end == -1 or end <= start:
        return None
    raw = text[start + len(start_tag):end].strip()
    try:
        return json.loads(raw)
    except Exception:
        return None


def _parse_all_json_between_tags(text: str, start_tag: str = "---JSON_START---", end_tag: str = "---JSON_END---") -> list:
    """S.2.3.1 — itère TOUS les blocs JSON balisés (le CR en contient plusieurs :
    commercial, supply chain, etc.). Permet de retenir uniquement le bloc qui est
    réellement un JSON Supply Chain, au lieu de prendre aveuglément le premier."""
    out: list = []
    if not text:
        return out
    i = 0
    while True:
        s = text.find(start_tag, i)
        if s == -1:
            break
        e = text.find(end_tag, s)
        if e == -1:
            break
        raw = text[s + len(start_tag):e].strip()
        try:
            out.append(json.loads(raw))
        except Exception:
            pass
        i = e + len(end_tag)
    return out


# M6-A2.2.2 - garde de schema Supply Chain factorisee dans utils.sc_schema (source de
# verite UNIQUE partagee avec codir_engine, pour que moteur et deck decident a l identique).
from utils.sc_schema import (
    is_supply_chain_json as _is_supply_chain_json,
)


def _norm_enum(value) -> str:
    """S.2.3.2 — normalise un libellé enum : sans accents, minuscules, espaces/tirets
    en underscores. Permet de comparer libellés FR et EN de façon identique."""
    s = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return s.strip().lower().replace(" ", "_").replace("-", "_")


_SC_STATUS_MAP = {
    "sain": "healthy", "healthy": "healthy", "ok": "healthy", "good": "healthy",
    "sous_tension": "under_pressure", "under_pressure": "under_pressure", "tendu": "under_pressure",
    "degrade": "degraded", "degraded": "degraded",
    "critique": "critical", "critical": "critical",
}


def _canon_sc_status(value) -> str:
    """S.2.3.2 — statut SC canonique. L'agent peut émettre FR (sain/sous_tension…) OU
    EN (healthy/under_pressure…) ; sans canonisation, « healthy » != « sain » faisait
    croire à un statut dégradé et activait une slide SC à tort."""
    n = _norm_enum(value)
    return _SC_STATUS_MAP.get(n, n)


_SC_PROB_MAP = {
    "elevee": "high", "high": "high", "haute": "high", "forte": "high",
    "moyenne": "medium", "medium": "medium", "moyen": "medium",
    "faible": "low", "low": "low", "basse": "low",
}


def _canon_sc_probability(value) -> str:
    """S.2.3.2 — probabilité de risque canonique (high/medium/low), FR comme EN."""
    n = _norm_enum(value)
    return _SC_PROB_MAP.get(n, n)


# M6-A2.2.4 — helpers type-safe : un champ JSON mal typé (LLM) ne doit JAMAIS crasher le
# consommateur. On normalise au point d'usage (dict attendu -> dict ; liste attendue -> liste).
# M6-A2.2.5 — helpers type-safe importés depuis utils.sc_schema (source partagée moteur+deck)
from utils.sc_schema import as_dict as _as_dict, as_list as _as_list, as_str_list as _as_str_list


def _sc_enabled_from_json(sc_json: dict | None, explicit_flag: bool | None = None) -> bool:
    if explicit_flag is not None:
        return bool(explicit_flag)
    if not isinstance(sc_json, dict):
        return False
    # S.2.3.2 — statut canonisé : seul un statut NON-healthy active la slide.
    if _canon_sc_status(sc_json.get("global_status", "healthy")) != "healthy":
        return True
    for risk in _as_list(sc_json.get("major_risks")):
        # S.2.3.2 — probabilité canonisée (high == élevée). A2.2.4 — risk forcé en dict.
        if _canon_sc_probability(_as_dict(risk).get("probability", "")) == "high":
            return True
    scores = _as_dict(sc_json.get("scores"))
    for key, threshold in (("cash_impact", 4), ("service_level", 5)):
        value = scores.get(key)
        if value is None:
            continue
        try:
            if float(value) <= threshold:
                return True
        except Exception:
            pass
    tradeoffs = [x for x in _as_str_list(sc_json.get("codir_tradeoffs")) if str(x).strip()]
    return len(tradeoffs) >= 2


def _sc_material_signal(text: str) -> bool:
    low = (text or "").lower()
    return any(k in low for k in ["supply chain", "stock", "stocks", "bfr", "disponibil", "rupture", "surstock", "logistique", "fournisseur", "pricing", "cash", "otif", "rotation", "coverage", "lead time", "wholesale", "dtc", "outlet", "sku", "allocation"])


def _estimate_sc_scores_from_text(source_text: str) -> dict:
    """Heuristique SC scores — copie locale de codir_engine._estimate_sc_scores."""
    low = (source_text or "").lower()
    service = stock = supplier = cash = 6

    if any(k in low for k in ["rupture", "penurie", "pénurie", "service", "otif", "disponibil"]):
        service -= 2
    if any(k in low for k in ["audit", "allocation", "pilotage", "sku critique", "sku priorit"]):
        service += 1
    if any(k in low for k in ["surstock", "obsol", "stock record", "rotation", "stocks eleves", "stocks élevés"]):
        stock -= 2
    if any(k in low for k in ["destockage", "déstockage", "liquidation", "reduire stocks", "réduire stocks"]):
        stock += 1
    if any(k in low for k in ["dependance", "dépendance", "asie", "chine", "fourn", "lead time", "mexique", "nearshoring", "dual sourcing"]):
        supplier -= 2
    if any(k in low for k in ["sourcing alternatif", "dual sourcing", "nearshoring", "mexique", "europe"]):
        supplier += 1
    if any(k in low for k in ["bfr", "cash", "dso", "creances", "créances", "tresorerie", "trésorerie"]):
        cash -= 2
    if any(k in low for k in ["liberer", "libérer", "cash libere", "cash libéré", "rotation stock"]):
        cash += 1

    def clamp(v):
        return max(3, min(8, int(v)))

    return {
        "service_level": clamp(service),
        "stock_management": clamp(stock),
        "supply_resilience": clamp(supplier),
        "cash_impact": clamp(cash),
        "scores_estimated": True,
    }


def _sc_synth_tile_label_b1318(sc: dict, data: dict, sc_signal: str) -> str:
    """B.1.3.18 (run 10 dossier anglophone coté) — libellé de la tuile Supply Chain de la
    slide synthèse. Si le payload est « not_covered » MAIS que le CR parle
    retail/ops (_retail_kw14, filet 3.14), la tuile dit « LIGHT (CR) » :
    le deck ne doit jamais se contredire (slide « narrative available » vs
    synthèse « NOT COVERED »). Sinon : statut localisé tronqué (18).

    B.1.3.20 (P2-H, runs dossier industriel + dossier agroalimentaire) — les enums bruts « NOT
    COVERED » / « SKIPPED » fuyaient tels quels dans les decks FR. Ils sont
    désormais localisés (la voie structurée — SOUS TENSION… — l'était déjà)."""
    if (str((sc or {}).get("global_status", "")).strip().lower() == "not_covered"
            and (data or {}).get("_retail_kw14")):
        return "LIGHT (CR)"
    _lang20 = str((data or {}).get("lang", "") or "").lower()
    _sig20 = (sc_signal or "").strip().upper().replace("_", " ")
    if _lang20.startswith("fr"):
        _fr_map20 = {"NOT COVERED": "NON COUVERTE",
                     "SKIPPED": "NON EXÉCUTÉE",
                     "LIGHT INDUSTRIAL": "LIGHT (CR)"}  # B.1.3.23 P1-G'
        if _sig20 in _fr_map20:
            return _t(_fr_map20[_sig20], 18)
    if _sig20 == "LIGHT INDUSTRIAL":
        return "LIGHT (CR)"
    return _t((sc_signal or "").upper(), 18)


def _sc_not_covered_payload(enabled: bool = False, reason: str = "") -> dict:
    """S.2.3 — payload Supply Chain « non couvert » : aucun JSON SC structuré
    exploitable. On NE reconstruit PAS d'analyse par grattage de la prose du CR.
    Le message localisé est rendu par _slide_supply_chain. enabled=False par défaut
    (slide absente, ex. deck solo) ; le gating corporate le passe à True (slide
    explicite « non couvert »)."""
    return {
        "enabled": enabled,
        "global_status": "not_covered",
        "not_covered": True,
        "reason": reason,
        "executive_summary": "",
        "findings": [], "risks": [], "tradeoffs": [], "dg_decisions": [],
        "actions": {"0_30_days": [], "1_3_months": [], "3_12_months": []},
        "scores": {},
    }


def _build_supply_chain_payload_from_context(cr_text: str, explicit_flag: bool | None = None) -> dict:
    # S.2.3 — SUPPRESSION de la recomposition heuristique. Cette fonction grattait
    # auparavant TOUT le CR avec des mots-clés finance/commercial (cash, marge,
    # service, stock, pricing, dtc, wholesale, marque) et présentait le résultat
    # comme une analyse Supply Chain. C'était la source de la slide SC « molle » /
    # incohérente quand le JSON SC manquait. On renvoie désormais « non couvert ».
    return _sc_not_covered_payload(
        enabled=bool(explicit_flag) if explicit_flag is not None else False)


_SC_LIGHT_SIGNAL_RE = None


def _extract_light_ops_findings(cr_text: str, max_items: int = 5) -> list:
    """B.1.3.56 (scope C, durci gate ChatGPT) — constats opérationnels
    DÉTERMINISTES pour le mode LIGHT : citations de lignes du CR portant un
    signal opérationnel EN CONTEXTE LOCAL (collocation forte, ou deux signaux
    faibles dans la même ligne). Jamais un simple mot-clé : « site web »,
    « stock-options », « flux de trésorerie » ou « achat de titres » ne
    déclenchent pas. Les recommandations (« devrait réduire les stocks »)
    sont exclues : un constat est une observation, pas une action proposée.
    Chaque constat retourné est un dict tracé :
    {"text", "source": "CR_NARRATIVE", "line_hash"} — citation non
    structurée, pas un fait page-confirmé. 0 constat => bandeau seul."""
    import re as _re
    import hashlib as _hl
    if not cr_text:
        return []
    strong = _re.compile(
        r"\b(?:sites?\s+(?:industriels?|de\s+production)|usines?|ateliers?|"
        r"capacit[ée]s?\s+(?:industrielles?|de\s+production)|"
        r"rotation\s+des\s+stocks|(?:sur)?stocks?\s+(?:mati[èe]res?|de\s+"
        r"mati[èe]res?|produits?|outils?)|rupture[s]?\s+de\s+stock|"
        r"doublement\s+des\s+stocks|"
        r"flux\s+(?:logistiques?|amont|aval|physiques?)|"
        r"cha[îi]ne\s+(?:logistique|d['’]approvisionnement)|"
        r"approvisionnements?|fournisseurs?|"
        r"BFR|besoin\s+en\s+fonds\s+de\s+roulement|"
        r"OTIF|taux\s+de\s+service|"
        r"industrial\s+sites?|production\s+(?:plants?|sites?|capacity)|"
        r"inventory\s+(?:turnover|levels?|days|coverage)|stock\s+coverage|stockouts?|"
        r"suppl(?:y\s+chain|iers?)|procurement|working\s+capital)\b", _re.I)
    weak = _re.compile(
        r"\b(?:stocks?|achats?|logistique|transports?|production|entrep[ôo]ts?|"
        r"inventaires?|sku|allocation|inventor(?:y|ies)|logistics|warehouse)\b",
        _re.I)
    excluded = _re.compile(
        r"stock[- ]options?|stock\s+(?:price|market|exchange|index)|"
        r"share\s+price|equity\s+market|supplier\s+sentiment|vendor\s+sentiment|"
        r"market\s+sentiment|site\s+(?:web|internet)|"
        r"flux\s+de\s+tr[ée]sorerie|flux\s+financiers?|cash[- ]?flows?|"
        r"achats?\s+(?:de\s+titres|d['’]actions)|rachats?\s+d['’]actions|"
        r"acquisitions?\s+(?:de\s+|d['’])?(?:la\s+)?"
        r"(?:cible|soci[ée]t[ée]|entreprise|titres|groupe)",
        _re.I)
    reco = _re.compile(
        r"\b(?:devr(?:ait|aient|a|ont)|doit|doivent|devra|il\s+faut|"
        r"recommand|pr[ée]conis|sugg[ée]r|should|must|recommend|"
        r"pr[ée]voi(?:t|ent)|envisag(?:e|ent)|projett(?:e|ent)|"
        r"planifi(?:e|ent)|plans?\s+to|intends?\s+to|expects?\s+to|will|"
        # B.1.3.56 gate 3 (intégration Claude) — plans CONJUGUÉS : futur
        # proche FR (« va/vont réduire ») et passé composé de planification
        # (« a prévu de », « ont décidé d'optimiser ») restent des intentions,
        # jamais des constats. EN symétrique (going to / has planned to).
        r"(?:va|vont)\s+(?:se\s+|s['’])?\w+(?:er|ir|re)\b|"
        r"(?:a|ont|avai(?:t|ent))\s+(?:pr[ée]vu|planifi[ée]|envisag[ée]|"
        r"d[ée]cid[ée]|projet[ée]|convenu)\b|"
        r"(?:is|are)\s+going\s+to|"
        r"(?:has|have|had)\s+(?:planned|decided|agreed|committed)\s+to|"
        # Gate 4 — intentions et futurs ordinaires qui ne doivent jamais être
        # promus en constats opérationnels.
        r"(?:vise|visent|cherche|cherchent|entend|entendent|souhaite|souhaitent|"
        r"compte|comptent)\s+[àa]\s+|"
        r"(?:a|ont|avait|avaient)\s+pour\s+objectif\s+d['’e]\s+|"
        r"(?:objectif|ambition|cible)\s*:?\s*(?:de\s+|d['’]\s*)?"
        r"(?:se\s+|s['’])?\w+(?:er|ir|re)\b|"
        r"(?:r[ée]duir|diminu|optimis|cartographi|rationalis|mutualis|centralis|"
        r"consolid|am[ée]lior|augment|acc[ée]l[ée]r|d[ée]ploi|s[ée]curis|"
        r"renforc|modernis|harmonis|"
        # gate 4, intégration Claude — verbes d'évolution hors liste initiale
        # (« les stocks baisseront », « les délais passeront à 60 jours »).
        r"baiss|mont|pass|chut|progress|recul|doubl|tripl|atteind|"
        r"reviendr|redescend|descend|remont|cro[îi]tr|grimp|g[ée]n[ée]r|"
        r"d[ée]gag|tomb|[ée]volu|stabilis|converg|repli|"
        r"s['’][ée]tabli|s['’][ée]l[èe]v)"
        r"(?:era|eront|ira|iront|ra|ront)\b|"
        r"(?:sera|seront)\s+(?:r[ée]duit|diminu[ée]|optimis[ée]|cartographi[ée]|"
        r"rationalis[ée]|mutualis[ée]|centralis[ée]|consolid[ée]|am[ée]lior[ée]|"
        r"augment[ée]|d[ée]ploy[ée]|s[ée]curis[ée]|renforc[ée]|modernis[ée]|"
        r"harmonis[ée])s?\b|"
        r"(?:aims?|seeks?|targets?|hopes?|wants?)\s+to|"
        r"(?:anticipe|anticipent|s['’]attend(?:ent)?\s+[àa]|table(?:nt)?\s+sur)\b|"
        r"(?:est|sont)\s+(?:attendue?s?|anticip[ée]e?s?|pr[ée]vue?s?|"
        r"projet[ée]e?s?|escompt[ée]e?s?)\b|"
        r"(?:baisse|hausse|r[ée]duction|augmentation|am[ée]lioration|d[ée]t[ée]rioration)\s+"
        r"(?:attendue|anticip[ée]e|pr[ée]vue|projet[ée]e)\b|"
        r"(?:forecasts?|anticipates?|expects?)\s+"
        r"(?:an?\s+|lower|higher|reduced|increased|improved|further|that)|"
        r"(?:management|the\s+(?:company|group|firm|board)|"
        r"la\s+direction|le\s+groupe|la\s+soci[ée]t[ée]|"
        r"le\s+management)\s+projects?\b|"
        r"(?:expected|forecast|projected|anticipated)\s+"
        r"(?:reduction|decline|increase|improvement|deterioration)\b|"
        r"(?:is|are|was|were)\s+(?:expected|forecast|forecasted|projected|anticipated|planned|intended|set|scheduled)\s+to|"
        r"the\s+plan\s+is\s+to|(?:objective|target|ambition)\s*:?\s*(?:is\s+to|to))\b", _re.I)
    # Gate 8 — une PRÉVISION n'est jamais un constat courant, quelle que soit
    # la place du sujet ou du complément (« The company expects supplier lead
    # times… », « The expected supplier lead time… »). Le nom composé
    # « forecast error » reste un constat observable et n'est pas exclu.
    forecast56 = _re.compile(
        r"\b(?:expects?|projects?|anticipates?|pr[ée]voit|pr[ée]voient|"
        r"anticipe|anticipent|s['’]attend(?:ent)?\s+[àa])\b|"
        r"\bforecasts\b|"
        r"\b(?:we|they|management|the\s+(?:company|group|firm|board)|"
        r"la\s+direction|le\s+groupe|la\s+soci[ée]t[ée])\s+forecast\b|"
        r"\b(?:expected|forecast(?:ed)?|projected|anticipated)\b"
        r"(?!\s+error\b)(?=[^\n]{0,100}\b(?:inventory|stocks?|suppliers?|"
        r"lead\s+times?|procurement|logistics|warehouse|working\s+capital|BFR)\b)",
        _re.I)
    # Gate 9 — measured forecast QUALITY is an observation, not a forecast.
    # Preserve operational facts such as "forecasts were inaccurate" or
    # "forecast accuracy is 72%", while future values ("forecast at 90 days")
    # remain excluded from the LIGHT diagnosis.
    forecast_quality_observed56 = _re.compile(
        r"\bforecast(?:s)?\s+(?:was|were|is|are|remains?|remained)\s+"
        r"(?:inaccurate|accurate|biased|wrong|revised|updated|volatile|"
        r"unstable|frequent|stable)\b|"
        r"\bforecast\s+(?:error|accuracy|bias|quality|revisions?|updates?)\b|"
        r"\bforecasts?\s+revisions?\s+(?:was|were|is|are|remain(?:ed|s)?)\b|"
        r"\b(?:forecasting|demand[- ]planning)\s+(?:error|accuracy|bias|quality)\b",
        _re.I,
    )

    # Gate 4 — second, deliberately readable intent boundary. It complements
    # the historical monolithic regex and makes the common future/goal forms
    # auditable without relying on a fragile final word-boundary.
    intent56 = _re.compile(
        r"\b(?:vise|visent|cherche|cherchent)\s+[àa]\s+|"
        r"\b(?:entend|entendent|souhaite|souhaitent|compte|comptent)\s+(?:de\s+|[àa]\s+)?|"
        r"\b(?:a|ont|avait|avaient)\s+pour\s+objectif\s+d(?:e|['’])\s+|"
        r"\b(?:objectif|ambition|cible)\s*:?\s*(?:de\s+|d['’]\s*)?"
        r"(?:se\s+|s['’])?\w+(?:er|ir|re)\b|"
        r"\b(?:r[ée]duira|r[ée]duiront|diminuera|diminueront|optimisera|optimiseront|"
        r"cartographiera|cartographieront|rationalisera|rationaliseront|"
        r"mutualisera|mutualiseront|centralisera|centraliseront|consolidera|"
        r"consolideront|am[ée]liorera|am[ée]lioreront|augmentera|augmenteront|"
        r"acc[ée]l[ée]rera|acc[ée]l[ée]reront|d[ée]ploiera|d[ée]ploieront|"
        r"s[ée]curisera|s[ée]curiseront|renforcera|renforceront|modernisera|"
        r"moderniseront|harmonisera|harmoniseront)\b|"
        r"\b(?:sera|seront)\s+(?:r[ée]duit|diminu[ée]|optimis[ée]|cartographi[ée]|"
        r"rationalis[ée]|mutualis[ée]|centralis[ée]|consolid[ée]|am[ée]lior[ée]|"
        r"augment[ée]|d[ée]ploy[ée]|s[ée]curis[ée]|renforc[ée]|modernis[ée]|"
        r"harmonis[ée])s?\b|"
        r"\b(?:aims?|seeks?|targets?|hopes?|wants?)\s+to\b|"
        r"\b(?:anticipe|anticipent|s['’]attend(?:ent)?\s+[àa]|table(?:nt)?\s+sur)\b|"
        r"\b(?:est|sont)\s+(?:attendue?s?|anticip[ée]e?s?|pr[ée]vue?s?|"
        r"projet[ée]e?s?|escompt[ée]e?s?)\b|"
        r"\b(?:baisse|hausse|r[ée]duction|augmentation|am[ée]lioration|d[ée]t[ée]rioration)\s+"
        r"(?:attendue|anticip[ée]e|pr[ée]vue|projet[ée]e)\b|"
        r"\b(?:forecasts?|anticipates?|expects?)\s+"
        r"(?:an?\s+|lower|higher|reduced|increased|improved|further|that)|"
        r"\b(?:management|the\s+(?:company|group|firm|board)|"
        r"la\s+direction|le\s+groupe|la\s+soci[ée]t[ée]|"
        r"le\s+management)\s+projects?\b|"
        r"\b(?:expected|forecast|projected|anticipated)\s+"
        r"(?:reduction|decline|increase|improvement|deterioration)\b|"
        r"\b(?:is|are|was|were)\s+(?:expected|forecast|forecasted|projected|anticipated|planned|intended|set|scheduled)\s+to\b|"
        r"\b(?:is|are|was|were)\s+(?:expected|forecast|forecasted|projected|anticipated)\s+(?:at|for)\b|"
        r"\bthe\s+plan\s+is\s+to\b|"
        r"\b(?:objective|target|ambition)\s*:?\s*(?:is\s+to|to)\b",
        _re.I,
    )
    noise = _re.compile(
        r"^\s*(?:#|\||-\s*\[|Sujet\s*\||.*\|\s*Porteur\s*\|)", _re.I)
    out, seen = [], set()
    for raw in str(cr_text).splitlines():
        line = raw.strip().strip("-*• ").strip()
        if len(line) < 40 or noise.match(raw) or raw.count("|") >= 3:
            continue
        # Un contexte explicitement exclu invalide la ligne entière. Le
        # supprimer puis rescanner pouvait laisser « fournisseurs » survivre
        # dans « site internet ... fournisseurs ... stock-options ».
        if excluded.search(line):
            continue
        probe = line
        if not (strong.search(probe) or len(set(
                m.group(0).lower() for m in weak.finditer(probe))) >= 2):
            continue
        if reco.search(line) or intent56.search(line):
            continue
        if forecast56.search(line) and not forecast_quality_observed56.search(line):
            continue
        if _re.match(r"^(?:Finaliser|Optimiser|Mettre|Lancer|Recruter|"
                     r"R[ée]aliser|Auditer|Structurer|D[ée]ployer|"
                     r"Formaliser|Corriger|Harmoniser|N[ée]gocier|"
                     r"S[ée]curiser|Renforcer|Impl[ée]menter|R[ée]duire|"
                     r"Diminuer|Cartographier|Analyser|Identifier|"
                     r"[ÉE]valuer|Planifier|Pr[ée]voir|Surveiller|Suivre|"
                     r"Am[ée]liorer|Augmenter|Acc[ée]l[ée]rer|Rationaliser|"
                     r"Mutualiser|Centraliser|Consolider|Reduce|Decrease|"
                     r"Map|Analyse|Analyze|Identify|Assess|Plan|Monitor|"
                     r"Improve|Increase|Accelerate|Rationali[sz]e|"
                     r"Consolidate)\b", line, _re.I):
            continue
        clean = _re.sub(r"\*\*", "", line)
        clean = _re.sub(r"\s+", " ", clean).strip()
        if len(clean) > 200:
            cut = max(clean.rfind(c, 0, 200) for c in (".", ";", ",", ")"))
            clean = clean[:cut + 1] if cut > 80 else clean[:197] + "…"
        key = clean[:60].lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "text": clean,
            "source": "CR_NARRATIVE",
            "line_hash": _hl.sha256(clean.encode("utf-8")).hexdigest()[:10],
        })
    # B.1.3.56 correctif P1-C56-07 — sélection PAR CATÉGORIES : sur corpus
    # réel, l'ordre de lecture donnait 3 formulations « sites » quasi
    # équivalentes et évinçait achats/flux. Chaque candidat est catégorisé
    # (first-match, mêmes familles que l'audit) ; une ligne prioritaire par
    # catégorie d'abord, puis complément round-robin. ≤2 par catégorie.
    def _cat56(t):
        s2 = t.lower()
        if _re.search(r"\b(site|usine|plant|factory|capacit)", s2):
            return "sites_capacity"
        if _re.search(r"\b(stock|inventory|bfr|obsol|coverage)", s2):
            return "inventory_bfr"
        if _re.search(r"\b(achat|procurement|supplier|fournisseur|sourcing|"
                      r"mati[èe]re)", s2):
            return "procurement_supplier"
        if _re.search(r"\b(flux|logisti|wms|erp|otif|lead.?time)", s2):
            return "flows_systems"
        if _re.search(r"\b(service|d[ée]lai|on.?time|taux\s+de\s+service)",
                      s2):
            return "service_otif"
        return "other"
    _order = ("sites_capacity", "inventory_bfr", "procurement_supplier",
              "flows_systems", "service_otif", "other")
    _bycat = {}
    for item in out:
        _bycat.setdefault(_cat56(item["text"]), []).append(item)
    _sel = []
    for _rank in (0, 1):
        for _c in _order:
            if len(_sel) >= max_items:
                break
            _lst = _bycat.get(_c) or []
            if len(_lst) > _rank:
                _sel.append(_lst[_rank])
    out = _sel
    return out


def _sc_light_industrial_payload(cr_text: str = "") -> dict:
    """B.1.3.25 P1-A — le moteur a décidé light_industrial (profil produit/
    industriel) : le deck ne dit plus « non couverte », il dit LIGHT.
    B.1.3.56 (scope C) — la slide LIGHT porte 3-5 constats opérationnels
    cités du CR quand la matière existe (sites, stocks, flux, achats, BFR)."""
    p = _sc_not_covered_payload(enabled=True, reason="industrial_profile")
    p["global_status"] = "light_industrial"
    # 9.4.61 — contre-recette du 12/10 (§14) : des phrases de SEGMENTATION COMMERCIALE (clients, canaux, distributeurs,
    # prix) étaient retenues comme signaux logistiques ; elles sont écartées quand aucun terme d'approvisionnement fort
    # (usine, fournisseur, intrants, douane, stock de matières, fret…) ne les justifie
    import re as _re61
    _com61 = _re61.compile(r"(?i)\b(?:segment(?:ation)?s?|canal|canaux|clients?|distributeurs?|grande\s+distribution|"
                        r"e-?commerce|marketing|prix\s+de\s+vente|sell-?out|part\s+de\s+march[ée]|customers?|channels?)\b")
    _sup61 = _re61.compile(r"(?i)\b(?:usines?|sites?\s+(?:industriels?|de\s+production)|fournisseurs?|suppliers?|intrants|"
                        r"mati[èe]res?\s+premi[èe]res?|douan\w*|tariffs?|fret|freight|approvisionnements?|procurement|"
                        r"sous[- ]trait\w*|contract\s+manufactur\w*|stocks?\s+(?:de\s+)?mati[èe]res?|inventory)\b")
    p["light_findings"] = [f for f in _extract_light_ops_findings(cr_text)
                           if not (_com61.search(str((f or {}).get("text") or "")) and not _sup61.search(str((f or {}).get("text") or "")))]
    p["light_note61"] = "citations du CR, sans analyse Supply Chain dédiée"
    return p


def _extract_supply_chain_payload(cr_text: str, extra_context: dict | None = None) -> dict:
    extra_context = extra_context or {}

    # v16.5.67 F3 — Si Supply Chain est explicitement SKIPPED en amont
    # (profil services / solo / activité non pertinente), on retourne un
    # payload désactivé et _slide_supply_chain ne rendra pas la slide.
    # Fix du bug "slide SC fantôme" : en v16.5.66, le pipeline déclarait
    # SKIPPED mais la slide était rendue avec du contenu inventé à partir
    # de la section Supply Chain du CR (même quand cette section avait
    # été produite par erreur).
    sc_status = (extra_context.get("supply_chain_bundle_status") or "").upper()
    if sc_status == "SKIPPED":
        return {
            "enabled":           False,
            "executive_summary": "",
            "global_status":     "skipped",
            "findings": [], "risks": [], "tradeoffs": [],
            "dg_decisions": [],
            "actions": {"0_30_days": [], "1_3_months": [], "3_12_months": []},
            "scores": {},
            "skipped_reason": extra_context.get("supply_chain_bundle_warning", ""),
        }

    section = _extract_section(
        cr_text,
        ["SUPPLY CHAIN & PERFORMANCE OPÉRATIONNELLE", "SUPPLY CHAIN & OPERATIONAL PERFORMANCE", "SUPPLY CHAIN & PERFORMANCE OPERATIONNELLE", "DIRECTION SUPPLY CHAIN", "SUPPLY CHAIN"],
        ["DIRECTION COMMERCIALE", "COMMERCIAL DIRECTION", "COMMERCIAL", "SYNTHÈSE DES DÉCISIONS", "DECISION SYNTHESIS", "DIRECTION GÉNÉRALE", "GENERAL MANAGEMENT", "CEO", "DG / CEO"],
    )
    # S.2.3.1 — n'accepter qu'un JSON RÉELLEMENT Supply Chain. Le CR contient souvent
    # un JSON commercial (et d'autres rôles) ; prendre aveuglément le premier bloc
    # JSON faisait passer un JSON commercial pour du SC → payload vide non-not_covered
    # → slide honnête « non couvert » non affichée. On scanne tous les blocs et on ne
    # retient que celui qui passe la garde de schéma.
    candidate = extra_context.get("supply_chain_json")
    sc_json = candidate if _is_supply_chain_json(candidate) else None
    if sc_json is None:
        _sec_json = _parse_json_between_tags(section)
        if _is_supply_chain_json(_sec_json):
            sc_json = _sec_json
        else:
            sc_json = next((j for j in _parse_all_json_between_tags(cr_text)
                            if _is_supply_chain_json(j)), None)
    explicit_flag = extra_context.get("supply_chain_slide_flag")

    if isinstance(sc_json, dict):
        # SC v16.5.28 — _strip_code_artifacts appliqué sur tous les champs texte
        def _sc_clean(text: str, maxlen: int) -> str:
            return _clean_bullet(_strip_code_artifacts(str(text)), maxlen)

        findings = [_sc_clean(x, 58) for x in _as_str_list(sc_json.get("key_findings"))
                    if _sc_clean(x, 58)]
        risks = []
        for risk in _as_list(sc_json.get("major_risks"))[:3]:  # A2.2.4 — _as_list -> slice sûr
            if not isinstance(risk, dict):
                continue
            title = _sc_clean(risk.get("risk", ""), 42)
            if not title.strip():
                continue
            impact = _sc_clean(risk.get("business_impact", ""), 30)
            prob = _strip_code_artifacts(str(risk.get("probability", ""))).strip()
            risks.append(f"{title} — {prob} / {impact}" if impact else f"{title} — {prob}")
        tradeoffs = [_sc_clean(x, 42) for x in _as_str_list(sc_json.get("codir_tradeoffs"))
                     if _sc_clean(x, 42)]
        recs = _as_dict(sc_json.get("recommendations"))  # A2.2.3/4 — jamais .get() sur une liste/str

        def _sc_recs(lst, maxlen):
            lst = _as_str_list(lst)  # A2.2.4 — horizon mal typé -> liste vide, pas de crash
            return [b for b in _pick_bullets(
                [_sc_clean(x, maxlen) for x in lst if _sc_clean(x, maxlen)],
                len(lst), filler=""
            ) if b.strip()]

        # v16.5.28 — dg_decisions : décisions SC-5 structurées pour slide
        raw_dg_decisions = _as_str_list(sc_json.get("dg_decisions"))
        dg_decisions = [_sc_clean(d, 90) for d in raw_dg_decisions if _sc_clean(d, 90)]

        payload = {
            "enabled": _sc_enabled_from_json(sc_json, explicit_flag=explicit_flag),
            "executive_summary": _sc_clean(sc_json.get("executive_summary", ""), 110),
            "global_status": str(sc_json.get("global_status", "sain")),
            "findings":  [b for b in _pick_bullets(findings,  3, filler="") if b.strip()],
            "risks":     [b for b in _pick_bullets(risks,     3, filler="") if b.strip()],
            "tradeoffs": [b for b in _pick_bullets(tradeoffs, 3, filler="") if b.strip()],
            "dg_decisions": dg_decisions[:3],
            "actions": {
                "0_30_days":   _sc_recs(recs.get("0_30_days"),   48)[:2],
                "1_3_months":  _sc_recs(recs.get("1_3_months"),  48)[:1],
                "3_12_months": _sc_recs(recs.get("3_12_months"), 48)[:1],
            },
            "scores": _as_dict(sc_json.get("scores")),
        }
        return payload

    lines = _clean_lines(section, 64)
    if not lines or "non disponible" in section.lower():
        if (extra_context or {}).get("sc_decision") == "light_industrial":
            return _sc_light_industrial_payload(cr_text)  # B.1.3.25 P1-A + scope C 3.56
        return _build_supply_chain_payload_from_context(cr_text, explicit_flag=explicit_flag)
    # S.2.3 — section SC présente dans le CR mais AUCUN JSON structuré exploitable :
    # on ne fabrique plus une analyse par grattage de mots-clés (rupture/cash/service…).
    # « non couvert » ; le gating corporate l'affichera explicitement.
    # M6-A2.2 — narrative SC présente mais JSON structuré invalide/absent → reason dédié.
    if (extra_context or {}).get("sc_decision") == "light_industrial":
        return _sc_light_industrial_payload(cr_text)  # B.1.3.25 P1-A + scope C 3.56
    return _sc_not_covered_payload(
        enabled=bool(explicit_flag) if explicit_flag is not None else False,
        reason="structured_invalid")


# ───────────────────────────────────────────────────────────────────────────────
# 1. EXTRACTION TEXTE DOCX
# ───────────────────────────────────────────────────────────────────────────────

def extract_text_from_docx(docx_path: str | Path) -> str:
    if Document is None:
        raise ImportError("python-docx manquant")
    doc = Document(str(docx_path))
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


# ───────────────────────────────────────────────────────────────────────────────
# 2. PROMPT IA
# ───────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = textwrap.dedent("""
Tu es un expert en communication executive et stratégie d'entreprise.
À partir d'un compte-rendu CoDIR IA, tu génères un PowerPoint de 8 à 10 slides.

RÈGLES ABSOLUES :
- Réponds UNIQUEMENT avec un objet JSON valide, sans markdown ni texte autour.
- Extrais les vraies données du CR (chiffres, KPIs, actions datées).
- Aucun bruit technique (tokens, provider, "COMPTE RENDU", "Pièces jointes").
- Aucun placeholder générique ("Point 1", "Action 1", "À définir").
- Items texte : concis, style direction générale, verbe d'action.
- Si le CR contient une section commerciale ou des recommandations commerciales, la clé "commercial" doit absolument reprendre sa substance réelle (opportunités, actions, challenges marketing/finance).
- STATUT DES INFORMATIONS (v62.13.9.4.22) : ce que le CR présente comme « à investiguer », « à confirmer », « à vérifier », « non mesuré » ou « inconnu » reste une hypothèse ou une question dans le deck — jamais un constat. Écris « visibilité digitale à évaluer », jamais « faible visibilité digitale », si le CR ne l'a pas établi. L'absence d'information n'est pas une absence de dispositif.
- ÉCHÉANCES : reprends les dates absolues du plan d'action ou du tableau de la direction générale telles qu'elles figurent dans le CR (ex. 2026-09-12), dans le même ordre ; n'invente pas de J+7 / J+30 si le CR donne des dates.

STRUCTURE JSON :
{
  "titre": "Titre court et percutant (max 45 car.)",
  "sous_titre": "Contexte en 1 ligne (max 70 car.)",
  "entreprise": "Nom exact de l'entreprise",
  "date": "Date ou année du CR",
  "deck_type": "solo si brief d'une personne/cabinet/manager de transition/indépendant — corporate si brief d'une entreprise/groupe/ETI/organisation avec CA, effectifs, plan stratégique",
  "contexte_corporate": {
    "ca": "ex: 8,2 Md€ — n'ajoute une année entre parenthèses QUE si elle figure explicitement dans le CR pour CE chiffre ; sinon, montant seul",
    "croissance": "ex: +3% organique",
    "effectif": "ex: 34 000 collaborateurs",
    "situation": "Résumé factuel de la situation en 1 phrase (max 80 car.)",
    "risques_top": [
      {"label": "Risque 1 (max 42 car.)", "probabilite": "élevée|moyenne|faible", "impact": "élevé|moyen|faible"},
      {"label": "Risque 2", "probabilite": "...", "impact": "..."},
      {"label": "Risque 3", "probabilite": "...", "impact": "..."}
    ],
    "arbitrages": [
      "Arbitrage 1 à trancher (max 55 car.)",
      "Arbitrage 2",
      "Arbitrage 3",
      "Arbitrage 4"
    ]
  },
  "marche": {
    "taille": "ex: VALEUR marché (chiffrée, sourcée dans le CR)",
    "croissance": "ex: +X% vs ANNÉE",
    "missions": "ex: ~N missions/an",
    "duree_moy": "ex: X-Y mois",
    "tjm_moy": "ex: X-Y €",
    "tjm_detail": "ex: précision selon fonction/secteur",
    "drivers": [
      {"pct": "X%", "label": "Driver 1 (issu du CR)"},
      {"pct": "X%", "label": "Driver 2"},
      {"pct": "X%", "label": "Driver 3"},
      {"pct": "X%", "label": "Driver 4"}
    ],
    "segments": [
      {"nom": "Segment 1", "pct": "X%", "etoiles": 5},
      {"nom": "Segment 2", "pct": "X%", "etoiles": 4},
      {"nom": "Segment 3", "pct": "X%", "etoiles": 3},
      {"nom": "Segment 4", "pct": "X%", "etoiles": 2}
    ]
  },
  "swot": {
    "forces": ["Force 1 factuelle (max 48 car.)", "Force 2", "Force 3", "Force 4"],
    "faiblesses": ["Faiblesse 1 (max 48 car.)", "Faiblesse 2", "Faiblesse 3", "Faiblesse 4"],
    "opportunites": ["Opportunité 1 chiffrée (max 48 car.)", "Opp 2", "Opp 3", "Opp 4"],
    "risques": ["Risque 1 concret (max 48 car.)", "Risque 2", "Risque 3", "Risque 4"]
  },
  "axes": [
    {"num": "1", "titre": "AXE 1 (max 35 car.)", "points": ["Action 1 avec KPI (max 55 car.)", "pt2", "pt3", "pt4"]},
    {"num": "2", "titre": "AXE 2", "points": ["pt1", "pt2", "pt3", "pt4"]},
    {"num": "3", "titre": "AXE 3", "points": ["pt1", "pt2", "pt3", "pt4"]},
    {"num": "4", "titre": "AXE 4", "points": ["pt1", "pt2", "pt3", "pt4"]}
  ],
  "modele_eco": {
    "tjm_actuel": "ex: X-Y €",
    "tjm_marche": "ex: X-Y € (ANNÉE)",
    "tjm_cible": "ex: X-Y € (ANNÉE)",
    "temps_partage_titre": "OFFRE TEMPS PARTAGÉ DG / DAF si le brief porte sur une offre de temps partagé ; sinon 'INDICATEURS CLÉS D'ACTIVITÉ' ou titre court adapté au contexte (max 35 car.)",
    "temps_partage": [
      {"kpi": "KPI 1", "label": "Libellé 1"},
      {"kpi": "KPI 2", "label": "Libellé 2"},
      {"kpi": "KPI 3", "label": "Libellé 3"},
      {"kpi": "KPI 4", "label": "Libellé 4"}
    ],
    "reseau_titre": "RÉSEAU CO-TRAITANTS si le brief porte sur un réseau de co-traitants ; sinon 'RÉSEAU PRESCRIPTEURS' ou titre court adapté au contexte (max 30 car.)",
    "reseau": [
      {"kpi": "KPI 1", "label": "Libellé 1"},
      {"kpi": "KPI 2", "label": "Libellé 2"},
      {"kpi": "KPI 3", "label": "Libellé 3"},
      {"kpi": "KPI 4", "label": "Libellé 4"}
    ]
  },
  "roadmap": [
    {
      "phase": "T1", "date": "Période 1", "titre": "PHASE 1 (max 18 car.)",
      "items": ["Action 1 (issue du CR)", "Action 2", "Action 3"],
      "kpi": "KPI de phase", "budget": "Budget (si présent au CR)", "extra": "Porteur / précision"
    },
    {
      "phase": "T2", "date": "Période 2", "titre": "PHASE 2",
      "items": ["Action 1", "Action 2", "Action 3"],
      "kpi": "KPI de phase", "budget": "Budget", "extra": "Porteur / précision"
    },
    {
      "phase": "T3", "date": "Période 3", "titre": "PHASE 3",
      "items": ["Action 1", "Action 2", "Action 3"],
      "kpi": "KPI de phase", "budget": "Budget", "extra": "Porteur / précision"
    },
    {
      "phase": "T4", "date": "Période 4", "titre": "PHASE 4",
      "items": ["Action 1", "Action 2", "Action 3"],
      "kpi": "KPI de phase", "budget": "Budget", "extra": "Porteur / précision"
    }
  ],
  "next_steps": [
    {"date": "Échéance 1", "action": "Action datée 1 (issue du CR)", "owner": "Porteur"},
    {"date": "Échéance 2", "action": "Action datée 2", "owner": "Porteur"},
    {"date": "Échéance 3", "action": "Action datée 3", "owner": "Porteur"},
    {"date": "Échéance 4", "action": "Action datée 4", "owner": "Porteur"},
    {"date": "Échéance 5", "action": "Action datée 5", "owner": "Porteur"}
  ],
  "questions_ouvertes": [
    "Arbitrage / question ouverte 1 (issue du CR)",
    "Arbitrage / question ouverte 2",
    "Arbitrage / question ouverte 3",
    "Arbitrage / question ouverte 4"
  ],
  "decisions_codir": [
    "Décision attendue 1 (issue du CR)",
    "Décision attendue 2",
    "Décision attendue 3"
  ],
  "conclusion": {
    "headline": "Message-clé de synthèse (issu du CR, max 45 car.)",
    "points": [
      "Point de conclusion 1 (chiffré si sourcé)",
      "Point de conclusion 2",
      "Point de conclusion 3"
    ],
    "contact": "CoDIR IA · Synthèse exécutive"
  }
}

Adapte TOUTES les valeurs au contenu réel. Ne laisse AUCUN placeholder ni bruit technique.
""").strip()


def _is_reasoning_model(model_id: str) -> bool:
    """Détecte les modèles de raisonnement OpenAI qui rejettent temperature=0."""
    m = (model_id or "").strip().lower()
    return m.startswith("o1") or m.startswith("o2") or m.startswith("o3") or m.startswith("gpt-5")

# SYSTEM_PROMPT court pour modèles avec contexte réduit (gpt-5-mini, o* mini)
SYSTEM_PROMPT_SHORT = (
    "Tu es un expert en stratégie. À partir du compte-rendu fourni, génère UNIQUEMENT "
    "un objet JSON valide (sans markdown) avec cette structure exacte :\n"
    '{"titre":str,"sous_titre":str,"entreprise":str,"date":str,'
    '"deck_type":"solo|corporate",'
    '"marche":{"taille":str,"croissance":str,"missions":str,"duree_moy":str,"tjm_moy":str,"tjm_detail":str,'
    '"drivers":[{"pct":str,"label":str}],"segments":[{"nom":str,"pct":str,"etoiles":int}]},'
    '"contexte_corporate":{"ca":str,"croissance":str,"effectif":str,"situation":str,'
    '"risques_top":[{"label":str,"probabilite":str,"impact":str}],'
    '"arbitrages":[str,str,str]},'
    '"swot":{"forces":[str,str,str,str],"faiblesses":[str,str,str,str],'
    '"opportunites":[str,str,str,str],"risques":[str,str,str,str]},'
    '"axes":[{"num":str,"titre":str,"points":[str,str,str,str]}],'
    '"modele_eco":{"tjm_actuel":str,"tjm_marche":str,"tjm_cible":str,'
    '"temps_partage_titre":str,"temps_partage":[{"kpi":str,"label":str}],"reseau_titre":str,"reseau":[{"kpi":str,"label":str}]},'
    '"roadmap":[{"phase":str,"date":str,"titre":str,"items":[str,str,str],"kpi":str,"budget":str,"extra":str}],'
    '"next_steps":[{"date":str,"action":str,"owner":str}],'
    '"commercial":{"titre":str,"opportunites":[str,str,str,str],"plan_actions":[{"action":str,"kpi":str,"delai":str}],"challenges_marketing":[str,str],"challenges_finance":[str,str]},"questions_ouvertes":[str,str,str,str],"decisions_codir":[str,str,str],'
    '"conclusion":{"headline":str,"points":[str,str,str],"contact":str}}'
    "\ndeck_type='solo' si brief d'une personne/cabinet/indépendant, 'corporate' si brief d'une entreprise/groupe/ETI/organisation."
    "\nAdapte TOUTES les valeurs au contenu réel. Aucun bruit technique. JSON pur uniquement."
)


def _call_provider(provider: str, user_msg: str, settings, max_tokens: int,
                   use_short_prompt: bool = False, lang: str = "fr") -> str:
    """
    Appelle le provider avec le bon SYSTEM_PROMPT et les bons paramètres.
    - Modèles reasoning (gpt-5*, o1*, o3*) : pas de temperature, prompt court, tokens réduits
    - Autres modèles : temperature=0.0, prompt complet
    """
    sys_prompt = SYSTEM_PROMPT_SHORT if use_short_prompt else SYSTEM_PROMPT
    # M.5.10 (FIX B) — verrou de langue : le SYSTEM_PROMPT du deck est rédigé en
    # français ; sans cette règle, le LLM produit des titres/axes/SWOT en français
    # même dans un run EN (le CR, lui, est anglais car les agents ont déjà la règle).
    if lang == "en":
        sys_prompt += (
            "\n\nLANGUAGE RULE (override): Produce the ENTIRE JSON output in ENGLISH. "
            "All titles, axis names, SWOT items, risks, actions, KPI labels, statuses "
            "and risk levels (high/medium/low) must be in English. Do NOT use French "
            "words or French section labels, even if the source compte-rendu is in French.")

    if provider == "openai":
        from providers.openai_provider import call_openai
        model = settings.openai_model_id
        # Pour les modèles reasoning : pas de temperature, tokens limités à 2048 max
        if _is_reasoning_model(model):
            max_tok = min(max_tokens, 2048)
            resp = call_openai(user_msg, system=sys_prompt, model=model,
                               temperature=None, max_tokens=max_tok)
        else:
            resp = call_openai(user_msg, system=sys_prompt, model=model,
                               temperature=0.0, max_tokens=max_tokens)
        return resp.get("output", "")

    if provider == "anthropic":
        from providers.claude_provider import call_claude
        resp = call_claude(user_msg, system=sys_prompt,
                           model=settings.anthropic_model_id,
                           temperature=0.0, max_tokens=max_tokens)
        return resp.get("output", "")

    if provider == "google":
        from providers.gemini_provider import call_gemini
        resp = call_gemini(user_msg, system=sys_prompt,
                           model=settings.google_model_id,
                           temperature=0.0, max_tokens=max_tokens)
        return resp.get("output", "")

    if provider == "mistral":
        from providers.mistral_provider import call_mistral
        resp = call_mistral(user_msg, system=sys_prompt,
                            model=settings.mistral_model_id,
                            temperature=0.0, max_tokens=max_tokens)
        return resp.get("output", "")

    raise ValueError(f"Provider inconnu : {provider}")


def _extract_json_from_raw(raw: str) -> dict:
    if not raw or not raw.strip():
        raise ValueError("Réponse IA vide")
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw).strip()
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e == -1 or e <= s:
        raise ValueError(f"Aucun JSON trouvé (len={len(raw)})")
    candidate = re.sub(r",\s*([}\]])", r"\1", raw[s:e + 1])
    return json.loads(candidate)


# P0-3 (M.5.8, FIX2b) — détection de RETRAIT dans le CR : marqueur P0-3 injecté
# (incohérence de scénario / axes conditionnels) OU « mise en sommeil recommandée ».
_WINDDOWN_DECK_RE = re.compile(
    r"incoh[eé]rence de sc[eé]nario|axes?\s+conditionnels?|retrait recommand|"
    r"mise en sommeil\s+recommand|recommand\w+[^.\n]{0,30}mise en sommeil",
    re.IGNORECASE,
)
_GROWTH_AXIS_KW = ("marketing", "commercial", "prospection", "linkedin",
                   "communication", "développement comm", "newsletter",
                   "campagne", "réseaux", "apporteurs")


def _demote_growth_axes_if_winddown(axes: list, cr_text: str, lang: str = "fr") -> list:
    """Sous une décision de RETRAIT (sommeil/cessation), démote les axes de
    croissance active hors des « axes principaux » : préfixe d'avertissement sur le
    titre + caveat en tête de points. Renvoie la liste d'axes (modifiée si retrait)."""
    if not _WINDDOWN_DECK_RE.search(cr_text or ""):
        return axes
    caveat = ("⚠️ Conditionnel — hors plan principal (à mener seulement si le "
              "retrait n'est pas confirmé)" if lang != "en" else
              "⚠️ Conditional — out of the main plan (only if wind-down not confirmed)")
    for ax in axes:
        blob = (str(ax.get("titre", "")) + " " + " ".join(ax.get("points", []))).lower()
        if any(k in blob for k in _GROWTH_AXIS_KW):
            if not str(ax.get("titre", "")).lstrip().startswith("⚠"):
                ax["titre"] = ("⚠️ " + ax.get("titre", ""))[:38]
            ax["points"] = [caveat] + [p for p in ax.get("points", []) if p != caveat][:3]
    return axes


def _apply_winddown_deck_governance(data: dict, cr_text: str, lang: str = "fr") -> None:
    """M.5.9 (FIX B, retex run dossier de conseil M.5.8) — gouvernance P0-3 appliquée au
    POINT DE CONVERGENCE du deck, quel que soit le chemin (LLM ou fallback). En
    M.5.8, la démotion ne tournait que dans le fallback ; le chemin LLM y échappait,
    et la cohérence des axes ne tenait qu'à la chance du LLM.
      (a) démote les axes de croissance hors plan principal ;
      (b) sous retrait, requalifie la slide commerciale en « maintien relationnel
          minimal — hors prospection active » (drapeau lu par _slide_commercial)."""
    if not _WINDDOWN_DECK_RE.search(cr_text or ""):
        return
    if isinstance(data.get("axes"), list):
        data["axes"] = _demote_growth_axes_if_winddown(data["axes"], cr_text, lang)
    comm = data.get("commercial")
    if isinstance(comm, dict):
        comm["winddown"] = True


_OPTION_TITLE_RE = re.compile(r"(?im)^\s*(?:#{1,6}\s*)?\**\s*option\s*(?:n[°º]\s*)?([1-9])\s*[:—–\-]\s*(.+?)\**\s*$")
_RECO_OPTION_N_RE = re.compile(
    r"(?i)(?:privil[ée]gi(?:er|ons|e)|reten(?:ir|ons)|opter\s+pour|recommand(?:ation\s+est\s+de\s+privil[ée]gier|ons|e|é)\s*(?:de\s+)?(?:privil[ée]gier|retenir)?|"
    r"pr[ée]conis(?:ons|e|é)\s*(?:de\s+)?(?:privil[ée]gier|retenir)?|recommended\s+option|we\s+recommend\s+option)\s+(?:l['’]|the\s+)?option\s*(?:n[°º]\s*)?([1-9])\b")
_RECO_MARK_RE = re.compile(r"(?i)\b(?:recommand[ée]e?s?|pr[ée]conis[ée]e?s?|recommended|à\s+retenir)\b")
_RECO_SENTENCE_RE = re.compile(
    r"(?i)^\s*(?:[-*•]\s*)?(?:\**\s*)?(?:la\s+recommandation\s+(?:est|serait)|il\s+est\s+recommand[ée]|nous\s+recommandons|nous\s+pr[ée]conisons|"
    r"orientation\s+recommand[ée]e\s*:|recommandation\s*:|we\s+recommend|the\s+recommendation\s+is)")


_PRODUCT_STATUS_RE = re.compile(
    r"(?i)^\s*(?:⚠|✅|❌|▌)?\s*(?:base\s+financi[èe]re|statut\s+mission|r[ée]serves?\s+d[ée]tect[ée]es?|contradiction\s+interne|"
    r"usage\s+interne\s+supervis[ée]|situation\s+financi[èe]re\s+actuelle|position\s+financi[èe]re|vocabulaire\s+du\s+produit|"
    r"cible\s+chiffr[ée]e\s+[ée]cart[ée]e|proposition\s+chiffr[ée]e|note\s+de\s+sortie|compl[ée]ment\s+v62|codir\s+ia\b)")


def _is_product_status_line(line: str) -> bool:
    t = str(line or "").strip()
    if not t:
        return True
    if _PRODUCT_STATUS_RE.search(t):
        return True
    letters = [c for c in t if c.isalpha()]
    return bool(letters) and len(letters) >= 12 and sum(1 for c in letters if c.isupper()) / len(letters) > 0.7


def _option_titles(cr_text: str) -> dict:
    """{n: « Option n — titre »} depuis les titres d'options du CR (sans la parenthèse de scénario)."""
    out: dict = {}
    for m in _OPTION_TITLE_RE.finditer(cr_text or ""):
        n, rest = m.group(1), m.group(2).strip()
        rest = re.sub(r"\s*\([^()]*\)\s*$", "", rest).strip(" *—–-:")
        if rest and n not in out:
            out[n] = f"Option {n} — {rest}"
    return out


def _recommended_option_number(dg_block: str, synth_block: str, cr_text: str) -> str:
    """Numéro de l'option recommandée : la phrase de la DG d'abord (« privilégier
    l'option 2 »), puis la synthèse, puis un titre d'option marqué RECOMMANDÉ."""
    for block in (dg_block, synth_block):
        m = _RECO_OPTION_N_RE.search(block or "")
        if m:
            return m.group(1)
    for m in _OPTION_TITLE_RE.finditer(cr_text or ""):
        if _RECO_MARK_RE.search(m.group(2)):
            return m.group(1)
    return ""


def _recommendation_sentence(dg_block: str, synth_block: str) -> str:
    """Première vraie phrase qui recommande (jamais une mention passée « … recommandé le 30/05/2025 »)."""
    for block in (dg_block, synth_block):
        for ln in (block or "").splitlines():
            t = _clean_bullet(ln, 160, truncate=False) if "_clean_bullet" in globals() else ln.strip()
            if t and _RECO_SENTENCE_RE.search(t) and not re.search(r"\d{1,2}/\d{1,2}/\d{4}", t[:80]):
                return t
    return ""


def _build_fallback_data(cr_text: str, lang: str = "fr") -> dict:
    """
    Fallback heuristique neutre — activé quand l'IA échoue à produire un JSON valide.
    Extrait le maximum d'informations réelles du CR, sans données hardcodées ni
    référence à un cas client spécifique (dossier de conseil, étude de marché, etc.).
    """
    lines = [l.strip() for l in (cr_text or "").splitlines()
             if l.strip() and not _is_noise(l.strip())]
    clean = [_clean_bullet(l, 90) for l in lines]
    clean = [l for l in clean if l and len(l) >= 8]

    # ── Extraction heuristique de base ────────────────────────────────────────
    def _find(patterns, default="—"):
        for p in patterns:
            m = re.search(p, cr_text or "", re.IGNORECASE)
            if m:
                return _strip_md(m.group(0).strip())
        return default

    date_val   = _find([r"\b(janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\s+20\d{2}\b", r"\b20\d{2}\b"], "2026")
    entreprise = _find([r"[A-Z][A-Z\s&]{3,30}(?:SAS|SARL|SA|SASU|SNC|ETI|PME|GROUP|GROUPE)(?:\s+\w+)?",
                        r"société\s*:\s*([^\n,]{3,40})", r"entreprise\s*:\s*([^\n,]{3,40})"], "")

    # ── Titre et sous-titre depuis le brief ou le CR ──────────────────────────
    brief_section = _extract_section(cr_text or "",
                                     ["BRIEF INITIAL", "BRIEF CODIR", "CONTEXTE"],
                                     ["STRATÉGIE", "STRATEGY", "MARKETING", "FINANCE", "SUPPLY"])
    titre_lines = [_clean_bullet(l, 55) for l in (brief_section or cr_text or "").splitlines()
                   if _clean_bullet(l, 55) and len(_clean_bullet(l, 55)) >= 15]
    titre    = titre_lines[0][:55] if titre_lines else "Compte-rendu CoDIR IA"
    sous_titre = titre_lines[1][:75] if len(titre_lines) > 1 else ("Board of Directors summary" if lang=="en" else "Synthèse du comité de direction")

    # ── Sections du CR extraites proprement ──────────────────────────────────
    def _sec(headings, stops, maxlines=12):
        block = _extract_section(cr_text or "", headings, stops)
        return [_clean_bullet(l, 80) for l in (block or "").splitlines()
                if _clean_bullet(l, 80) and len(_clean_bullet(l, 80)) >= 10][:maxlines]

    strat_lines  = _sec(["STRATÉGIE","STRATEGY"], ["BRIEF CODIR","BOARD BRIEF","MARKETING","FINANCE"], 8)
    mkt_lines    = _sec(["MARKETING"], ["FINANCE","SUPPLY","COMMERCIAL"], 8)
    fin_lines    = _sec(["FINANCE"], ["SUPPLY","COMMERCIAL","SYNTHÈSE","DECISION SYNTHESIS","GENERAL MANAGEMENT"], 8)
    sc_lines     = _sec(["SUPPLY CHAIN","SUPPLY"], ["COMMERCIAL","SYNTHÈSE","DECISION SYNTHESIS","GENERAL MANAGEMENT"], 8)
    comm_lines   = _sec(["DIRECTION COMMERCIALE","COMMERCIAL DIRECTION","COMMERCIAL"], ["SYNTHÈSE","DECISION SYNTHESIS","GENERAL MANAGEMENT"], 8)
    synth_lines  = _sec(["SYNTHÈSE DES DÉCISIONS","SYNTHÈSE","DECISION SYNTHESIS"], ["DIRECTION GÉNÉRALE","GENERAL MANAGEMENT","CEO"], 8)
    dg_lines     = _sec(["DIRECTION GÉNÉRALE","GENERAL MANAGEMENT","CEO","SYNTHÈSE CEO"], [], 8)

    # ── SWOT construit depuis les lignes du CR ────────────────────────────────
    def _kw_pick(pool, keywords, n=4, fallback=None):
        found, seen = [], set()
        for l in pool:
            if any(k in l.lower() for k in keywords):
                k = l[:35].lower()
                if k not in seen:
                    seen.add(k); found.append(l[:52])
            if len(found) >= n: break
        result = found[:n]
        if fallback:
            for fb in fallback:
                if len(result) >= n: break
                if fb[:35].lower() not in {r[:35].lower() for r in result}:
                    result.append(fb)
        return result[:n]

    all_lines = strat_lines + mkt_lines + fin_lines + sc_lines + comm_lines + synth_lines + dg_lines
    forces    = _kw_pick(all_lines, ["atout","force","solide","compétence","expertise","leader","différen"],
                         fallback=[SL("fallback_strength_1",lang),SL("fallback_strength_2",lang),SL("fallback_strength_3",lang),SL("fallback_strength_4",lang)])
    faiblesses= _kw_pick(all_lines, ["faible","limit","manque","absence","améliorer","risque","insuffisant"],
                         fallback=[SL("fallback_weakness_1",lang),SL("fallback_weakness_2",lang),SL("fallback_weakness_3",lang),SL("fallback_weakness_4",lang)])
    opps      = _kw_pick(all_lines, ["opportun","croissance","potentiel","développ","marché","levier","+"],
                         fallback=[SL("fallback_opp_1",lang),SL("fallback_opp_2",lang),SL("fallback_opp_3",lang),SL("fallback_opp_4",lang)])
    risques   = _kw_pick(all_lines, ["risque","menace","concurren","pression","retard","tension","rupture","dépendance"],
                         fallback=[SL("fallback_risk_1",lang),SL("fallback_risk_2",lang),SL("fallback_risk_3",lang),SL("fallback_risk_4",lang)])

    # ── Axes stratégiques depuis le CR ────────────────────────────────────────
    axes_raw = re.findall(r"(?:\d+\.|AXE\s*\d+)[.\s:–-]*([A-ZÉÀÈÊ][^\n]{5,40})", cr_text or "")
    axes_titles = [_strip_md(a).strip()[:38] for a in axes_raw if not _is_noise(a)][:4]
    axes_defaults = SL("fallback_axes",lang).split("|")
    for i in range(len(axes_titles), 4):
        axes_titles.append(axes_defaults[i])

    pool_axes = strat_lines + dg_lines + synth_lines
    axes = [
        {"num": str(i+1), "titre": t,
         "points": _pick_bullets(pool_axes[i*5:(i+1)*5] or clean[i*4:(i+1)*4], 4,
                                 filler=SL("fallback_confirm_session",lang))}
        for i, t in enumerate(axes_titles)
    ]

    # P0-3 (M.5.8, FIX2b) — sous décision de RETRAIT, démoter les axes de
    # CROISSANCE ACTIVE hors des « axes principaux » (préfixe + caveat).
    axes = _demote_growth_axes_if_winddown(axes, cr_text, lang)


    kpi_lines = [l for l in all_lines if any(c in l for c in ["%", "€", "K€", "M€", "j/"])]
    def _kpi_pair(idx, default_kpi, default_label):
        if idx < len(kpi_lines):
            return {"kpi": kpi_lines[idx][:16], "label": kpi_lines[idx][16:40].strip() or default_label}
        return {"kpi": default_kpi, "label": default_label}

    modele_eco = {
        "tjm_actuel": _find([r"TJM\s*actuel[^\n]{0,20}", r"\d{3,4}[-–]\d{3,4}\s*€/j"], SL("fallback_to_specify",lang)),
        "tjm_marche": _find([r"TJM\s*march[eé][^\n]{0,20}", r"marché[^\n]{0,30}\d{3,4}\s*€"], SL("fallback_to_specify",lang)),
        "tjm_cible":  _find([r"TJM\s*cible[^\n]{0,20}", r"cible[^\n]{0,20}\d{3,4}\s*€"], SL("fallback_to_specify",lang)),
        "temps_partage": [_kpi_pair(i, "—", l) for i, l in enumerate(
            [("Engagement type" if lang=="en" else "Engagement type"), ("Monthly revenue" if lang=="en" else "Revenu mensuel"), ("ARR potential" if lang=="en" else "ARR potentiel"), ("Contract length" if lang=="en" else "Durée contrats")])],
        "reseau": [_kpi_pair(i+4, "—", l) for i, l in enumerate(
            [("Partners" if lang=="en" else "Partenaires"), ("Fee" if lang=="en" else "Commission"), ("Capacity" if lang=="en" else "Capacité"), ("Fixed costs" if lang=="en" else "Coûts fixes")])],
    }

    # ── Roadmap depuis le CR ou phases génériques ─────────────────────────────
    phases_generic = [
        {"phase": "T1", "date": f"{date_val}", "titre": "STABILISATION",
         "items": (dg_lines[:3] or ["Consolider l'existant","Consolider l'existant","Consolider l'existant"]),
         "kpi": SL("fallback_foundations",lang), "budget": SL("fallback_to_define",lang), "extra": ""},
        {"phase": "T2", "date": f"{date_val}", "titre": SL("fallback_develop",lang),
         "items": (strat_lines[:3] or [SL("fallback_deploy",lang),SL("fallback_activate",lang),SL("fallback_track",lang)]),
         "kpi": SL("fallback_in_progress",lang), "budget": SL("fallback_to_define",lang), "extra": ""},
        {"phase": "T3", "date": f"{date_val}", "titre": SL("fallback_accelerate",lang),
         "items": (comm_lines[:3] or [SL("fallback_capitalize",lang),SL("fallback_extend",lang),SL("fallback_reinforce",lang)]),
         "kpi": SL("fallback_momentum",lang), "budget": SL("fallback_to_define",lang), "extra": ""},
        {"phase": "T4", "date": f"{date_val}", "titre": ("CONSOLIDATION" if lang=="en" else "CONSOLIDATION"),
         "items": (synth_lines[:3] or [("Review and adjust" if lang=="en" else "Bilan et ajustements"), ("Prepare next phase" if lang=="en" else "Préparer la suite"), ("Document results" if lang=="en" else "Documenter les résultats")]),
         "kpi": SL("fallback_goals_met",lang), "budget": SL("fallback_to_define",lang), "extra": ""},
    ]

    # ── Next steps depuis le CR (DG section) ─────────────────────────────────
    ns_lines = [l for l in dg_lines + synth_lines
                if any(k in l.lower() for k in ["action", "lancer", "valider", "déployer",
                                                  "mettre en place", "prioriser", "suivre"])]
    next_steps = []
    for i, l in enumerate(ns_lines[:5]):
        next_steps.append({"date": date_val, "action": l[:65], "owner": "À définir"})
    if not next_steps:
        next_steps = [{"date": date_val, "action": l[:65], "owner": "DG"} for l in (dg_lines or clean)[:5]]

    # ── Questions ouvertes et décisions depuis synthèse ───────────────────────
    qo_raw = re.search(
        r"(?:QUESTIONS?\s+OUVERTE[S]?|ARBITRAGE[S]?)[^\n]{0,20}\n([\s\S]{0,600})",
        cr_text or "", re.IGNORECASE)
    questions = []
    if qo_raw:
        for ln in qo_raw.group(1).splitlines():
            b = _clean_bullet(ln, 52)
            if b and len(b) >= 12:
                if not b.endswith("?"): b += " ?"
                questions.append(b)
        questions = questions[:4]
    if not questions:
        questions = [_clean_bullet(l, 52) + (" ?" if not _clean_bullet(l, 52).endswith("?") else "")
                     for l in (synth_lines + dg_lines)[:4] if _clean_bullet(l, 52)][:4]
    if not questions:
        questions = [SL("fallback_priorities_q",lang),
                     SL("fallback_arbitrages_q",lang),
                     ("Which KPIs to track?" if lang=="en" else "Quels indicateurs de suivi retenir ?"),
                     ("What time horizon to adopt?" if lang=="en" else "Quel horizon temporel retenir ?")]

    decisions_raw = re.findall(
        r"(?:DÉCISION[S]?|NEXT.STEP[S]?|ACTION[S]\s+PRIORITAIRE[S]?)[^\n]{0,20}\n([\s\S]{0,400})",
        cr_text or "", re.IGNORECASE)
    decisions = []
    for block in decisions_raw:
        for ln in block.splitlines():
            b = _clean_bullet(ln, 52)
            if b and len(b) >= 12: decisions.append(b)
        if len(decisions) >= 3: break
    decisions = decisions[:3] or (dg_lines[:3] if dg_lines else
                                   [SL("fallback_validate_strat",lang),
                                    ("Approve the action plan" if lang=="en" else "Approuver le plan d'action"),
                                    SL("fallback_define_owners",lang)])

    # ── Conclusion ────────────────────────────────────────────────────────────
    # v62.13.9.4.32 (B) — LA RECOMMANDATION DE PROVENANCE FAIT FOI. Le message
    # de couverture prenait la PREMIÈRE ligne de la section Direction générale —
    # au run réel ee08f0, la liste des options ouvre la section et la trame
    # titrait « Décision : Option 1 » alors que la DG recommande l'option 2
    # (contre-audit du 11/09/2026). La couverture cherche d'abord la phrase qui
    # recommande (recommander, préconiser, privilégier, retenir, opter pour) dans
    # la DG puis la synthèse ; quand elle désigne « l'option N », c'est le titre
    # de cette option qui devient le message. Jamais « toujours l'option 2 » :
    # seule la provenance décide.
    _dg_block = _extract_section(cr_text or "", ["DIRECTION GÉNÉRALE", "GENERAL MANAGEMENT", "CEO", "SYNTHÈSE CEO"], []) or ""
    _synth_block = _extract_section(cr_text or "", ["SYNTHÈSE DES DÉCISIONS", "SYNTHÈSE", "DECISION SYNTHESIS"], ["DIRECTION GÉNÉRALE", "GENERAL MANAGEMENT", "CEO"]) or ""
    _opt_titles = _option_titles(cr_text or "")
    _reco_n = _recommended_option_number(_dg_block, _synth_block, cr_text or "")
    _reco_headline = _opt_titles.get(_reco_n, "") if _reco_n else _recommendation_sentence(_dg_block, _synth_block)
    # v62.13.9.4.32 (B) — jamais une ligne de statut du produit en message de
    # couverture (« BASE FINANCIÈRE ACTUELLE CONFIRMÉE À LA PAGE », « ⚠ Statut
    # mission », « Réserves détectées ») : la couverture porte l'orientation ou,
    # à défaut, la première ligne de sens de la DG.
    headline_candidates = ([_reco_headline] if _reco_headline else []) + [
        ln for ln in (dg_lines or synth_lines or clean) if not _is_product_status_line(ln)]
    headline = headline_candidates[0][:58] if headline_candidates else SL("fallback_codir_synth",lang)
    conclusion_points = _pick_bullets(
        (dg_lines + synth_lines)[:6] or clean[:6], 3, filler=SL("fallback_confirm_session",lang))
    contact = _find([r"[\w.]+@[\w.]+\.[a-z]{2,}", r"linkedin\.com/in/[\w-]+"], "")

    return {
        "titre":      titre[:55],
        "sous_titre": sous_titre[:75],
        "entreprise": entreprise[:40] if entreprise != "—" else "",
        "date":       date_val,
        "marche": {
            "taille":     _find([r"\d{2,4}\s*[MG]€[^,\n]{0,20}"], "—"),
            "croissance": _find([r"[+\-]\s*\d+\s*%[^,\n]{0,15}"], "—"),
            "missions":   _find([r"\d[\d\s]*\s*missions?[^,\n]{0,20}"], "—"),
            "duree_moy":  _find([r"\d+[-–]\d+\s*mois"], "—"),
            "tjm_moy":    _find([r"\d{3,4}[-–]\d{3,4}\s*€"], "—"),
            "tjm_detail": "",
            "drivers":  [{"pct": "—", "label": l[:40]} for l in (strat_lines[:4] or ["—","—","—","—"])],
            "segments": [{"nom": l[:28], "pct": "—", "etoiles": 3}
                         for l in ((strat_lines + mkt_lines)[:4] or ["—","—","—","—"])],
        },
        "swot": {"forces": forces, "faiblesses": faiblesses,
                 "opportunites": opps, "risques": risques},
        "axes": axes,
        "modele_eco": modele_eco,
        "roadmap": phases_generic,
        "next_steps": next_steps,
        "commercial": _extract_commercial_payload(cr_text, lang=lang),
        "questions_ouvertes": questions,
        "decisions_codir":    decisions,
        "conclusion": {
            "headline": headline,
            "points":   conclusion_points,
            "contact":  contact,
        },
    }


def call_ia_for_structure_with_provider(cr_text: str, provider: str, settings, lang: str = "fr") -> dict:
    """
    Appelle l'IA pour structurer le CR en JSON.
    Stratégie à 3 niveaux selon le modèle :

    Modèles "reasoning" (gpt-5*, o1*, o3*) :
      - Tentative 1 : prompt court + texte tronqué à 5 000 chars + 1 500 tokens
      - Tentative 2 : prompt court + texte 3 000 chars + 1 024 tokens
      → Fallback local si échec

    Autres modèles (GPT-4o, Claude, Gemini, Mistral) :
      - Tentative 1 : prompt complet + texte 10 000 chars + 3 000 tokens
      - Tentative 2 : prompt complet + texte 14 000 chars + 4 096 tokens
      → Fallback local si échec
    """
    is_reasoning = (provider == "openai" and _is_reasoning_model(settings.openai_model_id))

    commercial_focus = _extract_section(
        cr_text,
        ["DIRECTION COMMERCIALE", "COMMERCIAL DIRECTION", "COMMERCIAL", "VOLET COMMERCIAL", "PRÉCONISATIONS COMMERCIALES", "COMMERCIAL DIAGNOSIS"],
        ["SYNTHÈSE DES DÉCISIONS", "DECISION SYNTHESIS", "DIRECTION GÉNÉRALE", "GENERAL MANAGEMENT", "CEO", "DG / CEO"],
    )
    marketing_focus = _extract_section(
        cr_text,
        ["MARKETING & COMMUNICATION", "MARKETING & COMMUNICATIONS", "MARKETING"],
        ["FINANCE", "DIRECTION COMMERCIALE", "COMMERCIAL", "SYNTHÈSE DES DÉCISIONS"],
    )
    finance_focus = _extract_section(
        cr_text,
        ["FINANCE & FISCALITÉ", "FINANCE & TAX", "FINANCE"],
        ["DIRECTION COMMERCIALE", "COMMERCIAL", "SYNTHÈSE DES DÉCISIONS", "DIRECTION GÉNÉRALE"],
    )

    focus_blocks = []
    if _has_meaningful_section(commercial_focus):
        focus_blocks.append("--- EXTRAIT DIRECTION COMMERCIALE ---\n" + commercial_focus[:3500])
    if _has_meaningful_section(marketing_focus):
        focus_blocks.append("--- EXTRAIT MARKETING ---\n" + marketing_focus[:2200])
    if _has_meaningful_section(finance_focus):
        focus_blocks.append("--- EXTRAIT FINANCE ---\n" + finance_focus[:2200])
    focus_text = "\n\n".join(focus_blocks)

    user_tmpl = (
        "Voici le compte-rendu CoDIR IA. Extrais les informations clés "
        "(chiffres, stratégies, actions datées, KPIs) et génère le JSON. "
        "UNIQUEMENT du JSON valide, rien d'autre.\n\n"
        "Si un volet commercial est présent dans les extraits ou dans le compte-rendu, il doit impérativement apparaître dans l'objet JSON 'commercial'.\n\n"
        "{focus}\n\n--- COMPTE-RENDU ---\n{text}\n--- FIN ---"
    )

    if is_reasoning:
        # Modèles reasoning : prompt minimal, texte court, tokens modérés
        attempts = [
            (cr_text[:5000],  1500, True),   # prompt court
            (cr_text[:3000],  1024, True),   # encore plus court
        ]
    else:
        # Modèles standards : prompt complet, texte long
        attempts = [
            (cr_text[:10000], 3000, False),
            (cr_text[:14000], 4096, False),
        ]

    last_error = None
    for text, max_tok, use_short in attempts:
        try:
            user_msg = user_tmpl.format(text=text, focus=focus_text)
            raw = _call_provider(provider, user_msg, settings, max_tok,
                                 use_short_prompt=use_short, lang=lang)
            if not raw or not raw.strip():
                raise ValueError("Réponse vide du provider")
            data = _extract_json_from_raw(raw)
            if not isinstance(data, dict) or "titre" not in data:
                raise ValueError("JSON reçu incomplet (clé 'titre' manquante)")
            return data
        except Exception as e:
            last_error = e
            continue

    warnings.warn(
        f"pptx_from_cr: JSON IA invalide ({last_error}). "
        "Utilisation du fallback local (extraction heuristique).",
        RuntimeWarning, stacklevel=2,
    )
    return _build_fallback_data(cr_text, lang=lang)


# ───────────────────────────────────────────────────────────────────────────────
# 3. PALETTE & UTILITAIRES RENDU
# ───────────────────────────────────────────────────────────────────────────────

# ── Bilingual slide labels — v16.5.38 ────────────────────────────────────────
SLIDE_LABELS: dict[str, dict[str, str]] = {
    "fr": {
        # Slide headers
        "slide_title_strategy":    "STRATÉGIE",
        "slide_title_marketing":   "MARKETING & COMMUNICATION",
        "slide_title_finance":     "FINANCE & FISCALITÉ",
        "slide_title_sc":          "SUPPLY CHAIN & PERFORMANCE OPÉRATIONNELLE",
        "slide_title_commercial":  "DIRECTION COMMERCIALE",
        "slide_title_synthesis":   "SYNTHÈSE DES DÉCISIONS",
        "slide_title_dg":          "DIRECTION GÉNÉRALE",
        # Section labels
        "exec_summary":            "SYNTHÈSE EXÉCUTIVE",
        "decisions_dg":            "DÉCISIONS PROPOSÉES AU DG",
        "decisions_to_decide":     "ARBITRAGES À EXAMINER PAR LE DG",
        "decisions_expected":      "DÉCISIONS ATTENDUES",
        "board_tradeoffs":         "ARBITRAGES CODIR",
        "action_plan":             "PLAN D'ACTION",
        "sc_diagnosis":            "DIAGNOSTIC OPÉRATIONNEL",
        "sc_kpis":                 "KPI SUPPLY CHAIN",
        "sc_risks":                "RISQUES SUPPLY CHAIN",
        "sc_legend_fact":          "[FAIT]",
        "sc_legend_ref":           "[REF SECT.]",
        "sc_legend_estim":         "[ESTIM. IA]",
        "commercial_diagnosis":    "DIAGNOSTIC COMMERCIAL",
        "commercial_opport":       "OPPORTUNITÉS",
        "commercial_actions":      "PRÉCONISATIONS",
        "roadmap_label":           "FEUILLE DE ROUTE",
        "generated_by":            f"Généré par CoDIR IA — {_GEN_VERSION}",
        "for_internal_use":        "Document confidentiel — usage interne",
        "estimated_badge":         "est.",
        # Bool/status
        "status_healthy":          "sain",
        "status_stressed":         "sous tension",
        "status_degraded":         "dégradé",
        "status_critical":         "critique",
        # Fallback inline text
        "not_specified":           "Non précisé",
        "to_confirm":              "À confirmer",
        "brief_codir_label":       "BRIEF CODIR",
        "period_label":            "Période",
        "company_label":           "Société",
        # Slide titre
        "title_subtitle":          "Analyse multi-directionnelle  ·  Synthèse exécutive  ·  Plan d'action",
        "codir_synth":             "CoDIR IA · Synthèse exécutive",
        "ctx_ca":                  "Chiffre d'affaires (indicatif)",  # M.5.9 FIX C — valeur brief/narratif, non probante
        "synth_ca_indic":          "CA (indicatif)",
        "ctx_headcount":           "Effectif",
        "ctx_situation":           "Situation actuelle",
        "ctx_collaborateurs":      "collaborateurs",
        "augmented_board":         "Décision augmentée",
        # Slide SWOT
        "swot_title":              "POSITIONNEMENT",
        "swot_subtitle":           "Forces · Faiblesses · Opportunités · Risques",
        "swot_opportunities":      "OPPORTUNITÉS",
        "swot_risks_quad":         "RISQUES",
        "footer_ai":               "Document généré par IA — revue humaine requise — AI Act art. 50(4) si applicable",
        # B.1.3 — slide « Cadre de lecture » (prudence dès la slide 2)
        "b13_frame_title":         "CADRE DE LECTURE",
        "b13_frame_sub":           "Prudence — statut de la preuve",
        "b13_grade_line":          "Grade {g} — cadrage interne uniquement",
        "b13_no_fs":               "Aucun compte consolidé fourni",
        "b13_fs_ok":               "Comptes consolidés fournis",
        "b13_hypo":                "Montants hors faits sourcés = hypothèses à vérifier",
        "b13_ctx_line":            "Contexte : mode {m} · périmètre {p} · entité {e}",
        "b13_nondistrib":          "⛔ RUN NON VALIDABLE — LIVRABLE NON DISTRIBUABLE EN L'ÉTAT — {n} section(s) incomplète(s)",
        "b13_orientation":         "ORIENTATION NON CERTIFIÉE (pièces financières requises)",
        "ctx_diag_title":          "CONTEXTE & DIAGNOSTIC",
        "overview_title":          "VUE D'ENSEMBLE",
        "status_to_qualify":       "À QUALIFIER",
        "sc_status_sain":          "SAIN",
        "sc_status_sous_tension":  "SOUS TENSION",
        "sc_status_degrade":       "DÉGRADÉ",
        "risk_lvl_high":           "élevée",
        "risk_lvl_medium":         "moyenne",
        "risk_lvl_low":            "faible",
        "sc_dim_service":          "Service",
        "sc_dim_stock":            "Stock",
        "sc_dim_supplier":         "Fourn.",
        "sc_dim_cash":             "Cash",
        "swot_strengths":          "Forces",
        "swot_weaknesses":         "Faiblesses",
        "swot_threats":            "Risques",
        # Slide modèle éco
        "eco_title":               "MODÈLE ÉCONOMIQUE OPTIMISÉ",
        "eco_subtitle":            "TJM · Temps partagé · Réseau prescripteurs",
        "eco_offer_default":       "OFFRE TEMPS PARTAGÉ DG / DAF",
        "eco_network_default":     "RÉSEAU CO-TRAITANTS",
        "eco_activity_fallback":   "MODÈLE D'ACTIVITÉ",
        "eco_network_fallback":    "RÉSEAU & PARTENAIRES",
        "eco_tjm_labels":          "TJM actuel estimé|TJM marché senior (2026)|TJM cible 2027 (niches)",
        # Slide roadmap
        "roadmap_title":           "PLAN D'EXÉCUTION",
        "roadmap_subtitle":        "Roadmap trimestrielle · Actions · KPIs · Budgets",
        # Slide conclusion / marché
        "market_size_label":       "Taille du marché",
        "key_points_label":        "Points clés",
        "scope_label":             "Périmètre analysé",
        "avg_duration_label":      "Durée moyenne",
        "per_mission_label":       "par mission",
        "growth_label":            "Croissance",
        "market_label":            "Marché FR",
        "positioning_label":       "Positionnement",
        "differentiation_label":   "Différenciation",
        # Slide risques corporate
        "arbitrages_to_decide":    "ARBITRAGES À EXAMINER",
        # SC legend estimated
        "sc_briefing_mode":        "Scores : estimés (MODE BRIEFING)",
        "sc_briefing_mode_en":     "Scores: estimated (BRIEFING MODE)",
        # Fallback data
        "fallback_consolidate":    "Consolider l'existant",
        "fallback_validate_prio":  "Valider les priorités",
        "fallback_align_teams":    "Aligner les équipes",
        "fallback_foundations":    "Fondations posées",
        "fallback_to_define":      "À définir",
        "fallback_develop":        "DÉVELOPPEMENT",
        "fallback_deploy":         "Déployer le plan",
        "fallback_activate":       "Activer les leviers",
        "fallback_track":          "Suivre les KPIs",
        "fallback_in_progress":    "Plan en cours",
        "fallback_accelerate":     "ACCÉLÉRATION",
        "fallback_capitalize":     "Capitaliser sur les acquis",
        "fallback_extend":         "Étendre l'offre",
        "fallback_reinforce":      "Renforcer les positions",
        "fallback_momentum":       "Traction confirmée",
        "fallback_goals_met":      "Objectifs atteints",
        "fallback_confirm_session":"À confirmer en séance",
        "fallback_to_specify":     "À préciser",
        "fallback_priorities_q":   "Quelles sont les priorités immédiates ?",
        "fallback_arbitrages_q":   "Quels arbitrages valider en séance ?",
        "fallback_validate_strat": "Valider les priorités stratégiques",
        "fallback_define_owners":  "Définir les responsables et délais",
        "fallback_codir_synth":    "Synthèse CoDIR IA",
        "fallback_axes": "PRIORITÉS STRATÉGIQUES|PERFORMANCE OPÉRATIONNELLE|DÉVELOPPEMENT COMMERCIAL|PLAN D'EXÉCUTION",
        # SWOT fallbacks
        "fallback_strength_1": "Expertise confirmée",
        "fallback_strength_2": "Agilité opérationnelle",
        "fallback_strength_3": "Couverture multi-secteurs",
        "fallback_strength_4": "Crédibilité terrain",
        "fallback_weakness_1": "Ressources à renforcer",
        "fallback_weakness_2": "Visibilité à développer",
        "fallback_weakness_3": "Processus à structurer",
        "fallback_weakness_4": "Capacité à calibrer",
        "fallback_opp_1": "Croissance du marché adressable",
        "fallback_opp_2": "Nouvelles offres à déployer",
        "fallback_opp_3": "Partenariats stratégiques",
        "fallback_opp_4": "Transformation digitale",
        "fallback_risk_1": "Pression concurrentielle",
        "fallback_risk_2": "Dépendances fournisseurs",
        "fallback_risk_3": "Volatilité de la demande",
        "fallback_risk_4": "Risque d'exécution",

        # Slide axes
        "axes_title":              "4 AXES STRATÉGIQUES",
        "axes_subtitle":           "Préconisations CoDIR IA · Priorités stratégiques",
        # Slide SC subtitles / inline
        "sc_subtitle":             "Diagnostic · Risques · Arbitrages · Plan d'action",
        "sc_global_status":        "STATUT GLOBAL",
        "sc_findings":             "CONSTATS CLÉS",
        "sc_major_risks":          "RISQUES MAJEURS",
        "sc_no_critical_risk":     "Aucun risque critique identifié",
        "sc_decisions_to_arb":     "Décisions à arbitrer en séance",
        "sc_data_unavailable":     "Données non disponibles",
        "sc_legend":               "[FAIT] donnée fournie · [REF SECT.] benchmark · [ESTIM. IA] estimation",
        # Slide Commercial subtitles
        "commercial_subtitle":     "Opportunités · Plan d'actions · Challenges Marketing & Finance",
        "commercial_opportunities":"OPPORTUNITÉS IDENTIFIÉES",
        "commercial_action_plan":  "PLAN D'ACTIONS COMMERCIAL",
        "marketing_challenges":    "CHALLENGES MARKETING",
        "finance_challenges":      "CHALLENGES FINANCE",
        # Slide Next steps
        "next_steps_title":        "PROCHAINES ÉTAPES & DÉCISIONS",
        "next_steps_subtitle":     "Actions datées · Questions ouvertes · Décisions CoDIR",
        "priority_actions":        "PROCHAINES ÉTAPES — ACTIONS PRIORITAIRES",
        "questions_to_decide":     "QUESTIONS OUVERTES",
        "to_define":               "À définir",
        # Slide Risques & Arbitrages (corporate)
        "risks_arbitrages_title":  "RISQUES & ARBITRAGES CODIR",
        "risks_arbitrages_sub":    "Matrice risques · Décisions DG · Points de vigilance",
        "high_risks":              "RISQUES ÉLEVÉS",
        "medium_risks":            "RISQUES MOYENS",
        "watch_points":            "POINTS DE VEILLE",
    },
    "en": {
        # Slide headers
        "slide_title_strategy":    "STRATEGY",
        "slide_title_marketing":   "MARKETING & COMMUNICATIONS",
        "slide_title_finance":     "FINANCE & TAX",
        "slide_title_sc":          "SUPPLY CHAIN & OPERATIONAL PERFORMANCE",
        "slide_title_commercial":  "SALES & COMMERCIAL",
        "slide_title_synthesis":   "DECISION SUMMARY",
        "slide_title_dg":          "EXECUTIVE MANAGEMENT",
        # Section labels
        "exec_summary":            "EXECUTIVE SUMMARY",
        "decisions_dg":            "DECISIONS PROPOSED TO CEO",
        "decisions_to_decide":     "DECISIONS TO BE MADE BY CEO",
        "decisions_expected":      "EXPECTED DECISIONS",
        "board_tradeoffs":         "EXECUTIVE TRADE-OFFS",
        "action_plan":             "ACTION PLAN",
        "sc_diagnosis":            "OPERATIONAL DIAGNOSIS",
        "sc_kpis":                 "SUPPLY CHAIN KPIs",
        "sc_risks":                "SUPPLY CHAIN RISKS",
        "sc_legend_fact":          "[FACT]",
        "sc_legend_ref":           "[SECT. REF.]",
        "sc_legend_estim":         "[AI ESTIM.]",
        "commercial_diagnosis":    "COMMERCIAL DIAGNOSIS",
        "commercial_opport":       "OPPORTUNITIES",
        "commercial_actions":      "RECOMMENDATIONS",
        "roadmap_label":           "ROADMAP",
        "generated_by":            f"Generated by CoDIR IA — {_GEN_VERSION}",
        "for_internal_use":        "Confidential — internal use only",
        "estimated_badge":         "est.",
        # Bool/status
        "status_healthy":          "healthy",
        "status_stressed":         "under pressure",
        "status_degraded":         "degraded",
        "status_critical":         "critical",
        # Fallback inline text
        "not_specified":           "Not specified",
        "to_confirm":              "To be confirmed",
        "brief_codir_label":       "BOARD BRIEF",
        "period_label":            "Period",
        "company_label":           "Company",
        # Slide titre
        "title_subtitle":          "Multi-directional analysis  ·  Executive synthesis  ·  Action plan",
        "codir_synth":             "CoDIR IA · Executive synthesis",
        "ctx_ca":                  "Revenue (indicative)",  # M.5.9 FIX C
        "synth_ca_indic":          "Revenue (indic.)",
        "ctx_headcount":           "Headcount",
        "ctx_situation":           "Current situation",
        "ctx_collaborateurs":      "employees",
        "augmented_board":         "Augmented decision",
        # Slide SWOT
        "swot_title":              "POSITIONING",
        "swot_subtitle":           "Strengths · Weaknesses · Opportunities · Risks",
        "swot_opportunities":      "OPPORTUNITIES",
        "swot_risks_quad":         "RISKS",
        "footer_ai":               "AI-generated document — human review required — AI Act art. 50(4) where applicable",
        # B.1.3 — "Reading frame" slide (prudence from slide 2)
        "b13_frame_title":         "READING FRAME",
        "b13_frame_sub":           "Prudence — status of the evidence",
        "b13_grade_line":          "Grade {g} — internal framing only",
        "b13_no_fs":               "No consolidated accounts provided",
        "b13_fs_ok":               "Consolidated accounts provided",
        "b13_hypo":                "Figures outside sourced facts = hypotheses to verify",
        "b13_ctx_line":            "Context: {m} · {p} perimeter · entity {e}",
        "b13_nondistrib":          "⛔ RUN NOT VALIDATABLE — DELIVERABLE NOT DISTRIBUTABLE AS IS — {n} incomplete section(s)",
        "b13_orientation":         "UNCERTIFIED ORIENTATION (financial documents required)",
        "ctx_diag_title":          "CONTEXT & DIAGNOSIS",
        "overview_title":          "OVERVIEW",
        "status_to_qualify":       "TO QUALIFY",
        "sc_status_sain":          "HEALTHY",
        "sc_status_sous_tension":  "UNDER PRESSURE",
        "sc_status_degrade":       "DEGRADED",
        "risk_lvl_high":           "high",
        "risk_lvl_medium":         "medium",
        "risk_lvl_low":            "low",
        "sc_dim_service":          "Service",
        "sc_dim_stock":            "Stock",
        "sc_dim_supplier":         "Supplier",
        "sc_dim_cash":             "Cash",
        "swot_strengths":          "Strengths",
        "swot_weaknesses":         "Weaknesses",
        "swot_threats":            "Risks",
        # Slide modèle éco
        "eco_title":               "OPTIMISED BUSINESS MODEL",
        "eco_subtitle":            "Day rate · Part-time · Prescriber network",
        "eco_offer_default":       "PART-TIME CEO / CFO OFFERING",
        "eco_network_default":     "SUBCONTRACTOR NETWORK",
        "eco_activity_fallback":   "ACTIVITY MODEL",
        "eco_network_fallback":    "NETWORK & PARTNERS",
        "eco_tjm_labels":          "Current day rate (est.)|Senior market rate (2026)|Target rate 2027 (niches)",
        # Slide roadmap
        "roadmap_title":           "EXECUTION PLAN",
        "roadmap_subtitle":        "Quarterly roadmap · Actions · KPIs · Budgets",
        # Slide conclusion / marché
        "market_size_label":       "Market size",
        "key_points_label":        "Key points",
        "scope_label":             "Scope analysed",
        "avg_duration_label":      "Average duration",
        "per_mission_label":       "per engagement",
        "growth_label":            "Growth",
        "market_label":            "Market",
        "positioning_label":       "Positioning",
        "differentiation_label":   "Differentiation",
        # Slide risques corporate
        "arbitrages_to_decide":    "DECISIONS TO ARBITRATE",
        # SC legend estimated
        "sc_briefing_mode":        "Scores: estimated (BRIEFING MODE)",
        "sc_briefing_mode_en":     "Scores: estimated (BRIEFING MODE)",
        # Fallback data
        "fallback_consolidate":    "Consolidate existing base",
        "fallback_validate_prio":  "Validate priorities",
        "fallback_align_teams":    "Align teams",
        "fallback_foundations":    "Foundations laid",
        "fallback_to_define":      "To be defined",
        "fallback_develop":        "DEVELOPMENT",
        "fallback_deploy":         "Deploy the plan",
        "fallback_activate":       "Activate levers",
        "fallback_track":          "Track KPIs",
        "fallback_in_progress":    "Plan underway",
        "fallback_accelerate":     "ACCELERATION",
        "fallback_capitalize":     "Build on achievements",
        "fallback_extend":         "Extend the offering",
        "fallback_reinforce":      "Reinforce positions",
        "fallback_momentum":       "Momentum confirmed",
        "fallback_goals_met":      "Objectives achieved",
        "fallback_confirm_session":"To be confirmed in session",
        "fallback_to_specify":     "To be specified",
        "fallback_priorities_q":   "What are the immediate priorities?",
        "fallback_arbitrages_q":   "Which decisions to validate in session?",
        "fallback_validate_strat": "Validate strategic priorities",
        "fallback_define_owners":  "Define owners and deadlines",
        "fallback_codir_synth":    "CoDIR IA Summary",
        "fallback_axes": "STRATEGIC PRIORITIES|OPERATIONAL PERFORMANCE|COMMERCIAL DEVELOPMENT|EXECUTION PLAN",
        # SWOT fallbacks
        "fallback_strength_1": "Proven expertise",
        "fallback_strength_2": "Operational agility",
        "fallback_strength_3": "Multi-sector coverage",
        "fallback_strength_4": "Field credibility",
        "fallback_weakness_1": "Resources to strengthen",
        "fallback_weakness_2": "Visibility to develop",
        "fallback_weakness_3": "Processes to structure",
        "fallback_weakness_4": "Capacity to calibrate",
        "fallback_opp_1": "Addressable market growth",
        "fallback_opp_2": "New offerings to deploy",
        "fallback_opp_3": "Strategic partnerships",
        "fallback_opp_4": "Digital transformation",
        "fallback_risk_1": "Competitive pressure",
        "fallback_risk_2": "Supplier dependencies",
        "fallback_risk_3": "Demand volatility",
        "fallback_risk_4": "Execution risk",

        # Slide axes
        "axes_title":              "4 STRATEGIC PRIORITIES",
        "axes_subtitle":           "CoDIR IA Recommendations · Strategic priorities",
        # Slide SC subtitles / inline
        "sc_subtitle":             "Diagnosis · Risks · Trade-offs · Action Plan",
        "sc_global_status":        "OVERALL STATUS",
        "sc_findings":             "KEY FINDINGS",
        "sc_major_risks":          "MAJOR RISKS",
        "sc_no_critical_risk":     "No critical risk identified",
        "sc_decisions_to_arb":     "Decisions to arbitrate in session",
        "sc_data_unavailable":     "Data unavailable",
        "sc_legend":               "[FACT] provided data · [SECT. REF.] benchmark · [AI ESTIM.] estimate",
        # Slide Commercial subtitles
        "commercial_subtitle":     "Opportunities · Action Plan · Marketing & Finance Challenges",
        "commercial_opportunities":"IDENTIFIED OPPORTUNITIES",
        "commercial_action_plan":  "COMMERCIAL ACTION PLAN",
        "marketing_challenges":    "MARKETING CHALLENGES",
        "finance_challenges":      "FINANCE CHALLENGES",
        # Slide Next steps
        "next_steps_title":        "NEXT STEPS & DECISIONS",
        "next_steps_subtitle":     "Dated actions · Open questions · Board decisions",
        "priority_actions":        "PRIORITY ACTIONS",
        "questions_to_decide":     "QUESTIONS TO DECIDE",
        "to_define":               "To be defined",
        # Slide Risques & Arbitrages (corporate)
        "risks_arbitrages_title":  "RISKS & BOARD TRADE-OFFS",
        "risks_arbitrages_sub":    "Risk matrix · CEO decisions · Watch points",
        "high_risks":              "HIGH RISKS",
        "medium_risks":            "MEDIUM RISKS",
        "watch_points":            "WATCH POINTS",
    },
}

def SL(key: str, lang: str = "fr") -> str:
    """Return a slide label in the requested language (falls back to FR)."""
    return SLIDE_LABELS.get(lang, SLIDE_LABELS["fr"]).get(key, SLIDE_LABELS["fr"].get(key, key))


# ── M.5.10 (Language Closure) — normalisation FR+EN des valeurs LLM ───────────
_RISK_LEVEL_NORM = {
    "élevée": "high", "elevee": "high", "élevé": "high", "eleve": "high", "high": "high",
    "moyenne": "medium", "moyen": "medium", "medium": "medium", "mid": "medium",
    "faible": "low", "low": "low",
}


def _risk_level_color(value: str):
    """Couleur d'un niveau de risque, quelle que soit la langue (FR ou EN)."""
    n = _RISK_LEVEL_NORM.get(str(value).strip().lower())
    return {"high": C_RED, "medium": C_GOLD, "low": C_GREEN}.get(n, C_MID_GRAY)


def _loc_risk_level(value: str, lang: str = "fr") -> str:
    """Affiche un niveau de risque dans la langue du run (normalise FR→EN→label)."""
    n = _RISK_LEVEL_NORM.get(str(value).strip().lower())
    if not n:
        return str(value)
    return SL({"high": "risk_lvl_high", "medium": "risk_lvl_medium", "low": "risk_lvl_low"}[n], lang)


_SC_STATUS_KEY = {
    "sain": "sc_status_sain", "saine": "sc_status_sain", "healthy": "sc_status_sain",
    "sous tension": "sc_status_sous_tension", "sous_tension": "sc_status_sous_tension",
    "under pressure": "sc_status_sous_tension", "tendu": "sc_status_sous_tension",
    "dégradé": "sc_status_degrade", "degrade": "sc_status_degrade",
    "dégradée": "sc_status_degrade", "degraded": "sc_status_degrade",
}


def _loc_sc_status(value: str, lang: str = "fr") -> str:
    """Affiche un statut supply chain dans la langue du run."""
    key = _SC_STATUS_KEY.get(str(value).replace("_", " ").strip().lower())
    return SL(key, lang) if key else str(value).replace("_", " ").upper()


# ── M.5.10.4 — Normalisation EN du VOCABULAIRE CONTRÔLÉ supply chain ──────────
# Les agents SC émettent des enums/statuts/tags en français (« moyenne »,
# « RECOMMANDÉE », « À TRANCHER », « sous tension »…) même en run EN. Le verrou de
# prompt réduit la dérive du texte libre mais ne garantit pas le vocabulaire
# structuré. On le localise donc DÉTERMINISTEMENT au rendu (le texte libre
# résiduel reste, lui, du ressort du Language Gate).
import re as _re_sc

_SC_VOCAB_EN = [
    # décisions / statuts d'arbitrage (casse préservée par le remplacement ciblé)
    (_re_sc.compile(r"\bRECOMMAND[EÉ]{1,2}E?\b", _re_sc.I), "RECOMMENDED"),
    (_re_sc.compile(r"\b[AÀ]\s+TRANCHER\b", _re_sc.I),       "TO ARBITRATE"),
    (_re_sc.compile(r"\b[AÀ]\s+ARBITRER\b", _re_sc.I),       "TO ARBITRATE"),
    (_re_sc.compile(r"\b[AÀ]\s+QUALIFIER\b", _re_sc.I),      "TO QUALIFY"),
    # statuts supply chain
    (_re_sc.compile(r"\bsous[\s_]tension\b", _re_sc.I),      "under pressure"),
    (_re_sc.compile(r"\bd[ée]grad[ée]e?\b", _re_sc.I),       "degraded"),
    (_re_sc.compile(r"\bcritique\b", _re_sc.I),              "critical"),
    (_re_sc.compile(r"\bsaine?\b", _re_sc.I),                "healthy"),
    # niveaux de risque / probabilité
    (_re_sc.compile(r"\b[ée]lev[ée]e?\b", _re_sc.I),         "high"),
    (_re_sc.compile(r"\bmoyenne?\b", _re_sc.I),              "medium"),
    (_re_sc.compile(r"\bfaible\b", _re_sc.I),                "low"),
    # M.5.10.10 — vocabulaire SC contrôlé manquant (audit dossier anglophone coté EN)
    (_re_sc.compile(r"\bsaturation\s+logistique\b", _re_sc.I), "logistics saturation"),
    (_re_sc.compile(r"\bsurstock(?:age)?\b", _re_sc.I),       "overstock"),
    (_re_sc.compile(r"\bruptures?\s+de\s+stock\b", _re_sc.I), "stockout"),
    (_re_sc.compile(r"\bruptures?\b", _re_sc.I),              "stockout"),
    (_re_sc.compile(r"\bp[ée]nuries?\b", _re_sc.I),           "shortage"),
    (_re_sc.compile(r"\bretards?\s+de\s+livraison\b", _re_sc.I), "delivery delays"),
]


def _loc_sc_text(value, lang: str = "fr"):
    """Normalise le vocabulaire contrôlé SC en EN (no-op en FR / hors EN).

    Traite str ou list[str]. Ne touche QUE les tokens d'enum/statut/décision ;
    le reste du texte (narratif libre) est laissé tel quel.
    """
    if (lang or "fr").lower() != "en" or not value:
        return value
    if isinstance(value, (list, tuple)):
        return [_loc_sc_text(v, lang) for v in value]
    out = str(value)
    for rx, repl in _SC_VOCAB_EN:
        out = rx.sub(repl, out)
    return out


# M.5.10 — langue courante du deck, pour les rendus sans lang en signature (footer).
_DECK_LANG = "fr"


C_NAVY       = RGBColor(0x1E,0x27,0x61)
C_ICE_BLUE   = RGBColor(0xCA,0xDC,0xFC)
C_GOLD       = RGBColor(0xE8,0xB8,0x4B)
C_WHITE      = RGBColor(0xFF,0xFF,0xFF)
C_LIGHT_GRAY = RGBColor(0xF5,0xF7,0xFA)
C_MID_GRAY   = RGBColor(0x88,0x96,0xB0)
C_TEXT_DARK  = RGBColor(0x1A,0x1F,0x36)
C_GREEN      = RGBColor(0x27,0xAE,0x60)
C_TEAL       = RGBColor(0x0D,0x94,0x88)
C_RED        = RGBColor(0xE7,0x4C,0x3C)
C_BLUE_MED   = RGBColor(0x5E,0x81,0xF4)
C_ORANGE     = RGBColor(0xF9,0x61,0x67)
C_DARK_NAVY  = RGBColor(0x0D,0x14,0x3D)  # v16.5.59 — fond slides titre/couverture


def _rgb(r,g,b): return RGBColor(r,g,b)

def _add_rect(slide,x,y,w,h,fill,line=None):
    s=slide.shapes.add_shape(1,Inches(x),Inches(y),Inches(w),Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb=fill
    if line: s.line.color.rgb=line
    else: s.line.fill.background()
    return s

def _add_oval(slide,x,y,w,h,fill):
    s=slide.shapes.add_shape(9,Inches(x),Inches(y),Inches(w),Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb=fill; s.line.fill.background(); return s

def _add_text(slide,text,x,y,w,h,font_size=12,bold=False,italic=False,
              color=None,align=PP_ALIGN.LEFT,font_name="Calibri",auto_fit=False,
              role=None):
    if color is None: color=C_TEXT_DARK
    b=slide.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(h))
    if role:
        try:
            b.name = str(role)
        except Exception:
            pass
    tf=b.text_frame; tf.word_wrap=True
    if role and str(role).startswith("HCRIT:"):
        # Critical boxes are never allowed to rely on a fixed font size that
        # can silently overflow.  Compute a deterministic best-fit size while
        # preserving the H floor of 8 pt.
        # H2-R7 (10/08/2026) — plancher EXÉCUTIF 11 pt sur les surfaces de
        # lecture 90 s ; les zones HCRIT héritées gardent le plancher
        # technique 8 pt tant que R3 n'a pas réduit leur contenu (mesuré
        # par audit_90s, relèvement global après preuve E2E).
        _floor = 11
        font_size = max(float(_floor), min(float(font_size),
                        float(_auto_font(str(text), w, h,
                                         max_pt=max(_floor, int(font_size)),
                                         min_pt=_floor))))
        tf.margin_left = tf.margin_right = Inches(0.03)
        tf.margin_top = tf.margin_bottom = Inches(0.02)
    if auto_fit:
        from pptx.enum.text import MSO_AUTO_SIZE
        tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    p=tf.paragraphs[0]; p.alignment=align
    # 9.4.65 — neuvième vérification (21/10) : une zone « HNOTE: » est une note écrite par l'outil (pagination
    # « 8 entrées — détail dans le CR », renvoi au compte rendu) ; elle est typée « texte de l'outil » dès sa
    # création (marqueur U+2063), pour n'être jamais signalée « chiffre sans pièce » par le finaliseur.
    _txt865 = str(text)
    if role and str(role).startswith("HNOTE:") and _txt865 and not _txt865.startswith("\u2063"):
        _txt865 = "\u2063" + _txt865
    r=p.add_run(); r.text=_txt865
    r.font.size=Pt(font_size); r.font.bold=bold; r.font.italic=italic
    r.font.color.rgb=color; r.font.name=font_name
    return b

def _auto_font(text: str, w_in: float, h_in: float,
               max_pt: int, min_pt: int = 7) -> int:
    """Return the largest deterministic font size expected to fit.

    The former estimator used a fixed chars-per-inch ratio, independent of the
    selected font size.  H-v2 needs the inverse relationship: larger fonts fit
    fewer characters and fewer lines.  The loop is intentionally conservative
    and language-agnostic; the finalizer independently validates HCRIT boxes.
    """
    import math
    raw = str(text or "")
    width_pt = max(8.0, float(w_in) * 72.0 - 4.0)
    height_pt = max(8.0, float(h_in) * 72.0 - 4.0)
    for pt in range(int(max_pt), int(min_pt) - 1, -1):
        chars_per_line = max(1, int(width_pt / max(1.0, pt * 0.52)))
        needed = sum(max(1, math.ceil(max(1, len(line)) / chars_per_line))
                     for line in (raw.splitlines() or [raw]))
        capacity = height_pt / max(1.0, pt * 1.12)
        if needed <= capacity + 0.20:
            return pt
    return int(min_pt)

def _add_text_auto(slide, text, x, y, w, h,
                   max_pt=14, min_pt=7, bold=False, italic=False,
                   color=None, align=PP_ALIGN.LEFT, font_name="Calibri"):
    """Ajoute du texte avec taille de police automatique."""
    pt = _auto_font(str(text), w, h, max_pt, min_pt)
    return _add_text(slide, text, x, y, w, h,
                     font_size=pt, bold=bold, italic=italic,
                     color=color, align=align, font_name=font_name)


_CONTROL_PLACEHOLDER_RE = re.compile(r"(?i)^\s*(?:proposition chiffrée|quantified proposal|cible chiffrée|valeur retirée|withdrawn value)")


def _is_control_placeholder(text: str) -> bool:
    """Un message de contrôle du produit, pas un point de travail (v62.13.9.4.33)."""
    return bool(_CONTROL_PLACEHOLDER_RE.match(str(text or "")))


def _add_coverage_note(slide, shown: int, total: int, x: float, y: float,
                       w: float, lang: str = "fr"):
    if total <= shown:
        return None
    text = ((f"{shown} ligne{'s' if shown > 1 else ''} sur {total} — détail complet dans le CR")   # v62.13.9.4.33 — « 1 ligne », pas « 1 lignes »
            if lang != "en" else
            f"{shown} of {total} lines — full detail in the Word report")
    return _add_text(slide, text, x, y, w, 0.20, font_size=7.5,
                     italic=True, color=C_MID_GRAY, role="HNOTE:coverage")

def _add_header(slide, icon, title, subtitle):
    # v62.13.9.3 — a provider or legacy payload may already be ellipsized.
    # Critical titles are repaired before they are written to the deck.
    from utils.pptx_title_safety import safe_hcrit_title
    title = safe_hcrit_title(title, _DECK_LANG)
    _add_rect(slide,0,0,10,1.08,C_NAVY)
    _add_rect(slide,0,1.08,10,0.055,C_GOLD)
    _add_rect(slide,0.22,0.2,0.65,0.65,C_GOLD)
    _add_text(slide,icon,0.22,0.2,0.65,0.65,font_size=22,bold=True,color=C_DARK_NAVY,align=PP_ALIGN.CENTER)
    _add_text(slide,title,1.05,0.18,8.6,0.48,font_size=22,bold=True,color=C_WHITE,
              role="HCRIT:slide:title")
    _add_text(slide,subtitle,1.05,0.62,8.6,0.3,font_size=11,color=C_ICE_BLUE,
              role="HINFO:slide:subtitle")

def _pgnum(slide,n,ref=""):
    # v16.5.75.5 — Footer AI Act article 50(4) sur toutes les slides (posé en premier)
    _add_text(slide,
              SL("footer_ai", _DECK_LANG),
              0.3,5.32,7.05,0.22,font_size=7,italic=True,color=C_MID_GRAY,align=PP_ALIGN.LEFT)
    # H2-R6 — renvoi déterministe sur CHAQUE slide. Le numéro de section suit
    # l'ordre du deck ; le CR conserve la profondeur et le deck la surface.
    # v62.13.9.4.31 — quand la rubrique de la synthèse est connue, le pied de
    # slide renvoie à elle (« Synthèse §3 — Décisions proposées ») : le lecteur
    # retrouve le développement, et le numéro vient du document généré.
    # v62.13.9.4.32 (C) — sans rubrique connue, aucun numéro inventé (« CR §13 » n'existait pas).
    _txt = str(ref or "").strip() or ("Détail : voir le compte rendu" if _DECK_LANG != "en" else "Detail: see the report")
    _w = 3.6 if ref else 2.4
    _add_text(slide, _txt,
              9.2 - _w, 5.32, _w, 0.22, font_size=8, italic=True, color=C_MID_GRAY,
              align=PP_ALIGN.RIGHT, role="HNOTE:cr-ref")
    _add_text(slide,f"{n:02d}",9.5,5.3,0.45,0.25,font_size=10,color=C_MID_GRAY,align=PP_ALIGN.RIGHT)

def _t(text, n):
    s=str(text or ""); return s if len(s)<=n else s[:n-1]+"…"


def _format_cover_date(value, lang: str = "fr") -> str:
    """Date de couverture déterministe : date exacte du run/autorité."""
    from datetime import date as _date
    try:
        d = value if isinstance(value, _date) else _date.fromisoformat(str(value)[:10])
    except Exception:
        return str(value or "")
    if (lang or "fr").lower() == "en":
        months = ("January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December")
        return f"{d.day} {months[d.month-1]} {d.year}"
    months = ("janvier", "février", "mars", "avril", "mai", "juin",
              "juillet", "août", "septembre", "octobre", "novembre", "décembre")
    return f"{d.day} {months[d.month-1]} {d.year}"


# ───────────────────────────────────────────────────────────────────────────────
# 4. SLIDES
# ───────────────────────────────────────────────────────────────────────────────

def _slide_cadre_prudence(prs, data):
    """B.1.3 (audit dossier industriel (composants) P2 / dossier anglophone coté) — la prudence dès la slide 2.

    Rendue UNIQUEMENT si data["b13_prudence"] est présent (Grade ≤ C,
    source_quality < 40 ou sections incomplètes). Contenu : badge Grade,
    statut des comptes consolidés, rappel « hypothèses à vérifier »,
    mini-ligne de contexte d'analyse (mode · périmètre · entité), et
    bannière NON DISTRIBUABLE si le completion gate a flaggé.
    Avant B.1.3 : le Grade D n'apparaissait qu'en slide 14/14 alors que
    les slides 3-11 affichaient cibles et montants avec force visuelle
    de plan validé.
    """
    p = data.get("b13_prudence") or {}
    if not p:
        return False
    lang = data.get("lang", "fr")
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb = C_LIGHT_GRAY
    _add_header(slide, "🧭", _h2_title("prudence", data, lang, SL("b13_frame_title", lang)), SL("b13_frame_sub", lang))
    _y = 1.45
    _n_incomplete = int(p.get("n_incomplete") or 0)
    if _n_incomplete:
        _add_rect(slide, 0.3, _y, 9.4, 0.5, C_RED)
        _add_text(slide, SL("b13_nondistrib", lang).format(n=_n_incomplete),
                  0.5, _y + 0.08, 9.0, 0.34, font_size=13, bold=True, color=C_WHITE)
        _y += 0.72
    _g = str(p.get("grade") or "?").upper()
    _add_rect(slide, 0.3, _y, 9.4, 0.62, C_NAVY)
    _add_text(slide, SL("b13_grade_line", lang).format(g=_g),
              0.5, _y + 0.12, 9.0, 0.38, font_size=15, bold=True, color=C_GOLD)
    _y += 0.86
    _lines = []
    _lines.append(SL("b13_fs_ok", lang) if p.get("has_fs") else SL("b13_no_fs", lang))
    _lines.append(SL("b13_hypo", lang))
    _ctx = p.get("ctx") or {}
    if _ctx:
        # B.1.3.12 (audit #6) — les VALEURS du contexte restaient en FR
        # dans la reading frame EN (« mode groupe · perimeter consolide »).
        _m12 = str(_ctx.get("mode", "?"))
        _p12 = str(_ctx.get("target_perimeter_level", "?"))
        if lang == "en":
            _map12 = {"groupe": "group", "consolide": "consolidated",
                      "consolidé": "consolidated", "social": "standalone",
                      "individuel": "standalone"}
            _m12 = _map12.get(_m12.strip().lower(), _m12)
            _p12 = _map12.get(_p12.strip().lower(), _p12)
        else:
            # B.1.3.16 — le FR aussi localise les valeurs internes
            # non accentuées (« consolide » → « consolidé »).
            _map12_fr = {"consolide": "consolidé"}
            _m12 = _map12_fr.get(_m12.strip().lower(), _m12)
            _p12 = _map12_fr.get(_p12.strip().lower(), _p12)
        _lines.append(SL("b13_ctx_line", lang).format(
            m=_m12, p=_p12,
            e=str(_ctx.get("target_entity", "?"))))
    for _ln in _lines:
        _add_rect(slide, 0.3, _y, 9.4, 0.5, C_WHITE)
        _add_rect(slide, 0.3, _y, 0.07, 0.5, C_GOLD)
        _add_text(slide, _ln, 0.55, _y + 0.07, 9.0, 0.36,
                  font_size=_auto_font(_ln, 9.0, 0.36, max_pt=12, min_pt=8),
                  color=C_TEXT_DARK, role="HCRIT:reading-frame:line")
        _y += 0.62
    _pgnum(slide, len(prs.slides))
    return True



# ── H2 (spec gelée 10/08/2026) — règles de lecture exécutive ────────────────
from utils.exec_reading import (kpi_selector as _h2_kpi_selector,
                                build_kpi_candidates as _h2_build_kpis,
                                safe_executive_kpi_value as _h2_safe_kpi_value,
                                compact_exec_text as _h2_compact,
                                assertion_title as _h2_assertion,
                                sort_actions as _h2_sort_actions,
                                sort_risques as _h2_sort_risques,
                                derive_key_message as _h2_key_message,
                                select_deadline as _h2_select_deadline,
                                select_top_risk as _h2_select_top_risk,
                                is_open_action as _h2_is_open_action)


def _h2_deadline_info(data):
    """Échéance H2 relative à la date d'autorité du run.

    La première date future est une prochaine échéance. Si toutes les dates
    sont passées, la plus récente est signalée comme EN RETARD ; elle n'est
    jamais présentée comme « prochaine ».
    """
    items = []
    for step in (data.get("next_steps") or []):
        if isinstance(step, dict):
            items.append(step)
    for phase in (data.get("roadmap") or []):
        if isinstance(phase, dict):
            items.append(phase)
    ref = str(data.get("_h2_reference_date") or "")
    return _h2_select_deadline(items, ref)


def _h2_cover_message(data):
    """Message de couverture : orientation/synthèse avant simple situation."""
    # Finition v3 (11/08) — l'extraction peut livrer une conclusion en dict
    # structuré, en CHAÎNE libre, ou une forme inattendue : la couverture ne
    # crashe JAMAIS pour une forme de donnée (doctrine fail-open).
    concl = data.get("conclusion")
    candidates = []
    if isinstance(concl, dict):
        candidates.append(concl.get("headline"))
    elif isinstance(concl, str):
        candidates.append(concl)
    candidates += [
        data.get("decision_finale"),
        data.get("orientation"),
        (data.get("contexte_corporate") or {}).get("situation"),
        data.get("sous_titre"),
    ]
    generic = {"conclusion", "synthèse", "synthese", "executive summary",
               "compte-rendu codir ia", "codir ia"}
    for value in candidates:
        try:
            msg = _h2_key_message(str(value or ""))
        except Exception:
            msg = ""
        if msg and msg.strip().lower() not in generic:
            return msg
    return ""



def _h2_exec(text, lang="fr", max_words=12, max_chars=None,
             drop_trailing_deadline=False):
    """Texte exécutable R4, borné par mots ET largeur utile.

    ``max_chars`` est un budget de secours propre aux boîtes étroites. La
    coupe reste toujours tracée vers le CR ; aucune ellipse silencieuse.
    """
    return _h2_compact(
        str(text or ""), max_words=max_words, lang=lang,
        max_chars=max_chars,
        drop_trailing_deadline=drop_trailing_deadline,
    )[0]


_H2_DANGLING_BEFORE_REF_RE = re.compile(
    r"\s+(?:et|ou|and|or|avec|with|de|du|des|d['’]|à|au|aux|pour|for|en|in|sur|on|dans|par|by|puis|then|"
    r"un|une|a|an|the|le|la|les|l['’]|que|qu['’]|qui|dont)\s*(—\s*CR)\s*$", re.I)


_CR_REF_MAP = {
    "marche": ("marketing", "marché", "market", "commerciale", "commercial"),
    "swot": ("stratégie", "strategy", "swot"),
}
_SYNTH_REF_MAP = (
    ("decision", ("décisions proposées", "decisions", "décision")),
    ("swot", ("risques et points de vigilance", "risques")),
    ("marche", ("options examinées", "synthèse & décisions", "direction générale")),
    ("commercial", ("plan d'actions", "décisions proposées")),
    ("arbitration", ("arbitrages ouverts", "arbitrages")),
    ("roadmap", ("plan d'actions", "plan d’actions")),
    ("next", ("plan d'actions", "plan d’actions")),
    ("question", ("questions ouvertes", "hypothèses de travail à discuter")),
    ("conclusion", ("conclusion", "synthèse & décisions")),
)


def _synth_ref(kind: str, data, lang: str = "fr") -> str:
    """v62.13.9.4.31 — renvoi de slide vers la rubrique de la synthèse Word.
    Rien n'est affiché si la synthèse n'a pas été générée (aucun numéro deviné)."""
    idx = list((data or {}).get("synthesis_index") or [])
    if not idx:
        return ""
    wanted = next((v for k, v in _SYNTH_REF_MAP if k == kind), ())
    # v62.13.9.4.33 (lot 1) — le marché et le SWOT ne sont pas des rubriques de la
    # synthèse : leur détail est dans le CR (Stratégie, Marketing). Le renvoi
    # vise d'abord la rubrique du CR qui porte réellement la matière, puis la
    # synthèse ; jamais un rang de slide (contre-audit du 12/09/2026 :
    # « marché → Options examinées » et « SWOT → Risques » ne donnaient pas
    # accès au détail pertinent).
    cr_idx = list((data or {}).get("report_index") or [])
    cr_wanted = _CR_REF_MAP.get(kind, ())
    if cr_idx and cr_wanted:
        for target in cr_wanted:
            for i, name in enumerate(cr_idx, start=1):
                if target in str(name or "").lower():
                    label = "CR §" if not str(lang).startswith("en") else "Report §"
                    return f"{label}{i} — {name}"
    for target in wanted:
        for i, name in enumerate(idx, start=1):
            if target in str(name or "").lower():
                label = "Synthèse §" if not str(lang).startswith("en") else "Synthesis §"
                return f"{label}{i} — {name}"
    return ""


def _question_gist(q: str) -> str:
    """v62.13.9.4.29 — une question garde son alternative (« … ou faut-il élargir ? ») :
    parenthèses et incises « avec … » retirées avant la coupe du titre."""
    s = re.sub(r"\s*\([^()]{0,80}\)", "", str(q or ""))
    s = re.sub(r",?\s+avec\s+[^,?]{3,60}(?=[,?]|\s+ou\b|$)", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    # trop long pour un titre : chaque branche de l'alternative est raccourcie à sa
    # tête (9 / 7 mots, sans connecteur orphelin), le « ou » et le « ? » restent
    m = re.search(r"\s+(?:ou|or)\s+", s)
    if m and len(s.split()) > 16:
        _dang = re.compile(r"\s+(?:et|ou|and|or|de|du|des|d['’]|à|au|aux|pour|en|sur|dans|par|les?|la|un|une|the|to|of)$", re.I)
        left = " ".join(s[:m.start()].split()[:9]); right = " ".join(s[m.end():].rstrip(" ?").split()[:7])
        while _dang.search(left): left = _dang.sub("", left)
        while _dang.search(right): right = _dang.sub("", right)
        s = f"{left}, {m.group(0).strip()} {right} ?"
    return s


def _h2_title(kind, data, lang, default):
    """v62.13.9.4.25 — contre-audit v24 (§3) : un titre-message coupé avant son
    renvoi ne finit pas sur un connecteur (« … via un CRM léger et — CR »)."""
    title = _h2_title_raw(kind, data, lang, default)
    # v62.13.9.4.29 — audit du dossier industriel v28 (slides 9 et 12) : un titre-message n'est
    # jamais un message de contrôle (« Proposition chiffrée — voir l'annexe »,
    # « Cible chiffrée écartée ») : le titre par défaut de la slide le remplace.
    try:
        from utils.analysis_objects import _is_product_marker as _ipm
        if _ipm(str(title or "")):
            title = default
    except Exception:
        pass
    try:
        title = _H2_DANGLING_BEFORE_REF_RE.sub(r" \1", str(title or ""))
        # v62.13.9.4.26 — une parenthèse dans un titre-message est un détail du
        # corps (« (≈50 cibles) »), jamais le message ; elle reste dans le CR.
        title = re.sub(r"\s*\([^()]{0,80}\)", "", title)
        return re.sub(r"\s+", " ", title).strip()
    except Exception:
        return title


def _h2_title_raw(kind, data, lang, default):
    """Titre-assertion R2, dérivé d'une vérité déjà présente dans le dossier."""
    cc = data.get("contexte_corporate") or {}
    swot = data.get("swot") or {}
    axes = data.get("axes") or []
    next_steps = _h2_sort_actions([x for x in (data.get("next_steps") or [])
                                   if isinstance(x, dict) and _h2_is_open_action(x)])
    if kind == "prudence":
        p = data.get("b13_prudence") or {}
        grade = str(p.get("grade") or "?").upper()
        return (f"CADRE DE LECTURE — Usage limité : Grade {grade}, preuves à compléter" if lang != "en"
                else f"READING FRAME — Limited use: Grade {grade}, evidence to complete")
    if kind == "essentiel":
        msg = _h2_cover_message(data)
        return _h2_assertion("Décision" if lang != "en" else "Decision", msg, lang) or default
    if kind == "context":
        msg = cc.get("situation") or _h2_select_top_risk(cc.get("risques_top") or [], swot.get("risques") or [])
        return _h2_assertion("Situation" if lang != "en" else "Situation", msg, lang) or default
    if kind == "swot":
        risks = _h2_select_top_risk(cc.get("risques_top") or [], swot.get("risques") or [])
        return _h2_assertion("Risque clé" if lang != "en" else "Key risk", risks, lang) or default
    if kind == "axes":
        first = next((str(a.get("titre") or "").strip() for a in axes if isinstance(a, dict) and str(a.get("titre") or "").strip()), "")
        return _h2_assertion("Priorité" if lang != "en" else "Priority", first, lang) or default
    if kind == "supply":
        sc = data.get("supply_chain") or {}
        msg = sc.get("headline") or sc.get("global_status") or sc.get("reason")
        token = str(msg or "").strip().lower().replace("_", " ")
        if token in {"not covered", "structured invalid", ""}:
            msg = ("aucune analyse structurée dans ce run" if lang != "en"
                   else "no structured analysis in this run")
        elif token == "light industrial":
            msg = ("signaux opérationnels disponibles dans le CR" if lang != "en"
                   else "operational signals available in the report")
        return _h2_assertion("Supply chain", msg, lang) or default
    if kind == "commercial":
        comm = data.get("commercial") or {}
        _candidates = (comm.get("opportunites") or comm.get("actions") or [])
        msg = next((
            str(x).strip() for x in _candidates
            if str(x).strip()
            and not re.search(r"quantified proposals? withheld|propositions? chiffr[ée]es? [ée]cart[ée]es?", str(x), re.I)
        ), "")
        return _h2_assertion("Commercial", msg, lang) or default
    if kind == "risks":
        msg = next((str(x).strip() for x in (cc.get("arbitrages") or []) if str(x).strip()), "")
        return _h2_assertion("Arbitrage" if lang != "en" else "Decision", msg, lang) or default
    if kind == "next":
        msg = str((next_steps[0].get("action") if next_steps else "") or "")
        return _h2_assertion("Prochaine action" if lang != "en" else "Next action", msg, lang) or default
    return default


def _h2_sorted_structured_risks(data):
    cc = data.get("contexte_corporate") or {}
    risks = [r for r in (cc.get("risques_top") or []) if isinstance(r, dict) and str(r.get("label") or "").strip()]
    return _h2_sort_risques(risks)

def _slide_essentiel(prs, data):
    """H2-R1 (spec gelée 10/08/2026) — « L'essentiel en 90 secondes ».
    Trois chiffres (R5 dégradé au schéma réel : trio prioritaire puis
    complément du dossier), risque n°1, arbitrage n°1, prochaine échéance.
    Toutes les zones porteuses sont HCRIT (plancher exécutif 11 pt, R7) ;
    le renvoi vers le CR remplace toute coupe (R3/R6)."""
    lang = data.get("lang", "fr")
    cc = data.get("contexte_corporate") or {}
    swot = data.get("swot") or {}
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_DARK_NAVY
    _cands = _h2_build_kpis(cc, lang)
    # Normalisation visuelle de l'effectif, si utilisé comme repli.
    for _k in _cands:
        if str(_k.get("nom", "")).lower() in {"effectif", "headcount"}:
            _k["val"] = _format_headcount_card(_k.get("val", ""), lang)
    _selected_kpis = _h2_kpi_selector(_cands, 3)
    _n_kpi = min(3, len(_selected_kpis))
    _fr_n = {1: "Un chiffre clé", 2: "Deux chiffres clés", 3: "Trois chiffres clés"}.get(_n_kpi, f"{_n_kpi} chiffres clés")
    _en_n = {1: "One key figure", 2: "Two key figures", 3: "Three key figures"}.get(_n_kpi, f"{_n_kpi} key figures")
    # v62.13.9.4.25 — contre-audit v24 : « 0 chiffres clés » n'est pas un
    # sous-titre ; sans chiffre clé, le sous-titre ne compte que ce qui existe.
    _sub = ((f"{_fr_n} · un risque · un arbitrage · une échéance" if _n_kpi else
             "Un risque · un arbitrage · une échéance")
            if lang != "en" else
            (f"{_en_n} · one risk · one decision · one deadline" if _n_kpi else
             "One risk · one decision · one deadline"))
    _add_header(slide, "⏱",
                _h2_title("essentiel", data, lang,
                          "L'ESSENTIEL EN 90 SECONDES" if lang != "en"
                          else "THE ESSENTIALS IN 90 SECONDS"), _sub)
    # (la « situation » est une phrase : elle vit au message-clé du cover,
    #  pas dans une carte-chiffre ; le 3e slot attend EBITDA/cash du schéma)
    for i, k in enumerate(_selected_kpis):
        cx = 0.28 + i * 3.22
        _add_rect(slide, cx, 1.28, 3.04, 1.16, C_WHITE)
        _add_rect(slide, cx, 1.28, 3.04, 0.06, C_GOLD)
        pt_v = _auto_font(str(k["val"]), 2.8, 0.52, max_pt=17, min_pt=11)
        _add_text(slide, str(k["val"]), cx + 0.12, 1.42, 2.8, 0.52,
                  font_size=pt_v, bold=True, color=C_DARK_NAVY,
                  role=f"HCRIT:essentiel:kpi:{i}")
        _add_text(slide, str(k["nom"]), cx + 0.12, 1.94, 2.8, 0.26,
                  font_size=11, bold=True, color=C_NAVY,
                  role=f"HCRIT:essentiel:kpi-label:{i}")
        if str(k.get("sub", "")).strip():
            _add_text(slide, str(k["sub"]), cx + 0.12, 2.18, 2.8, 0.22,
                      font_size=11, color=C_TEAL,
                      role=f"HCRIT:essentiel:kpi-sub:{i}")

    risk1 = _h2_select_top_risk(cc.get("risques_top") or [],
                                  swot.get("risques") or [])
    _add_rect(slide, 0.28, 2.62, 9.44, 0.94, _rgb(0x1A, 0x23, 0x50))
    _add_rect(slide, 0.28, 2.62, 0.07, 0.94, C_RED)
    _add_text(slide, "RISQUE N°1" if lang != "en" else "RISK #1",
              0.46, 2.68, 2.2, 0.30, font_size=11, bold=True, color=C_RED,
              role="HCRIT:essentiel:risque-label")
    if risk1:
        risk1 = _h2_exec(risk1, lang)
        pt_r = _auto_font(risk1, 8.9, 0.52, max_pt=13, min_pt=11)
        _add_text(slide, risk1, 0.46, 2.98, 8.9, 0.52,
                  font_size=pt_r, color=C_WHITE, role="HCRIT:essentiel:risque")

    arb1 = next((str(a).strip() for a in (cc.get("arbitrages") or [])
                 if str(a).strip()), "")
    _add_rect(slide, 0.28, 3.66, 9.44, 0.94, _rgb(0x1A, 0x23, 0x50))
    _add_rect(slide, 0.28, 3.66, 0.07, 0.94, C_GOLD)
    _add_text(slide, "ARBITRAGE N°1" if lang != "en" else "DECISION #1",
              0.46, 3.72, 2.6, 0.30, font_size=11, bold=True, color=C_GOLD,
              role="HCRIT:essentiel:arbitrage-label")
    if arb1:
        arb1 = _h2_exec(arb1, lang)
        pt_a = _auto_font(arb1, 8.9, 0.52, max_pt=13, min_pt=11)
        _add_text(slide, arb1, 0.46, 4.02, 8.9, 0.52,
                  font_size=pt_a, color=C_WHITE,
                  role="HCRIT:essentiel:arbitrage")

    _di = _h2_deadline_info(data)
    if _di:
        _y, _m, _d = _di["date_key"]
        ech = f"{_d:02d}/{_m:02d}/{_y}"
        overdue = _di.get("status") == "overdue"
        if lang == "en":
            _lbl = "OVERDUE DEADLINE: " if overdue else "NEXT DEADLINE: "
        else:
            _lbl = "ÉCHÉANCE EN RETARD : " if overdue else "PROCHAINE ÉCHÉANCE : "
        _add_text(slide, _lbl + ech, 0.28, 4.78, 5.4, 0.34,
                  font_size=12, bold=True, color=C_RED if overdue else C_GOLD,
                  role="HCRIT:essentiel:echeance")
    _pgnum(slide, len(prs.slides), _synth_ref("decision", data, lang if "lang" in dir() else data.get("lang", "fr")))


def _slide_titre(prs, data):
    """
    Slide 1 — Titre executive avec composition géométrique intégrée.
    Colonne gauche : contenu textuel.
    Colonne droite : cercles concentriques intégrés (entièrement dans la slide).
    """
    lang = data.get("lang", "fr")  # v16.5.38 bilingual
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_DARK_NAVY

    # ── Barre gauche accent ──────────────────────────────────────────────────
    _add_rect(slide, 0, 0, 0.12, 5.625, C_GOLD)

    # ── Composition cercles droite — entièrement dans les 10" de la slide ─────
    # Slide = 10" x 5.625" → zone droite disponible : x de 6.3 à 9.9 = 3.6" max
    cx   = 6.30   # bord gauche du cercle extérieur
    cy   = 0.30   # bord haut
    cr   = 5.00   # diamètre — cx+cr = 11.3, déborde à droite (voulu : demi-cercle)
    # On veut que le contenu visible soit centré verticalement → cy=(5.625-cr)/2
    cy   = (5.625 - cr) / 2   # = 0.3125

    # Cercle extérieur : anneau fin, partiellement visible (demi-cercle à droite)
    s_outer = slide.shapes.add_shape(9, Inches(cx), Inches(cy),
                                     Inches(cr), Inches(cr))
    s_outer.fill.background()
    s_outer.line.color.rgb = _rgb(0x2A, 0x35, 0x7A)
    s_outer.line.width = Pt(1.5)

    # Cercle intermédiaire — entièrement visible
    off2 = 0.6
    cx2, cy2 = cx + off2, cy + off2
    cr2 = cr - 2 * off2
    s_mid = slide.shapes.add_shape(9, Inches(cx2), Inches(cy2),
                                   Inches(cr2), Inches(cr2))
    s_mid.fill.solid()
    s_mid.fill.fore_color.rgb = _rgb(0x1A, 0x22, 0x5E)
    s_mid.line.color.rgb = _rgb(0x2E, 0x3A, 0x8A)
    s_mid.line.width = Pt(0.75)

    # Cercle intérieur gold — entièrement visible, cx3+cr3 ≤ 10"
    off3 = 1.3
    cx3, cy3 = cx + off3, cy + off3
    cr3 = cr - 2 * off3   # = 2.4"  → cx3+cr3 = 6.3+1.3+2.4 = 10.0 ✅
    s_inner = slide.shapes.add_shape(9, Inches(cx3), Inches(cy3),
                                     Inches(cr3), Inches(cr3))
    s_inner.fill.solid()
    s_inner.fill.fore_color.rgb = C_GOLD
    s_inner.line.fill.background()

    # Initiales au centre du cercle gold — v16.5.76 item 1 :
    # Avant : "".join(w[0] for w in entreprise.split()[:2]) → "AG" pour dossier réseau de soins Groupe, "SH" pour dossier de conseil.
    # Après : nom court lisible (1er mot significatif, jusqu'à 10 caractères, taille adaptative).
    # Fallback "HG" si pas de nom → "dossier de conseil" (mode démo/test).
    _ent_raw = data.get("entreprise", "").strip()
    # Mots à ignorer (forme juridique, articles, préfixes)
    _stopwords = {"sa", "sas", "sasu", "sarl", "eurl", "snc", "scop", "sci",
                  "le", "la", "les", "l'", "du", "de", "des", "the", "ltd", "inc",
                  "corp", "group", "groupe", "company", "co", "&", "et", "and"}
    _words = [w for w in _ent_raw.replace("!", "").replace(".", "").split()
              if w and w.lower() not in _stopwords and w.lower().rstrip(",") not in _stopwords]
    if _words:
        # 1er mot significatif, tronqué à 10 caractères max pour rester lisible
        ent_abbr = _words[0][:10]
    else:
        # Fallback : initiales des 2 premiers mots (comportement v75.5)
        ent_abbr = "".join(w[0] for w in _ent_raw.split()[:2]).upper() if _ent_raw else "HG"
    # Taille de police adaptative : plus le mot est long, plus la police rétrécit
    _abbr_pt = 40 if len(ent_abbr) <= 3 else (32 if len(ent_abbr) <= 6 else 24)
    _add_text(slide, ent_abbr,
              cx3 + 0.1, cy3 + 0.1, cr3 - 0.2, cr3 - 0.2,
              font_size=_abbr_pt, bold=True, color=C_DARK_NAVY,
              align=PP_ALIGN.CENTER, font_name="Calibri")

    # ── Contenu textuel gauche ───────────────────────────────────────────────
    # Tag catégorie — dynamique selon disponibilité du contexte entreprise
    ent_name = data.get("entreprise", "")
    tag_label = (f"CODIR IA · {ent_name[:28]}" if ent_name and ent_name.lower() not in (SL("not_specified",lang).lower(), "")
                 else "COMPTE-RENDU CODIR IA")
    _add_rect(slide, 0.28, 0.55, 3.8, 0.38, C_GOLD)
    _add_text(slide, tag_label, 0.28, 0.55, 3.8, 0.38,
              font_size=10, bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)

    # Titre principal
    titre = str(data.get("titre", "Compte-rendu CoDIR IA") or "").strip()
    pt_titre = _auto_font(titre, 6.0, 1.18, max_pt=36, min_pt=18)
    _add_text(slide, titre, 0.28, 1.02, 6.0, 1.18,
              font_size=pt_titre, bold=True, color=C_WHITE, font_name="Calibri",
              role="HCRIT:cover:title")

    # Sous-titre
    sous = str(data.get("sous_titre", "") or "").strip()
    if sous:
        pt_sous = _auto_font(sous, 6.0, 0.56, max_pt=17, min_pt=11)
        _add_text(slide, sous, 0.28, 2.22, 6.0, 0.56,
                  font_size=pt_sous, bold=True, color=C_GOLD, font_name="Calibri",
                  role="HCRIT:cover:subtitle")

    # H2-R1 — message principal du dossier : phrase entière si elle tient ;
    # sinon compact R3 (≤ 12 mots, coupe SIGNALÉE « — CR ») — hotfix terrain
    # 11/08 : une phrase réelle de dossier dépassait la capacité de la boîte
    # (2 lignes au plancher 11 pt) et BLOQUAIT la livraison entière.
    _km = _h2_cover_message(data)
    if _km:
        _km, _ = _h2_compact(_km, 12, data.get("lang", "fr"))
    if _km and _km != sous and _km != titre:
        pt_km = _auto_font(_km, 6.2, 0.46, max_pt=13, min_pt=11)
        _add_text(slide, _km, 0.28, 2.70, 6.2, 0.46,
                  font_size=pt_km, italic=True, color=C_ICE_BLUE,
                  role="HCRIT:cover:key-message")

    # Ligne séparatrice — sous le message, jamais au travers des badges.
    _add_rect(slide, 0.28, 3.22, 5.0, 0.04, _rgb(0x3A, 0x46, 0x8A))

    # Entreprise
    ent = _t(data.get("entreprise", ""), 40)
    pt_ent = _auto_font(ent, 5.5, 0.38, max_pt=19, min_pt=13)
    _add_text(slide, ent, 0.28, 3.34, 5.5, 0.38,
              font_size=pt_ent, bold=True, color=C_ICE_BLUE)

    # Tagline — v62.13.9.4.34 (lot 1) : une analyse rétrospective se dit sur la
    # couverture. Contre-audit du 14/09/2026 (run réel dossier réseau de soins) : rien n'indiquait
    # que le dossier avait été lu depuis une autre date que celle du jour.
    _retro34 = str(data.get("retrospective_note") or "").strip()
    _add_text(slide, (_retro34 or SL("title_subtitle", lang)),
              0.28, 3.78, 6.1, 0.28, font_size=10.5,
              color=(C_GOLD if _retro34 else C_MID_GRAY))

    # 3 badges info en bas
    badges = [
        (str(data.get("analysis_date_label") or data.get("date", "2026")), C_NAVY),
        ("CoDIR IA", C_NAVY),
        (SL("augmented_board", lang), C_NAVY),
    ]
    for i, (label, color) in enumerate(badges):
        bx = 0.28 + i * 2.02
        _add_rect(slide, bx, 4.18, 1.88, 0.44, color)
        _add_rect(slide, bx, 4.18, 0.06, 0.44, C_GOLD)
        pt_b = _auto_font(label, 1.78, 0.44, max_pt=11, min_pt=8)
        _add_text(slide, label, bx + 0.1, 4.18, 1.78, 0.44,
                  font_size=pt_b, bold=True, color=C_ICE_BLUE,
                  align=PP_ALIGN.CENTER, role=f"HINFO:cover:badge:{i}")

    # Pied de page + renvoi R6 de la couverture.
    _add_text(slide, ("Détail : CR §1" if lang != "en" else "Detail: report §1"),
              0.28, 5.25, 2.4, 0.28, font_size=8, italic=True,
              color=_rgb(0x44, 0x50, 0x7A), role="HNOTE:cr-ref")
    # 9.4.65 — huitième vérification du 21/10 : en français, le détecteur des chiffres non étayés prenait
    # « Généré par CoDIR IA — v17.0 (build 9.4.65) » pour un chiffre de pilotage et l'annotait « chiffre sans
    # pièce » sur la couverture. Doctrine : un texte de l'outil est typé à la construction et jamais signalé.
    try:
        from utils.quantity_ledger import mark_tool_text as _mtt865
        _gen_by_865 = _mtt865(SL("generated_by", lang))
    except Exception:
        _gen_by_865 = "\u2063" + SL("generated_by", lang)
    _add_text(slide, _gen_by_865, 2.8, 5.25, 6.88, 0.28,
              font_size=9, italic=True, color=_rgb(0x44, 0x50, 0x7A),
              align=PP_ALIGN.RIGHT)


def _slide_marche(prs, data):
    lang = data.get("lang", "fr")  # v16.5.59
    """Slide SOLO uniquement — JAMAIS appelée en deck CORPORATE.
    Affiche taille marché, TJM moyen, drivers, segments — spécifique management de transition.
    Pour un deck CORPORATE, c'est _slide_contexte_corporate qui est appelée.
    """
    d=data.get("marche",{})
    slide=prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb=C_LIGHT_GRAY
    _add_header(slide,"📈",SL("overview_title",lang),
                SL("codir_synth", lang) + " · "+str(data.get("date","2026")))
    kpis=[(d.get("taille","—"),SL("market_size_label",lang),d.get("croissance","")),
          (d.get("missions","—"),SL("key_points_label",lang),SL("scope_label",lang)),
          (d.get("duree_moy","—"),SL("avg_duration_label",lang),SL("per_mission_label",lang)),
          (d.get("tjm_moy","—"),"TJM moyen",d.get("tjm_detail",""))]
    # v62.13.9.4.32 (C) — PROJETER SELON LE DOSSIER : une carte sans donnée
    # n'est pas rendue (contre-audits du 11/09/2026 : « TJM moyen » et « Durée
    # moyenne par mission » vides dans une biscuiterie et un industriel — un
    # gabarit de conseil projeté sur un autre métier). Les cartes restantes
    # gardent leur place ; aucune valeur n'est inventée pour remplir un cadre.
    kpis=[k for k in kpis if str(k[0] or "").strip() not in ("", "—", "-", "–", "N/A", "n/a", "NC", "nc")]
    cw,ch,cy,gap,sx=2.1,1.42,1.32,0.32,0.3
    for i,(val,label,sub) in enumerate(kpis):
        cx=sx+i*(cw+gap)
        _add_rect(slide,cx,cy,cw,ch,C_WHITE); _add_rect(slide,cx,cy,cw,0.07,C_GOLD)
        # Taille auto pour valeur KPI
        pt_v = _auto_font(str(val), cw-0.1, 0.52, max_pt=22, min_pt=12)
        _add_text(slide,_t(val,16),cx,cy+0.22,cw,0.52,font_size=pt_v,bold=True,color=C_NAVY,align=PP_ALIGN.CENTER)
        _add_text(slide,label,cx,cy+0.74,cw,0.32,font_size=10,bold=True,color=C_TEXT_DARK,align=PP_ALIGN.CENTER)
        _add_text(slide,sub,cx,cy+1.06,cw,0.28,font_size=9,italic=True,color=C_MID_GRAY,align=PP_ALIGN.CENTER)
    _add_rect(slide,0.3,2.9,4.5,2.48,C_WHITE); _add_rect(slide,0.3,2.9,0.07,2.48,C_TEAL)
    _en_mk38 = str(data.get("lang", "fr") if isinstance(data, dict) else "fr").lower().startswith("en")   # v62.13.9.4.38 — libellés de gabarit EN
    _add_text(slide,"GROWTH DRIVERS" if _en_mk38 else "DRIVERS DE CROISSANCE",0.5,2.97,4.1,0.35,font_size=11,bold=True,color=C_NAVY)
    _part31 = str(data.get("_marche_part") or "")
    for i,drv in enumerate((d.get("drivers",[]) if _part31 != "demande" else [])[:4]):
        dy=3.5+i*0.44
        _add_rect(slide,0.5,dy,0.74,0.3,C_NAVY)
        _add_text(slide,drv.get("pct",""),0.5,dy,0.74,0.3,font_size=10,bold=True,color=C_GOLD,align=PP_ALIGN.CENTER)
        lbl=_t(drv.get("label",""),40)
        pt_lbl=_auto_font(lbl,3.3,0.3,max_pt=10,min_pt=8)
        _add_text(slide,lbl,1.34,dy,3.3,0.3,font_size=pt_lbl,color=C_TEXT_DARK)
    _add_rect(slide,5.05,2.9,4.65,2.48,C_WHITE); _add_rect(slide,5.05,2.9,0.07,2.48,C_GOLD)
    _add_text(slide,"CUSTOMER SEGMENTATION" if _en_mk38 else "SEGMENTATION CLIENTS",5.25,2.97,4.3,0.35,font_size=11,bold=True,color=C_NAVY)
    for i,seg in enumerate((d.get("segments",[]) if _part31 != "offre" else [])[:4]):
        sy=3.47+i*0.47
        nom=_t(seg.get("nom",""),26)
        pt_nom=_auto_font(nom,2.0,0.32,max_pt=10,min_pt=8)
        _add_text(slide,nom,5.25,sy,2.0,0.32,font_size=pt_nom,color=C_TEXT_DARK)
        _add_rect(slide,7.35,sy+0.04,0.56,0.26,C_NAVY)
        _add_text(slide,seg.get("pct",""),7.35,sy+0.04,0.56,0.26,font_size=10,bold=True,color=C_GOLD,align=PP_ALIGN.CENTER)
        st=min(int(seg.get("etoiles",3)),5)
        _add_text(slide,"●"*st+"○"*(5-st),8.0,sy,1.6,0.32,font_size=10,color=C_GOLD)
    _pgnum(slide, len(prs.slides), _synth_ref("marche", data, lang if "lang" in dir() else data.get("lang", "fr")))


def _slide_swot(prs, data):
    lang = data.get("lang", "fr")  # v16.5.59
    swot=data.get("swot",{})
    slide=prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb=C_LIGHT_GRAY
    _add_header(slide,"🎯",_h2_title("swot", data, lang, SL("swot_title",lang)),SL("swot_subtitle",lang))
    _structured_risk_labels = [str(r.get("label") or "") for r in _h2_sorted_structured_risks(data)]
    quads=[(SL("swot_strengths",lang).upper(),C_GREEN,swot.get("forces",[]),0.25,1.25),
           (SL("swot_weaknesses",lang).upper(),C_RED,swot.get("faiblesses",[]),5.18,1.25),
           (SL("swot_opportunities", lang).upper(),C_TEAL,swot.get("opportunites",[]),0.25,3.42),
           # v62.13.9.4.32 (C) — les MENACES externes construites pour la matrice
           # priment ; les risques structurés (points de vigilance, tâches de
           # contrôle) ne les remplacent qu'à défaut (contre-audits du 11/09/2026 :
           # cinq menaces préparées, trois points de vigilance rendus à la place).
           (SL("swot_risks_quad",lang).upper(),C_GOLD,swot.get("risques",[]) or _structured_risk_labels,5.18,3.42)]
    # v62.13.9.4.31 — demande de Robin (09/09) : trois à cinq entrées courtes par
    # quadrant (3 à 5 mots), le développement restant dans le Word que le renvoi
    # désigne. La matrice porte toujours une note de couverture : le lecteur sait
    # combien d'entrées existent et où lire le détail.
    _swot_shown31 = _swot_total31 = 0
    for title,color,items,qx,qy in quads:
        _add_rect(slide,qx,qy,4.62,2.06,C_WHITE)
        _add_rect(slide,qx,qy,4.62,0.44,color)
        tc=C_DARK_NAVY if color==C_GOLD else C_WHITE
        _add_text(slide,title,qx,qy,4.62,0.44,font_size=12,bold=True,color=tc,align=PP_ALIGN.CENTER)
        _items = [x for x in items if str(x).strip()]
        _n31 = min(len(_items), 5)
        _step31 = 0.43 if _n31 <= 3 else (0.36 if _n31 == 4 else 0.30)
        # v62.13.9.4.33 (lot 1) — le dernier point ne descend jamais sous le
        # pied de page (contre-audit du 12/09/2026 : cinquième point du quadrant
        # bas près du pied) : on réduit le nombre affiché, la note de
        # couverture dit le reste.
        _avail33 = 5.12 - (qy + 0.55)                       # hauteur disponible au-dessus du pied de page
        while _n31 > 2:
            _fit = min(_step31, (_avail33 - 0.24) / max(_n31 - 1, 1))
            if _fit >= 0.26:
                _step31 = _fit
                break
            _n31 -= 1
            _step31 = 0.43 if _n31 <= 3 else (0.36 if _n31 == 4 else 0.30)
        for j,item in enumerate(_items[:_n31]):
            clean = _h2_exec(_clean_bullet_full(str(item)) or str(item).strip(), lang)
            iy=qy+0.55+j*_step31
            _add_rect(slide,qx+0.12,iy+0.09,0.14,0.14,color)
            _h31 = min(0.40, _step31 - 0.03, max(0.20, 5.12 - iy))   # jamais sous le pied de page
            pt_item=_auto_font(clean, 4.14, _h31, max_pt=10, min_pt=8)
            _add_text(slide,clean,qx+0.36,iy,4.14,_h31,font_size=pt_item,
                      color=C_TEXT_DARK, role=f"HCRIT:swot:item:{j}")
        _add_coverage_note(slide, min(_n31, len(_items)), len(_items),
                           qx+0.36, qy+0.55+_n31*_step31+0.04, 4.1, lang)
        _swot_shown31 += min(_n31, len(_items)); _swot_total31 += len(_items)
    _ref31 = _synth_ref("swot", data, lang)
    _add_text(slide,
              ((f"{_swot_shown31} entrées affichées sur {_swot_total31}" if _swot_total31 > _swot_shown31
                else f"{_swot_shown31} entrées") + (f" — détail : {_ref31}" if _ref31 else " — détail dans le CR")
               if lang != "en" else
               (f"{_swot_shown31} of {_swot_total31} entries" if _swot_total31 > _swot_shown31
                else f"{_swot_shown31} entries") + (f" — detail: {_ref31}" if _ref31 else " — detail in the report")),
              0.25, 5.10, 6.5, 0.20, font_size=7.5, italic=True, color=C_MID_GRAY, role="HNOTE:coverage")
    _pgnum(slide, len(prs.slides), _ref31)


def _slide_axes(prs, data):
    lang = data.get("lang", "fr")  # v16.5.59
    axes=data.get("axes",[])
    slide=prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb=C_DARK_NAVY
    _add_header(slide,"🚀",_h2_title("axes", data, lang, SL("axes_title",lang)),SL("axes_subtitle",lang))
    colors=[C_TEAL,C_BLUE_MED,C_GOLD,C_ORANGE]
    positions=[(0.25,1.05),(5.05,1.05),(0.25,3.32),(5.05,3.32)]      # v62.13.9.4.37 — cartes de 2,2 po, option 2 de Robin (18/09/2026)
    for i,axe in enumerate(axes[:4]):
        color=colors[i]; px,py=positions[i]
        _add_rect(slide,px,py,4.52,2.2,C_NAVY); _add_rect(slide,px,py,0.07,2.2,color)
        _add_rect(slide,px+0.18,py+0.14,0.42,0.42,color)
        _add_text(slide,axe.get("num",str(i+1)),px+0.18,py+0.14,0.42,0.42,
                  font_size=16,bold=True,color=C_DARK_NAVY,align=PP_ALIGN.CENTER)
        titre_a = _clean_bullet_full(str(axe.get("titre",""))) or str(i+1)
        pt_t=_auto_font(titre_a,3.65,0.4,max_pt=13,min_pt=9)
        _add_text(slide,titre_a,px+0.72,py+0.16,3.65,0.4,font_size=pt_t,
                  bold=True,color=C_WHITE,role=f"HCRIT:axis:title:{i}")
        _points = [x for x in (axe.get("points",[]) or []) if str(x).strip()]
        # v62.13.9.4.33 (lot 1) — JUSQU'À TROIS POINTS PAR CARTE quand la
        # matière existe (décision Robin du 12/09/2026, amendement de la
        # spécification H2 : trois par carte, douze par slide, comptés par
        # carte par le gate) : le point qualitatif d'abord ; un message de
        # contrôle (« Proposition chiffrée … ») ne prend jamais la place d'un
        # point développable — il n'apparaît que s'il n'y a rien d'autre.
        _clean_pts, _placeholders = [], []
        for pt in _points:
            # v62.13.9.4.37 — amendement H2 du 18/09/2026 (décision de Robin) : un point de
            # carte porte jusqu'à 35 mots sur deux lignes ; la mise en page n'est pas la
            # doctrine. Bande de 0,62 po à 10 pt, trois points par carte au plus.
            clean_pt = _h2_exec(_clean_bullet_full(str(pt)), lang,
                                max_words=35, max_chars=350, drop_trailing_deadline=True)
            if not clean_pt:
                continue
            if _is_control_placeholder(clean_pt):
                _placeholders.append(clean_pt)
                continue
            _clean_pts.append(clean_pt)
            if len(_clean_pts) >= 3:
                break
        if not _clean_pts and _placeholders:
            _clean_pts = _placeholders[:1]
        for j, clean_pt in enumerate(_clean_pts):
            # v62.13.9.4.38 — revue ChatGPT du 19/09 : le troisième point (py+1,64, h 0,50)
            # et la note de couverture (py+1,68) occupaient la même bande. Trois bandes
            # de 0,46 po (pas 0,47) : le troisième point s'arrête à py+2,01 ; la note est
            # réservée SOUS les points, à py+2,02, dans la carte de 2,2 po.
            by = py + 0.60 + j * 0.47
            _add_rect(slide,px+0.2,by+0.11,0.1,0.1,color)
            _add_text(slide,clean_pt,px+0.38,by,4.0,0.46,font_size=10,
                      color=C_ICE_BLUE,role=f"HCRIT:axis:action:{i}:{j}")
        _add_coverage_note(slide, min(len(_clean_pts), len(_points)), len(_points),
                           px+0.38, py+2.00, 3.95, lang)   # bas de note = bas de carte
    _pgnum(slide, len(prs.slides), _synth_ref("decision", data, lang if "lang" in dir() else data.get("lang", "fr")))



def _score_color(val) -> "RGBColor":
    """Couleur selon score /10 : vert ≥7, or 5-6, rouge ≤4."""
    try:
        v = float(val)
        if v >= 7:   return C_GREEN
        if v >= 5:   return C_GOLD
        return C_RED
    except Exception:
        return C_MID_GRAY


def _slide_supply_chain(prs, data):
    lang = data.get("lang", "fr")  # v16.5.38 bilingual
    sc = data.get("supply_chain") or {}
    if not sc.get("enabled"):
        return
    # S.2.3 — état « non couvert » : aucun JSON SC exploitable. On rend une slide
    # honnête (bandeau neutre + message localisé), SANS scores ni findings fabriqués.
    if sc.get("not_covered") or str(sc.get("global_status", "")).strip().lower() == "not_covered":
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.background.fill.solid(); slide.background.fill.fore_color.rgb = C_LIGHT_GRAY
        _add_header(slide, "🚚", _h2_title("supply", data, lang, SL("slide_title_sc", lang)), SL("sc_subtitle", lang))
        if data.get("_retail_kw14"):
            # B.1.3.18 (run 10 dossier anglophone coté : « structured_invalid » passait AVANT
            # le filet 3.14 — le deck disait « narrative available » en slide
            # et NOT COVERED en synthèse). Quand le CR PARLE retail/ops, LIGHT
            # gagne sur tout autre motif : c'est le message le plus informatif.
            msg = ("Retail Ops / Inventory — LIGHT (from CR narrative) — "
                   "see the CR section."
                   if (lang or "fr").lower() == "en" else
                   "Retail Ops / Stocks — LIGHT (narratif CR) — voir la "
                   "section CR.")
        elif str(sc.get("reason", "")).strip() == "structured_invalid":
            msg = ("Supply Chain: narrative available, structured output invalid — refer to the CR section."
                   if (lang or "fr").lower() == "en" else
                   "Supply Chain : analyse narrative disponible, sortie structurée invalide — voir la section CR.")
        else:
            if str((sc or {}).get("global_status", "")) == "light_industrial":
                msg = ("Supply Chain / Industry — LIGHT mode: operational material "
                       "available in the CR (sites, inventory, flows); no dedicated "
                       "structured analysis in this run."
                       if lang == "en" else
                       "Supply Chain / Industrie — mode LIGHT : matière opérationnelle "
                       "disponible au CR (sites, stocks, flux) ; pas d'analyse "
                       "structurée dédiée dans cette exécution.")
            else:
                msg = ("Supply Chain not covered in this run — refer to the CR section."
                   if (lang or "fr").lower() == "en" else
                   "Supply Chain non couverte dans cette exécution — voir la section CR.")
        # B.1.3.56 (scope H) — bandeau sur DEUX lignes possibles : plus aucune
        # troncature du message LIGHT au rendu.
        _add_rect(slide, 0.25, 1.22, 9.5, 0.78, C_NAVY)
        _add_text(slide, msg, 0.35, 1.28, 9.3, 0.68,
                  font_size=_auto_font(msg, 9.3, 0.40, max_pt=12, min_pt=9),
                  bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)
        # B.1.3.56 (scope C) — constats opérationnels cités du CR (3-5,
        # déterministes). Slide jamais « presque vide » quand la matière existe.
        _lf = []
        for x in (sc.get("light_findings") or []):
            _txt = (x.get("text") if isinstance(x, dict) else str(x)) or ""
            if _txt.strip():
                _lf.append(_txt.strip())
        if _lf:
            _hdr = ("Operational findings quoted from the CR"
                    if (lang or "fr").lower() == "en"
                    else "Constats opérationnels cités du CR")
            _add_text(slide, _hdr, 0.45, 2.25, 9.1, 0.32, font_size=13,
                      bold=True, color=C_NAVY)
            _y = 2.62
            for _f in _lf[:5]:
                _add_text(slide, "•  " + _f, 0.55, _y, 8.9, 0.52,
                          font_size=_auto_font("•  " + _f, 8.9, 0.50,
                                               max_pt=11, min_pt=9),
                          color=C_NAVY)
                _y += 0.56
            _src = ("Unstructured CR quotes (deterministic selection, "
                    "operational signals) — not page-confirmed facts."
                    if (lang or "fr").lower() == "en" else
                    "Citations non structurées du CR (sélection déterministe, "
                    "signaux opérationnels) — pas des faits page-confirmés.")
            _add_text(slide, _src, 0.45, min(_y + 0.05, 5.05), 9.1, 0.3,
                      font_size=9, italic=True, color=C_NAVY)
        _pgnum(slide, len(prs.slides))  # S.2.3.1 — footer AI Act + n° de slide
        return
    # F.6.10 (audit dossier réseau de soins F.6.9) — nettoyage board-safe de TOUS les champs texte
    # de la slide (findings/risks/tradeoffs/dg_decisions/executive_summary/kpis) :
    # retire codes SC-x + balises cassées, humanise les tags épistémiques. Couvre
    # le chemin JSON ET le chemin fallback (qui injectait des en-têtes bruts).
    sc = dict(sc)
    for _k in ("findings", "risks", "tradeoffs", "dg_decisions",
               "executive_summary", "kpis", "key_findings", "codir_tradeoffs"):
        if _k in sc:
            sc[_k] = _board_safe_field(sc[_k])
    # M.5.10.4 — normalisation EN du vocabulaire contrôlé SC (no-op en FR).
    # Couvre executive_summary + listes + le sous-dict actions par horizon.
    if (lang or "fr").lower() == "en":
        for _k in ("executive_summary", "findings", "risks", "tradeoffs",
                   "dg_decisions", "kpis", "key_findings", "codir_tradeoffs"):
            if _k in sc:
                sc[_k] = _loc_sc_text(sc[_k], lang)
        _acts = sc.get("actions")
        if isinstance(_acts, dict):
            sc["actions"] = {hk: _loc_sc_text(hv, lang) for hk, hv in _acts.items()}
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb = C_LIGHT_GRAY
    _add_header(slide, "🚚", _h2_title("supply", data, lang, SL("slide_title_sc", lang)),
                SL("sc_subtitle", lang))

    # ── Bandeau message clé ──────────────────────────────────────────────────
    status = str(sc.get("global_status", "sain") or "sain").strip().lower()
    # S.2.4.1 — couleur du bandeau SC via le CANONISEUR : l'agent/normalisation peut
    # émettre « sous tension » (espace) ou « under_pressure », que l'ancien
    # `== "sous_tension"` ratait → bandeau ROUGE par défaut alors que sous-tension = or.
    _cs = _canon_sc_status(status)
    status_color = (C_GREEN if _cs == "healthy"
                    else C_GOLD if _cs == "under_pressure"
                    else C_ORANGE if _cs == "degraded"
                    else C_RED)   # critical / inconnu
    text_on_banner = C_DARK_NAVY if status_color == C_GOLD else C_WHITE
    _add_rect(slide, 0.25, 1.22, 9.5, 0.44, status_color)
    msg = _clean_bullet(str(sc.get("executive_summary", "")), 125) \
          or ("Supply chain diagnosis available" if (lang or "fr").lower() == "en"
              else "Diagnostic supply chain disponible")
    _add_text(slide, msg, 0.35, 1.24, 9.3, 0.40,
              font_size=_auto_font(msg, 9.3, 0.40, max_pt=11, min_pt=9),
              bold=True, color=text_on_banner, align=PP_ALIGN.CENTER)

    # ── Statut + scores colorés ──────────────────────────────────────────────
    _add_rect(slide, 0.25, 1.86, 2.2, 2.1, C_WHITE)
    _add_rect(slide, 0.25, 1.86, 2.2, 0.38, C_NAVY)
    _add_text(slide, SL("sc_global_status", lang), 0.25, 1.86, 2.2, 0.38,
              font_size=10, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)
    status_label = _loc_sc_status(status, lang)  # M.5.10 — localisé
    _add_text(slide, status_label, 0.35, 2.30, 2.0, 0.36,
              font_size=_auto_font(status_label, 2.0, 0.36, max_pt=16, min_pt=10),
              bold=True, color=status_color, align=PP_ALIGN.CENTER)

    # ── v16.5.28 — Scores : plus de "n/a", badge "est." si MODE BRIEFING ────
    scores = sc.get("scores") or {}
    _scores_estimated = bool(scores.get("scores_estimated", False))
    score_defs = [
        (SL("sc_dim_service", lang),  scores.get("service_level")),
        (SL("sc_dim_stock", lang),    scores.get("stock_management")),
        (SL("sc_dim_supplier", lang),   scores.get("supply_resilience")),
        (SL("sc_dim_cash", lang),     scores.get("cash_impact")),
    ]
    for i, (lab, val) in enumerate(score_defs):
        sy = 2.76 + i * 0.28
        if val is None:
            sval, sc_color = "–", C_MID_GRAY          # jamais "n/a"
        elif _scores_estimated:
            # F.6.8 (P2, audit ChatGPT) — un score « 5/10 est. » sans donnée KPI
            # source n'est pas défendable : on affiche « À QUALIFIER » (pas de
            # barre proportionnelle trompeuse).
            sval, sc_color, val = SL("status_to_qualify", lang), C_MID_GRAY, None
        else:
            try:
                sval = f"{float(val):.0f}/10"
            except Exception:
                sval = str(val)
            sc_color = _score_color(val)
        # Barre de fond score
        _add_rect(slide, 0.38, sy + 0.06, 1.88, 0.20,
                  _rgb(0xEE, 0xF2, 0xF8))
        # Barre remplie proportionnelle (si valeur numérique)
        try:
            fill_w = max(0.04, min(1.88, 1.88 * float(val) / 10))
            _add_rect(slide, 0.38, sy + 0.06, fill_w, 0.20, sc_color)
        except Exception:
            pass
        _add_text(slide, f"{lab} : {sval}", 0.40, sy, 1.84, 0.22,
                  font_size=8.5, bold=(val is not None and sval != "–"),
                  color=C_TEXT_DARK)

    # ── Constats clés ────────────────────────────────────────────────────────
    _add_rect(slide, 2.65, 1.86, 3.2, 2.1, C_WHITE)
    _add_rect(slide, 2.65, 1.86, 3.2, 0.38, C_TEAL)
    _add_text(slide, SL("sc_findings", lang), 2.65, 1.86, 3.2, 0.38,
              font_size=11, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)
    findings = [f for f in (sc.get("findings") or []) if str(f).strip()]
    if findings:
        for i, item in enumerate(findings[:3]):
            iy = 2.36 + i * 0.52
            clean = _clean_bullet(str(item), 56)
            if not clean:
                continue
            _add_rect(slide, 2.80, iy + 0.10, 0.12, 0.12, C_TEAL)
            _add_text(slide, clean, 3.02, iy, 2.60, 0.36,
                      font_size=_auto_font(clean, 2.60, 0.36, max_pt=10, min_pt=7.5),
                      color=C_TEXT_DARK)
    else:
        _add_text(slide, SL("sc_data_unavailable", lang), 2.80, 2.55, 2.80, 0.36,
                  font_size=9, italic=True, color=C_MID_GRAY, align=PP_ALIGN.CENTER)

    # ── Risques majeurs ──────────────────────────────────────────────────────
    _add_rect(slide, 6.05, 1.86, 3.7, 2.1, C_WHITE)
    _add_rect(slide, 6.05, 1.86, 3.7, 0.38, C_ORANGE)
    _add_text(slide, SL("sc_major_risks", lang), 6.05, 1.86, 3.7, 0.38,
              font_size=11, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)
    risks = [r for r in (sc.get("risks") or []) if str(r).strip()]
    if risks:
        for i, item in enumerate(risks[:3]):
            iy = 2.36 + i * 0.52
            clean = _clean_bullet(str(item), 64)
            if not clean:
                continue
            _add_rect(slide, 6.20, iy + 0.10, 0.12, 0.12, C_ORANGE)
            _add_text(slide, clean, 6.42, iy, 3.05, 0.36,
                      font_size=_auto_font(clean, 3.05, 0.36, max_pt=10, min_pt=7.5),
                      color=C_TEXT_DARK)
    else:
        _add_text(slide, SL("sc_no_critical_risk", lang), 6.20, 2.55, 3.25, 0.36,
                  font_size=9, italic=True, color=C_MID_GRAY, align=PP_ALIGN.CENTER)

    # ── v16.5.28 — Décisions DG (SC-5) ou Arbitrages CODIR ─────────────────
    dg_decisions = [d for d in (sc.get("dg_decisions") or []) if str(d).strip()]
    tradeoffs    = [t for t in (sc.get("tradeoffs")    or []) if str(t).strip()]
    # Priorité : décisions DG structurées (SC-5) > arbitrages génériques
    use_decisions = bool(dg_decisions)
    box_title  = SL("decisions_dg", lang) if use_decisions else SL("board_tradeoffs", lang)
    box_color  = C_RED if use_decisions else C_DARK_NAVY
    items_list = dg_decisions if use_decisions else tradeoffs
    _add_rect(slide, 0.25, 4.16, 4.65, 1.02, box_color)
    _add_rect(slide, 0.25, 4.16, 0.07, 1.02, C_GOLD)
    _add_text(slide, box_title, 0.45, 4.20, 4.2, 0.30,
              font_size=10, bold=True, color=C_GOLD)
    if items_list:
        for i, item in enumerate(items_list[:3]):
            iy = 4.54 + i * 0.20
            clean = _clean_bullet(str(item), 72)
            if not clean:
                continue
            prefix = "▸ " if use_decisions else "• "
            _add_text(slide, prefix + clean, 0.45, iy, 4.2, 0.18,
                      font_size=_auto_font(clean, 4.0, 0.18, max_pt=8.5, min_pt=6.5),
                      color=C_WHITE)
    else:
        _add_text(slide, SL("sc_decisions_to_arb", lang), 0.45, 4.54, 4.2, 0.36,
                  font_size=8.5, italic=True, color=C_MID_GRAY)

    # ── Plan d'action — une ligne par horizon ────────────────────────────────
    _add_rect(slide, 5.05, 4.16, 4.7, 1.02, C_WHITE)
    _add_rect(slide, 5.05, 4.16, 4.7, 0.30, C_GOLD)
    _add_text(slide, SL("action_plan", lang), 5.05, 4.16, 4.7, 0.30,
              font_size=10, bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)
    actions = sc.get("actions") or {}
    # M.5.10.10 — libellés d'horizon localisés (audit dossier anglophone coté EN : « 0-30j / 1-3m
    # / 3-12m » fuyaient dans le deck anglais).
    _h = (("0-30d", "1-3mo", "3-12mo") if (lang or "fr").lower() == "en"
          else ("0-30j", "1-3m", "3-12m"))
    plan_items = [
        (_h[0],  actions.get("0_30_days")   or []),
        (_h[1],  actions.get("1_3_months")  or []),
        (_h[2],  actions.get("3_12_months") or []),
    ]
    py = 4.52
    for lab, lst in plan_items:
        lst_clean = [a for a in lst if str(a).strip()]
        for act in lst_clean[:1]:
            txt = f"{lab} : {act}"
            txt = _clean_bullet(txt, 64) or txt[:64]
            _add_text(slide, txt, 5.18, py, 4.35, 0.21,
                      font_size=_auto_font(txt, 4.35, 0.21, max_pt=9, min_pt=7),
                      color=C_TEXT_DARK)
            py += 0.23
        if not lst_clean:
            _add_text(slide, f"{lab}: {SL('to_confirm', lang)}", 5.18, py, 4.35, 0.20,
                      font_size=8.5, italic=True, color=C_MID_GRAY)
            py += 0.22
    # Note SC Fix v16.5.28 : le fallback "Plan d'action à définir en séance" (position fixe y=4.54)
    # a été supprimé car il chevauchait les lignes SL("to_confirm", lang) déjà rendues quand toutes les
    # listes d'actions sont vides. Les SL("to_confirm", lang) par horizon sont suffisants.

    # ── v16.5.28 — Légende épistémique SC ───────────────────────────────────
    _scores_est_flag = bool((data.get("supply_chain") or {}).get("scores", {}).get("scores_estimated", False))
    _legend_parts = [
        SL("sc_legend_fact",lang)  + (" = data from brief"          if lang=="en" else " = donnée du brief"),
        SL("sc_legend_ref",lang)   + (" = sector benchmark"         if lang=="en" else " = benchmark sectoriel"),
        SL("sc_legend_estim",lang) + (" = model inference — verify" if lang=="en" else " = inférence modèle — à vérifier"),
    ]
    _legend_txt = "  ·  ".join(_legend_parts)
    if _scores_est_flag:
        _legend_txt += "  ·  " + SL("sc_briefing_mode", lang)
    _add_text(slide, _legend_txt, 0.25, 5.28, 9.5, 0.20,
              font_size=6.5, italic=True, color=C_MID_GRAY, align=PP_ALIGN.LEFT)

    _pgnum(slide, len(prs.slides))


def _slide_commercial(prs, data):
    """
    Slide 5 — Direction Commerciale (Grok).
    Gauche : Opportunités + Plan d'actions (3 lignes action/KPI/délai).
    Droite : Challenges Marketing (haut) + Challenges Finance (bas).
    """
    lang = data.get("lang", "fr")  # v16.5.38 bilingual
    comm = data.get("commercial", {})
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_DARK_NAVY

    # M.5.9 (FIX B2) — sous retrait (mise en sommeil), la slide n'est plus un plan
    # de prospection : requalification en « maintien relationnel minimal ».
    if comm.get("winddown"):
        _comm_title = ("MAINTIEN RELATIONNEL MINIMAL" if lang != "en"
                       else "MINIMAL RELATIONSHIP UPKEEP")
        _comm_sub = ("Hors prospection active — pendant la mise en sommeil" if lang != "en"
                     else "No active prospecting — during dormancy")
    else:
        _comm_title = SL("slide_title_commercial", lang)
        _comm_sub = SL("commercial_subtitle", lang)
    _add_header(slide, "\U0001f4bc", _h2_title("commercial", data, lang, _comm_title), _comm_sub)

    # ── Colonne gauche : opportunités + plan d'actions ─────────────────────
    _add_rect(slide, 0.25, 1.22, 5.6, 0.38, C_TEAL)
    _add_text(slide, SL("commercial_opportunities", lang), 0.25, 1.22, 5.6, 0.38,
              font_size=10, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)

    opportunites = (comm.get("opportunites") or [])[:4]
    for i, opp in enumerate(opportunites):
        oy = 1.68 + i * 0.32
        _add_rect(slide, 0.28, oy + 0.07, 0.12, 0.12, C_TEAL)
        # Fix v16.5.28 — ne pas restituer le bruit via le fallback raw
        clean = _clean_bullet(str(opp), 62)
        if not clean:
            continue
        pt = _auto_font(clean, 4.85, 0.30, max_pt=9.5, min_pt=7.5)
        _add_text(slide, clean, 0.48, oy, 4.85, 0.30, font_size=pt, color=C_ICE_BLUE)

    # Plan d'actions — 3 lignes avec action / KPI / délai
    _add_rect(slide, 0.25, 3.0, 5.6, 0.35, C_GOLD)
    _add_text(slide, SL("commercial_action_plan", lang), 0.25, 3.0, 5.6, 0.35,
              font_size=10, bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)

    actions = (comm.get("plan_actions") or [])[:3]
    # Fix v16.5.28 — délais progressifs au rendu : évite T1/T1 quand item 3
    # a un délai différent mais son action est filtrée (if not clean: continue)
    _used_delais: list[str] = []
    _fallback_delais = ["T1", "T2", "T3"]
    for i, item in enumerate(actions):
        ay = 3.42 + i * 0.65
        # Fix v16.5.28/16 — ne pas restituer le bruit
        action = _clean_bullet(str(item.get("action", "")), 62)
        if not action:
            continue
        kpi   = _t(str(item.get("kpi",   "")), 55)
        delai = _t(str(item.get("delai", "")), 8)
        # Fix v16.5.28 — délai progressif au rendu : si vide ou déjà utilisé → prochain T libre
        if not delai or delai in _used_delais:
            delai = next((d for d in _fallback_delais if d not in _used_delais), delai)
        _used_delais.append(delai)
        # Fond de ligne — Fix v16.5.28 : hauteur 0.46 → 0.56
        _add_rect(slide, 0.28, ay, 5.55, 0.56, _rgb(0x1A, 0x23, 0x50))
        _add_rect(slide, 0.28, ay, 0.06, 0.56, C_GOLD)
        # Délai (badge)
        _add_rect(slide, 0.38, ay + 0.10, 0.46, 0.30, C_GOLD)
        _add_text(slide, delai, 0.38, ay + 0.10, 0.46, 0.30,
                  font_size=8, bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)
        # Action — largeur 4.7, auto_fit v16.5.28
        pt_a = _auto_font(action, 4.7, 0.24, max_pt=9.5, min_pt=7.5)
        _add_text(slide, action, 0.92, ay + 0.02, 4.7, 0.24, font_size=pt_a, bold=True, color=C_WHITE, auto_fit=True)
        # KPI — Fix v16.5.28 : hauteur 0.20 → 0.28 pour éviter la troncature verticale
        pt_k = _auto_font(kpi, 4.7, 0.28, max_pt=8.5, min_pt=7)
        _add_text(slide, kpi, 0.92, ay + 0.26, 4.7, 0.28, font_size=pt_k, color=C_TEAL, auto_fit=True)

    # ── Colonne droite : challenges ───────────────────────────────────────────
    # Challenge Marketing
    _add_rect(slide, 6.05, 1.22, 3.7, 0.38, C_ORANGE)
    _add_text(slide, "\u26a0 CHALLENGES MARKETING", 6.05, 1.22, 3.7, 0.38,
              font_size=10, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)
    ch_mkt = (comm.get("challenges_marketing") or [])[:3]
    for i, ch in enumerate(ch_mkt):
        cy2 = 1.68 + i * 0.38
        _add_rect(slide, 6.08, cy2 + 0.1, 0.08, 0.08, C_ORANGE)
        clean = _clean_bullet(str(ch), 55)
        if not clean:
            continue
        pt = _auto_font(clean, 3.5, 0.34, max_pt=9.5, min_pt=7.5)
        _add_text(slide, clean, 6.24, cy2, 3.5, 0.34, font_size=pt, color=C_ICE_BLUE)

    # Ligne séparatrice
    _add_rect(slide, 6.05, 3.0, 3.7, 0.04, C_MID_GRAY)

    # Challenge Finance
    _add_rect(slide, 6.05, 3.1, 3.7, 0.38, C_BLUE_MED)
    _add_text(slide, "\u26a0 CHALLENGES FINANCE", 6.05, 3.1, 3.7, 0.38,
              font_size=10, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)
    ch_fin = (comm.get("challenges_finance") or [])[:3]
    for i, ch in enumerate(ch_fin):
        cy2 = 3.56 + i * 0.38
        _add_rect(slide, 6.08, cy2 + 0.1, 0.08, 0.08, C_BLUE_MED)
        clean = _clean_bullet(str(ch), 55)
        if not clean:
            continue
        pt = _auto_font(clean, 3.5, 0.34, max_pt=9.5, min_pt=7.5)
        _add_text(slide, clean, 6.24, cy2, 3.5, 0.34, font_size=pt, color=C_ICE_BLUE)

    _pgnum(slide, len(prs.slides), _synth_ref("commercial", data, lang if "lang" in dir() else data.get("lang", "fr")))


def _slide_modele_eco(prs, data):
    lang = data.get("lang", "fr")  # v16.5.59
    """Slide SOLO uniquement — JAMAIS appelée en deck CORPORATE.
    Contient TJM, temps partagé, réseau prescripteurs/co-traitants.
    Pour un deck CORPORATE, c'est _slide_risques_arbitrages qui est appelée.
    Voir generate_pptx_from_cr_with_provider() pour le routing deck_type.
    """
    eco=data.get("modele_eco",{})
    slide=prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb=C_LIGHT_GRAY

    # Titres dynamiques selon contexte (temps partagé vs indicateurs activité) — v16.5.28+
    tp_titre  = _t(str(eco.get("temps_partage_titre") or SL("eco_offer_default", lang)), 35)
    res_titre = _t(str(eco.get("reseau_titre") or SL("eco_network_default", lang)), 30)
    # Nettoyer : si l'IA a mis la description d'instruction plutôt qu'un vrai titre, fallback
    _instruction_markers = ["si le brief", "sinon", "selon le contexte", "max 35", "max 30"]
    if any(m in tp_titre.lower() for m in _instruction_markers):
        tp_titre = SL("eco_activity_fallback", lang)
    if any(m in res_titre.lower() for m in _instruction_markers):
        res_titre = SL("eco_network_fallback", lang)

    _add_header(slide, "💰", SL("eco_title", lang),
                f"Pricing valeur · {tp_titre.title()} · {res_titre.title()}")
    _add_rect(slide,0.25,1.25,9.5,1.58,C_WHITE); _add_rect(slide,0.25,1.25,0.07,1.58,C_GOLD)
    # v16.5.28 — titre section TJM dynamique (SOLO uniquement)
    _valorisation_titre = _t(str(eco.get("valorisation_titre") or "REVALORISATION DU TJM"), 32)
    if any(m in _valorisation_titre.lower() for m in ["si le brief", "sinon", "selon"]):
        _valorisation_titre = "REVALORISATION DU TJM"
    _add_text(slide, _valorisation_titre, 0.45,1.35,4.0,0.32,font_size=11,bold=True,color=C_NAVY)
    rows=[(eco.get("tjm_actuel","n/d"),0.55,C_MID_GRAY),
          (eco.get("tjm_marche","n/d"),0.72,C_TEAL),
          (eco.get("tjm_cible","n/d"),0.90,C_GREEN)]
    labels=SL("eco_tjm_labels",lang).split("|")
    for i,(val,pct,color) in enumerate(rows):
        ty=1.83+i*0.28
        _add_text(slide,labels[i],0.45,ty,3.0,0.26,font_size=10,color=C_TEXT_DARK)
        _add_rect(slide,3.55,ty+0.04,4.5,0.17,_rgb(0xE8,0xEC,0xF0))
        _add_rect(slide,3.55,ty+0.04,4.5*pct,0.17,color)
        _add_text(slide,_t(val,22),8.15,ty,1.6,0.26,font_size=10,bold=True,color=color)
    _add_rect(slide,0.25,3.0,4.65,2.38,C_WHITE); _add_rect(slide,0.25,3.0,4.65,0.45,C_TEAL)
    _add_text(slide, tp_titre, 0.25,3.0,4.65,0.45,
              font_size=_auto_font(tp_titre, 4.65, 0.45, max_pt=11, min_pt=9),
              bold=True,color=C_WHITE,align=PP_ALIGN.CENTER)
    for i,row in enumerate(eco.get("temps_partage",[])[:4]):
        ty=3.6+i*0.42
        _add_rect(slide,0.35,ty,1.55,0.3,C_NAVY)
        pt_kpi=_auto_font(str(row.get("kpi","")),1.55,0.3,max_pt=11,min_pt=8)
        _add_text(slide,_t(row.get("kpi",""),18),0.35,ty,1.55,0.3,font_size=pt_kpi,bold=True,color=C_GOLD,align=PP_ALIGN.CENTER)
        _add_text(slide,_t(row.get("label",""),32),2.0,ty,2.78,0.3,font_size=10,color=C_TEXT_DARK)
    _add_rect(slide,5.1,3.0,4.65,2.38,C_WHITE); _add_rect(slide,5.1,3.0,4.65,0.45,C_GOLD)
    _add_text(slide, res_titre, 5.1,3.0,4.65,0.45,
              font_size=_auto_font(res_titre, 4.65, 0.45, max_pt=11, min_pt=9),
              bold=True,color=C_DARK_NAVY,align=PP_ALIGN.CENTER)
    for i,row in enumerate(eco.get("reseau",[])[:4]):
        ty=3.6+i*0.42
        _add_rect(slide,5.2,ty,1.1,0.3,C_NAVY)
        pt_kpi=_auto_font(str(row.get("kpi","")),1.1,0.3,max_pt=11,min_pt=8)
        _add_text(slide,_t(row.get("kpi",""),12),5.2,ty,1.1,0.3,font_size=pt_kpi,bold=True,color=C_GOLD,align=PP_ALIGN.CENTER)
        _add_text(slide,_t(row.get("label",""),32),6.4,ty,3.25,0.3,font_size=10,color=C_TEXT_DARK)
    _pgnum(slide, len(prs.slides))


def _slide_roadmap(prs, data):
    lang = data.get("lang", "fr")  # v16.5.59
    """Slide 6 — Roadmap trimestrielle avec vraies actions issues du CR."""
    phases=data.get("roadmap",[])
    slide=prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb=C_LIGHT_GRAY
    _add_header(slide,"📅",SL("roadmap_title",lang),SL("roadmap_subtitle",lang))
    _add_rect(slide,0.65,2.02,8.7,0.05,C_MID_GRAY)
    phase_colors=[C_TEAL,C_BLUE_MED,C_GREEN,C_GOLD]
    pw,sx=2.2,0.35
    total_gap=(10-2*sx-4*pw)/3
    for i,phase in enumerate(phases[:4]):
        color=phase_colors[i]; px=sx+i*(pw+total_gap)
        # Cercle timeline
        ov=slide.shapes.add_shape(9,Inches(px+pw/2-0.25),Inches(1.82),Inches(0.5),Inches(0.5))
        ov.fill.solid(); ov.fill.fore_color.rgb=color; ov.line.fill.background()
        _add_text(slide,phase.get("phase",""),px+pw/2-0.25,1.82,0.5,0.5,
                  font_size=13,bold=True,color=C_WHITE,align=PP_ALIGN.CENTER)
        _add_text(slide,phase.get("date",""),px,1.32,pw,0.34,
                  font_size=9,italic=True,color=C_MID_GRAY,align=PP_ALIGN.CENTER)
        _add_rect(slide,px,2.42,pw,3.00,C_WHITE); _add_rect(slide,px,2.42,pw,0.40,color)
        tc=C_DARK_NAVY if color==C_GOLD else C_WHITE
        _phase_title = str(phase.get("titre","") or "").strip()
        _add_text(slide,_phase_title,px,2.42,pw,0.40,
                  font_size=_auto_font(_phase_title,pw,0.40,max_pt=11,min_pt=9),
                  bold=True,color=tc,align=PP_ALIGN.CENTER,
                  role=f"HCRIT:roadmap:title:{i}")
        # H2-R3 : trois actions par horizon, triées dans l'ordre fourni par
        # le moteur (l'horizon porte déjà sa séquence), puis coupe tracée.
        _ritems = [x for x in (phase.get("items",[]) or []) if str(x).strip()]
        for j,item in enumerate(_ritems[:3]):
            # v62.4 — budget étroit stable sous variabilité LLM. La période est
            # déjà affichée au-dessus de la colonne ; les dates terminales sont
            # donc retirées de l'action courte, sans perdre le détail du CR.
            clean_item = _h2_exec(
                _clean_bullet_full(str(item)), lang,
                max_words=7, max_chars=44,
                drop_trailing_deadline=True,
            )
            iy=2.84+j*0.52
            _add_rect(slide,px+0.15,iy+0.18,0.1,0.1,color)
            _add_text(slide,clean_item,px+0.32,iy,pw-0.38,0.48,font_size=11,
                      color=C_TEXT_DARK,role=f"HCRIT:roadmap:action:{i}:{j}")
        # Une note de couverture n'apporte rien lorsque les trois actions
        # tiennent déjà dans la colonne. Si une phase en contient davantage,
        # on réserve explicitement une voie séparée AVANT le badge KPI afin
        # qu'aucun texte gris ne passe derrière la carte (défaut terrain v62.3).
        _has_coverage = len(_ritems) > 3
        if _has_coverage:
            _add_coverage_note(slide, 3, len(_ritems),
                               px+0.32, 4.34, pw-0.38, lang)
        # Badge KPI
        kpi=_clean_bullet_full(str(phase.get("kpi",SL("to_define", lang)))) or "KPI"
        kpi_short = _h2_exec(kpi, lang, max_words=6, max_chars=36)
        _kpi_y = 4.66 if _has_coverage else 4.58
        if kpi_short.strip() and kpi_short.strip().upper() != "KPI":         # v62.13.9.4.24 — pas de « KPI : KPI »
            _add_rect(slide,px+0.1,_kpi_y,pw-0.2,0.54,C_NAVY)
            _add_text(slide,"KPI : "+kpi_short,px+0.1,_kpi_y,pw-0.2,0.54,
                      font_size=11,bold=True,color=C_GOLD,align=PP_ALIGN.CENTER,
                      role=f"HCRIT:roadmap:kpi:{i}")
        # Budget — v16.5.28 : filtrer placeholders vides
        _budget_raw = _sanitize_slide_text(str(phase.get("budget", "") or ""), 20, "")
        _extra_raw  = _sanitize_slide_text(str(phase.get("extra",  "") or ""), 20, "")
        if _budget_raw or _extra_raw:
            budget = _t((" · ".join(x for x in [_budget_raw, _extra_raw] if x)), 35)
        else:
            budget = ""
        if budget:
            _budget_y = 5.22 if _has_coverage else 5.16
            _add_text(slide,budget,px,_budget_y,pw,0.18,
                      font_size=8,italic=True,color=C_MID_GRAY,align=PP_ALIGN.CENTER)
    _pgnum(slide, len(prs.slides), _synth_ref("roadmap", data, lang if "lang" in dir() else data.get("lang", "fr")))


def _slide_next_steps(prs, data):
    """H2-R3/R4 — deux surfaces : 3 actions + 2 décisions, puis 4 questions.

    Le précédent écran concentrait actions, questions et décisions dans une
    seule slide. La spec gèle N=3 actions par horizon et N=4 questions ; deux
    slides sont nécessaires pour respecter simultanément le budget 5/12.
    """
    lang = data.get("lang", "fr")
    steps = _h2_sort_actions([x for x in (data.get("next_steps") or [])
                              if isinstance(x, dict) and _h2_is_open_action(x)])
    questions = [str(x).strip() for x in (data.get("questions_ouvertes") or []) if str(x).strip()]
    decisions = [str(x).strip() for x in (data.get("decisions_codir") or []) if str(x).strip()]
    _bs = data.get("board_safe")

    # Slide A — trois actions et deux décisions : cinq messages exécutifs.
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb = C_LIGHT_GRAY
    _ns_default = ("PROCHAINES ÉTAPES & POINTS À REMONTER" if (_bs and lang == "fr")
                   else "NEXT STEPS & ITEMS TO ESCALATE" if _bs
                   else SL("next_steps_title", lang))
    _add_header(slide, "▶", _h2_title("next", data, lang, _ns_default),
                SL("next_steps_subtitle", lang))
    _add_rect(slide, 0.25, 1.25, 5.35, 3.92, C_WHITE)
    _add_rect(slide, 0.25, 1.25, 5.35, 0.44, C_NAVY)
    _add_text(slide, SL("priority_actions", lang), 0.25, 1.25, 5.35, 0.44,
              font_size=11, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)
    _steps = [x for x in steps if str(x.get("action") or "").strip()]
    for i, step in enumerate(_steps[:3]):
        sy = 1.86 + i * 0.86
        date_txt = str(step.get("date") or step.get("deadline") or "?")
        _add_rect(slide, 0.38, sy, 1.42, 0.38, C_GOLD)
        _add_text(slide, date_txt, 0.38, sy, 1.42, 0.38, font_size=11,
                  bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)
        # 9.4.60 — F59-06 / §7 : « Sélectionner et briefer un nombre limité de comptes pilotes par — CR » : la coupe à
        # 12 mots tombait avant l'objet ; 20 mots laissent le verbe ET son objet sur la carte
        action = _h2_exec(_clean_bullet_full(str(step.get("action") or "")), lang, max_words=20)
        _add_text(slide, action, 1.94, sy, 3.38, 0.44, font_size=11,
                  color=C_TEXT_DARK, role=f"HCRIT:next-step:action:{i}")
        owner = str(step.get("owner") or step.get("porteur") or "").strip()
        if owner and owner != SL("to_define", lang):
            _add_text(slide, owner, 1.94, sy + 0.46, 3.2, 0.22,
                      font_size=11, bold=True, color=C_NAVY,
                      role=f"HINFO:next-step:owner:{i}")
    _add_coverage_note(slide, min(3, len(_steps)), len(_steps), 1.94, 4.78, 3.3, lang)

    _add_rect(slide, 5.82, 1.25, 3.93, 3.92, C_DARK_NAVY)
    _add_rect(slide, 5.82, 1.25, 0.07, 3.92, C_GOLD)
    _dec_title = ("Points à remonter (Comité d'audit)" if (_bs and lang == "fr")
                  else "Items to escalate (Audit Committee)" if _bs
                  else SL("decisions_expected", lang))
    _add_text(slide, _dec_title, 6.03, 1.38, 3.5, 0.48,
              font_size=12, bold=True, color=C_GOLD)
    _prefix = "•  " if _bs else "✓  "
    for i, dec in enumerate(decisions[:2]):
        clean = _h2_exec(_clean_bullet_full(dec), lang)
        y = 2.12 + i * 0.88
        _add_text(slide, f"{_prefix}{i+1}. {clean}", 6.03, y, 3.45, 0.64,
                  font_size=11, color=C_WHITE,
                  role=f"HCRIT:next-step:decision:{i}")
    _add_coverage_note(slide, min(2, len(decisions)), len(decisions), 6.03, 4.78, 3.3, lang)
    _pgnum(slide, len(prs.slides), _synth_ref("next", data, lang if "lang" in dir() else data.get("lang", "fr")))

    # Slide B — quatre questions ouvertes, ordre conservé et coupe tracée.
    qslide = prs.slides.add_slide(prs.slide_layouts[6])
    qslide.background.fill.solid(); qslide.background.fill.fore_color.rgb = C_LIGHT_GRAY
    first_q = questions[0] if questions else ("Questions à documenter" if lang != "en" else "Questions to document")
    # v62.13.9.4.29 — contre-audit v27/v28 (slide 11) : une question coupée avant son
    # alternative (« … et les cabinets de — CR ? ») ne conserve pas le choix. Le
    # titre garde les deux branches : parenthèses et incises retirées, puis une
    # coupe à 18 mots, jamais à 12 sur une question.
    qtitle = _h2_assertion("Question clé" if lang != "en" else "Key question", _question_gist(first_q), lang, max_words=18)
    # 9.4.65 — dixième vérification (T10-R1) : sous-titre fixe écrit par l'outil, typé texte de l'outil (U+2063) ;
    # en anglais, « Up to 4 open questions » recevait « ⟨status : unsourced figure⟩ » après finalisation.
    _add_header(qslide, "?", qtitle,
                "\u20634 questions ouvertes maximum" if lang != "en" else "\u2063Up to 4 open questions")
    _add_rect(qslide, 0.45, 1.30, 9.10, 3.78, C_WHITE)
    _add_rect(qslide, 0.45, 1.30, 0.08, 3.78, C_RED)
    for i, q in enumerate(questions[:4]):
        # 9.4.61 — contre-recette du 12/10 (§14) : « Cadre de l'option 2. ? » — la coupe gardait le titre de la question
        # et perdait son objet ; c'est la phrase INTERROGATIVE qui est conservée (20 mots), sans point orphelin
        _q61 = _clean_bullet_full(q)
        _qm61 = re.search(r"([^.?!]{8,}\?)", _q61)
        clean = _h2_exec(_qm61.group(1).strip() if _qm61 else _q61, lang, max_words=20)
        clean = re.sub(r"[\s.]+\?$", " ?", clean or "")
        if clean and not clean.endswith("?"):
            clean += " ?"
        y = 1.62 + i * 0.78
        _add_rect(qslide, 0.72, y + 0.08, 0.32, 0.32, C_RED)
        _add_text(qslide, str(i + 1), 0.72, y + 0.08, 0.32, 0.32,
                  font_size=11, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)
        _add_text(qslide, clean, 1.22, y, 7.85, 0.48, font_size=11,
                  color=C_TEXT_DARK, role=f"HCRIT:next-step:question:{i}")
    _add_coverage_note(qslide, min(4, len(questions)), len(questions), 1.22, 4.78, 7.4, lang)
    _pgnum(qslide, len(prs.slides))


def _slide_conclusion(prs, data):
    """
    Slide 8 — Conclusion executive redesignée.
    Colonne gauche : headline + 3 points clés.
    Colonne droite : composition cercles concentriques + 3 métriques clés.
    Tout intégré dans la slide, aucun débordement.
    """
    lang = data.get("lang", "fr")  # v16.5.38 bilingual
    concl   = data.get("conclusion", {})
    d_marche = data.get("marche", {})

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_DARK_NAVY

    # ── Barre gauche accent ──────────────────────────────────────────────────
    _add_rect(slide, 0, 0, 0.12, 5.625, C_GOLD)

    # ── Composition cercles droite intégrée ─────────────────────────────────
    cx, cy = 5.85, 0.38
    cr = 4.85

    # Cercle extérieur (anneau fin)
    s_out = slide.shapes.add_shape(9, Inches(cx), Inches(cy),
                                   Inches(cr), Inches(cr))
    s_out.fill.background()
    s_out.line.color.rgb = _rgb(0x2A, 0x35, 0x7A)
    s_out.line.width = Pt(1.5)

    # Anneau intermédiaire
    off2 = 0.5
    s_mid = slide.shapes.add_shape(9, Inches(cx+off2), Inches(cy+off2),
                                   Inches(cr-2*off2), Inches(cr-2*off2))
    s_mid.fill.solid()
    s_mid.fill.fore_color.rgb = _rgb(0x1A, 0x22, 0x5E)
    s_mid.line.color.rgb = _rgb(0x2E, 0x3A, 0x8A)
    s_mid.line.width = Pt(0.75)

    # 3 métriques dans le cercle — zones plus larges pour texte complet
    # Disposition verticale : empilées, centrées dans l'anneau
    # Zone anneau : cx+off2 .. cx+off2+cr-2*off2 = centre ≈ 8.1"
    m_cx   = cx + off2          # 6.35
    m_cr   = cr - 2 * off2      # 3.85"
    m_ctr  = m_cx + m_cr / 2    # centre X de l'anneau ≈ 8.275"
    mw     = 2.0                 # largeur zone métrique (assez pour "+8% vs 2025")
    mh     = 1.0                 # hauteur zone métrique
    mgap   = 0.12                # espace vertical entre métriques
    m_total_h = 3 * mh + 2 * mgap
    m_start_y = cy + off2 + (m_cr - m_total_h) / 2  # centré dans l'anneau

    if str(data.get("deck_type", "")).strip().lower() == "corporate":
        cc = data.get("contexte_corporate") or {}
        sc = data.get("supply_chain") or {}
        sc_signal = _loc_sc_status(sc.get("global_status", "sous_tension") or "sous_tension", lang)
        # B.1.3.18 (run 10) — cohérence synthèse/slide : la tuile ne dit
        # jamais NOT COVERED quand le CR parle retail/ops (_retail_kw14) ;
        # helper pur module-level pour testabilité.
        _sc_tile = _sc_synth_tile_label_b1318(sc, data, sc_signal)
        # v62.6 — un scénario illustratif d'entreprise n'est jamais une
        # métrique exécutive. La croissance marché est un objet distinct : elle
        # ne peut pas être affichée comme « sous-KPI » du CA de l'entreprise.
        _ca_fallback = "Not disclosed" if lang == "en" else "Non communiqué"
        _growth_fallback = "To establish — report" if lang == "en" else "À établir — CR"
        _ca_exec = _h2_safe_kpi_value(cc.get("ca"), _ca_fallback)
        _growth_exec = _h2_safe_kpi_value(cc.get("croissance"), _growth_fallback)
        if data.get("current_financial_state_established") is False:
            # v62.12.1 (ChatGPT §5 — P1 vérité utilisateur) : sous gate fermé,
            # AUCUN chiffre historique ne se présente comme photographie
            # courante. Bannière fail-closed, mêmes composants, même géométrie.
            _lup = str(data.get("latest_confirmed_period_end") or "")
            _lup_lbl = ((f"to {_lup}" if lang == "en" else f"au {_lup}")
                        if _lup else ("see report" if lang == "en" else "voir CR"))
            metrics = [
                ("NOT ESTABLISHED",
                 "Current financial position" if lang == "en" else "Position financière courante",
                 C_GOLD),
                (_lup_lbl,
                 "Latest usable historical period" if lang == "en" else "Dernière période historique",
                 C_TEAL),
                (_sc_tile, "Supply Chain", C_GREEN),
            ]
        else:
            metrics = [
                (_ca_exec, SL("synth_ca_indic", lang), C_GOLD),
                (_growth_exec, SL("growth_label",lang), C_TEAL),
                (_sc_tile, "Supply Chain", C_GREEN),
            ]
    else:
        metrics = [
            (d_marche.get("taille",     "n/d"),   SL("market_label",lang),  C_GOLD),
            (d_marche.get("croissance", "n/d"), SL("growth_label",lang), C_TEAL),
            (SL("positioning_label",lang),                           SL("differentiation_label",lang), C_GREEN),
        ]

    # v16.5.67.9 — En mode GENERIC, les chiffres-clés des pastilles viennent
    # d'un LLM qui a inventé des ordres de grandeur sans aucune source.
    # On ajoute un tag visuel au label pour que le lecteur client ne les
    # prenne pas pour des faits sourcés. Le suffixe "⚠" attire l'œil sans
    # alourdir visuellement (l'espace label est contraint à 8pt).
    # Exception : "Supply Chain" en mode corporate qui porte sa propre
    # sémantique (SAIN / SOUS TENSION / DÉGRADÉ) — pas de tag nécessaire.
    _is_generic = str(data.get("brief_mode", "")).strip().upper() == "GENERIC"
    if _is_generic:
        _tag_suffix = " ⚠" if lang == "fr" else " ⚠"
        metrics = [
            (val, lbl + _tag_suffix if lbl not in ("Supply Chain",) else lbl, color)
            for (val, lbl, color) in metrics
        ]
    # v62.13.9.4.27 — contre-audit v25 (§4, slide Conclusion) : sur un dossier
    # sans supply chain (deck construit depuis les objets, sujet absent), la
    # tuile « Supply Chain : NON EXÉCUTÉE » n'apporte rien : elle laisse la place
    # à l'effectif de registre quand il existe, sinon elle est omise.
    if (str(data.get("_built_from") or "") == "analysis_objects"
            and "supply_chain" not in [str(x) for x in (data.get("_topics") or [])]):
        _eff27 = str(((data.get("contexte_corporate") or {}).get("effectif") or "")).strip()
        metrics = [m for m in metrics if m[1] != "Supply Chain"]
        if _eff27:
            metrics.append((_format_headcount_card(_eff27, lang), SL("ctx_headcount", lang), C_GREEN))
        m_total_h = len(metrics) * mh + max(0, len(metrics) - 1) * mgap
        m_start_y = cy + off2 + (m_cr - m_total_h) / 2
    for i, (val, lbl, color) in enumerate(metrics):
        my = m_start_y + i * (mh + mgap)
        mx = m_ctr - mw / 2
        # Cercle de fond (carré arrondi simulé par un ovale)
        s_m = slide.shapes.add_shape(9, Inches(mx + 0.35), Inches(my),
                                     Inches(mw - 0.7), Inches(mh - 0.1))
        s_m.fill.solid()
        s_m.fill.fore_color.rgb = _rgb(0x14, 0x1A, 0x4A)
        s_m.line.color.rgb = color
        s_m.line.width = Pt(2.2)
        # Valeur — pas de troncature, taille adaptée
        val_str = str(val)
        pt_v = _auto_font(val_str, mw - 0.1, 0.48, max_pt=16, min_pt=9)
        _add_text(slide, val_str, mx, my + 0.06, mw, 0.48,
                  font_size=pt_v, bold=True, color=color, align=PP_ALIGN.CENTER)
        # Label
        _add_text(slide, lbl, mx, my + 0.58, mw, 0.28,
                  font_size=8, color=C_MID_GRAY, align=PP_ALIGN.CENTER)

    # ── Contenu textuel gauche ───────────────────────────────────────────────
    # Tag
    _add_rect(slide, 0.28, 0.42, 3.2, 0.36, C_GOLD)
    _add_text(slide, SL("exec_summary", lang), 0.28, 0.42, 3.2, 0.36,
              font_size=10, bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)

    # Headline
    headline = _clean_bullet_full(str(concl.get("headline", "Conclusion"))) or "Conclusion"
    pt_h = _auto_font(headline, 5.35, 1.15, max_pt=28, min_pt=14)
    _add_text(slide, headline, 0.28, 0.92, 5.35, 1.15,
              font_size=pt_h, bold=True, color=C_WHITE, font_name="Calibri",
              role="HCRIT:conclusion:headline")

    # Séparateur
    _add_rect(slide, 0.28, 2.2, 4.8, 0.04, _rgb(0x3A, 0x46, 0x8A))

    # 3 points clés
    badge_colors = [C_GOLD, C_TEAL, C_GREEN]
    for i, pt in enumerate(concl.get("points", [])[:3]):
        py = 2.34 + i * 0.72
        clean_pt = _clean_bullet(str(pt), 72)
        color = badge_colors[i]
        # Pastille ronde
        s_dot = slide.shapes.add_shape(9, Inches(0.28), Inches(py + 0.06),
                                       Inches(0.36), Inches(0.36))
        s_dot.fill.solid()
        s_dot.fill.fore_color.rgb = color
        s_dot.line.fill.background()
        _add_text(slide, str(i+1), 0.28, py + 0.06, 0.36, 0.36,
                  font_size=13, bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)
        pt_sz = _auto_font(clean_pt, 4.8, 0.5, max_pt=12, min_pt=8)
        _add_text(slide, clean_pt, 0.76, py, 4.8, 0.5,
                  font_size=pt_sz, color=C_ICE_BLUE)

    # Pied de page — bande navy + contact
    _add_rect(slide, 0, 5.18, 10, 0.445, _rgb(0x0D, 0x11, 0x30))
    _add_rect(slide, 0, 5.18, 10, 0.04, C_GOLD)
    contact = str(concl.get("contact",
                             SL("codir_synth", lang)))
    _add_text(slide, contact, 0.28, 5.22, 9.44, 0.36,
              font_size=10, color=C_MID_GRAY, align=PP_ALIGN.CENTER)
    _pgnum(slide, len(prs.slides), _synth_ref("conclusion", data, lang if "lang" in dir() else data.get("lang", "fr")))


# ───────────────────────────────────────────────────────────────────────────────
# 5. POINT D'ENTRÉE
# ───────────────────────────────────────────────────────────────────────────────

_CODE_ARTIFACT_RE = re.compile(r"""^[\s'"\)\(\[\]\{\}\\n\r]+""")

# F.6.10 (audit dossier réseau de soins F.6.9) — humanise les tags épistémiques internes en
# mentions LISIBLES dans le deck. Gère formes BIEN FORMÉES et ORPHELINES.
_TAG_HUMANIZE = [
    (re.compile(r"\[?\s*ESTIM[\s\-]*HYPOTH[ÈE]SE\s*\]", re.I), "(hypothèse à valider)"),
    (re.compile(r"\[?\s*ESTIM[\s\-]*FILINGS?\s*\]", re.I),     "(estimé d'après pièces)"),
    (re.compile(r"\[?\s*ESTIM[\s\-]*COMPARABLE\s*\]", re.I),   "(estimé par comparable)"),
    (re.compile(r"\[?\s*NON\s*SOURC[ÉE]\s*\]", re.I),          "(non sourcé)"),
    (re.compile(r"\[?\s*REF\s*SECT\.?\s*\]", re.I),            "(réf. sectorielle)"),
    (re.compile(r"\[?\s*À?\s*D[ÉE]FINIR\s*\]", re.I),          "(à définir)"),
    (re.compile(r"\[?\s*À?\s*V[ÉE]RIFIER\s*\]", re.I),         "(à vérifier)"),
    (re.compile(r"\[?\s*FAIT\s*\]", re.I),                     "(donnée du brief)"),
]


def _humanize_epistemic_tags(text: str) -> str:
    if not text or not isinstance(text, str):
        return text
    for rx, repl in _TAG_HUMANIZE:
        text = rx.sub(repl, text)
    return re.sub(r"\s{2,}", " ", text).strip()


def _board_safe_text(text: str) -> str:
    """Artefacts code + codes SC + balises cassées, puis humanisation des tags."""
    return _humanize_epistemic_tags(_strip_code_artifacts(str(text)))


def _board_safe_field(val):
    if isinstance(val, str):
        return _board_safe_text(val)
    if isinstance(val, list):
        return [_board_safe_text(x) if isinstance(x, str) else x for x in val]
    return val


def _strip_code_artifacts(text: str) -> str:
    """
    Fix v16.5.28 — Supprime les artefacts de code en début de chaîne.
    Ex: \"')\\n1 000 connexions\" → \"1 000 connexions\"
    B.1.3.1 (bloquant 1 audit, défense en profondeur) — le deck retire AUSSI
    les blocs AGENT_JSON/JSON/AUDIT : si le CR amont fuit, le deck reste
    étanche (même scrub PUR que le moteur : utils/json_scrub).
    """
    try:
        from utils.json_scrub import strip_agent_json_blocks
        text = strip_agent_json_blocks(str(text))
    except Exception:
        pass
    text = _CODE_ARTIFACT_RE.sub("", str(text)).strip()
    # Supprimer aussi les artefacts JSON résiduels courants
    text = re.sub(r"^None\b\s*", "", text).strip()
    # F.6.8 (P2, audit ChatGPT) — artefacts de l'agent Supply Chain dans le deck :
    #  • codes de section SC-1..SC-5 (parfois « [SC-2 [NON SOURCÉ]] ») → retirés ;
    #  • crochets doublés « ]] » → « ] » ; balise « FAIT] » orpheline → retirée ;
    #  • « [NON SOURCÉ] » normalisé (lisible, pas cassé).
    text = re.sub(r"\[?\s*SC-\d\b\s*\]?", " ", text)
    text = re.sub(r"\]\s*\]", "]", text)
    text = re.sub(r"\s*\bFAIT\]", "", text)
    text = re.sub(r"\[\s*NON\s*SOURC[ÉE]\s*\]", "[non sourcé]", text, flags=re.I)
    text = re.sub(r"\s{2,}", " ", text).strip(" -–—|")
    return text


def _normalize_plan_action_items(items: list) -> list:
    """
    Fix v16.5.28/15 — Normalise les items plan_actions quand l'IA stocke la ligne
    pipe complète dans le champ 'action' au lieu de la parser.
    Supprime également les artefacts de code (') etc.) de tous les champs.

    Cas détectés :
    - action contient " | " avec "KPI" → re-parser le format pipe
    - action commence par "ACTION:" ou "ACTION :" → supprimer le préfixe
    - kpi ou délai commencent par artefacts ') " etc. → nettoyer
    - délai vide, null, ou "…" → laisser vide (géré par le rendu)
    """
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        action_raw = _strip_code_artifacts(str(item.get("action", "")))
        kpi_raw    = _strip_code_artifacts(str(item.get("kpi",    "")))
        delai_raw  = _strip_code_artifacts(str(item.get("delai",  "")))

        # Cas 1 — ligne pipe complète dans le champ action
        if " | " in action_raw and any(k in action_raw.upper() for k in ["KPI", "KPI :"]):
            parts = {}
            for segment in action_raw.split(" | "):
                if ":" in segment:
                    k, v = segment.split(":", 1)
                    parts[k.strip().upper()] = _strip_code_artifacts(v)
            action_raw = parts.get("ACTION", action_raw)
            kpi_raw    = parts.get("KPI",    kpi_raw) or kpi_raw
            delai_raw  = parts.get("DÉLAI",  parts.get("DELAI", delai_raw)) or delai_raw

        # Cas 2 — préfixe "ACTION:" littéral
        action_raw = re.sub(r"^ACTION\s*:\s*", "", action_raw, flags=re.IGNORECASE).strip()

        # Cas 3 — délai dégénéré ("…", "None", ponctuation seule)
        if not delai_raw or delai_raw in {"…", ".", "None", "null"}:
            delai_raw = ""

        # Cas 4 — kpi dégénéré : "…", trop court (<4 chars), ou placeholder
        _KPI_NOISE = {"…", ".", "none", "null", "kpi", "kpi à confirmer", "kpi to confirm", "kpi:"}
        if kpi_raw.lower() in _KPI_NOISE or (len(kpi_raw) < 4 and not kpi_raw.isdigit()):
            kpi_raw = ""

        result.append({"action": action_raw, "kpi": kpi_raw, "delai": delai_raw})
    return result


def _enrich_commercial_if_empty(data: dict, cr_text: str,
                                extra_context: dict | None = None) -> None:
    """
    Option B — v16.5.28.
    Priorité absolue : si commercial_json (extrait directement depuis Grok) est
    présent dans extra_context, il écrase entièrement le bloc commercial produit
    par la couche 2 (IA de structuration JSON). La couche 2 est court-circuitée.

    Sinon : fallback sur le bloc JSON IA + complétion heuristique si incomplet.
    Mutation in-place sur data["commercial"].
    """
    extra_context = extra_context or {}

    # ── Priorité 1 : JSON commercial direct Grok (Option B) ───────────────────
    comm_json = extra_context.get("commercial_json") \
        if isinstance(extra_context.get("commercial_json"), dict) else None

    if isinstance(comm_json, dict):
        payload = _extract_commercial_payload(cr_text, extra_context=extra_context, lang=data.get("lang","fr"), deck_type=data.get("deck_type",""))
        pa = payload.get("plan_actions") or []
        opps = payload.get("opportunites") or []
        if pa and opps and any(str(a.get("action", "")).strip() for a in pa):
            data["commercial"] = payload
            return  # ← sortie propre, couche 2 ignorée

    # ── Priorité 2 : complétion du JSON IA si incomplet ──────────────────────
    comm = data.get("commercial")
    if not isinstance(comm, dict):
        data["commercial"] = _extract_commercial_payload(cr_text, lang=data.get("lang","fr"), deck_type=data.get("deck_type",""))
        return

    # Normaliser plan_actions (nettoyage artefacts, re-parsing pipe)
    pa = _normalize_plan_action_items(comm.get("plan_actions") or [])
    # Forcer délais progressifs si identiques ou manquants
    delais = [str(item.get("delai", "")).strip() for item in pa]
    if len(set(d for d in delais if d)) <= 1 and pa:
        for i, item in enumerate(pa):
            item["delai"] = f"T{i + 1}"
    comm["plan_actions"] = pa

    fallback = None

    if not any(isinstance(a, dict) and str(a.get("action", "")).strip() for a in pa):
        fallback = fallback or _extract_commercial_payload(cr_text, lang=data.get("lang","fr"), deck_type=data.get("deck_type",""))
        comm["plan_actions"] = fallback["plan_actions"]

    if not any(str(x).strip() for x in (comm.get("challenges_marketing") or [])):
        fallback = fallback or _extract_commercial_payload(cr_text, lang=data.get("lang","fr"), deck_type=data.get("deck_type",""))
        comm["challenges_marketing"] = fallback["challenges_marketing"]

    if not any(str(x).strip() for x in (comm.get("challenges_finance") or [])):
        fallback = fallback or _extract_commercial_payload(cr_text, lang=data.get("lang","fr"), deck_type=data.get("deck_type",""))
        comm["challenges_finance"] = fallback["challenges_finance"]

    if not any(str(x).strip() for x in (comm.get("opportunites") or [])):
        fallback = fallback or _extract_commercial_payload(cr_text, lang=data.get("lang","fr"), deck_type=data.get("deck_type",""))
        comm["opportunites"] = fallback["opportunites"]


def _enrich_marche_if_incomplete(data: dict) -> None:
    """
    Fix v16.5.28 — complète drivers et segments si l'IA en a retourné moins de 4.
    Mutation in-place sur data["marche"].
    """
    _driver_fallbacks = [
        {"pct": "—", "label": "Transformation digitale / IA"},
        {"pct": "—", "label": "Restructuration / retournement"},
        {"pct": "—", "label": ("ESG & decarbonation transitions" if data.get("lang","fr")=="en" else "Transitions RSE & décarbonation")},
        {"pct": "—", "label": "Successions & croissance externe"},
    ]
    _segment_fallbacks = [
        {"nom": "ETI industrielles",    "pct": "—", "etoiles": 4},
        {"nom": "PME en croissance",    "pct": "—", "etoiles": 4},
        {"nom": "Filiales de groupes",  "pct": "—", "etoiles": 3},
        {"nom": "Secteur public",       "pct": "—", "etoiles": 2},
    ]
    marche = data.get("marche")
    if not isinstance(marche, dict):
        return
    # Compléter drivers jusqu'à 4
    drivers = marche.get("drivers") or []
    drivers = [d for d in drivers if isinstance(d, dict) and str(d.get("label", "")).strip()]
    while len(drivers) < 4:
        drivers.append(_driver_fallbacks[len(drivers)])
    marche["drivers"] = drivers[:4]
    # Compléter segments jusqu'à 4
    segments = marche.get("segments") or []
    segments = [s for s in segments if isinstance(s, dict) and str(s.get("nom", "")).strip()]
    while len(segments) < 4:
        segments.append(_segment_fallbacks[len(segments)])
    marche["segments"] = segments[:4]


def _slide_contexte_corporate(prs, data):
    """
    Chantier 2 — v16.5.28.
    Slide 2 du deck CORPORATE : remplace _slide_marche.
    Affiche CA, situation, contexte clé — pas de TJM ni de segmentation missions.
    """
    lang = data.get("lang", "fr")  # v16.5.59 — fix NameError
    cc = data.get("contexte_corporate") or {}
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_LIGHT_GRAY
    _add_header(slide, "🏭", _h2_title("context", data, lang, SL("ctx_diag_title", lang)),
                SL("codir_synth", lang) + " · " + str(data.get("date", "2026")))

    # ── KPIs haut : CA / Effectif / Situation ──────────────────────────────
    # v62.6 — le CA illustratif et la croissance marché ne partagent jamais
    # une même carte. Sans fait d'entreprise, le CA reste explicitement à
    # collecter ; la tendance marché vit dans le CR / la slide de preuves.
    _ca_fallback = "Not disclosed" if lang == "en" else "Non communiqué"
    _ca_sub_fallback = "Not available — collect" if lang == "en" else "Non disponible — à collecter"
    if data.get("current_financial_state_established") is False:
        # v62.12.1 (ChatGPT §5) — pas de CA « courant » quand le gate est fermé.
        _ne_val = "NOT ESTABLISHED"
        _ne_sub = ("Current position not established — see report" if lang == "en"
                   else "Position courante non établie — voir CR")
        cc = dict(cc); cc["ca"] = _ne_val; cc["ca_sub"] = _ne_sub
    _ca_raw = _sanitize_slide_text(cc.get("ca", ""), 1000, "")
    _ca_exec = _h2_safe_kpi_value(_ca_raw, _ca_fallback)
    _ca_sub = "" if _ca_exec != _ca_fallback else _ca_sub_fallback
    _kpi_meta = cc.get("financial_kpi_metadata") or {}
    _ca_meta = _kpi_meta.get("ca") if isinstance(_kpi_meta, dict) else None
    _ca_label = str((_ca_meta or {}).get("label") or SL("ctx_ca", lang))
    try:                                                   # v62.13.9.4.48 — libellé monolingue
        from utils.financial_facts_table import monolingual_metric_label as _mml48
        _ca_label = _mml48(_ca_label, lang)
    except Exception:
        pass
    if _ca_meta and str((_ca_meta or {}).get("proof_status") or "").upper() in {"CONFIRMED_ON_PAGE", "DERIVED_FROM_CONFIRMED_ON_PAGE"}:
        _ca_sub = ""
    kpis = [
        (_ca_exec, _ca_label, _ca_sub),
        (_format_headcount_card(cc.get("effectif", ""), lang),       SL("ctx_headcount", lang),  SL("ctx_collaborateurs", lang)),
        (_h2_exec(_sanitize_slide_text(cc.get("situation", ""), 1000, "—"), lang),   SL("ctx_situation", lang),  ""),
    ]
    cw, ch, cy, gap, sx = 2.8, 1.32, 1.22, 0.22, 0.3
    for i, (val, label, sub) in enumerate(kpis):
        cx = sx + i * (cw + gap)
        _add_rect(slide, cx, cy, cw, ch, C_WHITE)
        _add_rect(slide, cx, cy, cw, 0.07, C_GOLD)
        pt_v = _auto_font(str(val), cw - 0.1, 0.45, max_pt=18, min_pt=10)
        _role = "HCRIT:context:situation" if i == 2 else f"HCRIT:context:kpi:{i}"
        _add_text(slide, str(val), cx, cy + 0.12, cw, 0.52,
                  font_size=max(11, pt_v), bold=True, color=C_NAVY, align=PP_ALIGN.CENTER,
                  role=_role)
        _add_text(slide, label, cx, cy + 0.65, cw, 0.28,
                  font_size=10, bold=True, color=C_TEXT_DARK, align=PP_ALIGN.CENTER)
        if sub:
            _add_text(slide, str(sub), cx, cy + 0.93, cw, 0.28,
                      font_size=_auto_font(str(sub),cw,0.28,max_pt=9,min_pt=8),
                      italic=True, color=C_MID_GRAY, align=PP_ALIGN.CENTER,
                      role=f"HCRIT:context:kpi-sub:{i}")

    # ── Risques prioritaires (gauche) ───────────────────────────────────────
    _add_rect(slide, 0.25, 2.72, 4.7, 2.62, C_WHITE)
    _add_rect(slide, 0.25, 2.72, 4.7, 0.40, C_ORANGE)
    _add_text(slide, ("⚠ HIGH-PRIORITY RISKS" if lang=="en" else "⚠ RISQUES PRIORITAIRES"), 0.25, 2.72, 4.7, 0.40,
              font_size=11, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)
    risks = _h2_sorted_structured_risks(data)
    for i, risk in enumerate(risks[:3]):
        ry = 3.22 + i * 0.62
        label = _h2_exec(_clean_bullet_full(str(risk.get("label", ""))), lang)
        if not label:
            continue
        prob = str(risk.get("probabilite", "")).lower().strip()
        imp  = str(risk.get("impact", "")).strip()
        col  = _risk_level_color(prob)
        _add_rect(slide, 0.35, ry + 0.12, 0.22, 0.22, col)
        pt_l = _auto_font(label, 3.95, 0.38, max_pt=11, min_pt=11)
        _add_text(slide, label, 0.68, ry, 3.95, 0.38, font_size=pt_l, bold=True,
                  color=C_TEXT_DARK, role=f"HCRIT:risk:item:{i}")
        badge = (f"{_loc_risk_level(prob, lang)} / {_loc_risk_level(imp, lang)}"
                 if imp else _loc_risk_level(prob, lang))
        _add_text(slide, badge, 0.68, ry + 0.39, 3.95, 0.18,
                  font_size=8, italic=True, color=C_MID_GRAY)
    _add_coverage_note(slide,min(3,len(risks)),len(risks),0.68,5.08,3.95,lang)

    # ── Arbitrages DG (droite) ──────────────────────────────────────────────
    _add_rect(slide, 5.2, 2.72, 4.55, 2.62, C_WHITE)
    _add_rect(slide, 5.2, 2.72, 4.55, 0.40, C_NAVY)
    _add_text(slide, SL("arbitrages_to_decide", lang), 5.2, 2.72, 4.55, 0.40,
              font_size=11, bold=True, color=C_GOLD, align=PP_ALIGN.CENTER)
    arbitrages = [a for a in (cc.get("arbitrages") or []) if str(a).strip()]
    for i, arb in enumerate(arbitrages[:2]):
        ay = 3.22 + i * 0.62
        clean = _h2_exec(_clean_bullet_full(str(arb)), lang)
        if not clean:
            continue
        _add_rect(slide, 5.30, ay + 0.12, 0.20, 0.20, C_GOLD)
        _add_text(slide, str(i + 1), 5.30, ay + 0.12, 0.20, 0.20,
                  font_size=9, bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)
        pt_a = _auto_font(clean, 3.95, 0.48, max_pt=11, min_pt=11)
        _add_text(slide, clean, 5.58, ay, 3.95, 0.48, font_size=pt_a,
                  color=C_TEXT_DARK, role=f"HCRIT:arbitration:item:{i}")
    _add_coverage_note(slide,min(2,len(arbitrages)),len(arbitrages),5.58,5.08,3.95,lang)

    _pgnum(slide, len(prs.slides))


def _slide_risques_arbitrages(prs, data):
    """H2-R2/R3/R4 — 3 risques classés + 2 arbitrages, jamais 10 puces.

    La slide précédente présentait trois colonnes hétérogènes et jusqu'à dix
    messages. La version H2 .58 assume une seule assertion : les trois risques
    qui structurent la décision et les deux arbitrages qui doivent suivre.
    """
    lang = data.get("lang", "fr")
    cc = data.get("contexte_corporate") or {}
    swot = data.get("swot") or {}
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb = C_DARK_NAVY
    _add_header(slide, "⚖️", _h2_title("risks", data, lang,
                SL("risks_arbitrages_title", lang)), SL("risks_arbitrages_sub", lang))

    # Trois risques : source structurée classée, puis repli SWOT.
    typed = _h2_sorted_structured_risks(data)
    risk_items = []
    for r in typed:
        label = str(r.get("label") or "").strip()
        if label:
            risk_items.append((label, str(r.get("probabilite") or ""), str(r.get("impact") or "")))
    # Complète avec le SWOT sans doublon pour tracer la coupe Top-3 sur M.
    seen = {x[0].strip().lower() for x in risk_items}
    for raw in (swot.get("risques") or []):
        label = str(raw).strip()
        if label and label.lower() not in seen:
            risk_items.append((label, "", "")); seen.add(label.lower())
    shown_risks = risk_items[:3]
    _add_rect(slide, 0.28, 1.25, 9.44, 0.42, C_RED)
    _add_text(slide, "3 RISQUES QUI STRUCTURENT LA DÉCISION" if lang != "en"
              else "3 RISKS SHAPING THE DECISION", 0.28, 1.25, 9.44, 0.42,
              font_size=12, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)
    for i, (label, prob, impact) in enumerate(shown_risks):
        y = 1.86 + i * 0.62
        clean = _h2_exec(label, lang)
        _add_rect(slide, 0.42, y + 0.08, 0.28, 0.28, C_RED if i == 0 else C_ORANGE)
        _add_text(slide, str(i + 1), 0.42, y + 0.08, 0.28, 0.28,
                  font_size=11, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)
        _add_text(slide, clean, 0.84, y, 6.65, 0.44, font_size=11,
                  color=C_WHITE, role=f"HCRIT:risks-slide:risk:{i}")
        badge = " / ".join(x for x in (_loc_risk_level(prob, lang), _loc_risk_level(impact, lang)) if x)
        if badge:
            _add_text(slide, badge, 7.65, y, 1.75, 0.44, font_size=11,
                      italic=True, color=C_GOLD, align=PP_ALIGN.RIGHT)
    _add_coverage_note(slide, min(3, len(risk_items)), len(risk_items),
                       0.84, 3.66, 8.2, lang)

    # Deux arbitrages seulement : le n°1 est déjà repris dans L'Essentiel.
    arbitrages = [str(x).strip() for x in (cc.get("arbitrages") or []) if str(x).strip()]
    if not arbitrages:
        arbitrages = [str(x).strip() for x in (data.get("decisions_codir") or []) if str(x).strip()]
    _add_rect(slide, 0.28, 3.92, 9.44, 0.42, C_GOLD)
    _add_text(slide, "2 ARBITRAGES À TRANCHER" if lang != "en" else "2 DECISIONS TO MAKE",
              0.28, 3.92, 9.44, 0.42, font_size=12, bold=True,
              color=C_DARK_NAVY, align=PP_ALIGN.CENTER)
    for i, item in enumerate(arbitrages[:2]):
        y = 4.48 + i * 0.44
        clean = _h2_exec(item, lang)
        _add_text(slide, f"{i+1}. {clean}", 0.62, y, 8.7, 0.36,
                  font_size=11, color=C_WHITE,
                  role=f"HCRIT:risks-slide:arbitration:{i}")
    _add_coverage_note(slide, min(2, len(arbitrages)), len(arbitrages),
                       0.62, 5.18, 8.1, lang)
    _pgnum(slide, len(prs.slides), _synth_ref("arbitration", data, lang if "lang" in dir() else data.get("lang", "fr")))


def _count_signal_hits(text: str, patterns: list[str]) -> int:
    hits = 0
    for pat in patterns:
        if re.search(pat, text, flags=re.IGNORECASE):
            hits += 1
    return hits


def _detect_deck_type(data: dict, report_text: str = "", extra_context: dict | None = None) -> str:
    """Détection hybride : JSON IA + signaux textuels du brief/CR."""
    extra_context = extra_context or {}
    dt = str(data.get("deck_type", "")).strip().lower()
    cc = data.get("contexte_corporate") or {}
    if dt == "corporate" and (cc.get("ca") or cc.get("situation") or cc.get("risques_top") or cc.get("arbitrages")):
        return "corporate"

    text_blob = "\n".join([
        str(data.get("titre", "")),
        str(data.get("sous_titre", "")),
        str(data.get("entreprise", "")),
        report_text or "",
    ]).lower()
    corporate_patterns = [
        r"\bgroupe\b", r"\bcodir\b", r"\bdg\b", r"\bt1\b", r"\bca\b", r"chiffre d'affaires",
        r"résultats?", r"marge", r"\bbfr\b", r"supply chain", r"stocks?", r"pricing",
        r"plan d['’]économies", r"marques?", r"g[ée]ographies?", r"ebit", r"cash"
    ]
    solo_patterns = [
        r"\btjm\b", r"mission", r"prescripteur", r"manager de transition", r"cabinet", r"consultant",
        r"ind[ée]pendant", r"couverture nationale", r"leads?", r"sasu"
    ]
    corp_hits = _count_signal_hits(text_blob, corporate_patterns)
    solo_hits = _count_signal_hits(text_blob, solo_patterns)
    if corp_hits >= 3 and corp_hits >= solo_hits + 1:
        return "corporate"
    if solo_hits >= 2 and solo_hits > corp_hits:
        return "solo"
    if dt in {"solo", "corporate"}:
        return dt
    return "corporate" if _sc_material_signal(text_blob) else "solo"

def _enrich_corporate_context_if_needed(data: dict, report_text: str) -> None:
    cc = data.get("contexte_corporate") or {}
    if not isinstance(cc, dict):
        cc = {}
    txt = report_text or ""
    if not cc.get("ca"):
        # v16.5.28 — patterns CA élargis : Md€, M€, Md$, M$, milliards, billions
        _ca_pattern = re.compile(
            r"(\d[\d\s,\.]*\s*(?:Md€|M€|Md\$|M\$|milliards?|billions?))",
            re.IGNORECASE
        )
        m = _ca_pattern.search(txt)
        if m:
            cc["ca"] = m.group(1).strip()
        else:
            # Fallback : chercher "revenus" ou "chiffre d'affaires" suivi d'un chiffre
            m2 = re.search(
                r"(?:revenus?|chiffre d.affaires?|sales|revenue)[^\d]{0,20}(\d[\d\s,\.]*\s*(?:Md|M|G|B|k)?[€$]?)",
                txt, re.IGNORECASE
            )
            if m2:
                cc["ca"] = m2.group(1).strip()
    if not cc.get("effectif"):
        # v16.5.28 — extraction effectif depuis le texte si non fourni par l'IA
        m_eff = re.search(
            r"(\d[\d\s]*(?:\s*000)?)\s*(?:collaborateurs?|employés?|salariés?|employees?|people|workforce|ETP|FTE)",
            txt, re.IGNORECASE
        )
        if m_eff:
            cc["effectif"] = m_eff.group(1).strip().replace(" ", " ")
        m = re.search(r"(croissance.{0,45})", txt, re.IGNORECASE)
        m = re.search(r"(croissance[^\\n\\r]{0,45})", txt, re.IGNORECASE)
        if m:
            cc["croissance"] = _clean_bullet(m.group(1), 32)
    if not cc.get("situation"):
        for ln in _clean_lines(txt, 90):
            if any(k in ln.lower() for k in ["rentabil", "cash", "bfr", "supply chain", "pricing", "portefeuille"]):
                cc["situation"] = _clean_bullet(ln, 42)
                break
    if not cc.get("risques_top"):
        risks = []
        for ln in _clean_lines(txt, 80):
            low = ln.lower()
            if any(k in low for k in ["risque", "rupture", "surstock", "tarif", "devise", "bfr", "til-ch", "pricing"]):
                risks.append({
                    "label": _clean_bullet(ln, 42),
                    "probabilite": "élevée" if any(k in low for k in ["rupture", "surstock", "tarif", "bfr"]) else "moyenne",
                    "impact": "élevé" if any(k in low for k in ["cash", "marge", "service", "disponibil"]) else "moyen",
                })
            if len(risks) >= 3:
                break
        if risks:
            cc["risques_top"] = risks
    if not cc.get("arbitrages") and str(data.get("_built_from") or "") != "analysis_objects":   # v62.13.9.4.29 — jamais une décision ou une action à la place d'un arbitrage
        arbs = []
        for ln in _clean_lines(txt, 80):
            low = ln.lower()
            if any(k in low for k in ["arbitrage", "service", "stock", "cash", "marge", "pricing", "portefeuille"]):
                arbs.append(_clean_bullet(ln, 55))
            if len(arbs) >= 4:
                break
        if arbs:
            cc["arbitrages"] = arbs
    data["contexte_corporate"] = cc


# ─────────────────────────────────────────────────────────────────────────────
# v17.1.0-B2.3-F.4 — Slides CoDIR : Registre d'actions & Faits marché sourcés
# Rendues UNIQUEMENT si les données existent (injectées via extra_context →
# data["agenda_register"] / data["web_facts_ledger"]). Fail-open : toute erreur
# est avalée, la génération du deck continue.
# ─────────────────────────────────────────────────────────────────────────────
def _result_meta51(extra_context, key: str, default=""):
    """9.4.51 — une donnée du run rangée par le moteur au premier niveau du résultat OU dans son sous-ensemble « meta »
    (recette du 02/10/2026 : la date de clôture et les faits SEC étaient cherchés au premier niveau seulement, d'où
    l'absence de « dernier publié » sur les cartes)."""
    r = (extra_context or {}).get("result") or {}
    if isinstance(r, dict):
        v = r.get(key)
        if v in (None, "", [], {}):
            v = (r.get("meta") or {}).get(key) if isinstance(r.get("meta"), dict) else None
        return v if v not in (None,) else default
    return default


def _fill_headcount51(data: dict, extra_context, lang: str = "fr") -> None:
    """9.4.51 — un effectif écrit « Non communiqué » par un agent, alors que les pièces le donnent, est complété par
    l'effectif lu dans les pièces (aucune estimation : seulement une formule de rapport annuel)."""
    try:
        cc = data.get("contexte_corporate")
        if not isinstance(cc, dict):
            return
        cur = str(cc.get("effectif") or "").strip()
        # 9.4.59 — recette 9.4.58 : la carte affichait « Non disponible — à collecter » alors que les pièces donnaient
        # l'effectif ; toute valeur SANS chiffre (non disponible, à collecter, N.D., non renseigné…) est complétée
        if cur and re.search(r"\d", cur) and not re.search(
                r"(?i)non\s+communiqu|not\s+disclosed|n/?a\b|^[—–-]$|inconnu|unknown", cur):
            return
        hc = str(_result_meta51(extra_context, "headcount51") or "").strip()
        if hc.isdigit():
            n = f"{int(hc):,}".replace(",", " " if not str(lang).startswith("en") else ",")
            cc["effectif"] = (f"{n} employees (documents provided)" if str(lang).startswith("en")
                              else f"{n} salariés (pièces fournies)")
    except Exception:
        pass


def _format_headcount_card(text: str, lang: str = "fr") -> str:
    """Carte effectif qualifiée, sans fausse précision ni faux périmètre.

    Gate 5 — la modalité (approximation, borne, plage), les séparateurs de
    milliers, le périmètre et la période font partie de la donnée. Les
    métadonnées sont associées au span d'effectif le plus proche ; si plusieurs
    effectifs distincts coexistent dans la même phrase, le renderer conserve le
    texte brut plutôt que d'en choisir arbitrairement un.
    """
    import re as _re
    t = str(text or "").strip()
    if not t:
        return "—"
    en = str(lang or "fr").lower().startswith("en")

    _approx_terms = (
        r"environ|approximativement|approx\.?|autour\s+de|près\s+de|pres\s+de|"
        r"presque|quelque|circa|ca\.?|c\.|de\s+l['’]ordre\s+de|"
        r"plus\s+ou\s+moins|approximately|about|around|roughly|nearly|almost|"
        r"some|more\s+or\s+less|or\s+so|on\s+the\s+order\s+of|in\s+the\s+region\s+of"
    )
    _approx_re = _re.compile(rf"(?:^|\b)(?:{_approx_terms})(?:\b|\s)", _re.I)
    approx = bool(_approx_re.search(t) or _re.search(r"[~≈±]", t))
    _approx_opt = rf"(?:(?:{_approx_terms})\s*)?"
    _approx_after_num = r"(?:(?:or\s+so|environ|approximativement|approximately|about|roughly)\s*)?"

    # Nombre avec séparateurs usuels : espace/NBSP/NNBSP, virgule, point,
    # apostrophe droite ou typographique. Le groupe complet est conservé.
    _num = r"[~≈]?\s*(?:\d{1,3}(?:[\s\u00a0\u202f,.'’]\d{3})+|\d+)"
    _unit = (r"(?:employees?|collaborateurs?|salari[ée]s?|employ[ée]e?s?|"
             r"people|workforce|FTEs?|ETP)\b")

    def _clean_num(value: str) -> str:
        value = _re.sub(r"[\u00a0\u202f]", " ", str(value or ""))
        value = _re.sub(r"\s+", " ", value).strip()
        return value

    def _raw_card() -> str:
        """Fail-safe : préserver le texte quand plusieurs valeurs/périmètres
        sont en concurrence plutôt que fabriquer une carte plus précise que la
        source. Le chantier H dimensionnera ensuite la zone d'affichage."""
        if len(t) <= 72:
            return t
        cut = t.rfind(" ", 0, 72)
        return t[:cut if cut > 30 else 72].rstrip() + "…"

    range_patterns = [
        rf"(?P<lo>{_num})\s*(?:-|–|—|\bà\b|\bto\b|\bthrough\b|\bjusqu['’]à\b)\s*"
        rf"{_approx_opt}(?P<hi>{_num})\s*{_approx_after_num}{_unit}",
        rf"(?:\b(?:effectif\s+compris\s+)?entre\b|\bbetween\b)\s*{_approx_opt}"
        rf"(?P<lo>{_num})\s*(?:\bet\b|\band\b)\s*{_approx_opt}(?P<hi>{_num})\s*{_approx_after_num}{_unit}",
    ]
    rm = None
    for pat in range_patterns:
        rm = _re.search(pat, t, _re.I)
        if rm:
            break
    # Gate 6, intégration Claude — une ÉVOLUTION n'est pas une tranche :
    # « grew from 450 to 500 employees » / « passés de 450 à 500 salariés »
    # décrivent un mouvement temporel ; en fabriquer la plage 450–500
    # présenterait deux instants comme un intervalle d'incertitude. Un verbe
    # d'évolution devant la borne basse impose le texte brut. Les tranches
    # légitimes (« ranging from », « un effectif de 450 à 500 ») restent
    # des tranches.
    if rm:
        _pre_rm = t[max(0, rm.start() - 34):rm.start()]
        if _re.search(
                r"(?:\b(?:grew|rose|climbed|increased|decreased|declined|"
                r"fell|dropped|went|moved|evolved|expanded|shrank|jumped|"
                r"recovered|rebounded|changed|varied|fluctuated|shifted|"
                r"transitioned)\s+from|"
                r"\b(?:up|down)\s+from|"
                r"(?:pass[ée]e?s?|augment[ée]e?s?|mont[ée]e?s?|grimp[ée]e?s?|"
                r"progress[ée]e?s?|chut[ée]e?s?|tomb[ée]e?s?|baiss[ée]e?s?|"
                r"recul[ée]e?s?|[ée]volu[ée]e?s?|r[ée]duits?e?s?|pass[ée]e?|"
                r"chang[ée]e?s?|vari[ée]e?s?|fluctu[ée]e?s?|d[ée]plac[ée]e?s?|"
                r"transform[ée]e?s?)\s+de)\s*$", _pre_rm, _re.I):
            return _raw_card()

    threshold_patterns = [
        (r"\b(?:pas\s+plus\s+de|au\s+plus|au\s+maximum|maximum\s+de|jusqu['’]à)\s+", "≤"),
        (r"\b(?:pas\s+moins\s+de|au\s+moins|au\s+minimum|minimum\s+de)\s+", "≥"),
        (r"\b(?:plus\s+de|davantage\s+de|sup[ée]rieur(?:e)?\s+à)\s+", ">"),
        (r"\b(?:moins\s+de|inf[ée]rieur(?:e)?\s+à)\s+", "<"),
        (r"\b(?:no\s+more\s+than|at\s+most|maximum\s+of|up\s+to)\s+", "≤"),
        (r"\b(?:not\s+less\s+than|no\s+fewer\s+than)\s+", "≥"),
        (r"\b(?:at\s+least|minimum\s+of)\s+", "≥"),
        (r"\b(?:more\s+than|over|above|upwards\s+of|north\s+of)\s+", ">"),
        (r"\b(?:less\s+than|under|below|fewer\s+than)\s+", "<"),
        (r"[≤]", "≤"), (r"[≥]", "≥"), (r"<", "<"), (r">", ">"),
    ]
    threshold = None
    threshold_match = None
    if not rm:
        for pref, symbol in threshold_patterns:
            tm = _re.search(rf"(?:{pref}){_approx_opt}(?P<num>{_num})\s*{_approx_after_num}{_unit}", t, _re.I)
            if tm:
                threshold = symbol + _clean_num(tm.group("num"))
                threshold_match = tm
                break
        if threshold is None:
            pm = _re.search(rf"(?P<num>{_num})\s*\+\s*{_approx_after_num}{_unit}", t, _re.I)
            if pm:
                threshold = _clean_num(pm.group("num")) + "+"
                threshold_match = pm
        if threshold is None:
            smore = _re.search(
                rf"(?P<num>{_num})\s*{_approx_after_num}{_unit}\s*(?:or\s+more|and\s+(?:above|over)|ou\s+plus|et\s+plus|minimum|at\s+least|min\.?|au\s+minimum)\b",
                t, _re.I)
            sfewer = _re.search(
                rf"(?P<num>{_num})\s*{_approx_after_num}{_unit}\s*(?:or\s+(?:fewer|less)|and\s+below|ou\s+moins|et\s+moins|maximum|at\s+most|max\.?|au\s+maximum|au\s+plus)\b",
                t, _re.I)
            if smore:
                threshold = "≥" + _clean_num(smore.group("num")); threshold_match = smore
            elif sfewer:
                threshold = "≤" + _clean_num(sfewer.group("num")); threshold_match = sfewer

    scalar = None
    scalar_match = None
    if not rm and threshold is None:
        sm = _re.search(rf"(?<![\d,.'’])(?P<num>{_num})\s*{_approx_after_num}{_unit}", t, _re.I)
        if sm:
            scalar = _clean_num(sm.group("num")); scalar_match = sm

    selected = rm or threshold_match or scalar_match
    if selected:
        span = selected.span()
        # Plusieurs effectifs distincts dans une phrase : ne jamais choisir une
        # valeur/périmètre par ordre d'apparition. Le texte brut reste plus honnête.
        unit_matches = list(_re.finditer(rf"(?<![\d,.'’])(?P<num>{_num})\s*{_approx_after_num}{_unit}", t, _re.I))
        if len(unit_matches) > 1:
            return _raw_card()

        # Une ventilation secondaire peut omettre l’unité ("500 employees,
        # including 114 in the subsidiary"). Dans ce cas, choisir le scope
        # le plus proche transformerait 500 groupe en 500 filiale. Fail-safe :
        # conserver le texte brut plutôt que fabriquer un périmètre.
        _secondary_breakdown = _re.search(
            r"(?:\b(?:including|of\s+whom|of\s+which|including\s+approximately|dont|"
            r"y\s+compris|parmi(?:\s+lesquels?)?)\b|(?<!\d)[,;](?!\d)|\s-\s)"
            r".{0,45}?\b(?:\d{1,3}(?:[\s\u00a0\u202f,.'’]\d{3})+|\d+)\b"
            r".{0,35}?\b(?:subsidiary|filiale|site|[ée]tablissement|holding|"
            r"group|groupe|company|soci[ée]t[ée])\b", t, _re.I)
        _tail_breakdown = _re.search(
            r"^\s*(?:\(|[—–-])\s*(?:about\s+|approximately\s+|environ\s+)?"
            r"\d{1,3}(?:[\s\u00a0\u202f,.'’]\d{3})*\b.{0,35}?"
            r"\b(?:subsidiary|filiale|site|[ée]tablissement|holding|group|"
            r"groupe|company|soci[ée]t[ée])\b", t[span[1]:], _re.I)
        if _secondary_breakdown or _tail_breakdown:
            return _raw_card()

        # Gate 6 — une seconde quantité sans unité peut décrire une valeur
        # après restructuration, une base de comparaison ou des suppressions
        # de postes. Choisir la première valeur supprimerait précisément le
        # contexte qui en détermine le sens (ex. 8 500 avant 1 700 suppressions,
        # ou 500 en 2024 puis 550 en 2025). Dans ces contextes, texte brut.
        _plain_num = _re.compile(
            r"(?<![\d,.'’])(?:\d{1,3}(?:[\s\u00a0\u202f,.'’]\d{3})+|\d+)(?![\d])")
        _date_spans = [m.span() for m in _re.finditer(
            r"(?<!\d)(?:20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}|"
            r"\d{1,2}[-/.]\d{1,2}[-/.](?:20)?\d{2})(?!\d)", t)]
        _secondary_numbers = []
        for _nm in _plain_num.finditer(t):
            if not (_nm.end() <= span[0] or _nm.start() >= span[1]):
                continue
            if any(a <= _nm.start() and _nm.end() <= b for a, b in _date_spans):
                continue
            _digits = _re.sub(r"\D", "", _nm.group(0))
            try:
                _ival = int(_digits) if _digits else None
            except Exception:
                _ival = None
            _aft = t[_nm.end():_nm.end()+32]
            _bef = t[max(0, _nm.start()-48):_nm.start()]
            # années, pourcentages, dates et montants financiers ne sont pas
            # des effectifs concurrents. Les montants sans symbole (« revenue
            # GBP 100m ») sont identifiés par le contexte métrique local et
            # leur suffixe d'échelle.
            if _ival is not None and 1900 <= _ival <= 2099:
                continue
            if _re.match(r"\s*(?:%|pct|percent|pour\s*cent)\b", _aft, _re.I):
                continue
            if _re.search(r"[€$£]\s*$", _bef) or _re.match(r"\s*[€$£]", _aft):
                continue
            if (_re.search(r"\b(?:revenue|sales|turnover|chiffre\s+d['’]affaires|CA|"
                           r"EBITDA|profit|r[ée]sultat|margin|marge|cash|debt|dette)\b"
                           r"[^,;:.]{0,24}$", _bef, _re.I)
                    and _re.match(r"\s*(?:k|m|mn|bn|million|millions|billion|milliards?)?"
                                  r"\s*(?:€|EUR|GBP|USD|CHF|\$|£)?\b", _aft, _re.I)):
                continue
            if _re.match(r"\s*(?:k|m|mn|bn|million|millions|billion|milliards?)\s*"
                         r"(?:€|EUR|GBP|USD|CHF|\$|£)?\b", _aft, _re.I):
                continue
            # « 3 sites et 450 salariés » : le nombre de sites, placé avant
            # l'effectif, qualifie légitimement son périmètre et n'est pas une
            # valeur d'effectif concurrente. La forme inverse « 500 salariés
            # répartis sur 3 sites » reste ambiguë et conserve le texte brut.
            if (_nm.end() <= span[0]
                    and _re.match(r"\s*(?:sites?|[ée]tablissements?|plants?|factories?)\b",
                                  _aft, _re.I)):
                continue
            _secondary_numbers.append(_nm)
        # Toute seconde quantité ordinaire hors du span sélectionné est une
        # ambiguïté de valeur (évolution, ventilation, nombre de sites,
        # suppressions de postes, sous-population...). Une carte exécutive ne
        # choisit jamais arbitrairement l'une des quantités : elle conserve le
        # texte brut. Les années, pourcentages et montants monétaires ont été
        # exclus ci-dessus.
        if _secondary_numbers:
            return _raw_card()

        if rm:
            num = f"{_clean_num(rm.group('lo'))}–{_clean_num(rm.group('hi'))}"
        else:
            num = threshold if threshold is not None else scalar
        if approx and (rm or threshold is None) and num and not str(num).lstrip().startswith(("~", "≈")):
            num = "≈" + str(num)
        parts = [num]

        _WORD2CODE = {
            "société": "COMPANY", "societe": "COMPANY", "sociétés": "COMPANY",
            "societes": "COMPANY", "company": "COMPANY",
            "companies": "COMPANY", "standalone": "COMPANY", "opco": "COMPANY",
            "filiale": "SUBSIDIARY", "filiales": "SUBSIDIARY",
            "subsidiary": "SUBSIDIARY", "subsidiaries": "SUBSIDIARY",
            "holding": "HOLDING", "holdings": "HOLDING", "groupe": "GROUP",
            "groupes": "GROUP", "group": "GROUP", "groups": "GROUP",
            "établissement": "SITE", "etablissement": "SITE",
            "établissements": "SITE", "etablissements": "SITE", "site": "SITE",
            "sites": "SITE", "entité": "ENTITY", "entite": "ENTITY", "entity": "ENTITY",
            "entities": "ENTITY", "entités": "ENTITY", "entites": "ENTITY",
        }
        scope_re = _re.compile(
            r"\b(soci[ée]t[ée]s?|filiales?|subsidiar(?:y|ies)|standalone|opco|"
            r"compan(?:y|ies)|holdings?|groupes?|groups?|[ée]tablissements?|sites?|"
            r"entit[ée]s?|entities?)\b", _re.I)

        def _distance(m):
            if m.end() <= span[0]:
                return span[0] - m.end()
            if m.start() >= span[1]:
                return m.start() - span[1]
            return 0

        scopes = [(m, _WORD2CODE.get(m.group(1).lower())) for m in scope_re.finditer(t)]
        _distribution_scope = _re.compile(
            r"(?:across|over|throughout|among|between|spread\s+(?:across|over)|"
            r"distributed\s+(?:across|over)|located\s+(?:across|over)|"
            r"r[ée]parti(?:s|es)?\s+(?:sur|entre)|implant[ée](?:s|es)?\s+sur|"
            r"pr[ée]sent(?:s|es)?\s+sur|au\s+sein\s+de)"
            r"(?:\s+(?:the|les?|des?|de\s+la|du))?"
            r"(?:\s+(?:one|two|three|four|five|six|seven|eight|nine|ten|"
            r"un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|\d+|"
            r"multiple|several|various|many|numerous|plusieurs|divers(?:es)?|"
            r"diff[ée]rents?|nombreux|nombreuses))?\s*$",
            _re.I)
        _site_count_prefix = _re.compile(
            r"(?:^|\b)(?:one|two|three|four|five|six|seven|eight|nine|ten|"
            r"un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|\d+|"
            r"multiple|several|various|many|numerous|plusieurs|divers(?:es)?|"
            r"diff[ée]rents?|nombreux|nombreuses)\s*$",
            _re.I)
        _narrow_scope_codes = {"SITE", "SUBSIDIARY", "COMPANY", "ENTITY"}
        _plural_scope = _re.compile(
            r"(?i)(?:sites|[ée]tablissements|filiales|subsidiaries|companies|"
            r"soci[ée]t[ée]s|entities|entit[ée]s)$")
        _scopes_filtered = []
        for m, code in scopes:
            if not code or _distance(m) > 80:
                continue
            # Gate 8 — « 3 sites et 500 salariés » et « 500 employees across
            # three sites » décrivent une DISTRIBUTION, pas le périmètre du
            # total. Un site nommé sans quantité (« 500 salariés au site de
            # Lanvallay ») reste un périmètre SITE valide.
            if code in _narrow_scope_codes:
                _scope_prefix = t[max(0, m.start()-64):m.start()]
                _scope_suffix = t[m.end():m.end()+24]
                _is_plural = bool(_plural_scope.fullmatch(m.group(1)))
                _network_distribution = bool(_re.match(
                    r"\s+(?:network|r[ée]seau|portfolio|portefeuille)\b",
                    _scope_suffix, _re.I))
                if (_is_plural
                        or _distribution_scope.search(_scope_prefix)
                        or _site_count_prefix.search(_scope_prefix)
                        or _network_distribution):
                    continue
            _scopes_filtered.append((m, code))
        scopes = _scopes_filtered
        scope_code = min(scopes, key=lambda x: (_distance(x[0]), 0 if x[0].start() >= span[1] else 1))[1] if scopes else None

        l10n = {
            "fr": {"COMPANY": "société", "SUBSIDIARY": "filiale", "HOLDING": "holding",
                   "GROUP": "groupe", "SITE": "site", "ENTITY": "entité", "FACT": "fait",
                   "ESTIMATE": "estim.", "RANGE": "tranche"},
            "en": {"COMPANY": "company", "SUBSIDIARY": "subsidiary", "HOLDING": "holding",
                   "GROUP": "group", "SITE": "site", "ENTITY": "entity", "FACT": "fact",
                   "ESTIMATE": "estimate", "RANGE": "range"},
        }["en" if en else "fr"]
        if scope_code:
            parts.append(l10n[scope_code])

        years = list(_re.finditer(r"(?i)(?<!\w)(?:FY|CY)?\s*(20\d\d)\b", t))
        nearby_years = []
        for _ym in years:
            # Gate 8 — un effectif de 2024 personnes n'est pas automatiquement
            # un effectif daté de 2024 : si le span année recouvre la valeur
            # d'effectif sélectionnée, il ne qualifie pas sa période.
            if not (_ym.end() <= span[0] or _ym.start() >= span[1]):
                continue
            if _distance(_ym) > 100:
                continue
            _a, _b = sorted((span[1] if _ym.start() >= span[1] else span[0],
                             _ym.start() if _ym.start() >= span[1] else _ym.end()))
            _between = t[_a:_b]
            # Une autre métrique/valeur entre l'effectif et l'année indique que
            # l'année ne qualifie probablement pas l'effectif.
            if _re.search(r"\b(?:revenue|sales|chiffre\s+d['’]affaires|CA|EBITDA|"
                          r"profit|r[ée]sultat|marge|margin)\b", _between, _re.I):
                continue
            if _re.search(r"[€$£]", _between):
                continue
            nearby_years.append(_ym)
        if nearby_years:
            ym = min(nearby_years, key=lambda m: (_distance(m), 0 if m.start() >= span[1] else 1))
            parts.append(ym.group(1))

        if rm or threshold is not None:
            parts.append(l10n["RANGE"])
        if approx or _re.search(r"estim|hypoth", t, _re.I):
            parts.append(l10n["ESTIMATE"])
        elif _re.search(r"\bfait\b|\bfact\b|sourc|annexe|trait[ée]|deed", t, _re.I):
            parts.append(l10n["FACT"])
        return " · ".join(parts)

    if len(t) <= 44:
        return t
    cut = t.rfind(" ", 0, 44)
    return t[:cut if cut > 20 else 44].rstrip() + "…"

def _slide_table_generic(prs, icon, title, subtitle, headers, rows, lang="fr",
                         col_widths=None, max_rows=8, cut_kind="generic",
                         status_col=None):
    if not rows:
        return
    try:
        # B.1.3.56 (scope E, durci gate ChatGPT) — plus JAMAIS de coupe
        # silencieuse, et un wording PAR TYPE de table : « premières sur »
        # n'a de sens que pour le registre ; une table de faits ou de risques
        # reçoit un libellé neutre. Si des lignes coupées portent un statut
        # critique (En retard / À arbitrer / Overdue), la note le dit.
        # B.1.3.56 correctif P2-E56-08 — wording NEUTRE : « N lignes sur M
        # affichées », l'ordre n'est ni une priorité ni une qualification
        # (« premières » retiré). Détection langue robuste (en, en-GB…).
        en = str(lang or "fr").lower().startswith("en")
        if len(rows) > max_rows:
            n, m = max_rows, len(rows)
            if cut_kind == "register":
                _cut_note = (f"{n} of {m} rows shown — full register in the CR"
                             if en else
                             f"{n} lignes sur {m} affichées — registre complet dans le CR")
            else:
                _cut_note = (f"{n} of {m} rows shown — full detail in the CR"
                             if en else
                             f"{n} lignes sur {m} affichées — détail complet dans le CR")
            if status_col is not None:
                _crit = ("en retard", "à arbitrer", "a arbitrer", "overdue",
                         "to arbitrate", "late")
                _n_crit = sum(
                    1 for r in rows[max_rows:]
                    if len(r) > status_col
                    and any(c in str(r[status_col]).lower() for c in _crit))
                if _n_crit:
                    _cut_note += ((f" — including {_n_crit} overdue/arbitration "
                                   f"item(s) not shown") if en else
                                  (f" — dont {_n_crit} en retard/à arbitrer "
                                   f"non affichée(s)"))
            subtitle = f"{subtitle} · {_cut_note}" if subtitle else _cut_note
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = C_LIGHT_GRAY
        _add_header(slide, icon, title, subtitle)
        n_rows = min(len(rows), max_rows) + 1
        n_cols = len(headers)
        tbl_shape = slide.shapes.add_table(
            n_rows, n_cols, Inches(0.3), Inches(1.3), Inches(9.4), Inches(0.4 * n_rows))
        table = tbl_shape.table
        if col_widths and len(col_widths) == n_cols:
            # Fix chantier H (10/08/2026) : les largeurs de colonnes REMPLACENT
            # la largeur du cadre — quand leur somme excède le canevas, la table
            # déborde (0,76 cm mesuré sur tout le corpus T5/T6/T8). On les
            # normalise à la largeur disponible, proportions conservées,
            # relative au canevas réel — jamais de littéral absolu.
            _avail = int(prs.slide_width) - int(Inches(0.6))  # 0,3″ de marge par côté
            _tot = sum(int(Inches(w)) for w in col_widths)
            _scale = min(1.0, _avail / _tot) if _tot > 0 else 1.0
            for ci, w in enumerate(col_widths):
                table.columns[ci].width = int(int(Inches(w)) * _scale)
        # En-tête
        for ci, h in enumerate(headers):
            cell = table.cell(0, ci)
            cell.text = str(h)
            cell.fill.solid(); cell.fill.fore_color.rgb = C_NAVY
            for p in cell.text_frame.paragraphs:
                p.alignment = PP_ALIGN.LEFT
                for r in p.runs:
                    r.font.size = Pt(9); r.font.bold = True; r.font.color.rgb = C_WHITE
        # Lignes
        for ri, row in enumerate(rows[:max_rows], start=1):
            for ci in range(n_cols):
                cell = table.cell(ri, ci)
                cell.text = str(row[ci]) if ci < len(row) else ""
                for p in cell.text_frame.paragraphs:
                    for r in p.runs:
                        r.font.size = Pt(8); r.font.color.rgb = C_TEXT_DARK
    except Exception:
        pass


# ── M.5.10.6 — localisation EN des statuts de registre côté PPT ──────────────
# Le deck consomme des rows (agenda_register via to_rows, et codir_history via
# open_actions/reapparues) où le statut peut rester brut en français (« À lancer »,
# « En cours », « À arbitrer »…). On localise au point de rendu (idempotent : un
# statut déjà EN n'est pas dans la map et reste inchangé). Union des deux maps de
# registre (agenda_register + codir_register_history).
_STATUT_PPT_EN = {
    "À lancer": "To start", "En cours": "In progress", "Fait": "Done",
    "Bloqué": "Blocked", "À arbitrer": "To arbitrate", "Reportée": "Deferred",
    "Clôturée": "Closed", "En retard": "Overdue",
}


def _loc_statut_ppt(statut, lang):
    if (lang or "fr") != "en" or not statut:
        return statut
    return _STATUT_PPT_EN.get(statut, statut)


def _status_display_ppt(row, lang):
    try:
        from patches.codir_register_history import action_status_display
        return action_status_display(row or {}, lang)
    except Exception:
        return _loc_statut_ppt((row or {}).get("statut", "") or "—", lang)


def _govern_action_rows_ppt(rows, lang):
    try:
        from patches.codir_register_history import govern_action_status_row
        for row in (rows or []):
            govern_action_status_row(row, lang=lang)
    except Exception:
        # Truth-critical renderer fallback: never let an unverified completion
        # survive merely because the shared helper failed to import/execute.
        _done = {"fait", "done", "closed", "completed", "terminé", "termine"}
        for row in (rows or []):
            if isinstance(row, dict) and str(row.get("statut", "") or "").strip().lower() in _done:
                row["statut"] = "To start" if lang == "en" else "À lancer"
                row["statut_conflict"] = "ACTION_STATUS_GUARD_FAILURE"


def _slide_registre_actions(prs, data):
    reg = data.get("agenda_register") or []
    lang = data.get("lang", "fr")
    # v62.13.9.4.41 — ANNEXE DE CONTINUATION. La planche exécutive gèle trois actions et
    # deux décisions : c'est un choix de format, pas un défaut. Mais les actions qui n'y
    # tiennent pas disparaissaient du fichier. À défaut de registre d'agenda, cette annexe
    # reprend les étapes de la structure, pour qu'aucun engagement ne sorte du deck sans
    # être écrit quelque part.
    # Deux sources, deux objets : le registre d'agenda suit les actions des séances
    # PRÉCÉDENTES, les étapes portent les engagements de la séance EN COURS. Les faire
    # partager une case revenait à ce que l'une chasse l'autre — mesuré le 23/09/2026 :
    # brancher le registre avait fait retomber le deck de quatorze objets écrits à huit.
    # L'annexe écrit les deux, séance en cours d'abord, sans doublon.
    _seen41 = {re.sub(r"\s+", " ", str(r.get("action") or "")).strip().lower() for r in reg}
    _steps41 = []
    for x in (data.get("next_steps") or []):
        if not isinstance(x, dict):
            continue
        _a41 = str(x.get("action") or "").strip()
        _k41 = re.sub(r"\s+", " ", _a41).lower()
        if not _a41 or _k41 in _seen41:
            continue
        _seen41.add(_k41)
        _steps41.append({"sujet": "", "action": _a41, "porteur": str(x.get("owner") or ""),
                         "echeance": str(x.get("date") or ""), "statut": ""})
    reg = _steps41 + list(reg)
    # B1.3.60-L1/S2 — gate sémantique : un fait historique n'entre jamais au
    # registre (terrain : « 168,8 M€ réalisés au S1 2025 » devenu EN RETARD).
    try:
        from utils.exec_reading import filter_semantic_action_rows
        reg, _dropped = filter_semantic_action_rows(reg)
    except Exception:
        pass
    _govern_action_rows_ppt(reg, lang)
    if not reg:
        return
    headers = (["Sujet", "Action", "Porteur", "Échéance", "Statut"] if lang == "fr"
               else ["Topic", "Action", "Owner", "Deadline", "Status"])
    rows = [[r.get("sujet", "") or "—", r.get("action", "") or "—",
             r.get("porteur", "") or "—", r.get("echeance", "") or "—",
             _status_display_ppt(r, lang)] for r in reg]
    _slide_table_generic(
        prs, "✓", "Registre d'actions" if lang == "fr" else "Action register",
        "Sujet · action · porteur · échéance · statut" if lang == "fr"
        else "Topic · action · owner · deadline · status",
        headers, rows, lang, col_widths=[1.7, 3.4, 1.5, 1.3, 1.5],
        cut_kind="register", status_col=4)


def _slide_suivi_multiseances(prs, data):
    """Cycle C — slide MULTI-SÉANCES (actions ouvertes du dossier, avec relances
    et statut « En retard » dérivé). Rendu UNIQUEMENT si un historique existe."""
    ch = data.get("codir_history") or None
    if not ch:
        return
    opens = ch.get("open_actions") or []
    # M.5.9 (FIX E1) — skip défensif : un séparateur « Axes conditionnels » qui
    # aurait été ingéré par un run antérieur (M.5.8) ne doit pas s'afficher comme
    # action ouverte.
    def _is_sep_action(a):
        act = (a.get("action", "") or "").strip().lower()
        return (a.get("_separator") or a.get("_row_type") == "section_header"
                or act.startswith("axes conditionnels — hors plan principal")
                or act.startswith("conditional axes — out of the main plan"))
    opens = [a for a in opens if not _is_sep_action(a)]
    # B1.3.60-L1/S2 — gate sémantique : aucun fait historique en action ouverte.
    try:
        from utils.exec_reading import filter_semantic_action_rows
        opens, _ = filter_semantic_action_rows(opens)
    except Exception:
        pass
    if not opens:
        return
    lang = data.get("lang", "fr")
    _govern_action_rows_ppt(opens, lang)
    headers = (["Sujet", "Action", "Porteur", "Échéance", "Statut", "Relances"]
               if lang == "fr" else
               ["Topic", "Action", "Owner", "Deadline", "Status", "Follow-ups"])
    rows = [[a.get("sujet", "") or "—", a.get("action", "") or "—",
             a.get("porteur", "") or "—", a.get("echeance", "") or "—",
             _status_display_ppt(a, lang), str(a.get("relance_count", 0))]
            for a in opens]
    _slide_table_generic(
        prs, "↻", "Suivi multi-séances" if lang == "fr" else "Multi-session tracking",
        "Actions ouvertes · relances · retard (historique du dossier)" if lang == "fr"
        else "Open actions · follow-ups · overdue (dossier history)",
        headers, rows, lang, col_widths=[1.6, 3.3, 1.5, 1.3, 1.4, 0.9],
        cut_kind="register", status_col=4)


def _slide_historique_codir(prs, data):
    """Cycle C (F.5.1) — slide HISTORIQUE CoDIR → CoDIR + écarts de décision.
    Rendu seulement si un historique multi-séances existe."""
    ch = data.get("codir_history") or None
    if not ch:
        return
    timeline = ch.get("timeline") or []
    ecarts = ch.get("decision_ecarts") or []
    reapparues = ch.get("reapparues") or []
    if not timeline and not ecarts and not reapparues:
        return
    lang = data.get("lang", "fr")
    if timeline:
        headers = (["Date", "Nouvelles", "Reconduites", "Relances", "Reportées", "Clôturées"]
                   if lang == "fr" else
                   ["Date", "New", "Carried", "Follow-ups", "Reported", "Closed"])
        rows = [[t.get("run_date", "") or "—", str(t.get("created", 0)),
                 str(t.get("carried", 0)), str(t.get("relance", 0)),
                 str(t.get("reported", 0)), str(t.get("closed", 0))] for t in timeline]
        _slide_table_generic(
            prs, "↺", "Historique CoDIR → CoDIR" if lang == "fr" else "CoDIR → CoDIR history",
            "Par séance : nouvelles · reconduites · relances · reportées · clôturées"
            if lang == "fr" else "Per session: new · carried · follow-ups · reported · closed",
            headers, rows, lang, col_widths=[1.6, 1.6, 1.6, 1.4, 1.5, 1.5])
    if ecarts:
        headers = (["Décision précédente", "Décision actuelle"] if lang == "fr"
                   else ["Previous decision", "Current decision"])
        rows = [[e.get("from", "") or "—", e.get("to", "") or "—"] for e in ecarts]
        _slide_table_generic(
            prs, "⚠", "Écarts de décision (N-1 → N)" if lang == "fr"
            else "Decision changes (N-1 → N)",
            "Changement de décision d'un CoDIR au suivant — à expliciter" if lang == "fr"
            else "Decision change across CoDIRs — to explain",
            headers, rows, lang, col_widths=[4.7, 4.7])
    if reapparues:
        # F.5.2.3 — actions clôturées réapparues : point d'ARBITRAGE dans le deck
        # (maintenir clôturée / rouvrir / créer une nouvelle action liée).
        headers = (["Action", "Porteur", "Statut", "Arbitrage attendu"] if lang == "fr"
                   else ["Action", "Owner", "Status", "Expected arbitration"])
        arb = ("maintenir clôturée / rouvrir / nouvelle action liée" if lang == "fr"
               else "keep closed / reopen / new linked action")
        rows = [[(a.get("action", "") or "—")[:60], a.get("porteur", "") or "—",
                 _loc_statut_ppt(a.get("statut", "") or "—", lang), arb] for a in reapparues]
        _slide_table_generic(
            prs, "⟳", "Actions clôturées réapparues — à arbitrer" if lang == "fr"
            else "Closed actions that reappeared — to arbitrate",
            "Clôturées puis réapparues : pas de réouverture auto, décision requise"
            if lang == "fr" else
            "Closed then reappeared: no auto-reopen, decision required",
            headers, rows, lang, col_widths=[4.0, 1.7, 1.5, 2.2])


def _slide_valorisation(prs, data):
    """Cycle D, brique 3 — slide VALORISATION conditionnelle. Rendue seulement si
    une valorisation a été déclenchée et qu'au moins une méthode est exploitable.
    Affiche la fourchette (football field), le détail par méthode, et un bandeau
    de gouvernance NON board-safe (la valorisation est dérivée — F.4.3)."""
    val = data.get("valuation") or None
    if not val or not val.get("triggered"):
        return
    summary = val.get("summary") or {}
    methods = val.get("methods") or []
    if not summary.get("methods_used"):
        return
    lang = data.get("lang", "fr")

    def _fmt(v):
        if v is None:
            return "—"
        try:
            a = float(v)
        except (TypeError, ValueError):
            return str(v)
        if abs(a) >= 1e9:
            return f"{a/1e9:.2f} Md€".replace(".", ",")
        if abs(a) >= 1e6:
            return f"{a/1e6:.1f} M€".replace(".", ",")
        if abs(a) >= 1e3:
            return f"{a/1e3:.0f} k€"
        return f"{a:.0f} €"

    low, mid, high = summary.get("low"), summary.get("mid"), summary.get("high")
    n = summary.get("methods_used")
    basis = summary.get("basis") or val.get("valuation_basis") or "equity"
    is_eq = basis == "equity"
    val_word = ("equity" if is_eq else "Enterprise Value")
    sub = (("Fourchette {w} {l} – {h} (médiane {m}) · {n} méthode(s) · "
            "DÉRIVÉE — NON « board-safe »"
            + ("" if is_eq else " · pont EV→Equity indisponible (dette nette absente)")
            if lang == "fr" else
            "{w} range {l} – {h} (median {m}) · {n} method(s) · DERIVED — NOT board-safe"
            + ("" if is_eq else " · EV→Equity bridge unavailable (net debt missing)"))
           ).format(w=val_word, l=_fmt(low), h=_fmt(high), m=_fmt(mid), n=n)

    # Table d'INTRANTS + pont (la chaîne de calcul, exigence M&A).
    inp = val.get("inputs") or {}
    nd_txt = ("inconnue" if not inp.get("net_debt_known") else _fmt(inp.get("net_debt")))
    if inp.get("net_debt_known"):
        nd_txt += f"  ({inp.get('net_debt_basis')})"
        nd_txt += ("  ✓ confirmée" if inp.get("net_debt_confirmed") else "  ⚠ à vérifier")
    in_headers = (["Intrant", "Valeur"] if lang == "fr" else ["Input", "Value"])
    in_rows = [
        ["CA", _fmt(inp.get("revenue"))], ["EBITDA", _fmt(inp.get("ebitda"))],
        ["Résultat net" if lang == "fr" else "Net income", _fmt(inp.get("net_income"))],
        ["Trésorerie" if lang == "fr" else "Cash", _fmt(inp.get("cash"))],
        ["Dette brute" if lang == "fr" else "Gross debt", _fmt(inp.get("gross_debt"))],
        ["Dette nette" if lang == "fr" else "Net debt", nd_txt],
        ["Multiples", f"EV/EBITDA {inp.get('ev_ebitda_multiple')}x · EV/Sales "
                      f"{inp.get('ev_sales_multiple')}x ({inp.get('multiples_source')})"],
    ]
    _slide_table_generic(
        prs, "€",
        ("Valorisation — intrants & pont" if lang == "fr" else "Valuation — inputs & bridge"),
        ("Chaîne de calcul (dérivée, non board-safe)" if lang == "fr"
         else "Calculation chain (derived, non board-safe)"),
        in_headers, in_rows, lang, col_widths=[3.2, 6.0])

    headers = (["Méthode", ("Equity" if is_eq else "EV"), "Hypothèse / statut"] if lang == "fr"
               else ["Method", ("Equity" if is_eq else "EV"), "Assumption / status"])
    rows = []
    for m in methods:
        applicable = m.get("applicable", True)
        status = m.get("assumption") or ""
        if not applicable:
            status = ("écartée : non applicable" if lang == "fr"
                      else "excluded: not applicable")
        headline_val = m.get("equity_value") if is_eq else m.get("enterprise_value")
        rows.append([(m.get("method", "") or "—")[:46],
                     _fmt(headline_val), (status or "—")[:48]])

    # caveats clés (fidélité / bridge / EV-EBITDA écarté) sous forme de lignes
    caveats = val.get("caveats") or []
    for c in caveats:
        if any(k in c for k in ("ligne-à-ligne", "EV/EBITDA", "Pont EV→Equity", "NON DISPONIBLE", "NON CONFIRMÉS")):
            rows.append(["⚠", "", c[:64]])

    _slide_table_generic(
        prs, "€",
        "Valorisation indicative" if lang == "fr" else "Indicative valuation",
        sub, headers, rows, lang, col_widths=[3.6, 1.9, 4.0])


def _slide_faits_marche(prs, data):
    """Render a decision-readable market evidence table.

    v62.3 exposed parser residue (``| **``), merged years into values and showed
    raw URLs.  The v62.4 surface is deliberately a WORKING evidence map: value
    with its unit, period/scope, nature/reliability and compact source domain.
    Forecasts and actor-level results remain visible but explicitly marked as
    not decision-safe.
    """
    led = [r for r in (data.get("web_facts_ledger") or []) if isinstance(r, dict)]
    if not led:
        return
    lang = data.get("lang", "fr")
    en = str(lang or "fr").lower().startswith("en")
    headers = (["Metric", "Value", "Period / scope", "Nature / status", "Source"]
               if en else
               ["Métrique", "Valeur", "Période / périmètre", "Nature / statut", "Source"])

    class_labels = {
        "MARKET_SIZE": ("Market size" if en else "Taille du marché"),
        "GROWTH": ("Growth / dynamics" if en else "Croissance / dynamique"),
        "PRICING": ("Pricing / daily rate" if en else "Prix / TJM"),
        "PLAYERS": ("Players / shares" if en else "Acteurs / parts"),
        "SEGMENT": ("Segments / trends" if en else "Segments / tendances"),
    }
    scope_labels = {
        "TOTAL_MARKET": ("total market" if en else "marché total"),
        "INTERMEDIATED_MARKET": ("intermediated" if en else "intermédié"),
        "DIRECT_MARKET": ("direct" if en else "direct"),
        "SOURCE_ACTOR": ("source actor" if en else "acteur source"),
        "UNKNOWN": ("scope n/a" if en else "périmètre n/d"),
    }
    nature_labels = {
        "OBSERVED": ("observed" if en else "observé"),
        "FORECAST": ("forecast" if en else "prévision"),
        "ESTIMATE": ("estimate" if en else "estimation"),
        "ACTOR_RESULT": ("actor" if en else "acteur"),
        "UNKNOWN": ("nature n/a" if en else "nature n/d"),
    }

    def _metric(r):
        mclass = str(r.get("metric_class") or "OTHER").upper()
        if mclass in class_labels:
            return class_labels[mclass]
        raw = str(r.get("metric") or "—")
        raw = raw.replace("**", "").replace("|", " ").replace("`", " ")
        return _t(" ".join(raw.split()), 38)

    def _fallback_value(r):
        ce, lo, hi = r.get("valeur_centrale"), r.get("valeur_basse"), r.get("valeur_haute")
        if ce is None:
            return "—"
        def fmt(v):
            try:
                f = float(v)
                return str(int(f)) if f.is_integer() else str(round(f, 2)).replace(".", ",")
            except Exception:
                return str(v)
        return f"{fmt(lo)}–{fmt(hi)}" if lo != hi else fmt(ce)

    def _value(r):
        raw = str(r.get("value_display") or "").strip()
        if raw:
            return _t(raw.replace("**", "").replace("|", " "), 28)
        return _t(_fallback_value(r), 28)

    def _period_scope(r):
        year = str(r.get("annee") or "—")
        scope = scope_labels.get(str(r.get("scope") or "UNKNOWN").upper(),
                                 scope_labels["UNKNOWN"])
        return _t(f"{year} · {scope}", 30)

    def _status(r):
        nature = nature_labels.get(str(r.get("nature") or "UNKNOWN").upper(),
                                   nature_labels["UNKNOWN"])
        reliability = str(r.get("fiabilite") or "—").upper()
        safe = bool(r.get("decision_safe"))
        suffix = ("decision-safe" if en else "décision-safe") if safe else (
            "to verify" if en else "à vérifier")
        return _t(f"{nature} · {reliability} · {suffix}", 34)

    def _source(r):
        from urllib.parse import urlparse
        u = str(r.get("source_url") or "").strip()
        if not u:
            return "—"
        try:
            host = urlparse(u).netloc or u
            host = host.lower().removeprefix("www.")
            return _t(host, 30)
        except Exception:
            return _t(u, 30)

    # Evidence useful to decisions first, then traceable evidence, then the
    # residual hypotheses.  Stable sort preserves the source order within tiers.
    led = sorted(enumerate(led), key=lambda it: (
        0 if it[1].get("decision_safe") else
        1 if it[1].get("board_safe") else
        2 if it[1].get("source_url") else 3,
        it[0],
    ))
    rows = [[_metric(r), _value(r), _period_scope(r), _status(r), _source(r)]
            for _, r in led]
    _slide_table_generic(
        prs, "◆", "Market facts — reconciled" if en else "Faits marché — réconciliés",
        ("Value · period · scope · nature · source" if en else
         "Valeur · période · périmètre · nature · source"),
        headers, rows, lang, col_widths=[2.05, 1.35, 2.0, 2.35, 1.65],
        max_rows=8, cut_kind="generic")


import re as _re_dk

# M.5.10.11 — chokepoint langue du DECK. Le run réel dossier anglophone coté EN a montré que le
# fallback narratif Supply Chain (codé en dur en FR dans codir_engine) et certains
# tags épistémiques échappaient à toute localisation côté PPTX. On applique une
# passe FINALE sur le presentation construit : tags épistémiques + phrases SC
# fallback + label GLEIF, EN uniquement, idempotente (ne touche que des marqueurs
# FR connus → no-op sur du texte déjà anglais).
_DECK_EN_PHRASES = [(_re_dk.compile(p, _re_dk.I), r) for p, r in [
    (r"GLEIF\s*[—\-–]\s*Référentiel international", "GLEIF — International reference database"),
    (r"Référentiel international", "International reference database"),
    (r"Risque de désalignement entre niveau de stock, disponibilité produit et objectifs de cash à court terme\.?",
     "Risk of misalignment between inventory level, product availability and short-term cash targets."),
    (r"Supply chain sous tension\s*[—\-–]?\s*BFR et disponibilité produit à piloter en urgence",
     "Supply chain under pressure — working capital and product availability require urgent steering"),
    (r"stocks? et disponibilité produit à piloter en urgence",
     "inventory and product availability require urgent steering"),
    (r"BFR et disponibilité produit à piloter en urgence",
     "working capital and product availability require urgent steering"),
    (r"Supply chain sous tension", "supply chain under pressure"),
    (r"Audit express stocks et disponibilit[ée](?:\s+sur r[ée]f[ée]rences critiques)?",
     "rapid inventory & availability audit"),
    (r"Audit express stocks et BFR", "rapid inventory & working-capital audit"),
    (r"Audit express", "rapid audit"),
    (r"Arbitrer taux service vs r[ée]duction BFR", "arbitrate service level vs working-capital reduction"),
    (r"Programme(?:\s+de)?\s+r[ée]silience supply chain(?:\s+long terme)?",
     "long-term supply chain resilience programme"),
    (r"Programme(?:\s+de)?\s+r[ée]silience", "resilience programme"),
    (r"BFR sensible aux d[ée]lais fournisseurs mati[èe]res?",
     "working capital sensitive to raw-material supplier lead times"),
    (r"Couverture stock\s*:?\s*mati[èe]res? premi[èe]res?", "stock coverage: raw materials"),
    (r"Couverture stock", "stock coverage"),
    (r"Taux de service cible", "target service level"),
    (r"Taux de service", "service level"),
    (r"D[ée]salignement stock\s*/\s*service\s*/\s*cash", "stock/service/cash misalignment"),
    (r"D[ée]salignement", "misalignment"),
    (r"mati[èe]res? premi[èe]res?", "raw materials"),
    (r"disponibilit[ée] produit", "product availability"),
    (r"D[ÉE]CISION\s+(\d+)\s+RECOMMAND[ÉE]E", r"RECOMMENDED DECISION \1"),
    (r"\[ESTIM\.\s*IA\]", "[AI ESTIM.]"),
    (r"\bBFR\b", "working capital"),
    (r"\bdisponibilit[ée]\b", "availability"),
]]


def _localize_deck_text(s, lang: str = "fr"):
    """Localise une chaîne du deck en EN : tags épistémiques + phrases SC fallback
    + GLEIF. No-op si lang != en ou si la chaîne ne contient aucun marqueur FR."""
    if not isinstance(s, str) or not s or (lang or "fr").lower() != "en":
        return s
    out = s
    try:
        from patches.output_hygiene import localize_epistemic_tags as _let
        out = _let(out, "en")
    except Exception:
        pass
    for rx, rep in _DECK_EN_PHRASES:
        out = rx.sub(rep, out)
    return out


def _localize_presentation(prs, lang: str = "fr"):
    """Passe finale : applique _localize_deck_text à TOUTE surface texte du deck
    (textboxes + cellules de tableau + shapes groupées). Garantit P0-5 sur le
    PPTX complet — c'est la surface que le test strict extrait et scanne."""
    if (lang or "fr").lower() != "en":
        return
    def _walk(shapes):
        for sh in shapes:
            try:
                if sh.has_text_frame:
                    for para in sh.text_frame.paragraphs:
                        for run in para.runs:
                            run.text = _localize_deck_text(run.text, lang)
            except Exception:
                pass
            try:
                if sh.has_table:
                    for row in sh.table.rows:
                        for cell in row.cells:
                            for para in cell.text_frame.paragraphs:
                                for run in para.runs:
                                    run.text = _localize_deck_text(run.text, lang)
            except Exception:
                pass
            try:
                if sh.shape_type == 6:  # MSO_SHAPE_TYPE.GROUP
                    _walk(sh.shapes)
            except Exception:
                pass
    for slide in prs.slides:
        _walk(slide.shapes)


def _apply_temporal_gate_to_deck(
    data: dict, lang: str = "fr", run_date=None
) -> int:
    """Gouverne les échéances d'action du deck avec la date d'autorité du run.

    Une présentation peut être régénérée plusieurs jours après la session. Le
    renderer ne doit donc jamais utiliser ``date.today()`` : sans ``run_date``
    explicite, il ne fabrique aucun état « en retard ». Le passage couvre les
    champs de délai structurés *et* les dates incluses dans les textes d'action
    réellement rendus (axes, roadmap, prochaines étapes, commercial, registre).
    Les constats historiques restent protégés par le garde narratif central.
    """
    if not isinstance(data, dict) or not run_date:
        return 0
    try:
        from datetime import date as _date
        from patches.temporal_gate import (
            flag_past_dated_actions as _flag_rows,
            flag_past_action_dates_in_text as _flag_text,
        )
        if isinstance(run_date, _date):
            rd = run_date
        else:
            rd = _date.fromisoformat(str(run_date)[:10])
    except Exception:
        # Autorité temporelle absente ou invalide : aucune inférence depuis
        # l'horloge de la machine de rendu.
        return 0

    n = 0

    def _flag_string(container, key):
        nonlocal n
        if not isinstance(container, dict):
            return
        raw = container.get(key)
        if not isinstance(raw, str) or not raw:
            return
        governed = _flag_text(raw, rd, lang)
        if governed != raw:
            container[key] = governed
            n += 1

    def _flag_string_list(container, key):
        nonlocal n
        if not isinstance(container, dict):
            return
        values = container.get(key)
        if not isinstance(values, list):
            return
        updated = []
        for raw in values:
            if isinstance(raw, str) and raw:
                governed = _flag_text(raw, rd, lang)
                if governed != raw:
                    n += 1
                updated.append(governed)
            else:
                updated.append(raw)
        container[key] = updated

    roadmap = data.get("roadmap") or []
    n += _flag_rows(roadmap, rd, lang, date_keys=("date",))
    for item in roadmap:
        _flag_string(item, "titre")
        _flag_string_list(item, "items")

    next_steps = data.get("next_steps") or []
    n += _flag_rows(next_steps, rd, lang, date_keys=("date", "deadline"))
    for item in next_steps:
        _flag_string(item, "action")

    # Compatibilité avec l'ancien schéma racine et schéma live imbriqué.
    root_actions = data.get("plan_actions") or []
    n += _flag_rows(root_actions, rd, lang, date_keys=("delai", "deadline", "date"))
    for item in root_actions:
        _flag_string(item, "action")

    commercial = data.get("commercial") or {}
    commercial_actions = (commercial.get("plan_actions") or []
                          if isinstance(commercial, dict) else [])
    n += _flag_rows(commercial_actions, rd, lang,
                    date_keys=("delai", "deadline", "date"))
    for item in commercial_actions:
        _flag_string(item, "action")

    agenda = data.get("agenda_register") or []
    n += _flag_rows(agenda, rd, lang,
                    date_keys=("echeance", "échéance", "deadline", "date"))
    for item in agenda:
        _flag_string(item, "action")
        _flag_string(item, "sujet")

    for axis in data.get("axes") or []:
        _flag_string_list(axis, "points")

    return n


# B.1.3.6 — écho d'instrumentation du builder prudence (lu par app.py pour
# la row diagnostics deck_b13) : la slide cadre manque au terrain alors que
# le test d'intégration est vert — cette trace tranchera au prochain run.
LAST_DECK_DIAG: dict = {}


def _pptx_delivery_mode(settings, extra_context: Optional[dict] = None) -> str:
    """Return ``working`` for the product surface, ``strict`` for QA/full deck.

    Legacy/test callers that do not expose the setting retain the historical
    strict behavior. The real Settings object introduced in v62.7 defaults to
    ``working``.
    """
    extra_context = extra_context or {}
    raw = (extra_context.get("pptx_delivery_mode")
           or getattr(settings, "pptx_delivery_mode", "strict")
           or "strict")
    mode = str(raw).strip().lower()
    return mode if mode in {"working", "strict"} else "working"


def generate_pptx_blocked_local(dossier_label: str = "",
                                status_line: str = "",
                                lang: str = "fr") -> bytes:
    """Correctif TCR-C1 — deck BLOQUÉ local et déterministe : zéro
    provider, zéro réseau, zéro coût. Une slide : titre, bandeau du
    TemporalStatusRenderer, consigne de correction et de relance."""
    from io import BytesIO
    from pptx import Presentation
    from pptx.util import Inches, Pt
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    tb = slide.shapes.add_textbox(Inches(0.6), Inches(0.9),
                                  prs.slide_width - Inches(1.2),
                                  Inches(4.6))
    tb.name = "HCRIT:blocked:message"
    tf = tb.text_frame
    tf.word_wrap = True
    tf.text = ("Analyse bloquée — autorité temporelle non établie"
               if lang == "fr" else
               "Analysis blocked — temporal authority not established")
    tf.paragraphs[0].runs[0].font.size = Pt(28)
    tf.paragraphs[0].runs[0].font.bold = True
    if dossier_label:
        p2 = tf.add_paragraph()
        p2.text = dossier_label
        p2.runs[0].font.size = Pt(16)
    if status_line:
        p3 = tf.add_paragraph()
        p3.text = status_line
        p3.runs[0].font.size = Pt(14)
    p4 = tf.add_paragraph()
    p4.text = ("Corrigez la date d'analyse (Réglages ou brief) puis "
               "relancez : aucun agent n'a été appelé, aucun coût "
               "engagé." if lang == "fr" else
               "Fix the analysis date (Settings or brief) and relaunch: "
               "no agent was called, no cost incurred.")
    p4.runs[0].font.size = Pt(14)
    buf = BytesIO()
    try:
        from utils.ai_content_marking import apply_marking as _mark50
        from version import PUBLISHER as _PUB
        _mark50(prs, provider=_PUB)
    except Exception:
        pass
    try:
        # Chantier H (10/08/2026) — filet géométrique systémique avant scellement.
        from utils.deck_layout_guard import apply_deck_layout_guard as _h2_guard
        _h2_guard(prs)
    except Exception:
        pass
    prs.save(buf)
    # v62.13.9.4.41 — RÉCONCILIATION APRÈS ÉCRITURE. Les planches coupent (trois actions à
    # l'écran exécutif, trois éléments par phase, huit lignes de table) : c'est légitime,
    # mais rien ne disait ce qui restait dehors. On rouvre le fichier qu'on vient d'écrire
    # et tout élément de la trame absent du rendu part dans la trace avec son motif.
    try:
        import io as _io41, re as _re41
        from pptx import Presentation as _P41
        from utils.objects_render import trace_template_cut41 as _ttc41
        _blob41 = buf.getvalue()
        _prs41 = _P41(_io41.BytesIO(_blob41))
        _txt41 = " ".join(
            [sh.text_frame.text for sl in _prs41.slides for sh in sl.shapes
             if getattr(sh, "has_text_frame", False)]
            + [c.text for sl in _prs41.slides for sh in sl.shapes
               if getattr(sh, "has_table", False) for rw in sh.table.rows for c in rw.cells])
        _n41 = lambda x: _re41.sub(r"\s+", " ", str(x or "")).strip().lower()
        _written41 = _n41(_txt41)
        _cands41 = list(data.get("next_steps") or [])
        for _ph41 in (data.get("roadmap") or []):
            _cands41 += [{"action": _i41} for _i41 in (_ph41.get("items") or [])]
        _cands41 += [{"action": _d41, "kind": "decision"} for _d41 in (data.get("decisions_codir") or [])]
        _cut41 = [c for c in _cands41 if isinstance(c, dict)
                  and _n41(c.get("action"))[:40]
                  and _n41(c.get("action"))[:40] not in _written41]
        if _cut41:
            _ttc41(_cut41, "non écrit par le gabarit (capacité de planche)")
    except Exception:
        pass

    return buf.getvalue()


def apply_truth_flags_from_cr(data: dict, report_text: str) -> dict:
    """v62.12.1 (spec §5) — pose l'état du gate de vérité dans le payload deck.

    Le CR gouverné est la source unique verbalisée : s'il porte le marqueur
    « CURRENT FINANCIAL POSITION NOT ESTABLISHED », le deck n'affiche aucun
    chiffre historique comme photographie courante (bannière fail-closed).
    """
    if not isinstance(data, dict):
        return data
    cr = str(report_text or "")
    if cr:
        not_established = "CURRENT FINANCIAL POSITION NOT ESTABLISHED" in cr
        data["current_financial_state_established"] = not not_established
        m = re.search(
            r"Latest critical page-confirmed period\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})",
            cr)
        if not m:
            m = re.search(
                r"latest usable[^:\n]*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})",
                cr, re.IGNORECASE)
        if m:
            data["latest_confirmed_period_end"] = m.group(1)
    return data


def generate_pptx_from_cr_with_provider(
    report_text: str,
    provider: str,
    settings,
    output_path: Optional[str | Path] = None,
    extra_context: Optional[dict] = None,
    lang: str = "fr",
) -> bytes:
    # v62.13.9.4.43 — la trace de sélection est locale au run : on ouvre son jeton ici,
    # au début de la fabrication du deck, avec l'identifiant du run quand il existe.
    try:
        from utils.objects_render import reset_selection_trace41 as _rst41
        _rst41(str(((extra_context or {}).get("result") or {}).get("run_id") or ""))
    except Exception:
        pass
    extra_context = extra_context or {}
    _pptx_mode = _pptx_delivery_mode(settings, extra_context)
    # B.1.3.29-chatgpt — optional per-call diagnostics sink.  LAST_DECK_DIAG
    # remains for legacy instrumentation, but substantive decisions in app.py
    # consume this session-local object to avoid cross-session races.
    _diag_out28 = extra_context.get("_deck_diag_out")
    if isinstance(_diag_out28, dict):
        _diag_out28.clear()
    # B.1.3.30 audit — diagnostics are built in a call-local dictionary.
    # The legacy module global is updated only after the call completes.
    _deck_diag28: dict = {}
    # Correctif TCR-C1 — boundary applicative explicite : AUCUN appel
    # provider si le run est temporellement bloqué (ceinture derrière
    # l'early-return applicatif d'app.py).
    if bool((extra_context or {}).get("temporal_early_return")):
        data = {"title": "Analyse bloquée" if lang == "fr" else
                "Analysis blocked", "slides": []}
    else:
        _guarded_report_text = report_text
        # v62.13.9.4.23 — TRAME DEPUIS LES OBJETS (contrat du 06/09/2026). Quand
        # le résultat porte des objets d'analyse suffisants, la structure du
        # deck est construite sans appel modèle : décisions, sujets traités,
        # actions datées, risques, questions — jamais un nom de section pris
        # pour une décision (« NOTE CEO »), jamais un emplacement rempli par
        # défaut. Le structurant modèle ne sert que si les objets manquent.
        data = {}
        try:
            from utils.objects_render import deck_data_from_objects as _ddfo
            _res_obj = (extra_context or {}).get("result") or {}
            _objs = _res_obj.get("analysis_objects") if isinstance(_res_obj, dict) else None
            if isinstance(_objs, dict) and _objs.get("objects"):
                data = _ddfo(_objs, _res_obj, lang) or {}
        except Exception:
            data = {}
        if not data:
            data = call_ia_for_structure_with_provider(
                _guarded_report_text, provider, settings, lang=lang)
    data["lang"] = lang  # v16.5.38 — propagé à toutes les fonctions _slide_*
    # v62.12.1 (spec §5) — vérité fail-closed jusqu'au deck : l'état du gate
    # se lit dans le CR gouverné (source unique verbalisée).
    data = apply_truth_flags_from_cr(data, report_text)
    # v62.10 — semantic KPI gate at the common deck boundary.  A retail-unit
    # count (stores / shops / doors) must not survive as company headcount in
    # context slides, even if the structuring model placed it in ``effectif``.
    try:
        from utils.exec_reading import is_valid_headcount_candidate as _valid_hc6210
        _cc6210 = data.get("contexte_corporate")
        if isinstance(_cc6210, dict):
            for _hc_key6210 in ("effectif", "headcount"):
                if _hc_key6210 in _cc6210 and not _valid_hc6210(_cc6210.get(_hc_key6210)):
                    _cc6210.pop(_hc_key6210, None)
    except Exception:
        pass
    # v62.10 — défense en profondeur : le renderer ne doit pas réintroduire
    # des cibles exécutives chiffrées non étayées après structuration du CR.
    if str(extra_context.get("finance_tone") or "").upper() == "BOARD_SCRUTINY":
        try:
            from utils.board_scrutiny_guard import strip_numeric_targets_from_mapping
            data = strip_numeric_targets_from_mapping(
                data, lang=lang,
                numeric_support_claims=(extra_context or {}).get("numeric_support_claims")
                or (extra_context or {}).get("canonical_financial_claims") or [])
            data["lang"] = lang
        except Exception:
            pass
    # v62.11 — confirmed financial KPI cards are populated from the single
    # page-confirmed ledger after speculative target scrubbing.
    try:
        from utils.financial_proof_layer import inject_confirmed_financial_kpis as _icfk6211
        _deck_diag28["financial_proof_kpis"] = _icfk6211(
            data, (extra_context or {}).get("financial_facts_table"), lang=lang,
            canonical_claims=(extra_context or {}).get("canonical_financial_claims"),
            external_facts=(_result_meta51(extra_context, "external_facts50") or {}).get("facts"),
            analysis_date=str((((extra_context or {}).get("result") or {}).get("temporal_authority") or {}).get("analysis_date") or ""),
            fiscal_year_end=str(_result_meta51(extra_context, "fiscal_year_end50")))
        _fill_headcount51(data, extra_context, lang)        # 9.4.51 — effectif des pièces si l'agent l'a dit absent
    except Exception as _kpi_exc6211:
        _deck_diag28["financial_proof_kpis"] = {
            "status": "ERROR",
            "error": f"{type(_kpi_exc6211).__name__}: {str(_kpi_exc6211)[:120]}",
        }

    data["pptx_delivery_mode"] = _pptx_mode
    _deck_diag28["pptx_delivery_mode"] = _pptx_mode
    if extra_context.get("run_date"):
        data["date"] = _format_cover_date(extra_context.get("run_date"), lang)
        data["_h2_reference_date"] = str(extra_context.get("run_date"))[:10]

    # M6-S.2.1.2 — verrou entité : le nom en couverture ne doit pas dépendre d'une
    # extraction heuristique du CR. Si l'entité d'analyse est connue, elle prime.
    _aed = (extra_context.get("analysis_entity_display") or "").strip()
    if _aed:
        data["entreprise"] = _aed
        # S.2.1.3 — verrouiller aussi titre/sous-titre du cover (ils viennent encore
        # de l'extraction IA et peuvent contenir le nom registre).
        _red = (extra_context.get("registry_entity_display") or "").strip()
        if _red and _red.lower() != _aed.lower():
            import re as _re_cov
            _rxc = _re_cov.compile(_re_cov.escape(_red), _re_cov.I)
            for _k in ("titre", "sous_titre"):
                if isinstance(data.get(_k), str) and data[_k]:
                    data[_k] = _rxc.sub(_aed, data[_k])
    global _DECK_LANG; _DECK_LANG = lang  # M.5.10 — footer / rendus sans lang
    # S.2.2.1 — deck_type détecté AVANT l'enrichissement commercial : le gating
    # anti-template solo en dépend (sinon _enrich reçoit un deck_type vide).
    deck_type = _detect_deck_type(data, report_text=report_text, extra_context=extra_context)
    data["deck_type"] = deck_type
    # B.1.3.61/S4 — le statut amont doit exister AVANT enrichissement/scrub.
    # En 3.60 il n'était propagé qu'après ces appels : le vrai pipeline perdait
    # l'analyse TJM d'un dossier corporate dont la Supply Chain était SKIPPED.
    data["supply_chain_bundle_status"] = str(
        extra_context.get("supply_chain_bundle_status") or "").upper()
    # v62.13.9.4.24 — trame depuis les objets : les anciens enrichissements qui
    # RELISENT le rapport pour remplir les cases vides sont coupés (ils prenaient
    # « OBJETS D'ANALYSE » pour un risque et « IMPACT SUPPLY CHAIN » pour la
    # situation). Une case sans objet reste vide ou disparaît.
    _from_objects62424 = str(data.get("_built_from") or "") == "analysis_objects"
    if not _from_objects62424:
        # Option B — v16.5.28 : commercial_json direct Grok prioritaire sur couche 2
        _enrich_commercial_if_empty(data, report_text, extra_context=extra_context)
    # S.2.2.1 — garde anti-template post-enrich, indépendante de la source.
    _scrub_commercial_for_deck_type(data, lang=lang)
    if not _from_objects62424:
        _enrich_marche_if_incomplete(data)
    # M.5.9 (FIX B) — démotion P0-3 universelle (LLM + fallback) + drapeau slide
    # commerciale, au point de convergence du deck.
    _apply_winddown_deck_governance(data, report_text, lang=lang)
    if _from_objects62424 and "supply_chain" not in set(data.get("_topics") or []):
        data["supply_chain"] = {}                       # sujet absent : aucune slide, aucun message
    else:
        data["supply_chain"] = _extract_supply_chain_payload(report_text, extra_context=extra_context)
    if str(extra_context.get("finance_tone") or "").upper() == "BOARD_SCRUTINY":
        try:
            from utils.board_scrutiny_guard import strip_numeric_targets_from_mapping as _strip_map6210
            if isinstance(data.get("commercial"), dict):
                data["commercial"] = _strip_map6210(
                    data["commercial"], lang=lang, _path=("commercial",),
                    numeric_support_claims=(extra_context or {}).get("numeric_support_claims")
                    or (extra_context or {}).get("canonical_financial_claims") or [])
            if isinstance(data.get("supply_chain"), dict):
                data["supply_chain"] = _strip_map6210(
                    data["supply_chain"], lang=lang, _path=("supply_chain",),
                    numeric_support_claims=(extra_context or {}).get("numeric_support_claims")
                    or (extra_context or {}).get("canonical_financial_claims") or [])
        except Exception:
            pass
    # v62.13.3 F3 — de-duplicate guard fallbacks per semantic slide
    # section after commercial and Supply Chain enrichment.  Geometry and
    # paging are untouched: only repeated content strings are collapsed.
    try:
        from utils.board_scrutiny_guard import deduplicate_guard_fallbacks as _dedup_guard62133
        _dedup_diag62133 = {"duplicates_removed": 0, "summaries_inserted": 0, "sections": {}}
        for _section_key62133, _section_value62133 in list(data.items()):
            if not isinstance(_section_value62133, (dict, list, tuple)):
                continue
            _clean_section62133, _section_diag62133 = _dedup_guard62133(
                _section_value62133, lang=lang)
            if int((_section_diag62133 or {}).get("duplicates_removed") or 0):
                data[_section_key62133] = _clean_section62133
                _dedup_diag62133["sections"][_section_key62133] = _section_diag62133
                _dedup_diag62133["duplicates_removed"] += int(_section_diag62133.get("duplicates_removed") or 0)
                _dedup_diag62133["summaries_inserted"] += int(_section_diag62133.get("summaries_inserted") or 0)
        _deck_diag28["guard_fallback_dedup"] = _dedup_diag62133
    except Exception as _dedup_exc62133:
        _deck_diag28["guard_fallback_dedup"] = {
            "status": "ERROR", "error": f"{type(_dedup_exc62133).__name__}: {str(_dedup_exc62133)[:120]}"}

    # v17.1.0-B2.3-F.4 — artefacts CoDIR pour slides dédiées (si fournis en amont).
    data["agenda_register"] = extra_context.get("agenda_register") or []
    _apply_temporal_gate_to_deck(
        data, lang=lang, run_date=extra_context.get("run_date")
    )  # B.1.3.56 Gate 10 — date du run explicite
    data["web_facts_ledger"] = extra_context.get("web_facts_ledger") or []
    data["codir_history"] = extra_context.get("codir_history") or None
    try:
        from patches.strategic_horizon import ensure_roadmap_reaches_target as _errt6210
        data = _errt6210(
            data,
            target_end_date=str(extra_context.get("strategic_target_end_date") or ""),
            lang=lang,
        )
    except Exception:
        pass
    # B.1.3 — cadre de lecture (prudence slide 2) + garde de wording décision.
    # La prudence n'attend plus la slide 14 : Grade ≤ C, source_quality < 40
    # ou sections incomplètes ⇒ slide dédiée juste après le titre.
    try:
        _deck_diag28.clear()
        _b13g = str(extra_context.get("confidence_grade") or "").upper()
        _b13sq = extra_context.get("source_quality")
        _b13ci = extra_context.get("completion_issues") or []
        _b13_need = (
            _b13g in ("C", "D", "E")
            or (_b13sq is not None and float(_b13sq) < 40)
            or bool(_b13ci)
        )
        _deck_diag28.update({"grade": _b13g, "need": bool(_b13_need),
                               "b13ci_len": len(_b13ci or [])})
        if _b13ci:
            # B.1.3.8 (audit #6) — livrable flaggé non distribuable ⇒ le deck
            # s'annonce BROUILLON dès la slide 1 (le cadre porte déjà la
            # bannière ; le titre ne doit pas « vendre » un plan validé).
            try:
                _st0 = str(data.get("sous_titre") or "")[:58]
                data["sous_titre"] = (_st0 + (" — DRAFT" if lang == "en" else " — BROUILLON")).strip(" —")
                if lang == "en":
                    data["sous_titre"] = (_st0 + " — DRAFT").strip()
                else:
                    data["sous_titre"] = (_st0 + " — BROUILLON").strip()
            except Exception:
                pass
        if _b13_need:
            _deck_diag28["prudence_set"] = True
            data["b13_prudence"] = {
                "grade": _b13g or "?",
                "source_quality": _b13sq,
                "has_fs": bool(extra_context.get("n_pdfs_with_fs")),
                "ctx": extra_context.get("b1_analysis_context") or {},
                "n_incomplete": len(_b13ci),
            }
        # Grade D/E : un deck ne « décide » pas — GO CONDITIONNEL et
        # Décision finale deviennent une orientation non certifiée,
        # partout dans le payload (titres, bullets, décisions).
        if _b13g in ("D", "E"):
            import re as _re_b13
            _subs = [
                (_re_b13.compile(r"GO\s+CONDITIONNEL", _re_b13.I),
                 SL("b13_orientation", lang)),
                (_re_b13.compile(r"CONDITIONAL\s+GO", _re_b13.I),
                 SL("b13_orientation", lang)),
                (_re_b13.compile(r"D[ée]cision\s+finale", _re_b13.I),
                 "Orientation de travail" if lang == "fr" else "Working orientation"),
                (_re_b13.compile(r"Final\s+decision", _re_b13.I),
                 "Working orientation" if lang == "en" else "Orientation de travail"),
            ]
            def _b13_sweep(node):
                if isinstance(node, str):
                    for _rx, _rep in _subs:
                        node = _rx.sub(_rep, node)
                    return node
                if isinstance(node, list):
                    return [_b13_sweep(x) for x in node]
                if isinstance(node, dict):
                    return {k: _b13_sweep(v) for k, v in node.items()}
                return node
            for _k in list(data.keys()):
                if _k in ("lang", "b13_prudence"):
                    continue
                data[_k] = _b13_sweep(data[_k])
    except Exception:
        pass
    # C-01a (audit dossier réseau de soins) — DECK BOARD-SAFE en revue de clôture / Comité d'audit.
    # Un agenda ALERTS_ONLY (revue de clôture) n'est pas un comité de décision
    # commerciale : on retire les slides marketing/commercial et valorisation (hors
    # objet, non board-safe) et on reformule « décisions » en points à remonter.
    # Signal dérivé du brief/CR (genre), sans dépendance au plumbing amont.
    _board_safe = bool(extra_context.get("board_safe"))
    if not _board_safe:
        try:
            from patches.agenda_genre import detect_agenda_genre as _dag_deck
            _g_deck = _dag_deck(report_text or "")
            _board_safe = (bool(getattr(_g_deck, "forbids_go_nogo", False))
                           or str(getattr(_g_deck, "decision_mode", "")).upper() == "ALERTS_ONLY")
        except Exception:
            _board_safe = False
    data["board_safe"] = _board_safe

    # v16.5.28 : routing adaptatif hybride (JSON IA + signaux textuels) — déjà
    # calculé en amont (avant l'enrichissement commercial, cf. S.2.2.1).
    # v16.5.67.9 — propagation brief_mode pour tagging visuel pastilles GENERIC
    data["brief_mode"] = (extra_context.get("brief_mode") or "").upper()
    if deck_type == "corporate" and not _from_objects62424:
        _enrich_corporate_context_if_needed(data, report_text)
        # v16.5.67.3 — Fix Supply Chain fantôme (bug observé run 19/04) :
        # Ce bloc réactivait la slide SC via _sc_material_signal (mots comme
        # "cash", "pricing", "fournisseur" dans le texte du CR) MÊME QUAND
        # le pipeline avait explicitement déclaré supply_chain_bundle_status
        # = "SKIPPED" en amont (profil services / solo).
        # Règle corrigée : si le pipeline a explicitement skippé, AUCUN signal
        # textuel dans le CR ne peut rétablir la slide. La décision amont est
        # la vérité de référence.
        # S.2.3 — consumption gate. On ne FORCE plus une slide SC à partir de
        # signaux textuels du CR (_sc_material_signal grattait cash/pricing/fournisseur
        # n'importe où dans le CR et reconstruisait une slide molle). Règle :
        #  - SKIPPED amont → slide absente (la SC ne s'applique pas).
        #  - JSON SC valide → déjà consommé en amont (inchangé).
        #  - sinon (corporate, non SKIPPED) → slide explicite « non couvert ».
        sc_status_upstream = str(data.get("supply_chain_bundle_status") or "").upper()
        if sc_status_upstream != "SKIPPED":
            _scp = data.get("supply_chain") or {}
            if _scp.get("not_covered"):
                _scp["enabled"] = True
                data["supply_chain"] = _scp

    # ── B.1.3.28-chatgpt — EXECUTIVE EVIDENCE GUARD, real wiring ───────────
    # Runs after corporate-context enrichment, and covers the actual corporate
    # headline fields, SWOT/axes/roadmap/commercial/supply surfaces.
    try:
        from patches.executive_evidence_guard import (
            govern_executive_payload as _gep28,
            govern_kpi_value as _gkv28,  # compatibility token + direct contract
            kpi_stability_check as _ksc28,
        )
        _lang28 = str(data.get("lang", "fr") or "fr")
        _stats28 = _gep28(
            data, report_text, _lang28,
            (extra_context or {}).get("financial_facts_table"),
        )
        _headline28 = list(_stats28.get("headline_values") or [])
        _note28 = _ksc28(
            (extra_context or {}).get("runtime_state_dir"),
            (extra_context or {}).get("att_hash"),
            _headline28[:1],
            _lang28,
        )
        if _note28:
            data.setdefault("pipeline_flags", []).append(_note28)
            _cc28 = data.get("contexte_corporate")
            _mm28 = data.get("marche")
            if isinstance(_cc28, dict) and _cc28.get("ca"):
                _cc28["ca"] = ("Instable entre runs — à vérifier"
                               if _lang28 == "fr" else
                               "Unstable across runs — to verify")
            elif isinstance(_mm28, dict) and _mm28.get("taille"):
                _mm28["taille"] = ("Instable entre runs — à vérifier"
                                   if _lang28 == "fr" else
                                   "Unstable across runs — to verify")
        _deck_diag28.update({
            "executive_guard_changed": int(_stats28.get("changed") or 0),
            "executive_hypothesis_kpis": bool(_stats28.get("hypothesis_kpis")),
            "numeric_instability": bool(_note28),
        })
    except Exception as _eeg_err:
        try:
            import logging
            logging.getLogger("codir").warning(
                "executive_evidence_guard failed: %s", _eeg_err)
        except Exception:
            pass

    # v62.11 — the executive evidence guard may demote values that are not
    # reproduced verbatim in the narrative CR.  Page-confirmed ledger facts
    # are stronger than narrative presence, so re-assert those KPI cards at
    # the final common boundary before rendering.
    try:
        from utils.financial_proof_layer import inject_confirmed_financial_kpis as _icfk6211_final
        _deck_diag28["financial_proof_kpis_final"] = _icfk6211_final(
            data, (extra_context or {}).get("financial_facts_table"), lang=lang,
            canonical_claims=(extra_context or {}).get("canonical_financial_claims"),
            external_facts=(_result_meta51(extra_context, "external_facts50") or {}).get("facts"),
            analysis_date=str((((extra_context or {}).get("result") or {}).get("temporal_authority") or {}).get("analysis_date") or ""),
            fiscal_year_end=str(_result_meta51(extra_context, "fiscal_year_end50")))
        _fill_headcount51(data, extra_context, lang)
    except Exception as _kpi_final_exc6211:
        _deck_diag28["financial_proof_kpis_final"] = {
            "status": "ERROR",
            "error": f"{type(_kpi_final_exc6211).__name__}: {str(_kpi_final_exc6211)[:120]}",
        }

    # B.1.3.47-chatgpt — garde comptable transversale au dernier point de
    # convergence du payload deck. Elle couvre risques, arbitrages, axes, roadmap
    # et prochaines étapes, pas seulement le registre d'actions.
    try:
        from patches.codir_register_history import govern_accounting_commitment_text as _gact47
        _accounting_changed47 = 0
        def _accounting_sweep47(node):
            nonlocal _accounting_changed47
            if isinstance(node, str):
                _new, _n = _gact47(node, lang=lang)
                _accounting_changed47 += _n
                return _new
            if isinstance(node, list):
                return [_accounting_sweep47(x) for x in node]
            if isinstance(node, dict):
                return {k: _accounting_sweep47(v) for k, v in node.items()}
            return node
        data = _accounting_sweep47(data)
        if _accounting_changed47:
            _deck_diag28["accounting_action_guard_changed"] = _accounting_changed47
    except Exception as _accounting_action_exc54:
        # TRUTH_FAIL_CLOSED — a deck must not be produced from an ungoverned
        # accounting-action payload.  The caller receives an explicit failure
        # instead of a visually valid but potentially false presentation.
        raise RuntimeError(
            "accounting action guard failed before PPTX rendering") from _accounting_action_exc54

    prs = Presentation()
    prs.slide_width  = Inches(10)
    prs.slide_height = Inches(5.625)

    _slide_titre(prs, data)
    _b13_emitted = _slide_cadre_prudence(prs, data)   # B.1.3 — prudence slide 2
    _slide_essentiel(prs, data)   # H2-R1 — l'essentiel en 90 s (slide 3)
    try:
        _deck_diag28["slide_emitted"] = bool(_b13_emitted)
    except Exception:
        pass

    if deck_type == "corporate":
        # v62.7 — le mode Working Deck est la surface produit : 8-15 slides
        # orientées présentation orale. Les registres, historiques et ledgers
        # restent dans le Word/JSON. Le mode strict conserve le deck complet
        # pour les audits internes et les tests de surqualité.
        _slide_contexte_corporate(prs, data)
        # v62.13.9.4.31 — demande de Robin (09/09) et contre-audit v30 : le plan
        # du deck découle des questions du brief. Quand le dossier porte une étude
        # de marché, elle est restituée AVANT les préconisations, y compris sur un
        # deck d'entreprise — le marché n'est pas réservé aux dossiers solo.
        _m31c = data.get("marche") or {}
        if any(str(v).strip() for v in _m31c.values() if isinstance(v, str)) or _m31c.get("segments") or _m31c.get("drivers"):
            if _m31c.get("drivers") and _m31c.get("segments"):
                data["_marche_part"] = "offre"; _slide_marche(prs, data)
                data["_marche_part"] = "demande"; _slide_marche(prs, data)
                data.pop("_marche_part", None)
            else:
                _slide_marche(prs, data)
        _slide_swot(prs, data)
        _slide_axes(prs, data)
        _slide_supply_chain(prs, data)
        if not data.get("board_safe"):          # C-01a — hors objet en revue de clôture
            _slide_commercial(prs, data)
        _slide_risques_arbitrages(prs, data)
        _slide_roadmap(prs, data)
        _slide_next_steps(prs, data)
        # v62.13.9.4.41 — la planche de registre reste réservée au mode strict : le deck de
        # travail garde sa forme gelée (huit à quinze planches, sans annexe). Le filet qui
        # empêche un engagement de disparaître est l'annexe de CONTINUATION, ajoutée juste
        # avant la sauvegarde et seulement s'il reste des objets qu'aucune planche ne porte.
        if _pptx_mode == "strict":
            _slide_registre_actions(prs, data)
            _slide_suivi_multiseances(prs, data)
            _slide_historique_codir(prs, data)
            _slide_faits_marche(prs, data)
            if not data.get("board_safe"):      # C-01a — valorisation non board-safe
                _slide_valorisation(prs, data)
        _slide_conclusion(prs, data)
    else:
        # Deck SOLO : même séparation surface/profondeur.
        # v62.13.9.4.23 — contrat de trame : une slide n'existe que si son
        # sujet est traité (« pas de slide stocks si le dossier n'en parle
        # pas, pas de case remplie parce que le gabarit a un emplacement »).
        _from_objects = str(data.get("_built_from") or "") == "analysis_objects"
        _topics = set(data.get("_topics") or [])
        _has = lambda *keys: any(str(data.get(k) or "").strip() for k in keys)   # noqa: E731
        # v62.13.9.4.31 — demande de Robin (09/09) et contre-audit v30 : quand le
        # dossier porte une étude de marché, le deck la restitue AVANT les
        # préconisations. La slide est incluse dès qu'il y a de la matière —
        # segments de demande ou facteurs de marché — pas seulement des chiffres.
        _m31 = data.get("marche") or {}
        if (not _from_objects
                or any(str(v).strip() for v in _m31.values() if isinstance(v, str))
                or (_m31.get("segments") or _m31.get("drivers"))):
            # v62.13.9.4.31 — au plus deux slides marché (offre puis demande), et
            # jamais plus de points par slide que le budget éditorial H2.
            if _m31.get("drivers") and _m31.get("segments"):
                data["_marche_part"] = "offre"; _slide_marche(prs, data)
                data["_marche_part"] = "demande"; _slide_marche(prs, data)
                data.pop("_marche_part", None)
            else:
                _slide_marche(prs, data)
        _slide_swot(prs, data)
        _slide_axes(prs, data)
        if not _from_objects or "supply_chain" in _topics:
            _slide_supply_chain(prs, data)
        if not data.get("board_safe") and (not _from_objects or (data.get("commercial") or {}).get("titre")):   # C-01a
            _slide_commercial(prs, data)
        _me = data.get("modele_eco") or {}
        if not _from_objects or any(str(_me.get(k) or "").strip() for k in ("tjm_actuel", "tjm_marche", "tjm_cible")) or _me.get("temps_partage") or _me.get("reseau"):
            _slide_modele_eco(prs, data)
        _slide_roadmap(prs, data)
        _slide_next_steps(prs, data)
        # v62.13.9.4.41 — la planche de registre reste réservée au mode strict : le deck de
        # travail garde sa forme gelée (huit à quinze planches, sans annexe). Le filet qui
        # empêche un engagement de disparaître est l'annexe de CONTINUATION, ajoutée juste
        # avant la sauvegarde et seulement s'il reste des objets qu'aucune planche ne porte.
        if _pptx_mode == "strict":
            _slide_registre_actions(prs, data)
            _slide_suivi_multiseances(prs, data)
            _slide_historique_codir(prs, data)
            _slide_faits_marche(prs, data)
            if not data.get("board_safe"):      # C-01a
                _slide_valorisation(prs, data)
        _slide_conclusion(prs, data)

    _deck_diag28["slides_before_enrichment"] = len(prs.slides)
    _deck_diag28["annex_slides_included"] = (_pptx_mode == "strict")

    # M.5.10.11 — passe finale de localisation EN sur tout le deck (textboxes +
    # tableaux + groupes) : SC fallback, GLEIF, tags épistémiques. Garantit P0-5
    # sur le PPTX complet, quelle que soit la fonction qui a écrit le texte.
    try:
        _localize_presentation(prs, lang)
    except Exception:
        pass

    buf = io.BytesIO()
    try:
        from patches.entity_scope import lock_entity_in_pptx_titles as _lock_pptx
        _an = (extra_context.get("analysis_entity_display") or "").strip()
        _rg = (extra_context.get("registry_entity_display") or "").strip()
        if _an and _rg:
            _lock_pptx(prs, _an, _rg)   # titres deck → entité d'analyse (filet)
    except Exception:
        pass
    try:
        from patches.lexicon_gate import sanitize_pptx as _san_pptx, LEXICON_STATS as _lx
        _n = _san_pptx(prs)   # neutralise tout résidu VALIDATED/DECIDED/BLOCKING
        _lx["status"] = "ok"
        import logging as _lg
        _lg.getLogger("codir.lexicon").info("lexicon gate (pptx): %d remplacements", _n)
    except Exception as _e:
        try:
            from patches.lexicon_gate import LEXICON_STATS as _lx
            _lx["status"] = "failed"
        except Exception:
            pass
        import logging as _lg
        _lg.getLogger("codir.lexicon").warning("lexicon gate pptx KO: %s", _e)
    # Temporal Core Refactor — bandeau temporel DÉTERMINISTE sur la
    # slide de garde (jamais confié au modèle) : un deck non-live ou
    # bloqué porte son statut quoi qu'il arrive.
    try:
        _tsl19 = str((extra_context or {}).get("temporal_status_line")
                     or "").strip()
        if _tsl19 and getattr(prs, "slides", None) and len(prs.slides):
            from pptx.dml.color import RGBColor as _RGB19
            from pptx.util import Inches as _In19, Pt as _Pt19
            _sl0 = prs.slides[0]
            _tb19 = _sl0.shapes.add_textbox(
                _In19(0.28), _In19(4.68),
                prs.slide_width - _In19(0.63), _In19(0.50))
            _tb19.name = "HCRIT:cover:temporal-banner"
            _tb19.fill.solid()
            _tb19.fill.fore_color.rgb = _RGB19(0xE8, 0xB8, 0x4B)
            _tb19.line.fill.background()
            _tf19 = _tb19.text_frame
            _tf19.word_wrap = True
            _tf19.margin_left = _tf19.margin_right = _In19(0.10)
            _tf19.margin_top = _tf19.margin_bottom = _In19(0.03)
            _tf19.text = _tsl19
            try:
                _r19 = _tf19.paragraphs[0].runs[0]
                _r19.font.size = _Pt19(11)
                _r19.font.bold = True
                _r19.font.color.rgb = _RGB19(0x0D, 0x14, 0x3D)
            except Exception:
                pass
    except Exception:
        pass
    try:
        from utils.ai_content_marking import apply_marking as _mark50
        from version import PUBLISHER as _PUB
        _mark50(prs, provider=_PUB)
    except Exception:
        pass
    try:
        # Chantier H (10/08/2026) — filet géométrique systémique avant scellement.
        from utils.deck_layout_guard import apply_deck_layout_guard as _h2_guard
        _h2_guard(prs)
    except Exception:
        pass
    # v62.13.9.4.41 — RÉCONCILIATION AVANT SAUVEGARDE, SUR LE FICHIER ET NON SUR LA TRAME.
    # Juger la couverture sur la structure était l'erreur de fond : un objet rangé dans une
    # case dont la planche n'écrit que le titre passait pour couvert. Un seul point de
    # vérité : ce que les planches portent réellement. Ce qui manque part dans une annexe
    # de continuation ; ce qui n'y tient pas est inscrit dans la trace avec son motif.
    try:
        import re as _re41
        from utils.objects_render import trace_template_cut41 as _ttc41
        _n41 = lambda x: _re41.sub(r"\s+", " ", str(x or "")).strip().lower()
        _written41 = _n41(" ".join(
            [sh.text_frame.text for sl in prs.slides for sh in sl.shapes
             if getattr(sh, "has_text_frame", False)]
            + [c.text for sl in prs.slides for sh in sl.shapes
               if getattr(sh, "has_table", False) for rw in sh.table.rows for c in rw.cells]))
        _bk41 = (((extra_context or {}).get("result") or {}).get("analysis_objects") or {}).get("by_kind") or {}
        _objs41 = [o for k in ("action", "decision") for o in (_bk41.get(k) or [])
                   if isinstance(o, dict) and _n41(o.get("text"))[:40]
                   and _n41(o.get("text"))[:40] not in _written41]
        if _objs41:
            _lang41 = data.get("lang", lang)
            _hd41 = (["Action", "Porteur", "Échéance"] if _lang41 == "fr"
                     else ["Action", "Owner", "Deadline"])
            _rows41 = [[_h2_exec(_clean_bullet_full(str(o.get("text") or "")), _lang41)[:160],
                        str(o.get("owner") or "") or "—", str(o.get("deadline") or "") or "—"]
                       for o in _objs41[:8]]
            _slide_table_generic(
                prs, "▷",
                "Engagements — suite" if _lang41 == "fr" else "Commitments — continued",
                "Repris de l'analyse, non portés par les planches précédentes" if _lang41 == "fr"
                else "Carried from the analysis, not shown on the previous slides",
                _hd41, _rows41, _lang41, col_widths=[5.6, 1.9, 1.4], cut_kind="generic")
            if len(_objs41) > 8:
                _ttc41(_objs41[8:], "au-delà de la capacité de l'annexe de continuation")
    except Exception:
        pass
    prs.save(buf)
    pptx_bytes = buf.getvalue()
    if output_path:
        Path(output_path).write_bytes(pptx_bytes)
    # Publish one completed snapshot.  The per-call sink is authoritative for
    # substantive decisions; the module global is legacy instrumentation only.
    if isinstance(_diag_out28, dict):
        _diag_out28.clear()
        _diag_out28.update(_deck_diag28)
    LAST_DECK_DIAG.clear()
    LAST_DECK_DIAG.update(_deck_diag28)
    return pptx_bytes
