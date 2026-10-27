"""9.4.61 — demande du dirigeant (12/10/2026) : le bandeau d'enrichissement annonçait « Enrichissement Pappers » et des
« sociétés » détectées (« Option », « Conseil ») pour une société américaine que Pappers ne couvre pas. Le bandeau
nomme désormais le ou les registres officiels réellement applicables, d'après les identifiants présents dans le brief."""
import re

_CIK = re.compile(r"(?i)\bCIK(?:\s+SEC)?\s*[:#n°]*\s*(\d{4,10})\b")
_LEI = re.compile(r"(?i)\bLEI\s*[:#n°]*\s*([A-Z0-9]{18}\d{2})\b")
_SIREN = re.compile(r"(?i)\bSIRE[NT]\s*[:#n°]*\s*(\d{3}\s?\d{3}\s?\d{3})(?:\s?\d{5})?\b")
_UKCH = re.compile(r"(?i)\b(?:Companies\s+House|company\s+(?:number|no\.?))\s*[:#n°]*\s*([A-Z]{0,2}\d{6,8})\b")


def detect_registry_sources(brief: str) -> list:
    """[(registre, identifiant)] des registres officiels applicables, dans l'ordre d'usage du produit."""
    s = str(brief or "")
    out = []
    m = _SIREN.search(s)
    if m:
        out.append(("Pappers (registre français)", "SIREN " + m.group(1).replace(" ", "")))
    m = _CIK.search(s)
    if m:
        out.append(("SEC EDGAR", "CIK " + m.group(1)))
    m = _UKCH.search(s)
    if m:
        out.append(("Companies House", m.group(1)))
    m = _LEI.search(s)
    if m:
        out.append(("GLEIF", "LEI " + m.group(1).upper()))
    return out


def registry_banner(brief: str, company: str, lang: str = "fr") -> str:
    en = str(lang).lower().startswith("en")
    src = detect_registry_sources(brief)
    who = f" **{company}**" if company else ""
    if src:
        lst = " · ".join(f"{n} ({i})" for n, i in src)
        return ((f"🔍 Enrichissement par registres officiels —{who} : {lst}") if not en
                else (f"🔍 Enrichment from official registers —{who}: {lst}"))
    return ((f"🔍 Enrichissement par registres officiels —{who} : aucun identifiant dans le brief ; le registre est choisi "
             f"selon le pays (Pappers pour la France, SEC EDGAR pour une société cotée aux États-Unis, Companies House au "
             f"Royaume-Uni, GLEIF par LEI). Ajoutez SIREN, CIK ou LEI pour garantir le rapprochement.") if not en else
            (f"🔍 Enrichment from official registers —{who}: no identifier in the brief; the register depends on the "
             f"country (Pappers for France, SEC EDGAR for a US-listed company, Companies House in the UK, GLEIF by LEI). "
             f"Add a SIREN, CIK or LEI to guarantee the match."))
