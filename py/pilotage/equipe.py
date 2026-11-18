"""Gestion de l'annuaire de l'équipe (onglet Annuaire du classeur de pilotage)."""
from pilotage.classeurs import Classeurs
from pilotage.lecture import (ColonneIntrouvable, _cellule, _ligne, _texte, lettres_colonnes, lire_annuaire)
from pilotage.modeles import Personne
from pilotage.textes import email_valide, normaliser

ONGLET = "Annuaire"
ENTETE_FONDATEURS = 5
PREMIERE_LIGNE_FONDATEUR, DERNIERE_LIGNE_FONDATEUR = 6, 11
MSG_EMAIL = "Adresse e-mail invalide"


class FondateursComplets(Exception):
    pass


def _entete_conseils(valeurs: list[list]) -> int | None:
    return next((n for n in range(DERNIERE_LIGNE_FONDATEUR + 1, len(valeurs) + 1)
                 if normaliser(_texte(_cellule(_ligne(valeurs, n), 0))) == "nom ou structure"), None)


def _texte_excel(valeur: str) -> str:
    """Excel interprète « 0612… », « +237… », « -x », « =x » : l'apostrophe initiale force le texte."""
    v = valeur.strip()
    return "'" + v if v and (v[0].isdigit() or v[0] in "+-=") else v


def _verifier_email(email: str | None) -> None:
    if email and email.strip() and not email_valide(email.strip()):
        raise ValueError(MSG_EMAIL)


class Equipe:
    def __init__(self, classeurs: Classeurs, item_id: str):
        self._c = classeurs
        self._id = item_id

    def _lire(self) -> list[list]:
        return self._c.lire(self._id, ONGLET)

    def _ecrire(self, cellule: str, valeur: str) -> None:
        self._c.ecrire(self._id, ONGLET, cellule, [[valeur]])

    def lister(self) -> list[Personne]:
        return lire_annuaire(self._lire())

    def modifier(self, p: Personne, telephone: str | None, email: str | None) -> None:
        _verifier_email(email)
        valeurs = self._lire()
        if p.groupe == "conseil":
            entete = _entete_conseils(valeurs)
            if entete is None:
                raise ColonneIntrouvable("Bloc « Conseils et prestataires » introuvable dans l'Annuaire")
            col_nom = "Nom ou structure"
        else:
            entete, col_nom = ENTETE_FONDATEURS, "Nom et prénom"
        col = lettres_colonnes(valeurs, [col_nom, "Téléphone", "E-mail"], ONGLET, entete)
        if normaliser(_texte(self._cell(valeurs, p.ligne, col[col_nom]))) != normaliser(p.nom):
            raise ValueError(f"La ligne de « {p.nom} » a changé dans l'Annuaire : rechargez l'équipe.")
        if telephone is not None:
            self._ecrire(f"{col['Téléphone']}{p.ligne}", _texte_excel(telephone))
        if email is not None:
            self._ecrire(f"{col['E-mail']}{p.ligne}", email.strip())

    def ajouter(self, nom: str, groupe: str, email: str | None, telephone: str | None,
                fonction: str = "") -> Personne:
        _verifier_email(email)
        valeurs = self._lire()
        if groupe == "fondateur":
            col_nom = "Nom et prénom"
            col = lettres_colonnes(valeurs, [col_nom, "Téléphone", "E-mail"], ONGLET, ENTETE_FONDATEURS)
            ligne = next((n for n in range(PREMIERE_LIGNE_FONDATEUR, DERNIERE_LIGNE_FONDATEUR + 1)
                          if not _texte(self._cell(valeurs, n, col[col_nom]))), None)
            if ligne is None:
                raise FondateursComplets("Les 6 places de fondateurs sont occupées")
            fonction_a_ecrire = False
        else:
            col_nom = "Nom ou structure"
            entete = _entete_conseils(valeurs)
            if entete is None:
                raise ValueError("Bloc « Conseils et prestataires » introuvable dans l'Annuaire")
            col = lettres_colonnes(valeurs, [col_nom, "Fonction", "Téléphone", "E-mail"], ONGLET, entete)
            ligne = self._ligne_conseil(valeurs, entete, col, fonction)
            fonction_a_ecrire = bool(fonction.strip()) and not _texte(self._cell(valeurs, ligne, col["Fonction"]))
        self._ecrire(f"{col[col_nom]}{ligne}", _texte_excel(nom))
        if fonction_a_ecrire:
            self._ecrire(f"{col['Fonction']}{ligne}", _texte_excel(fonction))
        if telephone and telephone.strip():
            self._ecrire(f"{col['Téléphone']}{ligne}", _texte_excel(telephone))
        if email and email.strip():
            self._ecrire(f"{col['E-mail']}{ligne}", email.strip())
        return Personne(nom=nom.strip(), email=(email or "").strip() or None,
                        telephone=(telephone or "").strip() or None, groupe=groupe, ligne=ligne)

    @staticmethod
    def _cell(valeurs: list[list], n: int, lettre: str):
        return _cellule(_ligne(valeurs, n), Equipe._indice(lettre))

    def _ligne_conseil(self, valeurs, entete: int, col: dict[str, str], fonction: str) -> int:
        fin = entete
        while fin < len(valeurs) and any(_texte(c) for c in valeurs[fin]):
            fin += 1
        i_fonction = self._indice(col["Fonction"])
        i_nom = self._indice(col["Nom ou structure"])
        voulue = normaliser(fonction)
        sans_nom, vides = [], []
        for n in range(entete + 1, fin + 1):
            ligne = _ligne(valeurs, n)
            if _texte(_cellule(ligne, i_nom)):
                continue
            if any(_texte(c) for i, c in enumerate(ligne) if i != i_fonction):
                continue
            f = normaliser(_texte(_cellule(ligne, i_fonction)))
            if f:
                sans_nom.append((n, f))
            else:
                vides.append(n)
        if voulue:
            for n, f in sans_nom:
                if f == voulue:
                    return n
        return vides[0] if vides else fin + 1

    @staticmethod
    def _indice(lettre: str) -> int:
        i = 0
        for c in lettre:
            i = i * 26 + ord(c) - 64
        return i - 1
