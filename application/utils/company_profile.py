"""
CoDIR IA — utils/company_profile.py — v16.5.67
==================================================================
Routeur léger de profil d'entreprise → activation/désactivation
conditionnelle des rôles du CoDIR.

Motivation
----------
Sur le cas dossier de conseil (SASU unipersonnelle de DAF de transition,
CA 173 k€, effectif 0), le pipeline a produit :
- un plan Marketing "webinars + RP + CRM 8 k€" totalement hors-sol,
- un rôle Supply Chain convoqué pour [À DÉFINIR] (pas de flux matières),
- un challenge commercial raisonnant en "perte de clients" alors que
  le CA dépend du nombre de jours facturés par un solo.

La cause racine : le pipeline traite toutes les sociétés comme des
PME industrielles. Il manque une couche amont qui détecte le PROFIL
et reconfigure ou désactive les rôles en conséquence.

Philosophie
-----------
LÉGER. Pas d'usine à gaz. On reste sur :
- une classification simple à 4 profils (SOLO / TPE / PME / ETI_PLUS),
- un drapeau "service_only" vs "physical_ops",
- une matrice rôle × profil qui dit "active / skip / downgrade".

Le profil est détecté à partir de 3 sources (dans l'ordre de priorité) :
1. Données Pappers (effectif, forme juridique, code APE, CA)
2. Brief utilisateur (champ "Taille", "Secteur", "Géographie")
3. Heuristiques de fallback (si aucune source — profil inconnu → PME)

Aucune consommation de LLM pour la détection — c'est une fonction
pure, rapide, déterministe, testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# ── Profils ─────────────────────────────────────────────────────────────────
PROFILE_SOLO       = "solo"        # SASU unipersonnelle, EURL, micro, effectif 0-1
PROFILE_TPE        = "tpe"         # 2-9 salariés, CA < 2 M€
PROFILE_PME        = "pme"         # 10-249 salariés, CA 2-50 M€
PROFILE_ETI_PLUS   = "eti_plus"    # 250+ salariés ou CA > 50 M€

# Nature opérationnelle
NATURE_SERVICES    = "services"     # conseil, IT, avocat, DAF de transition
NATURE_PRODUCT     = "product"      # industrie, négoce, logistique, retail
NATURE_MIXED       = "mixed"        # inconnu ou hybride


# ── Codes APE services-only connus ──────────────────────────────────────────
# Section M (Activités spécialisées, scientifiques et techniques) et
# section J (Information et communication) sont essentiellement des
# services intellectuels sans flux physiques significatifs.
_APE_SERVICES_ONLY_PREFIXES = (
    "62",   # Programmation, conseil informatique
    "63",   # Services d'information
    "69",   # Activités juridiques et comptables
    "70",   # Activités des sièges sociaux ; conseil de gestion
    "71",   # Architecture, ingénierie ; contrôle et analyses techniques
    "72",   # Recherche-développement
    "73",   # Publicité et études de marché
    "74",   # Autres activités spécialisées, scientifiques et techniques
    "85",   # Enseignement
    "86",   # Activités pour la santé humaine (cabinet médical)
    "88",   # Action sociale sans hébergement
)

# Codes APE avec flux physiques prépondérants (Supply Chain matérielle)
_APE_PHYSICAL_OPS_PREFIXES = (
    "01", "02", "03",  # Agriculture / sylviculture / pêche
    "05", "06", "07", "08", "09",  # Industries extractives
    "10", "11", "12", "13", "14", "15", "16", "17", "18", "19",
    "20", "21", "22", "23", "24", "25", "26", "27", "28", "29",
    "30", "31", "32", "33",  # Industries manufacturières
    "41", "42", "43",  # Construction
    "45", "46", "47",  # Commerce / réparation auto / gros / détail
    "49", "50", "51", "52", "53",  # Transports et entreposage
    "55", "56",  # Hébergement / restauration
)


# ── Formes juridiques unipersonnelles ───────────────────────────────────────
_UNIPERSONNELLES = {
    "sasu", "eurl", "ei", "entreprise individuelle",
    "micro-entreprise", "micro entreprise", "auto-entrepreneur",
    "eirl",
}


@dataclass
class CompanyProfile:
    """Profil synthétique de l'entité analysée."""
    size:       str = PROFILE_PME           # solo | tpe | pme | eti_plus
    nature:     str = NATURE_MIXED          # services | product | mixed
    is_solo:    bool = False                # SASU/EURL unipersonnelle, effectif 0-1
    is_services: bool = False               # pas de flux physiques significatifs
    headcount:  int | None = None
    ca_eur:     float | None = None
    ape_code:   str = ""
    legal_form: str = ""
    confidence: str = "low"                 # low | medium | high
    source:     str = "default"             # pappers | brief | heuristic | default
    notes:      list[str] = None            # type: ignore[assignment]
    # ── Champs internationaux (Since v16.5.72) ─────────────────────────────
    # Patch v16.5.72 (audit ChatGPT round 14 sur dossier anglophone coté) — Le profil société
    # affichait "SIREN: 03458224" pour dossier anglophone coté plc alors que c'est un UK
    # Company Number, pas un SIREN français. Le profil ne distinguait pas non
    # plus le pays ni le LEI ni le registre source.
    country:           str | None = None      # "FR" | "UK" | "US" | "DE" | etc.
    company_number:    str | None = None      # Companies House (UK), CIK (SEC), Handelsregister (DE), etc.
    company_number_kind: str = ""             # "siren" | "ch_number" | "cik" | "lei" | etc.
    registry:          str | None = None      # "Pappers" | "Companies House" | "SEC EDGAR" | "GLEIF" | etc.
    lei:               str | None = None      # Legal Entity Identifier (GLEIF)
    company_name_official: str | None = None  # nom complet officiel (dossier anglophone coté Group plc)
    sector_label:      str = ""               # libellé secteur en clair (Luxury / Fashion / Retail)
    registry_quarantined: bool = False        # M6-A2.1 — candidat registre rejeté (mismatch entité)
    registry_rejected_name: str = ""          # M6-A2.1 — nom registre rejeté (pour message/diag)
    # v62.13.9.4.15 — STATUT JURIDIQUE EXPLICITE au registre. ACTIVE | CEASED
    # | UNKNOWN. Jamais déduit d'un numéro ou d'une forme juridique : seuls
    # les champs de statut de la fiche (entreprise_cessee, statut_rcs,
    # date_cessation, date_radiation_rcs) le fixent. UNKNOWN n'autorise
    # aucune neutralisation de radiation et n'en fabrique aucune.
    registry_status: str = "UNKNOWN"
    registry_status_detail: str = ""

    def __post_init__(self):
        if self.notes is None:
            self.notes = []

    def summary_line(self) -> str:
        bits = [
            f"size={self.size}",
            f"nature={self.nature}",
            f"solo={self.is_solo}",
            f"services={self.is_services}",
            f"conf={self.confidence}",
            f"src={self.source}",
        ]
        if self.headcount is not None:
            bits.append(f"hc={self.headcount}")
        if self.ca_eur is not None:
            bits.append(f"ca={int(self.ca_eur)}")
        if self.ape_code:
            bits.append(f"ape={self.ape_code}")
        # Patch v16.5.72 — Champs internationaux dans summary
        if self.country:
            bits.append(f"country={self.country}")
        if self.company_number:
            kind_label = self.company_number_kind or "id"
            bits.append(f"{kind_label}={self.company_number}")
        if self.lei:
            bits.append(f"lei={self.lei[:12]}...")
        if self.registry:
            bits.append(f"registry={self.registry}")
        return "profile | " + " ".join(bits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "size":        self.size,
            "nature":      self.nature,
            "is_solo":     self.is_solo,
            "is_services": self.is_services,
            "headcount":   self.headcount,
            "ca_eur":      self.ca_eur,
            "ape_code":    self.ape_code,
            "legal_form":  self.legal_form,
            "confidence":  self.confidence,
            "source":      self.source,
            "notes":       list(self.notes),
            # Patch v16.5.72 — Champs internationaux
            "country":               self.country,
            "company_number":        self.company_number,
            "company_number_kind":   self.company_number_kind,
            "registry":              self.registry,
            "lei":                   self.lei,
            "company_name_official": self.company_name_official,
            "sector_label":          self.sector_label,
            # M6-A2.1.1 — visibilité quarantine registre dans les sorties structurées
            "registry_quarantined":   self.registry_quarantined,
            # v62.13.9.4.15.1 — le statut explicite manquait ici : le run réel
            # du 02/09/2026 19:53 portait registry_status=None dans le dossier,
            # et l'autorité du registre en maintenance finale (qui lit le
            # profil sérialisé) était inerte. La fiche transmise aux agents le
            # portait, le filet aval ne le voyait pas.
            "registry_status":        self.registry_status,
            "registry_status_detail": self.registry_status_detail,
            "registry_rejected_name": self.registry_rejected_name,
            "registry_candidate_status": "rejected" if self.registry_quarantined else "accepted",
        }

    def to_user_facing_label(self, lang: str = "fr") -> str:
        """
        Patch v16.5.72 — Rendu lisible utilisateur du profil société.

        Cas dossier anglophone coté plc :
            "dossier anglophone coté Group plc · UK Company Number 03458224 ·
             Registre: Companies House · LEI: 213800PE1KEFCNFR1R50 ·
             Forme: public limited company · Secteur: Luxury / Fashion"

        Cas dossier réseau de soins SAS :
            "dossier réseau de soins Groupe · SIREN 310612387 · Registre: Pappers · APE: 4774Z ·
             Forme: SAS · Secteur: Retail médical"
        """
        parts = []
        if self.company_name_official:
            parts.append(self.company_name_official)
        if self.country and self.country != "FR":
            id_label = "Company Number" if self.country == "UK" else "ID"
            if self.company_number_kind == "ch_number":
                id_label = "UK Company Number"
            elif self.company_number_kind == "cik":
                id_label = "SEC CIK"
            if self.company_number:
                parts.append(f"{id_label} {self.company_number}")
        elif self.company_number:
            id_label = "SIREN" if self.company_number_kind == "siren" else "ID"
            parts.append(f"{id_label} {self.company_number}")
        if self.registry:
            parts.append(f"Registre: {self.registry}" if lang == "fr" else f"Registry: {self.registry}")
        if self.lei:
            parts.append(f"LEI: {self.lei}")
        if self.legal_form:
            # M6-A2.x — filet : ne jamais afficher une forme juridique française
            # (sas/sarl/…) sur une entité dont le pays n'est pas FR (résidu Pappers).
            _lf_low = self.legal_form.lower()
            _fr_form = any(_f in _lf_low for _f in
                           ("sasu", "sas", "sarl", "eurl", "selarl", "sci", "scp",
                            "société par actions", "société à responsabilité"))
            if not (self.country and self.country != "FR" and _fr_form):
                parts.append(f"Forme: {self.legal_form}" if lang == "fr" else f"Form: {self.legal_form}")
        if self.sector_label:
            parts.append(f"Secteur: {self.sector_label}" if lang == "fr" else f"Sector: {self.sector_label}")
        return " · ".join(parts) if parts else ""


