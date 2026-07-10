# Guide de déploiement — Plateforme inter-SERM

Diffusion de la plateforme Streamlit sur Internet via **Streamlit Community Cloud** (gratuit),
avec lien privé protégé par mot de passe.

---

## Architecture cible

```
Votre PC (local)
  ├── Scripts de préparation (scripts/prepare_*.py)   ← accès NAS OPSAM
  ├── Script d'optimisation (scripts/optimize_for_deployment.py)
  └── Bundle allégé (data/ ~25 Mo)
          │
          │  git push
          ▼
GitHub (dépôt privé)
  └── Code + données optimisées (~25 Mo)
          │
          │  déclenchement automatique
          ▼
Streamlit Community Cloud (gratuit)
  └── URL https://xxx.streamlit.app
        + Page de login par mot de passe
        + Lien partageable aux partenaires
```

---

## Étape 1 — Optimiser les données

Cette étape réduit le bundle de ~99 Mo à ~25 Mo en :
- convertissant les GPKG réseau en GeoParquet simplifié (~67 Mo → ~15 Mo) ;
- simplifiant les géométries des GeoJSON (précision ~30 m suffit) ;
- excluant les caches data.gouv (retéléchargés à la demande).

```powershell
cd "D:\12__OPSAM\plateforme_analyse_inter_SERM"
& "C:/Program Files/Python313/python.exe" scripts/optimize_for_deployment.py
```

Les originaux sont sauvegardés dans `data/.backup_avant_optim/` (non versionné).

**Vérification :** le dossier `data/` doit peser < 30 Mo après l'opération.

---

## Étape 2 — Générer le hash du mot de passe

Choisissez un mot de passe pour protéger l'accès à la plateforme, puis générez son hash :

```powershell
& "C:/Program Files/Python313/python.exe" -c "import hashlib; print(hashlib.sha256(b'VOTRE_MOT_DE_PASSE').hexdigest())"
```

Notez le hash affiché (64 caractères hexadécimaux). **Ne le partagez qu'avec les personnes de confiance.**

---

## Étape 3 — Créer le dépôt GitHub privé

1. Connectez-vous sur [github.com](https://github.com) (créer un compte si besoin).
2. Cliquez **New repository** → nommez-le `plateforme-inter-serm` → cochez **Private**.
3. Dans PowerShell :

```powershell
cd "D:\12__OPSAM\plateforme_analyse_inter_SERM"

# Initialiser git (si pas encore fait)
git init
git branch -M main

# Ajouter le dépôt distant (remplacez VOTRE_LOGIN par votre identifiant GitHub)
git remote add origin https://github.com/VOTRE_LOGIN/plateforme-inter-serm.git

# Premier commit et push
git add .
git commit -m "feat: plateforme inter-SERM optimisée pour déploiement"
git push -u origin main
```

> **Vérifiez que .gitignore exclut bien** `data/.backup_avant_optim/`,
> `EXPORT_LIVRABLES/`, `data/reseau_serm/*.gpkg` et `.streamlit/secrets.toml`
> avant de pousser.

---

## Étape 4 — Déployer sur Streamlit Community Cloud

1. Ouvrez [share.streamlit.io](https://share.streamlit.io) et connectez-vous avec GitHub.
2. Cliquez **New app**.
3. Sélectionnez votre dépôt `plateforme-inter-serm`, branche `main`, fichier `app.py`.
4. Cliquez **Advanced settings** → onglet **Secrets** → collez :

```toml
MOT_DE_PASSE_HASH = "LE_HASH_GENERE_A_LETAPE_2"
MAPBOX_TOKEN = ""
```

5. Cliquez **Deploy**. Le déploiement prend 2–5 minutes.

Vous obtenez une URL du type `https://plateforme-inter-serm-xyz.streamlit.app`.

---

## Étape 5 — Partager le lien de manière sécurisée

- L'URL **n'est pas indexée** par les moteurs de recherche.
- Partagez l'URL **et le mot de passe** aux partenaires par canal sécurisé (e-mail chiffré, messagerie interne).
- Chaque utilisateur devra saisir le mot de passe à sa première visite (session conservée tant que l'onglet est ouvert).

---

## Mise à jour des données

Quand le bundle est regénéré (nouveau modèle OPSAM) :

```powershell
# 1. Regénérer le bundle depuis le NAS
& "C:/Program Files/Python313/python.exe" scripts/rebuild_for_new_perimeter.py

# 2. Ré-optimiser pour le déploiement
& "C:/Program Files/Python313/python.exe" scripts/optimize_for_deployment.py

# 3. Pousser sur GitHub → Streamlit Cloud se met à jour automatiquement
git add data/
git commit -m "data: mise à jour bundle OPSAM Ref2025"
git push
```

---

## Changer le mot de passe

1. Générez un nouveau hash (voir Étape 2).
2. Sur Streamlit Cloud : **Settings > Secrets** → mettez à jour `MOT_DE_PASSE_HASH`.
3. L'app se redémarre automatiquement.

---

## Limites de la formule gratuite (Streamlit Community Cloud)

| Ressource | Limite |
|-----------|--------|
| RAM | 1 GB |
| CPU | 1 vCPU partagé |
| Dépôt GitHub | < 1 GB (données ~25 Mo ✓) |
| Apps simultanées | 3 |
| Inactivité | L'app se met en veille après 7 j sans visite (redémarrage automatique à la première visite) |

Si 1 GB RAM est insuffisant (carte trafic Dijon chargée en mémoire), les options payantes sont :
- **Streamlit Community Cloud Teams** (~50 $/mois, 8 GB RAM)
- **Render.com** (~7 $/mois, configuration via `render.yaml` fourni)

---

## Dépannage

| Problème | Solution |
|----------|----------|
| "Bundle indisponible" au démarrage | Vérifier que `data/` est bien présent dans le dépôt |
| Carte réseau ne s'affiche pas | Vérifier que `data/reseau_serm/*.parquet` existent |
| Erreur mémoire sur Streamlit Cloud | Passer à un forfait avec plus de RAM |
| Mot de passe oublié | Regénérer un hash, mettre à jour dans Secrets |
| Cache data.gouv absent | Normal : il est téléchargé à la demande (page Contexte) |
