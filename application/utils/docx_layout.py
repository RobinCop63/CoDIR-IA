"""v62.13.9.4.23 — MISE EN PAGE EFFICACE du document de travail (contrat du
06/09/2026 : « une version efficace, synthétique, professionnelle », ≤ 30 pages
quand le dossier le justifie). Rien n'est retiré de l'analyse : la pagination
se gagne par la mise en page — marges, corps de texte, interlignes, tableaux —
mesurée au rendu LibreOffice (49 → ~30 pages sur le run 4bb8d3).
"""
from __future__ import annotations


def compact_layout(doc, *, body_pt: float = 10.0, table_pt: float = 8.5, margin_cm: float = 1.7,
                   space_after_pt: float = 2.0) -> None:
    try:
        from docx.shared import Pt, Cm
    except Exception:
        return
    try:
        for section in doc.sections:
            section.left_margin = Cm(margin_cm)
            section.right_margin = Cm(margin_cm)
            section.top_margin = Cm(margin_cm)
            section.bottom_margin = Cm(margin_cm)
    except Exception:
        pass
    try:
        styles = doc.styles
        normal = styles["Normal"]
        normal.font.size = Pt(body_pt)
        normal.paragraph_format.space_after = Pt(space_after_pt)
        normal.paragraph_format.space_before = Pt(0)
        normal.paragraph_format.line_spacing = 1.0
        for name in ("List Bullet", "List Number"):
            try:
                st = styles[name]
                st.font.size = Pt(body_pt)
                st.paragraph_format.space_after = Pt(1)
            except Exception:
                pass
        for lvl, size in ((1, 13), (2, 11.5), (3, 10.5)):
            try:
                st = styles[f"Heading {lvl}"]
                st.font.size = Pt(size)
                st.paragraph_format.space_before = Pt(6 if lvl == 1 else 4)
                st.paragraph_format.space_after = Pt(2)
            except Exception:
                pass
    except Exception:
        pass
    try:
        for tbl in doc.tables:
            for row in tbl.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        p.paragraph_format.space_after = Pt(0)
                        p.paragraph_format.space_before = Pt(0)
                        for r in p.runs:
                            r.font.size = Pt(table_pt)
    except Exception:
        pass
