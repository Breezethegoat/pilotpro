"""Orchestration : analyser (lecture seule) puis exécuter (écritures et envois)."""
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Callable

from pilotage.classeurs import Classeurs
from html import escape

from pilotage.courriers import (Courrier, Moteur, contexte_recap, contexte_responsable,
                                niveau_escalade)
from pilotage.envoi import Envoi
from pilotage.etat import Etat, Reglages
from pilotage.lecture import (
    est_onglet_plan, lettres_colonnes, lire_actions, lire_annuaire, lire_questions,
    lire_risques, lire_taches,
)
from pilotage.modeles import Action, Anomalie, Question
from pilotage.regles import (
    Destinataire, Evolution, ModifTache, Stats, actions_uniques, anomalies_actions, anomalies_risques, calculer_plan, evolutions,
    preparer_destinataires, qualifier, questions_ouvertes, risques_a_rappeler, statistiques,
)

COLONNES_PLAN = ["Statut", "Avancement saisi (%)", "Date de réalisation"]
CONTROLE = ["N°"] + COLONNES_PLAN  # N° vérifié au contrôle, jamais écrit
_ORIGINE_EXCEL = date(1899, 12, 30)


@dataclass
class Analyse:
    jour: date
    stats: Stats
    evolutions: list[Evolution]
    anomalies: list[Anomalie]
    destinataires: list[Destinataire]
    courriers: dict[str, Courrier]
    modifs_plan: list[ModifTache]
    questions_sans_responsable: list[Question]
    actions: list[Action]
    colonnes_plan: dict[str, dict[str, str]] = field(default_factory=dict)
    valeurs_plan_lues: dict[tuple[str, int], list] = field(default_factory=dict)
    escalades: dict[str, dict] = field(default_factory=dict)  # e-mail -> {niveau, jours}
    lien_classeur: str = ""
    qualifiees: list = field(default_factory=list)
    risques: list = field(default_factory=list)
    questions: list = field(default_factory=list)
    taches: list = field(default_factory=list)
    annuaire: list = field(default_factory=list)


@dataclass
class Resultat:
    envoyes: list[str]  # clés de courriers (e-mail, ou "__recap__")
    echecs: dict[str, str]
    plan_ecrit: int
    instantane_enregistre: bool
    mode_test: bool = True
    adresse_test: str = ""


class PlanModifieEntreTemps(Exception):
    def __init__(self, taches: list[str]):
        super().__init__("Le plan a été modifié depuis l'analyse : " + ", ".join(taches))
        self.taches = taches


def _index(lettre: str) -> int:
    n = 0
    for c in lettre:
        n = n * 26 + ord(c) - 64
    return n - 1


def _serie(d: date | None):
    return "" if d is None else (d - _ORIGINE_EXCEL).days


def _cellules(valeurs: list[list], ligne: int, lettres: dict[str, str]) -> list:
    r = valeurs[ligne - 1] if 0 < ligne <= len(valeurs) else []
    indices = [_index(lettres[c]) for c in CONTROLE]
    return [r[i] if i < len(r) else "" for i in indices]


def _bandeau_escalade(niveau: str, jours: int) -> str:
    if niveau == "ferme":
        texte = (f"Relance : au moins une de vos actions est en retard de {jours} jours. "
                 "Merci de la traiter ou de proposer une nouvelle échéance cette semaine.")
        couleur = "#c0392b"
    else:
        texte = f"Une de vos actions est en retard de {jours} jours : le fondateur est en copie de ce message."
        couleur = "#d35400"
    return (f'<p style="font-family:Arial,Helvetica,sans-serif;font-size:14px;padding:8px 12px;'
            f'border-left:4px solid {couleur};background:#fdf2e9;color:#222;"><b>{texte}</b></p>')


