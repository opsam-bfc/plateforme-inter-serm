"""export_livrables_par_serm.py.

Exporte hors plateforme l'ensemble des productions du bundle ``data/``
organisees par SERM (et un dossier inter-SERM), avec une note explicative
pour chaque fichier livre.

Usage :
    python scripts/export_livrables_par_serm.py
    python scripts/export_livrables_par_serm.py --out-dir D:/exports/SERM
    python scripts/export_livrables_par_serm.py --zip

Sortie par defaut (si non precisee) :
    ../../4_OUTPUT/LIVRABLES_SERM_Ref2024/
    ou ./EXPORT_LIVRABLES/ a la racine du projet.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
import pandas as pd

# Racine projet (pour data_loader)
RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from data_loader import (  # noqa: E402
    SERM_INFO,
    calculer_metriques_serm,
    charger_echanges_epci,
    charger_matrice_inter_serm,
    charger_perimetres_serm,
    charger_synthese_serm,
    charger_top_od_communes,
    data_dir,
    enrichir_noms_epci_flux_od,
)

LOG = logging.getLogger("export_livrables")

SCENARIO = "Ref2024"
SOURCES_OPSAM = (
    "Scenario OPSAM : Ref2024\n"
    "Synthese macrozones : synthese_m1_Ref2024.csv, synthese_m2_Ref2024.csv\n"
    "Matrice OD VL : matrice_vl_Ref2024.csv\n"
    "Reseau : reseau_detaille_linkshape_Ref2024.shp (TMJA_P, PL_P)\n"
    "Zonage : zonage_OPSAM_poly.shp + lookup_dep_com_epci_macrozone.csv\n"
    "Deduction VL : VKM_VL = VKM - VKM_PL (charges + vides)\n"
)

# Fiches descriptives des types de livrables (note explicative)
FICHES: dict[str, dict[str, str]] = {
    "synthese": {
        "titre": "Synthese VKM par type de voie, flux et distance",
        "action": "Action 1 — Socle de connaissance",
        "description": (
            "Table issue des macrozones OPSAM (M1/M2) reaffectees aux "
            "trois SERM. Contient les VKM totaux, PL et VL reconstitues "
            "par flux (Echange E, Transit T, Interne I) et par classe "
            "de distance (D1 a D5), ventiles par type d'infrastructure "
            "(Autoroute, Nationale, Departementale, locales)."
        ),
        "colonnes_cles": (
            "code_serm, nom_serm, CL_ADMIN, VKM, VKM_VL, VKM_PL, "
            "VKM_E/T/I, VKM_VL_* , VKM_PL_* , DISTANCE"
        ),
        "usage": (
            "KPI territoriaux, Sankey, profils distance, comparaisons "
            "inter-SERM dans la plateforme et rapports PDF."
        ),
    },
    "kpi": {
        "titre": "Indicateurs synthetiques par SERM",
        "action": "Action 1 — Socle de connaissance",
        "description": (
            "Agregation des VKM et parts modales (% transit, echange, "
            "interne, longue distance) calculee a partir de la synthese."
        ),
        "colonnes_cles": "nom_serm, VKM_VL_milliers, pct_transit, pct_echange, pct_interne",
        "usage": "Tableaux de bord, fiches SERM, communication DREAL.",
    },
    "perimetre": {
        "titre": "Perimetre geographique du SERM",
        "action": "Action 1 — Socle de connaissance",
        "description": (
            "Multipolygone du SERM (dissolution des zones OPSAM du lookup), "
            "simplifie et reprojete en WGS84 (EPSG:4326)."
        ),
        "colonnes_cles": "code_serm, nom_serm, geometry",
        "usage": "Cartes choropleth, decoupage spatial, fond de carte.",
    },
    "reseau": {
        "titre": "Reseau routier classe intersecte avec le SERM",
        "action": "Action 1 — Socle de connaissance",
        "description": (
            "Troncons Autoroute / Nationale / Departementale du reseau "
            "detaille OPSAM situes dans le SERM. TMJA_P (tous vehicules), "
            "PL_P et VL_jour = TMJA_P - PL_P."
        ),
        "colonnes_cles": "CL_ADMIN, TMJA_P, PL_P, VL_jour, geometry",
        "usage": "Cartographie du trafic par SERM (carte TMJA / VL).",
    },
    "limites_communes": {
        "titre": "Limites communales du SERM",
        "action": "Action 2 — Corridors",
        "description": (
            "Communes couvertes par le SERM (zones OPSAM dissoutes par "
            "code INSEE), avec nom de commune et code EPCI."
        ),
        "colonnes_cles": "INSEE_COM, NOM_COM, EPCI, code_serm, geometry",
        "usage": "Fond de carte des flux internes commune a commune.",
    },
    "top_interne": {
        "titre": "Top flux VL internes (commune x commune)",
        "action": "Action 2 — Corridors",
        "description": (
            "Principaux deplacements VL dont origine et destination sont "
            "dans le meme SERM, agreges a la commune (zones IRIS regroupees). "
            "Hors deplacements intra-commune."
        ),
        "colonnes_cles": "nom_O, nom_D, volume (VL/j), com_O, com_D",
        "usage": "Cartes de flux (arcs), identification des corridors internes.",
    },
    "top_emis": {
        "titre": "Top flux VL emis vers EPCI exterieurs",
        "action": "Action 2 — Corridors",
        "description": (
            "Flux partant d'une commune du SERM vers un EPCI hors SERM "
            "(EPCI code 0 exclu). Libelles : nom commune origine, nom EPCI "
            "destination."
        ),
        "colonnes_cles": "nom_O, nom_D (EPCI), volume (VL/j)",
        "usage": "Cartes de desir emis, analyse peri-urbain / attracteurs.",
    },
    "top_recus": {
        "titre": "Top flux VL recus depuis EPCI exterieurs",
        "action": "Action 2 — Corridors",
        "description": (
            "Flux arrivant dans une commune du SERM depuis un EPCI hors "
            "SERM (EPCI code 0 exclu)."
        ),
        "colonnes_cles": "nom_O (EPCI), nom_D, volume (VL/j)",
        "usage": "Cartes de desir recus, flux pendulaires entrants.",
    },
    "echanges_internes_epci": {
        "titre": "Echanges VL entre EPCI au sein du SERM",
        "action": "Action 2 — Echanges EPCI",
        "description": (
            "Matrice agregée EPCI origine x EPCI destination pour les "
            "deplacements dont origine et destination sont dans le meme SERM."
        ),
        "colonnes_cles": "epci_O_nom, epci_D_nom, volume (VL/j)",
        "usage": "Heatmap EPCI x EPCI, hierarchie des mobilities internes.",
    },
    "echanges_hors_serm": {
        "titre": "Echanges VL avec EPCI hors SERM",
        "action": "Action 2 — Echanges EPCI",
        "description": (
            "Flux entre un EPCI du SERM et un EPCI situe hors du SERM "
            "(perimetre exterieur BFC ou autre SERM)."
        ),
        "colonnes_cles": "epci_O_nom, epci_D_nom, volume (VL/j)",
        "usage": "Heatmap echanges peripheriques, attractivite territoriale.",
    },
    "matrice_inter_serm": {
        "titre": "Matrice OD VL entre SERM (4 x 4)",
        "action": "Inter-SERM",
        "description": (
            "Volumes VL/jour entre les trois SERM et le reste BFC "
            "(hors perimetres SERM), agreges depuis la matrice OD OPSAM."
        ),
        "colonnes_cles": "serm_O_nom, serm_D_nom, volume",
        "usage": "Heatmap inter-SERM, comparaison des attractivites.",
    },
    "limites_epci": {
        "titre": "Limites EPCI (referentiel lookup BFC)",
        "action": "Inter-SERM / contexte",
        "description": (
            "Perimetres des EPCI presents dans le lookup OPSAM de la "
            "mission, avec code SIREN et nom officiel."
        ),
        "colonnes_cles": "CODE_SIREN, NOM, code_serm, geometry",
        "usage": "Fond de carte des echanges EPCI, jointures attributaires.",
    },
}


def _export_dir_defaut() -> Path:
    v = os.environ.get("SERM_EXPORT_DIR")
    if v:
        return Path(v)
    candidats = (
        RACINE.parent.parent.parent / "4_OUTPUT" / f"LIVRABLES_SERM_{SCENARIO}",
        RACINE.parent.parent / "4_OUTPUT" / f"LIVRABLES_SERM_{SCENARIO}",
    )
    for cand in candidats:
        if cand.parent.exists():
            return cand
    return RACINE / "EXPORT_LIVRABLES"


def _ecrire_note_fiche(chemin: Path, cle_fiche: str, fichier_nom: str) -> None:
    """Ecrit une mini-note Markdown pour un fichier produit."""
    f = FICHES[cle_fiche]
    contenu = (
        f"# {f['titre']}\n\n"
        f"**Fichier :** `{fichier_nom}`  \n"
        f"**Action mission :** {f['action']}  \n"
        f"**Scenario :** {SCENARIO}\n\n"
        f"## Description\n\n{f['description']}\n\n"
        f"## Colonnes principales\n\n{f['colonnes_cles']}\n\n"
        f"## Usage\n\n{f['usage']}\n\n"
        f"---\n"
        f"*Genere par `scripts/export_livrables_par_serm.py` — "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*\n"
    )
    chemin.write_text(contenu, encoding="utf-8")


def _csv(df: pd.DataFrame, chemin: Path) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(chemin, index=False, sep=";", encoding="utf-8-sig", decimal=".")


def _copier_si_existe(src: Path, dst: Path) -> bool:
    if not src.is_file():
        LOG.warning("Fichier absent, ignore : %s", src)
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _extraire_perimetre_serm(code: int, dst: Path) -> bool:
    try:
        gdf = charger_perimetres_serm()
        sous = gdf[gdf["code_serm"] == code]
        if sous.empty:
            return False
        sous.to_file(dst, driver="GeoJSON")
        return True
    except Exception as exc:
        LOG.warning("Perimetre SERM %d : %s", code, exc)
        return False


def _manifest_ligne(
    rel: str, serm: str, cle: str, chemin: Path,
) -> dict[str, Any]:
    fiche = FICHES.get(cle, {})
    return {
        "fichier": rel,
        "serm": serm,
        "action": fiche.get("action", ""),
        "titre": fiche.get("titre", ""),
        "taille_ko": round(chemin.stat().st_size / 1024, 1) if chemin.is_file() else 0,
    }


def exporter_serm(
    code: int,
    info: dict,
    data: Path,
    racine_out: Path,
    manifest: list[dict],
) -> None:
    """Exporte tous les livrables d'un SERM."""
    slug = info["slug"]
    nom = info["nom"]
    dossier = racine_out / f"SERM_{code:02d}_{slug}"
    d_socle = dossier / "01_socle_connaissance"
    d_corridors = dossier / "02_corridors_top_flux_OD"
    d_epci = dossier / "03_echanges_EPCI"

    # --- Socle : synthese filtree ---
    try:
        df_syn = charger_synthese_serm()
        syn_serm = df_syn[df_syn["code_serm"] == code]
        f_syn = d_socle / f"synthese_VL_PL_{slug}.csv"
        _csv(syn_serm, f_syn)
        _ecrire_note_fiche(d_socle / "NOTE_synthese.md", "synthese", f_syn.name)
        manifest.append(_manifest_ligne(
            str(f_syn.relative_to(racine_out)), nom, "synthese", f_syn,
        ))
    except Exception as exc:
        LOG.error("Synthese SERM %d : %s", code, exc)

    # --- KPI ---
    try:
        metr = calculer_metriques_serm(charger_synthese_serm())
        kpi = metr[metr["code_serm"] == code]
        f_kpi = d_socle / f"KPI_agreges_{slug}.csv"
        _csv(kpi, f_kpi)
        _ecrire_note_fiche(d_socle / "NOTE_KPI.md", "kpi", f_kpi.name)
        manifest.append(_manifest_ligne(
            str(f_kpi.relative_to(racine_out)), nom, "kpi", f_kpi,
        ))
    except Exception as exc:
        LOG.error("KPI SERM %d : %s", code, exc)

    # --- Perimetre ---
    f_peri = d_socle / f"perimetre_{slug}.geojson"
    if _extraire_perimetre_serm(code, f_peri):
        _ecrire_note_fiche(d_socle / "NOTE_perimetre.md", "perimetre", f_peri.name)
        manifest.append(_manifest_ligne(
            str(f_peri.relative_to(racine_out)), nom, "perimetre", f_peri,
        ))

    # --- Reseau GPKG ---
    f_res = data / "reseau_serm" / f"{slug}.gpkg"
    dst_res = d_socle / f"reseau_routier_{slug}.gpkg"
    if _copier_si_existe(f_res, dst_res):
        _ecrire_note_fiche(d_socle / "NOTE_reseau.md", "reseau", dst_res.name)
        manifest.append(_manifest_ligne(
            str(dst_res.relative_to(racine_out)), nom, "reseau", dst_res,
        ))

    # --- Limites communes ---
    f_com = data / f"limites_communes_serm{code}.geojson"
    dst_com = d_socle / f"limites_communes_{slug}.geojson"
    if _copier_si_existe(f_com, dst_com):
        _ecrire_note_fiche(
            d_socle / "NOTE_limites_communes.md", "limites_communes", dst_com.name,
        )
        manifest.append(_manifest_ligne(
            str(dst_com.relative_to(racine_out)), nom, "limites_communes", dst_com,
        ))

    # --- Corridors : top OD ---
    try:
        top = enrichir_noms_epci_flux_od(charger_top_od_communes())
        top_s = top[top["serm"] == code]
        mapping = (
            ("interne_serm", "top_interne", f"top_flux_internes_communes_{slug}.csv"),
            ("echange_emis", "top_emis", f"top_flux_emis_vers_EPCI_{slug}.csv"),
            ("echange_recus", "top_recus", f"top_flux_recus_depuis_EPCI_{slug}.csv"),
        )
        for typo, cle, nom_f in mapping:
            sous = top_s[top_s["typologie"] == typo].copy()
            if sous.empty:
                continue
            cols = [c for c in sous.columns if c in (
                "nom_serm", "typologie", "nom_O", "nom_D",
                "com_O", "com_D", "volume",
            )]
            path = d_corridors / nom_f
            _csv(sous[cols], path)
            _ecrire_note_fiche(d_corridors / f"NOTE_{cle}.md", cle, nom_f)
            manifest.append(_manifest_ligne(
                str(path.relative_to(racine_out)), nom, cle, path,
            ))
    except Exception as exc:
        LOG.error("Top OD SERM %d : %s", code, exc)

    # --- Echanges EPCI ---
    try:
        ech = charger_echanges_epci()
        ech_s = ech[ech["serm"] == code]
        for typo, cle, nom_f in (
            ("interne_serm", "echanges_internes_epci",
             f"echanges_internes_EPCI_{slug}.csv"),
            ("echange_serm", "echanges_hors_serm",
             f"echanges_avec_hors_SERM_EPCI_{slug}.csv"),
        ):
            sous = ech_s[ech_s["typologie"] == typo].copy()
            if sous.empty:
                continue
            cols_pref = [
                "nom_serm", "typologie", "epci_O", "epci_O_nom",
                "epci_D", "epci_D_nom", "volume",
            ]
            cols = [c for c in cols_pref if c in sous.columns]
            path = d_epci / nom_f
            _csv(sous[cols], path)
            _ecrire_note_fiche(d_epci / f"NOTE_{cle}.md", cle, nom_f)
            manifest.append(_manifest_ligne(
                str(path.relative_to(racine_out)), nom, cle, path,
            ))
    except Exception as exc:
        LOG.error("Echanges EPCI SERM %d : %s", code, exc)

    # --- Note explicative globale du SERM ---
    note_serm = (
        f"# Livrables — {nom}\n\n"
        f"**Code SERM :** {code}  \n"
        f"**Slug :** `{slug}`  \n"
        f"**Scenario OPSAM :** {SCENARIO}\n\n"
        f"## Structure du dossier\n\n"
        f"| Dossier | Contenu |\n"
        f"|---------|--------|\n"
        f"| `01_socle_connaissance/` | Synthese VKM/VL/PL, KPI, perimetre, "
        f"reseau, communes |\n"
        f"| `02_corridors_top_flux_OD/` | Top flux internes, emis, recus "
        f"(communes / EPCI) |\n"
        f"| `03_echanges_EPCI/` | Matrices d'echanges entre EPCI |\n\n"
        f"Chaque sous-dossier contient des fichiers `NOTE_*.md` decrivant "
        f"la production associee.\n\n"
        f"## Sources\n\n{SOURCES_OPSAM}\n"
    )
    (dossier / "NOTE_EXPLICATIVE_SERM.md").write_text(
        note_serm, encoding="utf-8",
    )


