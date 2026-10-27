"""Technical integrity validation for serialized PPTX packages.

The layout guard answers an editorial question (is the deck pleasant and
readable?).  This module answers a different, stricter question: is the OOXML
package structurally valid and therefore safe to expose as an editable PPTX?

Only objective package defects are release blockers here: malformed XML,
missing relationship targets, missing required parts, duplicate non-visual
shape identifiers, or negative drawing extents.  Content-density and visual
quality findings belong to ``deck_layout_guard`` and remain warnings.
"""
from __future__ import annotations

from collections import Counter
from io import BytesIO
import posixpath
from typing import Any, Dict, Iterable, Optional
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET
import zipfile


_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_REQUIRED_PARTS = (
    "[Content_Types].xml",
    "_rels/.rels",
    "ppt/presentation.xml",
    "ppt/_rels/presentation.xml.rels",
)


def _source_part_from_rels(rels_name: str) -> Optional[str]:
    """Return the owning OOXML part for a ``*.rels`` entry.

    ``_rels/.rels`` owns the package root.  A part relationship such as
    ``ppt/slides/_rels/slide1.xml.rels`` owns ``ppt/slides/slide1.xml``.
    """
    if rels_name == "_rels/.rels":
        return ""
    marker = "/_rels/"
    if marker not in rels_name or not rels_name.endswith(".rels"):
        return None
    parent, rel_file = rels_name.split(marker, 1)
    return posixpath.join(parent, rel_file[:-5])


def _resolved_target(source_part: str, target: str) -> Optional[str]:
    raw = unquote(str(target or "").strip())
    if not raw or raw.startswith("#"):
        return None
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc:
        return None
    path = parsed.path
    if path.startswith("/"):
        joined = path.lstrip("/")
    else:
        base_dir = posixpath.dirname(source_part) if source_part else ""
        joined = posixpath.join(base_dir, path)
    normalized = posixpath.normpath(joined).lstrip("/")
    if normalized.startswith("../") or normalized == "..":
        return None
    return normalized


def _iter_slide_parts(names: Iterable[str]) -> list[str]:
    return sorted(
        n for n in names
        if n.startswith("ppt/slides/slide") and n.endswith(".xml")
        and "/_rels/" not in n
    )


