"""prepare_avatar_stations.py.

Transforme les sorties brutes d'``avatar_bfc_horaire.py`` en bundle leger
pour la plateforme Streamlit :

  data/avatar/stations.parquet          - metadonnees des stations (lon/lat)
  data/avatar/profils_horaires.parquet  - profil horaire moyen (heure 0-23)
                                          par station : flow, pl_pct, vitesse

Le calcul des profils lit les CSV mensuels individuels du dossier
``horaire/dir_est/`` et ``horaire/dir_centre_est/`` (et non le fichier
consolide, qui peut etre trop volumineux).  L'agregation est incrementale :
un seul fichier mensuel en memoire a la fois.

Utilisation :
    python scripts/prepare_avatar_stations.py \\
        --metadonnees sortie_avatar_bfc/metadonnees_stations_bfc.csv \\
        --dossier-horaire sortie_avatar_bfc/horaire
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import numpy as np
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
# Agregation incrementale
# ---------------------------------------------------------------------------

def _accumuler_csv(
    chemin: Path,
    acc_sum: dict[tuple, list],
    acc_cnt: dict[tuple, list],
) -> int:
    """Lit un CSV mensuel AVATAR et accumule sommes/comptages par (id, heure).

    Args:
        chemin: Fichier CSV mensuel.
        acc_sum: Accumulateur de sommes {(count_point_id, heure): [flow, truck, speed]}.
        acc_cnt: Accumulateur de comptages {(count_point_id, heure): [n_flow, n_truck, n_speed]}.

    Returns:
        Nombre de lignes utiles traitees.
    """
    if not chemin.is_file():
        return 0
    try:
        df = pd.read_csv(chemin, sep=";", decimal=".", low_memory=False)
    except Exception as exc:
        logger.warning("Lecture impossible %s : %s", chemin.name, exc)
        return 0

    # Colonne datetime : identifier le bon nom
    col_dt = next(
        (c for c in df.columns if "datetime" in c.lower()), None
    )
    if col_dt is None or "count_point_id" not in df.columns:
        logger.debug("Colonnes manquantes dans %s — ignore.", chemin.name)
        return 0

    df["heure"] = pd.to_datetime(df[col_dt], errors="coerce").dt.hour
    df["count_point_id"] = pd.to_numeric(df["count_point_id"], errors="coerce")

    col_flow = "flow[veh/h]"
    col_truck = "truck[veh/h]"
    col_speed = "speed[km/h]"

    for col in (col_flow, col_truck, col_speed):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["count_point_id", "heure", col_flow])
    if df.empty:
        return 0

    n_lignes = 0
    for _, row in df.iterrows():
        cle = (int(row["count_point_id"]), int(row["heure"]))
        flow = row[col_flow]
        truck = row.get(col_truck, np.nan) if col_truck in df.columns else np.nan
        speed = row.get(col_speed, np.nan) if col_speed in df.columns else np.nan

        if cle not in acc_sum:
            acc_sum[cle] = [0.0, 0.0, 0.0]
            acc_cnt[cle] = [0, 0, 0]

        if not np.isnan(flow):
            acc_sum[cle][0] += flow
            acc_cnt[cle][0] += 1
        if not np.isnan(truck):
            acc_sum[cle][1] += truck
            acc_cnt[cle][1] += 1
        if not np.isnan(speed):
            acc_sum[cle][2] += speed
            acc_cnt[cle][2] += 1
        n_lignes += 1

    return n_lignes


def _accumuler_csv_vectorise(
    chemin: Path,
    acc: dict[tuple, list],
) -> int:
    """Version vectorisee (pandas groupby) : plus rapide que la boucle ligne.

    acc[(count_point_id, heure)] = [sum_flow, cnt_flow,
                                    sum_truck, cnt_truck,
                                    sum_speed, cnt_speed]
    """
    if not chemin.is_file():
        return 0
    try:
        df = pd.read_csv(chemin, sep=";", decimal=".", low_memory=False)
    except Exception as exc:
        logger.warning("Lecture impossible %s : %s", chemin.name, exc)
        return 0

    col_dt = next(
        (c for c in df.columns if "datetime" in c.lower()), None
    )
    if col_dt is None or "count_point_id" not in df.columns:
        return 0

    df["heure"] = pd.to_datetime(df[col_dt], errors="coerce").dt.hour
    df["count_point_id"] = pd.to_numeric(
        df["count_point_id"], errors="coerce"
    )

    col_flow = "flow[veh/h]"
    col_truck = "truck[veh/h]"
    col_speed = "speed[km/h]"

    for col in (col_flow, col_truck, col_speed):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = np.nan

    df = df.dropna(subset=["count_point_id", "heure", col_flow])
    if df.empty:
        return 0

    grp = df.groupby(["count_point_id", "heure"])
    sums = grp[[col_flow, col_truck, col_speed]].sum(min_count=1)
    cnts = grp[[col_flow, col_truck, col_speed]].count()

    for (cp_id, heure), row_s in sums.iterrows():
        row_c = cnts.loc[(cp_id, heure)]
        cle = (int(cp_id), int(heure))
        if cle not in acc:
            acc[cle] = [0.0, 0, 0.0, 0, 0.0, 0]
        v = acc[cle]
        f_s = row_s[col_flow]
        f_c = int(row_c[col_flow])
        t_s = row_s[col_truck]
        t_c = int(row_c[col_truck])
        sp_s = row_s[col_speed]
        sp_c = int(row_c[col_speed])
        if not np.isnan(f_s):
            v[0] += f_s
            v[1] += f_c
        if not np.isnan(t_s):
            v[2] += t_s
            v[3] += t_c
        if not np.isnan(sp_s):
            v[4] += sp_s
            v[5] += sp_c

    return len(df)


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------

def preparer_stations(
    chemin_meta: Path,
    dossier_horaire: Path,
) -> None:
    """Pipeline : lit les CSV mensuels AVATAR, ecrit les parquet.

    Args:
        chemin_meta: Fichier ``metadonnees_stations_bfc.csv``.
        dossier_horaire: Dossier ``horaire/`` contenant les sous-dossiers
            operateurs (``dir_est/``, ``dir_centre_est/``).

    Raises:
        FileNotFoundError: Si l'un des chemins d'entree est absent.
    """
    if not chemin_meta.is_file():
        raise FileNotFoundError(f"Metadonnees introuvables : {chemin_meta}")
    if not dossier_horaire.is_dir():
        raise FileNotFoundError(f"Dossier horaire introuvable : {dossier_horaire}")

    dossier_sortie = data_dir() / "avatar"
    dossier_sortie.mkdir(parents=True, exist_ok=True)

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

    stations_dispo = stations[stations.get("disponible_2026", pd.Series(True, index=stations.index))].copy()
    chemin_stations = dossier_sortie / "stations.parquet"
    stations_dispo.to_parquet(chemin_stations, index=False)
    logger.info(
        "Stations exportees : %s (%d/%d avec donnees)",
        chemin_stations, len(stations_dispo), len(stations),
    )

    # ── Agregation incrementale des profils horaires ─────────────────────
    # acc[(count_point_id, heure)] = [sum_flow, cnt_flow,
    #                                  sum_truck, cnt_truck,
    #                                  sum_speed, cnt_speed]
    acc: dict[tuple, list] = {}

    fichiers_csv = sorted(dossier_horaire.rglob("*.csv"))
    logger.info(
        "Agregation incrementale sur %d fichiers CSV mensuels...",
        len(fichiers_csv),
    )
    total_lignes = 0
    for i, fic in enumerate(fichiers_csv, 1):
        n = _accumuler_csv_vectorise(fic, acc)
        total_lignes += n
        logger.info(
            "[%d/%d] %s — %d lignes (cumul : %d)",
            i, len(fichiers_csv), fic.name, n, total_lignes,
        )

    if not acc:
        raise ValueError(
            "Aucune donnee horaire trouvee dans "
            f"{dossier_horaire}. Verifier les CSV."
        )

    # ── Construction du DataFrame de profils ─────────────────────────────
    lignes = []
    for (cp_id, heure), v in acc.items():
        sum_flow, cnt_flow = v[0], v[1]
        sum_truck, cnt_truck = v[2], v[3]
        sum_speed, cnt_speed = v[4], v[5]

        flow_moy = sum_flow / cnt_flow if cnt_flow > 0 else np.nan
        truck_moy = sum_truck / cnt_truck if cnt_truck > 0 else np.nan
        speed_moy = sum_speed / cnt_speed if cnt_speed > 0 else np.nan

        pl_pct_moy = (
            truck_moy / flow_moy * 100
            if (flow_moy and not np.isnan(flow_moy) and flow_moy > 0
                and not np.isnan(truck_moy))
            else np.nan
        )
        lignes.append({
            "count_point_id": cp_id,
            "heure": heure,
            "flow_moy": round(flow_moy, 2) if not np.isnan(flow_moy) else np.nan,
            "pl_pct_moy": round(pl_pct_moy, 2) if not np.isnan(pl_pct_moy) else np.nan,
            "vitesse_moy": round(speed_moy, 2) if not np.isnan(speed_moy) else np.nan,
        })

    profils = pd.DataFrame(lignes).sort_values(
        ["count_point_id", "heure"]
    ).reset_index(drop=True)

    chemin_profils = dossier_sortie / "profils_horaires.parquet"
    profils.to_parquet(chemin_profils, index=False)
    logger.info(
        "Profils exportes : %s (%d lignes, %d stations uniques)",
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
            "Prepare le bundle AVATAR (stations + profils horaires moyens 0-23h) "
            "pour la plateforme Streamlit inter-SERM.\n\n"
            "Lit les CSV mensuels individuels (pas le consolide volumineux) "
            "pour une agregation incrementale econome en memoire."
        )
    )
    parser.add_argument(
        "--metadonnees",
        type=Path,
        required=True,
        help="Chemin vers metadonnees_stations_bfc.csv.",
    )
    parser.add_argument(
        "--dossier-horaire",
        type=Path,
        required=True,
        dest="dossier_horaire",
        help=(
            "Dossier horaire/ contenant les sous-dossiers operateurs "
            "(dir_est/, dir_centre_est/, ...)."
        ),
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
    preparer_stations(args.metadonnees, args.dossier_horaire)


if __name__ == "__main__":
    main()
