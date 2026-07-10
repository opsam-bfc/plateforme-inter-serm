"""data_loader.py.

Chargement du bundle de donnees precalcule (dossier ``data/``) pour
l'application Streamlit ``plateforme_analyse_inter_SERM``.

Pour absorber des evolutions de perimetres SERM, les precalculs sont
regeneres hors application (``scripts/rebuild_for_new_perimeter.py``)
et la signature du bundle (timestamps des fichiers) est utilisee pour
invalider les caches Streamlit lorsque les fichiers changent.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

import geopandas as gpd
import pandas as pd

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes — chargees depuis config/territoire.yaml
# ---------------------------------------------------------------------------

# SERM_INFO et ORDRE_SERM sont derives de la configuration du territoire.
# Ne pas les editer ici : modifier config/territoire.yaml a la place.
try:
    from config.territoire_loader import ordre_zones, serm_info as _serm_info_fn
    SERM_INFO: dict[int, dict] = _serm_info_fn()
    ORDRE_SERM: list[int] = ordre_zones()
except Exception as _cfg_err:
    # Fallback BFC pour compatibilite (si config absente en dev).
    LOG.warning(
        "config/territoire.yaml inaccessible (%s) — fallback BFC.", _cfg_err
    )
    SERM_INFO = {
        1: {"code": 1, "nom": "SERM Dijonnais", "nom_court": "Dijon",
            "slug": "dijon", "couleur": "#C62828"},
        2: {"code": 2, "nom": "SERM Nord Franche-Comte", "nom_court": "NFC",
            "slug": "nfc", "couleur": "#2E7D32"},
        3: {"code": 3, "nom": "SERM Bisontain", "nom_court": "Besancon",
            "slug": "besancon", "couleur": "#1565C0"},
        0: {"code": 0, "nom": "Reste BFC (hors SERM)", "nom_court": "Reste BFC",
            "slug": "reste_bfc", "couleur": "#90A4AE"},
    }
    ORDRE_SERM = [1, 2, 3, 0]

CLASSES_DISTANCE = {
    "D1": "< 100 km",
    "D2": "100-200 km",
    "D3": "200-400 km",
    "D4": "400-1 000 km",
    "D5": "> 1 000 km",
}

FLUX_LABELS = {
    "E": "Echange",
    "T": "Transit",
    "I": "Interne",
}

TYPES_VOIE_LABELS = {
    "NoData": "Voies locales",
    "Departementale": "Voies departementales",
    "Nationale": "Voies nationales",
    "Autoroute": "Autoroutes",
}


# ---------------------------------------------------------------------------
# Chemins (resolution avec fallback variables d'environnement)
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent


def data_dir() -> Path:
    """Retourne le dossier ``data/`` actif."""
    v = os.environ.get("SERM_DATA_DIR")
    if v:
        return Path(v)
    return _ROOT / "data"


def fichier_data(nom: str) -> Path:
    return data_dir() / nom


def signature_bundle() -> float:
    """Somme des mtime des fichiers du bundle (pour invalider les caches)."""
    total = 0.0
    for p in data_dir().rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_mtime
            except OSError:
                pass
    return total


# ---------------------------------------------------------------------------
# Chargements typés
# ---------------------------------------------------------------------------

def charger_synthese_serm() -> pd.DataFrame:
    """Charge ``synthese_serm_vl_pl.csv`` avec colonnes VL/PL deduites."""
    chemin = fichier_data("synthese_serm_vl_pl.csv")
    if not chemin.is_file():
        raise FileNotFoundError(
            f"Fichier introuvable : {chemin}. "
            "Lancer scripts/prepare_synthese_serm.py."
        )
    df = pd.read_csv(chemin, sep=";", decimal=".")
    df.columns = [str(c).strip() for c in df.columns]
    if "code_serm" in df.columns:
        df["code_serm"] = pd.to_numeric(df["code_serm"], errors="coerce").astype("Int64")
    return df


def charger_perimetres_serm() -> gpd.GeoDataFrame:
    """Charge ``perimetres_serm.geojson`` (3 multipolygones)."""
    chemin = fichier_data("perimetres_serm.geojson")
    if not chemin.is_file():
        raise FileNotFoundError(
            f"Fichier introuvable : {chemin}. "
            "Lancer scripts/prepare_perimetres_serm.py."
        )
    gdf = gpd.read_file(chemin)
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    return gdf


def charger_zones_serm() -> gpd.GeoDataFrame:
    """Charge ``zones_serm.geojson`` (zones OPSAM SERM uniquement)."""
    chemin = fichier_data("zones_serm.geojson")
    if not chemin.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}.")
    gdf = gpd.read_file(chemin)
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    return gdf


def charger_reseau_serm(slug: str) -> gpd.GeoDataFrame:
    """Charge le reseau routier pour le SERM ``slug``.

    Priorite : GeoParquet (version allégée deployable) puis GPKG (complet).
    Le GeoParquet est produit par ``scripts/optimize_for_deployment.py``.
    """
    for extension in ("parquet", "gpkg"):
        chemin = fichier_data(f"reseau_serm/{slug}.{extension}")
        if chemin.is_file():
            LOG.debug("Chargement reseau %s depuis %s", slug, chemin.name)
            if extension == "parquet":
                gdf = gpd.read_parquet(chemin)
            else:
                gdf = gpd.read_file(chemin)
            if gdf.crs is None or gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(4326)
            return gdf
    raise FileNotFoundError(
        f"Reseau introuvable pour le SERM '{slug}' "
        f"(cherche reseau_serm/{slug}.parquet puis .gpkg). "
        "Lancer scripts/prepare_reseau_serm.py ou "
        "scripts/optimize_for_deployment.py."
    )


def charger_matrice_inter_serm() -> pd.DataFrame:
    """Charge la matrice OD agregee SERM x SERM."""
    chemin = fichier_data("matrice_inter_serm.csv")
    if not chemin.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}.")
    return pd.read_csv(chemin, sep=";")


def charger_echanges_epci() -> pd.DataFrame:
    """Charge les agregats par EPCI (interne_serm + echange_serm)."""
    chemin = fichier_data("echanges_epci_serm.parquet")
    if not chemin.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}.")
    return pd.read_parquet(chemin)


def charger_top_od_vl() -> pd.DataFrame:
    """Charge le top N flux OD VL par SERM (granularite zone OPSAM)."""
    chemin = fichier_data("top_od_vl_par_serm.parquet")
    if not chemin.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}.")
    return pd.read_parquet(chemin)


def _code_epci_str(serie: pd.Series) -> pd.Series:
    """Normalise les codes EPCI (entiers, flottants, chaines)."""
    return (
        serie.astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.strip()
    )


@lru_cache(maxsize=1)
def mapping_noms_epci() -> dict[str, str]:
    """Dictionnaire {code SIREN EPCI -> nom officiel}."""
    gdf = charger_limites_epci()
    if gdf is not None and not gdf.empty:
        return dict(
            zip(
                _code_epci_str(gdf["CODE_SIREN"]),
                gdf["NOM"].astype(str),
            )
        )
    chemin = Path(
        r"\\nas-bfc\COMMUN\21_MOBILITE\21.2_COMMUN\DATA\EPCI\EPCI_2025.shp"
    )
    if chemin.is_file():
        gdf_nat = gpd.read_file(chemin, columns=["CODE_SIREN", "NOM"])
        return dict(
            zip(
                _code_epci_str(gdf_nat["CODE_SIREN"]),
                gdf_nat["NOM"].astype(str),
            )
        )
    return {}


def enrichir_noms_epci_flux_od(df: pd.DataFrame) -> pd.DataFrame:
    """Remplace les codes EPCI par les noms dans ``nom_O`` / ``nom_D``.

    S'applique aux typologies ``echange_emis`` (destination EPCI) et
    ``echange_recus`` (origine EPCI).
    """
    noms = mapping_noms_epci()
    if not noms:
        return df

    df = df.copy()
    m_emis = df["typologie"] == "echange_emis"
    m_recus = df["typologie"] == "echange_recus"

    if m_emis.any() and "com_D" in df.columns:
        codes = _code_epci_str(df.loc[m_emis, "com_D"])
        df.loc[m_emis, "nom_D"] = codes.map(noms).fillna(
            df.loc[m_emis, "nom_D"]
        )

    if m_recus.any() and "com_O" in df.columns:
        codes = _code_epci_str(df.loc[m_recus, "com_O"])
        df.loc[m_recus, "nom_O"] = codes.map(noms).fillna(
            df.loc[m_recus, "nom_O"]
        )

    return df


def charger_top_od_communes() -> pd.DataFrame:
    """Charge les flux OD agreges a la commune (interne) / EPCI (echange)."""
    chemin = fichier_data("top_od_com_serm.parquet")
    if not chemin.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}.")
    df = pd.read_parquet(chemin)
    return enrichir_noms_epci_flux_od(df)


def charger_centroides_zones() -> pd.DataFrame:
    """Charge les centroides des zones OPSAM (lon/lat WGS84)."""
    chemin = fichier_data("centroides_zones.parquet")
    if not chemin.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}.")
    return pd.read_parquet(chemin)


def charger_communes_serm(code_serm: int) -> gpd.GeoDataFrame | None:
    """Charge les limites communales pour un SERM (WGS84).

    Retourne ``None`` si le fichier n'a pas encore été généré par
    ``scripts/prepare_limites.py``.
    Colonnes : INSEE_COM, NOM_COM, EPCI, code_serm, geometry.
    """
    chemin = fichier_data(f"limites_communes_serm{code_serm}.geojson")
    if not chemin.is_file():
        LOG.debug("Limites communes SERM %d absentes : %s", code_serm, chemin)
        return None
    gdf = gpd.read_file(chemin)
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    return gdf


def charger_limites_epci() -> gpd.GeoDataFrame | None:
    """Charge les limites EPCI (WGS84) filtrées au lookup SERM.

    Retourne ``None`` si le fichier n'a pas encore été généré.
    Colonnes : CODE_SIREN, NOM, code_serm, geometry.
    """
    chemin = fichier_data("limites_epci.geojson")
    if not chemin.is_file():
        LOG.debug("Limites EPCI absentes : %s", chemin)
        return None
    gdf = gpd.read_file(chemin)
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    return gdf


# ---------------------------------------------------------------------------
# Aides au calcul (utilises par visualizations.py / app.py)
# ---------------------------------------------------------------------------

def colonne_vl(colonne_totale: str) -> str:
    """Retourne le nom de la colonne VL deduite (ex. 'VKM_E' -> 'VKM_VL_E')."""
    if colonne_totale.startswith("VKM"):
        suffixe = colonne_totale[len("VKM"):]
        return "VKM_VL" + suffixe
    return colonne_totale


def colonne_pl(colonne_totale: str) -> str:
    """Retourne le nom de la colonne PL agregee (charges + vides)."""
    if colonne_totale.startswith("VKM"):
        suffixe = colonne_totale[len("VKM"):]
        return "VKM_PL" + suffixe
    return colonne_totale


def calculer_metriques_serm(df: pd.DataFrame) -> pd.DataFrame:
    """Agrege la synthese SERM x CL_ADMIN en KPI par SERM.

    Renvoie un DataFrame indexe par code_serm avec les colonnes :
      * VKM_TV_milliers, VKM_VL_milliers, VKM_PL_milliers ;
      * pct_pl (% PL dans les VKM totaux) ;
      * pct_transit, pct_echange, pct_interne (sur tous vehicules) ;
      * pct_transit_vl, pct_echange_vl, pct_interne_vl (sur VL) ;
      * pct_longue_distance (D3-D5 vs tous, tous vehicules) ;
      * DISTANCE (km de reseau cumules).
    """
    agg_cols = [
        "VKM", "VKM_PL", "VKM_VL", "DISTANCE",
        "VKM_E", "VKM_T", "VKM_I",
        "VKM_VL_E", "VKM_VL_T", "VKM_VL_I",
        "VKM_PL_E", "VKM_PL_T", "VKM_PL_I",
    ]
    for f in ("E", "T", "I"):
        for d in ("D3", "D4", "D5"):
            agg_cols.append(f"VKM_{f}_{d}")
            agg_cols.append(f"VKM_VL_{f}_{d}")
    agg_cols = [c for c in agg_cols if c in df.columns]

    agreg = (
        df.groupby(["code_serm", "nom_serm", "slug_serm"], dropna=False)[agg_cols]
        .sum()
        .reset_index()
    )

    agreg["VKM_TV_milliers"] = agreg["VKM"] / 1000.0
    agreg["VKM_VL_milliers"] = agreg["VKM_VL"] / 1000.0
    agreg["VKM_PL_milliers"] = agreg["VKM_PL"] / 1000.0
    agreg["pct_pl"] = (agreg["VKM_PL"] / agreg["VKM"].replace(0, pd.NA) * 100).fillna(0)

    for f, libelle in (("E", "echange"), ("T", "transit"), ("I", "interne")):
        agreg[f"pct_{libelle}"] = (
            agreg[f"VKM_{f}"] / agreg["VKM"].replace(0, pd.NA) * 100
        ).fillna(0)
        agreg[f"pct_{libelle}_vl"] = (
            agreg[f"VKM_VL_{f}"] / agreg["VKM_VL"].replace(0, pd.NA) * 100
        ).fillna(0)

    longue_dist_total = sum(
        agreg.get(f"VKM_{f}_{d}", 0) for f in ("E", "T", "I") for d in ("D3", "D4", "D5")
    )
    agreg["pct_longue_distance"] = (
        longue_dist_total / agreg["VKM"].replace(0, pd.NA) * 100
    ).fillna(0)

    longue_dist_vl = sum(
        agreg.get(f"VKM_VL_{f}_{d}", 0) for f in ("E", "T", "I") for d in ("D3", "D4", "D5")
    )
    agreg["pct_longue_distance_vl"] = (
        longue_dist_vl / agreg["VKM_VL"].replace(0, pd.NA) * 100
    ).fillna(0)

    return agreg


def repartition_par_voie(df: pd.DataFrame, code_serm: int) -> pd.DataFrame:
    """Sous-table SERM x CL_ADMIN pour les graphiques par type d'infrastructure."""
    sous = df[df["code_serm"] == code_serm].copy()
    if "CL_ADMIN" in sous.columns:
        sous["TYPE_VOIE"] = sous["CL_ADMIN"].map(TYPES_VOIE_LABELS).fillna(sous["CL_ADMIN"])
    return sous


