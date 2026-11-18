"""Paquet d'installation : une archive .zip du programme, sans aucune donnée personnelle."""
import zipfile
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
# Ce qui part dans le paquet. Jamais « donnees/ » (jeton, mots de passe, réglages), ni « .venv/ », ni « .git/ ».
CONTENU = ["pilotage", "outils", "docs/guide-azure.md", "lancer.pyw", "requirements.txt", "README.md",
           "Installer PilotPro.bat"]
EXCLUS = {"__pycache__", "donnees", ".venv", ".git", ".claude", ".pytest_cache"}


def _fichiers(racine: Path):
    for entree in CONTENU:
        chemin = racine / entree
        if chemin.is_file():
            yield chemin
        elif chemin.is_dir():
            for f in sorted(chemin.rglob("*")):
                if f.is_file() and not EXCLUS.intersection(f.relative_to(racine).parts) and f.suffix != ".pyc":
                    yield f


def creer(dossier_sortie: Path, jour: date, racine: Path = RACINE) -> Path:
    """Crée « PilotPro-installation-AAAA-MM-JJ.zip » dans `dossier_sortie` et renvoie son chemin."""
    dossier_sortie = Path(dossier_sortie)
    dossier_sortie.mkdir(parents=True, exist_ok=True)
    archive = dossier_sortie / f"PilotPro-installation-{jour.isoformat()}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for f in _fichiers(Path(racine)):
            z.write(f, Path("PilotPro") / f.relative_to(racine))
    return archive
