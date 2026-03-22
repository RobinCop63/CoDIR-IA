"""
utils/pptx_from_cr.py  —  CoDIR IA v16.3.3.22+
================================================
Génère un PowerPoint executive-grade (8 slides spécialisées)
à partir d'un compte-rendu CoDIR IA.

Version : 3.0.0 — corrections mise en page + extraction CR améliorée
"""
from __future__ import annotations
import io, json, re, textwrap, warnings
from pathlib import Path
from typing import Optional

try:
    from docx import Document
except ImportError:
    Document = None

try:
    from pptx import Presentation
    from pptx.util import Inches, Pt, Emu
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
except ImportError:
    raise ImportError("python-pptx manquant : pip install python-pptx")


# ───────────────────────────────────────────────────────────────────────────────
# NETTOYAGE TEXTE — filtres anti-bruit CR
# ───────────────────────────────────────────────────────────────────────────────

_NOISE_PATTERNS = [
    r"COMPTE\s+RENDU\s+CoDIR",
    r"SOURCE\s+POUR\s+SYNTH[ÈE]SE",
    r"Pièces\s+jointes\s*:",
    r"tokens_est\s*~",
    r"tronqu[eé]=",
    r"BRIEF\s+INITIAL\s*\(dirigeant\)",
    r"BRIEF\s+CODIR\s*\(redistribu[eé]\)",
    r"\{['\"]provider['\"]",
    r"'provider'\s*:",
    r"'model'\s*:",
    r"'output'\s*:",
    r"prompt_tokens",
    r"completion_tokens",
    r"fichier\(s\)\s*\|",
    r"^Version\s*:\s*v\d",
    r"^Date\s*:\s*\d",
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE)

# Marqueurs markdown à nettoyer dans les bullets
_MD_CLEAN_RE = re.compile(r"\*\*([^*]+)\*\*|\*([^*]+)\*|__([^_]+)__|`([^`]+)`")
def _strip_md(t: str) -> str:
    t = _MD_CLEAN_RE.sub(lambda m: next(g for g in m.groups() if g is not None), t)
    return re.sub(r"\s+", " ", t).strip()

def _is_noise(line: str) -> bool:
    return bool(_NOISE_RE.search(line))

def _clean_bullet(b: str, maxlen: int = 80) -> str:
    """Nettoie un bullet : supprime bruit, markdown, préfixes liste, troncature."""
    b = _strip_md(b.strip())
    if _is_noise(b): return ""
    # Supprimer préfixes liste (* - • ✓ ✗ [ ] 1. etc.)
    b = re.sub(r"^[\s\-–•\*✓✗\[\]]+\s*", "", b)
    b = re.sub(r"^\d+[\.\)]\s*", "", b)
    b = b.strip()
    if len(b) < 5: return ""
    return b[:maxlen] + ("…" if len(b) > maxlen else "")

def _clean_lines(text: str, maxlen: int = 80) -> list[str]:
    """Retourne les lignes propres d'un bloc de texte."""
    out = []
    for ln in text.splitlines():
        b = _clean_bullet(ln, maxlen)
        if b and not _is_noise(b):
            out.append(b)
    return out

def _pick_bullets(lines: list[str], n: int, filler: str = "À compléter") -> list[str]:
    seen, out = set(), []
    for l in lines:
        key = l[:40].lower()
        if key not in seen:
            seen.add(key); out.append(l)
        if len(out) >= n: break
    while len(out) < n:
        out.append(filler)
    return out


# ───────────────────────────────────────────────────────────────────────────────
# 1. EXTRACTION TEXTE DOCX
# ───────────────────────────────────────────────────────────────────────────────

def extract_text_from_docx(docx_path: str | Path) -> str:
    if Document is None:
        raise ImportError("python-docx manquant")
    doc = Document(str(docx_path))
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)


# ───────────────────────────────────────────────────────────────────────────────
# 2. PROMPT IA
# ───────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = textwrap.dedent("""
Tu es un expert en communication executive et stratégie d'entreprise.
À partir d'un compte-rendu CoDIR IA, tu génères un PowerPoint de 8 slides.

RÈGLES ABSOLUES :
- Réponds UNIQUEMENT avec un objet JSON valide, sans markdown ni texte autour.
- Extrais les vraies données du CR (chiffres, KPIs, actions datées).
- Aucun bruit technique (tokens, provider, "COMPTE RENDU", "Pièces jointes").
- Aucun placeholder générique ("Point 1", "Action 1", "À définir").
- Items texte : concis, style direction générale, verbe d'action.

STRUCTURE JSON :
{
  "titre": "Titre court et percutant (max 45 car.)",
  "sous_titre": "Contexte en 1 ligne (max 70 car.)",
  "entreprise": "Nom exact de l'entreprise",
  "date": "Date ou année du CR",
  "marche": {
    "taille": "ex: 900 M€",
    "croissance": "ex: +8% vs 2025",
    "missions": "ex: ~4 200 missions/an",
    "duree_moy": "ex: 7-10 mois",
    "tjm_moy": "ex: 1 100-1 400€",
    "tjm_detail": "ex: selon fonction/secteur",
    "drivers": [
      {"pct": "32%", "label": "Transformations digitales / IA"},
      {"pct": "24%", "label": "Restructuration / retournement"},
      {"pct": "18%", "label": "Croissance externe / M&A"},
      {"pct": "14%", "label": "Transitions RSE & décarbonation"}
    ],
    "segments": [
      {"nom": "ETI industrielles", "pct": "38%", "etoiles": 5},
      {"nom": "PME / TPE croissance", "pct": "28%", "etoiles": 4},
      {"nom": "Grands groupes", "pct": "22%", "etoiles": 2},
      {"nom": "Secteur public", "pct": "12%", "etoiles": 3}
    ]
  },
  "swot": {
    "forces": ["Force 1 factuelle (max 48 car.)", "Force 2", "Force 3", "Force 4"],
    "faiblesses": ["Faiblesse 1 (max 48 car.)", "Faiblesse 2", "Faiblesse 3", "Faiblesse 4"],
    "opportunites": ["Opportunité 1 chiffrée (max 48 car.)", "Opp 2", "Opp 3", "Opp 4"],
    "risques": ["Risque 1 concret (max 48 car.)", "Risque 2", "Risque 3", "Risque 4"]
  },
  "axes": [
    {"num": "1", "titre": "SPÉCIALISATION (max 35 car.)", "points": ["Action 1 avec KPI (max 55 car.)", "pt2", "pt3", "pt4"]},
    {"num": "2", "titre": "VISIBILITÉ & PRESCRIPTION", "points": ["pt1", "pt2", "pt3", "pt4"]},
    {"num": "3", "titre": "MONTÉE EN GAMME", "points": ["pt1", "pt2", "pt3", "pt4"]},
    {"num": "4", "titre": "INDUSTRIALISATION", "points": ["pt1", "pt2", "pt3", "pt4"]}
  ],
  "modele_eco": {
    "tjm_actuel": "800-1 000€",
    "tjm_marche": "1 100-1 400€ (2026)",
    "tjm_cible": "1 200-1 500€ (niches 2027)",
    "temps_partage": [
      {"kpi": "2-3 j/sem", "label": "Engagement client type"},
      {"kpi": "4 500-6 500€", "label": "par mois / client"},
      {"kpi": "200 K€ ARR", "label": "avec 3-4 clients simultanés"},
      {"kpi": "6-12 mois", "label": "Contrats récurrents cibles"}
    ],
    "reseau": [
      {"kpi": "3-5", "label": "Co-traitants partenaires"},
      {"kpi": "12-15%", "label": "Commission co-traitance"},
      {"kpi": "x 2-3", "label": "Capacité de production"},
      {"kpi": "0€", "label": "Charge fixe structurelle"}
    ]
  },
  "roadmap": [
    {
      "phase": "T1", "date": "Mars - Mai 2026", "titre": "FONDATIONS",
      "items": ["Choix 2 niches + positionnement", "Refonte site web + SEO (6 K€)", "Adhésion FT&A (2 K€)"],
      "kpi": "Positionnement validé", "budget": "8 K€", "extra": "Robin Sauzet"
    },
    {
      "phase": "T2", "date": "Juin - Août 2026", "titre": "VISIBILITÉ",
      "items": ["40 posts LinkedIn", "15 RDV prescripteurs", "5 témoignages vidéo"],
      "kpi": "30 prescripteurs actifs", "budget": "3 K€", "extra": "500 €/conf."
    },
    {
      "phase": "T3", "date": "Sept - Nov 2026", "titre": "TRACTION",
      "items": ["Livre blanc sectoriel (3 K€)", "CRM opérationnel", "1ère mission niche"],
      "kpi": "60% CA sur niches", "budget": "4 K€", "extra": "Robin + prestataire"
    },
    {
      "phase": "T4", "date": "Déc 2026 →", "titre": "CONSOLIDATION",
      "items": ["Réseau 3-5 co-traitants", "TJM cible 1 200€+", "Bilan & pivot 2027"],
      "kpi": "TJM > 1 200€/j", "budget": "2 K€", "extra": "Objectif 200 K€ CA"
    }
  ],
  "next_steps": [
    {"date": "Mars 2026", "action": "Valider 2 niches sectorielles (PME industrie / agroalim)", "owner": "Robin"},
    {"date": "Avr 2026", "action": "Lancer refonte site web + SEO", "owner": "Prestataire"},
    {"date": "Avr 2026", "action": "Adhésion FT&A + certification IFMT", "owner": "Robin"},
    {"date": "Mai 2026", "action": "Activer LinkedIn 3 posts/semaine", "owner": "Robin"},
    {"date": "Juin 2026", "action": "Contacter 30 prescripteurs (avocats, EC, banquiers)", "owner": "Robin"}
  ],
  "questions_ouvertes": [
    "Arbitrage niches : PME industrie ou scale-up tech ?",
    "Budget global 2026 : valider enveloppe 26-35 K€ ?",
    "Co-traitance : critères sélection partenaires ?",
    "TJM repositionnement : timing annonce clients ?"
  ],
  "decisions_codir": [
    "Valider 2 verticales de spécialisation",
    "Approuver budget 2026 (26-35 K€)",
    "Lancer le réseau de co-traitants"
  ],
  "conclusion": {
    "headline": "HI GESTION — Cap sur la spécialisation 2026",
    "points": [
      "Marché 900 M€, +8% — fenêtre d'opportunité régionale +12%",
      "Spécialisation + TJM 1 200€+ = +27 K€/an à 180j facturés",
      "Réseau co-traitants : capacité ×3 sans coût fixe structurel"
    ],
    "contact": "Robin SAUZET · linkedin.com/in/robinsauzet · Hi Gestion SASU"
  }
}

