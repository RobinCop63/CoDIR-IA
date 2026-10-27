"""
CoDIR IA — Pappers enrichment tool — v16.5.67
Enrichit le contexte de chaque agent avec les données officielles Pappers.fr
(INSEE, INPI, BODACC) sur les entreprises citées dans le brief.

Architecture :
  1. Extraction SIREN directe depuis le brief (priorité absolue, sans crédit)
  2. Si pas de SIREN : pré-filtre Claude (haiku) + fallback regex
  3. Hiérarchie multi-entités :
     - Entité principale : fiche complète + comptes si contexte financier
     - Entités secondaires : fiche résumée uniquement (sans comptes)
  4. Deux blocs de sortie : full (Finance/DG/Stratégie/Synthèse) et summary (Marketing/Commercial/SC)
  5. Cache disque JSON avec TTL différencié par type de donnée
  6. lru_cache L1 intra-session en plus du cache disque L2

Niveaux de confiance :
  SIREN_DIRECT  > CLAUDE > FALLBACK_REGEX

Nouveautés v16.5.52 :
  - PappersCache : cache disque avec TTL différencié (identité 7j, procédures 1j, comptes 30j)
  - _PAPPERS_SCOPE : mapping rôle → full|summary
  - _format_fiche(scope) : deux formats de sortie
  - _detect_primary_entity() : hiérarchie multi-entités par fréquence de mention
  - build_pappers_blocks() : génère full + summary + meta, entité principale identifiée
  - confirmed_entity : override utilisateur respecté en priorité absolue

Nouveautés v16.5.52.1 :
  - CONFIDENCE_USER_CONFIRMED : niveau distinct entre SIREN_DIRECT et CLAUDE
    (nom confirmé par l'utilisateur ≠ SIREN à 9 chiffres)
  - TTL procédures collectives réellement séparé : cache proc_{siren} 24h,
    _fetch_proc_fresh() pour refresh ciblé sans refaire la fiche entière
  - Fusion proc fraîche dans fiche cachée si proc expirée
  - Supply Chain reçoit le bloc summary directement (voir codir_engine.py)

Nouveautés v16.5.55 :
  - PappersResolutionLog : objet de traçabilité audit-ready (3.1 + 3.4 fusionnés)
    → chemin réel, source, SIREN utilisé, cache_hit, tokens injectés, timestamps
  - _detect_primary_entity : pondération sémantique (champ Société ×3, confirmed ×max)
    → résout les briefs "Nous analysons X face à Y où Y est plus mentionné"
  - SUMMARY_FIELDS : contrat figé du bloc summary — liste immuable de champs
    → empêche la dérive "summary = full déguisé" sur les futures versions
  - PappersCache : fallback corruption JSON + purge automatique TTL expiré
    → robustesse accès concurrent et fichier corrompu
  - build_pappers_blocks retourne "resolution_log" dans son dict de résultat
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional  # Any, Dict : hotfix B1.3.62.10.1 (F821)

import requests

# ── Objet de résolution audit-ready ──────────────────────────────────────────

@dataclass
class PappersResolutionLog:
    """
    Trace complète et immuable du chemin de résolution Pappers pour une session.
    Utilisé pour l'audit, le debug, la démo et la mesure de coût token.

    Champs :
      input_preview    : début du brief (max 120 chars)
      path             : SIREN_DIRECT | USER_CONFIRMED | CLAUDE | FALLBACK_REGEX
      source           : BRIEF_SIREN | UI_CONFIRM | CLAUDE_EXTRACT | REGEX
      siren_used       : SIREN effectivement envoyé à Pappers (ou "")
      primary_name     : raison sociale de l'entité principale (ou "")
      secondaries      : liste des entités secondaires
      fallback_used    : True si Claude a échoué et regex a pris le relais
      cache_hit        : True si fiche servie depuis le cache disque
      cache_age_h      : âge du cache en heures (None si pas de cache)
      contexte_fin     : True si contexte financier détecté
      tokens_est_full  : estimation tokens bloc full (len/4)
      tokens_est_summary : estimation tokens bloc summary (len/4)
      entities_not_found : entités non trouvées dans Pappers
      timestamp        : ISO 8601 UTC
    """
    input_preview:       str       = ""
    path:                str       = ""
    source:              str       = ""
    siren_used:          str       = ""
    primary_name:        str       = ""
    secondaries:         list      = field(default_factory=list)
    fallback_used:       bool      = False
    cache_hit:           bool      = False
    cache_age_h:         Optional[float] = None
    contexte_fin:        bool      = False
    tokens_est_full:     int       = 0
    tokens_est_summary:  int       = 0
    entities_not_found:  list      = field(default_factory=list)
    # v62.8 — identité explicite du brief immuable. Un SIREN conservé en
    # session/UI peut être obsolète ; il est tracé mais ne peut pas remplacer
    # le SIREN saisi dans le brief courant.
    authoritative_siren: str       = ""
    identity_conflict:    bool      = False
    conflicting_confirmed_entity: str = ""
    pappers_credits_est: float     = 0.0   # estimation crédits consommés (calculée par pappers_sessions)
    # v16.5.62 — Objets métier pour le routeur company_profile
    # Ces champs portent les données Pappers structurées afin que le moteur
    # puisse les passer à detect_profile() sans requêter Pappers à nouveau.
    # Ils sont EXCLUS de to_dict() pour ne pas alourdir les logs JSON.
    fiche:               dict      = field(default_factory=dict, repr=False)
    comptes:             dict      = field(default_factory=dict, repr=False)
    timestamp:           str       = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict:
        """Export JSON-safe : exclut fiche/comptes (volumineux) des logs."""
        d = asdict(self)
        d.pop("fiche", None)
        d.pop("comptes", None)
        return d

    def summary_line(self) -> str:
        """Ligne de log synthétique pour les logs applicatifs."""
        return (
            f"path={self.path} | source={self.source} | siren={self.siren_used or 'n/a'} | credits≈{self.pappers_credits_est}"
            f" | primary={self.primary_name or 'n/a'} | cache={self.cache_hit}"
            f" | fallback={self.fallback_used} | tokens_full≈{self.tokens_est_full}"
            f" | tokens_summary≈{self.tokens_est_summary}"
        )


# ── Config ────────────────────────────────────────────────────────────────────
PAPPERS_BASE_URL = "https://api.pappers.fr/v2"
_REQUEST_TIMEOUT = 8
_MAX_ENTITIES    = 3
_CACHE_SIZE      = 32

# Niveaux de confiance du matching
CONFIDENCE_SIREN_DIRECT   = "SIREN_DIRECT"    # SIREN 9 chiffres saisi ou détecté
CONFIDENCE_USER_CONFIRMED = "USER_CONFIRMED"  # Nom confirmé par l'utilisateur (UI)
CONFIDENCE_CLAUDE         = "CLAUDE"          # Extraction Claude Haiku réussie
CONFIDENCE_FALLBACK       = "FALLBACK_REGEX"  # Heuristique regex uniquement

# Scopes par rôle moteur
_PAPPERS_SCOPE: dict[str, str] = {
    "strategie":    "full",
    "finance":      "full",
    "dg":           "full",
    "synthese":     "full",
    "marketing":    "summary",
    "commercial":   "summary",
    "supply_chain": "summary",
}

# ── Contrat figé du bloc SUMMARY ─────────────────────────────────────────────
# DISCIPLINE : cette liste est le contrat de ce que summary contient.
# Ne jamais ajouter un champ ici sans décision explicite et mise à jour du test.
# Si tu veux plus de détails → scope="full", pas une extension de summary.
SUMMARY_FIELDS = (
    "entity_header",   # Nom de la société
    "siren",           # SIREN
    "ca",              # CA dernier exercice
    "effectif",        # Effectif déclaré
    "proc",            # Procédures collectives (alerte critique)
    # FIN DU CONTRAT — toute modification doit être documentée dans CHANGELOG
)

# TTL cache disque en secondes
_TTL = {
    "fiche":     7  * 24 * 3600,   # identité légale      : 7 jours
    "comptes":   30 * 24 * 3600,   # comptes annuels       : 30 jours
    "proc":      1  * 24 * 3600,   # procédures collectives : 24 heures
}

_FINANCIAL_KEYWORDS = {
    "fr": [
        "bilan", "comptes", "ebitda", "ebit", "ebe",
        "due diligence", "acquisition", "cession", "rachat", "fusion",
        "tresorerie", "trésorerie", "dette", "endettement", "capitaux propres",
        "solvabilite", "solvabilité", "diagnostic financier", "audit",
        "liasse", "liasse fiscale", "marge", "amortissement", "provision",
        "bfr", "besoin en fonds de roulement", "dso", "dpo",
        "valorisation", "multiple", "lbo", "private equity", "investisseur",
    ],
    "en": [
        "balance sheet", "accounts", "p&l", "profit and loss", "ebitda", "ebit",
        "due diligence", "acquisition", "disposal", "merger", "takeover",
        "cash", "debt", "leverage", "equity", "solvency",
        "financial review", "audit", "financial statements",
        "margin", "depreciation", "amortization", "provision",
        "working capital", "dso", "dpo", "valuation", "multiple",
        "lbo", "private equity", "investor",
    ],
}

# ── Labels bilingues ──────────────────────────────────────────────────────────
_LABELS = {
    "fr": {
        "block_header":         "DONNEES PAPPERS — SOURCE OFFICIELLE (INSEE / INPI / BODACC)",
        "block_header_summary": "PAPPERS — CONTEXTE SOCIÉTÉ (résumé)",
        "block_footer":         "Données injectées en début de session, partagées par rôle. Actualisées quotidiennement.",
        "block_footer_summary": "Données résumées — rôle opérationnel. Voir bloc Finance/DG pour la fiche complète.",
        "comptes_inclus":       "Comptes annuels détaillés inclus",
        "entity_header":        "Entreprise",
        "entity_primary":       "Société analysée (principale)",
        "entity_secondary":     "Entité secondaire",
        "siren":                "SIREN",
        "forme":                "Forme juridique",
        "siege":                "Siège",
        "ca":                   "CA (dernier exercice connu)",
        "resultat":             "Résultat net",
        "effectif":             "Effectif déclaré",
        "proc":                 "Procédures collectives",
        "proc_none":            "Aucune",
        "proc_warn":            "ALERTE : {n} procédure(s) détectée(s)",
        "dirigeants":           "Dirigeants",
        "comptes_header":       "Comptes annuels détaillés",
        "actif_immo":           "Immobilisations nettes",
        "actif_stocks":         "Stocks",
        "actif_creances":       "Créances clients",
        "actif_tresorerie":     "Trésorerie",
        "passif_cp":            "Capitaux propres",
        "passif_dettes_fin":    "Dettes financières",
        "passif_dettes_fou":    "Dettes fournisseurs",
        "cr_ebe":               "EBE",
        "cr_charges_pers":      "Charges de personnel",
        "cr_dotations":         "Dotations aux amortissements",
        "cr_resultat_fin":      "Résultat financier",
        "ratios_header":        "Ratios calculés",
        "ratio_gearing":        "Gearing (dettes fin. / CP)",
        "ratio_marge_nette":    "Marge nette",
        "no_data":              "(non disponible)",
        "matching_siren":       "Résolution : SIREN saisi — confiance maximale",
        "matching_user_confirmed": "Résolution : entité confirmée par l'utilisateur — confiance élevée",
        "matching_claude":      "Résolution : détection Claude — confiance élevée",
        "matching_fallback":    "Résolution : heuristique regex — confiance modérée (à vérifier)",
        "not_found_warn":       "⚠ Société '{name}' non trouvée dans Pappers (registre français uniquement)",
        "cache_hit":            "Source : cache local ({age}h)",
        # Captions bandeau
        "banner_caption_siren":     "SIREN saisi directement — identification certaine, 0 ambiguïté",
        "banner_caption_heuristic": "Pré-détection locale (heuristique) — Claude affinera la détection au lancement",
        "banner_caption_fallback":  "Pré-détection heuristique uniquement — configurez ANTHROPIC_API_KEY pour améliorer",
        "banner_caption_none":      "Saisissez un SIREN dans le brief ou dans les précisions pour une identification certaine",
        # Confirm entity UI
        "confirm_primary":      "Société principale analysée",
        "confirm_option_none":  "— Aucune / Désactiver l'enrichissement —",
        "confirm_option_manual":"Autre SIREN (saisie manuelle)",
        "confirm_siren_input":  "SIREN de la société principale (9 chiffres)",
    },
    "en": {
        "block_header":         "PAPPERS DATA — OFFICIAL SOURCE (INSEE / INPI / BODACC)",
        "block_header_summary": "PAPPERS — COMPANY CONTEXT (summary)",
        "block_footer":         "Data injected at session start, per role. Updated daily.",
        "block_footer_summary": "Summary data — operational role. See Finance/DG block for full details.",
        "comptes_inclus":       "Detailed annual accounts included",
        "entity_header":        "Company",
        "entity_primary":       "Analysed company (primary)",
        "entity_secondary":     "Secondary entity",
        "siren":                "SIREN",
        "forme":                "Legal form",
        "siege":                "Registered office",
        "ca":                   "Revenue (latest known FY)",
        "resultat":             "Net income",
        "effectif":             "Headcount",
        "proc":                 "Insolvency proceedings",
        "proc_none":            "None",
        "proc_warn":            "WARNING: {n} proceeding(s) detected",
        "dirigeants":           "Officers",
        "comptes_header":       "Detailed annual accounts",
        "actif_immo":           "Net fixed assets",
        "actif_stocks":         "Inventories",
        "actif_creances":       "Trade receivables",
        "actif_tresorerie":     "Cash & equivalents",
        "passif_cp":            "Shareholders equity",
        "passif_dettes_fin":    "Financial debt",
        "passif_dettes_fou":    "Trade payables",
        "cr_ebe":               "EBITDA",
        "cr_charges_pers":      "Personnel costs",
        "cr_dotations":         "D&A",
        "cr_resultat_fin":      "Financial result",
        "ratios_header":        "Computed ratios",
        "ratio_gearing":        "Gearing (fin. debt / equity)",
        "ratio_marge_nette":    "Net margin",
        "no_data":              "(not available)",
        "matching_siren":       "Resolution: user-supplied SIREN — maximum confidence",
        "matching_user_confirmed": "Resolution: entity confirmed by user — high confidence",
        "matching_claude":      "Resolution: Claude detection — high confidence",
        "matching_fallback":    "Resolution: regex heuristic — moderate confidence (verify)",
        "not_found_warn":       "⚠ Company '{name}' not found in Pappers (French registry only)",
        "cache_hit":            "Source: local cache ({age}h)",
        "banner_caption_siren":     "SIREN provided directly — certain identification, zero ambiguity",
        "banner_caption_heuristic": "Local pre-detection (heuristic) — Claude will refine at launch if key is set",
        "banner_caption_fallback":  "Local heuristic only — configure ANTHROPIC_API_KEY to improve accuracy",
        "banner_caption_none":      "Add a SIREN to your brief or detail fields for certain identification",
        "confirm_primary":      "Primary company being analysed",
        "confirm_option_none":  "— None / Disable enrichment —",
        "confirm_option_manual":"Other SIREN (manual entry)",
        "confirm_siren_input":  "Primary company SIREN (9 digits)",
    },
}


def _t(key, lang, **kw):
    lbl = _LABELS.get(lang, _LABELS["fr"]).get(key, key)
    return lbl.format(**kw) if kw else lbl


# ── Clés ──────────────────────────────────────────────────────────────────────

def _pappers_key():
    return os.environ.get("PAPPERS_API_KEY", "").strip() or None

def _anthropic_key():
    return os.environ.get("ANTHROPIC_API_KEY", "").strip() or None


# ── Cache disque L2 ───────────────────────────────────────────────────────────

class PappersCache:
    """
    Cache JSON sur disque avec TTL différencié par type de donnée.
      fiche    : 7 jours  (identité légale)
      proc     : 24 h     (procédures collectives — peut évoluer rapidement)
      comptes  : 30 jours (comptes annuels — changent à la publication du bilan)
    Utilisé comme L2 sous le lru_cache L1 (intra-session).
    """
    def __init__(self):
        from utils.config_paths import ensure_cache_dir
        self._path = ensure_cache_dir() / "pappers_cache.json"
        self._data: dict = {}
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        try:
            if self._path.exists():
                with open(self._path, "r", encoding="utf-8") as f:
                    raw = f.read()
                self._data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            # Fichier corrompu → on purge proprement et on repart à zéro
            try:
                self._path.rename(self._path.with_suffix(".bak"))
            except Exception:
                pass
            self._data = {}
        except Exception:
            self._data = {}
        self._loaded = True

    def _save(self):
        try:
            # v16.5.76 Phase 7a (VULN-5) — dossier 0o700 sur POSIX (fail-open)
            try:
                from utils.config_paths import ensure_private_dir as _epd
                _epd(self._path.parent)
            except Exception:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            # atomic write: write to .tmp then rename (Écriture atomique)
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            tmp.replace(self._path)
        except Exception:
            pass

    def purge_expired(self):
        """Supprime les entrées dont le TTL est expiré. À appeler périodiquement."""
        self._load()
        now = time.time()
        expired = [k for k, v in self._data.items()
                   if isinstance(v, dict) and now - v.get("fetched_at", 0) > 30 * 24 * 3600]
        for k in expired:
            del self._data[k]
        if expired:
            self._save()
        return len(expired)

    def get(self, key: str, ttl_seconds: int):
        self._load()
        entry = self._data.get(key)
        if not entry:
            return None
        age = time.time() - entry.get("fetched_at", 0)
        if age > ttl_seconds:
            del self._data[key]
            return None
        entry["_cache_age_h"] = round(age / 3600, 1)
        return entry.get("value")

    def set(self, key: str, value):
        self._load()
        self._data[key] = {"value": value, "fetched_at": time.time()}
        self._save()

    def age_hours(self, key: str) -> Optional[float]:
        self._load()
        entry = self._data.get(key)
        if not entry:
            return None
        return round((time.time() - entry.get("fetched_at", 0)) / 3600, 1)


_disk_cache = PappersCache()


# ── Extraction SIREN prioritaire ──────────────────────────────────────────────

def _extract_siren_from_brief(brief_text: str) -> Optional[str]:
    # v17.1-B2.1 (B2.1-04) — délègue à l'extracteur multi-SIREN qui tolère les
    # espaces/points (« SIREN 850 415 290 »). Évite que le chemin PRIMAIRE rate un
    # SIREN espacé et retombe sur un fallback Claude.
    if not brief_text:
        return None
    alls = _extract_all_sirens_from_brief(brief_text)
    return alls[0] if alls else None


def _extract_all_sirens_from_brief(brief_text: str) -> list:
    """v17.1-A4 (A4-01) — extrait TOUS les SIREN du brief, y compris écrits avec
    espaces (« 501 152 193 »), dans l'ordre d'apparition, dédupliqués. Corrige le
    chemin mono-SIREN qui affamait l'enrichissement de la 2e entité (comparatif)."""
    if not brief_text:
        return []
    out: list = []
    # 1) SIREN labellisés (tolère espaces/points) : SIREN/n°/numéro : 501 152 193
    for m in re.finditer(
            r'(?:SIREN|N[°ºo]|num[ée]ro)\s*[:\-]?\s*(\d{3}[\s.]?\d{3}[\s.]?\d{3})',
            brief_text, re.IGNORECASE):
        s = re.sub(r'\D', '', m.group(1))
        if len(s) == 9 and s not in out:
            out.append(s)
    # 2) SIREN « nus » contigus (9 chiffres)
    for m in re.finditer(r'\b(\d{9})\b', brief_text):
        s = m.group(1)
        if s not in out:
            out.append(s)
    return out


