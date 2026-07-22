"""visualizations.py.

Fabriques de figures Plotly pour la plateforme inter-SERM.

Conventions :
  * fond carto : ``carto-positron`` si jeton Mapbox disponible, sinon
    ``open-street-map`` (gere par l'app).
  * palette : couleurs des SERM definies dans ``data_loader.SERM_INFO``.
"""

from __future__ import annotations

import json
import math
from typing import Iterable, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from data_loader import (
    CLASSES_DISTANCE,
    FLUX_LABELS,
    SERM_INFO,
    TYPES_VOIE_LABELS,
    info_serm,
)

# ---------------------------------------------------------------------------
# Palette / utilitaires
# ---------------------------------------------------------------------------

COULEUR_VL = "#1A6BB5"
COULEUR_PL = "#E07010"

ECHELLE_TMJA = "Plasma"
ECHELLE_PCT_PL = "Reds"

_FONT_CHART = "Source Sans 3, Segoe UI, sans-serif"
_COULEUR_TEXTE = "#243447"
_COULEUR_TITRE = "#0E2A47"
_COULEUR_GRILLE = "#E6EBF1"
_COULEUR_AXE = "#C5CFDA"


def _theme_layout(**extra) -> dict:
    """Layout Plotly commun (typo, fonds, marges de base)."""
    base = dict(
        font=dict(family=_FONT_CHART, color=_COULEUR_TEXTE, size=13),
        title=dict(
            font=dict(family=_FONT_CHART, color=_COULEUR_TITRE, size=15),
            x=0.01,
            xanchor="left",
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#FFFFFF",
        legend=dict(
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor="#D5DCE5",
            borderwidth=1,
            font=dict(size=12),
        ),
        hoverlabel=dict(
            bgcolor="white",
            bordercolor="#D5DCE5",
            font=dict(family=_FONT_CHART, size=12, color=_COULEUR_TEXTE),
        ),
    )
    base.update(extra)
    return base


def _appliquer_theme_axes(fig: go.Figure) -> go.Figure:
    """Grilles et axes discrets pour un rendu plus institutionnel."""
    fig.update_xaxes(
        gridcolor=_COULEUR_GRILLE,
        zerolinecolor=_COULEUR_AXE,
        linecolor=_COULEUR_AXE,
        tickfont=dict(size=11, color="#5C6B7A"),
        title_font=dict(size=12, color="#5C6B7A"),
    )
    fig.update_yaxes(
        gridcolor=_COULEUR_GRILLE,
        zerolinecolor=_COULEUR_AXE,
        linecolor=_COULEUR_AXE,
        tickfont=dict(size=11, color="#5C6B7A"),
        title_font=dict(size=12, color="#5C6B7A"),
    )
    return fig


def _layout_mapbox(
    style_mapbox: str, hauteur: int = 600, marge: int = 5
) -> dict:
    return _theme_layout(
        mapbox_style=style_mapbox,
        margin={"r": marge, "t": marge, "l": marge, "b": marge},
        height=hauteur,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor="#D5DCE5",
            borderwidth=1,
        ),
    )


# ---------------------------------------------------------------------------
# Carte vue d'ensemble (3 SERM colores par indicateur)
# ---------------------------------------------------------------------------

def carte_vue_ensemble(
    perimetres_gdf,
    metriques: pd.DataFrame,
    indicateur: str,
    style_mapbox: str,
    libelle_indicateur: str | None = None,
) -> go.Figure:
    """Carte choropleth des 3 SERM coloree par l'indicateur choisi."""
    gdf = perimetres_gdf.merge(
        metriques[["code_serm", indicateur, "nom_serm"]],
        on="code_serm",
        how="left",
        suffixes=("", "_metr"),
    )
    geojson = json.loads(gdf.to_json())

    fig = px.choropleth_mapbox(
        gdf,
        geojson=geojson,
        locations=gdf.index,
        color=indicateur,
        color_continuous_scale="Viridis",
        hover_name="nom_serm",
        hover_data={indicateur: ":,.1f"},
        opacity=0.55,
        center={"lat": 47.2, "lon": 5.0},
        zoom=6.2,
    )
    fig.update_traces(marker_line_width=2, marker_line_color="#0E2A47")

    if libelle_indicateur:
        fig.update_coloraxes(colorbar_title=libelle_indicateur)

    fig.update_layout(**_layout_mapbox(style_mapbox, hauteur=620))
    return fig


# ---------------------------------------------------------------------------
# Carte trafic par SERM (TMJA / % PL / VL_jour)
# ---------------------------------------------------------------------------

def _coords_lignes(
    gdf_sub,
    metrique: str | None = None,
) -> tuple[list, list, list]:
    """Construit les listes lat/lon/texte pour un GeoDataFrame de linestrings.

    Utilise le separateur ``None`` entre troncons pour un rendu efficace
    en une seule trace Scattermapbox.
    """
    lats: list = []
    lons: list = []
    textes: list = []
    for _, row in gdf_sub.iterrows():
        geom = row.geometry
        segments = (
            list(geom.geoms)
            if geom.geom_type == "MultiLineString"
            else [geom]
        )
        for seg in segments:
            xs, ys = seg.coords.xy
            lats.extend(ys)
            lons.extend(xs)
            lats.append(None)
            lons.append(None)
            if metrique and metrique in row.index:
                val = row[metrique]
                label = (
                    f"{row.get('CL_ADMIN', '')} | {metrique}: {val:,.0f}"
                    if pd.notna(val)
                    else f"{row.get('CL_ADMIN', '')} | pas de comptage"
                )
                textes.extend([label] * len(xs))
            else:
                textes.extend([""] * len(xs))
            textes.append(None)
    return lats, lons, textes