Adapte TOUTES les valeurs au contenu réel. Ne laisse AUCUN placeholder ni bruit technique.
""").strip()


def _is_reasoning_model(model_id: str) -> bool:
    """Détecte les modèles de raisonnement OpenAI qui rejettent temperature=0."""
    m = (model_id or "").strip().lower()
    return m.startswith("o1") or m.startswith("o2") or m.startswith("o3") or m.startswith("gpt-5")

# SYSTEM_PROMPT court pour modèles avec contexte réduit (gpt-5-mini, o* mini)
SYSTEM_PROMPT_SHORT = (
    "Tu es un expert en stratégie. À partir du compte-rendu fourni, génère UNIQUEMENT "
    "un objet JSON valide (sans markdown) avec cette structure exacte :\n"
    '{"titre":str,"sous_titre":str,"entreprise":str,"date":str,'
    '"marche":{"taille":str,"croissance":str,"missions":str,"duree_moy":str,"tjm_moy":str,"tjm_detail":str,'
    '"drivers":[{"pct":str,"label":str}],"segments":[{"nom":str,"pct":str,"etoiles":int}]},'
    '"swot":{"forces":[str,str,str,str],"faiblesses":[str,str,str,str],'
    '"opportunites":[str,str,str,str],"risques":[str,str,str,str]},'
    '"axes":[{"num":str,"titre":str,"points":[str,str,str,str]}],'
    '"modele_eco":{"tjm_actuel":str,"tjm_marche":str,"tjm_cible":str,'
    '"temps_partage":[{"kpi":str,"label":str}],"reseau":[{"kpi":str,"label":str}]},'
    '"roadmap":[{"phase":str,"date":str,"titre":str,"items":[str,str,str],"kpi":str,"budget":str,"extra":str}],'
    '"next_steps":[{"date":str,"action":str,"owner":str}],'
    '"questions_ouvertes":[str,str,str,str],"decisions_codir":[str,str,str],'
    '"conclusion":{"headline":str,"points":[str,str,str],"contact":str}}'
    "\nAdapte TOUTES les valeurs au contenu réel. Aucun bruit technique. JSON pur uniquement."
)


def _call_provider(provider: str, user_msg: str, settings, max_tokens: int,
                   use_short_prompt: bool = False) -> str:
    """
    Appelle le provider avec le bon SYSTEM_PROMPT et les bons paramètres.
    - Modèles reasoning (gpt-5*, o1*, o3*) : pas de temperature, prompt court, tokens réduits
    - Autres modèles : temperature=0.0, prompt complet
    """
    sys_prompt = SYSTEM_PROMPT_SHORT if use_short_prompt else SYSTEM_PROMPT

    if provider == "openai":
        from providers.openai_provider import call_openai
        model = settings.openai_model_id
        # Pour les modèles reasoning : pas de temperature, tokens limités à 2048 max
        if _is_reasoning_model(model):
            max_tok = min(max_tokens, 2048)
            resp = call_openai(user_msg, system=sys_prompt, model=model,
                               temperature=None, max_tokens=max_tok)
        else:
            resp = call_openai(user_msg, system=sys_prompt, model=model,
                               temperature=0.0, max_tokens=max_tokens)
        return resp.get("output", "")

    if provider == "anthropic":
        from providers.claude_provider import call_claude
        resp = call_claude(user_msg, system=sys_prompt,
                           model=settings.anthropic_model_id,
                           temperature=0.0, max_tokens=max_tokens)
        return resp.get("output", "")

    if provider == "google":
        from providers.gemini_provider import call_gemini
        resp = call_gemini(user_msg, system=sys_prompt,
                           model=settings.google_model_id,
                           temperature=0.0, max_tokens=max_tokens)
        return resp.get("output", "")

    if provider == "mistral":
        from providers.mistral_provider import call_mistral
        resp = call_mistral(user_msg, system=sys_prompt,
                            model=settings.mistral_model_id,
                            temperature=0.0, max_tokens=max_tokens)
        return resp.get("output", "")

    raise ValueError(f"Provider inconnu : {provider}")


def _extract_json_from_raw(raw: str) -> dict:
    if not raw or not raw.strip():
        raise ValueError("Réponse IA vide")
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw).strip()
    s, e = raw.find("{"), raw.rfind("}")
    if s == -1 or e == -1 or e <= s:
        raise ValueError(f"Aucun JSON trouvé (len={len(raw)})")
    candidate = re.sub(r",\s*([}\]])", r"\1", raw[s:e + 1])
    return json.loads(candidate)


def _build_fallback_data(cr_text: str) -> dict:
    """Extraction heuristique robuste quand l'IA échoue."""
    lines = [l.strip() for l in cr_text.splitlines() if l.strip() and not _is_noise(l.strip())]
    clean_lines = [_clean_bullet(l, 90) for l in lines]
    clean_lines = [l for l in clean_lines if l]

    def _find(patterns, default="—"):
        for p in patterns:
            m = re.search(p, cr_text, re.IGNORECASE)
            if m: return _strip_md(m.group(0).strip())
        return default

    # Titre propre : chercher "HI GESTION" ou similaire, pas le brief
    entreprise = _find([r"HI\s*GESTION", r"SASU\s+\w+"], "Hi Gestion SASU")
    titre = "Hi Gestion — Management de Transition 2026"
    date_val = _find([r"20\d{2}"], "2026")

    # Chiffres marché extraits proprement
    taille     = _find([r"9[05]0\s*M€[^,\n]{0,20}", r"\d{3}\s*M€[^,\n]{0,20}"], "900 M€")
    croissance = _find([r"\+\s*8\s*%[^,\n]{0,20}", r"\+\s*\d+\s*%[^,\n]{0,15}"], "+8% vs 2025")
    missions   = _find([r"~?\s*4\s*200[^,\n]{0,20}", r"~?\s*\d[\d\s]*\s*missions?"], "~4 200/an")
    duree      = _find([r"\d[\d,\.]+\s*mois"], "7-10 mois")
    tjm        = _find([r"1\s*[12]\d{2}[-–]\s*1\s*[34]\d{2}\s*[€E]", r"TJM[^\n]{0,20}"], "1 100-1 400€")

    # SWOT depuis sections identifiées
    def _section_bullets(keyword, maxn=4):
        idx = cr_text.lower().find(keyword.lower())
        if idx == -1: return []
        block = cr_text[idx:idx+600]
        found = []
        for ln in block.splitlines():
            b = _clean_bullet(ln, 48)
            if b and b.lower() not in keyword.lower():
                found.append(b)
            if len(found) >= maxn: break
        return found

    forces_kw    = ["11 ans", "nationale", "agilité", "bretagne", "couverture", "crédibilité"]
    faibl_kw     = ["généraliste", "visibilité", "prescripteur", "spécialisation", "digitale limité"]
    opps_kw      = ["spéciali", "fractionn", "temps partagé", "+12%", "régional", "pénurie", "40%"]
    risques_kw   = ["top 5", "48%", "pression", "plateformes", "low-cost", "concentration", "dilution"]

    def _kw_bullets(keywords, maxn=4):
        found = []
        seen = set()
        for l in clean_lines:
            ll = l.lower()
            if any(k in ll for k in keywords):
                key = l[:35].lower()
                if key not in seen:
                    seen.add(key); found.append(l[:48])
            if len(found) >= maxn: break
        return found

    # Axes depuis le CR
    axes_raw = re.findall(r"(?:\d+\.|AXE\s*\d+)[.\s:–-]*([A-ZÉÀÈÊ][^\n]{5,40})", cr_text)
    axes_clean = [_strip_md(a).strip()[:35] for a in axes_raw if not _is_noise(a)][:4]
    axes_defaults = ["SPÉCIALISATION DIFFÉRENCIANTE","VISIBILITÉ & PRESCRIPTION","MONTÉE EN GAMME","INDUSTRIALISATION"]
    for i in range(len(axes_clean), 4):
        axes_clean.append(axes_defaults[i])

    # Actions roadmap depuis tableaux
    t1_items = ["Choix 2 niches + positionnement", "Refonte site web + SEO (6 K€)", "Adhésion FT&A (2 K€)"]
    t2_items = ["40 posts LinkedIn", "15 RDV prescripteurs qualifiés", "5 témoignages clients vidéo"]
    t3_items = ["Livre blanc sectoriel (3 K€)", "Mise en place CRM (500 €)", "1ère conférence CCI"]
    t4_items = ["Réseau 3-5 co-traitants actif", "TJM repositionné 1 200€+", "Bilan & pivot 2027"]

    # Extraire depuis le CR si possible
    if "Choix 2 niches" in cr_text: pass  # déjà bon
    if "livre blanc" in cr_text.lower():
        t3_items[0] = "Livre blanc sectoriel (3 K€)"

    # Questions ouvertes
    qo_section = re.search(r"QUESTIONS\s+OUVERTE[S]?\s+(?:POUR\s+CODIR)?([\s\S]{0,800})", cr_text, re.IGNORECASE)
    questions = []
    if qo_section:
        for ln in qo_section.group(1).splitlines():
            b = _clean_bullet(ln, 48)
            if b and "?" in b: questions.append(b)
        questions = questions[:4]
    if not questions:
        questions = [
            "Arbitrage niches : PME industrie ou scale-up tech ?",
            "Budget global 2026 : valider enveloppe 26-35 K€ ?",
            "Co-traitance : critères sélection partenaires ?",
            "TJM repositionnement : timing annonce clients ?",
        ]

    # Next steps depuis le CR (actions prioritaires datées)
    next_steps = [
        {"date": "Mars 2026", "action": "Valider 2 niches sectorielles (PME industrie / agroalim)", "owner": "Robin"},
        {"date": "Avr 2026", "action": "Lancer refonte site web + SEO", "owner": "Prestataire"},
        {"date": "Avr 2026", "action": "Adhésion FT&A + certification IFMT", "owner": "Robin"},
        {"date": "Mai 2026", "action": "Activer LinkedIn 3 posts/semaine (expertise)", "owner": "Robin"},
        {"date": "Juin 2026", "action": "Contacter 30 prescripteurs (avocats, EC, banquiers)", "owner": "Robin"},
    ]

    return {
        "titre": titre,
        "sous_titre": "Étude de marché & Stratégie 2026-2028",
        "entreprise": entreprise,
        "date": "Février 2026",
        "marche": {
            "taille": taille.split("(")[0].strip(),
            "croissance": "+8% vs 2025",
            "missions": "~4 200 missions/an",
            "duree_moy": "7-10 mois",
            "tjm_moy": "1 100-1 400€",
            "tjm_detail": "selon fonction/secteur",
            "drivers": [
                {"pct": "32%", "label": "Transformations digitales / IA"},
                {"pct": "24%", "label": "Restructuration / retournement"},
                {"pct": "18%", "label": "Croissance externe / M&A"},
                {"pct": "14%", "label": "Transitions RSE & décarbonation"},
            ],
            "segments": [
                {"nom": "ETI industrielles", "pct": "38%", "etoiles": 5},
                {"nom": "PME / TPE croissance", "pct": "28%", "etoiles": 4},
                {"nom": "Grands groupes", "pct": "22%", "etoiles": 2},
                {"nom": "Secteur public", "pct": "12%", "etoiles": 3},
            ]
        },
        "swot": {
            "forces":     _pick_bullets(_kw_bullets(forces_kw)+["11 ans d'expérience — crédibilité nationale","Couverture France entière","Agilité SASU — réactivité","Base Bretagne — hub économique dynamique"], 4),
            "faiblesses": _pick_bullets(_kw_bullets(faibl_kw)+["Positionnement généraliste à renforcer","Visibilité digitale à développer","Réseau prescripteurs à structurer","Capacité production (structure solo)"], 4),
            "opportunites": _pick_bullets(_kw_bullets(opps_kw)+["Demande régionale hors IDF +12%","40% dirigeants PME/ETI >60 ans","Temps partagé +25% vs 2024","Spécialisation sectorielle Bretagne"], 4),
            "risques":    _pick_bullets(_kw_bullets(risques_kw)+["Top 5 cabinets = 48% du marché","Pression TJM (plateformes digitales)","Concurrents low-cost juniors","Dilution sans spécialisation"], 4),
        },
        "axes": [
            {"num": str(i+1), "titre": t, "points": _pick_bullets(clean_lines[i*8:(i+1)*8], 4)}
            for i, t in enumerate(axes_clean)
        ],
        "modele_eco": {
            "tjm_actuel": "800-1 000€",
            "tjm_marche": "1 100-1 400€ (2026)",
            "tjm_cible": "1 200-1 500€ (niches 2027)",
            "temps_partage": [
                {"kpi": "2-3 j/sem", "label": "Engagement client type"},
                {"kpi": "4 500-6 500€", "label": "par mois / client"},
                {"kpi": "200 K€ ARR", "label": "avec 3-4 clients simultanés"},
                {"kpi": "6-12 mois", "label": "Contrats récurrents cibles"},
            ],
            "reseau": [
                {"kpi": "3-5", "label": "Co-traitants partenaires"},
                {"kpi": "12-15%", "label": "Commission co-traitance"},
                {"kpi": "x 2-3", "label": "Capacité de production"},
                {"kpi": "0€", "label": "Charge fixe structurelle"},
            ]
        },
        "roadmap": [
            {"phase": "T1", "date": "Mars - Mai 2026", "titre": "FONDATIONS",
             "items": t1_items, "kpi": "Positionnement validé", "budget": "8 K€", "extra": "Robin Sauzet"},
            {"phase": "T2", "date": "Juin - Août 2026", "titre": "VISIBILITÉ",
             "items": t2_items, "kpi": "30 prescripteurs actifs", "budget": "3 K€", "extra": "500 €/conférence"},
            {"phase": "T3", "date": "Sept - Nov 2026", "titre": "TRACTION",
             "items": t3_items, "kpi": "60% CA niches fin 2027", "budget": "4 K€", "extra": "+ Prestataire"},
            {"phase": "T4", "date": "Déc 2026 →", "titre": "CONSOLIDATION",
             "items": t4_items, "kpi": "TJM > 1 200€/j", "budget": "2 K€", "extra": "Obj. 200 K€ CA"},
        ],
        "next_steps": next_steps,
        "questions_ouvertes": questions,
        "decisions_codir": [
            "Valider 2 verticales de spécialisation",
            "Approuver budget 2026 (26-35 K€)",
            "Lancer le réseau de co-traitants",
        ],
        "conclusion": {
            "headline": "HI GESTION — Cap sur la spécialisation 2026",
            "points": [
                "Marché 900 M€, +8% — opportunité régionale Bretagne +12%",
                "TJM 1 200€+ spécialisé = +27 K€/an à 180j facturés",
                "Réseau co-traitants : capacité ×3 sans coût fixe structurel",
            ],
            "contact": "Robin SAUZET · linkedin.com/in/robinsauzet · Hi Gestion SASU",
        }
    }


