"""Lecture des feuilles Excel (tableaux 2-D renvoyés par Graph) en objets de domaine."""
import re
from datetime import date

from pilotage.modeles import Action, Anomalie, Personne, Question, Risque, Tache
from pilotage.textes import date_depuis_excel, normaliser, separer_codes, separer_noms

LIGNE_ENTETE = 5


class ColonneIntrouvable(Exception):
    pass


def _lettre(i: int) -> str:
    """Index de colonne 0-based -> lettre Excel (A, B, ..., Z, AA...)."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


# Autres intitulés acceptés pour un en-tête (forme normalisée), essayés dans l'ordre.
SYNONYMES = {
    "responsable": ["realisateur"],          # onglet Actions en ligne
    "tache": ["besoin couvert", "domaine"],  # onglet 5-Prestataires du plan
}


def _indexer(en_tetes_ligne: list, requis: list[str], onglet: str) -> dict[str, int]:
    """Associe chaque en-tête demandé à l'index de sa première occurrence (ou d'un synonyme)."""
    positions: dict[str, int] = {}
    for i, c in enumerate(en_tetes_ligne):
        positions.setdefault(normaliser(c), i)
    res = {}
    for e in requis:
        n = normaliser(e)
        trouve = next((c for c in [n, *SYNONYMES.get(n, [])] if c in positions), None)
        if trouve is None:
            raise ColonneIntrouvable(f"Colonne « {e} » introuvable dans l'onglet « {onglet} »")
        res[e] = positions[trouve]
    return res


def _ligne(valeurs: list[list], n: int) -> list:
    return valeurs[n - 1] if 0 < n <= len(valeurs) else []


def lettres_colonnes(valeurs: list[list], en_tetes: list[str], onglet: str,
                     ligne_entete: int = LIGNE_ENTETE) -> dict[str, str]:
    idx = _indexer(_ligne(valeurs, ligne_entete), en_tetes, onglet)
    return {e: _lettre(i) for e, i in idx.items()}


def _texte(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _opt(v) -> str | None:
    t = _texte(v)
    return t or None


def _cellule(ligne: list, i: int):
    return ligne[i] if i < len(ligne) else ""


def _date(v, num: str, en_tete: str, anomalies: list[Anomalie]) -> date | None:
    try:
        return date_depuis_excel(v)
    except ValueError:
        anomalies.append(Anomalie("date", f"{num} : date illisible « {_texte(v)} » ({en_tete})"))
        return None


def _date_souple(v) -> date | None:
    """Date d'une colonne facultative : une valeur illisible est ignorée, sans anomalie."""
    try:
        return date_depuis_excel(v)
    except ValueError:
        return None


def _note(v) -> int | None:
    """Note de 1 à 5 (probabilité, impact) ; None si absente ou hors échelle."""
    try:
        n = int(float(_texte(v).replace(",", ".")))
    except ValueError:
        return None
    return n if 1 <= n <= 5 else None


def _lire(valeurs, onglet, requis, construire, optionnels=()):
    """`optionnels` : colonnes lues si elles existent ; sinon la valeur est ""."""
    entete = _ligne(valeurs, LIGNE_ENTETE)
    idx = _indexer(entete, requis, onglet)
    for e in optionnels:
        try:
            idx.update(_indexer(entete, [e], onglet))
        except ColonneIntrouvable:
            pass
    objets, anomalies = [], []
    for n in range(LIGNE_ENTETE + 1, len(valeurs) + 1):
        ligne = valeurs[n - 1]
        get = lambda e, ligne=ligne: _cellule(ligne, idx[e]) if e in idx else ""
        num = _texte(get("N°"))
        if not num:
            continue
        objet = construire(num, n, get, anomalies)
        if objet is not None:
            objets.append(objet)
    return objets, anomalies


def lire_actions(valeurs: list[list], onglet: str = "Actions"):
    req = ["N°", "Date de création", "Tâche du plan", "Action", "Livrable attendu", "Responsable",
           "Échéance", "Priorité", "Statut", "Date de réalisation"]

    def f(num, n, get, ano):
        if not _texte(get("Action")) and not _texte(get("Statut")):
            return None  # ligne pré-numérotée encore vide
        return Action(
            num=num,
            date_creation=_date(get("Date de création"), num, "Date de création", ano),
            taches_plan=separer_codes(_texte(get("Tâche du plan"))),
            libelle=_texte(get("Action")),
            livrable=_texte(get("Livrable attendu")),
            responsables=separer_noms(_texte(get("Responsable"))),
            echeance=_date(get("Échéance"), num, "Échéance", ano),
            priorite=_texte(get("Priorité")),
            statut=_texte(get("Statut")),
            date_realisation=_date(get("Date de réalisation"), num, "Date de réalisation", ano),
            ligne=n)
    return _lire(valeurs, onglet, req, f)


