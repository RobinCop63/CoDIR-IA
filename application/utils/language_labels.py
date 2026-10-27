"""utils/language_labels.py — v17.4.3.1-M6B-B1.3.1 : libellés de langue PURS.

Extrait de brief_ui._loc_lang_value (audit B.1.3, point hygiène) :
verify_installation lance pytest patches/tests/ en sous-processus, et le
test B.1.3 importait brief_ui → streamlit → 42/43 dans un environnement nu.
Un self-check doit rester hermétique : ce module n'importe RIEN du projet
ni streamlit.

Contrat B.1.3 (requalifié avec Robin, run dossier anglophone coté) : l'écho « Langue : … »
du brief reflète LE CHOIX RÉEL du sélecteur (celui qui pilote le run via
active_output_language), pas la langue d'affichage de l'app.

Historique : M.5.10.4 écrasait le label stocké par `lang` (langue UI) —
ce qui corrigeait un écho périmé mais créait le mensonge inverse :
sélecteur écran = « English », écho = « Langue : Français » → l'auditeur
a conclu à tort à une régression UI-1. Désormais : stored fait foi
(c'est lui la source du run) ; `lang` ne sert que de repli si vide.
"""
from __future__ import annotations


def loc_lang_value(stored: str, lang: str) -> str:
    sv = str(stored or "").strip().lower()
    if "biling" in sv:
        return "Bilingual FR / EN" if (lang or "fr").lower() == "en" else "Bilingue FR / EN"
    if sv.startswith("engl") or sv == "en":
        return "English"
    if sv.startswith("fran") or sv == "fr":
        return "Français"
    return "English" if (lang or "fr").lower() == "en" else "Français"
