"""visualizations_avatar.py.

Visualisations Plotly pour le module de comptages AVATAR (DIR Est /
DIR Centre-Est BFC) de la plateforme inter-SERM.

Fonctions exportees :
  - carte_stations_avatar   : carte Scattermapbox des stations (style
                              identique a carte_trafic_serm)
  - profil_horaire_avatar   : graphique profil horaire moyen (0-23h)
                              avec 3 panneaux : debit / vitesse / part PL
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

# Couleurs par operateur DIR
_COULEURS_OPERATEUR: dict[str, str] = {
    "DIR Est": "#E53935",
    "DIR Centre-Est": "#1E88E5",
}
_COULEUR_DEFAUT = "#757575"


# ---------------------------------------------------------------------------
# Carte stations
# ---------------------------------------------------------------------------

def carte_stations_avatar(
    stations: pd.DataFrame,
    perimetre_gdf,
    style_mapbox: str = "carto-positron",
    station_id_sel: int | None = None,
) -> go.Figure:
    """Carte Scattermapbox des stations AVATAR dans un SERM.

    Le style de rendu (fond carto, contour du perimetre) est identique
    a ``carte_trafic_serm`` pour coherence visuelle.

    Args:
        stations: DataFrame filtre sur le SERM cible, issu de
            ``charger_stations_avatar()``.
        perimetre_gdf: GeoDataFrame du perimetre du SERM (1 ligne).
        style_mapbox: Style Plotly (``carto-positron`` ou ``open-street-map``).
        station_id_sel: count_point_id de la station selectionnee
            (mise en evidence par un cercle plus grand).

    Returns:
        Figure Plotly prete pour ``st.plotly_chart``.
    """
    fig = go.Figure()

    # ── Contour du perimetre SERM ────────────────────────────────────────
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
        fig.add_trace(
            go.Scattermapbox(
                lat=lats_p,
                lon=lons_p,
                mode="lines",
                line=dict(width=2, color="#142850"),
                fill="toself",
                fillcolor="rgba(20,40,80,0.04)",
                hoverinfo="skip",
                showlegend=False,
            )
        )

    # ── Marqueurs stations par operateur ─────────────────────────────────
    if stations.empty:
        _centrer_carte_bfc(fig, style_mapbox)
        fig.update_layout(
            title="Aucune station AVATAR dans ce SERM."
        )
        return fig

    for operateur, groupe in stations.groupby("operator_name"):
        couleur = _COULEURS_OPERATEUR.get(str(operateur), _COULEUR_DEFAUT)
        tailles = []
        hover_texts = []
        custom: list[list] = []

        for _, row in groupe.iterrows():
            cp_id = int(row["count_point_id"])
            nom = str(row.get("count_point_name") or cp_id)
            route = str(row.get("op_road_name") or row.get("route_normalisee") or "?")
            direction = str(row.get("op_direction") or "")
            nb_h = int(row.get("nb_heures_2026") or 0)

            tailles.append(22 if cp_id == station_id_sel else 13)
            hover_texts.append(
                f"<b>{nom}</b><br>"
                f"Route : {route}"
                + (f" ({direction})" if direction else "")
                + f"<br>Operateur : {operateur}"
                + f"<br>Heures disponibles : {nb_h:,}"
                + "<br><i>Cliquer pour afficher le profil</i>"
            )
            custom.append([cp_id, nom, str(operateur), route])

        fig.add_trace(
            go.Scattermapbox(
                lat=groupe["latitude"].tolist(),
                lon=groupe["longitude"].tolist(),
                mode="markers",
                marker=go.scattermapbox.Marker(
                    size=tailles,
                    color=couleur,
                    opacity=0.9,
                ),
                text=hover_texts,
                hoverinfo="text",
                customdata=custom,
                name=str(operateur),
                showlegend=True,
            )
        )

    # Centre et zoom sur les stations affichees
    lats_s = stations["latitude"].dropna()
    lons_s = stations["longitude"].dropna()
    centre_lat = float(lats_s.mean()) if len(lats_s) else 47.2
    centre_lon = float(lons_s.mean()) if len(lons_s) else 5.4

    fig.update_layout(
        mapbox=dict(
            style=style_mapbox,
            center=dict(lat=centre_lat, lon=centre_lon),
            zoom=8,
        ),
        margin={"l": 0, "r": 0, "t": 40, "b": 0},
        height=520,
        title="Stations de comptage AVATAR — cliquer pour afficher le profil",
        font=dict(family="Source Sans 3, Segoe UI, sans-serif", color="#243447"),
        paper_bgcolor="rgba(0,0,0,0)",
        legend=dict(
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor="#D5DCE5",
            borderwidth=1,
            font=dict(color="#243447", size=12),
            x=0.01,
            y=0.99,
        ),
        hoverlabel=dict(
            bgcolor="white",
            bordercolor="#D5DCE5",
            font=dict(family="Source Sans 3, Segoe UI, sans-serif", size=12),
        ),
    )
    return fig


def _centrer_carte_bfc(fig: go.Figure, style_mapbox: str) -> None:
    """Centre la carte sur la BFC sans station."""
    fig.update_layout(
        mapbox=dict(
            style=style_mapbox,
            center=dict(lat=47.2, lon=5.4),
            zoom=7,
        ),
        margin={"l": 0, "r": 0, "t": 40, "b": 0},
        height=520,
    )


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

    profil = profils[profils["count_point_id"] == count_point_id].sort_values(
        "heure"
    )
    if profil.empty:
        return go.Figure().update_layout(
            title=f"Aucun profil disponible pour la station {count_point_id}.",
            height=200,
        )

    # Metadonnees de la station pour le titre
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
        "vitesse_moy" in profil.columns
        and profil["vitesse_moy"].notna().any()
    )
    has_pl = (
        "pl_pct_moy" in profil.columns
        and profil["pl_pct_moy"].notna().any()
    )

    # Construire la grille de sous-graphiques
    panneaux = ["Débit moyen (veh/h)"]
    if has_vitesse:
        panneaux.append("Vitesse moyenne (km/h)")
    if has_pl:
        panneaux.append("Part PL (%)")
    n_rows = len(panneaux)

    if n_rows == 3:
        row_heights = [0.50, 0.28, 0.22]
    elif n_rows == 2:
        row_heights = [0.62, 0.38]
    else:
        row_heights = [1.0]

    fig = sp.make_subplots(
        rows=n_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.07,
        subplot_titles=panneaux,
        row_heights=row_heights,
    )

    heures = profil["heure"].tolist()

    # ── Panneau 1 : debit ────────────────────────────────────────────────
    fig.add_trace(
        go.Scatter(
            x=heures,
            y=profil["flow_moy"].round(1).tolist(),
            mode="lines+markers",
            line=dict(color="#1A6BB5", width=2.5),
            fill="tozeroy",
            fillcolor="rgba(26,107,181,0.14)",
            marker=dict(size=5, color="#1A6BB5"),
            name="Débit",
            hovertemplate="%{x}h00 → %{y:.0f} veh/h<extra></extra>",
        ),
        row=1, col=1,
    )

    row_courant = 2

    # ── Panneau 2 : vitesse ──────────────────────────────────────────────
    if has_vitesse:
        fig.add_trace(
            go.Scatter(
                x=heures,
                y=profil["vitesse_moy"].round(1).tolist(),
                mode="lines+markers",
                line=dict(color="#66BB6A", width=2.5),
                marker=dict(size=5, color="#66BB6A"),
                name="Vitesse",
                hovertemplate="%{x}h00 → %{y:.1f} km/h<extra></extra>",
            ),
            row=row_courant, col=1,
        )
        row_courant += 1

    # ── Panneau 3 : part PL ──────────────────────────────────────────────
    if has_pl:
        fig.add_trace(
            go.Bar(
                x=heures,
                y=profil["pl_pct_moy"].round(1).tolist(),
                marker_color="#FFA726",
                opacity=0.85,
                name="Part PL",
                hovertemplate="%{x}h00 → %{y:.1f} %<extra></extra>",
            ),
            row=row_courant, col=1,
        )

    # Axe X commun
    fig.update_xaxes(
        tickvals=list(range(0, 24, 2)),
        ticktext=[f"{h:02d}h" for h in range(0, 24, 2)],
        title_text="Heure",
        row=n_rows, col=1,
    )
    fig.update_yaxes(gridcolor="#E6EBF1", zerolinecolor="#C5CFDA", linecolor="#C5CFDA")
    fig.update_xaxes(gridcolor="#E6EBF1", linecolor="#C5CFDA")

    titre_complet = f"<b>Profil horaire moyen — {nom_station}</b>"
    if sous_titre:
        titre_complet += (
            f"<br><sup style='color:#9E9E9E'>{sous_titre}</sup>"
        )

    fig.update_layout(
        title=dict(
            text=titre_complet,
            font=dict(family="Source Sans 3, Segoe UI, sans-serif", color="#0E2A47", size=15),
        ),
        height=380 + 130 * (n_rows - 1),
        showlegend=False,
        margin={"l": 60, "r": 20, "t": 80, "b": 40},
        plot_bgcolor="#FFFFFF",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(
            family="Source Sans 3, Segoe UI, sans-serif",
            color="#243447",
        ),
        hoverlabel=dict(
            bgcolor="white",
            bordercolor="#D5DCE5",
            font=dict(family="Source Sans 3, Segoe UI, sans-serif", size=12, color="#243447"),
        ),
    )
    return fig
