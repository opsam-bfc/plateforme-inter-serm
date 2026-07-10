"""datagouv_context.py.

Page Contexte enrichi : visualisations par SERM a partir de donnees
ouvertes data.gouv.fr / SDES / INSEE.

Sources utilisees (identifiees via MCP user-datagouv) :
  1. RP 2022 — modes domicile-travail par IRIS (Geoptis / INSEE, 21 MB)
  2. VP electriques Crit'Air E par EPCI, 2019-2025 (SDES Ecolab, 1 MB)
  3. Crit'Air distribution par EPCI, 2023 (SDES, 5.5 MB)
  4. Gares SNCF (geolocalisation)
  5. Frequentation en gares (SNCF Open Data)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Metadonnees des sources
# ---------------------------------------------------------------------------

SOURCES_CONTEXTE: list[dict] = [
    {
        "cle": "rp2022_modes",
        "titre": "Modes domicile-travail par IRIS (RP 2022)",
        "organisation": "Geoptis / INSEE",
        "page_datagouv": "https://www.data.gouv.fr/datasets/mode-de-deplacement-domicile-travail-1",
        "url": (
            "https://static.data.gouv.fr/resources/"
            "mode-de-deplacement-domicile-travail-1/20260126-132631/"
            "recensement-activite-des-residents-2022-1769433927511.csv"
        ),
        "nom_cache": "rp2022_modes_dt.csv",
        "description": "Parts modales voiture/TC/velo/marche par IRIS.",
    },
    {
        "cle": "vp_elec_epci",
        "titre": "Part VP electriques (Crit'Air E) par EPCI 2019-2025",
        "organisation": "SDES / Ecolab",
        "page_datagouv": (
            "https://www.data.gouv.fr/datasets/"
            "part-de-voitures-particulieres-electriques-critair-e-dans-le-parc"
        ),
        "url": (
            "https://static.data.gouv.fr/resources/"
            "part-de-voitures-particulieres-electriques-critair-e-dans-le-parc/"
            "20260203-173701/"
            "part-de-voitures-particulieres-electriques-crit-air-e-dans-le-parc-epci.csv"
        ),
        "nom_cache": "vp_elec_epci.csv",
        "description": "Evolution part VP electriques par EPCI (2019-2025).",
    },
    {
        "cle": "critair_epci",
        "titre": "Distribution Crit'Air VP par EPCI (2023)",
        "organisation": "SDES / Tableau de bord mobilites",
        "page_datagouv": (
            "https://www.data.gouv.fr/datasets/"
            "part-de-voitures-particulieres-vp-en-circulation-par-vignette-critair"
        ),
        "url": (
            "https://static.data.gouv.fr/resources/"
            "part-de-voitures-particulieres-vp-en-circulation-par-vignette-critair/"
            "20260414-111625/part-vp-circulat-critair-epci.csv"
        ),
        "nom_cache": "critair_epci.csv",
        "description": "Repartition Crit'Air E/1/2/3/4/5 du parc VP par EPCI.",
    },
    {
        "cle": "gares_sncf",
        "titre": "Gares SNCF (geolocalisation)",
        "organisation": "SNCF",
        "page_datagouv": "https://www.data.gouv.fr/datasets/liste-des-gares",
        "url": (
            "https://ressources.data.sncf.com/api/explore/v2.1/catalog/"
            "datasets/liste-des-gares/exports/geojson"
        ),
        "nom_cache": "gares_sncf.geojson",
        "description": "Poles d'echange multimodaux du territoire.",
    },
    {
        "cle": "freq_gares",
        "titre": "Frequentation en gares (SNCF)",
        "organisation": "SNCF",
        "page_datagouv": "https://www.data.gouv.fr/datasets/frequentation-en-gares",
        "url": (
            "https://ressources.data.sncf.com/api/explore/v2.1/catalog/"
            "datasets/frequentation-gares/exports/csv?use_labels=true"
        ),
        "nom_cache": "freq_gares.csv",
        "description": "Attractivite des gares (voyageurs/an).",
    },
]

# Codes departements BFC
DEPS_BFC = {"21", "25", "39", "58", "70", "71", "89", "90"}

# Couleurs des modes de transport
COULEURS_MODES = {
    "Voiture": "#E53935",
    "TC": "#1E88E5",
    "Velo": "#43A047",
    "Marche": "#FB8C00",
    "2RM": "#8E24AA",
    "Sans transport": "#90A4AE",
}

# Ordre des vignettes Crit'Air
ORDRE_CRITAIR = [
    "Crit'Air E", "Crit'Air 1", "Crit'Air 2",
    "Crit'Air 3", "Crit'Air 4", "Crit'Air 5",
    "Non classe", "Non classee",
]
COULEURS_CRITAIR = {
    "Crit'Air E": "#1B5E20",
    "Crit'Air 1": "#66BB6A",
    "Crit'Air 2": "#FDD835",
    "Crit'Air 3": "#F57C00",
    "Crit'Air 4": "#B71C1C",
    "Crit'Air 5": "#4E342E",
    "Non classe": "#9E9E9E",
    "Non classee": "#9E9E9E",
}


# ---------------------------------------------------------------------------
# Utilitaires cache fichier
# ---------------------------------------------------------------------------

def _cache_dir() -> Path:
    from data_loader import data_dir
    cache = data_dir() / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _charger_url(url: str, nom_cache: str) -> Path:
    """Telecharge ``url`` une seule fois et met en cache local."""
    chemin = _cache_dir() / nom_cache
    if chemin.exists() and chemin.stat().st_size > 0:
        return chemin
    LOG.info("Telechargement %s ...", url)
    r = requests.get(url, timeout=180, stream=True)
    r.raise_for_status()
    with chemin.open("wb") as f:
        for chunk in r.iter_content(chunk_size=64 * 1024):
            if chunk:
                f.write(chunk)
    LOG.info("Sauvegarde -> %s (%.1f Mo)", chemin, chemin.stat().st_size / 1e6)
    return chemin


# ---------------------------------------------------------------------------
# Chargeurs de donnees (caches Streamlit)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Chargement RP 2022 - modes domicile-travail...")
def charger_rp2022_modes() -> pd.DataFrame:
    """RP 2022 modes domicile-travail par IRIS (21 Mo, filtre BFC)."""
    src = next(s for s in SOURCES_CONTEXTE if s["cle"] == "rp2022_modes")
    chemin = _charger_url(src["url"], src["nom_cache"])
    cols_modes = [
        "Commune ou ARM",
        "Département",
        "Actif occ 15 ans ou plus en 2022 (compl)",
        "Actifs occ 15 ans ou plus voiture en 2022 (compl)",
        "Actifs occ 15 ans ou plus transport en commun en 2022 (compl)",
        "Actifs occ 15 ans ou plus vélo en 2022 (compl)",
        "Actifs occ 15 ans ou plus marche à pied pour travail en 2022 (",
        "Actifs occ 15 ans ou plus deux-roues motorisé en 2022 (compl)",
        "Actifs occ 15 ans ou plus pas de transport pour travail en 2022",
    ]
    try:
        df = pd.read_csv(chemin, sep=";", encoding="utf-8", low_memory=False,
                         usecols=lambda c: any(k in c for k in
                                               ["Commune ou ARM", "Département",
                                                "voiture", "transport en commun",
                                                "vélo", "marche", "deux-roues",
                                                "pas de transport",
                                                "en 2022 (compl)"]))
    except Exception:
        df = pd.read_csv(chemin, sep=";", encoding="latin-1", low_memory=False)

    # Normaliser les noms de colonnes
    df.columns = [str(c).strip() for c in df.columns]

    # Filtrer BFC
    col_dep = next((c for c in df.columns if "Département" in c or
                    "département" in c.lower()), None)
    if col_dep:
        df[col_dep] = df[col_dep].astype(str).str.zfill(2)
        df = df[df[col_dep].isin(DEPS_BFC)].copy()

    return df


@st.cache_data(show_spinner="Chargement VP electriques par EPCI...")
def charger_vp_elec_epci() -> pd.DataFrame:
    """Part VP Crit'Air E par EPCI, series temporelles 2019-2025."""
    src = next(s for s in SOURCES_CONTEXTE if s["cle"] == "vp_elec_epci")
    chemin = _charger_url(src["url"], src["nom_cache"])
    df = pd.read_csv(chemin, sep=";", encoding="utf-8")
    df.columns = [str(c).strip() for c in df.columns]
    return df