# ── Détection depuis Pappers ────────────────────────────────────────────────
def _headcount_from_pappers(effectif: Any) -> int | None:
    """
    Pappers renvoie effectif soit en int soit en tranche "0-9" / "10-19".
    On extrait une borne basse comme approximation prudente.
    """
    if effectif is None:
        return None
    if isinstance(effectif, int):
        return effectif
    s = str(effectif).strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    # tranches type "0-9", "10-19", "50-99", "100-199"
    m = re.match(r"(\d+)\s*-\s*(\d+)", s)
    if m:
        return int(m.group(1))
    m = re.match(r"(\d+)", s)
    if m:
        return int(m.group(1))
    return None


def _size_from_headcount_and_ca(hc: int | None, ca: float | None) -> str:
    """Classification INSEE simplifiée."""
    # Priorité à l'effectif (plus fiable)
    if hc is not None:
        if hc <= 1:
            return PROFILE_SOLO
        if hc < 10:
            return PROFILE_TPE
        if hc < 250:
            return PROFILE_PME
        return PROFILE_ETI_PLUS
    # Fallback CA
    if ca is not None:
        if ca < 200_000:
            return PROFILE_SOLO
        if ca < 2_000_000:
            return PROFILE_TPE
        if ca < 50_000_000:
            return PROFILE_PME
        return PROFILE_ETI_PLUS
    return PROFILE_PME  # défaut conservateur


