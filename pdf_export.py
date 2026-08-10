"""pdf_export.py.

Generation de rapports PDF pour la plateforme inter-SERM :

  * ``generer_rapport_global`` : synthese inter-SERM (KPI, carte, heatmap) ;
  * ``generer_rapport_serm`` : rapport individuel par SERM (carte,
    Sankey, donut, profil distance).

Implementation calque sur celle de MACROZONE :
  * export image via ``kaleido`` (versions 0.2.x, sans Chrome systeme) ;
  * mise en page via ``reportlab`` (A4 paysage).
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Iterable, Optional

import plotly.graph_objects as go

try:
    import kaleido  # noqa: F401
except ImportError:
    pass

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm

from formatting import fmt_nombre
from reportlab.platypus import (
    Image as RLImage,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conversion Plotly -> PNG (robuste sur Streamlit Cloud)
# ---------------------------------------------------------------------------

def _png_bytes(fig: Optional[go.Figure], largeur: int = 1400, hauteur: int = 800) -> Optional[bytes]:
    """Convertit une figure Plotly en PNG. Renvoie ``None`` en cas d'echec."""
    if fig is None:
        return None
    try:
        fig_copy = go.Figure(fig)
        fig_copy.update_layout(
            paper_bgcolor="white",
            plot_bgcolor="white",
            font=dict(family="Arial, Helvetica, sans-serif"),
        )
        return fig_copy.to_image(
            format="png", width=largeur, height=hauteur, scale=1,
            engine="kaleido",
        )
    except Exception as exc:  # pragma: no cover - depend de Chrome/kaleido
        LOG.warning("Echec export PNG : %s", exc)
        return None


def _image_flowable(png: Optional[bytes], largeur_cm: float = 24.0) -> Optional[RLImage]:
    if not png:
        return None
    buf = BytesIO(png)
    img = RLImage(buf, width=largeur_cm * cm, height=largeur_cm * cm * 9 / 16)
    return img


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "titre": ParagraphStyle(
            "Titre", parent=base["Title"], fontSize=18, leading=22,
            textColor="#142850", spaceAfter=10,
        ),
        "soustitre": ParagraphStyle(
            "Sous", parent=base["Heading2"], fontSize=12, leading=16,
            textColor="#1565C0", spaceAfter=4,
        ),
        "p": ParagraphStyle(
            "Normal", parent=base["BodyText"], fontSize=9, leading=12,
        ),
    }


# ---------------------------------------------------------------------------
# Rapport global inter-SERM
# ---------------------------------------------------------------------------

