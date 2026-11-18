"""Règles métier de PilotPro : logique pure, sans réseau ni fichier."""
import re
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Literal

from pilotage.modeles import Action, Anomalie, Personne, Question, Risque, Tache
from pilotage.textes import email_valide, normaliser

_FERMEES = ("Réalisée", "Annulée")


def _uniques(noms: list[str]) -> list[str]:
    vus: set[str] = set()
    res = []
    for n in noms:
        k = normaliser(n)
        if k not in vus:
            vus.add(k)
            res.append(n)
    return res


def est_ouverte(a: Action) -> bool:
    return a.statut not in _FERMEES


def actions_uniques(actions: list[Action]) -> list[Action]:
    """Une seule ligne par N° : la PREMIÈRE ligne gagne, les doublons sont ignorés.

    Sert au qualificatif, aux évolutions, à l'instantané et au calcul du plan : un N° en double
    ne doit pas fausser les pourcentages. Le doublon est signalé par `anomalies_actions`.
    """
    vus: set[str] = set()
    res = []
    for a in actions:
        if a.num in vus:
            continue
        vus.add(a.num)
        res.append(a)
    return res


def anomalies_actions(actions: list[Action]) -> list[Anomalie]:
    lignes: dict[str, list[int]] = {}
    for a in actions:
        lignes.setdefault(a.num, []).append(a.ligne)
    return [Anomalie("action", f"{num} : N° en double (lignes {', '.join(str(n) for n in ls)})")
            for num, ls in lignes.items() if len(ls) > 1]


@dataclass
class ActionQualifiee:
    action: Action
    nouvelle: bool
    proche: bool
    en_retard: bool

    @property
    def signalee(self) -> bool:
        return self.nouvelle or self.proche or self.en_retard


def qualifier(actions: list[Action], instantane: dict | None, jour: date, seuil: int = 3) -> list[ActionQualifiee]:
    connues = None if instantane is None else set((instantane.get("actions") or {}).keys())
    resultat = []
    for a in actions:
        ouverte = est_ouverte(a)
        nouvelle = connues is not None and a.num not in connues
        proche = ouverte and a.echeance is not None and jour <= a.echeance <= jour + timedelta(days=seuil)
        retard = ouverte and a.echeance is not None and a.echeance < jour
        resultat.append(ActionQualifiee(a, nouvelle, proche, retard))
    return resultat


@dataclass
class Stats:
    total: int = 0
    ouvertes: int = 0
    a_attribuer: int = 0
    en_cours: int = 0
    bloquees: int = 0
    realisees: int = 0
    annulees: int = 0
    nouvelles: int = 0
    proches: int = 0
    en_retard: int = 0
    realisees_a_temps: int = 0
    realisees_en_retard: int = 0
    taux_realisation: float | None = None
    taux_delais: float | None = None
    par_responsable: dict[str, dict[str, int]] = field(default_factory=dict)


def statistiques(qualifiees: list[ActionQualifiee]) -> Stats:
    s = Stats(total=len(qualifiees))
    cles: dict[str, str] = {}
    for q in qualifiees:
        a = q.action
        s.nouvelles += q.nouvelle
        s.proches += q.proche
        s.en_retard += q.en_retard
        if a.statut == "À attribuer":
            s.a_attribuer += 1
        elif a.statut == "En cours":
            s.en_cours += 1
        elif a.statut == "Bloquée":
            s.bloquees += 1
        elif a.statut == "Annulée":
            s.annulees += 1
        elif a.statut == "Réalisée":
            s.realisees += 1
            if a.echeance is not None and a.date_realisation is not None:
                if a.date_realisation <= a.echeance:
                    s.realisees_a_temps += 1
                else:
                    s.realisees_en_retard += 1
        if est_ouverte(a):
            s.ouvertes += 1
            for nom in _uniques(a.responsables):
                cle = cles.setdefault(normaliser(nom), nom)
                d = s.par_responsable.setdefault(cle, {"ouvertes": 0, "en_retard": 0})
                d["ouvertes"] += 1
                d["en_retard"] += q.en_retard
    base = s.total - s.annulees
    if base > 0:
        s.taux_realisation = s.realisees / base
    mesurees = s.realisees_a_temps + s.realisees_en_retard
    if mesurees > 0:
        s.taux_delais = s.realisees_a_temps / mesurees
    return s


@dataclass
class Evolution:
    num: str
    type: Literal["realisee", "echeance", "responsable", "disparue"]
    avant: str
    apres: str


def _fmt_date(d: date | None) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def _fmt_iso(v) -> str:
    if not v:
        return ""
    try:
        return date.fromisoformat(v).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(v)


