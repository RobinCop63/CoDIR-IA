# =============================================================================
# CoDIR IA v16.5 — brief_ui.py
# Dual-mode brief: Terrain (5 champs) + Équipe (A→E)
# =============================================================================

# Hotfix B1.3.62.10.1 — import manquant du patch « UK Company Number » (.62.10) :
# re.sub() l.744+ (_assemble_equipe) plantait en NameError au premier rendu
# Équipe en mode EN avec identifiant 8 alphanumériques (terrain dossier anglophone coté 15/08).
import re

import streamlit as st

# Patch v16.5.69.1 patch session 7 — Banner ASCII versionnée dynamiquement
# (audit terrain dossier de conseil : la banner était hardcodée v16.5.67 et apparaissait
# dans les briefs envoyés aux agents → drift visible dans diagnostics_ia.csv).
try:
    from version import PRODUCT_VERSION as _APP_VERSION   # 9.4.65 — libellé produit affiché
except Exception:
    _APP_VERSION = "v17.0"  # fallback robuste si import en isolation


def _banner_line(label: str, width: int = 46) -> str:
    """
    Génère une ligne ASCII banner avec label centré et version dynamique.
    Largeur fixe pour aligner les bordures du cadre ╔═╗ / ╚═╝.

    La bordure top/bottom fait 48 chars (2 corners + 46 ═), donc l'intérieur
    doit faire 46 chars padded entre les 2 ║ pour matcher.
    """
    inner = f"  {label} — CoDIR IA {_APP_VERSION}"
    # Padding à droite pour atteindre la largeur cible (entre les caractères ║)
    padded = inner.ljust(width)
    return f"║{padded}║"

# ─────────────────────────────────────────────────────────────────────────────
# LABELS BILINGUES
# ─────────────────────────────────────────────────────────────────────────────
_L = {
    "fr": {
        "mode_title":        "Que souhaitez-vous préparer ?",
        "mode_sub":          "Un CoDIR efficace en quelques minutes, à partir de votre situation réelle",
        "terrain_title":     "Analyse",
        "terrain_personas":  "Dirigeant · Consultant · Manager de transition",
        "terrain_tagline":   "Un point précis. Allez à l'essentiel.",
        "terrain_tags":      ["Point précis", "5 min", "Prêt"],
        "terrain_cta":       "Analyser une situation →",
        "equipe_title":      "Ordre du jour",
        "equipe_personas":   "DAF · DG · Directeurs membres du CODIR",
        "equipe_tagline":    "Préparation structurée de l'ordre du jour.",
        "equipe_tags":       ["3 sections A→C", "10-15 min", "Enrichissement maximal"],
        "equipe_cta":        "Préparer un CoDIR complet →",
        "transfer_note":     "Analyse enrichissable à tout moment — les champs se transfèrent vers l'Ordre du jour",
        "change_mode":       "← Changer de mode",
        "enrich_btn":        "→ Structurer l'ordre du jour complet",
        "brief_ready":       "Prêt ✓",
        "fill_brief":        "Compléter avant de lancer",
        "prefill_banner":    "✓ Analyse importée — vérifiez et complétez",
        # Terrain fields
        "t_fr_label":        "Quel est le sujet de votre CODIR ?",
        "t_fr_sub":          "Décrivez librement votre situation",
        "t_fr_ph":           "Compléter librement — ex : « décider si on maintient la politique de stock malgré la baisse de rotation, ou si l'on dégrade temporairement le service pour protéger le cash avant le board du 15 avril »",
        "t_sit_label":       "Le contexte",
        "t_sit_sub":         "3 à 6 phrases — ce qui se passe, depuis quand, le déclencheur",
        "t_sit_ph":          "…",
        "t_q1_label":        "Question principale à trancher",
        "t_q1_ph":           "Formulez comme une phrase de comité…",
        "t_q1_type_label":   "Type",
        "t_hor_label":       "Horizon",
        "t_lang_label":      "Langue de sortie",
        "t_soc_label":       "Société analysée (optionnel)",
        "t_soc_ph":          "Raison sociale — ex : Acme SA",
        "t_siren_label":     "SIREN (optionnel)",
        "t_siren_ph":        "9 chiffres — identification sans ambiguïté pour Pappers",
        # v16.5.74 — Dropdown pays + numéro registre international
        "t_country_label":   "Pays du siège social",
        "t_country_help":    "Selon le pays, un identifiant national différent sera attendu",
        "t_intl_reg_label":  "Numéro d'enregistrement étranger (optionnel)",
        "t_intl_reg_help":   "Adapté au pays sélectionné — laissez vide si vous saisissez un SIREN ci-dessus",
        # Équipe fields
        "eq_fr_label":       "Fil rouge décisionnel",
        "eq_fr_sub":         "À l'issue de ce CODIR, le DG doit pouvoir…",
        "eq_fr_ph":          "ou compléter librement…",
        "eq_verb_label":     "Verbe pivot",
        "eq_msg_label":      "Message sensible à préparer (À qui expliquer la décision ?)",
        "eq_mode_label":     "Mode(s) de la séance",
        "eq_id_label":       "Identité entreprise",
        "eq_societe_ph":     "Nom légal ou d'usage",
        "eq_secteur_ph":     "Ex : industrie, SaaS B2B…",
        "eq_taille_ph":      "Ex : 45M€, 320 pers.",
        "eq_geo_ph":         "Marchés, pays, sites",
        "eq_acto_label":     "Actionnariat",
        "eq_field_societe":  "Société",
        "eq_field_secteur":  "Secteur / activité",
        "eq_field_taille":   "Taille (CA, effectif)",
        "eq_field_geo":      "Géographie",
        "eq_field_siren":    "SIREN",
        "echo_analyse":      "ANALYSE",
        "echo_not_provided": "(non renseigné)",
        "echo_decision_thread": "FIL ROUGE DÉCISIONNEL",
        "echo_context_up":   "CONTEXTE",
        "echo_main_q":       "QUESTION PRINCIPALE",
        "echo_output_lang":  "LANGUE DE SORTIE",
        "echo_company_up":   "SOCIÉTÉ",
        "echo_hq_country":   "PAYS DU SIÈGE",
        "echo_foreign_reg":  "NUMÉRO REGISTRE ÉTRANGER",
        "echo_horizon_def":  "30 jours",
        "echo_kpi_hr":       "RH",
        "echo_force_sc":     "FORCER SUPPLY CHAIN",
        "echo_user_override": "override wizard utilisateur",
        "echo_yes":          "oui",
        "echo_no":           "non",
        "eq_field_declencheur": "Événement déclencheur",
        "eq_field_q2":       "Q2 (optionnel)",
        "eq_field_deadline": "Deadline externe",
        "eq_field_kpis":     "KPIs disponibles",
        "echo_agenda":       "ORDRE DU JOUR",
        "echo_a":            "A · FIL ROUGE & MODE",
        "echo_filrouge":     "Fil rouge",
        "echo_msg":          "Messages sensibles",
        "echo_modes":        "Mode(s) de séance",
        "echo_b":            "B · CONTEXTE BUSINESS",
        "echo_societe":      "Société",
        "echo_secteur":      "Secteur",
        "echo_taille":       "Taille",
        "echo_geo":          "Géographie",
        "echo_acto":         "Actionnariat",
        "echo_ref":          "Référence",
        "echo_declencheur":  "Déclencheur",
        "echo_situation":    "Situation",
        "echo_c":            "C · CŒUR DU CODIR",
        "echo_horizon":      "Horizon",
        "echo_deadline":     "Deadline",
        "echo_risk":         "Risque de non-décision",
        "echo_d":            "D · ENRICHISSEMENT",
        "echo_focus":        "Focus directions",
        "echo_e":            "E · FINALISATION",
        "echo_decisions":    "Décisions actées",
        "echo_contraintes":  "Contraintes",
        "echo_langue":       "Langue",
        "echo_zone":         "Zone humaine",
        "eq_siren_ph":       "SIREN / Company reg.",
        "eq_sit_label":      "Situation du moment",
        "eq_sit_sub":        "Que se passe-t-il — depuis quand — qu'est-ce qui a changé — quel déclencheur",
        "eq_sit_ph":         "3 à 6 phrases libres…",
        "eq_ref_label":      "Référence de performance",
        "eq_decl_ph":        "Événement déclencheur — ce qui motive ce CODIR",
        "eq_q1_label":       "Questions & décisions attendues",
        "eq_q1_sub":         "Formuler comme une phrase de comité : Faut-il / Doit-on / Peut-on / Quel arbitrage…",
        "eq_q1_ph":          "Question principale de délibération",
        "eq_q2_ph":          "Question secondaire (optionnel)",
        "eq_hor_label":      "Horizon de la séance",
        "eq_dl_ph":          "Deadline externe — board, closing, appel d'offre…",
        "eq_echec_label":    "Ce qui ferait échouer la séance (optionnel)",
        "eq_echec_ph":       "Si le CODIR se termine sans décision, quelle conséquence concrète ?",
        "eq_focus_label":    "Focus par direction (optionnel)",
        "eq_kpi_com":        "KPIs Commercial",
        "eq_kpi_fin":        "KPIs Finance",
        "eq_kpi_sc":         "KPIs Supply Chain",
        "eq_kpi_rh":         "KPIs RH / Organisation",
        "eq_kpi_ph":         "Données disponibles…",
        "eq_decisions_label":"Décisions déjà actées (optionnel)",
        "eq_decisions_ph":   "Ex : acquisition en cours de closing, restructuration annoncée…",
        "eq_contraintes_label":"Contraintes externes (optionnel)",
        "eq_contraintes_ph": "Ex : accord collectif, engagement banquier…",
        "eq_lang_label":     "Langue de sortie",
        "eq_sc_label":       "Analyse Supply Chain",
        "eq_sc_help":        "Force l'activation ou la désactivation de l'agent Supply Chain, même si le pre-filter automatique aurait décidé autrement (utile pour holdings avec APE trompeur)",
        "eq_sc_auto":        "Automatique (pre-filter)",
        "eq_sc_force_yes":   "Forcer l'analyse",
        "eq_sc_force_no":    "Désactiver l'analyse",
        "eq_zh_label":       "CE QUE SEUL VOUS POUVEZ DIRE",
        "eq_zh_sub":         "Tensions, non-dits, contexte politique — aucun KPI ne peut le capturer",
        "eq_zh_ph":          '"Mon DAF et le DSC sont en conflit depuis 6 mois…"\n"Le DG ne sait pas encore que les chiffres Q1 vont être très mauvais."',
        "btn_next":          "Suivant →",
        "btn_prev":          "← Retour",
        "btn_launch":        "Préparer mon CoDIR ▶",
        "section_A":         "A · Contexte & Fil rouge",
        "section_B":         "B · Ordre du jour",
        "section_C":         "C · Enrichissement & Finalisation",
        "section_D":         "C · Enrichissement & Finalisation",
        "section_E":         "C · Enrichissement & Finalisation",
    },
    "en": {
        "mode_title":        "What would you like to prepare?",
        "mode_sub":          "An effective CODIR in a few minutes, based on your real situation",
        "terrain_title":     "Analysis",
        "terrain_personas":  "CEO · Consultant · Interim Manager",
        "terrain_tagline":   "One specific point. Get straight to it.",
        "terrain_tags":      ["Specific point", "5 min", "Ready"],
        "terrain_cta":       "Analyse a situation →",
        "equipe_title":      "Agenda",
        "equipe_personas":   "CFO · CEO · CODIR Directors",
        "equipe_tagline":    "Structured preparation of the meeting agenda.",
        "equipe_tags":       ["3 sections A→C", "10-15 min", "Maximum detail"],
        "equipe_cta":        "Prepare a full CODIR →",
        "transfer_note":     "Terrain brief can be enriched anytime — 5 fields transfer to Team Brief",
        "change_mode":       "← Change mode",
        "enrich_btn":        "→ Structure the full agenda",
        "brief_ready":       "Ready ✓",
        "fill_brief":        "Complete the brief before launching",
        "prefill_banner":    "✓ Terrain brief imported — review and complete",
        "t_fr_label":        "What is the decision?",
        "t_fr_sub":          "After this CODIR, you need to be able to…",
        "t_fr_ph":           "Complete freely…",
        "t_sit_label":       "The context",
        "t_sit_sub":         "3 to 6 sentences — what's happening, since when, the trigger",
        "t_sit_ph":          "…",
        "t_q1_label":        "The question to decide",
        "t_q1_ph":           "Phrase it like a committee agenda item…",
        "t_q1_type_label":   "Type",
        "t_hor_label":       "Time horizon",
        "t_lang_label":      "Output language",
        "t_soc_label":       "Company (optional)",
        "t_soc_ph":          "Legal name — e.g. Acme SA",
        "t_siren_label":     "SIREN (optional)",
        "t_siren_ph":        "9-digit French company ID — unambiguous Pappers lookup",
        # v16.5.74 — Country dropdown + international registration number
        "t_country_label":   "Country of head office",
        "t_country_help":    "A country-specific national ID will be expected",
        "t_intl_reg_label":  "Foreign registration number (optional)",
        "t_intl_reg_help":   "Adapted to the selected country — leave empty if you entered a SIREN above",
        "eq_fr_label":       "Decision thread",
        "eq_fr_sub":         "After this CODIR, the CEO must be able to…",
        "eq_fr_ph":          "or complete freely…",
        "eq_verb_label":     "Pivot verb",
        "eq_msg_label":      "Sensitive message to prepare (Who needs the decision explained?)",
        "eq_mode_label":     "Meeting mode(s)",
        "eq_id_label":       "Company identity",
        "eq_societe_ph":     "Legal or trade name",
        "eq_secteur_ph":     "E.g.: industry, B2B SaaS…",
        "eq_taille_ph":      "E.g.: €45M, 320 employees",
        "eq_geo_ph":         "Markets, countries, sites",
        "eq_acto_label":     "Ownership structure",
        "eq_field_societe":  "Company",
        "eq_field_secteur":  "Sector / activity",
        "eq_field_taille":   "Size (revenue, headcount)",
        "eq_field_geo":      "Geography",
        "eq_field_siren":    "Company number",
        "echo_analyse":      "ANALYSIS",
        "echo_not_provided": "(not provided)",
        "echo_decision_thread": "DECISION THREAD",
        "echo_context_up":   "CONTEXT",
        "echo_main_q":       "MAIN QUESTION",
        "echo_output_lang":  "OUTPUT LANGUAGE",
        "echo_company_up":   "COMPANY",
        "echo_hq_country":   "HQ COUNTRY",
        "echo_foreign_reg":  "FOREIGN REGISTRY NUMBER",
        "echo_horizon_def":  "30 days",
        "echo_kpi_hr":       "HR",
        "echo_force_sc":     "FORCE SUPPLY CHAIN",
        "echo_user_override": "user wizard override",
        "echo_yes":          "yes",
        "echo_no":           "no",
        "eq_field_declencheur": "Trigger event",
        "eq_field_q2":       "Q2 (optional)",
        "eq_field_deadline": "External deadline",
        "eq_field_kpis":     "Available KPIs",
        "echo_agenda":       "AGENDA",
        "echo_a":            "A · DECISION THREAD & MODE",
        "echo_filrouge":     "Decision thread",
        "echo_msg":          "Sensitive messages",
        "echo_modes":        "Session mode(s)",
        "echo_b":            "B · BUSINESS CONTEXT",
        "echo_societe":      "Company",
        "echo_secteur":      "Sector",
        "echo_taille":       "Size",
        "echo_geo":          "Geography",
        "echo_acto":         "Ownership",
        "echo_ref":          "Benchmark",
        "echo_declencheur":  "Trigger",
        "echo_situation":    "Situation",
        "echo_c":            "C · CORE OF THE CODIR",
        "echo_horizon":      "Horizon",
        "echo_deadline":     "Deadline",
        "echo_risk":         "Cost of no decision",
        "echo_d":            "D · ENRICHMENT",
        "echo_focus":        "Function focus",
        "echo_e":            "E · FINALISATION",
        "echo_decisions":    "Decisions made",
        "echo_contraintes":  "Constraints",
        "echo_langue":       "Language",
        "echo_zone":         "Human zone",
        "eq_siren_ph":       "SIREN / Company reg.",
        "eq_sit_label":      "Current situation",
        "eq_sit_sub":        "What's happening — since when — what changed — what triggered this",
        "eq_sit_ph":         "3 to 6 free sentences…",
        "eq_ref_label":      "Performance reference",
        "eq_decl_ph":        "Triggering event — what makes this CODIR necessary today",
        "eq_q1_label":       "Questions & expected decisions",
        "eq_q1_sub":         "Phrase as committee agenda: Should we / Must we / Can we / What tradeoff…",
        "eq_q1_ph":          "Main deliberation topic",
        "eq_q2_ph":          "Secondary question (optional)",
        "eq_hor_label":      "Meeting horizon",
        "eq_dl_ph":          "External deadline — board, closing, tender…",
        "eq_echec_label":    "What would make this session fail (optional)",
        "eq_echec_ph":       "If CODIR ends without a decision, what's the concrete consequence?",
        "eq_focus_label":    "Focus by department (optional)",
        "eq_kpi_com":        "Commercial KPIs",
        "eq_kpi_fin":        "Finance KPIs",
        "eq_kpi_sc":         "Supply Chain KPIs",
        "eq_kpi_rh":         "HR / Organisation KPIs",
        "eq_kpi_ph":         "Available data…",
        "eq_decisions_label":"Already decided (optional)",
        "eq_decisions_ph":   "E.g.: acquisition in progress, announced restructuring…",
        "eq_contraintes_label":"External constraints (optional)",
        "eq_contraintes_ph": "E.g.: collective agreement, bank covenant…",
        "eq_lang_label":     "Output language",
        "eq_sc_label":       "Supply Chain analysis",
        "eq_sc_help":        "Force activation or deactivation of the Supply Chain agent, overriding the automatic pre-filter (useful for holdings with misleading APE codes)",
        "eq_sc_auto":        "Automatic (pre-filter)",
        "eq_sc_force_yes":   "Force analysis",
        "eq_sc_force_no":    "Disable analysis",
        "eq_zh_label":       "WHAT ONLY YOU CAN SAY",
        "eq_zh_sub":         "Politics, tensions, unspoken history — no KPI can capture this",
        "eq_zh_ph":          '"My CFO and CSO have been in conflict for 6 months…"\n"The CEO doesn\'t know yet that Q1 numbers will be very bad."',
        "btn_next":          "Next →",
        "btn_prev":          "← Back",
        "btn_launch":        "Prepare my CODIR ▶",
        "section_A":         "A · Context & Thread",
        "section_B":         "B · Agenda",
        "section_C":         "C · Enrichment & Finalisation",
        "section_D":         "C · Enrichment & Finalisation",
        "section_E":         "C · Enrichment & Finalisation",
    }
}

