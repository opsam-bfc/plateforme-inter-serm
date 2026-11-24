"""Zones a cheval M1/M2 restent dans chaque perimetre SERM."""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from prepare_perimetres_serm import assigner_code_serm  # noqa: E402


def _zone(identifiant: int) -> dict:
    return {
        "ID_ZONAGE": identifiant,
        "geometry": Point(identifiant, 47.0),
    }


def test_zone_m2_seule_dans_bisontin():
    """M2=3 sans M1 va au SERM Bisontin."""
    zones = gpd.GeoDataFrame([_zone(1)], crs="EPSG:4326")
    lookup = pd.DataFrame(
        [{"ID_ZONAGE": 1, "M1": 0, "M2": 3}]
    )
    out = assigner_code_serm(zones, lookup)
    assert list(out["code_serm"]) == [3]
    assert list(out["slug_serm"]) == ["besancon"]


def test_zone_m1_et_m2_dans_les_deux_perimetres():
    """CC Jura Nord / Val de Gray : M1=1 et M2=3, deux lignes."""
    zones = gpd.GeoDataFrame([_zone(10)], crs="EPSG:4326")
    lookup = pd.DataFrame(
        [{"ID_ZONAGE": 10, "M1": 1, "M2": 3}]
    )
    out = assigner_code_serm(zones, lookup)
    assert set(out["code_serm"]) == {1, 3}
    assert len(out) == 2
    assert out.loc[out["code_serm"] == 3, "slug_serm"].iloc[0] == "besancon"


def test_zone_hors_serm_et_lookup_absent():
    """M1=M2=0 ou zone absente du lookup : hors SERM."""
    zones = gpd.GeoDataFrame([_zone(2), _zone(3)], crs="EPSG:4326")
    lookup = pd.DataFrame(
        [{"ID_ZONAGE": 2, "M1": 0, "M2": 0}]
    )
    out = assigner_code_serm(zones, lookup)
    assert set(out["code_serm"]) == {0}
    assert len(out) == 2