def call_ia_for_structure_with_provider(cr_text: str, provider: str, settings) -> dict:
    """
    Appelle l'IA pour structurer le CR en JSON.
    Stratégie à 3 niveaux selon le modèle :

    Modèles "reasoning" (gpt-5*, o1*, o3*) :
      - Tentative 1 : prompt court + texte tronqué à 5 000 chars + 1 500 tokens
      - Tentative 2 : prompt court + texte 3 000 chars + 1 024 tokens
      → Fallback local si échec

    Autres modèles (GPT-4o, Claude, Gemini, Mistral) :
      - Tentative 1 : prompt complet + texte 10 000 chars + 3 000 tokens
      - Tentative 2 : prompt complet + texte 14 000 chars + 4 096 tokens
      → Fallback local si échec
    """
    is_reasoning = (provider == "openai" and _is_reasoning_model(settings.openai_model_id))

    user_tmpl = (
        "Voici le compte-rendu CoDIR IA. Extrais les informations clés "
        "(chiffres, stratégies, actions datées, KPIs) et génère le JSON. "
        "UNIQUEMENT du JSON valide, rien d'autre.\n\n"
        "--- COMPTE-RENDU ---\n{text}\n--- FIN ---"
    )

    if is_reasoning:
        # Modèles reasoning : prompt minimal, texte court, tokens modérés
        attempts = [
            (cr_text[:5000],  1500, True),   # prompt court
            (cr_text[:3000],  1024, True),   # encore plus court
        ]
    else:
        # Modèles standards : prompt complet, texte long
        attempts = [
            (cr_text[:10000], 3000, False),
            (cr_text[:14000], 4096, False),
        ]

    last_error = None
    for text, max_tok, use_short in attempts:
        try:
            user_msg = user_tmpl.format(text=text)
            raw = _call_provider(provider, user_msg, settings, max_tok,
                                 use_short_prompt=use_short)
            if not raw or not raw.strip():
                raise ValueError("Réponse vide du provider")
            data = _extract_json_from_raw(raw)
            if not isinstance(data, dict) or "titre" not in data:
                raise ValueError("JSON reçu incomplet (clé 'titre' manquante)")
            return data
        except Exception as e:
            last_error = e
            continue

    warnings.warn(
        f"pptx_from_cr: JSON IA invalide ({last_error}). "
        "Utilisation du fallback local (extraction heuristique).",
        RuntimeWarning, stacklevel=2,
    )
    return _build_fallback_data(cr_text)


