# -*- coding: utf-8 -*-
"""Lot CONFORMITÉ — marquage des contenus générés (AI Act, article 50).

Obligation visée
----------------
Règlement (UE) 2024/1689, article 50(2) : les fournisseurs de systèmes d'IA
générant du contenu de synthèse — texte compris — marquent les sorties dans
un format LISIBLE PAR MACHINE et détectable comme généré ou manipulé par IA.

Calendrier applicable à CoDIR-IA
--------------------------------
L'article 50 s'applique au 2 août 2026 et n'a PAS été reporté par le Digital
Omnibus (accord politique du 7 mai 2026, qui ne déplace que le haut-risque).
Le seul aménagement porte sur l'article 50(2) : les systèmes DÉJÀ mis sur le
marché au 2 août 2026 disposent d'un sursis jusqu'au 2 DÉCEMBRE 2026.
CoDIR-IA marque ses sorties SANS s'appuyer sur ce sursis (conformité d'abord).
Le sursis 111(4) ne serait invocable que si la mise sur le marché antérieure au
2 août 2026 (publication publique de décembre 2025) est documentée au dossier
légal (dépôt, tag, licence, dates) — preuve à archiver, validation conseil.

Choix de mise en œuvre
----------------------
Le marquage est porté par les PROPRIÉTÉS DE DOCUMENT OOXML (docProps/core.xml),
présentes à l'identique dans .docx et .pptx :

    content_status  marqueur primaire, valeur exacte AI_GENERATED
    category        libellé lisible
    keywords        étiquettes normalisées, séparées par des virgules
    comments        enregistrement STRUCTURÉ clé=valeur, parsable sans schéma

Ce support a trois qualités : il survit à la copie du fichier, il ne dépend
d'aucune bibliothèque tierce, et il se lit sans ouvrir le document (un simple
`unzip -p fichier docProps/core.xml`).

Le marquage machine-readable ne dispense pas de la mention VISIBLE attendue
par les articles 50(1) et 50(4) ; `visible_notice()` fournit ce libellé,
bilingue, pour les pieds de page.

⚠ Ce module n'est pas un avis juridique. Le périmètre exact des obligations
et la qualité de fournisseur relèvent d'une analyse au cas par cas.
"""
from __future__ import annotations

from typing import Optional

# Marqueur primaire — valeur stable, testée, jamais traduite.
AI_MARKER = "AI_GENERATED"

# Clé de l'enregistrement structuré déposé dans `comments`.
_RECORD_KEYS = ("ai_generated", "generator", "provider", "regulation",
                "marking_version")
MARKING_VERSION = "1"

_KEYWORDS = ("AI-generated", "synthetic-content", "EU-AI-Act-Article-50")

_NOTICE = {
    "fr": ("Document produit avec l'assistance d'un système d'intelligence "
           "artificielle (CoDIR-IA). Contenu généré par IA — à vérifier "
           "avant diffusion."),
    "en": ("Document produced with the assistance of an artificial "
           "intelligence system (CoDIR-IA). AI-generated content — verify "
           "before distribution."),
}


def marking_record(generator: str = "CoDIR-IA",
                   version: str = "",
                   provider: str = "") -> str:
    """Enregistrement structuré, une paire clé=valeur par point-virgule.

    Format volontairement trivial à analyser :

        ai_generated=true; generator=CoDIR-IA; generator_version=v17…;
        provider=…; regulation=EU-AI-Act-Art-50(2); marking_version=1
    """
    parts = [
        "ai_generated=true",
        f"generator={generator}",
    ]
    if version:
        parts.append(f"generator_version={version}")
    if provider:
        parts.append(f"provider={provider}")
    parts.append("regulation=EU-AI-Act-Art-50(2)")
    parts.append(f"marking_version={MARKING_VERSION}")
    return "; ".join(parts)


def visible_notice(lang: str = "fr") -> str:
    """Mention VISIBLE pour les pieds de page (articles 50(1) et 50(4))."""
    return _NOTICE.get((lang or "fr").strip().lower()[:2], _NOTICE["fr"])


def apply_marking(container, generator: str = "CoDIR-IA",
                  version: str = "", provider: str = "",
                  title: Optional[str] = None) -> bool:
    """Marque un `docx.Document` ou un `pptx.Presentation`.

    Les deux bibliothèques exposent la MÊME interface `core_properties`,
    ce qui permet un point de marquage unique. Renvoie True si le marquage
    a été posé.

    Le marquage ne doit JAMAIS faire échouer un export : toute anomalie est
    absorbée et signalée par la valeur de retour.
    """
    try:
        props = container.core_properties
    except Exception:
        return False
    try:
        props.content_status = AI_MARKER
        props.category = "AI-generated document"
        props.keywords = ", ".join(_KEYWORDS)
        props.comments = marking_record(generator, version, provider)
        if title and not (getattr(props, "title", "") or "").strip():
            props.title = title
        return True
    except Exception:
        return False


def read_marking(path_or_bytes) -> dict:
    """Relit le marquage d'un fichier OOXML — sert aux tests et à l'audit.

    Renvoie un dictionnaire des paires clé=valeur, plus `content_status`.
    Aucune dépendance : lecture directe de `docProps/core.xml` dans le ZIP.
    """
    import io
    import re
    import zipfile

    src = (io.BytesIO(path_or_bytes)
           if isinstance(path_or_bytes, (bytes, bytearray))
           else path_or_bytes)
    out: dict = {}
    try:
        with zipfile.ZipFile(src) as zf:
            xml = zf.read("docProps/core.xml").decode("utf-8", "replace")
    except Exception:
        return out
    for tag, key in (("contentStatus", "content_status"),
                     ("category", "category"),
                     ("keywords", "keywords"),
                     ("description", "comments")):
        m = re.search(rf"<[^:>]*:?{tag}[^>]*>(.*?)</[^:>]*:?{tag}>", xml,
                      re.S)
        if m:
            out[key] = m.group(1).strip()
    for pair in (out.get("comments") or "").split(";"):
        if "=" in pair:
            k, _s, v = pair.partition("=")
            out[k.strip()] = v.strip()
    return out
