"""visualizations_avatar.py.

Visualisations Plotly pour le module "Comptages horaires" de la plateforme
inter-SERM.

Carte multicouche (Scattermapbox) :
  - Reseau routier (trafic VL)   : lignes colorees par volume
  - Arrets Mobigo                : points verts
  - Gares SNCF                   : points bleus
  - Stations AVATAR (DIR)        : points orange (profil horaire au clic)

Graphique profil horaire (0-23h) par station AVATAR :
  - Debit moyen (veh/h)
  - Vitesse moyenne (km/h)
  - Part PL (%)
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from formatting import fmt_nombre

# ---------------------------------------------------------------------------
# Helpers reseau routier
# ---------------------------------------------------------------------------

_PALETTE_RESEAU = [
    [0.0,  "#1a237e"],
    [0.25, "#283593"],
    [0.5,  "#1565c0"],
    [0.75, "#ef6c00"],
    [1.0,  "#b71c1c"],
]

_COULEURS_VOIE = {
    "Autoroute":      "#E53935",
    "Nationale":      "#FB8C00",
    "Departementale": "#43A047",
    "NoData":         "#90A4AE",
}


def _coords_lignes_reseau(gdf) -> tuple[list, list, list]:
    """Extrait lat/lon/texte des geometries lineaires avec separateurs None."""
    lats: list = []
    lons: list = []
    textes: list = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        lines = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
        for line in lines:
            coords = list(line.coords)
            lats.extend(c[1] for c in coords)
            lons.extend(c[0] for c in coords)
            val = row.get("VL_jour") or row.get("TMJA_P") or 0
            textes.extend([f"{fmt_nombre(val, 0)} VL/j"] * len(coords))
            lats.append(None)
            lons.append(None)
            textes.append(None)
    return lats, lons, textes


def _ajouter_reseau(fig: go.Figure, reseau_gdf, metrique: str = "VL_jour") -> None:
    """Ajoute le reseau routier en traces Scattermapbox par type de voie."""
    if reseau_gdf is None or len(reseau_gdf) == 0:
        return

    reseau = reseau_gdf.copy()
    if metrique not in reseau.columns:
        metrique = next(
            (c for c in ("TMJA_P", "VL_jour") if c in reseau.columns), None
        )
    if metrique is None:
        return

    reseau[metrique] = reseau[metrique].fillna(0)

    # Troncons sans comptage en gris clair
    sans = reseau[reseau[metrique] == 0]
    if not sans.empty:
        lats, lons, _ = _coords_lignes_reseau(sans)
        fig.add_trace(go.Scattermapbox(
            lat=lats, lon=lons, mode="lines",
            line=dict(width=0.8, color="#BDBDBD"),
            hoverinfo="skip", showlegend=False,
        ))

    # Troncons avec comptage : couleur par type de voie
    avec = reseau[reseau[metrique] > 0]
    col_voie = next(
        (c for c in ("CL_ADMIN", "type_voie", "classe_admin") if c in avec.columns),
        None,
    )
    groupes = (
        avec.groupby(col_voie)
        if col_voie
        else [(None, avec)]
    )
    for voie, grp in groupes:
        voie_str = str(voie) if voie else ""
        couleur = next(
            (v for k, v in _COULEURS_VOIE.items() if k.lower() in voie_str.lower()),
            "#90A4AE",
        )
        epaisseur = 3.0 if "auto" in voie_str.lower() else (
            2.2 if "nat" in voie_str.lower() else 1.4
        )
        lats, lons, textes = _coords_lignes_reseau(grp)
        fig.add_trace(go.Scattermapbox(
            lat=lats, lon=lons, mode="lines",
            line=dict(width=epaisseur, color=couleur),
            text=textes,
            hoverinfo="text",
            showlegend=False,
        ))


# ---------------------------------------------------------------------------
# Carte multicouche principale
# ---------------------------------------------------------------------------

def carte_comptages_horaires(
    stations: pd.DataFrame,
    perimetre_gdf,
    style_mapbox: str = "carto-positron",
    station_id_sel: int | None = None,
    reseau_gdf=None,
    gares_gdf=None,
    mobigo_gdf=None,
) -> go.Figure:
    """Carte Scattermapbox multicouche pour le module Comptages horaires.

    Couches (ordre d'empilement bas → haut) :
      1. Contour du perimetre SERM
      2. Reseau routier (trafic VL, couleur par type de voie)
      3. Arrets Mobigo  — points verts
      4. Gares SNCF     — points bleus
      5. Stations AVATAR — points orange (clic → profil horaire)

    Args:
        stations: DataFrame metadonnees stations AVATAR (deja filtre sur SERM).
        perimetre_gdf: GeoDataFrame perimetre du SERM selectionne.
        style_mapbox: Style de fond Plotly.
        station_id_sel: count_point_id de la station selectionnee.
        reseau_gdf: GeoDataFrame du reseau routier (optionnel).
        gares_gdf: GeoDataFrame des gares SNCF (optionnel).
        mobigo_gdf: GeoDataFrame des arrets Mobigo (optionnel).

    Returns:
        Figure Plotly.
    """
    fig = go.Figure()

    # ── 1. Contour du perimetre SERM ─────────────────────────────────────
    if perimetre_gdf is not None and len(perimetre_gdf) > 0:
        gdf_wgs = perimetre_gdf.to_crs(4326)
        lats_p: list = []
        lons_p: list = []
        for _, row in gdf_wgs.iterrows():
            geoms = (
                list(row.geometry.geoms)
                if row.geometry.geom_type == "MultiPolygon"
                else [row.geometry]
            )
            for poly in geoms:
                xs, ys = poly.exterior.coords.xy
                lats_p.extend(list(ys))
                lons_p.extend(list(xs))
                lats_p.append(None)
                lons_p.append(None)
        fig.add_trace(go.Scattermapbox(
            lat=lats_p, lon=lons_p, mode="lines",
            line=dict(width=2.5, color="#142850"),
            fill="toself",
            fillcolor="rgba(20,40,80,0.04)",
            hoverinfo="skip", showlegend=False,
        ))

    # ── 2. Reseau routier ────────────────────────────────────────────────
    _ajouter_reseau(fig, reseau_gdf)

    # ── 3. Arrets Mobigo (vert) ──────────────────────────────────────────
    if mobigo_gdf is not None and len(mobigo_gdf) > 0:
        mob = mobigo_gdf.copy()
        if mob.crs is not None and mob.crs.to_epsg() != 4326:
            mob = mob.to_crs(4326)
        lats_m = mob.geometry.y.tolist()
        lons_m = mob.geometry.x.tolist()
        noms_m = mob.get("stop_name", pd.Series([""] * len(mob))).tolist()
        hover_m = [f"<b>{n}</b><br>Arret Mobigo" for n in noms_m]
        fig.add_trace(go.Scattermapbox(
            lat=lats_m, lon=lons_m,
            mode="markers",
            marker=go.scattermapbox.Marker(size=12, color="#43A047", opacity=0.8),
            text=hover_m,
            hoverinfo="text",
            name="Arrets Mobigo",
            showlegend=True,
        ))

    # ── 4. Gares SNCF (bleu) ─────────────────────────────────────────────
    if gares_gdf is not None and len(gares_gdf) > 0:
        gares = gares_gdf.copy()
        if gares.crs is not None and gares.crs.to_epsg() != 4326:
            gares = gares.to_crs(4326)
        col_nom = next(
            (c for c in (
                "intitule_p", "libelle", "nom", "nom_gare", "stop_name", "name"
            ) if c in gares.columns),
            gares.columns[0],
        )
        centroides_g = gares.geometry.centroid
        lats_g = centroides_g.y.tolist()
        lons_g = centroides_g.x.tolist()
        noms_g = gares[col_nom].tolist()
        hover_g = [f"<b>{n}</b><br>Gare SNCF" for n in noms_g]
        fig.add_trace(go.Scattermapbox(
            lat=lats_g, lon=lons_g,
            mode="markers",
            marker=go.scattermapbox.Marker(
                size=14, color="#1565C0", opacity=0.95,
            ),
            text=hover_g,
            hoverinfo="text",
            name="Gares SNCF",
            showlegend=True,
        ))

    # ── 5. Stations AVATAR (orange) ──────────────────────────────────────
    if not stations.empty:
        tailles = []
        hover_av: list[str] = []
        custom: list[list] = []

        for _, row in stations.iterrows():
            cp_id = int(row["count_point_id"])
            nom = str(row.get("count_point_name") or cp_id)
            route = str(row.get("op_road_name") or row.get("route_normalisee") or "?")
            direction = str(row.get("op_direction") or "")
            nb_h = int(row.get("nb_heures_2026") or 0)

            tailles.append(20 if cp_id == station_id_sel else 12)
            hover_av.append(
                f"<b>{nom}</b><br>"
                f"Route : {route}"
                + (f" ({direction})" if direction else "")
                + f"<br>{fmt_nombre(nb_h, 0)} heures disponibles"
                + "<br><i>Cliquer pour le profil horaire</i>"
            )
            custom.append([cp_id, nom, route])

        fig.add_trace(go.Scattermapbox(
            lat=stations["latitude"].tolist(),
            lon=stations["longitude"].tolist(),
            mode="markers",
            marker=go.scattermapbox.Marker(
                size=tailles, color="#F57C00", opacity=0.95,
            ),
            text=hover_av,
            hoverinfo="text",
            customdata=custom,
            name="Stations de Comptages",
            showlegend=True,
        ))

    # ── Cadrage et mise en page ──────────────────────────────────────────
    lats_s = stations["latitude"].dropna() if not stations.empty else pd.Series(dtype=float)
    centre_lat = float(lats_s.mean()) if len(lats_s) else 47.2
    centre_lon = float(stations["longitude"].dropna().mean()) if not stations.empty else 5.4

    fig.update_layout(
        mapbox=dict(
            style=style_mapbox,
            center=dict(lat=centre_lat, lon=centre_lon),
            zoom=8,
        ),
        margin={"l": 0, "r": 0, "t": 40, "b": 0},
        height=580,
        title=(
            "Carte des transports — "
            "<span style='color:#F57C00'>■ Stations de Comptages</span>  "
            "<span style='color:#1565C0'>■ Gares SNCF</span>  "
            "<span style='color:#43A047'>■ Arrêts Mobigo</span>"
        ),
        legend=dict(
            bgcolor="rgba(30,30,30,0.80)",
            font=dict(color="white", size=11),
            x=0.01, y=0.99,
        ),
    )
    return fig


# ---------------------------------------------------------------------------
# Profil horaire
# ---------------------------------------------------------------------------

def profil_horaire_avatar(
    profils: pd.DataFrame,
    count_point_id: int,
    stations: pd.DataFrame,
) -> go.Figure:
    """Graphique profil horaire moyen (0-23h) pour une station AVATAR.

    Trois panneaux superposes a axe X partage :
      1. Debit moyen (veh/h) — courbe remplie
      2. Vitesse moyenne (km/h) — courbe (si disponible)
      3. Part PL (%) — barres (si disponible)

    Args:
        profils: DataFrame issu de ``charger_profils_avatar()``.
        count_point_id: Identifiant AVATAR de la station.
        stations: DataFrame metadonnees pour le titre (nom, route).

    Returns:
        Figure Plotly.
    """
    import plotly.subplots as sp

    profil = profils[profils["count_point_id"] == count_point_id].sort_values("heure")
    if profil.empty:
        return go.Figure().update_layout(
            title=f"Aucun profil disponible pour la station {count_point_id}.",
            height=200,
        )

    row_st = stations[stations["count_point_id"] == count_point_id]
    if not row_st.empty:
        r = row_st.iloc[0]
        nom_station = str(r.get("count_point_name") or count_point_id)
        route = str(r.get("op_road_name") or r.get("route_normalisee") or "")
        direction = str(r.get("op_direction") or "")
        operateur = str(r.get("operator_name") or "")
        sous_titre = " — ".join(filter(None, [route, direction, operateur]))
    else:
        nom_station = str(count_point_id)
        sous_titre = ""

    has_vitesse = (
        "vitesse_moy" in profil.columns and profil["vitesse_moy"].notna().any()
    )
    has_pl = (
        "pl_pct_moy" in profil.columns and profil["pl_pct_moy"].notna().any()
    )

    panneaux = ["Débit moyen (veh/h)"]
    if has_vitesse:
        panneaux.append("Vitesse moyenne (km/h)")
    if has_pl:
        panneaux.append("Part PL (%)")
    n_rows = len(panneaux)

    row_heights = (
        [0.50, 0.28, 0.22] if n_rows == 3
        else [0.62, 0.38] if n_rows == 2
        else [1.0]
    )

    fig = sp.make_subplots(
        rows=n_rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.07,
        subplot_titles=panneaux,
        row_heights=row_heights,
    )

    heures = profil["heure"].tolist()

    fig.add_trace(go.Scatter(
        x=heures, y=profil["flow_moy"].round(1).tolist(),
        mode="lines+markers",
        line=dict(color="#F57C00", width=2.5),
        fill="tozeroy", fillcolor="rgba(245,124,0,0.15)",
        marker=dict(size=5, color="#F57C00"),
        name="Débit",
        customdata=[
            fmt_nombre(v, 0) for v in profil["flow_moy"].round(1).tolist()
        ],
        hovertemplate="%{x}h00 → %{customdata} veh/h<extra></extra>",
    ), row=1, col=1)

    row_courant = 2
    if has_vitesse:
        fig.add_trace(go.Scatter(
            x=heures, y=profil["vitesse_moy"].round(1).tolist(),
            mode="lines+markers",
            line=dict(color="#66BB6A", width=2.5),
            marker=dict(size=5, color="#66BB6A"),
            name="Vitesse",
            customdata=[
                fmt_nombre(v, 1) for v in profil["vitesse_moy"].round(1).tolist()
            ],
            hovertemplate="%{x}h00 → %{customdata} km/h<extra></extra>",
        ), row=row_courant, col=1)
        row_courant += 1

    if has_pl:
        fig.add_trace(go.Bar(
            x=heures, y=profil["pl_pct_moy"].round(1).tolist(),
            marker_color="#1565C0", opacity=0.85,
            name="Part PL",
            customdata=[
                fmt_nombre(v, 1) for v in profil["pl_pct_moy"].round(1).tolist()
            ],
            hovertemplate="%{x}h00 → %{customdata} %<extra></extra>",
        ), row=row_courant, col=1)

    fig.update_xaxes(
        tickvals=list(range(0, 24, 2)),
        ticktext=[f"{h:02d}h" for h in range(0, 24, 2)],
        title_text="Heure", row=n_rows, col=1,
    )
    fig.update_yaxes(gridcolor="#333", zerolinecolor="#555")

    titre_complet = f"<b>Profil horaire moyen — {nom_station}</b>"
    if sous_titre:
        titre_complet += f"<br><sup style='color:#9E9E9E'>{sous_titre}</sup>"

    fig.update_layout(
        title=titre_complet,
        height=380 + 130 * (n_rows - 1),
        showlegend=False,
        margin={"l": 60, "r": 20, "t": 80, "b": 40},
        plot_bgcolor="#1A1A2E",
        paper_bgcolor="#1A1A2E",
        font=dict(color="#E0E0E0"),
    )
    return fig