@st.cache_data(show_spinner="Chargement distribution Crit'Air par EPCI...")
def charger_critair_epci() -> pd.DataFrame:
    """Distribution Crit'Air VP par EPCI, annee 2023."""
    src = next(s for s in SOURCES_CONTEXTE if s["cle"] == "critair_epci")
    chemin = _charger_url(src["url"], src["nom_cache"])
    for sep in [";", ","]:
        try:
            df = pd.read_csv(chemin, sep=sep, encoding="utf-8")
            if len(df.columns) > 3:
                df.columns = [str(c).strip() for c in df.columns]
                return df
        except Exception:
            continue
    return pd.DataFrame()


@st.cache_data(show_spinner="Chargement gares SNCF...")
def charger_gares_sncf() -> gpd.GeoDataFrame:
    src = next(s for s in SOURCES_CONTEXTE if s["cle"] == "gares_sncf")
    chemin = _charger_url(src["url"], src["nom_cache"])
    gdf = gpd.read_file(chemin)
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    return gdf


@st.cache_data(show_spinner="Chargement frequentation gares...")
def charger_freq_gares() -> pd.DataFrame:
    src = next(s for s in SOURCES_CONTEXTE if s["cle"] == "freq_gares")
    chemin = _charger_url(src["url"], src["nom_cache"])
    return pd.read_csv(chemin, sep=";")


# ---------------------------------------------------------------------------
# Helpers geographiques
# ---------------------------------------------------------------------------