def generer_rapport_global(
    metriques,
    fig_carte: Optional[go.Figure],
    fig_heatmap: Optional[go.Figure],
    scenario: str | None = None,
) -> bytes:
    """Rapport global inter-SERM (KPI, carte, heatmap)."""
    try:
        from data_loader import scenario_actif
        scenario = scenario or scenario_actif()
    except Exception:
        scenario = scenario or "OPSAM"
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=1.2 * cm, rightMargin=1.2 * cm,
        topMargin=1.0 * cm, bottomMargin=1.0 * cm,
        title="Rapport inter-SERM",
    )
    styles = _styles()
    story: list = []
    story.append(Paragraph(
        f"Plateforme inter-SERM - Synthese (scenario OPSAM {scenario})",
        styles["titre"],
    ))
    story.append(Paragraph(
        "Reconstitution des volumes vehicules legers par soustraction "
        "Total - PL (charges + vides). Source : OPSAM Atmo BFC.",
        styles["p"],
    ))
    story.append(Spacer(1, 6))

    sous = metriques[metriques["code_serm"] > 0].copy()
    if not sous.empty:
        donnees = [[
            "SERM", "VKM TV (k km/j)", "VKM VL (k km/j)", "VKM PL (k km/j)",
            "% PL", "% Transit", "% Echange", "% Interne",
        ]]
        for _, r in sous.iterrows():
            donnees.append([
                r["nom_serm"],
                fmt_nombre(r["VKM_TV_milliers"], 1),
                fmt_nombre(r["VKM_VL_milliers"], 1),
                fmt_nombre(r["VKM_PL_milliers"], 1),
                f"{fmt_nombre(r['pct_pl'], 1)} %",
                f"{fmt_nombre(r['pct_transit'], 1)} %",
                f"{fmt_nombre(r['pct_echange'], 1)} %",
                f"{fmt_nombre(r['pct_interne'], 1)} %",
            ])
        tbl = Table(donnees, hAlign="LEFT")
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), "#142850"),
            ("TEXTCOLOR", (0, 0), (-1, 0), "white"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("ALIGN", (0, 0), (0, -1), "LEFT"),
            ("GRID", (0, 0), (-1, -1), 0.3, "#90A4AE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), ["white", "#EEF1F5"]),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 10))

    img_carte = _image_flowable(_png_bytes(fig_carte))
    if img_carte:
        story.append(Paragraph("Carte BFC - Indicateur selectionne", styles["soustitre"]))
        story.append(img_carte)
        story.append(Spacer(1, 6))

    img_heat = _image_flowable(_png_bytes(fig_heatmap, largeur=1200, hauteur=600), largeur_cm=22)
    if img_heat:
        story.append(PageBreak())
        story.append(Paragraph(
            "Matrice OD inter-SERM (VL/jour)", styles["soustitre"]
        ))
        story.append(img_heat)

    doc.build(story)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Rapport individuel par SERM
# ---------------------------------------------------------------------------

def generer_rapport_serm(
    info_serm: dict,
    metr_row,
    fig_carte: Optional[go.Figure],
    fig_sankey: Optional[go.Figure],
    fig_donut: Optional[go.Figure],
    fig_distance: Optional[go.Figure],
) -> bytes:
    """Rapport individuel pour un SERM."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=1.2 * cm, rightMargin=1.2 * cm,
        topMargin=1.0 * cm, bottomMargin=1.0 * cm,
        title=f"Rapport {info_serm['nom']}",
    )
    styles = _styles()
    story: list = []
    story.append(Paragraph(info_serm["nom"], styles["titre"]))
    try:
        from data_loader import scenario_actif
        _sc = scenario_actif()
    except Exception:
        _sc = "OPSAM"
    story.append(Paragraph(f"Scenario OPSAM {_sc} - Atmo BFC", styles["p"]))
    story.append(Spacer(1, 6))

    kpi = [[
        "Indicateur", "Valeur",
    ], [
        "VKM total tous vehicules (k km/jour)",
        f"{metr_row['VKM_TV_milliers']:.1f}",
    ], [
        "VKM vehicules legers (k km/jour)",
        f"{metr_row['VKM_VL_milliers']:.1f}",
    ], [
        "VKM poids lourds (k km/jour)",
        f"{metr_row['VKM_PL_milliers']:.1f}",
    ], [
        "Part PL (VKM)", f"{metr_row['pct_pl']:.1f} %",
    ], [
        "Part Transit (tous vehicules)", f"{metr_row['pct_transit']:.1f} %",
    ], [
        "Part Echange (tous vehicules)", f"{metr_row['pct_echange']:.1f} %",
    ], [
        "Part Interne (tous vehicules)", f"{metr_row['pct_interne']:.1f} %",
    ], [
        "Réseau cumulé (km)", fmt_nombre(metr_row["DISTANCE"], 0),
    ]]
    tbl = Table(kpi, hAlign="LEFT", colWidths=[10 * cm, 4 * cm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), "#142850"),
        ("TEXTCOLOR", (0, 0), (-1, 0), "white"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("GRID", (0, 0), (-1, -1), 0.3, "#90A4AE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), ["white", "#EEF1F5"]),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8))

    for libelle, fig in (
        ("Carte de trafic", fig_carte),
        ("Sankey VL / PL par type de voie et flux", fig_sankey),
        ("Repartition VL / PL", fig_donut),
        ("Profil par classe de distance", fig_distance),
    ):
        img = _image_flowable(_png_bytes(fig, largeur=1200, hauteur=700), largeur_cm=22)
        if img:
            story.append(PageBreak())
            story.append(Paragraph(libelle, styles["soustitre"]))
            story.append(img)

    doc.build(story)
    return buffer.getvalue()
