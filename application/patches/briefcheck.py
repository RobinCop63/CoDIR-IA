"""
CoDIR-IA — briefcheck v1.1 (v16.5.65 — livraison 2 partie A)

Module autonome de vérification du brief et préparation du contexte pipeline.

v1.0 (v16.5.63) — Partie 1 :
- 1.1.1 Détection "documents mentionnés mais non attachés"
- 1.1.2 Résolution horizon
- 1.1.3 Détection besoin d'expansion holding → filiales

v1.1 (v16.5.65) — Partie 2 : DÉTECTION DU MODE DE BRIEFING
- 1.2.1 Détection des 4 leviers de qualification :
    (a) contexte société explicite (SIREN, nom, ou profil confiance>low)
    (b) chiffres-clés présents (≥2 métriques financières/opérationnelles)
    (c) décision attendue formulée (go/no-go, arbitrage, choix)
    (d) enjeu qualifié (risque, contrainte, tension, urgence)
- 1.2.2 Calcul du brief_mode ∈ {GENERIC, PARTIAL, FRAMED} + plafond score
- 1.2.3 Template de brief minimal retourné en mode GENERIC (pédagogie)
- 1.2.4 Bandeau markdown "MODE GÉNÉRIQUE" / "MODE PARTIEL" pour rendu UI

USAGE
-----
    from patches.briefcheck import run_briefcheck

    result = run_briefcheck(
        brief_text="Analyse dossier réseau de soins sur la base des documents définitifs 2022...",
        attachments=[Path("uploads/liasse.pdf")],  # ou []
        lang="fr",
        company_profile={"ape_code": "7021Z", "is_holding": True, "ca_eur": 38300000},
    )

    # result["doc_check"]["severity"] ∈ {"OK", "WARN_BANNER"}
    # result["horizon"] ∈ {"T+90j", "FY_N1", "FY_N1_N3", "FY_N1_N5"}
    # result["scope_expansion"]["should_expand"] : bool
    # result["banner_markdown"] : str (vide si OK, markdown sinon)
    # result["brief_mode"] : {
    #     "mode": "GENERIC" | "PARTIAL" | "FRAMED",
    #     "score_cap": int,
    #     "leviers": {"context": bool, "figures": bool, "decision": bool, "issues": bool},
    #     "present_count": int (0..4),
    #     "missing": list[str],
    #     "banner_markdown": str,
    #     "suggested_template": str (vide sauf en GENERIC),
    # }

Module PUR : aucun I/O réseau.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


# =============================================================================
# PATTERNS DE DÉTECTION DOCUMENTS (v4 section 1.1.1)
# =============================================================================

DOC_PATTERNS_FR: list[str] = [
    # Comptes et états financiers
    r"\b(liasse[s]?\s+(?:fiscale[s]?|de\s+consolidation)?)\b",
    r"\b(compte[s]?\s+(?:de\s+r[ée]sultat|sociaux|consolid[ée]s?|annuels?))\b",
    r"\b(bilan[s]?|balance\s+g[ée]n[ée]rale|grand[- ]?livre|FEC)\b",
    r"\b(annexe[s]?\s+(?:comptables?|financi[èe]res?)?)\b",
    r"\b(reporting|tableau\s+de\s+bord|TDB)\b",
    # Prévisionnel
    r"\b(budget[s]?|BP|business\s+plan|pr[ée]visionnel|plan\s+de\s+tr[ée]sorerie)\b",
    r"\b(forecast|atterrissage|re[- ]?pr[ée]vi)",
    # Références indicatives
    r"\b(documents?\s+(?:d[ée]finitifs?|fournis?|joints?|en\s+annexe|de\s+cl[ôo]ture))\b",
    r"\b(pi[èe]ces?\s+(?:jointes?|comptables?|justificatives?))\b",
    r"\b(les\s+[ée]l[ée]ments\s+(?:fournis?|transmis?|communiqu[ée]s?))\b",
    r"\bsur\s+la\s+base\s+(?:du|des|de\s+(?:la|l['']))",
]

DOC_PATTERNS_EN: list[str] = [
    r"\b(trial\s+balance|general\s+ledger|closing\s+documents?)\b",
    r"\b(management\s+accounts?|financial\s+statements?|P\s*&?\s*L|balance\s+sheet)\b",
    r"\b(budget|business\s+plan|forecast|cash\s+plan)\b",
    r"\b(attached\s+(?:documents?|files?)|based\s+on\s+the\s+(?:provided|attached))\b",
]


# =============================================================================
# PATTERNS HORIZON (v4 section 1.1.2)
# =============================================================================

HORIZON_PATTERNS: list[tuple[str, str]] = [
    # (regex, horizon normalisé) — ORDRE IMPORTANT : du plus long au plus court
    (r"\b(\+?\s*5\s*ans|long\s+terme|plan\s+(?:quinqu|5\s*)annuel|strat[ée]gique\s+long)\b",
     "FY_N1_N5"),
    (r"\b(\+?\s*(?:2|3|4)\s*ans|plan\s+(?:tri|3|quadri|4)\s*annuel|moyen\s+terme|pluriannuel)\b",
     "FY_N1_N3"),
    (r"\b(\+?\s*1\s*an|N\s*\+\s*1|exercice\s+suivant|prochaine?\s+ann[ée]e|plus\s+d['']?\s*un\s+an)\b",
     "FY_N1_N3"),  # "plus d'un an" implique minimum pluriannuel
    (r"\b(T\+?90|90\s*jours|trois\s+mois|3\s*mois|premier\s+trimestre|Q1)\b",
     "T+90j"),
]

HORIZON_PATTERNS_EN: list[tuple[str, str]] = [
    (r"\b(\+?\s*5\s*years?|long[- ]term|5[- ]year\s+plan)\b", "FY_N1_N5"),
    (r"\b(\+?\s*(?:2|3|4)\s*years?|mid[- ]term|multi[- ]year|3[- ]year\s+plan)\b", "FY_N1_N3"),
    (r"\b(\+?\s*1\s*year|next\s+(?:fiscal|financial)?\s*year|following\s+FY|over\s+a\s+year)\b", "FY_N1_N3"),
    (r"\b(T\+?90|90\s*days|three\s+months|3\s*months|first\s+quarter|Q1)\b", "T+90j"),
]


# =============================================================================
# EXPANSION HOLDING (v4 section 1.1.3)
# =============================================================================

HOLDING_APE_PREFIXES: tuple[str, ...] = (
    "70.10", "70.1",   # Activités des sièges sociaux
    "70.2", "70.21",   # Conseil / conseil en RP
    "64.2", "64.20",   # Activités de holding financière
)


def should_expand_to_subsidiaries(company_profile: dict | None,
                                  subsidiaries: list[dict] | None = None) -> bool:
    """
    Détermine si le pipeline doit remonter de la holding vers les filiales.
    
    Critères (OR) :
    - Code APE de la mère commence par un préfixe holding (70.x, 64.2)
    - Profile explicitement marqué is_holding=True
    - CA mère < 10% du CA cumulé filiales (quand filiales connues)
    - Forme juridique SPFPL ou SPF
    """
    if company_profile is None:
        return False
    
    ape = str(company_profile.get("ape_code", "")).replace(" ", "").upper()
    if any(ape.startswith(p.replace(".", "")) or ape.startswith(p)
           for p in HOLDING_APE_PREFIXES):
        return True
    
    if company_profile.get("is_holding") is True:
        return True
    
    legal = str(company_profile.get("legal_form", "")).lower()
    if "société de participation" in legal or "spf" in legal.split():
        return True
    
    if subsidiaries:
        ca_mother = company_profile.get("ca_eur") or 0
        ca_subs = sum(s.get("ca_eur", 0) for s in subsidiaries)
        if ca_subs > 0 and ca_mother > 0 and ca_mother < 0.10 * ca_subs:
            return True
    
    return False


# =============================================================================
# HEURISTIQUES DE DÉTECTION PIÈCES FINANCIÈRES
# =============================================================================

FINANCIAL_FILE_EXTENSIONS: set[str] = {".xlsx", ".xlsm", ".xls", ".csv", ".pdf", ".xml"}
FINANCIAL_FILE_KEYWORDS: tuple[str, ...] = (
    "liasse", "kbis", "bilan", "compte", "resultat", "budget", "reporting",
    "fec", "balance", "tdb", "atterrissage", "previsionnel", "rapport",
    "cac", "annexe", "grand_livre", "gl",
)


def _looks_like_financial(path: Path) -> bool:
    """Heuristique simple : extension + mot-clé dans le nom."""
    if path.suffix.lower() not in FINANCIAL_FILE_EXTENSIONS:
        return False
    name_lower = path.name.lower()
    return any(kw in name_lower for kw in FINANCIAL_FILE_KEYWORDS)


def has_financial_attachment(attachments: list[Path] | None) -> bool:
    if not attachments:
        return False
    return any(_looks_like_financial(a) for a in attachments)


# =============================================================================
# DÉTECTION DES RÉFÉRENCES DOCUMENTAIRES
# =============================================================================

def detect_doc_references(brief_text: str, lang: str = "fr") -> list[dict]:
    """Retourne les matches trouvés dans le brief."""
    patterns = DOC_PATTERNS_FR if lang == "fr" else DOC_PATTERNS_EN
    hits = []
    for p in patterns:
        try:
            for m in re.finditer(p, brief_text, flags=re.IGNORECASE | re.UNICODE):
                hits.append({
                    "pattern": p,
                    "match": m.group(0),
                    "pos": m.start(),
                })
        except re.error:
            # pattern invalide ignoré (robustesse)
            continue
    return hits


# =============================================================================
# COMPLETENESS CHECK — produit le bandeau conditionnel
# =============================================================================

def briefcheck_doc_completeness(brief_text: str,
                                attachments: list[Path] | None,
                                lang: str = "fr",
                                source_mode: str = "OPEN",
                                financial_block_present: bool = False) -> dict:
    """
    Vérifie la cohérence entre les documents mentionnés dans le brief et
    les pièces réellement attachées.

    F.6.7.1 — corrige deux contradictions du run dossier réseau de soins :
      - `financial_block_present` : si le moteur a déjà parsé des états financiers
        (financial_statements_block / bundles / attachments_meta), les pièces SONT
        présentes même si les noms de fichiers (ex. dossier réseau de soins~1.PDF) ne contiennent
        pas de mot-clé « bilan / liasse ». On ne dit plus « aucune pièce attachée ».
      - `source_mode=ATTACHMENTS_ONLY` : on ne cite JAMAIS « données publiques
        Pappers » (Pappers est désactivé dans ce mode).

    Retourne:
    - severity: "OK" | "WARN_BANNER"
    - refs_found, has_financial_attachment, banner_markdown
    """
    refs = detect_doc_references(brief_text, lang)
    has_fin = has_financial_attachment(attachments) or bool(financial_block_present)
    attachments_present = bool(attachments) or bool(financial_block_present)
    attach_only = (source_mode == "ATTACHMENTS_ONLY")

    if refs and not has_fin:
        # Exemples les plus parlants pour le bandeau (dédup, max 3)
        seen = set()
        examples = []
        for h in refs:
            m = h["match"].lower().strip()
            if m not in seen:
                seen.add(m)
                examples.append(h["match"])
            if len(examples) >= 3:
                break

        # Provenance des chiffres : en mode pièces jointes, jamais Pappers.
        if lang == "fr":
            if attachments_present:
                head = ("Des pièces jointes sont présentes, mais leur signal financier "
                        "n'a pas pu être reconnu automatiquement (noms de fichiers non "
                        "explicites). Vérifier manuellement leur contenu comptable — ne "
                        "pas conclure à une absence de pièces.")
            else:
                head = (f"Le brief mentionne des documents comptables ou prévisionnels "
                        f"({', '.join(examples)}…) mais aucune pièce financière n'a été "
                        f"attachée à la session.")
            if attach_only:
                prov = ("- exclusivement les pièces jointes fournies (mode pièces jointes "
                        "uniquement — aucune source externe, Pappers désactivé)\n"
                        "- inférences et ordres de grandeur du modèle, signalés comme tels\n\n")
            else:
                prov = ("- données publiques Pappers (comptes sociaux déposés)\n"
                        "- inférences et ordres de grandeur du modèle\n\n")
            banner = (
                "⚠️ **AVERTISSEMENT — Vérifier les pièces sources**\n\n"
                + head + "\n\n"
                "**Les chiffres produits dans ce livrable sont issus de :**\n"
                + prov +
                "Ils **ne doivent pas être présentés à un DG/Conseil** en l'état "
                "sans rapprochement avec les pièces comptables réelles."
            )
        else:
            if attachments_present:
                head = ("Attachments are present, but their financial signal could not "
                        "be auto-recognised (non-explicit file names). Check their "
                        "accounting content manually — do not conclude there are no documents.")
            else:
                head = (f"The brief references accounting or forecast documents "
                        f"({', '.join(examples)}…) but no financial document has been "
                        f"attached to the session.")
            if attach_only:
                prov = ("- the attached files only (attachments-only mode — no external "
                        "source, Pappers disabled)\n"
                        "- model inferences and orders of magnitude, flagged as such\n\n")
            else:
                prov = ("- public Pappers data (filed statutory accounts)\n"
                        "- model inferences and orders of magnitude\n\n")
            banner = (
                "⚠️ **WARNING — Verify source documents**\n\n"
                + head + "\n\n"
                "**Figures produced in this deliverable are based on:**\n"
                + prov +
                "They **should not be presented to a CEO/Board** as-is without "
                "reconciliation against actual accounting records."
            )
        return {
            "severity": "WARN_BANNER",
            "refs_found": refs,
            "has_financial_attachment": False,
            "attachments_present": attachments_present,
            "banner_markdown": banner,
        }

    return {
        "severity": "OK",
        "refs_found": refs,
        "has_financial_attachment": has_fin,
        "attachments_present": attachments_present,
        "banner_markdown": "",
    }


# =============================================================================
# RÉSOLUTION HORIZON
# =============================================================================

def resolve_horizon(brief_text: str, lang: str = "fr",
                    default: str = "FY_N1") -> str:
    """
    Déduit l'horizon voulu depuis le brief.
    Ordre : patterns spécifiques, puis règle spéciale "plan stratégique + filiales/croissance",
    puis default.
    """
    patterns = HORIZON_PATTERNS if lang == "fr" else HORIZON_PATTERNS_EN
    text = brief_text.lower() if brief_text else ""
    
    for pattern, horizon in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return horizon
    
    # Règle spéciale : plan stratégique mentionnant filiales ou croissance
    if lang == "fr":
        if (re.search(r"plan\s+strat[ée]gique", text)
                and re.search(r"filiales?|croissance|d[ée]veloppement", text)):
            return "FY_N1_N3"
    else:
        if (re.search(r"strategic\s+plan", text)
                and re.search(r"subsidiaries|growth|expansion", text)):
            return "FY_N1_N3"
    
    return default


# =============================================================================
# MODE DE BRIEFING (v1.1 — v16.5.65) — 4 leviers de qualification
# =============================================================================
# Principe : un brief doit réunir 4 éléments pour que le pipeline produise
# un livrable actionnable. Moins il y en a, plus le score est plafonné
# mécaniquement. L'utilisateur voit un bandeau explicite en tête du livrable.
#
# Leviers détectés (indépendants, combinables) :
#   (a) CONTEXT  — contexte société identifiable
#   (b) FIGURES  — chiffres-clés exploitables (≥2 métriques)
#   (c) DECISION — décision ou arbitrage attendu formulé
#   (d) ISSUES   — enjeu / contrainte / tension explicite
#
# Seuils :
#   0 levier      → GENERIC  (cap 45 → Grade D max)
#   1-3 leviers   → PARTIAL  (cap 70 → Grade B max)
#   4 leviers     → FRAMED   (cap 100, pas de plafond)
# =============================================================================

MODE_GENERIC = "GENERIC"
MODE_PARTIAL = "PARTIAL"
MODE_FRAMED  = "FRAMED"

# Plafonds de score cohérents avec les grades A-E du confidence_scorer
# (grade A ≥ 85, B ≥ 70, C ≥ 60, D ≥ 45, E ≥ 0)
MODE_SCORE_CAP: dict[str, int] = {
    MODE_GENERIC: 45,    # plafonné à Grade D
    MODE_PARTIAL: 70,    # plafonné à Grade B
    MODE_FRAMED:  100,   # aucun plafond additionnel
}

LEVIER_LABELS_FR: dict[str, str] = {
    "context":  "Contexte société (nom, SIREN, secteur, forme juridique)",
    "figures":  "Chiffres-clés (≥2 métriques : CA, effectif, cash, marge…)",
    "decision": "Décision attendue (go/no-go, arbitrage, choix explicite)",
    "issues":   "Enjeu qualifié (risque, contrainte, tension, urgence)",
}

LEVIER_LABELS_EN: dict[str, str] = {
    "context":  "Company context (name, registry ID, sector, legal form)",
    "figures":  "Key figures (≥2 metrics: revenue, headcount, cash, margin…)",
    "decision": "Decision expected (go/no-go, trade-off, explicit choice)",
    "issues":   "Qualified issue (risk, constraint, tension, urgency)",
}


# ── (a) CONTEXTE SOCIÉTÉ ────────────────────────────────────────────────────

_RE_SIREN  = re.compile(r"\b\d{3}\s?\d{3}\s?\d{3}\b")
_RE_SIRET  = re.compile(r"\b\d{3}\s?\d{3}\s?\d{3}\s?\d{5}\b")
_RE_LEGAL_FORM = re.compile(
    r"\b(SAS(?:U)?|SARL|EURL|SASU|SA\b|SCI|SNC|SCA|SCS|GIE|SELARL|SELAS|SELAFA|SE\b|SCOP|SCIC|micro[- ]entreprise)\b",
    re.IGNORECASE,
)
_RE_COMPANY_HINT = re.compile(
    r"\b(Groupe\s+[A-ZÉÈÊÀÂÎÔÛ][\wÉÈÊÀÂÎÔÛéèêàâîôû\-]+|"
    r"[A-ZÉÈÊÀÂÎÔÛ][\wÉÈÊÀÂÎÔÛéèêàâîôû\-]+\s+(?:SAS|SARL|SASU|EURL|SA|SCI)\b|"
    r"[A-ZÉÈÊÀÂÎÔÛ][\wÉÈÊÀÂÎÔÛéèêàâîôû\-]+\s+&\s+(?:Associés|Partenaires|Fils|Cie))",
    re.UNICODE,
)

def detect_company_context(brief_text: str,
                           company_profile: dict | None = None) -> dict:
    """
    Retourne {"found": bool, "evidence": list[str]}.

    Signaux positifs :
    - SIREN / SIRET dans le brief
    - forme juridique mentionnée (SAS, SARL...)
    - pattern nom-société ("Groupe X", "X SAS", "X & Associés")
    - company_profile.confidence >= medium ET source != default
    """
    brief_text = brief_text or ""
    evidence: list[str] = []

    m = _RE_SIRET.search(brief_text)
    if m:
        evidence.append(f"SIRET: {m.group(0)}")
    else:
        m = _RE_SIREN.search(brief_text)
        if m:
            evidence.append(f"SIREN: {m.group(0)}")

    m = _RE_LEGAL_FORM.search(brief_text)
    if m:
        evidence.append(f"legal_form: {m.group(0)}")

    m = _RE_COMPANY_HINT.search(brief_text)
    if m and len(m.group(0)) < 60:
        evidence.append(f"company_hint: {m.group(0).strip()}")

    # company_profile : on ne retient que si le profil a été résolu avec un minimum
    # de confiance (ex. Pappers trouvé ou brief bien structuré). Un profil par défaut
    # (source=default, confidence=low) ne compte pas — c'est justement ce qu'on veut
    # détecter comme "mode générique".
    if company_profile and isinstance(company_profile, dict):
        conf = str(company_profile.get("confidence", "low")).lower()
        src = str(company_profile.get("source", "default")).lower()
        if conf in ("high", "medium") and src != "default":
            evidence.append(f"company_profile: conf={conf} src={src}")

    return {"found": bool(evidence), "evidence": evidence}


# ── (b) CHIFFRES-CLÉS ───────────────────────────────────────────────────────

_RE_MONEY = re.compile(
    r"(?<![A-Za-z])"
    r"\d{1,4}(?:[ .]\d{3})*(?:[,.]\d+)?\s*"
    r"(?:K[\s\xa0]?€|€|MEUR|M€|Md€|Mrd€|k\$|\$|KUSD|MUSD|£|GBP|EUR|euros?)"
    r"(?![A-Za-z])",
    re.IGNORECASE,
)

_RE_PERCENT_METRIC = re.compile(
    r"\b(?:marge|croissance|rentabilit[ée]|ROI|ROCE|EBITDA|BFR|taux|growth|margin)\b[^.\n]{0,40}?"
    r"\b\d{1,3}(?:[,.]\d{1,2})?\s?%",
    re.IGNORECASE,
)

_RE_HEADCOUNT = re.compile(
    r"\b\d{1,5}\s*(?:salari[ée]s?|collaborateurs?|ETP|FTE|employ[ée]s?|personnes?|employees?|headcount)\b",
    re.IGNORECASE,
)

_RE_DURATION_CYCLE = re.compile(
    r"\b(?:cycle|mission|contrat|p[ée]riode|dur[ée]e)\s+(?:de\s+|moyen(?:ne)?\s+de\s+)?"
    r"\d{1,3}\s*(?:jours?|semaines?|mois|ans?|years?|months?)\b",
    re.IGNORECASE,
)

_RE_FIN_METRIC_LABEL = re.compile(
    r"\b(?:CA|chiffre\s+d['']affaires?|EBIT(?:DA)?|RN|r[ée]sultat\s+(?:net|d['']exploitation)|"
    r"cash\s*(?:flow)?|tr[ée]sorerie|encours|pipeline|carnet\s+de\s+commandes?|MRR|ARR|"
    r"revenue|gross\s+margin|net\s+income)\b"
    r"[^.\n]{0,30}?\d",
    re.IGNORECASE,
)

def detect_key_figures(brief_text: str) -> dict:
    """
    Retourne {"found": bool, "count": int, "evidence": list[str]}.
    Seuil : ≥2 patterns distincts pour valider le levier.

    v16.5.76 item 8 : ajout de la détection des identifiants chiffrés
    structurants (SIREN, dates fiscales FY20XX, périodes Q/T20XX, dates
    jj/mm/aaaa) qui qualifient un brief même sans CA/EBITDA explicites.
    """
    brief_text = brief_text or ""
    evidence: list[str] = []

    if _RE_MONEY.search(brief_text):
        hits = _RE_MONEY.findall(brief_text)
        evidence.append(f"money: {len(hits)} occurrence(s) (ex. {hits[0].strip()})")

    if _RE_PERCENT_METRIC.search(brief_text):
        m = _RE_PERCENT_METRIC.search(brief_text)
        evidence.append(f"percent_metric: {m.group(0)[:60].strip()}")

    if _RE_HEADCOUNT.search(brief_text):
        m = _RE_HEADCOUNT.search(brief_text)
        evidence.append(f"headcount: {m.group(0).strip()}")

    if _RE_DURATION_CYCLE.search(brief_text):
        m = _RE_DURATION_CYCLE.search(brief_text)
        evidence.append(f"duration: {m.group(0).strip()}")

    if _RE_FIN_METRIC_LABEL.search(brief_text):
        m = _RE_FIN_METRIC_LABEL.search(brief_text)
        evidence.append(f"fin_metric: {m.group(0)[:60].strip()}")

    # v16.5.76 item 8 : identifiants chiffrés structurants
    # SIREN (9 chiffres), SIRET (14 chiffres)
    if re.search(r"\b(?:SIREN|SIRET)\b\s*:?\s*\d{9,14}", brief_text, re.IGNORECASE) \
       or re.search(r"\b\d{9}\b(?!\s*\d)", brief_text):
        m = re.search(r"(?:SIREN|SIRET)?\s*\d{9,14}", brief_text, re.IGNORECASE)
        if m:
            evidence.append(f"identifier: {m.group(0).strip()[:30]}")

    # Dates fiscales FY20XX, FY20XX-20XX
    if re.search(r"\bFY\s*20\d{2}(?:[-–]20?\d{2})?\b", brief_text, re.IGNORECASE):
        m = re.search(r"\bFY\s*20\d{2}(?:[-–]20?\d{2})?\b", brief_text, re.IGNORECASE)
        evidence.append(f"fiscal_period: {m.group(0).strip()}")

    # Périodes trimestrielles (T1 2026, Q4 2025)
    if re.search(r"\b(?:T|Q)[1-4]\s+20\d{2}\b", brief_text, re.IGNORECASE):
        m = re.search(r"\b(?:T|Q)[1-4]\s+20\d{2}\b", brief_text, re.IGNORECASE)
        evidence.append(f"quarter: {m.group(0).strip()}")

    # Dates précises jj/mm/aaaa ou aaaa-mm-jj (deadlines structurantes)
    date_pattern = r"\b(?:0?[1-9]|[12]\d|3[01])/(?:0?[1-9]|1[0-2])/20\d{2}\b|\b20\d{2}-(?:0?[1-9]|1[0-2])-(?:0?[1-9]|[12]\d|3[01])\b"
    if re.search(date_pattern, brief_text):
        m = re.search(date_pattern, brief_text)
        evidence.append(f"deadline_date: {m.group(0).strip()}")

    count = len(evidence)
    return {"found": count >= 2, "count": count, "evidence": evidence}


# ── (c) DÉCISION ATTENDUE ───────────────────────────────────────────────────

_RE_DECISION_FR = re.compile(
    r"\b(?:"
    r"go[/\s-]?no[/\s-]?go|"
    r"faut[- ]il|"
    r"doit[- ]on|"
    r"devons[- ]nous|"
    r"d[ée]cider\s+(?:de|si|entre|quel)|"
    r"arbitr(?:er|age)|"
    r"choisir\s+(?:entre|parmi|si)|"
    r"valider\s+(?:le|la|les)|"
    r"option\s+[A1]\s+(?:ou|vs|contre)|"
    r"trancher|"
    r"recommand(?:er|ation)\s+sur|"
    r"quelle?s?\s+options?|"
    r"lancer\s+ou\s+pas|"
    r"continuer\s+ou\s+arr[êe]ter|"
    r"investir\s+ou\s+pas"
    r")\b",
    re.IGNORECASE,
)

_RE_DECISION_EN = re.compile(
    r"\b(?:"
    r"go[/\s-]?no[/\s-]?go|"
    r"should\s+(?:we|i|they)|"
    r"must\s+(?:we|i)|"
    r"decide\s+(?:whether|between|on|if)|"
    r"trade[- ]off|"
    r"choose\s+(?:between|among|whether)|"
    r"approve\s+(?:the|our)|"
    r"option\s+[A1]\s+(?:or|vs)|"
    r"recommendation\s+on|"
    r"which\s+options?|"
    r"launch\s+or\s+not"
    r")\b",
    re.IGNORECASE,
)

def detect_decision_ask(brief_text: str, lang: str = "fr") -> dict:
    """Retourne {"found": bool, "evidence": list[str]}."""
    brief_text = brief_text or ""
    pattern = _RE_DECISION_FR if lang == "fr" else _RE_DECISION_EN
    evidence: list[str] = []

    for m in pattern.finditer(brief_text):
        snippet = m.group(0).strip()
        if snippet not in evidence:
            evidence.append(snippet)
        if len(evidence) >= 3:
            break

    # Question directe + racine verbale de décision
    if not evidence and "?" in brief_text:
        for sent in re.split(r"(?<=[.!?])\s+", brief_text):
            if sent.rstrip().endswith("?"):
                if re.search(
                    r"\b(?:faut|doit|devons|puis[- ]je|dois[- ]je|should|must|can|shall)\b",
                    sent, flags=re.IGNORECASE):
                    evidence.append(f"question: {sent.strip()[:60]}")
                    break

    return {"found": bool(evidence), "evidence": evidence}


# ── (d) ENJEUX QUALIFIÉS ────────────────────────────────────────────────────

_RE_ISSUES_FR = re.compile(
    r"\b(?:"
    r"enjeux?|"
    r"contraint(?:e|s|es)|"
    r"risques?\s+(?:de|que|pour|li[ée]s?\s+[àa])|"
    r"tensions?\s+(?:sur|entre|interne)|"
    r"difficult[ée]s?\s+(?:de|[àa]|pour|avec)|"
    r"obstacles?|"
    r"probl[èe]mes?\s+(?:de|avec|sur|[àa])|"
    r"urgenc(?:e|es)|"
    r"(?:menace|alerte)\s+(?:sur|pour|de)|"
    r"blocage|"
    r"d[ée]faillance|"
    r"crise"
    r")\b",
    re.IGNORECASE,
)

_RE_ISSUES_EN = re.compile(
    r"\b(?:"
    r"issues?|"
    r"constraints?|"
    r"risks?\s+(?:of|that|for|linked\s+to)|"
    r"tensions?\s+(?:on|between|within)|"
    r"difficulties|"
    r"blockers?|"
    r"urgency|"
    r"pain\s+point|"
    r"challenges?\s+(?:on|with|for)|"
    r"crisis"
    r")\b",
    re.IGNORECASE,
)

def detect_qualified_issues(brief_text: str, lang: str = "fr") -> dict:
    """Retourne {"found": bool, "evidence": list[str]}."""
    brief_text = brief_text or ""
    pattern = _RE_ISSUES_FR if lang == "fr" else _RE_ISSUES_EN
    evidence: list[str] = []

    for m in pattern.finditer(brief_text):
        start = m.start()
        ctx = brief_text[start:start + 60].replace("\n", " ").strip()
        evidence.append(ctx[:50])
        if len(evidence) >= 3:
            break

    return {"found": bool(evidence), "evidence": evidence}


# =============================================================================
# v16.5.76 item 8 — DÉTECTION DES BALISES EXPLICITES EN PROSE LIBRE
# =============================================================================
# Bug observé sur test A/B dossier de conseil (run #4 du 2026-05-15) :
# brief Robin contenait explicitement CONTEXTE: / ENJEU: / RISQUE PRINCIPAL: /
# HORIZON: en majuscules en prose libre, mais briefcheck n'a compté que 2/4
# leviers parce que :
#   - `figures` : 1 seule occurrence € (seuil = 2)
#   - `decision` : pattern `décider\s+(?:de|si|entre|quel)` ne matchait pas
#                  "décider DU futur statutaire"
#
# Solution : compléter les détecteurs avec des patterns "balises explicites"
# qui reconnaissent l'intention de cadrage du brief même sans les chiffres
# ou tournures précises. C'est pour les power-users qui balisent à la main.

_RE_BALISE_ENJEU = re.compile(
    r"(?:^|\n|\.\s+|;\s+)\s*(?:ENJEU|ISSUE|STAKE)S?\s*[:\-—]",
    re.IGNORECASE,
)
_RE_BALISE_RISQUE = re.compile(
    r"(?:^|\n|\.\s+|;\s+)\s*(?:RISQUE(?:S|\s+(?:PRINCIPAL|MAJEUR|CL[ÉE]))?|"
    r"RISK(?:S|\s+(?:MAIN|KEY|MAJOR))?)\s*[:\-—]",
    re.IGNORECASE,
)
_RE_BALISE_HORIZON = re.compile(
    r"(?:^|\n|\.\s+|;\s+)\s*(?:HORIZON|D[ÉE]LAI|DEADLINE|[ÉE]CH[ÉE]ANCE|TIMING)\s*[:\-—]",
    re.IGNORECASE,
)
_RE_BALISE_DECISION = re.compile(
    r"(?:^|\n|\.\s+|;\s+)\s*(?:D[ÉE]CISION|ARBITRAGE|CHOIX|GO\s*/\s*NO[- ]?GO)\s*[:\-—]"
    r"|d[ée]cision\s+(?:[àa]\s+prendre|attendue|requise)"
    r"|d[ée]cider\s+(?:du|de\s+la|des|de\s+l['']\s*)",
    re.IGNORECASE,
)
_RE_BALISE_CONTEXTE = re.compile(
    r"(?:^|\n|\.\s+|;\s+)\s*(?:CONTEXTE|CONTEXT|P[ÉE]RIM[ÈE]TRE|SCOPE)\s*[:\-—]",
    re.IGNORECASE,
)


def detect_explicit_balises(brief_text: str) -> dict:
    """
    Détecte les balises EXPLICITES en prose libre (ENJEU:, RISQUE:, HORIZON:,
    DÉCISION:, CONTEXTE:) que les utilisateurs avancés mettent à la main pour
    structurer leur brief.

    Ces balises BOOSTENT chacun leur levier respectif :
      - ENJEU:    → issues
      - RISQUE:   → issues
      - HORIZON:  → decision (un horizon implique une décision à prendre)
      - DÉCISION: → decision
      - CONTEXTE: → context

    Retourne {"levier_name": list[evidence_snippets]}.
    """
    brief_text = brief_text or ""
    found: dict[str, list[str]] = {
        "context":  [],
        "decision": [],
        "issues":   [],
    }

    if _RE_BALISE_CONTEXTE.search(brief_text):
        m = _RE_BALISE_CONTEXTE.search(brief_text)
        found["context"].append(f"balise: {m.group(0).strip()[:30]}")

    for pattern, levier in [
        (_RE_BALISE_ENJEU,    "issues"),
        (_RE_BALISE_RISQUE,   "issues"),
        (_RE_BALISE_HORIZON,  "decision"),
        (_RE_BALISE_DECISION, "decision"),
    ]:
        for m in pattern.finditer(brief_text):
            snippet = m.group(0).strip()[:30]
            if snippet not in found[levier]:
                found[levier].append(f"balise: {snippet}")
            if len(found[levier]) >= 2:
                break

    return found


def score_brief_levers(brief_text: str,
                       company_profile: dict | None = None,
                       lang: str = "fr") -> int:
    """
    v16.5.76 item 8 — API publique exposant le nombre de leviers détectés
    (0..4). Utile pour les tests de non-régression et l'UI qui veut afficher
    une jauge sans tout recalculer.
    """
    return compute_brief_mode(brief_text, company_profile, lang)["present_count"]


# ── CALCUL DU MODE ──────────────────────────────────────────────────────────

def compute_brief_mode(brief_text: str,
                       company_profile: dict | None = None,
                       lang: str = "fr") -> dict:
    """
    Évalue le mode de briefing en combinant les 4 détecteurs.

    v16.5.76 : intègre les balises explicites en prose libre (ENJEU:, RISQUE:,
    HORIZON:, DÉCISION:, CONTEXTE:) qui boostent les leviers correspondants
    pour les power-users qui balisent à la main.

    Retourne :
    {
        "mode": "GENERIC" | "PARTIAL" | "FRAMED",
        "score_cap": int,
        "leviers": {context, figures, decision, issues: bool},
        "evidence": {levier: list[str]},
        "present_count": int,
        "missing": list[str],
        "banner_markdown": str,
        "suggested_template": str,
    }
    """
    brief_text = brief_text or ""
    lang = lang if lang in ("fr", "en") else "fr"

    ctx = detect_company_context(brief_text, company_profile)
    fig = detect_key_figures(brief_text)
    dec = detect_decision_ask(brief_text, lang)
    iss = detect_qualified_issues(brief_text, lang)

    # v16.5.76 item 8 : balises explicites en prose libre
    balises = detect_explicit_balises(brief_text)

    # Un levier est "found" si soit la détection naturelle, soit la balise explicite, fonctionne
    leviers = {
        "context":  ctx["found"]  or bool(balises["context"]),
        "figures":  fig["found"],  # figures reste sur détection naturelle (pas de balise)
        "decision": dec["found"]  or bool(balises["decision"]),
        "issues":   iss["found"]  or bool(balises["issues"]),
    }
    present = sum(1 for v in leviers.values() if v)

    if present == 0:
        mode = MODE_GENERIC
    elif present >= 4:
        mode = MODE_FRAMED
    else:
        mode = MODE_PARTIAL

    labels = LEVIER_LABELS_FR if lang == "fr" else LEVIER_LABELS_EN
    missing = [labels[k] for k, v in leviers.items() if not v]

    # Evidence enrichie : on combine détection naturelle + balises explicites
    return {
        "mode": mode,
        "score_cap": MODE_SCORE_CAP[mode],
        "leviers": leviers,
        "evidence": {
            "context":  ctx["evidence"]  + balises["context"],
            "figures":  fig["evidence"],
            "decision": dec["evidence"]  + balises["decision"],
            "issues":   iss["evidence"]  + balises["issues"],
        },
        "present_count": present,
        "missing": missing,
        "banner_markdown": _build_mode_banner(mode, present, missing, lang),
        "suggested_template": _brief_template(lang) if mode == MODE_GENERIC else "",
    }


# ── WORDING DES BANDEAUX + TEMPLATE ─────────────────────────────────────────

def _build_mode_banner(mode: str, present: int, missing: list[str], lang: str) -> str:
    """Bandeau markdown injecté en tête du livrable (DOCX + UI)."""
    if mode == MODE_FRAMED:
        return ""

    if lang == "fr":
        if mode == MODE_GENERIC:
            lines = [
                "🔴 **MODE GÉNÉRIQUE — AUCUN CONTEXTE CLIENT FOURNI**",
                "",
                "Le brief ne contient aucun des 4 leviers de qualification attendus "
                "(contexte société, chiffres-clés, décision attendue, enjeu qualifié).",
                "",
                "**Le système a inféré un cas-type fictif pour fournir un livrable "
                "démonstratif. Aucune donnée de ce document ne doit être "
                "utilisée comme analyse réelle.**",
                "",
                "**Pour obtenir un livrable actionnable, complétez le brief avec :**",
                *[f"- {m}" for m in missing],
                "",
                "*Score plafonné mécaniquement à Grade D — voir bloc Confidence ci-dessous.*",
            ]
        else:  # PARTIAL
            lines = [
                f"🟡 **MODE PARTIEL — {present}/4 leviers renseignés**",
                "",
                "Le brief est partiellement qualifié. Le livrable est exploitable "
                "en CoDIR interne mais doit être validé avant toute présentation externe.",
                "",
                "**Complétez le brief pour passer en mode cadré :**",
                *[f"- {m}" for m in missing],
                "",
                "*Score plafonné mécaniquement à Grade B — voir bloc Confidence ci-dessous.*",
            ]
    else:  # EN
        if mode == MODE_GENERIC:
            lines = [
                "🔴 **GENERIC MODE — NO CLIENT CONTEXT PROVIDED**",
                "",
                "The brief contains none of the 4 expected qualification levers "
                "(company context, key figures, decision expected, qualified issue).",
                "",
                "**The system inferred a fictional case to produce a demonstrative "
                "deliverable. No data in this document should be used as actual analysis.**",
                "",
                "**To produce an actionable deliverable, enrich the brief with:**",
                *[f"- {m}" for m in missing],
                "",
                "*Score mechanically capped at Grade D — see Confidence block below.*",
            ]
        else:
            lines = [
                f"🟡 **PARTIAL MODE — {present}/4 levers provided**",
                "",
                "The brief is partially qualified. The deliverable is usable "
                "in internal CoDIR but must be validated before external presentation.",
                "",
                "**Enrich the brief to reach framed mode:**",
                *[f"- {m}" for m in missing],
                "",
                "*Score mechanically capped at Grade B — see Confidence block below.*",
            ]
    return "\n".join(lines)


def _brief_template(lang: str) -> str:
    """Template de brief minimal proposé à l'utilisateur en mode GENERIC."""
    if lang == "fr":
        return (
            "## Template de brief minimal\n\n"
            "**Société / contexte** : [Nom, SIREN si connu, secteur, forme juridique, effectif approximatif]\n\n"
            "**Chiffres-clés** : [CA, EBITDA ou marge, trésorerie / cash, au moins 2 métriques datées]\n\n"
            "**Décision attendue** : [Go/No-Go sur X ?  |  Arbitrer entre A et B ?  |  Valider budget de Y ?]\n\n"
            "**Enjeu principal** : [Quel risque, contrainte ou tension justifie cette analyse ?]\n\n"
            "**Horizon** : [90 jours / N+1 / pluriannuel / 5 ans]\n\n"
            "*Un brief qui renseigne ces 4 blocs débloque un livrable CoDIR Grade A/B.*"
        )
    return (
        "## Minimal brief template\n\n"
        "**Company / context**: [Name, registry ID if known, sector, legal form, approx. headcount]\n\n"
        "**Key figures**: [Revenue, EBITDA or margin, cash, at least 2 dated metrics]\n\n"
        "**Decision expected**: [Go/No-Go on X?  |  Trade-off A vs B?  |  Approve Y budget?]\n\n"
        "**Main issue**: [What risk, constraint or tension drives this analysis?]\n\n"
        "**Horizon**: [90 days / FY+1 / multi-year / 5 years]\n\n"
        "*A brief covering these 4 blocks unlocks a Grade A/B CoDIR deliverable.*"
    )


