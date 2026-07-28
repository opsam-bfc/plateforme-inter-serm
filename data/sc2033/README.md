# Bundle OPSAM sc2033

Ce dossier accueille le bundle précalculé du scénario **sc2033**.

Génération (machine avec accès NAS OPSAM) :

```bash
python scripts/rebuild_for_new_perimeter.py --scenario sc2033 --data-dir data/sc2033 -v
python scripts/optimize_for_deployment.py --data-dir data/sc2033
```

Fichiers OPSAM attendus :
- `Outputs/sc2033/synthese_m1_sc2033.csv`, `synthese_m2_sc2033.csv`
- `Outputs/sc2033/matrice_vl_sc2033.csv`
- `Base/sc2033/reseau_detaille_linkshape_sc2033.shp` (+ Link_evolue si besoin)