def exporter_inter_serm(
    data: Path, racine_out: Path, manifest: list[dict],
) -> None:
    """Exporte les livrables communs aux trois SERM."""
    dossier = racine_out / "00_INTER_SERM"
    dossier.mkdir(parents=True, exist_ok=True)

    f_mat = dossier / "matrice_OD_inter_SERM_VL.csv"
    try:
        _csv(charger_matrice_inter_serm(), f_mat)
        _ecrire_note_fiche(dossier / "NOTE_matrice_inter_SERM.md", "matrice_inter_serm", f_mat.name)
        manifest.append(_manifest_ligne(
            str(f_mat.relative_to(racine_out)), "Inter-SERM", "matrice_inter_serm", f_mat,
        ))
    except Exception as exc:
        LOG.error("Matrice inter-SERM : %s", exc)

    f_peri = dossier / "perimetres_3_SERM.geojson"
    try:
        charger_perimetres_serm().to_file(f_peri, driver="GeoJSON")
        _ecrire_note_fiche(dossier / "NOTE_perimetres.md", "perimetre", f_peri.name)
        manifest.append(_manifest_ligne(
            str(f_peri.relative_to(racine_out)), "Inter-SERM", "perimetre", f_peri,
        ))
    except Exception as exc:
        LOG.error("Perimetres : %s", exc)

    f_epci = dossier / "limites_EPCI_referentiel.geojson"
    src_epci = data / "limites_epci.geojson"
    if _copier_si_existe(src_epci, f_epci):
        _ecrire_note_fiche(dossier / "NOTE_limites_EPCI.md", "limites_epci", f_epci.name)
        manifest.append(_manifest_ligne(
            str(f_epci.relative_to(racine_out)), "Inter-SERM", "limites_epci", f_epci,
        ))

    try:
        _csv(charger_synthese_serm(), dossier / "synthese_4_zones_incluant_reste_BFC.csv")
    except Exception as exc:
        LOG.error("Synthese complete : %s", exc)

    (dossier / "SOURCES_OPSAM.txt").write_text(SOURCES_OPSAM, encoding="utf-8")

    note = (
        "# Livrables inter-SERM\n\n"
        "Fichiers couvrant les trois perimetres SERM et le reste de la region "
        "BFC (zone hors SERM, code 0).\n\n"
        "Voir les notes `NOTE_*.md` pour le detail de chaque fichier.\n"
    )
    (dossier / "NOTE_EXPLICATIVE_INTER_SERM.md").write_text(note, encoding="utf-8")


