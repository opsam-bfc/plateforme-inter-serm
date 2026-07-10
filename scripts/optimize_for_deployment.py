"""optimize_for_deployment.py.

Script de preparation des donnees optimisees pour le deploiement Streamlit.

Objectif : reduire le volume du bundle ``data/`` de ~99 Mo a ~25 Mo en :
  1. Convertissant les GPKG reseau en GeoParquet (colonnes essentielles seules).
  2. Simplifiant les geometries GeoJSON (communes, EPCI, zones) avec une
     tolerance metrique equivalente a ~30 m (sans perte visible a l'ecran).
  3. Excluant le cache data.gouv (retelecharge a la demande).

Usage :
    python scripts/optimize_for_deployment.py [--data-dir <dossier>]

Le dossier source par defaut est ``data/`` a cote de ce script.
Le resultat est ecrit dans le meme dossier (remplacement en place, avec
sauvegarde des originaux dans ``data/.backup_avant_optim/``).
"""

from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

import geopandas as gpd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Colonnes conservees dans les GPKG reseau (tout le reste est supprime).
COLONNES_RESEAU = ["CL_ADMIN", "TMJA_P", "PL_jour", "VL_jour", "geometry"]

# Fichiers GeoJSON a simplifier (relatifs a data_dir).
# La liste des limites_communes_serm{N}.geojson est construite dynamiquement
# depuis la config du territoire (cf. _geojson_a_simplifier()).
_GEOJSON_FIXES = [
    "limites_epci.geojson",
    "zones_serm.geojson",
]


def _geojson_a_simplifier(data_dir: "Path") -> list[str]:
    """Construit la liste des GeoJSON a simplifier depuis la config."""
    fichiers = list(_GEOJSON_FIXES)
    try:
        import sys
        sys.path.insert(0, str(data_dir.parent))
        from config.territoire_loader import codes_zones
        for code in codes_zones(inclure_hors_serm=False):
            fichiers.append(f"limites_communes_serm{code}.geojson")
    except Exception as exc:
        LOG.warning(
            "Impossible de lire la config (%s) — "
            "utilisation de limites_communes_serm1/2/3.geojson par defaut.",
            exc,
        )
        for code in (1, 2, 3):
            fichiers.append(f"limites_communes_serm{code}.geojson")
    return fichiers


def _gpkg_a_convertir(data_dir: "Path") -> list[str]:
    """Construit la liste des GPKG a convertir depuis la config."""
    try:
        import sys
        sys.path.insert(0, str(data_dir.parent))
        from config.territoire_loader import slugs_reseau
        return [f"{slug}.gpkg" for slug in slugs_reseau()]
    except Exception as exc:
        LOG.warning(
            "Impossible de lire la config (%s) — "
            "utilisation de dijon/nfc/besancon.gpkg par defaut.",
            exc,
        )
        return ["dijon.gpkg", "nfc.gpkg", "besancon.gpkg"]

# Fichiers data.gouv caches a exclure (non necessaires hors page contexte).
CACHE_A_EXCLURE = [
    "rp2022_modes_dt.csv",
    "critair_epci.csv",
    "gares_sncf.geojson",
    "vp_elec_epci.csv",
    "freq_gares.csv",
]


# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------

def _taille_mo(chemin: Path) -> str:
    """Retourne la taille d'un fichier en Mo (affichage)."""
    try:
        return f"{chemin.stat().st_size / 1e6:.1f} Mo"
    except OSError:
        return "???"


def _sauvegarder(chemin: Path, backup_dir: Path) -> None:
    """Copie le fichier dans backup_dir avant transformation."""
    if not chemin.exists():
        return
    dest = backup_dir / chemin.name
    if not dest.exists():
        shutil.copy2(chemin, dest)
        LOG.debug("Sauvegarde : %s -> %s", chemin.name, backup_dir)


# ---------------------------------------------------------------------------
# Etape 1 : Conversion GPKG -> GeoParquet
# ---------------------------------------------------------------------------

def convertir_gpkg_en_parquet(data_dir: Path, backup_dir: Path) -> None:
    """Convertit les GPKG reseau en GeoParquet allege."""
    reseau_dir = data_dir / "reseau_serm"
    if not reseau_dir.is_dir():
        LOG.warning("Dossier introuvable : %s — etape ignoree.", reseau_dir)
        return

    for nom_gpkg in _gpkg_a_convertir(data_dir):
        chemin_gpkg = reseau_dir / nom_gpkg
        if not chemin_gpkg.is_file():
            LOG.warning("GPKG introuvable : %s — ignore.", chemin_gpkg)
            continue

        slug = chemin_gpkg.stem
        chemin_parquet = reseau_dir / f"{slug}.parquet"
        taille_avant = _taille_mo(chemin_gpkg)

        LOG.info("Conversion : %s (%s) ...", nom_gpkg, taille_avant)

        # Lecture GPKG
        gdf = gpd.read_file(chemin_gpkg)
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)

        # Conservation des colonnes essentielles uniquement
        cols_presentes = [c for c in COLONNES_RESEAU if c in gdf.columns]
        gdf = gdf[cols_presentes].copy()

        # Simplification geometrique (projection Lambert93 puis retour WGS84
        # pour une tolerance en metres coherente).
        try:
            gdf_proj = gdf.to_crs(2154)
            # Tolerance 30 m en systeme metrique
            gdf_proj["geometry"] = gdf_proj["geometry"].simplify(
                tolerance=30, preserve_topology=True
            )
            gdf = gdf_proj.to_crs(4326)
        except Exception as exc:
            LOG.warning(
                "Simplification echouee pour %s (%s) — conserve geometrie brute.",
                nom_gpkg, exc,
            )

        # Sauvegarde avant ecrasement
        _sauvegarder(chemin_gpkg, backup_dir)

        # Ecriture GeoParquet
        gdf.to_parquet(chemin_parquet, index=False)
        taille_apres = _taille_mo(chemin_parquet)
        LOG.info(
            "  -> %s : %s -> %s (colonnes conservees : %s)",
            chemin_parquet.name, taille_avant, taille_apres,
            ", ".join(cols_presentes[:-1]),  # sans 'geometry'
        )


