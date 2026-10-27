"""
patches/upload_format_guard.py — M.5.9 (FIX A, retex run dossier de conseil M.5.8)

Validation des pièces jointes par le CONTENU (magic bytes), pas seulement par
l'extension. Motivation : sous Windows, les noms courts 8.3 tronquent .docx→~1.DOC
et .pptx→~1.PPT ; la validation par extension (M.5.8) rejetait alors à tort des
fichiers OOXML modernes valides, et le run réel se retrouvait « Sans pièce jointe ».

Règles :
  - en-tête PK\\x03\\x04 (ZIP)  → OOXML moderne (docx/pptx/xlsx) : ACCEPTÉ, et si
    l'extension est tronquée (.doc/.ppt/.xls), on NORMALISE le nom (.docx/.pptx/.xlsx)
    pour que le routeur par extension en aval lise le bon format ;
  - en-tête D0 CF 11 E0 (OLE2) → vrai ancien .doc/.ppt/.xls : REJETÉ (convertir) ;
  - .pdf/.csv/.txt/.md         → acceptés par extension (pas de sniff Office) ;
  - sinon                       → si extension OOXML connue, accepté ; sinon rejeté.
"""
from __future__ import annotations

import io
import os
import zipfile
from typing import List, Optional, Tuple

_ZIP_MAGIC = b"PK\x03\x04"
_OLE2_MAGIC = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"

_PLAIN_EXT = {".pdf", ".csv", ".txt", ".md"}
_MODERN_OOXML_EXT = {".docx", ".pptx", ".xlsx", ".xlsm"}
# Extension héritée (ou tronquée 8.3) → extension OOXML moderne cible.
_LEGACY_TO_MODERN = {".doc": ".docx", ".ppt": ".pptx", ".xls": ".xlsx"}
_LEGACY_LABEL = {".doc": "Word", ".ppt": "PowerPoint", ".xls": "Excel"}


def sniff_office_format(data: bytes) -> str:
    """'ooxml' (zip moderne), 'ole2' (legacy binaire), ou 'other'."""
    if not data:
        return "other"
    if data[:4] == _ZIP_MAGIC:
        return "ooxml"
    if data[:8] == _OLE2_MAGIC:
        return "ole2"
    return "other"


def detect_ooxml_kind(data: bytes) -> Optional[str]:
    """M.5.9.1 (durcissement, retex audit M.5.9) — un en-tête ZIP ne suffit PAS :
    un .zip/.png/.bin quelconque commence aussi par « PK\\x03\\x04 ». On inspecte le
    CONTENU du ZIP pour confirmer un OOXML et déterminer le vrai type :
      - word/document.xml   → .docx
      - ppt/presentation.xml → .pptx
      - xl/workbook.xml      → .xlsx (.xlsm si macros vbaProject.bin)
    [Content_Types].xml est toujours présent dans un OOXML — sa présence sert de
    garde-fou. Renvoie l'extension OOXML, ou None si ce n'est pas un document Office."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
    except Exception:
        return None
    if "[Content_Types].xml" not in names:
        return None
    if "word/document.xml" in names:
        return ".docx"
    if "ppt/presentation.xml" in names:
        return ".pptx"
    if "xl/workbook.xml" in names:
        return ".xlsm" if "xl/vbaProject.bin" in names else ".xlsx"
    return None


class RenamedUpload:
    """Proxy d'un fichier uploadé Streamlit avec un nom corrigé (extension
    normalisée). Transmet getvalue/read/seek et tout autre attribut au fichier
    d'origine, mais expose un .name corrigé pour le routeur par extension."""

    def __init__(self, f, new_name: str):
        self._f = f
        self.name = new_name

    def getvalue(self):
        return self._f.getvalue()

    def read(self, *a, **k):
        return self._f.read(*a, **k)

    def seek(self, *a, **k):
        return self._f.seek(*a, **k)

    @property
    def size(self):
        try:
            return self._f.size
        except Exception:
            return len(self._f.getvalue())

    def __getattr__(self, k):
        return getattr(self._f, k)


def _msg(name: str, why_fr: str, why_en: str, lang: str) -> Tuple[str, str]:
    return (name, why_fr if lang != "en" else why_en)


def validate_uploads(uploaded, lang: str = "fr") -> Tuple[list, List[Tuple[str, str]]]:
    """Renvoie (accepted, rejected). accepted = liste de fichiers (éventuellement
    renommés). rejected = liste de (nom, raison)."""
    accepted, rejected = [], []
    for f in (uploaded or []):
        name = getattr(f, "name", "") or ""
        ext = os.path.splitext(name)[1].lower()
        if ext in _PLAIN_EXT:
            accepted.append(f)
            continue
        try:
            data = f.getvalue()
        except Exception:
            data = b""
        kind = sniff_office_format(data)
        if kind == "ooxml":
            # M.5.9.1 — on inspecte la STRUCTURE INTERNE : un ZIP n'est accepté que
            # s'il est un vrai OOXML. Le CONTENU prime sur l'extension (gère 8.3 :
            # ~1.DOC dont le contenu est un .docx). Un ZIP non-OOXML est REJETÉ —
            # jamais renommé en .docx par défaut (faille corrigée).
            detected = detect_ooxml_kind(data)
            if detected is None:
                rejected.append(_msg(
                    name,
                    "archive ZIP non reconnue comme document Office (docx/pptx/xlsx) — non chargée",
                    "ZIP archive not recognized as an Office document (docx/pptx/xlsx) — not loaded",
                    lang))
                continue
            if ext != detected:
                base = os.path.splitext(name)[0]
                accepted.append(RenamedUpload(f, base + detected))
            else:
                accepted.append(f)
        elif kind == "ole2":
            lbl = _LEGACY_LABEL.get(ext, "Office")
            rejected.append(_msg(
                name,
                f"vrai ancien format Office {lbl} (binaire OLE2) — convertir en .docx/.pptx/.xlsx",
                f"genuine legacy Office {lbl} (OLE2 binary) — convert to .docx/.pptx/.xlsx",
                lang))
        else:
            if ext in _MODERN_OOXML_EXT:
                accepted.append(f)   # extension moderne fiable, sniff non concluant
            else:
                rejected.append(_msg(
                    name, "format non reconnu", "unrecognized format", lang))
    return accepted, rejected
