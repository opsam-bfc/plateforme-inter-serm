"""prepare_reseau_serm.py.

Decoupe le reseau routier OPSAM en sous-reseaux par SERM, par intersection
spatiale avec les polygones SERM dissous.

Source privilegiee (deja enrichie des volumes d'affectation) ::

    4_OUTPUT/DATA/reseau_affecte_ref2024_serm/
        reseau_final_Ref2024_serm_true_shape.shp

Champs utilises :
  - ``TMJA_P`` : TMJA total tous vehicules (consolide)
  - ``PL_P``   : volume PL absolu (vehicules/jour)
  - ``VL_jour`` = ``TMJA_P`` - ``PL_P`` (calcule a la volee)
  - ``VOLUME`` : volume modelise tous vehicules
  - ``VOL_M1_I/E/T``, ``VOL_M2_I/E/T`` : volumes affectes par referentiel

Si ``VOLUME`` / ``VOL_Mn_*`` sont absents du shapefile, jointure optionnelle
depuis ``Link_evolue_*.csv`` via ``A_SIMPLE``/``B_SIMPLE`` ↔ ``A``/``B``.

Recalage sur le TMJA consolide (par composante X in {I, E, T}) ::

    TMJA_X = TMJA_P * VOL_Mn_X / VOLUME
    PART_X = VOL_Mn_X / VOLUME

``n`` vaut 1 (Dijon, NFC) ou 2 (Besancon) selon ``territoire.yaml``.

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
import pandas as pd

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

# Reseau SERM deja affecte (true shape) — source par defaut.
_RESEAU_SERM_DEFAUT = (
    r"\\nas-bfc\COMMUN\21_MOBILITE\21.4_PROJETS\DREAL\2026_SERM"
    r"\4_OUTPUT\DATA\reseau_affecte_ref2024_serm"
    r"\reseau_final_Ref2024_serm_true_shape.shp"
)

# Attributs du shapefile conserves dans le bundle.
ATTRIBUTS_CONSERVES = [
    "ID",
    "NATURE",
    "CL_ADMIN",
    "NUMERO",
    "DISTANCE",
    "NB_VOIES",
    "TMJA_P",
    "PL_P",
    "VOLUME",
    "VOL_M1_I",
    "VOL_M1_E",
    "VOL_M1_T",
    "VOL_M2_I",
    "VOL_M2_E",
    "VOL_M2_T",
    "A_SIMPLE",
    "B_SIMPLE",
    "A",
    "B",
    "INSEECOM_G",
    "INSEECOM_D",
]

# Colonnes volume lues depuis Link_evolue (jointure A/B, fallback).
COLONNES_VOLUME_LINK = [
    "A",
    "B",
    "VOLUME",
    "VOL_M1_I",
    "VOL_M1_E",
    "VOL_M1_T",
    "VOL_M2_I",
    "VOL_M2_E",
    "VOL_M2_T",
]

COLONNES_VOLUME_REQUISES = [
    "VOLUME",
    "VOL_M1_I",
    "VOL_M1_E",
    "VOL_M1_T",
    "VOL_M2_I",
    "VOL_M2_E",
    "VOL_M2_T",
]

FLUX_IET = ("I", "E", "T")

# Fallback si config/territoire.yaml inaccessible.
_SOURCE_MACROZONE_FALLBACK = {
    "dijon": "M1",
    "nfc": "M1",
    "besancon": "M2",
}


# ---------------------------------------------------------------------------
# Helpers chemins
# ---------------------------------------------------------------------------

def _scenario_opsam() -> str:
    """Identifiant scénario (env ``SERM_SCENARIO``, défaut Ref2024)."""
    return (os.environ.get("SERM_SCENARIO") or "Ref2024").strip()


def _reseau_shp() -> Path:
    """Retourne le shapefile reseau a utiliser.

    Priorite :
    1. ``SERM_RESEAU_SHP``
    2. ``chemins.reseau_shp`` dans ``territoire.yaml``
    3. reseau SERM true_shape (4_OUTPUT)
    4. fallback Base OPSAM ``reseau_detaille_linkshape_*.shp``
    """
    v = os.environ.get("SERM_RESEAU_SHP")
    if v:
        return Path(v)
    try:
        racine = Path(__file__).resolve().parents[1]
        if str(racine) not in sys.path:
            sys.path.insert(0, str(racine))
        from config.territoire_loader import charger_config

        raw_chemin = getattr(charger_config().chemins, "reseau_shp", "") or ""
        if raw_chemin and Path(raw_chemin).is_file():
            return Path(raw_chemin)
    except Exception as exc:
        LOG.debug("reseau_shp config indisponible : %s", exc)
    candidat = Path(_RESEAU_SERM_DEFAUT)
    if candidat.is_file():
        return candidat
    scenario = _scenario_opsam()
    base_dir = (
        os.environ.get("SERM_OPSAM_BASE_DIR")
        or rf"\\poste-2-170\OPSAM_v3\OPSAM\Base\{scenario}"
    )
    return Path(base_dir) / f"reseau_detaille_linkshape_{scenario}.shp"


def _link_evolue_csv() -> Path:
    """Table d'affectation contenant VOLUME et VOL_Mn_I/E/T."""
    v = os.environ.get("SERM_LINK_EVOLUE_CSV")
    if v:
        return Path(v)
    scenario = _scenario_opsam()
    base_dir = (
        os.environ.get("SERM_OPSAM_BASE_DIR")
        or rf"\\poste-2-170\OPSAM_v3\OPSAM\Base\{scenario}"
    )
    return Path(base_dir) / f"Link_evolue_{scenario}.csv"


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


