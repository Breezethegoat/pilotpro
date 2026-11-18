"""Mode démonstration : la vraie interface et le vrai code, sur des classeurs fictifs en mémoire.

Rien n'est lu ni écrit en ligne, aucun mail ne part. Sert à essayer l'application ou à vérifier
une modification de l'interface dans un navigateur :
    .venv\\Scripts\\python.exe outils\\apercu.py        puis ouvrir http://localhost:8765
"""
import json
import sys
import tempfile
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from pilotage.etat import Etat, Reglages  # noqa: E402
from pilotage.interface.api import Api  # noqa: E402

INTERFACE = RACINE / "pilotage" / "interface"
PORT = 8765
PIL, PLAN, RISQ = "pil", "plan", "risq"
AUJ = date.today()


def s(jours: int):
    """Date Excel (numéro de série) à `jours` d'aujourd'hui."""
    return (AUJ + timedelta(days=jours) - date(1899, 12, 30)).days


def feuille(entetes, lignes):
    return [[""] * len(entetes) for _ in range(4)] + [list(entetes)] + [list(l) for l in lignes]


def _tables() -> dict:
    e_act = ["N°", "Date de création", "Réunion n°", "Tâche du plan", "Catégorie", "Action", "Livrable attendu",
             "Réalisateur", "Échéance", "Priorité", "Statut", "Date de réalisation", "Jours de retard", "Commentaires"]
    A = lambda n, cree, tache, lib, resp, ech, prio, statut, real="": [
        f"A-2026-{n:03d}", s(cree), 1, tache, "", lib, "", resp, s(ech) if ech is not None else "", prio, statut,
        s(real) if real != "" else "", "", ""]
    actions = [
        A(1, -40, "V-01", "Rédiger le questionnaire clients", "Marc", -25, "Haute", "Réalisée", -27),
        A(2, -40, "V-01.2", "Tester le questionnaire sur 10 personnes", "Marc", -12, "Haute", "Réalisée", -8),
        A(3, -30, "V-02", "Recruter 4 enquêteurs", "Aline", -16, "Haute", "En cours"),
        A(4, -30, "M-01", "Choisir le nom de la marque", "Brice", -9, "Haute", "En cours"),
        A(5, -20, "M-02", "Brief du logo pour le designer", "Aline", 2, "Normale", "À faire"),
        A(6, -20, "J-01", "Comparer SARL et SAS avec l'avocat", "Cabinet Juridique", -3, "Haute", "Bloquée"),
        A(7, -10, "J-02", "Réserver le nom de domaine", "Brice", 1, "Normale", "En cours"),
        A(8, -10, "V-03", "Relever les prix de 5 concurrents", "Paul", 12, "Normale", "À faire"),
        A(9, -5, "M-01", "Vérifier la disponibilité de la marque à l'OAPI", "", 20, "Normale", "À attribuer"),
        A(10, -2, "V-02", "Préparer le budget de l'étude terrain", "Paul", 9, "Haute", "À faire"),
        A(11, -45, "J-01", "Lister les pièces pour l'immatriculation", "Brice", -30, "Normale", "Réalisée", -31),
        A(12, -15, "-", "Ouvrir le compte bancaire professionnel", "Brice", -1, "Haute", "Annulée"),
    ] + [[f"A-2026-{n:03d}"] + [""] * 13 for n in range(13, 17)]

    e_plan = ["N°", "Tâche", "Détail", "Phase", "Dépend de (proposition)", "Responsable", "Contributeurs",
              "Relecteur ou valideur", "Début prévu", "Échéance", "Statut", "Avancement saisi (%)",
              "Date de réalisation", "Avancement retenu", "Jours de retard", "Fin de phase"]
    T = lambda num, lib, resp, deb, fin, statut, av: [num, lib, "", "1", "", resp, "", "", s(deb), s(fin), statut, av,
                                                        "", "", "", s(120)]
    plan = {
        "1-Validation": [T("V-01", "Concevoir les questionnaires", "Marc", -45, -10, "En cours", 50),
                         T("V-02", "Définir l'échantillon et le plan de collecte", "Marc", -20, 15, "À faire", 0),
                         T("V-03", "Collecter les données sur le terrain", "Paul", 10, 50, "À faire", 0)],
        "2-Marque": [T("M-01", "Choisir le nom et vérifier sa disponibilité", "Brice", -30, -5, "En cours", 0),
                     T("M-02", "Créer l'identité visuelle", "Aline", -5, 35, "À faire", 0)],
        "3-Juridique": [T("J-01", "Choisir la forme juridique", "Brice", -40, 5, "À faire", 0),
                        T("J-02", "Déposer la marque et le nom de domaine", "Brice", 0, 30, "À faire", 0),
                        T("J-03", "Immatriculer la société", "Brice", 30, 75, "À faire", 0),
                        ["J-04", "Ouvrir le compte bancaire", "", "1", "", "Brice", "", "", "", "", "À faire", 0, "", "", "", s(90)]],
    }

    e_ris = ["N°", "Catégorie", "Phase(s)", "Risque", "Description : cause et conséquence", "Signaux d'alerte",
             "Source", "P", "I", "Criticité", "Niveau", "Stratégie", "Mesures de prévention", "Plan de contingence",
             "Tâches liées du plan", "Propriétaire", "Échéance des mesures", "Avancement des mesures", "P", "I",
             "Niveau", "Tendance", "Statut du risque"]
    niveau = lambda c: "Critique" if c >= 15 else "Élevé" if c >= 10 else "Modéré" if c >= 5 else "Faible"
    R = lambda n, cat, lib, p, i, prop, ech: [
        f"R-{n:02d}", cat, "1-2", lib, "", "", "", p, i, p * i, niveau(p * i), "Réduire", "", "", "", prop,
        s(ech) if ech is not None else "", "À lancer", "", "", "", "Stable", "Ouvert"]
    risques = [R(1, "Marché", "Densité de commandes insuffisante", 3, 5, "Brice", 2),
               R(2, "Marché", "Hypothèses invalidées par l'étude de terrain", 3, 4, "Marc", 20),
               R(3, "Marché", "Prix jugés trop élevés", 3, 4, "Marc", -4),
               R(4, "Juridique", "Retard d'immatriculation", 2, 4, "Brice", 30),
               R(5, "Technique", "Paiement mobile indisponible au lancement", 2, 5, "Paul", 40),
               R(6, "Équipe", "Disponibilité réduite d'un fondateur", 4, 2, "", None),
               R(7, "Opérations", "Pénurie de livreurs aux heures de pointe", 3, 3, "Aline", 25),
               R(8, "Finances", "Trésorerie insuffisante avant la levée", 2, 3, "Brice", 60),
               R(9, "Marque", "Nom déjà déposé", 1, 3, "Aline", None),
               R(10, "Technique", "Panne du prestataire de cartographie", 1, 2, "Paul", 90)]

    e_q = ["N°", "Question", "Contexte", "Options envisagées", "Information nécessaire", "Moyen de résolution",
           "Phase", "Responsable", "Échéance", "Statut", "Décision liée", "Commentaires"]
    Q = lambda n, lib, resp, ech, statut: [f"Q-{n:03d}", lib, "", "", "", "", "2", resp,
                                           s(ech) if ech is not None else "", statut, "", ""]
    questions = [Q(1, "Rémunération du livreur en tournée", "", None, "Ouverte"),
                 Q(2, "Tarifs de l'option Économique au-delà de 15 km", "Marc", 6, "Ouverte"),
                 Q(3, "Forfait de déplacement en cas d'annulation", "", None, "Ouverte"),
                 Q(4, "Commission pour les vendeurs sur les réseaux sociaux", "Brice", 14, "En instruction"),
                 Q(5, "Ouverture le dimanche dès le lancement ?", "", None, "Reportée")]

    v = [""] * 9
    L = lambda *c: list(c) + [""] * (9 - len(c))
    annuaire = [v, v, v, L("Fondateurs"),
                L("Nom et prénom", "Rôle", "Catégories", "Téléphone", "E-mail"),
                L("Brice", "Direction", "", "699001122", "brice@exemple.cm"),
                L("Marc", "Marché", "", "+237 677 00 11 22", "marc@exemple.cm"),
                L("Aline", "Marque", "", "655443322", "aline@exemple.cm"),
                L("Paul", "Technique", "", "", "paul@exemple.cm"),
                v, v, L("Total"), v, L("Conseils et prestataires"),
                L("Nom ou structure", "Fonction", "Mission", "Téléphone", "E-mail"),
                L("Cabinet Juridique", "Avocat", "", "", ""), v]

    tables = {(PIL, "Actions"): feuille(e_act, actions), (PIL, "Questions ouvertes"): feuille(e_q, questions),
              (PIL, "Annuaire"): annuaire, (RISQ, "Registre"): feuille(e_ris, risques)}
    for onglet, lignes in plan.items():
        tables[(PLAN, onglet)] = feuille(e_plan, lignes)
    return tables


