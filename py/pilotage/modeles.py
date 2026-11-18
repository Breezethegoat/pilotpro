"""Modèles de domaine de PilotPro."""
from dataclasses import dataclass
from datetime import date
from typing import Literal


@dataclass
class Personne:
    nom: str
    email: str | None
    telephone: str | None
    groupe: Literal["fondateur", "conseil"]
    ligne: int


@dataclass
class Action:
    num: str
    date_creation: date | None
    taches_plan: list[str]
    libelle: str
    livrable: str
    responsables: list[str]
    echeance: date | None
    priorite: str
    statut: str
    date_realisation: date | None
    ligne: int


@dataclass
class Tache:
    num: str
    libelle: str
    onglet: str
    ligne: int
    statut: str
    avancement: float | None
    date_realisation: date | None
    responsable: str = ""
    debut: date | None = None
    echeance: date | None = None
    fin_phase: date | None = None


@dataclass
class Risque:
    num: str
    intitule: str
    niveau: str
    proprietaires: list[str]
    echeance: date | None
    avancement: str
    statut: str
    ligne: int
    categorie: str = ""
    probabilite: int | None = None
    impact: int | None = None


@dataclass
class Question:
    num: str
    intitule: str
    responsables: list[str]
    echeance: date | None
    statut: str
    ligne: int


@dataclass
class Anomalie:
    type: str
    message: str
