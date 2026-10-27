from __future__ import annotations
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config_paths import ensure_config_dir, get_secrets_path, candidate_config_dirs

@dataclass
class Secrets:
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    google_api_key: str = ""
    gemini_api_key: str = ""       # alias, optional
    mistral_api_key: str = ""
    perplexity_api_key: str = ""   # v16.5 — Synthèse des décisions
    grok_api_key: str = ""         # v16.5 — Direction Commerciale (xAI)
    pappers_api_key: str = ""      # v16.5.59 — Enrichissement données entreprises FR

    # ── v16.5.68 — Sources de données / API externes additionnelles ──────────
    # GLEIF n'a pas de clé (API publique mondiale).
    opensanctions_api_key: str = ""    # v16.5.68 — Sanctions / PEP / watchlists (mondial)
    companies_house_api_key: str = ""  # v16.5.68 — Companies House Public Data API (UK — registre + filing history)
    companies_house_document_api_key: str = ""  # v16.5.68 — Companies House Document API (UK — téléchargement PDFs/XHTML des filings)
    sec_edgar_user_agent: str = ""     # v16.5.68 — User-Agent requis par SEC.gov pour EDGAR
                                       # Format recommandé : "Nom Prenom contact@email.com"

    def to_env(self) -> Dict[str, str]:
        env: Dict[str, str] = {}
        if self.openai_api_key:
            env["OPENAI_API_KEY"] = self.openai_api_key
        if self.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = self.anthropic_api_key
        if self.google_api_key:
            env["GOOGLE_API_KEY"] = self.google_api_key
        if self.gemini_api_key and "GOOGLE_API_KEY" not in env:
            env["GEMINI_API_KEY"] = self.gemini_api_key
        if self.mistral_api_key:
            env["MISTRAL_API_KEY"] = self.mistral_api_key
        if self.perplexity_api_key:
            env["PERPLEXITY_API_KEY"] = self.perplexity_api_key
        if self.grok_api_key:
            env["GROK_API_KEY"] = self.grok_api_key
            env["XAI_API_KEY"] = self.grok_api_key
        if self.pappers_api_key:
            env["PAPPERS_API_KEY"] = self.pappers_api_key
        # v16.5.68 — Sources externes additionnelles
        if self.opensanctions_api_key:
            env["OPENSANCTIONS_API_KEY"] = self.opensanctions_api_key
        if self.companies_house_api_key:
            env["COMPANIES_HOUSE_API_KEY"] = self.companies_house_api_key
        if self.companies_house_document_api_key:
            env["COMPANIES_HOUSE_DOCUMENT_API_KEY"] = self.companies_house_document_api_key
        if self.sec_edgar_user_agent:
            env["SEC_EDGAR_USER_AGENT"] = self.sec_edgar_user_agent
        return env

    @classmethod
    def managed_env_keys(cls) -> list[str]:
        """
        Patch v16.5.69.1 (audit ChatGPT round 3) — Liste exhaustive des
        variables d'environnement potentiellement gérées par CoDIR-IA.

        Utilisée par apply_secrets_to_env(override=True) pour nettoyer
        os.environ avant d'appliquer les nouvelles valeurs. Ce nettoyage
        explicite est nécessaire parce que to_env() ne retourne PAS les
        clés vides : sans pop() préalable, une ancienne clé chargée d'un
        précédent secrets.json restait indéfiniment dans os.environ même
        après que l'utilisateur l'ait vidée — court-circuitant les fallbacks
        gracieux (cas typique : COMPANIES_HOUSE_DOCUMENT_API_KEY obsolète
        qui empêchait le fallback sur COMPANIES_HOUSE_API_KEY).

        Note Google/Gemini : ce sont 2 variables distinctes même si
        sémantiquement l'une est l'alias de l'autre dans to_env() — il faut
        donc lister les deux pour le nettoyage. Idem GROK/XAI.

        Cette liste est la SOURCE DE VÉRITÉ pour toutes les clés env
        gérées. Toute nouvelle clé ajoutée à to_env() v16.5.70+ devra être
        ajoutée ici aussi (test test_managed_env_keys_complete vérifie cette
        cohérence pour empêcher l'oubli silencieux).
        """
        return [
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",        # alias Google, var distincte dans os.environ
            "MISTRAL_API_KEY",
            "PERPLEXITY_API_KEY",
            "GROK_API_KEY",
            "XAI_API_KEY",           # alias Grok, var distincte dans os.environ
            "PAPPERS_API_KEY",
            "OPENSANCTIONS_API_KEY",
            "COMPANIES_HOUSE_API_KEY",
            "COMPANIES_HOUSE_DOCUMENT_API_KEY",
            "SEC_EDGAR_USER_AGENT",
        ]