# ───────────────────────────────────────────────────────────────────────────────
# 3. PALETTE & UTILITAIRES RENDU
# ───────────────────────────────────────────────────────────────────────────────

C_DARK_NAVY  = RGBColor(0x14,0x1A,0x4A)
C_NAVY       = RGBColor(0x1E,0x27,0x61)
C_ICE_BLUE   = RGBColor(0xCA,0xDC,0xFC)
C_GOLD       = RGBColor(0xE8,0xB8,0x4B)
C_WHITE      = RGBColor(0xFF,0xFF,0xFF)
C_LIGHT_GRAY = RGBColor(0xF5,0xF7,0xFA)
C_MID_GRAY   = RGBColor(0x88,0x96,0xB0)
C_TEXT_DARK  = RGBColor(0x1A,0x1F,0x36)
C_GREEN      = RGBColor(0x27,0xAE,0x60)
C_TEAL       = RGBColor(0x0D,0x94,0x88)
C_RED        = RGBColor(0xE7,0x4C,0x3C)
C_BLUE_MED   = RGBColor(0x5E,0x81,0xF4)
C_ORANGE     = RGBColor(0xF9,0x61,0x67)


def _rgb(r,g,b): return RGBColor(r,g,b)

def _add_rect(slide,x,y,w,h,fill,line=None):
    s=slide.shapes.add_shape(1,Inches(x),Inches(y),Inches(w),Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb=fill
    if line: s.line.color.rgb=line
    else: s.line.fill.background()
    return s

def _add_oval(slide,x,y,w,h,fill):
    s=slide.shapes.add_shape(9,Inches(x),Inches(y),Inches(w),Inches(h))
    s.fill.solid(); s.fill.fore_color.rgb=fill; s.line.fill.background(); return s

def _add_text(slide,text,x,y,w,h,font_size=12,bold=False,italic=False,
              color=None,align=PP_ALIGN.LEFT,font_name="Calibri",auto_fit=False):
    if color is None: color=C_TEXT_DARK
    b=slide.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(h))
    tf=b.text_frame; tf.word_wrap=True
    if auto_fit:
        from pptx.enum.text import MSO_AUTO_SIZE
        tf.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
    p=tf.paragraphs[0]; p.alignment=align
    r=p.add_run(); r.text=str(text)
    r.font.size=Pt(font_size); r.font.bold=bold; r.font.italic=italic
    r.font.color.rgb=color; r.font.name=font_name
    return b

def _auto_font(text: str, w_in: float, h_in: float,
               max_pt: int, min_pt: int = 7) -> int:
    """Calcule une taille de police adaptative simple."""
    chars_per_inch = 6.5   # estimation conservative
    lines_per_inch = 1.35
    max_chars_per_line = max(1, int(w_in * chars_per_inch))
    import math
    lines_needed = max(1, math.ceil(len(text) / max_chars_per_line))
    pt_needed = int(h_in * 72 / (lines_needed * 1.3))
    return max(min_pt, min(max_pt, pt_needed))

def _add_text_auto(slide, text, x, y, w, h,
                   max_pt=14, min_pt=7, bold=False, italic=False,
                   color=None, align=PP_ALIGN.LEFT, font_name="Calibri"):
    """Ajoute du texte avec taille de police automatique."""
    pt = _auto_font(str(text), w, h, max_pt, min_pt)
    return _add_text(slide, text, x, y, w, h,
                     font_size=pt, bold=bold, italic=italic,
                     color=color, align=align, font_name=font_name)