def carte_trafic_serm(
    reseau_gdf,
    perimetre_gdf,
    metrique: str,
    style_mapbox: str,
    titre: Optional[str] = None,
) -> go.Figure:
    """Carte du reseau routier d'un SERM, lignes colorees selon ``metrique``.

    Affiche l'integralite du reseau classe (Autoroute, Nationale,
    Departementale). Les troncons sans comptage (TMJA = 0 ou NaN) sont
    traces en gris clair ; les autres sont colores par plage de valeur.

    ``metrique`` parmi : ``TMJA_P`` (tous vehicules, modelise), ``VL_jour``,
    ``PL_jour`` (= ``PL_P``).
    """
    if metrique not in reseau_gdf.columns:
        raise ValueError(f"Metrique {metrique!r} absente du reseau.")

    reseau = reseau_gdf.copy()
    reseau[metrique] = reseau[metrique].fillna(0)

    if len(reseau) == 0:
        return go.Figure().update_layout(title="Aucun troncon a afficher.")

    # Reds pour PL_jour (volume PL absolu), Plasma pour les autres metriques.
    palette = "Reds" if metrique == "PL_jour" else "Plasma"

    fig = go.Figure()

    # ── Contour du perimetre SERM ────────────────────────────────────────────
    if perimetre_gdf is not None and len(perimetre_gdf) > 0:
        gdf_proj = perimetre_gdf.to_crs(4326)
        for _, row in gdf_proj.iterrows():
            geoms = (
                list(row.geometry.geoms)
                if row.geometry.geom_type == "MultiPolygon"
                else [row.geometry]
            )
            for poly in geoms:
                xs, ys = poly.exterior.coords.xy
                fig.add_trace(
                    go.Scattermapbox(
                        lat=list(ys),
                        lon=list(xs),
                        mode="lines",
                        line=dict(width=2, color="#142850"),
                        hoverinfo="skip",
                        showlegend=False,
                    )
                )

    # ── Troncons sans comptage : gris clair (fond de reseau) ─────────────────
    reseau_sans = reseau[reseau[metrique] == 0]
    if not reseau_sans.empty:
        lats, lons, textes = _coords_lignes(reseau_sans, metrique)
        fig.add_trace(
            go.Scattermapbox(
                lat=lats,
                lon=lons,
                mode="lines",
                line=dict(width=1.0, color="#CCCCCC"),
                name="Pas de comptage",
                hoverinfo="text",
                hovertext=textes,
            )
        )

    # ── Troncons avec comptage : colores par plage quantile ──────────────────
    reseau_avec = reseau[reseau[metrique] > 0].copy()
    if not reseau_avec.empty:
        valeurs = reseau_avec[metrique].to_numpy()
        v_max = max(float(valeurs.max()), 1.0)
        reseau_avec["_largeur"] = 1.0 + 5.0 * (valeurs / v_max) ** 0.5

        seuils = _quantiles_seuils(valeurs, nb=5)
        couleurs = px.colors.sample_colorscale(
            palette, [0.15, 0.35, 0.55, 0.75, 0.95]
        )
        for i, (seuil_bas, seuil_haut) in enumerate(
            zip(seuils[:-1], seuils[1:])
        ):
            masque = (
                (reseau_avec[metrique] >= seuil_bas)
                & (reseau_avec[metrique] < seuil_haut)
            )
            if not masque.any():
                continue
            sub = reseau_avec[masque]
            lats, lons, textes = _coords_lignes(sub, metrique)
            larg_moy = float(sub["_largeur"].mean())
            fig.add_trace(
                go.Scattermapbox(
                    lat=lats,
                    lon=lons,
                    mode="lines",
                    line=dict(width=larg_moy, color=couleurs[i]),
                    name=f"{seuil_bas:,.0f} – {seuil_haut:,.0f}",
                    hoverinfo="text",
                    hovertext=textes,
                )
            )

    centre = _centre_geometrique(perimetre_gdf)
    fig.update_layout(
        **_theme_layout(
            mapbox_style=style_mapbox,
            mapbox_center=centre,
            mapbox_zoom=8.5,
            margin={"r": 5, "t": 40, "l": 5, "b": 5},
            height=620,
            title=titre,
            legend_title_text=metrique,
        )
    )
    return fig


def _quantiles_seuils(valeurs, nb: int = 5) -> list[float]:
    """Renvoie ``nb+1`` seuils issus des quantiles (avec borne haute = max+1)."""
    s = pd.Series(valeurs)
    seuils = [float(s.quantile(q)) for q in [0.0, 0.5, 0.75, 0.9, 0.99]]
    seuils.append(float(s.max()) + 1.0)
    return seuils


def _centre_geometrique(gdf) -> dict:
    """Centre lon/lat d'un GeoDataFrame en WGS84."""
    if gdf is None or len(gdf) == 0:
        return {"lat": 47.2, "lon": 5.5}
    bounds = gdf.to_crs(4326).total_bounds  # minx, miny, maxx, maxy
    return {
        "lat": float((bounds[1] + bounds[3]) / 2),
        "lon": float((bounds[0] + bounds[2]) / 2),
    }


# ---------------------------------------------------------------------------
# Diagrammes Sankey VL / PL par SERM
# ---------------------------------------------------------------------------

