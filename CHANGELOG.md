# Changelog — CoDIR IA

Toutes les modifications notables sont documentées ici.
Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/).

---

## [16.3.3.22] — 2026-02-15

### Ajouté
- **Export PPT visuel professionnel** (palette Navy / Or) :
  - Slide titre : fond Navy foncé, titre blanc/or, barre dorée, badge date, décor géométrique
  - Slides contenu : fond gris clair, header Navy avec icône sur fond or, carte blanche avec bordure colorée
  - Slide plan d'action : fond Navy foncé, cartes par direction avec badge coloré (Teal / Orange / Vert / Or)
  - Couleurs de contenu cycliques par thème (Teal, Bleu, Vert, Orange, Rouge, Or, Navy)
  - Numéros de page, numéros de bullets, sous-titres en italique
- **Module `utils/pptx_from_cr.py`** (v1.0.0) : déplacé dans `experimental/` — module spécialisé (schéma marché/SWOT/roadmap), non utilisé par `app.py`, disponible pour usage avancé futur

### Modifié
- `utils/pptx_export.py` : refonte complète du rendu visuel (API publique inchangée, rétrocompatible)
- Version incrémentée v16.3.3.22

---

## [16.3.3.21] — 2026-02-15

### Corrigé
- **Windows** : correction `SyntaxError` dans `app.py` qui empêchait Streamlit de démarrer

### Amélioré
- Export **PPTX** business-grade : 5–10 slides, bullets propres, chiffres clés conservés
- Setup discret avec progression [1/5]…[5/5] + logs dans `outputs/`
- Alignement Windows / macOS

---

## [16.3.3.20] — 2026-02-14

### Amélioré
- Export PPTX : nettoyage bruit technique, priorité DG/CEO
- Fallback local PPTX par sections + heuristiques métiers

---

## [16.3.3.16] — 2026-02-11

### Corrigé
- Raccourci Windows : lancement fiable via wscript/VBS
- Setup Windows plus robuste

---

## [16.3.3.12] — 2026-02-11

### Corrigé
- Streamlit : `use_container_width=` → `width=`
- Documentation harmonisée

### Modifié
- `google-genai>=1.51.0` dans requirements.txt

---

## [16.3.3] — 2026-02-10

### Ajouté
- Configuration UI pour clés API
- Pièces jointes (PDF, DOCX, PPTX, XLSX, CSV, TXT, MD)
- Export PPTX initial (5 slides)
- Fallback automatique multi-providers
- Brief CoDIR redistribué aux rôles métier
- Diagnostics CSV/JSON exportables

### Modifié
- Migration vers `google-genai` (nouveau SDK Google)
- Stockage clés dans `secrets.json` (hors repo)

---

## [16.1.3] — 2026-02

### Ajouté
- `secrets.json` et `settings.json`
- Logging structuré
- Architecture Brief CoDIR (2 étapes)

---

## [16.0.0] — 2026-02-04

### Ajouté
- Version initiale open-source sur GitHub
- Multi-providers : OpenAI, Anthropic, Google, Mistral
- Mode CoDIR IA (4 directions) + Mode Libre
- Export DOCX + Markdown
- Scripts d'installation Windows et macOS

---

*CoDIR IA — Votre Comité de Direction augmenté par l'IA*