_QTYPE_LOC = {"Décision": "Decision", "Analyse": "Analysis",
              "Validation": "Validation", "Alerte": "Alert"}


def _loc_qtype(val: str, lang: str) -> str:
    """Localise un type de question (défaut FR) vers la langue du run."""
    if (lang or "fr").lower() == "en":
        return _QTYPE_LOC.get(str(val), str(val))
    return str(val)


def _loc_lang_value(stored: str, lang: str) -> str:
    """B.1.3.1 — délégué à utils/language_labels.loc_lang_value (module PUR,
    hermétique : verify/pytest ne doivent pas tirer streamlit pour tester un
    libellé). Contrat B.1.3 inchangé — voir la docstring du module pur."""
    from utils.language_labels import loc_lang_value
    return loc_lang_value(stored, lang)


def _l(key: str, lang: str) -> str:
    d = _L.get(lang) or _L["fr"]
    return d.get(key) or _L["fr"].get(key, key)

# ─────────────────────────────────────────────────────────────────────────────
# CSS — Design system CoDIR IA
# ─────────────────────────────────────────────────────────────────────────────
_CSS = """
<style>
/* ── Palette ── */
:root {
  --cbui-navy: #1E1B4B;
  --cbui-navyL: #252248;
  --cbui-purple: #6D28D9;
  --cbui-purpleM: #8B5CF6;
  --cbui-purpleL: #EDE9FE;
  --cbui-purpleD: #5B21B6;
  --cbui-blue: #1D4ED8;
  --cbui-blueL: #DBEAFE;
  --cbui-blueB: #93C5FD;
  --cbui-teal: #0F766E;
  --cbui-tealL: #CCFBF1;
  --cbui-terrain: #B45309;
  --cbui-terrainL: #FEF3C7;
}

/* ── Mode selection cards ── */
.cbui-mode-card {
  background: #252248;
  border-radius: 12px;
  padding: 24px 20px 18px;
  margin-bottom: 6px;
}
.cbui-mode-card.terrain { border-top: 3px solid #B45309; }
.cbui-mode-card.equipe  { border-top: 3px solid #1D4ED8; }
.cbui-badge {
  width: 44px; height: 44px; border-radius: 9px;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 18px; font-weight: 700; color: white; margin-bottom: 12px;
}
.terrain .cbui-badge { background: #B45309; }
.equipe  .cbui-badge { background: #1D4ED8; }
.cbui-card-title { font-size: 17px; font-weight: 600; color: white; margin-bottom: 6px; }
.cbui-card-personas { font-size: 12px; font-weight: 500; margin-bottom: 4px; }
.terrain .cbui-card-personas { color: #FCD34D; }
.equipe  .cbui-card-personas { color: #93C5FD; }
.cbui-card-tagline { font-size: 12px; color: #9CA3AF; font-style: italic; margin-bottom: 14px; }
.cbui-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.cbui-tag {
  border-radius: 100px; padding: 3px 11px;
  font-size: 10px; font-weight: 500;
}
.terrain .cbui-tag { background: #422006; border: 0.5px solid #78350F; color: #FCD34D; }
.equipe  .cbui-tag { background: #1E3A5F; border: 0.5px solid #93C5FD; color: #93C5FD; }
.cbui-transfer-note {
  background: #1A1848; border: 0.5px solid #2D2B6B;
  border-radius: 8px; padding: 10px 14px;
  font-size: 11px; color: #534AB7; margin-top: 12px; text-align: center;
}

/* ── Section bars ── */
.cbui-section-bar {
  border-radius: 9px; padding: 12px 16px; margin-bottom: 14px;
  display: flex; align-items: center; gap: 12px;
}
.cbui-section-bar.terrain {
  background: #FEF3C7; border-left: 4px solid #B45309;
}
.cbui-section-bar.equipe-A { background: #EDE9FE; border-left: 4px solid #6D28D9; }
.cbui-section-bar.equipe-B { background: #DBEAFE; border-left: 4px solid #1D4ED8; }
.cbui-section-bar.equipe-C { background: #E0E7FF; border-left: 4px solid #4338CA; }
.cbui-section-bar.equipe-D { background: #CCFBF1; border-left: 4px solid #0F766E; }
.cbui-section-bar.equipe-E { background: #EDE9FE; border-left: 4px solid #6D28D9; }
.cbui-bar-letter {
  width: 28px; height: 28px; border-radius: 6px;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700; color: white; flex-shrink: 0;
}
.terrain   .cbui-bar-letter { background: #B45309; }
.equipe-A  .cbui-bar-letter { background: #6D28D9; }
.equipe-B  .cbui-bar-letter { background: #1D4ED8; }
.equipe-C  .cbui-bar-letter { background: #4338CA; }
.equipe-D  .cbui-bar-letter { background: #0F766E; }
.equipe-E  .cbui-bar-letter { background: #6D28D9; }
.cbui-bar-text { flex: 1; }
.cbui-bar-title { font-size: 13px; font-weight: 600; }
.terrain   .cbui-bar-title { color: #92400E; }
.equipe-A  .cbui-bar-title { color: #5B21B6; }
.equipe-B  .cbui-bar-title { color: #1D4ED8; }
.equipe-C  .cbui-bar-title { color: #3730A3; }
.equipe-D  .cbui-bar-title { color: #0F766E; }
.equipe-E  .cbui-bar-title { color: #5B21B6; }
.cbui-bar-sub { font-size: 11px; color: #6B7280; font-style: italic; }

/* ── Step indicator ── */
.cbui-steps {
  display: flex; gap: 4px; margin-bottom: 16px;
}
.cbui-step {
  flex: 1; height: 4px; border-radius: 2px;
  background: #E5E7EB; transition: background .25s;
}
.cbui-step.done   { background: #16A34A; }
.cbui-step.active { background: #475569; }

/* ── Prefill banner ── */
.cbui-prefill-banner {
  background: #F0FDF4; border: 0.5px solid #16A34A;
  border-radius: 8px; padding: 8px 14px;
  font-size: 11px; color: #15803D; margin-bottom: 12px;
}

/* ── Zone humaine ── */
.cbui-zh-header {
  background: #1E1B4B; border-radius: 10px;
  padding: 14px 16px 8px; margin-bottom: 6px;
}
.cbui-zh-title { color: white; font-size: 14px; font-weight: 600; margin-bottom: 3px; }
.cbui-zh-sub   { color: #6B7280; font-size: 11px; font-style: italic; }

/* ── Button overrides ── */
div[data-testid="stButton"] > button[kind="secondary"] {
  border-radius: 8px !important;
}

/* ── Hauteur — réduire le padding Streamlit et adapter verticalement ── */

/* Padding Streamlit réduit au minimum */
.block-container {
  padding-top: 1.5rem !important;
  padding-bottom: 0.5rem !important;
  max-width: 100% !important;
}

/* Espacement vertical entre éléments réduit */
[data-testid="stVerticalBlock"] > div {
  gap: 0.3rem !important;
}

/* Retirer l'espace superflu autour des dividers */
[data-testid="stDivider"] {
  margin-top: 0.4rem !important;
  margin-bottom: 0.4rem !important;
}

/* Titre de l'app Streamlit — réduire l'espace qu'il consomme */
h1 {
  font-size: 1.4rem !important;
  margin-bottom: 0 !important;
  padding-bottom: 0 !important;
}

/* Caption sous le titre */
p[data-testid="stCaptionContainer"] {
  margin-top: 0 !important;
  margin-bottom: 0.25rem !important;
}

/* Compact sur écrans <= 768px hauteur */
@media screen and (max-height: 768px) {
  .block-container { padding-top: 0.75rem !important; }
  .cbui-section-bar { padding: 7px 12px !important; margin-bottom: 8px !important; }
  .cbui-steps { margin-bottom: 6px !important; }
  .cbui-bar-sub { display: none !important; }
  [data-testid="stVerticalBlock"] > div { gap: 0.2rem !important; }
}

/* Très compact <= 600px hauteur */
@media screen and (max-height: 600px) {
  .block-container { padding-top: 0.25rem !important; }
  .cbui-section-bar { padding: 5px 10px !important; margin-bottom: 4px !important; }
  .cbui-bar-title { font-size: 11px !important; }
  .cbui-steps { margin-bottom: 4px !important; }
}

/* ── Responsive — toutes tailles d'écran ── */

/* Pills et radio : toujours en retour à la ligne */
.pills, .dg-pills {
  flex-wrap: wrap !important;
}
div[data-testid="stRadio"] > div[role="radiogroup"],
div[data-testid="stRadio"] > div > div {
  flex-wrap: wrap !important;
  gap: 4px !important;
}
div[data-testid="stRadio"] > div > div > label {
  white-space: nowrap;
}

/* Colonnes Streamlit : empilées sous 900px */
@media screen and (max-width: 900px) {
  [data-testid="stHorizontalBlock"] {
    flex-wrap: wrap !important;
  }
  [data-testid="stHorizontalBlock"] > [data-testid="column"] {
    min-width: min(100%, 280px) !important;
    flex: 1 1 280px !important;
  }
}

/* HTML grids internes (g2, g3, hl-2) : empilés sous 700px */
@media screen and (max-width: 700px) {
  .g2  { grid-template-columns: 1fr !important; }
  .g3  { grid-template-columns: 1fr !important; }
  .hl-2 { grid-template-columns: 1fr !important; }
}

/* Mode selection cards : empilées sous 600px */
@media screen and (max-width: 600px) {
  .cbui-mode-card { padding: 16px 14px !important; }
}

/* Step bar : toujours visible */
.cbui-steps {
  flex-wrap: nowrap;
  overflow: hidden;
}

/* Section bars : texte réduit sur petit écran */
@media screen and (max-width: 600px) {
  .cbui-bar-title { font-size: 12px !important; }
  .cbui-bar-sub   { display: none; }
}

/* Inputs et textareas : toujours 100% de leur conteneur */
.f, .t-field, .q-inp, .dg-q-inp {
  max-width: 100% !important;
  box-sizing: border-box !important;
}

/* Éviter le débordement horizontal global */
section[data-testid="stSidebar"] ~ div {
  overflow-x: hidden;
}
</style>
"""

