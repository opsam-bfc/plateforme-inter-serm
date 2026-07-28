"""rebuild_for_new_perimeter.py.

Orchestre la regeneration complete du bundle ``data/{scenario}/`` apres une
evolution des perimetres SERM (par exemple modification du lookup
``lookup_dep_com_epci_macrozone.csv``).

Etapes enchainees :

1. ``prepare_synthese_serm`` (synthese OPSAM m1 + m2, deduction VL) ;
2. ``prepare_perimetres_serm`` (dissolution polygones par SERM) ;
3. ``prepare_reseau_serm`` (intersection reseau routier / SERM) ;
4. ``prepare_od_vl`` (agregation matrice OD VL).
5. ``prepare_limites`` (limites communes / EPCI).

Chaque etape lit ses propres variables d'environnement (``SERM_*``) et
les options ``--scenario`` / ``--data-dir`` transmises ici.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Callable

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
sys.path.insert(0, str(ICI))
sys.path.insert(0, str(RACINE))

from prepare_synthese_serm import main as etape_synthese  # noqa: E402
from prepare_perimetres_serm import main as etape_perimetres  # noqa: E402
from prepare_reseau_serm import main as etape_reseau  # noqa: E402
from prepare_od_vl import main as etape_od  # noqa: E402
from prepare_limites import main as etape_limites  # noqa: E402
from export_livrables_par_serm import main as etape_export  # noqa: E402

LOG = logging.getLogger("rebuild_for_new_perimeter")


ETAPES: list[tuple[str, Callable]] = [
    ("Synthese SERM (VL = Total - PL)", etape_synthese),
    ("Perimetres SERM (geojson)", etape_perimetres),
    ("Reseau routier par SERM (GPKG)", etape_reseau),
    ("Matrice OD VL (top flux, inter-SERM, EPCI)", etape_od),
    ("Limites communes et EPCI (geojson)", etape_limites),
]


def _appliquer_chemins_scenario(scenario: str, data_dir: Path) -> None:
    """Configure env SERM_* d'après config/territoire.yaml pour le scénario."""
    try:
        from config.territoire_loader import chemins_pour_scenario
        ch = chemins_pour_scenario(scenario)
    except Exception as exc:
        LOG.warning("Impossible de charger les chemins scénario : %s", exc)
        return

    os.environ["SERM_DATA_DIR"] = str(data_dir)
    os.environ["SERM_SCENARIO"] = scenario
    if ch.opsam_outputs:
        os.environ["SERM_OPSAM_DIR"] = ch.opsam_outputs
    if ch.opsam_base:
        os.environ["SERM_OPSAM_BASE_DIR"] = ch.opsam_base
    if ch.lookup_csv:
        os.environ.setdefault("SERM_LOOKUP_CSV", ch.lookup_csv)
    if ch.zonage_shp:
        os.environ.setdefault("SERM_ZONAGE_SHP", ch.zonage_shp)
    if ch.epci_shp:
        os.environ.setdefault("SERM_EPCI_SHP", ch.epci_shp)
    if ch.reseau_shp:
        os.environ["SERM_RESEAU_SHP"] = ch.reseau_shp
    if ch.matrice_vl_csv:
        # Chemin relatif au dossier Outputs si ce n'est pas absolu
        mat = Path(ch.matrice_vl_csv)
        if not mat.is_absolute():
            mat = Path(ch.opsam_outputs) / mat
        os.environ["SERM_MATRICE_VL_CSV"] = str(mat)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        default=None,
        help="Identifiant de scénario OPSAM (ex. Ref2024, sc2033).",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Dossier de sortie du bundle (défaut : data/{scenario}).",
    )
    parser.add_argument(
        "--ignorer", nargs="*", default=[],
        help="Etapes a ignorer (ex. : synthese, perimetres, reseau, od).",
    )
    parser.add_argument(
        "--export", action="store_true",
        help="Apres le rebuild, lance export_livrables_par_serm.py.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    scenario = args.scenario or os.environ.get("SERM_SCENARIO") or "Ref2024"
    data_dir = args.data_dir or (RACINE / "data" / scenario)
    data_dir = data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    _appliquer_chemins_scenario(scenario, data_dir)
    LOG.info("Scénario=%s | data-dir=%s", scenario, data_dir)

    mapping_short = {
        "synthese": etape_synthese,
        "perimetres": etape_perimetres,
        "reseau": etape_reseau,
        "od": etape_od,
        "limites": etape_limites,
    }
    ignorer = {mapping_short[k] for k in args.ignorer if k in mapping_short}

    extras: dict[Callable, list[str]] = {
        etape_synthese: ["--scenario", scenario, "--data-dir", str(data_dir)],
        etape_perimetres: ["--data-dir", str(data_dir)],
        etape_reseau: ["--data-dir", str(data_dir)],
        etape_od: ["--data-dir", str(data_dir)],
        etape_limites: ["--data-dir", str(data_dir)],
    }

    debut = time.time()
    for libelle, etape in ETAPES:
        if etape in ignorer:
            LOG.info("[SKIP] %s", libelle)
            continue
        LOG.info("[START] %s", libelle)
        t0 = time.time()
        argv_etape = list(extras.get(etape, []))
        if args.verbose:
            argv_etape.append("-v")
        code = etape(argv_etape)
        if code != 0:
            LOG.error("[FAIL ] %s (code %d)", libelle, code)
            return code
        LOG.info(
            "[OK   ] %s en %.1f s", libelle, time.time() - t0
        )

    LOG.info("Bundle %s regenere en %.1f s.", scenario, time.time() - debut)

    if args.export:
        LOG.info("[START] Export livrables par SERM")
        code_exp = etape_export(
            ["-v", "--effacer", "--data-dir", str(data_dir)]
        )
        if code_exp != 0:
            LOG.error("[FAIL ] Export livrables (code %d)", code_exp)
            return code_exp

    return 0


if __name__ == "__main__":
    sys.exit(main())
