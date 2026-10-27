from __future__ import annotations

import logging as _logging_pdfminer_quiet

# v62.9 — silence ciblé du warning pdfminer FontBBox (non bloquant).
# Indispensable ici aussi : ce module peut être importé par des workers.
_logging_pdfminer_quiet.getLogger("pdfminer.pdffont").setLevel(
    _logging_pdfminer_quiet.ERROR)

# M.5.10.4 — module worker ré-importé par les enfants spawn (parsing PJ //).
# On silence le warning ScriptRunContext dès l'import pour garder la console
# propre côté workers. No-op si Streamlit absent.
try:
    import patches.streamlit_quiet as _sq  # noqa: F401
except Exception:
    _sq = None

import hashlib
import io
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
import multiprocessing as _mp
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Tuple, Optional

import pandas as pd

# ════════════════════════════════════════════════════════════════════════════
# Patch v16.5.72.9 (retex Robin) — Cache module-level pour parsing PJ
# ════════════════════════════════════════════════════════════════════════════
#
# Streamlit ré-exécute tout le script Python à chaque interaction utilisateur.
# Sans cache, parser 20 PJ (PDFs lourds, Excel) à chaque transition d'onglet
# = 20-60s perdues à chaque clic.
#
# Solution : cache module-level keyé par hash du contenu (MD5 sur les bytes).
# - Hit cache : instantané (lookup dict)
# - Miss cache : parsing normal + stockage du résultat
# - Pas de TTL : un fichier n'est parsé qu'une fois par session Python.
# - Limite mémoire : max 200 entrées (LRU eviction si dépassé)
#
# Effet attendu sur Robin (entreprise FR + 20 PJ) :
# - 1ère ouverture : 20-60s parsing (inchangé)
# - Transitions A→B→C suivantes : 0s sur le parsing (cache hit)
_PARSE_CACHE: Dict[str, Tuple[str, float]] = {}  # hash -> (text, timestamp)
_PARSE_CACHE_MAX = 200
_PARSE_CACHE_STATS = {"hits": 0, "misses": 0, "evictions": 0}


def _content_hash(data: bytes) -> str:
    """Hash MD5 du contenu pour cache key. MD5 suffit ici (pas crypto)."""
    return hashlib.md5(data).hexdigest()


def _cache_get(h: str) -> Optional[str]:
    entry = _PARSE_CACHE.get(h)
    if entry is None:
        _PARSE_CACHE_STATS["misses"] += 1
        return None
    _PARSE_CACHE_STATS["hits"] += 1
    # Refresh timestamp pour LRU
    _PARSE_CACHE[h] = (entry[0], time.time())
    return entry[0]


def _cache_set(h: str, text: str) -> None:
    if len(_PARSE_CACHE) >= _PARSE_CACHE_MAX:
        # Eviction LRU : supprime l'entrée la plus ancienne
        oldest = min(_PARSE_CACHE.items(), key=lambda kv: kv[1][1])
        del _PARSE_CACHE[oldest[0]]
        _PARSE_CACHE_STATS["evictions"] += 1
    _PARSE_CACHE[h] = (text, time.time())


def get_parse_cache_stats() -> Dict[str, int]:
    """Pour diagnostic : retourne les stats du cache parsing."""
    return {**_PARSE_CACHE_STATS, "size": len(_PARSE_CACHE)}


def reset_parse_cache() -> None:
    """Pour tests : reset du cache."""
    _PARSE_CACHE.clear()
    _PARSE_CACHE_STATS["hits"] = 0
    _PARSE_CACHE_STATS["misses"] = 0
    _PARSE_CACHE_STATS["evictions"] = 0


@dataclass
class AttachmentText:
    filename: str
    mimetype: str
    size_bytes: int
    text: str

def _estimate_tokens(text: str) -> int:
    # Rough heuristic: ~4 chars per token (English-ish). French is similar enough for budgeting.
    return max(1, int(len(text) / 4))

