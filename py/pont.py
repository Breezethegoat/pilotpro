"""Pont entre l'interface mobile (JavaScript) et le code de PilotPro, exécuté dans le téléphone.

Le téléphone fait tourner le même code Python que l'ordinateur (grâce à Pyodide) : mêmes règles,
mêmes contrôles avant écriture. Seuls changent les accès réseau (le navigateur du téléphone)
et les réglages, repris de ceux que l'ordinateur dépose sur OneDrive.
"""
import json as _json
import sys
import types
from pathlib import Path

DOSSIER = Path("/donnees")
# Ce que le téléphone a le droit de faire (pas d'envoi de mails, pas de réglages).
AUTORISEES = {"analyser", "modifier_action", "creer_action", "modifier_questions", "decider_echeance",
              "ouvrir_whatsapp", "ouvrir_action"}
MSG_SANS_REGLAGES = ("PilotPro n'a pas encore été préparé pour le téléphone : sur l'ordinateur, "
                     "ouvrez PilotPro et lancez une analyse une fois (version à jour), puis revenez ici.")
MSG_PARTAGE = ("OneDrive n'a pas pu être mis à jour : vos décisions sur les échéances sont gardées "
               "sur ce téléphone jusqu'à la prochaine connexion réussie.")

_API = None
_FAB = None


def _installer_requests() -> None:
    """Remplace la bibliothèque « requests » (absente du navigateur) par des requêtes du navigateur.

    Les requêtes sont synchrones : c'est permis ici car le code tourne dans un « worker »,
    à l'écart de l'affichage, qui ne se fige donc pas."""
    # « ssl » ne sert qu'à l'envoi par Gmail, qui n'existe pas sur le téléphone.
    if not isinstance(sys.modules.get("ssl"), types.ModuleType):
        ssl = types.ModuleType("ssl")

        def _indisponible(*a, **k):
            raise RuntimeError("L'envoi de mails se fait depuis l'ordinateur.")
        ssl.create_default_context = _indisponible
        sys.modules["ssl"] = ssl
    if getattr(sys.modules.get("requests"), "_pilotpro", False):
        return
    from js import XMLHttpRequest

    mod = types.ModuleType("requests")

    class RequestException(Exception):
        pass

    class Reponse:
        def __init__(self, statut, texte, attente):
            self.status_code, self.text = statut, texte
            self.headers = {"Retry-After": attente} if attente else {}

        def json(self):
            return _json.loads(self.text)

    class Session:
        def request(self, method, url, headers=None, json=None, data=None, timeout=None):
            x = XMLHttpRequest.new()
            x.open(method, url, False)
            for k, v in (headers or {}).items():
                x.setRequestHeader(k, v)
            corps = _json.dumps(json) if json is not None else data
            if isinstance(corps, bytes):
                corps = corps.decode("utf-8")
            try:
                x.send() if corps is None else x.send(corps)
            except Exception as e:
                raise RequestException(str(e)) from None
            if x.status == 0:
                raise RequestException("Réseau indisponible")
            return Reponse(x.status, x.responseText or "", x.getResponseHeader("Retry-After"))

    mod.RequestException, mod.Session, mod._pilotpro = RequestException, Session, True
    sys.modules["requests"] = mod


class _Connexion:
    def __init__(self, fab):
        self._fab = fab

    def jeton(self):
        return self._fab.jeton


class _CoffreVide:
    def lire(self):
        return ""


class FabriqueMobile:
    """Ce dont l'Api a besoin, version téléphone. Tout ce qui touche à l'ordinateur est refusé."""
    publie_pour_mobile = False

    def __init__(self):
        self.jeton, self.a_ouvrir = "", []

    def coffre(self, dossier):
        return _CoffreVide()

    def connexion(self, client_id, dossier):
        return _Connexion(self)

    def graph(self, connexion):
        from pilotage.graph import Graph
        return Graph(connexion.jeton)

    def classeurs(self, graph):
        from pilotage.classeurs import Classeurs
        return Classeurs(graph)

    def partage(self, graph):
        from pilotage.partage import Partage
        return Partage(graph)

    def ouvrir_navigateur(self, url):
        self.a_ouvrir.append(url)

    def __getattr__(self, nom):
        if nom.startswith("__"):
            raise AttributeError(nom)

        def refus(*a, **k):
            raise ValueError("Cette fonction n'existe que sur l'ordinateur.")
        return refus


def demarrer(jeton: str) -> str:
    """Reprend les réglages déposés par l'ordinateur sur OneDrive et prépare l'Api."""
    global _API, _FAB
    _installer_requests()
    from pilotage.etat import Etat, Reglages
    from pilotage.graph import ErreurGraph, Graph, ReconnexionRequise
    from pilotage.interface.api import Api
    from pilotage.partage import Partage

    _FAB = FabriqueMobile()
    _FAB.jeton = jeton
    try:
        partage = Partage(Graph(lambda: _FAB.jeton))
        brut = partage.lire("reglages.json")
        tendances = partage.lire("tendances.json") or []
    except (ReconnexionRequise, ErreurGraph) as e:
        if isinstance(e, ReconnexionRequise) or e.statut == 401:
            return _json.dumps({"ok": False, "reconnexion": True, "erreur": "Reconnexion Microsoft requise."})
        return _json.dumps({"ok": False, "erreur": f"Microsoft a refusé l'opération ({e.statut}) : {e.message}"})
    except Exception:
        return _json.dumps({"ok": False, "erreur": "Impossible de joindre OneDrive : vérifiez la connexion Internet."})
    if not brut:
        return _json.dumps({"ok": False, "erreur": MSG_SANS_REGLAGES})
    etat = Etat(DOSSIER)
    r = Reglages()
    for k, v in brut.items():
        if hasattr(r, k):
            setattr(r, k, v)
    r.mode_test = True  # garde-fou : aucun envoi ne peut partir du téléphone
    etat.enregistrer_reglages(r)
    etat._ecrire("tendances.json", tendances)
    _API = Api(DOSSIER, _FAB)
    return _json.dumps({"ok": True})


def demarrer_demo() -> str:
    """Démonstration : classeurs fictifs en mémoire, rien n'est lu ni écrit en ligne."""
    global _API, _FAB
    _installer_requests()
    from apercu import creer_api_fictive
    _API = creer_api_fictive(Path("/demo"))
    _FAB = FabriqueMobile()
    _API._fab.ouvrir_navigateur = _FAB.ouvrir_navigateur
    return _json.dumps({"ok": True})


def appeler(nom: str, args_json: str, jeton: str) -> str:
    if _API is None:
        return _json.dumps({"ok": False, "erreur": "PilotPro n'est pas encore prêt."})
    if nom not in AUTORISEES:
        return _json.dumps({"ok": False, "erreur": "Cette fonction n'existe que sur l'ordinateur."})
    _FAB.jeton, _FAB.a_ouvrir = jeton, []
    r = getattr(_API, nom)(*_json.loads(args_json or "[]"))
    r["a_ouvrir"] = list(_FAB.a_ouvrir)
    if _API._etat.partage_erreur:
        r["avertissement"] = MSG_PARTAGE
    journal = DOSSIER / "erreurs.log"
    if not r.get("ok") and journal.exists():  # détail technique, visible dans la console du navigateur
        r["detail"] = journal.read_text(encoding="utf-8")[-3000:]
    return _json.dumps(r, ensure_ascii=False, default=str)
