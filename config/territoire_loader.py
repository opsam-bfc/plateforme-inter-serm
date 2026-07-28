"""territoire_loader.py.

Chargement et validation du fichier de configuration ``config/territoire.yaml``.

Ce module est le point d'entrée unique pour tout le code qui a besoin de
connaitre les zones d'etude (noms, codes, couleurs, slugs) et les parametres
du territoire. Il remplace les constantes hardcodees ``SERM_INFO``,
``SERM_REFERENTIEL`` et ``NOMS_SERM`` dispersees dans le projet.

Usage :
    from config.territoire_loader import cfg, serm_info, codes_zones

    # Dictionnaire {code: {nom, nom_court, slug, couleur, macrozone}}
    print(serm_info())

    # Liste des codes zones (sans la zone residuelle)
    print(codes_zones())   # ex. [1, 2, 3]

    # Tous les codes (avec la zone residuelle)
    print(codes_zones(inclure_hors_serm=True))  # ex. [1, 2, 3, 0]
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Localisation du fichier de config
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path(__file__).parent
_FICHIER_DEFAUT = _CONFIG_DIR / "territoire.yaml"


def _chemin_config() -> Path:
    """Retourne le chemin vers le fichier de configuration actif.

    Peut etre surcharge par la variable d'environnement ``SERM_CONFIG``.
    """
    env = os.environ.get("SERM_CONFIG", "").strip()
    if env:
        p = Path(env)
        if p.is_file():
            return p
        raise FileNotFoundError(
            f"Fichier de config introuvable (SERM_CONFIG={env})."
        )
    return _FICHIER_DEFAUT


# ---------------------------------------------------------------------------
# Structures de donnees
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Macrozone:
    """Correspondance avec les champs M1/M2 du modele OPSAM."""
    source: str   # "M1" ou "M2"
    code: int     # valeur dans le champ M1 ou M2


@dataclass(frozen=True)
class Zone:
    """Une zone d'analyse (SERM ou equivalent)."""
    code: int
    nom: str
    nom_court: str
    slug: str
    couleur: str
    macrozone: Macrozone


@dataclass(frozen=True)
class RegionConfig:
    """Parametres du territoire global."""
    nom: str
    nom_court: str
    departements: list[str]
    carte_centre_lat: float
    carte_centre_lon: float
    carte_zoom: float


@dataclass(frozen=True)
class ScenarioConfig:
    """Un scénario OPSAM (bundle data/{id}/ + chemins NAS de rebuild)."""
    id: str
    libelle: str
    opsam_outputs: str = ""
    opsam_base: str = ""
    matrice_vl_csv: str = ""
    reseau_shp: str = ""


@dataclass(frozen=True)
class PlateformeConfig:
    """Identite de la plateforme."""
    nom: str
    description: str
    institution: str
    scenario_opsam: str


@dataclass(frozen=True)
class CheminsConfig:
    """Chemins vers les sources de donnees OPSAM."""
    opsam_outputs: str
    opsam_base: str
    lookup_csv: str
    zonage_shp: str
    epci_shp: str
    matrice_vl_csv: str
    reseau_shp: str = ""


@dataclass(frozen=True)
class TerritoireConfig:
    """Configuration complete d'un territoire."""
    plateforme: PlateformeConfig
    region: RegionConfig
    zones: list[Zone]
    zone_hors_serm: Optional[Zone]
    chemins: CheminsConfig
    scenarios: list[ScenarioConfig] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Chargement depuis YAML
# ---------------------------------------------------------------------------

def _charger_yaml(chemin: Path) -> dict:
    """Charge le YAML sans dependance externe si PyYAML absent."""
    try:
        import yaml  # type: ignore[import-untyped]
        with chemin.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except ImportError:
        # Fallback minimal : parser le YAML simple via tomllib-like pour
        # ne pas bloquer si PyYAML manque.
        raise ImportError(
            "PyYAML est requis pour lire la configuration. "
            "Installez-le : pip install pyyaml"
        )


