"""prepare_od_vl.py.

Agrege la matrice OD VL d'OPSAM en plusieurs vues utiles pour la
plateforme :

* matrice inter-SERM 4 x 4 (3 SERM + reste BFC) ;
* echanges agreges par EPCI pour chaque SERM ;
* top N flux OD VL agreges a la commune (flux internes) ou a l'EPCI
  (flux echanges), avec centroides pour le trace des arcs.

Sorties (dossier ``data/``) :
  - ``matrice_inter_serm.csv``
  - ``echanges_epci_serm.parquet``
  - ``top_od_vl_par_serm.parquet``   (anciennes zones OPSAM, garde pour compat)
  - ``top_od_com_serm.parquet``       (agrege : commune interne, EPCI echange)
  - ``centroides_zones.parquet``
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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOG = logging.getLogger("prepare_od_vl")

EPSG_AFFICHAGE = 4326
EPSG_CALCULS = 2154

TOP_N_DEFAUT = 300
# Flux conserves en plus du top global, pour chaque EPCI implique : garantit
# qu'un EPCI a faibles volumes reste filtrable dans la plateforme.
TOP_N_EPCI_DEFAUT = 50


# ---------------------------------------------------------------------------
# Helpers chemins
# ---------------------------------------------------------------------------

def _matrice_vl_csv() -> Path:
    v = os.environ.get("SERM_MATRICE_VL_CSV")
    if v:
        return Path(v)
    opsam = os.environ.get("SERM_OPSAM_DIR") or r"\\poste-2-170\OPSAM_v3\OPSAM\Outputs\Ref2024"
    return Path(opsam) / "matrice_vl_Ref2024.csv"


def _lookup_csv() -> Path:
    v = os.environ.get("SERM_LOOKUP_CSV")
    if v:
        return Path(v)
    return Path(
        r"\\nas-bfc\COMMUN\21_MOBILITE\21.4_PROJETS\DREAL\2026_SERM"
        r"\2_INPUT\DATA\lookupfile_serm"
        r"\lookup_dep_com_epci_macrozone.csv"
    )


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


def _data_dir() -> Path:
    v = os.environ.get("SERM_DATA_DIR")
    if v:
        return Path(v)
    return Path(__file__).resolve().parents[1] / "data"


# ---------------------------------------------------------------------------
# Lecture des noms EPCI
# ---------------------------------------------------------------------------

def lire_noms_epci(chemin: Path) -> dict[str, str]:
    """Retourne un dict {code_EPCI: nom_EPCI} depuis le shapefile EPCI.

    Si le fichier est absent, renvoie un dictionnaire vide (noms = codes).
    """
    if not chemin.exists():
        LOG.warning("Shapefile EPCI introuvable : %s", chemin)
        return {}
    try:
        import geopandas as gpd
        gdf = gpd.read_file(chemin, columns=["CODE_SIREN", "NOM"])
        mapping = dict(zip(gdf["CODE_SIREN"].astype(str), gdf["NOM"].astype(str)))
        LOG.info("Noms EPCI charges : %d entrees", len(mapping))
        return mapping
    except Exception as exc:
        LOG.warning("Lecture shapefile EPCI echouee : %s", exc)
        return {}


def enrichir_noms_epci(df: pd.DataFrame, noms: dict[str, str],
                       cols: list[str]) -> pd.DataFrame:
    """Ajoute une colonne ``{col}_nom`` pour chaque colonne de code EPCI."""
    df = df.copy()
    for col in cols:
        if col not in df.columns:
            continue
        df[f"{col}_nom"] = df[col].astype(str).map(noms).fillna(
            "EPCI " + df[col].astype(str)
        )
    return df


# ---------------------------------------------------------------------------
# Lecture matrice et lookup
# ---------------------------------------------------------------------------

def lire_matrice_od(chemin: Path) -> pd.DataFrame:
    """Lit la matrice OD VL (CSV sans entete : O, D, volume)."""
    if not chemin.is_file():
        raise FileNotFoundError(f"Matrice OD introuvable : {chemin}")
    LOG.info("Lecture matrice OD : %s", chemin)
    df = pd.read_csv(chemin, header=None, names=["O", "D", "volume"])
    df["O"] = pd.to_numeric(df["O"], errors="coerce").astype("Int64")
    df["D"] = pd.to_numeric(df["D"], errors="coerce").astype("Int64")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0)
    df = df.dropna(subset=["O", "D"])
    LOG.info("Matrice OD : %d couples, volume total = %.0f", len(df), df["volume"].sum())
    return df


def lire_lookup(chemin: Path) -> pd.DataFrame:
    """Lit le lookup ID_ZONAGE -> M1/M2/EPCI/COM.

    Accepte un séparateur ``;`` (défaut SERM) ou ``,``.
    """
    if not chemin.is_file():
        raise FileNotFoundError(f"Lookup introuvable : {chemin}")
    df = pd.read_csv(chemin, sep=";", dtype=str)
    if len(df.columns) == 1:
        df = pd.read_csv(chemin, sep=",", dtype=str)
    df.columns = [str(c).strip() for c in df.columns]
    df["ID_ZONAGE"] = pd.to_numeric(df["ID_ZONAGE"], errors="coerce").astype("Int64")
    df["M1"] = pd.to_numeric(df["M1"], errors="coerce").fillna(0).astype("Int64")
    df["M2"] = pd.to_numeric(df["M2"], errors="coerce").fillna(0).astype("Int64")
    df["EPCI"] = df["EPCI"].astype(str)
    df["COM"] = df["COM"].astype(str)
    return df


def assigner_code_serm_lookup(lookup: pd.DataFrame) -> pd.DataFrame:
    """Ajoute les appartenances SERM M1/M2 et ``code_serm`` de repli.

    Certaines zones ont M1=1 (Dijon) **et** M2=3 (Besançon).  L'ancienne
    logique ecrasait M1 par M2 ; on conserve ``serm_m1`` / ``serm_m2``.
    """
    lookup = lookup.copy()
    lookup["serm_m1"] = lookup["M1"].where(
        lookup["M1"].isin([1, 2]), 0
    ).astype(int)
    lookup["serm_m2"] = lookup["M2"].where(
        lookup["M2"] == 3, 0
    ).astype(int)
    lookup["code_serm"] = lookup["serm_m1"]
    masque_m2 = lookup["code_serm"] == 0
    lookup.loc[masque_m2, "code_serm"] = lookup.loc[masque_m2, "serm_m2"]
    return lookup


def _colonnes_serm_flux(code_serm: int) -> tuple[str, str]:
    """Colonnes origine/destination a filtrer pour un SERM donne."""
    if code_serm in (1, 2):
        return "serm_m1_O", "serm_m1_D"
    if code_serm == 3:
        return "serm_m2_O", "serm_m2_D"
    return "serm_O", "serm_D"


def _masque_interne_serm(df_od: pd.DataFrame, code_serm: int) -> pd.Series:
    col_o, col_d = _colonnes_serm_flux(code_serm)
    return (df_od[col_o] == code_serm) & (df_od[col_d] == code_serm)


def _masque_echange_serm(df_od: pd.DataFrame, code_serm: int) -> pd.Series:
    col_o, col_d = _colonnes_serm_flux(code_serm)
    return (
        ((df_od[col_o] == code_serm) & (df_od[col_d] != code_serm))
        | ((df_od[col_d] == code_serm) & (df_od[col_o] != code_serm))
    )


# ---------------------------------------------------------------------------
# Centroides
# ---------------------------------------------------------------------------

def calculer_centroides_zones(
    chemin_zonage: Path, lookup_enrichi: pd.DataFrame
) -> pd.DataFrame:
    """Calcule lon/lat des centroides des zones OPSAM (en WGS84)."""
    LOG.info("Lecture zonage pour calcul des centroides : %s", chemin_zonage)
    gdf = gpd.read_file(chemin_zonage, columns=["ID_ZONAGE", "NOM_COM", "INSEE_COM"])
    if gdf.crs is None:
        gdf = gdf.set_crs(EPSG_CALCULS, allow_override=True)
    # Centroide en Lambert 93 (precis) puis reprojection WGS84.
    gdf_l = gdf.to_crs(EPSG_CALCULS)
    centro_l = gdf_l.copy()
    centro_l["geometry"] = centro_l.geometry.representative_point()
    centro = centro_l.to_crs(EPSG_AFFICHAGE)
    centro["lon"] = centro.geometry.x
    centro["lat"] = centro.geometry.y
    centro = centro.drop(columns=["geometry"])
    centro = centro.merge(
        lookup_enrichi[[
            "ID_ZONAGE", "code_serm", "serm_m1", "serm_m2",
            "EPCI", "COM", "M1", "M2",
        ]],
        on="ID_ZONAGE", how="left",
    )
    centro["code_serm"] = centro["code_serm"].fillna(0).astype(int)
    LOG.info("Centroides calcules pour %d zones", len(centro))
    return centro


# ---------------------------------------------------------------------------
# Jointures OD <-> lookup
# ---------------------------------------------------------------------------

def joindre_attributs(
    matrice: pd.DataFrame, lookup_enrichi: pd.DataFrame
) -> pd.DataFrame:
    """Joint M1/M2/appartenances SERM/EPCI/COM aux extremites OD."""
    cols_o = {
        "ID_ZONAGE": "O",
        "code_serm": "serm_O",
        "serm_m1": "serm_m1_O",
        "serm_m2": "serm_m2_O",
        "EPCI": "epci_O",
        "COM": "com_O",
    }
    cols_d = {
        "ID_ZONAGE": "D",
        "code_serm": "serm_D",
        "serm_m1": "serm_m1_D",
        "serm_m2": "serm_m2_D",
        "EPCI": "epci_D",
        "COM": "com_D",
    }
    keep = list(cols_o.keys())
    LOG.info("Jointure attributs origine")
    df = matrice.merge(
        lookup_enrichi[keep].rename(columns=cols_o), on="O", how="left",
    )
    LOG.info("Jointure attributs destination")
    df = df.merge(
        lookup_enrichi[keep].rename(columns=cols_d), on="D", how="left",
    )
    for col in (
        "serm_O", "serm_D", "serm_m1_O", "serm_m1_D",
        "serm_m2_O", "serm_m2_D",
    ):
        df[col] = df[col].fillna(0).astype(int)
    return df


# ---------------------------------------------------------------------------
# Agregats
# ---------------------------------------------------------------------------

NOMS_SERM = {
    0: "Reste BFC",
    1: "SERM Dijonnais",
    2: "SERM Nord Franche-Comte",
    3: "SERM Bisontin",
}


def matrice_inter_serm(df_od: pd.DataFrame) -> pd.DataFrame:
    """Matrice des volumes VL entre SERM (origine x destination)."""
    pivot = (
        df_od.groupby(["serm_O", "serm_D"])["volume"].sum().reset_index()
    )
    pivot["serm_O_nom"] = pivot["serm_O"].map(NOMS_SERM)
    pivot["serm_D_nom"] = pivot["serm_D"].map(NOMS_SERM)
    return pivot[["serm_O", "serm_O_nom", "serm_D", "serm_D_nom", "volume"]]


def echanges_epci_par_serm(df_od: pd.DataFrame) -> pd.DataFrame:
    """Pour chaque SERM, agrege les volumes EPCI_O x EPCI_D.

    Trois grandes typologies de flux :
      * ``interne_serm`` : O et D dans le meme SERM ;
      * ``echange_serm`` : O dans le SERM, D hors (ou inverse) ;
      * ``transit`` : ni O ni D dans le SERM (pas analyse ici).
    """
    blocs = []
    for code_serm, nom in NOMS_SERM.items():
        if code_serm == 0:
            continue
        masque_interne = _masque_interne_serm(df_od, code_serm)
        interne = (
            df_od[masque_interne]
            .groupby(["epci_O", "epci_D"])["volume"].sum().reset_index()
            .assign(serm=code_serm, nom_serm=nom, typologie="interne_serm")
        )
        masque_echange = _masque_echange_serm(df_od, code_serm)
        masque_epci_valides = (
            (df_od["epci_O"].astype(str) != "0")
            & (df_od["epci_D"].astype(str) != "0")
        )
        echange = (
            df_od[masque_echange & masque_epci_valides]
            .groupby(["epci_O", "epci_D"])["volume"].sum().reset_index()
            .assign(serm=code_serm, nom_serm=nom, typologie="echange_serm")
        )
        blocs.append(interne)
        blocs.append(echange)
    return pd.concat(blocs, ignore_index=True)


def top_od_par_serm(
    df_od: pd.DataFrame, centroides: pd.DataFrame, top_n: int = TOP_N_DEFAUT
) -> pd.DataFrame:
    """Top N flux OD VL par SERM (interne + echange), granularite zone OPSAM."""
    df_od = df_od[df_od["O"] != df_od["D"]].copy()
    centro = centroides[["ID_ZONAGE", "lon", "lat", "NOM_COM"]].copy()

    blocs = []
    for code_serm, nom in NOMS_SERM.items():
        if code_serm == 0:
            continue
        for typo, masque in (
            ("interne_serm", _masque_interne_serm(df_od, code_serm)),
            ("echange_emis", (
                _masque_echange_serm(df_od, code_serm)
                & (df_od[_colonnes_serm_flux(code_serm)[0]] == code_serm)
            )),
            ("echange_recus", (
                _masque_echange_serm(df_od, code_serm)
                & (df_od[_colonnes_serm_flux(code_serm)[1]] == code_serm)
            )),
        ):
            top = df_od[masque].nlargest(top_n, "volume").copy()
            top["serm"] = code_serm
            top["nom_serm"] = nom
            top["typologie"] = typo
            blocs.append(top)

    top_total = pd.concat(blocs, ignore_index=True)
    top_total = top_total.merge(
        centro.rename(columns={
            "ID_ZONAGE": "O", "lon": "lon_O", "lat": "lat_O", "NOM_COM": "nom_com_O",
        }),
        on="O", how="left",
    )
    top_total = top_total.merge(
        centro.rename(columns={
            "ID_ZONAGE": "D", "lon": "lon_D", "lat": "lat_D", "NOM_COM": "nom_com_D",
        }),
        on="D", how="left",
    )
    return top_total


# ---------------------------------------------------------------------------
# Centroides agreges (commune et EPCI)
# ---------------------------------------------------------------------------

def centroides_communes(centroides_zones: pd.DataFrame) -> pd.DataFrame:
    """Centroide moyen des zones OPSAM regroupe par commune INSEE (COM)."""
    return (
        centroides_zones.dropna(subset=["COM"])
        .groupby("COM")
        .agg(lon=("lon", "mean"), lat=("lat", "mean"),
             NOM_COM=("NOM_COM", "first"),
             code_serm=("code_serm", "first"),
             EPCI=("EPCI", "first"))
        .reset_index()
    )


def centroides_epci(centroides_zones: pd.DataFrame) -> pd.DataFrame:
    """Centroide moyen des zones OPSAM regroupe par EPCI."""
    return (
        centroides_zones.dropna(subset=["EPCI"])
        .groupby("EPCI")
        .agg(lon=("lon", "mean"), lat=("lat", "mean"),
             code_serm=("code_serm", "first"))
        .reset_index()
    )


def _tops_par_epci(
    agg: pd.DataFrame,
    cles_couple: list[str],
    top_n: int,
    top_n_epci: int,
) -> pd.DataFrame:
    """Union du top global et du top de chaque EPCI implique.

    Sans cette union, un EPCI aux volumes modestes (ex. une CC rurale
    recemment rattachee a un SERM) n'apparait dans aucun couple du top
    global : le filtre par territoire de l'application ne trouve alors
    aucun flux, bien que ceux-ci existent dans la matrice OD.
    """
    blocs = [agg.nlargest(top_n, "volume")]
    if top_n_epci > 0:
        codes = pd.unique(
            pd.concat(
                [agg.get("epci_O"), agg.get("epci_D")]
            ).dropna().astype(str)
        )
        for code_epci in codes:
            if code_epci in ("0", "", "nan", "None"):
                continue
            masque = pd.Series(False, index=agg.index)
            for col in ("epci_O", "epci_D"):
                if col in agg.columns:
                    masque |= agg[col].astype(str) == code_epci
            blocs.append(agg[masque].nlargest(top_n_epci, "volume"))
    return (
        pd.concat(blocs, ignore_index=True)
        .drop_duplicates(subset=cles_couple)
        .reset_index(drop=True)
    )


def top_od_communes_par_serm(
    df_od: pd.DataFrame,
    centroides_zones: pd.DataFrame,
    top_n: int = TOP_N_DEFAUT,
    top_n_epci: int = TOP_N_EPCI_DEFAUT,
) -> pd.DataFrame:
    """Top N flux OD agreges a la commune (interne) ou a l'EPCI (echange).

    Au top global s'ajoute, pour chaque EPCI implique, ses ``top_n_epci``
    plus gros flux : le filtre par territoire de l'application reste ainsi
    exploitable pour les EPCI a faibles volumes.

    Colonnes de sortie :
      serm, nom_serm, typologie, com_O, nom_O, lon_O, lat_O,
      com_D, nom_D, lon_D, lat_D, volume, epci_O, epci_D.
    """
    com_c = centroides_communes(centroides_zones)
    epci_c = centroides_epci(centroides_zones)
    com_vers_epci = (
        com_c.dropna(subset=["COM"]).set_index("COM")["EPCI"].astype(str)
    )

    blocs = []
    for code_serm, nom in NOMS_SERM.items():
        if code_serm == 0:
            continue

        # -- Flux internes : agregation commune x commune -------------------
        m_int = (
            _masque_interne_serm(df_od, code_serm)
            & (df_od["com_O"] != df_od["com_D"])
        )
        agg_int = (
            df_od[m_int]
            .groupby(["com_O", "com_D"])["volume"]
            .sum()
            .reset_index()
        )
        agg_int["epci_O"] = agg_int["com_O"].map(com_vers_epci)
        agg_int["epci_D"] = agg_int["com_D"].map(com_vers_epci)
        top_int = _tops_par_epci(
            agg_int, ["com_O", "com_D"], top_n, top_n_epci,
        ).assign(serm=code_serm, nom_serm=nom, typologie="interne_serm")
        top_int = top_int.merge(
            com_c[["COM", "lon", "lat", "NOM_COM"]].rename(columns={
                "COM": "com_O", "lon": "lon_O", "lat": "lat_O", "NOM_COM": "nom_O",
            }), on="com_O", how="left",
        )
        top_int = top_int.merge(
            com_c[["COM", "lon", "lat", "NOM_COM"]].rename(columns={
                "COM": "com_D", "lon": "lon_D", "lat": "lat_D", "NOM_COM": "nom_D",
            }), on="com_D", how="left",
        )
        blocs.append(top_int)

        # -- Flux emis : commune SERM -> EPCI externe (EPCI 0 exclu) ----------
        col_o, col_d = _colonnes_serm_flux(code_serm)
        m_emis = (df_od[col_o] == code_serm) & (df_od[col_d] != code_serm)
        agg_emis = (
            df_od[m_emis & (df_od["epci_D"].astype(str) != "0")]
            .groupby(["com_O", "epci_D"])["volume"]
            .sum()
            .reset_index()
        )
        agg_emis["epci_O"] = agg_emis["com_O"].map(com_vers_epci)
        top_emis = _tops_par_epci(
            agg_emis, ["com_O", "epci_D"], top_n, top_n_epci,
        ).assign(serm=code_serm, nom_serm=nom, typologie="echange_emis")
        top_emis = top_emis.merge(
            com_c[["COM", "lon", "lat", "NOM_COM"]].rename(columns={
                "COM": "com_O", "lon": "lon_O", "lat": "lat_O", "NOM_COM": "nom_O",
            }), on="com_O", how="left",
        )
        top_emis = top_emis.merge(
            epci_c[["EPCI", "lon", "lat"]].rename(columns={
                "EPCI": "epci_D", "lon": "lon_D", "lat": "lat_D",
            }), on="epci_D", how="left",
        )
        top_emis["com_D"] = top_emis["epci_D"]
        # nom_D sera rempli apres (necessaire pour avoir noms_epci disponible)
        blocs.append(top_emis)

        # -- Flux recus : EPCI externe -> commune SERM (EPCI 0 exclu) ---------
        m_recus = (df_od[col_d] == code_serm) & (df_od[col_o] != code_serm)
        agg_recus = (
            df_od[m_recus & (df_od["epci_O"].astype(str) != "0")]
            .groupby(["epci_O", "com_D"])["volume"]
            .sum()
            .reset_index()
        )
        agg_recus["epci_D"] = agg_recus["com_D"].map(com_vers_epci)
        top_recus = _tops_par_epci(
            agg_recus, ["epci_O", "com_D"], top_n, top_n_epci,
        ).assign(serm=code_serm, nom_serm=nom, typologie="echange_recus")
        top_recus = top_recus.merge(
            epci_c[["EPCI", "lon", "lat"]].rename(columns={
                "EPCI": "epci_O", "lon": "lon_O", "lat": "lat_O",
            }), on="epci_O", how="left",
        )
        top_recus["com_O"] = top_recus["epci_O"]
        # nom_O sera rempli apres
        top_recus = top_recus.merge(
            com_c[["COM", "lon", "lat", "NOM_COM"]].rename(columns={
                "COM": "com_D", "lon": "lon_D", "lat": "lat_D", "NOM_COM": "nom_D",
            }), on="com_D", how="left",
        )
        blocs.append(top_recus)

    df_final = pd.concat(blocs, ignore_index=True)
    for col in ["nom_O", "nom_D", "com_O", "com_D",
                "lon_O", "lat_O", "lon_D", "lat_D",
                "epci_O", "epci_D"]:
        if col not in df_final.columns:
            df_final[col] = None
    # nom_O / nom_D des entrees EPCI (flux emis/recus) sont a None ici ;
    # l'appelant (main) les remplira avec les vrais noms EPCI.
    return df_final[[
        "serm", "nom_serm", "typologie",
        "com_O", "nom_O", "lon_O", "lat_O",
        "com_D", "nom_D", "lon_D", "lat_D",
        "volume", "epci_O", "epci_D",
    ]]


def _code_epci_str(serie: pd.Series) -> pd.Series:
    """Normalise les codes EPCI (entiers, flottants, chaines)."""
    return (
        serie.astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
    )


def appliquer_noms_epci_top_od(
    df: pd.DataFrame, noms_epci: dict[str, str]
) -> pd.DataFrame:
    """Remplace les codes EPCI par les noms officiels dans nom_O / nom_D."""
    df = df.copy()
    masque_emis = df["typologie"] == "echange_emis"
    masque_recus = df["typologie"] == "echange_recus"
    if masque_emis.any() and "com_D" in df.columns:
        codes = _code_epci_str(df.loc[masque_emis, "com_D"])
        df.loc[masque_emis, "nom_D"] = codes.map(noms_epci).fillna(
            df.loc[masque_emis, "nom_D"]
        )
    if masque_recus.any() and "com_O" in df.columns:
        codes = _code_epci_str(df.loc[masque_recus, "com_O"])
        df.loc[masque_recus, "nom_O"] = codes.map(noms_epci).fillna(
            df.loc[masque_recus, "nom_O"]
        )
    return df


# ---------------------------------------------------------------------------
# Point d'entree CLI
# ---------------------------------------------------------------------------

def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrice", type=Path, default=None)
    parser.add_argument("--lookup", type=Path, default=None)
    parser.add_argument("--zonage", type=Path, default=None)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument(
        "--top-n", type=int, default=TOP_N_DEFAUT,
        help=f"Nombre de flux top par SERM et par typologie (defaut {TOP_N_DEFAUT}).",
    )
    parser.add_argument(
        "--top-n-epci", type=int, default=TOP_N_EPCI_DEFAUT,
        help=(
            "Nombre de flux conserves par EPCI implique, en plus du top "
            f"global (defaut {TOP_N_EPCI_DEFAUT}). 0 desactive."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    data = args.data_dir or _data_dir()
    data.mkdir(parents=True, exist_ok=True)

    lookup = lire_lookup(args.lookup or _lookup_csv())
    lookup = assigner_code_serm_lookup(lookup)

    centroides = calculer_centroides_zones(args.zonage or _zonage_shp(), lookup)
    centroides.to_parquet(data / "centroides_zones.parquet", index=False)
    LOG.info("Ecrit %s", data / "centroides_zones.parquet")

    matrice = lire_matrice_od(args.matrice or _matrice_vl_csv())
    od = joindre_attributs(matrice, lookup)

    matrice_serm = matrice_inter_serm(od)
    matrice_serm.to_csv(data / "matrice_inter_serm.csv", index=False, sep=";")
    LOG.info("Ecrit %s", data / "matrice_inter_serm.csv")

    # Chargement des noms EPCI (shapefile national)
    noms_epci = lire_noms_epci(_epci_shp())

    echanges = echanges_epci_par_serm(od)
    echanges = enrichir_noms_epci(echanges, noms_epci, ["epci_O", "epci_D"])
    echanges.to_parquet(data / "echanges_epci_serm.parquet", index=False)
    LOG.info("Ecrit %s (%d lignes)", data / "echanges_epci_serm.parquet", len(echanges))

    top_od = top_od_par_serm(od, centroides, top_n=args.top_n)
    top_od.to_parquet(data / "top_od_vl_par_serm.parquet", index=False)
    LOG.info("Ecrit %s (%d lignes)", data / "top_od_vl_par_serm.parquet", len(top_od))

    top_com = top_od_communes_par_serm(
        od, centroides, top_n=args.top_n, top_n_epci=args.top_n_epci,
    )
    top_com = appliquer_noms_epci_top_od(top_com, noms_epci)
    top_com.to_parquet(data / "top_od_com_serm.parquet", index=False)
    LOG.info("Ecrit %s (%d lignes)", data / "top_od_com_serm.parquet", len(top_com))

    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