def _safe_read_json(p: Path) -> Dict[str, Any]:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def load_secrets() -> Secrets:
    data = {}
    for p in candidate_config_dirs():
        data = _safe_read_json(p / "secrets.json")
        if data:
            break
    return Secrets(
        openai_api_key=str(data.get("OPENAI_API_KEY") or data.get("openai_api_key") or ""),
        anthropic_api_key=str(data.get("ANTHROPIC_API_KEY") or data.get("anthropic_api_key") or ""),
        google_api_key=str(data.get("GOOGLE_API_KEY") or data.get("google_api_key") or ""),
        gemini_api_key=str(data.get("GEMINI_API_KEY") or data.get("gemini_api_key") or ""),
        mistral_api_key=str(data.get("MISTRAL_API_KEY") or data.get("mistral_api_key") or ""),
        perplexity_api_key=str(data.get("PERPLEXITY_API_KEY") or data.get("perplexity_api_key") or ""),
        grok_api_key=str(data.get("GROK_API_KEY") or data.get("XAI_API_KEY") or data.get("grok_api_key") or ""),
        pappers_api_key=str(data.get("PAPPERS_API_KEY") or data.get("pappers_api_key") or ""),
        # v16.5.68 — sources externes additionnelles ; rétro-compat : si absent du JSON, valeur vide
        opensanctions_api_key=str(data.get("OPENSANCTIONS_API_KEY") or data.get("opensanctions_api_key") or ""),
        companies_house_api_key=str(data.get("COMPANIES_HOUSE_API_KEY") or data.get("companies_house_api_key") or ""),
        companies_house_document_api_key=str(data.get("COMPANIES_HOUSE_DOCUMENT_API_KEY") or data.get("companies_house_document_api_key") or ""),
        sec_edgar_user_agent=str(data.get("SEC_EDGAR_USER_AGENT") or data.get("sec_edgar_user_agent") or ""),
    )

def save_secrets(secrets: Secrets) -> Path:
    ensure_config_dir()
    p = get_secrets_path()
    payload = {
        "OPENAI_API_KEY":           secrets.openai_api_key.strip(),
        "ANTHROPIC_API_KEY":        secrets.anthropic_api_key.strip(),
        "GOOGLE_API_KEY":           secrets.google_api_key.strip(),
        "GEMINI_API_KEY":           secrets.gemini_api_key.strip(),
        "MISTRAL_API_KEY":          secrets.mistral_api_key.strip(),
        "PERPLEXITY_API_KEY":       secrets.perplexity_api_key.strip(),
        "GROK_API_KEY":             secrets.grok_api_key.strip(),
        "PAPPERS_API_KEY":          secrets.pappers_api_key.strip(),
        # v16.5.68
        "OPENSANCTIONS_API_KEY":    secrets.opensanctions_api_key.strip(),
        "COMPANIES_HOUSE_API_KEY":           secrets.companies_house_api_key.strip(),
        "COMPANIES_HOUSE_DOCUMENT_API_KEY":  secrets.companies_house_document_api_key.strip(),
        "SEC_EDGAR_USER_AGENT":              secrets.sec_edgar_user_agent.strip(),
    }
    tmp = p.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    # v16.5.76 Phase 7a (audit sécurité 25 mai 2026, VULN-1 validée ChatGPT) :
    # Restreindre les permissions du fichier secrets.json à 0o600 (rw user
    # uniquement) sur POSIX AVANT le replace atomique. Sans ce chmod, le
    # fichier hérite de l'umask par défaut (souvent 0o644 = world-readable),
    # ce qui exposerait les 7-12 clés API stockées à tout user local sur Mac
    # multi-utilisateurs / VM partagée / environnement client.
    # Sur Windows, os.chmod n'a pas d'effet sur les ACL — la mitigation
    # native (Windows Credential Manager) est tracée comme chantier v17.
    if os.name == 'posix':
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            # Fail-open : si le chmod échoue (FS exotique, droits restreints),
            # on continue avec le replace pour ne pas casser la sauvegarde.
            pass

    tmp.replace(p)

    # Double vérification post-replace : sur certains systèmes, replace peut
    # restaurer les permissions du fichier cible existant. On force à nouveau
    # 0o600 si nécessaire.
    if os.name == 'posix':
        try:
            current_mode = p.stat().st_mode & 0o777
            if current_mode & 0o077 != 0:  # group/other ont des bits → corriger
                os.chmod(p, 0o600)
        except OSError:
            pass

    saved = _safe_read_json(p)
    expected = payload.get("PAPPERS_API_KEY", "")
    if saved.get("PAPPERS_API_KEY", "") != expected:
        raise RuntimeError(f"Secrets save verification failed for {p}")
    return p

