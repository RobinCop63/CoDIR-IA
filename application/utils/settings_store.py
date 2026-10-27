from __future__ import annotations
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping

from .config_paths import ensure_config_dir, get_settings_path

@dataclass
class Settings:
    mode_default: str = "equilibre"  # equilibre | qualite | eco
    temperature: float = 0.4
    max_output_tokens: int = 8000          # 9.4.53 — maximum de l'écran ; les rôles principaux ont leur propre plancher

    openai_model_id: str = "gpt-5.4"             # 9.4.58 — qualité d'abord (était gpt-5.4-mini)
    google_model_id: str = "gemini-3.6-flash"     # v62.13.9.4.50 — 2.5 fermé aux nouveaux comptes
    anthropic_model_id: str = "claude-sonnet-5-5"   # v62.13.9.4.50 — Sonnet 4.5 retiré le 24/11/2026 (avis Anthropic du 30/09/2026)
    mistral_model_id: str = "mistral-medium-latest"
    perplexity_model_id: str = "perplexity/sonar" # v62.13.9.4.50 — API Agent (Sonar chat completions fermé le 27/09/2026)
    grok_model_id: str = "grok-4.3"               # v62.13.9.4.50 — Grok 3 retiré le 15/05/2026

    sc_prefilter_model_id: str = "gpt-5.4"        # v16.5.29 — SC pre-filter  (provider: OpenAI) — 9.4.58 : modèle complet
    sc_primary_model_id: str = "gpt-5.4"          # v16.5.29 — SC primary     (provider: OpenAI)
    sc_challenge_model_id: str = "gemini-3.6-flash" # v16.5.29 — SC challenge (provider: Google) — 9.4.50, modèle stable

    output_language: str = "fr"           # v16.5.38 — "fr" | "en"

    # v62.7 — contrat produit PPTX. ``working`` est la surface normale :
    # deck de travail 8-15 slides, éditable, livré avec avertissements de
    # mise en page non bloquants. ``strict`` conserve le contrôle QA historique
    # et le deck complet avec annexes pour les audits internes.
    pptx_delivery_mode: str = "working"      # working | strict

    # F.5.2 (Cycle C) — libellé de dossier : fil continu auquel se rattachent les
    # CoDIR successifs (ex. « Lhyfe vs FDE — M&A hydrogène »). Mode NORMAL de
    # regroupement multi-séances ; vide → repli société + genre. Per-dossier.
    dossier_label: str = ""

    # Temporal Core Refactor (A5, arbitrage Robin 26/07) — DATE D'ANALYSE
    # STRUCTURÉE : autorité temporelle de RANG 1 (au-dessus des labels
    # contractuels du brief et de toute inférence textuelle). ISO strict
    # YYYY-MM-DD ; vide = pas de scénario structuré. Une valeur malformée
    # BLOQUE le run (fail-closed) — jamais ignorée en silence.
    analysis_as_of_date: str = ""

    fallback_enabled: bool = True
    fallback_max_attempts: int = 2

    attachments_max_files: int = 20       # v16.5 (était 5)
    attachments_max_total_mb: int = 500   # v16.5 (était 25)
    # v62.13.9.4.39 — 8 000 tronquait les liasses avant le bilan : sur un dossier réel du
    # 20/09/2026 (neuf pièces), zéro fait de bilan extrait, les stocks — problème n°1 du
    # dossier — invisibles. Décision de Robin (21/09) : 50 000 par défaut.
    attachments_doc_token_budget: int = 120000    # 9.4.57 — demande du 10/10 : 50 000 → 120 000 (14 PDF tronqués à 50 000)

    # Since v16.5.69 — Téléchargement automatique des filings Companies House
    # Si True ET target_entity confirmée est UK ET COMPANIES_HOUSE_DOCUMENT_API_KEY
    # configurée, alors le pipeline télécharge automatiquement les derniers
    # Annual Accounts + Confirmation Statement et les ajoute à attachments_meta.
    # Désactivé par défaut pour éviter aspiration involontaire.
    enable_uk_filings_download: bool = False

    # v62.12.8 — identité canonique structurée de la dernière cible confirmée.
    # Le nom seul de v62.12.7 est conservé pour migration, mais tous les écrans
    # réutilisent désormais le même objet (registre, identifiant, LEI, pays,
    # source et confiance) après un clic explicite de l'utilisateur.
    last_target_entity: Dict[str, Any] = field(default_factory=dict)
    last_target_entity_name: str = ""

    # v62.13.2 — Option B ratifiée : seules les valeurs page-confirmées et
    # leurs dérivés déterministes sont admis dans les surfaces principales.
    # Doctrine courante : un scénario chiffré admis reste entier et qualifié dans le
    # corps ; écarté, il va au registre du dossier complet. Le champ est
    # conservé pour lire d'anciens settings.json, mais sa seule valeur active
    # est désormais "strict".
    numeric_post_control_policy: str = "strict"

