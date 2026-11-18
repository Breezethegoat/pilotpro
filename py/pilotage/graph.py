"""Client minimal pour Microsoft Graph."""
import time
from typing import Callable

import requests

BASE = "https://graph.microsoft.com/v1.0"
ESSAIS_MAX = 3
ATTENTE_DEFAUT = 5.0


class ErreurGraph(Exception):
    def __init__(self, statut: int, message: str):
        super().__init__(f"Graph {statut} : {message}")
        self.statut = statut
        self.message = message


class ReconnexionRequise(Exception):
    pass


def _message(rep) -> str:
    try:
        corps = rep.json()
        msg = corps["error"]["message"]
        if msg:
            return str(msg)
    except Exception:
        pass
    return rep.text or ""


class Graph:
    def __init__(self, fournisseur_jeton: Callable[[], str | None],
                 session: requests.Session | None = None,
                 attente: Callable[[float], None] = time.sleep):
        self._jeton = fournisseur_jeton
        self._session = session or requests.Session()
        self._attente = attente

    def _requete(self, methode: str, chemin: str, corps: dict | None = None,
                 brut: bytes | None = None) -> dict | None:
        jeton = self._jeton()
        if not jeton:
            raise ReconnexionRequise("Reconnexion Microsoft requise.")
        entetes = {"Authorization": f"Bearer {jeton}"}
        if corps is not None or brut is not None:
            entetes["Content-Type"] = "application/json"
        # Les liens de pagination (@odata.nextLink) sont des URL complètes.
        url = chemin if chemin.startswith(BASE + "/") else BASE + chemin
        for essai in range(1, ESSAIS_MAX + 1):
            rep = self._session.request(methode, url, headers=entetes, json=corps, data=brut, timeout=30)
            if rep.status_code in (429, 503) and essai < ESSAIS_MAX:
                try:
                    delai = float(rep.headers.get("Retry-After", ATTENTE_DEFAUT))
                except (TypeError, ValueError):
                    delai = ATTENTE_DEFAUT
                self._attente(delai)
                continue
            if rep.status_code >= 400:
                raise ErreurGraph(rep.status_code, _message(rep))
            if rep.status_code == 204 or not (rep.text or "").strip():
                return None
            return rep.json()
        raise AssertionError("inatteignable")

    def get(self, chemin: str) -> dict:
        return self._requete("GET", chemin) or {}

    def patch(self, chemin: str, corps: dict) -> dict:
        return self._requete("PATCH", chemin, corps) or {}

    def post(self, chemin: str, corps: dict) -> dict | None:
        return self._requete("POST", chemin, corps)

    def deposer(self, chemin: str, contenu: bytes) -> dict:
        """Écrit le contenu d'un fichier (PUT …:/content)."""
        return self._requete("PUT", chemin, brut=contenu) or {}

    def telecharger(self, url: str) -> str:
        """Lit un fichier par son lien de téléchargement temporaire (déjà autorisé : pas de jeton)."""
        rep = self._session.request("GET", url, timeout=30)
        if rep.status_code >= 400:
            raise ErreurGraph(rep.status_code, _message(rep))
        return rep.text
