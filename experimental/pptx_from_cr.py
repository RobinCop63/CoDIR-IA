"""
CoDIR IA — utils/pptx_from_cr.py
=================================
Génère automatiquement un PowerPoint professionnel (8 slides)
à partir d'un compte-rendu Word produit par CoDIR IA.

Workflow :
  1. Lecture du .docx  →  extraction du texte brut
  2. Appel IA (provider actif)  →  structuration JSON du contenu
  3. Rendu python-pptx  →  fichier .pptx

Intégration Streamlit (app.py) :
    from utils.pptx_from_cr import generate_pptx_from_cr
    pptx_bytes = generate_pptx_from_cr(docx_path, client, model)
    st.download_button("📊 Télécharger le PPT", pptx_bytes, "codir_synthese.pptx")

Auteur  : CoDIR IA
Version : 1.0.0
"""

from __future__ import annotations

import io
import json
import re
import textwrap
from pathlib import Path
from typing import Optional

# ── dépendances obligatoires ──────────────────────────────────────────────────
try:
    from docx import Document
except ImportError:
    raise ImportError("python-docx manquant : pip install python-docx")

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt
except ImportError:
    raise ImportError("python-pptx manquant : pip install python-pptx")


# ═══════════════════════════════════════════════════════════════════════════════
# 1.  EXTRACTION TEXTE DU DOCX
# ═══════════════════════════════════════════════════════════════════════════════

def extract_text_from_docx(docx_path: str | Path) -> str:
    """Extrait le texte intégral d'un .docx (paragraphes + tableaux)."""
    doc = Document(str(docx_path))
    lines: list[str] = []

    for para in doc.paragraphs:
        txt = para.text.strip()
        if txt:
            lines.append(txt)

    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                lines.append(" | ".join(cells))

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 2.  PROMPT IA → JSON STRUCTURÉ
# ═══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = textwrap.dedent("""
Tu es un expert en communication executive.
À partir d'un compte-rendu de CoDIR, tu extrais et structures
l'information pour un PowerPoint de 8 slides.

Réponds UNIQUEMENT avec un objet JSON valide, sans markdown, sans commentaires.
Structure exacte attendue :