def _safe_read_json(p: Path) -> Dict[str, Any]:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

# Modèles obsolètes → remplacés automatiquement à la lecture
_MODEL_MIGRATIONS: Dict[str, str] = {
    "gpt-5-mini":                  "gpt-5.4",          # 9.4.64 — GPT-4.1 retiré le 14/01/2027
    "gpt-5":                       "gpt-5.4",
    "gpt-4o-mini":                 "gpt-5.4",
    "gpt-5.3":                     "gpt-5.4",          # v16.5.38 — upgrade SC primary
    "mistral-large-latest":        "mistral-medium-latest",
    "gemini-2.0-flash":            "gemini-2.5-flash",
    # v62.13.9.4.50 — avis Anthropic du 30/09/2026 : Claude Sonnet 4.5 est retiré de l'API le 24/11/2026 (disponibilité
    # réduite dès le 30/10/2026). Décision Robin du 30/09 : Claude Sonnet 5.5 par défaut. Les réglages enregistrés sur un
    # Sonnet retiré ou en fin de vie sont migrés au chargement.
    "claude-3-5-sonnet-20241022":  "claude-sonnet-5-5",
    "claude-3-5-sonnet-20240620":  "claude-sonnet-5-5",
    "claude-3-7-sonnet-20250219":  "claude-sonnet-5-5",
    "claude-sonnet-4-20250514":    "claude-sonnet-5-5",
    "claude-sonnet-4-5":           "claude-sonnet-5-5",
    "claude-sonnet-4-5-20250929":  "claude-sonnet-5-5",
}

# v62.13.9.4.50 — MIGRATION PAR FAMILLE des modèles retirés ou fermés aux nouveaux comptes (au 01/10/2026), appliquée
# aux réglages enregistrés ET aux variables d'environnement (ANTHROPIC_MODEL, OPENAI_MODEL, GOOGLE_MODEL…). Une table
# d'identifiants exacts laissait passer les variantes ; une famille retirée l'est sous tous ses noms.
_FAMILY_MIGRATIONS50 = {
    "anthropic": ((r"claude-3", r"claude-sonnet-4"), "claude-sonnet-5-5"),
    "openai": ((r"gpt-3\.5", r"gpt-4o", r"gpt-4\.1", r"gpt-4-", r"gpt-4$", r"o1", r"o3-mini", r"o4-mini", r"gpt-5\.4-mini"), "gpt-5.4"),
    "google": ((r"gemini-1", r"gemini-2\.0", r"gemini-2\.5", r"gemini-pro$", r"gemini-3-pro-preview"), "gemini-3.6-flash"),
    "grok": ((r"grok-2", r"grok-3", r"grok-4-0709", r"grok-4-fast", r"grok-4-1-fast", r"grok-code-fast"), "grok-4.3"),
    "perplexity": ((r"sonar", r"llama-3", r"pplx-"), "perplexity/sonar"),
}
_FIELD_PROVIDER50 = {"anthropic_model_id": "anthropic", "openai_model_id": "openai", "google_model_id": "google",
                     "grok_model_id": "grok", "perplexity_model_id": "perplexity", "sc_prefilter_model_id": "openai",
                     "sc_primary_model_id": "openai", "sc_challenge_model_id": "google"}


def migrate_model_id(field_or_provider: str, value):
    """Identifiant de modèle à jour pour ce fournisseur (ou ce champ de réglage) ; inchangé s'il n'est pas retiré."""
    import re as _re50
    v = str(value or "").strip()
    prov = _FIELD_PROVIDER50.get(field_or_provider, field_or_provider)
    fam = _FAMILY_MIGRATIONS50.get(prov)
    if not v or not fam:
        return value
    if v.lower().startswith("claude-haiku") or v.lower().startswith("claude-opus"):
        return value                                  # Haiku 4.5 et les Opus restent au choix de l'utilisateur
    for pat in fam[0]:
        if _re50.match(pat, v.lower()):
            return fam[1]
    return value


def env_model_override(provider: str) -> str:
    """Valeur (migrée) de la variable d'environnement qui REMPLACE le réglage pour ce fournisseur, ou "" ."""
    names = {"anthropic": ("ANTHROPIC_MODEL",), "openai": ("OPENAI_MODEL",), "google": ("GOOGLE_MODEL", "GEMINI_MODEL"),
             "mistral": ("MISTRAL_MODEL",), "perplexity": ("PERPLEXITY_MODEL",), "grok": ("GROK_MODEL", "XAI_MODEL")}
    for n in names.get(provider, ()):
        v = (os.getenv(n) or "").strip()
        if v:
            return str(migrate_model_id(provider, v))
    return ""