class Service:
    def __init__(self, classeurs: Classeurs, envoi_fabrique: Callable[[Reglages], Envoi],
                 etat: Etat, moteur: Moteur):
        self.classeurs, self.envoi_fabrique, self.etat, self.moteur = classeurs, envoi_fabrique, etat, moteur

    @staticmethod
    def _id(reglages: Reglages, cle: str) -> str:
        ident = (reglages.classeurs.get(cle) or {}).get("id")
        if not ident:
            raise ValueError(f"Classeur « {cle} » non configuré")
        return ident

    def analyser(self, jour: date) -> Analyse:
        reglages = self.etat.reglages()
        pil, plan, reg = (self._id(reglages, c) for c in ("pilotage", "plan", "risques"))
        if not reglages.email_fondateur.strip():
            raise ValueError("Adresse e-mail du fondateur non configurée")
        actions, anomalies = lire_actions(self.classeurs.lire(pil, "Actions"))
        anomalies += anomalies_actions(actions)
        actions = actions_uniques(actions)  # N° en double : seule la première ligne compte
        questions, ano = lire_questions(self.classeurs.lire(pil, "Questions ouvertes"))
        anomalies += ano
        annuaire = lire_annuaire(self.classeurs.lire(pil, "Annuaire"))
        risques, ano = lire_risques(self.classeurs.lire(reg, "Registre"))
        anomalies += ano
        taches, colonnes, lues = [], {}, {}
        onglets_plan = [o for o in self.classeurs.onglets(plan) if est_onglet_plan(o)]
        if not onglets_plan:
            nom_plan = reglages.classeurs.get("plan", {}).get("nom", "")
            raise ValueError(f"Aucun onglet de plan (« 1-… » à « 8-… ») dans le classeur « {nom_plan} » : "
                             "vérifiez le classeur du plan choisi dans les Réglages.")
        for onglet in onglets_plan:
            valeurs = self.classeurs.lire(plan, onglet)
            ts, ano = lire_taches(valeurs, onglet)
            taches += ts
            anomalies += ano
            colonnes[onglet] = lettres_colonnes(valeurs, CONTROLE, onglet)
            for t in ts:
                lues[(onglet, t.ligne)] = _cellules(valeurs, t.ligne, colonnes[onglet])

        instantane = self.etat.instantane()
        qualifiees = qualifier(actions, instantane, jour, reglages.seuil_proche)
        stats = statistiques(qualifiees)
        evols = evolutions(actions, instantane)
        modifs, ano = calculer_plan(taches, actions)
        anomalies += ano
        anomalies += anomalies_risques(risques)
        avec_resp, sans_resp = questions_ouvertes(questions)
        destinataires, ano = preparer_destinataires(
            qualifiees, risques_a_rappeler(risques, jour, reglages.seuil_proche),
            avec_resp, annuaire, tous_risques=risques)
        anomalies += ano

        try:
            lien = self.classeurs.lien(pil)
        except Exception:  # le lien est un confort : l'analyse continue sans lui
            lien = ""
        fondateur = reglages.email_fondateur.strip()
        courriers: dict[str, Courrier] = {}
        escalades: dict[str, dict] = {}
        for d in destinataires:
            niveau, pire = niveau_escalade(d, jour, int(reglages.escalade_jours or 0),
                                           int(reglages.escalade_ferme_jours or 0))
            objet, html = self.moteur.rendre("responsable", contexte_responsable(d, jour, lien, niveau))
            copie = ""
            if niveau:
                escalades[d.personne.email] = {"niveau": niveau, "jours": pire}
                html = _bandeau_escalade(niveau, pire) + html
                if niveau == "ferme":
                    objet = "[Relance] " + objet
                if fondateur.lower() != d.personne.email.lower():
                    copie = fondateur
            if lien and escape(lien, quote=True) not in html and lien not in html:
                # modèle personnalisé sans lien : on l'ajoute en pied de mail
                html += f'<p><a href="{escape(lien, quote=True)}">Ouvrir le classeur de pilotage</a></p>'
            courriers[d.personne.email] = Courrier(d.personne.email, objet, html, copie)
        objet, html = self.moteur.rendre("recap", contexte_recap(
            stats, evols, anomalies, sans_resp, modifs, destinataires, jour))
        courriers["__recap__"] = Courrier(reglages.email_fondateur.strip(), objet, html)
        return Analyse(jour, stats, evols, anomalies, destinataires, courriers, modifs,
                       sans_resp, actions, colonnes, lues, escalades=escalades, lien_classeur=lien,
                       qualifiees=qualifiees, risques=risques, questions=questions, taches=taches,
                       annuaire=annuaire)

    def _controler(self, analyse: Analyse, plan_id: str) -> None:
        changees, cache = [], {}
        for m in analyse.modifs_plan:
            t = m.tache
            if t.onglet not in cache:
                cache[t.onglet] = self.classeurs.lire(plan_id, t.onglet)
            actuel = _cellules(cache[t.onglet], t.ligne, analyse.colonnes_plan[t.onglet])
            if actuel != analyse.valeurs_plan_lues[(t.onglet, t.ligne)]:
                changees.append(t.num)
        if changees:
            raise PlanModifieEntreTemps(changees)

    def _sauvegarder_plan(self, analyse: Analyse) -> None:
        """Note les valeurs d'avant écriture : elles pourront être restaurées."""
        if not analyse.modifs_plan:
            return
        self.etat.ajouter_sauvegarde({
            "date": datetime.now().isoformat(timespec="seconds"),
            "lignes": [{"num": m.tache.num, "onglet": m.tache.onglet, "ligne": m.tache.ligne,
                        "colonnes": [analyse.colonnes_plan[m.tache.onglet][c] for c in COLONNES_PLAN],
                        "avant": analyse.valeurs_plan_lues[(m.tache.onglet, m.tache.ligne)][1:],
                        "apres": [m.statut, m.avancement]} for m in analyse.modifs_plan]})

    def restaurer_plan(self, sauvegarde: dict) -> int:
        """Réécrit dans le plan les valeurs notées avant une mise à jour automatique."""
        plan_id = self._id(self.etat.reglages(), "plan")
        for l in sauvegarde.get("lignes", []):
            for lettre, valeur in zip(l["colonnes"], l["avant"]):
                self.classeurs.ecrire(plan_id, l["onglet"], f"{lettre}{l['ligne']}",
                                      [["" if valeur is None else valeur]])
        return len(sauvegarde.get("lignes", []))

    def _ecrire_plan(self, analyse: Analyse, plan_id: str) -> int:
        self._sauvegarder_plan(analyse)
        for m in analyse.modifs_plan:
            t = m.tache
            cols = [analyse.colonnes_plan[t.onglet][c] for c in COLONNES_PLAN]
            if m.statut == "Réalisée":
                # Date calculée ; si elle est inconnue, la cellule existante est laissée intacte.
                ecrire = cols if m.date_realisation is not None else cols[:2]
                valeurs = [m.statut, m.avancement, _serie(m.date_realisation)][:len(ecrire)]
            else:
                ecrire, valeurs = cols[:2], [m.statut, m.avancement]  # jamais la date de réalisation
            idx = [_index(c) for c in ecrire]
            if len(ecrire) > 1 and idx == list(range(idx[0], idx[0] + len(idx))):
                self.classeurs.ecrire(plan_id, t.onglet, f"{ecrire[0]}{t.ligne}:{ecrire[-1]}{t.ligne}", [valeurs])
            else:
                for c, v in zip(ecrire, valeurs):
                    self.classeurs.ecrire(plan_id, t.onglet, f"{c}{t.ligne}", [[v]])
        return len(analyse.modifs_plan)

    def _envoyer(self, analyse: Analyse, cles: list[str], reglages: Reglages) -> tuple[list[str], dict[str, str]]:
        envoi = self.envoi_fabrique(reglages)
        envoyes, echecs = [], {}
        for cle in cles:
            try:
                envoi.envoyer(analyse.courriers[cle])
                envoyes.append(cle)
            except Exception as e:  # une erreur par destinataire ne bloque pas les autres
                echecs[cle] = str(e)
        return envoyes, echecs

    def _terminer(self, analyse: Analyse, envoyes: list[str], echecs: dict[str, str],
                  plan_ecrit: int, reglages: Reglages) -> Resultat:
        # Mode test : la semaine n'est pas clôturée (les actions restent « nouvelles » pour le vrai envoi).
        enregistre = not echecs and not reglages.mode_test
        if enregistre:
            self.etat.enregistrer_instantane(analyse.actions, analyse.jour)
        self.etat.ajouter_historique({
            "date": datetime.now().date().isoformat(), "envoyes": envoyes, "echecs": echecs,
            "plan_ecrit": plan_ecrit, "mode_test": reglages.mode_test})
        return Resultat(envoyes, echecs, plan_ecrit, enregistre, reglages.mode_test, reglages.adresse_test)

    def executer(self, analyse: Analyse, exclus: set[str]) -> Resultat:
        reglages = self.etat.reglages()
        plan_id = self._id(reglages, "plan")
        self._controler(analyse, plan_id)
        plan_ecrit = self._ecrire_plan(analyse, plan_id)
        cles = [k for k, c in analyse.courriers.items() if k == "__recap__" or c.destinataire not in exclus]
        envoyes, echecs = self._envoyer(analyse, cles, reglages)
        return self._terminer(analyse, envoyes, echecs, plan_ecrit, reglages)

    def renvoyer_echecs(self, analyse: Analyse, resultat: Resultat) -> Resultat:
        # Mêmes réglages d'envoi que l'exécution d'origine ; seules les clés en échec sont rejouées.
        reglages = replace(self.etat.reglages(), mode_test=resultat.mode_test,
                           adresse_test=resultat.adresse_test)
        envoyes, echecs = self._envoyer(analyse, list(resultat.echecs), reglages)
        return self._terminer(analyse, resultat.envoyes + envoyes, echecs, 0, reglages)