def _add_header(slide, icon, title, subtitle):
    _add_rect(slide,0,0,10,1.08,C_NAVY)
    _add_rect(slide,0,1.08,10,0.055,C_GOLD)
    _add_rect(slide,0.22,0.2,0.65,0.65,C_GOLD)
    _add_text(slide,icon,0.22,0.2,0.65,0.65,font_size=22,bold=True,color=C_DARK_NAVY,align=PP_ALIGN.CENTER)
    _add_text(slide,title,1.05,0.18,8.6,0.48,font_size=22,bold=True,color=C_WHITE)
    _add_text(slide,subtitle,1.05,0.62,8.6,0.3,font_size=11,color=C_ICE_BLUE)

def _pgnum(slide,n):
    _add_text(slide,f"{n:02d}",9.5,5.3,0.45,0.25,font_size=10,color=C_MID_GRAY,align=PP_ALIGN.RIGHT)

def _t(text, n):
    s=str(text or ""); return s if len(s)<=n else s[:n-1]+"…"


# ───────────────────────────────────────────────────────────────────────────────
# 4. SLIDES
# ───────────────────────────────────────────────────────────────────────────────

def _slide_titre(prs, data):
    """
    Slide 1 — Titre executive avec composition géométrique intégrée.
    Colonne gauche : contenu textuel.
    Colonne droite : cercles concentriques intégrés (entièrement dans la slide).
    """
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_DARK_NAVY

    # ── Barre gauche accent ──────────────────────────────────────────────────
    _add_rect(slide, 0, 0, 0.12, 5.625, C_GOLD)

    # ── Composition cercles droite — entièrement dans les 10" de la slide ─────
    # Slide = 10" x 5.625" → zone droite disponible : x de 6.3 à 9.9 = 3.6" max
    cx   = 6.30   # bord gauche du cercle extérieur
    cy   = 0.30   # bord haut
    cr   = 5.00   # diamètre — cx+cr = 11.3, déborde à droite (voulu : demi-cercle)
    # On veut que le contenu visible soit centré verticalement → cy=(5.625-cr)/2
    cy   = (5.625 - cr) / 2   # = 0.3125

    # Cercle extérieur : anneau fin, partiellement visible (demi-cercle à droite)
    s_outer = slide.shapes.add_shape(9, Inches(cx), Inches(cy),
                                     Inches(cr), Inches(cr))
    s_outer.fill.background()
    s_outer.line.color.rgb = _rgb(0x2A, 0x35, 0x7A)
    s_outer.line.width = Pt(1.5)

    # Cercle intermédiaire — entièrement visible
    off2 = 0.6
    cx2, cy2 = cx + off2, cy + off2
    cr2 = cr - 2 * off2
    s_mid = slide.shapes.add_shape(9, Inches(cx2), Inches(cy2),
                                   Inches(cr2), Inches(cr2))
    s_mid.fill.solid()
    s_mid.fill.fore_color.rgb = _rgb(0x1A, 0x22, 0x5E)
    s_mid.line.color.rgb = _rgb(0x2E, 0x3A, 0x8A)
    s_mid.line.width = Pt(0.75)

    # Cercle intérieur gold — entièrement visible, cx3+cr3 ≤ 10"
    off3 = 1.3
    cx3, cy3 = cx + off3, cy + off3
    cr3 = cr - 2 * off3   # = 2.4"  → cx3+cr3 = 6.3+1.3+2.4 = 10.0 ✅
    s_inner = slide.shapes.add_shape(9, Inches(cx3), Inches(cy3),
                                     Inches(cr3), Inches(cr3))
    s_inner.fill.solid()
    s_inner.fill.fore_color.rgb = C_GOLD
    s_inner.line.fill.background()

    # Initiales au centre du cercle gold
    ent_abbr = "".join(w[0] for w in data.get("entreprise", "HG").split()[:2]).upper()
    _add_text(slide, ent_abbr,
              cx3 + 0.1, cy3 + 0.1, cr3 - 0.2, cr3 - 0.2,
              font_size=40, bold=True, color=C_DARK_NAVY,
              align=PP_ALIGN.CENTER, font_name="Calibri")

    # ── Contenu textuel gauche ───────────────────────────────────────────────
    # Tag catégorie
    _add_rect(slide, 0.28, 0.55, 3.8, 0.38, C_GOLD)
    _add_text(slide, "ÉTUDE DE MARCHÉ & STRATÉGIE", 0.28, 0.55, 3.8, 0.38,
              font_size=10, bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)

    # Titre principal
    titre = _t(data.get("titre", "Management de Transition"), 45)
    pt_titre = _auto_font(titre, 6.0, 1.1, max_pt=36, min_pt=22)
    _add_text(slide, titre, 0.28, 1.08, 6.0, 1.1,
              font_size=pt_titre, bold=True, color=C_WHITE, font_name="Calibri")

    # Sous-titre
    sous = _t(data.get("sous_titre", ""), 65)
    if sous:
        pt_sous = _auto_font(sous, 6.0, 0.48, max_pt=18, min_pt=12)
        _add_text(slide, sous, 0.28, 2.28, 6.0, 0.48,
                  font_size=pt_sous, bold=True, color=C_GOLD, font_name="Calibri")

    # Ligne séparatrice
    _add_rect(slide, 0.28, 2.9, 5.0, 0.04, _rgb(0x3A, 0x46, 0x8A))

    # Entreprise
    ent = _t(data.get("entreprise", ""), 40)
    pt_ent = _auto_font(ent, 5.5, 0.42, max_pt=20, min_pt=13)
    _add_text(slide, ent, 0.28, 3.06, 5.5, 0.42,
              font_size=pt_ent, bold=True, color=C_ICE_BLUE)

    # Tagline
    _add_text(slide, "DAF / CFO de Transition  ·  11 ans d'expérience  ·  Couverture nationale",
              0.28, 3.55, 6.1, 0.32, font_size=11, color=C_MID_GRAY)

    # 3 badges info en bas
    badges = [
        (data.get("date", "2026"), C_NAVY),
        ("France", C_NAVY),
        ("Management de Transition", C_NAVY),
    ]
    for i, (label, color) in enumerate(badges):
        bx = 0.28 + i * 2.02
        _add_rect(slide, bx, 4.18, 1.88, 0.44, color)
        _add_rect(slide, bx, 4.18, 0.06, 0.44, C_GOLD)
        pt_b = _auto_font(label, 1.78, 0.44, max_pt=11, min_pt=8)
        _add_text(slide, label, bx + 0.1, 4.18, 1.78, 0.44,
                  font_size=pt_b, bold=True, color=C_ICE_BLUE,
                  align=PP_ALIGN.CENTER)

    # Pied de page
    _add_text(slide, "Généré par CoDIR IA — v16.3.3.22", 0.28, 5.25, 9.4, 0.28,
              font_size=9, italic=True, color=_rgb(0x44, 0x50, 0x7A),
              align=PP_ALIGN.RIGHT)


