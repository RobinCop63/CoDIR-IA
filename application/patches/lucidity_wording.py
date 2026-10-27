"""
patches/lucidity_wording.py — v16.5.67

Post-processor qui remplace automatiquement le vocabulaire décisionnel "ferme"
par un vocabulaire "propositionnel", aligné avec la philosophie CoDIR-IA :

    CoDIR-IA n'est pas un décideur. Il structure une réflexion.
    La décision reste humaine, responsable, contextualisée.

Règles de remplacement
----------------------
- DÉCISION VALIDÉE / Décision validée / décision validée  →  RECOMMANDÉ
- VALIDÉ / Validé / validé (forme isolée, pas "non validé")→ RECOMMANDÉ
- DÉCIDÉ / Décidé / décidé                                 →  À ARBITRER
- CONFIRMÉ / Confirmé / confirmé                           →  À INVESTIGUER
- ACTÉ / Acté / acté                                       →  RECOMMANDÉ

Chaque remplacement effectué est loggué dans le retour pour traçabilité
(verifiable dans codir_ia.log et diagnostics_ia.csv).

Non intrusif
-----------
- Préserve la casse locale :
    "DÉCISION VALIDÉE" → "RECOMMANDÉ"
    "Décision validée" → "Recommandé"
    "décision validée" → "recommandé"
- Ne touche PAS les sous-chaînes déjà remplacées (idempotent).
- Ne touche PAS "NON VALIDÉ", "non validé", "invalidé", "revalidation", etc.
- Peut être désactivé via CODIR_USE_LUCIDITY_WORDING=0.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


# ── Règles de remplacement ──────────────────────────────────────────────────
# (pattern regex, replacement, nom pour log)
# Ordre important : "décision validée" doit passer avant "validé" isolé.


# ── B.1.3.56 (scope G) — wording juridique prudent ────────────────────────────
# Jamais de certitude d'erreur ou d'inexistence juridique à partir des seules
# pièces fournies : « erroné » devient « apparemment incohérent — à vérifier »,
# « absence/inexistant » devient « non fourni/non établi dans les pièces —
# existence à vérifier ». Insertions grammaticalement neutres (aucun accord
# verbal cassé) et idempotentes.
_LEGAL_PRUDENCE_RULES = [
    (re.compile(r"((?:code\s+)?(?:APE|NAF)(?:\s+[\d.]+[A-Z]?)?)\s+"
                r"erron[ée]e?s?((?:\s+de\s+(?:la|l['’]|du|des)\s*\w+){0,1})",
                re.IGNORECASE),
     r"\1\2 (apparemment incohérent avec l'activité — à vérifier)",
     "legal_ape_apparent"),
    (re.compile(r"\babsence\s+de\s+(?=conventions?\b|organigramme\b|"
                r"statuts?\b|pacte\b|d[ée]l[ée]gations?\b)", re.IGNORECASE),
     "absence apparente, dans les pièces fournies, de ",
     "legal_absence_apparent"),
    # Gate 7, intégration Claude — PARITÉ FR/EN sur l'affirmatif : la règle
    # EN couvre missing/absent/not formalized/non-existent/not provided/
    # not established avec copule optionnelle ; la règle FR ne couvrait que
    # « absentes/inexistantes » en adjacence directe. « Conventions
    # manquantes » et « Les conventions sont manquantes » affirmaient un
    # état du monde sans requalification. Les négations restent intactes
    # (lookbehinds « ne/n'/non/pas ») — symétrie avec le masque EN.
    (re.compile(r"\b((?:les\s+)?conventions?\s+"
                r"(?:intra[- ]groupe|r[ée]glement[ée]es?)|"
                r"documents?\s+de\s+prix\s+de\s+transfert|"
                r"contrats?\s+intra[- ]groupe)\s+"
                r"(?:(?<!ne )(?<!n['’])(?:sont|restent|demeurent|est|reste|"
                r"demeure)\s+)?"
                r"(?<!non )(?<!pas )"
                r"(?:absent[es]?s?|inexistant[es]?s?|manquant[es]?s?)\b",
                re.IGNORECASE),
     lambda m: m.group(1) + (
         " non fournis dans les pièces — existence à vérifier"
         if re.match(r"(?i)\s*(?:documents?|contrats?)", m.group(1))
         else " non fournies dans les pièces — existence à vérifier"),
     "legal_not_provided"),
    # Gate 8 — forme verbale active (« les conventions manquent »), même
    # prudence. Les négations sont protégées par lookbehind.
    (re.compile(r"\b((?:les\s+)?conventions?\s+"
                r"(?:intra[- ]groupe|r[ée]glement[ée]es?)|"
                r"documents?\s+de\s+prix\s+de\s+transfert|"
                r"contrats?\s+intra[- ]groupe)\s+"
                r"(?<!ne )(?<!n['’])(?<!non )(?<!pas )"
                r"(?:manque|manquent|fait\s+d[ée]faut|font\s+d[ée]faut)\b",
                re.IGNORECASE),
     lambda m: m.group(1) + (
         " non fournis dans les pièces — existence à vérifier"
         if re.match(r"(?i)\s*(?:documents?|contrats?)", m.group(1))
         else " non fournies dans les pièces — existence à vérifier"),
     "legal_not_provided"),
    (re.compile(r"\b(organigramme(?:\s+\w+)?|pacte\s+d['’]associ[ée]s|"
                r"d[ée]l[ée]gations?\s+de\s+pouvoirs?)\s+inexistant[es]?\b",
                re.IGNORECASE),
     r"\1 non établi dans les pièces — existence à vérifier",
     "legal_not_provided"),
    # B.1.3.56 (gate ChatGPT, correction d'arbitrage) — l'ACTION « corriger le
    # code APE » affirme l'erreur : elle devient « faire vérifier puis corriger
    # uniquement si confirmé ». Un code cible éventuel est « envisagé », jamais
    # certifié.
    (re.compile(r"\bcorriger\s+le\s+code\s+APE"
                r"((?:\s+de\s+(?:la|l['’]|du|des)\s*\w+)?)"
                r"(?:\s+en\s+([\d.]+[A-Z]?))?", re.IGNORECASE),
     lambda m: (("Faire" if m.group(0)[:1].isupper() else "faire")
                + " vérifier l'adéquation du code APE"
                + (m.group(1) or "")
                + " auprès de l'INSEE"
                + (f" ({m.group(2)} envisagé)" if m.group(2) else "")
                + " et demander sa correction uniquement si l'INSEE constate "
                  "l'inadéquation"),
     "legal_ape_verify_first"),
    (re.compile(r"\b[àa]\s+corriger\s+en\s+([\d.]+[A-Z]?)", re.IGNORECASE),
     r"correction en \1 envisagée — à confirmer après vérification INSEE",
     "legal_ape_verify_first"),
    (re.compile(r"\b(conventions?(?:\s+intra[- ]groupe|\s+r[ée]glement[ée]es?)?)"
                r"\s+non\s+formalis[ée]e?s?\b", re.IGNORECASE),
     r"\1 non établies dans les pièces — existence, formalisation et "
     r"conformité à vérifier",
     "legal_not_provided"),
    # Parité EN (runs anglais : mêmes prudences, zéro fuite FR)
    (re.compile(r"\b((?:the\s+)?(?:APE|NAF)\s+code(?:\s+[\d.]+[A-Z]?)?)\s+"
                r"(?:is\s+)?(?:erroneous|incorrect|wrong)\b", re.IGNORECASE),
     r"\1 (apparently inconsistent with the activity — to be verified)",
     "legal_ape_apparent"),
    (re.compile(r"\bcorrect\s+the\s+(?:APE|NAF)\s+code"
                r"(?:\s+to\s+([\d.]+[A-Z]?))?", re.IGNORECASE),
     lambda m: (("Have" if m.group(0)[:1].isupper() else "have")
                + " the APE code adequacy verified with INSEE"
                + (f" ({m.group(1)} considered)" if m.group(1) else "")
                + " and request its correction only if the mismatch is "
                  "established by the registry"),
     "legal_ape_verify_first"),
    # B.1.3.56 correctif P1-G56-06 — parité EN complète sur l'ABSENCE de
    # conventions/documents : « missing/absent/not formalized/non-existent/
    # not provided/not established » affirme un état du monde ; les pièces
    # reçues permettent seulement de constater qu'ils n'y figurent pas.
    (re.compile(r"(?<!no )\b((?:intra[- ]group\s+)?agreements?|"
                r"(?:the\s+)?documents?)\s+"
                r"(?:are\s+|is\s+|remain\s+)?"
                r"(?:missing|absent|not\s+formali[sz]ed|non[- ]existent|"
                r"not\s+provided|not\s+established)\b"
                r"(?!\s+or\s+not\s+established)", re.IGNORECASE),
     r"\1 not provided or not established in the documents received — "
     r"existence, formalisation and compliance to be verified",
     "legal_not_provided_en"),
]


def _mask_quoted_spans(text: str):
    """B.1.3.56 — les règles de prudence juridique ne réécrivent JAMAIS une
    citation ni un intitulé de pièce : les spans « … », "…" et les lignes
    référençant un fichier (.pdf/.docx) sont masqués pendant la passe légale."""
    spans = []
    def _put(m):
        spans.append(m.group(0))
        return f"\x00LQ{len(spans)-1}\x00"
    out = re.sub(
        r"«[^»]{0,300}»|\"[^\"\n]{0,300}\"|“[^”\n]{0,300}”|‘[^’\n]{0,300}’|"
        r"`[^`\n]{1,300}`|(?<!\w)'[^'\n]{1,300}'(?!\w)|"
        # gate 5, intégration Claude — la protection des négations couvre
        # TOUTES les pièces juridiques usuelles, pas seulement « agreements »
        # (« No transfer pricing documents are missing » était réécrit à
        # contresens), et toutes les qualifications de la règle EN.
        r"(?i:\bnot\s+(?:a\s+single|one)\s+(?:[\w-]+\s+){0,3}?"
        r"(?:agreements?|documents?|contracts?|conventions?|policies|files?)\s+"
        r"(?:are\s+|is\s+|remain\s+)?"
        r"(?:missing|absent|not\s+formali[sz]ed|non[- ]existent|"
        r"not\s+provided|not\s+established)\b)|"
        r"(?i:\bnone\s+of\s+the\s+(?:[\w-]+\s+){0,3}?"
        r"(?:agreements?|documents?|contracts?|conventions?|policies|files?)\s+"
        r"(?:are\s+|is\s+|remain\s+)?"
        r"(?:missing|absent|not\s+formali[sz]ed|non[- ]existent|"
        r"not\s+provided|not\s+established)\b)|"
        r"(?i:\bneither(?:\s+of\s+the)?\s+(?:[\w-]+\s+){0,3}?"
        r"(?:agreements?|documents?|contracts?|conventions?|policies|files?)\s+"
        r"(?:are\s+|is\s+|remain\s+)?"
        r"(?:missing|absent|not\s+formali[sz]ed|non[- ]existent|"
        r"not\s+provided|not\s+established)\b)|"
        r"(?i:\bno\s+(?:[\w-]+\s+){0,3}?"
        r"(?:agreements?|documents?|contracts?|conventions?|policies|files?)\s+"
        r"(?:are\s+|is\s+|remain\s+)?"
        r"(?:missing|absent|not\s+formali[sz]ed|non[- ]existent|"
        r"not\s+provided|not\s+established)\b)|"
        r"(?i:\bnot\s+all\s+(?:[\w-]+\s+){0,3}?"
        r"(?:agreements?|documents?|contracts?|conventions?|policies|files?)\s+"
        r"(?:are\s+|is\s+|remain\s+)?"
        r"(?:missing|absent|not\s+formali[sz]ed|non[- ]existent|"
        r"not\s+provided|not\s+established)\b)|"
        r"(?i:\bthere\s+(?:are|is)\s+(?:not\s+any|no)\s+"
        r"(?:[\w-]+\s+){0,3}?"
        r"(?:agreements?|documents?|contracts?|conventions?|policies|files?)\s+"
        r"(?:missing|absent)\b)|"
        r"(?i:\bthe\s+phrase\s+(?:intra[- ]group\s+)?agreements?\s+(?:are\s+)?missing"
        r"\s+is\s+(?:a\s+)?(?:title|heading)\b)|"
        r"(?i:\b(?:the\s+)?(?:heading|section\s+title|title|label)\s*"
        r"(?:reads?|is)?\s*[:—–-]\s*[^\n]{0,160}?"
        r"(?:agreements?|documents?|contracts?|conventions?|policies|files?)\s+"
        r"(?:are\s+|is\s+)?(?:missing|absent|not\s+formali[sz]ed|"
        r"non[- ]existent|not\s+provided|not\s+established)\b)|"
        r"(?i:\bthe\s+(?:heading|section\s+title|title|label)\s+reads?\s*[:—–-]?\s*"
        r"[^\n]{0,160}?(?:agreements?|documents?|contracts?|conventions?|policies|files?)\s+"
        r"(?:are\s+|is\s+)?(?:missing|absent|not\s+formali[sz]ed|"
        r"non[- ]existent|not\s+provided|not\s+established)\b)|"
        # Métatexte non guillemeté : nom de section, phrase citée, intitulé.
        # Gate 8 — questions et métatexte FR/EN ne sont pas des assertions.
        # Gate 8, intégration Claude — les masques couvrent aussi les formes
        # VERBALES (« manquent-elles ? », « il est faux de dire que …
        # manquent ») : la règle active requalifiait des questions et des
        # méta-négations que les masques participiaux ne voyaient pas.
        r"(?im:^[^\n?]{0,240}(?:conventions?|documents?|contrats?|agreements?|contracts?)"
        r"[^\n?]{0,160}(?:manquant|manquent?|f(?:ait|ont)\s+d[ée]faut|"
        r"missing|absent|inexistant|non[- ]existent)"
        r"[^\n?]{0,80}\?)|"
        r"(?i:\b(?:le|la)\s+(?:titre|intitul[ée]|libell[ée]|phrase|question|mention)\s+"
        r"(?:est|dit|indique|reprend|porte)\s*:?[ ]*[^\n]{0,160}?"
        r"(?:conventions?|documents?|contrats?)\s+[^\n]{0,100}?"
        r"(?:manquant\w*|manquent?|f(?:ait|ont)\s+d[ée]faut|"
        r"absent\w*|inexistant\w*))|"
        r"(?i:\b(?:il\s+est\s+faux|il\s+serait\s+faux|on\s+ne\s+peut\s+pas)"
        r"\s+(?:de\s+)?(?:dire|conclure|affirmer)\s+que\s+[^\n]{0,160}?"
        r"(?:conventions?|documents?|contrats?)\s+[^\n]{0,100}?"
        r"(?:manquant\w*|manquent?|f(?:ait|ont)\s+d[ée]faut|"
        r"absent\w*|inexistant\w*))|"
        r"(?i:\bthe\s+(?:phrase|sentence|section\s+name|heading|title|label|wording)\s+"
        r"[^\n]{0,120}?(?:agreements?|documents?|contracts?|conventions?|policies|files?)\s+"
        r"(?:are\s+|is\s+)?(?:missing|absent|not\s+formali[sz]ed|non[- ]existent)"
        r"[^\n]{0,120}?(?:appears?|reads?|states?|was\s+quoted|is\s+quoted|"
        r"is\s+(?:a\s+)?(?:title|heading|label)|below|above|in\s+the\s+report)\b)",
        _put, text)
    # Gate 9 — protect epistemic uncertainty and negative absence forms
    # outside the already-masked quotes/titles. These are not assertions that
    # a document/agreement is missing; turning them into "not provided" would
    # manufacture a legal conclusion.
    _epistemic_patterns = (
        re.compile(
            r"\b(?:nous\s+ne\s+savons\s+pas|on\s+ne\s+sait\s+pas|"
            r"nous\s+ignorons|on\s+ignore|"
            r"il\s+reste\s+[àa]\s+(?:d[ée]terminer|[ée]tablir|v[ée]rifier|clarifier)|"
            r"la\s+question\s+de\s+savoir\s+si|"
            r"il\s+est\s+(?:incertain|impossible)\s+de\s+(?:savoir|d[ée]terminer)|"
            r"il\s+n['’]est\s+pas\s+[ée]tabli\s+que|"
            r"il\s+n['’]est\s+pas\s+certain\s+que|"
            r"il\s+n['’]est\s+pas\s+possible\s+de\s+(?:savoir|d[ée]terminer)|"
            r"(?:reste|restent|demeure)\s+[àa]\s+savoir\s+si|"
            r"rien\s+ne\s+permet\s+d['’][ée]tablir\s+que|"
            r"on\s+ne\s+peut\s+pas\s+(?:d[ée]terminer|[ée]tablir))\b"
            r"[^\n.!?;]{0,240}?(?:conventions?|documents?|contrats?)\b"
            r"[^\n.!?;]{0,160}?(?:manquant\w*|manquent?|f(?:ait|ont)\s+d[ée]faut|"
            r"absent\w*|inexistant\w*)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:we\s+(?:do\s+not|don't)\s+know|"
            r"it\s+(?:is|remains)\s+(?:unclear|uncertain|unknown)|"
            r"we\s+(?:cannot|can't|are\s+unable\s+to)\s+determine|"
            r"it\s+remains\s+to\s+be\s+determined|"
            r"it\s+has\s+not\s+been\s+established|"
            r"there\s+is\s+no\s+evidence)\b"
            r"[^\n.!?;]{0,80}?\b(?:whether|if|that)\b[^\n.!?;]{0,200}?"
            r"(?:agreements?|documents?|contracts?|conventions?|policies|files?)\b"
            r"[^\n.!?;]{0,140}?(?:missing|absent|not\s+formali[sz]ed|non[- ]existent|"
            r"not\s+provided|not\s+established)",
            re.IGNORECASE,
        ),
        # Gate 9, intégration Claude — « Whether … are missing remains open »
        # ouvre la proposition par le marqueur épistémique lui-même : aucun
        # second connecteur n'existe, le pattern général ne matchait pas.
        re.compile(
            r"\bwhether(?:\s+or\s+not)?\b[^\n.!?;]{0,200}?"
            r"(?:agreements?|documents?|contracts?|conventions?|policies|files?)\b"
            r"[^\n.!?;]{0,140}?(?:missing|absent|not\s+formali[sz]ed|"
            r"non[- ]existent|not\s+provided|not\s+established)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\bsans\s+(?:[\w-]+\s+){0,5}?(?:conventions?|documents?|contrats?)"
            r"[^\n.!?;]{0,120}?(?:manquant\w*|absent\w*|inexistant\w*)",
            re.IGNORECASE,
        ),
    )
    for _pat in _epistemic_patterns:
        out = _pat.sub(_put, out)
    return out, spans


def _unmask_quoted_spans(text: str, spans) -> str:
    for i, sp in enumerate(spans):
        text = text.replace(f"\x00LQ{i}\x00", sp)
    return text

_RULES: list[tuple[re.Pattern, str, str]] = [
    # DÉCISION VALIDÉE (+ variantes avec parenthèses ou chiffres)
    (re.compile(r"\bDÉCISION\s+VALID[ÉE]E?\b", re.UNICODE), "RECOMMANDÉ", "DECISION_VALIDEE→RECOMMANDE"),
    (re.compile(r"\bDécision\s+validée\b", re.UNICODE),     "Recommandé", "Decision_validee→Recommande"),
    (re.compile(r"\bdécision\s+validée\b", re.UNICODE),     "recommandé", "decision_validee→recommande"),
    # ACTÉ / ACTÉE
    (re.compile(r"\bACTÉE?\b", re.UNICODE), "RECOMMANDÉ", "ACTE→RECOMMANDE"),
    (re.compile(r"\bActée?\b", re.UNICODE), "Recommandé", "Acte→Recommande"),
    (re.compile(r"\bactée?\b", re.UNICODE), "recommandé", "acte→recommande"),
    # DÉCIDÉ
    (re.compile(r"\bDÉCIDÉE?\b", re.UNICODE),   "À ARBITRER",  "DECIDE→A_ARBITRER"),
    (re.compile(r"\bDécidée?\b", re.UNICODE),   "À arbitrer",  "Decide→A_arbitrer"),
    (re.compile(r"\bdécidée?\b", re.UNICODE),   "à arbitrer",  "decide→a_arbitrer"),
    # CONFIRMÉ
    (re.compile(r"\bCONFIRMÉE?\b", re.UNICODE), "À INVESTIGUER", "CONFIRME→A_INVESTIGUER"),
    (re.compile(r"\bConfirmée?\b", re.UNICODE), "À investiguer", "Confirme→A_investiguer"),
    (re.compile(r"\bconfirmée?\b", re.UNICODE), "à investiguer", "confirme→a_investiguer"),
    # VALIDÉ isolé (en dernier pour ne pas perturber "DÉCISION VALIDÉE" déjà capturé)
    # On évite "non validé", "NON VALIDÉ", "invalidé", "revalidation" via regex négatif
    (re.compile(r"(?<!non\s)(?<!NON\s)(?<!re)(?<!in)\bVALIDÉE?\b", re.UNICODE),
     "RECOMMANDÉ", "VALIDE→RECOMMANDE"),
    (re.compile(r"(?<!non\s)(?<!NON\s)(?<!re)(?<!in)\bValidée?\b", re.UNICODE),
     "Recommandé", "Valide→Recommande"),
    (re.compile(r"(?<!non\s)(?<!NON\s)(?<!re)(?<!in)\bvalidée?\b", re.UNICODE),
     "recommandé", "valide→recommande"),
]

# Flag d'environnement
_ENABLED = os.getenv("CODIR_USE_LUCIDITY_WORDING", "1").lower() in ("1", "true", "yes", "on")


@dataclass
class LucidityReplacementLog:
    """Trace auditable des remplacements effectués sur un texte."""
    total_count: int = 0
    by_rule: dict[str, int] = field(default_factory=dict)
    samples: list[str] = field(default_factory=list)  # extraits avant remplacement

    def to_dict(self) -> dict:
        return {
            "lucidity_wording_replacements": self.total_count,
            "lucidity_wording_by_rule": dict(self.by_rule),
            "lucidity_wording_samples": self.samples[:5],
        }


def apply_lucidity_wording(text: str, role: str = "") -> tuple[str, LucidityReplacementLog]:
    """
    Applique le vocabulaire Lucidité à un texte (sortie agent, CR, slide, etc.).

    Retourne (texte_modifié, log).
    Si le flag est désactivé, retourne (texte, log vide).
    """
    log = LucidityReplacementLog()
    if not text or not _ENABLED:
        return text, log

    modified = text
    for pattern, replacement, rule_name in list(_RULES):
        matches = list(pattern.finditer(modified))
        if not matches:
            continue
        log.total_count += len(matches)
        log.by_rule[rule_name] = log.by_rule.get(rule_name, 0) + len(matches)
        # Collecter 1-2 échantillons de contexte avant remplacement
        for m in matches[:2]:
            start = max(0, m.start() - 20)
            end = min(len(modified), m.end() + 20)
            sample = modified[start:end].replace("\n", " ")
            if role:
                sample = f"[{role}] {sample}"
            log.samples.append(sample)
        modified = pattern.sub(replacement, modified)

    # Passe légale (B.1.3.56) — citations et intitulés de pièces protégés.
    masked, _spans = _mask_quoted_spans(modified)
    for pattern, replacement, rule_name in _LEGAL_PRUDENCE_RULES:
        matches = list(pattern.finditer(masked))
        if not matches:
            continue
        log.total_count += len(matches)
        log.by_rule[rule_name] = log.by_rule.get(rule_name, 0) + len(matches)
        for m in matches[:2]:
            start = max(0, m.start() - 20)
            end = min(len(masked), m.end() + 20)
            sample = masked[start:end].replace("\n", " ")
            if role:
                sample = f"[{role}] {sample}"
            log.samples.append(sample)
        masked = pattern.sub(replacement, masked)
    modified = _unmask_quoted_spans(masked, _spans)

    return modified, log


_FLAG_IN_PLACE50 = True

_STATUS_WORDS50 = re.compile(r"(?i)\b(?:d[ée]cision\s+(?:valid[ée]e|act[ée]e)|d[ée]cid[ée]e?s?|act[ée]e?s?|valid[ée]e?s?|confirm[ée]e?s?|"
                             r"decided|approved|validated|confirmed|agreed)\b")
_NEGATED50 = re.compile(r"(?i)\b(?:non|pas|not|never|jamais|sans|without|to\s+be|à\s+(?:valider|confirmer))\s+(?:\w+\s+){0,1}$")
_CONTENT_WORD50 = re.compile(r"[A-Za-zÀ-ÿ]{5,}")


_HEADING50 = re.compile(r"^\s*(?:#{1,6}\s|\d+(?:\.\d+)*[.)]?\s+\S[^|]{0,90}$|\*\*[^*]+\*\*[\s:]*$)")
_SOURCE_CONTEXT50 = re.compile(r"(?i)\b(?:confirm[ée]e?s?|validated|confirmed)\s+(?:par|by|dans|in|on|à\s+la\s+page|at\s+page)\b|"
                               r"\b(?:p\.\s?\d+|page\s+\d+|10-K|rapport\s+annuel|annual\s+report|pi[èe]ce|source)\b")
_DECISION_NOUN50 = re.compile(r"(?i)\b(?:d[ée]cision|option|plan|hypoth[èe]se|orientation|strat[ée]gie|budget|action|recommandation|"
                              r"arbitrage|choix|lancement|investissement|cession|acquisition|decision|assumption|strategy|"
                              r"recommendation|choice|launch|investment|divestiture|roadmap|feuille\s+de\s+route)")


def _content_words50(s: str) -> set:
    return {w.lower() for w in _CONTENT_WORD50.findall(str(s or ""))}


def lucidity_flag_lines(text: str, lang: str = "fr", brief: str = "") -> list:
    """v62.13.9.4.50 — lignes où un agent présente comme ÉTABLI (décidé, acté, validé, confirmé) ce que le brief du
    dirigeant n'établit pas ; et affirmations juridiques d'absence ou d'erreur non établies par les pièces.

    Un statut que le BRIEF donne lui-même (« Actions déjà décidées : … ») est l'autorité du dirigeant : une ligne qui le
    reprend n'est pas signalée. Retourne [(indice de ligne, motif)] ; le texte n'est jamais modifié."""
    en = str(lang or "").lower().startswith("en")
    brief_lines = [l for l in str(brief or "").splitlines() if re.search(r"(?i)d[ée]cid|decided|approved|valid", l)]
    brief_sets = [_content_words50(l) for l in brief_lines]
    decided_block = bool(re.search(r"(?i)actions?\s+d[ée]j[àa]\s+d[ée]cid|already\s+decided", str(brief or "")))
    out = []
    for i, line in enumerate(str(text or "").splitlines()):
        # un TITRE n'est pas signalé (règle des titres) ; un fait « confirmé par la pièce / à la page » n'est pas un
        # statut de décision ; seul un statut appliqué à une DÉCISION (option, plan, hypothèse, action…) est jugé
        if _HEADING50.match(line):
            continue
        m = _STATUS_WORDS50.search(line)
        if m and (_SOURCE_CONTEXT50.search(line) or not _DECISION_NOUN50.search(line)):
            m = None
        if m and not _NEGATED50.search(line[:m.start()]):
            words = _content_words50(line)
            backed = any(len(words & bs) >= 4 for bs in brief_sets) or (
                decided_block and any(len(words & _content_words50(bl)) >= 3 for bl in str(brief or "").splitlines()))
            if not backed:
                out.append((i, "“decided/approved” status not established by the brief" if en
                            else "statut « décidé » non établi par le brief"))
                continue
        for pattern, _rep, _name in _LEGAL_PRUDENCE_RULES:
            if pattern.search(line):
                out.append((i, "legal assertion not established by the documents" if en
                            else "affirmation juridique non établie par les pièces"))
                break
    return out


def is_lucidity_wording_enabled() -> bool:
    return _ENABLED


# ── Système prompt complément (Lucidité L2) ─────────────────────────────────
# Instruction à injecter dans tous les prompts agents pour bannir VALIDÉE/DÉCIDÉ
# en amont (plutôt que d'attendre le post-processor).

LUCIDITY_PROMPT_FR = (
    "\n\n---\n"
    "VOCABULAIRE OBLIGATOIRE (CoDIR-IA v16.5.67 — Lucidité) :\n"
    "Tu n'es PAS un décideur. Tu structures la réflexion du CoDIR humain.\n"
    "Tu NE DOIS PAS utiliser les mots : VALIDÉ, DÉCIDÉ, CONFIRMÉ, ACTÉ, \n"
    "DÉCISION VALIDÉE, DÉCISION ACTÉE.\n"    "EXCEPTION (v62.13.9.4.50) : un statut que le BRIEF DU DIRIGEANT donne lui-même (« action déjà décidée », « réalisée »,\n"
    "« reportée ») est repris tel quel — c'est sa décision, pas la tienne ; ne le transforme jamais en « à arbitrer ».\n"
    "Tu DOIS utiliser à la place :\n"
    "  - RECOMMANDÉ             (au lieu de VALIDÉ / ACTÉ)\n"
    "  - À ARBITRER             (au lieu de DÉCIDÉ)\n"
    "  - À INVESTIGUER          (au lieu de CONFIRMÉ)\n"
    "  - À VÉRIFIER             (pour les points qui demandent confirmation humaine)\n"
    "\n"
    "Ces mots traduisent honnêtement le statut de tes propositions : "
    "elles ne remplacent pas la décision humaine, elles l'éclairent.\n"
)

LUCIDITY_PROMPT_EN = (
    "\n\n---\n"
    "MANDATORY VOCABULARY (CoDIR-IA v16.5.67 — Lucidity):\n"
    "You are NOT a decision-maker. You structure the human executive committee's reflection.\n"
    "You MUST NOT use the words: VALIDATED, DECIDED, CONFIRMED, APPROVED, \n"
    "VALIDATED DECISION, APPROVED DECISION.\n"    "EXCEPTION (v62.13.9.4.50): a status that the LEADER'S BRIEF itself gives (“already decided”, “completed”,\n"
    "“postponed”) is quoted as is — it is the leader's decision, not yours; never turn it into “to be arbitrated”.\n"
    "You MUST use instead:\n"
    "  - RECOMMENDED              (in place of VALIDATED / APPROVED)\n"
    "  - TO BE ARBITRATED         (in place of DECIDED)\n"
    "  - TO INVESTIGATE           (in place of CONFIRMED)\n"
    "  - TO VERIFY                (for points requiring human confirmation)\n"
    "\n"
    "These words honestly reflect the status of your proposals: "
    "they do not replace the human decision, they inform it.\n"
)


def lucidity_prompt(lang: str = "fr") -> str:
    """Retourne l'instruction Lucidité à concaténer à un prompt agent."""
    return LUCIDITY_PROMPT_EN if lang == "en" else LUCIDITY_PROMPT_FR


__all__ = [
    "apply_lucidity_wording",
    "is_lucidity_wording_enabled",
    "lucidity_prompt",
    "LUCIDITY_PROMPT_FR",
    "LUCIDITY_PROMPT_EN",
    "LucidityReplacementLog",
]