def _read_txt_bytes(data: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except Exception:
            continue
    return data.decode("utf-8", errors="ignore")

# ── v16.5.60 — Priorisation & détection "note de synthèse" ──────────────────
# Contexte : sur le cas dossier de conseil, la note Capeos courte (2 pages) qui
# contient l'info critique sur le CCA débiteur était noyée dans 80 pages
# de liasse fiscale, tronquée par le budget token global. On introduit :
#   1. un budget élargi (8000 → 24000 tokens par défaut),
#   2. une détection des "notes de synthèse" (via nom de fichier + taille),
#      servies EN PREMIER et sans troncature,
#   3. une limite PDF relevée (20 → 50 pages).

_SYNTHESIS_KEYWORDS = re.compile(
    r"(note[\s_-]*de[\s_-]*synth|synthese|synth[eè]se|résum[eé]|resume|"
    r"brief|memo|compte[\s_-]*rendu|cr[\s_-]*reunion|executive[\s_-]*summary|"
    r"capeos|kbis|k-bis)",
    re.IGNORECASE,
)

# v16.5.60 — détection dans les premières lignes du contenu extrait :
# certaines notes de synthèse arrivent avec des noms de fichier opaques
# (ex. "251007_CLIENT_CRM_2022.pdf") mais contiennent clairement
# "NOTE DE SYNTHESE" / "SYNTHÈSE" / "COMPTE-RENDU" dans leur en-tête.
_SYNTHESIS_CONTENT_HEAD = re.compile(
    r"(note\s+de\s+synth|synth[eè]se|compte[\s-]*rendu|"
    r"executive\s+summary|memo|brief(?:ing)?|"
    r"avis\s+du\s+cabinet|recommandations)",
    re.IGNORECASE,
)


def _is_likely_synthesis(filename: str, size_bytes: int, text: str = "") -> bool:
    """
    Un fichier est considéré comme "synthèse" (donc prioritaire) si
    AU MOINS UNE des conditions est remplie :
      - Mot-clé synthèse dans le nom de fichier ET taille < 200 KB
      - Fichier très court (< 30 KB) — ratio signal/bruit élevé par défaut
      - Mot-clé synthèse détecté dans les 600 premiers caractères du
        texte extrait (captures les notes avec noms opaques type
        "251007_CLIENT_CRM_2022.pdf" dont l'en-tête dit clairement
        "NOTE DE SYNTHESE DU 07/10/2025").
    """
    if _SYNTHESIS_KEYWORDS.search(filename) and size_bytes < 200_000:
        return True
    if size_bytes < 30_000:
        return True
    if text and _SYNTHESIS_CONTENT_HEAD.search(text[:600]):
        return True
    return False

# v62.13.9.4.40 — texte illisible : part du texte faite de glyphes sans correspondance Unicode —
# « (cid:NN) » chez le lecteur PDF des pièces, caractères de contrôle chez d'autres lecteurs.
_CID40_RE = re.compile(r"\(cid:\d+\)")
_UNREADABLE_PAGE40 = "[unreadable page / page illisible — text discarded / texte écarté]"
_UNREADABLE_FILE40_RE = re.compile(r"unreadable pages / pages illisibles:\s*(\d+)/(\d+)")


def _unreadable_text40(text: str, threshold: float = 0.05) -> bool:
    t = str(text or "")
    if len(t) < 80:
        return False
    ctrl = sum(1 for c in t if ord(c) < 32 and c not in "\n\t\r")
    cid = sum(len(m.group(0)) for m in _CID40_RE.finditer(t))
    return (ctrl + cid) / len(t) > threshold


def extract_text_from_upload(filename: str, mimetype: str, data: bytes) -> str:
    # Patch v16.5.72.9 — cache hit instantané sur ré-extraction du même fichier
    # (pattern Streamlit : tout le script rerun à chaque interaction).
    # Hash du contenu = clé. Si même bytes uploadés, on évite le re-parsing.
    cache_key = _content_hash(data)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    text = _extract_text_from_upload_uncached(filename, mimetype, data)
    _cache_set(cache_key, text)
    return text


def _extract_text_from_upload_uncached(filename: str, mimetype: str, data: bytes) -> str:
    ext = (Path(filename).suffix or "").lower()

    # Plain text / markdown
    if ext in [".txt", ".md"] or (mimetype.startswith("text/") if mimetype else False):
        return _read_txt_bytes(data)

    # CSV
    if ext == ".csv":
        df = pd.read_csv(io.BytesIO(data))
        return df.to_csv(index=False)

    # XLSX
    if ext in [".xlsx", ".xlsm"]:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        parts = []
        for ws in wb.worksheets[:5]:
            parts.append(f"## Feuille: {ws.title}")
            rows = []
            max_rows = min(ws.max_row or 0, 200)
            max_cols = min(ws.max_column or 0, 30)
            for r in range(1, max_rows + 1):
                row = []
                for c in range(1, max_cols + 1):
                    v = ws.cell(row=r, column=c).value
                    row.append("" if v is None else str(v))
                rows.append(row)
            # render as CSV-like text
            for row in rows:
                parts.append(",".join([x.replace("\n"," ").replace("\r"," ") for x in row]))
            parts.append("")
        return "\n".join(parts).strip()

    # DOCX
    if ext == ".docx":
        from docx import Document
        doc = Document(io.BytesIO(data))
        return "\n".join([p.text for p in doc.paragraphs if p.text.strip()])

    # PPTX
    if ext == ".pptx":
        from pptx import Presentation
        prs = Presentation(io.BytesIO(data))
        out = []
        for i, slide in enumerate(prs.slides, start=1):
            out.append(f"## Slide {i}")
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text:
                    out.append(shape.text.strip())
            out.append("")
        return "\n".join(out).strip()

    # PDF (best effort, no OCR)
    # v16.5.75.3 — Sprint #2 : détection rapide PDF scanné pour skip
    # extract_tables() qui est coûteux et inutile sans couche texte.
    if ext == ".pdf":
        import pdfplumber
        is_native_pdf = pdf_quick_native_check(data)
        txt_parts = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not is_native_pdf:
                # PDF scanné : on ajoute une note explicite + on saute extract_tables
                # (qui ne retournerait rien sur PDF sans couche texte).
                # On tente quand même extract_text() au cas où il y aurait une
                # couche OCR partielle (PDF hybride rare).
                txt_parts.append("[PDF scanné détecté — OCR non disponible dans CoDIR-IA v16.5.75.3]")
            # v16.5.60 — limite portée de 20 à 50 pages pour capter le détail
            # comptable (liasse fiscale intégrale) sans tronquer.
            _unread40, _read40 = 0, 0
            for i, page in enumerate(pdf.pages[:50], start=1):
                txt_parts.append(f"## Page {i}")
                text = page.extract_text() or ""
                if text.strip():
                    _read40 += 1
                    # v62.13.9.4.40 — PAGE ILLISIBLE. Une police à encodage non standard rend un texte
                    # chiffré (caractères de contrôle, lettres décalées) : il occupait le budget des
                    # pièces sans rien apporter, et la pièce passait pour exploitable.
                    if _unreadable_text40(text):
                        _unread40 += 1
                        txt_parts.append(_UNREADABLE_PAGE40)
                        txt_parts.append("")
                        continue
                    txt_parts.append(text)
                # v16.5.75.3 : skip extract_tables sur PDF scanné (gain ~30-50% sur batch FDE)
                if is_native_pdf:
                    try:
                        tables = page.extract_tables() or []
                        for t in tables[:3]:
                            for row in t[:30]:
                                txt_parts.append("\t".join([("" if x is None else str(x)) for x in row]))
                    except Exception:
                        pass
                txt_parts.append("")
        if _unread40:
            txt_parts.insert(0, f"[unreadable pages / pages illisibles: {_unread40}/{_read40} — "
                                "non-standard font encoding, OCR required / encodage de police non standard, OCR requis]")
        return "\n".join(txt_parts).strip()

    # Unknown/binary: return empty to avoid garbage
    return ""

# ════════════════════════════════════════════════════════════════════════════
# v16.5.75.3 — Détection PDF natif vs scanné (Sprint #2)
# ════════════════════════════════════════════════════════════════════════════
#
# Brief Robin : sur dossiers riches en PDFs, le parsing perd du temps à
# extraire les tables (page.extract_tables()) sur des PDFs scannés où il
# n'y a aucune couche texte → 0 caractère récupéré, mais coût en temps
# significatif. Pareil dans financial_statement_extractor.py : un scan
# 400 pages sur PDF scanné = pure perte (pas d'OCR dans CoDIR-IA actuel).
#
# Solution : check rapide en 1ère page (et 2-3 pages échantillonnées si
# > 5 pages) du ratio caractères extractibles / surface page. Seuil
# empirique : < 50 caractères par page → probablement scanné.
#
# Usage :
#   - utils/attachments.py : skip extract_tables() si scanné
#   - utils/financial_statement_extractor.py : skip deep scan + bundle vide
#     avec note "PDF scanné — OCR requis (non disponible dans CoDIR-IA v16.5.75.3)"
#
# Coût : 1 ouverture pdfplumber sur 1-3 pages = ~50-200ms (vs ~500ms-2s
# pour extract_tables sur 50 pages). Largement rentable dès qu'un PDF
# scanné est présent dans le batch.
# ════════════════════════════════════════════════════════════════════════════

# Seuil empirique : un PDF natif a typiquement >> 200 chars par page
# (rapport annuel : 1500-3000). Un PDF scanné sans OCR : 0-30 chars
# (juste artefacts d'index). Marge de sécurité confortable à 50.
# Seuil sur la page la PLUS riche de l'échantillon (logique : un PDF scanné
# est uniformément vide ; un PDF natif a au moins quelques pages bien fournies).
# Calibré pour distinguer :
#   - PDF scanné sans OCR : 0-10 chars/page (juste numéros)
#   - PDF scanné avec OCR catastrophique : 5-40 chars/page
#   - PDF natif : ≥ 80 chars/page minimum dès qu'il y a du contenu réel
# Seuil 50 = robuste sans faux positifs sur OCR partiel exploitable.
_PDF_NATIVE_MAX_CHARS_THRESHOLD = 50

# Échantillonnage dense pour couvrir les rapports annuels longs (FS dispersées)
# sans cramer les perfs (8-15 ouvertures de page = ~50-300ms).
_PDF_NATIVE_SAMPLES_SHORT = 8     # PDFs ≤ 50 pages
_PDF_NATIVE_SAMPLES_LONG = 15     # PDFs > 50 pages

# Cache : un même PDF (par hash) n'est checké qu'une fois.
_PDF_NATIVE_CACHE: Dict[str, bool] = {}
_PDF_NATIVE_CACHE_MAX = 200


def pdf_quick_native_check(data: bytes) -> bool:
    """
    Vérifie en 5-12 pages échantillonnées si un PDF semble natif ou scanné.

    Stratégie :
      - ≤ 50 pages → 5 échantillons répartis sur tout le doc
      - > 50 pages → 12 échantillons (couvre mieux les rapports annuels longs
        avec FS en fin de doc — cas dossier anglophone coté, FDE...)
      - Décision : MAX(chars) sur l'échantillon ≥ 100 → natif
        (logique : un PDF scanné est uniformément vide partout ; un PDF natif
        a au moins UNE page bien fournie sur l'échantillon)

    Returns:
        True si PDF natif (au moins une page riche détectée).
        True par défaut en cas d'erreur (fail-open : on tente le parsing).
        False si PDF scanné (toutes pages échantillonnées vides ou quasi).

    Performance : ~50-300ms typique selon la taille. Largement rentable dès
    qu'un PDF scanné est présent dans un batch (économie 5-30s sur le scan
    profond inutile).
    """
    # Cache hit
    h = hashlib.md5(data).hexdigest()
    cached = _PDF_NATIVE_CACHE.get(h)
    if cached is not None:
        return cached

    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            n_pages = len(pdf.pages)
            if n_pages == 0:
                _PDF_NATIVE_CACHE[h] = True  # PDF vide → fail-open
                return True

            # Échantillonnage adaptatif : positions équiréparties sur tout le doc.
            # Inclut TOUJOURS la 1ère et la dernière page (les FS d'un rapport
            # annuel sont typiquement en fin de doc).
            n_samples = _PDF_NATIVE_SAMPLES_SHORT if n_pages <= 50 else _PDF_NATIVE_SAMPLES_LONG
            n_samples = min(n_samples, n_pages)
            if n_samples == 1:
                indices = [0]
            else:
                indices = sorted(set(
                    int(i * (n_pages - 1) / (n_samples - 1)) for i in range(n_samples)
                ))

            max_chars = 0
            pages_checked = 0
            for idx in indices:
                if idx >= n_pages:
                    continue
                try:
                    text = pdf.pages[idx].extract_text() or ""
                    chars = len(text.strip())
                    if chars > max_chars:
                        max_chars = chars
                    pages_checked += 1
                    # Optim : si on a déjà trouvé une page riche, inutile de continuer
                    if max_chars >= _PDF_NATIVE_MAX_CHARS_THRESHOLD:
                        break
                except Exception:
                    # Page corrompue : on continue avec les autres
                    continue

            if pages_checked == 0:
                _PDF_NATIVE_CACHE[h] = True  # fail-open
                return True

            is_native = max_chars >= _PDF_NATIVE_MAX_CHARS_THRESHOLD

    except Exception:
        # Erreur d'ouverture du PDF : fail-open (on laisse le parsing principal essayer)
        _PDF_NATIVE_CACHE[h] = True
        return True

    # Eviction LRU simple (FIFO en pratique car pas de tracking timestamp ici)
    if len(_PDF_NATIVE_CACHE) >= _PDF_NATIVE_CACHE_MAX:
        # Supprime le 1er élément inséré (Python 3.7+ ordered dict)
        first_key = next(iter(_PDF_NATIVE_CACHE))
        del _PDF_NATIVE_CACHE[first_key]

    _PDF_NATIVE_CACHE[h] = is_native
    return is_native


def reset_pdf_native_cache() -> None:
    """Vide le cache de détection PDF natif/scanné. Utile pour tests."""
    _PDF_NATIVE_CACHE.clear()


# ════════════════════════════════════════════════════════════════════════════
# v16.5.75.3 — Parallélisation threads (Sprint #1)
# ════════════════════════════════════════════════════════════════════════════
#
# Brief Robin : sur 20 PJ (cas FDE), le parsing séquentiel prend 60s.
# Cible : ~15s avec parallélisation x4 sur Mac M4 (multi-core).
#
# Choix technique : ThreadPoolExecutor (vs ProcessPoolExecutor).
#   - pdfplumber + openpyxl libèrent le GIL pendant les calculs C natifs
#     et l'I/O → threading offre un gain réel (×3-5 typique).
#   - ProcessPool serait théoriquement ×8 mais :
#     * pickling des bytes coûte sur fichiers volumineux,
#     * cache module-level _PARSE_CACHE inopérant cross-process,
#     * fork-safety incertaine sur certaines plateformes (Windows).
#   - ThreadPool est le compromis pragmatique fiable.
#
# Désactivable via CODIR_DISABLE_PARALLEL_PARSING=1 pour debug ou en cas
# de bug spécifique sur un environnement.
# ════════════════════════════════════════════════════════════════════════════

# Nombre par défaut de workers (capé pour ne pas saturer un Mac mini)
_DEFAULT_PARSE_WORKERS = min(8, (os.cpu_count() or 4))


def _is_parallel_parsing_disabled() -> bool:
    """Permet à un test ou à Robin de forcer le mode séquentiel (debug)."""
    return os.environ.get("CODIR_DISABLE_PARALLEL_PARSING", "").strip() not in ("", "0", "false", "False")


# ════════════════════════════════════════════════════════════════════════════
# v17.2-M.1 — Moteur de parsing MULTIPROCESS (priorité v17)
# ════════════════════════════════════════════════════════════════════════════
#
# Pourquoi multiprocess (et plus seulement threads) : l'analyse de mise en page
# pdfminer.six (sous pdfplumber) et le parsing openpyxl sont en GRANDE PARTIE du
# Python pur, donc bornés par le GIL — les threads plafonnent vite sur des PDF
# natifs lourds. Le multiprocess donne un vrai parallélisme CPU (cible : ×cœurs).
#
# Les 3 objections historiques au ProcessPool sont neutralisées ici :
#   1. Pickling des octets : on ne dispatche QUE les fichiers absents du cache,
#      et le coût de pickle reste faible devant le temps de parsing d'un PDF lourd.
#   2. Cache module-level inopérant cross-process : le PARENT pré-vérifie le cache
#      (les hits sont servis sans worker) PUIS re-peuple son cache avec les
#      résultats des workers → le bénéfice « 0s aux transitions Streamlit » est
#      conservé.
#   3. Fork-safety Windows : worker = fonction top-level d'un module LÉGER
#      (utils.attachments, sans import Streamlit/app) ; contexte « spawn » explicite
#      (uniforme Win/macOS) ; toute défaillance du pool → repli thread → séquentiel.
#
# Sélection du moteur : param `engine` > env CODIR_PARSE_ENGINE > défaut « thread ».
# Valeurs : « process », « thread », « sequential », « auto » (process si le nombre
# de fichiers à parser ≥ CODIR_PROCESS_MIN_FILES, sinon thread). Le défaut reste
# « thread » (comportement éprouvé, zéro régression) ; le multiprocess est activé
# explicitement (env/param) ou via « auto », et app.py l'active sur les gros lots.
# ════════════════════════════════════════════════════════════════════════════

_PROCESS_AUTO_MIN = max(2, int(os.environ.get("CODIR_PROCESS_MIN_FILES", "6") or "6"))


def _resolve_parse_engine(requested: Optional[str], n_to_parse: int) -> str:
    """Renvoie « process », « thread » ou « sequential »."""
    if _is_parallel_parsing_disabled() or n_to_parse <= 1:
        return "sequential"
    eng = (requested or os.environ.get("CODIR_PARSE_ENGINE", "") or "thread").strip().lower()
    if eng == "auto":
        return "process" if n_to_parse >= _PROCESS_AUTO_MIN else "thread"
    if eng in ("process", "thread", "sequential"):
        return eng
    return "thread"


def _run_parse_pool(executor_factory, to_parse: List[Tuple[int, Tuple[str, str, bytes]]],
                    n_total: int, done_offset: int,
                    progress_cb: Optional[Callable[[int, int, str], None]]
                    ) -> Dict[int, "AttachmentText"]:
    """Exécute le parsing des `to_parse` via l'executor fourni (Thread ou Process).
    Isolation par fichier (un plantage fichier ne casse pas le lot), ordre restauré
    par l'appelant via les index. Une défaillance du POOL lui-même
    (BrokenProcessPool — ex. worker incapable de démarrer) est PROPAGÉE pour
    déclencher le repli amont (process→thread→séquentiel)."""
    from concurrent.futures.process import BrokenProcessPool
    results: Dict[int, AttachmentText] = {}
    done = done_offset
    with executor_factory() as ex:
        futures = {ex.submit(_parse_one_upload, item): (idx, item[0]) for idx, item in to_parse}
        for fut in as_completed(futures):
            idx, fname = futures[fut]
            try:
                results[idx] = fut.result()
            except BrokenProcessPool:
                raise  # pool HS → repli moteur (géré par l'appelant)
            except Exception as e:
                results[idx] = AttachmentText(
                    filename=fname, mimetype="", size_bytes=0,
                    text=f"[ERREUR PARSING : {type(e).__name__}: {str(e)[:200]}]")
            done += 1
            if progress_cb is not None:
                try:
                    progress_cb(done, n_total, fname)
                except Exception:
                    pass
    return results


def _parse_one_upload(item: Tuple[str, str, bytes]) -> "AttachmentText":
    """Wrapper picklable pour un seul upload — utilisé par le ThreadPool."""
    filename, mimetype, data = item
    text = extract_text_from_upload(filename, mimetype or "", data)
    return AttachmentText(
        filename=filename,
        mimetype=mimetype or "",
        size_bytes=len(data),
        text=text,
    )


def prepare_attachments_parallel(
    uploads: List[Tuple[str, str, bytes]],
    max_files: int = 20,
    max_total_mb: int = 500,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    max_workers: Optional[int] = None,
    engine: Optional[str] = None,
) -> List["AttachmentText"]:
    """
    Parsing des PJ avec moteur sélectionnable (v17.2-M.1).

    Args:
        uploads          : liste des (filename, mimetype, data)
        max_files        : limite nombre fichiers (rétrocompat)
        max_total_mb     : limite taille totale (rétrocompat)
        progress_cb      : callback optionnel (done, total, current_filename)
        max_workers      : nombre de workers (défaut : min(8, cpu_count))
        engine           : « process » | « thread » | « sequential » | « auto » |
                           None (→ env CODIR_PARSE_ENGINE, défaut « thread »)

    Returns:
        Liste d'AttachmentText dans l'ORDRE D'ORIGINE.

    Robustesse : cache parent pré-vérifié (hits servis sans worker), repli
    process→thread→séquentiel sur défaillance du pool, isolation par fichier.
    """
    uploads = uploads[:max_files]
    max_total_bytes = int(max_total_mb * 1024 * 1024)
    # M.5.10.5 — ré-applique le silence ScriptRunContext APRÈS l'init Streamlit
    # (le logger « streamlit » et ses handlers existent désormais ; on y pose le
    # filtre). Le parsing // (threads par défaut) émet sinon le warning en boucle.
    if _sq is not None:
        try:
            _sq.silence_script_run_context()
        except Exception:
            pass

    # Filtrage budget total — on garde l'ordre d'origine
    accepted: List[Tuple[int, Tuple[str, str, bytes]]] = []
    total = 0
    for idx, (filename, mimetype, data) in enumerate(uploads):
        size = len(data)
        if total + size > max_total_bytes:
            break
        total += size
        accepted.append((idx, (filename, mimetype, data)))

    n_total = len(accepted)
    if n_total == 0:
        return []

    # 1) Pré-vérification du CACHE parent : les hits sont servis sans worker
    #    (rend le moteur process compatible avec le cache anti-reparse Streamlit).
    results: Dict[int, AttachmentText] = {}
    to_parse: List[Tuple[int, Tuple[str, str, bytes]]] = []
    done = 0
    for idx, (fn, mt, data) in accepted:
        cached = _cache_get(_content_hash(data))
        if cached is not None:
            results[idx] = AttachmentText(filename=fn, mimetype=mt or "",
                                          size_bytes=len(data), text=cached)
            done += 1
            if progress_cb is not None:
                try:
                    progress_cb(done, n_total, fn)
                except Exception:
                    pass
        else:
            to_parse.append((idx, (fn, mt, data)))

    n_to_parse = len(to_parse)
    chosen = _resolve_parse_engine(engine, n_to_parse)

    # 2) Mode séquentiel (1 fichier à parser, ou désactivé)
    if chosen == "sequential":
        for idx, item in to_parse:
            results[idx] = _parse_one_upload(item)
            done += 1
            if progress_cb is not None:
                try:
                    progress_cb(done, n_total, item[0])
                except Exception:
                    pass
    elif n_to_parse > 0:
        n_workers = max_workers or min(_DEFAULT_PARSE_WORKERS, n_to_parse)
        parsed: Optional[Dict[int, AttachmentText]] = None
        if chosen == "process":
            try:
                ctx = _mp.get_context("spawn")
                _pp_init = (_sq.worker_init if _sq is not None else None)
                parsed = _run_parse_pool(
                    lambda: ProcessPoolExecutor(max_workers=n_workers, mp_context=ctx,
                                                initializer=_pp_init),
                    to_parse, n_total, done, progress_cb)
            except Exception:
                parsed = None  # pool process indisponible → repli thread
        if parsed is None:
            try:
                parsed = _run_parse_pool(
                    lambda: ThreadPoolExecutor(max_workers=n_workers),
                    to_parse, n_total, done, progress_cb)
            except Exception:
                # ultime repli : séquentiel (ne jamais casser le parsing)
                parsed = {}
                d = done
                for idx, item in to_parse:
                    parsed[idx] = _parse_one_upload(item)
                    d += 1
                    if progress_cb is not None:
                        try:
                            progress_cb(d, n_total, item[0])
                        except Exception:
                            pass
        results.update(parsed)

    # 3) Re-peuplement du cache parent (bénéfice anti-reparse conservé en process)
    for idx, (fn, mt, data) in to_parse:
        r = results.get(idx)
        if r is not None and r.text and not r.text.startswith("[ERREUR PARSING"):
            _cache_set(_content_hash(data), r.text)

    # 4) Restaure l'ordre d'origine
    return [results[idx] for idx, _ in accepted if idx in results]


def prepare_attachments(
    uploads: List[Tuple[str, str, bytes]],
    max_files: int = 20,
    max_total_mb: int = 500,
) -> List[AttachmentText]:
    uploads = uploads[:max_files]
    max_total_bytes = int(max_total_mb * 1024 * 1024)
    total = 0
    out: List[AttachmentText] = []
    for filename, mimetype, data in uploads:
        size = len(data)
        if total + size > max_total_bytes:
            break
        total += size
        text = extract_text_from_upload(filename, mimetype or "", data)
        out.append(AttachmentText(filename=filename, mimetype=mimetype or "", size_bytes=size, text=text))
    return out

def build_attachments_block(items: List[AttachmentText], token_budget: int = 24000) -> Tuple[str, dict]:
    """
    Assemble le bloc de pièces jointes pour injection dans les prompts.

    v16.5.60 — Priorisation & budget élargi :
      - Budget par défaut porté à 24 000 tokens (vs 8 000 avant).
      - Les "notes de synthèse" courtes (Capeos, K-bis, CR, memos)
        sont placées EN TÊTE et servies sans troncature. C'est elles
        qui contiennent le plus haut ratio signal/bruit (ex. mention
        explicite d'un CCA débiteur, d'un cautionnement, d'une clause).
      - Les liasses fiscales et autres PDF longs sont ensuite servis,
        avec troncature head+tail si le budget restant l'exige.
      - La troncature par fichier n'agit plus que sur les fichiers
        "longs" — les synthèses restent intègres.

    Retourne (text_block, stats).
    """
    if not items:
        return "", {"files": 0, "tokens_est": 0, "truncated": False}

    # ── B.1.3.20 (P1-G, runs dossier industriel + dossier agroalimentaire) — PIÈCES NON EXPLOITABLES.
    # Racine : 3 des 4 millésimes de comptes dossier industriel étaient des scans sans
    # OCR (couche structurée vide, fs_hash du vide) ; l'agent devait le
    # DEVINER. Statut déterministe : « fournie » ≠ « exploitable ». La ligne
    # est injectée EN TÊTE du bloc (les agents l'énoncent au lieu de
    # l'inférer) et les stats l'exposent pour le diagnostic CSV.
    _extract_stats = classify_extractability(items)
    _unex_header = ""
    if _extract_stats["n_unextractable"] > 0:
        _names = ", ".join(_extract_stats["unextractable_names"][:4])
        _unex_header = (
            f"⚠ PIÈCES FOURNIES MAIS NON EXPLOITABLES PAR EXTRACTION TEXTE "
            f"(scan sans OCR probable) : "
            f"{_extract_stats['n_unextractable']}/{_extract_stats['n_files']}"
            f" — {_names}. Leur contenu n'a pas pu être lu : ne produire "
            f"AUCUN chiffre en leur nom (pas de compensation par un fait "
            f"non sourcé).\n\n")

    # ── Étape 1 : partitionner synthèses / autres ───────────────────────────
    synth: list[AttachmentText] = []
    other: list[AttachmentText] = []
    for a in items:
        if _is_likely_synthesis(a.filename, a.size_bytes):
            synth.append(a)
        else:
            other.append(a)

    # Les synthèses passent d'abord, avec tri par taille croissante (la plus
    # courte d'abord = la plus dense en signal).
    synth.sort(key=lambda a: a.size_bytes)
    # v62.13.9.4.39 — LES ÉTATS FINANCIERS PASSENT AVANT LES AUTRES PIÈCES. Sur un dossier
    # réel du 20/09/2026 (neuf pièces, budget de 8 000 tokens), les liasses étaient coupées
    # avant leur bilan : zéro fait de bilan extrait, les stocks — problème n°1 du dossier —
    # invisibles pour tous les agents. Une pièce dont le texte porte des rubriques de bilan
    # ou de compte de résultat est servie d'abord ; les pièces de texte (actes, rapports,
    # présentations) viennent ensuite. Le budget lui-même passe à 50 000 par défaut.
    _fin_rx = re.compile(r"(?i)\b(?:bilan|balance\s+sheet|compte\s+de\s+r[ée]sultat|income\s+statement|"
                         r"profit\s+and\s+loss|total\s+(?:actif|passif|assets|liabilities)|stocks?\s+et\s+en[- ]cours|"
                         r"inventories|cr[ée]ances\s+clients|trade\s+receivables|dettes\s+fournisseurs|trade\s+payables|"
                         r"capitaux\s+propres|shareholders'?\s+equity|liasse|2050|2051|2052|2053)\b")
    _financial = [a for a in other if _fin_rx.search(str(getattr(a, "text", "") or "")[:200000])]
    _rest = [a for a in other if a not in _financial]
    ordered = synth + _financial + _rest

    blocks: list[str] = []
    total_tokens = 0
    truncated = False
    synth_tokens_consumed = 0
    SYNTH_PROTECTED_BUDGET = int(token_budget * 0.40)  # 40% du budget réservé

    for idx, a in enumerate(ordered):
        t = a.text or ""
        tok = _estimate_tokens(t)
        is_synth = a in synth
        tag = " [SYNTHÈSE]" if is_synth else ""

        # Synthèses : on les sert intégralement tant qu'on ne dépasse pas
        # le budget protégé (40% du total). Si l'une déborde, on tronque
        # celle-là mais pas la suivante.
        if is_synth:
            if synth_tokens_consumed + tok <= SYNTH_PROTECTED_BUDGET:
                synth_tokens_consumed += tok
                total_tokens += tok
                blocks.append(
                    f"### Fichier: {a.filename}{tag}\n"
                    f"Type: {a.mimetype or 'n/a'} | Taille: {a.size_bytes} octets\n---\n{t}\n"
                )
                continue
            # Synthèse qui excède son budget protégé : on la tronque mais
            # on garde head + tail généreux (2/3 head, 1/3 tail).
            remaining = max(1500, SYNTH_PROTECTED_BUDGET - synth_tokens_consumed)
            head_chars = int(remaining * 4 * 0.67)
            tail_chars = int(remaining * 4 * 0.33)
            t_trunc = t[:head_chars] + "\n\n[...]\n\n" + (t[-tail_chars:] if len(t) > head_chars + tail_chars else "")
            tok_trunc = _estimate_tokens(t_trunc)
            synth_tokens_consumed += tok_trunc
            total_tokens += tok_trunc
            truncated = True
            blocks.append(
                f"### Fichier: {a.filename}{tag}\n"
                f"Type: {a.mimetype or 'n/a'} | Taille: {a.size_bytes} octets\n---\n{t_trunc}\n"
            )
            continue

        # Fichiers "longs" : on partage le budget restant équitablement.
        remaining_budget = token_budget - total_tokens
        if remaining_budget <= 500:
            truncated = True
            blocks.append(
                f"### Fichier: {a.filename}\n"
                f"Type: {a.mimetype or 'n/a'} | Taille: {a.size_bytes} octets\n---\n"
                f"[Fichier non chargé — budget tokens épuisé]\n"
            )
            continue

        remaining_files = len(ordered) - idx
        per_file_budget = max(1000, remaining_budget // max(1, remaining_files))
        if tok <= per_file_budget:
            total_tokens += tok
            blocks.append(
                f"### Fichier: {a.filename}{tag}\n"
                f"Type: {a.mimetype or 'n/a'} | Taille: {a.size_bytes} octets\n---\n{t}\n"
            )
        else:
            # Troncature head + tail
            truncated = True
            head_chars = int(per_file_budget * 4 * 0.60)
            tail_chars = int(per_file_budget * 4 * 0.40)
            t_trunc = t[:head_chars] + "\n\n[...]\n\n" + (t[-tail_chars:] if len(t) > head_chars + tail_chars else "")
            tok_trunc = _estimate_tokens(t_trunc)
            total_tokens += tok_trunc
            blocks.append(
                f"### Fichier: {a.filename}{tag}\n"
                f"Type: {a.mimetype or 'n/a'} | Taille: {a.size_bytes} octets\n---\n{t_trunc}\n"
            )

    joined = "\n\n".join(blocks).strip()
    joined_tokens = _estimate_tokens(joined)
    # Garde-fou ultime
    if joined_tokens > token_budget * 1.2:
        truncated = True
        joined = joined[: int(token_budget * 1.2) * 4].rstrip() + "\n\n[...] (troncature globale)\n"
        joined_tokens = _estimate_tokens(joined)

    # B.1.3.20 (P1-G) — la ligne d'exploitabilité N'EST PAS troncable :
    # ajoutée après le garde-fou, en tête du bloc.
    if _unex_header:
        joined = _unex_header + joined
        joined_tokens = _estimate_tokens(joined)

    return joined, {
        "files": len(items),
        "synth_files": len(synth),
        "tokens_est": joined_tokens,
        "truncated": truncated,
        # v16.5.67.10 — liste explicite des noms de fichiers pour
        # briefcheck, Finance attachments hint, etc.
        "filenames": [a.filename for a in items],
        # B.1.3.20 (P1-G) — exploitabilité par extraction texte
        "n_unextractable": _extract_stats["n_unextractable"],
        "unextractable_names": _extract_stats["unextractable_names"],
        # 9.4.57 — contre-recette ChatGPT du 10/10 (§5.4) : l'effectif (« our 714 employees », 10-K p.5) était lu sur le bloc
        # TRONQUÉ des pièces (≈ 50 000 jetons pour 14 PDF) ; la page qui le porte n'y entrait pas. Il est lu sur le texte
        # COMPLET de chaque pièce, avant la troncature.
        "headcount57": _headcount_full57(items),
    }


def _headcount_full57(items) -> str:
    """Effectif lu sur le texte complet de chaque pièce. 9.4.59 — recette 9.4.58 : « 644 employees » (10-K et rapport
    FY2024) l'emportait par sa fréquence sur « 714 employees » (10-K FY2025). La valeur retenue est celle du document
    le plus RÉCENT (année la plus haute dans son nom ou dans son en-tête d'exercice) ; à égalité, la plus fréquente."""
    try:
        import re as _re59
        from utils.fiscal_year_end50 import detect_headcount as _dh
        from collections import Counter
        found = []
        for a in (items or []):
            txt = getattr(a, "text", "") or ""
            h = _dh(txt)
            if not h:
                continue
            name = str(getattr(a, "filename", "") or getattr(a, "name", "") or "")
            # « FY2024 », « 2025 » isolé, ou date « 20250831 » (aaaammjj) des dépôts SEC
            years = [int(y) for y in _re59.findall(r"(?<!\d)(20[0-4]\d)(?=[01]\d[0-3]\d(?!\d)|(?!\d))", name)]
            years += [int(y) for y in _re59.findall(r"(?i)fiscal\s+(?:year\s+)?(?:ended\s+\w+\s+\d{1,2},\s+)?(20[0-4]\d)|\bFY\s?(20[0-4]\d)", txt[:30000])
                      for y in ((y,) if isinstance(y, str) else y) if y]
            found.append((max(years) if years else 0, h))
        if not found:
            return ""
        top = max(y for y, _ in found)
        recent = [h for y, h in found if y == top]
        c = Counter(recent)
        best = max(c.values())
        return next(h for h in recent if c[h] == best)
    except Exception:
        return ""
        c = Counter(found)
        best = max(c.values())
        return next(h for h in found if c[h] == best)
    except Exception:
        return ""


def classify_extractability(items: List[AttachmentText],
                            min_chars: int = 200,
                            min_bytes: int = 20_000) -> dict:
    """B.1.3.20 (P1-G) — pièce FOURNIE vs pièce EXPLOITABLE par extraction.

    Heuristique déterministe : un fichier « lourd » (>= min_bytes) dont le
    texte extrait est quasi vide (< min_chars) est très probablement un scan
    sans OCR (cas réel : comptes dossier industriel 2020/2023/2024). Les petits fichiers
    quasi vides ne sont pas classés scan (pièce réellement vide/mineure).
    """
    n_unex = 0
    names: list[str] = []
    for a in items or []:
        try:
            _len = len((a.text or "").strip())
            # v62.13.9.4.40 — plus de la moitié des pages lues illisibles : pièce non exploitable
            _ur40 = _UNREADABLE_FILE40_RE.search((a.text or "")[:400])
            if _ur40 and int(_ur40.group(2) or 0) and int(_ur40.group(1)) * 2 > int(_ur40.group(2)):
                n_unex += 1
                names.append(a.filename)
                continue
            if _len < min_chars and int(a.size_bytes or 0) >= min_bytes:
                n_unex += 1
                names.append(a.filename)
        except Exception:
            continue
    return {"n_files": len(items or []), "n_unextractable": n_unex,
            "unextractable_names": names}
