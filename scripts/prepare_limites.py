"""prepare_limites.py.

Prepare les couches géographiques de référence pour la plateforme :

* Limites communales par SERM : dissolution des zones OPSAM par INSEE_COM
  pour chaque SERM, avec attributs (nom commune, code EPCI, code SERM).
  Sorties : ``data/limites_communes_serm1.geojson``, ``...serm2.geojson``,
  ``...serm3.geojson``.

* Limites EPCI nationales (filtrées aux EPCI présents dans le lookup) :
  Sortie : ``data/limites_epci.geojson``.

Ces fichiers sont chargés par ``data_loader.py`` et utilisés dans
``visualizations.py`` pour afficher les contours sur les cartes de flux.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import pandas as pd

LOG = logging.getLogger(__name__)

EPSG_CALCULS = 2154   # RGF93 Lambert 93 — calculs
EPSG_AFFICHAGE = 4326  # WGS84 — sortie

# Correspondance code SERM -> colonne du shapefile zonage
SERM_COLONNES = {
    1: "SERM_dijon",
    2: "SERM_NFC",
    3: "SERM_besan",
}


# ---------------------------------------------------------------------------
# Chemins (résolution avec fallback variables d'environnement)
# ---------------------------------------------------------------------------

def _zonage_shp() -> Path:
    v = os.environ.get("SERM_ZONAGE_SHP")
    if v:
        return Path(v)
    return Path(
        r"\\nas-bfc\COMMUN\21_MOBILITE\21.2_COMMUN\DATA"
        r"\ZONAGE_OPSAM\zonage_OPSAM_poly.shp"
    )


def _epci_shp() -> Path:
    v = os.environ.get("SERM_EPCI_SHP")
    if v:
        return Path(v)
    return Path(
        r"\\nas-bfc\COMMUN\21_MOBILITE\21.2_COMMUN\DATA"
        r"\EPCI\EPCI_2025.shp"
    )


def _lookup_csv() -> Path:
    v = os.environ.get("SERM_LOOKUP_CSV")
    if v:
        return Path(v)
    return Path(
        r"\\nas-bfc\COMMUN\21_MOBILITE\21.4_PROJETS\DREAL\2026_SERM"
        r"\2_INPUT\DATA\lookupfile_serm"
        r"\lookup_dep_com_epci_macrozone.csv"
    )


def _data_dir() -> Path:
    v = os.environ.get("SERM_DATA_DIR")
    if v:
        return Path(v)
    return Path(__file__).resolve().parents[1] / "data"


# ---------------------------------------------------------------------------
# Lecture lookup
# ---------------------------------------------------------------------------

def lire_lookup(chemin: Path) -> pd.DataFrame:
    """Charge le lookup OPSAM zones -> COM / EPCI / SERM.

    Accepte un séparateur ``;`` (défaut SERM) ou ``,``.
    """
    df = pd.read_csv(chemin, sep=";", dtype=str)
    if len(df.columns) == 1:
        df = pd.read_csv(chemin, sep=",", dtype=str)
    df.columns = [c.strip() for c in df.columns]
    for col in ("M1", "M2"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    return df


# ---------------------------------------------------------------------------
# Limites communales par SERM
# ---------------------------------------------------------------------------

def preparer_communes_serm(
    chemin_zonage: Path,
    lookup: pd.DataFrame,
    code_serm: int,
) -> gpd.GeoDataFrame:
    """Dissout le shapefile de zonage par INSEE_COM pour un SERM donné.

    Args:
        chemin_zonage: Chemin vers le shapefile OPSAM.
        lookup: Table de correspondance OPSAM -> COM / EPCI / SERM.
        code_serm: Code du SERM (1, 2 ou 3).

    Returns:
        GeoDataFrame avec une ligne par commune du SERM (WGS84).
    """
    LOG.info("Lecture zonage : %s", chemin_zonage)
    gdf = gpd.read_file(chemin_zonage)
    if gdf.crs is None:
        gdf = gdf.set_crs(EPSG_CALCULS)
    else:
        gdf = gdf.to_crs(EPSG_CALCULS)

    # Sélection des zones appartenant au SERM via le lookup
    if code_serm in (1, 2):
        col_serm_lookup = "M1"
    else:
        col_serm_lookup = "M2"

    zones_serm = lookup[lookup[col_serm_lookup] == code_serm]["ID_ZONAGE"].astype(str)
    gdf["ID_ZONAGE"] = gdf["ID_ZONAGE"].astype(str)
    gdf_serm = gdf[gdf["ID_ZONAGE"].isin(zones_serm)].copy()

    if gdf_serm.empty:
        LOG.warning("Aucune zone trouvée pour SERM %d", code_serm)
        return gpd.GeoDataFrame()

    # Jointure du code EPCI depuis le lookup
    lookup_epci = lookup[["ID_ZONAGE", "COM", "EPCI"]].copy()
    lookup_epci["ID_ZONAGE"] = lookup_epci["ID_ZONAGE"].astype(str)
    gdf_serm = gdf_serm.merge(lookup_epci, on="ID_ZONAGE", how="left")

    # Dissolution par commune (INSEE_COM)
    LOG.info("Dissolution par commune pour SERM %d (%d zones)...",
             code_serm, len(gdf_serm))
    communes = gdf_serm.dissolve(
        by="INSEE_COM",
        aggfunc={
            "NOM_COM": "first",
            "EPCI": "first",
        },
    ).reset_index()

    communes["code_serm"] = code_serm
    communes = communes.to_crs(EPSG_AFFICHAGE)
    communes = communes[["INSEE_COM", "NOM_COM", "EPCI", "code_serm", "geometry"]]
    LOG.info("SERM %d : %d communes", code_serm, len(communes))
    return communes


# ---------------------------------------------------------------------------
# Limites EPCI filtrées au lookup
# ---------------------------------------------------------------------------

def preparer_epci_limites(
    chemin_epci: Path,
    lookup: pd.DataFrame,
) -> gpd.GeoDataFrame:
    """Charge le shapefile EPCI et filtre aux EPCI présents dans le lookup.

    Args:
        chemin_epci: Chemin vers le shapefile EPCI national.
        lookup: Table de correspondance OPSAM -> COM / EPCI / SERM.

    Returns:
        GeoDataFrame des EPCI (WGS84) avec colonnes CODE_SIREN, NOM, code_serm.
    """
    LOG.info("Lecture EPCI : %s", chemin_epci)
    epci_gdf = gpd.read_file(chemin_epci)
    if epci_gdf.crs is None:
        epci_gdf = epci_gdf.set_crs(EPSG_AFFICHAGE)
    else:
        epci_gdf = epci_gdf.to_crs(EPSG_AFFICHAGE)

    # Codes EPCI présents dans le lookup avec affectation SERM
    lookup_epci = lookup[lookup["EPCI"].notna()].copy()

    def _serm_pour_epci(grp: pd.DataFrame) -> int:
        """Renvoie le code SERM dominant pour un EPCI (zones M1/M2 != 0)."""
        for col in ("M1", "M2"):
            if col in grp.columns:
                vals = grp[col][grp[col] != 0]
                if not vals.empty:
                    return int(vals.mode().iloc[0])
        return 0

    serm_par_epci = (
        lookup_epci.groupby("EPCI")
        .apply(_serm_pour_epci, include_groups=False)
        .reset_index(name="code_serm")
    )

    epci_gdf["CODE_SIREN"] = epci_gdf["CODE_SIREN"].astype(str)
    serm_par_epci["EPCI"] = serm_par_epci["EPCI"].astype(str)

    gdf_filtre = epci_gdf.merge(
        serm_par_epci, left_on="CODE_SIREN", right_on="EPCI", how="inner",
    )
    gdf_filtre = gdf_filtre[["CODE_SIREN", "NOM", "code_serm", "geometry"]]
    LOG.info("EPCI retenus dans le lookup : %d", len(gdf_filtre))
    return gdf_filtre


# ---------------------------------------------------------------------------
# Point d'entrée CLI
# ---------------------------------------------------------------------------

def main(argv: Iterable[str] | None = None) -> int:
    """Génère les couches de limites et les sauvegarde dans ``data/``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zonage", type=Path, default=None)
    parser.add_argument("--epci", type=Path, default=None)
    parser.add_argument("--lookup", type=Path, default=None)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    data = args.data_dir or _data_dir()
    data.mkdir(parents=True, exist_ok=True)

    lookup = lire_lookup(args.lookup or _lookup_csv())

    # -- Communes par SERM ---------------------------------------------------
    chemin_zonage = args.zonage or _zonage_shp()
    for code in (1, 2, 3):
        gdf = preparer_communes_serm(chemin_zonage, lookup, code)
        if not gdf.empty:
            sortie = data / f"limites_communes_serm{code}.geojson"
            gdf.to_file(sortie, driver="GeoJSON")
            LOG.info("Écrit %s (%d communes)", sortie, len(gdf))

    # -- EPCI ----------------------------------------------------------------
    chemin_epci = args.epci or _epci_shp()
    gdf_epci = preparer_epci_limites(chemin_epci, lookup)
    if not gdf_epci.empty:
        sortie_epci = data / "limites_epci.geojson"
        gdf_epci.to_file(sortie_epci, driver="GeoJSON")
        LOG.info("Écrit %s (%d EPCI)", sortie_epci, len(gdf_epci))

    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
