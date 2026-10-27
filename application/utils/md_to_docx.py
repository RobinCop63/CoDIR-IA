"""Bounded Markdown-to-DOCX renderer for CoDIR-IA chantier H-v2.

The renderer intentionally supports only the Markdown constructs emitted by the
agents.  It is deterministic, dependency-free and fail-open *per block*:
malformed input is preserved literally rather than corrupting or aborting the
whole report.

CONTRAT marqueurs non fermés (finition H-v2, 10/08/2026) : un ``**``
sans fermeture est conservé TEL QUEL dans le texte rendu — jamais
interprété, jamais supprimé en silence. La lisibilité brute prime sur
une devinette de sens ; contrat verrouillé par test.
"""
from __future__ import annotations

import re
from typing import Any, List, Sequence, Tuple

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^[\-–•*✓]\s+")
_NUM_RE = re.compile(r"^\d+[.)]\s+")
_FENCE_RE = re.compile(r"^\s*```(?P<lang>[A-Za-z0-9_+.-]*)\s*$")
_TABLE_SEP_CELL = re.compile(r"^\s*:?-{3,}:?\s*$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def _set_style(paragraph: Any, preferred: str) -> None:
    try:
        paragraph.style = preferred
    except Exception:
        pass


def _add_literal(paragraph: Any, text: str) -> None:
    run = paragraph.add_run(text)
    run.text = text


def _next_special(text: str, start: int) -> Tuple[int, str] | None:
    candidates: List[Tuple[int, str]] = []
    for marker in ("**", "`", "*", "["):
        pos = text.find(marker, start)
        if pos >= 0:
            candidates.append((pos, marker))
    return min(candidates, default=None, key=lambda x: x[0])


def _add_inline(paragraph: Any, text: str) -> None:
    """Render balanced inline syntax; preserve malformed markers literally."""
    i = 0
    while i < len(text):
        nxt = _next_special(text, i)
        if nxt is None:
            paragraph.add_run(text[i:])
            break
        pos, marker = nxt
        if pos > i:
            paragraph.add_run(text[i:pos])
        if marker == "**":
            end = text.find("**", pos + 2)
            if end < 0:
                paragraph.add_run(text[pos:])
                break
            run = paragraph.add_run(text[pos + 2:end])
            run.font.bold = True
            i = end + 2
            continue
        if marker == "`":
            end = text.find("`", pos + 1)
            if end < 0:
                paragraph.add_run(text[pos:])
                break
            run = paragraph.add_run(text[pos + 1:end])
            run.font.name = "Consolas"
            i = end + 1
            continue
        if marker == "*":
            # Avoid consuming the first star of a bold marker (already handled).
            end = text.find("*", pos + 1)
            if end < 0:
                paragraph.add_run(text[pos:])
                break
            run = paragraph.add_run(text[pos + 1:end])
            run.font.italic = True
            i = end + 1
            continue
        # Markdown link.  We deliberately render a stable visible form instead
        # of creating OOXML relationships: text (URL).
        m = _LINK_RE.match(text, pos)
        if m:
            paragraph.add_run(m.group(1))
            u = paragraph.add_run(f" ({m.group(2)})")
            try:
                u.font.underline = True
            except Exception:
                pass
            i = m.end()
            continue
        paragraph.add_run("[")
        i = pos + 1


def _split_pipe_row(line: str) -> List[str]:
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|"):
        raw = raw[:-1]
    cells: List[str] = []
    buf: List[str] = []
    escaped = False
    for ch in raw:
        if escaped:
            buf.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == "|":
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    cells.append("".join(buf).strip())
    return cells


def _is_table_sep(line: str) -> bool:
    cells = _split_pipe_row(line)
    return len(cells) >= 2 and all(_TABLE_SEP_CELL.match(c or "") for c in cells)


def _is_table_start(lines: Sequence[str], i: int) -> bool:
    if i + 1 >= len(lines):
        return False
    return "|" in lines[i] and _is_table_sep(lines[i + 1])


def _mark_header_row(row: Any) -> None:
    try:
        from docx.oxml.ns import qn
        trPr = row._tr.get_or_add_trPr()
        tblHeader = trPr.makeelement(qn("w:tblHeader"), {})
        trPr.append(tblHeader)
    except Exception:
        pass


def _add_pipe_table(doc: Any, block: Sequence[str]) -> None:
    if len(block) < 2 or not _is_table_sep(block[1]):
        raise ValueError("invalid markdown table")
    rows = [_split_pipe_row(block[0])] + [_split_pipe_row(x) for x in block[2:]]
    n_cols = max(len(row) for row in rows)
    table = doc.add_table(rows=len(rows), cols=n_cols)
    try:
        table.style = "Table Grid"
    except Exception:
        pass
    for ri, cells in enumerate(rows):
        for ci in range(n_cols):
            para = table.cell(ri, ci).paragraphs[0]
            _add_inline(para, cells[ci] if ci < len(cells) else "")
            if ri == 0:
                for run in para.runs:
                    run.font.bold = True
    _mark_header_row(table.rows[0])


def _add_code_block(doc: Any, lines: Sequence[str], lang: str = "") -> None:
    if lang:
        p = doc.add_paragraph()
        _set_style(p, "Caption")
        r = p.add_run(lang)
        r.font.italic = True
    if not lines:
        lines = [""]
    for line in lines:
        p = doc.add_paragraph()
        _set_style(p, "No Spacing")
        run = p.add_run(line)
        run.font.name = "Consolas"


def _fallback_block(doc: Any, lines: Sequence[str]) -> None:
    for line in lines:
        doc.add_paragraph(line)


def add_markdown(doc: Any, text: str, base_level: int = 1) -> None:
    """Render agent Markdown into ``doc`` with per-block fail-open semantics."""
    lines = (text or "").splitlines()
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i].rstrip("\r")
        if not raw.strip():
            i += 1
            continue
        # fenced code block
        fm = _FENCE_RE.match(raw)
        if fm:
            start = i
            lang = fm.group("lang") or ""
            i += 1
            code: List[str] = []
            closed = False
            while i < n:
                if _FENCE_RE.match(lines[i]) and not (lines[i].strip()[3:]):
                    closed = True
                    i += 1
                    break
                code.append(lines[i])
                i += 1
            try:
                if closed:
                    _add_code_block(doc, code, lang)
                else:
                    _fallback_block(doc, lines[start:i])
            except Exception:
                _fallback_block(doc, lines[start:i])
            continue
        # markdown table, with or without outer pipes
        if _is_table_start(lines, i):
            start = i
            block = [lines[i], lines[i + 1]]
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                block.append(lines[i])
                i += 1
            try:
                _add_pipe_table(doc, block)
            except Exception:
                _fallback_block(doc, block)
            continue
        try:
            hm = _HEADING_RE.match(raw)
            if hm:
                level = min(base_level + len(hm.group(1)) - 1, 6)
                p = doc.add_heading(level=level)
                _add_inline(p, hm.group(2).strip())
                i += 1
                continue
            if raw.lstrip().startswith(">"):
                p = doc.add_paragraph()
                _set_style(p, "Quote")
                _add_inline(p, re.sub(r"^\s*>\s?", "", raw))
                i += 1
                continue
            if _BULLET_RE.match(raw):
                p = doc.add_paragraph()
                _set_style(p, "List Bullet")
                _add_inline(p, _BULLET_RE.sub("", raw).strip())
                i += 1
                continue
            if _NUM_RE.match(raw):
                p = doc.add_paragraph()
                _set_style(p, "List Number")
                _add_inline(p, _NUM_RE.sub("", raw).strip())
                i += 1
                continue
            p = doc.add_paragraph()
            _add_inline(p, raw)
            i += 1
        except Exception:
            doc.add_paragraph(raw)
            i += 1


__all__ = ["add_markdown"]
