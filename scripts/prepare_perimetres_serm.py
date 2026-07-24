"""prepare_perimetres_serm.py.

Construit les perimetres geographiques des trois SERM (Dijon, Nord
Franche-Comte, Besancon) a partir du shapefile des zones OPSAM, en
priorisant la jointure par le lookup ``M1``/``M2`` (logique des
calculs OPSAM), avec un repli sur les colonnes ``SERM_*`` du
shapefile si le lookup n'est pas accessible.

Le geojson de sortie est reprojete en WGS84 (EPSG:4326), simplifie
et allege pour rester utilisable dans une application Streamlit.

Sorties :
  - ``data/perimetres_serm.geojson`` (multipolygones SERM uniquement)
  - ``data/zones_serm.geojson`` (zones OPSAM enrichies du code SERM)
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

from prepare_synthese_serm import SERM_REFERENTIEL  # type: ignore  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOG = logging.getLogger("prepare_perimetres_serm")

EPSG_AFFICHAGE = 4326  # WGS84 (Mapbox / Plotly)
EPSG_CALCULS = 2154    # RGF93 Lambert 93 (calculs metriques)
TOLERANCE_SIMPLIFICATION_M = 50.0  # 50 m : marge raisonnable pour cartographie


# ---------------------------------------------------------------------------
# Helpers chemins
# ---------------------------------------------------------------------------

def _zonage_shp() -> Path:
    """Chemin du shapefile zonage OPSAM (variable SERM_ZONAGE_SHP)."""
    v = os.environ.get("SERM_ZONAGE_SHP")
    if v:
        return Path(v)
    return Path(
        r"\\nas-bfc\COMMUN\21_MOBILITE\21.2_COMMUN\DATA"
        r"\ZONAGE_OPSAM\zonage_OPSAM_poly.shp"
    )


def _lookup_csv() -> Path:
    """Chemin du lookup macrozone (variable SERM_LOOKUP_CSV)."""
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
# Lecture des donnees source
# ---------------------------------------------------------------------------

def lire_zonage(chemin: Path) -> gpd.GeoDataFrame:
    """Lit le shapefile des zones OPSAM."""
    if not chemin.is_file():
        raise FileNotFoundError(f"Shapefile introuvable : {chemin}")
    LOG.info("Lecture du shapefile zonage : %s", chemin)
    gdf = gpd.read_file(chemin)
    if gdf.crs is None:
        raise ValueError("Le shapefile n'a pas de CRS defini.")
    if "ID_ZONAGE" not in gdf.columns:
        raise ValueError("La colonne 'ID_ZONAGE' est attendue dans le zonage.")
    return gdf


def lire_lookup(chemin: Path) -> pd.DataFrame:
    """Lit le lookup ID_ZONAGE -> M1/M2/COM/EPCI.

    Accepte un séparateur ``;`` (défaut SERM) ou ``,``.
    """
    if not chemin.is_file():
        raise FileNotFoundError(f"Lookup introuvable : {chemin}")
    LOG.info("Lecture du lookup macrozone : %s", chemin)
    df = pd.read_csv(chemin, sep=";", dtype=str)
    if len(df.columns) == 1:
        df = pd.read_csv(chemin, sep=",", dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    requis = {"ID_ZONAGE", "M1", "M2"}
    manquantes = requis - set(df.columns)
    if manquantes:
        raise ValueError(
            f"Colonnes manquantes dans le lookup : {sorted(manquantes)}"
        )
    df["ID_ZONAGE"] = pd.to_numeric(df["ID_ZONAGE"], errors="coerce").astype("Int64")
    df["M1"] = pd.to_numeric(df["M1"], errors="coerce").astype("Int64")
    df["M2"] = pd.to_numeric(df["M2"], errors="coerce").astype("Int64")
    return df


# ---------------------------------------------------------------------------
# Construction du code SERM par zone
# ---------------------------------------------------------------------------

def assigner_code_serm(
    gdf: gpd.GeoDataFrame, lookup: pd.DataFrame
) -> gpd.GeoDataFrame:
    """Joint le lookup au zonage et assigne ``code_serm`` selon le referentiel.

    Une zone est attribuee a un SERM si elle correspond a son couple
    (source_macrozonage, code_macrozone). M1 et M2 etant independants
    par construction (cf. note OPSAM), une zone est dans au plus un SERM.
    """
    gdf = gdf.merge(
        lookup[["ID_ZONAGE", "M1", "M2"]],
        on="ID_ZONAGE",
        how="left",
        suffixes=("", "_lookup"),
    )

    def _resoudre(row) -> dict:
        for entree in SERM_REFERENTIEL:
            col = entree["source_macrozonage"]
            val = row.get(col)
            if pd.notna(val) and int(val) == entree["code_macrozone"]:
                return {
                    "code_serm": entree["code_serm"],
                    "nom_serm": entree["nom_serm"],
                    "slug_serm": entree["slug_serm"],
                }
        return {"code_serm": 0, "nom_serm": "Hors SERM", "slug_serm": "hors_serm"}

    attribs = gdf.apply(_resoudre, axis=1, result_type="expand")
    return gpd.GeoDataFrame(
        pd.concat([gdf.drop(columns=attribs.columns, errors="ignore"), attribs], axis=1),
        geometry=gdf.geometry,
        crs=gdf.crs,
    )


# ---------------------------------------------------------------------------
# Dissolution + simplification
# ---------------------------------------------------------------------------

def dissoudre_serm(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Dissout les zones par SERM et simplifie les multipolygones.

    La simplification est faite dans la projection metrique
    (RGF93 Lambert 93) puis le resultat est reproject vers WGS84
    pour la cartographie.
    """
    LOG.info("Reprojection en Lambert 93 pour calculs metriques")
    gdf_lambert = gdf.to_crs(EPSG_CALCULS)
    LOG.info("Dissolution par code_serm")
    dissous = gdf_lambert[["code_serm", "nom_serm", "slug_serm", "geometry"]].dissolve(
        by="code_serm", as_index=False, aggfunc="first"
    )
    LOG.info(
        "Simplification (tolerance %g m)", TOLERANCE_SIMPLIFICATION_M
    )
    dissous["geometry"] = dissous["geometry"].simplify(
        TOLERANCE_SIMPLIFICATION_M, preserve_topology=True
    )
    dissous["surface_km2"] = dissous.geometry.area / 1e6
    # On exclut le code_serm = 0 (reste BFC) du fichier final, garde la presence
    # mais on l'isole dans une couche dediee.
    dissous_wgs = dissous.to_crs(EPSG_AFFICHAGE)
    return dissous_wgs