# ---------------------------------------------------------------------------
# Etape 2 : Simplification GeoJSON
# ---------------------------------------------------------------------------

def simplifier_geojson(data_dir: Path, backup_dir: Path) -> None:
    """Simplifie les geometries des GeoJSON volumineux."""
    for nom in _geojson_a_simplifier(data_dir):
        chemin = data_dir / nom
        if not chemin.is_file():
            LOG.warning("GeoJSON introuvable : %s — ignore.", chemin)
            continue

        taille_avant = _taille_mo(chemin)
        LOG.info("Simplification : %s (%s) ...", nom, taille_avant)

        gdf = gpd.read_file(chemin)
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(4326)

        # Simplification en systeme metrique pour une tolerance coherente
        try:
            gdf_proj = gdf.to_crs(2154)
            gdf_proj["geometry"] = gdf_proj["geometry"].simplify(
                tolerance=30, preserve_topology=True
            )
            gdf = gdf_proj.to_crs(4326)
        except Exception as exc:
            LOG.warning(
                "Simplification echouee pour %s (%s) — conserve geometrie brute.",
                nom, exc,
            )

        # Sauvegarde avant ecrasement
        _sauvegarder(chemin, backup_dir)

        # Reecriture GeoJSON compresse (sans indentation)
        gdf.to_file(chemin, driver="GeoJSON")
        taille_apres = _taille_mo(chemin)
        LOG.info("  -> %s : %s -> %s", nom, taille_avant, taille_apres)


# ---------------------------------------------------------------------------
# Etape 3 : Deplacement des fichiers cache data.gouv
# ---------------------------------------------------------------------------

def deplacer_cache_datagouv(data_dir: Path, backup_dir: Path) -> None:
    """Deplace les fichiers cache data.gouv vers le backup (non deployes)."""
    deplaces = 0
    for nom in CACHE_A_EXCLURE:
        chemin = data_dir / nom
        if chemin.is_file():
            dest = backup_dir / nom
            if not dest.exists():
                shutil.move(str(chemin), str(dest))
                LOG.info("Cache deplace : %s -> backup/", nom)
            deplaces += 1
    if deplaces == 0:
        LOG.info("Aucun fichier cache data.gouv trouve — deja deplace ou absent.")


# ---------------------------------------------------------------------------
# Rapport final
# ---------------------------------------------------------------------------

def rapport_final(data_dir: Path) -> None:
    """Affiche le volume final du bundle optimise."""
    total = sum(
        f.stat().st_size for f in data_dir.rglob("*") if f.is_file()
    )
    LOG.info("=" * 60)
    LOG.info("Volume final bundle data/ : %.1f Mo", total / 1e6)
    LOG.info("=" * 60)
    for f in sorted(data_dir.rglob("*"), key=lambda p: -p.stat().st_size):
        if f.is_file():
            LOG.info("  %-45s %6.1f Mo", f.relative_to(data_dir), f.stat().st_size / 1e6)


# ---------------------------------------------------------------------------
# Point d'entree
# ---------------------------------------------------------------------------

def main() -> None:
    """Orchestre les trois etapes d'optimisation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Chemin vers le dossier data/ (defaut : ../data/ relatif a ce script)",
    )
    args = parser.parse_args()

    if args.data_dir:
        data_dir = Path(args.data_dir).resolve()
    else:
        data_dir = (Path(__file__).parent.parent / "data").resolve()

    if not data_dir.is_dir():
        raise SystemExit(f"Dossier data/ introuvable : {data_dir}")

    backup_dir = data_dir / ".backup_avant_optim"
    backup_dir.mkdir(exist_ok=True)
    LOG.info("Sauvegarde des originaux dans : %s", backup_dir)

    LOG.info("Etape 1 : Conversion GPKG -> GeoParquet ...")
    convertir_gpkg_en_parquet(data_dir, backup_dir)

    LOG.info("Etape 2 : Simplification GeoJSON ...")
    simplifier_geojson(data_dir, backup_dir)

    LOG.info("Etape 3 : Exclusion cache data.gouv ...")
    deplacer_cache_datagouv(data_dir, backup_dir)

    rapport_final(data_dir)
    LOG.info("Optimisation terminee. Les originaux sont dans %s", backup_dir)


if __name__ == "__main__":
    main()