def apply_secrets_to_env(secrets: Optional[Secrets] = None, override: bool = False) -> Secrets:
    """
    Charge les valeurs Secrets dans os.environ.

    Patch v16.5.69.1 (audit ChatGPT round 3) — En mode override=True, on
    nettoie EXPLICITEMENT toutes les variables d'environnement gérées
    AVANT de remettre les nouvelles valeurs. Sans cela, une clé pre-existante
    dans os.environ (chargée d'un précédent secrets.json puis vidée par
    l'utilisateur) restait silencieusement, court-circuitant les fallbacks
    gracieux comme celui de Companies House Document → Public Data.

    En mode override=False, comportement inchangé (rétro-compat) : on ne
    set que les variables non encore présentes dans l'env.
    """
    if secrets is None:
        secrets = load_secrets()
    import os
    # Patch v16.5.69.1 — Nettoyage explicite en mode override pour fiabiliser
    # les rotations de clés en session courante (UX correction Document API).
    if override:
        for k in Secrets.managed_env_keys():
            os.environ.pop(k, None)
    env_map = secrets.to_env()
    for k, v in env_map.items():
        if override or not os.getenv(k):
            os.environ[k] = v
    return secrets

def has_any_key(secrets: Optional[Secrets] = None) -> bool:
    """True si au moins une clé API est configurée (LLM ou source de données externe)."""
    s = secrets or load_secrets()
    return any([
        bool(s.openai_api_key.strip()),
        bool(s.anthropic_api_key.strip()),
        bool(s.google_api_key.strip() or s.gemini_api_key.strip()),
        bool(s.mistral_api_key.strip()),
        bool(s.perplexity_api_key.strip()),
        bool(s.grok_api_key.strip()),
        bool(s.pappers_api_key.strip()),         # v16.5.59
        bool(s.opensanctions_api_key.strip()),                # v16.5.68
        bool(s.companies_house_api_key.strip()),               # v16.5.68 — Public Data API
        bool(s.companies_house_document_api_key.strip()),      # v16.5.68 — Document API
        # SEC EDGAR User-Agent et GLEIF (no key) ne comptent pas comme "clé configurée"
        # car ils ne nécessitent pas de saisie obligatoire.
    ])

def has_llm_key(secrets: Optional[Secrets] = None) -> bool:
    """True si au moins une clé LLM est configurée (nécessaire pour lancer une session CoDIR)."""
    s = secrets or load_secrets()
    return any([
        bool(s.openai_api_key.strip()),
        bool(s.anthropic_api_key.strip()),
        bool(s.google_api_key.strip() or s.gemini_api_key.strip()),
        bool(s.mistral_api_key.strip()),
        bool(s.perplexity_api_key.strip()),
        bool(s.grok_api_key.strip()),
    ])