# Style des libelles Sankey (lisibilite sur fonds colores)
_SANKEY_HALO_BLANC = (
    "0 0 5px #ffffff, 0 0 5px #ffffff, "
    "-1px -1px 0 #ffffff, 1px -1px 0 #ffffff, "
    "-1px 1px 0 #ffffff, 1px 1px 0 #ffffff, "
    "0 0 8px #ffffff"
)
_SANKEY_TEXTFONT = dict(
    family="Arial Black, Arial, sans-serif",
    size=16,
    color="#1A1A2E",
    shadow=_SANKEY_HALO_BLANC,
)


def _libelles_sankey_gras(noeuds: list[str]) -> list[str]:
    """Libelles en gras (HTML) pour les noeuds Sankey."""
    return [f"<b>{n}</b>" for n in noeuds]


def _appliquer_style_sankey(fig: go.Figure, titre: str) -> go.Figure:
    """Applique police grasse, taille et halo blanc aux libelles."""
    fig.update_layout(
        **_theme_layout(
            title=titre,
            height=540,
            margin={"l": 20, "r": 20, "t": 65, "b": 15},
            font=dict(**_SANKEY_TEXTFONT),
        )
    )
    fig.update_traces(
        textfont=dict(**_SANKEY_TEXTFONT),
        selector=dict(type="sankey"),
    )
    return fig


def sankey_vl_pl_par_voie(df_serm: pd.DataFrame, titre: str) -> go.Figure:
    """Sankey : types de voies -> flux E/T/I -> VL / PL.

    Utilise les VKM tous vehicules pour la repartition par flux, ventiles
    en VL/PL grace aux colonnes deduites.
    """
    types = []
    for cl, libelle in TYPES_VOIE_LABELS.items():
        masque = df_serm["CL_ADMIN"] == cl
        if masque.any():
            types.append((libelle, cl))
    flux = [(FLUX_LABELS[f], f) for f in ("E", "T", "I")]
    vehicules = [("VL", "VL"), ("PL", "PL")]

    noeuds = [t[0] for t in types] + [f[0] for f in flux] + [v[0] for v in vehicules]
    libelles = _libelles_sankey_gras(noeuds)
    couleurs = ["#90A4AE"] * len(types) + ["#1A237E", "#B71C1C", "#33691E"] + [
        COULEUR_VL, COULEUR_PL
    ]
    index = {n: i for i, n in enumerate(noeuds)}

    sources, targets, values, labels = [], [], [], []
    # Type voie -> flux
    for libelle_t, cl in types:
        for libelle_f, f in flux:
            total = df_serm.loc[df_serm["CL_ADMIN"] == cl, f"VKM_{f}"].sum()
            if total > 0:
                sources.append(index[libelle_t])
                targets.append(index[libelle_f])
                values.append(float(total))
                labels.append(f"{libelle_t} -> {libelle_f}: {total:,.0f}")
    # Flux -> VL / PL
    for libelle_f, f in flux:
        vl = df_serm[f"VKM_VL_{f}"].sum() if f"VKM_VL_{f}" in df_serm.columns else 0
        pl = df_serm[f"VKM_PL_{f}"].sum() if f"VKM_PL_{f}" in df_serm.columns else 0
        if vl > 0:
            sources.append(index[libelle_f])
            targets.append(index["VL"])
            values.append(float(vl))
            labels.append(f"{libelle_f} -> VL: {vl:,.0f}")
        if pl > 0:
            sources.append(index[libelle_f])
            targets.append(index["PL"])
            values.append(float(pl))
            labels.append(f"{libelle_f} -> PL: {pl:,.0f}")

    fig = go.Figure(
        go.Sankey(
            textfont=dict(**_SANKEY_TEXTFONT),
            node=dict(
                pad=22,
                thickness=22,
                line=dict(color="white", width=2.5),
                label=libelles,
                color=couleurs,
            ),
            link=dict(
                source=sources, target=targets, value=values,
                label=labels, color="rgba(149,165,166,0.4)",
            ),
        )
    )
    return _appliquer_style_sankey(fig, titre)


# ---------------------------------------------------------------------------
# Donut VL / PL
# ---------------------------------------------------------------------------

def donut_vl_pl(repartition: pd.DataFrame, titre: str) -> go.Figure:
    """Donut total VL vs PL pour un SERM (somme des flux E/T/I)."""
    vl = float(repartition["VKM_VL"].sum())
    pl = float(repartition["VKM_PL"].sum())
    fig = go.Figure(
        go.Pie(
            values=[vl, pl],
            labels=["VL", "PL"],
            hole=0.55,
            marker=dict(colors=[COULEUR_VL, COULEUR_PL]),
            textinfo="label+percent",
        )
    )
    fig.update_layout(
        **_theme_layout(
            title=titre,
            height=300,
            margin={"l": 10, "r": 10, "t": 40, "b": 10},
            showlegend=False,
        )
    )
    return fig


# ---------------------------------------------------------------------------
# Profils distance (D1..D5) VL / PL par flux
# ---------------------------------------------------------------------------

def barres_distance_vl_pl(
    profil: pd.DataFrame, flux_choisi: str = "Echange"
) -> go.Figure:
    """Barres groupees VL/PL par classe de distance pour un flux donne."""
    sous = profil[profil["flux"] == flux_choisi]
    if sous.empty:
        return go.Figure().update_layout(title=f"Aucune donnee pour {flux_choisi}.")
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=sous["classe_distance_label"],
            y=sous["VKM_VL"],
            name="VL",
            marker_color=COULEUR_VL,
        )
    )
    fig.add_trace(
        go.Bar(
            x=sous["classe_distance_label"],
            y=sous["VKM_PL"],
            name="PL",
            marker_color=COULEUR_PL,
        )
    )
    fig.update_layout(
        **_theme_layout(
            barmode="group",
            title=f"VKM VL / PL par classe de distance - {flux_choisi}",
            xaxis_title="Classe de distance",
            yaxis_title="VKM (km/jour)",
            height=380,
            margin={"l": 40, "r": 10, "t": 50, "b": 40},
        )
    )
    return _appliquer_theme_axes(fig)