def validate_pptx_package(pptx_bytes: bytes) -> Dict[str, Any]:
    """Validate the serialized PPTX package without mutating it.

    The report is deliberately JSON-serializable and fail-closed.  A caller may
    safely use ``report['ok']`` as the technical editability gate.
    """
    report: Dict[str, Any] = {
        "ok": False,
        "size_bytes": len(pptx_bytes or b""),
        "zip_entries": 0,
        "slide_count": 0,
        "required_parts_missing": [],
        "duplicate_zip_entries": [],
        "bad_xml_parts": [],
        "missing_relationship_targets": [],
        "unresolved_presentation_slide_ids": [],
        "duplicate_shape_ids": [],
        "negative_extents": [],
        "errors": [],
        "warnings": [],
    }
    raw = bytes(pptx_bytes or b"")
    if not raw:
        report["errors"].append("empty_pptx_bytes")
        return report
    if not raw.startswith(b"PK"):
        report["errors"].append("not_a_zip_package")
        return report

    try:
        with zipfile.ZipFile(BytesIO(raw), "r") as zf:
            infos = zf.infolist()
            names = [i.filename for i in infos]
            name_set = set(names)
            report["zip_entries"] = len(names)
            dupes = sorted(n for n, count in Counter(names).items() if count > 1)
            report["duplicate_zip_entries"] = dupes
            report["required_parts_missing"] = [
                part for part in _REQUIRED_PARTS if part not in name_set
            ]
            bad_member = zf.testzip()
            if bad_member:
                report["errors"].append(f"zip_crc_error:{bad_member}")

            xml_roots: Dict[str, ET.Element] = {}
            for name in names:
                if not (name.endswith(".xml") or name.endswith(".rels")):
                    continue
                try:
                    xml_roots[name] = ET.fromstring(zf.read(name))
                except Exception as exc:
                    report["bad_xml_parts"].append(
                        {"part": name, "error": f"{type(exc).__name__}:{exc}"}
                    )

            # Every internal relationship target must exist in the package.
            for rels_name, root in xml_roots.items():
                if not rels_name.endswith(".rels"):
                    continue
                source_part = _source_part_from_rels(rels_name)
                if source_part is None:
                    report["warnings"].append(f"unmapped_relationship_part:{rels_name}")
                    continue
                for rel in root.findall(f"{{{_REL_NS}}}Relationship"):
                    if str(rel.attrib.get("TargetMode", "")).lower() == "external":
                        continue
                    resolved = _resolved_target(source_part, rel.attrib.get("Target", ""))
                    if resolved and resolved not in name_set:
                        report["missing_relationship_targets"].append({
                            "rels": rels_name,
                            "id": rel.attrib.get("Id", ""),
                            "target": rel.attrib.get("Target", ""),
                            "resolved": resolved,
                        })

            # Presentation slide IDs must resolve to concrete slide parts.
            p_root = xml_roots.get("ppt/presentation.xml")
            p_rels = xml_roots.get("ppt/_rels/presentation.xml.rels")
            if p_root is not None and p_rels is not None:
                rel_map = {
                    rel.attrib.get("Id", ""): _resolved_target(
                        "ppt/presentation.xml", rel.attrib.get("Target", "")
                    )
                    for rel in p_rels.findall(f"{{{_REL_NS}}}Relationship")
                    if str(rel.attrib.get("TargetMode", "")).lower() != "external"
                }
                slide_ids = p_root.findall(
                    f".//{{{_P_NS}}}sldIdLst/{{{_P_NS}}}sldId"
                )
                for node in slide_ids:
                    rid = node.attrib.get(f"{{{_R_NS}}}id", "")
                    target = rel_map.get(rid)
                    if not target or target not in name_set:
                        report["unresolved_presentation_slide_ids"].append({
                            "relationship_id": rid,
                            "resolved": target or "",
                        })
                report["slide_count"] = len(slide_ids)
            else:
                report["slide_count"] = len(_iter_slide_parts(names))

            # Non-visual drawing IDs must be unique inside each slide.  Negative
            # extents are invalid OOXML geometry and can make editors repair or
            # refuse a deck.  Zero extents remain legal for line-like shapes.
            for slide_name in _iter_slide_parts(names):
                root = xml_roots.get(slide_name)
                if root is None:
                    continue
                ids = [node.attrib.get("id", "") for node in root.findall(f".//{{{_P_NS}}}cNvPr")]
                duplicate_ids = sorted(i for i, count in Counter(ids).items() if i and count > 1)
                if duplicate_ids:
                    report["duplicate_shape_ids"].append({
                        "slide": slide_name, "ids": duplicate_ids,
                    })
                for node in root.findall(f".//{{{_A_NS}}}ext"):
                    try:
                        cx = int(node.attrib.get("cx", "0"))
                        cy = int(node.attrib.get("cy", "0"))
                    except Exception:
                        continue
                    if cx < 0 or cy < 0:
                        report["negative_extents"].append({
                            "slide": slide_name, "cx": cx, "cy": cy,
                        })
    except zipfile.BadZipFile as exc:
        report["errors"].append(f"BadZipFile:{exc}")
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}:{exc}")

    hard_fields = (
        "required_parts_missing",
        "duplicate_zip_entries",
        "bad_xml_parts",
        "missing_relationship_targets",
        "unresolved_presentation_slide_ids",
        "duplicate_shape_ids",
        "negative_extents",
        "errors",
    )
    report["ok"] = not any(bool(report.get(field)) for field in hard_fields)
    return report


__all__ = ["validate_pptx_package"]
