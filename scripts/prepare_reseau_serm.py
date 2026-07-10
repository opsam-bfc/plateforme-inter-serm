"""prepare_reseau_serm.py.

Decoupe le reseau routier OPSAM (``reseau_detaille_linkshape_Ref2024.shp``)
en sous-reseaux par SERM, par intersection spatiale avec les polygones
SERM dissous.

Source privilegiee : ``Base/Ref2024/reseau_detaille_linkshape_Ref2024.shp``
qui contient les champs de trafic modelise consolides :
  - ``TMJA_P`` : TMJA total tous vehicules (toutes macrozones confondues)
  - ``PL_P``   : volume PL absolu (vehicules/jour)
  - ``VL_jour`` = ``TMJA_P`` - ``PL_P`` (calcule a la volee)

Seuls les troncons du reseau classe (Autoroute, Nationale, Departementale)
sont conserves. Les troncons sans trafic modelise (TMJA_P = 0) restent dans
le fichier et sont affiches en gris sur la carte.

Sortie : un GeoPackage par SERM dans ``data/reseau_serm/``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Iterable

import geopandas as gpd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOG = logging.getLogger("prepare_reseau_serm")

EPSG_AFFICHAGE = 4326
EPSG_CALCULS = 2154

# Classes administratives du reseau a conserver (les connecteurs "Conn"
# et les voies non classifiees "NoData" sont exclus car trop nombreux
# et non pertinents pour la carto inter-SERM).
CLASSES_ADMIN_VALIDES = {"Autoroute", "Nationale", "Departementale"}

# Attributs du shapefile reseau_detaille_linkshape conserves dans le bundle.
# TMJA_P = trafic modelise consolide (toutes macrozones), PL_P = volume PL absolu.
ATTRIBUTS_CONSERVES = [
    "ID",
    "NATURE",
    "CL_ADMIN",
    "NUMERO",
    "DISTANCE",
    "NB_VOIES",
    "TMJA_P",
    "PL_P",
    "INSEECOM_G",
    "INSEECOM_D",
]


# ---------------------------------------------------------------------------
# Helpers chemins
# ---------------------------------------------------------------------------

def _reseau_shp() -> Path:
    v = os.environ.get("SERM_RESEAU_SHP")
    if v:
        return Path(v)
    # Utilise reseau_detaille_linkshape (Base/) qui contient TMJA_P et PL_P.
    # Fallback : variable SERM_OPSAM_BASE_DIR pour configurer le dossier Base/.
    base_dir = os.environ.get("SERM_OPSAM_BASE_DIR") or r"\\poste-2-170\OPSAM_v3\OPSAM\Base\Ref2024"
    return Path(base_dir) / "reseau_detaille_linkshape_Ref2024.shp"


def _data_dir() -> Path:
    v = os.environ.get("SERM_DATA_DIR")
    if v:
        return Path(v)
    return Path(__file__).resolve().parents[1] / "data"


# ---------------------------------------------------------------------------
# Traitement principal
# ---------------------------------------------------------------------------

def lire_perimetres(chemin: Path) -> gpd.GeoDataFrame:
    """Lit le geojson des perimetres SERM dissous."""
    if not chemin.is_file():
        raise FileNotFoundError(
            f"Perimetres SERM introuvables : {chemin}. "
            "Lancer d'abord prepare_perimetres_serm.py."
        )
    gdf = gpd.read_file(chemin)
    return gdf.to_crs(EPSG_CALCULS)


def lire_reseau(chemin: Path) -> gpd.GeoDataFrame:
    """Lit le shapefile reseau routier (RGF93 Lambert 93 / EPSG:2154).

    Utilise ``reseau_detaille_linkshape_Ref2024.shp`` (dossier Base/)
    qui contient les champs ``TMJA_P`` et ``PL_P`` issus de l'affectation
    CUBE.  Si le CRS n'est pas detecte, on l'impose en EPSG:2154.
    """
    if not chemin.is_file():
        raise FileNotFoundError(f"Reseau introuvable : {chemin}")
    LOG.info("Lecture du reseau : %s", chemin)
    gdf = gpd.read_file(chemin)
    if gdf.crs is None:
        LOG.warning(
            "Aucun CRS dans le shapefile, hypothese RGF93 Lambert 93 (EPSG:2154)"
        )
        gdf = gdf.set_crs(EPSG_CALCULS, allow_override=True)
    else:
        gdf = gdf.to_crs(EPSG_CALCULS)
    LOG.info("Reseau : %d troncons, CRS : %s", len(gdf), gdf.crs.to_epsg())
    cols_presentes = [c for c in ATTRIBUTS_CONSERVES if c in gdf.columns]
    manquantes = [c for c in ATTRIBUTS_CONSERVES if c not in gdf.columns]
    if manquantes:
        LOG.warning("Colonnes absentes du shapefile : %s", manquantes)
    return gdf[cols_presentes + ["geometry"]]


def calculer_volumes_derives(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Ajoute les colonnes ``VL_jour`` et ``PL_jour`` (vehicules/jour).

    ``TMJA_P`` = trafic total consolide (tous vehicules, modelise).
    ``PL_P``   = volume PL absolu (vehicules/jour, modelise).
    ``VL_jour`` = max(0, TMJA_P - PL_P).
    ``PL_jour`` = PL_P (alias explicite pour coherence avec les autres vues).
    """
    gdf = gdf.copy()
    if "TMJA_P" in gdf.columns and "PL_P" in gdf.columns:
        tmja = gdf["TMJA_P"].fillna(0).clip(lower=0)
        pl = gdf["PL_P"].fillna(0).clip(lower=0)
        gdf["PL_jour"] = pl
        gdf["VL_jour"] = (tmja - pl).clip(lower=0)
    return gdf