def barres_distance_par_flux(profil: pd.DataFrame, mode: str = "VL") -> go.Figure:
    """Barres empilees par classe de distance, separees par flux."""
    col = "VKM_VL" if mode == "VL" else "VKM_PL"
    pivot = profil.pivot_table(
        index="classe_distance_label", columns="flux", values=col, aggfunc="sum"
    ).fillna(0)
    fig = go.Figure()
    couleurs_flux = {"Echange": "#1A237E", "Transit": "#B71C1C", "Interne": "#33691E"}
    for flux in pivot.columns:
        fig.add_trace(
            go.Bar(
                x=pivot.index, y=pivot[flux], name=flux,
                marker_color=couleurs_flux.get(flux, None),
            )
        )
    fig.update_layout(
        **_theme_layout(
            barmode="stack",
            title=f"Repartition {mode} par flux et classe de distance",
            xaxis_title="Classe de distance",
            yaxis_title="VKM (km/jour)",
            height=380,
            margin={"l": 40, "r": 10, "t": 50, "b": 40},
        )
    )
    return _appliquer_theme_axes(fig)


# ---------------------------------------------------------------------------
# Heatmap inter-SERM
# ---------------------------------------------------------------------------

def heatmap_inter_serm(matrice: pd.DataFrame) -> go.Figure:
    """Heatmap des volumes VL entre SERM (origine x destination)."""
    pivot = matrice.pivot(index="serm_O_nom", columns="serm_D_nom", values="volume")
    pivot = pivot.fillna(0)
    fig = go.Figure(
        go.Heatmap(
            z=pivot.values,
            x=list(pivot.columns),
            y=list(pivot.index),
            colorscale="Blues",
            colorbar=dict(title="Volume VL/j"),
            text=[[f"{int(v):,}".replace(",", " ") for v in row] for row in pivot.values],
            texttemplate="%{text}",
            hovertemplate="O: %{y}<br>D: %{x}<br>Volume: %{z:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        **_theme_layout(
            title="Matrice OD inter-SERM (vehicules legers par jour)",
            height=420,
            margin={"l": 40, "r": 10, "t": 50, "b": 40},
            xaxis_title="Destination",
            yaxis_title="Origine",
        )
    )
    return _appliquer_theme_axes(fig)


# ---------------------------------------------------------------------------
# Lignes de desir (top OD)
# ---------------------------------------------------------------------------

def _arc_bezier(
    lat1: float, lon1: float, lat2: float, lon2: float,
    n_pts: int = 24, courbure: float = 0.18,
) -> tuple[list[float], list[float]]:
    """Points d'un arc Bezier quadratique entre deux coordonnees lat/lon.

    Le point de controle est offset perpendiculairement au segment,
    cote gauche (sens O -> D), ce qui cree une courbure consistante.
    """
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    dist = math.sqrt(dlat ** 2 + dlon ** 2)
    if dist < 1e-10:
        return [lat1, lat2], [lon1, lon2]
    mid_lat = (lat1 + lat2) / 2
    mid_lon = (lon1 + lon2) / 2
    # Vecteur perpendiculaire (rotation +90°) normalise
    perp_lat = -dlon / dist * dist * courbure
    perp_lon = dlat / dist * dist * courbure
    ctrl_lat = mid_lat + perp_lat
    ctrl_lon = mid_lon + perp_lon
    lats, lons = [], []
    for i in range(n_pts + 1):
        t = i / n_pts
        u = 1.0 - t
        lats.append(u * u * lat1 + 2 * t * u * ctrl_lat + t * t * lat2)
        lons.append(u * u * lon1 + 2 * t * u * ctrl_lon + t * t * lon2)
    return lats, lons


def _couleur_depuis_volume(v_norm: float, palette: str = "YlOrRd") -> str:
    """Renvoie une couleur CSS hex issue d'une palette Plotly pour v_norm in [0,1]."""
    rgba = px.colors.sample_colorscale(palette, [max(0.05, min(0.98, v_norm))])[0]
    # rgba peut etre "rgb(r,g,b)" ou "#rrggbb" - normaliser en hex
    if rgba.startswith("#"):
        return rgba
    parts = rgba.replace("rgb(", "").replace("rgba(", "").replace(")", "").split(",")
    r, g, b = int(float(parts[0])), int(float(parts[1])), int(float(parts[2]))
    return f"#{r:02x}{g:02x}{b:02x}"


def _libelle_epci_lisible(nom: str, max_len: int = 36) -> str:
    """Raccourcit un nom d'EPCI pour un affichage carte lisible."""
    import re

    s = " ".join(str(nom or "").split())
    if not s:
        return ""
    s = re.sub(
        r"^Communauté\s+(d['’]agglomération|de\s+communes|urbaine)\s+",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"^(CA|CC|CU|Métropole)\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^de\s+", "", s, flags=re.IGNORECASE)
    if " - " in s and len(s) > max_len:
        s = s.split(" - ", 1)[0].strip()
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip(" ,-") + "…"
    return s