def _zone_depuis_dict(d: dict) -> Zone:
    mz = d.get("macrozone", {})
    return Zone(
        code=int(d["code"]),
        nom=str(d["nom"]),
        nom_court=str(d["nom_court"]),
        slug=str(d["slug"]),
        couleur=str(d["couleur"]),
        macrozone=Macrozone(
            source=str(mz.get("source", "M1")),
            code=int(mz.get("code", 0)),
        ),
    )


@lru_cache(maxsize=1)
def charger_config(chemin: Optional[str] = None) -> TerritoireConfig:
    """Charge et retourne la configuration du territoire (mis en cache).

    Parameters
    ----------
    chemin : str, optional
        Chemin explicite vers le fichier YAML. Si absent, utilise
        ``SERM_CONFIG`` ou ``config/territoire.yaml`` par defaut.
    """
    p = Path(chemin) if chemin else _chemin_config()
    if not p.is_file():
        raise FileNotFoundError(
            f"Fichier de configuration introuvable : {p}\n"
            "Verifiez que config/territoire.yaml existe."
        )

    raw = _charger_yaml(p)
    LOG.info("Configuration chargee depuis : %s", p)

    # Plateforme
    pf = raw.get("plateforme", {})
    plateforme = PlateformeConfig(
        nom=pf.get("nom", "Plateforme d'analyse"),
        description=pf.get("description", ""),
        institution=pf.get("institution", ""),
        scenario_opsam=pf.get("scenario_opsam", ""),
    )

    # Region
    rg = raw.get("region", {})
    region = RegionConfig(
        nom=rg.get("nom", ""),
        nom_court=rg.get("nom_court", ""),
        departements=[str(d) for d in rg.get("departements", [])],
        carte_centre_lat=float(rg.get("carte_centre_lat", 46.5)),
        carte_centre_lon=float(rg.get("carte_centre_lon", 2.0)),
        carte_zoom=float(rg.get("carte_zoom", 6.0)),
    )

    # Zones
    zones = [_zone_depuis_dict(z) for z in raw.get("zones", [])]
    if not zones:
        raise ValueError(
            "Le fichier de configuration ne contient aucune zone (cle 'zones')."
        )

    # Zone hors SERM
    hors_raw = raw.get("zone_hors_serm")
    zone_hors_serm: Optional[Zone] = (
        _zone_depuis_dict(hors_raw) if hors_raw else None
    )

    # Chemins (défaut / rétrocompat — scénario actif peut les surcharger)
    ch = raw.get("chemins", {})
    chemins = CheminsConfig(
        opsam_outputs=ch.get("opsam_outputs", ""),
        opsam_base=ch.get("opsam_base", ""),
        lookup_csv=ch.get("lookup_csv", ""),
        zonage_shp=ch.get("zonage_shp", ""),
        epci_shp=ch.get("epci_shp", ""),
        matrice_vl_csv=ch.get("matrice_vl_csv", ""),
        reseau_shp=ch.get("reseau_shp", ""),
    )

    # Scénarios OPSAM (multi-bundle data/{id}/)
    scenarios: list[ScenarioConfig] = []
    for sc in raw.get("scenarios", []) or []:
        scenarios.append(
            ScenarioConfig(
                id=str(sc["id"]),
                libelle=str(sc.get("libelle", sc["id"])),
                opsam_outputs=str(sc.get("opsam_outputs", "")),
                opsam_base=str(sc.get("opsam_base", "")),
                matrice_vl_csv=str(sc.get("matrice_vl_csv", "")),
                reseau_shp=str(sc.get("reseau_shp", "")),
            )
        )
    if not scenarios and plateforme.scenario_opsam:
        # Rétrocompat : un seul scénario dérivé de plateforme + chemins
        scenarios = [
            ScenarioConfig(
                id=plateforme.scenario_opsam,
                libelle=plateforme.scenario_opsam,
                opsam_outputs=chemins.opsam_outputs,
                opsam_base=chemins.opsam_base,
                matrice_vl_csv=chemins.matrice_vl_csv,
                reseau_shp=chemins.reseau_shp,
            )
        ]

    return TerritoireConfig(
        plateforme=plateforme,
        region=region,
        zones=zones,
        zone_hors_serm=zone_hors_serm,
        chemins=chemins,
        scenarios=scenarios,
    )