def _nature_from_ape(ape: str) -> str:
    if not ape:
        return NATURE_MIXED
    # normaliser "70.22Z" → "70"
    code = ape.strip().replace(".", "").replace("-", "")[:2]
    if code in (p[:2] for p in _APE_SERVICES_ONLY_PREFIXES):
        return NATURE_SERVICES
    if code in (p[:2] for p in _APE_PHYSICAL_OPS_PREFIXES):
        return NATURE_PRODUCT
    return NATURE_MIXED


def registry_status_from_fiche(fiche: dict | None) -> tuple[str, str]:
    """v62.13.9.4.15 — (statut, détail) lus dans les champs EXPLICITES d'une
    fiche Pappers. Renvoie ("UNKNOWN", "") si aucun champ de statut n'est
    présent : l'absence d'information n'est pas une information."""
    if not isinstance(fiche, dict) or not fiche:
        return "UNKNOWN", ""
    cessee = fiche.get("entreprise_cessee")
    statut_rcs = str(fiche.get("statut_rcs") or "").strip()
    statut_rne = str(fiche.get("statut_rne") or "").strip()
    d_cess = str(fiche.get("date_cessation") or "").strip()
    d_rad = str(fiche.get("date_radiation_rcs") or "").strip()
    low = (statut_rcs + " " + statut_rne).lower()
    if cessee is True or "radi" in low or d_cess or d_rad:
        bits = []
        if statut_rcs:
            bits.append(f"RCS : {statut_rcs}")
        if d_rad:
            bits.append(f"radiation RCS le {d_rad}")
        if d_cess:
            bits.append(f"cessation le {d_cess}")
        if cessee is True and not bits:
            bits.append("entreprise cessée (registre)")
        return "CEASED", " · ".join(bits)
    if cessee is False or "inscrit" in low or "actif" in low or "active" in low:
        bits = []
        if statut_rcs:
            bits.append(f"RCS : {statut_rcs}")
        if statut_rne:
            bits.append(f"RNE : {statut_rne}")
        if cessee is False and not bits:
            bits.append("entreprise en activité (registre)")
        return "ACTIVE", " · ".join(bits)
    return "UNKNOWN", ""


def detect_profile_from_pappers(
    pappers_fiche: dict | None,
    pappers_comptes: dict | None = None,
) -> CompanyProfile | None:
    """
    Construit un CompanyProfile à partir des données Pappers.
    Retourne None si Pappers ne contient rien d'exploitable.
    """
    if not pappers_fiche or not isinstance(pappers_fiche, dict):
        return None
    if pappers_fiche.get("_not_found") or pappers_fiche.get("_error"):
        return None

    hc = _headcount_from_pappers(pappers_fiche.get("effectif"))
    legal = str(pappers_fiche.get("forme_juridique") or "").strip().lower()
    ape = str(pappers_fiche.get("code_naf") or pappers_fiche.get("code_ape") or "").strip()

    # CA : on prend le plus récent dans "finances" si disponible
    ca = None
    finances = pappers_fiche.get("finances") or []
    if isinstance(finances, list) and finances:
        latest = finances[0] if isinstance(finances[0], dict) else None
        if latest:
            raw_ca = latest.get("chiffre_affaires") or latest.get("ca")
            try:
                ca = float(raw_ca) if raw_ca is not None else None
            except (TypeError, ValueError):
                ca = None
    # Si on a Pappers comptes séparément, on tente d'en extraire un CA
    if ca is None and pappers_comptes and isinstance(pappers_comptes, dict):
        raw = pappers_comptes.get("chiffre_affaires") or pappers_comptes.get("ca")
        try:
            ca = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            ca = None

    size = _size_from_headcount_and_ca(hc, ca)
    nature = _nature_from_ape(ape)

    is_solo = (
        size == PROFILE_SOLO
        and (legal in _UNIPERSONNELLES or hc is not None and hc <= 1)
    )
    is_services = (nature == NATURE_SERVICES)

    notes: list[str] = []
    conf = "high"
    if hc is None and ca is None:
        conf = "low"
        notes.append("Ni effectif ni CA dans Pappers — estimation prudente.")
    elif hc is None or ca is None:
        conf = "medium"

    _rs, _rsd = registry_status_from_fiche(pappers_fiche)
    return CompanyProfile(
        size=size,
        nature=nature,
        is_solo=is_solo,
        is_services=is_services,
        headcount=hc,
        ca_eur=ca,
        ape_code=ape,
        legal_form=legal,
        confidence=conf,
        source="pappers",
        notes=notes,
        registry_status=_rs,
        registry_status_detail=_rsd,
    )


# ── Détection depuis le brief (fallback) ────────────────────────────────────
_BRIEF_SIZE_PATTERNS = [
    (re.compile(r"\beffectif[s]?\s*[:=]\s*(\d+)", re.I), "headcount"),
    (re.compile(r"\b(\d+)\s*salari[ée]s?\b", re.I), "headcount"),
    (re.compile(r"\bCA\s*[:=]?\s*([\d\s.,]+)\s*(k\s*€|m\s*€|€|keur|meur|md\s*[€£$]?|mds?|mrd|bn|billions?|milliards?)?", re.I), "ca"),
    (re.compile(r"\btaille\s*[:=]\s*([^\n]+)", re.I), "size_raw"),
]