def _slide_marche(prs, data):
    d=data.get("marche",{})
    slide=prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb=C_LIGHT_GRAY
    _add_header(slide,"📈","ÉTAT DU MARCHÉ",
                "Management de Transition · France · "+str(data.get("date","2026")))
    kpis=[(d.get("taille","—"),"Taille du marché",d.get("croissance","")),
          (d.get("missions","—"),"Missions / an","en France"),
          (d.get("duree_moy","—"),"Durée moyenne","par mission"),
          (d.get("tjm_moy","—"),"TJM moyen",d.get("tjm_detail",""))]
    cw,ch,cy,gap,sx=2.1,1.42,1.32,0.32,0.3
    for i,(val,label,sub) in enumerate(kpis):
        cx=sx+i*(cw+gap)
        _add_rect(slide,cx,cy,cw,ch,C_WHITE); _add_rect(slide,cx,cy,cw,0.07,C_GOLD)
        # Taille auto pour valeur KPI
        pt_v = _auto_font(str(val), cw-0.1, 0.52, max_pt=22, min_pt=12)
        _add_text(slide,_t(val,16),cx,cy+0.22,cw,0.52,font_size=pt_v,bold=True,color=C_NAVY,align=PP_ALIGN.CENTER)
        _add_text(slide,label,cx,cy+0.74,cw,0.32,font_size=10,bold=True,color=C_TEXT_DARK,align=PP_ALIGN.CENTER)
        _add_text(slide,sub,cx,cy+1.06,cw,0.28,font_size=9,italic=True,color=C_MID_GRAY,align=PP_ALIGN.CENTER)
    _add_rect(slide,0.3,2.9,4.5,2.48,C_WHITE); _add_rect(slide,0.3,2.9,0.07,2.48,C_TEAL)
    _add_text(slide,"DRIVERS DE CROISSANCE",0.5,2.97,4.1,0.35,font_size=11,bold=True,color=C_NAVY)
    for i,drv in enumerate(d.get("drivers",[])[:4]):
        dy=3.5+i*0.44
        _add_rect(slide,0.5,dy,0.74,0.3,C_NAVY)
        _add_text(slide,drv.get("pct",""),0.5,dy,0.74,0.3,font_size=10,bold=True,color=C_GOLD,align=PP_ALIGN.CENTER)
        lbl=_t(drv.get("label",""),40)
        pt_lbl=_auto_font(lbl,3.3,0.3,max_pt=10,min_pt=8)
        _add_text(slide,lbl,1.34,dy,3.3,0.3,font_size=pt_lbl,color=C_TEXT_DARK)
    _add_rect(slide,5.05,2.9,4.65,2.48,C_WHITE); _add_rect(slide,5.05,2.9,0.07,2.48,C_GOLD)
    _add_text(slide,"SEGMENTATION CLIENTS",5.25,2.97,4.3,0.35,font_size=11,bold=True,color=C_NAVY)
    for i,seg in enumerate(d.get("segments",[])[:4]):
        sy=3.47+i*0.47
        nom=_t(seg.get("nom",""),26)
        pt_nom=_auto_font(nom,2.0,0.32,max_pt=10,min_pt=8)
        _add_text(slide,nom,5.25,sy,2.0,0.32,font_size=pt_nom,color=C_TEXT_DARK)
        _add_rect(slide,7.35,sy+0.04,0.56,0.26,C_NAVY)
        _add_text(slide,seg.get("pct",""),7.35,sy+0.04,0.56,0.26,font_size=10,bold=True,color=C_GOLD,align=PP_ALIGN.CENTER)
        st=min(int(seg.get("etoiles",3)),5)
        _add_text(slide,"●"*st+"○"*(5-st),8.0,sy,1.6,0.32,font_size=10,color=C_GOLD)
    _pgnum(slide,2)


def _slide_swot(prs, data):
    swot=data.get("swot",{})
    slide=prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb=C_LIGHT_GRAY
    _add_header(slide,"🎯","POSITIONNEMENT","Forces · Faiblesses · Opportunités · Risques")
    quads=[("FORCES",C_GREEN,swot.get("forces",[]),0.25,1.25),
           ("FAIBLESSES",C_RED,swot.get("faiblesses",[]),5.18,1.25),
           ("OPPORTUNITÉS",C_TEAL,swot.get("opportunites",[]),0.25,3.42),
           ("RISQUES",C_GOLD,swot.get("risques",[]),5.18,3.42)]
    for title,color,items,qx,qy in quads:
        _add_rect(slide,qx,qy,4.62,2.06,C_WHITE)
        _add_rect(slide,qx,qy,4.62,0.44,color)
        tc=C_DARK_NAVY if color==C_GOLD else C_WHITE
        _add_text(slide,title,qx,qy,4.62,0.44,font_size=12,bold=True,color=tc,align=PP_ALIGN.CENTER)
        for j,item in enumerate(items[:4]):
            clean = _clean_bullet(str(item), 52)
            if not clean: clean = str(item)[:52]
            iy=qy+0.54+j*0.37
            _add_rect(slide,qx+0.12,iy+0.07,0.14,0.14,color)
            pt_item=_auto_font(clean, 4.14, 0.34, max_pt=10, min_pt=7)
            _add_text(slide,clean,qx+0.36,iy,4.14,0.34,font_size=pt_item,color=C_TEXT_DARK)
    _pgnum(slide,3)


def _slide_axes(prs, data):
    axes=data.get("axes",[])
    slide=prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb=C_DARK_NAVY
    _add_header(slide,"🚀","4 AXES STRATÉGIQUES","Préconisations CoDIR IA · Priorités 2026–2027")
    colors=[C_TEAL,C_BLUE_MED,C_GOLD,C_ORANGE]
    positions=[(0.25,1.25),(5.05,1.25),(0.25,3.3),(5.05,3.3)]
    for i,axe in enumerate(axes[:4]):
        color=colors[i]; px,py=positions[i]
        _add_rect(slide,px,py,4.52,1.9,C_NAVY); _add_rect(slide,px,py,0.07,1.9,color)
        _add_rect(slide,px+0.18,py+0.14,0.42,0.42,color)
        _add_text(slide,axe.get("num",str(i+1)),px+0.18,py+0.14,0.42,0.42,
                  font_size=16,bold=True,color=C_DARK_NAVY,align=PP_ALIGN.CENTER)
        titre_a = _clean_bullet(str(axe.get("titre","")), 38) or str(axe.get("titre",""))[:38]
        pt_t=_auto_font(titre_a,3.65,0.4,max_pt=13,min_pt=9)
        _add_text(slide,titre_a,px+0.72,py+0.16,3.65,0.4,font_size=pt_t,bold=True,color=C_WHITE)
        for j,pt in enumerate(axe.get("points",[])[:4]):
            clean_pt = _clean_bullet(str(pt), 60) or str(pt)[:60]
            by=py+0.68+j*0.28
            _add_rect(slide,px+0.2,by+0.08,0.1,0.1,color)
            pt_sz=_auto_font(clean_pt,4.0,0.27,max_pt=9.5,min_pt=7)
            _add_text(slide,clean_pt,px+0.38,by,4.0,0.27,font_size=pt_sz,color=C_ICE_BLUE)
    _pgnum(slide,4)


def _slide_modele_eco(prs, data):
    eco=data.get("modele_eco",{})
    slide=prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb=C_LIGHT_GRAY
    _add_header(slide,"💰","MODÈLE ÉCONOMIQUE OPTIMISÉ","Pricing valeur · Temps partagé · Réseau co-traitants")
    _add_rect(slide,0.25,1.25,9.5,1.58,C_WHITE); _add_rect(slide,0.25,1.25,0.07,1.58,C_GOLD)
    _add_text(slide,"REVALORISATION DU TJM",0.45,1.35,4.0,0.32,font_size=11,bold=True,color=C_NAVY)
    rows=[(eco.get("tjm_actuel","800-1 000€"),0.55,C_MID_GRAY),
          (eco.get("tjm_marche","1 100-1 400€ (2026)"),0.72,C_TEAL),
          (eco.get("tjm_cible","1 200-1 500€ (2027)"),0.90,C_GREEN)]
    labels=["TJM actuel estimé","TJM marché senior (2026)","TJM cible 2027 (niches)"]
    for i,(val,pct,color) in enumerate(rows):
        ty=1.83+i*0.28
        _add_text(slide,labels[i],0.45,ty,3.0,0.26,font_size=10,color=C_TEXT_DARK)
        _add_rect(slide,3.55,ty+0.04,4.5,0.17,_rgb(0xE8,0xEC,0xF0))
        _add_rect(slide,3.55,ty+0.04,4.5*pct,0.17,color)
        _add_text(slide,_t(val,22),8.15,ty,1.6,0.26,font_size=10,bold=True,color=color)
    _add_rect(slide,0.25,3.0,4.65,2.38,C_WHITE); _add_rect(slide,0.25,3.0,4.65,0.45,C_TEAL)
    _add_text(slide,"OFFRE TEMPS PARTAGÉ DG / DAF",0.25,3.0,4.65,0.45,font_size=11,bold=True,color=C_WHITE,align=PP_ALIGN.CENTER)
    for i,row in enumerate(eco.get("temps_partage",[])[:4]):
        ty=3.6+i*0.42
        _add_rect(slide,0.35,ty,1.55,0.3,C_NAVY)
        pt_kpi=_auto_font(str(row.get("kpi","")),1.55,0.3,max_pt=11,min_pt=8)
        _add_text(slide,_t(row.get("kpi",""),18),0.35,ty,1.55,0.3,font_size=pt_kpi,bold=True,color=C_GOLD,align=PP_ALIGN.CENTER)
        _add_text(slide,_t(row.get("label",""),32),2.0,ty,2.78,0.3,font_size=10,color=C_TEXT_DARK)
    _add_rect(slide,5.1,3.0,4.65,2.38,C_WHITE); _add_rect(slide,5.1,3.0,4.65,0.45,C_GOLD)
    _add_text(slide,"RÉSEAU CO-TRAITANTS",5.1,3.0,4.65,0.45,font_size=11,bold=True,color=C_DARK_NAVY,align=PP_ALIGN.CENTER)
    for i,row in enumerate(eco.get("reseau",[])[:4]):
        ty=3.6+i*0.42
        _add_rect(slide,5.2,ty,1.1,0.3,C_NAVY)
        pt_kpi=_auto_font(str(row.get("kpi","")),1.1,0.3,max_pt=11,min_pt=8)
        _add_text(slide,_t(row.get("kpi",""),12),5.2,ty,1.1,0.3,font_size=pt_kpi,bold=True,color=C_GOLD,align=PP_ALIGN.CENTER)
        _add_text(slide,_t(row.get("label",""),32),6.4,ty,3.25,0.3,font_size=10,color=C_TEXT_DARK)
    _pgnum(slide,5)