class ClasseursFictifs:
    """Classeurs en mémoire : les écritures sont réellement appliquées."""

    def __init__(self):
        self.tables = _tables()

    def onglets(self, item_id):
        return [o for (i, o) in self.tables if i == item_id]

    def lire(self, item_id, onglet, plage=None):
        return [list(l) for l in self.tables[(item_id, onglet)]]

    def ecrire(self, item_id, onglet, adresse, valeurs, format=None):
        t = self.tables[(item_id, onglet)]
        debut = adresse.split(":")[0]
        lettres = "".join(c for c in debut if c.isalpha())
        col = 0
        for c in lettres:
            col = col * 26 + ord(c) - 64
        ligne = int(debut[len(lettres):])
        while len(t) < ligne:
            t.append([""] * len(t[4]))
        for k, valeur in enumerate(valeurs[0]):
            while len(t[ligne - 1]) < col + k:
                t[ligne - 1].append("")
            t[ligne - 1][col - 1 + k] = valeur.lstrip("'") if isinstance(valeur, str) else valeur

    def lien(self, item_id):
        return "https://exemple.invalid/classeur.xlsx"

    def chercher(self, texte):
        return [{"id": PIL, "nom": "Classeur fictif.xlsx", "chemin": "/drive/root:/Démo"}]


