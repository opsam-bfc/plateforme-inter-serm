"""prepare_avatar_stations.py.

Transforme les sorties brutes d'``avatar_bfc_horaire.py`` en bundle leger
pour la plateforme Streamlit :

  data/avatar/stations.parquet          - metadonnees des stations (lon/lat)
  data/avatar/profils_horaires.parquet  - profil horaire moyen (heure 0-23)
                                          par station : flow, pl_pct, vitesse

Utilisation :
    python scripts/prepare_avatar_stations.py \\
        --metadonnees sortie_avatar_bfc/metadonnees_stations_bfc.csv \\
        --horaire     sortie_avatar_bfc/horaire_consolide_2026.csv
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Chemins
# ---------------------------------------------------------------------------

def data_dir() -> Path:
    """Retourne le dossier ``data/`` actif (respecte SERM_DATA_DIR)."""
    v = os.environ.get("SERM_DATA_DIR")
    return Path(v) if v else _ROOT / "data"


# ---------------------------------------------------------------------------
# Preparation
# ---------------------------------------------------------------------------

def preparer_stations(chemin_meta: Path, chemin_horaire: Path) -> None:
    """Pipeline complet : lit les CSV bruts AVATAR, ecrit les parquet.

    Args:
        chemin_meta: Fichier ``metadonnees_stations_bfc.csv`` produit par
            ``avatar_bfc_horaire.py``.
        chemin_horaire: Fichier ``horaire_consolide_YYYY.csv`` produit par
            la meme pipeline (fusion de tous les CSV mensuels).

    Raises:
        FileNotFoundError: Si l'un des fichiers d'entree est absent.
    """
    for chemin in (chemin_meta, chemin_horaire):
        if not chemin.is_file():
            raise FileNotFoundError(f"Fichier introuvable : {chemin}")

    dossier = data_dir() / "avatar"
    dossier.mkdir(parents=True, exist_ok=True)

    # ── Metadonnees stations ─────────────────────────────────────────────
    logger.info("Chargement metadonnees : %s", chemin_meta)
    stations = pd.read_csv(chemin_meta, sep=";", decimal=".", dtype=str)

    stations["count_point_id"] = pd.to_numeric(
        stations["count_point_id"], errors="coerce"
    ).astype("Int64")
    for col in ("longitude", "latitude"):
        stations[col] = pd.to_numeric(stations[col], errors="coerce")
    for col in ("nb_heures_2026", "operator_id"):
        if col in stations.columns:
            stations[col] = pd.to_numeric(stations[col], errors="coerce")
    if "disponible_2026" in stations.columns:
        stations["disponible_2026"] = (
            pd.to_numeric(stations["disponible_2026"], errors="coerce")
            .fillna(0).astype(bool)
        )

    # Conserver uniquement les stations avec donnees horaires disponibles
    stations_dispo = stations[stations["disponible_2026"]].copy()

    chemin_stations = dossier / "stations.parquet"
    stations_dispo.to_parquet(chemin_stations, index=False)
    logger.info(
        "Stations exportees : %s (%d/%d avec donnees)",
        chemin_stations,
        len(stations_dispo),
        len(stations),
    )

    # ── Profils horaires moyens ──────────────────────────────────────────
    logger.info("Chargement horaire consolide : %s", chemin_horaire)

    # Lecture par chunks (fichier potentiellement volumineux)
    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        chemin_horaire,
        sep=";",
        decimal=".",
        chunksize=500_000,
    ):
        # Normaliser le nom de la colonne datetime (presence variable)
        col_dt = next(
            (c for c in chunk.columns if "datetime" in c.lower()), None
        )
        if col_dt is None:
            logger.warning("Colonne measure_datetime absente dans un chunk.")
            continue
        chunk["heure"] = pd.to_datetime(
            chunk[col_dt], errors="coerce"
        ).dt.hour

        cols_interet = [
            "count_point_id", "heure",
            "flow[veh/h]", "truck[veh/h]", "speed[km/h]",
        ]
        cols_present = [c for c in cols_interet if c in chunk.columns]
        chunks.append(chunk[cols_present].copy())

    if not chunks:
        raise ValueError("Aucune donnee horaire chargee - verifier le CSV.")

    horaire = pd.concat(chunks, ignore_index=True)
    del chunks

    horaire["count_point_id"] = pd.to_numeric(
        horaire["count_point_id"], errors="coerce"
    )
    horaire["flow[veh/h]"] = pd.to_numeric(
        horaire["flow[veh/h]"], errors="coerce"
    )
    horaire = horaire.dropna(subset=["count_point_id", "heure", "flow[veh/h]"])

    if "truck[veh/h]" in horaire.columns:
        horaire["truck[veh/h]"] = pd.to_numeric(
            horaire["truck[veh/h]"], errors="coerce"
        )
        mask_pos = horaire["flow[veh/h]"] > 0
        horaire["pl_pct"] = float("nan")
        horaire.loc[mask_pos, "pl_pct"] = (
            horaire.loc[mask_pos, "truck[veh/h]"]
            / horaire.loc[mask_pos, "flow[veh/h]"]
            * 100
        )
    else:
        horaire["pl_pct"] = float("nan")

    if "speed[km/h]" in horaire.columns:
        horaire["speed[km/h]"] = pd.to_numeric(
            horaire["speed[km/h]"], errors="coerce"
        )

    # Agregation : moyenne par station x heure
    colonnes_agg: dict[str, str] = {"flow[veh/h]": "mean", "pl_pct": "mean"}
    if "speed[km/h]" in horaire.columns:
        colonnes_agg["speed[km/h]"] = "mean"

    profils = (
        horaire.groupby(["count_point_id", "heure"])
        .agg(colonnes_agg)
        .reset_index()
        .rename(columns={
            "flow[veh/h]": "flow_moy",
            "pl_pct": "pl_pct_moy",
            "speed[km/h]": "vitesse_moy",
        })
    )
    profils["heure"] = profils["heure"].astype(int)

    chemin_profils = dossier / "profils_horaires.parquet"
    profils.to_parquet(chemin_profils, index=False)
    logger.info(
        "Profils exportes : %s (%d lignes, %d stations)",
        chemin_profils,
        len(profils),
        profils["count_point_id"].nunique(),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parser_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare le bundle AVATAR (stations + profils horaires) "
            "pour la plateforme Streamlit inter-SERM."
        )
    )
    parser.add_argument(
        "--metadonnees",
        type=Path,
        required=True,
        help="Chemin vers metadonnees_stations_bfc.csv.",
    )
    parser.add_argument(
        "--horaire",
        type=Path,
        required=True,
        help="Chemin vers horaire_consolide_YYYY.csv.",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Journalisation detaillee."
    )
    return parser.parse_args()


def main() -> None:
    """Point d'entree CLI."""
    args = _parser_arguments()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    preparer_stations(args.metadonnees, args.horaire)


if __name__ == "__main__":
    main()