def _ajouter_polygones_gdf(
    fig: go.Figure,
    gdf,
    couleur_ligne: str = "#607D8B",
    largeur_ligne: float = 1.0,
    couleur_remplissage: str = "rgba(96,125,139,0.06)",
    hover_col: str | None = None,
    showlegend: bool = False,
    name: str = "",
) -> None:
    """Ajoute les polygones d'un GeoDataFrame en UNE SEULE trace Scattermapbox.

    Toutes les geometries sont concatenees avec des separateurs ``None``
    (meme technique que _coords_lignes pour le reseau routier).
    Cela reduit N traces (ex. 754 communes) a 1 trace, divisant par N
    le temps de serialisation JSON et de rendu navigateur.
    Le hover par polygone est conserve via une liste repetee par point.
    """
    lats_all: list = []
    lons_all: list = []
    hover_all: list = []

    for _, row in gdf.iterrows():
        geom = row.geometry
        hover_text = str(row[hover_col]) if hover_col and hover_col in row.index else ""
        geoms = (
            list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
        )
        for poly in geoms:
            xs, ys = poly.exterior.coords.xy
            pts = list(ys)
            lats_all.extend(pts)
            lons_all.extend(list(xs))
            hover_all.extend([hover_text] * len(pts))
            lats_all.append(None)
            lons_all.append(None)
            hover_all.append(None)
            for interior in poly.interiors:
                xi, yi = interior.coords.xy
                pts_i = list(yi)
                lats_all.extend(pts_i)
                lons_all.extend(list(xi))
                hover_all.extend([hover_text] * len(pts_i))
                lats_all.append(None)
                lons_all.append(None)
                hover_all.append(None)

    if not lats_all:
        return

    fig.add_trace(
        go.Scattermapbox(
            lat=lats_all,
            lon=lons_all,
            mode="lines",
            line=dict(width=largeur_ligne, color=couleur_ligne),
            fill="toself",
            fillcolor=couleur_remplissage,
            hovertext=hover_all,
            hoverinfo="text" if hover_col else "skip",
            showlegend=showlegend,
            name=name,
        )
    )


def _labels_centroides(
    fig: go.Figure,
    gdf,
    col_nom: str,
    taille: int = 10,
    couleur: str = "#37474F",
    libelles: list[str] | None = None,
) -> None:
    """Ajoute des labels texte aux centroides d'un GeoDataFrame.

    ``libelles`` permet de fournir des textes déjà formatés (ex. noms EPCI
    raccourcis) à la place de ``gdf[col_nom]``.
    """
    centroides = gdf.copy()
    # Centroides en projection métrique pour rester dans le polygone
    try:
        gdf_m = centroides.to_crs(2154)
        pts = gdf_m.geometry.representative_point().to_crs(4326)
        centroides["_cx"] = pts.x
        centroides["_cy"] = pts.y
    except Exception:
        centroides["_cx"] = centroides.geometry.centroid.x
        centroides["_cy"] = centroides.geometry.centroid.y

    if libelles is not None:
        centroides = centroides.assign(_label=list(libelles))
        col_txt = "_label"
    else:
        col_txt = col_nom

    centroides = centroides.dropna(subset=["_cx", "_cy", col_txt])
    if centroides.empty:
        return
    fig.add_trace(
        go.Scattermapbox(
            lat=centroides["_cy"].tolist(),
            lon=centroides["_cx"].tolist(),
            mode="text",
            text=centroides[col_txt].astype(str).tolist(),
            textfont=dict(
                size=taille,
                color=couleur,
                family="Source Sans 3, Segoe UI, sans-serif",
            ),
            textposition="middle center",
            hoverinfo="skip",
            showlegend=False,
        )
    )


def _labels_points_flux(
    fig: go.Figure,
    sous: pd.DataFrame,
    col_lon: str,
    col_lat: str,
    col_nom: str,
    taille: int = 10,
    couleur: str = "#37474F",
) -> None:
    """Labels texte aux extremites des flux (noms communes ou EPCI)."""
    pts = (
        sous.dropna(subset=[col_lon, col_lat, col_nom])
        .drop_duplicates(subset=[col_lon, col_lat])
    )
    if pts.empty:
        return
    fig.add_trace(
        go.Scattermapbox(
            lat=pts[col_lat].tolist(),
            lon=pts[col_lon].tolist(),
            mode="text",
            text=pts[col_nom].astype(str).tolist(),
            textfont=dict(size=taille, color=couleur),
            hoverinfo="skip",
            showlegend=False,
        )
    )