def evolutions(actions: list[Action], instantane: dict | None) -> list[Evolution]:
    if not instantane:
        return []
    avant = instantane.get("actions") or {}
    resultat: list[Evolution] = []
    presentes = set()
    for a in actions:
        presentes.add(a.num)
        p = avant.get(a.num)
        if not p:
            continue
        if "statut" in p and a.statut == "Réalisée" and p["statut"] != "Réalisée":
            resultat.append(Evolution(a.num, "realisee", p["statut"] or "", a.statut))
        if "echeance" in p:
            if (p["echeance"] or None) != (a.echeance.isoformat() if a.echeance else None):
                resultat.append(Evolution(a.num, "echeance", _fmt_iso(p["echeance"]), _fmt_date(a.echeance)))
        if "responsables" in p:
            anciens = p["responsables"] or []
            if {normaliser(n) for n in anciens} != {normaliser(n) for n in a.responsables}:
                resultat.append(Evolution(a.num, "responsable", ", ".join(anciens), ", ".join(a.responsables)))
    for num, p in avant.items():
        if num not in presentes:
            resultat.append(Evolution(num, "disparue", (p or {}).get("statut") or "", ""))
    return resultat


@dataclass
class ModifTache:
    tache: Tache
    avancement: int
    statut: str
    date_realisation: date | None

    @property
    def change(self) -> bool:
        t = self.tache
        if self.avancement != round(t.avancement or 0):
            return True
        if self.statut != t.statut:
            return True
        return self.statut == "Réalisée" and self.date_realisation != t.date_realisation


def _calcul_tache(liees: list[Action]) -> tuple[int, str, date | None]:
    realisees = [a for a in liees if a.statut == "Réalisée"]
    avancement = round(100 * len(realisees) / len(liees))
    if len(realisees) == len(liees):
        dates = [a.date_realisation for a in realisees if a.date_realisation]
        return avancement, "Réalisée", max(dates) if dates else None
    if any(a.statut == "Bloquée" for a in liees):
        return avancement, "Bloquée", None
    if realisees or any(a.statut == "En cours" for a in liees):
        return avancement, "En cours", None
    return avancement, "À faire", None


def _tache_parente(code: str) -> str:
    """Code de la tâche du plan dont `code` est une sous-tâche : « P-18.1 » → « P-18 ».
    Un code sans suffixe « .n » est renvoyé tel quel."""
    return re.sub(r"(\.\d+)+$", "", code.strip())


def calculer_plan(taches: list[Tache], actions: list[Action]) -> tuple[list[ModifTache], list[Anomalie]]:
    par_num = {normaliser(t.num): t for t in taches}
    liens: dict[str, list[Action]] = {}
    anomalies: list[Anomalie] = []
    for a in actions:
        if not a.taches_plan:
            anomalies.append(Anomalie("plan", f"{a.num} : aucune tâche du plan"))
            continue
        rattachees: list[str] = []
        for code in _uniques(a.taches_plan):
            cle = normaliser(code)
            parente = _tache_parente(code)
            if cle in par_num:
                rattachees.append(cle)
            elif parente != code and normaliser(parente) in par_num:
                rattachees.append(normaliser(parente))
            elif parente != code:
                anomalies.append(Anomalie(
                    "plan", f"{a.num} : tâche « {parente} » inconnue (sous-tâche {code})"))
            else:
                anomalies.append(Anomalie("plan", f"{a.num} : tâche « {code} » inconnue"))
        # Une action liée à plusieurs sous-tâches d'une même tâche ne compte qu'une fois pour elle.
        for cle in dict.fromkeys(rattachees):
            liens.setdefault(cle, []).append(a)
    modifs: list[ModifTache] = []
    for t in taches:
        liees = [a for a in liens.get(normaliser(t.num), []) if a.statut != "Annulée"]
        if not liees:
            continue
        avancement, statut, date_real = _calcul_tache(liees)
        if t.statut in ("Réalisée", "Annulée"):
            if statut != t.statut:
                anomalies.append(Anomalie(
                    "plan", f"{t.num} est « {t.statut} » mais ses actions donnent « {statut} » : non modifiée"))
            continue
        m = ModifTache(t, avancement, statut, date_real)
        if m.change:
            modifs.append(m)
    return modifs, anomalies


def risques_a_rappeler(risques: list[Risque], jour: date, seuil: int = 3) -> list[Risque]:
    limite = jour + timedelta(days=seuil)
    resultat = []
    for r in risques:
        if r.statut == "Clos" or r.avancement in ("Réalisé", "Abandonné"):
            continue
        if r.niveau == "Critique" or (r.echeance is not None and r.echeance <= limite):
            resultat.append(r)
    return resultat