class EnvoiFictif:
    def envoyer(self, courrier):
        print("  [démo] mail non envoyé :", courrier.destinataire, "|", courrier.objet,
              ("| copie " + courrier.cc) if courrier.cc else "")


class ConnexionFictive:
    def jeton(self): return "jeton-fictif"
    def compte(self): return "demo@exemple.cm"
    def demarrer(self): return {"user_code": "DEMO1234", "verification_uri": "https://microsoft.com/devicelogin"}
    def terminer(self, flux): return "demo@exemple.cm"
    def deconnecter(self): pass


class CoffreFictif:
    secret = ""
    def lire(self): return self.secret
    def enregistrer(self, x): self.secret = x
    def effacer(self): self.secret = ""


class FabriqueFictive:
    def __init__(self):
        self._classeurs, self._coffre = ClasseursFictifs(), CoffreFictif()

    def connexion(self, client_id, dossier): return ConnexionFictive()
    def graph(self, connexion): return object()
    def classeurs(self, graph): return self._classeurs
    def partage(self, graph): return None  # démonstration : tout reste en mémoire
    def envoi(self, graph, mode_test, adresse_test): return EnvoiFictif()
    def envoi_gmail(self, adresse, mdp, mode_test, adresse_test): return EnvoiFictif()
    def coffre(self, dossier): return self._coffre
    def ouvrir_navigateur(self, url): print("  [démo] lien non ouvert :", url)
    def copier(self, texte): pass
    def planifier(self, jour, heure): print("  [démo] planification non créée :", jour, heure)
    def deplanifier(self): pass
    def prochaine_execution(self): return "lundi prochain 08:00 (démo)"
    def dossier_documents(self): return Path(tempfile.gettempdir()) / "PilotPro-demo"
    def pdf(self, html, pdf):
        from pilotage import rapports
        rapports.html_vers_pdf(html, pdf)
    def ouvrir_fichier(self, chemin): print("  [démo] document créé :", chemin)

    def __getattr__(self, nom):  # toute autre action système est neutralisée en démonstration
        def neutre(*a, **k):
            print("  [démo] action neutralisée :", nom)
            return ""
        return neutre