# ─────────────────────────────────────────────────────────────────────────────
# STATE INIT
# ─────────────────────────────────────────────────────────────────────────────
_TERRAIN_DEFAULTS = {
    "bui_t_verb":    "",
    "bui_t_fr":      "",
    "bui_t_q1":      "",
    "bui_t_horizon": "30 jours",
    "bui_t_langue":  "Français",
    "bui_t_soc":     "",
    "bui_t_siren":   "",
    # v16.5.74 — Item #6
    "bui_t_country":  "🇫🇷 France",
    "bui_t_intl_reg": "",
}
_EQUIPE_DEFAULTS = {
    "bui_e_verb": "",
    "bui_e_fr": "",
    "bui_e_msg": [],
    "bui_e_modes": [],
    "bui_e_societe": "",
    "bui_e_secteur": "",
    "bui_e_taille": "",
    "bui_e_geo": "",
    "bui_e_acto": "PE / Fonds",
    "bui_e_siren": "",
    "bui_e_sit": "",
    "bui_e_ref": "vs Budget",
    "bui_e_declencheur": "",
    "bui_e_q1": "",
    "bui_e_q1_type": "Décision",
    "bui_e_q2": "",
    "bui_e_q2_type": "Analyse",
    "bui_e_horizon": "30 jours",
    "bui_e_deadline": "",
    "bui_e_echec": "",
    "bui_e_focus": [],
    "bui_e_kpi_com": "",
    "bui_e_kpi_fin": "",
    "bui_e_kpi_sc": "",
    "bui_e_kpi_rh": "",
    "bui_e_decisions": "",
    "bui_e_contraintes": "",
    "bui_e_langue": "Français",
    "bui_e_sc_override": "auto",  # v16.5.76 item 6 — override supply chain : "auto" / "yes" / "no"
    "bui_e_zh": "",
    "bui_eq_step": 0,
    "bui_prefilled": False,
}

def _init_state():
    if "bui_mode" not in st.session_state:
        st.session_state["bui_mode"] = None
    for k, v in {**_TERRAIN_DEFAULTS, **_EQUIPE_DEFAULTS}.items():
        if k not in st.session_state:
            st.session_state[k] = v

def reset_brief_state():
    """Call this when user clicks 'Nouvelle session'."""
    st.session_state["bui_mode"] = None
    for k, v in {**_TERRAIN_DEFAULTS, **_EQUIPE_DEFAULTS}.items():
        st.session_state[k] = v

# ─────────────────────────────────────────────────────────────────────────────
# ASSEMBLY
# ─────────────────────────────────────────────────────────────────────────────