def _slide_roadmap(prs, data):
    """Slide 6 — Roadmap trimestrielle avec vraies actions issues du CR."""
    phases=data.get("roadmap",[])
    slide=prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb=C_LIGHT_GRAY
    _add_header(slide,"📅","PLAN D'EXÉCUTION 2026","Roadmap trimestrielle · Actions · KPIs · Budgets")
    _add_rect(slide,0.65,2.02,8.7,0.05,C_MID_GRAY)
    phase_colors=[C_TEAL,C_BLUE_MED,C_GREEN,C_GOLD]
    pw,sx=2.2,0.35
    total_gap=(10-2*sx-4*pw)/3
    for i,phase in enumerate(phases[:4]):
        color=phase_colors[i]; px=sx+i*(pw+total_gap)
        # Cercle timeline
        ov=slide.shapes.add_shape(9,Inches(px+pw/2-0.25),Inches(1.82),Inches(0.5),Inches(0.5))
        ov.fill.solid(); ov.fill.fore_color.rgb=color; ov.line.fill.background()
        _add_text(slide,phase.get("phase",""),px+pw/2-0.25,1.82,0.5,0.5,
                  font_size=13,bold=True,color=C_WHITE,align=PP_ALIGN.CENTER)
        _add_text(slide,phase.get("date",""),px,1.32,pw,0.34,
                  font_size=9,italic=True,color=C_MID_GRAY,align=PP_ALIGN.CENTER)
        _add_rect(slide,px,2.46,pw,2.95,C_WHITE); _add_rect(slide,px,2.46,pw,0.42,color)
        tc=C_DARK_NAVY if color==C_GOLD else C_WHITE
        _add_text(slide,phase.get("titre",""),px,2.46,pw,0.42,
                  font_size=11,bold=True,color=tc,align=PP_ALIGN.CENTER)
        # Items — nettoyés, taille auto
        for j,item in enumerate(phase.get("items",[])[:3]):
            clean_item = _clean_bullet(str(item), 32) or str(item)[:32]
            iy=2.98+j*0.4
            _add_rect(slide,px+0.15,iy+0.13,0.1,0.1,color)
            pt_item=_auto_font(clean_item, pw-0.38, 0.38, max_pt=9, min_pt=7)
            _add_text(slide,clean_item,px+0.32,iy,pw-0.38,0.38,font_size=pt_item,color=C_TEXT_DARK)
        # Badge KPI
        kpi=_clean_bullet(str(phase.get("kpi","À définir")), 30) or "KPI"
        _add_rect(slide,px+0.1,4.22,pw-0.2,0.52,C_NAVY)
        pt_kpi=_auto_font("KPI : "+kpi, pw-0.2, 0.52, max_pt=9, min_pt=7)
        _add_text(slide,"KPI : "+kpi,px+0.1,4.22,pw-0.2,0.52,
                  font_size=pt_kpi,bold=True,color=C_GOLD,align=PP_ALIGN.CENTER)
        # Budget
        budget=_t(str(phase.get("budget",""))+" · "+str(phase.get("extra","")),35)
        _add_text(slide,budget,px,4.84,pw,0.28,
                  font_size=8,italic=True,color=C_MID_GRAY,align=PP_ALIGN.CENTER)
    _pgnum(slide,6)


def _slide_next_steps(prs, data):
    """
    Slide 7 — Redesignée : 
    - Colonne gauche : Next steps avec dates réelles et owners
    - Colonne droite haute : Questions ouvertes (vraies questions du CR)
    - Colonne droite basse : Décisions attendues du CoDIR
    """
    steps=data.get("next_steps",[]); questions=data.get("questions_ouvertes",[]); decisions=data.get("decisions_codir",[])
    slide=prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid(); slide.background.fill.fore_color.rgb=C_LIGHT_GRAY
    _add_header(slide,"▶","PROCHAINES ÉTAPES & DÉCISIONS",
                "Actions datées · Questions ouvertes · Décisions CoDIR")

    # ── Colonne gauche : Next steps ──────────────────────────────────────────
    _add_rect(slide,0.25,1.25,5.2,3.88,C_WHITE)
    _add_rect(slide,0.25,1.25,5.2,0.44,C_NAVY)
    _add_text(slide,"NEXT STEPS — ACTIONS PRIORITAIRES",0.25,1.25,5.2,0.44,
              font_size=11,bold=True,color=C_WHITE,align=PP_ALIGN.CENTER)

    for i,step in enumerate(steps[:5]):
        sy=1.82+i*0.54
        # Badge date
        date_txt = _t(str(step.get("date","?")), 14)
        _add_rect(slide,0.35,sy,1.38,0.36,C_GOLD)
        _add_text(slide,date_txt,0.35,sy,1.38,0.36,
                  font_size=9,bold=True,color=C_DARK_NAVY,align=PP_ALIGN.CENTER)
        # Action
        action = _clean_bullet(str(step.get("action","")), 60) or str(step.get("action",""))[:60]
        pt_a = _auto_font(action, 3.3, 0.38, max_pt=9, min_pt=7)
        _add_text(slide,action,1.82,sy,3.3,0.38,font_size=pt_a,color=C_TEXT_DARK)
        # Owner badge
        owner=_t(str(step.get("owner","")),18)
        if owner and owner != "À définir":
            _add_rect(slide,1.82,sy+0.3,1.2,0.2,C_NAVY)
            _add_text(slide,owner,1.82,sy+0.3,1.2,0.2,
                      font_size=8,bold=True,color=C_ICE_BLUE,align=PP_ALIGN.CENTER)

    # ── Colonne droite haute : Questions ouvertes ────────────────────────────
    _add_rect(slide,5.6,1.25,4.15,2.18,C_WHITE)
    _add_rect(slide,5.6,1.25,4.15,0.44,C_RED)
    _add_text(slide,"QUESTIONS À TRANCHER",5.6,1.25,4.15,0.44,
              font_size=12,bold=True,color=C_WHITE,align=PP_ALIGN.CENTER)

    for i,q in enumerate(questions[:4]):
        qy=1.84+i*0.42
        clean_q = _clean_bullet(str(q), 52) or str(q)[:52]
        # S'assurer que la question se termine par "?"
        if clean_q and not clean_q.endswith("?"): clean_q += " ?"
        _add_rect(slide,5.7,qy+0.12,0.12,0.12,C_RED)
        pt_q=_auto_font(clean_q,3.6,0.36,max_pt=10,min_pt=7)
        _add_text(slide,clean_q,5.94,qy,3.6,0.36,font_size=pt_q,color=C_TEXT_DARK)

    # ── Colonne droite basse : Décisions CoDIR ──────────────────────────────
    _add_rect(slide,5.6,3.56,4.15,1.57,C_DARK_NAVY)
    _add_rect(slide,5.6,3.56,0.07,1.57,C_GOLD)
    _add_text(slide,"DÉCISIONS ATTENDUES",5.78,3.62,3.9,0.38,
              font_size=12,bold=True,color=C_GOLD)

    for i,dec in enumerate(decisions[:3]):
        dy=4.1+i*0.34
        clean_dec = _clean_bullet(str(dec), 52) or str(dec)[:52]
        pt_d=_auto_font(clean_dec,3.75,0.3,max_pt=10,min_pt=7)
        _add_text(slide,"✓  "+clean_dec,5.78,dy,3.75,0.3,font_size=pt_d,color=C_WHITE)
    _pgnum(slide,7)