def volumes_deja_presents(gdf: gpd.GeoDataFrame) -> bool:
    """True si VOLUME et VOL_Mn_I/E/T sont deja dans le GeoDataFrame."""
    return all(c in gdf.columns for c in COLONNES_VOLUME_REQUISES)


def joindre_volumes_affectation(
    gdf: gpd.GeoDataFrame,
    chemin_csv: Path,
) -> gpd.GeoDataFrame:
    """Joint ``VOLUME`` et ``VOL_Mn_I/E/T`` depuis Link_evolue (fallback).

    Cle privilegiee : ``A_SIMPLE``/``B_SIMPLE`` ↔ ``A``/``B``.
    Sinon tente ``A``/``B`` du shapefile.
    """
    if not chemin_csv.is_file():
        raise FileNotFoundError(
            f"Table d'affectation introuvable : {chemin_csv}. "
            "Definir SERM_LINK_EVOLUE_CSV ou placer Link_evolue_*.csv "
            "dans SERM_OPSAM_BASE_DIR."
        )

    if {"A_SIMPLE", "B_SIMPLE"}.issubset(gdf.columns):
        left_on = ["A_SIMPLE", "B_SIMPLE"]
    elif {"A", "B"}.issubset(gdf.columns):
        left_on = ["A", "B"]
        LOG.warning(
            "Jointure sur A/B (pas A_SIMPLE/B_SIMPLE) — couverture "
            "potentiellement incomplete."
        )
    else:
        raise KeyError(
            "Ni A_SIMPLE/B_SIMPLE ni A/B dans le reseau — "
            "jointure Link_evolue impossible."
        )

    LOG.info("Lecture des volumes d'affectation : %s", chemin_csv)
    vols = pd.read_csv(chemin_csv, usecols=COLONNES_VOLUME_LINK)
    LOG.info("Table Link_evolue : %d liens", len(vols))

    avant = len(gdf)
    merged = gdf.merge(
        vols,
        left_on=left_on,
        right_on=["A", "B"],
        how="left",
        suffixes=("", "_vol"),
    )
    for col in ("A", "B"):
        col_vol = f"{col}_vol"
        if col_vol in merged.columns:
            merged = merged.drop(columns=[col_vol])

    n_ok = int(merged["VOLUME"].notna().sum()) if "VOLUME" in merged.columns else 0
    LOG.info(
        "Jointure volumes : %d / %d troncons matches (%.1f %%)",
        n_ok,
        avant,
        100.0 * n_ok / max(avant, 1),
    )
    return merged


