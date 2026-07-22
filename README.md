# Plateforme d'analyse inter-SERM (OPSAM Ref2024)

Plateforme **Streamlit** d'analyse inter-SERM (Dijon, Nord Franche-Comte, Besancon)
pour la DREAL Bourgogne-Franche-Comte, calquee sur l'application
`MACROZONE` existante.

Elle exploite les sorties OPSAM Ref2024 (CSV de synthese par macrozone,
matrice OD VL/PL, reseau routier) en reconstituant les volumes VL par
deduction (`Total - PL_charges - PL_vides`).

## Perimetre V1

- **Action 1 - Socle de connaissance** : KPI, cartes de trafic VL/PL par
  troncon clipe au SERM, diagrammes de Sankey VL/PL par infrastructure et
  par flux Echange / Transit / Interne, profils par classes de distance.
- **Action 2 - Corridors a enjeux** : top flux OD VL internes au SERM,
  lignes de desir, flux inter-SERM et echanges centre / peripherie via les
  EPCI.
- **Hors V1** : bilan energetique OPTEER, simulation de scenarios CUBE,
  gouvernance.

## Periodes SERM (lookup courant)

- `M1 = 1` -> SERM Dijonnais (891 zones, 20 EPCI)
- `M1 = 2` -> SERM Nord Franche-Comte (263 zones, 6 EPCI)
- `M2 = 3` -> SERM Bisontin (732 zones, 16 EPCI)

Les perimetres ne sont pas figes : le pipeline de precalcul accepte un
nouveau `lookup_dep_com_epci_macrozone.csv` pour regenerer le bundle
`data/`.

## Arborescence

```
plateforme_analyse_inter_SERM/
|-- app.py                       # Streamlit multipage
|-- data_loader.py               # Chargement bundle data/
|-- visualizations.py            # Cartes, Sankey, donuts, lignes de desir
|-- pdf_export.py                # Rapports PDF
|-- style.css                    # Theme
|-- requirements.txt
|-- runtime.txt
|-- .streamlit/
|   |-- config.toml
|   `-- secrets.toml.example
|-- scripts/                     # Precalculs hors app (executes a part)
|   |-- prepare_synthese_serm.py
|   |-- prepare_perimetres_serm.py
|   |-- prepare_reseau_serm.py
|   |-- prepare_od_vl.py
|   |-- prepare_lookup_epci.py
|   `-- rebuild_for_new_perimeter.py
`-- data/                        # Bundle leger (sortie des scripts)
    |-- synthese_serm_vl_pl.csv
    |-- perimetres_serm.geojson
    |-- reseau_serm/{dijon,nfc,besancon}.gpkg
    |-- top_od_vl_par_serm.parquet
    |-- matrice_inter_serm.csv
    |-- echanges_epci_serm.parquet
    `-- lookup_serm_actuel.csv
```

## Installation locale

Python **3.11** (aligne sur `runtime.txt`).

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Pipeline de precalcul (a executer hors application)

Les scripts du dossier `scripts/` lisent les sorties OPSAM (chemins
configurables par variables d'environnement, voir ci-dessous) et
ecrivent le bundle `data/`.

```bash
python scripts/rebuild_for_new_perimeter.py
```

Le script orchestrateur enchaine :

1. `prepare_synthese_serm.py` (CSV synthese m1/m2 + deduction VL)
2. `prepare_perimetres_serm.py` (dissolution polygones SERM)
3. `prepare_reseau_serm.py` (intersection reseau / SERM)
4. `prepare_od_vl.py` (agregats matrice OD VL)

## Variables d'environnement

| Variable                | Defaut                                                                                                                | Role                                  |
|-------------------------|------------------------------------------------------------------------------------------------------------------------|---------------------------------------|
| `SERM_DATA_DIR`         | `./data`                                                                                                              | Dossier du bundle precalcule          |
| `SERM_OPSAM_DIR`        | `\\poste-2-170\OPSAM_v3\OPSAM\Outputs\Ref2024`                                                                        | Dossier des sorties OPSAM             |
| `SERM_LOOKUP_CSV`       | `\\nas-bfc\COMMUN\21_MOBILITE\21.4_PROJETS\DREAL\2026_SERM\2_INPUT\DATA\lookupfile_serm\lookup_dep_com_epci_macrozone.csv` | Lookup ID_ZONAGE -> M1/M2/EPCI/COM    |
| `SERM_ZONAGE_SHP`       | `\\nas-bfc\COMMUN\21_MOBILITE\21.2_COMMUN\DATA\ZONAGE_OPSAM\zonage_OPSAM_poly.shp`                                    | Shapefile des zones OPSAM             |
| `SERM_EPCI_SHP`         | `\\nas-bfc\COMMUN\21_MOBILITE\21.2_COMMUN\DATA\EPCI\EPCI_2025.shp`                                                    | Couche EPCI nationale (IGN)           |
| `SERM_RESEAU_SHP`       | `<SERM_OPSAM_DIR>\reseau_final_Ref2024.shp`                                                                           | Reseau OPSAM (TMJA, PL_P_TMJA)        |
| `SERM_MATRICE_VL_CSV`   | `<SERM_OPSAM_DIR>\matrice_vl_Ref2024.csv`                                                                             | Matrice OD VL (O, D, volume)          |
| `MAPBOX_TOKEN`          | -                                                                                                                     | Jeton public Mapbox (optionnel)       |

## Lancement de l'application

```bash
streamlit run app.py
```

## Sources de donnees

- Synthese par macrozone : `synthese_m1_Ref2024.csv`, `synthese_m2_Ref2024.csv`
- Matrices OD : `matrice_vl_Ref2024.csv`, `matrice_pl_Ref2024.csv`
- Reseau routier OPSAM : `reseau_final_Ref2024.shp`
- Zonage OPSAM : `zonage_OPSAM_poly.shp` (avec colonnes `SERM_dijon`,
  `SERM_NFC`, `SERM_besan`)
- Lookup macrozone : `lookup_dep_com_epci_macrozone.csv`
- EPCI 2025 (IGN) : `EPCI_2025.shp`

## Methodologie : VL par deduction

Le module OPSAM ne fournit pas de colonnes VL ; on les obtient par
soustraction `Total - PL` pour chaque flux et chaque classe de distance,
en suivant la decomposition documentee dans la note
`202511_C2500058_Note_explicative_macrozonage_OPSAM.pdf`.