def creer_api_fictive(dossier: Path) -> Api:
    Etat(dossier).enregistrer_reglages(Reglages(
        client_id="demo", email_fondateur="brice@exemple.cm", mode_test=True, adresse_test="brice@exemple.cm",
        classeurs={"pilotage": {"id": PIL, "nom": "Outils_de_pilotage (démo).xlsx"},
                   "plan": {"id": PLAN, "nom": "Plan_de_realisation (démo).xlsx"},
                   "risques": {"id": RISQ, "nom": "Registre_des_risques (démo).xlsx"}}))
    etat = Etat(dossier)
    for k in range(8, 0, -1):  # huit semaines d'historique fictif pour les courbes
        etat.enregistrer_tendance({
            "date": (AUJ - timedelta(weeks=k)).isoformat(), "total": 12 - k // 2, "ouvertes": 9 - k // 3,
            "en_retard": max(0, 5 - k // 2), "realisees": 4 - k // 3, "taux_realisation": 0.36 - 0.03 * k,
            "taux_delais": 0.5 + 0.03 * k, "avancement_plan": 0.07 - 0.008 * k})
    # Deux échéances « repoussées dans Excel » depuis la dernière analyse, pour montrer l'écran de décision.
    etat._ecrire("echeances.json", {"changements": [], "connues": {
        "A-2026-005": (AUJ - timedelta(days=5)).isoformat(), "A-2026-008": (AUJ + timedelta(days=5)).isoformat()}})
    return Api(dossier, FabriqueFictive())


PONT = b"""<script>
window.pywebview = { api: new Proxy({}, { get: (_, nom) => async (...args) =>
  (await fetch("/api/" + nom, { method: "POST", body: JSON.stringify(args) })).json() }) };
</script>"""
TYPES = {"html": "text/html", "css": "text/css", "js": "application/javascript", "svg": "image/svg+xml",
         "woff2": "font/woff2", "ico": "image/x-icon"}


def serveur(api: Api) -> ThreadingHTTPServer:
    class Requete(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _repondre(self, code, type_, corps):
            self.send_response(code)
            self.send_header("Content-Type", type_ + ("; charset=utf-8" if type_.startswith(("text", "appl")) else ""))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corps)

        def do_GET(self):
            nom = self.path.split("?")[0].lstrip("/") or "index.html"
            fichier = (INTERFACE / nom).resolve()
            if INTERFACE not in fichier.parents or not fichier.is_file():
                return self._repondre(404, "text/plain", b"introuvable")
            corps = fichier.read_bytes()
            if nom == "index.html":
                corps = corps.replace(b'<script src="app.js">', PONT + b'<script src="app.js">')
            self._repondre(200, TYPES.get(nom.rsplit(".", 1)[-1], "application/octet-stream"), corps)

        def do_POST(self):
            nom = self.path.rsplit("/", 1)[-1]
            args = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"[]")
            methode = getattr(api, nom, None)
            if nom.startswith("_") or not callable(methode):
                resultat = {"ok": False, "erreur": f"Méthode inconnue : {nom}"}
            else:
                resultat = methode(*args)
            self._repondre(200, "application/json", json.dumps(resultat, ensure_ascii=False, default=str).encode())

    return ThreadingHTTPServer(("127.0.0.1", PORT), Requete)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        print(f"PilotPro en démonstration : http://localhost:{PORT}  (Ctrl+C pour arrêter)")
        serveur(creer_api_fictive(Path(tmp))).serve_forever()