def filtrer_gares_dans_serm(
    gares: gpd.GeoDataFrame, perimetres: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:
    if gares.empty or perimetres.empty:
        return gares.iloc[0:0]
    union = perimetres.unary_union
    sous = gares[gares.geometry.within(union)].copy()
    sous = gpd.sjoin(
        sous,
        perimetres[["code_serm", "nom_serm", "geometry"]],
        predicate="within", how="left",
    )
    return sous


def _contour_serm(fig: go.Figure, perimetres_gdf: gpd.GeoDataFrame,
                  couleurs: dict | None = None) -> None:
    from data_loader import info_serm
    for _, row in perimetres_gdf.iterrows():
        code = int(row.get("code_serm", 0))
        couleur = (couleurs or {}).get(code, "#9E9E9E")
        geoms = (
            list(row.geometry.geoms)
            if row.geometry.geom_type == "MultiPolygon"
            else [row.geometry]
        )
        for poly in geoms:
            xs, ys = poly.exterior.coords.xy
            fig.add_trace(go.Scattermapbox(
                lat=list(ys), lon=list(xs), mode="lines",
                line=dict(width=2, color=couleur),
                hoverinfo="skip", showlegend=False,
            ))


def _lookup_serm() -> tuple[dict, dict]:
    """Renvoie (com_to_serm, epci_to_serm) depuis le parquet centroides."""
    from data_loader import data_dir
    chemin = data_dir() / "centroides_zones.parquet"
    if not chemin.is_file():
        return {}, {}
    try:
        df = pd.read_parquet(chemin, columns=["COM", "EPCI", "code_serm"])
        df["COM"] = df["COM"].astype(str).str.zfill(5)
        df["EPCI"] = df["EPCI"].astype(str)
        com_to = df.dropna(subset=["COM"]).set_index("COM")["code_serm"].to_dict()
        epci_to = df.dropna(subset=["EPCI"]).set_index("EPCI")["code_serm"].to_dict()
        return com_to, epci_to
    except Exception as exc:
        LOG.warning("Lookup SERM indisponible : %s", exc)
        return {}, {}


def _noms_serm() -> dict:
    from data_loader import SERM_INFO
    return {c: SERM_INFO[c]["nom"] for c in SERM_INFO}


def _couleurs_serm() -> dict:
    from data_loader import SERM_INFO
    return {c: SERM_INFO[c]["couleur"] for c in SERM_INFO}


# ---------------------------------------------------------------------------
# Preparation des donnees
# ---------------------------------------------------------------------------

def preparer_modes_par_serm(df_rp: pd.DataFrame) -> pd.DataFrame:
    """Agrege les modes domicile-travail par SERM depuis le RP 2022.

    Colonnes de sortie : serm, nom_serm, Voiture, TC, Velo, Marche,
    2RM, Sans_transport, Total, pct_Voiture, pct_TC, pct_Velo, ...
    """
    com_to, _ = _lookup_serm()
    if not com_to:
        return pd.DataFrame()

    df = df_rp.copy()
    # Identifier colonnes modes
    def _col(kw: str) -> str | None:
        return next((c for c in df.columns if kw.lower() in c.lower()), None)

    col_com = _col("Commune ou ARM")
    col_voit = _col("voiture")
    col_tc = _col("transport en commun")
    col_velo = _col("vélo") or _col("velo")
    col_march = _col("marche")
    col_2rm = _col("deux-roues")
    col_sans = _col("pas de transport")
    col_tot = _col("en 2022 (compl)")

    if not all([col_com, col_voit, col_tc]):
        LOG.warning("Colonnes modes manquantes dans le RP 2022.")
        return pd.DataFrame()

    df[col_com] = df[col_com].astype(str).str.zfill(5)
    df["code_serm"] = df[col_com].map(com_to).fillna(0).astype(int)

    # Sommer par SERM (uniquement les 3 SERM identifies)
    for c in [col_voit, col_tc, col_velo, col_march, col_2rm, col_sans, col_tot]:
        if c:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    agg = df[df["code_serm"] > 0].groupby("code_serm").agg(
        Voiture=(col_voit, "sum"),
        TC=(col_tc, "sum"),
        Velo=(col_velo, "sum") if col_velo else ("code_serm", "count"),
        Marche=(col_march, "sum") if col_march else ("code_serm", "count"),
        _2RM=(col_2rm, "sum") if col_2rm else ("code_serm", "count"),
        Sans_transport=(col_sans, "sum") if col_sans else ("code_serm", "count"),
        Total=(col_tot, "sum") if col_tot else (col_voit, "sum"),
    ).reset_index()

    # Correction si velo/marche/2rm absent
    for col in ["Velo", "Marche", "_2RM", "Sans_transport"]:
        if col in agg.columns and (col_velo is None and col == "Velo"):
            agg[col] = 0

    noms = _noms_serm()
    agg["nom_serm"] = agg["code_serm"].map(noms)

    tot = agg["Total"].replace(0, 1)
    for mode in ["Voiture", "TC", "Velo", "Marche", "_2RM", "Sans_transport"]:
        if mode in agg.columns:
            agg[f"pct_{mode}"] = agg[mode] / tot * 100

    return agg.rename(columns={"_2RM": "2RM", "pct__2RM": "pct_2RM"})


def preparer_modes_par_commune_serm(
    df_rp: pd.DataFrame, code_serm: int
) -> pd.DataFrame:
    """Parts modales par commune pour un SERM donne."""
    com_to, _ = _lookup_serm()
    if not com_to:
        return pd.DataFrame()

    df = df_rp.copy()

    def _col(kw: str) -> str | None:
        return next((c for c in df.columns if kw.lower() in c.lower()), None)

    col_com = _col("Commune ou ARM")
    col_lib = next((c for c in df.columns if "libellé commune" in c.lower()
                    or "libelle commune" in c.lower()), col_com)
    col_voit = _col("voiture")
    col_tc = _col("transport en commun")
    col_velo = _col("vélo") or _col("velo")
    col_tot = _col("en 2022 (compl)")

    if not all([col_com, col_voit, col_tc]):
        return pd.DataFrame()

    df[col_com] = df[col_com].astype(str).str.zfill(5)
    df["code_serm"] = df[col_com].map(com_to).fillna(0).astype(int)
    df = df[df["code_serm"] == code_serm].copy()

    for c in [col_voit, col_tc, col_velo, col_tot]:
        if c:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

    # Agréger par commune (plusieurs IRIS par commune)
    cols_agg = {
        "Voiture": (col_voit, "sum"),
        "TC": (col_tc, "sum"),
    }
    if col_velo:
        cols_agg["Velo"] = (col_velo, "sum")
    if col_tot:
        cols_agg["Total"] = (col_tot, "sum")

    grp = [col_com]
    if col_lib != col_com:
        grp.append(col_lib)
    com_agg = df.groupby(grp).agg(**{k: v for k, v in cols_agg.items()}).reset_index()
    com_agg = com_agg[com_agg["Total"] > 0] if "Total" in com_agg else com_agg
    tot = com_agg.get("Total", com_agg.get("Voiture", pd.Series([1]))).replace(0, 1)
    com_agg["pct_Voiture"] = com_agg["Voiture"] / tot * 100
    com_agg["pct_TC"] = com_agg["TC"] / tot * 100
    if "Velo" in com_agg:
        com_agg["pct_Velo"] = com_agg["Velo"] / tot * 100
    com_agg = com_agg.rename(columns={col_com: "code_com",
                                       col_lib: "nom_commune"})
    return com_agg.sort_values("pct_Voiture", ascending=False)


def preparer_vp_elec_serm(df_elec: pd.DataFrame) -> pd.DataFrame:
    """Associe les EPCI au SERM et calcule la moyenne par SERM/annee."""
    _, epci_to = _lookup_serm()
    if not epci_to:
        return pd.DataFrame()

    df = df_elec.copy()
    col_epci = next((c for c in df.columns
                     if "geocode" in c.lower() or "code_epci" in c.lower()
                     or "geocode_epci" in c.lower()), None)
    col_val = next((c for c in df.columns if "valeur" in c.lower()), None)
    col_date = next((c for c in df.columns
                     if "date" in c.lower() or "annee" in c.lower()), None)

    if not all([col_epci, col_val, col_date]):
        return pd.DataFrame()

    df[col_epci] = df[col_epci].astype(str)
    df["code_serm"] = df[col_epci].map(epci_to).fillna(0).astype(int)
    df = df[df["code_serm"] > 0].copy()
    df[col_val] = pd.to_numeric(df[col_val], errors="coerce")
    # Annee
    df["annee"] = pd.to_datetime(df[col_date]).dt.year if "T" in str(
        df[col_date].iloc[0]) else pd.to_numeric(df[col_date], errors="coerce")

    noms = _noms_serm()
    df["nom_serm"] = df["code_serm"].map(noms)

    agg = df.groupby(["annee", "code_serm", "nom_serm"])[col_val].mean().reset_index()
    agg = agg.rename(columns={col_val: "pct_electrique"})
    return agg.sort_values("annee")


def preparer_critair_serm(df_critair: pd.DataFrame) -> pd.DataFrame:
    """Distribution Crit'Air par SERM (moyenne ponderee par EPCI)."""
    _, epci_to = _lookup_serm()
    if not epci_to:
        return pd.DataFrame()

    df = df_critair.copy()
    col_epci = next((c for c in df.columns
                     if "code_epci" in c.lower() or "epci" in c.lower()), None)
    col_critair = next((c for c in df.columns
                        if "vignette" in c.lower() or "critair" in c.lower()), None)
    col_val = next((c for c in df.columns if "valeur" in c.lower()), None)
    col_num = next((c for c in df.columns if "numerateur" in c.lower()), None)
    col_den = next((c for c in df.columns if "denominateur" in c.lower()), None)
    col_annee = next((c for c in df.columns if "annee" in c.lower()), None)

    if not all([col_epci, col_critair, col_num]):
        return pd.DataFrame()

    df[col_epci] = df[col_epci].astype(str)
    df["code_serm"] = df[col_epci].map(epci_to).fillna(0).astype(int)
    df = df[df["code_serm"] > 0].copy()

    # Filtrer sur la derniere annee disponible
    if col_annee:
        annee_max = pd.to_numeric(df[col_annee], errors="coerce").max()
        df = df[pd.to_numeric(df[col_annee], errors="coerce") == annee_max]

    df[col_num] = pd.to_numeric(df[col_num], errors="coerce").fillna(0)
    if col_den:
        df[col_den] = pd.to_numeric(df[col_den], errors="coerce").fillna(1)

    # Agréger : somme numerateur + denominateur par SERM x vignette
    grp = df.groupby(["code_serm", col_critair]).agg(
        numerateur_sum=(col_num, "sum"),
        denominateur_sum=(col_den, "sum") if col_den else (col_num, "sum"),
    ).reset_index()
    grp["pct"] = grp["numerateur_sum"] / grp["denominateur_sum"].replace(0, 1) * 100

    noms = _noms_serm()
    grp["nom_serm"] = grp["code_serm"].map(noms)
    grp = grp.rename(columns={col_critair: "vignette"})
    return grp


# ---------------------------------------------------------------------------
# Figures Plotly
# ---------------------------------------------------------------------------

def _fig_modes_barres_serm(agg: pd.DataFrame) -> go.Figure:
    """Barres groupees des parts modales domicile-travail par SERM."""
    modes = ["Voiture", "TC", "Velo", "Marche", "2RM"]
    fig = go.Figure()
    couleurs_serm = _couleurs_serm()
    noms = agg["nom_serm"].tolist()

    for mode in modes:
        col_pct = f"pct_{mode}"
        if col_pct not in agg.columns:
            continue
        fig.add_trace(go.Bar(
            name=mode,
            x=noms,
            y=agg[col_pct].tolist(),
            marker_color=COULEURS_MODES.get(mode, "#90A4AE"),
            text=[f"{v:.1f}%" for v in agg[col_pct]],
            textposition="outside",
        ))

    fig.update_layout(
        barmode="group",
        title="Parts modales domicile-travail par SERM (RP 2022)",
        xaxis_title="SERM",
        yaxis_title="% des actifs occupes",
        height=450,
        margin={"l": 50, "r": 20, "t": 60, "b": 40},
        legend_title="Mode",
    )
    return fig


def _fig_modes_donut_serm(agg: pd.DataFrame, code_serm: int) -> go.Figure:
    """Donut des parts modales pour un SERM."""
    row = agg[agg["code_serm"] == code_serm]
    if row.empty:
        return go.Figure()
    row = row.iloc[0]
    modes = [m for m in ["Voiture", "TC", "Velo", "Marche", "2RM", "Sans_transport"]
             if f"pct_{m}" in row.index]
    vals = [float(row.get(f"pct_{m}", 0)) for m in modes]
    couleurs = [COULEURS_MODES.get(m, "#90A4AE") for m in modes]
    nom = row.get("nom_serm", f"SERM {code_serm}")

    fig = go.Figure(go.Pie(
        labels=modes, values=vals, hole=0.5,
        marker=dict(colors=couleurs),
        textinfo="label+percent",
        hovertemplate="%{label} : %{value:.1f}%<extra></extra>",
    ))
    fig.update_layout(
        title=nom, height=320,
        margin={"l": 10, "r": 10, "t": 40, "b": 10},
        showlegend=False,
    )
    return fig


def _fig_top_communes_voit(df_com: pd.DataFrame, code_serm: int,
                            n: int = 15) -> go.Figure:
    """Top N communes avec la plus forte part voiture dans un SERM."""
    col_lib = "nom_commune" if "nom_commune" in df_com.columns else "code_com"
    top = df_com.nlargest(n, "pct_Voiture")
    flop = df_com.nsmallest(n, "pct_Voiture")

    from data_loader import info_serm
    couleur = info_serm(code_serm)["couleur"]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=top["pct_Voiture"], y=top[col_lib],
        orientation="h", name="Fort usage VP",
        marker_color=couleur, opacity=0.9,
    ))
    fig.update_layout(
        title=f"Communes a fort usage VP ({info_serm(code_serm)['nom']})",
        xaxis_title="% voiture dom-trav", yaxis=dict(autorange="reversed"),
        height=420, margin={"l": 160, "r": 20, "t": 50, "b": 40},
    )
    return fig


