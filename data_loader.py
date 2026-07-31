"""data_loader.py.

Chargement du bundle de donnees precalcule (dossier ``data/``) pour
l'application Streamlit ``plateforme_analyse_inter_SERM``.

Pour absorber des evolutions de perimetres SERM, les precalculs sont
regeneres hors application (``scripts/rebuild_for_new_perimeter.py``)
et la signature du bundle (timestamps des fichiers) est utilisee pour
invalider les caches Streamlit lorsque les fichiers changent.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
import zipfile
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
        3: {"code": 3, "nom": "SERM Bisontin", "nom_court": "Besancon",
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
_CLE_SCENARIO_ENV = "SERM_SCENARIO"
_DOSSIERS_EXCLUS = {"avatar"}


def data_root() -> Path:
    """Racine ``data/`` (contient les sous-dossiers de scénario + avatar)."""
    return _ROOT / "data"


def avatar_dir() -> Path:
    """Dossier AVATAR partagé (indépendant du scénario OPSAM)."""
    return data_root() / "avatar"


def scenario_actif() -> str:
    """Identifiant du scénario OPSAM actif (env ``SERM_SCENARIO`` ou config)."""
    env = (os.environ.get(_CLE_SCENARIO_ENV) or "").strip()
    if env:
        return env
    try:
        from config.territoire_loader import scenario_defaut
        return scenario_defaut()
    except Exception:
        return "Ref2024"


def definir_scenario(scenario_id: str) -> None:
    """Fixe le scénario actif pour le process (et les chargeurs)."""
    os.environ[_CLE_SCENARIO_ENV] = str(scenario_id).strip()


def scenarios_avec_bundle() -> list[str]:
    """Scénarios dont le bundle est présent (fichier synthese détecté)."""
    root = data_root()
    trouves: list[str] = []
    if root.is_dir():
        for p in sorted(root.iterdir()):
            if (
                p.is_dir()
                and p.name not in _DOSSIERS_EXCLUS
                and not p.name.startswith(".")
                and (p / "synthese_serm_vl_pl.csv").is_file()
            ):
                trouves.append(p.name)
    # Rétrocompat layout plat data/synthese_*.csv
    if not trouves and (root / "synthese_serm_vl_pl.csv").is_file():
        try:
            from config.territoire_loader import scenario_defaut
            trouves = [scenario_defaut()]
        except Exception:
            trouves = ["Ref2024"]
    return trouves


def bundle_complet(scenario_id: str | None = None) -> bool:
    """True si le bundle du scénario contient la synthèse SERM."""
    sid = scenario_id or scenario_actif()
    return (data_root() / sid / "synthese_serm_vl_pl.csv").is_file() or (
        sid == scenario_actif()
        and (data_root() / "synthese_serm_vl_pl.csv").is_file()
    )


def data_dir() -> Path:
    """Retourne le dossier bundle du scénario actif.

    Ordre de résolution :
    1. ``SERM_DATA_DIR`` (surcharge absolue) ;
    2. ``data/{SERM_SCENARIO|défaut}/`` s'il existe ;
    3. ``data/`` plat (rétrocompatibilité).
    """
    v = (os.environ.get("SERM_DATA_DIR") or "").strip()
    if v:
        return Path(v)

    root = data_root()
    scenario = scenario_actif()
    candidate = root / scenario
    if candidate.is_dir() and (
        (candidate / "synthese_serm_vl_pl.csv").is_file()
        or any(candidate.iterdir())
    ):
        return candidate

    # Layout historique (fichiers à la racine de data/)
    if (root / "synthese_serm_vl_pl.csv").is_file():
        return root

    return candidate


def fichier_data(nom: str) -> Path:
    return data_dir() / nom


def signature_bundle() -> float:
    """Somme des mtime du bundle scénario + avatar (invalidation caches)."""
    total = 0.0
    for base in (data_dir(), avatar_dir()):
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_mtime
                except OSError:
                    pass
    # Inclure l'id de scénario pour forcer un refresh au changement
    total += sum(ord(c) for c in scenario_actif()) * 0.001
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


def gdf_vers_shapefile_zip(
    gdf: gpd.GeoDataFrame,
    nom_couche: str,
    *,
    epsg: int = 2154,
) -> bytes:
    """Serialise un GeoDataFrame en archive ZIP shapefile (shp/shx/dbf/prj/cpg).

    Par défaut en Lambert 93 (EPSG:2154), standard SIG DREAL / OPSAM.
    Les noms de colonnes sont tronqués à 10 caractères (limite DBF).
    """
    if gdf is None or gdf.empty:
        raise ValueError("GeoDataFrame vide — export shapefile impossible.")

    couche = "".join(
        c if (c.isalnum() or c in "_-") else "_" for c in nom_couche
    ).strip("_") or "couche"
    couche = couche[:50]

    export = gdf.copy()
    if export.crs is None:
        export = export.set_crs(4326)
    if export.crs.to_epsg() != epsg:
        export = export.to_crs(epsg)

    # Limite shapefile / DBF : 10 caractères par champ.
    renames: dict[str, str] = {}
    used: set[str] = set()
    for col in export.columns:
        if col == "geometry":
            continue
        base = str(col)[:10]
        candidate = base
        n = 1
        while candidate.lower() in used:
            suffix = f"_{n}"
            candidate = f"{base[: 10 - len(suffix)]}{suffix}"
            n += 1
        used.add(candidate.lower())
        if candidate != col:
            renames[col] = candidate
    if renames:
        export = export.rename(columns=renames)

    with tempfile.TemporaryDirectory(prefix="serm_shp_") as tmp:
        tmp_path = Path(tmp)
        shp_path = tmp_path / f"{couche}.shp"
        export.to_file(shp_path, driver="ESRI Shapefile", encoding="utf-8")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fichier in sorted(tmp_path.iterdir()):
                if fichier.is_file():
                    zf.write(fichier, arcname=fichier.name)
        return buf.getvalue()


def exporter_reseau_shapefile_zip(
    slug: str,
    *,
    epsg: int = 2154,
    nom_couche: str | None = None,
) -> bytes:
    """Charge le réseau trafic d'un SERM et renvoie un ZIP shapefile."""
    gdf = charger_reseau_serm(slug)
    return gdf_vers_shapefile_zip(
        gdf,
        nom_couche or f"reseau_trafic_{slug}",
        epsg=epsg,
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


# ---------------------------------------------------------------------------
# Filtrage des flux OD par territoire (EPCI ou commune)
# ---------------------------------------------------------------------------

def _cotes_epci(typologie: str) -> tuple[bool, bool]:
    """Indique si (origine, destination) portent un code EPCI, non communal."""
    if typologie == "echange_emis":
        return False, True
    if typologie == "echange_recus":
        return True, False
    return False, False


def mapping_commune_epci() -> dict[str, str]:
    """Correspondance code commune INSEE -> code EPCI (centroides du bundle)."""
    try:
        centro = charger_centroides_zones()
    except FileNotFoundError:
        return {}
    if "COM" not in centro.columns or "EPCI" not in centro.columns:
        return {}
    sous = centro.dropna(subset=["COM", "EPCI"])
    return dict(
        zip(_code_epci_str(sous["COM"]), _code_epci_str(sous["EPCI"]))
    )


def enrichir_epci_flux_od(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute ``epci_O`` / ``epci_D`` aux flux OD si le bundle ne les a pas.

    Les bundles anterieurs a l'ajout du filtre par territoire ne portent
    que les codes communes : l'EPCI de rattachement est alors deduit des
    centroides de zones.
    """
    if df is None or df.empty:
        return df
    if "epci_O" in df.columns and "epci_D" in df.columns:
        return df
    mapping = mapping_commune_epci()
    if not mapping or "typologie" not in df.columns:
        return df

    df = df.copy()
    for indice, suffixe in enumerate(("O", "D")):
        col_code = f"com_{suffixe}"
        if col_code not in df.columns:
            continue
        codes = _code_epci_str(df[col_code])
        deja_epci = (
            df["typologie"]
            .astype(str)
            .map(lambda t, i=indice: _cotes_epci(t)[i])
            .fillna(False)
            .astype(bool)
        )
        df[f"epci_{suffixe}"] = codes.where(deja_epci, codes.map(mapping))
    return df


def territoires_flux_od(df: pd.DataFrame) -> pd.DataFrame:
    """Territoires (EPCI et communes) presents dans un jeu de flux OD.

    Colonnes : ``type`` (``epci`` / ``commune``), ``code``, ``nom``,
    ``volume`` (somme des flux touchant le territoire).
    """
    colonnes = ["type", "code", "nom", "volume"]
    if df is None or df.empty:
        return pd.DataFrame(columns=colonnes)

    df = enrichir_epci_flux_od(df)
    noms_epci = mapping_noms_epci()
    morceaux: list[pd.DataFrame] = []

    for typologie, bloc in df.groupby("typologie"):
        cote_o, cote_d = _cotes_epci(str(typologie))
        for col_code, col_nom, est_epci in (
            ("com_O", "nom_O", cote_o),
            ("com_D", "nom_D", cote_d),
        ):
            if col_code not in bloc.columns:
                continue
            codes = _code_epci_str(bloc[col_code])
            noms = (
                bloc[col_nom].astype(str)
                if col_nom in bloc.columns
                else codes
            )
            morceaux.append(pd.DataFrame({
                "type": "epci" if est_epci else "commune",
                "code": codes.values,
                "nom": noms.values,
                "volume": bloc["volume"].values,
            }))
        # EPCI de rattachement des communes (flux internes notamment).
        for col in ("epci_O", "epci_D"):
            if col not in bloc.columns:
                continue
            codes = _code_epci_str(bloc[col])
            morceaux.append(pd.DataFrame({
                "type": "epci",
                "code": codes.values,
                "nom": codes.map(noms_epci).fillna(codes).values,
                "volume": bloc["volume"].values,
            }))

    if not morceaux:
        return pd.DataFrame(columns=colonnes)

    tous = pd.concat(morceaux, ignore_index=True)
    tous = tous[~tous["code"].isin(["0", "", "nan", "None"])]
    tous = tous[tous["code"].notna()]
    if tous.empty:
        return pd.DataFrame(columns=colonnes)

    agrege = (
        tous.groupby(["type", "code"], as_index=False)
        .agg(nom=("nom", "first"), volume=("volume", "sum"))
        .sort_values("volume", ascending=False)
        .reset_index(drop=True)
    )
    return agrege[colonnes]


def filtrer_flux_od(
    df: pd.DataFrame,
    type_territoire: str | None = None,
    code: str | None = None,
) -> pd.DataFrame:
    """Conserve les flux dont une extremite est le territoire demande."""
    if df is None or df.empty or not type_territoire or not code:
        return df

    cible = str(code).strip()
    df = enrichir_epci_flux_od(df)
    colonnes = ["com_O", "com_D"]
    if type_territoire == "epci":
        # Les codes EPCI apparaissent aussi dans com_O / com_D pour les
        # extremites externes des flux emis / recus.
        colonnes = ["epci_O", "epci_D", "com_O", "com_D"]

    masque = pd.Series(False, index=df.index)
    for col in colonnes:
        if col in df.columns:
            masque |= _code_epci_str(df[col]) == cible
    return df[masque]


def _centroides_communes_epci() -> pd.DataFrame:
    """Table COM / NOM_COM / EPCI / lon / lat depuis les centroides zones."""
    centro = charger_centroides_zones()
    if centro.empty:
        return pd.DataFrame(
            columns=["COM", "NOM_COM", "EPCI", "lon", "lat", "code_serm"]
        )
    agg = {
        "lon": ("lon", "mean"),
        "lat": ("lat", "mean"),
        "NOM_COM": ("NOM_COM", "first"),
        "EPCI": ("EPCI", "first"),
    }
    if "code_serm" in centro.columns:
        agg["code_serm"] = ("code_serm", "first")
    return (
        centro.dropna(subset=["COM"])
        .assign(COM=lambda d: _code_epci_str(d["COM"]))
        .groupby("COM", as_index=False)
        .agg(**agg)
        .assign(EPCI=lambda d: _code_epci_str(d["EPCI"]))
    )


def agreger_top_od_vl_en_communes(df_vl: pd.DataFrame) -> pd.DataFrame:
    """Reagrege ``top_od_vl_par_serm`` au format commune / EPCI des Corridors.

    Utile en secours lorsque le top commune (``top_od_com_serm``) a elimine
    un EPCI a faibles volumes (troncature TOP 300) alors que des flux
    zone OPSAM existent encore dans ``top_od_vl_par_serm``.
    """
    if df_vl is None or df_vl.empty:
        return pd.DataFrame()

    com_c = _centroides_communes_epci()
    com_meta = com_c.set_index("COM")
    epci_c = (
        com_c.groupby("EPCI", as_index=False)
        .agg(lon=("lon", "mean"), lat=("lat", "mean"))
        if not com_c.empty
        else pd.DataFrame(columns=["EPCI", "lon", "lat"])
    )
    noms_epci = mapping_noms_epci()
    blocs: list[pd.DataFrame] = []

    for (serm, typo), bloc in df_vl.groupby(["serm", "typologie"]):
        if typo == "interne_serm":
            sous = bloc[bloc["com_O"].astype(str) != bloc["com_D"].astype(str)]
            top = (
                sous.groupby(["com_O", "com_D"], as_index=False)["volume"]
                .sum()
            )
            top["com_O"] = _code_epci_str(top["com_O"])
            top["com_D"] = _code_epci_str(top["com_D"])
            top["epci_O"] = top["com_O"].map(com_meta["EPCI"])
            top["epci_D"] = top["com_D"].map(com_meta["EPCI"])
            top["nom_O"] = top["com_O"].map(com_meta["NOM_COM"])
            top["nom_D"] = top["com_D"].map(com_meta["NOM_COM"])
            top["lon_O"] = top["com_O"].map(com_meta["lon"])
            top["lat_O"] = top["com_O"].map(com_meta["lat"])
            top["lon_D"] = top["com_D"].map(com_meta["lon"])
            top["lat_D"] = top["com_D"].map(com_meta["lat"])
        elif typo == "echange_emis":
            sous = bloc[bloc["epci_D"].astype(str) != "0"]
            top = (
                sous.groupby(["com_O", "epci_D"], as_index=False)["volume"]
                .sum()
            )
            top["com_O"] = _code_epci_str(top["com_O"])
            top["epci_D"] = _code_epci_str(top["epci_D"])
            top["epci_O"] = top["com_O"].map(com_meta["EPCI"])
            top["com_D"] = top["epci_D"]
            top["nom_O"] = top["com_O"].map(com_meta["NOM_COM"])
            top["nom_D"] = top["epci_D"].map(noms_epci).fillna(top["epci_D"])
            top["lon_O"] = top["com_O"].map(com_meta["lon"])
            top["lat_O"] = top["com_O"].map(com_meta["lat"])
            top = top.merge(
                epci_c.rename(columns={
                    "EPCI": "epci_D", "lon": "lon_D", "lat": "lat_D",
                }),
                on="epci_D", how="left",
            )
        elif typo == "echange_recus":
            sous = bloc[bloc["epci_O"].astype(str) != "0"]
            top = (
                sous.groupby(["epci_O", "com_D"], as_index=False)["volume"]
                .sum()
            )
            top["epci_O"] = _code_epci_str(top["epci_O"])
            top["com_D"] = _code_epci_str(top["com_D"])
            top["epci_D"] = top["com_D"].map(com_meta["EPCI"])
            top["com_O"] = top["epci_O"]
            top["nom_O"] = top["epci_O"].map(noms_epci).fillna(top["epci_O"])
            top["nom_D"] = top["com_D"].map(com_meta["NOM_COM"])
            top["lon_D"] = top["com_D"].map(com_meta["lon"])
            top["lat_D"] = top["com_D"].map(com_meta["lat"])
            top = top.merge(
                epci_c.rename(columns={
                    "EPCI": "epci_O", "lon": "lon_O", "lat": "lat_O",
                }),
                on="epci_O", how="left",
            )
        else:
            continue

        top["serm"] = serm
        top["nom_serm"] = SERM_INFO.get(int(serm), {}).get("nom", str(serm))
        top["typologie"] = typo
        blocs.append(top)

    if not blocs:
        return pd.DataFrame()
    cols = [
        "serm", "nom_serm", "typologie",
        "com_O", "nom_O", "lon_O", "lat_O",
        "com_D", "nom_D", "lon_D", "lat_D",
        "volume", "epci_O", "epci_D",
    ]
    out = pd.concat(blocs, ignore_index=True)
    for col in cols:
        if col not in out.columns:
            out[col] = None
    return out[cols]


def flux_od_corridors(
    code_serm: int,
    typologie: str,
    type_territoire: str | None = None,
    code: str | None = None,
) -> pd.DataFrame:
    """Flux OD pour la page Corridors, avec secours zone OPSAM si besoin.

    1. Filtre ``top_od_com_serm`` (fichier principal de l'UI).
    2. Si un territoire est demande et qu'aucun couple n'y figure (cas
       typique d'un EPCI sous le seuil TOP 300, ex. CC Arbois en flux
       internes), reagrege ``top_od_vl_par_serm`` puis refiltre.
    """
    try:
        principal = charger_top_od_communes()
    except FileNotFoundError:
        principal = pd.DataFrame()

    filtre = pd.DataFrame()
    if not principal.empty:
        sous = principal[
            (principal["serm"] == code_serm)
            & (principal["typologie"] == typologie)
        ]
        filtre = filtrer_flux_od(sous, type_territoire, code)
        if not type_territoire or not code or not filtre.empty:
            return enrichir_epci_flux_od(filtre)

    # Secours : couples absents du top commune mais presents au niveau zone.
    try:
        secours = agreger_top_od_vl_en_communes(charger_top_od_vl())
    except FileNotFoundError:
        return enrichir_epci_flux_od(filtre)

    if secours.empty:
        return enrichir_epci_flux_od(filtre)

    sous_s = secours[
        (secours["serm"] == code_serm)
        & (secours["typologie"] == typologie)
    ]
    return filtrer_flux_od(sous_s, type_territoire, code)


def territoires_corridors(code_serm: int, typologie: str) -> pd.DataFrame:
    """Territoires filtrables : EPCI du SERM + communes visibles dans les flux.

    Les EPCI du polygone (`limites_epci.geojson`) sont toujours proposes,
    meme s'ils n'ont aucun couple dans le top 300 commune (ex. Arbois).
    Le volume affiche combine top commune, top zone et echanges EPCI.
    """
    colonnes = ["type", "code", "nom", "volume"]
    morceaux: list[pd.DataFrame] = []
    noms_epci = mapping_noms_epci()

    # 1) EPCI du SERM (couche geographique — toujours presents).
    try:
        epci_gdf = charger_limites_epci()
    except Exception:
        epci_gdf = None
    if epci_gdf is not None and not epci_gdf.empty:
        epci_serm = epci_gdf[epci_gdf["code_serm"] == code_serm]
        if not epci_serm.empty:
            codes = _code_epci_str(epci_serm["CODE_SIREN"])
            noms = epci_serm["NOM"].astype(str).values
            morceaux.append(pd.DataFrame({
                "type": "epci",
                "code": codes.values,
                "nom": noms,
                "volume": 0.0,
            }))

    # 2) Volumes issus des flux commune + secours zone OPSAM.
    try:
        flux = flux_od_corridors(code_serm, typologie)
        if not flux.empty:
            morceaux.append(territoires_flux_od(flux))
        # Completer avec les couples absents du top commune (ex. Arbois).
        secours = agreger_top_od_vl_en_communes(charger_top_od_vl())
        if not secours.empty:
            sous_s = secours[
                (secours["serm"] == code_serm)
                & (secours["typologie"] == typologie)
            ]
            if not sous_s.empty:
                morceaux.append(territoires_flux_od(sous_s))
    except Exception as exc:
        LOG.debug("Territoires flux OD indisponibles : %s", exc)

    # 3) Volumes agreges EPCI (page echanges) pour informer le libelle.
    try:
        ech = charger_echanges_epci()
        typo_ech = (
            "echange_serm"
            if typologie in ("echange_emis", "echange_recus")
            else "interne_serm"
        )
        sous = ech[(ech["serm"] == code_serm) & (ech["typologie"] == typo_ech)]
        if not sous.empty:
            for col, col_nom in (
                ("epci_O", "epci_O_nom"), ("epci_D", "epci_D_nom"),
            ):
                codes = _code_epci_str(sous[col])
                noms = (
                    sous[col_nom].astype(str)
                    if col_nom in sous.columns
                    else codes.map(noms_epci).fillna(codes)
                )
                morceaux.append(pd.DataFrame({
                    "type": "epci",
                    "code": codes.values,
                    "nom": noms.values,
                    "volume": sous["volume"].values,
                }))
    except Exception as exc:
        LOG.debug("Volumes echanges EPCI indisponibles : %s", exc)

    # 4) Communes du SERM (centroides) pour les typologies internes.
    if typologie == "interne_serm":
        try:
            com_c = _centroides_communes_epci()
            if "code_serm" in com_c.columns:
                com_serm = com_c[com_c["code_serm"] == code_serm]
            else:
                com_serm = com_c
            if not com_serm.empty:
                morceaux.append(pd.DataFrame({
                    "type": "commune",
                    "code": com_serm["COM"].values,
                    "nom": com_serm["NOM_COM"].astype(str).values,
                    "volume": 0.0,
                }))
        except Exception as exc:
            LOG.debug("Communes centroides indisponibles : %s", exc)

    if not morceaux:
        return pd.DataFrame(columns=colonnes)

    tous = pd.concat(morceaux, ignore_index=True)
    tous = tous[~tous["code"].isin(["0", "", "nan", "None"])]
    tous = tous[tous["code"].notna()]
    if tous.empty:
        return pd.DataFrame(columns=colonnes)

    return (
        tous.groupby(["type", "code"], as_index=False)
        .agg(nom=("nom", "first"), volume=("volume", "sum"))
        .sort_values(["type", "volume"], ascending=[True, False])
        .reset_index(drop=True)
    )[colonnes]


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


# ---------------------------------------------------------------------------
# Comptages AVATAR (DIR Est / DIR Centre-Est)
# ---------------------------------------------------------------------------

def charger_stations_avatar() -> pd.DataFrame:
    """Charge ``data/avatar/metadonnees_stations_bfc.csv`` (stations).

    Returns:
        DataFrame avec colonnes : count_point_id, count_point_name,
        operator_name, longitude, latitude, op_road_name,
        route_normalisee, op_direction, nb_heures_2026, ...

    Raises:
        FileNotFoundError: Si le fichier de metadonnees est absent.
    """
    chemin = avatar_dir() / "metadonnees_stations_bfc.csv"
    if not chemin.is_file():
        raise FileNotFoundError(
            f"Fichier introuvable : {chemin}. "
            "Copier sortie_avatar_bfc/metadonnees_stations_bfc.csv "
            "dans data/avatar/."
        )
    df = pd.read_csv(chemin, sep=";", decimal=".", dtype=str)
    df["count_point_id"] = pd.to_numeric(
        df["count_point_id"], errors="coerce"
    )
    for col in ("longitude", "latitude"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    for col in ("nb_heures_2026", "operator_id"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "disponible_2026" in df.columns:
        df["disponible_2026"] = (
            pd.to_numeric(df["disponible_2026"], errors="coerce")
            .fillna(0).astype(bool)
        )
        df = df[df["disponible_2026"]].copy()
    return df.reset_index(drop=True)


def charger_profils_avatar() -> pd.DataFrame:
    """Charge ``data/avatar/moyenne_horaire_consolide_2026.csv``.

    Chaque ligne = (count_point_id, heure 0-23, flow_moy, pl_pct_moy,
    vitesse_moy). Profil moyen toutes periodes confondues.

    Genere par ``generer_moyenne_horaire.py`` (script standalone).

    Returns:
        DataFrame avec colonnes : count_point_id, heure, flow_moy,
        pl_pct_moy, vitesse_moy (NaN si absentes).

    Raises:
        FileNotFoundError: Si le fichier CSV n'a pas encore ete genere.
    """
    chemin = avatar_dir() / "moyenne_horaire_consolide_2026.csv"
    if not chemin.is_file():
        raise FileNotFoundError(
            f"Fichier introuvable : {chemin}. "
            "Lancer generer_moyenne_horaire.py puis copier le resultat "
            "dans data/avatar/."
        )
    df = pd.read_csv(chemin, sep=";", decimal=".")
    df["count_point_id"] = pd.to_numeric(
        df["count_point_id"], errors="coerce"
    )
    df["heure"] = pd.to_numeric(df["heure"], errors="coerce").astype("Int64")
    for col in ("flow_moy", "pl_pct_moy", "vitesse_moy"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


@lru_cache(maxsize=8)
def _mtime(chemin: str) -> float:
    p = Path(chemin)
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0