{
  "titre": "Titre principal de la présentation (max 60 car.)",
  "sous_titre": "Sous-titre ou contexte (max 80 car.)",
  "entreprise": "Nom entreprise / structure",
  "date": "Date ou période",
  "marche": {
    "taille": "ex: 850-900 M€",
    "croissance": "ex: +8% vs 2025",
    "missions": "ex: ~12 000",
    "duree_moy": "ex: 7,2 mois",
    "tjm_moy": "ex: 1 200€",
    "tjm_detail": "ex: 950-1 400€ senior",
    "drivers": [
      {"pct": "35%", "label": "Transformations digitales / IA"},
      {"pct": "22%", "label": "Transitions RSE & décarbonation"},
      {"pct": "18%", "label": "Restructurations post-inflation"},
      {"pct": "25%+", "label": "Missions fractionnées"}
    ],
    "segments": [
      {"nom": "ETI industrielles", "pct": "38%", "etoiles": 5},
      {"nom": "PME / TPE croissance", "pct": "28%", "etoiles": 4},
      {"nom": "Grands groupes", "pct": "22%", "etoiles": 2},
      {"nom": "Secteur public", "pct": "12%", "etoiles": 3}
    ]
  },
  "swot": {
    "forces": ["item 1", "item 2", "item 3", "item 4"],
    "faiblesses": ["item 1", "item 2", "item 3", "item 4"],
    "opportunites": ["item 1", "item 2", "item 3", "item 4"],
    "risques": ["item 1", "item 2", "item 3", "item 4"]
  },
  "axes": [
    {
      "num": "1",
      "titre": "Spécialisation Différenciante",
      "points": ["point 1", "point 2", "point 3", "point 4"]
    },
    {
      "num": "2",
      "titre": "Industrialisation Commerciale",
      "points": ["point 1", "point 2", "point 3", "point 4"]
    },
    {
      "num": "3",
      "titre": "Modèle Économique Scalable",
      "points": ["point 1", "point 2", "point 3", "point 4"]
    },
    {
      "num": "4",
      "titre": "Visibilité & Autorité Digitale",
      "points": ["point 1", "point 2", "point 3", "point 4"]
    }
  ],
  "modele_eco": {
    "tjm_actuel": "800-1 000€",
    "tjm_marche": "950-1 400€",
    "tjm_cible": "1 200-1 500€",
    "temps_partage": [
      {"kpi": "2-3 j/sem", "label": "Engagement client"},
      {"kpi": "4 500-6 500€", "label": "par mois, par client"},
      {"kpi": "200 K€ ARR", "label": "avec 3-4 clients simultanés"},
      {"kpi": "6-12 mois", "label": "Contrats récurrents"}
    ],
    "reseau": [
      {"kpi": "5-8", "label": "Managers séniors partenaires"},
      {"kpi": "20-25%", "label": "Commission sur apports"},
      {"kpi": "× 3", "label": "Capacité de production"},
      {"kpi": "0€", "label": "Charge fixe structurelle"}
    ]
  },
  "roadmap": [
    {
      "phase": "T1", "date": "Mars - Mai", "titre": "FONDATIONS",
      "items": ["item 1", "item 2", "item 3"],
      "kpi": "Pipeline structuré", "budget": "18 K€", "extra": "25 j Robin"
    },
    {
      "phase": "T2", "date": "Juin - Août", "titre": "TRACTION",
      "items": ["item 1", "item 2", "item 3"],
      "kpi": "15 RDV / mois", "budget": "6 K€", "extra": "120 K€ CA"
    },
    {
      "phase": "T3", "date": "Sept - Nov", "titre": "ACCÉLÉRATION",
      "items": ["item 1", "item 2", "item 3"],
      "kpi": "3 missions / an partenaires", "budget": "8 K€", "extra": "200 K€ CA"
    },
    {
      "phase": "T4", "date": "Déc 2026 -", "titre": "CONSOLIDATION",
      "items": ["item 1", "item 2", "item 3"],
      "kpi": "Rentabilité 35%+", "budget": "CA cible", "extra": "350 K€ ARR"
    }
  ],
  "next_steps": [
    {"date": "JJ/MM/AAAA", "action": "Description courte (max 90 car.)", "owner": "Robin"},
    {"date": "JJ/MM/AAAA", "action": "Description courte (max 90 car.)", "owner": "Agence"},
    {"date": "JJ/MM/AAAA", "action": "Description courte (max 90 car.)", "owner": "Robin + DAF"},
    {"date": "JJ/MM/AAAA", "action": "Description courte (max 90 car.)", "owner": "Robin"},
    {"date": "JJ/MM/AAAA", "action": "Description courte (max 90 car.)", "owner": "Robin + DAF"}
  ],
  "questions_ouvertes": [
    "Question 1 ?",
    "Question 2 ?",
    "Question 3 ?",
    "Question 4 ?"
  ],
  "decisions_codir": [
    "Décision attendue 1",
    "Décision attendue 2",
    "Décision attendue 3"
  ],
  "conclusion": {
    "headline": "Message fort de conclusion (max 80 car.)",
    "points": [
      "Point clé 1 avec chiffre ou impact mesurable",
      "Point clé 2 avec chiffre ou impact mesurable",
      "Point clé 3 avec chiffre ou impact mesurable"
    ],
    "contact": "Prénom NOM · linkedin.com/in/... · Entreprise"
  }
}

