"""Passage automatique (sans fenêtre), notifications Windows et tâche planifiée hebdomadaire."""
import base64
import subprocess
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

NOM_TACHE = "PilotPro - passage hebdomadaire"
JOURS = {"lundi": "Monday", "mardi": "Tuesday", "mercredi": "Wednesday", "jeudi": "Thursday",
         "vendredi": "Friday", "samedi": "Saturday", "dimanche": "Sunday"}
# Identité sous laquelle Windows affiche la notification (PowerShell, présent sur tout Windows 10/11).
_APPLI_NOTIF = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
_SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _powershell(script: str, delai: int = 60) -> subprocess.CompletedProcess:
    """Exécute un script PowerShell sans fenêtre ; le script est encodé pour éviter tout souci de guillemets."""
    code = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", code],
                          capture_output=True, text=True, timeout=delai, creationflags=_SANS_FENETRE)


def _ps(texte: str) -> str:
    """Chaîne PowerShell entre apostrophes."""
    return "'" + str(texte).replace("'", "''") + "'"


# ---------- notifications ----------
def notifier(titre: str, texte: str) -> bool:
    """Affiche une notification Windows ; renvoie False si elle n'a pas pu être affichée."""
    xml = ("<toast><visual><binding template='ToastGeneric'>"
           f"<text>{escape(titre)}</text><text>{escape(texte)}</text></binding></visual></toast>")
    script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml({_ps(xml)})
$toast = New-Object Windows.UI.Notifications.ToastNotification $doc
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier({_ps(_APPLI_NOTIF)}).Show($toast)
"""
    try:
        return _powershell(script, 30).returncode == 0
    except Exception:
        return False


# ---------- tâche planifiée ----------
def _verifier(jour: str, heure: str) -> None:
    if jour not in JOURS:
        raise ValueError("Jour inconnu : choisissez un jour de la semaine.")
    try:
        datetime.strptime(heure, "%H:%M")
    except (TypeError, ValueError):
        raise ValueError("Heure invalide : utilisez le format HH:MM (par exemple 08:00).") from None


def planifier(racine: Path, jour: str, heure: str) -> None:
    """Crée (ou remplace) la tâche Windows qui lance le passage chaque semaine."""
    _verifier(jour, heure)
    racine = Path(racine)
    python = racine / ".venv" / "Scripts" / "pythonw.exe"
    script = f"""
$ErrorActionPreference = 'Stop'
$action = New-ScheduledTaskAction -Execute {_ps(python)} -Argument {_ps('"' + str(racine / 'lancer.pyw') + '" --auto')} -WorkingDirectory {_ps(racine)}
$quand = New-ScheduledTaskTrigger -Weekly -DaysOfWeek {JOURS[jour]} -At {_ps(heure)}
$reglages = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName {_ps(NOM_TACHE)} -Action $action -Trigger $quand -Settings $reglages -Description 'Passage hebdomadaire PilotPro' -Force | Out-Null
"""
    r = _powershell(script)
    if r.returncode != 0:
        raise ValueError("Windows a refusé de créer la tâche planifiée : " + (r.stderr or "").strip()[:300])


def deplanifier() -> None:
    _powershell(f"Unregister-ScheduledTask -TaskName {_ps(NOM_TACHE)} -Confirm:$false -ErrorAction SilentlyContinue")


def prochaine_execution() -> str:
    """Date du prochain passage planifié (« jj/mm/aaaa hh:mm »), ou "" si aucune tâche."""
    script = (f"$i = Get-ScheduledTaskInfo -TaskName {_ps(NOM_TACHE)} -ErrorAction SilentlyContinue; "
              "if ($i -and $i.NextRunTime) { $i.NextRunTime.ToString('dd/MM/yyyy HH:mm') }")
    try:
        return (_powershell(script, 30).stdout or "").strip()
    except Exception:
        return ""


# ---------- passage automatique ----------
def resume(analyse: dict, resultat: dict | None) -> str:
    s = analyse["stats"]
    morceaux = []
    if resultat is not None:
        mode = " (mode test)" if resultat.get("mode_test") else ""
        morceaux.append(f"{len(resultat['envoyes'])} mail(s) envoyé(s){mode}")
        if resultat["echecs"]:
            morceaux.append(f"{len(resultat['echecs'])} échec(s)")
    else:
        morceaux.append(f"{len(analyse['mails'])} mail(s) prêt(s) : ouvrez PilotPro pour valider l'envoi")
    morceaux.append(f"{s['en_retard']} action(s) en retard")
    if analyse.get("nb_risques_critiques"):
        morceaux.append(f"{analyse['nb_risques_critiques']} risque(s) critique(s)")
    return ", ".join(morceaux) + "."


def passage_automatique(api, validation: bool, notification=notifier) -> dict:
    """Analyse puis, sauf en mode validation, envoie. Notifie le résultat dans tous les cas."""
    a = api.analyser()
    if not a["ok"]:
        notification("PilotPro : passage non effectué", a["erreur"])
        return {"ok": False, "erreur": a["erreur"]}
    titre = "PilotPro : point du " + a["donnees"]["date"]
    if validation:
        notification(titre, resume(a["donnees"], None))
        return {"ok": True, "envoye": False}
    r = api.executer([])
    if not r["ok"]:
        notification("PilotPro : envoi non effectué", r["erreur"])
        return {"ok": False, "erreur": r["erreur"]}
    notification(titre, resume(a["donnees"], r["donnees"]))
    return {"ok": True, "envoye": True}
