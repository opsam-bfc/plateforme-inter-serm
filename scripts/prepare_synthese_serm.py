"""prepare_synthese_serm.py.

Fusionne les fichiers de synthese macrozone OPSAM (synthese_m1, synthese_m2)
pour produire un fichier unique decrivant les trois SERM de
Bourgogne-Franche-Comte, enrichi des colonnes VL reconstituees par
deduction (Total - PL_charges - PL_vides) sur chaque flux et chaque
classe de distance.

Sortie : ``data/synthese_serm_vl_pl.csv``
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Iterable

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOG = logging.getLogger("prepare_synthese_serm")

# Definition du referentiel SERM unifie.
# Chaque SERM est decrit par la source (synthese_m1 ou m2) et le code
# de macrozone correspondant.
SERM_REFERENTIEL: list[dict] = [
    {
        "code_serm": 1,
        "nom_serm": "SERM Dijonnais",
        "slug_serm": "dijon",
        "source_macrozonage": "M1",
        "code_macrozone": 1,
    },
    {
        "code_serm": 2,
        "nom_serm": "SERM Nord Franche-Comte",
        "slug_serm": "nfc",
        "source_macrozonage": "M1",
        "code_macrozone": 2,
    },
    {
        "code_serm": 3,
        "nom_serm": "SERM Bisontin",
        "slug_serm": "besancon",
        "source_macrozonage": "M2",
        "code_macrozone": 3,
    },
]

CLASSES_DISTANCE = ("D1", "D2", "D3", "D4", "D5")
FLUX_LETTRES = ("E", "T", "I")  # Echange, Transit, Interne


# ---------------------------------------------------------------------------
# Helpers chemins / IO
# ---------------------------------------------------------------------------

def _opsam_dir() -> Path:
    """Dossier des sorties OPSAM (variable SERM_OPSAM_DIR sinon defaut NAS)."""
    v = os.environ.get("SERM_OPSAM_DIR")
    if v:
        return Path(v)
    return Path(r"\\poste-2-170\OPSAM_v3\OPSAM\Outputs\Ref2024")


def _data_dir() -> Path:
    """Dossier de sortie du bundle (variable SERM_DATA_DIR sinon ./data)."""
    v = os.environ.get("SERM_DATA_DIR")
    if v:
        return Path(v)
    return Path(__file__).resolve().parents[1] / "data"


def _lire_synthese(chemin: Path, colonne_id: str) -> pd.DataFrame:
    """Lit un fichier de synthese OPSAM (separateur virgule, decimal point)."""
    if not chemin.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}")
    df = pd.read_csv(chemin)
    df.columns = [str(c).strip() for c in df.columns]
    if colonne_id not in df.columns:
        raise ValueError(
            f"Colonne {colonne_id!r} absente de {chemin.name}. "
            f"Colonnes : {list(df.columns)[:10]}..."
        )
    # Normalisation : codes en entier, autres colonnes numeriques.
    df[colonne_id] = pd.to_numeric(df[colonne_id], errors="coerce").astype("Int64")
    for col in df.columns:
        if col in {colonne_id, "CL_ADMIN"}:
            continue
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


# ---------------------------------------------------------------------------
# Calcul VL = Total - PL (par flux et par distance)
# ---------------------------------------------------------------------------

def ajouter_colonnes_vl(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute toutes les colonnes VL_* deduites par soustraction Total - PL.

    Pour chaque flux (Echange E, Transit T, Interne I) on agrege PL = PL_*C + PL_*V
    (chargés + vides) puis on calcule VL = Total - PL, en gardant les valeurs
    a 0 si negatives (effets d'arrondi).
    """
    df = df.copy()

    # Totaux PL agreges (chargés + vides) par flux et par distance.
    for f in FLUX_LETTRES:
        col_c = f"VKM_PL_{f}C"
        col_v = f"VKM_PL_{f}V"
        if col_c in df.columns and col_v in df.columns:
            df[f"VKM_PL_{f}"] = df[col_c].fillna(0) + df[col_v].fillna(0)
        for d in CLASSES_DISTANCE:
            col_c_d = f"VKM_PL_{f}C_{d}"
            col_v_d = f"VKM_PL_{f}V_{d}"
            if col_c_d in df.columns and col_v_d in df.columns:
                df[f"VKM_PL_{f}_{d}"] = (
                    df[col_c_d].fillna(0) + df[col_v_d].fillna(0)
                )

    # VL global = VKM total - VKM_PL total.
    if "VKM" in df.columns and "VKM_PL" in df.columns:
        df["VKM_VL"] = (df["VKM"].fillna(0) - df["VKM_PL"].fillna(0)).clip(lower=0)

    # VL par flux et par classe de distance.
    for f in FLUX_LETTRES:
        col_tv = f"VKM_{f}"
        col_pl = f"VKM_PL_{f}"
        if col_tv in df.columns and col_pl in df.columns:
            df[f"VKM_VL_{f}"] = (
                df[col_tv].fillna(0) - df[col_pl].fillna(0)
            ).clip(lower=0)
        for d in CLASSES_DISTANCE:
            col_tv_d = f"VKM_{f}_{d}"
            col_pl_d = f"VKM_PL_{f}_{d}"
            if col_tv_d in df.columns and col_pl_d in df.columns:
                df[f"VKM_VL_{f}_{d}"] = (
                    df[col_tv_d].fillna(0) - df[col_pl_d].fillna(0)
                ).clip(lower=0)

    return df