Adapte TOUTES les valeurs au contenu réel du compte-rendu fourni.
Si une information est absente, génère une valeur cohérente avec le contexte.
""").strip()


def call_ia_for_structure(
    cr_text: str,
    client,
    model: str,
    provider: str = "anthropic"
) -> dict:
    """
    Appelle l'API IA active pour structurer le CR en JSON.
    Compatible avec les 4 providers de CoDIR IA.

    Args:
        cr_text   : texte brut extrait du docx
        client    : instance SDK déjà initialisée (openai, anthropic, gemini, mistral)
        model     : identifiant du modèle (ex: "claude-opus-4-5-20251101")
        provider  : "anthropic" | "openai" | "gemini" | "mistral"

    Returns:
        dict structuré prêt pour le rendu PPT
    """
    user_msg = f"Voici le compte-rendu CoDIR IA à structurer :\n\n{cr_text[:12000]}"

    # ── Anthropic ──────────────────────────────────────────────────────────────
    if provider == "anthropic":
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}]
        )
        raw = response.content[0].text

    # ── OpenAI ─────────────────────────────────────────────────────────────────
    elif provider == "openai":
        response = client.chat.completions.create(
            model=model,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg}
            ]
        )
        raw = response.choices[0].message.content

    # ── Gemini ─────────────────────────────────────────────────────────────────
    elif provider == "gemini":
        from google.genai import types
        response = client.models.generate_content(
            model=model,
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=4096
            )
        )
        raw = response.text

    # ── Mistral ────────────────────────────────────────────────────────────────
    elif provider == "mistral":
        response = client.chat.complete(
            model=model,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg}
            ]
        )
        raw = response.choices[0].message.content

    else:
        raise ValueError(f"Provider inconnu : {provider}")

    # ── nettoyage JSON ─────────────────────────────────────────────────────────
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    raw = raw.strip()

    return json.loads(raw)


# ═══════════════════════════════════════════════════════════════════════════════
# 3.  UTILITAIRES DE RENDU python-pptx
# ═══════════════════════════════════════════════════════════════════════════════

# Palette "Midnight Executive Gold"
C_DARK_NAVY  = RGBColor(0x14, 0x1A, 0x4A)
C_NAVY       = RGBColor(0x1E, 0x27, 0x61)
C_ICE_BLUE   = RGBColor(0xCA, 0xDC, 0xFC)
C_GOLD       = RGBColor(0xE8, 0xB8, 0x4B)
C_WHITE      = RGBColor(0xFF, 0xFF, 0xFF)
C_LIGHT_GRAY = RGBColor(0xF5, 0xF7, 0xFA)
C_MID_GRAY   = RGBColor(0x88, 0x96, 0xB0)
C_TEXT_DARK  = RGBColor(0x1A, 0x1F, 0x36)
C_GREEN      = RGBColor(0x27, 0xAE, 0x60)
C_TEAL       = RGBColor(0x0D, 0x94, 0x88)
C_RED        = RGBColor(0xE7, 0x4C, 0x3C)
C_BLUE_MED   = RGBColor(0x5E, 0x81, 0xF4)
C_ORANGE     = RGBColor(0xF9, 0x61, 0x67)


def _rgb(r: int, g: int, b: int) -> RGBColor:
    return RGBColor(r, g, b)


def _inches(*args):
    """Convertit des pouces en Emu (unité interne pptx)."""
    return tuple(Inches(a) for a in args)


def _add_rect(slide, x, y, w, h, fill_color: RGBColor, line_color: Optional[RGBColor] = None):
    from pptx.util import Inches
    shape = slide.shapes.add_shape(
        1,  # MSO_SHAPE_TYPE.RECTANGLE
        Inches(x), Inches(y), Inches(w), Inches(h)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    if line_color:
        shape.line.color.rgb = line_color
    else:
        shape.line.fill.background()
    return shape


def _add_text(
    slide, text: str,
    x: float, y: float, w: float, h: float,
    font_size: int = 12,
    bold: bool = False,
    italic: bool = False,
    color: RGBColor = C_TEXT_DARK,
    align=PP_ALIGN.LEFT,
    font_name: str = "Calibri"
):
    from pptx.util import Inches, Pt
    txBox = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.name = font_name
    return txBox


def _add_header(slide, icon_char: str, title: str, subtitle: str):
    """Bande de titre commune à toutes les slides de contenu."""
    _add_rect(slide, 0, 0, 10, 1.1, C_NAVY)
    _add_rect(slide, 0, 1.1, 10, 0.06, C_GOLD)

    # icône emoji dans un carré or
    _add_rect(slide, 0.2, 0.22, 0.7, 0.65, C_GOLD)
    _add_text(slide, icon_char, 0.2, 0.22, 0.7, 0.65,
              font_size=22, bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)

    _add_text(slide, title, 1.1, 0.2, 8.5, 0.48,
              font_size=22, bold=True, color=C_WHITE)
    _add_text(slide, subtitle, 1.1, 0.64, 8.5, 0.32,
              font_size=11, color=C_ICE_BLUE)


def _add_page_num(slide, num: int):
    _add_text(slide, str(num).zfill(2), 9.5, 5.28, 0.4, 0.28,
              font_size=10, color=C_MID_GRAY, align=PP_ALIGN.RIGHT)


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


# ═══════════════════════════════════════════════════════════════════════════════
# 4.  SLIDES
# ═══════════════════════════════════════════════════════════════════════════════

def _slide_titre(prs: Presentation, data: dict):
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_DARK_NAVY

    # Barre gauche or
    _add_rect(slide, 0, 0, 0.12, 5.625, C_GOLD)

    # Cercles décoratifs
    from pptx.util import Inches
    from pptx.enum.shapes import MSO_SHAPE_TYPE
    ov1 = slide.shapes.add_shape(9, Inches(7.0), Inches(-1.5), Inches(5.5), Inches(5.5))  # OVAL=9
    ov1.fill.solid()
    ov1.fill.fore_color.rgb = C_NAVY
    ov1.line.fill.background()

    # Tag catégorie
    _add_rect(slide, 0.35, 1.05, 3.4, 0.42, C_GOLD)
    _add_text(slide, "ÉTUDE DE MARCHÉ & STRATÉGIE", 0.35, 1.05, 3.4, 0.42,
              font_size=10, bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)

    # Titre principal
    titre = _truncate(data.get("titre", "Management de Transition"), 55)
    _add_text(slide, titre, 0.35, 1.6, 9.0, 0.9,
              font_size=42, bold=True, color=C_WHITE, font_name="Calibri")

    sous_titre = _truncate(data.get("sous_titre", ""), 75)
    if sous_titre:
        _add_text(slide, sous_titre, 0.35, 2.55, 9.0, 0.6,
                  font_size=26, bold=True, color=C_GOLD, font_name="Calibri")

    # Séparateur
    _add_rect(slide, 0.35, 3.3, 5.5, 0.04, C_MID_GRAY)

    # Entreprise
    _add_text(slide, data.get("entreprise", ""), 0.35, 3.48, 7, 0.42,
              font_size=16, bold=True, color=C_ICE_BLUE)
    _add_text(slide, "DAF / CFO de Transition  ·  11 ans d'expérience  ·  Couverture nationale",
              0.35, 3.9, 8.5, 0.35, font_size=12, color=C_MID_GRAY)

    # Badge date
    _add_rect(slide, 0.35, 4.72, 2.3, 0.52, C_NAVY)
    _add_text(slide, data.get("date", "2026"), 0.35, 4.72, 2.3, 0.52,
              font_size=12, bold=True, color=C_ICE_BLUE, align=PP_ALIGN.CENTER)

    _add_text(slide, "Généré par CoDIR IA", 7.0, 5.22, 2.9, 0.28,
              font_size=9, italic=True, color=C_MID_GRAY, align=PP_ALIGN.RIGHT)


def _slide_marche(prs: Presentation, data: dict):
    d = data.get("marche", {})
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_LIGHT_GRAY

    _add_header(slide, "📈", "ÉTAT DU MARCHÉ",
                "Management de Transition · France · " + data.get("date", "2026"))

    # ── 4 KPI cards ──────────────────────────────────────────────────────────
    kpis = [
        (d.get("taille", "—"), "Taille du marché", d.get("croissance", "")),
        (d.get("missions", "—"), "Missions / an", "en France"),
        (d.get("duree_moy", "—"), "Durée moyenne", "par mission"),
        (d.get("tjm_moy", "—"), "TJM moyen", d.get("tjm_detail", "")),
    ]
    cw, ch, cy, gap, sx = 2.1, 1.42, 1.32, 0.32, 0.3
    for i, (val, label, sub) in enumerate(kpis):
        cx = sx + i * (cw + gap)
        _add_rect(slide, cx, cy, cw, ch, C_WHITE)
        _add_rect(slide, cx, cy, cw, 0.07, C_GOLD)
        _add_text(slide, _truncate(val, 14), cx, cy + 0.2, cw, 0.54,
                  font_size=22, bold=True, color=C_NAVY, align=PP_ALIGN.CENTER)
        _add_text(slide, label, cx, cy + 0.72, cw, 0.32,
                  font_size=10, bold=True, color=C_TEXT_DARK, align=PP_ALIGN.CENTER)
        _add_text(slide, sub, cx, cy + 1.04, cw, 0.28,
                  font_size=9, italic=True, color=C_MID_GRAY, align=PP_ALIGN.CENTER)

    # ── Drivers ───────────────────────────────────────────────────────────────
    _add_rect(slide, 0.3, 2.92, 4.45, 2.45, C_WHITE)
    _add_rect(slide, 0.3, 2.92, 0.07, 2.45, C_TEAL)
    _add_text(slide, "DRIVERS DE CROISSANCE", 0.5, 3.0, 4.0, 0.35,
              font_size=11, bold=True, color=C_NAVY)

    drivers = d.get("drivers", [])
    for i, drv in enumerate(drivers[:4]):
        dy = 3.5 + i * 0.44
        _add_rect(slide, 0.5, dy, 0.72, 0.3, C_NAVY)
        _add_text(slide, drv.get("pct", ""), 0.5, dy, 0.72, 0.3,
                  font_size=10, bold=True, color=C_GOLD, align=PP_ALIGN.CENTER)
        _add_text(slide, _truncate(drv.get("label", ""), 38), 1.3, dy, 3.3, 0.3,
                  font_size=10, color=C_TEXT_DARK)

    # ── Segmentation ──────────────────────────────────────────────────────────
    _add_rect(slide, 5.05, 2.92, 4.65, 2.45, C_WHITE)
    _add_rect(slide, 5.05, 2.92, 0.07, 2.45, C_GOLD)
    _add_text(slide, "SEGMENTATION CLIENTS", 5.25, 3.0, 4.3, 0.35,
              font_size=11, bold=True, color=C_NAVY)

    segs = d.get("segments", [])
    for i, seg in enumerate(segs[:4]):
        sy = 3.48 + i * 0.46
        _add_text(slide, _truncate(seg.get("nom", ""), 22), 5.25, sy, 2.0, 0.32,
                  font_size=10, color=C_TEXT_DARK)
        _add_rect(slide, 7.35, sy + 0.04, 0.55, 0.26, C_NAVY)
        _add_text(slide, seg.get("pct", ""), 7.35, sy + 0.04, 0.55, 0.26,
                  font_size=10, bold=True, color=C_GOLD, align=PP_ALIGN.CENTER)
        stars = seg.get("etoiles", 3)
        star_str = "●" * min(stars, 5) + "○" * (5 - min(stars, 5))
        _add_text(slide, star_str, 8.0, sy, 1.6, 0.32,
                  font_size=10, color=C_GOLD)

    _add_page_num(slide, 2)


def _slide_swot(prs: Presentation, data: dict):
    swot = data.get("swot", {})
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_LIGHT_GRAY

    _add_header(slide, "🎯", "POSITIONNEMENT",
                "Forces · Faiblesses · Opportunités · Risques")

    quadrants = [
        ("FORCES",       C_GREEN,    swot.get("forces", []),       0.25, 1.25),
        ("FAIBLESSES",   C_RED,      swot.get("faiblesses", []),   5.15, 1.25),
        ("OPPORTUNITÉS", C_TEAL,     swot.get("opportunites", []), 0.25, 3.42),
        ("RISQUES",      C_GOLD,     swot.get("risques", []),      5.15, 3.42),
    ]

    for title, color, items, qx, qy in quadrants:
        _add_rect(slide, qx, qy, 4.6, 2.05, C_WHITE)
        _add_rect(slide, qx, qy, 4.6, 0.45, color)
        txt_color = C_DARK_NAVY if color == C_GOLD else C_WHITE
        _add_text(slide, title, qx, qy, 4.6, 0.45,
                  font_size=12, bold=True, color=txt_color, align=PP_ALIGN.CENTER)
        for j, item in enumerate(items[:4]):
            iy = qy + 0.55 + j * 0.37
            _add_rect(slide, qx + 0.12, iy + 0.06, 0.18, 0.18, color)  # bullet carré
            _add_text(slide, _truncate(item, 52), qx + 0.38, iy, 4.1, 0.34,
                      font_size=9.5, color=C_TEXT_DARK)

    _add_page_num(slide, 3)


def _slide_axes(prs: Presentation, data: dict):
    axes = data.get("axes", [])
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_DARK_NAVY

    _add_header(slide, "🚀", "4 AXES STRATÉGIQUES",
                "Préconisations CoDIR IA · Priorités 2026–2027")

    colors = [C_TEAL, C_BLUE_MED, C_GOLD, C_ORANGE]
    positions = [(0.25, 1.25), (5.03, 1.25), (0.25, 3.28), (5.03, 3.28)]

    for i, axe in enumerate(axes[:4]):
        color = colors[i]
        px, py = positions[i]
        _add_rect(slide, px, py, 4.5, 1.9, C_NAVY)
        _add_rect(slide, px, py, 0.07, 1.9, color)
        # badge numéro
        _add_rect(slide, px + 0.18, py + 0.14, 0.42, 0.42, color)
        _add_text(slide, axe.get("num", str(i + 1)), px + 0.18, py + 0.14, 0.42, 0.42,
                  font_size=16, bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)
        # titre axe
        _add_text(slide, _truncate(axe.get("titre", ""), 40), px + 0.72, py + 0.16, 3.65, 0.4,
                  font_size=12, bold=True, color=C_WHITE)
        # points
        for j, pt in enumerate(axe.get("points", [])[:4]):
            by = py + 0.68 + j * 0.28
            _add_rect(slide, px + 0.2, by + 0.08, 0.1, 0.1, color)
            _add_text(slide, _truncate(pt, 58), px + 0.38, by, 4.0, 0.27,
                      font_size=9.5, color=C_ICE_BLUE)

    _add_page_num(slide, 4)


def _slide_modele_eco(prs: Presentation, data: dict):
    eco = data.get("modele_eco", {})
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_LIGHT_GRAY

    _add_header(slide, "💰", "MODÈLE ÉCONOMIQUE OPTIMISÉ",
                "Pricing valeur · Temps partagé · Réseau managers")

    # ── TJM bar chart ─────────────────────────────────────────────────────────
    _add_rect(slide, 0.25, 1.25, 9.5, 1.58, C_WHITE)
    _add_rect(slide, 0.25, 1.25, 0.07, 1.58, C_GOLD)
    _add_text(slide, "REVALORISATION DU TJM", 0.45, 1.35, 4.0, 0.32,
              font_size=11, bold=True, color=C_NAVY)

    tjm_rows = [
        (eco.get("tjm_actuel", "800-1 000€"), 0.55, C_MID_GRAY),
        (eco.get("tjm_marche", "950-1 400€"), 0.72, C_TEAL),
        (eco.get("tjm_cible", "1 200-1 500€"), 0.90, C_GREEN),
    ]
    labels = ["TJM actuel estimé", "TJM marché senior (2026)", "TJM cible 2027 (niches)"]
    for i, (val, pct, color) in enumerate(tjm_rows):
        ty = 1.83 + i * 0.28
        _add_text(slide, labels[i], 0.45, ty, 3.0, 0.26,
                  font_size=10, color=C_TEXT_DARK)
        _add_rect(slide, 3.55, ty + 0.04, 4.5, 0.17, _rgb(0xE8, 0xEC, 0xF0))
        _add_rect(slide, 3.55, ty + 0.04, 4.5 * pct, 0.17, color)
        _add_text(slide, val, 8.15, ty, 1.6, 0.26,
                  font_size=10, bold=True, color=color)

    # ── Offre temps partagé ───────────────────────────────────────────────────
    _add_rect(slide, 0.25, 3.02, 4.65, 2.35, C_WHITE)
    _add_rect(slide, 0.25, 3.02, 4.65, 0.45, C_TEAL)
    _add_text(slide, "OFFRE TEMPS PARTAGÉ DG / DAF", 0.25, 3.02, 4.65, 0.45,
              font_size=11, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)

    for i, row in enumerate(eco.get("temps_partage", [])[:4]):
        ty = 3.62 + i * 0.42
        _add_rect(slide, 0.35, ty, 1.55, 0.3, C_NAVY)
        _add_text(slide, _truncate(row.get("kpi", ""), 16), 0.35, ty, 1.55, 0.3,
                  font_size=10, bold=True, color=C_GOLD, align=PP_ALIGN.CENTER)
        _add_text(slide, _truncate(row.get("label", ""), 30), 2.0, ty, 2.78, 0.3,
                  font_size=10, color=C_TEXT_DARK)

    # ── Réseau managers ───────────────────────────────────────────────────────
    _add_rect(slide, 5.1, 3.02, 4.65, 2.35, C_WHITE)
    _add_rect(slide, 5.1, 3.02, 4.65, 0.45, C_GOLD)
    _add_text(slide, "RÉSEAU MANAGERS ASSOCIÉS", 5.1, 3.02, 4.65, 0.45,
              font_size=11, bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)

    for i, row in enumerate(eco.get("reseau", [])[:4]):
        ty = 3.62 + i * 0.42
        _add_rect(slide, 5.2, ty, 1.1, 0.3, C_NAVY)
        _add_text(slide, _truncate(row.get("kpi", ""), 10), 5.2, ty, 1.1, 0.3,
                  font_size=11, bold=True, color=C_GOLD, align=PP_ALIGN.CENTER)
        _add_text(slide, _truncate(row.get("label", ""), 32), 6.4, ty, 3.25, 0.3,
                  font_size=10, color=C_TEXT_DARK)

    _add_page_num(slide, 5)


def _slide_roadmap(prs: Presentation, data: dict):
    phases = data.get("roadmap", [])
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_LIGHT_GRAY

    _add_header(slide, "📅", "PLAN D'EXÉCUTION 2026",
                "Roadmap trimestrielle · Priorités & KPIs")

    # Ligne de timeline
    _add_rect(slide, 0.65, 2.02, 8.7, 0.05, C_MID_GRAY)

    phase_colors = [C_TEAL, C_BLUE_MED, C_GREEN, C_GOLD]
    pw, sx = 2.2, 0.35
    total_gap = (10 - 2 * sx - 4 * pw) / 3

    for i, phase in enumerate(phases[:4]):
        color = phase_colors[i]
        px = sx + i * (pw + total_gap)

        # ── cercle timeline ───────────────────────────────────────────────────
        from pptx.util import Inches
        ov = slide.shapes.add_shape(9, Inches(px + pw / 2 - 0.25), Inches(1.82),
                                     Inches(0.5), Inches(0.5))
        ov.fill.solid(); ov.fill.fore_color.rgb = color
        ov.line.fill.background()
        _add_text(slide, phase.get("phase", ""), px + pw / 2 - 0.25, 1.82, 0.5, 0.5,
                  font_size=13, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)

        # date au-dessus
        _add_text(slide, phase.get("date", ""), px, 1.32, pw, 0.34,
                  font_size=9, italic=True, color=C_MID_GRAY, align=PP_ALIGN.CENTER)

        # carte principale
        _add_rect(slide, px, 2.46, pw, 2.95, C_WHITE)
        _add_rect(slide, px, 2.46, pw, 0.42, color)
        txt_color = C_DARK_NAVY if color == C_GOLD else C_WHITE
        _add_text(slide, phase.get("titre", ""), px, 2.46, pw, 0.42,
                  font_size=11, bold=True, color=txt_color, align=PP_ALIGN.CENTER)

        for j, item in enumerate(phase.get("items", [])[:3]):
            iy = 2.98 + j * 0.4
            _add_rect(slide, px + 0.15, iy + 0.13, 0.1, 0.1, color)
            _add_text(slide, _truncate(item, 30), px + 0.32, iy, pw - 0.38, 0.38,
                      font_size=9, color=C_TEXT_DARK)

        # KPI badge
        _add_rect(slide, px + 0.1, 4.22, pw - 0.2, 0.52, C_NAVY)
        _add_text(slide, "KPI : " + _truncate(phase.get("kpi", ""), 28), px + 0.1, 4.22, pw - 0.2, 0.52,
                  font_size=9, bold=True, color=C_GOLD, align=PP_ALIGN.CENTER)

        # budget
        budget_txt = phase.get("budget", "") + " · " + phase.get("extra", "")
        _add_text(slide, _truncate(budget_txt, 32), px, 4.84, pw, 0.28,
                  font_size=8.5, italic=True, color=C_MID_GRAY, align=PP_ALIGN.CENTER)

    _add_page_num(slide, 6)


def _slide_next_steps(prs: Presentation, data: dict):
    steps = data.get("next_steps", [])
    questions = data.get("questions_ouvertes", [])
    decisions = data.get("decisions_codir", [])

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_LIGHT_GRAY

    _add_header(slide, "▶", "PROCHAINES ÉTAPES & DÉCISIONS",
                "Actions immédiates · Questions ouvertes · Go / No Go")

    # ── Next steps ────────────────────────────────────────────────────────────
    _add_rect(slide, 0.25, 1.25, 5.2, 3.85, C_WHITE)
    _add_rect(slide, 0.25, 1.25, 5.2, 0.45, C_NAVY)
    _add_text(slide, "NEXT STEPS (datés)", 0.25, 1.25, 5.2, 0.45,
              font_size=12, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)

    for i, step in enumerate(steps[:5]):
        sy = 1.86 + i * 0.54
        _add_rect(slide, 0.35, sy, 1.38, 0.36, C_GOLD)
        _add_text(slide, step.get("date", ""), 0.35, sy, 1.38, 0.36,
                  font_size=9.5, bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)
        _add_text(slide, _truncate(step.get("action", ""), 58), 1.82, sy, 3.45, 0.38,
                  font_size=9, color=C_TEXT_DARK)
        owner = step.get("owner", "")
        if owner:
            _add_rect(slide, 1.82, sy + 0.34, 1.1, 0.2, C_NAVY)
            _add_text(slide, owner, 1.82, sy + 0.34, 1.1, 0.2,
                      font_size=8, bold=True, color=C_ICE_BLUE, align=PP_ALIGN.CENTER)

    # ── Questions ouvertes ────────────────────────────────────────────────────
    _add_rect(slide, 5.6, 1.25, 4.15, 2.18, C_WHITE)
    _add_rect(slide, 5.6, 1.25, 4.15, 0.45, C_RED)
    _add_text(slide, "QUESTIONS OUVERTES", 5.6, 1.25, 4.15, 0.45,
              font_size=12, bold=True, color=C_WHITE, align=PP_ALIGN.CENTER)

    for i, q in enumerate(questions[:4]):
        qy = 1.88 + i * 0.4
        _add_rect(slide, 5.7, qy + 0.1, 0.14, 0.14, C_RED)
        _add_text(slide, _truncate(q, 48), 5.95, qy, 3.68, 0.36,
                  font_size=10, color=C_TEXT_DARK)

    # ── Décision attendue ─────────────────────────────────────────────────────
    _add_rect(slide, 5.6, 3.56, 4.15, 1.54, C_NAVY)
    _add_rect(slide, 5.6, 3.56, 0.07, 1.54, C_GOLD)
    _add_text(slide, "DÉCISION ATTENDUE DU CODIR", 5.78, 3.65, 3.9, 0.35,
              font_size=11, bold=True, color=C_GOLD)

    for i, dec in enumerate(decisions[:3]):
        dy = 4.1 + i * 0.32
        _add_text(slide, "✓  " + _truncate(dec, 50), 5.78, dy, 3.9, 0.3,
                  font_size=9.5, color=C_WHITE)

    _add_page_num(slide, 7)


def _slide_conclusion(prs: Presentation, data: dict):
    concl = data.get("conclusion", {})
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_DARK_NAVY

    # Barre gauche or
    _add_rect(slide, 0, 0, 0.12, 5.625, C_GOLD)

    # Cercle décoratif
    from pptx.util import Inches
    ov = slide.shapes.add_shape(9, Inches(6.5), Inches(-1.2), Inches(6.0), Inches(6.0))
    ov.fill.solid(); ov.fill.fore_color.rgb = C_NAVY
    ov.line.fill.background()

    # Tag
    _add_rect(slide, 0.35, 0.88, 2.6, 0.4, C_GOLD)
    _add_text(slide, "SYNTHÈSE & CONCLUSION", 0.35, 0.88, 2.6, 0.4,
              font_size=9.5, bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)

    # Headline
    headline = _truncate(concl.get("headline", "Conclusion"), 70)
    _add_text(slide, headline, 0.35, 1.42, 7.5, 1.5,
              font_size=30, bold=True, color=C_WHITE, font_name="Calibri")

    # 3 points clés
    for i, pt in enumerate(concl.get("points", [])[:3]):
        py = 3.05 + i * 0.62
        _add_rect(slide, 0.35, py + 0.08, 0.14, 0.14, C_GOLD)
        _add_text(slide, _truncate(pt, 75), 0.62, py, 7.5, 0.5,
                  font_size=13, color=C_ICE_BLUE)

    # Séparateur
    _add_rect(slide, 0.35, 4.92, 5.5, 0.04, C_NAVY)

    # Contact
    _add_text(slide, concl.get("contact", ""), 0.35, 5.08, 8.5, 0.35,
              font_size=10, color=C_MID_GRAY)

    _add_page_num(slide, 8)


# ═══════════════════════════════════════════════════════════════════════════════
# 5.  POINT D'ENTRÉE PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def generate_pptx_from_cr(
    docx_path: str | Path,
    client,
    model: str,
    provider: str = "anthropic",
    output_path: Optional[str | Path] = None
) -> bytes:
    """
    Pipeline complet : DOCX  →  IA  →  PPTX bytes.

    Args:
        docx_path   : chemin vers le .docx généré par CoDIR IA
        client      : instance SDK IA active
        model       : identifiant modèle
        provider    : "anthropic" | "openai" | "gemini" | "mistral"
        output_path : si fourni, sauvegarde aussi sur disque

    Returns:
        bytes du fichier .pptx (pour st.download_button)
    """
    # 1. Extraction texte
    cr_text = extract_text_from_docx(docx_path)

    # 2. Structuration IA
    data = call_ia_for_structure(cr_text, client, model, provider)

    # 3. Rendu PPT
    prs = Presentation()
    prs.slide_width  = Inches(10)
    prs.slide_height = Inches(5.625)

    _slide_titre(prs, data)
    _slide_marche(prs, data)
    _slide_swot(prs, data)
    _slide_axes(prs, data)
    _slide_modele_eco(prs, data)
    _slide_roadmap(prs, data)
    _slide_next_steps(prs, data)
    _slide_conclusion(prs, data)

    # 4. Sérialisation
    buf = io.BytesIO()
    prs.save(buf)
    pptx_bytes = buf.getvalue()

    if output_path:
        Path(output_path).write_bytes(pptx_bytes)

    return pptx_bytes