# ---------------------------------------------------------------------------
# Accesseurs rapides (API publique)
# ---------------------------------------------------------------------------

def cfg() -> TerritoireConfig:
    """Retourne la configuration du territoire actif."""
    return charger_config()


def serm_info() -> dict[int, dict]:
    """Retourne un dictionnaire {code: metadonnees} compatible avec l'ancien
    ``SERM_INFO`` de ``data_loader``.

    Inclut toutes les zones + la zone hors SERM si presente.
    """
    config = charger_config()
    resultat: dict[int, dict] = {}
    for zone in config.zones:
        resultat[zone.code] = {
            "code": zone.code,
            "nom": zone.nom,
            "nom_court": zone.nom_court,
            "slug": zone.slug,
            "couleur": zone.couleur,
        }
    if config.zone_hors_serm:
        z = config.zone_hors_serm
        resultat[z.code] = {
            "code": z.code,
            "nom": z.nom,
            "nom_court": z.nom_court,
            "slug": z.slug,
            "couleur": z.couleur,
        }
    return resultat


def codes_zones(inclure_hors_serm: bool = False) -> list[int]:
    """Retourne la liste des codes zones d'etude.

    Parameters
    ----------
    inclure_hors_serm : bool
        Si True, inclut le code de la zone residuelle (hors SERM).
    """
    config = charger_config()
    codes = [z.code for z in config.zones]
    if inclure_hors_serm and config.zone_hors_serm:
        codes.append(config.zone_hors_serm.code)
    return codes


def ordre_zones() -> list[int]:
    """Retourne l'ordre d'affichage : zones d'etude puis zone residuelle."""
    return codes_zones(inclure_hors_serm=True)


def slugs_reseau() -> list[str]:
    """Retourne les slugs des zones disposant d'un reseau routier GPKG/Parquet."""
    return [z.slug for z in charger_config().zones]


def scenarios() -> list[ScenarioConfig]:
    """Liste des scénarios OPSAM déclarés dans la config."""
    return list(charger_config().scenarios)


def scenario_par_id(scenario_id: str) -> Optional[ScenarioConfig]:
    """Retourne le ScenarioConfig pour ``scenario_id``, ou None."""
    for sc in scenarios():
        if sc.id == scenario_id:
            return sc
    return None


def scenario_defaut() -> str:
    """Identifiant du scénario par défaut (plateforme.scenario_opsam)."""
    config = charger_config()
    if config.plateforme.scenario_opsam:
        return config.plateforme.scenario_opsam
    if config.scenarios:
        return config.scenarios[0].id
    return "Ref2024"


def chemins_pour_scenario(scenario_id: str | None = None) -> CheminsConfig:
    """Chemins NAS pour un scénario (surcharge sur les chemins globaux)."""
    config = charger_config()
    sid = scenario_id or scenario_defaut()
    sc = scenario_par_id(sid)
    base = config.chemins
    if sc is None:
        return base
    return CheminsConfig(
        opsam_outputs=sc.opsam_outputs or base.opsam_outputs,
        opsam_base=sc.opsam_base or base.opsam_base,
        lookup_csv=base.lookup_csv,
        zonage_shp=base.zonage_shp,
        epci_shp=base.epci_shp,
        matrice_vl_csv=sc.matrice_vl_csv or base.matrice_vl_csv,
        reseau_shp=sc.reseau_shp or base.reseau_shp,
    )
