"""I/E/T du reseau et somme des deux sens d'un lien."""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from prepare_reseau_serm import (  # noqa: E402
    agreger_sens_contraire,
    calculer_flux_iet_recales,
)


def _ligne(a: int, b: int, tmja: float, m1, m2) -> dict:
    return {
        "A": a,
        "B": b,
        "CL_ADMIN": "Departementale",
        "TMJA_P": tmja,
        "PL_P": 0.0,
        "VOLUME": 100.0,
        "VOL_M1_I": m1[0],
        "VOL_M1_E": m1[1],
        "VOL_M1_T": m1[2],
        "VOL_M2_I": m2[0],
        "VOL_M2_E": m2[1],
        "VOL_M2_T": m2[2],
        "geometry": LineString([(a, 0), (b, 0)]),
    }


def test_m2_sans_echange_utilise_m1():
    """VOL_M2_E vide : le ratio echange/transit vient de M1."""
    gdf = gpd.GeoDataFrame(
        [_ligne(1, 2, 200, (10, 60, 30), (100, 0, 0))],
        crs="EPSG:2154",
    )
    out = calculer_flux_iet_recales(gdf, "M2")
    assert out["source_macrozone"].iloc[0] == "M1"
    assert out["TMJA_E"].iloc[0] == 120
    assert out["TMJA_T"].iloc[0] == 60
    assert out["TMJA_I"].iloc[0] == 20


def test_m1_conserve_quand_il_decompose():
    """Dijon reste sur M1 si ses colonnes portent l'echange."""
    gdf = gpd.GeoDataFrame(
        [_ligne(1, 2, 100, (40, 40, 20), (100, 0, 0))],
        crs="EPSG:2154",
    )
    out = calculer_flux_iet_recales(gdf, "M1")
    assert out["source_macrozone"].iloc[0] == "M1"
    assert out["TMJA_E"].iloc[0] == 40


def test_deux_sens_sommes_une_fois():
    """Le sens inverse s'ajoute. Deux morceaux du meme sens ne doublent pas."""
    aller = _ligne(1, 2, 100, (50, 50, 0), (100, 0, 0))
    morceau = dict(aller)
    morceau["geometry"] = LineString([(1, 0), (1.5, 0)])
    retour = _ligne(2, 1, 40, (20, 80, 0), (100, 0, 0))
    gdf = gpd.GeoDataFrame(
        [aller, morceau, retour], crs="EPSG:2154"
    )
    flux = calculer_flux_iet_recales(gdf, "M2")
    out = agreger_sens_contraire(flux)
    assert len(out) == 1
    assert float(out["TMJA_P"].iloc[0]) == 140
    assert float(out["TMJA_E"].iloc[0]) == 50 + 32


def test_volume_absent_met_iet_a_zero():
    """Sans VOLUME, les indicateurs I/E/T restent a 0."""
    gdf = gpd.GeoDataFrame(
        [{
            "A": 1,
            "B": 2,
            "TMJA_P": 10,
            "geometry": LineString([(0, 0), (1, 0)]),
        }],
        crs="EPSG:2154",
    )
    out = calculer_flux_iet_recales(gdf, "M2")
    assert float(out["TMJA_E"].iloc[0]) == 0
    assert float(out["PART_T"].iloc[0]) == 0
