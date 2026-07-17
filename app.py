"""app.py.

Plateforme Streamlit d'analyse inter-SERM (Dijon, Nord Franche-Comte,
Besancon) - DREAL Bourgogne-Franche-Comte.

Pages :
  1. Vue d'ensemble inter-SERM (KPI, carte BFC, comparatif)
  2. Socle par SERM (carte trafic, Sankey, donut, profils distance)
  3. Corridors & top flux OD VL (lignes de desir)
  4. Echanges inter-SERM & EPCI (matrices, centre/periph)
  5. Contexte enrichi (MCP datagouv)
  6. Reglages (perimetres SERM, regeneration du bundle)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Enregistrer kaleido pour fig.to_image (PDF) - silencieux si absent.
try:
    import kaleido  # noqa: F401
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from auth import deconnecter, verifier_authentification  # noqa: E402
from config.territoire_loader import cfg, codes_zones  # noqa: E402

from data_loader import (  # noqa: E402
    CLASSES_DISTANCE,
    FLUX_LABELS,
    SERM_INFO,
    calculer_metriques_serm,
    charger_centroides_zones,
    charger_communes_serm,
    charger_echanges_epci,
    charger_limites_epci,
    charger_matrice_inter_serm,
    charger_perimetres_serm,
    charger_profils_avatar,
    charger_reseau_serm,
    charger_stations_avatar,
    charger_synthese_serm,
    charger_top_od_communes,
    charger_top_od_vl,
    info_serm,
    profil_distance_vl_pl,
    repartition_par_voie,
    repartition_vl_pl_par_flux,
    signature_bundle,
)
from visualizations import (  # noqa: E402
    barres_comparatives_serm,
    barres_distance_par_flux,
    barres_distance_vl_pl,
    carte_trafic_serm,
    carte_vue_ensemble,
    donut_vl_pl,
    heatmap_epci_x_epci,
    heatmap_inter_serm,
    lignes_de_desir,
    sankey_vl_pl_par_voie,
)
from visualizations_avatar import (  # noqa: E402
    carte_stations_avatar,
    profil_horaire_avatar,
)
from pdf_export import (  # noqa: E402
    generer_rapport_global,
    generer_rapport_serm,
)
import datagouv_context  # noqa: E402


# ---------------------------------------------------------------------------
# Configuration page
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Plateforme inter-SERM - OPSAM",
    page_icon=":material/hub:",
    layout="wide",
    initial_sidebar_state="expanded",
)

css_path = Path(__file__).parent / "style.css"
if css_path.exists():
    st.markdown(
        f"<style>{css_path.read_text(encoding='utf-8')}</style>",
        unsafe_allow_html=True,
    )

# Verification d'acces : stoppe le rendu si non authentifie.
if not verifier_authentification():
    st.stop()


def _get_mapbox_token() -> str:
    """Token Mapbox optionnel (variable d'environnement ou st.secrets)."""
    t = (os.environ.get("MAPBOX_TOKEN") or "").strip()
    if t:
        return t
    try:
        return (st.secrets.get("MAPBOX_TOKEN") or "").strip()
    except Exception:
        return ""


def _style_mapbox() -> str:
    return "carto-positron" if _get_mapbox_token() else "open-street-map"


def _fmt_milliers(val) -> str:
    if pd.isna(val):
        return "-"
    return f"{int(round(float(val))):,}".replace(",", " ")


# ---------------------------------------------------------------------------
# Chargements (caches)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Chargement de la synthese SERM...")
def _synthese(signature: float):
    del signature  # signature seulement pour invalidation cache
    return charger_synthese_serm()


@st.cache_data(show_spinner="Calcul des metriques par SERM...")
def _metriques(signature: float):
    del signature
    return calculer_metriques_serm(charger_synthese_serm())


@st.cache_data(show_spinner="Chargement des perimetres...")
def _perimetres(signature: float):
    del signature
    return charger_perimetres_serm()


@st.cache_data(show_spinner="Chargement du reseau routier...")
def _reseau(slug: str, signature: float):
    del signature
    return charger_reseau_serm(slug)


@st.cache_data(show_spinner="Generation de la carte reseau...", max_entries=6)
def _carte_trafic(
    code_serm: int,
    metrique: str,
    style_mapbox: str,
    signature: float,
):
    """Cache la figure Plotly de la carte trafic (couteuse a generer).

    Le cache est invalide quand signature ou metrique change.
    max_entries=6 : 3 SERM x 2 metriques.
    """
    del signature
    inf = SERM_INFO[code_serm]
    reseau = charger_reseau_serm(inf["slug"])
    perimetres = charger_perimetres_serm()
    peri = perimetres[perimetres["code_serm"] == code_serm]
    return carte_trafic_serm(
        reseau, peri, metrique, style_mapbox,
        titre=f"{inf['nom']} — {metrique}",
    )


@st.cache_data(show_spinner="Chargement de la matrice inter-SERM...")
def _matrice(signature: float):
    del signature
    return charger_matrice_inter_serm()


@st.cache_data(show_spinner="Chargement des echanges EPCI...")
def _echanges(signature: float):
    del signature
    return charger_echanges_epci()


@st.cache_data(show_spinner="Chargement des top OD VL...")
def _top_od(signature: float):
    del signature
    return charger_top_od_vl()


@st.cache_data(show_spinner="Chargement des flux agreges communes/EPCI...")
def _top_od_communes(signature: float):
    del signature
    return charger_top_od_communes()


@st.cache_data(show_spinner="Chargement des centroides...")
def _centroides(signature: float):
    del signature
    return charger_centroides_zones()


@st.cache_data(
    show_spinner="Generation de la carte des flux...",
    max_entries=18,  # 3 SERM x 3 typologies x 2 nb_max_buckets
)
def _lignes_de_desir(
    code_serm: int,
    typologie: str,
    nb_max: int,
    seuil_pct: float,
    style_mapbox: str,
    signature: float,
):
    """Cache la figure lignes de desir (754 polygones communes = couteux)."""
    del signature
    communes_gdf = charger_communes_serm(code_serm)
    epci_gdf = charger_limites_epci()
    perimetres = charger_perimetres_serm()
    try:
        top_od = charger_top_od_communes()
    except FileNotFoundError:
        top_od = charger_top_od_vl()
    return lignes_de_desir(
        top_od, perimetres, style_mapbox,
        code_serm=code_serm, typologie=typologie,
        nb_max=nb_max, seuil_pct_max=float(seuil_pct),
        communes_gdf=communes_gdf, epci_gdf=epci_gdf,
    )


@st.cache_data(show_spinner="Chargement des limites communales...")
def _communes_serm(code_serm: int, signature: float):
    del signature
    return charger_communes_serm(code_serm)


@st.cache_data(show_spinner="Chargement des limites EPCI...")
def _limites_epci(signature: float):
    del signature
    return charger_limites_epci()


# ---------------------------------------------------------------------------
# Sidebar : navigation + meta donnees
# ---------------------------------------------------------------------------

with st.sidebar:
    _cfg = cfg()
    st.markdown(
        f"<h1 style='color:#E0E0E0; font-size:1.4rem; margin-bottom:0;'>"
        f"{_cfg.plateforme.nom}</h1>"
        f"<p style='color:#90A4AE; font-size:0.85rem; margin-top:4px;'>"
        f"{_cfg.plateforme.description}</p>",
        unsafe_allow_html=True,
    )
    st.divider()

    try:
        signature = signature_bundle()
    except Exception as e:
        st.error(f"Bundle indisponible : {e}")
        st.stop()

    PAGES = {
        "Vue d'ensemble": "bar_chart",
        "Socle par SERM": "search",
        "Corridors & top flux OD": "route",
        "Echanges inter-SERM & EPCI": "compare_arrows",
        "Comptages AVATAR": "sensors",
        "Contexte enrichi (datagouv)": "hub",
        "Reglages": "settings",
    }
    page = st.radio(
        "Navigation",
        list(PAGES.keys()),
        index=0,
        captions=[
            "KPI compares + carte BFC",
            "Zoom sur un SERM (carte, Sankey, distances)",
            "Top flux VL internes / emis / recus",
            "Matrices OD inter-SERM et par EPCI",
            "Profils horaires DIR Est & DIR Centre-Est",
            "Donnees contextuelles INSEE / SNCF",
            "Perimetres, regeneration du bundle",
        ],
    )

    st.divider()
    with st.expander("Bundle de donnees", expanded=False):
        from data_loader import data_dir
        st.code(str(data_dir()), language=None)
        st.caption(f"Signature (timestamps cumules) : {signature:.0f}")

    # Bouton de deconnexion (visible uniquement si mot de passe configure).
    from auth import _hash_attendu
    if _hash_attendu():
        st.divider()
        if st.button(":material/logout: Se deconnecter", use_container_width=True):
            deconnecter()


# ---------------------------------------------------------------------------
# Pre-chargement commun
# ---------------------------------------------------------------------------

try:
    df_synthese = _synthese(signature)
    metriques = _metriques(signature)
    perimetres_gdf = _perimetres(signature)
except Exception as exc:
    st.error(f"Erreur de chargement : {exc}")
    st.stop()


# =========================================================================
# Page 1 : Vue d'ensemble
# =========================================================================

if page == "Vue d'ensemble":
    st.header("Vue d'ensemble des trois SERM de Bourgogne-Franche-Comte")
    st.caption(
        "Indicateurs agreges issus de la synthese OPSAM Ref2024, avec les "
        "volumes VL reconstitues par soustraction Total - PL (chargés + vides)."
    )

    _codes_actifs = codes_zones(inclure_hors_serm=False)
    sous = metriques[metriques["code_serm"].isin(_codes_actifs)]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("VKM VL (k km/j)", _fmt_milliers(sous["VKM_VL_milliers"].sum()))
    k2.metric("% Transit moyen", f"{sous['pct_transit'].mean():.1f} %")
    k3.metric("% Interne moyen", f"{sous['pct_interne'].mean():.1f} %")
    k4.metric("Reseau cumule (km)", _fmt_milliers(sous["DISTANCE"].sum()))

    st.markdown("")
    col_sel, _ = st.columns([1, 3])
    with col_sel:
        choix_metrique = st.selectbox(
            "Colorer la carte par",
            [
                "VKM_VL_milliers", "pct_transit", "pct_echange",
                "pct_interne", "pct_longue_distance",
            ],
            format_func=lambda x: {
                "pct_transit": "% Transit (VL)",
                "pct_echange": "% Echange (VL)",
                "pct_interne": "% Interne (VL)",
                "VKM_VL_milliers": "VKM VL (k km/j)",
                "pct_longue_distance": "% Longue distance (>200 km)",
            }[x],
        )

    fig_c = carte_vue_ensemble(
        perimetres_gdf, metriques, choix_metrique, _style_mapbox(),
        libelle_indicateur=choix_metrique,
    )
    st.plotly_chart(fig_c, use_container_width=True)

    st.subheader("Tableau de synthese")
    cols = [
        "nom_serm", "VKM_VL_milliers",
        "pct_transit", "pct_echange", "pct_interne",
        "pct_longue_distance", "DISTANCE",
    ]
    df_tab = sous[cols].copy()
    df_tab = df_tab.rename(columns={
        "nom_serm": "SERM",
        "VKM_VL_milliers": "VKM VL (k km/j)",
        "pct_transit": "% Transit",
        "pct_echange": "% Echange",
        "pct_interne": "% Interne",
        "pct_longue_distance": "% Long. dist.",
        "DISTANCE": "Reseau (km)",
    })
    col_cfg = {
        c: st.column_config.NumberColumn(format="%.1f")
        for c in df_tab.columns if c not in ("SERM",)
    }
    col_cfg["Reseau (km)"] = st.column_config.NumberColumn(format="%d")
    st.dataframe(
        df_tab, use_container_width=True, hide_index=True, column_config=col_cfg
    )

    st.subheader("Comparatifs inter-SERM")
    col_a, col_b = st.columns(2)
    with col_a:
        st.plotly_chart(
            barres_comparatives_serm(metriques, "VKM_VL_milliers", "VKM VL (k km/j) par SERM"),
            use_container_width=True,
        )
    with col_b:
        st.plotly_chart(
            barres_comparatives_serm(metriques, "pct_interne", "% Interne (VL) par SERM"),
            use_container_width=True,
        )

    col_c, col_d = st.columns(2)
    with col_c:
        st.plotly_chart(
            barres_comparatives_serm(metriques, "pct_transit", "% Transit (VL) par SERM"),
            use_container_width=True,
        )
    with col_d:
        st.plotly_chart(
            barres_comparatives_serm(metriques, "pct_longue_distance", "% Longue distance (>200 km) par SERM"),
            use_container_width=True,
        )

    st.divider()
    col_e1, col_e2 = st.columns([1, 1])
    with col_e1:
        csv_bytes = df_tab.to_csv(index=False, sep=";").encode("utf-8-sig")
        st.download_button(
            ":material/download: Exporter la synthese (CSV)",
            csv_bytes,
            "synthese_inter_serm.csv",
            "text/csv",
        )
    with col_e2:
        if st.button(":material/picture_as_pdf: Rapport PDF global"):
            with st.spinner("Generation du PDF..."):
                try:
                    fig_carte = carte_vue_ensemble(
                        perimetres_gdf, metriques, "pct_pl", _style_mapbox(),
                        libelle_indicateur="% PL",
                    )
                    fig_heat = heatmap_inter_serm(_matrice(signature))
                    pdf_bytes = generer_rapport_global(metriques, fig_carte, fig_heat)
                    st.session_state["dl_pdf_global"] = pdf_bytes
                except Exception as exc:
                    st.error(f"Erreur : {exc}")
        if st.session_state.get("dl_pdf_global"):
            st.download_button(
                "Telecharger le PDF",
                st.session_state["dl_pdf_global"],
                file_name="rapport_inter_serm.pdf",
                mime="application/pdf",
            )


# =========================================================================
# Page 2 : Socle par SERM
# =========================================================================

elif page == "Socle par SERM":
    st.header("Socle de connaissance par SERM")

    col_sel, _ = st.columns([1, 3])
    with col_sel:
        code = st.selectbox(
            "SERM",
            codes_zones(inclure_hors_serm=False),
            format_func=lambda c: SERM_INFO[c]["nom"],
        )
    info = info_serm(code)
    df_serm = df_synthese[df_synthese["code_serm"] == code]
    metr_row = metriques[metriques["code_serm"] == code].iloc[0]

    st.markdown(
        f"<span class='serm-badge serm-{info['slug']}'>{info['nom']}</span>",
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("VKM VL (k km/j)", _fmt_milliers(metr_row["VKM_VL_milliers"]))
    c2.metric("% Transit", f"{metr_row['pct_transit']:.1f} %")
    c3.metric("% Echange", f"{metr_row['pct_echange']:.1f} %")
    c4.metric("% Interne", f"{metr_row['pct_interne']:.1f} %")

    st.divider()

    st.subheader("Carte de trafic sur le reseau du SERM")
    col_sel_carte, _ = st.columns([1, 3])
    with col_sel_carte:
        metrique_carte = st.selectbox(
            "Indicateur",
            ["VL_jour", "TMJA_P"],
            format_func=lambda x: {
                "TMJA_P": "TMJA tous vehicules (modelise)",
                "VL_jour": "Vehicules Legers / jour",
            }[x],
        )
    try:
        fig_carte_serm = _carte_trafic(
            code, metrique_carte, _style_mapbox(), signature
        )
        st.plotly_chart(fig_carte_serm, use_container_width=True)
    except Exception as exc:
        fig_carte_serm = None
        st.warning(f"Carte indisponible : {exc}")

    st.divider()

    col_sankey, col_donut = st.columns([3, 1])
    with col_sankey:
        fig_sankey = sankey_vl_pl_par_voie(df_serm, f"Sankey {info['nom']}")
        st.plotly_chart(fig_sankey, use_container_width=True)
    with col_donut:
        rep = repartition_vl_pl_par_flux(df_serm)
        fig_donut = donut_vl_pl(rep, "Part VL / PL (VKM)")
        st.plotly_chart(fig_donut, use_container_width=True)

    st.divider()

    st.subheader("Profils VL par classes de distance")
    profil = profil_distance_vl_pl(df_serm)
    col_a, col_b = st.columns(2)
    with col_a:
        flux = st.selectbox("Type de flux", list(FLUX_LABELS.values()), index=0)
        st.plotly_chart(
            barres_distance_vl_pl(profil, flux), use_container_width=True
        )
    with col_b:
        st.plotly_chart(
            barres_distance_par_flux(profil, "VL"), use_container_width=True
        )

    st.divider()
    if st.button(":material/picture_as_pdf: Rapport PDF du SERM"):
        with st.spinner("Generation du PDF..."):
            try:
                pdf_bytes = generer_rapport_serm(
                    info, metr_row,
                    fig_carte_serm,
                    fig_sankey,
                    fig_donut,
                    barres_distance_vl_pl(profil, "Echange"),
                )
                st.session_state[f"dl_pdf_{info['slug']}"] = pdf_bytes
            except Exception as exc:
                st.error(f"Erreur : {exc}")
    if st.session_state.get(f"dl_pdf_{info['slug']}"):
        st.download_button(
            f"Telecharger le rapport PDF - {info['nom']}",
            st.session_state[f"dl_pdf_{info['slug']}"],
            file_name=f"rapport_{info['slug']}.pdf",
            mime="application/pdf",
        )


# =========================================================================
# Page 3 : Corridors & top flux OD VL
# =========================================================================

elif page == "Corridors & top flux OD":
    st.header("Corridors a enjeux - flux VL par commune / EPCI")
    st.caption(
        "Arcs proportionnels aux flux VL (taille + couleur). "
        "Flux internes agreges a la commune (zones IRIS regroupees). "
        "Flux externes agreges a l'EPCI de destination/origine."
    )

    col_serm, col_typo, col_nb, col_seuil = st.columns([1, 1, 1, 1])
    with col_serm:
        code = st.selectbox(
            "SERM", codes_zones(inclure_hors_serm=False),
            format_func=lambda c: SERM_INFO[c]["nom"],
            key="code_serm_corridors",
        )
    with col_typo:
        typo = st.selectbox(
            "Typologie",
            ["interne_serm", "echange_emis", "echange_recus"],
            format_func=lambda x: {
                "interne_serm": "Flux internes (communes)",
                "echange_emis": "Flux emis vers EPCI ext.",
                "echange_recus": "Flux recus depuis EPCI ext.",
            }[x],
        )
    with col_nb:
        nb_max = st.slider("Nb de flux max", 5, 300, 30)
    with col_seuil:
        seuil_pct = st.slider(
            "Seuil min (% du max)", 0, 20, 3,
            help="Supprimer les flux < N % du flux maximum affiche.",
        )

    fig_lignes = _lignes_de_desir(
        code, typo, nb_max, float(seuil_pct), _style_mapbox(), signature
    )

    st.plotly_chart(fig_lignes, use_container_width=True)

    st.subheader(f"Top {nb_max} flux — {info_serm(code)['nom']} ({typo})")
    top_od_com = _top_od_communes(signature)
    try:
        sous = top_od_com[
            (top_od_com["serm"] == code) & (top_od_com["typologie"] == typo)
        ].nlargest(nb_max, "volume").copy()
        col_nom_O = "nom_O" if "nom_O" in sous.columns else "nom_com_O"
        col_nom_D = "nom_D" if "nom_D" in sous.columns else "nom_com_D"
        affichage = sous[[col_nom_O, col_nom_D, "volume"]].rename(columns={
            col_nom_O: "Origine",
            col_nom_D: "Destination",
            "volume": "Volume VL/j",
        })
        v_max_tab = float(sous["volume"].max() or 1)
        affichage["% du max"] = (
            sous["volume"] / v_max_tab * 100
        ).round(1).values
        st.dataframe(
            affichage, use_container_width=True, hide_index=True,
            column_config={
                "Volume VL/j": st.column_config.NumberColumn(format="%.0f"),
                "% du max": st.column_config.NumberColumn(format="%.1f %%"),
            },
        )
        col_dl, _ = st.columns([1, 3])
        with col_dl:
            csv_bytes = affichage.to_csv(
                index=False, sep=";", encoding="utf-8-sig",
            ).encode("utf-8-sig")
            st.download_button(
                ":material/download: Export CSV",
                csv_bytes,
                f"top_flux_{info_serm(code)['slug']}_{typo}.csv",
                "text/csv",
            )
    except Exception as exc:
        st.info(f"Tableau indisponible : {exc}")


# =========================================================================
# Page 4 : Echanges inter-SERM & EPCI
# =========================================================================

elif page == "Echanges inter-SERM & EPCI":
    st.header("Echanges entre SERM et entre EPCI")

    matrice = _matrice(signature)
    st.plotly_chart(heatmap_inter_serm(matrice), use_container_width=True)

    st.subheader("Echanges EPCI x EPCI au sein d'un SERM")
    col_serm, col_typo, col_n = st.columns([1, 1, 1])
    with col_serm:
        code = st.selectbox(
            "SERM", codes_zones(inclure_hors_serm=False),
            format_func=lambda c: SERM_INFO[c]["nom"],
            key="code_serm_epci",
        )
    with col_typo:
        typo = st.selectbox(
            "Typologie",
            ["interne_serm", "echange_serm"],
            format_func=lambda x: {
                "interne_serm": "Echanges internes (EPCI dans le SERM)",
                "echange_serm": "Echanges avec EPCI hors SERM",
            }[x],
        )
    with col_n:
        top_n = st.slider("Top N EPCI", 5, 30, 12)

    echanges = _echanges(signature)
    st.plotly_chart(
        heatmap_epci_x_epci(echanges, code, typo, top_n_epci=top_n),
        use_container_width=True,
    )

    with st.expander("Données brutes (CSV)"):
        sous = echanges[
            (echanges["serm"] == code) & (echanges["typologie"] == typo)
        ].copy()
        st.caption(
            "Export complet (tous les couples EPCI). Les EPCI a cheval "
            "sur deux SERM (ex. Grand Dole, Val de Gray) apparaissent "
            "dans les echanges internes de chaque SERM concerne."
        )
        # Colonnes affichées : noms si disponibles, sinon codes
        col_o_lbl = "epci_O_nom" if "epci_O_nom" in sous.columns else "epci_O"
        col_d_lbl = "epci_D_nom" if "epci_D_nom" in sous.columns else "epci_D"
        cols_display = [col_o_lbl, col_d_lbl, "volume", "nom_serm", "typologie"]
        cols_display = [c for c in cols_display if c in sous.columns]
        renommage = {col_o_lbl: "EPCI Origine", col_d_lbl: "EPCI Destination",
                     "volume": "VL/j", "nom_serm": "SERM", "typologie": "Type"}
        st.dataframe(
            sous[cols_display].rename(columns=renommage),
            use_container_width=True, hide_index=True,
        )
        csv_bytes = sous.to_csv(index=False, sep=";").encode("utf-8-sig")
        st.download_button(
            ":material/download: Exporter ce sous-ensemble (CSV)",
            csv_bytes,
            f"echanges_epci_{info_serm(code)['slug']}_{typo}.csv",
            "text/csv",
        )


# =========================================================================
# Page 5 : Comptages AVATAR
# =========================================================================

elif page == "Comptages AVATAR":
    import geopandas as gpd
    from shapely.geometry import Point

    st.header("Comptages horaires AVATAR — DIR Est & DIR Centre-Est")
    st.caption(
        "Profils temporels horaires moyens (0-23h) des stations de "
        "comptage permanentes sur le reseau national en BFC. "
        "Donnees : API AVATAR Cerema."
    )

    # ── Chargement du bundle AVATAR ──────────────────────────────────────
    try:
        stations_all = charger_stations_avatar()
        profils_all = charger_profils_avatar()
    except FileNotFoundError as exc:
        st.warning(
            f"Bundle AVATAR introuvable : {exc}\n\n"
            "Lancer d'abord :\n"
            "```\n"
            "python scripts/prepare_avatar_stations.py "
            "--metadonnees sortie_avatar_bfc/metadonnees_stations_bfc.csv "
            "--horaire sortie_avatar_bfc/horaire_consolide_2026.csv\n"
            "```"
        )
        st.stop()

    # ── Selecteur SERM (identique aux autres pages) ──────────────────────
    code_serm_av = st.selectbox(
        "SERM",
        codes_zones(inclure_hors_serm=False),
        format_func=lambda c: SERM_INFO[c]["nom"],
        key="code_serm_avatar",
    )

    peri_serm_av = perimetres_gdf[
        perimetres_gdf["code_serm"] == code_serm_av
    ].copy()

    # Filtrage spatial : stations dans le perimetre du SERM selectionne
    if not peri_serm_av.empty:
        union_serm = peri_serm_av.to_crs(4326).union_all()
        mask_serm = stations_all.apply(
            lambda r: Point(r["longitude"], r["latitude"]).within(union_serm),
            axis=1,
        )
        stations_serm = stations_all[mask_serm].copy()
    else:
        stations_serm = stations_all.copy()

    st.caption(
        f"{len(stations_serm)} station(s) avec donnees dans ce SERM — "
        f"cliquer sur un point pour afficher son profil horaire."
    )

    # ── Etat de la station selectionnee (session state) ──────────────────
    if "avatar_station_id" not in st.session_state:
        st.session_state["avatar_station_id"] = None

    # ── Carte des stations ───────────────────────────────────────────────
    fig_carte_av = carte_stations_avatar(
        stations_serm,
        peri_serm_av,
        style_mapbox=_style_mapbox(),
        station_id_sel=st.session_state["avatar_station_id"],
    )
    ev = st.plotly_chart(
        fig_carte_av,
        use_container_width=True,
        on_select="rerun",
        key="carte_avatar",
    )

    # Lecture du clic sur la carte
    pts = (ev.selection.points if ev and ev.selection else [])
    if pts:
        cd = pts[0].get("customdata")
        if cd and len(cd) >= 1:
            st.session_state["avatar_station_id"] = int(cd[0])

    # ── Profil horaire de la station selectionnee ─────────────────────────
    station_id_av = st.session_state["avatar_station_id"]
    if station_id_av is not None:
        # Verifier que la station est bien dans ce SERM
        if station_id_av not in stations_serm["count_point_id"].values:
            st.session_state["avatar_station_id"] = None
        else:
            st.divider()
            st.subheader("Profil horaire moyen")
            fig_profil = profil_horaire_avatar(
                profils_all, station_id_av, stations_serm
            )
            st.plotly_chart(fig_profil, use_container_width=True)

            # Tableau de donnees brutes
            with st.expander("Donnees brutes du profil (CSV)"):
                profil_station = profils_all[
                    profils_all["count_point_id"] == station_id_av
                ].sort_values("heure").copy()
                profil_station["heure"] = profil_station["heure"].apply(
                    lambda h: f"{int(h):02d}h"
                )
                st.dataframe(
                    profil_station.rename(columns={
                        "heure": "Heure",
                        "flow_moy": "Debit moy. (veh/h)",
                        "pl_pct_moy": "Part PL (%)",
                        "vitesse_moy": "Vitesse moy. (km/h)",
                    }).drop(columns=["count_point_id"], errors="ignore"),
                    use_container_width=True,
                    hide_index=True,
                )
                csv_av = profil_station.to_csv(index=False, sep=";").encode(
                    "utf-8-sig"
                )
                row_st_av = stations_serm[
                    stations_serm["count_point_id"] == station_id_av
                ].iloc[0]
                slug_av = str(
                    row_st_av.get("count_point_name") or station_id_av
                ).replace(" ", "_").lower()
                st.download_button(
                    ":material/download: Exporter le profil (CSV)",
                    csv_av,
                    f"profil_avatar_{slug_av}.csv",
                    "text/csv",
                )
    else:
        st.info(
            ":material/touch_app: Cliquer sur une station sur la carte "
            "pour afficher son profil horaire."
        )


# =========================================================================
# Page 6 : Contexte enrichi (datagouv)
# =========================================================================

elif page == "Contexte enrichi (datagouv)":
    st.header("Contexte enrichi par les donnees data.gouv.fr")
    st.caption(
        "Cette page utilise le serveur MCP `user-datagouv` pour rechercher "
        "des jeux de donnees pertinents (INSEE, gares, parts modales) "
        "complementaires aux indicateurs OPSAM."
    )
    datagouv_context.afficher_panneau_contexte(perimetres_gdf)


# =========================================================================
# Page 6 : Reglages
# =========================================================================

elif page == "Reglages":
    st.header("Reglages - perimetres SERM et bundle de donnees")
    st.markdown(
        "Les perimetres SERM peuvent evoluer. Pour mettre a jour la "
        "plateforme :"
    )
    st.markdown(
        "1. Modifier le fichier "
        "`lookup_dep_com_epci_macrozone.csv` "
        "(colonnes `M1` et `M2`) ;\n"
        "2. Mettre a jour la variable d'environnement "
        "`SERM_LOOKUP_CSV` si necessaire ;\n"
        "3. Executer `python scripts/rebuild_for_new_perimeter.py` "
        "pour regenerer le bundle `data/`.\n"
    )

    st.divider()
    st.subheader("Bundle actuel")
    from data_loader import data_dir
    chemins = sorted(data_dir().rglob("*"))
    rows = []
    for p in chemins:
        if p.is_file():
            rows.append({
                "fichier": p.relative_to(data_dir()).as_posix(),
                "taille_ko": round(p.stat().st_size / 1024, 1),
                "modifie_le": pd.Timestamp(p.stat().st_mtime, unit="s"),
            })
    st.dataframe(
        pd.DataFrame(rows), use_container_width=True, hide_index=True,
        column_config={
            "taille_ko": st.column_config.NumberColumn(format="%.1f ko"),
        },
    )

    st.divider()
    st.subheader("Export des livrables par SERM")
    st.caption(
        "Genere un dossier structure (CSV, GeoJSON, GPKG) avec une note "
        "explicative par fichier, en dehors de la plateforme. "
        "Commande : `python scripts/export_livrables_par_serm.py --zip`"
    )
    col_exp1, col_exp2 = st.columns(2)
    with col_exp1:
        faire_zip = st.checkbox("Creer une archive ZIP", value=False)
    with col_exp2:
        effacer_export = st.checkbox(
            "Reinitialiser le dossier d'export", value=False,
        )
    if st.button(":material/folder_zip: Exporter les livrables par SERM"):
        racine = Path(__file__).resolve().parent
        cmd = [
            sys.executable,
            str(racine / "scripts" / "export_livrables_par_serm.py"),
            "-v",
        ]
        if faire_zip:
            cmd.append("--zip")
        if effacer_export:
            cmd.append("--effacer")
        with st.spinner("Export en cours..."):
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, cwd=str(racine),
                    timeout=600,
                )
                st.code(result.stdout + "\n" + result.stderr, language="text")
                if result.returncode == 0:
                    st.success("Export termine. Voir le chemin dans les logs.")
                else:
                    st.error(f"Echec export (code {result.returncode}).")
            except Exception as exc:
                st.error(f"Erreur : {exc}")

    st.divider()
    st.subheader("Lancer la regeneration du bundle")
    st.caption(
        "Equivalent shell : `python scripts/rebuild_for_new_perimeter.py`. "
        "Cette operation peut prendre plusieurs minutes (intersection reseau)."
    )
    if st.button(":material/refresh: Lancer la regeneration"):
        racine = Path(__file__).resolve().parent
        cmd = [sys.executable, str(racine / "scripts" / "rebuild_for_new_perimeter.py"), "-v"]
        with st.spinner("Execution..."):
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, cwd=str(racine),
                    timeout=900,
                )
                st.code(result.stdout + "\n" + result.stderr, language="text")
                if result.returncode == 0:
                    st.success("Bundle regenere avec succes.")
                    st.cache_data.clear()
                else:
                    st.error(f"Echec (code retour {result.returncode}).")
            except Exception as exc:
                st.error(f"Erreur : {exc}")
