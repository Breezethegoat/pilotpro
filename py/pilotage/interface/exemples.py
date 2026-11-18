"""Données d'exemple pour l'aperçu des modèles quand aucune analyse n'a encore été faite."""
from datetime import date, timedelta

from pilotage.courriers import contexte_recap, contexte_responsable
from pilotage.modeles import Action, Anomalie, Personne, Question, Risque, Tache
from pilotage.regles import ActionQualifiee, Destinataire, Evolution, ModifTache, Stats


def _action(num, libelle, statut, echeance, responsables=("Marie Exemple",)):
    return Action(num=num, date_creation=None, taches_plan=["V-01"], libelle=libelle, livrable="",
                  responsables=list(responsables), echeance=echeance, priorite="Haute",
                  statut=statut, date_realisation=None, ligne=6)


def destinataire_exemple(jour: date) -> Destinataire:
    p = Personne(nom="Marie Exemple", email="marie@exemple.fr", telephone=None,
                 groupe="fondateur", ligne=6)
    actions = [
        ActionQualifiee(_action("A-001", "Envoyer le dossier à la banque", "En cours",
                                jour - timedelta(days=4)), False, False, True),
        ActionQualifiee(_action("A-002", "Relire les statuts", "À faire",
                                jour + timedelta(days=2)), False, True, False),
        ActionQualifiee(_action("A-003", "Préparer le budget prévisionnel", "À faire",
                                jour + timedelta(days=20)), True, False, False),
    ]
    risques = [Risque(num="R-01", intitule="Retard de financement", niveau="Élevé",
                      proprietaires=[p.nom], echeance=jour + timedelta(days=1),
                      avancement="En cours", statut="Ouvert", ligne=6)]
    questions = [Question(num="Q-01", intitule="Quel statut juridique retenir ?",
                          responsables=[p.nom], echeance=jour + timedelta(days=7),
                          statut="Ouverte", ligne=6)]
    return Destinataire(p, actions, risques, questions)


def contexte_exemple(nom: str, jour: date) -> dict:
    d = destinataire_exemple(jour)
    if nom == "responsable":
        return contexte_responsable(d, jour)
    stats = Stats(total=12, ouvertes=8, a_attribuer=1, en_cours=4, bloquees=1, realisees=4,
                  annulees=0, nouvelles=1, proches=1, en_retard=1, realisees_a_temps=3,
                  realisees_en_retard=1, taux_realisation=4 / 12, taux_delais=0.75,
                  par_responsable={"Marie Exemple": {"ouvertes": 3, "en_retard": 1}})
    evolutions = [Evolution("A-004", "realisee", "En cours", "Réalisée"),
                  Evolution("A-005", "echeance", "01/12/2026", "15/12/2026")]
    anomalies = [Anomalie("annuaire", "« Paul Exemple » : absent de l'Annuaire"),
                 Anomalie("plan", "A-006 : aucune tâche du plan")]
    sans_resp = [Question(num="Q-02", intitule="Qui suit le dossier assurance ?", responsables=[],
                          echeance=None, statut="Ouverte", ligne=7)]
    tache = Tache(num="V-01", libelle="Statuts de la société", onglet="1-Validation", ligne=6,
                  statut="À faire", avancement=0, date_realisation=None)
    modifs = [ModifTache(tache, 50, "En cours", None)]
    return contexte_recap(stats, evolutions, anomalies, sans_resp, modifs, [d], jour)