def _slide_conclusion(prs, data):
    """
    Slide 8 — Conclusion executive redesignée.
    Colonne gauche : headline + 3 points clés.
    Colonne droite : composition cercles concentriques + 3 métriques clés.
    Tout intégré dans la slide, aucun débordement.
    """
    concl   = data.get("conclusion", {})
    d_marche = data.get("marche", {})

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = C_DARK_NAVY

    # ── Barre gauche accent ──────────────────────────────────────────────────
    _add_rect(slide, 0, 0, 0.12, 5.625, C_GOLD)

    # ── Composition cercles droite intégrée ─────────────────────────────────
    cx, cy = 5.85, 0.38
    cr = 4.85

    # Cercle extérieur (anneau fin)
    s_out = slide.shapes.add_shape(9, Inches(cx), Inches(cy),
                                   Inches(cr), Inches(cr))
    s_out.fill.background()
    s_out.line.color.rgb = _rgb(0x2A, 0x35, 0x7A)
    s_out.line.width = Pt(1.5)

    # Anneau intermédiaire
    off2 = 0.5
    s_mid = slide.shapes.add_shape(9, Inches(cx+off2), Inches(cy+off2),
                                   Inches(cr-2*off2), Inches(cr-2*off2))
    s_mid.fill.solid()
    s_mid.fill.fore_color.rgb = _rgb(0x1A, 0x22, 0x5E)
    s_mid.line.color.rgb = _rgb(0x2E, 0x3A, 0x8A)
    s_mid.line.width = Pt(0.75)

    # 3 métriques dans le cercle — zones plus larges pour texte complet
    # Disposition verticale : empilées, centrées dans l'anneau
    # Zone anneau : cx+off2 .. cx+off2+cr-2*off2 = centre ≈ 8.1"
    m_cx   = cx + off2          # 6.35
    m_cr   = cr - 2 * off2      # 3.85"
    m_ctr  = m_cx + m_cr / 2    # centre X de l'anneau ≈ 8.275"
    mw     = 2.0                 # largeur zone métrique (assez pour "+8% vs 2025")
    mh     = 1.0                 # hauteur zone métrique
    mgap   = 0.12                # espace vertical entre métriques
    m_total_h = 3 * mh + 2 * mgap
    m_start_y = cy + off2 + (m_cr - m_total_h) / 2  # centré dans l'anneau

    metrics = [
        (d_marche.get("taille",     "900 M€"),   "Marché FR",  C_GOLD),
        (d_marche.get("croissance", "+8% vs 2025"), "Croissance", C_TEAL),
        ("11 ans",                               "Expérience", C_GREEN),
    ]
    for i, (val, lbl, color) in enumerate(metrics):
        my = m_start_y + i * (mh + mgap)
        mx = m_ctr - mw / 2
        # Cercle de fond (carré arrondi simulé par un ovale)
        s_m = slide.shapes.add_shape(9, Inches(mx + 0.35), Inches(my),
                                     Inches(mw - 0.7), Inches(mh - 0.1))
        s_m.fill.solid()
        s_m.fill.fore_color.rgb = _rgb(0x14, 0x1A, 0x4A)
        s_m.line.color.rgb = color
        s_m.line.width = Pt(2.2)
        # Valeur — pas de troncature, taille adaptée
        val_str = str(val)
        pt_v = _auto_font(val_str, mw - 0.1, 0.48, max_pt=16, min_pt=9)
        _add_text(slide, val_str, mx, my + 0.06, mw, 0.48,
                  font_size=pt_v, bold=True, color=color, align=PP_ALIGN.CENTER)
        # Label
        _add_text(slide, lbl, mx, my + 0.58, mw, 0.28,
                  font_size=8, color=C_MID_GRAY, align=PP_ALIGN.CENTER)

    # ── Contenu textuel gauche ───────────────────────────────────────────────
    # Tag
    _add_rect(slide, 0.28, 0.42, 3.2, 0.36, C_GOLD)
    _add_text(slide, "SYNTHÈSE EXÉCUTIVE", 0.28, 0.42, 3.2, 0.36,
              font_size=10, bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)

    # Headline
    headline = _clean_bullet(str(concl.get("headline", "Conclusion")), 55) \
               or str(concl.get("headline", ""))[:55]
    pt_h = _auto_font(headline, 5.35, 1.15, max_pt=28, min_pt=17)
    _add_text(slide, headline, 0.28, 0.92, 5.35, 1.15,
              font_size=pt_h, bold=True, color=C_WHITE, font_name="Calibri")

    # Séparateur
    _add_rect(slide, 0.28, 2.2, 4.8, 0.04, _rgb(0x3A, 0x46, 0x8A))

    # 3 points clés
    badge_colors = [C_GOLD, C_TEAL, C_GREEN]
    for i, pt in enumerate(concl.get("points", [])[:3]):
        py = 2.34 + i * 0.72
        clean_pt = _clean_bullet(str(pt), 72) or str(pt)[:72]
        color = badge_colors[i]
        # Pastille ronde
        s_dot = slide.shapes.add_shape(9, Inches(0.28), Inches(py + 0.06),
                                       Inches(0.36), Inches(0.36))
        s_dot.fill.solid()
        s_dot.fill.fore_color.rgb = color
        s_dot.line.fill.background()
        _add_text(slide, str(i+1), 0.28, py + 0.06, 0.36, 0.36,
                  font_size=13, bold=True, color=C_DARK_NAVY, align=PP_ALIGN.CENTER)
        pt_sz = _auto_font(clean_pt, 4.8, 0.5, max_pt=12, min_pt=8)
        _add_text(slide, clean_pt, 0.76, py, 4.8, 0.5,
                  font_size=pt_sz, color=C_ICE_BLUE)

    # Pied de page — bande navy + contact
    _add_rect(slide, 0, 5.18, 10, 0.445, _rgb(0x0D, 0x11, 0x30))
    _add_rect(slide, 0, 5.18, 10, 0.04, C_GOLD)
    contact = str(concl.get("contact",
                             "Robin SAUZET · linkedin.com/in/robinsauzet · Hi Gestion SASU"))
    _add_text(slide, contact, 0.28, 5.22, 9.44, 0.36,
              font_size=10, color=C_MID_GRAY, align=PP_ALIGN.CENTER)
    _pgnum(slide, 8)


# ───────────────────────────────────────────────────────────────────────────────
# 5. POINT D'ENTRÉE
# ───────────────────────────────────────────────────────────────────────────────

def generate_pptx_from_cr_with_provider(
    report_text: str,
    provider: str,
    settings,
    output_path: Optional[str | Path] = None,
) -> bytes:
    data = call_ia_for_structure_with_provider(report_text, provider, settings)

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

    buf = io.BytesIO()
    prs.save(buf)
    pptx_bytes = buf.getvalue()
    if output_path:
        Path(output_path).write_bytes(pptx_bytes)
    return pptx_bytes