# =============================================================================
# FONCTION PRINCIPALE
# =============================================================================

def run_briefcheck(brief_text: str,
                   attachments: list[Path] | None = None,
                   lang: str = "fr",
                   company_profile: dict | None = None,
                   subsidiaries: list[dict] | None = None,
                   default_horizon: str = "FY_N1",
                   source_mode: str = "OPEN",
                   financial_block_present: bool = False) -> dict:
    """
    Exécute les 4 vérifications de pré-orchestration.

    v1.0 : doc_check + horizon + scope_expansion
    v1.1 : + brief_mode (détection 4 leviers, plafond de score)
    """
    attachments = attachments or []
    lang = lang if lang in ("fr", "en") else "fr"
    brief_text = brief_text or ""

    doc_check = briefcheck_doc_completeness(brief_text, attachments, lang,
                                            source_mode=source_mode,
                                            financial_block_present=financial_block_present)
    horizon = resolve_horizon(brief_text, lang, default=default_horizon)
    should_expand = should_expand_to_subsidiaries(company_profile, subsidiaries)
    brief_mode = compute_brief_mode(brief_text, company_profile, lang)

    warnings = []
    if doc_check["severity"] == "WARN_BANNER":
        warnings.append("MISSING_FINANCIAL_DOCS")
    if should_expand and not subsidiaries:
        warnings.append("HOLDING_DETECTED_NO_SUBSIDIARIES_DATA")
    if brief_mode["mode"] == MODE_GENERIC:
        warnings.append("GENERIC_BRIEF_MODE")
    elif brief_mode["mode"] == MODE_PARTIAL:
        warnings.append("PARTIAL_BRIEF_MODE")

    # Bannière concaténée : mode en premier (plus critique), puis docs manquants
    banner_parts = []
    if brief_mode["banner_markdown"]:
        banner_parts.append(brief_mode["banner_markdown"])
    if doc_check["banner_markdown"]:
        banner_parts.append(doc_check["banner_markdown"])
    combined_banner = "\n\n---\n\n".join(banner_parts)

    return {
        "doc_check": doc_check,
        "horizon": horizon,
        "scope_expansion": {
            "should_expand": should_expand,
            "mother_ape": (company_profile or {}).get("ape_code"),
            "mother_ca_eur": (company_profile or {}).get("ca_eur"),
            "subsidiaries_count": len(subsidiaries) if subsidiaries else 0,
        },
        "brief_mode": brief_mode,
        "banner_markdown": combined_banner,
        "warnings": warnings,
        "lang": lang,
    }


__all__ = [
    "run_briefcheck",
    "detect_doc_references",
    "resolve_horizon",
    "should_expand_to_subsidiaries",
    "briefcheck_doc_completeness",
    "has_financial_attachment",
    # v1.1 — mode detection
    "compute_brief_mode",
    "detect_company_context",
    "detect_key_figures",
    "detect_decision_ask",
    "detect_qualified_issues",
    # constantes exportées pour tests et extensions
    "DOC_PATTERNS_FR", "DOC_PATTERNS_EN",
    "HORIZON_PATTERNS", "HORIZON_PATTERNS_EN",
    "HOLDING_APE_PREFIXES", "FINANCIAL_FILE_EXTENSIONS", "FINANCIAL_FILE_KEYWORDS",
    "MODE_GENERIC", "MODE_PARTIAL", "MODE_FRAMED", "MODE_SCORE_CAP",
    "LEVIER_LABELS_FR", "LEVIER_LABELS_EN",
]