def lire_taches(valeurs: list[list], onglet: str):
    req = ["N°", "Tâche", "Statut", "Avancement saisi (%)", "Date de réalisation"]

    def f(num, n, get, ano):
        av = get("Avancement saisi (%)")
        if isinstance(av, (int, float)) and not isinstance(av, bool):
            avancement = float(av)
        else:
            try:
                avancement = float(_texte(av).replace(",", ".").rstrip("%").strip())
            except ValueError:
                avancement = None
        return Tache(
            num=num, libelle=_texte(get("Tâche")), onglet=onglet, ligne=n,
            statut=_texte(get("Statut")), avancement=avancement,
            date_realisation=_date(get("Date de réalisation"), num, "Date de réalisation", ano),
            responsable=_texte(get("Responsable")),
            debut=_date_souple(get("Début prévu")), echeance=_date_souple(get("Échéance")),
            fin_phase=_date_souple(get("Fin de phase")))
    return _lire(valeurs, onglet, req, f, optionnels=["Responsable", "Début prévu", "Échéance", "Fin de phase"])


def lire_risques(valeurs: list[list], onglet: str = "Registre"):
    req = ["N°", "Risque", "Niveau", "Propriétaire", "Échéance des mesures",
           "Avancement des mesures", "Statut du risque"]

    def f(num, n, get, ano):
        return Risque(
            num=num, intitule=_texte(get("Risque")), niveau=_texte(get("Niveau")),
            proprietaires=separer_noms(_texte(get("Propriétaire"))),
            echeance=_date(get("Échéance des mesures"), num, "Échéance des mesures", ano),
            avancement=_texte(get("Avancement des mesures")),
            statut=_texte(get("Statut du risque")), ligne=n,
            categorie=_texte(get("Catégorie")),
            probabilite=_note(get("P")), impact=_note(get("I")))
    return _lire(valeurs, onglet, req, f, optionnels=["Catégorie", "P", "I"])


def lire_questions(valeurs: list[list], onglet: str = "Questions ouvertes"):
    req = ["N°", "Question", "Responsable", "Échéance", "Statut"]

    def f(num, n, get, ano):
        return Question(
            num=num, intitule=_texte(get("Question")),
            responsables=separer_noms(_texte(get("Responsable"))),
            echeance=_date(get("Échéance"), num, "Échéance", ano),
            statut=_texte(get("Statut")), ligne=n)
    return _lire(valeurs, onglet, req, f)


def _personnes(valeurs, ligne_entete, col_nom, debut, fin, groupe, onglet="Annuaire"):
    idx = _indexer(_ligne(valeurs, ligne_entete), [col_nom, "E-mail", "Téléphone"], onglet)
    res = []
    for n in range(debut, fin + 1):
        ligne = _ligne(valeurs, n)
        nom = _texte(_cellule(ligne, idx[col_nom]))
        if not nom:
            continue
        res.append(Personne(nom=nom, email=_opt(_cellule(ligne, idx["E-mail"])),
                            telephone=_opt(_cellule(ligne, idx["Téléphone"])),
                            groupe=groupe, ligne=n))
    return res


def lire_annuaire(valeurs: list[list]) -> list[Personne]:
    personnes = _personnes(valeurs, 5, "Nom et prénom", 6, 11, "fondateur")
    entete = next((n for n in range(12, len(valeurs) + 1)
                   if normaliser(_texte(_cellule(_ligne(valeurs, n), 0))) == "nom ou structure"), None)
    if entete is not None:
        fin = entete
        while fin < len(valeurs) and any(_texte(c) for c in valeurs[fin]):
            fin += 1
        personnes += _personnes(valeurs, entete, "Nom ou structure", entete + 1, fin, "conseil")
    return personnes


def est_onglet_plan(nom: str) -> bool:
    return re.match(r"^[1-8]-", nom) is not None