def lignes_de_desir(
    top_od: pd.DataFrame,
    perimetres_gdf,
    style_mapbox: str,
    code_serm: int,
    typologie: str = "interne_serm",
    nb_max: int = 30,
    seuil_pct_max: float = 2.0,
    communes_gdf=None,
    epci_gdf=None,
) -> go.Figure:
    """Carte des flux OD avec arcs Bezier courbes.

    La taille (épaisseur) ET la couleur représentent l'intensité du flux.
    Les flux inférieurs à ``seuil_pct_max`` % du maximum sont supprimés.

    Couches géographiques optionnelles :
    * ``communes_gdf`` : limites communales du SERM (flux internes).
    * ``epci_gdf``     : limites EPCI — toujours affichées pour le SERM
      sélectionné (contours + libellés lisibles) ; les EPCI hors SERM
      impliqués dans les échanges sont ajoutés en surcouche.
    * ``perimetres_gdf`` : périmètres SERM (toujours affiché si fourni).

    ``top_od`` peut provenir de ``top_od_vl_par_serm.parquet`` (zones OPSAM)
    ou de ``top_od_com_serm.parquet`` (communes / EPCI).
    """
    sous = top_od[
        (top_od["serm"] == code_serm) & (top_od["typologie"] == typologie)
    ].nlargest(nb_max, "volume").copy()

    if sous.empty:
        return go.Figure().update_layout(
            title=f"Aucun flux a afficher pour {info_serm(code_serm)['nom']}."
        )

    sous = sous.dropna(subset=["lon_O", "lat_O", "lon_D", "lat_D"])
    if sous.empty:
        return go.Figure().update_layout(title="Coordonnees manquantes.")

    v_max = float(sous["volume"].max() or 1.0)
    seuil_abs = v_max * seuil_pct_max / 100.0
    sous = sous[sous["volume"] >= seuil_abs]
    if sous.empty:
        return go.Figure().update_layout(title="Tous les flux sous le seuil.")

    v_max = float(sous["volume"].max() or 1.0)

    # Choisir la colonne de libelle disponible
    col_nom_O = "nom_O" if "nom_O" in sous.columns else "nom_com_O"
    col_nom_D = "nom_D" if "nom_D" in sous.columns else "nom_com_D"

    couleur_serm = info_serm(code_serm)["couleur"]
    est_interne = (typologie == "interne_serm")
    est_echange = (typologie in ("echange_emis", "echange_recus"))

    fig = go.Figure()

    # -- Couche 0 : contours + noms des EPCI du SERM -------------------------
    epci_serm = None
    if epci_gdf is not None and len(epci_gdf) > 0:
        if "code_serm" in epci_gdf.columns:
            epci_serm = epci_gdf[epci_gdf["code_serm"] == code_serm].copy()
        else:
            epci_serm = epci_gdf.copy()
        if epci_serm is not None and not epci_serm.empty:
            _ajouter_polygones_gdf(
                fig, epci_serm,
                couleur_ligne="#0E2A47",
                largeur_ligne=1.8,
                couleur_remplissage="rgba(14,42,71,0.04)",
                hover_col="NOM",
                showlegend=True,
                name="EPCI",
            )
            libelles_epci = [
                _libelle_epci_lisible(n) for n in epci_serm["NOM"].tolist()
            ]
            # Halo clair puis texte foncé pour une meilleure lisibilité
            _labels_centroides(
                fig, epci_serm, "NOM",
                taille=13, couleur="#FFFFFF",
                libelles=libelles_epci,
            )
            _labels_centroides(
                fig, epci_serm, "NOM",
                taille=12, couleur="#0E2A47",
                libelles=libelles_epci,
            )

    # -- Couche 1 : limites communales (flux internes) -----------------------
    if est_interne and communes_gdf is not None:
        _ajouter_polygones_gdf(
            fig, communes_gdf,
            couleur_ligne="#90A4AE",
            largeur_ligne=0.45,
            couleur_remplissage="rgba(144,164,174,0.03)",
            hover_col="NOM_COM",
        )
        # Labels communes impliquées (discrets — les EPCI portent le contexte)
        noms_o = set(sous[col_nom_O].dropna().unique())
        noms_d = set(sous[col_nom_D].dropna().unique())
        noms_impliques = noms_o | noms_d
        communes_labels = communes_gdf[
            communes_gdf["NOM_COM"].isin(noms_impliques)
        ]
        if not communes_labels.empty:
            _labels_centroides(
                fig, communes_labels, "NOM_COM",
                taille=9, couleur="#546E7A",
            )

    # -- Couche 2 : échanges (communes SERM + EPCI externes) -----------------
    if est_echange:
        if communes_gdf is not None:
            codes_com = set()
            if typologie == "echange_emis" and "com_O" in sous.columns:
                codes_com = set(sous["com_O"].astype(str).str.replace(
                    r"\.0$", "", regex=True
                ))
            elif typologie == "echange_recus" and "com_D" in sous.columns:
                codes_com = set(sous["com_D"].astype(str).str.replace(
                    r"\.0$", "", regex=True
                ))
            if codes_com:
                com_sous = communes_gdf[
                    communes_gdf["INSEE_COM"].astype(str).isin(codes_com)
                ]
                if not com_sous.empty:
                    _ajouter_polygones_gdf(
                        fig, com_sous,
                        couleur_ligne="#78909C",
                        largeur_ligne=0.7,
                        couleur_remplissage="rgba(120,144,156,0.05)",
                        hover_col="NOM_COM",
                    )

        if epci_gdf is not None:
            codes_epci_impliques: set[str] = set()
            if typologie == "echange_emis" and "com_D" in sous.columns:
                codes_epci_impliques = set(
                    sous["com_D"].astype(str).str.replace(r"\.0$", "", regex=True)
                )
            elif typologie == "echange_recus" and "com_O" in sous.columns:
                codes_epci_impliques = set(
                    sous["com_O"].astype(str).str.replace(r"\.0$", "", regex=True)
                )

            # Exclure les EPCI déjà dessinés (ceux du SERM)
            codes_serm = set()
            if epci_serm is not None and not epci_serm.empty:
                codes_serm = set(
                    epci_serm["CODE_SIREN"].astype(str).str.replace(
                        r"\.0$", "", regex=True
                    )
                )
            codes_ext = codes_epci_impliques - codes_serm

            if codes_ext:
                epci_sous = epci_gdf[
                    epci_gdf["CODE_SIREN"].astype(str).str.replace(
                        r"\.0$", "", regex=True
                    ).isin(codes_ext)
                ]
            else:
                epci_sous = epci_gdf.iloc[0:0]

            if not epci_sous.empty:
                _ajouter_polygones_gdf(
                    fig, epci_sous,
                    couleur_ligne="#E07010",
                    largeur_ligne=1.6,
                    couleur_remplissage="rgba(224,112,16,0.08)",
                    hover_col="NOM",
                    showlegend=True,
                    name="EPCI hors SERM",
                )
                libelles_ext = [
                    _libelle_epci_lisible(n) for n in epci_sous["NOM"].tolist()
                ]
                _labels_centroides(
                    fig, epci_sous, "NOM",
                    taille=12, couleur="#FFFFFF",
                    libelles=libelles_ext,
                )
                _labels_centroides(
                    fig, epci_sous, "NOM",
                    taille=11, couleur="#BF360C",
                    libelles=libelles_ext,
                )

        # Labels aux extremites des flux (noms, pas codes)
        if typologie == "echange_emis":
            _labels_points_flux(
                fig, sous, "lon_O", "lat_O", col_nom_O,
                taille=9, couleur="#37474F",
            )
            _labels_points_flux(
                fig, sous, "lon_D", "lat_D", col_nom_D,
                taille=10, couleur="#E65100",
            )
        elif typologie == "echange_recus":
            _labels_points_flux(
                fig, sous, "lon_O", "lat_O", col_nom_O,
                taille=10, couleur="#E65100",
            )
            _labels_points_flux(
                fig, sous, "lon_D", "lat_D", col_nom_D,
                taille=9, couleur="#37474F",
            )

    # -- Couche 3 : contour SERM (visible, coloré) ---------------------------
    if perimetres_gdf is not None:
        sub = perimetres_gdf[perimetres_gdf["code_serm"] == code_serm]
        for _, row in sub.iterrows():
            geom = row.geometry
            geoms = (
                list(geom.geoms)
                if geom.geom_type == "MultiPolygon"
                else [geom]
            )
            for poly in geoms:
                xs, ys = poly.exterior.coords.xy
                lats = list(ys) + [None]
                lons = list(xs) + [None]
                for interior in poly.interiors:
                    xi, yi = interior.coords.xy
                    lats += list(yi) + [None]
                    lons += list(xi) + [None]
                fig.add_trace(
                    go.Scattermapbox(
                        lat=lats, lon=lons,
                        mode="lines",
                        line=dict(width=3.0, color=couleur_serm),
                        hoverinfo="skip",
                        showlegend=False,
                    )
                )

    # -- Couche 4 : arcs Bezier ----------------------------------------------
    sous_sorted = sous.sort_values("volume")
    for _, r in sous_sorted.iterrows():
        v = float(r["volume"])
        v_norm = v / v_max
        couleur = _couleur_depuis_volume(v_norm)
        largeur = 0.8 + 7.0 * v_norm ** 0.55

        arc_lats, arc_lons = _arc_bezier(
            float(r["lat_O"]), float(r["lon_O"]),
            float(r["lat_D"]), float(r["lon_D"]),
            courbure=0.20,
        )
        nom_o = r.get(col_nom_O) or "?"
        nom_d = r.get(col_nom_D) or "?"
        hover = (
            f"<b>{nom_o}</b> → <b>{nom_d}</b>"
            f"<br>Volume VL/j : <b>{v:,.0f}</b>"
            f"<br>{v / v_max * 100:.1f} % du flux max"
        ).replace(",", "\u202f")

        fig.add_trace(
            go.Scattermapbox(
                lat=arc_lats, lon=arc_lons,
                mode="lines",
                line=dict(width=largeur, color=couleur),
                hovertext=hover, hoverinfo="text",
                showlegend=False,
            )
        )

    # -- Couche 5 : marqueurs origine / destination --------------------------
    for col_lon, col_lat, col_nom in (
        ("lon_O", "lat_O", col_nom_O),
        ("lon_D", "lat_D", col_nom_D),
    ):
        pts = sous.dropna(subset=[col_lon, col_lat]).copy()
        pts = pts.drop_duplicates(subset=[col_lon, col_lat])
        if pts.empty:
            continue
        v_pts_norm = pts["volume"].values / v_max
        couleurs_pts = [_couleur_depuis_volume(vn) for vn in v_pts_norm]
        noms = pts[col_nom].fillna("?").tolist()
        tailles = [6 + 5 * float(vn) ** 0.5 for vn in v_pts_norm]
        fig.add_trace(
            go.Scattermapbox(
                lat=pts[col_lat].tolist(), lon=pts[col_lon].tolist(),
                mode="markers",
                marker=dict(size=tailles, color=couleurs_pts),
                hovertext=noms, hoverinfo="text",
                showlegend=False,
            )
        )

    # -- Centrage carte -------------------------------------------------------
    if perimetres_gdf is not None:
        sub_peri = perimetres_gdf[perimetres_gdf["code_serm"] == code_serm]
        centre = _centre_geometrique(sub_peri)
    else:
        lats_all = sous[["lat_O", "lat_D"]].stack().dropna()
        lons_all = sous[["lon_O", "lon_D"]].stack().dropna()
        centre = {
            "lat": float(lats_all.mean()) if len(lats_all) else 47.2,
            "lon": float(lons_all.mean()) if len(lons_all) else 5.5,
        }

    zoom = 8.5 if est_interne else 7.2
    fig.update_layout(
        **_theme_layout(
            mapbox_style=style_mapbox,
            mapbox_center=centre,
            mapbox_zoom=zoom,
            margin={"r": 5, "t": 40, "l": 5, "b": 5},
            height=660,
            title=(
                f"Top {len(sous)} flux VL "
                f"({typologie.replace('_', ' ')}) — {info_serm(code_serm)['nom']}"
            ),
        )
    )
    return fig


