"""Lecture et écriture des classeurs Excel via Microsoft Graph."""
import re
from urllib.parse import quote

from pilotage.graph import Graph
from pilotage.textes import normaliser


LIGNES_MAX = 2000
PLAGE_LECTURE = f"A1:AD{LIGNES_MAX}"
PROFONDEUR_MAX = 2   # racine + 2 niveaux de sous-dossiers
DOSSIERS_MAX = 40    # borne le nombre d'appels Graph lors d'une recherche


def _compact(texte: str) -> str:
    """Forme de comparaison : minuscules, sans accents, lettres et chiffres seulement."""
    return re.sub(r"[^a-z0-9]", "", normaliser(texte))


def _litteral(texte: str) -> str:
    """Littéral OData entre apostrophes : apostrophes doublées, puis encodage URL."""
    return quote(texte.replace("'", "''"), safe="")


class Classeurs:
    def __init__(self, graph: Graph):
        self._g = graph

    def _onglet(self, item_id: str, onglet: str) -> str:
        return f"/me/drive/items/{item_id}/workbook/worksheets('{_litteral(onglet)}')"

    def lire(self, item_id: str, onglet: str, plage: str = PLAGE_LECTURE) -> list[list]:
        rep = self._g.get(f"{self._onglet(item_id, onglet)}/range(address='{plage}')?$select=values")
        valeurs = rep.get("values") or []
        derniere = re.search(r"(\d+)$", plage)
        # Garde-fou : une donnée sur la dernière ligne lue (1re colonne N°/nom non vide) = plage trop courte.
        # Les cellules "" des formules ne comptent pas, seule la 1re colonne est testée.
        if derniere and len(valeurs) >= int(derniere.group(1)) and valeurs[-1] \
                and str(valeurs[-1][0] if valeurs[-1][0] is not None else "").strip():
            raise ValueError(f"L'onglet « {onglet} » dépasse {derniere.group(1)} lignes : "
                             "agrandissez la plage de lecture.")
        return valeurs

    def ecrire(self, item_id: str, onglet: str, adresse: str, valeurs: list[list],
               format: str | None = None) -> None:
        corps: dict = {"values": valeurs}
        if format:  # même format pour toute la plage (ex. « dd/mm/yyyy » pour une date)
            corps["numberFormat"] = [[format] * len(ligne) for ligne in valeurs]
        self._g.patch(f"{self._onglet(item_id, onglet)}/range(address='{adresse}')", corps)

    def lien(self, item_id: str) -> str:
        """Adresse web du classeur (Excel en ligne)."""
        return self._g.get(f"/me/drive/items/{item_id}?$select=webUrl").get("webUrl") or ""

    def onglets(self, item_id: str) -> list[str]:
        rep = self._g.get(f"/me/drive/items/{item_id}/workbook/worksheets?$select=name")
        return [w["name"] for w in rep.get("value", [])]

    def _enfants(self, chemin: str):
        """Tous les éléments d'un dossier, en suivant la pagination."""
        while chemin:
            rep = self._g.get(chemin)
            yield from rep.get("value", [])
            chemin = rep.get("@odata.nextLink")

    def chercher(self, texte: str) -> list[dict]:
        """Classeurs .xlsx dont le nom contient `texte` (sans tenir compte des accents,
        majuscules, espaces ni « _ »). Parcourt la racine et les dossiers jusqu'à
        PROFONDEUR_MAX niveaux : la recherche Graph du OneDrive personnel ne trouve
        pas les fichiers de façon fiable."""
        cle = _compact(texte)
        trouves, a_visiter, visites = [], [("/me/drive/root/children", 0)], 0
        while a_visiter and visites < DOSSIERS_MAX:
            chemin, profondeur = a_visiter.pop(0)
            visites += 1
            for i in self._enfants(f"{chemin}?$top=200&$select=id,name,file,folder,parentReference"):
                nom = i.get("name", "")
                if "folder" in i and profondeur < PROFONDEUR_MAX:
                    a_visiter.append((f"/me/drive/items/{i['id']}/children", profondeur + 1))
                elif nom.lower().endswith(".xlsx") and cle in _compact(nom):
                    trouves.append({"id": i["id"], "nom": nom,
                                    "chemin": (i.get("parentReference") or {}).get("path") or ""})
        return trouves

    def compte(self) -> str:
        rep = self._g.get("/me")
        return rep.get("mail") or rep.get("userPrincipalName") or ""
