"""Envoi des mails, par Microsoft Graph ou par Gmail (SMTP), avec mode test."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import escape

from pilotage.courriers import Courrier
from pilotage.graph import Graph

SERVEUR_GMAIL = ("smtp.gmail.com", 465)
NOM_EXPEDITEUR = "PilotPro"


def preparer(c: Courrier, mode_test: bool, adresse_test: str) -> tuple[str, str, str, str]:
    """Renvoie (adresse, objet, html, copie) ; en mode test, tout est détourné vers l'adresse
    de test et personne n'est mis en copie."""
    if not mode_test:
        return c.destinataire, c.objet, c.html, c.cc
    if not adresse_test.strip():
        raise ValueError("Mode test : aucune adresse de test n'est configurée.")
    reel = escape(c.destinataire) + (f" (copie : {escape(c.cc)})" if c.cc else "")
    return (adresse_test.strip(), f"[TEST] {c.objet}",
            f"<p><i>Destinataire réel : {reel}</i></p>{c.html}", "")


class Envoi:
    def __init__(self, graph: Graph, mode_test: bool, adresse_test: str):
        self._g = graph
        self.mode_test = mode_test
        self.adresse_test = adresse_test

    def envoyer(self, c: Courrier) -> None:
        adresse, objet, html, copie = preparer(c, self.mode_test, self.adresse_test)
        message = {
            "subject": objet,
            "body": {"contentType": "HTML", "content": html},
            "toRecipients": [{"emailAddress": {"address": adresse}}],
        }
        if copie:
            message["ccRecipients"] = [{"emailAddress": {"address": copie}}]
        self._g.post("/me/sendMail", {"message": message, "saveToSentItems": True})


class EnvoiGmail:
    """Envoi par le serveur SMTP de Gmail avec un mot de passe d'application Google."""

    def __init__(self, expediteur: str, mot_de_passe: str, mode_test: bool, adresse_test: str,
                 smtp=smtplib.SMTP_SSL):
        if not expediteur.strip() or not mot_de_passe:
            raise ValueError("Envoi Gmail : renseignez l'adresse Gmail et le mot de passe "
                             "d'application dans les Réglages.")
        self.expediteur, self._mdp = expediteur.strip(), mot_de_passe
        self.mode_test, self.adresse_test = mode_test, adresse_test
        self._smtp = smtp

    def message(self, c: Courrier) -> EmailMessage:
        adresse, objet, html, copie = preparer(c, self.mode_test, self.adresse_test)
        m = EmailMessage()
        m["From"] = formataddr((NOM_EXPEDITEUR, self.expediteur))
        m["To"] = adresse
        if copie:
            m["Cc"] = copie
        m["Subject"] = objet
        m["Message-ID"] = make_msgid(domain=self.expediteur.split("@")[-1])
        m.set_content("Ce message est au format HTML : ouvrez-le dans un lecteur de mails compatible.")
        m.add_alternative(html, subtype="html")
        return m

    def envoyer(self, c: Courrier) -> None:
        m = self.message(c)
        hote, port = SERVEUR_GMAIL
        try:
            with self._smtp(hote, port, context=ssl.create_default_context(), timeout=30) as s:
                s.login(self.expediteur, self._mdp)
                s.send_message(m)
        except smtplib.SMTPAuthenticationError:
            raise ValueError("Gmail a refusé la connexion : vérifiez l'adresse Gmail et le mot de passe "
                             "d'application (16 lettres) dans les Réglages.") from None