# ---------------------------------------------------------------------------
# Fusion m1 + m2 -> referentiel SERM unifie
# ---------------------------------------------------------------------------

def construire_referentiel_serm(
    df_m1: pd.DataFrame,
    df_m2: pd.DataFrame,
    inclure_autre: bool = True,
) -> pd.DataFrame:
    """Construit la table unifiee SERM x CL_ADMIN avec colonnes VL + PL."""
    blocs: list[pd.DataFrame] = []

    for entree in SERM_REFERENTIEL:
        source = df_m1 if entree["source_macrozonage"] == "M1" else df_m2
        colonne_id = entree["source_macrozonage"]
        sous_df = source[source[colonne_id] == entree["code_macrozone"]].copy()
        if sous_df.empty:
            LOG.warning(
                "Aucune ligne pour SERM %s (%s = %s).",
                entree["nom_serm"],
                colonne_id,
                entree["code_macrozone"],
            )
            continue
        sous_df.insert(0, "code_serm", entree["code_serm"])
        sous_df.insert(1, "nom_serm", entree["nom_serm"])
        sous_df.insert(2, "slug_serm", entree["slug_serm"])
        sous_df.insert(3, "source_macrozonage", entree["source_macrozonage"])
        sous_df.insert(4, "code_macrozone", entree["code_macrozone"])
        blocs.append(sous_df)

    if inclure_autre:
        # Ligne "Reste BFC" vue depuis M1 (par defaut, evite la double-comptabilite).
        autre = df_m1[df_m1["M1"] == 0].copy()
        if not autre.empty:
            autre.insert(0, "code_serm", 0)
            autre.insert(1, "nom_serm", "Reste BFC (hors SERM)")
            autre.insert(2, "slug_serm", "reste_bfc")
            autre.insert(3, "source_macrozonage", "M1")
            autre.insert(4, "code_macrozone", 0)
            blocs.append(autre)

    if not blocs:
        raise RuntimeError("Aucune ligne SERM trouvee dans les fichiers de synthese.")

    df = pd.concat(blocs, ignore_index=True, sort=False)
    # On ne garde pas les colonnes id macrozones brutes (M1, M2) qui sont redondantes.
    df = df.drop(columns=[c for c in ("M1", "M2") if c in df.columns])
    return df


# ---------------------------------------------------------------------------
# Verifications de coherence
# ---------------------------------------------------------------------------

def verifier_coherence_vl_pl(df: pd.DataFrame) -> dict:
    """Verifications simples : VKM = VL + PL +- arrondis."""
    rapport: dict = {}
    for cle, attendue, pl_col, vl_col in (
        ("global", "VKM", "VKM_PL", "VKM_VL"),
        ("echange", "VKM_E", "VKM_PL_E", "VKM_VL_E"),
        ("transit", "VKM_T", "VKM_PL_T", "VKM_VL_T"),
        ("interne", "VKM_I", "VKM_PL_I", "VKM_VL_I"),
    ):
        if all(c in df.columns for c in (attendue, pl_col, vl_col)):
            ecart = (df[attendue] - (df[pl_col] + df[vl_col])).abs()
            rapport[cle] = {
                "ecart_max_kmj": float(ecart.max()),
                "ecart_relatif_pct": float(
                    100 * ecart.sum() / max(df[attendue].sum(), 1)
                ),
            }
    return rapport


# ---------------------------------------------------------------------------
# Point d'entree CLI
# ---------------------------------------------------------------------------

def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--opsam-dir",
        type=Path,
        default=None,
        help="Dossier des sorties OPSAM (sinon variable SERM_OPSAM_DIR).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Dossier de sortie du bundle (sinon variable SERM_DATA_DIR ou ./data).",
    )
    parser.add_argument(
        "--scenario",
        default="Ref2024",
        help="Identifiant de scenario OPSAM (defaut : Ref2024).",
    )
    parser.add_argument(
        "--sans-autre",
        action="store_true",
        help="N'inclut pas la ligne Reste BFC (M1=0).",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Logs detailles."
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    opsam = args.opsam_dir or _opsam_dir()
    data = args.data_dir or _data_dir()
    data.mkdir(parents=True, exist_ok=True)

    fichier_m1 = opsam / f"synthese_m1_{args.scenario}.csv"
    fichier_m2 = opsam / f"synthese_m2_{args.scenario}.csv"
    LOG.info("Lecture %s", fichier_m1)
    df_m1 = _lire_synthese(fichier_m1, "M1")
    LOG.info("Lecture %s", fichier_m2)
    df_m2 = _lire_synthese(fichier_m2, "M2")

    LOG.info("Calcul VL = Total - PL pour M1 (%d lignes)", len(df_m1))
    df_m1 = ajouter_colonnes_vl(df_m1)
    LOG.info("Calcul VL = Total - PL pour M2 (%d lignes)", len(df_m2))
    df_m2 = ajouter_colonnes_vl(df_m2)

    LOG.info("Construction du referentiel SERM unifie")
    df_serm = construire_referentiel_serm(
        df_m1, df_m2, inclure_autre=not args.sans_autre
    )

    rapport = verifier_coherence_vl_pl(df_serm)
    LOG.info("Coherence VKM = VL + PL : %s", rapport)

    chemin_sortie = data / "synthese_serm_vl_pl.csv"
    df_serm.to_csv(chemin_sortie, index=False, sep=";", encoding="utf-8-sig")
    LOG.info(
        "Ecrit %s (%d lignes, %d colonnes)",
        chemin_sortie,
        len(df_serm),
        df_serm.shape[1],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
