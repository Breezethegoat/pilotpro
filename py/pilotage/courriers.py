"""Modèles de mail (Jinja2) et construction des contextes de rendu."""
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote

from jinja2 import Environment, StrictUndefined, TemplateSyntaxError

from pilotage.regles import Destinataire

MODELES = ("responsable", "recap")
DEFAUT = Path(__file__).parent / "modeles_defaut"

VARIABLES = {
    "responsable": ["prenom", "nom", "date", "actions", "nb_retard", "nb_proches", "nb_nouvelles", "risques", "questions",
                    "lien_classeur", "max_retard", "escalade"],
    "recap": ["date", "stats", "evolutions", "anomalies", "questions_sans_responsable", "modifs_plan", "nb_mails"],
}


@dataclass
class Courrier:
    destinataire: str
    objet: str
    html: str
    cc: str = ""  # adresse en copie (escalade vers le fondateur)


def _date_fr(d) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def _pourcent(v) -> str:
    return "—" if v is None else f"{round(v * 100)} %"


def _env(autoescape: bool) -> Environment:
    env = Environment(autoescape=autoescape, undefined=StrictUndefined)
    env.filters["date_fr"] = _date_fr
    env.filters["pourcent"] = _pourcent
    return env


_ENV_CORPS = _env(True)
_ENV_OBJET = _env(False)


def _fichiers(nom: str) -> tuple[str, str]:
    if nom not in MODELES:
        raise ValueError(f"Modèle inconnu : {nom}")
    return f"{nom}.objet.txt", f"{nom}.html"