def _ordered_candidates(primary_siren: str, brief_text: str) -> list:
    """Liste de candidats SIREN avec le primaire en tête, suivi des autres SIREN
    détectés dans le brief (entités secondaires potentielles, ex. comparatif)."""
    alls = _extract_all_sirens_from_brief(brief_text)
    ordered = [primary_siren] + [s for s in alls if s != primary_siren]
    # dédup en préservant l'ordre
    seen, res = set(), []
    for s in ordered:
        if s and s not in seen:
            seen.add(s); res.append(s)
    return res


def _entity_summary(fiche: dict, comptes: dict | None = None) -> dict:
    """v17.1-A4.2 (A4.2-02) — résumé STRUCTURÉ d'une entité résolue, pour le bloc
    comparatif déterministe. Champs absents = 'n/d' (aucun chiffre fabriqué)."""
    nd = "n/d"
    fiche = fiche or {}
    ca = net = nd
    exercice = nd
    try:
        fins = fiche.get("finances") or []
        if fins:
            ca = fins[0].get("chiffre_affaires") or nd
            net = fins[0].get("resultat") or nd
            exercice = (fins[0].get("annee") or fins[0].get("date_cloture")
                        or fins[0].get("exercice") or nd)
    except Exception:
        pass
    treso = nd
    try:
        if comptes and not comptes.get("_error"):
            exs = comptes.get("comptes") or comptes.get("exercices") or []
            if exs and isinstance(exs[0], dict):
                act = exs[0].get("actif") or {}
                treso = act.get("tresorerie") or act.get("disponibilites") or nd
    except Exception:
        pass
    import re as _re2
    siren = _re2.sub(r"\D", "", str(fiche.get("_siren_resolved") or fiche.get("siren") or "")) or nd
    return {
        "name": fiche.get("nom_entreprise") or fiche.get("denomination") or nd,
        "siren": siren,
        "market": fiche.get("forme_juridique") or nd,
        "exercice": exercice,
        "ca": ca,
        "net_income": net,
        "effectif": fiche.get("effectif") or fiche.get("tranche_effectif_salarie") or nd,
        "tresorerie": treso,
        "source": "Pappers",
        "scope": "SOCIAL_STANDALONE",
    }