def load_settings() -> Settings:
    p = get_settings_path()
    d = _safe_read_json(p)
    s = Settings()
    _migrated = False
    for k in s.__dataclass_fields__.keys():
        if k in d:
            val = d[k]
            # Migration automatique des model_id obsolètes
            if k.endswith("_model_id") and val in _MODEL_MIGRATIONS:
                val = _MODEL_MIGRATIONS[val]
                _migrated = True
            if k.endswith("_model_id"):
                _new50 = migrate_model_id(k, val)
                if _new50 != val:
                    val, _migrated = _new50, True
            setattr(s, k, val)

    # Migration numérique v16.3 → v16.5 : upgrade des valeurs trop basses héritées
    if s.attachments_max_files < 20:
        s.attachments_max_files = 20
        _migrated = True
    if s.attachments_max_total_mb < 500:
        s.attachments_max_total_mb = 500
        _migrated = True

    # v62.7 — migration fail-safe du mode PPTX. Une ancienne configuration ne
    # doit jamais réactiver implicitement un rejet corporate du deck de travail.
    # v62.13.9.4.39 — un réglage enregistré à l'ANCIEN défaut (8 000) est relevé au nouveau
    # (50 000) : l'utilisateur n'a jamais choisi 8 000, c'était la valeur d'usine. Une
    # valeur choisie au-dessus de 8 000 est conservée.
    try:
        if int(getattr(s, "attachments_doc_token_budget", 0) or 0) < 120000:
            s.attachments_doc_token_budget = 120000     # 9.4.57 — relevé pour tous les réglages existants
    except Exception:
        s.attachments_doc_token_budget = 120000
    # 9.4.60 — contre-recette du 11/10 : une valeur « Max output tokens » enregistrée sous 8 000 (2 000 sur le PC de
    # recette) est relevée ; elle ne sert plus qu'aux appels auxiliaires, les agents ayant leur propre maximum
    try:
        if int(getattr(s, "max_output_tokens", 0) or 0) < 8000:
            s.max_output_tokens = 8000
    except Exception:
        s.max_output_tokens = 8000
    if str(getattr(s, "pptx_delivery_mode", "working") or "working").lower() not in {"working", "strict"}:
        s.pptx_delivery_mode = "working"
        _migrated = True

    # v62.13.2 — migration Option A -> Option B. Le réglage differentiated
    # n'avait plus d'émetteur produit fiable et créait une divergence Working /
    # Final difficile à auditer. Toute valeur historique est normalisée.
    if str(getattr(s, "numeric_post_control_policy", "strict") or "strict").lower() != "strict":
        s.numeric_post_control_policy = "strict"
        _migrated = True

    # v62.12.8 — migration du nom seul vers un objet structuré minimal.
    if not isinstance(getattr(s, "last_target_entity", None), dict):
        s.last_target_entity = {}
        _migrated = True
    if not s.last_target_entity and str(getattr(s, "last_target_entity_name", "") or "").strip():
        s.last_target_entity = {
            "name": str(s.last_target_entity_name).strip(),
            "source": "legacy_name",
            "confidence": "NAME_ONLY",
        }
        _migrated = True

    # Réécrire le settings.json si migration (met à jour le fichier local)
    if _migrated:
        save_settings(s)
    return s

def save_settings(settings: Settings) -> Path:
    """Persist settings atomically and privately.

    A partial write must never corrupt API/model settings or the remembered
    target. The temporary file is created in the same directory, fsynced,
    chmod 0600 on POSIX, then atomically replaced.
    """
    cfg = ensure_config_dir()
    p = get_settings_path()
    payload = json.dumps(settings.__dict__, indent=2, ensure_ascii=False)
    fd, tmp_name = tempfile.mkstemp(prefix="settings.", suffix=".tmp", dir=str(cfg))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        if os.name == "posix":
            os.chmod(tmp, 0o600)
        os.replace(tmp, p)
        if os.name == "posix":
            os.chmod(p, 0o600)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    return p


def update_last_target_entity(payload: Mapping[str, Any] | None) -> Path:
    """Persist only the remembered target fields.

    The active Streamlit ``Settings`` object may contain session-only values
    such as a retrospective ``analysis_as_of_date``.  Persisting that whole
    object when the user confirms a target would make the session date durable
    and could put later sessions into a phantom retrospective mode.  Reload the
    durable settings, update only the target fields, then save atomically.
    """
    durable = load_settings()
    clean = dict(payload or {})
    name = str(clean.get("name") or "").strip()
    if name:
        clean["name"] = name
    durable.last_target_entity = clean
    durable.last_target_entity_name = name
    return save_settings(durable)
