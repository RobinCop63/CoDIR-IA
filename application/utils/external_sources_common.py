"""
CoDIR-IA — utils/external_sources_common.py — v16.5.68

Socle commun pour toutes les sources de données / API externes :
    - Pappers (FR — déjà existant, non touché par cette factorisation)
    - GLEIF / LEI (mondial — sans clé)
    - SEC EDGAR (US — User-Agent requis, sans clé)
    - OpenSanctions (mondial — clé requise)
    - Companies House (UK — clé requise)

OBJECTIF DE CE MODULE
─────────────────────
Factoriser le pattern utilisé par pappers_tool.py pour éviter de dupliquer 4 fois
dans v16.5.68 :
    - cache disque JSON avec TTL et écriture atomique
    - statut "configuré / non configuré" pour la page Config
    - helper requests avec timeout + error handling uniformes
    - dataclass de log de résolution audit-ready

DISCIPLINE
──────────
Ce module N'IMPORTE RIEN de pappers_tool.py et N'EST PAS importé par lui :
le module Pappers v16.5.67 reste strictement intact (zéro régression).
La refactorisation de Pappers vers ExternalSourceCache est repoussée à v16.5.70+
quand on aura suffisamment de modules pour valider l'abstraction.

Architecture :
    ExternalSourceCache(filename, ttl_default)
        Cache JSON disque + TTL + écriture atomique + purge auto + fallback
        corruption JSON. Identique à PappersCache mais paramétré par filename.

    ExternalSourceStatus
        Dataclass uniforme pour la page Config (configured, key_preview,
        last_test_ok, last_test_at, last_test_msg).

    safe_get(url, params, timeout, headers)
        Wrapper requests.get avec timeout, error normalisé en dict.

    make_key_preview(key)
        Affichage uniforme "abcd1234...wxyz" pour les clés API dans la UI.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests

# ── Constantes globales ──────────────────────────────────────────────────────

DEFAULT_TIMEOUT_S = 8
DEFAULT_TTL_SECONDS = 7 * 24 * 3600  # 7 jours par défaut


# ── Cache disque générique ───────────────────────────────────────────────────

class ExternalSourceCache:
    """
    Cache JSON sur disque avec TTL paramétrable et écriture atomique.

    Différence avec PappersCache (v16.5.67) :
      - Filename paramétrable (un fichier par source : gleif_cache.json,
        sec_edgar_cache.json, etc.)
      - TTL par défaut configurable à la construction (override possible
        à chaque appel get())
      - Même contrat d'API : get / set / age_hours / purge_expired

    Exemple :
        cache = ExternalSourceCache("gleif_cache.json", ttl_default=7*86400)
        if (data := cache.get("lei_5493001KJTIIGC8Y1R12")) is None:
            data = fetch_lei_record(...)
            cache.set("lei_5493001KJTIIGC8Y1R12", data)
    """

    def __init__(self, filename: str, ttl_default: int = DEFAULT_TTL_SECONDS):
        if not filename or "/" in filename or "\\" in filename:
            raise ValueError(f"filename must be a basename, got: {filename!r}")
        from utils.config_paths import ensure_cache_dir
        cache_dir = ensure_cache_dir()
        self._path: Path = cache_dir / filename
        self._ttl_default: int = int(ttl_default)
        self._data: dict = {}
        self._loaded: bool = False

    # ── I/O privé ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._loaded:
            return
        try:
            if self._path.exists():
                with open(self._path, "r", encoding="utf-8") as f:
                    self._data = json.loads(f.read())
        except (json.JSONDecodeError, ValueError):
            # Fichier corrompu → on déplace en .bak et on repart à zéro
            try:
                self._path.rename(self._path.with_suffix(".bak"))
            except Exception:
                pass
            self._data = {}
        except Exception:
            self._data = {}
        self._loaded = True

    def _save(self) -> None:
        try:
            # v16.5.76 Phase 7a (VULN-5) — dossier 0o700 sur POSIX (fail-open)
            try:
                from utils.config_paths import ensure_private_dir as _epd
                _epd(self._path.parent)
            except Exception:
                self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            tmp.replace(self._path)
        except Exception:
            pass

    # ── API publique ─────────────────────────────────────────────────────────

    def get(self, key: str, ttl_seconds: Optional[int] = None) -> Optional[Any]:
        """Retourne la valeur cachée si non expirée, sinon None."""
        self._load()
        entry = self._data.get(key)
        if not entry:
            return None
        ttl = self._ttl_default if ttl_seconds is None else int(ttl_seconds)
        age = time.time() - entry.get("fetched_at", 0)
        if age > ttl:
            del self._data[key]
            return None
        return entry.get("value")

    def set(self, key: str, value: Any) -> None:
        """Stocke la valeur avec timestamp courant et persiste atomiquement."""
        self._load()
        self._data[key] = {"value": value, "fetched_at": time.time()}
        self._save()

    def age_hours(self, key: str) -> Optional[float]:
        """Âge du cache en heures, ou None si absent."""
        self._load()
        entry = self._data.get(key)
        if not entry:
            return None
        return round((time.time() - entry.get("fetched_at", 0)) / 3600, 1)

    def has(self, key: str, ttl_seconds: Optional[int] = None) -> bool:
        """True si entrée présente ET non expirée."""
        return self.get(key, ttl_seconds) is not None

    def purge_expired(self, max_age_seconds: int = 30 * 24 * 3600) -> int:
        """Supprime les entrées plus vieilles que max_age_seconds. Retourne le nb purgé."""
        self._load()
        now = time.time()
        expired = [k for k, v in self._data.items()
                   if isinstance(v, dict) and now - v.get("fetched_at", 0) > max_age_seconds]
        for k in expired:
            del self._data[k]
        if expired:
            self._save()
        return len(expired)

    @property
    def path(self) -> Path:
        """Chemin du fichier cache (utile pour tests / debug)."""
        return self._path


# ── Statut uniforme pour la page Config ──────────────────────────────────────

@dataclass
class ExternalSourceStatus:
    """
    Statut uniforme d'une source externe pour affichage UI.

    Sources sans clé (GLEIF, SEC EDGAR avec User-Agent par défaut) :
        configured = True (toujours)
        key_preview = "" (rien à afficher)
        requires_user_agent = True pour SEC EDGAR

    Sources avec clé (OpenSanctions, Companies House, Pappers) :
        configured = bool(key)
        key_preview = "abcd...wxyz" si configured

    Test de connexion :
        last_test_ok / last_test_at / last_test_msg sont mis à jour
        après un appel à test_connection() de chaque module.
    """
    name: str
    configured: bool
    requires_key: bool = True
    key_preview: str = ""
    requires_user_agent: bool = False
    user_agent_set: bool = False
    last_test_ok: Optional[bool] = None
    last_test_at: str = ""
    last_test_msg: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Helpers communs ──────────────────────────────────────────────────────────

def make_key_preview(key: str) -> str:
    """
    Affichage standard d'une clé API en UI : "abcdefgh...wxyz".
    Cohérent avec le format actuel de get_pappers_status() (8 + 4).
    Retourne "****" si clé trop courte.
    """
    if not key:
        return ""
    s = str(key).strip()
    if len(s) <= 12:
        return "****"
    return f"{s[:8]}...{s[-4:]}"


def safe_get(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT_S,
) -> Dict[str, Any]:
    """
    Wrapper requests.get avec error handling uniforme.

    Retourne TOUJOURS un dict :
        - succès : {"ok": True, "status_code": 200, "data": <json|text>, "elapsed_ms": int}
        - échec  : {"ok": False, "error": "<type>", "message": "<details>"}

    error ∈ {timeout, connection_error, http_error, json_decode_error,
             unexpected_error}

    Garantie : ne lève JAMAIS d'exception. Pas besoin de try/except côté appelant.
    """
    t0 = time.time()
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        elapsed_ms = int((time.time() - t0) * 1000)
        if r.status_code >= 400:
            return {
                "ok": False,
                "error": "http_error",
                "status_code": r.status_code,
                "message": r.text[:300] if r.text else f"HTTP {r.status_code}",
                "elapsed_ms": elapsed_ms,
            }
        # Tentative parsing JSON ; si échec, retourne le texte brut
        try:
            data = r.json()
        except (ValueError, json.JSONDecodeError):
            data = r.text
        return {
            "ok": True,
            "status_code": r.status_code,
            "data": data,
            "elapsed_ms": elapsed_ms,
        }
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "timeout", "message": f"Timeout après {timeout}s"}
    except requests.exceptions.ConnectionError as e:
        return {"ok": False, "error": "connection_error", "message": str(e)[:200]}
    except Exception as e:
        return {"ok": False, "error": "unexpected_error", "message": str(e)[:200]}


def safe_get_bytes(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 30,
    max_size_mb: int = 25,
    allow_redirects: bool = True,
) -> Dict[str, Any]:
    """
    Since v16.5.69 — Variant binaire de safe_get pour téléchargement de PDFs/XHTML.

    Différences avec safe_get :
      - Retourne des bytes bruts (pas de tentative parsing JSON)
      - Timeout par défaut plus long (30s) car les PDFs Companies House peuvent
        peser plusieurs Mo
      - Suit les redirections (Companies House Document API renvoie un 302
        vers un signed URL S3)
      - Limite de taille (25 Mo par défaut) pour éviter les téléchargements
        accidentels gigantesques
      - Renseigne `content_type` et `bytes_length`

    Retourne TOUJOURS un dict :
        - succès : {"ok": True, "status_code": 200, "content": <bytes>,
                    "content_type": str, "bytes_length": int, "elapsed_ms": int}
        - trop gros : {"ok": False, "error": "size_limit_exceeded", ...}
        - échec : {"ok": False, "error": "<type>", "message": "<details>"}

    Garantie : ne lève JAMAIS d'exception.
    """
    t0 = time.time()
    try:
        r = requests.get(
            url, params=params, headers=headers,
            timeout=timeout, allow_redirects=allow_redirects, stream=True,
        )
        elapsed_ms = int((time.time() - t0) * 1000)

        if r.status_code >= 400:
            # Lire un fragment du body pour le message d'erreur
            try:
                msg = r.text[:300] if r.text else f"HTTP {r.status_code}"
            except Exception:
                msg = f"HTTP {r.status_code}"
            return {
                "ok": False, "error": "http_error",
                "status_code": r.status_code,
                "message": msg,
                "elapsed_ms": elapsed_ms,
            }

        # Vérifier Content-Length avant de lire (gardes-fou)
        max_bytes = max_size_mb * 1024 * 1024
        content_length = r.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > max_bytes:
                    return {
                        "ok": False, "error": "size_limit_exceeded",
                        "message": f"Document {int(content_length) / 1024 / 1024:.1f}Mo > limite {max_size_mb}Mo",
                        "elapsed_ms": elapsed_ms,
                    }
            except (ValueError, TypeError):
                pass

        # Lire le contenu en streaming avec garde de taille
        chunks: list = []
        total = 0
        for chunk in r.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                return {
                    "ok": False, "error": "size_limit_exceeded",
                    "message": f"Document dépasse la limite {max_size_mb}Mo en cours de téléchargement",
                    "elapsed_ms": int((time.time() - t0) * 1000),
                }
            chunks.append(chunk)
        content = b"".join(chunks)

        return {
            "ok": True,
            "status_code": r.status_code,
            "content": content,
            "content_type": r.headers.get("Content-Type", "application/octet-stream"),
            "bytes_length": len(content),
            "elapsed_ms": int((time.time() - t0) * 1000),
        }
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "timeout",
                "message": f"Timeout après {timeout}s"}
    except requests.exceptions.ConnectionError as e:
        return {"ok": False, "error": "connection_error",
                "message": str(e)[:200]}
    except Exception as e:
        return {"ok": False, "error": "unexpected_error",
                "message": str(e)[:200]}


def now_iso() -> str:
    """Timestamp ISO 8601 UTC pour les logs et les statuts."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Registre des sources (pour la page Config et la persistance des tests) ──