def _status_preview50(text: str, lang: str = "fr", dossier_id: str = "") -> str:
    """v62.13.9.4.50 — APERÇU des statuts d'actions et de la décision du conseil que CoDIR IA a lus dans le brief, affiché
    avant le lancement (recette du 02/10/2026 : un bloc collé à la souris avait perdu ses retours à la ligne et sa fin ;
    l'utilisateur doit voir ce qui sera appliqué). Rien n'est modifié dans le texte."""
    try:
        from patches.codir_register_history import parse_brief_statuses, parse_board_decision
    except Exception:
        return ""
    s = str(text or "")
    decl = parse_brief_statuses(s)
    board = parse_board_decision(s)
    en = str(lang).lower().startswith("en")
    words = {"DONE": ("completed", "réalisée"), "POSTPONED": ("postponed", "reportée"), "DROPPED": ("dropped", "abandonnée")}
    # 9.4.57 — contre-recette ChatGPT du 10/10 (P56-01) : l'aperçu rapproche chaque ligne du registre du dossier AVANT le
    # lancement ; une ligne qui ne vise aucune action (ou une action déjà close) se voit tout de suite
    qual = {}
    try:
        if decl:
            if not dossier_id:
                import streamlit as _st57
                _lbl57 = str(_st57.session_state.get("codir_dossier_label") or "").strip()
                if _lbl57:
                    from patches.codir_register_history import compute_dossier_id as _cdi57
                    dossier_id = _cdi57(dossier_label=_lbl57)
            if dossier_id:
                from patches.codir_register_history import load_events as _le57, match_brief_statuses52 as _mb57
                if _le57(dossier_id):
                    for m in _mb57(dossier_id, s):
                        qual[m["action"]] = m
    except Exception:
        qual = {}
    _dossier59 = ""
    try:
        import streamlit as _st59
        _dossier59 = str(_st59.session_state.get("codir_dossier_label") or "").strip()
    except Exception:
        _dossier59 = ""
    tags = {"certaine": ("✓ found in the register", "✓ retrouvée au registre"),
            "déjà appliquée": ("already applied at a previous session", "déjà appliquée lors d'une séance précédente"),
            "ambiguë": ("⚠ ambiguous: several actions fit", "⚠ ambiguë : plusieurs actions possibles"),
            "non retrouvée": ("⚠ not found in the register", "⚠ non retrouvée au registre")}
    items = []
    for d in decl:
        w = words.get(d["status"], (d["status"], d["status"]))[0 if en else 1]
        q = qual.get(d["action"], {}).get("quality")
        tag = f" [{tags[q][0 if en else 1]}]" if q in tags else ""
        _prep57 = (("on" if en else "le") if d["status"] == "DONE" else ("to" if en else "au"))
        items.append(f"{d['action'][:70]} → {w}" + (f" ({_prep57} {d['date']})" if d.get("date") else "") + tag)
    if board:
        items.append((f"board: option {board} selected" if en else f"conseil : option {board} retenue"))
    import re as _re
    if not items and _re.search(r"(?i)r[ée]alis[ée]e|report[ée]e|abandonn[ée]e|completed|postponed|dropped", s):
        return ("⚠ Statuses mentioned but none could be read — put one action per line: « — action — completed / postponed to dd/mm/yyyy / dropped »."
                if en else "⚠ Des statuts sont mentionnés mais aucun n'a pu être lu — une action par ligne : « — action — réalisée / reportée au jj/mm/aaaa / abandonnée ».")
    if not items:
        return ""
    head = "Statuses read by CoDIR IA (applied at launch): " if en else "Statuts lus par CoDIR IA (appliqués au lancement) : "
    try:   # 9.4.64 — statut non reconnu signalé AVANT le lancement (« décidée », « en cours »)
        from patches.codir_register_history import unrecognized_statuses64 as _us64
        _unk64 = _us64(s)
    except Exception:
        _unk64 = []
    if _dossier59 and decl:
        # 9.4.59 — le dossier visé est nommé : un mauvais dossier se voit avant le lancement
        head = (f"Statuses read by CoDIR IA, file « {_dossier59} » (applied at launch): " if en
                else f"Statuts lus par CoDIR IA, dossier « {_dossier59} » (appliqués au lancement) : ")
    _txt64 = head + " ; ".join(items)
    if _unk64:
        _txt64 += (" — ⚠ NOT recognised, nothing applied: " if en else " — ⚠ statut NON reconnu, rien n'est appliqué : ") + " ; ".join(
            f"« {x['action'][:60]} » → « {x['word']} »" for x in _unk64) + (
            " (use completed, postponed to dd/mm/yyyy, dropped or kept)" if en else
            " (utiliser réalisée, reportée au jj/mm/aaaa, abandonnée ou maintenue)")
    return _txt64


def _control_and_business(raw_text: str, tci, expected_mode: str):
    """Correctif TCR-v10 (P0-3) — l'assemblage part de l'ENTRÉE COURANTE.

    Quand app.py transmet la photographie du rerun, ses `control_lines` et
    son `business_text` sont utilisés TELS QUELS : le brief final n'est
    plus reconstruit par une seconde séparation du texte, donc plus jamais
    reparsé. Le repli — mode différent, appel bibliothèque, test hérité,
    ou texte qui aurait bougé pendant le rendu — reste l'ancien chemin :
    une divergence ne peut pas faire assembler un brief sur une
    photographie périmée.
    """
    if (tci is not None
            and getattr(tci, "ui_mode", None) == expected_mode
            and getattr(tci, "raw_main_text", None) == raw_text):
        return list(tci.control_lines), tci.business_text
    try:
        from patches.mission_governance import (
            split_temporal_control_prefix as _stcp)
        return _stcp(raw_text)
    except Exception:
        return [], raw_text

def _assemble_terrain(lang: str = "fr", tci=None) -> str:
    s = st.session_state
    LL = lambda k: _l(k, lang)
    NP = _l("echo_not_provided", lang)
    verb = s.get("bui_t_verb", "")
    # Correctif TCR-v9 — .strip() écrasait l'indentation de la première
    # ligne (bloc de code) AVANT toute classification : on ne retire
    # que les lignes vides et les blancs de fin.
    fr = (s.get("bui_t_fr", "") or "").lstrip("\n\r").rstrip()
    # Correctif TCR-v8 (verdict v7, P0-1/P0-2) — l'ENTRÉE DE CONTRÔLE est
    # séparée du CONTENU MÉTIER *avant* toute transformation :
    #   1. lire les lignes de contrôle en TÊTE du champ principal brut ;
    #   2. les retirer du contenu métier ;
    #   3. appliquer le verbe pivot au contenu métier SEUL ;
    #   4. régénérer le bloc canonique avant toute décoration.
    # Le champ « situation » (et tout autre champ narratif) n'est JAMAIS
    # une source de contrôle : un rapport ou un email copié ne peut plus
    # être promu en autorité temporelle.
    _ctrl_lines, fr = _control_and_business(fr, tci, "terrain")
    # Correctif TCR-v9 (verdict v8, P0-1) — le verbe pivot est posé sur
    # SA PROPRE LIGNE : collé au contenu métier, il déplaçait la première
    # clause et détruisait une inférence legacy (« As of 15 February
    # 2023, … » devenait invisible → run live). Le pivot reste appliqué
    # au business_text seul, sans altérer ses frontières de clause.
    fr_line = ("\n".join(x for x in (verb, fr) if x).strip()
               if (verb or fr) else "")
    lines = [
        *_ctrl_lines,
        *([""] if _ctrl_lines else []),
        "╔══════════════════════════════════════════════╗",
        _banner_line(LL("echo_analyse")),
        "╚══════════════════════════════════════════════╝",
        "",
        f"▌ {LL('echo_decision_thread')}",
        fr_line or NP,
        "",
        f"▌ {LL('echo_context_up')}",
        s.get("bui_t_sit", "").strip() or NP,
        "",
        f"▌ {LL('echo_main_q')}  [{_loc_qtype(s.get('bui_t_q1_type','Décision'), lang)}]",
        s.get("bui_t_q1", "").strip() or NP,
        "",
        f"▌ {LL('echo_horizon')} : {s.get('bui_t_horizon') or LL('echo_horizon_def')}",
        f"▌ {LL('echo_output_lang')} : {_loc_lang_value(s.get('bui_t_langue'), lang)}",
    ]
    # Société et SIREN optionnels (pour enrichissement Pappers)
    if s.get("bui_t_soc", "").strip():
        lines.append(f"▌ {LL('echo_company_up')} : {s['bui_t_soc'].strip()}")
    if s.get("bui_t_siren", "").strip():
        lines.append(f"▌ SIREN : {s['bui_t_siren'].strip()}")
    # v16.5.74 — Pays + numéro registre international si renseignés
    _country_v74 = s.get("bui_t_country", "").strip()
    _intl_reg_v74 = s.get("bui_t_intl_reg", "").strip()
    if _country_v74 and _country_v74 != "🇫🇷 France":
        lines.append(f"▌ {LL('echo_hq_country')} : {_country_v74}")
    if _intl_reg_v74:
        lines.append(f"▌ {LL('echo_foreign_reg')} : {_intl_reg_v74}")
    return "\n".join(lines)

_SECTION62 = re.compile(r"(?im)^\s*▌?\s*(?:[B-E]\s*·\s*(?:CONTEXTE\s+BUSINESS|C[ŒO]E?UR\s+DU\s+CODIR|ENRICHISSEMENT|FINALISATION)|"
                        r"[B-E]\s*·\s*(?:BUSINESS\s+CONTEXT|CORE\s+OF\s+THE\s+CODIR|ENRICHMENT|FINALISATION|FINALIZATION))\b")


def is_complete_brief62(text: str) -> bool:
    """9.4.62 — vrai si le texte collé est déjà un brief complet (au moins deux sections B à E de l'ordre du jour)."""
    return len({m.group(0).strip().lstrip("▌").strip()[:1] for m in _SECTION62.finditer(str(text or ""))}) >= 2