def assurer_volumes(
    gdf: gpd.GeoDataFrame,
    chemin_csv: Path | None,
) -> gpd.GeoDataFrame:
    """Conserve les volumes du shp, sinon joint Link_evolue."""
    if volumes_deja_presents(gdf):
        LOG.info(
            "Volumes VOLUME / VOL_Mn_* deja presents dans le shapefile "
            "— pas de jointure Link_evolue."
        )
        return gdf
    if chemin_csv is None:
        raise FileNotFoundError(
            "VOLUME / VOL_Mn_* absents du reseau et aucun CSV Link_evolue "
            "fourni (--link-evolue / SERM_LINK_EVOLUE_CSV)."
        )
    LOG.warning(
        "VOLUME / VOL_Mn_* absents du shapefile — jointure Link_evolue."
    )
    return joindre_volumes_affectation(gdf, chemin_csv)


def _source_macrozone_par_slug() -> dict[str, str]:
    """Retourne ``{slug: 'M1'|'M2'}`` depuis ``territoire.yaml``."""
    racine = Path(__file__).resolve().parents[1]
    if str(racine) not in sys.path:
        sys.path.insert(0, str(racine))
    try:
        from config.territoire_loader import charger_config

        config = charger_config()
        mapping = {
            z.slug: z.macrozone.source.upper() for z in config.zones
        }
        LOG.info("Sources macrozone par slug : %s", mapping)
        return mapping
    except Exception as exc:
        LOG.warning(
            "Config territoire inaccessible (%s) — fallback %s",
            exc,
            _SOURCE_MACROZONE_FALLBACK,
        )
        return dict(_SOURCE_MACROZONE_FALLBACK)


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


def _volumes_iet(
    gdf: gpd.GeoDataFrame, prefix: str
) -> pd.DataFrame | None:
    """Volumes I/E/T d'un referentiel, ou None si une colonne manque."""
    colonnes = [f"VOL_{prefix}_{flux}" for flux in FLUX_IET]
    if any(col not in gdf.columns for col in colonnes):
        return None
    vols = pd.DataFrame(
        {
            flux: pd.to_numeric(
                gdf[f"VOL_{prefix}_{flux}"], errors="coerce"
            ).fillna(0).clip(lower=0).astype("float64")
            for flux in FLUX_IET
        },
        index=gdf.index,
    )
    return vols