def _fig_faible_voit_communes(df_com: pd.DataFrame, code_serm: int,
                               n: int = 15) -> go.Figure:
    """Top N communes avec la plus faible part voiture (potentiel alternatif)."""
    col_lib = "nom_commune" if "nom_commune" in df_com.columns else "code_com"
    df_filt = df_com[df_com.get("Total", df_com["Voiture"]) > 50]  # min actifs
    flop = df_filt.nsmallest(n, "pct_Voiture")

    from data_loader import info_serm
    fig = go.Figure(go.Bar(
        x=flop["pct_Voiture"], y=flop[col_lib],
        orientation="h",
        marker_color="#43A047",
        text=[f"{v:.1f}%" for v in flop["pct_Voiture"]],
        textposition="outside",
    ))
    fig.update_layout(
        title=(
            f"Communes a faible usage VP — potentiel alternatif "
            f"({info_serm(code_serm)['nom']})"
        ),
        xaxis_title="% voiture dom-trav",
        yaxis=dict(autorange="reversed"),
        height=420, margin={"l": 160, "r": 20, "t": 60, "b": 40},
    )
    return fig


def _fig_vp_elec_evolution(agg_elec: pd.DataFrame) -> go.Figure:
    """Courbe d'evolution part VP electriques par SERM."""
    couleurs_serm = _couleurs_serm()
    fig = go.Figure()
    for code in agg_elec["code_serm"].unique():
        sous = agg_elec[agg_elec["code_serm"] == code]
        nom = sous["nom_serm"].iloc[0]
        fig.add_trace(go.Scatter(
            x=sous["annee"], y=sous["pct_electrique"],
            mode="lines+markers",
            name=nom,
            line=dict(color=couleurs_serm.get(code, "#9E9E9E"), width=2.5),
            marker=dict(size=7),
            hovertemplate=f"<b>{nom}</b><br>%{{x}} : %{{y:.2f}} %<extra></extra>",
        ))
    fig.update_layout(
        title="Evolution de la part des VP electriques (Crit'Air E) par SERM",
        xaxis_title="Annee", yaxis_title="% VP electriques dans le parc",
        height=420, margin={"l": 60, "r": 20, "t": 60, "b": 40},
        legend_title="SERM",
    )
    return fig