# ---------------------------------------------------------------------------
# Comparatif inter-SERM (barres groupees)
# ---------------------------------------------------------------------------

def barres_comparatives_serm(
    metriques: pd.DataFrame, indicateur: str, titre: str
) -> go.Figure:
    """Barres comparatives entre SERM pour un indicateur donne."""
    sous = metriques[metriques["code_serm"] > 0].copy()
    sous["couleur"] = sous["code_serm"].map(
        {c: info_serm(c)["couleur"] for c in sous["code_serm"].unique()}
    )
    fig = go.Figure(
        go.Bar(
            x=sous["nom_serm"], y=sous[indicateur],
            marker_color=sous["couleur"],
            text=[f"{v:,.1f}" for v in sous[indicateur]],
            textposition="outside",
        )
    )
    fig.update_layout(
        **_theme_layout(
            title=titre,
            height=340,
            margin={"l": 40, "r": 10, "t": 50, "b": 40},
            showlegend=False,
            yaxis_title=indicateur,
        )
    )
    return _appliquer_theme_axes(fig)


# ---------------------------------------------------------------------------
# Tableau echanges EPCI
# ---------------------------------------------------------------------------

def heatmap_epci_x_epci(
    echanges: pd.DataFrame, code_serm: int, typologie: str = "interne_serm",
    top_n_epci: int = 15,
) -> go.Figure:
    """Heatmap des volumes VL entre EPCI pour un SERM donne.

    Les flux internes (epci_O == epci_D) sont conserves dans la matrice
    mais distingues visuellement : cellules grises, exclus de l'echelle
    de couleur (zmin/zmax calcules sur les echanges inter-EPCI uniquement).

    Utilise les colonnes ``epci_O_nom`` / ``epci_D_nom`` si disponibles.
    """
    import numpy as np

    sous = echanges[
        (echanges["serm"] == code_serm) & (echanges["typologie"] == typologie)
    ].copy()
    if sous.empty:
        return go.Figure().update_layout(
            title=f"Aucune donnee pour {info_serm(code_serm)['nom']}."
        )

    # Colonnes de labels : noms si disponibles, codes sinon
    col_o = "epci_O_nom" if "epci_O_nom" in sous.columns else "epci_O"
    col_d = "epci_D_nom" if "epci_D_nom" in sous.columns else "epci_D"

    top_epci = (
        pd.concat([sous["epci_O"], sous["epci_D"]])
        .value_counts().head(top_n_epci).index.tolist()
    )
    sous = sous[sous["epci_O"].isin(top_epci) & sous["epci_D"].isin(top_epci)]

    # Pivot sur les codes pour l'agrégation, index/colonnes = noms
    pivot_codes = sous.pivot_table(
        index="epci_O", columns="epci_D", values="volume", aggfunc="sum"
    ).fillna(0)

    # Correspondance code -> nom (premiere occurrence)
    map_o = sous.drop_duplicates("epci_O").set_index("epci_O")[col_o].to_dict()
    map_d = sous.drop_duplicates("epci_D").set_index("epci_D")[col_d].to_dict()
    pivot_noms = pivot_codes.rename(index=map_o, columns=map_d)

    rows = list(pivot_noms.index)
    cols = list(pivot_noms.columns)
    z_full = pivot_noms.values.astype(float)

    # Masquer les flux internes (diagonale) dans la matrice de couleur :
    # NaN → cellule blanche, hors du calcul de l'echelle.
    z_plot = z_full.copy()
    diagonale: list[tuple[int, int]] = []  # (idx_row, idx_col) des cellules internes
    for i, label in enumerate(rows):
        if label in cols:
            j = cols.index(label)
            z_plot[i, j] = np.nan
            diagonale.append((i, j))

    # Echelle calibree sur les echanges inter-EPCI uniquement
    valeurs_hors_diag = z_plot[~np.isnan(z_plot)]
    zmin = float(valeurs_hors_diag.min()) if len(valeurs_hors_diag) > 0 else 0.0
    zmax = float(valeurs_hors_diag.max()) if len(valeurs_hors_diag) > 0 else 1.0

    fig = go.Figure(
        go.Heatmap(
            z=z_plot,
            x=cols,
            y=rows,
            colorscale="Viridis",
            zmin=zmin,
            zmax=zmax,
            colorbar=dict(title="VL/j"),
            # customdata transporte les valeurs reelles pour le hover
            customdata=z_full,
            hovertemplate=(
                "Origine : %{y}<br>Destination : %{x}"
                "<br>Volume : %{customdata:,.0f} VL/j<extra></extra>"
            ),
        )
    )

    # Cellules diagonales : rectangle gris + valeur en annotation
    for i, j in diagonale:
        val = z_full[i, j]
        # Rectangle gris (layer="above" pour couvrir la cellule blanche NaN)
        fig.add_shape(
            type="rect",
            xref="x", yref="y",
            x0=j - 0.5, x1=j + 0.5,
            y0=i - 0.5, y1=i + 0.5,
            fillcolor="#BDBDBD",
            line=dict(color="white", width=1),
            layer="above",
        )
        # Valeur du flux interne inscrite dans la cellule
        fig.add_annotation(
            x=cols[j], y=rows[i],
            text=f"{val:,.0f}",
            showarrow=False,
            font=dict(size=8, color="#424242"),
            xref="x", yref="y",
        )

    fig.update_layout(
        **_theme_layout(
            title=(
                f"Échanges EPCI × EPCI — {info_serm(code_serm)['nom']}"
                f" ({typologie})"
                "<br><sup style='color:#9E9E9E'>"
                "Cellules grises = flux internes (hors echelle de couleur)"
                "</sup>"
            ),
            xaxis_title="EPCI destination",
            yaxis_title="EPCI origine",
            xaxis=dict(tickangle=-40),
            height=560,
            margin={"l": 220, "r": 20, "t": 80, "b": 200},
        )
    )
    return _appliquer_theme_axes(fig)