# ── Nettoyage des décorations non-métier avant extraction entités ────────────
# v16.5.62 — défense contre les faux candidats issus de la bannière ASCII
# et des sections de méta-instructions générées par brief_ui (ex. "ANALYSE —
# CoDIR IA v16.5.x" en tête). Ces tokens n'ont aucun sens métier mais sont
# capitalisés, donc pris comme entités par le regex fallback.
_DECORATIVE_CHARS = set("║╔╚╗╝═│─┌└┐┘━┃┏┗┓┛▌▐▀▄■□◆◇●○")
_META_HEADER_RE = re.compile(
    r"^\s*[║╔╚╗╝═│─┌└┐┘━┃┏┗┓┛▌▐]+.*(CoDIR\s*IA|ANALYSE|ANALYZE|FIL\s*ROUGE).*$",
    re.IGNORECASE | re.MULTILINE,
)

def _strip_decorative_noise(text: str) -> str:
    """
    Retire les lignes composées uniquement de caractères décoratifs et les
    en-têtes de bannière auto-générés par brief_ui. Conserve le contenu métier.
    """
    if not text:
        return text
    # 1. Supprimer les headers de bannière auto (ex: "║ ANALYSE — CoDIR IA v16.5.x ║")
    text = _META_HEADER_RE.sub("", text)
    # 2. Supprimer les lignes faites uniquement de décoration (≥50% caractères box-drawing)
    lines_out = []
    for ln in text.splitlines():
        stripped = ln.strip()
        if not stripped:
            lines_out.append(ln)
            continue
        deco_count = sum(1 for c in stripped if c in _DECORATIVE_CHARS)
        if deco_count >= max(1, len(stripped) // 2):
            continue  # ligne 100% décorative
        lines_out.append(ln)
    return "\n".join(lines_out)


# ── Pré-filtre Claude ─────────────────────────────────────────────────────────

def _prefilter_claude(brief_text, lang):
    # v16.5.62 — nettoyer la décoration avant envoi à Claude ou au fallback
    brief_text = _strip_decorative_noise(brief_text or "")
    ak = _anthropic_key()
    if not ak:
        result = _prefilter_fallback(brief_text, lang)
        result["_method"] = "fallback"
        return result
    try:
        if lang == "en":
            system = (
                "You are a named entity extractor. Return ONLY valid JSON, no markdown.\n"
                "Extract French company names explicitly mentioned (not cities, not people).\n"
                "Detect if the text has financial analysis context (balance sheet, EBITDA, "
                "due diligence, acquisition, debt, audit, valuation, accounts).\n"
                'Format: {"entreprises": ["Name1", "Name2"], "contexte_financier": true}'
            )
            user = f"Text:\n\n{brief_text[:2000]}"
        else:
            system = (
                "Tu es un extracteur d'entités nommées. Retourne UNIQUEMENT du JSON valide, sans markdown.\n"
                "Extrais les noms d'entreprises françaises explicitement mentionnés (pas les villes, pas les personnes).\n"
                "Détecte si le texte a un contexte d'analyse financière (bilan, comptes, EBITDA, "
                "due diligence, acquisition, dette, audit, valorisation, liasse).\n"
                'Format : {"entreprises": ["Nom1", "Nom2"], "contexte_financier": true}'
            )
            user = f"Texte :\n\n{brief_text[:2000]}"

        import anthropic as _ac
        client = _ac.Anthropic(api_key=ak)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        result = json.loads(raw)
        return {
            "entreprises":        (result.get("entreprises") or [])[:_MAX_ENTITIES],
            "contexte_financier": bool(result.get("contexte_financier", False)),
            "_method":            "claude",
        }
    except Exception:
        result = _prefilter_fallback(brief_text, lang)
        result["_method"] = "fallback"
        return result


def _prefilter_fallback(brief_text, lang):
    # v16.5.62 — nettoyer la décoration ASCII avant extraction regex
    brief_text = _strip_decorative_noise(brief_text or "")
    _STOP = {
        "groupe", "societe", "société", "entreprise", "sas", "sa", "sarl",
        "sasu", "eurl", "france", "europe", "holding", "services", "bonjour",
        "directeur", "directrice", "president", "président", "manager",
        # v16.5.62 — bruit récurrent issu des templates brief/méta-instructions
        "analyse", "analyser", "analyze", "analyzing",
        "codir", "fil", "rouge", "brief", "contexte", "horizon", "langue",
        "question", "sortie", "décision", "decision", "arbitrage", "synthèse",
        # B.1.3.20 (P1-D, run dossier industriel) — labels/valeurs du gabarit bloc B et
        # entêtes de sections : « Actionnariat » était candidat n°1 du picker
        # sur brouillon (fréquences=1 → tri alpha) et a fini confirmé →
        # Pappers('Actionnariat') → fiche « CHARLET ACTIONNARIAT ».
        "actionnariat", "actionnaire", "actionnaires", "autre", "référence",
        "reference", "géographie", "geographie", "secteur", "messages",
        "sensibles", "diagnostic", "enrichissement", "finalisation",
        "cœur", "coeur", "marché", "marche", "français", "francais",
        "contexte business", "ordre du jour",
        # 9.4.61 — vocabulaire des briefs de séance
        "option", "options", "conseil", "équipe", "équipes", "equipe", "equipes", "recommandation", "hypothèses",
        "hypotheses", "actions", "points", "mode", "modes", "séance", "seance", "exercice", "décisions", "decisions",
        "direction", "finalisation", "état", "etat",
    }
    pat = re.compile(
        r"\b([A-ZÀÂÉÈÊËÎÏÔÙÛÜ][A-Za-zÀ-ÿ]{2,}"
        r"(?:[\s\-][A-ZÀÂÉÈÊËÎÏÔÙÛÜ][A-Za-zÀ-ÿ]{2,})*)\b"
    )
    seen = {}
    for c in pat.findall(brief_text):
        low = c.strip().lower()
        if low not in _STOP and len(c) >= 4:
            seen[c] = seen.get(c, 0) + 1
    ranked = sorted(seen.keys(), key=lambda x: (-seen[x], x))
    # B.1.3.20 (P1-D, run dossier industriel) — le champ déclaré « Société : » passe EN
    # TÊTE AVANT le cap _MAX_ENTITIES. Racine reproduite : sur un brouillon où
    # toutes les fréquences valent 1, le tri alphabétique décidait du top-3 et
    # dossier industriel (capturé) était COUPÉ par le cap — le picker présélectionnait
    # « Actionnariat ». La déclaration explicite de l'utilisateur prime.
    _soc_m20 = re.search(
        r"^\s*(?:Soci[ée]t[ée]|Company|Entreprise)\s*:\s*(.+)$",
        brief_text or "", re.IGNORECASE | re.MULTILINE)
    if _soc_m20:
        _soc20 = re.sub(r"\([^)]*\)?", "", _soc_m20.group(1)).split(",")[0].strip()[:80]
        if _soc20:
            # 9.4.61 — « Option » et « Conseil » sortaient comme sociétés (cas de recette) : quand le dirigeant DÉCLARE la société,
            # les autres candidats ne sont retenus que s'ils portent une forme juridique (SA, SAS, Inc, Ltd, plc, GmbH…)
            _legal61 = re.compile(r"(?i)\b(?:SA|SAS|SASU|SARL|EURL|SNC|SCA|SE|Inc\.?|Corp\.?|Corporation|Company|Co\.?|"
                                  r"Ltd\.?|Limited|plc|LLC|LLP|GmbH|AG|NV|BV|SpA|SL|AB|ASA|Oy|Group|Groupe|Holding)\b")
            ranked = [_soc20] + [c for c in ranked
                                 if c.strip().lower() != _soc20.lower() and _legal61.search(c)
                                 and not _legal61.fullmatch(c.strip())          # « Company » seul n'est pas une société
                                 and c.strip().lower() not in _soc20.lower()]
    ranked = ranked[:_MAX_ENTITIES]
    text_lower = brief_text.lower()
    kws = _FINANCIAL_KEYWORDS.get(lang, _FINANCIAL_KEYWORDS["fr"])
    fin = any(k in text_lower for k in kws)
    return {"entreprises": ranked, "contexte_financier": fin, "_method": "fallback"}


# ── Hiérarchie multi-entités ──────────────────────────────────────────────────

def _resolve_ui_pref_to_candidate(pref: str, candidates: list, brief_text: str) -> Optional[str]:
    """v17.1-B2.3.2 — Résout un champ UI (confirmed_entity / societe_field) vers
    un candidat, MÊME quand les candidats sont des SIREN et le champ un nom (ou
    l'inverse). Corrige le P0 où le Cas 2 (SIREN→900) court-circuitait le champ
    UI et laissait le 1er SIREN gagner. Renvoie le candidat ou None."""
    pref = (pref or "").strip()
    if not pref or not candidates:
        return None
    pl = pref.lower()
    pref_digits = re.sub(r"\D", "", pref)
    # 1) Match direct sur le token candidat (SIREN==SIREN, nom==nom).
    for c in candidates:
        cl = (c or "").strip().lower()
        if cl and (cl == pl or cl in pl or pl in cl):
            return c
    # 2) Mapping nom <-> SIREN via le brief.
    try:
        from patches.entity_role_resolver import _name_for_siren
        for c in candidates:
            if re.fullmatch(r"\d{9}", (c or "").strip()):
                if pref_digits and pref_digits == c.strip():
                    return c
                nm = _name_for_siren(brief_text, c)
                if nm and (pl in nm.lower() or nm.lower() in pl):
                    return c
            else:
                # candidat = nom, pref = SIREN : mappe le SIREN pref vers son nom.
                if len(pref_digits) == 9:
                    nm = _name_for_siren(brief_text, pref_digits)
                    if nm and (nm.lower() in (c or "").lower() or (c or "").lower() in nm.lower()):
                        return c
    except Exception:
        pass
    return None


def _detect_primary_entity(
    candidates: list,
    brief_text: str,
    societe_field: str = "",
    confirmed_entity: str = "",
) -> tuple[Optional[str], list]:
    """
    Retourne (primary, secondaries) avec pondération sémantique — v16.5.55.

    Pondérations appliquées (cumulatives) :
      - confirmed_entity (UI) → score MAX (999) : certainté absolue
      - champ Société saisi   → score=800 + fréquence : bat toujours la fréquence brute
      - SIREN direct (9 chiffres) → score 900 : identifiant sans ambiguïté
      - mentions dans sections "contexte" ou "société analysée" → ×2
      - fréquence brute dans le brief → score de base

    Résout le cas "Nous analysons X face à Y (concurrent)" où Y serait
    plus mentionné que X par simple fréquence.
    """
    if not candidates:
        return None, []
    if len(candidates) == 1:
        return candidates[0], []

    # ── v17.1-B2.3.2 — Le champ UI explicite (confirmed/société) prime et est
    # résolu vers un candidat AVANT le scoring (qui sinon donne 900 à tout SIREN
    # et laisse le 1er gagner). Mapping nom<->SIREN inclus. P0 corrigé.
    for _pref in (confirmed_entity, societe_field):
        _m = _resolve_ui_pref_to_candidate(_pref, candidates, brief_text)
        if _m is not None:
            return _m, [c for c in candidates if c != _m]

    scores: dict[str, float] = {}
    _confirmed_clean = (confirmed_entity or "").strip().lower()
    _societe_clean   = (societe_field   or "").strip().lower()

    for cand in candidates:
        cand_low = cand.strip().lower()

        # Cas 1 : confirmed_entity (UI) → priorité absolue
        if _confirmed_clean and (cand_low == _confirmed_clean or
                                  cand_low in _confirmed_clean or
                                  _confirmed_clean in cand_low):
            scores[cand] = 999.0
            continue

        # Cas 2 : SIREN à 9 chiffres → très haut
        if re.match(r"^\d{9}$", cand):
            scores[cand] = 900.0
            continue

        # Cas 3 : champ Société explicitement saisi → score fixe élevé (800)
        # + bonus fréquence pour différencier deux entités dans le champ Société
        freq = len(re.findall(re.escape(cand), brief_text, re.IGNORECASE))
        if _societe_clean and (cand_low in _societe_clean or _societe_clean in cand_low):
            # Score 800 + fréquence : bat toujours la fréquence brute des concurrents
            scores[cand] = 800.0 + freq
            continue

        # Cas 4 : fréquence brute + léger boost tête de brief
        brief_head = brief_text[:400]
        freq_head  = len(re.findall(re.escape(cand), brief_head, re.IGNORECASE))
        scores[cand] = freq + (freq_head * 0.5)

    # ── v17.1-B2.3 — OVERRIDE DE RÔLE (sponsor/cible) ───────────────────────
    # Sur un brief M&A « je suis DAF de X … rapprochement avec Y », la CIBLE (Y)
    # doit être l'entité primaire d'analyse, pas le sponsor (X). v17.1-B2.3.2 : on
    # arrive ici uniquement si le champ UI explicite N'A PAS résolu vers un
    # candidat (sinon on a déjà renvoyé plus haut) — donc on laisse le role
    # resolver tourner même si societe_field/confirmed_entity étaient renseignés
    # mais sans correspondance. Fail-open. Fini le « premier SIREN = primaire ».
    if True:
        try:
            from patches.entity_role_resolver import role_adjusted_primary
            _role_primary, _roles = role_adjusted_primary(candidates, brief_text, scores)
            if _role_primary is not None and _role_primary in candidates:
                _sec = [c for c in candidates if c != _role_primary]
                return _role_primary, _sec
        except Exception:
            pass

    primary = max(candidates, key=lambda cand: scores.get(cand, 0))
    secondaries = [c for c in candidates if c != primary]
    return primary, secondaries


# ── Pappers API (cache L1 + L2) ───────────────────────────────────────────────

def _fetch_proc_fresh(siren: str) -> list:
    """
    Récupère uniquement les procédures collectives depuis Pappers.
    Utilisé pour rafraîchir la donnée critique (TTL 24h) sans refaire la fiche entière.
    Coût : 1 crédit. Stocké sous clé proc_{siren} avec TTL _TTL["proc"].
    """
    key = _pappers_key()
    if not key or not siren:
        return []
    try:
        r = requests.get(
            f"{PAPPERS_BASE_URL}/entreprise",
            params={
                "api_token": key, "siren": siren,
                "procedures_collectives": "true",
                "finances": "false", "dirigeants": "false",
                "beneficiaires_effectifs": "false",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        procs = r.json().get("procedures_collectives") or []
        _disk_cache.set(f"proc_{siren}", procs)
        return procs
    except Exception:
        return []


@lru_cache(maxsize=_CACHE_SIZE)
def _fetch_fiche(name_or_siren):
    key = _pappers_key()
    if not key:
        return {}
    try:
        clean = name_or_siren.strip()

        # ── Cache L2 fiche ────────────────────────────────────────────────────
        cache_key = f"fiche_{clean}"
        cached = _disk_cache.get(cache_key, _TTL["fiche"])
        if cached:
            cached["_from_cache"] = True
            cached["_cache_age_h"] = _disk_cache.age_hours(cache_key)
            # Fusionner proc fraîche si son TTL 24h est expiré
            _siren_cached = cached.get("_siren_resolved") or cached.get("siren", "")
            if _siren_cached:
                _proc_fresh = _disk_cache.get(f"proc_{_siren_cached}", _TTL["proc"])
                if _proc_fresh is None:
                    # TTL proc expiré → rafraîchir de manière non bloquante
                    _proc_fresh = _fetch_proc_fresh(_siren_cached)
                if _proc_fresh is not None:
                    cached["procedures_collectives"] = _proc_fresh
            return cached

        if re.match(r"^\d{9}$", clean):
            siren = clean
        else:
            r = requests.get(
                f"{PAPPERS_BASE_URL}/recherche",
                params={"api_token": key, "q": clean, "precision": "standard", "par_page": 1},
                timeout=_REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            res = r.json().get("resultats") or []
            if not res:
                return {"_not_found": True}
            siren = res[0].get("siren", "")
            if not siren:
                return {"_not_found": True}

        r2 = requests.get(
            f"{PAPPERS_BASE_URL}/entreprise",
            params={
                "api_token": key, "siren": siren,
                "finances": "true",
                "procedures_collectives": "true",
                "dirigeants": "true",
                "beneficiaires_effectifs": "true",
            },
            timeout=_REQUEST_TIMEOUT,
        )
        r2.raise_for_status()
        data = r2.json()
        data["_siren_resolved"] = siren
        _disk_cache.set(cache_key, data)
        # Stocker proc séparément avec TTL 24h
        _siren_for_proc = data.get("_siren_resolved") or data.get("siren", "") or siren
        if _siren_for_proc:
            _disk_cache.set(f"proc_{_siren_for_proc}", data.get("procedures_collectives") or [])
        return data
    except requests.exceptions.Timeout:
        return {"_error": "timeout"}
    except Exception as e:
        return {"_error": str(e)}


@lru_cache(maxsize=_CACHE_SIZE)
def _fetch_comptes(siren):
    key = _pappers_key()
    if not key:
        return {}
    try:
        cache_key = f"comptes_{siren}"
        cached = _disk_cache.get(cache_key, _TTL["comptes"])
        if cached:
            return cached
        r = requests.get(
            f"{PAPPERS_BASE_URL}/entreprise/comptes",
            params={"api_token": key, "siren": siren},
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        _disk_cache.set(cache_key, data)
        return data
    except Exception as e:
        return {"_error": str(e)}


# ── Formatage ─────────────────────────────────────────────────────────────────

def _fmt(val):
    if val is None:
        return ""
    try:
        v = int(val)
        if abs(v) >= 1_000_000_000:
            return f"{v/1_000_000_000:.2f} Md€"
        if abs(v) >= 1_000_000:
            return f"{v/1_000_000:.1f} M€"
        if abs(v) >= 1_000:
            return f"{v/1_000:.0f} k€"
        return f"{v} €"
    except Exception:
        return str(val)


def _pct(num, denom):
    try:
        if denom and int(denom) != 0:
            return f"{int(num)/int(denom)*100:.1f} %"
    except Exception:
        pass
    return "(n/c)"


def _format_fiche(fiche, comptes, lang, confidence=None, scope="full", role_label=None):
    """
    scope="full"    : fiche complète + comptes annuels si dispo
    scope="summary" : nom, SIREN, CA, effectif, procédures uniquement
    """
    nd = _t("no_data", lang)
    nom      = fiche.get("nom_entreprise") or fiche.get("denomination") or nd
    siren    = fiche.get("siren") or nd
    forme    = fiche.get("forme_juridique") or nd
    sg       = fiche.get("siege") or {}
    siege    = f"{sg.get('code_postal','') or ''} {sg.get('ville','') or ''}".strip() or nd
    fins     = fiche.get("finances") or []
    ca = res = None
    if fins:
        ca  = fins[0].get("chiffre_affaires")
        res = fins[0].get("resultat")
    effectif = fiche.get("effectif") or fiche.get("tranche_effectif_salarie") or nd
    procs    = fiche.get("procedures_collectives") or []
    proc_str = _t("proc_warn", lang, n=len(procs)) if procs else _t("proc_none", lang)
    # v62.13.9.4.15 — statut juridique explicite, lu dans les champs de la
    # fiche, jamais déduit ; transmis à tous les rôles (summary et full).
    try:
        from utils.company_profile import registry_status_from_fiche as _rsf
        _rs, _rsd = _rsf(fiche)
    except Exception:
        _rs, _rsd = "UNKNOWN", ""
    if _rs == "ACTIVE":
        statut_str = ("ACTIVE — registered" if lang == "en" else "EN ACTIVITÉ — inscrite") + (f" ({_rsd})" if _rsd else "")
    elif _rs == "CEASED":
        statut_str = ("STRUCK OFF / CEASED" if lang == "en" else "RADIÉE / CESSÉE") + (f" ({_rsd})" if _rsd else "")
    else:
        statut_str = "not stated by the registry" if lang == "en" else "non renseigné par le registre"
    statut_lbl = "Registry legal status" if lang == "en" else "Statut juridique (registre)"

    _conf_label = {
        CONFIDENCE_SIREN_DIRECT:   "matching_siren",
        CONFIDENCE_USER_CONFIRMED: "matching_user_confirmed",
        CONFIDENCE_CLAUDE:         "matching_claude",
        CONFIDENCE_FALLBACK:       "matching_fallback",
    }

    cache_note = ""
    if fiche.get("_from_cache") and fiche.get("_cache_age_h") is not None:
        cache_note = f"  {_t('cache_hit', lang, age=fiche['_cache_age_h'])}"

    W = 38

    # ── Summary scope ─────────────────────────────────────────────────────────
    if scope == "summary":
        lines = [
            f"  {_t('entity_header', lang):<{W}}: {nom}",
            f"  {_t('siren', lang):<{W}}: {siren}",
            f"  {_t('ca', lang):<{W}}: {_fmt(ca) or nd}",
            f"  {_t('effectif', lang):<{W}}: {effectif}",
            f"  {statut_lbl:<{W}}: {statut_str}",
            f"  {_t('proc', lang):<{W}}: {proc_str}",
        ]
        if confidence and confidence in _conf_label:
            lines.append(f"  {_t(_conf_label[confidence], lang)}")
        if cache_note:
            lines.append(cache_note)
        return "\n".join(lines)

    # ── Full scope ────────────────────────────────────────────────────────────
    dirs = fiche.get("dirigeants") or []
    dir_str = ", ".join(
        f"{d.get('prenom','').strip()} {d.get('nom','').strip()} ({d.get('qualite','')})"
        .strip()
        for d in dirs[:3] if d.get("nom")
    ) or nd

    header_label = role_label or _t("entity_header", lang)
    lines = [
        f"  {header_label:<{W}}: {nom}",
        f"  {_t('siren', lang):<{W}}: {siren}",
        f"  {_t('forme', lang):<{W}}: {forme}",
        f"  {_t('siege', lang):<{W}}: {siege}",
        f"  {_t('ca', lang):<{W}}: {_fmt(ca) or nd}",
        f"  {_t('resultat', lang):<{W}}: {_fmt(res) or nd}",
        f"  {_t('effectif', lang):<{W}}: {effectif}",
        f"  {statut_lbl:<{W}}: {statut_str}",
        f"  {_t('proc', lang):<{W}}: {proc_str}",
        f"  {_t('dirigeants', lang):<{W}}: {dir_str}",
    ]
    if confidence and confidence in _conf_label:
        lines.append(f"  {_t(_conf_label[confidence], lang)}")
    if cache_note:
        lines.append(cache_note)

    if comptes and not comptes.get("_error"):
        exs = comptes.get("comptes") or comptes.get("exercices") or []
        ex  = exs[0] if exs else comptes
        bil = ex.get("bilan") or {}
        cr  = ex.get("compte_de_resultat") or {}
        act = bil.get("actif") or {}
        pas = bil.get("passif") or {}
        immo       = act.get("immobilisations_nettes")
        stocks     = act.get("stocks")
        creances   = act.get("creances_clients") or act.get("creances")
        treso      = act.get("tresorerie") or act.get("disponibilites")
        cp_val     = pas.get("capitaux_propres")
        dettes_fin = pas.get("dettes_financieres") or pas.get("emprunts")
        dettes_fou = pas.get("dettes_fournisseurs")
        ebe        = cr.get("ebe") or cr.get("excedent_brut_exploitation")
        chg_pers   = cr.get("charges_personnel") or cr.get("salaires_charges")
        dotations  = cr.get("dotations_amortissements") or cr.get("dotations")
        res_fin    = cr.get("resultat_financier")
        lines.append(f"\n  ── {_t('comptes_header', lang)} ──")
        for lk, v in [
            ("actif_immo", immo), ("actif_stocks", stocks),
            ("actif_creances", creances), ("actif_tresorerie", treso),
            ("passif_cp", cp_val), ("passif_dettes_fin", dettes_fin),
            ("passif_dettes_fou", dettes_fou),
            ("cr_ebe", ebe), ("cr_charges_pers", chg_pers),
            ("cr_dotations", dotations), ("cr_resultat_fin", res_fin),
        ]:
            if v is not None:
                lines.append(f"    {_t(lk, lang):<{W}}: {_fmt(v)}")
        lines.append(f"\n  ── {_t('ratios_header', lang)} ──")
        lines.append(f"    {_t('ratio_gearing', lang):<{W}}: {_pct(dettes_fin, cp_val)}")
        lines.append(f"    {_t('ratio_marge_nette', lang):<{W}}: {_pct(res, ca)}")

    return "\n".join(lines)


# ── Points d'entrée publics ───────────────────────────────────────────────────

def build_pappers_blocks(
    brief_text: str,
    lang: str = "fr",
    confirmed_entity: Optional[str] = None,
) -> dict:
    """
    Pipeline principal v16.5.55.

    Retourne :
    {
      "full":        str,   # bloc complet pour Finance/DG/Stratégie/Synthèse
      "summary":     str,   # bloc résumé pour Marketing/Commercial/SC
      "primary":     str,   # identifiant de l'entité principale (nom ou SIREN)
      "secondaries": list,  # entités secondaires
      "confidence":  str,   # SIREN_DIRECT | CLAUDE | FALLBACK_REGEX
      "contexte_fin":   bool,              # contexte financier détecté
      "resolution_log": PappersResolutionLog, # traçabilité audit complète (None si échec)
    }
    """
    empty = {"full": "", "summary": "", "primary": "", "secondaries": [], "resolved_sirens": [], "resolved_entities": [], "confidence": "", "contexte_fin": False, "resolution_log": None}
    if not _pappers_key() or not brief_text or not brief_text.strip():
        return empty
    try:
        not_found_warn: list[str] = []

        # ── Priorité 1 : SIREN explicite du BRIEF courant ───────────────────
        # v62.8 — contrat d'identité : le SIREN saisi dans la demande courante
        # est immuable. Une valeur mémorisée dans l'UI/session peut être issue
        # d'un dossier précédent ; elle est tracée comme conflit mais ne gagne
        # jamais sur le brief.
        _confirmed_stripped = (confirmed_entity or "").strip()
        import re as _re
        _confirmed_is_siren = bool(_re.match(r"^\d{9}$", _confirmed_stripped))
        _siren_from_brief   = _extract_siren_from_brief(brief_text)
        _identity_conflict = bool(
            _siren_from_brief and _confirmed_is_siren
            and _siren_from_brief != _confirmed_stripped
        )
        _resolution_source = "UNKNOWN"

        if _siren_from_brief:
            siren_direct = _siren_from_brief
            candidates   = _ordered_candidates(siren_direct, brief_text)
            confidence   = CONFIDENCE_SIREN_DIRECT
            _resolution_source = "BRIEF_SIREN"
            text_lower   = brief_text.lower()
            kws          = _FINANCIAL_KEYWORDS.get(lang, _FINANCIAL_KEYWORDS["fr"])
            contexte_fin = any(k in text_lower for k in kws)
        elif _confirmed_is_siren:
            siren_direct = _confirmed_stripped
            candidates   = _ordered_candidates(siren_direct, brief_text)
            confidence   = CONFIDENCE_SIREN_DIRECT
            _resolution_source = "UI_CONFIRM"
            text_lower   = brief_text.lower()
            kws          = _FINANCIAL_KEYWORDS.get(lang, _FINANCIAL_KEYWORDS["fr"])
            contexte_fin = any(k in text_lower for k in kws)
        elif _confirmed_stripped:
            # Texte libre confirmé par l'UI (nom de société, pas SIREN)
            siren_direct = _confirmed_stripped
            candidates   = [siren_direct]
            confidence   = CONFIDENCE_USER_CONFIRMED
            _resolution_source = "UI_CONFIRM"
            text_lower   = brief_text.lower()
            kws          = _FINANCIAL_KEYWORDS.get(lang, _FINANCIAL_KEYWORDS["fr"])
            contexte_fin = any(k in text_lower for k in kws)
        else:
            # ── Priorité finale : Claude ou fallback regex ────────────────────
            pf           = _prefilter_claude(brief_text, lang)
            candidates   = pf.get("entreprises") or []
            contexte_fin = bool(pf.get("contexte_financier", False))
            _method      = pf.get("_method", "fallback")
            confidence   = CONFIDENCE_CLAUDE if _method == "claude" else CONFIDENCE_FALLBACK
            _resolution_source = "CLAUDE_EXTRACT" if _method == "claude" else "REGEX"

        if not candidates:
            return empty

        # ── B.1.3 (run dossier anglophone coté : candidat « dossier anglophone coté Forward ») ────────────
        # Normalisation des candidats AVANT toute résolution :
        #   1. le champ structuré « Société : » du brief, s'il existe, passe
        #      EN TÊTE (c'est la déclaration la plus fiable de l'utilisateur) ;
        #   2. les noms de PLANS/PROGRAMMES sont écartés — « dossier anglophone coté
        #      Forward », « Plan Horizon 2030 »… ne sont pas des sociétés.
        try:
            _societe_m = re.search(
                r"^\s*(?:Soci[ée]t[ée]|Company|Entreprise)\s*:\s*(.+)$",
                brief_text or "", re.IGNORECASE | re.MULTILINE)
            _societe = ""
            if _societe_m:
                _societe = re.sub(r"\([^)]*\)?", "", _societe_m.group(1))
                _societe = _societe.split(",")[0].strip()[:80]
            _plan_re = re.compile(
                r"\b(forward|plan|programme?|program|projet|project|"
                r"horizon|roadmap|initiative)\b", re.IGNORECASE)
            _kept = []
            for _c in candidates:
                _cs = (_c or "").strip()
                if not _cs:
                    continue
                if _plan_re.search(_cs) and (not _societe
                                             or _cs.lower() != _societe.lower()):
                    continue  # nom de plan, pas une société
                _kept.append(_cs)
            if _societe:
                _kept = [_societe] + [c for c in _kept
                                      if c.lower() != _societe.lower()]
            if _kept:
                candidates = _kept
        except Exception:
            pass

        # ── Hiérarchie principal / secondaires (pondération v16.5.55) ─────────
        # societe_field : extrait du brief si présent (signal explicite ×3)
        _soc_m = re.search(r"SOCI[EÉ]T[EÉ]\s*[:\-]?\s*([^\n]{2,80})", brief_text, re.IGNORECASE)
        _societe_field = _soc_m.group(1).strip() if _soc_m else ""
        if _siren_from_brief and _siren_from_brief in candidates:
            # v62.8 — le SIREN explicite du brief est l'entité primaire,
            # indépendamment d'un nom ou d'une confirmation de session.
            primary_cand = _siren_from_brief
            secondary_cands = [c for c in candidates if c != primary_cand]
        else:
            primary_cand, secondary_cands = _detect_primary_entity(
                candidates, brief_text,
                societe_field=_societe_field,
                confirmed_entity=confirmed_entity or ""
            )

        def _enrich(cand, is_primary: bool):
            fiche = _fetch_fiche(cand)
            if not fiche or fiche.get("_error"):
                return None, None
            if fiche.get("_not_found"):
                not_found_warn.append(_t("not_found_warn", lang, name=cand))
                return None, None
            comptes = {}
            if is_primary and contexte_fin:
                siren_res = fiche.get("_siren_resolved") or fiche.get("siren", "")
                if siren_res:
                    comptes = _fetch_comptes(siren_res)
            return fiche, comptes

        # ── Bloc FULL ─────────────────────────────────────────────────────────
        full_parts: list[str] = []
        summary_parts: list[str] = []
        primary_name = ""
        secondary_names: list[str] = []
        resolved_sirens: list[str] = []   # v17.1-A4 — SIREN réellement résolus
        resolved_entities: list[dict] = []  # v17.1-A4.2 — entités structurées

        p_fiche, p_comptes = _enrich(primary_cand, is_primary=True)
        if p_fiche:
            primary_name = p_fiche.get("nom_entreprise") or p_fiche.get("denomination") or primary_cand
            _ps = p_fiche.get("_siren_resolved") or p_fiche.get("siren") or ""
            if _ps:
                resolved_sirens.append(re.sub(r"\D", "", str(_ps)))
            resolved_entities.append(_entity_summary(p_fiche, p_comptes))
            full_parts.append(_format_fiche(
                p_fiche, p_comptes, lang, confidence=confidence, scope="full",
                role_label=_t("entity_primary", lang)
            ))
            summary_parts.append(_format_fiche(
                p_fiche, {}, lang, confidence=confidence, scope="summary",
                role_label=_t("entity_primary", lang)
            ))

        for sec_cand in secondary_cands:
            s_fiche, _ = _enrich(sec_cand, is_primary=False)
            if s_fiche:
                sec_name = s_fiche.get("nom_entreprise") or s_fiche.get("denomination") or sec_cand
                secondary_names.append(sec_name)
                _ss = s_fiche.get("_siren_resolved") or s_fiche.get("siren") or ""
                if _ss:
                    resolved_sirens.append(re.sub(r"\D", "", str(_ss)))
                resolved_entities.append(_entity_summary(s_fiche, None))
                # Secondaires : fiche résumée dans les deux blocs
                sec_fmt = _format_fiche(
                    s_fiche, {}, lang, confidence=confidence, scope="summary",
                    role_label=_t("entity_secondary", lang)
                )
                full_parts.append(sec_fmt)
                summary_parts.append(sec_fmt)

        if not full_parts and not not_found_warn:
            return empty

        sep = "\n" + "─" * 60 + "\n"

        def _wrap(parts, header_key, footer_key):
            if not parts and not not_found_warn:
                return ""
            header = f"\n{'═'*60}\n{_t(header_key, lang)}"
            if contexte_fin and header_key == "block_header" and full_parts:
                header += f"\n  ⚑  {_t('comptes_inclus', lang)}"
            header += f"\n{'═'*60}"
            footer  = f"\n{'═'*60}\n{_t(footer_key, lang)}\n{'═'*60}\n"
            body = sep.join(parts + not_found_warn)
            return header + "\n" + body + footer

        _blk_full    = _wrap(full_parts,    "block_header",         "block_footer")
        _blk_summary = _wrap(summary_parts, "block_header_summary", "block_footer_summary")

        # ── Log de résolution audit-ready (3.1 + 3.4) ────────────────────────
        _cache_hit = bool(p_fiche and p_fiche.get("_from_cache")) if p_fiche else False
        _cache_age = p_fiche.get("_cache_age_h") if p_fiche else None
        resolution_log = PappersResolutionLog(
            input_preview       = (brief_text or "")[:120].replace("\n", " "),
            path                = confidence,
            source              = _resolution_source,
            siren_used          = (p_fiche.get("_siren_resolved") or p_fiche.get("siren", "")) if p_fiche else "",
            primary_name        = primary_name,
            secondaries         = secondary_names,
            fallback_used       = confidence == CONFIDENCE_FALLBACK,
            cache_hit           = _cache_hit,
            cache_age_h         = _cache_age,
            contexte_fin        = contexte_fin,
            tokens_est_full     = len(_blk_full) // 4,
            tokens_est_summary  = len(_blk_summary) // 4,
            entities_not_found  = not_found_warn,
            authoritative_siren = _siren_from_brief or (_confirmed_stripped if _confirmed_is_siren else ""),
            identity_conflict   = _identity_conflict,
            conflicting_confirmed_entity = (_confirmed_stripped if _identity_conflict else ""),
            # v16.5.62 — données structurées pour le routeur company_profile
            fiche               = p_fiche or {},
            comptes             = p_comptes or {},
        )

        return {
            "full":           _blk_full,
            "summary":        _blk_summary,
            "primary":        primary_name,
            "secondaries":    secondary_names,
            "resolved_sirens": resolved_sirens,
            "resolved_entities": resolved_entities,
            "confidence":     confidence,
            "contexte_fin":   contexte_fin,
            "resolution_log": resolution_log,
        }

    except Exception as _ex:
        return {"full": "", "summary": "", "primary": "", "secondaries": [], "resolved_sirens": [], "resolved_entities": [], "confidence": "", "contexte_fin": False, "resolution_log": None}


def enrich_context_with_pappers(brief_text, lang="fr", confirmed_entity=None):
    """Wrapper rétrocompat. Retourne le bloc full uniquement."""
    return build_pappers_blocks(brief_text, lang, confirmed_entity=confirmed_entity).get("full", "")


def preview_pappers_detection(brief_text: str, lang: str = "fr") -> dict:
    """
    Détection légère pré-lancement — 0 crédit Pappers.
    Retourne active, siren_direct, candidates, confidence, has_claude, preview_method.
    """
    if not _pappers_key():
        return {"active": False}
    siren_direct = _extract_siren_from_brief(brief_text or "")
    has_claude   = bool(_anthropic_key())
    if siren_direct:
        return {
            "active":         True,
            "siren_direct":   siren_direct,
            "candidates":     [siren_direct],
            "confidence":     CONFIDENCE_SIREN_DIRECT,
            "has_claude":     has_claude,
            "preview_method": "siren_direct",
        }
    fb         = _prefilter_fallback(brief_text or "", lang)
    candidates = fb.get("entreprises") or []
    return {
        "active":         True,
        "siren_direct":   None,
        "candidates":     candidates,
        "confidence":     CONFIDENCE_CLAUDE if has_claude else CONFIDENCE_FALLBACK,
        "has_claude":     has_claude,
        "preview_method": "local_heuristic",
    }


def get_pappers_scope_for_role(role: str) -> str:
    """Retourne le scope Pappers pour un rôle donné."""
    return _PAPPERS_SCOPE.get(role, "full")


def get_pappers_status():
    key = _pappers_key()
    if not key:
        return {"configured": False, "key_preview": "", "has_claude": False}
    preview    = key[:8] + "..." + key[-4:] if len(key) > 12 else "****"
    has_claude = bool(_anthropic_key())
    return {"configured": True, "key_preview": preview, "has_claude": has_claude}


# ─────────────────────────────────────────────────────────────────────────────
# Patch v16.5.69.1 patch session 6 (audit terrain Robin) — test_connection
# ─────────────────────────────────────────────────────────────────────────────
# Bug détecté en condition réelle : le bouton "Tester Pappers" en page Config
# tentait d'importer `test_connection` depuis utils/pappers_tool.py mais cette
# fonction n'avait jamais été créée. Les 4 sources externes ajoutées en v16.5.68
# (GLEIF, SEC EDGAR, OpenSanctions, Companies House) ont chacune leur fonction
# `test_connection` standardisée, mais Pappers v16.5.59 n'avait pas été enrichi
# (cohérent avec la discipline "Pappers strictement intact" — mais ça crée ce
# bug UI quand le bouton est cliqué).
#
# Correction additive (pas de modification des fonctions existantes) :
# nouvelle fonction `test_connection()` qui appelle l'endpoint Pappers /entreprise
# sur un SIREN témoin (Vinci Construction = 552037806), vérifie le retour, et
# persiste le résultat via save_test_result (cohérent avec les 4 autres modules).

# Entité témoin pour le healthcheck — SIREN public stable, société française
# de référence dont la fiche existe toujours (Vinci Construction Grands Projets).
_PAPPERS_HEALTHCHECK_SIREN = "552037806"  # Vinci Construction Grands Projets


def test_connection(timeout: int = 8) -> Dict[str, Any]:
    """
    Test de connexion Pappers : appelle l'endpoint /entreprise sur un SIREN
    témoin (Vinci Construction Grands Projets) et vérifie la réponse.

    Patch v16.5.69.1 patch session 6 — ajout additif sans toucher aux
    fonctions existantes. Cohérent avec test_connection() des 4 autres
    modules de sources externes.

    Retourne :
      {"ok": bool, "message": str, "elapsed_ms": int}
    """
    import time
    # Imports locaux (pas globaux) — discipline "Pappers reste isolé"
    try:
        from utils.external_sources_common import safe_get, save_test_result
    except Exception:
        # Fallback minimal si external_sources_common indisponible
        # (par ex. en test isolé) — on retombe sur requests direct
        try:
            import requests
        except Exception:
            return {"ok": False, "message": "requests indisponible", "elapsed_ms": 0}

        key = _pappers_key()
        if not key:
            return {"ok": False, "message": "Clé Pappers absente — saisir PAPPERS_API_KEY dans Config", "elapsed_ms": 0}
        t0 = time.time()
        try:
            r = requests.get(
                f"{PAPPERS_BASE_URL}/entreprise",
                params={"api_token": key, "siren": _PAPPERS_HEALTHCHECK_SIREN},
                timeout=timeout,
            )
            elapsed_ms = int((time.time() - t0) * 1000)
            if r.status_code != 200:
                return {"ok": False, "message": f"HTTP {r.status_code} — {r.text[:120]}", "elapsed_ms": elapsed_ms}
            data = r.json()
            name = (data.get("nom_entreprise") or data.get("denomination") or "").upper()
            if "VINCI" in name:
                return {"ok": True, "message": f"OK — healthcheck Vinci Construction (SIREN {_PAPPERS_HEALTHCHECK_SIREN}) en {elapsed_ms}ms", "elapsed_ms": elapsed_ms}
            return {"ok": False, "message": f"Réponse 200 mais format inattendu (nom=«{name[:40]}»)", "elapsed_ms": elapsed_ms}
        except Exception as e:
            return {"ok": False, "message": f"{type(e).__name__}: {str(e)[:120]}", "elapsed_ms": int((time.time() - t0) * 1000)}

    # Voie nominale via external_sources_common.safe_get
    key = _pappers_key()
    if not key:
        msg = "Clé Pappers absente — saisir PAPPERS_API_KEY dans Config"
        save_test_result("pappers", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": 0}

    t0 = time.time()
    res = safe_get(
        f"{PAPPERS_BASE_URL}/entreprise",
        params={"api_token": key, "siren": _PAPPERS_HEALTHCHECK_SIREN},
        timeout=timeout,
    )
    elapsed_ms = int((time.time() - t0) * 1000)

    if not res.get("ok"):
        msg = f"{res.get('error', 'unknown')} — {res.get('message', '')[:120]}"
        save_test_result("pappers", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": elapsed_ms}

    # Vérifier qu'on a bien la fiche Vinci
    data = res.get("data", {})
    if not isinstance(data, dict):
        msg = "Réponse 200 mais payload non-dict"
        save_test_result("pappers", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": elapsed_ms}

    name = (data.get("nom_entreprise") or data.get("denomination") or "").upper()
    if "VINCI" in name:
        msg = f"OK — healthcheck Vinci Construction (SIREN {_PAPPERS_HEALTHCHECK_SIREN}) en {elapsed_ms}ms"
        save_test_result("pappers", ok=True, message=msg)
        return {"ok": True, "message": msg, "elapsed_ms": elapsed_ms}
    else:
        msg = f"Réponse 200 mais format inattendu (nom=«{name[:40]}»)"
        save_test_result("pappers", ok=False, message=msg)
        return {"ok": False, "message": msg, "elapsed_ms": elapsed_ms}