def _note_globale(racine_out: Path, manifest: list[dict]) -> None:
    """README a la racine de l'export."""
    lignes_table = "\n".join(
        f"| {m['serm']} | `{m['fichier']}` | {m['action']} | {m['titre']} | "
        f"{m['taille_ko']} |"
        for m in sorted(manifest, key=lambda x: (x["serm"], x["fichier"]))
    )
    readme = (
        f"# Export livrables SERM — {SCENARIO}\n\n"
        f"**Date :** {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
        "## Organisation\n\n"
        "- `00_INTER_SERM/` — productions communes (matrice 4x4, perimetres, "
        "EPCI referentiel)\n"
        "- `SERM_01_dijon/`, `SERM_02_nfc/`, `SERM_03_besancon/` — un dossier "
        "par territoire porteur de SERM\n\n"
        "Dans chaque dossier SERM :\n"
        "1. `01_socle_connaissance/` — Action 1 (VKM, reseau, perimetre)\n"
        "2. `02_corridors_top_flux_OD/` — Action 2 (top flux VL)\n"
        "3. `03_echanges_EPCI/` — Action 2 (echanges entre EPCI)\n\n"
        "## Catalogue des fichiers\n\n"
        "| SERM | Fichier | Action | Description | Taille (ko) |\n"
        "|------|---------|--------|-------------|-------------|\n"
        f"{lignes_table}\n\n"
        "## Regeneration\n\n"
        "```bash\n"
        "python scripts/rebuild_for_new_perimeter.py -v\n"
        "python scripts/prepare_limites.py -v\n"
        "python scripts/export_livrables_par_serm.py -v\n"
        "```\n\n"
        f"{SOURCES_OPSAM}\n"
    )
    (racine_out / "README.md").write_text(readme, encoding="utf-8")
    pd.DataFrame(manifest).to_csv(
        racine_out / "CATALOGUE_LIVRABLES.csv",
        index=False, sep=";", encoding="utf-8-sig",
    )