def calculer_flux_iet_recales(
    gdf: gpd.GeoDataFrame,
    source_macrozone: str,
) -> gpd.GeoDataFrame:
    """Recale les volumes I/E/T sur ``TMJA_P`` via le ratio / ``VOLUME``.

    Pour chaque flux X in {I, E, T} ::

        TMJA_X = TMJA_P * VOL_{Mn}_X / VOLUME
        PART_X = VOL_{Mn}_X / VOLUME

    L'export OPSAM laisse ``VOL_M2_E`` a 0 et range tout le volume
    dans ``VOL_M2_I``. Sur ces lignes, le ratio bascule sur ``VOL_M1_*``,
    qui decompose bien le volume en interne / echange / transit.

    Parameters
    ----------
    gdf :
        Troncons clips du SERM.
    source_macrozone :
        ``M1`` (Dijon, NFC) ou ``M2`` (Besancon).
    """
    gdf = gdf.copy()
    prefix = (source_macrozone or "M1").upper()
    if prefix not in {"M1", "M2"}:
        LOG.warning(
            "Source macrozone invalide %r — fallback M1", source_macrozone
        )
        prefix = "M1"

    if "TMJA_P" not in gdf.columns or "VOLUME" not in gdf.columns:
        LOG.warning(
            "TMJA_P ou VOLUME absents — TMJA_I/E/T et PART_I/E/T a 0"
        )
        for flux in FLUX_IET:
            gdf[f"TMJA_{flux}"] = 0.0
            gdf[f"PART_{flux}"] = 0.0
        gdf["source_macrozone"] = prefix
        return gdf

    tmja = pd.to_numeric(gdf["TMJA_P"], errors="coerce").fillna(0).clip(
        lower=0
    )
    volume = pd.to_numeric(gdf["VOLUME"], errors="coerce").fillna(0).clip(
        lower=0
    )
    preferes = _volumes_iet(gdf, prefix)
    autre_prefix = "M1" if prefix == "M2" else "M2"
    autres = _volumes_iet(gdf, autre_prefix)
    if preferes is None:
        LOG.warning(
            "Colonnes VOL_%s_I/E/T absentes — TMJA I/E/T a 0", prefix
        )
        for flux in FLUX_IET:
            gdf[f"TMJA_{flux}"] = 0.0
            gdf[f"PART_{flux}"] = 0.0
        gdf["source_macrozone"] = prefix
        return gdf

    utilise_autre = pd.Series(False, index=gdf.index)
    if autres is not None:
        echange_absent = preferes["E"] + preferes["T"] == 0
        autre_decompose = autres["E"] + autres["T"] > 0
        utilise_autre = echange_absent & autre_decompose

    choix = preferes.copy()
    if bool(utilise_autre.any()):
        choix.loc[utilise_autre] = autres.loc[utilise_autre]
        LOG.info(
            "Ratio I/E/T : %d troncons bascules de %s vers %s "
            "(echange/transit vides)",
            int(utilise_autre.sum()),
            prefix,
            autre_prefix,
        )
    source = pd.Series(prefix, index=gdf.index, dtype="object")
    source.loc[utilise_autre] = autre_prefix
    gdf["source_macrozone"] = source

    masque = volume > 0
    for flux in FLUX_IET:
        ratio = pd.Series(0.0, index=gdf.index, dtype="float64")
        ratio.loc[masque] = (
            choix.loc[masque, flux] / volume.loc[masque]
        ).clip(lower=0)
        gdf[f"TMJA_{flux}"] = (tmja * ratio).clip(lower=0)
        gdf[f"PART_{flux}"] = ratio

    return gdf


# Metriques de trafic additionnees quand les deux sens existent.
_COLONNES_SENS = (
    "TMJA_P",
    "PL_P",
    "PL_jour",
    "VL_jour",
    "TMJA_I",
    "TMJA_E",
    "TMJA_T",
    "VOLUME",
)