def _assemble_equipe(lang: str = "fr", tci=None) -> str:
    s = st.session_state
    LL = lambda k: _l(k, lang)  # M.5.10 — labels brief-echo localisés
    verb = s.get("bui_e_verb", "")
    fr = (s.get("bui_e_fr", "") or "").lstrip("\n\r").rstrip()
    # v62.10 — international identifier semantics.  The legacy team-mode field
    # is still named ``bui_e_siren`` for compatibility, but an 8-character
    # Companies House number must be rendered as a UK Company Number.  When the
    # user kept the copy/paste placeholder in the narrative brief, replace it
    # deterministically with the actual identifier rather than exposing French
    # setup text in an English report.
    _e_identifier = str(s.get("bui_e_siren") or "").strip()
    _e_is_uk_number = bool(
        str(lang or "fr").lower().startswith("en") and _e_identifier and
        ("companies house" in fr.lower() or (len(_e_identifier) == 8 and _e_identifier.isalnum()))
    )
    if _e_is_uk_number:
        fr = re.sub(
            r"(?i)(Companies\s+House\s+number\s*:\s*)\[[^\]]*\]",
            lambda m: m.group(1) + _e_identifier,
            fr,
        )
    # Correctif TCR-v8 — séparation contrôle / métier AVANT le verbe
    # pivot (sélectionné PAR DÉFAUT en mode Équipe : il ne doit jamais
    # masquer un label signé). Aucun champ narratif n'est source.
    _ctrl_lines, fr = _control_and_business(fr, tci, "equipe")
    # 9.4.62 — demande du dirigeant (13/10/2026) : un brief COMPLET collé dans le champ (préparé ailleurs, avec ses propres
    # sections B à E) était entouré du gabarit de l'application et de ses valeurs par défaut (deux horizons, deux « Messages
    # sensibles ») et déclenchait une alerte. Il est désormais utilisé TEL QUEL, précédé des seules lignes de contrôle.
    if is_complete_brief62(fr):
        _own = re.sub(r"^\s*-{3,}\s*\n", "", fr).strip("\n")
        # 9.4.63 — recette du 14/10 : le brief rendu doit être CANONIQUE (sans blanc en tête ni en fin). Le moteur le
        # « strip » avant de vérifier qu'il est exactement celui qui a été lié au contexte temporel ; un retour à la ligne
        # final faisait échouer cette vérification (« temporal_context mismatch (brief hash) ») et arrêtait le run.
        return "\n".join([*_ctrl_lines, *([""] if _ctrl_lines else []), _own]).strip()
    # Correctif TCR-v9 — idem côté Équipe (pivot sélectionné par défaut).
    fr_line = ("\n".join(x for x in (verb, fr) if x).strip()
               if (verb or fr) else _l("echo_not_provided", lang))
    msgs = s.get("bui_e_msg", [])
    modes = s.get("bui_e_modes", [])
    focus = s.get("bui_e_focus", [])
    def _kv(label, val):
        v = str(val).strip() if val else ""
        return f"  {label} : {v}" if v else ""
    def _block(title, *items):
        lines = [f"\n▌ {title}"]
        for item in items:
            if item: lines.append(item)
        return "\n".join(lines)
    parts = [
        *_ctrl_lines,
        *([""] if _ctrl_lines else []),
        "╔══════════════════════════════════════════════╗",
        _banner_line(LL("echo_agenda")),
        "╚══════════════════════════════════════════════╝",
    ]
    # A
    parts.append(_block(LL("echo_a"),
        # Correctif TCR-v9 — le fil rouge est rendu « libellé : » puis
        # VALEUR SUR SA PROPRE LIGNE : en ligne `Clé : valeur`, le
        # contenu métier perdait sa frontière de clause et une
        # inférence temporelle naturelle y devenait invisible (même
        # famille que le verbe pivot collé).
        f"  {LL('echo_filrouge')} :",
        *(f"  {_frl}" for _frl in fr_line.split("\n")),
        f"  {LL('echo_msg')} : {', '.join(msgs)}" if msgs else "",
        f"  {LL('echo_modes')} : {', '.join(modes)}" if modes else "",
    ))
    # B
    parts.append(_block(LL("echo_b"),
        _kv(LL("echo_societe"), s.get("bui_e_societe")),
        _kv(LL("echo_secteur"), s.get("bui_e_secteur")),
        _kv(LL("echo_taille"), s.get("bui_e_taille")),
        _kv(LL("echo_geo"), s.get("bui_e_geo")),
        _kv(LL("echo_acto"), s.get("bui_e_acto")),
        _kv(("UK Company Number" if _e_is_uk_number else
             (LL("echo_siren") if _l("echo_siren",lang)!="echo_siren" else "SIREN")),
            s.get("bui_e_siren")),
        f"\n  {LL('echo_situation')} : {s.get('bui_e_sit','').strip()}" if s.get("bui_e_sit","").strip() else "",
        _kv(LL("echo_ref"), s.get("bui_e_ref")),
        _kv(LL("echo_declencheur"), s.get("bui_e_declencheur")),
    ))
    # C
    q1 = s.get("bui_e_q1", "").strip()
    q2 = s.get("bui_e_q2", "").strip()
    echec = s.get("bui_e_echec", "").strip()
    parts.append(_block(LL("echo_c"),
        f"  Q1 [{_loc_qtype(s.get('bui_e_q1_type','Décision'), lang)}] : {q1}" if q1 else "",
        f"  Q2 [{_loc_qtype(s.get('bui_e_q2_type','Analyse'), lang)}] : {q2}" if q2 else "",
        f"  {LL('echo_horizon')} : {s.get('bui_e_horizon') or LL('echo_horizon_def')}",
        _kv(LL("echo_deadline"), s.get("bui_e_deadline")),
        f"  {LL('echo_risk')} : {echec}" if echec else "",
    ))
    # D
    kpis = [_kv(k, s.get(f"bui_e_kpi_{k2}")) for k, k2 in [("Commercial","com"),("Finance","fin"),("Supply Chain","sc"),(LL("echo_kpi_hr"),"rh")]]
    parts.append(_block(LL("echo_d"),
        f"  {LL('echo_focus')} : {', '.join(focus)}" if focus else "",
        "\n".join(k for k in kpis if k) or "",
    ))
    # E
    zh = s.get("bui_e_zh", "").strip()
    # v16.5.76 item 6 — Override Supply Chain : injecte la balise dans le brief
    # quand l'utilisateur a explicitement choisi "yes" ou "no" dans le wizard.
    # Le moteur (codir_engine._parse_supply_chain_override) la détecte et
    # court-circuite le pre-filter automatique.
    sc_override = s.get("bui_e_sc_override", "auto")
    sc_line = ""
    if sc_override == "yes":
        sc_line = f"  {LL('echo_force_sc')} : {LL('echo_yes')} ({LL('echo_user_override')})"
    elif sc_override == "no":
        sc_line = f"  {LL('echo_force_sc')} : {LL('echo_no')} ({LL('echo_user_override')})"
    parts.append(_block(LL("echo_e"),
        _kv(LL("echo_decisions"), s.get("bui_e_decisions")),
        _kv(LL("echo_contraintes"), s.get("bui_e_contraintes")),
        f"  {LL('echo_langue')} : {_loc_lang_value(s.get('bui_e_langue'), lang)}",
        sc_line,
        f"\n  {LL('echo_zone')} :\n{zh}" if zh else "",
    ))
    return "\n".join(parts)