_BRIEF_SECTOR_SERVICES_KW = [
    # B.1.3.20 (P1-E, runs dossier industriel + dossier agroalimentaire) — « conseil » nu matchait
    # l'ORGANE de gouvernance (« Messages sensibles : Conseil, Actionnaire »
    # du gabarit) et, services-first, écrasait « Fabrication de machines… »
    # et « pâtisserie industrielle » → supply SKIPPED. Désormais : « conseil »
    # ne compte que comme ACTIVITÉ (conseil en/aux, cabinet/société/activité
    # de conseil), jamais comme organe.
    "conseil en", "conseil aux", "cabinet de conseil", "société de conseil",
    "societe de conseil", "activité de conseil", "activite de conseil",
    "consulting", "daf de transition", "management de transition",
    "cabinet", "avocat", "expert-comptable", "expert comptable",
    "it", "software", "saas", "éditeur de logiciel", "editeur de logiciel",
    "coaching", "formation", "audit", "fintech", "insurtech",
]

_BRIEF_SECTOR_PRODUCT_KW = [
    "industrie", "industriel", "industrielle", "manufacturier", "usine",
    "usines", "chaîne de production", "chaine de production", "supply chain",
    "logistique", "entrepôt", "entrepot",
    "retail", "distribution", "négoce", "negoce", "grossiste",
    "e-commerce", "vente à distance", "vente en ligne",
    "transport", "construction", "btp",
    # B.1.3.20 (P1-E, runs dossier industriel + dossier agroalimentaire) — le secteur DÉCLARÉ
    # « Fabrication de machines agricoles et forestières » ne donnait que
    # 'mixed' : « fabrication »/« machines »/« agro » manquaient au lexique.
    "fabrication", "machines", "équipements", "equipements",
    "agroalimentaire", "agro-alimentaire", "agricole", "agricoles",
    "biscuiterie", "chocolaterie", "manufacture", "production de",
    "sites industriels", "site industriel",
]


def _kw_hit(kw: str, txt: str) -> bool:
    """Match d'un mot-clé secteur en FRONTIÈRE DE MOT. Retex ChatGPT M.5.2 :
    « it » en sous-chaîne matchait « british », « profitability »… → faux
    positif nature=services. On borne par des non-(mot|tiret)."""
    if not kw or not txt:
        return False
    return re.search(r"(?<![\w-])" + re.escape(kw) + r"(?![\w-])", txt) is not None


def detect_profile_from_brief(brief: str) -> CompanyProfile | None:
    """
    Fallback : extrait un profil du brief utilisateur quand Pappers
    n'est pas disponible ou n'a rien trouvé.
    """
    if not brief or not brief.strip():
        return None
    txt = brief.lower()

    # Headcount / CA
    hc: int | None = None
    ca: float | None = None
    size_raw = ""
    for pattern, kind in _BRIEF_SIZE_PATTERNS:
        m = pattern.search(brief)
        if not m:
            continue
        if kind == "headcount" and hc is None:
            try:
                hc = int(m.group(1))
            except (TypeError, ValueError):
                pass
        elif kind == "ca" and ca is None:
            try:
                num_str = re.sub(r"[^\d.,]", "", m.group(1)).replace(",", ".")
                num = float(num_str) if num_str else None
                unit = (m.group(2) or "").lower().replace(" ", "")
                if num is not None:
                    # P0-2 (M.5.2) — milliards d'ABORD : md/mrd/bn/billion/milliard
                    # contiennent un « m » et seraient sinon lus comme des millions
                    # (bug dossier anglophone coté : « 1,03 Md£ » lu 1,03 € → bascule SOLO).
                    if any(t in unit for t in ("md", "mrd", "bn", "billion", "milliard")):
                        num *= 1_000_000_000
                    elif "k" in unit:
                        num *= 1_000
                    elif "m" in unit:
                        num *= 1_000_000
                    ca = num
            except (TypeError, ValueError):
                pass
        elif kind == "size_raw" and not size_raw:
            size_raw = m.group(1).strip().lower()

    # Si "Taille : 200000" dans le brief (observé sur le cas dossier de conseil)
    # on tente de l'interpréter comme un CA en euros.
    if ca is None and size_raw:
        m = re.fullmatch(r"[\d\s]+", size_raw)
        if m:
            try:
                ca = float(re.sub(r"\s", "", size_raw))
            except (TypeError, ValueError):
                pass

    size = _size_from_headcount_and_ca(hc, ca)

    # Nature — B.1.3.20 (P1-E) : fin de la préséance services-first aveugle.
    # Les deux familles sont évaluées ; en cas de double hit, le champ
    # DÉCLARÉ « Secteur : » tranche (déclaration explicite de l'utilisateur),
    # à défaut le produit l'emporte quand des flux physiques sont décrits.
    nature = NATURE_MIXED
    _svc_hit = any(_kw_hit(kw, txt) for kw in _BRIEF_SECTOR_SERVICES_KW)
    _prd_hit = any(_kw_hit(kw, txt) for kw in _BRIEF_SECTOR_PRODUCT_KW)
    if _svc_hit and _prd_hit:
        _sect_m = re.search(r"^\s*Secteur\s*:\s*(.+)$", brief,
                            re.IGNORECASE | re.MULTILINE)
        _sect_txt = (_sect_m.group(1) if _sect_m else "").lower()
        if _sect_txt and any(_kw_hit(kw, _sect_txt)
                             for kw in _BRIEF_SECTOR_PRODUCT_KW):
            nature = NATURE_PRODUCT
        elif _sect_txt and any(_kw_hit(kw, _sect_txt)
                               for kw in _BRIEF_SECTOR_SERVICES_KW):
            nature = NATURE_SERVICES
        else:
            nature = NATURE_PRODUCT
    elif _svc_hit:
        nature = NATURE_SERVICES
    elif _prd_hit:
        nature = NATURE_PRODUCT

    # Unipersonnel ?
    legal = ""
    for fj in _UNIPERSONNELLES:
        if re.search(rf"\b{re.escape(fj)}\b", txt):
            legal = fj
            break
    is_solo = (size == PROFILE_SOLO) or (legal in _UNIPERSONNELLES)
    is_services = (nature == NATURE_SERVICES)

    # Confiance faible par défaut sur brief seul
    conf = "medium" if (hc is not None or ca is not None or legal) else "low"
    return CompanyProfile(
        size=size,
        nature=nature,
        is_solo=is_solo,
        is_services=is_services,
        headcount=hc,
        ca_eur=ca,
        ape_code="",
        legal_form=legal,
        confidence=conf,
        source="brief",
        notes=[],
    )


