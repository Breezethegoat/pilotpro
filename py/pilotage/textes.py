"""Utilitaires de texte et de dates."""
import re
import unicodedata
from datetime import date, datetime, timedelta

_ORIGINE_EXCEL = date(1899, 12, 30)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def email_valide(s: str | None) -> bool:
    return bool(s) and _EMAIL.match(s) is not None


def normaliser(s: str | None) -> str:
    if not s:
        return ""
    decompose = unicodedata.normalize("NFKD", str(s))
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sans_accents).strip().lower()


def numero_whatsapp(telephone, indicatif: str = "237") -> str:
    """Numéro au format international sans « + » (attendu par wa.me), ou "" s'il est inutilisable.
    Si plusieurs numéros sont saisis (« a / b »), le premier est retenu ; un numéro local à
    9 chiffres reçoit l'indicatif du pays."""
    if telephone is None:
        return ""
    if isinstance(telephone, float) and telephone.is_integer():
        telephone = int(telephone)
    premier = re.split(r"[/;,]|\bou\b", str(telephone))[0]
    international = premier.strip().startswith(("+", "00"))
    chiffres = re.sub(r"\D", "", premier)
    if chiffres.startswith("00"):
        chiffres = chiffres[2:]
    if not international and len(chiffres) == 9:
        chiffres = indicatif + chiffres
    return chiffres if 10 <= len(chiffres) <= 15 else ""


def separer_noms(s: str | None) -> list[str]:
    if not s:
        return []
    morceaux = re.split(r"[/,;]|\s+et\s+", str(s))
    return [m.strip() for m in morceaux if m.strip()]


def separer_codes(s: str | None) -> list[str]:
    if not s:
        return []
    # Un code doit contenir au moins une lettre ou un chiffre : « - » ou « — » signifie « aucun ».
    return [c.upper() for c in re.split(r"[,;\s]+", str(s)) if re.search(r"\w", c)]


def date_depuis_excel(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, bool):
        raise ValueError(f"Date invalide : {v!r}")
    if isinstance(v, (int, float)):
        return _ORIGINE_EXCEL + timedelta(days=int(v))
    if isinstance(v, str):
        t = v.strip()
        if not t:
            return None
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(t, fmt).date()
            except ValueError:
                pass
    raise ValueError(f"Date invalide : {v!r}")