def _fig_critair_par_serm(agg_critair: pd.DataFrame) -> go.Figure:
    """Barres empilees Crit'Air par SERM."""
    pivot = agg_critair.pivot_table(
        index="nom_serm", columns="vignette", values="pct", aggfunc="sum"
    ).fillna(0)

    # Reordonner colonnes selon l'ordre defini
    cols_ord = [c for c in ORDRE_CRITAIR if c in pivot.columns]
    cols_rest = [c for c in pivot.columns if c not in cols_ord]
    pivot = pivot[cols_ord + cols_rest]

    fig = go.Figure()
    for vignette in pivot.columns:
        fig.add_trace(go.Bar(
            name=vignette,
            x=pivot.index.tolist(),
            y=pivot[vignette].tolist(),
            marker_color=COULEURS_CRITAIR.get(vignette, "#BDBDBD"),
            text=[f"{v:.1f}%" for v in pivot[vignette]],
            textposition="auto",
        ))
    fig.update_layout(
        barmode="stack",
        title="Distribution du parc VP par vignette Crit'Air et SERM (2023)",
        xaxis_title="SERM", yaxis_title="% du parc VP",
        height=450, margin={"l": 50, "r": 20, "t": 60, "b": 40},
        legend_title="Vignette Crit'Air",
    )
    return fig