# ── P0-2 (M.5.2) — Garde de cohérence TAILLE + réconciliation d'entité ───────
# Empêche une bascule solo/tpe erronée quand le brief porte des signaux clairs de
# GRAND GROUPE (CA en milliards, effectif en milliers, société cotée / plc).
# Cas dossier anglophone coté : « 1,03 Md£ » mal mis à l'échelle → ca_eur=1.03 → SOLO → playbook
# consultant injecté. Le garde écrase cette classification et signale le décalage
# d'entité (filiale Ltd vs groupe coté nommé au brief).
_LARGE_REVENUE_RE = re.compile(r"\b\d[\d\s.,]*\s*(?:md|mds|mrd|bn|billion|milliard)", re.I)
_LARGE_HEADCOUNT_RE = re.compile(
    r"\b\d{1,3}[\s.\u202f]?\d{3,}\s*(?:salari|employ|collaborateur|effectif|headcount|employee)", re.I)
_LISTED_RE = re.compile(
    r"\b(?:cot[ée]e?s?|listed|plc|euronext|lse|ftse|nyse|nasdaq|bourse|"
    r"stock\s+exchange|cac\s*40|groupe\s+cot)\b", re.I)

# v62.8 — signaux déclaratifs de groupe industriel. Ils priment sur un profil
# registre contradictoire (homonyme, holding immobilière, effectif standalone).
_GROUP_DECL_RE = re.compile(
    r"\b(?:groupe|group|filiales?\s+op[ée]rationnelles?|p[ée]rim[èe]tre\s*:\s*groupe|"
    r"consolid[ée]|sites?\s+(?:de\s+)?production|actionnaires?\s+et\s+(?:le\s+)?codir)\b",
    re.I,
)
_INDUSTRIAL_DECL_RE = re.compile(
    r"\b(?:industrie|industriel|industrielle|agroalimentaire|agro-alimentaire|"
    r"biscuiterie|fabrication|production|usine|sites?\s+industriels?|mati[èe]res?\s+premi[èe]res?|"
    r"supply\s+chain|logistique|stocks?|gms|emballages?)\b",
    re.I,
)


def _large_group_signals(brief: str) -> list[str]:
    sig: list[str] = []
    if not brief:
        return sig
    if _LARGE_REVENUE_RE.search(brief):
        sig.append("CA en milliards")
    if _LARGE_HEADCOUNT_RE.search(brief):
        sig.append("effectif en milliers")
    if _LISTED_RE.search(brief):
        sig.append("société cotée / plc / groupe")
    return sig


def enforce_size_sanity(profile: "CompanyProfile | None", brief: str = "") -> "CompanyProfile | None":
    """P0-2 — garde de cohérence taille. Idempotent (dédup des notes)."""
    if profile is None:
        return profile
    signals = _large_group_signals(brief)
    _declared_group = bool(_GROUP_DECL_RE.search(brief or ""))
    _declared_industrial = bool(_INDUSTRIAL_DECL_RE.search(brief or ""))
    # v62.10 — les signaux de cotation / plc / milliard priment sur toute
    # classification héritée d'un micro-cycle sectoriel. Un groupe coté ne peut
    # jamais rester « pme », même si des mots comme stock/production apparaissent
    # dans les pièces jointes.
    if signals:
        old = profile.size
        profile.is_solo = False
        profile.size = PROFILE_ETI_PLUS
        if _declared_industrial:
            profile.is_services = False
            profile.nature = NATURE_PRODUCT
        note = ("Garde-fou taille P0-2 / v62.10 : signaux grand groupe (" + ", ".join(signals)
                + f") → classification {old} écrasée en eti_plus ; is_solo=False.")
        try:
            if not any("Garde-fou taille P0-2" in n for n in profile.notes):
                profile.notes.append(note)
        except Exception:
            pass
    elif (_declared_group and _declared_industrial):
        # Groupe industriel non coté : plancher PME, jamais solo/TPE.
        old = profile.size
        profile.is_solo = False
        profile.is_services = False
        profile.nature = NATURE_PRODUCT
        if profile.size in (PROFILE_SOLO, PROFILE_TPE) or not profile.size:
            profile.size = PROFILE_PME
        note = ("Garde-fou v62.10 : brief explicite groupe industriel → "
                f"classification {old} corrigée en {profile.size}, nature=product, is_solo=False.")
        try:
            if not any("brief explicite groupe industriel" in n for n in profile.notes):
                profile.notes.append(note)
        except Exception:
            pass
    # Réconciliation : entité résolue = filiale (Ltd) mais brief nomme un groupe coté (plc).
    name = (getattr(profile, "company_name_official", "") or "").lower()
    blow = (brief or "").lower()
    if (name and re.search(r"\b(?:ltd|limited)\b", name)
            and re.search(r"\b(?:plc|group|groupe\s+cot|listed|cot[ée]e?s?)\b", blow)):
        recon = ("Réconciliation entité P0-2 : l'entité résolue est une filiale (Ltd) "
                 "alors que le brief nomme un groupe coté (plc) — périmètre à confirmer "
                 "(groupe consolidé vs entité juridique).")
        try:
            if not any("Réconciliation entité P0-2" in n for n in profile.notes):
                profile.notes.append(recon)
        except Exception:
            pass
    return profile