def decouper_par_serm(
    gdf_reseau: gpd.GeoDataFrame,
    gdf_perimetres: gpd.GeoDataFrame,
    data_dir: Path,
) -> dict[str, Path]:
    """Pour chaque SERM, calcule l'intersection (clip) et ecrit un GPKG.

    Seul le reseau classe est conserve (Autoroute, Nationale,
    Departementale). Les connecteurs internes et voies non classifiees
    (CL_ADMIN = "Conn" / "NoData") sont exclus. Les troncons sans
    trafic modelise (TMJA_P = 0) restent dans le fichier et sont
    affiches en gris sur la carte.
    """
    dossier = data_dir / "reseau_serm"
    dossier.mkdir(parents=True, exist_ok=True)
    chemins: dict[str, Path] = {}

    if "CL_ADMIN" in gdf_reseau.columns:
        avant = len(gdf_reseau)
        gdf_reseau = gdf_reseau[
            gdf_reseau["CL_ADMIN"].isin(CLASSES_ADMIN_VALIDES)
        ].copy()
        LOG.info(
            "Filtre CL_ADMIN %s : %d -> %d troncons",
            CLASSES_ADMIN_VALIDES, avant, len(gdf_reseau),
        )

    sindex = gdf_reseau.sindex

    for _, row in gdf_perimetres.iterrows():
        slug = row["slug_serm"]
        nom = row["nom_serm"]
        polygone = row.geometry

        LOG.info("Decoupe pour SERM %s", nom)
        candidats_idx = list(sindex.query(polygone, predicate="intersects"))
        if not candidats_idx:
            LOG.warning("Aucun troncon n'intersecte le SERM %s", nom)
            continue
        candidats = gdf_reseau.iloc[candidats_idx]
        clipes = gpd.clip(candidats, polygone, keep_geom_type=True)
        if clipes.empty:
            LOG.warning("Clip vide pour SERM %s", nom)
            continue
        clipes = clipes.copy()
        clipes["DISTANCE_clip_km"] = clipes.geometry.length / 1000.0
        clipes = calculer_volumes_derives(clipes)
        clipes["slug_serm"] = slug
        clipes["nom_serm"] = nom

        clipes = clipes.to_crs(EPSG_AFFICHAGE)

        chemin = dossier / f"{slug}.gpkg"
        if chemin.exists():
            chemin.unlink()
        clipes.to_file(chemin, driver="GPKG")
        LOG.info(
            "Ecrit %s (%d troncons, %.1f km cumules)",
            chemin,
            len(clipes),
            float(clipes["DISTANCE_clip_km"].sum()),
        )
        chemins[slug] = chemin

    return chemins


# ---------------------------------------------------------------------------
# Point d'entree CLI
# ---------------------------------------------------------------------------

def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reseau", type=Path, default=None,
        help="Shapefile reseau OPSAM (sinon SERM_RESEAU_SHP).",
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

    data = args.data_dir or _data_dir()
    perimetres = lire_perimetres(data / "perimetres_serm.geojson")
    reseau = lire_reseau(args.reseau or _reseau_shp())
    decouper_par_serm(reseau, perimetres, data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