def _zipper(racine_out: Path) -> Path:
    zip_path = racine_out.parent / f"{racine_out.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in racine_out.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(racine_out.parent))
    return zip_path


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument(
        "--zip", action="store_true",
        help="Cree aussi une archive ZIP du dossier d'export.",
    )
    parser.add_argument(
        "--effacer", action="store_true",
        help="Supprime le dossier de sortie s'il existe deja.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s | %(message)s",
    )

    if args.data_dir:
        os.environ["SERM_DATA_DIR"] = str(args.data_dir)
    data = data_dir()
    racine_out = args.out_dir or _export_dir_defaut()

    if racine_out.exists() and args.effacer:
        shutil.rmtree(racine_out)
    racine_out.mkdir(parents=True, exist_ok=True)

    manifest: list[dict] = []

    exporter_inter_serm(data, racine_out, manifest)
    for code in (1, 2, 3):
        exporter_serm(code, SERM_INFO[code], data, racine_out, manifest)

    _note_globale(racine_out, manifest)

    meta = {
        "scenario": SCENARIO,
        "date_export": datetime.now(timezone.utc).isoformat(),
        "nb_fichiers": len(manifest),
        "dossier": str(racine_out),
    }
    (racine_out / "metadata_export.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8",
    )

    LOG.info("Export termine : %s (%d fichiers)", racine_out, len(manifest))

    if args.zip:
        zp = _zipper(racine_out)
        LOG.info("Archive : %s", zp)

    return 0


if __name__ == "__main__":
    sys.exit(main())
