"""Écriture dans les classeurs depuis l'application : modifier une ligne, créer une action."""
import re
from datetime import date

from pilotage.classeurs import Classeurs
from pilotage.lecture import LIGNE_ENTETE, _cellule, _indexer, _lettre, _ligne, _texte
from pilotage.textes import normaliser

FORMAT_DATE = "dd/mm/yyyy"
_ORIGINE_EXCEL = date(1899, 12, 30)
STATUTS_ACTION = ["À attribuer", "À faire", "En cours", "Bloquée", "Réalisée", "Annulée"]
PRIORITES = ["Haute", "Normale", "Basse"]
STATUTS_QUESTION = ["Ouverte", "En instruction", "Reportée", "Tranchée"]


class LigneModifiee(ValueError):
    """La ligne visée ne contient plus l'élément attendu (classeur modifié entre-temps)."""


def date_iso(texte: str | None) -> date | None:
    """« 2026-11-20 » (champ date de l'interface) -> date ; vide -> None."""
    t = (texte or "").strip()
    if not t:
        return None
    try:
        return date.fromisoformat(t)
    except ValueError:
        raise ValueError(f"Date invalide : {t}") from None


def _texte_excel(valeur: str) -> str:
    """Excel interprète « =x », « +237… », « -x » : l'apostrophe initiale force le texte."""
    v = str(valeur).strip()
    return "'" + v if v and v[0] in "+-=@" else v


def numero_suivant(numeros: list[str]) -> str:
    """Numéro qui suit le plus grand existant : « A-2026-015 » -> « A-2026-016 »."""
    meilleur = None
    for n in numeros:
        m = re.match(r"^(.*?)(\d+)$", n.strip())
        if m and (meilleur is None or int(m.group(2)) > int(meilleur.group(2))):
            meilleur = m
    if meilleur is None:
        return "A-001"
    suite = str(int(meilleur.group(2)) + 1).zfill(len(meilleur.group(2)))
    return meilleur.group(1) + suite


class Edition:
    def __init__(self, classeurs: Classeurs, item_id: str):
        self._c, self._id = classeurs, item_id

    def _ecrire(self, onglet: str, lettre: str, ligne: int, valeur) -> None:
        if isinstance(valeur, date):
            self._c.ecrire(self._id, onglet, f"{lettre}{ligne}", [[(valeur - _ORIGINE_EXCEL).days]],
                           format=FORMAT_DATE)
        else:
            self._c.ecrire(self._id, onglet, f"{lettre}{ligne}",
                           [["" if valeur is None else _texte_excel(valeur)]])

    def modifier(self, onglet: str, num: str, ligne: int, champs: dict) -> None:
        """Écrit `champs` ({en-tête: valeur}) sur la ligne de `num`, après avoir vérifié qu'elle
        contient toujours ce numéro. Une valeur `date` est écrite comme date Excel ; None vide la cellule."""
        valeurs = self._c.lire(self._id, onglet)
        idx = _indexer(_ligne(valeurs, LIGNE_ENTETE), ["N°", *champs], onglet)
        if normaliser(_texte(_cellule(_ligne(valeurs, ligne), idx["N°"]))) != normaliser(num):
            raise LigneModifiee(f"« {num} » n'est plus à la ligne {ligne} de l'onglet « {onglet} » : "
                                "relancez l'analyse.")
        for entete, valeur in champs.items():
            self._ecrire(onglet, _lettre(idx[entete]), ligne, valeur)

    def creer_action(self, champs: dict, jour: date) -> tuple[str, int]:
        """Ajoute une action sur la première ligne libre ; renvoie (numéro, ligne).
        `champs` : en-têtes parmi Action, Livrable attendu, Tâche du plan, Responsable,
        Échéance, Priorité, Statut."""
        onglet = "Actions"
        valeurs = self._c.lire(self._id, onglet)
        idx = _indexer(_ligne(valeurs, LIGNE_ENTETE), ["N°", "Action", "Date de création", *champs], onglet)
        numeros, libre = [], None
        for n in range(LIGNE_ENTETE + 1, len(valeurs) + 1):
            ligne = valeurs[n - 1]
            num, libelle = _texte(_cellule(ligne, idx["N°"])), _texte(_cellule(ligne, idx["Action"]))
            if libelle:
                numeros.append(num)
            elif libre is None:
                libre = (n, num)  # ligne pré-numérotée mais vide, ou première ligne vide
        if libre is None:
            libre = (len(valeurs) + 1, "")
        ligne, num = libre
        if not num:
            num = numero_suivant(numeros)
            self._ecrire(onglet, _lettre(idx["N°"]), ligne, num)
        self._ecrire(onglet, _lettre(idx["Date de création"]), ligne, jour)
        for entete, valeur in champs.items():
            if valeur not in (None, ""):
                self._ecrire(onglet, _lettre(idx[entete]), ligne, valeur)
        return num, ligne
