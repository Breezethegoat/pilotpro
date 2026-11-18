"""Documents à partager : rapport de pilotage et ordre du jour de réunion, en PDF.

Les documents sont rendus en HTML (modèles Jinja2) puis convertis en PDF par Microsoft Edge
en mode sans fenêtre : aucune bibliothèque PDF à installer.
"""
import subprocess
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

DOCUMENTS = {"rapport": "Rapport de pilotage", "reunion": "Ordre du jour"}
_MODELES = Path(__file__).parent / "modeles_defaut"
_EDGE = [Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
         Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe")]
_ENV = Environment(loader=FileSystemLoader(str(_MODELES)), autoescape=True, undefined=StrictUndefined)
_ENV.filters["pourcent"] = lambda v: "—" if v is None else f"{round(v * 100)} %"


def contexte(donnees: dict) -> dict:
    """Regroupe les données d'une analyse (celles de l'interface) pour les deux documents."""
    actions = donnees["actions"]
    ouvertes = [a for a in actions if a["ouverte"]]
    retard = sorted((a for a in ouvertes if a["en_retard"]), key=lambda a: -a["jours_retard"])
    risques = [r for r in donnees["risques"] if r["statut"] != "Clos"]
    volets: dict[str, dict] = {}
    for t in donnees["plan"]:
        v = volets.setdefault(t["onglet"], {"nom": t["onglet"], "taches": 0, "realisees": 0, "somme": 0, "retard": 0})
        v["taches"] += 1
        v["realisees"] += t["statut"] == "Réalisée"
        v["somme"] += t["avancement"]
        v["retard"] += bool(t["echeance"] and t["echeance"] < donnees["aujourdhui"]
                            and t["statut"] not in ("Réalisée", "Annulée"))
    for v in volets.values():
        v["avancement"] = round(v["somme"] / v["taches"]) if v["taches"] else 0
    questions = [q for q in donnees["questions"] if q["statut"] in ("Ouverte", "En instruction")]
    return {
        "date": donnees["date"], "stats": donnees["stats"],
        "retard": retard,
        "bloquees": [a for a in ouvertes if a["statut"] == "Bloquée"],
        "proches": [a for a in ouvertes if a["proche"]],
        "a_attribuer": [a for a in ouvertes if not a["responsables"]],
        "responsables": sorted(donnees["stats"]["par_responsable"].items(),
                               key=lambda x: (-x[1]["en_retard"], x[0])),
        "volets": list(volets.values()),
        "risques_majeurs": sorted((r for r in risques if r["niveau"] in ("Critique", "Élevé")),
                                  key=lambda r: -((r["p"] or 0) * (r["i"] or 0))),
        "nb_risques": len(risques),
        "questions": [q for q in questions if q["responsables"]],
        "questions_sans": [q for q in questions if not q["responsables"]],
        "evolutions": donnees["evolutions"],
        "tendances": donnees["tendances"][-8:],
    }


def rendre(nom: str, donnees: dict) -> str:
    if nom not in DOCUMENTS:
        raise ValueError(f"Document inconnu : {nom}")
    return _ENV.get_template(f"{nom}.html").render(contexte(donnees))


def html_vers_pdf(html: Path, pdf: Path) -> None:
    edge = next((p for p in _EDGE if p.exists()), None)
    if edge is None:
        raise ValueError("Microsoft Edge est introuvable : impossible de créer le PDF.")
    pdf.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profil:  # profil Edge jetable
        subprocess.run([str(edge), "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--user-data-dir={profil}", f"--print-to-pdf={pdf}", html.as_uri()],
                       capture_output=True, timeout=90, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if not pdf.exists():
        raise ValueError("Le PDF n'a pas pu être créé (Edge n'a rien produit).")