def _nature_from_ape(ape: str) -> str | None:
    """B.1.3.20 (P1-E) — nature depuis la division NAF (2 premiers chiffres).
    Manufacture / commerce / transport / construction / agro → product ;
    IT / professions / finance / conseil → services ; sinon None (on ne
    force rien : holdings 64.20, activités mixtes…)."""
    d = re.sub(r"\D", "", str(ape or ""))[:2]
    if not d:
        return None
    if d in {"01", "02", "03", "05", "06", "07", "08", "09"}:
        return NATURE_PRODUCT
    if "10" <= d <= "33" or d in {"35", "36", "37", "38", "39"}:
        return NATURE_PRODUCT
    if d in {"41", "42", "43", "45", "46", "47", "49", "50", "51", "52", "53"}:
        return NATURE_PRODUCT
    if d in {"58", "62", "63", "64", "65", "66", "69", "70", "71", "73",
             "74", "78", "80", "81", "82"}:
        return NATURE_SERVICES
    return None


def _detect_profile_core(
    pappers_fiche: dict | None = None,
    pappers_comptes: dict | None = None,
    brief: str = "",
) -> CompanyProfile:
    """
    Point d'entrée unique. Combine les sources avec priorité Pappers > brief.
    Retourne toujours un CompanyProfile (jamais None) — profil par défaut
    PME/mixed si aucune source exploitable.
    """
    # B.1.3.20 (P1-E, run dossier agroalimentaire) — l'APE de la fiche Pappers n'était
    # jamais propagé au profil quand le brief gagnait (ape_code vide malgré
    # SIREN_DIRECT résolu). Le gagnant est désormais estampillé APE + nature
    # NAF quand la fiche en porte un et que le brief n'a pas tranché.
    def _stamp_ape(prof):
        if prof is None or not isinstance(pappers_fiche, dict):
            return prof
        _ape = str(pappers_fiche.get("code_naf")
                   or pappers_fiche.get("ape")
                   or pappers_fiche.get("code_ape") or "").strip()
        if _ape:
            if not getattr(prof, "ape_code", ""):
                prof.ape_code = _ape
            if getattr(prof, "nature", NATURE_MIXED) == NATURE_MIXED:
                _nat = _nature_from_ape(_ape)
                if _nat:
                    prof.nature = _nat
                    prof.notes.append(f"Nature déduite de l'APE Pappers {_ape}.")
        return prof

    p = detect_profile_from_pappers(pappers_fiche, pappers_comptes)
    if p and p.confidence in ("high", "medium"):
        return _stamp_ape(p)
    b = detect_profile_from_brief(brief)
    if b:
        # Si Pappers low-conf existe, on complète avec le brief
        if p and not p.size and b.size:
            p.size = b.size
            p.notes.append("Taille complétée depuis brief.")
            return _stamp_ape(p)
        return _stamp_ape(b)
    if p:
        return _stamp_ape(p)
    return CompanyProfile(
        size=PROFILE_PME,
        nature=NATURE_MIXED,
        confidence="low",
        source="default",
        notes=["Aucune source exploitable — profil PME par défaut."],
    )


def detect_profile(
    pappers_fiche: dict | None = None,
    pappers_comptes: dict | None = None,
    brief: str = "",
) -> CompanyProfile:
    """Point d'entrée unique (wrapper P0-2). Calcule le profil puis applique le
    garde de cohérence taille/réconciliation avant de le renvoyer."""
    profile = _detect_profile_core(pappers_fiche, pappers_comptes, brief)
    return enforce_size_sanity(profile, brief)


# ── Matrice rôle × profil ───────────────────────────────────────────────────
# Pour chaque rôle, on définit :
#   - active : bool (le rôle est appelé)
#   - note   : str ("" ou raison de désactivation/adaptation)
#   - style_hint : str ("" ou instruction ajoutée au prompt)
#
# Règle d'or : par défaut tout est actif. On ne désactive que quand la
# valeur ajoutée du rôle est manifestement nulle pour le profil.

@dataclass
class RoleActivation:
    active: bool = True
    note: str = ""
    style_hint: str = ""