def ecrire_geojson(gdf: gpd.GeoDataFrame, chemin: Path) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if chemin.exists():
        chemin.unlink()
    gdf.to_file(chemin, driver="GeoJSON")


# ---------------------------------------------------------------------------
# Point d'entree CLI
# ---------------------------------------------------------------------------

def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--zonage", type=Path, default=None,
        help="Shapefile zonage OPSAM (sinon SERM_ZONAGE_SHP).",
    )
    parser.add_argument(
        "--lookup", type=Path, default=None,
        help="Lookup macrozone (sinon SERM_LOOKUP_CSV).",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=None,
        help="Dossier de sortie (sinon SERM_DATA_DIR ou ./data).",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Logs detailles."
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    zonage = args.zonage or _zonage_shp()
    lookup = args.lookup or _lookup_csv()
    data = args.data_dir or _data_dir()

    gdf = lire_zonage(zonage)
    df_lookup = lire_lookup(lookup)
    gdf_codes = assigner_code_serm(gdf, df_lookup)

    nb_par_serm = gdf_codes.groupby("nom_serm").size().to_dict()
    LOG.info("Nb de zones OPSAM par SERM : %s", nb_par_serm)

    # Couche zones SERM uniquement (alleg\u00e9e + simplification metrique).
    couche_zones_l = gdf_codes[gdf_codes["code_serm"] > 0][[
        "ID_ZONAGE", "code_serm", "nom_serm", "slug_serm", "geometry",
    ]].copy().to_crs(EPSG_CALCULS)
    couche_zones_l["geometry"] = couche_zones_l["geometry"].simplify(
        TOLERANCE_SIMPLIFICATION_M, preserve_topology=True
    )
    couche_zones = couche_zones_l.to_crs(EPSG_AFFICHAGE)

    # Couche dissoute : un polygone par SERM (hors reste BFC).
    couche_serm = dissoudre_serm(gdf_codes[gdf_codes["code_serm"] > 0])

    chemin_perimetres = data / "perimetres_serm.geojson"
    chemin_zones = data / "zones_serm.geojson"
    ecrire_geojson(couche_serm, chemin_perimetres)
    ecrire_geojson(couche_zones, chemin_zones)
    LOG.info(
        "Ecrit %s (%d entites) et %s (%d entites)",
        chemin_perimetres, len(couche_serm), chemin_zones, len(couche_zones),
    )
    return 0


if __name__ == "__main__":
    # Permettre l'import direct des constantes des autres scripts.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