# Catalogue des sources externes connues (Since v16.5.68).
# Utilisé par la page Config pour afficher la liste de manière déterministe
# et par les tests pour vérifier qu'aucune source n'a été oubliée.
EXTERNAL_SOURCES_CATALOG: Dict[str, Dict[str, Any]] = {
    "pappers": {
        "label": "Pappers",
        "country": "FR",
        "scope": "France — INSEE / INPI / BODACC",
        "requires_key": True,
        "requires_user_agent": False,
        "implemented_in": "v16.5.59",
    },
    "gleif": {
        "label": "GLEIF / LEI",
        "country": "WW",
        "scope": "Mondial — Identifiant d'entité juridique (LEI)",
        "requires_key": False,
        "requires_user_agent": False,
        "implemented_in": "v16.5.68",
    },
    "sec_edgar": {
        "label": "SEC EDGAR",
        "country": "US",
        "scope": "États-Unis — Sociétés cotées (10-K, 10-Q, 8-K)",
        "requires_key": False,
        "requires_user_agent": True,
        "implemented_in": "v16.5.68",
    },
    "opensanctions": {
        "label": "OpenSanctions",
        "country": "WW",
        "scope": "Mondial — Sanctions, PEP, watchlists",
        "requires_key": True,
        "requires_user_agent": False,
        "implemented_in": "v16.5.68",
    },
    "companies_house": {
        "label": "Companies House (Public Data)",
        "country": "UK",
        "scope": "Royaume-Uni — Registre des sociétés (profil + filing history)",
        "requires_key": True,
        "requires_user_agent": False,
        "implemented_in": "v16.5.68",
    },
    "companies_house_document": {
        "label": "Companies House (Document API)",
        "country": "UK",
        "scope": "Royaume-Uni — Téléchargement des documents filing (PDF / XHTML)",
        "requires_key": True,
        "requires_user_agent": False,
        "implemented_in": "v16.5.68",
    },
}


