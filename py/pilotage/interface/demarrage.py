"""Assemblage des vraies dépendances de l'interface."""
import os
import subprocess
import webbrowser
from pathlib import Path

from pilotage import automate, rapports
from pilotage.classeurs import Classeurs
from pilotage.coffre import Coffre
from pilotage.connexion import Connexion
from pilotage.envoi import Envoi, EnvoiGmail
from pilotage.graph import Graph


class Fabrique:
    """Crée les objets qui parlent à Microsoft et à Windows ; remplacée par des faux dans les tests."""

    def __init__(self, racine: Path | None = None):
        self.racine = Path(racine) if racine else Path(__file__).resolve().parents[2]

    def planifier(self, jour: str, heure: str) -> None:
        automate.planifier(self.racine, jour, heure)

    def deplanifier(self) -> None:
        automate.deplanifier()

    def prochaine_execution(self) -> str:
        return automate.prochaine_execution()

    def dossier_documents(self) -> Path:
        """Dossier des PDF produits : Documents\\PilotPro de l'utilisateur."""
        return Path.home() / "Documents" / "PilotPro"

    def pdf(self, html: Path, pdf: Path) -> None:
        rapports.html_vers_pdf(html, pdf)

    def ouvrir_fichier(self, chemin: Path) -> None:
        os.startfile(str(chemin))  # ouvre avec l'application par défaut de Windows

    def connexion(self, client_id: str, dossier: Path) -> Connexion:
        return Connexion(client_id, dossier)

    def graph(self, connexion: Connexion) -> Graph:
        return Graph(connexion.jeton)

    def classeurs(self, graph: Graph) -> Classeurs:
        return Classeurs(graph)

    def partage(self, graph: Graph):
        from pilotage.partage import Partage
        return Partage(graph)

    def envoi(self, graph: Graph, mode_test: bool, adresse_test: str) -> Envoi:
        return Envoi(graph, mode_test, adresse_test)

    def envoi_gmail(self, adresse: str, mot_de_passe: str, mode_test: bool, adresse_test: str) -> EnvoiGmail:
        return EnvoiGmail(adresse, mot_de_passe, mode_test, adresse_test)

    def coffre(self, dossier: Path) -> Coffre:
        return Coffre(Path(dossier) / "gmail.bin")

    def ouvrir_navigateur(self, url: str) -> None:
        """Ouvre la page dans le navigateur par défaut (seulement des liens https)."""
        if not url.startswith("https://"):
            raise ValueError(f"Lien refusé : {url}")
        if not webbrowser.open(url):
            raise OSError("Aucun navigateur n'a pu être ouvert.")

    def copier(self, texte: str) -> None:
        """Copie le texte dans le presse-papiers Windows."""
        subprocess.run(["clip"], input=texte.encode("ascii", "ignore"), check=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def creer_api(racine: Path):
    from pilotage.interface.api import Api
    return Api(Path(racine) / "donnees", Fabrique(racine))