def _une_ligne(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


class Moteur:
    def __init__(self, dossier_perso: Path):
        self.perso = Path(dossier_perso)

    def source(self, nom: str) -> tuple[str, str]:
        res = []
        for f in _fichiers(nom):
            p = self.perso / f
            if not p.exists():
                p = DEFAUT / f
            res.append(p.read_text(encoding="utf-8"))
        return res[0], res[1]

    def valider(self, objet: str, corps: str) -> str | None:
        try:
            _ENV_OBJET.parse(objet)
            _ENV_CORPS.parse(corps)
        except TemplateSyntaxError as e:
            return f"ligne {e.lineno} : {e.message}"
        return None

    def enregistrer(self, nom: str, objet: str, corps: str) -> None:
        f_objet, f_corps = _fichiers(nom)
        erreur = self.valider(objet, corps)
        if erreur:
            raise ValueError(erreur)
        self.perso.mkdir(parents=True, exist_ok=True)
        (self.perso / f_objet).write_text(objet, encoding="utf-8")
        (self.perso / f_corps).write_text(corps, encoding="utf-8")

    def retablir(self, nom: str) -> None:
        for f in _fichiers(nom):
            (self.perso / f).unlink(missing_ok=True)

    def rendre(self, nom: str, contexte: dict, objet: str | None = None,
               corps: str | None = None) -> tuple[str, str]:
        src_objet, src_corps = self.source(nom)
        objet = src_objet if objet is None else objet
        corps = src_corps if corps is None else corps
        return (_une_ligne(_ENV_OBJET.from_string(objet).render(contexte)),
                _ENV_CORPS.from_string(corps).render(contexte))


def _etiquette(q) -> str:
    return "En retard" if q.en_retard else "Proche" if q.proche else "Nouvelle" if q.nouvelle else ""


def lien_cellule(lien_classeur: str, onglet: str, cellule: str) -> str:
    """Lien qui ouvre le classeur en ligne sur une cellule précise (ou "" sans lien de classeur)."""
    if not lien_classeur:
        return ""
    cible = quote(f"'{onglet}'!{cellule}", safe="")
    return f"{lien_classeur}{'&' if '?' in lien_classeur else '?'}activeCell={cible}"


def jours_de_retard(q, jour: date) -> int:
    return (jour - q.action.echeance).days if q.en_retard and q.action.echeance else 0


def niveau_escalade(dest: Destinataire, jour: date, seuil_copie: int, seuil_ferme: int) -> tuple[str, int]:
    """("", "copie" ou "ferme", plus grand retard en jours) pour un destinataire."""
    pire = max((jours_de_retard(q, jour) for q in dest.actions), default=0)
    if seuil_ferme > 0 and pire >= seuil_ferme:
        return "ferme", pire
    if seuil_copie > 0 and pire >= seuil_copie:
        return "copie", pire
    return "", pire


def contexte_responsable(dest: Destinataire, jour: date, lien_classeur: str = "",
                         escalade: str = "") -> dict:
    nom = dest.personne.nom.strip()
    # Conseils : nom complet (« Cabinet X ») ; fondateurs : l'Annuaire ne contient que des prénoms.
    prenom = nom if dest.personne.groupe == "conseil" or not nom else nom.split()[0]
    return {
        "prenom": prenom,
        "nom": nom,
        "date": _date_fr(jour),
        "actions": [{"num": q.action.num, "libelle": q.action.libelle,
                     "echeance": _date_fr(q.action.echeance), "statut": q.action.statut,
                     "etiquette": _etiquette(q), "jours_retard": jours_de_retard(q, jour),
                     "lien": lien_cellule(lien_classeur, "Actions", f"A{q.action.ligne}")}
                    for q in dest.actions],
        "lien_classeur": lien_classeur,
        "max_retard": max((jours_de_retard(q, jour) for q in dest.actions), default=0),
        "escalade": escalade,
        "nb_retard": sum(q.en_retard for q in dest.actions),
        "nb_proches": sum(q.proche for q in dest.actions),
        "nb_nouvelles": sum(q.nouvelle for q in dest.actions),
        "risques": [{"num": r.num, "intitule": r.intitule, "niveau": r.niveau,
                     "echeance": _date_fr(r.echeance)} for r in dest.risques],
        "questions": [{"num": q.num, "intitule": q.intitule,
                       "echeance": _date_fr(q.echeance)} for q in dest.questions],
    }


def message_whatsapp(dest: Destinataire, jour: date) -> str:
    """Rappel court, en texte simple, pour WhatsApp."""
    c = contexte_responsable(dest, jour)
    lignes = [f"Bonjour {c['prenom']}, voici ton point PilotPro du {c['date']} :"]
    retard = [a for a in c["actions"] if a["etiquette"] == "En retard"]
    proches = [a for a in c["actions"] if a["etiquette"] == "Proche"]
    if retard:
        lignes.append(f"*{len(retard)} action(s) en retard*")
        lignes += [f"- {a['num']} {a['libelle']} (prévue le {a['echeance']})" for a in retard]
    if proches:
        lignes.append(f"*{len(proches)} action(s) à échéance proche*")
        lignes += [f"- {a['num']} {a['libelle']} (pour le {a['echeance']})" for a in proches]
    autres = len(c["actions"]) - len(retard) - len(proches)
    if autres:
        lignes.append(f"{autres} autre(s) action(s) ouverte(s).")
    if c["risques"]:
        lignes.append(f"{len(c['risques'])} risque(s) à suivre.")
    if c["questions"]:
        lignes.append(f"{len(c['questions'])} question(s) ouverte(s) à trancher.")
    lignes.append("Le détail est dans ton mail. Merci de mettre le classeur à jour.")
    return "\n".join(lignes)


def contexte_recap(stats, evolutions, anomalies, questions_sans_resp, modifs_plan,
                   destinataires, jour: date) -> dict:
    return {
        "date": _date_fr(jour),
        "stats": asdict(stats),
        "evolutions": [asdict(e) for e in evolutions],
        "anomalies": [{"type": a.type, "message": a.message} for a in anomalies],
        "questions_sans_responsable": [{"num": q.num, "intitule": q.intitule}
                                       for q in questions_sans_resp],
        "modifs_plan": [{"num": m.tache.num, "libelle": m.tache.libelle,
                         "avancement": m.avancement, "statut": m.statut,
                         "date_realisation": _date_fr(m.date_realisation)} for m in modifs_plan],
        "nb_mails": len(destinataires),
    }