# ── Persistance optionnelle des derniers tests de connexion ─────────────────

def get_test_results_path() -> Path:
    """Chemin du fichier de persistance des résultats de tests de connexion."""
    base = Path(os.environ.get("CODIR_CONFIG_DIR", "")).expanduser() if os.environ.get("CODIR_CONFIG_DIR") else None
    if base is None:
        # Réutiliser la même logique que config_paths.get_config_dir() sans dépendance circulaire
        try:
            from .config_paths import get_config_dir
            base = get_config_dir()
        except Exception:
            from .config_paths import ensure_config_dir
            base = ensure_config_dir()
    return base / "external_sources_tests.json"


def save_test_result(source_id: str, ok: bool, message: str = "") -> None:
    """Persiste le dernier résultat de test pour une source. Best-effort."""
    if source_id not in EXTERNAL_SOURCES_CATALOG:
        return
    try:
        path = get_test_results_path()
        # v16.5.76 Phase 7a (VULN-5) — dossier 0o700 sur POSIX (fail-open)
        try:
            from utils.config_paths import ensure_private_dir as _epd
            _epd(path.parent)
        except Exception:
            path.parent.mkdir(parents=True, exist_ok=True)
        existing: Dict[str, Any] = {}
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        existing[source_id] = {
            "ok": bool(ok),
            "at": now_iso(),
            "message": str(message)[:200],
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def load_test_result(source_id: str) -> Optional[Dict[str, Any]]:
    """Charge le dernier résultat de test pour une source, ou None."""
    try:
        path = get_test_results_path()
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get(source_id)
    except Exception:
        return None


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_TTL_SECONDS",
    "ExternalSourceCache",
    "ExternalSourceStatus",
    "EXTERNAL_SOURCES_CATALOG",
    "make_key_preview",
    "safe_get",
    "safe_get_bytes",  # Since v16.5.69 — téléchargement binaire (PDF/XHTML)
    "now_iso",
    "get_test_results_path",
    "save_test_result",
    "load_test_result",
]