def anomalies_risques(risques: list[Risque]) -> list[Anomalie]:
    anomalies = []
    for r in risques:
        if r.statut == "Clos":
            continue
        if not r.proprietaires:
            anomalies.append(Anomalie("risque", f"{r.num} : aucun propriétaire"))
        if r.echeance is None:
            anomalies.append(Anomalie("risque", f"{r.num} : aucune échéance des mesures"))
    return anomalies


def questions_ouvertes(questions: list[Question]) -> tuple[list[Question], list[Question]]:
    ouvertes = [q for q in questions if q.statut == "Ouverte"]
    return [q for q in ouvertes if q.responsables], [q for q in ouvertes if not q.responsables]


@dataclass
class Destinataire:
    personne: Personne
    actions: list[ActionQualifiee]
    risques: list[Risque]
    questions: list[Question]




def _rang(q: ActionQualifiee) -> int:
    return 0 if q.en_retard else 1 if q.proche else 2 if q.nouvelle else 3


def _trier(actions: list[ActionQualifiee]) -> list[ActionQualifiee]:
    return sorted(actions, key=lambda q: (_rang(q), q.action.echeance is None,
                                          q.action.echeance or date.min))


def preparer_destinataires(qualifiees: list[ActionQualifiee], risques_rappel: list[Risque],
                           questions_resp: list[Question], annuaire: list[Personne],
                           *, tous_risques: list[Risque] | None = None
                           ) -> tuple[list[Destinataire], list[Anomalie]]:
    ouvertes = [q for q in qualifiees if est_ouverte(q.action)]

    def de(nom_norm, elements, noms):
        return [e for e in elements if nom_norm in {normaliser(n) for n in noms(e)}]

    # Noms avec signal (destinataires potentiels) et noms à vérifier (anomalies).
    cites: dict[str, str] = {}
    a_verifier: dict[str, str] = {}

    def ajouter(cible, noms):
        for n in noms:
            cible.setdefault(normaliser(n), n)

    for q in ouvertes:
        ajouter(a_verifier, q.action.responsables)
        if q.signalee:
            ajouter(cites, q.action.responsables)
    for r in risques_rappel:
        ajouter(cites, r.proprietaires)
    for r in (risques_rappel if tous_risques is None else tous_risques):
        if r.statut != "Clos":
            ajouter(a_verifier, r.proprietaires)
    for qu in questions_resp:
        ajouter(cites, qu.responsables)
        ajouter(a_verifier, qu.responsables)
    ajouter(a_verifier, cites.values())
    cites.pop("", None)
    a_verifier.pop("", None)

    anomalies: list[Anomalie] = []
    en_annuaire: dict[str, Personne] = {}
    for p in annuaire:
        en_annuaire.setdefault(normaliser(p.nom), p)
    valides: set[str] = set()
    for cle, nom in a_verifier.items():
        p = en_annuaire.get(cle)
        if p is None:
            anomalies.append(Anomalie("annuaire", f"« {nom} » : absent de l'Annuaire"))
        elif not (p.email or "").strip():
            anomalies.append(Anomalie("annuaire", f"« {nom} » : pas d'e-mail dans l'Annuaire"))
        elif not email_valide(p.email.strip()):
            anomalies.append(Anomalie("annuaire", f"« {nom} » : e-mail mal formé"))
        elif cle in cites:
            valides.add(cle)

    destinataires: list[Destinataire] = []
    vus: set[str] = set()
    for p in annuaire:
        cle = normaliser(p.nom)
        if cle not in valides or cle in vus:
            continue
        vus.add(cle)
        acts = de(cle, ouvertes, lambda q: q.action.responsables)
        destinataires.append(Destinataire(
            replace(p, email=p.email.strip()), _trier(acts),
            de(cle, risques_rappel, lambda r: r.proprietaires),
            de(cle, questions_resp, lambda qu: qu.responsables)))
    return _fusionner_adresses(destinataires, anomalies), anomalies


def _fusionner_adresses(destinataires: list[Destinataire], anomalies: list[Anomalie]) -> list[Destinataire]:
    """Un seul mail par adresse : les personnes qui partagent une adresse sont fusionnées."""
    par_adresse: dict[str, Destinataire] = {}
    for d in destinataires:
        cle = d.personne.email.strip().lower()
        premier = par_adresse.get(cle)
        if premier is None:
            par_adresse[cle] = d
            continue
        anomalies.append(Anomalie("annuaire", f"« {premier.personne.nom} » et « {d.personne.nom} » "
                                              f"partagent l'adresse {premier.personne.email} : un seul mail"))
        nums = {q.action.num for q in premier.actions}
        premier.actions = _trier(premier.actions + [q for q in d.actions if q.action.num not in nums])
        premier.risques += [r for r in d.risques if r.num not in {x.num for x in premier.risques}]
        premier.questions += [q for q in d.questions if q.num not in {x.num for x in premier.questions}]
    return list(par_adresse.values())