# ---------------------------------------------------------------------------
# Panneau Streamlit principal
# ---------------------------------------------------------------------------

def afficher_panneau_contexte(perimetres_gdf: gpd.GeoDataFrame) -> None:
    """Affiche la page Contexte enrichi dans Streamlit."""

    bounds = perimetres_gdf.total_bounds
    centre_carte = {
        "lat": float((bounds[1] + bounds[3]) / 2),
        "lon": float((bounds[0] + bounds[2]) / 2),
    }

    with st.expander("Sources data.gouv.fr utilisees", expanded=False):
        df_src = pd.DataFrame([
            {"Source": s["titre"], "Organisation": s["organisation"],
             "Page data.gouv": s["page_datagouv"]}
            for s in SOURCES_CONTEXTE
        ])
        st.dataframe(df_src, use_container_width=True, hide_index=True,
                     column_config={"Page data.gouv": st.column_config.LinkColumn()})

    # =========================================================================
    # Section 1 : Modes domicile-travail (RP 2022)
    # =========================================================================

    st.subheader("1. Modes de transport domicile-travail (RP 2022)")
    st.caption(
        "Source : Recensement de la Population 2022, fichier activite des "
        "residents par IRIS (Geoptis / INSEE). Chaque actif occupe est "
        "comptabilise selon son mode de transport principal utilise pour "
        "aller travailler. Les communes sont affiliees aux SERM via le "
        "lookup OPSAM."
    )

    if not st.checkbox("Charger les donnees RP 2022 (21 Mo)", value=False,
                       key="cb_rp2022"):
        st.info("Activer pour telecharger et calculer les parts modales par SERM.")
    else:
        try:
            df_rp = charger_rp2022_modes()
        except Exception as exc:
            st.error(f"Erreur chargement RP 2022 : {exc}")
            df_rp = pd.DataFrame()

        if df_rp.empty:
            st.warning("Aucune donnee RP 2022 disponible.")
        else:
            st.caption(f"{len(df_rp):,} IRIS BFC charges.".replace(",", "\u202f"))
            agg_modes = preparer_modes_par_serm(df_rp)

            if agg_modes.empty:
                st.warning(
                    "Impossible d'associer les communes aux SERM. "
                    "Verifier que le bundle `data/` est regenere."
                )
            else:
                # -- Graphique barres comparatives par SERM ----------------
                st.plotly_chart(
                    _fig_modes_barres_serm(agg_modes),
                    use_container_width=True,
                )

                # -- Donuts par SERM ----------------------------------------
                st.markdown("**Part modale detaillee par SERM**")
                cols_donuts = st.columns(3)
                for i, code in enumerate([1, 2, 3]):
                    with cols_donuts[i]:
                        st.plotly_chart(
                            _fig_modes_donut_serm(agg_modes, code),
                            use_container_width=True,
                        )

                # -- KPIs ----------------------------------------------------
                st.markdown("**Indicateurs cles**")
                k_cols = st.columns(len(agg_modes))
                for i, (_, row) in enumerate(agg_modes.iterrows()):
                    with k_cols[i]:
                        pct_voit = row.get("pct_Voiture", 0)
                        pct_tc = row.get("pct_TC", 0)
                        pct_velo = row.get("pct_Velo", 0)
                        st.metric(row["nom_serm"],
                                  f"{pct_voit:.1f}% voiture",
                                  f"TC: {pct_tc:.1f}%  Velo: {pct_velo:.1f}%")

                # -- Tableau numerique ---------------------------------------
                with st.expander("Tableau numerique complet"):
                    cols_show = [c for c in agg_modes.columns
                                 if c.startswith("pct_") or c in ("nom_serm",)]
                    st.dataframe(
                        agg_modes[cols_show].rename(columns={"nom_serm": "SERM"}),
                        use_container_width=True, hide_index=True,
                        column_config={
                            c: st.column_config.NumberColumn(format="%.1f %%")
                            for c in cols_show if c != "nom_serm"
                        },
                    )

                # -- Analyse par commune (zoom SERM) -------------------------
                st.markdown("**Zoom par SERM — analyse communale**")
                from data_loader import SERM_INFO
                code_sel = st.selectbox(
                    "SERM a analyser",
                    [1, 2, 3],
                    format_func=lambda c: SERM_INFO[c]["nom"],
                    key="serm_modes_com",
                )
                df_com = preparer_modes_par_commune_serm(df_rp, code_sel)
                if df_com.empty:
                    st.info("Analyse communale indisponible.")
                else:
                    st.caption(
                        f"{len(df_com)} communes dans le SERM selectionne "
                        "(actives occupees > 0)."
                    )
                    col_h, col_l = st.columns(2)
                    with col_h:
                        st.plotly_chart(
                            _fig_top_communes_voit(df_com, code_sel, n=15),
                            use_container_width=True,
                        )
                    with col_l:
                        st.plotly_chart(
                            _fig_faible_voit_communes(df_com, code_sel, n=15),
                            use_container_width=True,
                        )

    # =========================================================================
    # Section 2 : Electrification du parc VP
    # =========================================================================

    st.divider()
    st.subheader("2. Electrification du parc VP par SERM")
    st.caption(
        "Source : SDES / Ecolab — Part des VP Crit'Air E au 1er janvier "
        "(2019-2025) par EPCI. Les EPCI sont affectes aux SERM via le "
        "lookup OPSAM."
    )

    if not st.checkbox("Charger les donnees VP electriques (1 Mo)", value=False,
                       key="cb_elec"):
        st.info("Activer pour telecharger et afficher l'evolution de l'electrification.")
    else:
        try:
            df_elec = charger_vp_elec_epci()
        except Exception as exc:
            st.error(f"Erreur : {exc}")
            df_elec = pd.DataFrame()

        if df_elec.empty:
            st.warning("Donnees VP electriques indisponibles.")
        else:
            agg_elec = preparer_vp_elec_serm(df_elec)
            if agg_elec.empty:
                st.warning(
                    "Impossible d'associer les EPCI aux SERM. "
                    "Verifier le bundle."
                )
            else:
                st.plotly_chart(
                    _fig_vp_elec_evolution(agg_elec),
                    use_container_width=True,
                )
                # KPIs derniere annee
                annee_max = int(agg_elec["annee"].max())
                derniere = agg_elec[agg_elec["annee"] == annee_max]
                st.markdown(f"**Part VP electriques au 1er janvier {annee_max}**")
                k_cols = st.columns(len(derniere))
                for i, (_, row) in enumerate(derniere.iterrows()):
                    with k_cols[i]:
                        st.metric(
                            row["nom_serm"],
                            f"{row['pct_electrique']:.2f} %",
                        )
                with st.expander("Donnees brutes"):
                    st.dataframe(agg_elec, use_container_width=True, hide_index=True)

    # =========================================================================
    # Section 3 : Distribution Crit'Air
    # =========================================================================

    st.divider()
    st.subheader("3. Distribution Crit'Air du parc VP par SERM")
    st.caption(
        "Source : SDES / Tableau de bord des mobilites durables — "
        "Part du parc VP par vignette Crit'Air (E, 1 a 5, Non classe). "
        "Donnees 2023 par EPCI, agreges par SERM."
    )

    if not st.checkbox("Charger les donnees Crit'Air par EPCI (5.5 Mo)", value=False,
                       key="cb_critair"):
        st.info("Activer pour afficher la distribution Crit'Air du parc VP.")
    else:
        try:
            df_critair = charger_critair_epci()
        except Exception as exc:
            st.error(f"Erreur : {exc}")
            df_critair = pd.DataFrame()

        if df_critair.empty:
            st.warning("Donnees Crit'Air indisponibles.")
        else:
            agg_critair = preparer_critair_serm(df_critair)
            if agg_critair.empty:
                st.warning("Association EPCI-SERM impossible.")
            else:
                st.plotly_chart(
                    _fig_critair_par_serm(agg_critair),
                    use_container_width=True,
                )
                # Focus sur Crit'Air E
                elec = agg_critair[agg_critair["vignette"].str.contains("E|electr",
                                                                          case=False,
                                                                          na=False)]
                if not elec.empty:
                    st.markdown("**Part Crit'Air E par SERM (2023)**")
                    k_cols = st.columns(len(elec))
                    for i, (_, row) in enumerate(elec.iterrows()):
                        with k_cols[i]:
                            st.metric(row["nom_serm"], f"{row['pct']:.2f} %")

                with st.expander("Donnees brutes"):
                    st.dataframe(agg_critair, use_container_width=True,
                                 hide_index=True)

    # =========================================================================
    # Section 4 : Gares SNCF
    # =========================================================================

    st.divider()
    st.subheader("4. Infrastructures ferroviaires dans les SERM")

    if not st.checkbox("Charger les gares SNCF", value=False, key="cb_gares"):
        st.info("Activer pour afficher les gares SNCF sur la carte.")
    else:
        try:
            gares = charger_gares_sncf()
        except Exception as exc:
            st.error(f"Erreur : {exc}")
            gares = gpd.GeoDataFrame()

        if not gares.empty:
            gares_serm = filtrer_gares_dans_serm(gares, perimetres_gdf)
            c1, c2 = st.columns(2)
            c1.metric("Gares totales (France)",
                      f"{len(gares):,}".replace(",", "\u202f"))
            c2.metric("Gares dans les 3 SERM",
                      f"{len(gares_serm):,}".replace(",", "\u202f"))

            couleurs_serm = _couleurs_serm()
            fig_g = go.Figure()
            _contour_serm(fig_g, perimetres_gdf, couleurs_serm)

            from data_loader import info_serm as _info_serm
            for code in [1, 2, 3]:
                sub = gares_serm[gares_serm.get(
                    "code_serm", pd.Series(dtype=int)
                ) == code]
                if sub.empty:
                    continue
                fig_g.add_trace(go.Scattermapbox(
                    lat=sub.geometry.y, lon=sub.geometry.x, mode="markers",
                    marker=dict(size=10, color=_info_serm(code)["couleur"]),
                    hovertext=sub.get("libelle", sub.index.astype(str)),
                    name=_info_serm(code)["nom_court"],
                ))
            fig_g.update_layout(
                mapbox_style="open-street-map",
                mapbox_center=centre_carte, mapbox_zoom=7.0,
                margin={"r": 5, "t": 5, "l": 5, "b": 5}, height=500,
                legend=dict(orientation="h", yanchor="bottom",
                            y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig_g, use_container_width=True)

            if st.checkbox("Voir la frequentation des gares", value=False,
                           key="cb_freq"):
                try:
                    freq = charger_freq_gares()
                    col_annee = next(
                        (c for c in freq.columns
                         if any(yr in str(c) for yr in ["2022", "2023", "2021"])),
                        freq.columns[-1],
                    )
                    col_gare = next(
                        (c for c in freq.columns
                         if any(k in str(c).lower()
                                for k in ["gare", "nom", "libelle"])),
                        freq.columns[0],
                    )
                    freq[col_annee] = pd.to_numeric(freq[col_annee], errors="coerce")
                    top_freq = freq[[col_gare, col_annee]].dropna().nlargest(20, col_annee)
                    fig_f = px.bar(
                        top_freq, x=col_gare, y=col_annee,
                        title=f"Top 20 gares par frequentation ({col_annee})",
                        labels={col_gare: "Gare", col_annee: "Voyageurs/an"},
                        color=col_annee, color_continuous_scale="Blues",
                    )
                    fig_f.update_layout(height=420, xaxis_tickangle=-35,
                                        showlegend=False)
                    st.plotly_chart(fig_f, use_container_width=True)
                except Exception as exc:
                    st.error(f"Frequentation : {exc}")

    # =========================================================================
    # Section 5 : Tableau de synthese des sources complementaires
    # =========================================================================

    st.divider()
    st.subheader("5. Donnees complementaires recommandees")
    st.markdown("""
| Jeu de donnees | Source | Granularite | Pertinence SERM |
|---|---|---|---|
| **Parc VP communal** (2011-2022) | SDES | Commune | Taux de motorisation |
| **EMP 2019** (enquete menages) | SDES | Individu/Menage | Budget temps, modes, distances |
| **GTFS Reseau BFC** | Mobigo / ATMO | Arret / Ligne | Couverture TC vs usage VP |
| **ZFE reglementations** | ADEME | Commune | Contraintes parc VP futur |
| **Accidentologie ONISR** | Min. Interieur | Accident | Securite modes actifs |
| **DVF (transactions)** | DGFIP | Commune | Dynamiques residentielles |

> Pour integrer une nouvelle source : ajouter une entree dans `SOURCES_CONTEXTE`
> (`datagouv_context.py`) et une fonction de chargement dediee.
    """)