def agreger_sens_contraire(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Une ligne par lien non oriente : les deux sens sont sommes.

    Les morceaux issus d'un clip gardent le TMJA du lien (max), ils
    ne sont pas additionnes entre eux. Seul le sens oppose l'est.
    """
    if gdf.empty or not {"A", "B"}.issubset(gdf.columns):
        return gdf

    from shapely.ops import unary_union

    df = gdf.copy()
    df["_A"] = pd.to_numeric(df["A"], errors="coerce")
    df["_B"] = pd.to_numeric(df["B"], errors="coerce")
    sans_noeuds = df[df["_A"].isna() | df["_B"].isna()].drop(
        columns=["_A", "_B"]
    )
    df = df.dropna(subset=["_A", "_B"]).copy()
    if df.empty:
        return gdf

    df["_u"] = df[["_A", "_B"]].min(axis=1)
    df["_v"] = df[["_A", "_B"]].max(axis=1)
    colonnes = [c for c in _COLONNES_SENS if c in df.columns]
    par_sens = (
        df.groupby(["_u", "_v", "_A", "_B"], dropna=False)[colonnes]
        .max()
        .reset_index()
    )
    sommes = par_sens.groupby(["_u", "_v"], as_index=False)[colonnes].sum()

    def _geom(groupe: pd.DataFrame):
        if "TMJA_P" in groupe.columns and len(groupe) > 1:
            score = groupe.groupby(["_A", "_B"])["TMJA_P"].max()
            noeud_a, noeud_b = score.idxmax()
            groupe = groupe[
                (groupe["_A"] == noeud_a) & (groupe["_B"] == noeud_b)
            ]
        return unary_union(list(groupe.geometry))

    geoms = df.groupby(["_u", "_v"], sort=False).apply(
        _geom, include_groups=False
    )
    geoms.name = "geometry"
    portees = [
        c for c in (
            "CL_ADMIN", "NUMERO", "NB_VOIES",
            "slug_serm", "nom_serm", "source_macrozone",
        )
        if c in df.columns
    ]
    if portees:
        attributs = (
            df.groupby(["_u", "_v"], sort=False)[portees]
            .first()
            .reset_index()
        )
    else:
        attributs = sommes[["_u", "_v"]].copy()
    out = sommes.merge(attributs, on=["_u", "_v"], how="left")
    out = out.merge(
        geoms.reset_index(), on=["_u", "_v"], how="left"
    )
    out["A"] = out["_u"]
    out["B"] = out["_v"]
    if "TMJA_P" in out.columns:
        tmja = pd.to_numeric(out["TMJA_P"], errors="coerce").fillna(0)
        for flux in FLUX_IET:
            col = f"TMJA_{flux}"
            if col not in out.columns:
                continue
            part = pd.Series(0.0, index=out.index, dtype="float64")
            masque = tmja > 0
            part.loc[masque] = (
                pd.to_numeric(out.loc[masque, col], errors="coerce")
                .fillna(0)
                / tmja.loc[masque]
            )
            out[f"PART_{flux}"] = part
    out = out.drop(columns=["_u", "_v"])
    resultat = gpd.GeoDataFrame(out, geometry="geometry", crs=gdf.crs)
    if (
        "DISTANCE_clip_km" in gdf.columns
        and resultat.crs is not None
        and resultat.crs.is_projected
    ):
        resultat["DISTANCE_clip_km"] = resultat.geometry.length / 1000.0
    if not sans_noeuds.empty:
        resultat = pd.concat(
            [resultat, sans_noeuds], ignore_index=True
        )
        resultat = gpd.GeoDataFrame(
            resultat, geometry="geometry", crs=gdf.crs
        )
    return resultat


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
    sources = _source_macrozone_par_slug()

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
        source_mz = sources.get(slug, "M1")

        LOG.info("Decoupe pour SERM %s (macrozone %s)", nom, source_mz)
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
        clipes = calculer_flux_iet_recales(clipes, source_mz)
        clipes = agreger_sens_contraire(clipes)
        clipes["slug_serm"] = slug
        clipes["nom_serm"] = nom

        clipes = clipes.to_crs(EPSG_AFFICHAGE)

        chemin = dossier / f"{slug}.gpkg"
        if chemin.exists():
            chemin.unlink()
        clipes.to_file(chemin, driver="GPKG")
        LOG.info(
            "Ecrit %s (%d troncons, %.1f km cumules, %s)",
            chemin,
            len(clipes),
            float(clipes["DISTANCE_clip_km"].sum()),
            source_mz,
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
        "--link-evolue", type=Path, default=None,
        help=(
            "CSV Link_evolue avec VOLUME / VOL_Mn_* "
            "(sinon SERM_LINK_EVOLUE_CSV)."
        ),
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
    link_csv = args.link_evolue
    if link_csv is None and not volumes_deja_presents(reseau):
        link_csv = _link_evolue_csv()
    reseau = assurer_volumes(reseau, link_csv)
    decouper_par_serm(reseau, perimetres, data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
