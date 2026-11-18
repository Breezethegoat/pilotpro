"""Coffre local pour le mot de passe d'application Gmail, chiffré par Windows (DPAPI)."""
from pathlib import Path

import msal_extensions


class Coffre:
    """Le secret n'est lisible que par la session Windows qui l'a enregistré."""

    def __init__(self, chemin: Path):
        self._chemin = Path(chemin)
        self._chemin.parent.mkdir(parents=True, exist_ok=True)
        self._p = msal_extensions.FilePersistenceWithDataProtection(str(self._chemin))

    def lire(self) -> str:
        if not self._chemin.exists():
            return ""
        try:
            return self._p.load() or ""
        except Exception:  # fichier illisible (autre session Windows, corruption)
            return ""

    def enregistrer(self, secret: str) -> None:
        self._p.save(secret)

    def effacer(self) -> None:
        self._chemin.unlink(missing_ok=True)
