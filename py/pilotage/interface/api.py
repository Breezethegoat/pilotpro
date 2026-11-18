"""Api exposée à l'interface (window.pywebview.api).

Chaque méthode publique renvoie {"ok": bool, "donnees"?: ..., "erreur"?: str} et ne lève jamais.
Les attributs internes commencent par « _ » pour que pywebview ne les expose pas.
"""
import functools
import re
import threading
import traceback
from dataclasses import asdict, fields, replace
from datetime import date, datetime
from pathlib import Path
from typing import Callable

import requests
from jinja2 import TemplateError

from pilotage.courriers import (MODELES, VARIABLES, Courrier, Moteur, contexte_recap, contexte_responsable,
                                jours_de_retard, lien_cellule, message_whatsapp)
from pilotage.edition import PRIORITES, STATUTS_ACTION, STATUTS_QUESTION, Edition, date_iso
from pilotage.equipe import ENTETE_FONDATEURS, Equipe, FondateursComplets, _entete_conseils
from pilotage.etat import DECISIONS_ECHEANCE, Etat, Reglages
from pilotage.graph import ErreurGraph, ReconnexionRequise
from pilotage.interface.exemples import contexte_exemple
from pilotage.lecture import ColonneIntrouvable, _cellule, _ligne, _texte, lettres_colonnes
from pilotage import paquet, rapports
from pilotage.service import PlanModifieEntreTemps, Service
from urllib.parse import quote

from pilotage.textes import email_valide, numero_whatsapp

RECAP = "__recap__"
# Réglages recopiés sur OneDrive pour l'application mobile (aucun mot de passe).
REGLAGES_MOBILE = ("client_id", "classeurs", "seuil_proche", "escalade_jours", "escalade_ferme_jours",
                   "email_fondateur")
CANAUX = ("microsoft", "gmail")
PAGE_MDP_GOOGLE = "https://myaccount.google.com/apppasswords"
MSG_GMAIL_INCOMPLET = ("Envoi par Gmail : renseignez l'adresse Gmail et enregistrez le mot de passe "
                       "d'application dans les Réglages (ou revenez à l'envoi par le compte Microsoft).")
MSG_ADRESSE_TEST = "Mode test : renseignez l'adresse de test dans les Réglages avant d'envoyer."
LIBELLE_RECAP = "Récapitulatif (vous)"
MSG_RECONNEXION = ("Votre connexion Microsoft a expiré ou n'est pas encore faite : "
                   "cliquez sur « Se reconnecter » (onglet Réglages) pour vous connecter à nouveau.")
MSG_RESEAU = "Impossible de joindre Microsoft : vérifiez la connexion Internet puis réessayez."
MSG_INATTENDUE = ("Erreur inattendue : l'opération n'a pas abouti. "
                  "Le détail a été noté dans le fichier donnees/erreurs.log.")


class _Refus(Exception):
    """Erreur métier dont le message est destiné à l'utilisateur."""


def _protege(methode):
    @functools.wraps(methode)
    def enveloppe(self, *args, **kwargs):
        try:
            return {"ok": True, "donnees": methode(self, *args, **kwargs)}
        except ReconnexionRequise:
            return {"ok": False, "erreur": MSG_RECONNEXION, "reconnexion": True}
        except ErreurGraph as e:
            if e.statut == 401:
                return {"ok": False, "erreur": MSG_RECONNEXION, "reconnexion": True}
            return {"ok": False, "erreur": f"Microsoft a refusé l'opération ({e.statut}) : {e.message}"}
        except PlanModifieEntreTemps as e:
            return {"ok": False, "relancer": True, "erreur": (
                "Le plan a été modifié depuis l'analyse (tâches " + ", ".join(e.taches)
                + "). Rien n'a été écrit ni envoyé : relancez l'analyse.")}
        except (_Refus, ValueError, ColonneIntrouvable, FondateursComplets) as e:
            return {"ok": False, "erreur": str(e)}
        except TemplateError as e:
            return {"ok": False, "erreur": f"Erreur dans un modèle de mail (onglet Modèles) : {e}"}
        except requests.RequestException:
            return {"ok": False, "erreur": MSG_RESEAU}
        except Exception:
            self._journaliser(methode.__name__)
            return {"ok": False, "erreur": MSG_INATTENDUE}
    return enveloppe


def _pourcent(v) -> str:
    try:
        return f"{round(float(v))} %"
    except (TypeError, ValueError):
        return "0 %"


def _noms_cites(anomalies) -> list[str]:
    noms = []
    for a in anomalies:
        m = re.match(r"« (.*) » :", a.message)
        if a.type == "annuaire" and m and m.group(1) not in noms:
            noms.append(m.group(1))
    return noms