def role_activation(
    profile: CompanyProfile,
    role: str,
    skip_context: dict[str, Any] | None = None,
) -> RoleActivation:
    """
    Décide si un rôle doit être appelé et avec quelle adaptation
    éventuelle. Règles :

    SOLO (SASU unipersonnelle, effectif ≤ 1) :
      - supply_chain : SKIP  (aucun flux matière)
      - marketing    : downgrade → pas de plan webinar/RP, focus réseau/LinkedIn perso/cabinets
      - commercial   : downgrade → raisonnement en jours facturés, pas en "clients perdus"

    TPE services :
      - supply_chain : SKIP
      - reste : actif

    PME / ETI+ : tout actif, pas d'adaptation.

    Services-only (toutes tailles) :
      - supply_chain : SKIP systématique
      - exception v16.5.67.10 : holding (APE 70.1/64.2/70.21) avec filiales
        opérationnelles détectées via skip_context["attachments_text"] → SC active

    skip_context : contexte optionnel pour pondérer la décision de skip.
        Clé supportée : "attachments_text" (str) — concat du texte des
        pièces jointes, utilisé pour détecter des signaux physiques
        (stocks, magasins, distribution) chez une filiale.
    """
    # Cas 1 : Supply Chain désactivée pour tous les profils services-only
    if role == "supply_chain":
        _brief_hint = (skip_context or {}).get("brief_text", "") if skip_context else ""
        _attachments_hint = (skip_context or {}).get("attachments_text", "") if skip_context else ""
        _physical_src = f"{_brief_hint}\n{_attachments_hint}"
        # v62.8 — le secteur/périmètre explicitement déclaré dans le brief
        # prime sur un profil registre erroné. Un groupe agro-industriel ne peut
        # jamais être SKIPPED ; le rôle est activé au minimum en mode LIGHT.
        if (_INDUSTRIAL_DECL_RE.search(_physical_src) and
                (_GROUP_DECL_RE.search(_physical_src) or
                 re.search(r"\b(?:usine|site\s+industriel|production|fabrication)\b",
                           _physical_src, re.I))):
            return RoleActivation(
                active=True,
                style_hint=(
                    "IMPORTANT — groupe industriel/agroalimentaire explicitement "
                    "déclaré dans le brief ou les pièces. Mode Supply Chain / "
                    "Industrie actif : analyser sites, capacités, flux matières, "
                    "stocks/BFR, achats, qualité, logistique et intégration des "
                    "filiales. Ne pas déduire un SKIP d'un effectif standalone ou "
                    "d'un APE de holding contradictoire."
                ),
            )
        # v16.5.67.10 — P1bis Exception holding+filiales opérationnelles :
        # si le profil est une HOLDING de pilotage (APE 70.1/64.2/70.21)
        # avec filiales distribution/stocks, ne pas skipper SC.
        # Cas observé dossier réseau de soins 19/04 : holding 70.21Z masquait sa filiale opérationnelle
        # (filiale distribution avec stocks +87%). Contexte récupéré via
        # les attachments passés dans skip_context.
        _is_holding = (
            profile.legal_form and "holding" in profile.legal_form.lower()
        ) or (
            profile.ape_code and profile.ape_code.upper() in {
                "70.10Z", "70.10",   # Activités des sièges sociaux
                "70.21Z", "70.21",   # Conseil en relations publiques / pilotage
                "64.20Z", "64.20",   # Activités des sociétés holding
            }
        )
        _has_physical_signals = False
        if _is_holding and _attachments_hint:
            # Mots-clés révélant une activité opérationnelle physique
            # chez une filiale (distribution, stocks, magasins, retail…)
            _keywords = (
                "stocks", "magasin", "magasins", "centre", "centres",
                "distribution", "réseau", "reseau", "audioprothèses",
                "audioprotheses", "entrepôt", "entrepot", "logistique",
                "livraison", "inventaire", "sku", "retail",
            )
            _att_lower = _attachments_hint.lower()
            _has_physical_signals = any(kw in _att_lower for kw in _keywords)

        if profile.is_services or profile.nature == NATURE_SERVICES:
            # Exception : holding avec signaux d'activité physique dans les
            # filiales → on laisse SC active (LLM pre-filter décidera avec
            # contexte enrichi).
            if _is_holding and _has_physical_signals:
                return RoleActivation(
                    active=True,
                    style_hint=(
                        "IMPORTANT — profil HOLDING avec filiales opérationnelles détecté. "
                        "L'APE de la maison mère est services/pilotage, mais au moins une "
                        "filiale exerce une activité physique (distribution, stocks, réseau "
                        "de points de vente). Concentrer l'analyse Supply Chain sur cette "
                        "ou ces filiales opérationnelles, pas sur la holding."
                    ),
                )
            # B.1.3 (run dossier anglophone coté, point 7) — retail/luxe classé « services »
            # (souvent par cascade d'entité : Ltd sans APE) : si le brief ou
            # les PJ révèlent inventaire/magasins/markdowns matériels, la
            # Supply Chain passe en mode LIGHT (Inventory / Retail Ops) au
            # lieu de SKIPPED.
            _retail_src = f"{_brief_hint}\n{_attachments_hint}".lower()
            _retail_kw = (
                "retail", "magasin", "boutique", "store", "stores",
                "inventaire", "inventory", "stock", "markdown",
                "wholesale", "dtc", "luxury", "luxe",
            )
            if any(kw in _retail_src for kw in _retail_kw):
                return RoleActivation(
                    active=True,
                    style_hint=(
                        "IMPORTANT — profil services avec signaux retail/inventaire "
                        "détectés (brief/PJ). Mode LIGHT : concentrer la Supply Chain "
                        "sur Inventory / Retail Operations (stocks, markdowns, "
                        "disponibilité, DTC vs wholesale, rationalisation points de "
                        "vente, cash immobilisé) — PAS de diagnostic industriel lourd "
                        "(fonderie, usinage, capacité usine)."
                    ),
                )
            # ── B.1.3.20 (P1-E, runs dossier industriel + dossier agroalimentaire) — INDUSTRIE/AGRO
            # LIGHT. Racine reproduite ×2 : profil « services » (homonyme
            # « Conseil » du gabarit) → seed SKIPPED sur un fabricant de
            # machines agricoles puis sur un groupe biscuitier 7 sites + 1
            # chocolaterie. Si le brief/PJ décrivent des flux physiques
            # industriels ou agroalimentaires, la Supply passe en LIGHT —
            # jamais SKIPPED sur la seule foi d'un profil services.
            _indus_kw = (
                "fabrication", "usine", "usines", "production",
                "site industriel", "sites industriels", "industriel",
                "industrielle", "machines", "équipement", "equipement",
                "agroalimentaire", "agro-alimentaire", "biscuiterie",
                "chocolaterie", "matières premières", "matieres premieres",
                "gms", "fusion de sites", "approvisionnement",
                "chaîne de production", "chaine de production",
            )
            if any(kw in _retail_src for kw in _indus_kw):
                return RoleActivation(
                    active=True,
                    style_hint=(
                        "IMPORTANT — profil classé services mais signaux "
                        "industriels/agroalimentaires détectés (brief/PJ). Mode "
                        "LIGHT : Supply Chain / Industrie — sites de production, "
                        "approvisionnements et matières, intégration/fusion de "
                        "sites, logistique aval (GMS/export), rationalisation "
                        "SKU. Pas de diagnostic industriel lourd non sourcé."
                    ),
                )
            return RoleActivation(
                active=False,
                note="Activité de services sans flux physiques — Supply Chain non pertinente.",
            )
        if profile.is_solo:
            return RoleActivation(
                active=False,
                note="Structure unipersonnelle sans opérations matérielles — Supply Chain non pertinente.",
            )

    # Cas 2 : Marketing adapté pour SOLO
    if role == "marketing" and profile.is_solo:
        return RoleActivation(
            active=True,
            style_hint=(
                "IMPORTANT — profil SOLO/TPE services détecté : pas de plan webinar, "
                "pas de RP presse, pas de budget CRM >1 k€. Focus sur canaux "
                "à coût marginal nul : LinkedIn personnel, réseau professionnel, "
                "mise en relation par cabinets de transition ou apporteurs d'affaires. "
                "Budget marketing réaliste pour un solo : <2 k€/an."
            ),
        )

    # Cas 3 : Commercial adapté pour SOLO services
    if role == "commercial" and profile.is_solo and profile.is_services:
        return RoleActivation(
            active=True,
            style_hint=(
                "IMPORTANT — profil SOLO services intellectuels détecté : raisonne "
                "en jours facturés × TJM, pas en 'portefeuille clients perdus'. "
                "Un CA qui baisse peut simplement refléter moins de jours en mission, "
                "pas une érosion commerciale structurelle. Ne propose pas de "
                "'prospection 50 prospects' : le canal réel est le réseau et les "
                "cabinets de transition (Valtus, EIM, Robert Walters, Delville, etc.)."
            ),
        )

    # Cas 4 : Finance — règle de cross-reference obligatoire (voir fix #3)
    # Ce rôle reste toujours actif, mais le moteur injectera une règle
    # additionnelle dans le prompt (géré côté codir_engine).

    # Cas par défaut : rôle actif, pas d'adaptation
    return RoleActivation(active=True)