# ─────────────────────────────────────────────────────────────────────────────
# MODE SELECTION
# ─────────────────────────────────────────────────────────────────────────────
def _render_mode_selection(lang: str):
    st.markdown(_CSS, unsafe_allow_html=True)

    L = lambda k: _l(k, lang)
    st.markdown(f"### {L('mode_title')}")
    st.caption(L("mode_sub"))
    st.write("")

    col1, col2 = st.columns(2, gap="large")

    with col1:
        tags_html = "".join(f'<span class="cbui-tag">{t}</span>' for t in L("terrain_tags"))
        st.markdown(f"""
        <div class="cbui-mode-card terrain">
          <div class="cbui-badge">A</div>
          <div class="cbui-card-title">{L('terrain_title')}</div>
          <div class="cbui-card-personas">{L('terrain_personas')}</div>
          <div class="cbui-card-tagline">{L('terrain_tagline')}</div>
          <div class="cbui-tags">{tags_html}</div>
        </div>
        """, unsafe_allow_html=True)
        if st.button(L("terrain_cta"), key="bui_btn_terrain", use_container_width=True, type="primary"):
            st.session_state["bui_mode"] = "terrain"
            st.rerun()

    with col2:
        tags_html = "".join(f'<span class="cbui-tag">{t}</span>' for t in L("equipe_tags"))
        st.markdown(f"""
        <div class="cbui-mode-card equipe">
          <div class="cbui-badge">E</div>
          <div class="cbui-card-title">{L('equipe_title')}</div>
          <div class="cbui-card-personas">{L('equipe_personas')}</div>
          <div class="cbui-card-tagline">{L('equipe_tagline')}</div>
          <div class="cbui-tags">{tags_html}</div>
        </div>
        """, unsafe_allow_html=True)
        if st.button(L("equipe_cta"), key="bui_btn_equipe", use_container_width=True):
            st.session_state["bui_mode"] = "equipe"
            st.rerun()

    st.markdown(f'<div class="cbui-transfer-note">💡 {L("transfer_note")}</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# BRIEF TERRAIN
# ─────────────────────────────────────────────────────────────────────────────
_VERBS_FR = ["Décider si…", "Valider que…", "Arbitrer entre…", "Comprendre pourquoi…", "Préparer le message…", "Sécuriser le plan…"]
_VERBS_EN = ["Decide whether…", "Validate that…", "Choose between…", "Understand why…", "Prepare the message…", "Secure the plan…"]
_Q_TYPES_FR = ["Décision", "Analyse", "Validation", "Alerte"]
_Q_TYPES_EN = ["Decision", "Analysis", "Validation", "Alert"]
_HOR_FR = ["Semaine", "30 jours", "1 – 3 mois", "3 – 12 mois", "+ 1 an"]
_HOR_EN = ["Week", "30 days", "1 – 3 months", "3 – 12 months", "+ 1 year"]
_LANG_OPTS = ["Français", "English", "Bilingue FR / EN"]

def _render_terrain(lang: str, temporal_control_input=None) -> str:
    st.markdown(_CSS, unsafe_allow_html=True)
    L = lambda k: _l(k, lang)
    s = st.session_state
    verbs = _VERBS_FR if lang == "fr" else _VERBS_EN
    q_types = _Q_TYPES_FR if lang == "fr" else _Q_TYPES_EN
    hors = _HOR_FR if lang == "fr" else _HOR_EN

    # Section bar
    st.markdown(f"""
    <div class="cbui-section-bar analyse">
      <div class="cbui-bar-letter">A</div>
      <div class="cbui-bar-text">
        <div class="cbui-bar-title">{L('terrain_title')}</div>
        <div class="cbui-bar-sub">{L('terrain_personas')} · {L('terrain_tagline')}</div>
      </div>
    </div>""", unsafe_allow_html=True)

    # Champ principal
    st.markdown(f"**{L('t_fr_label')}**")
    fr_text = st.text_area(" ", value=s["bui_t_fr"], placeholder=L("t_fr_ph"),
                           height=110, key="bui_t_fr_ta", label_visibility="collapsed")
    s["bui_t_fr"] = fr_text
    _pv50 = _status_preview50(fr_text, "fr")
    if _pv50:
        (st.warning if _pv50.startswith("⚠") else st.info)(_pv50)

    st.caption("Ou commencez par :")
    cols_v = st.columns(len(verbs))
    for i, (col, v) in enumerate(zip(cols_v, verbs)):
        with col:
            selected = s.get("bui_t_verb", "") == v
            if st.button(v, key=f"bui_t_verb_{i}",
                         type="primary" if selected else "secondary",
                         use_container_width=True):
                s["bui_t_verb"] = v if not selected else ""
                st.rerun()

    st.divider()

    # Champs secondaires (repliés)
    with st.expander("Précisions supplémentaires — question, horizon, langue, société", expanded=False):
        q1 = st.text_input(L("t_q1_label"), value=s["bui_t_q1"],
                           placeholder=L("t_q1_ph"), key="bui_t_q1_ti")
        s["bui_t_q1"] = q1
        h_idx = hors.index(s["bui_t_horizon"]) if s["bui_t_horizon"] in hors else 1
        hor = st.radio(L("t_hor_label"), hors, index=h_idx, horizontal=True, key="bui_t_hor_r")
        s["bui_t_horizon"] = hor
        l_idx = _LANG_OPTS.index(s["bui_t_langue"]) if s["bui_t_langue"] in _LANG_OPTS else 0
        lng = st.radio(L("t_lang_label"), _LANG_OPTS, index=l_idx, horizontal=True, key="bui_t_lang_r", on_change=_sync_ui_lang_b138, args=("bui_t_lang_r",))
        s["bui_t_langue"] = lng
        st.divider()
        # Société et SIREN — optionnels, alimentent l'enrichissement Pappers
        col_soc, col_siren = st.columns([3, 2])
        with col_soc:
            # v16.5.59 — Sync bui_t_soc_ti depuis bui_t_soc avant chaque render
            # Quand le lookup SIREN écrit dans s["bui_t_soc"] + st.rerun(),
            # on pousse la valeur dans la clé widget AVANT instanciation → affichage correct
            _soc_data = s.get("bui_t_soc", "")
            _soc_widget = st.session_state.get("bui_t_soc_ti", "")
            if _soc_data and _soc_data != _soc_widget:
                st.session_state["bui_t_soc_ti"] = _soc_data
            soc = st.text_input(L("t_soc_label"),
                                placeholder=L("t_soc_ph"), key="bui_t_soc_ti")
            s["bui_t_soc"] = soc
        with col_siren:
            siren_val = st.text_input(L("t_siren_label"), value=s.get("bui_t_siren", ""),
                                      placeholder=L("t_siren_ph"), key="bui_t_siren_ti",
                                      max_chars=9)
            # Validation souple : on accepte uniquement les chiffres
            s["bui_t_siren"] = "".join(c for c in siren_val if c.isdigit())[:9]
            # v16.5.59 — Auto-complétion nom société depuis SIREN
            _siren_clean = s["bui_t_siren"]
            if (len(_siren_clean) == 9
                    and not s.get("bui_t_soc", "").strip()
                    and _siren_clean != st.session_state.get("_last_siren_lookup", "")):
                try:
                    import os as _os
                    _pap_key = _os.getenv("PAPPERS_API_KEY", "").strip()
                    # Correctif TCR-v8 (verdict v7, P0-3) — le RENDU du
                    # brief n'a AUCUN effet externe tant que l'autorité
                    # temporelle n'est pas établie : l'auto-complétion
                    # Pappers n'est autorisée que si app.py a ouvert la
                    # porte APRÈS son préflight (drapeau posé avant le
                    # render). Absent ⇒ FERMÉ (fail-closed) : appel
                    # bibliothèque, test ou rendu hors app = zéro réseau.
                    if st.session_state.get(
                            "_temporal_gate_open") is not True:
                        _pap_key = ""
                    if _pap_key:
                        _nom_found = ""
                        # 1. Cache disque d'abord (0 crédit)
                        try:
                            from utils.pappers_tool import PappersCache as _PC
                            from utils.config_paths import get_config_dir as _gcd
                            _cache = _PC(_gcd() / "pappers_cache.json")
                            _fiche = _cache.get("fiche_" + _siren_clean)
                            if _fiche and _fiche.get("nom_entreprise"):
                                _nom_found = _fiche["nom_entreprise"]
                        except Exception:
                            pass
                        # 2. API Pappers si pas en cache
                        if not _nom_found:
                            import requests as _req
                            _r = _req.get(
                                "https://api.pappers.fr/v2/entreprise",
                                params={"api_token": _pap_key, "siren": _siren_clean,
                                        "champs": "nom_entreprise"},
                                timeout=4
                            )
                            if _r.status_code == 200:
                                _nom_found = _r.json().get("nom_entreprise", "")
                        if _nom_found:
                            # s = st.session_state → écriture directe dans l'état global
                            s["bui_t_soc"] = _nom_found
                            st.session_state["_last_siren_lookup"] = _siren_clean
                            st.rerun()
                except Exception:
                    pass  # Non bloquant

    # ─── v16.5.74 — Item #6 : Dropdown pays + numéro registre international ───
    # Avant v16.5.74 : un seul champ "SIREN (9 chiffres)" → ne convenait pas
    # aux sociétés étrangères. Test dossier anglophone coté (UK Companies House Number 8
    # chiffres, pas SIREN) → l'utilisateur saisissait dans le champ SIREN
    # et la validation `[:9].isdigit()` corrigeait silencieusement (heureux
    # hasard). Pour un utilisateur novice : ne pas remplir = pas d'enrichissement.
    # v16.5.74 : ajout d'un sélecteur de pays + d'un champ adaptatif pour les
    # numéros d'enregistrement étrangers (UK Company Number, US EIN/Ticker,
    # DE HRB, NL KvK, ES NIF, IT P.IVA, BE BCE).
    _COUNTRY_REGISTRY_FORMATS = {
        "🇫🇷 France":         {"id_label": "SIREN", "id_format": "9 chiffres", "id_help": "Champ SIREN ci-dessus", "regex_hint": r"\d{9}"},
        "🇬🇧 Royaume-Uni":   {"id_label": "Company Number (Companies House)", "id_format": "8 caractères (chiffres ou alphanumériques)", "id_help": "Ex : 8 caractères, ex. 00XXXXXX", "regex_hint": r"[A-Z]{0,2}\d{6,8}"},
        "🇺🇸 États-Unis":    {"id_label": "EIN ou ticker SEC", "id_format": "EIN 9 chiffres (XX-XXXXXXX) ou ticker boursier", "id_help": "Ex : AAPL, GOOGL", "regex_hint": r"\d{2}-\d{7}|[A-Z]{1,5}"},
        "🇩🇪 Allemagne":     {"id_label": "HRB / HRA Number", "id_format": "Format : HRB XXXXXX (Berlin, Munich…)", "id_help": "Numéro Handelsregister", "regex_hint": r"HR[AB]\s?\d{1,7}"},
        "🇳🇱 Pays-Bas":      {"id_label": "KvK Number", "id_format": "8 chiffres", "id_help": "Numéro Kamer van Koophandel", "regex_hint": r"\d{8}"},
        "🇧🇪 Belgique":      {"id_label": "BCE / Numéro d'entreprise", "id_format": "10 chiffres (XXXX.XXX.XXX)", "id_help": "Banque-Carrefour des Entreprises", "regex_hint": r"\d{4}\.?\d{3}\.?\d{3}"},
        "🇮🇹 Italie":        {"id_label": "Partita IVA", "id_format": "11 chiffres", "id_help": "Codice IVA", "regex_hint": r"\d{11}"},
        "🇪🇸 Espagne":       {"id_label": "NIF / CIF", "id_format": "9 caractères (1 lettre + 8 chiffres)", "id_help": "Número de Identificación Fiscal", "regex_hint": r"[A-Z]\d{8}"},
        "🌍 LEI uniquement": {"id_label": "LEI (Legal Entity Identifier)", "id_format": "20 caractères alphanumériques", "id_help": "Universel — fonctionne pour toute société cotée", "regex_hint": r"[A-Z0-9]{20}"},
    }
    _country_keys = list(_COUNTRY_REGISTRY_FORMATS.keys())

    st.write("")
    col_country, col_intl = st.columns([2, 3])
    with col_country:
        _current_country = s.get("bui_t_country", "🇫🇷 France")
        _idx = _country_keys.index(_current_country) if _current_country in _country_keys else 0
        _selected = st.selectbox(
            L("t_country_label"),
            _country_keys,
            index=_idx,
            help=L("t_country_help"),
            key="bui_t_country_sb",
        )
        s["bui_t_country"] = _selected
    with col_intl:
        _fmt = _COUNTRY_REGISTRY_FORMATS[_selected]
        if _selected == "🇫🇷 France":
            # France : on délègue au champ SIREN existant (au-dessus)
            st.caption(f"➜ Utilisez le champ **SIREN** ci-dessus ({_fmt['id_format']})")
        else:
            _intl_label = f"{_fmt['id_label']} — {_fmt['id_format']}"
            _intl_val = st.text_input(
                _intl_label,
                value=s.get("bui_t_intl_reg", ""),
                placeholder=_fmt.get("id_help", ""),
                help=L("t_intl_reg_help"),
                key="bui_t_intl_reg_ti",
                max_chars=30,
            )
            s["bui_t_intl_reg"] = _intl_val.strip()
    # ─── Fin v16.5.74 — Item #6 ──────────────────────────────────────────────

    st.write("")

    # Footer
    col_m, col_e, col_l = st.columns([2, 3, 2])
    with col_m:
        if st.button(L("change_mode"), key="bui_t_change"):
            st.session_state["bui_mode"] = None
            st.rerun()
    with col_e:
        if st.button(L("enrich_btn"), key="bui_t_enrich", type="secondary", use_container_width=True):
            _transfer_terrain_to_equipe()
            st.rerun()
    with col_l:
        if s["bui_t_fr"].strip():
            st.success(L("brief_ready"))
        else:
            st.caption(L("fill_brief"))

    return (_assemble_terrain(lang, temporal_control_input)
            if s["bui_t_fr"].strip() else "")

# ─────────────────────────────────────────────────────────────────────────────
# TRANSFER  Terrain → Équipe
# ─────────────────────────────────────────────────────────────────────────────
def _transfer_terrain_to_equipe():
    s = st.session_state
    # Correctif TCR-v9 (verdict v8, P0-2) — le champ principal Terrain
    # est DÉCISIONNAIRE : il doit atterrir dans le champ décisionnaire
    # Équipe (bui_e_fr), jamais dans le champ narratif « situation » —
    # sinon un label signé perd toute autorité et un backtest
    # read-only redevient un run live écrivant.
    if s.get("bui_t_fr"):       s["bui_e_fr"]      = s["bui_t_fr"]
    if s.get("bui_t_sit"):      s["bui_e_sit"]     = s["bui_t_sit"]
    if s.get("bui_t_verb"):     s["bui_e_verb"]    = s["bui_t_verb"]
    if s.get("bui_t_q1"):       s["bui_e_q1"]      = s["bui_t_q1"]
    if s.get("bui_t_horizon"):  s["bui_e_horizon"] = s["bui_t_horizon"]
    if s.get("bui_t_langue"):   s["bui_e_langue"]  = s["bui_t_langue"]
    if s.get("bui_t_soc"):      s["bui_e_societe"] = s["bui_t_soc"]
    if s.get("bui_t_siren"):    s["bui_e_siren"]   = s["bui_t_siren"]
    s["bui_prefilled"] = True
    s["bui_mode"]      = "equipe"
    s["bui_eq_step"]   = 0

# ─────────────────────────────────────────────────────────────────────────────
# BRIEF ÉQUIPE
# ─────────────────────────────────────────────────────────────────────────────
_MSG_OPTS_FR = ["Conseil", "Actionnaire", "Équipes", "Banque", "Client clé", "Partenaire social"]
_MSG_OPTS_EN = ["Board", "Shareholder", "Teams", "Bank", "Key client", "Social partner"]
_MODE_OPTS_FR = ["Diagnostic", "Décision / Arbitrage", "Alerte / Crise", "Revue périodique", "Préparation Conseil", "Post-acquisition", "Plan stratégique"]
_MODE_OPTS_EN = ["Diagnostic", "Decision / Arbitration", "Alert / Crisis", "Periodic review", "Board prep", "Post-acquisition", "Strategic plan"]
_ACTO_FR = ["Familial", "PE / Fonds", "Coté", "Public / Parapublic", "JV / Multi-actionnaires", "Autre"]
_ACTO_EN = ["Family", "PE / Funds", "Listed", "Public / Semi-public", "JV / Multi-shareholder", "Other"]
_REF_FR = ["vs Budget", "vs N-1", "vs Plan strat.", "vs Marché"]
_REF_EN = ["vs Budget", "vs N-1", "vs Strategic plan", "vs Market"]
_FOCUS_FR = ["Stratégie", "Marketing", "Finance", "Supply Chain", "Commercial", "DG / Synthèse"]
_FOCUS_EN = ["Strategy", "Marketing", "Finance", "Supply Chain", "Commercial", "CEO / Synthesis"]

_SECTION_STYLES = ["equipe-A", "equipe-B", "equipe-C", "equipe-D", "equipe-E"]
_SECTION_LETTERS = ["A", "B", "C", "D", "E"]

def _step_bar(step: int, total: int = 3):
    dots = ""
    for i in range(total):
        cls = "done" if i < step else ("active" if i == step else "")
        dots += f'<div class="cbui-step {cls}"></div>'
    st.markdown(f'<div class="cbui-steps">{dots}</div>', unsafe_allow_html=True)

def _section_bar(lang, key, letter, style):
    L = lambda k: _l(k, lang)
    titles = {
        "section_A": "Cap décisionnel — Fil rouge & Mode",
        "section_B": "Contexte business — Identité & Situation",
        "section_C": "Cœur du CODIR — Questions & Horizon",
        "section_D": "Enrichissement analytique",
        "section_E": "Finalisation — Contraintes & Zone humaine",
    }
    title = L(key) if L(key) != key else titles.get(key, key)
    st.markdown(f"""
    <div class="cbui-section-bar {style}">
      <div class="cbui-bar-letter">{letter}</div>
      <div class="cbui-bar-text">
        <div class="cbui-bar-title">{title}</div>
      </div>
    </div>""", unsafe_allow_html=True)

def _render_equipe(lang: str, temporal_control_input=None) -> str:
    st.markdown(_CSS, unsafe_allow_html=True)
    L = lambda k: _l(k, lang)
    s = st.session_state
    step = s.get("bui_eq_step", 0)
    verbs = _VERBS_FR if lang == "fr" else _VERBS_EN
    q_types = _Q_TYPES_FR if lang == "fr" else _Q_TYPES_EN
    hors = _HOR_FR if lang == "fr" else _HOR_EN
    msg_opts = _MSG_OPTS_FR if lang == "fr" else _MSG_OPTS_EN
    mode_opts = _MODE_OPTS_FR if lang == "fr" else _MODE_OPTS_EN
    acto_opts = _ACTO_FR if lang == "fr" else _ACTO_EN
    ref_opts = _REF_FR if lang == "fr" else _REF_EN
    focus_opts = _FOCUS_FR if lang == "fr" else _FOCUS_EN

    # Prefill banner
    if s.get("bui_prefilled"):
        st.markdown(f'<div class="cbui-prefill-banner">💡 {L("prefill_banner")}</div>', unsafe_allow_html=True)

    # UI-1 — sélecteur de langue VISIBLE dès le début du mode Développé (il n'était
    # accessible qu'à l'étape E). Le choix pilote réellement la langue du run.
    _lang_cols = st.columns([3, 2])
    with _lang_cols[1]:
        _eli = _LANG_OPTS.index(s["bui_e_langue"]) if s.get("bui_e_langue") in _LANG_OPTS else 0
        s["bui_e_langue"] = st.radio(L("eq_lang_label"), _LANG_OPTS, index=_eli,
                                     horizontal=True, key="bui_e_lang_top_r", on_change=_sync_ui_lang_b138, args=("bui_e_lang_top_r",))

    # ── HEADER : mode change + barre de progression + nav EN HAUT ──
    col_hdr, col_nav_l, col_nav_r = st.columns([2, 1, 1])
    with col_hdr:
        if st.button(L("change_mode"), key="bui_e_change"):
            st.session_state["bui_mode"] = None
            st.rerun()
    with col_nav_l:
        if step > 0:
            if st.button(L("btn_prev"), key="bui_e_prev_top"):
                s["bui_eq_step"] = step - 1
                st.rerun()
    with col_nav_r:
        if step < 2:
            if st.button(L("btn_next"), key="bui_e_next_top", type="primary"):
                s["bui_eq_step"] = step + 1
                st.rerun()
        else:
            if bool(s["bui_e_fr"] or s["bui_e_verb"]) and bool(s["bui_e_q1"]):
                st.success(L("brief_ready"))
    _step_bar(step, total=3)

    # ── SECTION A ──────────────────────────────────────────────────
    if step == 0:
        _section_bar(lang, "section_A", "A", "equipe-A")
        st.markdown(f"**{L('eq_fr_label')}**")
        st.caption(L("eq_fr_sub"))
        verb_idx = verbs.index(s["bui_e_verb"]) if s["bui_e_verb"] in verbs else 0
        verb = st.radio(" ", verbs, index=verb_idx, horizontal=True, key="bui_e_verb_r", label_visibility="collapsed")
        s["bui_e_verb"] = verb
        fr = st.text_area(" ", value=s["bui_e_fr"], placeholder=L("eq_fr_ph"), height=80,
                          key="bui_e_fr_ta", label_visibility="collapsed")
        s["bui_e_fr"] = fr
        _pv50 = _status_preview50(fr, str(locals().get("lang") or "fr"))
        if _pv50:
            (st.warning if _pv50.startswith("⚠") else st.info)(_pv50)
        st.divider()
        msg_default = [m for m in s["bui_e_msg"] if m in msg_opts]
        msgs = st.multiselect(L("eq_msg_label"), msg_opts, default=msg_default, key="bui_e_msg_ms")
        s["bui_e_msg"] = msgs
        st.divider()
        mode_default = [m for m in s["bui_e_modes"] if m in mode_opts]
        modes = st.multiselect(L("eq_mode_label"), mode_opts, default=mode_default, key="bui_e_modes_ms")
        s["bui_e_modes"] = modes

    # ── SECTION B ──────────────────────────────────────────────────
    elif step == 1:
        _section_bar(lang, "section_B", "B", "equipe-B")
        st.markdown(f"**{L('eq_id_label')}**")
        s["bui_e_societe"]  = st.text_input(L("eq_field_societe"), value=s["bui_e_societe"], placeholder=L("eq_societe_ph"), key="bui_e_soc")
        s["bui_e_secteur"]  = st.text_input(L("eq_field_secteur"), value=s["bui_e_secteur"], placeholder=L("eq_secteur_ph"), key="bui_e_sec")
        s["bui_e_taille"]   = st.text_input(L("eq_field_taille"), value=s["bui_e_taille"], placeholder=L("eq_taille_ph"), key="bui_e_tai")
        s["bui_e_geo"]      = st.text_input(L("eq_field_geo"), value=s["bui_e_geo"], placeholder=L("eq_geo_ph"), key="bui_e_geo_ti")
        acto_idx = acto_opts.index(s["bui_e_acto"]) if s["bui_e_acto"] in acto_opts else 0
        s["bui_e_acto"] = st.selectbox(L("eq_acto_label"), acto_opts, index=acto_idx, key="bui_e_acto_sb")
        s["bui_e_siren"] = st.text_input(L("eq_field_siren"), value=s["bui_e_siren"], placeholder=L("eq_siren_ph"), key="bui_e_siren_ti")
        st.divider()
        st.markdown(f"**{L('eq_sit_label')}**")
        st.caption(L("eq_sit_sub"))
        s["bui_e_sit"] = st.text_area(" ", value=s["bui_e_sit"], placeholder=L("eq_sit_ph"), height=90,
                                       key="bui_e_sit_ta", label_visibility="collapsed")
        ref_idx = ref_opts.index(s["bui_e_ref"]) if s["bui_e_ref"] in ref_opts else 0
        s["bui_e_ref"] = st.radio(L("eq_ref_label"), ref_opts, index=ref_idx, horizontal=True, key="bui_e_ref_r")
        s["bui_e_declencheur"] = st.text_input(L("eq_field_declencheur"), value=s["bui_e_declencheur"],
                                                placeholder=L("eq_decl_ph"), key="bui_e_decl_ti")

    # ── SECTION C ──────────────────────────────────────────────────
    elif step == 2:
        _section_bar(lang, "section_C", "C", "equipe-C")
        st.markdown(f"**{L('eq_q1_label')}**")
        st.caption(L("eq_q1_sub"))
        s["bui_e_q1"] = st.text_input("Q1", value=s["bui_e_q1"], placeholder=L("eq_q1_ph"), key="bui_e_q1_ti")
        qt1_idx = q_types.index(s["bui_e_q1_type"]) if s["bui_e_q1_type"] in q_types else 0
        s["bui_e_q1_type"] = st.selectbox("Type Q1", q_types, index=qt1_idx, key="bui_e_q1t_sb")
        s["bui_e_q2"] = st.text_input(L("eq_field_q2"), value=s["bui_e_q2"], placeholder=L("eq_q2_ph"), key="bui_e_q2_ti")
        qt2_idx = q_types.index(s["bui_e_q2_type"]) if s["bui_e_q2_type"] in q_types else 1
        s["bui_e_q2_type"] = st.selectbox("Type Q2", q_types, index=qt2_idx, key="bui_e_q2t_sb")
        st.divider()
        st.markdown(f"**{L('eq_hor_label')}**")
        h_idx = hors.index(s["bui_e_horizon"]) if s["bui_e_horizon"] in hors else 1
        s["bui_e_horizon"] = st.radio(" ", hors, index=h_idx, horizontal=True, key="bui_e_hor_r", label_visibility="collapsed")
        s["bui_e_deadline"] = st.text_input(L("eq_field_deadline"), value=s["bui_e_deadline"],
                                            placeholder=L("eq_dl_ph"), key="bui_e_dl_ti")
        st.divider()
        s["bui_e_echec"] = st.text_area(L("eq_echec_label"), value=s["bui_e_echec"],
                                         placeholder=L("eq_echec_ph"), height=68, key="bui_e_echec_ta")

    # ── SECTION D ──────────────────────────────────────────────────
    elif step == 3:
        _section_bar(lang, "section_D", "D", "equipe-D")
        focus_default = [f for f in s["bui_e_focus"] if f in focus_opts]
        s["bui_e_focus"] = st.multiselect(L("eq_focus_label"), focus_opts, default=focus_default, key="bui_e_focus_ms")
        st.divider()
        st.markdown(f"**{L('eq_field_kpis')}**")
        s["bui_e_kpi_com"] = st.text_area(L("eq_kpi_com"), value=s["bui_e_kpi_com"],
                                           placeholder=L("eq_kpi_ph"), height=60, key="bui_e_kpi_com_ta")
        s["bui_e_kpi_fin"] = st.text_area(L("eq_kpi_fin"), value=s["bui_e_kpi_fin"],
                                           placeholder=L("eq_kpi_ph"), height=60, key="bui_e_kpi_fin_ta")
        s["bui_e_kpi_sc"]  = st.text_area(L("eq_kpi_sc"),  value=s["bui_e_kpi_sc"],
                                           placeholder=L("eq_kpi_ph"), height=60, key="bui_e_kpi_sc_ta")
        s["bui_e_kpi_rh"]  = st.text_area(L("eq_kpi_rh"),  value=s["bui_e_kpi_rh"],
                                           placeholder=L("eq_kpi_ph"), height=60, key="bui_e_kpi_rh_ta")

    # ── SECTION E ──────────────────────────────────────────────────
    elif step == 4:
        _section_bar(lang, "section_E", "E", "equipe-E")
        s["bui_e_decisions"] = st.text_area(L("eq_decisions_label"), value=s["bui_e_decisions"],
                                             placeholder=L("eq_decisions_ph"), height=80, key="bui_e_dec_ta")
        s["bui_e_contraintes"] = st.text_area(L("eq_contraintes_label"), value=s["bui_e_contraintes"],
                                               placeholder=L("eq_contraintes_ph"), height=80, key="bui_e_con_ta")
        st.divider()  # UI-1 — sélecteur de langue déplacé en tête du mode Développé
        # v16.5.76 item 6 — Champ UI dédié pour forcer l'analyse Supply Chain
        # Complète la balise textuelle SUPPLY CHAIN: oui/non parsée par codir_engine._parse_supply_chain_override
        # Cas d'usage : holdings avec APE trompeur (dossier réseau de soins 70.21Z classée services, filiales 47.74Z avec stocks majeurs)
        _SC_OPTS = ["auto", "yes", "no"]
        _SC_LABELS = {
            "auto": L("eq_sc_auto"),
            "yes":  L("eq_sc_force_yes"),
            "no":   L("eq_sc_force_no"),
        }
        sc_current = s.get("bui_e_sc_override", "auto")
        if sc_current not in _SC_OPTS:
            sc_current = "auto"
        sc_idx = _SC_OPTS.index(sc_current)
        s["bui_e_sc_override"] = st.radio(
            L("eq_sc_label"),
            _SC_OPTS,
            index=sc_idx,
            format_func=lambda o: _SC_LABELS[o],
            horizontal=True,
            key="bui_e_sc_override_r",
            help=L("eq_sc_help"),
        )
        st.divider()
        st.markdown(f"""<div class="cbui-zh-header">
          <div class="cbui-zh-title">{L('eq_zh_label')}</div>
          <div class="cbui-zh-sub">{L('eq_zh_sub')}</div>
        </div>""", unsafe_allow_html=True)
        s["bui_e_zh"] = st.text_area(" ", value=s["bui_e_zh"], placeholder=L("eq_zh_ph"),
                                      height=90, key="bui_e_zh_ta", label_visibility="collapsed")

    # ── NAV BAS — version compacte pour confirmation visuelle ──────
    st.divider()
    nav_l, _, nav_r = st.columns([2, 3, 3])
    with nav_l:
        if step > 0:
            if st.button(L("btn_prev"), key="bui_e_prev"):
                s["bui_eq_step"] = step - 1
                st.rerun()
    with nav_r:
        if step < 2:
            if st.button(L("btn_next"), key="bui_e_next", type="primary"):
                s["bui_eq_step"] = step + 1
                st.rerun()
        else:
            ready = bool(s["bui_e_fr"] or s["bui_e_verb"]) and bool(s["bui_e_q1"])
            if ready: st.success(L("brief_ready"))
            else: st.caption(L("fill_brief"))

    # Return assembled brief (always, from whatever has been filled)
    return (_assemble_equipe(lang, temporal_control_input)
            if (s["bui_e_fr"] or s["bui_e_verb"]) else "")

# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
def _sync_ui_lang_b138(widget_key: str) -> None:
    """B.1.3.8 (demande terrain) — le choix de langue DU FORMULAIRE pilote
    aussi les ÉCRANS, immédiatement : override de session que app.py applique
    après load_settings() à chaque rerun (session-only : la préférence disque
    n'est jamais écrasée). Critère : cocher English à l'écran principal passe
    labels/boutons/messages en anglais sans ouvrir les paramètres."""
    try:
        val = st.session_state.get(widget_key)
        mapped = {"Français": "fr", "English": "en"}.get(str(val))
        if mapped:
            st.session_state["_ui_lang_override_b138"] = mapped
    except Exception:
        pass


def active_output_language(default: str = "fr") -> str:
    """UI-1 — langue de sortie EFFECTIVE choisie dans le brief (mode actif).
    « L'écran l'emporte » : ce choix pilote le run ; `default` (la config) sert de
    repli pour l'option « Bilingue » ou si rien n'a été sélectionné."""
    s = st.session_state
    mode = s.get("bui_mode")
    val = s.get("bui_e_langue") if mode == "equipe" else s.get("bui_t_langue")
    return {"Français": "fr", "English": "en"}.get(val, default)


def current_temporal_control_input(lang: str = "fr", settings=None):
    """Correctif TCR-v9 — instantané IMMUABLE de l'entrée temporelle
    COURANTE (valeurs des widgets du rerun en cours + pending A5), avant
    toute transformation d'interface. Lecture pure : aucun widget créé,
    aucune écriture d'état.

    Correctif TCR-v11 (verdict v10, P1-2) — `settings` est TRANSMIS par
    l'appelant : app.py le garde en variable locale et ne l'inscrit pas
    dans session_state, si bien que la réconciliation documentée de
    `settings.analysis_as_of_date` n'était pas active dans le chemin
    top-level. Repli sur session_state pour les appels bibliothèque."""
    from patches.temporal_control_input import build_temporal_control_input
    if settings is None:
        settings = st.session_state.get("settings")
    return build_temporal_control_input(st.session_state, settings)


def peek_control_input(lang: str = "fr") -> str:
    """Texte canonique de l'entrée temporelle courante, consommé par le
    pré-gate d'app.py AVANT le rendu du brief — donc avant tout
    enrichissement externe (Pappers & co.).

    Correctif TCR-v9 (verdict v8, P0-3) : la lecture part des CLÉS
    WIDGET (`bui_t_fr_ta` / `bui_e_fr_ta`, `codir_analysis_as_of_date`,
    pending A5) et non plus des copies canoniques écrites au rerun
    PRÉCÉDENT — le contrat « BLOCKED = zéro effet externe » ne dépend
    plus du contenu du rerun d'avant.

    Correctif TCR-v10 (verdict v9, P0-1) : FAIL-CLOSED. Une panne du
    producteur n'est plus rattrapée par une relecture permissive de
    l'état — elle rendait un brief live ordinaire et rouvrait les effets
    externes (1 appel Pappers observé). Le peek rend désormais la
    SENTINELLE de panne, que le résolveur — autorité unique — traduit en
    BLOCKED_ERROR. Le porteur reste une chaîne : tout consommateur du
    peek, y compris un consommateur écrit plus tard, hérite du
    fail-closed sans avoir à connaître la convention."""
    try:
        return current_temporal_control_input(lang).as_authority_text()
    except Exception:
        try:
            from patches.temporal_context import (
                TEMPORAL_INPUT_FAILURE_SENTINEL as _SENT)
            return _SENT
        except Exception:
            return "\x00codir:temporal-control-input-failure\x00"


def render(lang: str, temporal_control_input=None) -> str:
    """
    Renders the dual-mode brief UI and returns the assembled brief string.
    Returns "" if no brief has been composed yet.

    Correctif TCR-v10 (verdict v9, P0-3) — `temporal_control_input` est la
    photographie COURANTE déjà capturée par app.py et déjà résolue en
    contexte. Transmise ici, elle devient la source de l'assemblage : les
    lignes de contrôle et le contenu métier ne sont plus re-séparés à
    partir des copies canoniques, donc jamais reparsés. Absente (appel
    bibliothèque, test hérité), l'ancien chemin reste valide.
    """
    _init_state()
    mode = st.session_state.get("bui_mode")

    if mode is None:
        _render_mode_selection(lang)
        return ""
    elif mode == "terrain":
        return _render_terrain(lang, temporal_control_input)
    else:
        return _render_equipe(lang, temporal_control_input)