class Api:
    def __init__(self, dossier: Path, fabrique, *, aujourd_hui: Callable[[], date] = date.today,
                 fil=threading.Thread):
        self._dossier = Path(dossier)
        self._fab = fabrique
        self._etat = Etat(self._dossier)
        self._moteur = Moteur(self._dossier / "modeles")
        self._aujourdhui = aujourd_hui
        self._fil = fil
        self._conn, self._conn_id = None, None
        self._analyse, self._resultat, self._execute = None, None, False
        self._verrou = threading.Lock()
        self._connexion_fil = None
        self._connexion_erreur = None
        self._page_connexion = ""
        self._analyser_au_demarrage = False
        self._donnees = None  # dernières données d'analyse envoyées à l'interface
        self._coffre = fabrique.coffre(self._dossier)

    # ---- outils internes ----
    def _journaliser(self, contexte: str) -> None:
        try:
            with open(self._dossier / "erreurs.log", "a", encoding="utf-8") as f:
                f.write(f"--- {datetime.now().isoformat(timespec='seconds')} {contexte}\n")
                f.write(traceback.format_exc() + "\n")
        except OSError:
            pass

    def _connexion(self, obligatoire: bool = True):
        client_id = self._etat.reglages().client_id.strip()
        if not client_id:
            if obligatoire:
                raise _Refus("Renseignez d'abord l'ID d'application dans l'onglet Réglages.")
            return None
        if self._conn is None or self._conn_id != client_id:
            self._conn, self._conn_id = self._fab.connexion(client_id, self._dossier), client_id
        return self._conn

    def _graph(self):
        return self._fab.graph(self._connexion())

    def _brancher_partage(self, graph) -> None:
        self._etat.partage = self._fab.partage(graph)

    def _service(self) -> Service:
        graph = self._graph()
        self._brancher_partage(graph)
        return Service(self._fab.classeurs(graph), lambda r: self._envoi(graph, r),
                       self._etat, self._moteur)

    def _envoi(self, graph, r: Reglages):
        if r.canal_envoi == "gmail":
            return self._fab.envoi_gmail(r.gmail_adresse, self._coffre.lire(), r.mode_test, r.adresse_test)
        return self._fab.envoi(graph, r.mode_test, r.adresse_test)

    def _verifier_canal(self, r: Reglages) -> None:
        if r.canal_envoi == "gmail" and not (r.gmail_adresse.strip() and self._coffre.lire()):
            raise _Refus(MSG_GMAIL_INCOMPLET)

    def _reglages_json(self, r: Reglages) -> dict:
        return {**asdict(r), "gmail_mdp_enregistre": bool(self._coffre.lire())}

    def _id_pilotage(self) -> str:
        ident = (self._etat.reglages().classeurs.get("pilotage") or {}).get("id")
        if not ident:
            raise _Refus("Choisissez d'abord le classeur de pilotage dans l'onglet Réglages.")
        return ident

    def _libelle(self, cle: str) -> str:
        if cle == RECAP:
            return LIBELLE_RECAP
        c = self._analyse.courriers.get(cle) if self._analyse else None
        adresse = c.destinataire if c else cle
        d = next((d for d in self._analyse.destinataires if d.personne.email == cle), None) \
            if self._analyse else None
        return f"{d.personne.nom} <{adresse}>" if d else adresse

    def _resultat_json(self, r) -> dict:
        return {
            "envoyes": [{"cle": k, "libelle": self._libelle(k)} for k in r.envoyes],
            "echecs": [{"cle": k, "libelle": self._libelle(k), "erreur": m} for k, m in r.echecs.items()],
            "plan_ecrit": r.plan_ecrit,
            "instantane_enregistre": r.instantane_enregistre,
            "mode_test": r.mode_test,
            "adresse_test": r.adresse_test,
        }

    # ---- connexion ----
    @_protege
    def etat_connexion(self) -> dict:
        conn = self._connexion(obligatoire=False)
        compte = conn.compte() if conn else None
        en_cours = self._connexion_fil is not None and self._connexion_fil.is_alive()
        return {"client_id": conn is not None, "connecte": bool(compte), "compte": compte or "",
                "en_cours": en_cours, "erreur": self._connexion_erreur or ""}

    @_protege
    def demarrer_connexion(self) -> dict:
        conn = self._connexion()
        try:
            flux = conn.demarrer()
        except RuntimeError as e:
            raise _Refus(f"Connexion impossible : {e} — vérifiez l'ID d'application et le guide Azure.")
        self._connexion_erreur = None

        def attendre():
            try:
                compte = conn.terminer(flux)
                r = self._etat.reglages()
                if compte and not (r.email_fondateur.strip() and r.adresse_test.strip()):
                    r.email_fondateur = r.email_fondateur.strip() or compte
                    r.adresse_test = r.adresse_test.strip() or compte
                    self._etat.enregistrer_reglages(r)
            except Exception as e:
                self._connexion_erreur = str(e) or "Connexion échouée."

        self._connexion_fil = self._fil(target=attendre, daemon=True)
        self._connexion_fil.start()
        self._page_connexion = flux.get("verification_uri", "")
        code = flux.get("user_code", "")
        # Confort : le code est copié puis la page Microsoft s'ouvre ; un échec ici ne bloque pas la connexion.
        copie = self._sans_echec(self._fab.copier, code)
        ouvert = self._sans_echec(self._fab.ouvrir_navigateur, self._page_connexion)
        return {"user_code": code, "verification_uri": self._page_connexion,
                "message": flux.get("message", ""), "navigateur_ouvert": ouvert, "code_copie": copie}

    @staticmethod
    def _sans_echec(action, valeur) -> bool:
        if not valeur:
            return False
        try:
            action(valeur)
            return True
        except Exception:
            return False

    @_protege
    def ouvrir_page_connexion(self) -> dict:
        """Rouvre la page Microsoft de saisie du code (lien cliquable de l'interface)."""
        if not self._page_connexion:
            raise _Refus("Aucune connexion en cours : cliquez d'abord sur « Se connecter ».")
        self._fab.ouvrir_navigateur(self._page_connexion)
        return {"ouvert": True}

    @_protege
    def terminer_connexion(self) -> dict:
        """Attend (au plus 15 min) la fin de la connexion en cours et renvoie l'état."""
        if self._connexion_fil is not None:
            self._connexion_fil.join(timeout=900)
        return self.etat_connexion()["donnees"]

    @_protege
    def deconnecter(self) -> dict:
        conn = self._connexion(obligatoire=False)
        if conn:
            conn.deconnecter()
        return {"connecte": False}

    # ---- réglages ----
    @_protege
    def lire_reglages(self) -> dict:
        return self._reglages_json(self._etat.reglages())

    @_protege
    def enregistrer_reglages(self, d: dict) -> dict:
        r = self._etat.reglages()
        noms = {f.name for f in fields(Reglages)}
        for cle, valeur in (d or {}).items():
            if cle in noms:
                setattr(r, cle, valeur)
        try:
            r.seuil_proche = int(r.seuil_proche)
        except (TypeError, ValueError):
            raise _Refus("Le seuil « proche » doit être un nombre de jours.")
        if not 0 <= r.seuil_proche <= 60:
            raise _Refus("Le seuil « proche » doit être compris entre 0 et 60 jours.")
        for cle in ("escalade_jours", "escalade_ferme_jours"):
            try:
                setattr(r, cle, int(getattr(r, cle) or 0))
            except (TypeError, ValueError):
                raise _Refus("Les délais d'escalade doivent être des nombres de jours.")
            if not 0 <= getattr(r, cle) <= 365:
                raise _Refus("Les délais d'escalade doivent être compris entre 0 et 365 jours.")
        r.client_id = str(r.client_id or "").strip()
        r.mode_test = bool(r.mode_test)
        for cle, libelle in (("adresse_test", "de test"), ("email_fondateur", "du fondateur")):
            v = str(getattr(r, cle) or "").strip()
            if v and not email_valide(v):
                raise _Refus(f"Adresse e-mail {libelle} invalide : {v}")
            setattr(r, cle, v)
        if r.canal_envoi not in CANAUX:
            raise _Refus("Canal d'envoi inconnu : choisissez Microsoft ou Gmail.")
        r.gmail_adresse = str(r.gmail_adresse or "").strip()
        if r.gmail_adresse and not email_valide(r.gmail_adresse):
            raise _Refus(f"Adresse Gmail invalide : {r.gmail_adresse}")
        r.auto_actif, r.auto_validation = bool(r.auto_actif), bool(r.auto_validation)
        if r.theme not in ("auto", "clair", "sombre"):
            raise _Refus("Apparence inconnue : choisissez automatique, clair ou sombre.")
        self._etat.enregistrer_reglages(r)
        return self._reglages_json(r)

    # ---- passage automatique ----
    @_protege
    def enregistrer_planification(self, d: dict) -> dict:
        """Active ou désactive le passage hebdomadaire (tâche planifiée Windows)."""
        d = d or {}
        r = self._etat.reglages()
        jour, heure = str(d.get("jour") or r.auto_jour), str(d.get("heure") or r.auto_heure)
        if d.get("actif"):
            self._fab.planifier(jour, heure)   # lève ValueError si jour/heure invalides ou refus de Windows
        else:
            self._fab.deplanifier()
        r.auto_actif, r.auto_jour, r.auto_heure = bool(d.get("actif")), jour, heure
        r.auto_validation = bool(d.get("validation"))
        self._etat.enregistrer_reglages(r)
        return {**self._reglages_json(r), "prochaine": self._fab.prochaine_execution() if r.auto_actif else ""}

    @_protege
    def etat_planification(self) -> dict:
        r = self._etat.reglages()
        return {"actif": r.auto_actif, "prochaine": self._fab.prochaine_execution() if r.auto_actif else ""}

    @_protege
    def options_demarrage(self) -> dict:
        """Ce que l'interface doit faire à l'ouverture (analyse immédiate après un passage en validation)."""
        return {"analyser": self._analyser_au_demarrage}

    @_protege
    def enregistrer_mot_de_passe_gmail(self, mot_de_passe: str) -> dict:
        """Enregistre (chiffré) le mot de passe d'application Google ; vide = effacer."""
        mdp = re.sub(r"\s", "", str(mot_de_passe or ""))
        if not mdp:
            self._coffre.effacer()
            return {"gmail_mdp_enregistre": False}
        if not re.fullmatch(r"[A-Za-z]{16}", mdp):
            raise _Refus("Le mot de passe d'application Google compte 16 lettres "
                         "(les espaces sont ignorés). Ce n'est pas votre mot de passe Gmail habituel.")
        self._coffre.enregistrer(mdp)
        return {"gmail_mdp_enregistre": True}

    @_protege
    def ouvrir_aide_gmail(self) -> dict:
        """Ouvre la page Google de création des mots de passe d'application."""
        self._fab.ouvrir_navigateur(PAGE_MDP_GOOGLE)
        return {"ouvert": True}

    @_protege
    def tester_gmail(self) -> dict:
        """Envoie un mail d'essai de l'adresse Gmail vers elle-même."""
        r = replace(self._etat.reglages(), canal_envoi="gmail", mode_test=False)
        self._verifier_canal(r)
        self._fab.envoi_gmail(r.gmail_adresse, self._coffre.lire(), False, "").envoyer(Courrier(
            r.gmail_adresse, "PilotPro : test d'envoi Gmail",
            "<p>Ce mail confirme que PilotPro peut envoyer depuis votre adresse Gmail.</p>"))
        return {"envoye_a": r.gmail_adresse}

    @_protege
    def chercher_classeurs(self, texte: str) -> list[dict]:
        texte = (texte or "").strip()
        if not texte:
            raise _Refus("Saisissez une partie du nom du classeur.")
        return self._fab.classeurs(self._graph()).chercher(texte)

    @_protege
    def historique(self) -> list[dict]:
        return [{"date": h.get("date", ""), "nb_envoyes": len(h.get("envoyes") or []),
                 "nb_echecs": len(h.get("echecs") or {}), "echecs": list((h.get("echecs") or {}).keys()),
                 "plan_ecrit": h.get("plan_ecrit", 0), "mode_test": bool(h.get("mode_test"))}
                for h in reversed(self._etat.historique())]

    # ---- passage ----
    @_protege
    def analyser(self) -> dict:
        with self._verrou:
            service = self._service()
            a = service.analyser(self._aujourdhui())
            self._analyse, self._resultat, self._execute = a, None, False
        r = self._etat.reglages()
        avancements = [t.avancement or 0 for t in a.taches]
        self._etat.enregistrer_tendance({
            "date": a.jour.isoformat(), "total": a.stats.total, "ouvertes": a.stats.ouvertes,
            "en_retard": a.stats.en_retard, "realisees": a.stats.realisees,
            "taux_realisation": a.stats.taux_realisation, "taux_delais": a.stats.taux_delais,
            "avancement_plan": (sum(avancements) / len(avancements) / 100) if avancements else None})
        self._etat.relever_echeances(a.actions, a.jour)
        self._publier_pour_mobile(r)
        mails = []
        for d in a.destinataires:
            mails.append({"cle": d.personne.email, "email": d.personne.email, "nom": d.personne.nom,
                          "recap": False,
                          "nb_retard": sum(q.en_retard for q in d.actions),
                          "nb_proches": sum(q.proche for q in d.actions),
                          "nb_nouvelles": sum(q.nouvelle for q in d.actions),
                          "nb_risques": len(d.risques), "nb_questions": len(d.questions),
                          "escalade": a.escalades.get(d.personne.email, {}).get("niveau", ""),
                          "jours_retard": a.escalades.get(d.personne.email, {}).get("jours", 0),
                          "copie": a.courriers[d.personne.email].cc,
                          "whatsapp": bool(numero_whatsapp(d.personne.telephone))})
        mails.append({"cle": RECAP, "email": a.courriers[RECAP].destinataire, "nom": LIBELLE_RECAP,
                      "recap": True, "nb_retard": a.stats.en_retard, "nb_proches": a.stats.proches,
                      "nb_nouvelles": a.stats.nouvelles, "nb_risques": 0, "nb_questions": 0,
                      "whatsapp": False})
        self._donnees = {
            "date": a.jour.strftime("%d/%m/%Y"),
            "stats": asdict(a.stats),
            "evolutions": [asdict(e) for e in a.evolutions],
            "anomalies": [{"type": x.type, "message": x.message} for x in a.anomalies],
            "mails": mails,
            "modifs_plan": [{
                "num": m.tache.num, "libelle": m.tache.libelle, "onglet": m.tache.onglet,
                "avancement_avant": round(m.tache.avancement or 0), "avancement_apres": m.avancement,
                "statut_avant": m.tache.statut, "statut_apres": m.statut,
                "date_realisation": m.date_realisation.strftime("%d/%m/%Y") if m.date_realisation else "",
            } for m in a.modifs_plan],
            "questions_sans_responsable": [{"num": q.num, "intitule": q.intitule}
                                           for q in a.questions_sans_responsable],
            "manquants": _noms_cites(a.anomalies),
            "actions": [self._action_json(q, a) for q in a.qualifiees],
            "statuts_action": STATUTS_ACTION, "priorites": PRIORITES,
            "personnes": [p.nom for p in a.annuaire],
            "taches_plan": [{"num": t.num, "libelle": t.libelle} for t in a.taches],
            "lien_classeur": a.lien_classeur,
            "tendances": self._etat.tendances(),
            "aujourdhui": a.jour.isoformat(),
            "plan": [{"num": t.num, "libelle": t.libelle, "onglet": t.onglet, "responsable": t.responsable,
                      "debut": t.debut.isoformat() if t.debut else "",
                      "echeance": t.echeance.isoformat() if t.echeance else "",
                      "fin_phase": t.fin_phase.isoformat() if t.fin_phase else "",
                      "statut": t.statut, "avancement": round(t.avancement or 0)} for t in a.taches],
            "risques": [{"num": x.num, "intitule": x.intitule, "niveau": x.niveau, "categorie": x.categorie,
                         "p": x.probabilite, "i": x.impact, "proprietaires": ", ".join(x.proprietaires),
                         "echeance": x.echeance.strftime("%d/%m/%Y") if x.echeance else "",
                         "avancement": x.avancement, "statut": x.statut} for x in a.risques],
            "questions": [{"num": q.num, "intitule": q.intitule, "responsables": ", ".join(q.responsables),
                           "echeance": q.echeance.strftime("%d/%m/%Y") if q.echeance else "",
                           "echeance_iso": q.echeance.isoformat() if q.echeance else "",
                           "statut": q.statut, "ligne": q.ligne} for q in a.questions],
            "statuts_question": STATUTS_QUESTION,
            "changements_echeance": self._changements_json(),
            "nb_risques_critiques": sum(1 for x in a.risques if x.niveau == "Critique" and x.statut != "Clos"),
            "mode_test": r.mode_test, "adresse_test": r.adresse_test,
        }
        return self._donnees

    @_protege
    def apercu(self, cle: str) -> dict:
        if self._analyse is None:
            raise _Refus("Lancez d'abord une analyse.")
        c = self._analyse.courriers.get(cle)
        if c is None:
            raise _Refus("Ce mail ne fait pas partie de la dernière analyse.")
        return {"destinataire": c.destinataire, "objet": c.objet, "html": c.html}

    @_protege
    def executer(self, exclus: list | None = None) -> dict:
        with self._verrou:
            if self._analyse is None or self._execute:
                raise _Refus("Lancez une nouvelle analyse avant d'envoyer : "
                             "les mails de la dernière analyse sont déjà partis.")
            reg = self._etat.reglages()
            if reg.mode_test and not str(reg.adresse_test or "").strip():
                raise _Refus(MSG_ADRESSE_TEST)
            self._verifier_canal(reg)
            r = self._service().executer(self._analyse, set(exclus or []))
            self._resultat, self._execute = r, True
        return self._resultat_json(r)

    @_protege
    def renvoyer_echecs(self) -> dict:
        with self._verrou:
            if self._analyse is None or self._resultat is None or not self._resultat.echecs:
                raise _Refus("Aucun envoi en échec à renvoyer.")
            if self._resultat.mode_test and not str(self._resultat.adresse_test or "").strip():
                raise _Refus(MSG_ADRESSE_TEST)
            self._verifier_canal(self._etat.reglages())
            r = self._service().renvoyer_echecs(self._analyse, self._resultat)
            self._resultat = r
        return self._resultat_json(r)

    # ---- actions ----
    @staticmethod
    def _action_json(q, analyse) -> dict:
        x = q.action
        return {"num": x.num, "libelle": x.libelle, "livrable": x.livrable,
                "responsables": ", ".join(x.responsables), "statut": x.statut, "priorite": x.priorite,
                "echeance": x.echeance.strftime("%d/%m/%Y") if x.echeance else "",
                "echeance_iso": x.echeance.isoformat() if x.echeance else "",
                "date_realisation": x.date_realisation.strftime("%d/%m/%Y") if x.date_realisation else "",
                "taches": ", ".join(x.taches_plan), "ligne": x.ligne,
                "ouverte": x.statut not in ("Réalisée", "Annulée"),
                "en_retard": q.en_retard, "proche": q.proche, "nouvelle": q.nouvelle,
                "jours_retard": jours_de_retard(q, analyse.jour),
                "a_temps": (None if x.statut != "Réalisée" or not x.echeance or not x.date_realisation
                            else x.date_realisation <= x.echeance),
                "lien": lien_cellule(analyse.lien_classeur, "Actions", f"A{x.ligne}")}

    def _edition(self) -> Edition:
        return Edition(self._fab.classeurs(self._graph()), self._id_pilotage())

    @staticmethod
    def _champs_action(d: dict, creation: bool) -> dict:
        champs: dict = {}
        if "statut" in d:
            if d["statut"] not in STATUTS_ACTION:
                raise _Refus("Statut inconnu : choisissez un statut dans la liste.")
            champs["Statut"] = d["statut"]
        if "priorite" in d and d["priorite"]:
            if d["priorite"] not in PRIORITES:
                raise _Refus("Priorité inconnue : choisissez une priorité dans la liste.")
            champs["Priorité"] = d["priorite"]
        if "echeance" in d:
            champs["Échéance"] = date_iso(d["echeance"])
        for cle, entete in (("responsable", "Responsable"), ("libelle", "Action"),
                            ("livrable", "Livrable attendu"), ("tache", "Tâche du plan")):
            if cle in d and (creation or cle == "responsable" or str(d[cle]).strip()):
                champs[entete] = str(d[cle] or "").strip()
        return champs

    def _publier_pour_mobile(self, r: Reglages) -> None:
        """Dépose sur OneDrive ce dont l'application mobile a besoin (classeurs choisis, seuils, courbes)."""
        partage = self._etat.partage
        if partage is None or not getattr(self._fab, "publie_pour_mobile", True):
            return
        try:
            partage.ecrire("reglages.json", {k: getattr(r, k) for k in REGLAGES_MOBILE})
            partage.ecrire("tendances.json", self._etat.tendances())
        except Exception as e:  # confort : l'analyse sur l'ordinateur n'en dépend pas
            self._etat.partage_erreur = str(e)

    def _changements_json(self) -> list[dict]:
        """Changements d'échéance : ceux à décider d'abord, puis les plus récents."""
        def fr(iso):
            return date.fromisoformat(iso).strftime("%d/%m/%Y") if iso else ""

        def ecart(c):
            if not (c.get("avant") and c.get("apres")):
                return None
            return (date.fromisoformat(c["apres"]) - date.fromisoformat(c["avant"])).days

        liste = self._etat.echeances()["changements"]
        liste = sorted(liste, key=lambda c: (bool(c.get("decision")), -c.get("id", 0)))
        return [{"id": c["id"], "num": c["num"], "libelle": c.get("libelle", ""),
                 "responsables": ", ".join(c.get("responsables") or []),
                 "avant": fr(c.get("avant")), "apres": fr(c.get("apres")), "ecart": ecart(c),
                 "detecte_le": fr(c.get("detecte_le")), "origine": c.get("origine", "classeur"),
                 "decision": c.get("decision", ""), "decide_le": fr(c.get("decide_le")),
                 "note": c.get("note", "")} for c in liste]

    @_protege
    def decider_echeance(self, ident: int, decision: str, note: str = "") -> list:
        """Classe un changement d'échéance : "autorise", "violation", ou "" pour le remettre à décider."""
        if decision not in DECISIONS_ECHEANCE:
            raise _Refus("Décision inconnue.")
        self._brancher_partage(self._graph())  # la décision est rangée sur OneDrive, partagée avec le téléphone
        try:
            self._etat.decider_echeance(int(ident), decision, note, self._aujourdhui())
        except ValueError as e:
            raise _Refus(str(e)) from None
        return self._changements_json()

    @_protege
    def modifier_action(self, num: str, d: dict) -> dict:
        """Modifie une action dans le classeur (statut, échéance, responsable, priorité, libellé)."""
        with self._verrou:
            if self._analyse is None:
                raise _Refus("Lancez d'abord une analyse.")
            action = next((x for x in self._analyse.actions if x.num == num), None)
            if action is None:
                raise _Refus(f"Action {num} introuvable : relancez l'analyse.")
            champs = self._champs_action(d or {}, creation=False)
            if not champs:
                raise _Refus("Aucune modification à enregistrer.")
            if champs.get("Statut") == "Réalisée" and action.date_realisation is None:
                champs["Date de réalisation"] = self._aujourdhui()
            self._edition().modifier("Actions", num, action.ligne, champs)
            if "Échéance" in champs and champs["Échéance"] != action.echeance:
                self._etat.noter_echeance_autorisee(action, champs["Échéance"], self._aujourdhui())
            self._analyse, self._resultat, self._execute = None, None, False  # les mails préparés sont périmés
        return {"num": num}

    def _question_et_champs(self, num: str, d: dict):
        question = next((x for x in (self._analyse.questions if self._analyse else []) if x.num == num), None)
        if question is None:
            raise _Refus(f"Question {num} introuvable : relancez l'analyse.")
        champs: dict = {}
        if "statut" in d:
            if d["statut"] not in STATUTS_QUESTION:
                raise _Refus(f"Question {num} : statut inconnu, choisissez un statut dans la liste.")
            champs["Statut"] = d["statut"]
        if "responsable" in d:
            champs["Responsable"] = str(d["responsable"] or "").strip()
        if "echeance" in d:
            try:
                champs["Échéance"] = date_iso(d["echeance"])
            except ValueError as e:
                raise _Refus(f"Question {num} : {e}") from None
        if not champs:
            raise _Refus(f"Question {num} : aucune modification à enregistrer.")
        return question, champs

    @_protege
    def modifier_question(self, num: str, d: dict) -> dict:
        """Attribue un responsable, fixe une échéance ou change le statut d'une question ouverte."""
        with self._verrou:
            question, champs = self._question_et_champs(num, d or {})
            self._edition().modifier("Questions ouvertes", num, question.ligne, champs)
            self._analyse, self._resultat, self._execute = None, None, False
        return {"num": num}

    @_protege
    def modifier_questions(self, modifs: dict) -> dict:
        """Enregistre en une fois les modifications de plusieurs questions : {N°: {champ: valeur}}.
        Tout est vérifié avant la première écriture ; une écriture qui échoue n'empêche pas les suivantes."""
        modifs = modifs or {}
        if not modifs:
            raise _Refus("Aucune modification à enregistrer.")
        with self._verrou:
            prets = [(num, *self._question_et_champs(num, d or {})) for num, d in modifs.items()]
            edition, enregistrees, echecs = self._edition(), [], {}
            for num, question, champs in prets:
                try:
                    edition.modifier("Questions ouvertes", num, question.ligne, champs)
                    enregistrees.append(num)
                except ReconnexionRequise:
                    raise
                except Exception as e:
                    echecs[num] = str(e)
            if enregistrees:
                self._analyse, self._resultat, self._execute = None, None, False
        return {"enregistrees": enregistrees, "echecs": echecs}

    @_protege
    def ouvrir_whatsapp(self, cle: str) -> dict:
        """Ouvre WhatsApp avec le rappel pré-rédigé pour ce responsable (l'envoi reste manuel)."""
        d = next((d for d in (self._analyse.destinataires if self._analyse else [])
                  if d.personne.email == cle), None)
        if d is None:
            raise _Refus("Destinataire introuvable : relancez l'analyse.")
        numero = numero_whatsapp(d.personne.telephone)
        if not numero:
            raise _Refus(f"Pas de numéro de téléphone utilisable pour {d.personne.nom} : "
                         "complétez-le dans l'onglet Équipe.")
        texte = message_whatsapp(d, self._analyse.jour)
        self._fab.ouvrir_navigateur(f"https://wa.me/{numero}?text={quote(texte, safe='')}")
        return {"numero": numero}

    @_protege
    def ouvrir_action(self, num: str) -> dict:
        """Ouvre le classeur en ligne sur la ligne de l'action."""
        action = next((x for x in (self._analyse.actions if self._analyse else []) if x.num == num), None)
        if action is None or not self._analyse.lien_classeur:
            raise _Refus("Lien vers le classeur indisponible : relancez l'analyse.")
        self._fab.ouvrir_navigateur(lien_cellule(self._analyse.lien_classeur, "Actions", f"A{action.ligne}"))
        return {"ouvert": True}

    @_protege
    def creer_action(self, d: dict) -> dict:
        d = dict(d or {})
        if not str(d.get("libelle") or "").strip():
            raise _Refus("Décrivez l'action à réaliser.")
        d.setdefault("statut", "À faire" if str(d.get("responsable") or "").strip() else "À attribuer")
        with self._verrou:
            num, ligne = self._edition().creer_action(self._champs_action(d, creation=True), self._aujourdhui())
            self._analyse, self._resultat, self._execute = None, None, False
        return {"num": num, "ligne": ligne}

    # ---- documents PDF ----
    @_protege
    def generer_document(self, nom: str) -> dict:
        """Crée le rapport de pilotage ou l'ordre du jour en PDF, puis l'ouvre."""
        if nom not in rapports.DOCUMENTS:
            raise _Refus("Document inconnu.")
        if self._analyse is None or self._donnees is None:
            raise _Refus("Lancez d'abord une analyse : le document est construit à partir de ses résultats.")
        dossier = Path(self._fab.dossier_documents())
        dossier.mkdir(parents=True, exist_ok=True)
        base = f"{rapports.DOCUMENTS[nom]} {self._analyse.jour.isoformat()}"
        html, pdf = dossier / f"{base}.html", dossier / f"{base}.pdf"
        html.write_text(rapports.rendre(nom, self._donnees), encoding="utf-8")
        try:
            self._fab.pdf(html, pdf)
        finally:
            html.unlink(missing_ok=True)
        self._fab.ouvrir_fichier(pdf)
        return {"chemin": str(pdf)}

    @_protege
    def creer_paquet(self) -> dict:
        """Crée l'archive d'installation à transmettre à un associé, puis ouvre son dossier."""
        archive = paquet.creer(Path(self._fab.dossier_documents()), self._aujourdhui())
        self._fab.ouvrir_fichier(archive.parent)
        return {"chemin": str(archive)}

    # ---- sauvegardes du plan ----
    @_protege
    def lister_sauvegardes(self) -> list[dict]:
        return [{"indice": i, "date": s.get("date", "").replace("T", " "),
                 "taches": [{"num": l["num"], "onglet": l["onglet"],
                             "avant": f"{l['avant'][0] or '—'} · {_pourcent(l['avant'][1])}",
                             "apres": f"{l['apres'][0]} · {l['apres'][1]} %"} for l in s.get("lignes", [])]}
                for i, s in reversed(list(enumerate(self._etat.sauvegardes())))]

    @_protege
    def restaurer_sauvegarde(self, indice: int) -> dict:
        sauvegardes = self._etat.sauvegardes()
        if not 0 <= int(indice) < len(sauvegardes):
            raise _Refus("Sauvegarde introuvable : rechargez la liste.")
        with self._verrou:
            n = self._service().restaurer_plan(sauvegardes[int(indice)])
            self._analyse, self._resultat, self._execute = None, None, False
        return {"taches": n}

    # ---- modèles ----
    @staticmethod
    def _verifier_nom(nom: str) -> None:
        if nom not in MODELES:
            raise _Refus(f"Modèle inconnu : {nom}")

    def _contexte(self, nom: str) -> dict:
        a = self._analyse
        if a is None:
            return contexte_exemple(nom, self._aujourdhui())
        if nom == "responsable":
            if not a.destinataires:
                return contexte_exemple(nom, a.jour)
            return contexte_responsable(a.destinataires[0], a.jour)
        return contexte_recap(a.stats, a.evolutions, a.anomalies, a.questions_sans_responsable,
                              a.modifs_plan, a.destinataires, a.jour)

    def _rendre(self, nom: str, objet: str, corps: str, contexte: dict) -> tuple[str, str]:
        erreur = self._moteur.valider(objet, corps)
        if erreur:
            raise _Refus(f"Modèle invalide ({erreur})")
        try:
            return self._moteur.rendre(nom, contexte, objet, corps)
        except TemplateError as e:
            raise _Refus(f"Modèle invalide : {e}")

    @_protege
    def lire_modele(self, nom: str) -> dict:
        self._verifier_nom(nom)
        objet, corps = self._moteur.source(nom)
        personnalise = any((self._moteur.perso / f).exists()
                           for f in (f"{nom}.objet.txt", f"{nom}.html"))
        return {"objet": objet, "corps": corps, "variables": VARIABLES[nom],
                "personnalise": personnalise}

    @_protege
    def apercu_modele(self, nom: str, objet: str, corps: str) -> dict:
        self._verifier_nom(nom)
        o, html = self._rendre(nom, objet, corps, self._contexte(nom))
        return {"objet": o, "html": html, "exemple": self._analyse is None}

    @_protege
    def enregistrer_modele(self, nom: str, objet: str, corps: str) -> dict:
        self._verifier_nom(nom)
        # Rendu d'essai sur les données d'exemple : refuse aussi les variables inconnues.
        self._rendre(nom, objet, corps, contexte_exemple(nom, self._aujourdhui()))
        self._moteur.enregistrer(nom, objet, corps)
        return self.lire_modele(nom)["donnees"]

    @_protege
    def retablir_modele(self, nom: str) -> dict:
        self._verifier_nom(nom)
        self._moteur.retablir(nom)
        return self.lire_modele(nom)["donnees"]

    # ---- équipe ----
    def _equipe(self) -> tuple[Equipe, object]:
        classeurs = self._fab.classeurs(self._graph())
        return Equipe(classeurs, self._id_pilotage()), classeurs

    def _roles(self, classeurs) -> dict[int, str]:
        """Rôle (fondateurs) ou fonction (conseils) par numéro de ligne ; vide si illisible."""
        roles: dict[int, str] = {}
        try:
            valeurs = classeurs.lire(self._id_pilotage(), "Annuaire")
            blocs = [(ENTETE_FONDATEURS, "Rôle", range(ENTETE_FONDATEURS + 1, 12))]
            entete = _entete_conseils(valeurs)
            if entete is not None:
                blocs.append((entete, "Fonction", range(entete + 1, len(valeurs) + 1)))
            for ligne_entete, col, lignes in blocs:
                try:
                    lettre = lettres_colonnes(valeurs, [col], "Annuaire", ligne_entete)[col]
                except ColonneIntrouvable:
                    continue
                i = Equipe._indice(lettre)
                for n in lignes:
                    roles[n] = _texte(_cellule(_ligne(valeurs, n), i))
        except Exception:
            self._journaliser("roles")
        return roles

    @_protege
    def lister_equipe(self) -> dict:
        equipe, classeurs = self._equipe()
        personnes = equipe.lister()
        roles = self._roles(classeurs)
        manquants = _noms_cites(self._analyse.anomalies) if self._analyse else []
        return {"personnes": [{"nom": p.nom, "groupe": p.groupe, "role": roles.get(p.ligne, ""),
                               "telephone": p.telephone or "", "email": p.email or "",
                               "ligne": p.ligne} for p in personnes],
                "manquants": manquants}

    @_protege
    def ajouter_personne(self, d: dict) -> dict:
        d = d or {}
        nom = str(d.get("nom") or "").strip()
        groupe = d.get("groupe")
        if not nom:
            raise _Refus("Le nom est obligatoire.")
        if groupe not in ("fondateur", "conseil"):
            raise _Refus("Choisissez le groupe : fondateur ou conseil/prestataire.")
        equipe, _ = self._equipe()
        p = equipe.ajouter(nom, groupe, d.get("email"), d.get("telephone"),
                           str(d.get("fonction") or ""))
        return {"nom": p.nom, "ligne": p.ligne}

    @_protege
    def modifier_personne(self, ligne: int, telephone: str | None, email: str | None,
                          nom: str | None = None) -> dict:
        equipe, _ = self._equipe()
        p = next((p for p in equipe.lister() if p.ligne == int(ligne)), None)
        if p is None or (nom is not None and p.nom != nom):
            raise _Refus("L'Annuaire a changé depuis l'affichage : rechargez l'équipe.")
        equipe.modifier(p, telephone, email)
        return {"nom": p.nom, "ligne": p.ligne}
