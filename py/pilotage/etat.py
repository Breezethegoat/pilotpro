"""État local : réglages, instantané hebdomadaire et historique des envois."""
import json
import os
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from pathlib import Path

from pilotage.modeles import Action


@dataclass
class Reglages:
    client_id: str = ""
    classeurs: dict[str, dict] = field(default_factory=dict)
    seuil_proche: int = 3
    mode_test: bool = True
    adresse_test: str = ""
    email_fondateur: str = ""
    canal_envoi: str = "microsoft"  # "microsoft" (compte connecté) ou "gmail" (SMTP)
    gmail_adresse: str = ""
    escalade_jours: int = 7         # retard à partir duquel le fondateur est mis en copie (0 = jamais)
    escalade_ferme_jours: int = 14  # retard à partir duquel la relance devient ferme (0 = jamais)
    theme: str = "auto"             # apparence : "auto" (suit Windows), "clair" ou "sombre"
    auto_actif: bool = False        # passage hebdomadaire planifié (tâche Windows)
    auto_jour: str = "lundi"
    auto_heure: str = "08:00"
    auto_validation: bool = False   # True : analyse seule, l'envoi attend une validation dans l'application


SAUVEGARDES_MAX = 30
# Fichiers aussi rangés sur OneDrive (dossier « Applications/PilotPro ») : l'ordinateur et le téléphone
# partagent ainsi la mémoire des échéances, les décisions prises et l'état du dernier envoi.
PARTAGES = ("echeances.json", "instantane.json")
CHANGEMENTS_MAX = 500
DECISIONS_ECHEANCE = ("", "autorise", "violation")  # "" = à décider
TENDANCES_MAX = 156  # trois ans de passages hebdomadaires


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


class Etat:
    def __init__(self, dossier: Path):
        self.dossier = Path(dossier)
        self.dossier.mkdir(parents=True, exist_ok=True)
        self.partage = None          # Partage OneDrive, branché une fois connecté
        self.partage_erreur = ""     # dernière erreur du partage (le fichier local sert alors de repli)

    def _lire(self, nom: str):
        if self.partage is not None and nom in PARTAGES:
            try:
                distant = self.partage.lire(nom)
                self.partage_erreur = ""
                if distant is not None:
                    return distant
            except Exception as e:  # OneDrive injoignable : on travaille sur la copie locale
                self.partage_erreur = str(e)
        return self._lire_local(nom)

    def _lire_local(self, nom: str):
        chemin = self.dossier / nom
        if not chemin.exists():
            return None
        return json.loads(chemin.read_text(encoding="utf-8"))

    def _ecrire(self, nom: str, donnees) -> None:
        chemin = self.dossier / nom
        tmp = chemin.with_name(nom + ".tmp")
        tmp.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, chemin)
        if self.partage is not None and nom in PARTAGES:
            try:
                self.partage.ecrire(nom, donnees)
                self.partage_erreur = ""
            except Exception as e:
                self.partage_erreur = str(e)

    def reglages(self) -> Reglages:
        brut = self._lire("reglages.json")
        r = Reglages()
        if isinstance(brut, dict):
            for f in fields(Reglages):
                if f.name in brut:
                    setattr(r, f.name, brut[f.name])
        return r

    def enregistrer_reglages(self, r: Reglages) -> None:
        self._ecrire("reglages.json", asdict(r))

    def instantane(self) -> dict | None:
        return self._lire("instantane.json")

    def enregistrer_instantane(self, actions: list[Action], jour: date) -> None:
        self._ecrire("instantane.json", {
            "date": jour.isoformat(),
            "actions": {a.num: {
                "statut": a.statut,
                "responsables": list(a.responsables),
                "echeance": _iso(a.echeance),
                "date_realisation": _iso(a.date_realisation),
                "taches_plan": list(a.taches_plan),
            } for a in actions},
        })

    def historique(self) -> list[dict]:
        return self._lire("historique.json") or []

    def ajouter_historique(self, entree: dict) -> None:
        self._ecrire("historique.json", self.historique() + [entree])

    def tendances(self) -> list[dict]:
        return self._lire("tendances.json") or []

    def enregistrer_tendance(self, point: dict) -> None:
        """Un point par jour d'analyse (le dernier de la journée remplace le précédent)."""
        points = [p for p in self.tendances() if p.get("date") != point["date"]] + [point]
        self._ecrire("tendances.json", sorted(points, key=lambda p: p["date"])[-TENDANCES_MAX:])

    # ---- changements d'échéance ----
    def echeances(self) -> dict:
        """{"connues": {N°: échéance ISO ou None} ou None avant le premier relevé, "changements": [...]}."""
        brut = self._lire("echeances.json")
        if not isinstance(brut, dict):
            return {"connues": None, "changements": []}
        return {"connues": brut.get("connues"), "changements": list(brut.get("changements") or [])}

    def _ajouter_changement(self, e: dict, action: Action, avant: str | None, apres: str | None,
                            jour: date, decision: str = "", origine: str = "classeur") -> dict:
        c = {"id": max((x.get("id", 0) for x in e["changements"]), default=0) + 1,
             "num": action.num, "libelle": action.libelle, "responsables": list(action.responsables),
             "avant": avant, "apres": apres, "detecte_le": jour.isoformat(), "origine": origine,
             "decision": decision, "decide_le": jour.isoformat() if decision else "", "note": ""}
        e["changements"] = (e["changements"] + [c])[-CHANGEMENTS_MAX:]
        return c

    def relever_echeances(self, actions: list[Action], jour: date) -> list[dict]:
        """Compare l'échéance de chaque action à la dernière relevée. Tout écart est consigné comme
        changement « à décider ». Renvoie les changements nouvellement détectés."""
        e = self.echeances()
        connues = e["connues"]
        if connues is None:  # premier relevé : on repart du dernier envoi, s'il y en a eu un
            avant = (self.instantane() or {}).get("actions") or {}
            connues = {n: p["echeance"] for n, p in avant.items() if isinstance(p, dict) and "echeance" in p}
        nouveaux = []
        for a in actions:
            apres = _iso(a.echeance)
            if a.num in connues and (connues[a.num] or None) != apres:
                nouveaux.append(self._ajouter_changement(e, a, connues[a.num] or None, apres, jour))
            connues[a.num] = apres
        e["connues"] = connues
        self._ecrire("echeances.json", e)
        return nouveaux

    def noter_echeance_autorisee(self, action: Action, apres: date | None, jour: date) -> None:
        """Échéance changée par le fondateur dans l'application : consignée, et autorisée d'office."""
        e = self.echeances()
        self._ajouter_changement(e, action, _iso(action.echeance), _iso(apres), jour,
                                 decision="autorise", origine="application")
        e["connues"] = dict(e["connues"] or {}, **{action.num: _iso(apres)})
        self._ecrire("echeances.json", e)

    def decider_echeance(self, ident: int, decision: str, note: str, jour: date) -> None:
        if decision not in DECISIONS_ECHEANCE:
            raise ValueError("Décision inconnue.")
        e = self.echeances()
        c = next((x for x in e["changements"] if x.get("id") == ident), None)
        if c is None:
            raise ValueError("Changement d'échéance introuvable.")
        c.update(decision=decision, decide_le=jour.isoformat() if decision else "", note=(note or "").strip())
        self._ecrire("echeances.json", e)

    def sauvegardes(self) -> list[dict]:
        return self._lire("sauvegardes.json") or []

    def ajouter_sauvegarde(self, entree: dict) -> None:
        self._ecrire("sauvegardes.json", (self.sauvegardes() + [entree])[-SAUVEGARDES_MAX:])
