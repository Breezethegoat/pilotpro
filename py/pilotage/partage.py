"""Petits fichiers partagés entre l'ordinateur et le téléphone, rangés sur OneDrive.

Ils vont dans le dossier propre à l'application (« Applications/PilotPro » dans OneDrive),
jamais à côté des classeurs. Aucun mot de passe n'y est écrit.
"""
import json

from pilotage.graph import ErreurGraph, Graph

DOSSIER = "/me/drive/special/approot"


class Partage:
    def __init__(self, graph: Graph):
        self._g = graph

    def lire(self, nom: str):
        """Contenu JSON du fichier, ou None s'il n'existe pas encore."""
        try:
            meta = self._g.get(f"{DOSSIER}:/{nom}")
        except ErreurGraph as e:
            if e.statut == 404:
                return None
            raise
        return json.loads(self._g.telecharger(meta["@microsoft.graph.downloadUrl"]))

    def ecrire(self, nom: str, donnees) -> None:
        self._g.deposer(f"{DOSSIER}:/{nom}:/content",
                        json.dumps(donnees, ensure_ascii=False, indent=1).encode("utf-8"))
