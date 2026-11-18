"""Connexion Microsoft (MSAL, flux code d'appareil) avec cache de jeton chiffré."""
from pathlib import Path

import msal
import msal_extensions

AUTORITE = "https://login.microsoftonline.com/consumers"
SCOPES = ["Files.ReadWrite", "Mail.Send", "User.Read"]


class Connexion:
    def __init__(self, client_id: str, dossier: Path):
        dossier = Path(dossier)
        dossier.mkdir(parents=True, exist_ok=True)
        persistance = msal_extensions.FilePersistenceWithDataProtection(str(dossier / "jeton.bin"))
        self._cache = msal_extensions.PersistedTokenCache(persistance)
        self._app = msal.PublicClientApplication(
            client_id, authority=AUTORITE, token_cache=self._cache)

    def _premier_compte(self):
        comptes = self._app.get_accounts()
        return comptes[0] if comptes else None

    def jeton(self) -> str | None:
        compte = self._premier_compte()
        if compte is None:
            return None
        res = self._app.acquire_token_silent(SCOPES, account=compte)
        if not res or "access_token" not in res:
            return None
        return res["access_token"]

    def demarrer(self) -> dict:
        flux = self._app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flux:
            raise RuntimeError(flux.get("error_description") or "Impossible de démarrer la connexion.")
        return flux

    def terminer(self, flux: dict) -> str:
        res = self._app.acquire_token_by_device_flow(flux)
        if "access_token" not in res:
            raise RuntimeError(res.get("error_description") or res.get("error") or "Connexion échouée.")
        claims = res.get("id_token_claims") or {}
        return claims.get("preferred_username") or claims.get("email") or self.compte() or ""

    def compte(self) -> str | None:
        compte = self._premier_compte()
        return compte["username"] if compte else None

    def deconnecter(self) -> None:
        for compte in self._app.get_accounts():
            self._app.remove_account(compte)
