"""
CoDIR-IA — utils/financial_facts_table.py — Since v16.5.72

Module de traçabilité des faits financiers utilisés dans le livrable.

Bug racine identifié sur audit ChatGPT round 14 (dossier anglophone coté v16.5.71.5) :
- Le rapport contient des chiffres précis (CA 2,38 Md£, marge 0,7%, FCF négatif,
  dette/EBITDA 6,7x, stocks 120 jours) mais la traçabilité est incomplète :
  certains chiffres sont marqués [NON SOURCÉ] dans le Word puis deviennent
  affirmatifs dans le PPT.
- Le rapport peut dire à la fois « 18 PJ attachées » et « aucune pièce
  financière n'a été attachée ». Contradiction qui mine la crédibilité.

Solution v16.5.72 — Source Traceability :
- Dataclass `FinancialFact` typé (label, value, source, page, status, confidence)
- Helper `build_financial_facts_table()` qui construit une vue tabulaire
- Section dédiée dans le DOCX et PPTX (« Faits financiers utilisés »)
- Wording cohérent : un chiffre [NON SOURCÉ] dans Word reste [NON SOURCÉ] / [HYPOTHÈSE] dans PPT
- Logique de status alignée sur la cascade Source Quality v16.5.71

C'est le différenciant produit : passer de « assistant cadrage » (7,5/10)
à « assistant cadrage avec traçabilité auditable » (8,5/10).

Apprentissage round 14 : les recommandations chiffrées doivent être
explicitement taguées comme HYPOTHÈSE / ESTIM_IA, pas comme NON_SOURCÉ
(qui est ambigu).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Enums et constantes
# ─────────────────────────────────────────────────────────────────────────────


class FactStatus(str, Enum):
    """
    Statut de traçabilité d'un fait financier.

    Patch v16.5.72 (audit ChatGPT round 15) — Réduction de 7 à 4 statuts.
    Le DAF / consultant n'a pas besoin de 7 niveaux. 4 suffisent et sont
    plus parlants en réunion :

      - FAIT       : valeur extraite d'un document/source vérifiable
                     (Pappers, Companies House, GLEIF, Annual Report PDF, Excel comptable)
      - ESTIM_IA   : estimation calculée par CoDIR-IA depuis un fait
                     (ex : résultat courant = résultat net - exceptionnels)
      - HYPOTHÈSE  : recommandation chiffrée prescriptive (objectif, cible)
                     (ex : "+15% leads qualifiés", "DSO <60 jours")
      - À_VÉRIFIER : valeur dont la cohérence n'a pas pu être confirmée,
                     remplace INCERTAIN/NON_SOURCÉ (plus parlant DAF)

    Le statut NON_SOURCÉ est conservé en interne uniquement pour rétrocompat
    avec les anciens textes [NON SOURCÉ] des LLMs — converti en À_VÉRIFIER
    au rendu utilisateur.
    """
    FAIT = "FAIT"
    ESTIM_IA = "ESTIM IA"
    HYPOTHESE = "HYPOTHÈSE"
    A_VERIFIER = "À VÉRIFIER"
    # Conservé pour rétrocompat — converti en À_VÉRIFIER au rendu
    NON_SOURCE = "NON SOURCÉ"


# Couleurs / icônes pour rendu PPTX et DOCX (Since v16.5.72)
STATUS_ICON = {
    FactStatus.FAIT: "✅",
    FactStatus.ESTIM_IA: "🤖",
    FactStatus.HYPOTHESE: "💡",
    FactStatus.A_VERIFIER: "🔍",
    FactStatus.NON_SOURCE: "🔍",  # Mappé sur À_VÉRIFIER au rendu
}


# ─────────────────────────────────────────────────────────────────────────────
# Dataclass FinancialFact
# ─────────────────────────────────────────────────────────────────────────────


# B1.1-02 — rang de périmètre pour l'ordre d'affichage (consolidé d'abord).
# F.6.8 (audit dossier réseau de soins) — HOLDING (société mère social, ex. liasse 2050) distinct
# du CONSOLIDÉ groupe : un RN de liasse 2050 n'est PAS un consolidé groupe.
_SCOPE_DISPLAY_RANK = {"CONSOLIDATED": 0, "HOLDING": 1, "SEGMENT": 2, "SOCIAL_STANDALONE": 3,
    "MARKET": 4, "ESTIMATE": 5, "UNKNOWN": 6,
}


def _scope_rank(scope: Optional[str]) -> int:
    return _SCOPE_DISPLAY_RANK.get((scope or "UNKNOWN"), 5)


# ── P0-5 temps 2 (M.5.3) — Localisation EN des libellés de métriques ─────────
# Les faits portent un libellé canonique FR ; en rendu EN il fuyait tel quel
# (« Chiffre d'affaires »). On traduit au rendu, en tolérant un suffixe d'entité
# (« Chiffre d'affaires Groupe (consolidé) »).
_METRIC_LABEL_EN = {
    "Chiffre d'affaires": "Revenue",
    "EBITDA": "EBITDA",
    "EBIT": "EBIT",
    "Résultat net": "Net income",
    "Perte nette": "Net loss",
    "Marge brute": "Gross margin",
    "Marge d'EBITDA": "EBITDA margin",
    "Trésorerie": "Cash",
    "Dette brute": "Gross debt",
    "Dette nette": "Net debt",
    "Dettes financières": "Financial debt",
    "Capitaux propres": "Equity",
    "Effectif": "Headcount",
    "Capacité installée": "Installed capacity",
    "Free cash-flow": "Free cash flow",
    "Statut société (CH)": "Company status (CH)",
    # M.5.10.4 — libellés métadonnées/signal manquants (fuite EN audit dossier anglophone coté)
    "Dernière clôture comptable publiée": "Latest filed accounts date",
    "Signal financier exploitable détecté": "Exploitable financial signal detected",
    # B.1.3.17 (runs 9/2 : « Exploitable » contredit « 0 page-confirmed ») —
    # label requalifié posé par l'engine quand signal solide non effectif.
    "Fragments à consonance financière détectés — non utilisés comme faits":
        "Financial-looking fragments detected — not used as facts",
    "Signal financier multi-format détecté": "Multi-format financial signal detected",
    "Numéro d'entreprise (UK)": "UK Company Number",
}


# ── v62.13.9.4.48 — LIBELLÉS MONOLINGUES (programme 9.4.48, point 1) ─────────────────────────
# Les faits portent un libellé canonique bilingue (« Revenue / Chiffre d'affaires ») qui sert de CLÉ
# (compatibilité d'état, identité de métrique, regroupement des conflits) : il reste tel quel en
# interne. À l'AFFICHAGE, une seule langue — celle du run. Le mélange plafonnait les dossiers
# anglais au Grade C par la porte de langue (runs anglais du 26/09/2026) et alourdissait les Word
# français. Définition unique, utilisée par les deux rendus de la table de faits, les lignes
# exécutives du registre et le point de passage des sorties d'agents.
_BILINGUAL_METRIC_LABELS: dict[str, tuple[str, str]] = {
    "Revenue / Chiffre d'affaires": ("Revenue", "Chiffre d'affaires"),
    "Cost of sales / Coût des ventes": ("Cost of sales", "Coût des ventes"),
    "Gross profit / Marge brute": ("Gross profit", "Marge brute"),
    "Operating profit / Résultat d'exploitation": ("Operating profit", "Résultat d'exploitation"),
    "Profit before tax / Résultat avant impôts": ("Profit before tax", "Résultat avant impôts"),
    "Net income / Résultat net": ("Net income", "Résultat net"),
    "Total assets / Total actif": ("Total assets", "Total actif"),
    "Cash and cash equivalents / Trésorerie": ("Cash and cash equivalents", "Trésorerie"),
    "Total equity / Capitaux propres": ("Total equity", "Capitaux propres"),
    "Net debt / Dette nette": ("Net debt", "Dette nette"),
    "Free cash flow / FCF": ("Free cash flow", "Flux de trésorerie disponible"),
    "Operating cash flow / Flux d'exploitation": ("Operating cash flow", "Flux d'exploitation"),
    "Inventories / Stocks": ("Inventories", "Stocks"),
    "Trade receivables / Créances clients": ("Trade receivables", "Créances clients"),
    "Capex / Investissements": ("Capex", "Investissements"),
    "Effectif / Headcount": ("Headcount", "Effectif"),
    "Operating margin / Marge opérationnelle": ("Operating margin", "Marge opérationnelle"),
    "Margin change / Variation de marge": ("Margin change", "Variation de marge"),
    "EPS / Bénéfice par action": ("EPS", "Bénéfice par action"),
}
_BILINGUAL_RE48 = re.compile(
    "|".join(re.escape(k).replace("'", "['’]") for k in sorted(_BILINGUAL_METRIC_LABELS, key=len, reverse=True)))


def _pick48(bilingual: str, lang: str) -> str:
    key = bilingual.replace("’", "'")
    en, fr = _BILINGUAL_METRIC_LABELS[key]
    return en if str(lang or "fr").lower().startswith("en") else fr


def monolingual_metric_label(label: str, lang: str) -> str:
    """Libellé canonique bilingue → la seule langue du run (suffixe conservé). Inchangé sinon."""
    s = str(label or "")
    m = _BILINGUAL_RE48.match(s)
    return (_pick48(m.group(0), lang) + s[m.end():]) if m else s


def monolingualize_metric_labels(text: str, lang: str) -> str:
    """Même règle dans un texte libre (sorties d'agents qui recopient la table de faits)."""
    if not text:
        return text
    return _BILINGUAL_RE48.sub(lambda m: _pick48(m.group(0), lang), str(text))


def _localize_metric_label(label: str, lang: str) -> str:
    label = monolingual_metric_label(label, lang)          # v62.13.9.4.48 — dans les deux langues
    if lang != "en" or not label:
        return label
    if label in _METRIC_LABEL_EN:
        return _METRIC_LABEL_EN[label]
    for fr, en in _METRIC_LABEL_EN.items():
        if label.startswith(fr):
            return en + label[len(fr):]
    return label


# ── M.5.10.4 — Localisation EN de la COLONNE SOURCE et du STATUT ──────────────
# Les faits portent un source_doc/statut canonique FR qui fuyait tel quel en
# rendu EN (« Pièces jointes (multi-format Excel/Word/CSV) », « NON SOURCÉ »).
_SOURCE_LABEL_EN = {
    "Pièces jointes": "Attachments",
    "Pièce jointe": "Attachment",
    "Contexte société (Pappers)": "Company context (Pappers)",
    "Contexte entité légale (GLEIF)": "Legal entity context (GLEIF)",
    "Contexte société UK (Companies House)": "UK company context (Companies House)",
}

_FACT_STATUS_EN = {
    "FAIT": "FACT",
    "ESTIM IA": "AI ESTIM.",
    "HYPOTHÈSE": "ASSUMPTION",
    "À VÉRIFIER": "TO VERIFY",
    "NON SOURCÉ": "UNSOURCED",
    "NON SOURCE": "UNSOURCED",
}


def _localize_source(source: str, lang: str) -> str:
    """Localise un libellé de source (tolère un suffixe : « X (détail…) »)."""
    if lang != "en" or not source:
        return source
    s = str(source)
    if s in _SOURCE_LABEL_EN:
        return _SOURCE_LABEL_EN[s]
    for fr, en in _SOURCE_LABEL_EN.items():
        if s.startswith(fr):
            return en + s[len(fr):]
    return s


def _localize_fact_status(status: str, lang: str) -> str:
    """Localise un statut de fait (FAIT→FACT, NON SOURCÉ→UNSOURCED…)."""
    if lang != "en" or not status:
        return status
    return _FACT_STATUS_EN.get(str(status).strip().upper(), status)


@dataclass
class FinancialFact:
    """
    Représente un fait financier utilisé dans le livrable, avec sa source
    traçable et son statut de fiabilité.

    Champs :
        label           : libellé court ("Revenue FY25", "Marge opérationnelle")
        value           : valeur formatée ("2,383 M£", "0,7%", "-557 K€")
        source_doc      : nom du document source ("dossier anglophone coté Annual Report FY25")
        source_page     : page exacte (12) ou None si non applicable
        source_section  : section ("Income Statement", "Bilan consolidé") ou None
        status          : FactStatus — niveau de fiabilité
        confidence      : 0.0-1.0 — confiance subjective IA (None si non applicable)
        notes           : commentaires additionnels (ex: "calcul ratio dette/EBITDA")
    """
    label: str
    value: str
    source_doc: Optional[str] = None
    source_page: Optional[int] = None
    source_section: Optional[str] = None
    status: FactStatus = FactStatus.NON_SOURCE
    confidence: Optional[float] = None
    notes: List[str] = field(default_factory=list)
    # v17.1 (P0-01) — Périmètre du fait & usages autorisés (modèle Couche 1).
    # scope : CONSOLIDATED | SOCIAL_STANDALONE | SEGMENT | MARKET | ESTIMATE | UNKNOWN
    # allowed_uses : sous-ensemble de {narrative, finance_model, legal_alert,
    #   comparison} ; vide = pas de restriction explicite. Un agrégat social
    #   standalone d'une cotée NE DOIT PAS servir de chiffre groupe ni d'alerte
    #   juridique (racine du bug Lhyfe).
    scope: str = "UNKNOWN"
    allowed_uses: List[str] = field(default_factory=list)
    # ── M6-B B.1 (v17.4.0) — Schéma du fait probant (D7, note référente v3) ──
    # Schéma conçu COMPLET en amont (un churn de schéma contaminerait la
    # mémoire Christopher), peuplé PROGRESSIVEMENT : B.1 pose identité,
    # périmètre, conflit ; source_type/source_id/document_date → B.2 ;
    # confiance DÉRIVÉE → B.3. Tous les défauts sont neutres (rétrocompat).
    metric_canonical_id: str = ""      # B.1 — clé normalisée (REVENUE, NET_INCOME…)
    period: str = ""                   # B.1 — exercice 2023 | FY2024 | LTM | date
    unit: str = ""                     # B.1 — CUR | PERSONS | PCT | DAYS | RATIO
    currency: str = ""                 # B.1 — EUR | GBP | USD | NOK…
    scale: str = ""                    # B.1 — k | M | Md (l'affichage garde value)
    normalized_value: Optional[float] = None  # B.1 — valeur en unité de base
    perimeter_entity: str = ""         # B.1 — entité du périmètre du fait
    perimeter_role: str = ""           # B.1 — holding | opérationnelle | filiale
    consolidation_role: str = ""       # B.1 — est_le_groupe | contribue_au_groupe | sans_objet
    entity_id: str = ""                # B.1 — SIREN / LEI si connu
    source_type: str = ""              # B.2 (provisionné) — registre | pièce | narratif | benchmark | brief | hypothèse
    source_id: str = ""                # B.2 (provisionné)
    retrieved_at: str = ""             # B.1 — date de récupération (ISO)
    document_date: str = ""            # B.2 (provisionné) — de quand parle la donnée
    transformation: str = ""           # B.1 si agrégé — brut("") | recalculé | agrégé | normalisé | converti
    conflict_group_id: str = ""        # B.1 — lie les faits divergents (E4)
    perimeter_match: str = ""          # B.1 — FULL | COVERAGE | MISMATCH | NA (E3)
    entity_match: str = ""             # B.1 — exact_id | exact_name | alias | same_group_probable | unresolved | mismatch
    stable_fact_key: str = ""          # B.1 — identité stable inter-runs (E1)
    fact_instance_id: str = ""         # B.1 — identité × source_ref (E1)
    run_id: str = ""                   # B.1 — run porteur (hors clé stable)
    analysis_context_id: str = ""      # B.1 — contexte d'analyse du run (E2)
    board_safe_candidate: bool = False # §8.3 — jamais narratif ; gate enforcé en B.4a
    board_safe_blockers: List[str] = field(default_factory=list)
    # v62.11 — preuve financière page-confirmée. Ces champs sont neutres
    # pour les anciens producteurs mais permettent à un même ledger d'alimenter
    # le score, le Word, le PPTX et les diagnostics sans réinterprétation.
    proof_status: str = ""
    # v62.13.1 — la validité probatoire et le rôle canonique sont séparés.
    # Un fait historique ou post-clôture peut rester CONFIRMED_ON_PAGE tout en
    # n'étant pas la valeur courante canonique.
    canonical_role: str = "CURRENT"  # CURRENT | CONTRIBUTING_HISTORY | POST_CLOSE_INDICATION | SUPERSEDED
    definition_axis: str = ""
    source_excerpt: str = ""
    source_value_text: str = ""
    period_end_date: str = ""
    source_document_date: str = ""
    proof_layer_version: str = ""
    source_priority: int = 999

    def to_row_dict(self) -> Dict[str, Any]:  # noqa: C901
        """Conversion en dict pour rendu DOCX/PPTX/CSV diagnostic."""
        return {
            "label": self.label,
            "value": self.value,
            "source": self._format_source(),
            "page": self.source_page if self.source_page else "—",
            "status": self.status.value,
            "icon": STATUS_ICON.get(self.status, "❓"),
            "confidence": (
                f"{self.confidence:.0%}" if self.confidence is not None else "—"
            ),
            # v17.1-A3 — périmètre visible dans les rendus (DOCX/PPTX/CSV).
            # Évite qu'un agrégat social standalone soit lu comme chiffre groupe.
            # B.1.3.14 (runs 5/6/7 : H1 GBP 1.03bn relégué 3 fois) — la PÉRIODE
            # mourait à l'export table→rows : le sélecteur côté app tourne
            # sur les ROWS, deux Revenue à période vide collisionnaient.
            "period": getattr(self, "period", "") or "",
            # B.1.3.17 (dossier industriel (composants) run 2 : narratives au deck) — source_doc exporté :
            # le filtre narratif du render deck (B2.2) testait cette clé, absente
            # des rows depuis toujours (8e lecture morte). Tout consommateur rows
            # dispose désormais de la source canonique en plus du formaté.
            "source_doc": getattr(self, "source_doc", "") or "",
            "source_type": getattr(self, "source_type", "") or "",
            "source_id": getattr(self, "source_id", "") or "",
            "scope": getattr(self, "scope", "UNKNOWN"),
            "scope_note": self._scope_note(),
            # M6-B B.1 (v17.4.0) — traçabilité du fait probant (E1/E3/E4/§8.3)
            "metric_canonical_id": getattr(self, "metric_canonical_id", ""),
            "perimeter_match": getattr(self, "perimeter_match", ""),
            "perimeter_entity": getattr(self, "perimeter_entity", ""),
            "conflict_group_id": getattr(self, "conflict_group_id", ""),
            "stable_fact_key": getattr(self, "stable_fact_key", ""),
            "fact_instance_id": getattr(self, "fact_instance_id", ""),
            "board_safe_blockers": ",".join(
                getattr(self, "board_safe_blockers", []) or []),
            # v62.11 — provenance et statut de preuve consumables par toutes
            # les surfaces ; aucune page ne doit être reconstruite depuis le
            # narratif agent.
            "proof_status": getattr(self, "proof_status", "") or "",
            "canonical_role": getattr(self, "canonical_role", "CURRENT") or "CURRENT",
            "definition_axis": getattr(self, "definition_axis", "") or "",
            "source_excerpt": getattr(self, "source_excerpt", "") or "",
            "source_value_text": getattr(self, "source_value_text", "") or "",
            "period_end_date": getattr(self, "period_end_date", "") or "",
            "source_document_date": getattr(self, "source_document_date", "") or "",
            "proof_layer_version": getattr(self, "proof_layer_version", "") or "",
            "source_priority": int(getattr(self, "source_priority", 999) or 999),
            "normalized_value": getattr(self, "normalized_value", None),
            "unit": getattr(self, "unit", "") or "",
            "currency": getattr(self, "currency", "") or "",
            "scale": getattr(self, "scale", "") or "",
            # B.1.3.1 (bloquant 2 audit) — flag lisible par TOUS les rendus :
            # un chiffre du brief ne s'affiche jamais comme un FAIT nu.
            # B.1.3.56 correctif P0-F56-02 — la GOUVERNANCE voyage avec la row :
            # sans ces clés, un fait diagnostics-only redevenait une row
            # ordinaire chez les consommateurs (sélecteur de deck) et une
            # valeur registre non résolue était promue fait primaire visible.
            "allowed_uses": list(getattr(self, "allowed_uses", []) or []),
            "unresolved_value": getattr(self, "unresolved_value", None),
            "visible_fact": bool(is_visible_fact(self)),
            "brief_only": (
                (getattr(self, "source_doc", "") or "").strip().lower() == "brief"
                or "brief_only" in [str(b).lower() for b in
                                    (getattr(self, "board_safe_blockers", None) or [])]),
        }

    def _scope_note(self) -> str:
        """Note de périmètre lisible pour les rendus et les agents."""
        scope = getattr(self, "scope", "UNKNOWN")
        uses = getattr(self, "allowed_uses", []) or []
        if scope == "HOLDING":
            return ("HOLDING (société mère, comptes sociaux) — "
                    "NON représentatif du consolidé groupe")
        if scope == "SOCIAL_STANDALONE" and "narrative" in uses:
            return "SOCIAL_STANDALONE — usage narratif uniquement, non représentatif du consolidé groupe"
        if scope and scope != "UNKNOWN":
            return scope
        return "—"

    def _format_source(self) -> str:
        """Format propre de la source : doc + section."""
        parts = []
        if self.source_doc:
            parts.append(self.source_doc)
        if self.source_section:
            parts.append(self.source_section)
        if not parts:
            return "—"
        return " — ".join(parts)

    def is_solid(self) -> bool:
        """True si le fait est solidement traçable (FAIT)."""
        return self.status == FactStatus.FAIT

    def is_estimate(self) -> bool:
        """True si le fait est une estimation/hypothèse (taggué non factuel)."""
        return self.status in (
            FactStatus.ESTIM_IA, FactStatus.HYPOTHESE, FactStatus.A_VERIFIER,
        )

    def is_derived(self) -> bool:
        """v17.1.0-B2.3-F.4.3 — True si la VALEUR est CALCULÉE/dérivée (ex. dette
        nette = dette brute − trésorerie) plutôt que lue telle quelle dans une
        source. Un poste dérivé n'est PAS un fait board-safe : il doit être
        rétrogradé « À VÉRIFIER » et ne jamais compter comme FAIT plein."""
        s = (self.source_doc or "").strip().lower()
        if s.startswith("calcul") or "calcul (" in s or "= " in s:
            return True
        for n in (self.notes or []):
            if "calcul" in str(n).lower() or "dérivé" in str(n).lower():
                return True
        return False

    def is_financial_value(self) -> bool:
        """
        Patch v16.5.72.1 (audit ChatGPT round 16) — Distingue les faits
        d'IDENTITÉ SOCIÉTÉ (UK Company Number, LEI, SIREN, dernière
        clôture) vs les VRAIS chiffres financiers (CA, EBITDA, FCF...).

        Bug v16.5.72 : `n_facts_solid > 0` était utilisé pour déclencher
        "Signaux financiers exploitables détectés", ce qui était trompeur
        si on n'avait que LEI + Company Number (FAITS d'identité, pas
        de chiffres financiers).

        Heuristique : un fait est "financial_value" s'il contient des
        chiffres financiers (montants en M€/k€/£/$/%, ratio, etc.) OU
        si son label correspond à un indicateur financier connu.
        """
        if not self.value:
            return False

        # Labels d'identité société (NE comptent PAS comme financial_value)
        identity_labels = {
            "uk company number", "company number", "siren", "siret",
            "lei", "lei (legal entity identifier)", "ape",
            "company status", "statut société",
            "dernière clôture comptable publiée", "accounts made up to",
            "sections financières détectées",
        }
        label_lower = self.label.lower().strip()
        if label_lower in identity_labels:
            return False
        # Labels d'identité partielle (Company Number, SIREN, LEI...)
        for ident in ("company number", "siren", "lei", "siret",
                      "sections détectées", "sections financières"):
            if ident in label_lower:
                return False

        # Label d'indicateur financier connu
        financial_keywords = (
            "chiffre d'affaires", "ca ", "ca(", "revenue", "turnover", "sales",
            "résultat", "result", "profit", "loss", "income", "earnings",
            "ebit", "ebitda", "ebt",
            "marge", "margin",
            "trésorerie", "cash", "fcf", "cash flow", "free cash",
            "dette", "debt", "borrowings",
            "actif", "asset", "passif",
            "capitaux propres", "equity",
            "stocks", "stock", "inventory", "inventories",
            "créances", "receivables",
            "bfr", "working capital",
            "capex", "investment", "investissement",
            "dividend", "dividende",
            "effectif", "headcount",  # effectif Pappers = donnée factuelle
            "covenant",
            "dso", "dpo",
        )
        for kw in financial_keywords:
            if kw in label_lower:
                return True

        # Présence de montant/pourcentage dans la valeur
        if re.search(r"\d.*(?:M€|k€|Md€|M£|M\$|EUR|GBP|USD|€|£|\$|%|pts?|/100)",
                     self.value, re.IGNORECASE):
            return True
        # Ou format numérique évident (1,234.5 / 1 234,56 / 12 millions)
        if re.search(r"\d{1,3}(?:[,.\s]\d{3})+|\d+\s*(?:millions?|milliards?)",
                     self.value, re.IGNORECASE):
            return True

        return False


# ─────────────────────────────────────────────────────────────────────────────
# COUCHE 1 — Extracteur déterministe (Patch v16.5.72 audit ChatGPT round 15)
# ─────────────────────────────────────────────────────────────────────────────
# Construit une table de faits financiers à partir des sources DÉTERMINISTES :
#   - Pappers (FR) : CA, effectif, résultat net officiels
#   - Companies House (UK) : Company Number, statut, accounts last_made_up_to
#   - GLEIF : LEI confirmé
#   - financial_statement_extractor : sections détectées (FAIT par construction)
#   - financial_signal_detector : keywords + montants détectés (À_VÉRIFIER si pas de FS PDF)
#   - attachments_meta : nombre et nature des PJ
#
# Ces sources sont fiables : si Pappers dit CA=220M€, c'est un FAIT (pas une
# hypothèse LLM). On n'attend pas que le LLM le retag.


_BARE_AMOUNT_RE = re.compile(r"^[-+(]?\d[\d\s\u00A0\u202F.,]*\)?$")


def _qualify_bare_statement_amount(fact: "FinancialFact") -> None:
    """v62.13.9.4.32 (A) — UN MONTANT NU EXTRAIT D'UN ÉTAT FINANCIER N'EST PAS UN FAIT
    CERTIFIÉ. Contre-audit du 11/09/2026 (run réel ee08f0) : « Chiffre d'affaires :
    26 », « Stocks : 473,33 », « Résultat net : 906 », « Capitaux propres : 14 »
    portaient la coche FAIT sans unité, sans échelle, sans période — une page
    citée ne rétablit pas ces attributs. Quand ni la valeur, ni l'en-tête de
    colonne, ni la période n'ont fourni d'unité ou de date, le fait reste
    documentaire (page et source conservées) mais passe « À VÉRIFIER », avec la
    raison. Un identifiant de registre ou un fait typé n'est jamais concerné."""
    try:
        v = str(fact.value or "").strip()
        if fact.status != FactStatus.FAIT or not _BARE_AMOUNT_RE.fullmatch(v):
            return
        if (getattr(fact, "unit", "") or getattr(fact, "scale", "") or getattr(fact, "period", "")
                or getattr(fact, "currency", "")):
            return
        fact.status = FactStatus.A_VERIFIER
        fact.notes = list(fact.notes or []) + ["Montant nu : unité, échelle et période non renseignées — à qualifier avant usage"]
    except Exception:
        pass


def _make_fact(
    label: str,
    value: str,
    *,
    source_doc: Optional[str] = None,
    source_section: Optional[str] = None,
    source_page: Optional[int] = None,
    status: FactStatus = FactStatus.FAIT,
    confidence: Optional[float] = None,
    notes: Optional[List[str]] = None,
) -> "FinancialFact":
    """Helper de construction simplifiée d'un FinancialFact."""
    return FinancialFact(
        label=label, value=value,
        source_doc=source_doc, source_section=source_section, source_page=source_page,
        status=status, confidence=confidence,
        notes=notes or [],
    )


def build_facts_from_pappers(pappers_blocks: Optional[Dict[str, Any]]) -> List["FinancialFact"]:
    """
    Couche 1 — Extraction déterministe depuis Pappers (FR).

    Tolère :
      - pappers_blocks=None → liste vide
      - blocs sans données financières → liste vide
      - exception parsing → liste vide (pas de crash)
    """
    if not pappers_blocks or not isinstance(pappers_blocks, dict):
        return []

    facts: List[FinancialFact] = []
    full = pappers_blocks.get("full") or ""
    if not isinstance(full, str) or not full:
        return facts

    # Pattern : "Chiffre d'affaires : 220 124 567 € (2022)" ou "CA 2022 : 220 M€"
    # ou "Chiffre d'affaires (2022) : 220 124 567 €"
    # Patch v16.5.72 (audit ChatGPT round 15) : exiger un séparateur ":" ou un montant ≥ 4 chiffres
    # pour éviter d'attraper l'année (2022, 2023) entre parenthèses.
    ca_match = re.search(
        r"chiffre\s+d['']affaires"
        r"[^:\n]*?:\s*"  # exiger ":" pour éviter de matcher l'année (2022)
        r"([+\-]?\d{1,3}(?:[\s,.\u202F]\d{3})+(?:\s*[€MK]|EUR|MEUR)?|"
        r"\d{4,}(?:\s*[€MK]|EUR|MEUR)?)",
        full, re.IGNORECASE
    )
    if ca_match:
        ca_value = ca_match.group(1).strip()
        facts.append(_make_fact(
            label="Chiffre d'affaires",
            value=ca_value,
            source_doc="Pappers (registre français)",
            source_section="Données financières publiées",
            status=FactStatus.FAIT,
            confidence=0.95,
        ))

    # Effectif
    eff_match = re.search(
        r"effectif[^\d]*?(\d[\d\s]*)\s*(?:salarié|emplo|employé)",
        full, re.IGNORECASE
    )
    if eff_match:
        eff_value = eff_match.group(1).strip()
        facts.append(_make_fact(
            label="Effectif",
            value=f"{eff_value} salariés",
            source_doc="Pappers",
            status=FactStatus.FAIT,
            confidence=0.95,
        ))

    # Résultat net
    rn_match = re.search(
        r"(?:résultat\s+net|résultat\s+de\s+l['']exercice)[^\d]*?"
        r"([+\-]?\d[\d\s,.\u202F]+(?:\s*[€MK]|EUR|MEUR)?)",
        full, re.IGNORECASE
    )
    if rn_match:
        rn_value = rn_match.group(1).strip()
        # B.1.3.23 P1-H' + B.1.3.25 P2-D — une lettre d'échelle sans devise
        # (« -18.4 M ») devient M€ (registre français ⇒ EUR certain) ; une
        # valeur NUE (« 50 ») garde le caveat, on n'invente pas l'échelle.
        _scale25 = re.fullmatch(r"(-?[\d\s.,]+)\s*([KkMm])", rn_value.strip())
        if _scale25:
            rn_value = f"{_scale25.group(1).strip()} {_scale25.group(2).upper()}€"
        elif not re.search(r"[€$£]|EUR|MEUR|\b[KkMm]\s*€", rn_value):
            # B.1.3.56 (scope F, durci gate ChatGPT) — une valeur de registre
            # SANS unité ni période n'est jamais un fait PRÉSENTABLE, mais
            # elle ne disparaît pas : fait porteur `allowed_uses=["diagnostics"]`
            # (invisible des tables CR/deck, conservé dans result.financial_facts
            # et les exports de diagnostic).
            _unres56 = _make_fact(
                label="Résultat net (Pappers) — valeur non résolue",
                value=str(rn_value),
                source_doc="Pappers",
                source_section="Comptes annuels publiés",
                status=FactStatus.FAIT,
                confidence=0.3,
            )
            _unres56.allowed_uses = ["diagnostics"]
            _unres56.unresolved_value = {
                "kind": "UNRESOLVED_VALUE", "metric": "NET_INCOME",
                "raw_value": str(rn_value), "unit": "UNKNOWN",
                "period": "UNKNOWN", "source": "Pappers",
                "visible_fact": False,
            }
            facts.append(_unres56)
            rn_value = None
        if rn_value:
            facts.append(_make_fact(
                label="Résultat net (Pappers)",
                value=rn_value,
                source_doc="Pappers",
                source_section="Comptes annuels publiés",
                status=FactStatus.FAIT,
                confidence=0.95,
            ))

    # v17.1 (P0-01) — Les comptes Pappers SONT des comptes SOCIAUX standalone.
    # On marque le périmètre à la source. Les agrégats financiers (CA, résultat,
    # capitaux propres, EBITDA, bilan) ne peuvent servir ni de chiffre GROUPE
    # consolidé ni d'alerte juridique : c'est la correction à la racine du bug
    # Lhyfe (résultat net standalone re-typé en capitaux propres consolidés).
    _FIN_AGG_KW = ("capitaux propres", "résultat", "resultat", "chiffre d'affaires",
                   "chiffre d’affaires", "ebitda", "bilan", " ca ", "ca(", "marge")
    for _f in facts:
        _f.scope = "SOCIAL_STANDALONE"
        if "diagnostics" in (getattr(_f, "allowed_uses", []) or []):
            continue  # B.1.3.56 — un fait diagnostics-only reste invisible
        _lbl = (_f.label or "").lower()
        if any(_kw in _lbl for _kw in _FIN_AGG_KW):
            _f.allowed_uses = ["narrative"]  # ni legal_alert ni finance_model primaire

    return facts


def build_facts_from_companies_house(ch_blocks: Optional[Dict[str, Any]]) -> List["FinancialFact"]:
    """
    Couche 1 — Extraction déterministe depuis Companies House (UK).

    Patch v16.5.72.2 (audit ChatGPT round 17) — REFONTE :
    Avant v16.5.72.2, on parsait `ch_blocks["full"]` avec une regex
    `company[\\s_]?number` qui ne matchait QUE l'anglais.
    En français, le bloc dit "Numéro de société : 03458224" → 0 fact extrait
    → profil dossier anglophone coté retombait sur "size=pme nature=services".

    Solution v16.5.72.2 : utiliser les champs STRUCTURÉS (langue-agnostique)
    déjà disponibles dans ch_blocks :
      - ch_blocks["company_number"]   (string structuré)
      - ch_blocks["primary"]          (nom officiel)
      - ch_blocks["status"]           (active/dissolved/etc.)

    Le champ "full" (texte rendu) n'est plus parsé — on lit directement
    les structures, ce qui est robuste FR + EN par construction.
    """
    if not ch_blocks or not isinstance(ch_blocks, dict):
        return []

    facts: List[FinancialFact] = []

    # 1. Company Number (depuis champ structuré, pas depuis texte)
    company_number = ch_blocks.get("company_number") or ""
    if company_number:
        facts.append(_make_fact(
            label="UK Company Number",
            value=str(company_number),
            source_doc="Companies House",
            status=FactStatus.FAIT,
            confidence=1.0,
        ))

    # 2. Status (active / dissolved / liquidation / etc.)
    status_val = ch_blocks.get("status") or ""
    if status_val:
        facts.append(_make_fact(
            label="Statut société (CH)",
            value=str(status_val),
            source_doc="Companies House",
            status=FactStatus.FAIT,
            confidence=1.0,
        ))

    # 3. Date dernier compte publié (parsing du full uniquement pour cette
    # info qui n'est pas exposée séparément)
    full = ch_blocks.get("full", "") or ""
    if isinstance(full, str) and full:
        # Patterns multilingues : "Derniers comptes déposés", "Last accounts filed"
        date_match = re.search(
            r"(?:derniers?\s+comptes?\s+déposés?|last\s+accounts?\s+(?:filed|made\s+up\s+to))[\s:]+"
            r"(\d{4}-\d{2}-\d{2}|\d{1,2}\s+\w+\s+\d{4})",
            full, re.IGNORECASE
        )
        if date_match:
            facts.append(_make_fact(
                label="Dernière clôture comptable publiée",
                value=date_match.group(1),
                source_doc="Companies House",
                status=FactStatus.FAIT,
                confidence=1.0,
            ))

    return facts


def build_facts_from_gleif(gleif_blocks: Optional[Dict[str, Any]], lang: str = "fr") -> List["FinancialFact"]:
    """
    Couche 1 — Extraction déterministe depuis GLEIF (LEI international).

    Patch v16.5.72.2 (audit ChatGPT round 17) — REFONTE :
    Utilise les champs structurés au lieu de parser le texte rendu.
    Champs disponibles dans gleif_blocks :
      - gleif_blocks["primary_lei"]      (LEI 20 caractères)
      - gleif_blocks["primary"]          (raison sociale légale)
      - gleif_blocks["primary_country"]  (code pays)
    """
    if not gleif_blocks or not isinstance(gleif_blocks, dict):
        return []

    facts: List[FinancialFact] = []
    lei = gleif_blocks.get("primary_lei") or ""
    if lei and len(lei) == 20:
        facts.append(_make_fact(
            label="LEI (Legal Entity Identifier)",
            value=str(lei),
            source_doc="GLEIF",
            source_section=("International reference database" if (lang or "fr").lower() == "en" else "Référentiel international"),
            status=FactStatus.FAIT,
            confidence=1.0,
        ))
    return facts


def build_facts_from_fs_bundles(
    financial_statements_bundles: Optional[List[Any]],
) -> List["FinancialFact"]:
    """
    Couche 1 — Extraction déterministe depuis financial_statement_extractor.

    Pour chaque bundle FS détecté, ajoute un fait "Sections financières
    extraites" avec la liste des sections et les pages.
    """
    if not financial_statements_bundles:
        return []

    facts: List[FinancialFact] = []
    for bundle in financial_statements_bundles:
        if not getattr(bundle, "financial_statements_detected", False):
            continue
        sections = getattr(bundle, "sections_detected", []) or []
        if not sections:
            continue
        # Note : page exacte non systématiquement disponible — on l'omet sauf
        # si extracted_text_by_section fournit la page
        section_names = ", ".join(getattr(s, "section_name", str(s)) for s in sections)
        facts.append(_make_fact(
            label=f"Sections financières détectées",
            value=section_names,
            source_doc=getattr(bundle, "filename", "PDF"),
            source_section=f"{len(sections)} sections",
            status=FactStatus.FAIT,
            confidence=0.90,
            notes=[f"Pages détaillées dans le bloc Financial Statements"],
        ))
    return facts


def _legacy_build_facts_from_fs_block(
    financial_statements_block: Optional[str],
    *,
    source_doc_default: str = "Financial Statements (extraits PDF)",
) -> List["FinancialFact"]:
    """
    Patch v16.5.72.1 (audit ChatGPT round 16) — Extracteur de FAITS
    financiers depuis le bloc `financial_statements_block` produit par
    `utils/financial_statement_extractor.py` (Since v16.5.70).

    Patch v16.5.72.2 (audit ChatGPT round 17) — RENFORCEMENTS :
      1. Suivi du marqueur "-- p.135 --" → renseigne source_page sur les
         FAITS extraits (la promesse "Page" était vide en v16.5.72.1).
      2. Filtre "année comme valeur" : si montant ∈ [1900-2100] sans unité
         → ignoré (évite de capturer "2025" au lieu de "2,383" sur les
         tableaux multi-année type dossier anglophone coté "2025 2024 2023").
      3. Filtre "numéro de note" : si montant < 10 sans unité ni séparateur
         milliers → ignoré (évite de capturer "Note 4" au lieu de "2,383").
      4. Préférer montants "significatifs" : avec unité M£/M€/£m, ou
         avec séparateur milliers, ou valeur absolue > 50.

    Tolérant : ne crash jamais sur input None/vide/binaire.
    Retourne au plus 15 faits.
    """
    if not financial_statements_block or not isinstance(financial_statements_block, str):
        return []
    if len(financial_statements_block) < 50:
        return []

    facts: List[FinancialFact] = []

    indicators = [
        ("Revenue / Chiffre d'affaires",
         r"\b(?:revenue|turnover|net\s+sales|chiffre\s+d['']affaires|total\s+(?:net\s+)?sales)\b"),
        ("Cost of sales / Coût des ventes",
         r"\b(?:cost\s+of\s+sales|cogs|coût\s+des\s+ventes)\b"),
        ("Gross profit / Marge brute",
         r"\b(?:gross\s+profit|gross\s+margin|marge\s+brute)\b"),
        ("Operating profit / Résultat d'exploitation",
         r"\b(?:operating\s+profit|income\s+from\s+operations|operating\s+income|adjusted\s+operating\s+profit|résultat\s+(?:d['']exploitation|opérationnel))\b"),
        ("EBITDA",
         r"\bEBITDA\b"),
        ("EBIT",
         r"\bEBIT(?!DA)\b"),
        ("Profit before tax / Résultat avant impôts",
         r"\b(?:profit\s+before\s+tax|résultat\s+avant\s+imp[ôo]ts?)\b"),
        ("Net income / Résultat net",
         r"\b(?:net\s+income|net\s+profit|net\s+earnings|résultat\s+(?:net|de\s+l['']exercice))\b"),
        ("Total assets / Total actif",
         r"\b(?:total\s+assets|actif\s+total)\b"),
        ("Cash and cash equivalents / Trésorerie",
         r"\b(?:cash\s+and\s+cash\s+equivalents|cash\s+at\s+(?:bank|year[\s-]?end)|trésorerie\s+(?:nette)?)\b"),
        ("Total equity / Capitaux propres",
         r"\b(?:total\s+equity|shareholders[''']?\s+equity|capitaux\s+propres)\b"),
        ("Net debt / Dette nette",
         r"\b(?:net\s+debt|dette\s+nette)\b"),
        ("Free cash flow / FCF",
         r"\b(?:free\s+cash\s+flow|FCF)\b"),
        ("Operating cash flow / Flux d'exploitation",
         r"\b(?:operating\s+cash\s+flow|net\s+cash\s+from\s+operations|flux\s+d['']exploitation)\b"),
        ("Inventories / Stocks",
         r"\b(?:inventories|stocks?)\b"),
        ("Trade receivables / Créances clients",
         r"\b(?:trade\s+receivables|accounts\s+receivable|créances\s+clients?)\b"),
        ("Capex / Investissements",
         r"\b(?:capex|capital\s+expenditure|investissements?)\b"),
        ("Effectif / Headcount",
         r"\b(?:headcount|number\s+of\s+employees|effectif)\b"),
    ]

    # Pattern montant : capture entiers ou décimaux + unité optionnelle
    # Note v16.5.72.2 : on capture de manière permissive ici, le filtre
    # "is_significant_amount" décidera après si c'est un vrai montant.
    amount_pattern = re.compile(
        r"\(?\s*[+\-]?\d{1,5}(?:[,.\s]\d{3})*(?:[.,]\d{1,3})?\s*\)?"
        r"(?:\s*(?:M£|MGBP|MEUR|M€|MUSD|M\$|k€|KEUR|k\$|Md€|G€|"
        r"%|pts|millions?|billions?|milliards?))?"
    )

    # Patch v16.5.72.2 P0-2 — Pattern marqueur de page "-- p.135 --"
    page_marker_pattern = re.compile(r"--\s*p\.?\s*(\d{1,4})\s*--", re.IGNORECASE)

    def _is_significant_amount(amt_str: str) -> bool:
        """
        Patch v16.5.72.2 P0-2 — Distingue un VRAI montant financier d'un
        bruit (année, numéro de note, en-tête de colonne).

        Apprentissage round 17 : le filtre v1 était trop agressif, il
        rejetait les "petits" montants comme "16" (Operating profit 16 M£
        sur dossier anglophone coté FY25). Conséquence : le code prenait le 2ème montant
        (= valeur N-1, ex 418), donnant un fait FAUX.

        Règles raffinées v16.5.72.2 :
        - REJET STRICT : année isolée 1900-2100 (sans unité, sans séparateur)
        - REJET STRICT : numéro de note < 10 PRÉCÉDÉ par "Note" dans le contexte
          (mais pas si valeur isolée — Operating profit 16 est légitime)
        - SINON : ACCEPT (préférer faux positif à faux négatif sur petits montants)
        """
        if not amt_str or not amt_str.strip():
            return False
        s = amt_str.strip()

        # Présence d'unité financière → toujours accept
        has_unit = bool(re.search(
            r"M£|M€|MGBP|MEUR|MUSD|M\$|k€|KEUR|k\$|Md€|G€|%|pts|millions?|milliards?",
            s, re.IGNORECASE
        ))
        if has_unit:
            return True

        # Séparateur milliers → accept (vrai montant comptable)
        has_thousands_sep = bool(re.search(r"\d[\s,.]\d{3}\b", s))
        if has_thousands_sep:
            return True

        # Sans unité ni séparateur → analyser la valeur
        clean = s.replace("(", "").replace(")", "").replace(" ", "").strip()
        try:
            normalized = clean.replace(",", ".")
            val = abs(float(normalized))
        except ValueError:
            return False

        # Année isolée [1900, 2100] (sans décimale → entier) → rejet
        if 1900 <= val <= 2100 and val == int(val):
            return False

        # Sinon : ACCEPT (y compris petits montants comme "16" qui peuvent
        # être de vrais Operating profit 16 M£ pour dossier anglophone coté)
        return True

    def _line_has_note_indicator(line: str) -> bool:
        """
        Patch v16.5.72.2 — Détecte si la ligne contient "Note X" qui pourrait
        polluer la capture du montant.
        """
        return bool(re.search(r"\bNote\s+\d+\b", line, re.IGNORECASE))

    # Patch v16.5.72.3 (audit ChatGPT round 18) — TOKENISATION au lieu de regex permissive
    # Bug v16.5.72.2 : regex `\d(?:[,.\s]\d{3})*` était trop permissive sur les espaces.
    # Sur "Revenue 2025 £m 2,383 2024 £m 2,968", elle pouvait avaler "2,383 202"
    # (les 3 premiers chiffres de "2024" étaient ré-attachés via espace).
    # Sur "Inventories Note 13 550 497", elle avalait "13 550 497" en un seul match.
    # Solution v16.5.72.3 : tokeniser ligne par ESPACES MULTIPLES (≥2) ou tabulations,
    # filtrer chaque token (année, note, en-tête), retenir 1er token = montant valide.

    def _tokenize_line(text: str) -> List[str]:
        """
        Patch v16.5.72.3 v3 (round 18) — Tokenisation pragmatique.

        Décision méthodologique : entre l'ambiguïté FR "1 234 567" (un nombre
        avec espaces séparateurs milliers) et "Note 13 550 497" (4 tokens
        séparés par espaces), on choisit le **comportement le plus sûr** :

        ESPACE SIMPLE = SÉPARATEUR DE TOKENS (pas séparateur milliers).

        Conséquence :
        - "Revenue 2025 £m 2,383" → ["Revenue", "2025", "£m", "2,383"] ✓ (CAS_05 OK)
        - "Note 13 550 497" → ["Note", "13", "550", "497"] ✓ (CAS_06 OK : 1er token valide = 550)
        - "1 234 567" → ["1", "234", "567"] ❌ (CAS_08 KO sur format FR pur)

        Compromis :
        - On **PRÉSERVE l'unité collée** : "220 M€" reste un token (re-fusion
          si token = nombre seul SUIVI immédiatement de "M€"/"%"/"k€"/etc.)
        - Les vrais formats FR avec espaces séparateurs milliers (Pappers
          legacy) seront **mal extraits** mais c'est un cas marginal :
          • Pappers v16.5.71+ exporte les chiffres dans des champs structurés
          • Les Annual Reports français récents utilisent "1.234.567" ou
            "1,234,567" ou "1234567" dans leurs comptes consolidés
          • Le risque de FAUX POSITIF (extraire "Note 13" comme nombre)
            est plus dangereux qu'un FAUX NÉGATIF (rater un nombre FR)
        """
        # Découpe par tabulations + 2+ espaces (vraie mise en page tabulaire)
        primary = re.split(r"[\t]+|\s{2,}", text)
        primary = [t.strip() for t in primary if t.strip()]

        # Pour chaque primary token, si le pattern est un nombre FR PUR
        # (chiffres + espaces simples + chiffres + unité optionnelle), garder
        # entier. Sinon, tokeniser par 1 espace.
        # Pattern strict FR : pour Pappers/comptes fiscaux français
        fr_strict_pattern = re.compile(
            r"^[+\-]?\d{1,3}(?:[\u202F\u00A0]\d{3})+(?:[,.]\d{1,3})?"  # NB : utilise ESPACE INSÉCABLE pour FR
            r"(?:\s*(?:M£|MGBP|MEUR|M€|MUSD|M\$|k€|KEUR|k\$|Md€|G€|"
            r"%|pts|millions?|milliards?|€|£|\$|EUR|GBP|USD))?$"
        )
        # Pattern plus permissif FR (espace simple)
        fr_loose_pattern = re.compile(
            r"^[+\-]?\d{1,3}(?:\s\d{3})+(?:[,.]\d{1,3})?"
            r"(?:\s*(?:M£|MGBP|MEUR|M€|MUSD|M\$|k€|KEUR|k\$|Md€|G€|"
            r"%|pts|millions?|milliards?|€|£|\$|EUR|GBP|USD))?$"
        )

        tokens = []
        for ptok in primary:
            # Si le primary token entier est un nombre FR insécable strict
            # (Pappers utilise typiquement \u202F ou \u00A0)
            if fr_strict_pattern.match(ptok):
                tokens.append(ptok)
                continue
            # Si le primary token entier est un nombre FR loose ET ne contient
            # pas "Note" (ce qui exclurait "Note 13 550 497")
            if fr_loose_pattern.match(ptok) and "note" not in ptok.lower():
                tokens.append(ptok)
                continue

            # Fallback : split par 1 espace
            # v16.5.75 — Item #7 : avant le split, protéger les nombres style
            # UK avec ESPACE SIMPLE comme séparateur de milliers (ex: "2 461.7"
            # = 2461.7 M£ et non pas ["2", "461.7"]). Le bug dossier anglophone coté v16.5.73
            # extraisait Revenue=3 au lieu de 2461 sur exactement ce pattern.
            # Solution : remplacer "DDD\s\d{3}(\.\d+)?" par
            # "DDD\u202F\d{3}(\.\d+)?" (espace insécable) AVANT split, ET
            # utiliser split(' ') (espace ordinaire seulement) pour PRÉSERVER
            # l'espace insécable dans le token final.
            # Garde-fou : "note" insensible à la casse → on ne fusionne pas
            # (sinon "Note 13 550 497" deviendrait "Note 13\u202F550 497").
            ptok_protected = ptok
            if "note" not in ptok.lower():
                # Pattern UK : 1-3 chiffres + espace + 3 chiffres + (espace + 3 chiffres)* + (. + chiffres)?
                # Ex: "2 461", "12 345", "1 234 567", "2 461.7", "2 461.75"
                ptok_protected = re.sub(
                    r"(?<![\d\u202F\u00A0])(\d{1,3})\s(\d{3})(?:\s(\d{3}))?(?:\s(\d{3}))?(\.\d{1,3})?(?!\d)",
                    lambda m: "\u202F".join([g for g in m.groups()[:-1] if g]) + (m.group(5) or ""),
                    ptok,
                )

            # Split par ESPACE ORDINAIRE uniquement (' '), PAS str.split()
            # qui considérerait \u202F comme whitespace et casserait notre
            # protection ci-dessus.
            sub = [s for s in ptok_protected.split(' ') if s.strip()]
            # Re-fusion d'un nombre suivi immédiatement par une unité
            # (ex: "220" + "M€" → "220 M€")
            merged = []
            i = 0
            while i < len(sub):
                cur = sub[i]
                if i + 1 < len(sub):
                    nxt = sub[i + 1]
                    # Si "cur" est un nombre et "nxt" est une unité pure
                    if (re.match(r"^[+\-]?\(?\d[\d.,]*\)?$", cur)
                            and re.match(r"^(?:M£|MGBP|MEUR|M€|MUSD|M\$|k€|KEUR|k\$|Md€|G€|"
                                         r"%|pts|millions?|milliards?|€|£|\$|EUR|GBP|USD)$",
                                         nxt, re.IGNORECASE)):
                        merged.append(f"{cur} {nxt}")
                        i += 2
                        continue
                merged.append(cur)
                i += 1
            tokens.extend(merged)
        return tokens

    def _is_amount_token(tok: str) -> bool:
        """Vérifie qu'un token ressemble à un montant valide (≥ 1 chiffre)."""
        if not tok:
            return False
        # Doit contenir au moins 1 chiffre
        if not re.search(r"\d", tok):
            return False
        # Doit être majoritairement numérique (autorise (, ), -, +, ., ,, espace, €, £, $, %, M, k, etc.)
        valid_chars = set("0123456789(),.+-€£$%MmKkBb€\u202F\u00A0 ")
        # Aussi accepter "M€", "k€", "Md€", "M£", etc.
        # On vérifie qu'au moins 50% des caractères sont des chiffres
        n_digits = sum(1 for c in tok if c.isdigit())
        if n_digits == 0:
            return False
        # Limite : pas de mots alphabétiques longs (autres que unités)
        # Exemples invalides : "Note", "FY25", "Adjusted"
        # Mais "M€", "M£", "k€" sont OK
        # Heuristique : strip les chiffres+ponctuation, le résidu doit être <= 5 chars
        residual = re.sub(r"[\d\s().,+\-€£$%\u202F\u00A0]", "", tok)
        if len(residual) > 5:  # mot alphabétique trop long
            return False
        # Vérifier que le résidu est uniquement des unités attendues
        if residual and not re.match(r"^[MmKkBb]+(?:€|£|\$|EUR|GBP|USD)?$", residual):
            return False
        return True

    def _token_is_year(tok: str) -> bool:
        """Token = année isolée 1900-2100 ?"""
        clean = tok.replace("(", "").replace(")", "").strip()
        try:
            v = float(clean.replace(",", ".").replace(" ", "").replace("\u202F", ""))
        except ValueError:
            return False
        return 1900 <= v <= 2100 and v == int(v) and not re.search(r"[€£$%MmKkBb]", tok)

    def _token_is_note_marker(tok: str) -> bool:
        """Token est-il 'Note' ou un numéro de note isolé < 100 sans unité ?"""
        if tok.lower().startswith("note"):
            return True
        return False

    def _token_is_unit_header(tok: str) -> bool:
        """Token est-il juste une unité d'en-tête (£m, €M, %, etc.) sans nombre ?"""
        return tok in ("£m", "€m", "$m", "M£", "M€", "M$", "%", "GBP", "EUR", "USD") \
            or (re.match(r"^[€£$%MmKkBb]+$", tok) is not None)

    def _is_meaningful_amount_token(tok: str) -> bool:
        """
        Token = montant exploitable ?
        - Doit ressembler à un montant
        - PAS être une année isolée
        - PAS être un en-tête d'unité
        - PAS être "Note"
        - PAS être un numéro de note isolé < 10 SAUF si entre parenthèses (= comptable -8)
        """
        if not _is_amount_token(tok):
            return False
        if _token_is_year(tok):
            return False
        if _token_is_note_marker(tok):
            return False
        if _token_is_unit_header(tok):
            return False
        # Numéros de note isolés (1-9 sans unité, sans décimale, sans parenthèses)
        clean = tok.strip()
        if (re.match(r"^\d{1,2}$", clean)
                and "(" not in tok
                and not re.search(r"[€£$%MmKk]", tok)):
            try:
                v = int(clean)
                if 0 <= v <= 9:
                    return False  # probable numéro de note
            except ValueError:
                pass
        return True

    # Patch v16.5.72.4 P1 (audit ChatGPT round 19 + audit auto-critique D1) —
    # Tracking du nom de PDF source.
    # Le bloc Financial Statements peut contenir des marqueurs séparateurs
    # type :
    #     --- 📄 dossier anglophone coté_Annual_Report_FY25.pdf ---
    # ou variantes :
    #     === dossier anglophone coté FY25 Annual Report ===
    #     ## dossier anglophone coté_Preliminary_Results_FY25.pdf
    # On détecte ces marqueurs et on assigne le nom au fact en cours.
    pdf_marker_patterns = [
        # "--- 📄 fichier.pdf ---" (format Patch v16.5.70 standard)
        re.compile(r"---\s*📄?\s*([^\s][^\n]*?\.pdf)(?:\s*\([^)]*\))?\s*---", re.IGNORECASE),
        # "=== nom de doc ==="
        re.compile(r"===\s*(.{3,120}?)\s*===", re.IGNORECASE),
        # "## fichier.pdf" en titre
        re.compile(r"^#{1,3}\s+(.{3,80}?\.pdf)\s*$", re.IGNORECASE | re.MULTILINE),
    ]
    current_doc_name: Optional[str] = None

    seen_labels = set()
    n_added = 0
    max_facts = 15
    current_page: Optional[int] = None

    for line in financial_statements_block.splitlines():
        line_strip = line.strip()
        # Détecter marqueur de page
        page_m = page_marker_pattern.search(line_strip)
        if page_m:
            try:
                current_page = int(page_m.group(1))
            except (ValueError, TypeError):
                current_page = None
            continue

        # Patch v16.5.72.4 P1 — Détecter marqueur PDF source
        for doc_pat in pdf_marker_patterns:
            doc_m = doc_pat.search(line_strip)
            if doc_m:
                doc_name = doc_m.group(1).strip()
                # Filtrer marqueurs trop courts ou qui ne ressemblent pas à un doc
                if len(doc_name) >= 4 and not doc_name.startswith("p."):
                    current_doc_name = doc_name
                break

        if len(line_strip) < 5 or len(line_strip) > 400:
            continue

        line_has_note = _line_has_note_indicator(line_strip)

        for label_canon, label_pattern in indicators:
            if label_canon in seen_labels:
                continue
            lbl_m = re.search(label_pattern, line_strip, re.IGNORECASE)
            if not lbl_m:
                continue
            after = line_strip[lbl_m.end():]

            # Patch v16.5.72.4 P0 (audit auto-critique) — Pré-nettoyage des
            # marqueurs inline "(Note X)" et "(Notes X-Y)".
            # Bug v16.5.72.3 : sur "Revenue (Note 4)              2,383",
            # la tokenisation donnait ["(Note", "4)", "2,383"]. Le filtre
            # tolérait "(Note" mais "4)" passait comme montant négatif.
            # Solution : retirer "(Note X)" et variantes AVANT tokenisation.
            after_clean = re.sub(
                r"\(Notes?\s+\d+(?:[-–\s,]+\d+)*\)",  # (Note 4), (Note 4-5), (Notes 4-5), (Notes 4, 5)
                " ", after, flags=re.IGNORECASE,
            )

            # Patch v16.5.72.4 P1 (audit auto-critique A3) — Pré-nettoyage
            # des en-têtes "année £m" / "année EUR" / "FY25 £m" intercalés.
            # Bug v16.5.72.3 : sur "Revenue 2025 £m 2 383 2024 £m 2 968",
            # tokenisation donnait ["2025", "£m", "2", "383", "2024", "£m",
            # "2", "968"]. Année rejetée, "£m" rejeté, "2" rejeté (note 1-99),
            # → capture "383" au lieu de "2 383".
            # Solution : retirer les "année + unité_pure" inline pour permettre
            # à "2 383" de redevenir contigu après split.
            after_clean = re.sub(
                r"\b(?:19|20)\d{2}\s+(?:£m|€m|\$m|M£|M€|M\$|EUR|GBP|USD|"
                r"k€|k£|k\$|Md€)\b",
                " ", after_clean, flags=re.IGNORECASE,
            )
            # Idem pour "FY25 £m" / "FY24 £m"
            after_clean = re.sub(
                r"\bFY\d{2,4}\s+(?:£m|€m|\$m|M£|M€|M\$|EUR|GBP|USD|"
                r"k€|k£|k\$|Md€)\b",
                " ", after_clean, flags=re.IGNORECASE,
            )

            # Patch v16.5.72.3 (round 18) — Tokenisation propre
            tokens = _tokenize_line(after_clean)
            chosen_amount = None
            note_skip_done = False  # Patch v16.5.72.3 v3 — skip note number SI ligne avec "Note"

            # Patch v16.5.72.4 — Recalculer line_has_note APRÈS nettoyage
            # Bug v16.5.72.3 + v16.5.72.4 init : line_has_note était calculé
            # sur line_strip (avant nettoyage des "(Note X)"). Donc le skip
            # note se déclenchait à tort sur "Operating profit (Note 5) 16"
            # → "16" était traité comme numéro de note alors que (Note 5)
            # avait déjà été retiré.
            # Solution : recalculer line_has_note sur after_clean.
            line_has_note = _line_has_note_indicator(after_clean)

            for tok in tokens:
                # Si ligne avec "Note", skip explicitement le token "Note" puis
                # le 1er petit nombre (qui est le numéro de note)
                if line_has_note:
                    if tok.lower() == "note":
                        # token explicite "Note" : skip et marquer
                        note_skip_done = False  # le suivant sera le numéro
                        continue
                    if not note_skip_done:
                        # vérifier si c'est un numéro de note (entier 1-99 sans
                        # unité, sans virgule décimale, sans parenthèses)
                        clean_t = tok.strip()
                        if (re.match(r"^\d{1,2}$", clean_t)
                                and "(" not in tok
                                and not re.search(r"[€£$%MmKk,]", tok)):
                            try:
                                v_int = int(clean_t)
                                if 1 <= v_int <= 99:
                                    note_skip_done = True
                                    continue
                            except ValueError:
                                pass
                if _is_meaningful_amount_token(tok):
                    chosen_amount = tok
                    break

            if not chosen_amount:
                continue

            # Convertir parenthèses comptables → négatif
            if "(" in chosen_amount and not chosen_amount.startswith("-"):
                chosen_amount = "-" + chosen_amount.replace("(", "").replace(")", "").strip()

            facts.append(_make_fact(
                label=label_canon,
                value=chosen_amount,
                # Patch v16.5.72.4 P1 — utilise current_doc_name si disponible,
                # sinon fallback sur source_doc_default (générique).
                source_doc=current_doc_name or source_doc_default,
                source_section="Income Statement / Balance Sheet / Cash Flow",
                source_page=current_page,
                status=FactStatus.FAIT,
                confidence=0.85,
                notes=[f"Extrait automatique du bloc Financial Statements"],
            ))
            _qualify_bare_statement_amount(facts[-1])   # v62.13.9.4.32 (A)
            seen_labels.add(label_canon)
            n_added += 1
            if n_added >= max_facts:
                return facts
            break

    return facts


# ═══════════════════════════════════════════════════════════════════════════
# NOUVEAU PARSER v16.5.72.6 (audit ChatGPT round 21 P0 — option C1 refonte)
# ═══════════════════════════════════════════════════════════════════════════
#
# Architecture en 3 phases (au lieu de 6 couches de pré-nettoyage successives) :
#
#   PHASE 1 — DÉTECTION DE STRUCTURE
#     Pour chaque ligne, identifier :
#       - le label financier reconnu (ex: "Revenue", "Inventories")
#       - le pattern de tableau (1 colonne ? 2 colonnes ? multi-année avec en-tête ?)
#       - les zones à ignorer (Note X, en-têtes "year £m", FY markers)
#
#   PHASE 2 — EXTRACTION DES CELLULES
#     Segmenter la portion "après label" en cellules numériques cohérentes,
#     en utilisant les ZONES DÉTECTÉES en phase 1 comme bornes.
#
#   PHASE 3 — SÉLECTION DE LA VALEUR
#     Choisir la 1ère cellule non-vide significative, en appliquant :
#       - filtre année (1900-2100)
#       - filtre numéro de note (n'importe quel chiffre AVANT la zone "Note X")
#       - filtre en-tête d'unité ("£m", "%")
#       - tolérance comptable (parenthèses → négatif)


def _detect_table_structure(line_after_label: str) -> Dict[str, Any]:
    """
    PHASE 1 — Détection de structure d'une ligne de tableau financier.

    Retourne un dict avec :
      - "has_note_marker"     : bool — la ligne contient "(Note X)" ou "Note X"
      - "note_zone_end"       : int — index de fin de la zone Note (chars)
      - "year_unit_zones"     : List[Tuple[int, int]] — zones "2025 £m" à ignorer
      - "n_year_unit_zones"   : int
      - "is_multi_column"     : bool — pattern "X Y Z" type plusieurs années
      - "raw_after_label"     : str — texte d'origine (debug)
    """
    info = {
        "raw_after_label": line_after_label,
        "has_note_marker": False,
        "note_zone_end": 0,
        "year_unit_zones": [],
        "n_year_unit_zones": 0,
        "is_multi_column": False,
    }

    # Détection note "(Note X)" ou "(Notes X-Y)" ou "(Notes X, Y)"
    note_paren_re = re.compile(
        r"\(Notes?\s+\d+(?:[-–\s,]+\d+)*\)",
        re.IGNORECASE,
    )
    m_note_paren = note_paren_re.search(line_after_label)
    if m_note_paren:
        info["has_note_marker"] = True
        info["note_zone_end"] = m_note_paren.end()

    # Détection note "Note X" (sans parenthèses) — UNIQUEMENT si pas déjà
    # détecté par la version parenthèses
    if not info["has_note_marker"]:
        note_inline_re = re.compile(
            r"\bNote\s+\d{1,3}\b",  # supporte 1-3 chiffres (Note 105 etc.)
            re.IGNORECASE,
        )
        m_note_inline = note_inline_re.search(line_after_label)
        if m_note_inline:
            info["has_note_marker"] = True
            info["note_zone_end"] = m_note_inline.end()

    # Patch v16.5.72.7 (round 22 R01) — % et bps acceptés comme unités d'en-tête année
    # "Operating margin 2025 % 0.7 2024 % 14.1" → year_unit_zones doit détecter "2025 %"
    # Note : on n'utilise pas \b final car % et bps sont parfois suivis d'espace
    # ou de chiffres et le word boundary peut ne pas matcher proprement.
    year_unit_re = re.compile(
        r"\b(?:(?:19|20)\d{2}|FY\d{2,4})\s+"
        r"(?:£m|€m|\$m|M£|M€|M\$|EUR|GBP|USD|"
        r"NOKm|MNOK|kNOK|NOK|CHFm|CHF|"  # B.1.2 — entités scandinaves/suisses
        r"k€|k£|k\$|Md€|%|bps|pts)"
        r"(?=\s|$)",  # lookahead : suivi d'espace ou fin de chaîne
        re.IGNORECASE,
    )
    for m in year_unit_re.finditer(line_after_label):
        info["year_unit_zones"].append((m.start(), m.end()))
    info["n_year_unit_zones"] = len(info["year_unit_zones"])

    # Multi-colonne : si on a ≥2 zones year_unit OU si après nettoyage des
    # zones d'en-tête on a ≥2 montants distincts
    if info["n_year_unit_zones"] >= 2:
        info["is_multi_column"] = True

    return info


def _extract_value_zone(line_after_label: str, structure: Dict[str, Any]) -> str:
    """
    PHASE 2 — Extraction de la ZONE DE VALEUR pertinente.

    On retourne la portion de texte où se trouve la VALEUR COURANTE
    (typiquement année N), en excluant :
      - la zone "(Note X)" / "Note X" (jusqu'à note_zone_end)
      - les zones "année £m" en-têtes

    Pour multi-colonnes, on prend la zone APRÈS la 1ère zone year_unit
    et AVANT la 2ème zone year_unit (= zone valeur N).
    Pour mono-colonne, on prend tout après la note (ou tout depuis le début).
    """
    text = line_after_label

    # Si la ligne est multi-colonnes (≥2 zones year_unit), prendre la zone
    # entre la 1ère et la 2ème zone year_unit
    if structure["n_year_unit_zones"] >= 2:
        zones = structure["year_unit_zones"]
        # Zone de valeur N = entre fin de zone[0] et début de zone[1]
        return text[zones[0][1]:zones[1][0]]

    # Sinon : skip la zone Note si présente
    if structure["has_note_marker"]:
        text = text[structure["note_zone_end"]:]

    # Et nettoyer les en-têtes year_unit résiduelles (cas 1 seule zone)
    if structure["n_year_unit_zones"] == 1:
        z = structure["year_unit_zones"][0]
        # Si la zone est avant la note, recalculer en absolu
        text_clean = (line_after_label[:z[0]] + " "
                      + line_after_label[z[1]:])
        if structure["has_note_marker"]:
            # Recalculer note_zone_end après le nettoyage
            text_clean = re.sub(
                r"\(Notes?\s+\d+(?:[-–\s,]+\d+)*\)|\bNote\s+\d{1,3}\b",
                " ", text_clean, flags=re.IGNORECASE,
            )
        text = text_clean

    return text


def _extract_first_amount_in_zone(
    zone: str, *,
    has_year_unit_zones: bool,
    header_unit: Optional[str] = None,
    label_canon: Optional[str] = None,
) -> Optional[str]:
    """
    PHASE 3 — Sélection de la valeur dans la zone extraite.

    Tokenize la zone et retourne le 1er montant valide en appliquant :
      - filtre année (1900-2100 sans unité)
      - filtre numéro de note résiduel (1-3 chiffres sans unité ni séparateur)
      - filtre en-tête d'unité pure
      - re-fusion nombre + unité collée ("220" + "M€" → "220 M€")

    Comportement multi-colonne :
      Si has_year_unit_zones=True (ligne style "2025 £m 4 200 4 100"),
      on est dans une zone "valeur N" SOUS forme `4 200 4 100`. On veut
      prendre `4 200` (FR loose) puis stop. La logique : prendre tous
      les tokens contigus qui forment un nombre FR loose, puis stop.
    """
    if not zone or not zone.strip():
        return None

    # Pattern montant complet (nombre + unité optionnelle)
    # Décimales acceptées : . ou , ; séparateur milliers : , . \xa0 \u202f OU espace simple
    # Patch v16.5.72.6 (round 21) : ajout de l'espace simple comme séparateur milliers
    # accepté pour matcher "4 200" / "1 234" produit par les fusions FR loose.
    # Unités acceptées : monétaires + % + pts (case-insensitive)
    full_amount_re = re.compile(
        r"[+\-]?\(?\s*\d{1,5}(?:[,.\u202F\u00A0\s]\d{3})*(?:[,.]\d{1,3})?\s*\)?"
        r"(?:\s*(?:M£|MGBP|MEUR|M€|MUSD|M\$|k€|KEUR|k\$|Md€|G€|"
        r"%|pts|millions?|milliards?|€|£|\$|EUR|GBP|USD))?",
        re.IGNORECASE,
    )

    # Pattern token simple (sans unité)
    simple_num_re = re.compile(r"[+\-]?\(?\d+(?:[,.]\d+)?\)?")

    def _is_year(s: str) -> bool:
        clean = s.replace("(", "").replace(")", "").strip()
        try:
            v = float(clean.replace(",", ".").replace(" ", "").replace("\u202F", ""))
        except ValueError:
            return False
        return 1900 <= v <= 2100 and v == int(v)

    def _is_pure_unit(s: str) -> bool:
        return bool(re.fullmatch(r"[€£$%MmKkBb]+|pts|EUR|GBP|USD",
                                  s.strip(), re.IGNORECASE))

    # Tokenise par 2+ espaces / tabulations
    primary_tokens = re.split(r"[\t]+|\s{2,}", zone)
    primary_tokens = [t.strip() for t in primary_tokens if t.strip()]

    # Si une seule primary token, on a une zone simple (mono-colonne ou
    # multi-colonne après extraction). Pour mono-colonne avec note résiduelle,
    # on doit splitter intelligemment.

    # Fonction qui extrait le 1er montant valide d'un primary token
    def extract_from_primary(ptok: str) -> Optional[str]:
        # Cas 1 : le primary token entier est un nombre FR loose (insécable)
        # Pattern : 1-5 chiffres + (espace insécable + 3 chiffres)+ + unité optionnelle
        fr_loose_re = re.compile(
            r"^[+\-]?\d{1,5}(?:[\u202F\u00A0]\d{3})+(?:[,.]\d{1,3})?"
            r"(?:\s*(?:M£|MGBP|MEUR|M€|MUSD|M\$|k€|KEUR|k\$|Md€|G€|"
            r"%|pts|millions?|milliards?|€|£|\$|EUR|GBP|USD))?$"
        )
        if fr_loose_re.match(ptok):
            return ptok

        # FR loose avec espace simple — comportement nuancé (round 21) :
        #
        # Cas A — Avec unité monétaire en fin → ACCEPTER (signal fort)
        #   "1 234 567 €", "2 383 M£" → un nombre FR
        #
        # Cas B — Sans unité, ambiguïté "X YYY" :
        #   - Si X est de 1-2 chiffres (< 100) → probable nombre FR ("2 383")
        #   - Si X est de 3 chiffres (>= 100) → probable 2 colonnes ("550 497")
        # Patch v16.5.72.6 — discrimination par taille du 1er groupe.
        fr_loose_simple_with_unit_re = re.compile(
            r"^[+\-]?\d{1,3}(?:\s\d{3})+(?:[,.]\d{1,3})?"
            r"\s*(?:M£|MGBP|MEUR|M€|MUSD|M\$|k€|KEUR|k\$|Md€|G€|"
            r"%|pts|millions?|milliards?|€|£|\$|EUR|GBP|USD)$"
        )
        if fr_loose_simple_with_unit_re.match(ptok) and "note" not in ptok.lower():
            return ptok

        # Cas B sans unité : tester si le 1er groupe est 1-2 chiffres
        fr_loose_short_first_re = re.compile(
            r"^[+\-]?\d{1,2}\s\d{3}(?:\s\d{3})*(?:[,.]\d{1,3})?$"
        )
        if fr_loose_short_first_re.match(ptok) and "note" not in ptok.lower():
            return ptok

        # Cas 2 : primary token contient plusieurs sous-montants → split simple
        # Exemple : "Note 13 550 497" ou "550 M£" ou "4 200 4 100"
        sub_tokens = ptok.split()

        # Re-fusion nombre + unité collée
        merged: List[str] = []
        i = 0
        while i < len(sub_tokens):
            cur = sub_tokens[i]
            if i + 1 < len(sub_tokens):
                nxt = sub_tokens[i + 1]
                if (re.match(r"^[+\-]?\(?\d[\d.,]*\)?$", cur)
                        and _is_pure_unit(nxt)):
                    merged.append(f"{cur} {nxt}")
                    i += 2
                    continue
            merged.append(cur)
            i += 1
        sub_tokens = merged

        # Patch v16.5.72.6 — re-fusion FR LOOSE dans sub_tokens
        # Si on a "4 200 4 100" avec espaces simples, on veut détecter
        # le 1er groupe "4 200" comme un nombre FR loose.
        # Heuristique : si on voit token[i] = nombre court (1-3 chiffres)
        # SUIVI de token[i+1] = nombre 3 chiffres exactement, on les fusionne
        # SAUF si on a déjà des unités (cas multi-colonne qui doit prendre seulement le 1er).
        # NB : cette fusion ne se fait QUE pour mono-colonne, pas pour
        # multi-colonne où on a déjà extrait la zone correcte.
        if not has_year_unit_zones:
            merged2: List[str] = []
            i = 0
            while i < len(sub_tokens):
                cur = sub_tokens[i]
                # Détecter pattern "X" + "YYY" où X = 1-3 chiffres et YYY = 3 chiffres exactement
                if (i + 1 < len(sub_tokens)
                        and re.match(r"^[+\-]?\d{1,3}$", cur)
                        and re.match(r"^\d{3}$", sub_tokens[i + 1])):
                    # Vérifier qu'on n'est pas en multi-colonne (pas de pattern "X YYY X YYY")
                    # Fusionner UNIQUEMENT s'il n'y a pas une 2e occurrence du même pattern après
                    has_second_pattern = False
                    if i + 3 < len(sub_tokens):
                        cur2 = sub_tokens[i + 2]
                        nxt2 = sub_tokens[i + 3]
                        if (re.match(r"^[+\-]?\d{1,3}$", cur2)
                                and re.match(r"^\d{3}$", nxt2)):
                            has_second_pattern = True
                    if not has_second_pattern:
                        # Patch v16.5.72.7 (round 22 R02) — Discrimination FR Pappers vs colonnes :
                        # - "1 234 567" : 1er groupe 1-2 chiffres → vrai nombre FR
                        # - "550 497 430" : 1er groupe 3 chiffres → 3 colonnes (NE PAS fusionner)
                        try:
                            v_cur = int(cur.replace("-", "").replace("+", ""))
                        except ValueError:
                            v_cur = -1

                        # Fusion 3 groupes FR Pappers UNIQUEMENT si 1er groupe < 100
                        # (Vérifier suite "X YYY YYY" — 3 groupes de 3 chiffres exactement)
                        if (i + 2 < len(sub_tokens)
                                and re.match(r"^\d{3}$", sub_tokens[i + 2])
                                and 0 <= v_cur < 100):
                            # "1 234 567" → fusion 3 groupes (vrai nombre FR Pappers)
                            fused = f"{cur} {sub_tokens[i + 1]} {sub_tokens[i + 2]}"
                            if (i + 3 < len(sub_tokens)
                                    and _is_pure_unit(sub_tokens[i + 3])):
                                fused += f" {sub_tokens[i + 3]}"
                                i += 4
                            else:
                                i += 3
                            merged2.append(fused)
                            continue

                        # Fusion 2 groupes "X YYY" — heuristique :
                        # - v_cur < 10 (1 chiffre) → probable nombre FR ("1 234")
                        # - v_cur ≥ 10 (2-3 chiffres) → probable 2 colonnes ("550 497")
                        if 0 <= v_cur < 10:
                            # "1 234" / "9 999" → probable nombre FR
                            merged2.append(f"{cur} {sub_tokens[i + 1]}")
                            i += 2
                            continue
                        else:
                            # "550 497" / "100 200" → probable 2 colonnes
                            # On ne fusionne PAS, on prend juste cur
                            merged2.append(cur)
                            i += 1
                            continue
                    else:
                        # Patch v16.5.72.7 (round 22 G08) — Multi-colonne mono-segment
                        # "X YYY X YYY" : fusionner UNIQUEMENT si 1er groupe < 100
                        # Cas attendu : "4 200 4 100" → fusion "4 200" (FR loose)
                        # Cas rejeté  : "-350 280 -400 200" → ne PAS fusionner
                        try:
                            v_cur_else = int(cur.replace("-", "").replace("+", ""))
                        except ValueError:
                            v_cur_else = 9999
                        if 0 <= v_cur_else < 100:
                            # Multi-colonne mono-segment "4 200 4 100" → fusion 1er groupe
                            merged2.append(f"{cur} {sub_tokens[i + 1]}")
                            i += 2
                            continue
                        else:
                            # "-350 280 -400 200" → cur est déjà un nombre complet
                            merged2.append(cur)
                            i += 1
                            continue
                merged2.append(cur)
                i += 1
            sub_tokens = merged2

        # Sélection du 1er token valide
        # Patch v16.5.72.13 (retex Robin retest FDE EN page 93) — Cas réel :
        #   "Stocks 3,5 3,867,733 3,867,733 1,057,623"
        # Tokens espacés par 1 seul espace → primary = 1 seul token, mais
        # sub_tokens (split simple) = ['3,5', '3,867,733', '3,867,733', '1,057,623']
        # Le 1er sub_token '3,5' est un décimal court → numéro de note 3.5.
        # Les suivants sont les vraies valeurs (Gross/Amort/Net/N-1).
        #
        # Heuristique additionnelle : skip un décimal court (ex: "3,5", "3.6")
        # SI au moins un autre sub_token suivant est un montant clairement
        # comptable (≥4 chiffres OU avec séparateur milliers OU avec unité).
        # IMPORTANT : ne s'applique pas aux labels de la whitelist
        # LABELS_ACCEPTING_DECIMAL_VALUES (Operating margin, EPS, etc.) car
        # c'est leur valeur légitime.
        # Note : LABELS_ACCEPTING_DECIMAL_VALUES défini plus bas dans la
        # fonction main, on le redéfinit ici en local pour cette closure.
        _LOCAL_LABELS_DEC = {
            "Operating margin / Marge opérationnelle",
            "EPS / Bénéfice par action",
            "Gross profit / Marge brute",
            "Margin change / Variation de marge",
        }

        def _is_short_decimal_note(s):
            """'3,5' ou '3.6' ou '12,5' = décimal court 1-2 chiffres + sep + 1-2 chiffres."""
            return re.fullmatch(r"\d{1,2}[,.]\d{1,2}", s.strip()) is not None

        def _looks_like_real_amount(s):
            """Token qui ressemble clairement à un montant comptable."""
            s = s.strip()
            # Avec séparateur milliers (virgule, point, espace insécable)
            if re.search(r"\d[,.\u202F\u00A0]\d{3}", s):
                return True
            # Au moins 4 chiffres consécutifs
            digits_only = re.sub(r"[^\d]", "", s)
            if len(digits_only) >= 4:
                return True
            # Avec unité monétaire/% explicite
            if re.search(r"M£|M€|MGBP|MEUR|MUSD|M\$|k€|KEUR|k\$|Md€|G€|"
                         r"%|pts|bps|millions?|milliards?|€|£|\$|EUR|GBP|USD",
                         s, re.IGNORECASE):
                return True
            return False

        # Détection préventive : si label NON dans whitelist, et le 1er sub_token
        # NUMÉRIQUE est un décimal court ET il y a un autre sub_token plus tard
        # qui est un vrai montant → skipper le 1er décimal court.
        # Patch v16.5.72.13 — Important : chercher le 1er sub_token NUMÉRIQUE,
        # pas sub_tokens[0] (le PDF FDE a "Trade receivables AND RELATED ACCOUNTS 3.6 ..."
        # donc sub_tokens[0]='and' n'est pas un nombre).
        skip_decimal_note_token = None  # le token '3,5' à skipper
        if (label_canon is not None
                and label_canon not in _LOCAL_LABELS_DEC):
            # Trouver l'index du 1er sub_token NUMÉRIQUE
            first_numeric_idx = None
            for idx, t in enumerate(sub_tokens):
                if any(c.isdigit() for c in t):
                    first_numeric_idx = idx
                    break
            if (first_numeric_idx is not None
                    and _is_short_decimal_note(sub_tokens[first_numeric_idx])):
                # Vérifier qu'au moins UN sub_token NUMÉRIQUE après est un vrai montant
                if any(_looks_like_real_amount(t)
                       for t in sub_tokens[first_numeric_idx + 1:]):
                    skip_decimal_note_token = sub_tokens[first_numeric_idx].strip()

        skip_after_note = False
        decimal_note_skipped = False
        for tok in sub_tokens:
            # Patch v16.5.72.13 — skip 1er décimal court si pattern note résiduelle
            if (skip_decimal_note_token is not None
                    and not decimal_note_skipped
                    and tok.strip() == skip_decimal_note_token):
                decimal_note_skipped = True
                continue

            if tok.lower() == "note":
                skip_after_note = True
                continue
            if skip_after_note:
                # 1er petit nombre après Note = numéro de note (1-3 chiffres)
                if re.fullmatch(r"\d{1,3}", tok):
                    skip_after_note = False
                    continue
                skip_after_note = False  # reset si pas un numéro
            # Année isolée → skip
            if _is_year(tok):
                continue
            # Unité pure → skip
            if _is_pure_unit(tok):
                continue
            # Match montant ?
            m = full_amount_re.fullmatch(tok)
            if m and re.search(r"\d", tok):
                # Ne pas accepter "0" ou "—"
                if tok.strip() in ("0", "—", "-", ""):
                    continue
                # Ne pas accepter une note résiduelle 1-3 chiffres sans unité
                if re.fullmatch(r"\d{1,3}", tok):
                    # Acceptable seulement si > 99 OU si c'est le seul token
                    try:
                        v = int(tok)
                        if v <= 99:
                            # vérifier contexte : s'il y a d'autres tokens, c'est ambigu
                            # Pour l'instant on accepte (cas Operating profit = 16)
                            pass
                    except ValueError:
                        pass
                return tok

        return None

    # Patch v16.5.72.11 (retex Robin sur FDE — bug Note décimale comme valeur)
    # Cas réel observé v16.5.72.10 :
    #   "Inventories          3,5          8 422"
    #   → capture '3,5' (décimal court < 100) au lieu de '8 422'
    # Le numéro de note "3,5" était traité comme valeur car les primary_tokens
    # étaient ['3,5', '8 422'] et 3,5 matchait full_amount_re comme décimale.
    #
    # Heuristique fix : détecter le pattern "note décimale courte + valeur"
    # et skipper le 1er token si :
    #   - il est < 100 (probable num de note, pas montant comptable)
    #   - il n'a pas d'unité (% ou monétaire)
    #   - il est suivi d'un autre token qui ressemble plus à un montant
    #     (longueur >= 4 chars OU avec séparateur milliers OU >= 1000)
    #
    # Patch v16.5.72.12 — Extension : cas H8 (note seule sans valeur après).
    # Sur PDF FDE réel, certaines lignes ont JUSTE la référence à la note
    # sans valeur sur la même ligne. Le parser capturait alors le numéro de
    # note "3,5" comme valeur d'Inventories. Pour rejeter ces cas :
    # - Si label sémantiquement non-décimal (Inventories, Receivables, Equity,
    #   Revenue, Total assets, etc.) ET le SEUL token est un décimal < 100
    #   sans unité → REJETER (probable note résiduelle, pas vraie valeur).
    # - Exception : labels acceptant décimales (Operating margin, EPS, ratios)
    #   ne sont pas concernés car leur valeur LÉGITIME peut être < 100.
    LABELS_ACCEPTING_DECIMAL_VALUES = {
        # Labels où une valeur décimale courte < 100 EST légitime
        "Operating margin / Marge opérationnelle",
        "EPS / Bénéfice par action",
        "Gross profit / Marge brute",  # quand exprimé en %
        "Margin change / Variation de marge",
    }
    if len(primary_tokens) >= 2:
        first_tok = primary_tokens[0].strip()
        # Test : 1er token est-il un nombre décimal < 100 sans unité ?
        is_short_note = (
            re.fullmatch(r"\d{1,2}[,.]\d{1,2}", first_tok) is not None
            or re.fullmatch(r"\d{1,2}", first_tok) is not None
        )
        if is_short_note:
            try:
                val_first = float(first_tok.replace(",", "."))
            except ValueError:
                val_first = 999.0
            # Si 1er token < 100 ET (suivant ressemble plus à un montant)
            if val_first < 100:
                # Vérifier si un token suivant ressemble plus à un montant :
                # - contient un séparateur de milliers
                # - ou est ≥ 4 chiffres consécutifs
                # - ou contient une unité monétaire
                for next_tok in primary_tokens[1:]:
                    has_thousand_sep = bool(
                        re.search(r"\d[,.\s\u202F\u00A0]\d{3}", next_tok)
                    )
                    has_unit = bool(re.search(
                        r"M£|M€|MGBP|MEUR|MUSD|M\$|k€|KEUR|k\$|Md€|G€|"
                        r"€|£|\$|EUR|GBP|USD",
                        next_tok, re.IGNORECASE,
                    ))
                    digits_only = re.sub(r"[^\d]", "", next_tok)
                    has_long_digits = len(digits_only) >= 4
                    if has_thousand_sep or has_unit or has_long_digits:
                        # Skip le 1er token (probable note) → commencer à idx 1
                        primary_tokens = primary_tokens[1:]
                        break

    # Patch v16.5.72.12 — Cas H8 : note SEULE sans valeur après (PDF FDE réel).
    # Si après tous les filtres précédents, il reste UN SEUL token NUMÉRIQUE
    # parmi les primary_tokens (les autres étant du texte alphabétique non
    # numérique comme '/ Stocks'), et que c'est un décimal court < 100 sans
    # unité, ET que le label NE permet PAS de valeurs décimales courtes
    # légitimes → REJETER comme probable note résiduelle.
    if (label_canon is not None
            and label_canon not in LABELS_ACCEPTING_DECIMAL_VALUES):
        # Filtrer pour ne garder que les tokens qui contiennent au moins un chiffre
        numeric_tokens = [
            t.strip() for t in primary_tokens
            if any(c.isdigit() for c in t)
        ]
        if len(numeric_tokens) == 1:
            only_num_tok = numeric_tokens[0]
            # Décimal court < 100 sans unité ?
            is_short_decimal = (
                re.fullmatch(r"\d{1,2}[,.]\d{1,2}", only_num_tok) is not None
            )
            if is_short_decimal:
                try:
                    v = float(only_num_tok.replace(",", "."))
                except ValueError:
                    v = 999.0
                if v < 100:
                    # Vérifier qu'il n'y a PAS d'unité dans la zone
                    has_unit_in_zone = bool(re.search(
                        r"M£|M€|MGBP|MEUR|MUSD|M\$|k€|KEUR|k\$|Md€|G€|"
                        r"%|pts|bps|millions?|milliards?|€|£|\$|EUR|GBP|USD",
                        zone, re.IGNORECASE,
                    ))
                    if not has_unit_in_zone:
                        # Probable note résiduelle → rejeter
                        return None


    # Boucler sur primary tokens, retourner le 1er match
    for ptok in primary_tokens:
        result = extract_from_primary(ptok)
        if result:
            # Convertir parenthèses comptables en négatif
            if "(" in result and not result.startswith("-"):
                result = "-" + result.replace("(", "").replace(")", "").strip()
            result = result.strip()
            # Patch v16.5.72.7 (round 22 R01) — Coller header_unit si la valeur
            # extraite n'a pas déjà une unité.
            # Cas : "Operating margin 2025 % 0.7 2024 % 14.1" → result="0.7", header_unit="%"
            # → résultat final "0.7%"
            if header_unit:
                # Vérifier si le result contient déjà une unité connue
                has_unit = bool(re.search(
                    r"M£|M€|MGBP|MEUR|MUSD|M\$|k€|KEUR|k\$|Md€|G€|"
                    r"%|pts|bps|millions?|milliards?|€|£|\$|EUR|GBP|USD",
                    result, re.IGNORECASE,
                ))
                if not has_unit:
                    # Patch v16.5.72.7 (round 22 R01 raffiné) — Coller l'unité
                    # d'en-tête UNIQUEMENT pour les unités "non-monétaires"
                    # (% et bps), qui changent la sémantique du nombre.
                    # Pour les unités monétaires (£m, M€, etc.), le contexte
                    # de l'Annual Report les rend implicites — ne pas coller
                    # sinon on casse les anti-régressions.
                    h_clean = header_unit.strip()
                    if h_clean == "%":
                        result = f"{result}%"
                    # bps non collé : l'expectation utilise la valeur seule
            return result

    return None


# v62.13.9.4.41 — CONTRAT DE DONNÉE D'UN FAIT D'ÉTAT FINANCIER (contre-audit du 23/09/2026).
# Le balayage cherchait un libellé n'importe où dans le bloc des états et prenait le
# premier montant plausible, sans échelle, sans période, sans savoir de quel état venait
# la ligne : un chiffre d'affaires en milliers s'affichait en dollars (facteur mille), et
# des postes de bilan étaient lus dans le tableau des flux — des variations servies comme
# des soldes. Le libellé doit désormais ouvrir la ligne, la métrique doit être compatible
# avec l'état d'origine, l'échelle déclarée en tête de page et la période de l'en-tête de
# colonnes suivent la valeur ; ce qui ne peut pas être qualifié reste « à vérifier ».
_FS_SECTION_RES41 = [(k, re.compile(rx, re.IGNORECASE)) for k, rx in (
    # v62.13.9.4.41 — la pastille seule ne dit rien : un titre de section doit porter les
    # MOTS de l'état, sinon un intitulé générique ferait basculer toute une page dans le
    # mauvais état et ferait refuser des postes parfaitement légitimes.
    ("income_statement", r"compte\s+de\s+r[\u00e9e]sultat|income\s+statement|statements?\s+of\s+operations"),
    ("balance_sheet",    r"\bbilan\b|balance\s+sheets?"),
    ("cash_flow",        r"flux\s+de\s+tr[\u00e9e]sorerie|cash\s+flows?"),
    ("equity_changes",   r"capitaux\s+propres|changes\s+in\s+equity|stockholders.{0,3}\s+equity"),
    ("notes",            r"notes\s+annexes|notes\s+to\s+(?:the\s+)?(?:consolidated\s+)?financial"),
    ("auditor",          r"rapport\s+de\s+l.auditeur|auditor.s\s+report|accounting\s+firm"),
    ("financial_review", r"revue\s+financi[\u00e8e]re|financial\s+review"),
    ("directors_report", r"rapport\s+de\s+gestion|strategic\s+report|directors.\s+report"),
)]
_OPEN41 = {"financial_review", "directors_report", ""}
_METRIC_SECTIONS41 = {
    "Revenue / Chiffre d'affaires": {"income_statement"} | _OPEN41,
    "Cost of sales / Coût des ventes": {"income_statement"} | _OPEN41,
    "Gross profit / Marge brute": {"income_statement"} | _OPEN41,
    "Operating profit / Résultat d'exploitation": {"income_statement"} | _OPEN41,
    "Operating margin / Marge opérationnelle": {"income_statement"} | _OPEN41,
    "Margin change / Variation de marge": {"income_statement"} | _OPEN41,
    "EBITDA": {"income_statement"} | _OPEN41,
    "EBIT": {"income_statement"} | _OPEN41,
    "EPS / Bénéfice par action": {"income_statement"} | _OPEN41,
    "Profit before tax / Résultat avant impôts": {"income_statement"} | _OPEN41,
    "Net income / Résultat net": {"income_statement"} | _OPEN41,
    "Total assets / Total actif": {"balance_sheet"} | _OPEN41,
    "Cash and cash equivalents / Trésorerie": {"balance_sheet"} | _OPEN41,
    "Total equity / Capitaux propres": {"balance_sheet", "equity_changes"} | _OPEN41,
    "Net debt / Dette nette": {"balance_sheet"} | _OPEN41,
    "Inventories / Stocks": {"balance_sheet"} | _OPEN41,
    "Trade receivables / Créances clients": {"balance_sheet"} | _OPEN41,
    "Free cash flow / FCF": {"cash_flow"} | _OPEN41,
    "Operating cash flow / Flux d'exploitation": {"cash_flow"} | _OPEN41,
    "Capex / Investissements": {"cash_flow", "balance_sheet"} | _OPEN41,
    "Effectif / Headcount": {"notes"} | _OPEN41,
}
_FS_SCALE_RE41 = re.compile(
    r"^\s*[\(\[]?\s*(?:(?:amounts|dollars|figures|montants|chiffres)\s+)?(?:in|en)\s+"
    r"(?:(?:u\.?s\.?\s+)?(?:dollars?|euros?)\s+)?(thousands|milliers|millions|billions|milliards)\b",
    re.IGNORECASE)
_FS_SCALE_UNITS41 = {"thousands": ("k", 1e3), "milliers": ("k", 1e3), "millions": ("m", 1e6),
                     "billions": ("bn", 1e9), "milliards": ("bn", 1e9)}
# v62.13.9.4.41b — L'ÉCHELLE DE PAGE A DES EXCEPTIONS, ET LA PAGE LES ÉCRIT.
# Contre-audit du 24/09/2026 : sous « (In thousands, except per share amounts) », un
# bénéfice par action de 6,69 ressortait en « 6,69 kUSD » coché FAIT, et une marge de
# 8,5 % devenait une valeur monétaire. Une grandeur par action n'est pas une masse
# monétaire, un ratio n'a pas de devise : la nature de la métrique prime sur l'en-tête.
_PER_SHARE41 = {"EPS / Bénéfice par action"}
_RATIO41 = {"Operating margin / Marge opérationnelle", "Margin change / Variation de marge"}
_SCALE_EXCEPTION41 = re.compile(r"except|sauf|hors\b|other\s+than|[àa]\s+l['’]exception", re.IGNORECASE)
_PER_SHARE_WORDS41 = re.compile(r"per\s+share|par\s+action", re.IGNORECASE)
_PCT_VALUE41 = re.compile(r"%|\bpts?\b|\bbps\b|points?\s+de\s+base", re.IGNORECASE)
_FS_CCY_MARK41 = {"$": "USD", "£": "GBP", "€": "EUR"}
_FS_HEADER_PERIOD_RE41 = re.compile(
    r"^\s*(?:(?:fiscal|years?|ended|exercices?|clos|au|as\s+of|at|le|du)\b|[\d/.\-]|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"janvier|f[\u00e9e]vrier|mars|avril|mai|juin|juillet|ao[u\u00fb]t|septembre|octobre|novembre|d[\u00e9e]cembre|"
    r"(?:19|20)\d{2}|FY\s?\d{2,4}|[\s,|$£€])+$", re.IGNORECASE)
# v62.13.9.4.41 — un préfixe de période devant le libellé ne disqualifie pas la ligne :
# « FY25 Revenue 2,383 » reste une ligne de poste, comme « By 2027-01-31: Approve… » reste
# une action. C'est le libellé qui doit ouvrir le POSTE, pas la ligne typographique.
# v62.13.9.4.43 — un en-tête d'unité seul (« £m », « €k », « M€ », « in $m ») fixe devise et
# échelle de la page ; un titre « Group / Consolidated » ou « Company / Société » fixe le
# périmètre. Le validateur commun refuse un fait sans périmètre : le repli doit donc le
# lire là où la page l'écrit, comme le fait la couche primaire.
_FS_UNIT_HEADER41 = re.compile(
    r"^\s*(?:in\s+|en\s+)?(?:([£$€])\s*(m|bn|k|'000|000|million|thousand)s?|(M|Md|K|k)\s*([€$£]))\s*$",
    re.IGNORECASE)
_FS_SCOPE41 = (
    (re.compile(r"\bgroup\b|consolidated|consolid[ée]s?|\bgroupe\b", re.I), "CONSOLIDATED"),
    (re.compile(r"\bcompany\b|\bparent\b|statutory|soci[ée]t[ée]\b|comptes\s+(?:sociaux|annuels)|individuels?", re.I), "SOCIAL"),
)
_FS_LABEL_OPEN41 = re.compile(
    r"^[\s|•\-–—*#>]*"
    r"(?:(?:FY\s?\d{2,4}|(?:19|20)\d{2}|Q[1-4]\s?\d{0,4}|S[12]\s?\d{0,4}|"
    r"\d{1,2}[/.]\d{1,2}[/.]\d{2,4})[\s:.\-–—]*)*", re.IGNORECASE)


def build_facts_from_fs_block(
    financial_statements_block: Optional[str],
    *,
    source_doc_default: str = "Financial Statements (extraits PDF)",
) -> List["FinancialFact"]:
    """
    REFONTE v16.5.72.6 (audit ChatGPT round 21 P0 — option C1).

    Architecture en 3 phases (au lieu de 6 couches de pré-nettoyage successives) :
      PHASE 1 : Détection structure (note marker, year-unit zones, multi-column)
      PHASE 2 : Extraction zone de valeur pertinente
      PHASE 3 : Sélection 1er montant valide dans la zone

    Avantages :
      - Élimine les bugs de pré-nettoyage en cascade (round 21)
      - Distingue clairement "550 497" (multi-colonnes) vs "550 M€" (avec unité)
      - Préserve "1 234 567 €" (FR Pappers) sans fusion abusive
      - Gère "(Note 13) 550 497" → 550 (round 21 P0)
      - Gère "(Note 12) 4 200 4 100" → 4 200 (round 21 P0)

    Le module legacy reste disponible sous _legacy_build_facts_from_fs_block()
    comme garde-fou (rollback possible si régression détectée en condition réelle).
    """
    if not financial_statements_block or not isinstance(financial_statements_block, str):
        return []
    if len(financial_statements_block) < 50:
        return []

    facts: List[FinancialFact] = []

    indicators = [
        ("Revenue / Chiffre d'affaires",
         r"\b(?:revenue|turnover|net\s+sales|chiffre\s+d['']affaires|total\s+(?:net\s+)?sales|total\s+revenue)\b"),
        ("Cost of sales / Coût des ventes",
         r"\b(?:cost\s+of\s+sales|cogs|coût\s+des\s+ventes)\b"),
        ("Gross profit / Marge brute",
         r"\b(?:gross\s+profit|gross\s+margin|marge\s+brute)\b"),
        ("Operating profit / Résultat d'exploitation",
         r"\b(?:operating\s+profit|income\s+from\s+operations|operating\s+income|adjusted\s+operating\s+profit|résultat\s+(?:d['']exploitation|opérationnel))\b"),
        ("Operating margin / Marge opérationnelle",
         r"\b(?:operating\s+margin|marge\s+opérationnelle)\b"),
        ("Margin change / Variation de marge",
         r"\b(?:margin\s+change|variation\s+de\s+marge|change\s+in\s+margin)\b"),
        ("EBITDA",
         r"\bEBITDA\b"),
        ("EBIT",
         r"\bEBIT(?!DA)\b"),
        ("EPS / Bénéfice par action",
         r"\b(?:EPS|earnings\s+per\s+share|bénéfice\s+par\s+action|BPA)\b"),
        ("Profit before tax / Résultat avant impôts",
         r"\b(?:profit\s+before\s+tax|résultat\s+avant\s+imp[ôo]ts?)\b"),
        ("Net income / Résultat net",
         r"\b(?:net\s+income|net\s+profit|net\s+earnings|résultat\s+(?:net|de\s+l['']exercice))\b"),
        ("Total assets / Total actif",
         r"\b(?:total\s+assets|actif\s+total)\b"),
        ("Cash and cash equivalents / Trésorerie",
         r"\b(?:cash\s+and\s+cash\s+equivalents|cash\s+at\s+(?:bank|year[\s-]?end)|trésorerie\s+(?:nette)?)\b"),
        ("Total equity / Capitaux propres",
         r"\b(?:total\s+equity|shareholders[''']?\s+equity|capitaux\s+propres)\b"),
        ("Net debt / Dette nette",
         r"\b(?:net\s+debt|dette\s+nette)\b"),
        ("Free cash flow / FCF",
         r"\b(?:free\s+cash\s+flow|FCF)\b"),
        ("Operating cash flow / Flux d'exploitation",
         r"\b(?:operating\s+cash\s+flow|net\s+cash\s+from\s+operations|flux\s+d['']exploitation)\b"),
        ("Inventories / Stocks",
         r"\b(?:inventories|stocks?)\b"),
        ("Trade receivables / Créances clients",
         r"\b(?:trade\s+(?:and\s+other\s+)?(?:accounts\s+)?receivables?|accounts\s+receivable"
         r"|créances\s+clients?)\b"),
        ("Capex / Investissements",
         r"\b(?:capex|capital\s+expenditure|investissements?)\b"),
        ("Effectif / Headcount",
         r"\b(?:headcount|number\s+of\s+employees|effectif)\b"),
    ]

    page_marker_pattern = re.compile(r"--\s*p\.?\s*(\d{1,4})\s*--", re.IGNORECASE)

    pdf_marker_patterns = [
        re.compile(r"---\s*📄?\s*([^\s][^\n]*?\.pdf)(?:\s*\([^)]*\))?\s*---", re.IGNORECASE),
        re.compile(r"===\s*(.{3,120}?)\s*===", re.IGNORECASE),
        re.compile(r"^#{1,3}\s+(.{3,80}?\.pdf)\s*$", re.IGNORECASE | re.MULTILINE),
    ]
    current_doc_name: Optional[str] = None
    current_page: Optional[int] = None
    # v62.13.9.4.41 — contexte de page : état d'origine, échelle déclarée, devise,
    # périodes d'en-tête. Remis à zéro à chaque page et à chaque changement d'état.
    _sect41 = ""
    _scale41 = ("", 1.0)
    _ccy41 = ""
    _periods41: List[str] = []
    _rows41 = False
    _no_scale_per_share41 = False
    _scope41 = ""

    seen_labels = set()
    n_added = 0
    max_facts = 15

    for line in financial_statements_block.splitlines():
        line_strip = line.strip()

        # Page marker
        page_m = page_marker_pattern.search(line_strip)
        if page_m:
            try:
                current_page = int(page_m.group(1))
            except (ValueError, TypeError):
                current_page = None
            _scale41, _ccy41, _periods41, _rows41 = ("", 1.0), "", [], False
            _no_scale_per_share41 = False
            _scope41 = ""
            continue
        if line_strip.startswith("#"):
            for _k41, _rx41 in _FS_SECTION_RES41:
                if _rx41.search(line_strip):
                    _sect41 = _k41
                    _scale41, _ccy41, _periods41, _rows41 = ("", 1.0), "", [], False
                    break
        _uh41 = _FS_UNIT_HEADER41.match(line_strip)
        if _uh41 and not _rows41:
            _sym41 = _uh41.group(1) or _uh41.group(4) or ""
            _sc_tok41 = (_uh41.group(2) or _uh41.group(3) or "").lower()
            _ccy41 = _FS_CCY_MARK41.get(_sym41, _ccy41)
            _scale41 = {"m": ("m", 1e6), "million": ("m", 1e6), "bn": ("bn", 1e9), "md": ("bn", 1e9),
                        "k": ("k", 1e3), "'000": ("k", 1e3), "000": ("k", 1e3), "thousand": ("k", 1e3)}.get(_sc_tok41, _scale41)
        if not _rows41:
            for _srx41, _sval41 in _FS_SCOPE41:
                if _srx41.search(line_strip):
                    _scope41 = _sval41
                    break
        _sc41 = _FS_SCALE_RE41.match(line_strip)
        if _sc41:
            _scale41 = _FS_SCALE_UNITS41.get(_sc41.group(1).lower(), ("", 1.0))
            # « except per share amounts » : la page dit elle-même où son échelle s'arrête.
            _rest41 = line_strip[_sc41.end():]
            _no_scale_per_share41 = bool(_SCALE_EXCEPTION41.search(_rest41)
                                         and _PER_SHARE_WORDS41.search(_rest41))
            if not _ccy41:
                _ccy41 = ("EUR" if re.search(r"euros?", line_strip, re.I)
                          else "USD" if re.search(r"dollars?", line_strip, re.I) else "")
        if not _ccy41:
            _cm41 = re.search(r"[$£€]", line_strip)
            if _cm41:
                _ccy41 = _FS_CCY_MARK41.get(_cm41.group(0), "")
        if not _rows41 and _FS_HEADER_PERIOD_RE41.match(line_strip):
            _periods41.extend(re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", line_strip))

        # PDF marker
        for doc_pat in pdf_marker_patterns:
            doc_m = doc_pat.search(line_strip)
            if doc_m:
                doc_name = doc_m.group(1).strip()
                if len(doc_name) >= 4 and not doc_name.startswith("p."):
                    current_doc_name = doc_name
                break

        if len(line_strip) < 5 or len(line_strip) > 400:
            continue

        for label_canon, label_pattern in indicators:
            if label_canon in seen_labels:
                continue
            # v62.13.9.4.41 — le libellé doit OUVRIR la ligne (intitulé de poste),
            # pas apparaître au milieu d'une phrase ou d'une note.
            _open41 = _FS_LABEL_OPEN41.match(line_strip)
            _off41 = _open41.end() if _open41 else 0
            lbl_m = re.match(label_pattern, line_strip[_off41:], re.IGNORECASE)
            if not lbl_m:
                continue
            # v62.13.9.4.41 — un poste de bilan ne se lit pas dans le tableau des flux…
            # v62.13.9.4.43 — …sauf s'il y est explicitement un SOLDE : « Cash and cash
            # equivalents at end of year », « trésorerie à la clôture ». Pas de veto
            # global sur le tableau des flux (contre-audit du 25/09) : c'est la nature de
            # la ligne qui tranche, et le validateur commun la revérifie ensuite.
            if _sect41 and _sect41 not in _METRIC_SECTIONS41.get(label_canon, _OPEN41):
                try:
                    from utils.fact_contract42 import classify_line_nature42 as _cln42
                    _explicit_balance = (_sect41 == "cash_flow" and _cln42(line_strip) == "balance")
                except Exception:
                    _explicit_balance = False
                if not _explicit_balance:
                    continue
            _rows41 = True
            after_label = line_strip[_off41 + lbl_m.end():]

            # PHASE 1 — Détection structure
            structure = _detect_table_structure(after_label)

            # PHASE 2 — Extraction zone valeur
            value_zone = _extract_value_zone(after_label, structure)

            # Patch v16.5.72.7 (round 22 R01) — Extraire l'unité d'en-tête (%, £m...)
            # depuis la 1ère year_unit_zone pour la concaténer au montant si la
            # valeur extraite n'a pas d'unité propre.
            header_unit = None
            if structure["year_unit_zones"]:
                z_start, z_end = structure["year_unit_zones"][0]
                z_text = after_label[z_start:z_end]
                # Extraire la partie unité (après l'année + espace)
                _u_m = re.search(
                    r"\b(?:(?:19|20)\d{2}|FY\d{2,4})\s+(.+)$",
                    z_text, re.IGNORECASE,
                )
                if _u_m:
                    header_unit = _u_m.group(1).strip()

            # PHASE 3 — Sélection valeur
            chosen = _extract_first_amount_in_zone(
                value_zone,
                has_year_unit_zones=(structure["n_year_unit_zones"] >= 2),
                header_unit=header_unit,
                label_canon=label_canon,  # v16.5.72.12 — sémantique label
            )

            if not chosen:
                continue

            _f = _make_fact(
                label=label_canon,
                value=chosen,
                source_doc=current_doc_name or source_doc_default,
                source_section=(_sect41 or "Financial statements"),
                source_page=current_page,
                status=FactStatus.FAIT,
                confidence=0.85,
                notes=[f"Extrait automatique (parser v16.5.72.6)"],
            )
            # ── B.1.2 (audit gate B.2, P1) — l'unité d'EN-TÊTE de colonne
            # (« £m », « €m », « NOKm »…) alimente l'identité STRUCTURÉE du
            # fait, SANS toucher la value visible (les rendus historiques
            # attendent « 2,383 »). Sinon « Revenue 2025 £m 2,383 » produit
            # un fait visuellement juste mais faux d'un facteur 10³/10⁶ dans
            # les clés, conflits et agrégats. L'année de colonne, marquage
            # STRUCTUREL d'en-tête, devient la période du fait.
            if header_unit and structure["year_unit_zones"]:
                try:
                    from patches.fact_identity import parse_value as _pv_b12
                    _nv, _u, _cur, _sc = _pv_b12(f"{chosen} {header_unit}")
                    if _nv is not None and _u:
                        _f.normalized_value = _nv
                        _f.unit = _u
                        if _cur:
                            _f.currency = _cur
                        if _sc:
                            _f.scale = _sc
                        _f.notes = list(_f.notes or []) + [
                            f"Unité d'en-tête « {header_unit} » propagée "
                            f"à l'identité B.1 (B.1.2)"]
                    _z0, _z1 = structure["year_unit_zones"][0]
                    _ym = re.search(r"\b(?:FY\s?(\d{2,4})|((?:19|20)\d{2}))\b",
                                    after_label[_z0:_z1], re.IGNORECASE)
                    if _ym and not getattr(_f, "period", ""):
                        if _ym.group(1):
                            _yy = _ym.group(1)
                            _f.period = ("FY" + (_yy if len(_yy) == 4
                                                 else "20" + _yy))
                        else:
                            _f.period = _ym.group(2)
                except Exception:
                    pass  # fail-open : le fait garde sa value, enrich B.1 fera le reste
            # v62.13.9.4.41 — l'échelle déclarée en tête de page et la période de
            # l'en-tête de colonnes suivent la valeur jusqu'au fait livré.
            try:
                _is_ratio41 = (label_canon in _RATIO41 or bool(_PCT_VALUE41.search(str(chosen))))
                _is_per_share41 = (label_canon in _PER_SHARE41
                                   or bool(_PER_SHARE_WORDS41.search(line_strip)))
                if _is_ratio41:
                    _f.unit = "PCT" if _PCT_VALUE41.search(str(chosen) + line_strip) else getattr(_f, "unit", "")
                    _f.currency = ""
                    _f.scale = ""
                    _f.notes = list(_f.notes or []) + ["Ratio : pas de devise, pas d'échelle monétaire"]
                elif _is_per_share41:
                    _f.scale = ""
                    _f.notes = list(_f.notes or []) + [
                        "Montant par action : l'échelle de la page ne s'applique pas"]
                if (_scale41[0] and not getattr(_f, "scale", "")
                        and not _is_ratio41 and not _is_per_share41):
                    # le séparateur se lit sur la forme du nombre, pas sur la langue :
                    # « 341,343 » dans un état américain vaut 341 343, pas 341,343.
                    _raw41 = re.sub(r"[^\d.,\s\u00a0\u202f-]", "", str(chosen)).strip()
                    _n41 = None
                    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?", _raw41):
                        _n41 = float(_raw41.replace(",", ""))
                    elif re.fullmatch(r"-?\d{1,3}(?:[\s\u00a0\u202f]\d{3})+(?:,\d+)?", _raw41):
                        _n41 = float(re.sub(r"[\s\u00a0\u202f]", "", _raw41).replace(",", "."))
                    elif re.fullmatch(r"-?\d+(?:[.,]\d+)?", _raw41):
                        _n41 = float(_raw41.replace(",", "."))
                    if _n41 is not None:
                        _f.normalized_value = _n41 * _scale41[1]
                        _f.scale = _scale41[0]
                        _f.unit = getattr(_f, "unit", "") or "CUR"
                        _f.value = f"{_raw41} {_scale41[0]}{_ccy41 or ''}".strip()
                        if _ccy41 and not getattr(_f, "currency", ""):
                            _f.currency = _ccy41
                        _f.notes = list(_f.notes or []) + [
                            "Échelle déclarée en tête de page, propagée à la valeur"]
                if _periods41 and not getattr(_f, "period", ""):
                    # v62.13.9.4.41 — la période est celle de la COLONNE du montant retenu.
                    # Quand le nombre de valeurs de la ligne ne correspond pas au nombre
                    # d'exercices de l'en-tête (colonne de note, ligne composite), la
                    # colonne n'est pas établie : on ne date pas le fait plutôt que de
                    # lui coller l'exercice courant.
                    _cells41 = [m.group(0) for m in re.finditer(
                        r"(?<![\d.,])\(?-?\d{1,3}(?:[,\s\u00a0\u202f]\d{3})+(?:[.,]\d+)?\)?"
                        r"|(?<![\d.,])\(?-?\d+(?:[.,]\d+)?\)?", after_label)]
                    _norm41 = lambda t: re.sub(r"[^\d]", "", str(t))
                    # v62.13.9.4.43 — « 125 110 » sous deux exercices, ce sont deux colonnes,
                    # pas un nombre à séparateur d'espace : quand la lecture groupée donne
                    # moins de cellules que d'exercices, on relit en colonnes, et on ne
                    # retient cette lecture que si le compte tombe juste.
                    if len(_cells41) != len(_periods41):
                        _split41 = [t for t in re.split(r"[\s\u00a0\u202f]+", after_label.strip())
                                    if re.fullmatch(r"\(?-?\d{1,3}(?:[.,]\d+)?\)?|\(?-?\d+(?:[.,]\d+)?\)?", t)]
                        if len(_split41) == len(_periods41):
                            _cells41 = _split41
                    _idx41 = next((k for k, c in enumerate(_cells41)
                                   if _norm41(c) == _norm41(chosen)), -1)
                    if len(_cells41) == len(_periods41) and _idx41 >= 0:
                        _f.period = "FY" + _periods41[_idx41]
                        _f.notes = list(_f.notes or []) + [
                            "Période lue dans la colonne du montant"]
                    elif len(_periods41) == 1:
                        _f.period = "FY" + _periods41[0]
                        _f.notes = list(_f.notes or []) + [
                            "Période lue dans l'en-tête de colonnes de la page"]
                    else:
                        _f.notes = list(_f.notes or []) + [
                            "Colonne d'exercice non établie sur la ligne — période non renseignée"]
            except Exception:
                pass
            if _scope41 and str(getattr(_f, "scope", "") or "").strip().upper() in ("", "UNKNOWN"):
                _f.scope = _scope41
            # v62.13.9.4.43 — le repli cite sa ligne : sans extrait, ni le validateur commun
            # ni la garde d'extrait ne peuvent juger le fait, et il tombait pour cette seule
            # raison — un fait sans preuve produite par le produit lui-même.
            if not str(getattr(_f, "source_excerpt", "") or "").strip():
                _f.source_excerpt = line_strip[:500]
            if not str(getattr(_f, "source_value_text", "") or "").strip():
                _f.source_value_text = str(chosen).strip()
            # v62.13.9.4.43 — un fait du repli qui porte tout ce que la couche primaire
            # exige — ligne citée, valeur dans la ligne, devise et échelle, période de
            # colonne, périmètre — est confirmé à la page au même titre qu'elle. Le
            # validateur commun et la garde d'extrait passent ENSUITE et peuvent le
            # déclasser : l'étiquette n'est pas une preuve, la ligne l'est.
            try:
                if (_f.status == FactStatus.FAIT and not str(getattr(_f, "proof_status", "") or "")
                        and getattr(_f, "currency", "") and (getattr(_f, "scale", "") or getattr(_f, "unit", ""))
                        and str(getattr(_f, "period", "") or "").strip()
                        and str(getattr(_f, "scope", "") or "").strip().upper() not in ("", "UNKNOWN")):
                    _f.proof_status = "CONFIRMED_ON_PAGE"
            except Exception:
                pass
            _qualify_bare_statement_amount(_f)          # v62.13.9.4.32 (A)
            # v62.13.9.4.41b — sans période, un montant d'état n'est pas un fait : deux
            # exercices se lisent sur la même ligne, et un chiffre sans date ne se rattache
            # à rien. Contre-audit du 24/09 : FAIT sans période dans la table livrée.
            try:
                if _f.status == FactStatus.FAIT and not str(getattr(_f, "period", "") or "").strip():
                    _f.status = FactStatus.A_VERIFIER
                    _f.notes = list(_f.notes or []) + [
                        "Période non établie sur la ligne — à qualifier avant usage"]
            except Exception:
                pass
            # v62.13.9.4.41 — un montant sans devise ET sans échelle ni unité n'est pas
            # un fait, même si sa période est connue : il reste à qualifier, avec sa page.
            try:
                if (_f.status == FactStatus.FAIT
                        and _BARE_AMOUNT_RE.fullmatch(re.sub(r"[^\d.,\s\u00a0\u202f()+-]", "", str(_f.value)).strip())
                        and not (getattr(_f, "currency", "") and (getattr(_f, "scale", "") or getattr(_f, "unit", "")))):
                    _f.status = FactStatus.A_VERIFIER
                    _f.notes = list(_f.notes or []) + [
                        "Devise ou échelle non établie sur la page — à qualifier avant usage"]
            except Exception:
                pass
            facts.append(_f)
            seen_labels.add(label_canon)
            n_added += 1
            if n_added >= max_facts:
                return facts
            break

    return facts



def build_documentary_facts_from_attachments(
    attachments_block: Optional[str],
) -> List["FinancialFact"]:
    """Extrait des faits documentaires page-cités hors états financiers.

    v62.8 — un traité de fusion peut contenir des faits primaires utiles
    (effectif transféré, engagement retraite, couverture IFC) sans contenir un
    compte consolidé. Ces faits doivent irriguer la proof layer, mais ne doivent
    jamais débloquer les calculs de CA/EBITDA groupe.
    """
    block = str(attachments_block or "")
    if not block:
        return []
    try:
        from patches.financial_extractor import _iter_lines_with_provenance
    except Exception:
        return []

    rows = list(_iter_lines_with_provenance(block))
    facts: List[FinancialFact] = []
    seen: set[tuple] = set()

    def _num(raw: str) -> float | None:
        try:
            return float(re.sub(r"[^0-9,.-]", "", raw).replace(" ", "").replace(",", "."))
        except Exception:
            return None

    def _period(txt: str) -> str:
        m = re.search(r"\b(?:au\s+)?(\d{2}/\d{2}/20\d{2}|20\d{2})\b", txt, re.I)
        return m.group(1) if m else ""

    def _add(*, label: str, value: str, metric: str, unit: str,
             normalized: float | None, src: str, page: int, context: str,
             period: str = "") -> None:
        key = (metric, normalized, src, page, period)
        if key in seen:
            return
        seen.add(key)
        fact = _make_fact(
            label=label, value=value, source_doc=src or "Pièce jointe",
            source_section="Fait documentaire primaire",
            source_page=page or None, status=FactStatus.FAIT,
            confidence=0.92 if page else 0.75,
            notes=["Extraction déterministe v62.8", context[:240]],
        )
        fact.metric_canonical_id = metric
        fact.period = period
        fact.unit = unit
        fact.currency = "EUR" if unit == "CUR" else ""
        fact.normalized_value = normalized
        fact.scope = "SOCIAL_STANDALONE"
        fact.allowed_uses = ["narrative"]
        fact.source_type = "attachment"
        fact.source_id = f"{src}#p{page}" if src and page else (src or "attachment")
        fact.board_safe_candidate = bool(page)
        # v62.11 — documentary facts are page-confirmed when their value and
        # page are explicit. They remain narrative-only and therefore cannot
        # unlock consolidated revenue / EBITDA / cash analysis.
        fact.proof_status = "CONFIRMED_ON_PAGE" if page else "PAGE_UNAVAILABLE"
        fact.source_excerpt = context[:500]
        fact.source_value_text = value
        fact.period_end_date = period
        fact.source_document_date = period
        fact.proof_layer_version = "v62.11-documentary"
        fact.source_priority = 20
        if not page:
            fact.board_safe_blockers = ["page_missing"]
        facts.append(fact)

    for idx, (src, page, line) in enumerate(rows):
        # Fenêtre courte pour les tableaux où libellé et valeur sont sur des
        # lignes adjacentes. On ne traverse ni changement de fichier ni page.
        window = [line]
        for j in range(idx + 1, min(idx + 4, len(rows))):
            s2, p2, l2 = rows[j]
            if s2 != src or p2 != page:
                break
            window.append(l2)
        ctx = " ".join(w.strip() for w in window if w.strip())
        ctx = re.sub(r"\s+", " ", ctx)

        # Effectif — v62.13.9.4.41 : COHÉRENCE DE GRANDEUR ET ADJACENCE.
        # Contre-audit du 23/09/2026 : la règle « effectif … puis le premier nombre dans
        # les 80 caractères » prenait, dans une note d'engagements de retraite, le taux de
        # charges sociales (42 %) et le renvoyait en « 42 salariés » ; sur la même pièce
        # elle prenait aussi un renvoi « (1) » en « 1 salariés ». Un nombre de personnes
        # ne porte pas de %, d'euros, d'années ni de mois, et il doit être COLLÉ à son
        # libellé — pas trouvé quelque part dans le voisinage. La valeur affichée cite
        # désormais la page au lieu d'être reconstruite.
        _n41 = r"(\d{1,3}(?:[\s\u00a0\u202f]\d{3})+|\d{1,5})"
        mh = re.search(_n41 + r"\s+(?:salari[ée]s?|employ[ée]s?|collaborateurs?|ETP|personnes)\b",
                       ctx, re.I)
        if not mh:
            # un renvoi de note « (1) » n'est pas un effectif : le nombre ne doit pas
            # être entre parenthèses, et il suit son libellé à courte distance.
            mh = re.search(r"\b(?:effectif|headcount)s?\b[^\d\n(]{0,24}?" + _n41 + r"\b", ctx, re.I)
        if mh and not re.match(r"\s*(?:%|‰|€|EUR|\$|£|k€|M€|bps|pts?\b|ans?\b|ann[ée]es?\b|mois\b|\))",
                               ctx[mh.end(1):mh.end(1) + 12], re.I):
            n = int(re.sub(r"\D", "", mh.group(1)))
            if 0 < n < 100000:
                _add(label="Effectif", value=ctx[mh.start():mh.end()].strip()[:60],
                     metric="HEADCOUNT",
                     unit="PERSONS", normalized=float(n), src=src, page=page,
                     context=ctx, period=_period(ctx))

        # Engagement retraite brut.
        mr = re.search(
            r"\bengagements?\s+(?:de\s+)?retraite\b.{0,120}?"
            r"([0-9][0-9\s\u202f\u00a0.,]{2,})\s*(€|EUR|k€|M€)", ctx, re.I)
        if not mr:
            mr = re.search(
                r"([0-9][0-9\s\u202f\u00a0.,]{2,})\s*(€|EUR|k€|M€).{0,100}?"
                r"\bengagements?\s+(?:de\s+)?retraite\b", ctx, re.I)
        if mr:
            raw, scale = mr.group(1), mr.group(2).lower()
            val = _num(raw)
            if val is not None:
                if scale == "k€": val *= 1_000
                elif scale == "m€": val *= 1_000_000
                _add(label="Engagement retraite", value=f"{int(round(val)):,} €".replace(",", " "),
                     metric="PENSION_COMMITMENT", unit="CUR", normalized=val,
                     src=src, page=page, context=ctx, period=_period(ctx))

        # Couverture / contrat IFC, assurance CIC.
        mc = re.search(
            r"\b(?:contrat\s+de\s+couverture|couverture|contrat\s+IFC|IFC|CIC)\b"
            r".{0,140}?([0-9][0-9\s\u202f\u00a0.,]{2,})\s*(€|EUR|k€|M€)", ctx, re.I)
        if mc:
            raw, scale = mc.group(1), mc.group(2).lower()
            val = _num(raw)
            if val is not None:
                if scale == "k€": val *= 1_000
                elif scale == "m€": val *= 1_000_000
                _add(label="Couverture IFC / assurance", value=f"{int(round(val)):,} €".replace(",", " "),
                     metric="PENSION_COVERAGE", unit="CUR", normalized=val,
                     src=src, page=page, context=ctx, period=_period(ctx))
    return facts


def build_facts_from_financial_signal_report(
    fs_signal_report: Optional[Any],
) -> List["FinancialFact"]:
    """
    Couche 1 — Extraction déterministe depuis financial_signal_detector.

    Si signal solide détecté (dossier réseau de soins cas Excel/Word), ajoute un fait
    "Signal financier multi-format détecté" avec les indicateurs.
    """
    if not fs_signal_report:
        return []
    if not getattr(fs_signal_report, "financial_signal_solid", False):
        return []

    facts: List[FinancialFact] = []
    n_keywords = getattr(fs_signal_report, "n_keywords", 0)
    n_amounts = getattr(fs_signal_report, "n_amounts", 0)
    score = getattr(fs_signal_report, "confidence_score", 0)

    facts.append(_make_fact(
        label="Signal financier exploitable détecté",
        value=f"score {score}/100",
        source_doc="Pièces jointes (multi-format Excel/Word/CSV)",
        source_section=f"{n_keywords} keywords financiers + {n_amounts} montants détectés",
        status=FactStatus.FAIT,
        confidence=min(1.0, score / 100),
    ))
    return facts


def _num41(txt):
    """Valeur numérique d'un jeton, en lisant le séparateur sur la forme du nombre."""
    t = str(txt or "").strip().replace("\u00a0", " ").replace("\u202f", " ")
    neg = t.startswith("(") and t.endswith(")")
    t = re.sub(r"[^\d.,\s-]", "", t).strip()
    if not t:
        return None
    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?", t):
        v = t.replace(",", "")
    elif re.fullmatch(r"-?\d{1,3}(?:\s\d{3})+(?:,\d+)?", t):
        v = t.replace(" ", "").replace(",", ".")
    else:
        v = t.replace(" ", "").replace(",", ".")
    try:
        f = float(v)
    except ValueError:
        return None
    return -abs(f) if neg else f


_NUM_TOKEN41 = re.compile(
    r"\(?-?\d{1,3}(?:[\s\u00a0\u202f]\d{3})+(?:[.,]\d+)?\)?"   # 79 871 — groupes de trois
    r"|\(?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?"                    # 619,985
    r"|\(?-?\d+(?:[.,]\d+)?\)?")                                 # 42 / 6.6


# v62.13.9.4.41b — vocabulaire des grandeurs, pour vérifier que l'extrait parle bien de
# la métrique du fait. Général, sans nom de société ni valeur de dossier.
_METRIC_VOCAB41 = (
    (r"revenue|chiffre\s+d['’]affaires|turnover|net\s+sales",
     r"revenue|turnover|net\s+sales|chiffre\s+d['’]affaires|ventes\s+nettes|produits\s+d['’]exploitation"),
    (r"gross\s+profit|marge\s+brute", r"gross\s+(?:profit|margin)|marge\s+brute"),
    (r"operating\s+profit|income\s+from\s+operations|operating\s+income(?!\s+tax)|résultat\s+d['’]exploitation|résultat\s+opérationnel",
     r"operating\s+(?:profit|income)|income\s+from\s+operations|résultat\s+(?:d['’]exploitation|opérationnel)"),
    (r"operating\s+margin|marge\s+opérationnelle", r"operating\s+margin|marge\s+opérationnelle"),
    (r"net\s+income|résultat\s+net", r"net\s+(?:income|profit|earnings)|résultat\s+net|bénéfice\s+net"),
    (r"\bEPS\b|bénéfice\s+par\s+action", r"\bEPS\b|(?:earnings|bénéfice|résultat)\s+par\s+action|per\s+share"),
    (r"total\s+assets|total\s+actif", r"total\s+assets|total\s+(?:de\s+l['’])?actif|total\s+du\s+bilan"),
    (r"cash|trésorerie", r"cash(?:\s+and\s+cash\s+equivalents)?|trésorerie|disponibilités"),
    (r"equity|capitaux\s+propres", r"(?:total\s+)?equity|capitaux\s+propres|situation\s+nette"),
    (r"net\s+debt|dette\s+nette", r"net\s+debt|dette\s+(?:nette|financière)|endettement"),
    (r"inventor|stocks?", r"inventor(?:y|ies)|stocks?\b|en-cours"),
    (r"receivable|créances", r"receivables?|créances"),
    (r"free\s+cash\s+flow|\bFCF\b", r"free\s+cash\s+flow|\bFCF\b|flux\s+de\s+trésorerie\s+disponible"),
    (r"operating\s+cash\s+flow|flux\s+d['’]exploitation",
     r"(?:cash\s+flows?\s+from\s+)?operating\s+(?:activities|cash\s+flow)|flux\s+(?:nets?\s+)?d['’]exploitation"),
    (r"capex|investissements", r"capital\s+expenditures?|capex|investissements|acquisitions?\s+d['’]immobilisations"),
    (r"effectif|headcount", r"effectifs?|headcounts?|salari[ée]s?|employ[ée]s?|\bETP\b|collaborateurs?"),
)
_METRIC_VOCAB_RES41 = [(re.compile(k, re.IGNORECASE), re.compile(v, re.IGNORECASE))
                       for k, v in _METRIC_VOCAB41]
_NUM_TOKEN41 = re.compile(
    r"\(?-?\d{1,3}(?:[\s\u00a0\u202f]\d{3})+(?:[.,]\d+)?\)?"   # 79 871 — groupes de trois
    r"|\(?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?"                    # 619,985
    r"|\(?-?\d+(?:[.,]\d+)?\)?")                                 # 42 / 6.6


def _metric_regex41(fact):
    """Motif reconnaissant la grandeur du fait dans un extrait, ou None si indéterminable."""
    hay = " ".join(str(getattr(fact, a, "") or "") for a in
                   ("label", "metric_canonical_id", "metric", "source_section"))
    for key, vocab in _METRIC_VOCAB_RES41:
        if key.search(hay):
            return vocab
    words = [w for w in re.split(r"[^\w’'-]+", str(getattr(fact, "label", "") or "")) if len(w) >= 4]
    return re.compile("|".join(re.escape(w) for w in words), re.IGNORECASE) if words else None


def _num41(txt):
    """Valeur numérique d'un jeton, en lisant le séparateur sur la forme du nombre."""
    t = str(txt or "").strip().replace("\u00a0", " ").replace("\u202f", " ")
    neg = t.startswith("(") and t.endswith(")")
    t = re.sub(r"[^\d.,\s-]", "", t).strip()
    if not t:
        return None
    if re.fullmatch(r"-?\d{1,3}(?:,\d{3})+(?:\.\d+)?", t):
        v = t.replace(",", "")
    elif re.fullmatch(r"-?\d{1,3}(?:\s\d{3})+(?:,\d+)?", t):
        v = t.replace(" ", "").replace(",", ".")
    else:
        v = t.replace(" ", "").replace(",", ".")
    try:
        f = float(v)
    except ValueError:
        return None
    return -abs(f) if neg else f


def _enforce_excerpt_supports_value41(facts: List["FinancialFact"]) -> int:
    """v62.13.9.4.41b — UN EXTRAIT PROUVE UN FAIT, PAS UN NOMBRE.

    Trois défauts du contre-audit du 24/09/2026 sont fermés ici, et ils avaient la même
    racine : le garde regardait le nombre et rien d'autre.
      - « 125 » était confirmé par « Chiffre d'affaires : 3125 euros », parce qu'un test
        de sous-chaîne précédait la comparaison numérique. La comparaison se fait
        désormais sur des JETONS numériques, jamais sur des caractères.
      - des stocks étaient confirmés par un extrait d'effectif : même nombre, autre
        grandeur. L'extrait doit maintenant NOMMER la grandeur du fait.
      - un extrait absent laissait la confirmation en place, le garde passant son chemin.
        L'absence d'extrait est désormais un échec explicite, pas un silence.
    Retourne le nombre de faits déclassés.
    """
    n = 0
    for f in facts or []:
        try:
            exc = str(getattr(f, "source_excerpt", "") or "").strip()
            raw = str(getattr(f, "source_value_text", "") or getattr(f, "value", "") or "").strip()
            target = _num41(raw)
            motif = ""
            if not exc:
                # v62.13.9.4.41b — l'exigence d'extrait porte sur ce qui se PRÉTEND
                # confirmé à la page. Un fait venu d'un registre — numéro d'entreprise,
                # identifiant LEI, extrait de greffe — n'a pas de page à citer : sa preuve
                # est le registre lui-même. Trois contrats de traçabilité l'ont rappelé
                # dès la première suite complète du 24/09/2026 ; les déclasser aurait été
                # une sur-correction, et c'est ce que les témoins positifs servent à voir.
                if (str(getattr(f, "proof_status", "")) == "CONFIRMED_ON_PAGE"
                        or getattr(f, "source_page", None)):
                    motif = "Aucun extrait de preuve — confirmation retirée"
            elif target is None:
                motif = ""            # valeur non numérique : ce garde ne se prononce pas
            else:
                # v62.13.9.4.41b — deux colonnes accolées (« Stocks 125 118 ») se lisent
                # soit comme un nombre à séparateur d'espace, soit comme deux colonnes.
                # On accepte les deux lectures, mais UNIQUEMENT le groupe de tête pour la
                # seconde : dans « 3 125 000 », le 125 intérieur ne confirme rien.
                # v62.13.9.4.43 — COLONNES ACCOLÉES. « 79 871 79 088 » porte deux nombres
                # français à groupes de trois ; « 450 430 » deux colonnes ; « 3 125 000 »
                # un seul nombre. Les lectures admises sont les suites contiguës de
                # groupes dont tous les groupes après le premier ont trois chiffres, et une
                # suite qui ne commence pas au premier groupe n'est admise que si le groupe
                # précédent en a trois — c'est une frontière de colonne, pas l'intérieur
                # d'un nombre. Ainsi 125 n'est jamais lu dans « 3 125 000 ».
                _cands41 = []
                for m in _NUM_TOKEN41.finditer(exc):
                    tok = m.group(0)
                    _cands41.append(_num41(tok))
                    _core = tok.strip("()")
                    if re.search(r"[\s\u00a0\u202f]", _core):
                        _groups = re.split(r"[\s\u00a0\u202f]+", _core.strip())
                        for i in range(len(_groups)):
                            if i > 0 and len(re.sub(r"\D", "", _groups[i - 1])) != 3:
                                continue
                            for j in range(i, len(_groups)):
                                if j > i and len(re.sub(r"\D", "", _groups[j])) != 3:
                                    break
                                _cands41.append(_num41(" ".join(_groups[i:j + 1])))
                ok_num = any(
                    (v == target or (target and abs(v - target) <= abs(target) * 0.005))
                    for v in _cands41 if v is not None)
                if not ok_num:
                    motif = "Extrait de preuve ne contenant pas la valeur — confirmation retirée"
                else:
                    rx = _metric_regex41(f)
                    if rx is not None and not rx.search(exc):
                        motif = ("Extrait ne nommant pas la grandeur du fait — "
                                 "égalité de nombre sans égalité de grandeur")
                    elif rx is not None:
                        # v62.13.9.4.43 — LA VALEUR VA À LA GRANDEUR QUI LA PRÉCÈDE. Sur
                        # « Inventories 125; trade receivables 110 », le 110 était servi
                        # comme des stocks parce que l'extrait nommait les stocks quelque
                        # part. La grandeur nommée juste avant la valeur doit être celle
                        # du fait ; si c'en est une autre, la valeur ne lui appartient pas.
                        _spans = []
                        for _k, _v in _METRIC_VOCAB_RES41:
                            for _mm in _v.finditer(exc):
                                _spans.append((_mm.start(), _mm.end(), _v is rx))
                        # la grandeur du fait lui-même compte aussi quand elle n'est pas
                        # dans le vocabulaire commun (« Engagement retraite ») : sinon la
                        # grandeur connue la plus proche — l'effectif de la phrase d'avant —
                        # passerait pour la sienne.
                        if not any(_sp[2] for _sp in _spans):
                            for _mm in rx.finditer(exc):
                                _spans.append((_mm.start(), _mm.end(), True))
                        _spans.sort()
                        _pos = None
                        for _mt in _NUM_TOKEN41.finditer(exc):
                            _vals = [_num41(_mt.group(0))]
                            _core = _mt.group(0).strip("()")
                            if re.search(r"[\s\u00a0\u202f]", _core):
                                _gr = re.split(r"[\s\u00a0\u202f]+", _core.strip())
                                for _i in range(len(_gr)):
                                    if _i > 0 and len(re.sub(r"\D", "", _gr[_i - 1])) != 3:
                                        continue
                                    for _j in range(_i, len(_gr)):
                                        if _j > _i and len(re.sub(r"\D", "", _gr[_j])) != 3:
                                            break
                                        _vals.append(_num41(" ".join(_gr[_i:_j + 1])))
                            if any(_x is not None and (_x == target or (target and abs(_x - target) <= abs(target) * 0.005)) for _x in _vals):
                                _pos = _mt.start()
                                break
                        if _pos is not None and _spans:
                            _before = [sp for sp in _spans if sp[1] <= _pos]
                            if _before and not _before[-1][2]:
                                motif = ("Autre grandeur nommée juste avant la valeur dans l'extrait — "
                                         "la valeur ne lui appartient pas")
            if not motif:
                continue
            if str(getattr(f, "proof_status", "")) == "CONFIRMED_ON_PAGE":
                f.proof_status = "DECLARED_UNCONFIRMED"
                f.board_safe_candidate = False
                f.board_safe_blockers = list(getattr(f, "board_safe_blockers", []) or []) + ["excerpt_does_not_prove_fact"]
            if getattr(f, "status", None) == FactStatus.FAIT:
                f.status = FactStatus.A_VERIFIER
            f.notes = list(getattr(f, "notes", []) or []) + [motif]
            n += 1
        except Exception:
            continue
    return n

def build_facts_table_from_sources(
    *,
    pappers_blocks: Optional[Dict[str, Any]] = None,
    ch_blocks: Optional[Dict[str, Any]] = None,
    gleif_blocks: Optional[Dict[str, Any]] = None,
    financial_statements_bundles: Optional[List[Any]] = None,
    financial_signal_report: Optional[Any] = None,
    financial_statements_block: Optional[str] = None,
    attachments_block: Optional[str] = None,
    lang: str = "fr",
)-> "FinancialFactsTable":
    """
    Couche 1 — Construction d'une FinancialFactsTable depuis les sources
    déterministes du pipeline.

    Cette fonction ne dépend PAS du LLM — elle se base uniquement sur les
    sources externes vérifiables. Le LLM (Couche 2) peut ajouter des faits
    complémentaires via add_facts_from_llm_output() avec status par défaut
    ESTIM_IA ou HYPOTHESE.

    Patch v16.5.72.1 (audit ChatGPT round 16) — Ajout de
    `financial_statements_block` qui contient le texte des FS extraites
    depuis les PDFs (par financial_statement_extractor v16.5.70). On y
    parse les vrais chiffres financiers (Revenue/EBIT/FCF...) qui étaient
    manquants en v16.5.72.

    Tolère toutes les entrées None.
    """
    table = FinancialFactsTable()

    # Pappers
    for fact in build_facts_from_pappers(pappers_blocks):
        table.add(fact)

    # Companies House
    for fact in build_facts_from_companies_house(ch_blocks):
        table.add(fact)

    # GLEIF
    for fact in build_facts_from_gleif(gleif_blocks, lang):
        table.add(fact)

    # Financial Statements bundles (PDFs scannés — métadonnée sections)
    for fact in build_facts_from_fs_bundles(financial_statements_bundles):
        table.add(fact)

    # v62.11 — ledger financier page-confirmé, autorité primaire lorsque
    # le texte paginé des états financiers est disponible. Le parseur legacy
    # reste un fallback pour les anciens formats mais n'est jamais mélangé au
    # ledger autoritatif (sinon un libellé voisin peut recréer un conflit).
    _proof_facts_6211 = []
    try:
        from utils.financial_proof_layer import (
            build_page_confirmed_financial_facts as _bpcff6211,
            financial_proof_summary as _fps6211,
        )
        _proof_facts_6211 = _bpcff6211(
            financial_statements_block or "", attachments_block or "", lang=lang)
        for fact in _proof_facts_6211:
            table.add(fact)
        table._financial_proof_summary = _fps6211(_proof_facts_6211)
        try:
            from utils.financial_proof_layer import detect_ocr_required_documents as _docr6211
            table._financial_proof_summary["ocr_required_documents"] = _docr6211(
                financial_statements_block or "", attachments_block or "")
        except Exception:
            table._financial_proof_summary["ocr_required_documents"] = []
    except Exception as _proof_exc6211:
        table._financial_proof_summary = {
            "proof_layer_version": "v62.11", "status": "ERROR",
            "error": f"{type(_proof_exc6211).__name__}: {str(_proof_exc6211)[:160]}",
            "confirmed_on_page": 0, "critical_confirmed_on_page": 0,
            "conflicts": 0, "current_financial_state_established": False,
        }
        _proof_facts_6211 = []

    if not _proof_facts_6211:
        # Patch v16.5.72.1 — fallback legacy : chiffres depuis le bloc FS.
        for fact in build_facts_from_fs_block(financial_statements_block):
            table.add(fact)

    # Faits documentaires page-cités (traités, annexes sociales, actes).
    for fact in build_documentary_facts_from_attachments(attachments_block):
        table.add(fact)

    # Signal financier multi-format
    for fact in build_facts_from_financial_signal_report(financial_signal_report):
        table.add(fact)

    # v62.13.9.4.43 — CONTRAT DE FAIT AU POINT DE PASSAGE OBLIGÉ : signe, nature,
    # état d'origine, prospectif, périmètre, période — appliqué à tous les producteurs
    # (couche primaire, repli, documentaire, signal, registres) AVANT la garde d'extrait.
    try:
        from utils.fact_contract42 import enforce_fact_contract42 as _efc42
        _c42 = _efc42(getattr(table, "facts", []) or [], financial_statements_block or "")
        if _c42:
            try:
                table.diag = dict(getattr(table, "diag", {}) or {})
                table.diag["fact_contract42"] = _c42
            except Exception:
                pass
    except Exception:
        pass
    # v62.13.9.4.41 — garde d'extrait : appliquée à TOUS les faits de la table,
    # quel que soit le chemin qui les a produits.
    _n41 = _enforce_excerpt_supports_value41(getattr(table, "facts", []) or [])
    if _n41:
        try:
            table.diag = dict(getattr(table, "diag", {}) or {})
            table.diag["n_facts_excerpt_mismatch"] = _n41
        except Exception:
            pass
    # v62.13.9.4.48 — RAPPROCHEMENT ARITHMÉTIQUE (point 2) : sur les faits qui ont passé le contrat
    # et la garde d'extrait. Un résultat publié qui ne vaut pas le calcul passe « à vérifier ».
    try:
        from utils.arithmetic_reconciliation48 import reconcile_facts48 as _rf48
        _r48 = _rf48(getattr(table, "facts", []) or [], lang=lang)
        if _r48.get("checked"):
            table.diag = dict(getattr(table, "diag", {}) or {})
            table.diag["arithmetic_reconciliation48"] = _r48
    except Exception:
        pass
    return table


# ─────────────────────────────────────────────────────────────────────────────
# Extraction automatique des faits depuis le texte CR
# ─────────────────────────────────────────────────────────────────────────────


# Patterns pour détecter automatiquement les faits financiers et leurs tags
# dans le texte produit par les agents LLM. Multilingue FR + EN.

# Pattern : "Revenue FY25 : 2,383 M£" ou "CA <filiale> <montant> M€"
_FINANCIAL_LABEL_PATTERN = re.compile(
    r"\b(?:"
    r"Revenue|Turnover|Net\s+sales|Sales|"
    r"Chiffre\s+d['']affaires|CA\b|"
    r"Operating\s+profit|Income\s+from\s+operations|Operating\s+income|Adjusted\s+operating\s+profit|"
    r"Résultat\s+(?:d['']exploitation|opérationnel|net|courant)|"
    r"EBITDA|EBIT\b|"
    r"Net\s+income|Net\s+profit|Net\s+loss|"
    r"Total\s+assets|Total\s+equity|"
    r"Cash\s+and\s+cash\s+equivalents|Trésorerie|"
    r"Free\s+cash\s+flow|FCF\b|"
    r"Margin|Marge\s+(?:nette|brute|opérationnelle)|"
    r"Net\s+debt|Dette\s+nette|"
    r"Dividend|Dividende|"
    r"Capex|CAPEX|Investissements?|"
    r"Stocks?|Inventories|"
    r"DSO|BFR|Working\s+capital"
    r")\b",
    re.IGNORECASE
)

# Pattern montants typiques (réutilise patterns Since v16.5.71)
_AMOUNT_INLINE_PATTERN = re.compile(
    r"[+\-]?\d{1,4}(?:[,.\s]\d{3})*(?:[.,]\d{1,3})?"
    r"\s*"
    r"(?:M€|MEUR|k€|KEUR|Md€|G€|"
    r"M\$|k\$|MGBP|MUSD|M£|"
    r"€M|£M|\$M|"
    r"%|pts|bps|"
    r"M\b|k\b|Md\b|"
    r"millions?|milliards?)?",
    re.IGNORECASE
)

# Pattern statuts taggués dans le texte CR
_STATUS_TAG_PATTERN = re.compile(
    r"\[(FAIT|REF\s*SECT\.?|ESTIM\s*IA?|HYPOTH[ÈE]SE|INCERTAIN|"
    r"À\s*V[ÉE]RIFIER|A\s*V[ÉE]RIFIER|NON\s*SOURC[ÉE]|"
    r"À\s*INVESTIGUER|À\s*ARBITRER)\]",
    re.IGNORECASE
)


def detect_status_from_tag(tag_text: str) -> FactStatus:
    """
    Convertit un tag texte ([FAIT], [NON SOURCÉ]...) en FactStatus.

    Patch v16.5.72.1 (audit ChatGPT round 16) — Bug détecté :
    après réduction 7→4 statuts, les anciens REFSECT et INCERTAIN
    référençaient `FactStatus.REF_SECT` et `FactStatus.INCERTAIN`
    qui n'existent plus → AttributeError au runtime si un tag
    [REF SECT.] ou [INCERTAIN] arrivait dans le pipeline.

    Solution : mapping rétrocompat
      - REFSECT  → FactStatus.FAIT (référence sectorielle = fait sourcé)
      - INCERTAIN → FactStatus.A_VERIFIER (cohérence DAF)
    """
    t = (tag_text.upper()
         .replace(" ", "")
         .replace(".", "")
         .replace("É", "E").replace("È", "E").replace("Ê", "E")
         .replace("À", "A").replace("Â", "A")
         .replace("Î", "I").replace("Ô", "O").replace("Û", "U"))
    mapping = {
        "FAIT": FactStatus.FAIT,
        "REFSECT": FactStatus.FAIT,           # rétrocompat — sectoriel = factuel
        "ESTIMIA": FactStatus.ESTIM_IA,
        "ESTIM": FactStatus.ESTIM_IA,
        "HYPOTHESE": FactStatus.HYPOTHESE,
        "INCERTAIN": FactStatus.A_VERIFIER,    # rétrocompat — INCERTAIN équiv. À VÉRIFIER
        "AVERIFIER": FactStatus.A_VERIFIER,
        "NONSOURCE": FactStatus.NON_SOURCE,
    }
    return mapping.get(t, FactStatus.NON_SOURCE)


# ─────────────────────────────────────────────────────────────────────────────
# Construction de la table de traçabilité
# ─────────────────────────────────────────────────────────────────────────────



def is_visible_fact(obj) -> bool:
    """Filtre de visibilité partagé, fail-closed dès qu'une gouvernance existe.

    Une row legacy sans métadonnée reste visible. Si ``allowed_uses``,
    ``visible_fact`` ou ``unresolved_value`` est présent, le type et la forme
    doivent être valides ; une sérialisation partielle ou stringifiée ne doit
    jamais promouvoir un fait diagnostics-only.
    """
    governance_keys = {"allowed_uses", "visible_fact", "unresolved_value"}

    def _uses(value, governed: bool):
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            if not all(isinstance(x, str) for x in value):
                return None
            return [x.strip().lower() for x in value if x.strip()]
        # Les strings JSON, listes imprimées et séparateurs ad hoc sont
        # ambigus : seul un code d'usage simple est accepté.
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return []
            if any(ch in s for ch in "[]{};,\"") or " " in s:
                return None
            return [s.lower()]
        return None if governed else []

    try:
        if isinstance(obj, dict):
            governed = any(k in obj for k in governance_keys)
            if not governed:
                return True

            uses = _uses(obj.get("allowed_uses", None), True)
            if uses is None or "diagnostics" in set(uses):
                return False

            if "visible_fact" in obj:
                vf = obj.get("visible_fact")
                if not isinstance(vf, bool):
                    return False
                if vf is False:
                    return False

            if "unresolved_value" in obj:
                unres = obj.get("unresolved_value")
                if unres is None:
                    pass
                elif not isinstance(unres, dict):
                    return False
                else:
                    # Un objet unresolved doit porter une sémantique de
                    # visibilité explicite et booléenne ; sinon il reste caché.
                    if set(unres) and "visible_fact" not in unres:
                        return False
                    uvf = unres.get("visible_fact", None)
                    if uvf is not None and not isinstance(uvf, bool):
                        return False
                    if uvf is not True:
                        return False
            return True

        governed = any(hasattr(obj, k) for k in governance_keys)
        if not governed:
            return True
        uses = _uses(getattr(obj, "allowed_uses", None), True)
        if uses is None or "diagnostics" in set(uses):
            return False
        if hasattr(obj, "visible_fact"):
            vf = getattr(obj, "visible_fact")
            if not isinstance(vf, bool) or vf is False:
                return False
        if hasattr(obj, "unresolved_value"):
            unres = getattr(obj, "unresolved_value")
            if unres is None:
                pass
            elif not isinstance(unres, dict):
                return False
            else:
                if set(unres) and "visible_fact" not in unres:
                    return False
                uvf = unres.get("visible_fact", None)
                if uvf is not None and not isinstance(uvf, bool):
                    return False
                if uvf is not True:
                    return False
        return True
    except Exception:
        return False


@dataclass
class FinancialFactsTable:
    """
    Table de traçabilité complète des faits financiers utilisés dans
    le livrable.

    Attributs :
        facts                  : liste de FinancialFact
        n_facts_total          : nombre total
        n_facts_solid          : nombre marqués FAIT ou REF_SECT
        n_facts_estimate       : nombre marqués ESTIM/HYPOTHESE/INCERTAIN/À_VÉRIFIER
        n_facts_unsourced      : nombre marqués NON_SOURCE
        traceability_score     : 0-100, ratio (solid + estimate * 0.5) / total
    """
    facts: List[FinancialFact] = field(default_factory=list)

    @property
    def n_facts_total(self) -> int:
        return len(self.facts)

    @property
    def n_page_confirmed(self) -> int:
        return sum(1 for f in self.facts
                   if str(getattr(f, "proof_status", "") or "") == "CONFIRMED_ON_PAGE")

    @property
    def n_critical_page_confirmed(self) -> int:
        try:
            from utils.financial_proof_layer import CRITICAL_METRIC_IDS
            return sum(1 for f in self.facts
                       if str(getattr(f, "proof_status", "") or "") == "CONFIRMED_ON_PAGE"
                       and str(getattr(f, "metric_canonical_id", "") or "") in CRITICAL_METRIC_IDS)
        except Exception:
            return 0

    def proof_summary(self) -> Dict[str, Any]:
        private = dict(getattr(self, "_financial_proof_summary", {}) or {})
        try:
            from utils.financial_proof_layer import financial_proof_summary
            out = financial_proof_summary(self.facts)
            if private.get("ocr_required_documents"):
                out["ocr_required_documents"] = list(private.get("ocr_required_documents") or [])
            if private.get("status") == "ERROR":
                out["parser_error"] = private.get("error")
            return out
        except Exception:
            return private

    @staticmethod
    def _fact_is_brief_only(f) -> bool:
        """B.1.3.1 (bloquant 2 audit) — un fait est « brief-only » s'il vient
        du brief (source_doc='Brief', cas canonique) ou porte déjà le blocker
        brief_only. Ces faits restent VISIBLES mais ne comptent JAMAIS comme
        FAITS certifiants dans le score de traçabilité."""
        if (getattr(f, "source_doc", "") or "").strip().lower() == "brief":
            return True
        return "brief_only" in [str(b).lower() for b in
                                (getattr(f, "board_safe_blockers", None) or [])]

    @property
    def n_facts_brief(self) -> int:
        """B.1.3.1 — chiffres déclaratifs du brief (visibles, non certifiants)."""
        return sum(1 for f in self.facts
                   if f.is_financial_value() and self._fact_is_brief_only(f))

    @property
    def n_facts_solid(self) -> int:
        # B.1.3.1 — les faits du brief ne sont PLUS des FAITS certifiants :
        # « Traçabilité 100/100, 4 FAITS » sur du déclaratif pur (repro audit)
        # était exactement la confusion que B.1 devait supprimer.
        return sum(1 for f in self.facts
                   if f.is_solid() and not self._fact_is_brief_only(f))

    @property
    def n_facts_estimate(self) -> int:
        return sum(1 for f in self.facts if f.is_estimate())

    @property
    def n_facts_unsourced(self) -> int:
        return sum(1 for f in self.facts if f.status == FactStatus.NON_SOURCE)

    @property
    def n_financial_value_facts(self) -> int:
        """
        Patch v16.5.72.1 (audit ChatGPT round 16) — Nombre de faits qui
        sont de vrais chiffres financiers (CA, EBITDA, FCF...) et pas
        juste de l'identité société (LEI, Company Number).
        """
        return sum(1 for f in self.facts if f.is_financial_value())

    def has_financial_value_facts(self) -> bool:
        """
        True si la table contient AU MOINS un vrai chiffre financier
        (pas seulement de l'identité société).

        Patch v16.5.72.1 — Utilisé pour décider si "Signaux financiers
        exploitables" doit être affiché. UK Company Number + LEI seuls
        ne suffisent plus.
        """
        return self.n_financial_value_facts > 0

    def has_in_perimeter_financial_value_facts(self) -> bool:
        """
        B.1.1 (audit gate B.2, P0) — Variante EN PÉRIMÈTRE : True si au moins
        un vrai chiffre financier n'est PAS marqué MISMATCH par la couche de
        preuve. Un fait hors périmètre (compte social standalone présenté pour
        un groupe — cas dossier industriel (composants) v5) reste VISIBLE dans la table mais ne doit
        pas faire afficher « Signaux financiers exploitables ».
        Les faits non annotés (perimeter_match vide : B.1 non appliqué,
        table fallback) comptent comme avant — dégradation douce, pas de
        faux négatif si la couche de preuve n'a pas tourné.
        """
        return any(
            f.is_financial_value()
            and (getattr(f, "perimeter_match", "") or "") != "MISMATCH"
            for f in self.facts
        )

    def financial_values_brief_only(self) -> bool:
        """B.1.3 — True si TOUS les chiffres financiers en périmètre viennent
        du brief (source_doc='Brief') : le statut doit alors dire « issus du
        brief uniquement », jamais « Signaux financiers exploitables »."""
        vals = [f for f in self.facts
                if f.is_financial_value()
                and (getattr(f, "perimeter_match", "") or "") != "MISMATCH"]
        if not vals:
            return False
        return all((getattr(f, "source_doc", "") or "").strip().lower()
                   == "brief" for f in vals)

    @property
    def traceability_score(self) -> int:
        """
        Score de traçabilité 0-100.
        - FAIT/REF_SECT comptent pleinement (1.0)
        - ESTIM/HYPOTHESE/INCERTAIN/À_VÉRIFIER comptent à moitié (0.5)
        - NON_SOURCE pénalise (0.0)
        """
        if self.n_facts_total == 0:
            return 0
        # B.1.3.1 — le déclaratif du brief pèse comme une estimation (0.5),
        # jamais comme un fait sourcé (1.0) : 4 faits brief-only → 50/100,
        # pas 100/100.
        weighted = (self.n_facts_solid
                    + 0.5 * (self.n_facts_estimate + self.n_facts_brief))
        score = int(min(100, 100 * weighted / self.n_facts_total))
        # v17.1.0-B2.3-F.4.3 — Cap de cohérence : on n'affiche jamais 100/100
        # board-safe quand une contradiction critique subsiste (EBITDA double
        # statut) ou qu'un poste board est dérivé (CALCUL). Plafond Grade B (80).
        if getattr(self, "_coherence_capped", False):
            score = min(score, 80)
        return score

    # v17.1.0-B2.3-F.4.3 — Cap de cohérence : quand une contradiction critique
    # subsiste (ex. EBITDA présenté chiffré ici / non communiqué là), la table ne
    # doit JAMAIS afficher 100/100 board-safe. Activé par le moteur (gate EBITDA)
    # ou par auto-détection d'un poste dérivé en zone board. Défaut : inactif.
    _coherence_capped: bool = field(default=False, repr=False)
    _coherence_reasons: List[str] = field(default_factory=list, repr=False)

    def flag_coherence_issue(self, reason: str = "") -> None:
        """Signale une incohérence critique non résolue → plafonne la traçabilité.
        Fail-open : n'altère aucune valeur, ne fait que marquer."""
        self._coherence_capped = True
        if reason and reason not in self._coherence_reasons:
            self._coherence_reasons.append(reason)

    def add(self, fact: FinancialFact) -> None:
        """Ajoute un fait à la table (déduplication par label si même valeur).

        v17.1.0-B2.3-F.4.3 — Un fait dont la VALEUR est dérivée/calculée (source
        « CALCUL (… − …) ») est rétrogradé FAIT → À VÉRIFIER + note : il ne compte
        plus comme FAIT plein (donc plus de 100/100 sur un agrégat dérivé) et n'est
        plus affiché ✅ FAIT board-safe. Doctrine : on ne touche PAS la valeur, on
        corrige seulement le STATUT trompeur."""
        try:
            if fact.status == FactStatus.FAIT and fact.is_derived():
                fact.status = FactStatus.A_VERIFIER
                note = ("[CALCUL — poste dérivé, non board-safe : à vérifier "
                        "contre l'état financier primaire]")
                if note not in (fact.notes or []):
                    fact.notes = list(fact.notes or []) + [note]
                self.flag_coherence_issue("poste financier dérivé (CALCUL) en table")
        except Exception:
            pass
        for existing in self.facts:
            if existing.label == fact.label and existing.value == fact.value:
                return  # déjà présent, skip
        self.facts.append(fact)

    def sort_by_scope(self) -> None:
        """B1.1-02 — Réordonne les faits par périmètre (consolidé avant social)
        de façon STABLE, pour que le rendu deck (qui itère `.facts`) montre le
        consolidé en premier dès qu'il existe."""
        self.facts.sort(key=lambda f: _scope_rank(getattr(f, "scope", None)))

    @property
    def n_facts_narrative(self) -> int:
        """B.1.3.5 — nombre d'hypothèses narratives (source « Narratif agents »)."""
        return sum(1 for f in self.facts
                   if str(getattr(f, "source_doc", "") or "").startswith("Narratif agents"))

    def to_markdown_table(self, lang: str = "fr", max_rows: int = 25,
                          analysis_context=None, conflicts=None) -> str:
        """
        Rendu markdown de la table — pour DOCX et PPTX.

        Patch v16.5.72.2 (audit ChatGPT round 17) — Séparation en 2 zones :
          A. Faits financiers utilisés (Revenue, EBIT, FCF, etc.)
          B. Métadonnées d'identification (Company Number, LEI, sections)
        Évite le mélange "Revenue 2,383" et "UK Company Number 03458224"
        dans la même grille.

        M6-B B.1 (v17.4.0, E7) — rendu MINIMAL de la couche de preuve
        (la propagation riche → B.4) :
          · ⛔ sur un fait MISMATCH (montré mais EXCLU du score) + note ;
          · ⚡ sur un fait en conflit + messages des conflits détectés ;
          · bannière du contexte d'analyse (inféré, affiché — jamais silencieux).
        `analysis_context` et `conflicts` sont OPTIONNELS (rétrocompat totale).

        Args:
            lang : "fr" ou "en"
            max_rows : nombre max de lignes affichées par zone
            analysis_context : patches.analysis_context.AnalysisContext | None
            conflicts : liste de patches.fact_conflict.FactConflict | None
        """
        if not self.facts:
            return ""
        # B.1.3.56 (scope F) — les faits diagnostics-only (ex. valeur de
        # registre non résolue) ne sont JAMAIS rendus dans les tables
        # visibles ; ils restent dans self.facts pour les exports de diagnostic.
        _render_facts56 = [f for f in self.facts
                           if "diagnostics" not in (getattr(f, "allowed_uses", []) or [])]
        if not _render_facts56:
            return ""

        # Patch v16.5.72.2 — Séparation déterministe via is_financial_value()
        financial_facts = [f for f in _render_facts56 if f.is_financial_value()]
        identity_facts = [f for f in _render_facts56 if not f.is_financial_value()]
        # B.1.3.5 (audit dossier industriel (composants) P1) — les montants issus du NARRATIF des
        # agents (BFR estimé -2/-3 M€…) ne sont PAS des faits de preuve :
        # zone C dédiée « Hypothèses narratives », exclus de A. Rien n'est
        # supprimé — la frontière fait-de-preuve / hypothèse-d'analyse est
        # rendue VISIBLE.
        narrative_facts = [f for f in financial_facts
                           if str(getattr(f, "source_doc", "") or "").startswith("Narratif agents")]
        if narrative_facts:
            financial_facts = [f for f in financial_facts if f not in narrative_facts]

        # Trier chaque zone : périmètre d'abord (consolidé avant social — B1.1-02),
        # puis statut (FAIT avant estimations).
        order = {
            FactStatus.FAIT: 0,
            FactStatus.ESTIM_IA: 1,
            FactStatus.HYPOTHESE: 2,
            FactStatus.A_VERIFIER: 3,
            FactStatus.NON_SOURCE: 4,
        }
        financial_facts.sort(key=lambda f: (_scope_rank(getattr(f, "scope", None)),
                                            order.get(f.status, 99)))
        identity_facts.sort(key=lambda f: (_scope_rank(getattr(f, "scope", None)),
                                           order.get(f.status, 99)))

        if lang == "fr":
            headers = ["", "Fait", "Valeur", "Source", "Page", "Statut"]
            _brief_seg = (f", {self.n_facts_brief} du brief (non certifiés)"
                          if self.n_facts_brief else "")
            if self.n_facts_brief and self.financial_values_brief_only():
                # B.1.3.1 (bloquant 2 audit) — table 100 % déclarative : le
                # titre ne CERTIFIE pas, il qualifie.
                title = (
                    f"📋 FAITS FINANCIERS UTILISÉS — Traçabilité indicative : "
                    f"chiffres du brief uniquement, non certifiés "
                    f"({self.n_facts_brief} fait(s) déclaratif(s), "
                    f"score {self.traceability_score}/100 non board-safe)"
                )
            else:
                title = (
                    f"📋 FAITS FINANCIERS UTILISÉS — Traçabilité "
                    f"({self.traceability_score}/100, {self.n_facts_solid} FAITS, "
                    f"{self.n_facts_estimate} estimations{_brief_seg}, "
                    f"{self.n_facts_unsourced} non sourcés)"
                )
            section_a_title = "A. Faits financiers"
            section_b_title = "B. Métadonnées de traçabilité (identité société, sources)"
            section_c_title = ("C. Hypothèses narratives (agents) — à vérifier, "
                               "non probantes, hors preuve")
        else:
            headers = ["", "Fact", "Value", "Source", "Page", "Status"]
            _brief_seg = (f", {self.n_facts_brief} from brief (not certified)"
                          if self.n_facts_brief else "")
            if self.n_facts_brief and self.financial_values_brief_only():
                title = (
                    f"📋 FINANCIAL FACTS USED — Indicative traceability: "
                    f"brief figures only, not certified "
                    f"({self.n_facts_brief} declarative fact(s), "
                    f"score {self.traceability_score}/100 not board-safe)"
                )
            else:
                title = (
                    f"📋 FINANCIAL FACTS USED — Traceability "
                    f"({self.traceability_score}/100, {self.n_facts_solid} FACTS, "
                    f"{self.n_facts_estimate} estimates{_brief_seg}, "
                    f"{self.n_facts_unsourced} unsourced)"
                )
            section_a_title = "A. Financial facts"
            section_b_title = "B. Traceability metadata (company identity, sources)"
            section_c_title = ("C. Narrative hypotheses (agents) — to verify, "
                               "non-evidentiary")

        lines = [title, ""]

        # ── M6-B B.1 (E7) — bannière du contexte d'analyse (jamais silencieux)
        if analysis_context is not None:
            try:
                _ctx_mode = getattr(analysis_context, "mode", "")
                _ctx_target = getattr(analysis_context, "target_entity", "") or "—"
                _ctx_level = getattr(analysis_context, "target_perimeter_level", "")
                _ctx_from = getattr(analysis_context, "inferred_from", "")
                _ctx_conf = getattr(analysis_context, "inference_confidence", "")
                _ctx_ovr = getattr(analysis_context, "user_override", False)
                if lang == "fr":
                    _ovr_txt = " · surchargé par l'utilisateur" if _ctx_ovr else ""
                    lines.append(
                        f"🧭 **Contexte d'analyse** : mode={_ctx_mode} · "
                        f"cible={_ctx_target} · niveau={_ctx_level} · "
                        f"inféré de {_ctx_from} (confiance {_ctx_conf}){_ovr_txt}")
                else:
                    _ovr_txt = " · user-overridden" if _ctx_ovr else ""
                    lines.append(
                        f"🧭 **Analysis context**: mode={_ctx_mode} · "
                        f"target={_ctx_target} · level={_ctx_level} · "
                        f"inferred from {_ctx_from} ({_ctx_conf} confidence){_ovr_txt}")
                lines.append("")
            except Exception:
                pass

        # ── Zone A — Faits financiers ────────────────────────────────────────
        if financial_facts:
            lines.append(f"### {section_a_title}")
            lines.append("")
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("|" + "|".join(["---"] * len(headers)) + "|")
            for f in financial_facts[:max_rows]:
                r = f.to_row_dict()
                # B.1.3.16 (dossier industriel (composants) run 1 : « ⛔ ✅ FAIT » juxtaposé) — statut
                # UNIFIÉ : hors périmètre REMPLACE icône et statut ; le ⚡
                # conflit reste cumulable. Période au label (B.1.3.14 CR
                # Zone A → généralisée ici : le deck parse CETTE table).
                _pm16 = (getattr(f, "perimeter_match", "") == "MISMATCH")
                _cf16 = "⚡" if getattr(f, "conflict_group_id", "") else ""
                _lbl16 = _localize_metric_label(r["label"], lang)
                if str(r.get("period") or "").strip():
                    _lbl16 = f"{_lbl16} ({str(r['period']).strip()})"
                _av16 = (getattr(f, "status", None) == FactStatus.A_VERIFIER)
                _status16 = (
                    (("HORS PÉRIMÈTRE — exclu du score"
                      + (" · À VÉRIFIER (source faible)" if _av16 else ""))
                     if lang == "fr" else
                     ("OUT OF PERIMETER — excluded from score"
                      + (" · TO VERIFY (weak source)" if _av16 else "")))
                    if _pm16 else
                    _localize_fact_status(r["status"], lang)
                    # B.1.3.1 (bloquant 2 audit) — un chiffre du brief ne
                    # s'affiche JAMAIS comme un FAIT nu.
                    + ((" — brief non certifié" if lang == "fr"
                        else " — brief, not certified")
                       if r.get("brief_only") else ""))
                lines.append("| " + " | ".join([
                    ("⛔" if _pm16 else r["icon"]) + _cf16,
                    _lbl16[:46], r["value"][:30],
                    _localize_source(r["source"], lang)[:50], str(r["page"]),
                    _status16,
                ]) + " |")
            if len(financial_facts) > max_rows:
                n_more = len(financial_facts) - max_rows
                if lang == "fr":
                    lines.append(f"\n*… {n_more} faits financiers supplémentaires non affichés.*")
                else:
                    lines.append(f"\n*… {n_more} additional financial facts not shown.*")
            # v17.1-A3 — Note de périmètre visible pour les agents : empêche de
            # lire un agrégat social standalone (Pappers) comme un chiffre groupe.
            _social = [f for f in financial_facts
                       if getattr(f, "scope", "") == "SOCIAL_STANDALONE"]
            if _social:
                if lang == "fr":
                    lines.append(
                        "\n> ⚠️ **Périmètre** : les faits issus de Pappers sont des "
                        "**comptes SOCIAUX standalone** — usage **narratif uniquement**, "
                        "**non représentatifs du consolidé groupe**. Ne pas les utiliser "
                        "comme chiffre groupe ni comme base d'alerte juridique.")
                else:
                    lines.append(
                        "\n> ⚠️ **Scope**: Pappers-sourced facts are **standalone "
                        "statutory accounts** — **narrative use only**, **not representative "
                        "of the consolidated group**. Do not use as group figures or as a "
                        "basis for legal alerts.")
            # ── M6-B B.1 (E7) — hors-périmètre : MONTRÉ mais EXCLU du score ──
            _mismatch = [f for f in financial_facts
                         if getattr(f, "perimeter_match", "") == "MISMATCH"]
            if _mismatch:
                if lang == "fr":
                    lines.append(
                        f"\n> ⛔ **Hors périmètre** : {len(_mismatch)} fait(s) ne "
                        "décrivent pas le périmètre d'analyse — **montrés mais "
                        "exclus du score** (règle B.1 : un fait hors-périmètre "
                        "n'alimente pas le signal financier).")
                else:
                    lines.append(
                        f"\n> ⛔ **Out of perimeter**: {len(_mismatch)} fact(s) do "
                        "not describe the analysis perimeter — **shown but "
                        "excluded from the score** (B.1 rule: an out-of-perimeter "
                        "fact does not feed the financial signal).")
            # ── M6-B B.1 (E7) — conflits détectés (affichage riche → B.4c) ───
            if conflicts:
                try:
                    _head = ("\n> ⚡ **Tensions détectées entre les chiffres** :"
                             if lang == "fr"
                             else "\n> ⚡ **Tensions detected between figures**:")
                    lines.append(_head)
                    for _c in list(conflicts)[:6]:
                        _msg = getattr(_c, "user_visible_message", "") or ""
                        if _msg:
                            lines.append(f"> • {_msg}")
                except Exception:
                    pass
            lines.append("")

        # ── Zone B — Métadonnées ─────────────────────────────────────────────
        if identity_facts:
            lines.append(f"### {section_b_title}")
            lines.append("")
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("|" + "|".join(["---"] * len(headers)) + "|")
            for f in identity_facts[:max_rows]:
                r = f.to_row_dict()
                lines.append("| " + " | ".join([
                    r["icon"],
                    _localize_metric_label(r["label"], lang)[:40], r["value"][:30],
                    _localize_source(r["source"], lang)[:50], str(r["page"]),
                    _localize_fact_status(r["status"], lang),
                ]) + " |")

        if narrative_facts:
            lines.append("")
            lines.append(f"### {section_c_title}")
            lines.append("")
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("|" + "|".join(["---"] * len(headers)) + "|")
            for f in narrative_facts[:max_rows]:
                r = f.to_row_dict()
                lines.append("| " + " | ".join([
                    r["icon"],
                    _localize_metric_label(r["label"], lang)[:40], r["value"][:30],
                    _localize_source(r["source"], lang)[:50], str(r["page"]),
                    _localize_fact_status(r["status"], lang),
                ]) + " |")

        return "\n".join(lines)

    def to_diag_dict(self) -> Dict[str, Any]:
        """Pour traçabilité dans diagnostics_ia.csv."""
        return {
            "n_facts_total": self.n_facts_total,
            "n_facts_solid": self.n_facts_solid,
            "n_facts_estimate": self.n_facts_estimate,
            "n_facts_unsourced": self.n_facts_unsourced,
            "traceability_score": self.traceability_score,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Helper pour wording cohérent "documents financiers détectés"
# ─────────────────────────────────────────────────────────────────────────────


def build_financial_documents_status_message(
    *,
    has_some_financial_signal: bool,
    has_attachments_but_no_fs: bool,
    attachments_count: int,
    n_pdfs_with_fs: int = 0,
    financial_signal_score: Optional[int] = None,
    brief_facts_only: bool = False,
    n_page_confirmed: Optional[int] = None,  # B.1.3.8 — fidélité-page connue
    lang: str = "fr",
    n_unextractable: int = 0,  # B.1.3.23 P2-I' — scans sans OCR déclarés
) -> str:
    if has_some_financial_signal and not attachments_count:
        # B.1.3.5 (run dossier industriel (composants)) — « signaux détectés dans les 0 pièce(s) »
        # était sémantiquement faux : à zéro pièce, on le DIT, quelle que
        # soit la langue.
        return ("📋 Aucune pièce financière jointe — aucun signal financier "
                "issu de pièces. Chiffres disponibles : brief uniquement "
                "(non certifiés)."
                if lang == "fr" else
                "📋 No financial attachment provided — no attachment-based "
                "financial signal. Available figures: brief only (not "
                "certified).")
    """
    Construit un message de statut documents financiers cohérent.

    Patch v16.5.72 (audit ChatGPT round 14) — Le bug v16.5.71.5 :
    le rapport pouvait dire à la fois "18 PJ attachées" et "aucune pièce
    financière n'a été attachée". Contradiction structurelle qui mine
    la crédibilité.

    Solution : 4 messages clairs selon la cascade Source Quality :
      Cas A — Financial Statements PDF détectés et lus (FS structurés)
      Cas B — Documents attachés avec signal financier solide multi-format
      Cas C — Documents attachés mais signal financier non détecté
      Cas D — Aucun document attaché
    """
    if lang == "fr":
        if n_pdfs_with_fs > 0:
            return (
                f"📊 États financiers structurés détectés dans "
                f"{n_pdfs_with_fs} PDF(s) — Income Statement, Balance Sheet, "
                f"Cash Flow et Notes extraits."
            )
        if brief_facts_only:
            # B.1.3 (audit dossier anglophone coté) — les chiffres existent mais viennent du
            # BRIEF : le dire honnêtement, sans « exploitables » trompeur.
            _pj = (f"{attachments_count} pièce(s) jointe(s) fournie(s) — "
                   f"aucune pièce comptable exploitable reconnue. "
                   if attachments_count else "")
            return (f"📝 {_pj}Chiffres financiers issus du brief uniquement — "
                    f"non sourcés indépendamment (non board-safe).")
        if has_some_financial_signal:
            score_str = (
                f" (score {financial_signal_score}/100)"
                if financial_signal_score is not None else ""
            )
            _scan23 = (f" Dont {n_unextractable} pièce(s) non exploitable(s) "
                       f"par extraction texte (scan sans OCR probable)."
                       if n_unextractable else "")
            if n_page_confirmed == 0:
                return (
                    f"📋 Signaux d'apparence financière détectés dans "
                    f"{attachments_count} pièce(s){score_str} — NON exploitables "
                    f"comme faits : 0 confirmé à la page citée." + _scan23)
            return (
                f"📋 Signaux financiers exploitables détectés dans les "
                f"{attachments_count} pièce(s) jointe(s){score_str} — "
                f"chiffres comptables, ratios et indicateurs identifiés."
            )
        if has_attachments_but_no_fs:
            return (
                f"⚠️ {attachments_count} pièce(s) jointe(s) attachée(s) mais "
                f"signal financier non détecté — extraction insuffisante. "
                f"Analyse en mode prudence."
            )
        return "ℹ️ Aucune pièce financière n'a été attachée à la session."
    else:
        if n_pdfs_with_fs > 0:
            return (
                f"📊 Structured financial statements detected in "
                f"{n_pdfs_with_fs} PDF(s) — Income Statement, Balance Sheet, "
                f"Cash Flow and Notes extracted."
            )
        if brief_facts_only:
            # B.1.3 (dossier anglophone coté audit) — figures exist but come from the BRIEF:
            # say so honestly, no misleading "exploitable signals".
            _pj = (f"{attachments_count} attachment(s) provided — "
                   f"no exploitable accounting document recognised. "
                   f"Financial-looking fragments may appear in layer 1 "
                   f"but are NOT used in the primary proof table. "
                   if attachments_count else "")
            return (f"📝 {_pj}Financial figures from the brief only — "
                    f"not independently sourced (not board-safe).")
        if has_some_financial_signal:
            score_str = (
                f" (score {financial_signal_score}/100)"
                if financial_signal_score is not None else ""
            )
            if n_page_confirmed == 0:
                # B.1.3.8 (audit #5) — « exploitable » réservé aux faits
                # utilisables : signal détecté ≠ fait exploitable.
                return (
                    f"📋 Financial-looking signals detected in "
                    f"{attachments_count} attachment(s){score_str} — NOT "
                    f"exploitable as facts: 0 confirmed on cited page.")
            return (
                f"📋 Exploitable financial signals detected in "
                f"{attachments_count} attachment(s){score_str} — "
                f"accounting figures, ratios and indicators identified."
            )
        if has_attachments_but_no_fs:
            return (
                f"⚠️ {attachments_count} attachment(s) provided but no "
                f"financial signal detected — insufficient extraction. "
                f"Analysis in caution mode."
            )
        return "ℹ️ No financial attachment was provided in this session."


__all__ = [
    "FactStatus",
    "FinancialFact",
    "FinancialFactsTable",
    "STATUS_ICON",
    "detect_status_from_tag",
    "build_financial_documents_status_message",
    # Couche 1 — Extracteurs déterministes (Since v16.5.72)
    "build_facts_from_pappers",
    "build_facts_from_companies_house",
    "build_facts_from_gleif",
    "build_facts_from_fs_bundles",
    "build_facts_from_fs_block",  # Since v16.5.72.1 (audit round 16)
    "build_facts_from_financial_signal_report",
    "build_facts_table_from_sources",
]