def profil_distance_vl_pl(df_serm: pd.DataFrame) -> pd.DataFrame:
    """Pour un sous-ensemble de la synthese (un SERM), retourne le profil VL/PL
    par classe de distance D1..D5 et par flux E/T/I.
    """
    lignes: list[dict] = []
    for f, libelle in FLUX_LABELS.items():
        for cle, label_dist in CLASSES_DISTANCE.items():
            col_vl = f"VKM_VL_{f}_{cle}"
            col_pl = f"VKM_PL_{f}_{cle}"
            if col_vl in df_serm.columns and col_pl in df_serm.columns:
                lignes.append(
                    {
                        "flux": libelle,
                        "classe_distance": cle,
                        "classe_distance_label": label_dist,
                        "VKM_VL": float(df_serm[col_vl].sum()),
                        "VKM_PL": float(df_serm[col_pl].sum()),
                    }
                )
    return pd.DataFrame(lignes)


def repartition_vl_pl_par_flux(df_serm: pd.DataFrame) -> pd.DataFrame:
    """Donut VL vs PL par flux E/T/I pour un SERM."""
    lignes: list[dict] = []
    for f, libelle in FLUX_LABELS.items():
        col_vl = f"VKM_VL_{f}"
        col_pl = f"VKM_PL_{f}"
        if col_vl in df_serm.columns and col_pl in df_serm.columns:
            lignes.append(
                {
                    "flux": libelle,
                    "VKM_VL": float(df_serm[col_vl].sum()),
                    "VKM_PL": float(df_serm[col_pl].sum()),
                }
            )
    return pd.DataFrame(lignes)


def info_serm(code: int) -> dict:
    """Retourne les metadonnees d'un SERM (nom, slug, couleur)."""
    return SERM_INFO.get(code, SERM_INFO[0])


@lru_cache(maxsize=8)
def _mtime(chemin: str) -> float:
    p = Path(chemin)
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0