# ── Helper texte pour injecter le profil dans les prompts ──────────────────
def format_profile_hint(profile: CompanyProfile, lang: str = "fr") -> str:
    """
    Génère un bloc de contexte à injecter en tête de chaque prompt de rôle
    (comme le bloc Pappers). Ce bloc dit au LLM quel type de société il
    analyse, en termes structurels, pour qu'il calibre son raisonnement.
    """
    if lang == "en":
        header = "Company profile (auto-detected):"
        size_lbl = {
            PROFILE_SOLO: "SOLO (1-person SASU/EURL, services)",
            PROFILE_TPE: "VSE (2-9 staff)",
            PROFILE_PME: "SME (10-249 staff)",
            PROFILE_ETI_PLUS: "Mid-cap or large (250+ staff)",
        }.get(profile.size, "SME")
        nature_lbl = {
            NATURE_SERVICES: "intellectual services only (no physical operations)",
            NATURE_PRODUCT: "physical operations / product",
            NATURE_MIXED: "mixed or undetermined",
        }.get(profile.nature, "mixed")
    else:
        header = "Profil société (auto-détecté) :"
        size_lbl = {
            PROFILE_SOLO: "SOLO (SASU/EURL unipersonnelle, services intellectuels)",
            PROFILE_TPE: "TPE (2-9 salariés)",
            PROFILE_PME: "PME (10-249 salariés)",
            PROFILE_ETI_PLUS: "ETI / Grand compte (250+ salariés)",
        }.get(profile.size, "PME")
        nature_lbl = {
            NATURE_SERVICES: "services intellectuels uniquement (aucun flux physique)",
            NATURE_PRODUCT: "opérations physiques / produit",
            NATURE_MIXED: "mixte ou indéterminé",
        }.get(profile.nature, "mixte")

    _L = lambda fr, en: (en if lang == "en" else fr)
    lines = [
        header,
        f"- {_L('Taille', 'Size')} : {size_lbl}",
        f"- {_L('Nature', 'Nature')} : {nature_lbl}",
    ]
    if profile.headcount is not None:
        lines.append(f"- {_L('Effectif', 'Headcount')} : {profile.headcount}")
    if profile.ca_eur is not None:
        lines.append(f"- {_L('CA', 'Revenue')} : {int(profile.ca_eur):,} €".replace(",", " "))
    if profile.ape_code:
        lines.append(f"- {_L('Code APE', 'Industry code (APE)')} : {profile.ape_code}")
    if profile.legal_form:
        lines.append(f"- {_L('Forme juridique', 'Legal form')} : {profile.legal_form.upper()}")
    # Patch v16.5.72.5 — Champs internationaux exposés au LLM downstream
    # (identité : nom officiel, pays, identifiant, LEI, registre).
    if profile.company_name_official:
        lines.append(f"- {_L('Raison sociale (registre)', 'Registry official name')} : {profile.company_name_official}")
    if profile.country:
        lines.append(f"- {_L('Pays / juridiction', 'Country / jurisdiction')} : {profile.country}")
    if profile.company_number:
        # Choisir libellé selon le type d'identifiant
        kind_label = {
            "siren": "SIREN",
            "ch_number": "UK Company Number",
            "cik": "SEC CIK",
            "lei": "LEI",
        }.get(profile.company_number_kind, _L("Identifiant société", "Company ID"))
        lines.append(f"- {kind_label} : {profile.company_number}")
    if profile.lei:
        lines.append(f"- LEI (Legal Entity Identifier) : {profile.lei}")
    if profile.registry:
        lines.append(f"- {_L('Registre', 'Registry')} : {profile.registry}")
    if profile.sector_label:
        lines.append(f"- {_L('Secteur', 'Sector')} : {profile.sector_label}")
    # v62.13.9.4.15 — le statut juridique est transmis EN AMONT, aux agents,
    # comme donnée d'autorité : le run du 02/09/2026 (09:59) avait bâti son
    # livrable sur une radiation inventée que seule la maintenance finale
    # neutralisait, après que cinq agents avaient raisonné dessus.
    _rs = str(getattr(profile, "registry_status", "UNKNOWN") or "UNKNOWN")
    _rsd = str(getattr(profile, "registry_status_detail", "") or "")
    if _rs == "ACTIVE":
        lines.append(f"- {_L('Statut au registre', 'Registry status')} : "
                     f"{_L('EN ACTIVITÉ — inscrite', 'ACTIVE — registered')}"
                     + (f" ({_rsd})" if _rsd else "")
                     + f". {_L('Toute affirmation de radiation, dissolution ou cessation contredirait le registre officiel : ne pas la produire.', 'Any claim of strike-off, dissolution or cessation would contradict the official registry: do not produce it.')}")
    elif _rs == "CEASED":
        lines.append(f"- {_L('Statut au registre', 'Registry status')} : "
                     f"{_L('RADIÉE / CESSÉE', 'STRUCK OFF / CEASED')}"
                     + (f" ({_rsd})" if _rsd else "")
                     + f". {_L('Information de registre à conserver telle quelle.', 'Registry information to keep as is.')}")
    lines.append(f"- {_L('Confiance', 'Confidence')} : {profile.confidence} ({_L('source', 'source')} : {profile.source})")
    return "\n".join(lines) + "\n"
