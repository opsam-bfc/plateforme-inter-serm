"""generer_modop_pdf.py.

Génère le mode opératoire PDF de la plateforme Streamlit OPSAM.
Sortie : modop_plateforme_streamlit_opsam.pdf (à la racine du projet).

Usage :
    python scripts/generer_modop_pdf.py
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ---------------------------------------------------------------------------
# Couleurs
# ---------------------------------------------------------------------------

BLEU_DREAL = colors.HexColor("#1565C0")
BLEU_CLAIR = colors.HexColor("#E3F2FD")
GRIS_CLAIR = colors.HexColor("#F5F5F5")
GRIS_BORD = colors.HexColor("#BDBDBD")
VERT = colors.HexColor("#2E7D32")
ORANGE = colors.HexColor("#E65100")
ROUGE = colors.HexColor("#C62828")
BLANC = colors.white
NOIR = colors.HexColor("#1A1A2E")

# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

_base = getSampleStyleSheet()


def _style(
    name: str,
    parent: str = "Normal",
    fontSize: int = 10,
    textColor=NOIR,
    backColor=None,
    bold: bool = False,
    italic: bool = False,
    alignment: int = TA_LEFT,
    spaceBefore: float = 0,
    spaceAfter: float = 4,
    leftIndent: float = 0,
    leading: float | None = None,
) -> ParagraphStyle:
    return ParagraphStyle(
        name,
        parent=_base[parent],
        fontSize=fontSize,
        textColor=textColor,
        backColor=backColor,
        fontName="Helvetica-Bold" if bold else ("Helvetica-Oblique" if italic else "Helvetica"),
        alignment=alignment,
        spaceBefore=spaceBefore,
        spaceAfter=spaceAfter,
        leftIndent=leftIndent,
        leading=leading or (fontSize * 1.4),
    )


TITRE_DOC = _style("TitreDoc", fontSize=22, textColor=BLANC, bold=True,
                   alignment=TA_CENTER, spaceAfter=6, leading=28)
SOUS_TITRE_DOC = _style("SousTitreDoc", fontSize=13, textColor=BLEU_CLAIR,
                        alignment=TA_CENTER, spaceAfter=4, leading=18)
DATE_DOC = _style("DateDoc", fontSize=9, textColor=BLEU_CLAIR,
                  alignment=TA_CENTER, spaceAfter=0)

TITRE_SECTION = _style("TitreSection", fontSize=14, textColor=BLANC,
                       bold=True, spaceAfter=8, spaceBefore=4, leading=18)
TITRE_SS = _style("TitreSS", fontSize=11, textColor=BLEU_DREAL,
                  bold=True, spaceAfter=6, spaceBefore=10, leading=15)
TITRE_SSS = _style("TitreSSS", fontSize=10, textColor=NOIR,
                   bold=True, spaceAfter=4, spaceBefore=8)

CORPS = _style("Corps", fontSize=9, spaceAfter=5, leading=14,
               alignment=TA_JUSTIFY)
CORPS_INDENT = _style("CorpsIndent", fontSize=9, spaceAfter=4,
                      leftIndent=12, leading=13)
CODE = ParagraphStyle(
    "Code",
    parent=_base["Normal"],
    fontSize=8,
    textColor=colors.HexColor("#263238"),
    backColor=colors.HexColor("#ECEFF1"),
    fontName="Courier",
    leftIndent=8,
    rightIndent=4,
    spaceAfter=1,
    spaceBefore=1,
    leading=12,
)

PUCE = _style("Puce", fontSize=9, leftIndent=16, spaceAfter=3, leading=13)
PUCE_INDENT = _style("PuceIndent", fontSize=9, leftIndent=28, spaceAfter=2,
                     leading=12)

NOTE = _style("Note", fontSize=8, textColor=colors.HexColor("#5D4037"),
              backColor=colors.HexColor("#FFF8E1"), leftIndent=10,
              spaceAfter=4, leading=12)


# ---------------------------------------------------------------------------
# Utilitaires de mise en page
# ---------------------------------------------------------------------------

def entete_section(num: str, titre: str) -> list:
    """Bloc coloré pour un titre de section numérotée."""
    t = Table(
        [[Paragraph(f"{num}. {titre}", TITRE_SECTION)]],
        colWidths=[17 * cm],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLEU_DREAL),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("ROUNDEDCORNERS", (0, 0), (-1, -1), [4, 4, 4, 4]),
    ]))
    return [Spacer(1, 0.3 * cm), t, Spacer(1, 0.2 * cm)]


def etape(num: str, titre: str, corps: str | None = None) -> list:
    """Bloc numéroté pour une sous-étape."""
    items = []
    badge = Table(
        [[Paragraph(f"<b>{num}</b>", _style("Badge", fontSize=9,
          textColor=BLANC, bold=True, alignment=TA_CENTER)),
          Paragraph(f"<b>{titre}</b>", TITRE_SSS)]],
        colWidths=[0.9 * cm, 16.1 * cm],
    )
    badge.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), BLEU_DREAL),
        ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (0, 0), 4),
        ("LEFTPADDING", (1, 0), (1, 0), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, GRIS_BORD),
    ]))
    items.append(badge)
    if corps:
        items.append(Paragraph(corps, CORPS_INDENT))
    return items


def bloc_code(contenu: str) -> list:
    lignes = contenu.strip().split("\n")
    items = []
    for l in lignes:
        items.append(Paragraph(l.replace(" ", "&nbsp;"), CODE))
    return items


def note_info(texte: str) -> list:
    t = Table(
        [[Paragraph(f"<b>ℹ</b>&nbsp;&nbsp;{texte}", NOTE)]],
        colWidths=[17 * cm],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF8E1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#FFB300")),
    ]))
    return [t, Spacer(1, 0.2 * cm)]


def tableau(entetes: list[str], lignes: list[list], col_widths=None) -> Table:
    data = [entetes] + lignes
    if col_widths is None:
        w = 17 * cm / len(entetes)
        col_widths = [w] * len(entetes)
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BLEU_DREAL),
        ("TEXTCOLOR", (0, 0), (-1, 0), BLANC),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [BLANC, GRIS_CLAIR]),
        ("GRID", (0, 0), (-1, -1), 0.3, GRIS_BORD),
    ])
    # Wrapping texte dans chaque cellule
    wrapped = []
    for i, row in enumerate(data):
        st = TITRE_SECTION if i == 0 else CORPS
        wrapped.append([
            Paragraph(str(c), _style(f"Td{i}_{j}", fontSize=8,
                      textColor=BLANC if i == 0 else NOIR,
                      bold=(i == 0)))
            for j, c in enumerate(row)
        ])
    t = Table(wrapped, colWidths=col_widths)
    t.setStyle(style)
    return t


# ---------------------------------------------------------------------------
# Numérotation et filigrane des pages
# ---------------------------------------------------------------------------

def _page_callback(canvas, doc):
    canvas.saveState()
    w, h = A4
    # Pied de page
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#9E9E9E"))
    canvas.drawString(2 * cm, 1.2 * cm,
                      "Mode opératoire — Plateforme Streamlit OPSAM  |  DREAL BFC  |  Juillet 2026")
    canvas.drawRightString(
        w - 2 * cm, 1.2 * cm, f"Page {doc.page}"
    )
    # Filet en bas
    canvas.setStrokeColor(BLEU_DREAL)
    canvas.setLineWidth(0.5)
    canvas.line(2 * cm, 1.5 * cm, w - 2 * cm, 1.5 * cm)
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Contenu du document
# ---------------------------------------------------------------------------

def construire_contenu() -> list:
    story = []

    # ── PAGE DE TITRE ────────────────────────────────────────────────────────
    story.append(Spacer(1, 2 * cm))
    bandeau = Table(
        [[Paragraph("Mode Opératoire", TITRE_DOC)],
         [Paragraph("Plateforme Streamlit OPSAM", SOUS_TITRE_DOC)],
         [Paragraph("Alimentation · Optimisation · Diffusion sécurisée", SOUS_TITRE_DOC)],
         [Spacer(1, 0.3 * cm)],
         [Paragraph("DREAL Bourgogne-Franche-Comté  —  Juillet 2026", DATE_DOC)]],
        colWidths=[17 * cm],
    )
    bandeau.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLEU_DREAL),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 20),
        ("RIGHTPADDING", (0, 0), (-1, -1), 20),
    ]))
    story.append(bandeau)
    story.append(Spacer(1, 0.8 * cm))

    story.append(Paragraph(
        "Ce document décrit les étapes complètes pour préparer les données OPSAM, "
        "optimiser le bundle, configurer un territoire, déployer l'application sur "
        "Internet avec un lien sécurisé, et dupliquer la plateforme pour d'autres projets.",
        CORPS,
    ))
    story.append(Spacer(1, 0.4 * cm))

    # Tableau de synthèse des sections
    story.append(tableau(
        ["#", "Section", "Objectif"],
        [
            ["1", "Architecture & prérequis", "Vue d'ensemble et installation"],
            ["2", "Préparer les données", "Exécuter le pipeline OPSAM"],
            ["3", "Configurer le territoire", "Fichier config/territoire.yaml"],
            ["4", "Optimiser pour le déploiement", "Réduire ~99 Mo → ~25 Mo"],
            ["5", "Protéger par mot de passe", "Hash SHA-256 + st.secrets"],
            ["6", "Créer le dépôt GitHub privé", "Versionner code + données"],
            ["7", "Déployer sur Streamlit Cloud", "Mise en ligne gratuite"],
            ["8", "Partager le lien aux partenaires", "Lien privé sécurisé"],
            ["9", "Mettre à jour les données", "Nouveau modèle OPSAM"],
            ["10", "Dupliquer pour un autre territoire", "Nouveau projet en ~1 heure"],
        ],
        col_widths=[1 * cm, 7 * cm, 9 * cm],
    ))

    story.append(PageBreak())

    # ── SECTION 1 — Architecture ─────────────────────────────────────────────
    story += entete_section("1", "Architecture & Prérequis")

    story.append(Paragraph(
        "La plateforme repose sur une architecture en trois couches :", CORPS
    ))

    archi = Table(
        [
            [Paragraph("<b>1 — Sources NAS</b>", _style("A1", fontSize=9, textColor=BLANC, bold=True)),
             Paragraph("Sorties OPSAM (synthèse M1/M2, matrice VL, réseau routier, zonage, lookup EPCI)",
                       _style("A1t", fontSize=9, textColor=BLANC))],
            [Paragraph("&nbsp;&nbsp;&nbsp;↓ scripts/prepare_*.py", _style("Arrow", fontSize=8,
                       textColor=BLEU_CLAIR, italic=True)), Paragraph("", CORPS)],
            [Paragraph("<b>2 — Bundle data/</b>", _style("A2", fontSize=9, textColor=BLANC, bold=True)),
             Paragraph("Fichiers précalculés (CSV, GeoJSON, Parquet, GPKG) — ~25 Mo après optimisation",
                       _style("A2t", fontSize=9, textColor=BLANC))],
            [Paragraph("&nbsp;&nbsp;&nbsp;↓ GitHub + Streamlit Cloud", _style("Arrow2", fontSize=8,
                       textColor=BLEU_CLAIR, italic=True)), Paragraph("", CORPS)],
            [Paragraph("<b>3 — Application web</b>", _style("A3", fontSize=9, textColor=BLANC, bold=True)),
             Paragraph("app.py (Streamlit) — 6 pages d'analyse, export CSV/PDF, login sécurisé",
                       _style("A3t", fontSize=9, textColor=BLANC))],
        ],
        colWidths=[5 * cm, 12 * cm],
    )
    archi.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1A237E")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("LINEBELOW", (0, 0), (-1, 3), 0.3, BLEU_CLAIR),
    ]))
    story.append(archi)
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("<b>Prérequis logiciels</b>", TITRE_SS))
    story.append(tableau(
        ["Outil", "Version", "Installation"],
        [
            ["Python", "3.11 ou 3.13", "python.org/downloads"],
            ["Bibliothèques Python", "voir requirements.txt", "pip install -r requirements.txt"],
            ["Git", "≥ 2.40", "git-scm.com"],
            ["Compte GitHub", "gratuit", "github.com (dépôt privé)"],
            ["Compte Streamlit Cloud", "gratuit", "share.streamlit.io"],
        ],
        col_widths=[4 * cm, 4 * cm, 9 * cm],
    ))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        "Installer toutes les dépendances depuis le dossier du projet :", CORPS
    ))
    story += bloc_code("cd D:\\12__OPSAM\\plateforme_analyse_inter_SERM\n"
                       "python -m pip install -r requirements.txt")

    story.append(Paragraph("<b>Structure du projet</b>", TITRE_SS))
    story.append(tableau(
        ["Fichier / Dossier", "Rôle"],
        [
            ["app.py", "Point d'entrée Streamlit — 6 pages d'analyse"],
            ["data_loader.py", "Couche de lecture des données (CSV, GeoJSON, Parquet)"],
            ["visualizations.py", "Fabrique de graphiques Plotly (cartes, Sankey, heatmaps…)"],
            ["datagouv_context.py", "Page 5 — données contextuelles INSEE / SNCF"],
            ["pdf_export.py", "Export PDF des rapports (ReportLab + Kaleido)"],
            ["auth.py", "Module de login par mot de passe"],
            ["config/territoire.yaml", "⭐ Configuration du territoire (noms, codes, couleurs…)"],
            ["config/territoire_loader.py", "Chargement et validation du YAML"],
            ["data/", "Bundle de données précalculées (~25 Mo après optimisation)"],
            ["scripts/", "Pipeline de préparation et d'optimisation des données"],
            [".streamlit/secrets.toml", "Secrets (mot de passe, token Mapbox) — ne pas versionner"],
        ],
        col_widths=[6 * cm, 11 * cm],
    ))

    story.append(PageBreak())

    # ── SECTION 2 — Préparer les données ─────────────────────────────────────
    story += entete_section("2", "Préparer les données")

    story.append(Paragraph(
        "Les données sont précalculées depuis les sorties brutes du modèle OPSAM "
        "stockées sur le NAS. Le pipeline est orchestré par un script maître.", CORPS
    ))

    story += etape("2.1", "Vérifier l'accès aux sources NAS")
    story.append(Paragraph(
        "Les scripts ont besoin d'accéder aux partages réseau suivants "
        "(configurables dans <b>config/territoire.yaml</b>, section <i>chemins</i>) :", CORPS_INDENT
    ))
    story.append(tableau(
        ["Partage réseau", "Contenu"],
        [
            [r"\\poste-2-170\OPSAM_v3\OPSAM\Outputs\Ref2024", "Fichiers synthèse M1/M2"],
            [r"\\poste-2-170\OPSAM_v3\OPSAM\Base\Ref2024", "Réseau routier shapefile"],
            [r"\\nas-bfc\COMMUN\21_MOBILITE\...", "Lookup EPCI, zonage, EPCI shapefile"],
        ],
        col_widths=[8 * cm, 9 * cm],
    ))

    story += etape("2.2", "Lancer le pipeline complet (rebuild)")
    story.append(Paragraph(
        "Ce script orchestre les 5 scripts de préparation dans l'ordre correct :", CORPS_INDENT
    ))
    story += bloc_code(
        "cd D:\\12__OPSAM\\plateforme_analyse_inter_SERM\n"
        "python scripts/rebuild_for_new_perimeter.py\n\n"
        "# Options utiles :\n"
        "# --scenario Ref2025    (pour un nouveau scenario OPSAM)\n"
        "# --export               (génère aussi EXPORT_LIVRABLES/)\n"
        "# --verbose              (affiche le détail des étapes)"
    )
    story.append(Paragraph(
        "Le pipeline appelle dans l'ordre :", CORPS_INDENT
    ))
    story.append(Paragraph("① prepare_synthese_serm.py — synthèse VL/PL par SERM et type de voie", PUCE))
    story.append(Paragraph("② prepare_perimetres_serm.py — périmètres et zones OPSAM en GeoJSON", PUCE))
    story.append(Paragraph("③ prepare_reseau_serm.py — réseau routier découpé par SERM (GPKG)", PUCE))
    story.append(Paragraph("④ prepare_od_vl.py — matrices OD VL, top flux, échanges EPCI (Parquet)", PUCE))
    story.append(Paragraph("⑤ prepare_limites.py — limites communes et EPCI par SERM (GeoJSON)", PUCE))

    story += etape("2.3", "Vérifier le bundle produit")
    story += bloc_code(
        "# Lister les fichiers produits dans data/\n"
        "dir D:\\12__OPSAM\\plateforme_analyse_inter_SERM\\data"
    )
    story.append(Paragraph(
        "Les fichiers attendus dans <code>data/</code> :", CORPS_INDENT
    ))
    story.append(tableau(
        ["Fichier", "Description", "Format"],
        [
            ["synthese_serm_vl_pl.csv", "VKM par SERM / type voie / flux / distance", "CSV ; ~25 Ko"],
            ["matrice_inter_serm.csv", "Matrice OD 4×4 entre zones", "CSV ; <1 Ko"],
            ["perimetres_serm.geojson", "Polygones des périmètres SERM", "GeoJSON ; ~150 Ko"],
            ["zones_serm.geojson", "Maillage fin OPSAM par SERM", "GeoJSON ; ~2,5 Mo"],
            ["limites_epci.geojson", "Contours EPCI région", "GeoJSON ; ~19 Mo brut"],
            ["limites_communes_serm{N}.geojson", "Contours communes par SERM", "GeoJSON ; ~10 Mo brut"],
            ["reseau_serm/{slug}.gpkg", "Réseau routier avec trafics", "GPKG ; ~67 Mo brut"],
            ["top_od_vl_par_serm.parquet", "Top N flux OD VL par SERM", "Parquet ; ~100 Ko"],
            ["top_od_com_serm.parquet", "Top flux à la commune/EPCI", "Parquet ; ~90 Ko"],
            ["echanges_epci_serm.parquet", "Échanges EPCI×EPCI par SERM", "Parquet ; ~37 Ko"],
            ["centroides_zones.parquet", "Coordonnées centroïdes zones OPSAM", "Parquet ; ~320 Ko"],
        ],
        col_widths=[5.5 * cm, 7.5 * cm, 4 * cm],
    ))

    story.append(PageBreak())

    # ── SECTION 3 — Configurer le territoire ─────────────────────────────────
    story += entete_section("3", "Configurer le territoire")

    story.append(Paragraph(
        "Le fichier <b>config/territoire.yaml</b> est la source de vérité unique. "
        "Il contient tous les paramètres propres au territoire : noms, codes, couleurs, "
        "chemins NAS, départements de la région. <b>Ne jamais modifier SERM_INFO dans "
        "data_loader.py directement.</b>", CORPS
    ))

    story += etape("3.1", "Éditer config/territoire.yaml")
    story.append(Paragraph("Les sections à adapter pour chaque nouveau projet :", CORPS_INDENT))

    story.append(tableau(
        ["Section YAML", "Paramètre", "Exemple BFC", "À modifier pour"],
        [
            ["plateforme", "nom", "Plateforme inter-SERM", "Nom affiché dans l'UI"],
            ["plateforme", "institution", "DREAL BFC", "Organisation productrice"],
            ["plateforme", "scenario_opsam", "Ref2024", "Identifiant scénario OPSAM"],
            ["region", "nom / nom_court", "Bourgogne-Franche-Comté / BFC", "Région d'étude"],
            ["region", "departements", "[\"21\",\"25\",...]", "Codes INSEE départements"],
            ["region", "carte_centre_lat/lon", "47.2 / 5.0", "Centre carte par défaut"],
            ["zones[]", "code, nom, slug", "1, SERM Dijonnais, dijon", "Chaque territoire d'étude"],
            ["zones[]", "couleur", "#C62828", "Couleur hexadécimale carte"],
            ["zones[]", "macrozone", "{source: M1, code: 1}", "Lien avec sorties OPSAM M1/M2"],
            ["zone_hors_serm", "nom, code", "Reste BFC (hors SERM), 0", "Zone résiduelle (null si absent)"],
            ["chemins", "opsam_outputs / ...", r"\\poste-2-170\...", "Chemins accès NAS"],
        ],
        col_widths=[3 * cm, 3.5 * cm, 5 * cm, 5.5 * cm],
    ))
    story.append(Spacer(1, 0.3 * cm))
    story += note_info(
        "Les chemins NAS peuvent aussi être fournis via des variables d'environnement "
        "(SERM_OPSAM_DIR, SERM_LOOKUP_CSV, SERM_ZONAGE_SHP, SERM_EPCI_SHP) "
        "pour éviter de stocker des chemins réseau dans le YAML versionné."
    )

    story += etape("3.2", "Vérifier le chargement de la configuration")
    story += bloc_code(
        "python -c \"\n"
        "import sys; sys.path.insert(0, '.')\n"
        "from config.territoire_loader import cfg, codes_zones\n"
        "c = cfg()\n"
        "print('Territoire :', c.region.nom)\n"
        "print('Zones      :', codes_zones())\n"
        "\""
    )
    story.append(Paragraph("Résultat attendu :", CORPS_INDENT))
    story += bloc_code("Territoire : Bourgogne-Franche-Comté\nZones      : [1, 2, 3]")

    story.append(PageBreak())

    # ── SECTION 4 — Optimiser ─────────────────────────────────────────────────
    story += entete_section("4", "Optimiser les données pour le déploiement")

    story.append(Paragraph(
        "Le bundle brut pèse ~99 Mo (sans le cache data.gouv). Le script d'optimisation "
        "le réduit à ~25 Mo en trois actions, sans perte visible à l'écran :", CORPS
    ))
    story.append(Paragraph("• Convertit les GPKG réseau en GeoParquet (géométries simplifiées à 30 m) : 67 Mo → ~15 Mo", PUCE))
    story.append(Paragraph("• Simplifie les GeoJSON limites communes/EPCI (tolérance 30 m) : 29 Mo → ~5 Mo", PUCE))
    story.append(Paragraph("• Déplace le cache data.gouv hors du dossier déployable (32 Mo exclus)", PUCE))
    story.append(Spacer(1, 0.2 * cm))

    story += etape("4.1", "Lancer l'optimisation")
    story += bloc_code(
        "cd D:\\12__OPSAM\\plateforme_analyse_inter_SERM\n"
        "python scripts/optimize_for_deployment.py\n\n"
        "# Les originaux sont conservés dans data/.backup_avant_optim/\n"
        "# (ce dossier est exclu du dépôt Git par .gitignore)"
    )

    story += etape("4.2", "Vérifier la taille finale")
    story += bloc_code("dir /s data | findstr /C:\"octets\"")
    story += note_info(
        "Cible : dossier data/ < 30 Mo. Si la cible n'est pas atteinte, "
        "vérifier que les GPKG ont bien été convertis en .parquet et que "
        "les fichiers cache data.gouv ont été déplacés dans .backup_avant_optim/."
    )

    story.append(PageBreak())

    # ── SECTION 5 — Mot de passe ──────────────────────────────────────────────
    story += entete_section("5", "Protéger la plateforme par mot de passe")

    story.append(Paragraph(
        "L'accès à la plateforme est protégé par un formulaire de connexion. "
        "Le mot de passe est stocké sous forme de hash SHA-256 dans les secrets "
        "Streamlit (jamais en clair dans le code).", CORPS
    ))

    story += etape("5.1", "Générer le hash du mot de passe")
    story += bloc_code(
        "# Remplacer VOTRE_MOT_DE_PASSE par le mot de passe choisi\n"
        "python -c \"import hashlib; print(hashlib.sha256(b'VOTRE_MOT_DE_PASSE').hexdigest())\""
    )
    story.append(Paragraph(
        "Exemple de résultat (chaîne de 64 caractères hexadécimaux) :", CORPS_INDENT
    ))
    story += bloc_code("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    story += note_info(
        "Conserver le mot de passe en clair dans un gestionnaire de mots de passe "
        "(KeePass, Bitwarden…). Le hash seul ne permet pas de retrouver le mot de passe."
    )

    story += etape("5.2", "Créer le fichier secrets.toml local (facultatif, pour tests)")
    story.append(Paragraph(
        "Pour tester la protection en local, créer <code>.streamlit/secrets.toml</code> "
        "(ce fichier est dans le .gitignore, il ne sera jamais envoyé sur GitHub) :", CORPS_INDENT
    ))
    story += bloc_code(
        "# .streamlit/secrets.toml\n"
        "MOT_DE_PASSE_HASH = \"LE_HASH_GENERE_CI-DESSUS\"\n"
        "MAPBOX_TOKEN = \"\"   # optionnel"
    )

    story += etape("5.3", "Tester en local")
    story += bloc_code("streamlit run app.py")
    story.append(Paragraph(
        "La page de connexion doit s'afficher. Saisir le mot de passe pour accéder à l'application.", CORPS_INDENT
    ))

    story.append(PageBreak())

    # ── SECTION 6 — GitHub ────────────────────────────────────────────────────
    story += entete_section("6", "Créer le dépôt GitHub privé")

    story.append(Paragraph(
        "Le code et les données optimisées (~25 Mo) sont versionnés dans un "
        "dépôt GitHub privé. Streamlit Community Cloud se connecte directement à ce dépôt.", CORPS
    ))

    story += etape("6.1", "Créer le dépôt sur github.com")
    story.append(Paragraph("Se connecter sur github.com → <b>New repository</b> :", CORPS_INDENT))
    story.append(Paragraph("• Nom : <code>plateforme-inter-serm</code> (ou autre)", PUCE_INDENT))
    story.append(Paragraph("• Visibilité : <b>Private</b> (obligatoire)", PUCE_INDENT))
    story.append(Paragraph("• Ne pas initialiser avec README (on pousse un projet existant)", PUCE_INDENT))

    story += etape("6.2", "Initialiser et pousser le projet")
    story += bloc_code(
        "cd D:\\12__OPSAM\\plateforme_analyse_inter_SERM\n\n"
        "git init\n"
        "git branch -M main\n"
        "git remote add origin https://github.com/VOTRE_LOGIN/plateforme-inter-serm.git\n\n"
        "# Vérifier que .gitignore exclut bien les fichiers sensibles et lourds\n"
        "git status\n\n"
        "git add .\n"
        "git commit -m \"feat: plateforme inter-SERM — déploiement initial\"\n"
        "git push -u origin main"
    )
    story += note_info(
        "Vérifier AVANT le push que .gitignore exclut bien : "
        ".streamlit/secrets.toml, data/.backup_avant_optim/, "
        "data/reseau_serm/*.gpkg, EXPORT_LIVRABLES/, __pycache__/"
    )

    story.append(PageBreak())

    # ── SECTION 7 — Streamlit Cloud ───────────────────────────────────────────
    story += entete_section("7", "Déployer sur Streamlit Community Cloud")

    story.append(Paragraph(
        "Streamlit Community Cloud est le service d'hébergement gratuit de Streamlit. "
        "Il surveille le dépôt GitHub et redéploie automatiquement à chaque push.", CORPS
    ))

    story += etape("7.1", "Connexion et création de l'application")
    story.append(Paragraph("① Ouvrir <b>share.streamlit.io</b> → Se connecter avec GitHub", PUCE))
    story.append(Paragraph("② Cliquer <b>New app</b>", PUCE))
    story.append(Paragraph("③ Sélectionner le dépôt <code>plateforme-inter-serm</code>", PUCE))
    story.append(Paragraph("④ Branche : <code>main</code> — Fichier principal : <code>app.py</code>", PUCE))
    story.append(Paragraph("⑤ Cliquer <b>Advanced settings</b>", PUCE))

    story += etape("7.2", "Configurer les secrets")
    story.append(Paragraph(
        "Dans l'onglet <b>Secrets</b> des Advanced settings, coller :", CORPS_INDENT
    ))
    story += bloc_code(
        "MOT_DE_PASSE_HASH = \"LE_HASH_GENERE_A_L_ETAPE_5\"\n"
        "MAPBOX_TOKEN = \"\"   # laisser vide ou renseigner un jeton Mapbox"
    )
    story.append(Paragraph("⑥ Cliquer <b>Deploy!</b> — le déploiement prend 3 à 7 minutes.", PUCE))

    story += etape("7.3", "Résultat")
    story.append(Paragraph(
        "L'application est accessible via une URL du type :", CORPS_INDENT
    ))
    story += bloc_code("https://plateforme-inter-serm-abc123.streamlit.app")

    story.append(Paragraph("<b>Limites de la formule gratuite</b>", TITRE_SS))
    story.append(tableau(
        ["Ressource", "Limite", "Impact"],
        [
            ["RAM", "1 GB", "Suffisant pour les 3 SERM BFC après optimisation"],
            ["CPU", "1 vCPU partagé", "Temps de chargement des cartes ~3-5 s"],
            ["Stockage dépôt", "< 1 GB", "~25 Mo de données ✓ très large marge"],
            ["Apps simultanées", "3", "Une par territoire"],
            ["Inactivité", "Veille après 7 j sans visite", "Réveil automatique à la première visite"],
        ],
        col_widths=[3 * cm, 4 * cm, 10 * cm],
    ))

    story.append(PageBreak())

    # ── SECTION 8 — Partager ──────────────────────────────────────────────────
    story += entete_section("8", "Partager le lien aux partenaires")

    story.append(Paragraph(
        "La plateforme n'est pas indexée par les moteurs de recherche. "
        "L'accès nécessite de connaître à la fois l'URL et le mot de passe.", CORPS
    ))

    story += etape("8.1", "Communiquer l'accès")
    story.append(Paragraph("Envoyer par e-mail sécurisé (ou messagerie interne) :", CORPS_INDENT))
    story.append(Paragraph("• L'URL de l'application (https://xxx.streamlit.app)", PUCE_INDENT))
    story.append(Paragraph("• Le mot de passe d'accès", PUCE_INDENT))
    story.append(Paragraph("• Ce mode opératoire (optionnel)", PUCE_INDENT))

    story += etape("8.2", "Expérience de connexion partenaire")
    story.append(Paragraph("① Le partenaire ouvre l'URL dans un navigateur", PUCE))
    story.append(Paragraph("② Une page de connexion s'affiche (titre, champ mot de passe)", PUCE))
    story.append(Paragraph("③ Après connexion correcte, accès complet à la plateforme", PUCE))
    story.append(Paragraph("④ La session reste active tant que l'onglet est ouvert", PUCE))
    story.append(Paragraph("⑤ Le bouton « Se déconnecter » est disponible dans la sidebar", PUCE))

    story += etape("8.3", "Changer le mot de passe")
    story.append(Paragraph("Générer un nouveau hash (étape 5.1), puis :", CORPS_INDENT))
    story.append(Paragraph("• Sur Streamlit Cloud : <b>Settings > Secrets</b> → mettre à jour MOT_DE_PASSE_HASH", PUCE_INDENT))
    story.append(Paragraph("• L'application se redémarre automatiquement", PUCE_INDENT))

    story.append(PageBreak())

    # ── SECTION 9 — Mise à jour ────────────────────────────────────────────────
    story += entete_section("9", "Mettre à jour les données")

    story.append(Paragraph(
        "Quand un nouveau scénario OPSAM est disponible (ex. Ref2025), "
        "la mise à jour se fait en 4 commandes :", CORPS
    ))

    story += etape("9.1", "Mettre à jour le scénario dans la configuration")
    story += bloc_code(
        "# Éditer config/territoire.yaml :\n"
        "#   scenario_opsam: \"Ref2025\"   (à la place de Ref2024)\n"
        "# Et mettre à jour le chemin si le dossier NAS a changé :\n"
        "#   chemins.opsam_outputs: '\\\\poste-2-170\\...\\Ref2025'"
    )

    story += etape("9.2", "Régénérer le bundle depuis le NAS")
    story += bloc_code(
        "python scripts/rebuild_for_new_perimeter.py --scenario Ref2025"
    )

    story += etape("9.3", "Ré-optimiser pour le déploiement")
    story += bloc_code(
        "python scripts/optimize_for_deployment.py"
    )

    story += etape("9.4", "Pousser sur GitHub → déploiement automatique")
    story += bloc_code(
        "git add data/\n"
        "git commit -m \"data: mise à jour bundle OPSAM Ref2025\"\n"
        "git push\n\n"
        "# Streamlit Cloud détecte le push et redéploie automatiquement (~3 min)"
    )

    story.append(PageBreak())

    # ── SECTION 10 — Duplication ──────────────────────────────────────────────
    story += entete_section("10", "Dupliquer pour un autre territoire")

    story.append(Paragraph(
        "La plateforme est conçue pour être réutilisable. "
        "Pour un nouveau projet (autre région, autre scénario), "
        "seuls le fichier de configuration et les données changent. "
        "Le code applicatif reste identique.", CORPS
    ))

    story += etape("10.1", "Copier le projet")
    story += bloc_code(
        "# Option A : copier le dossier entier\n"
        "xcopy D:\\12__OPSAM\\plateforme_analyse_inter_SERM\n"
        "      D:\\MON_PROJET\\plateforme_mon_territoire /E /I\n\n"
        "# Option B : cloner depuis GitHub\n"
        "git clone https://github.com/VOTRE_LOGIN/plateforme-inter-serm\n"
        "          plateforme-mon-territoire"
    )

    story += etape("10.2", "Adapter config/territoire.yaml")
    story.append(Paragraph(
        "C'est la <b>seule étape de paramétrage</b> nécessaire pour l'application. "
        "Modifier les sections :", CORPS_INDENT
    ))
    story.append(Paragraph("• <code>plateforme</code> : nom, institution, scénario OPSAM", PUCE_INDENT))
    story.append(Paragraph("• <code>region</code> : nom, codes départements, centre carte", PUCE_INDENT))
    story.append(Paragraph("• <code>zones</code> : liste des territoires d'étude (N quelconque)", PUCE_INDENT))
    story.append(Paragraph("• <code>chemins</code> : chemins NAS vers les sorties OPSAM du nouveau projet", PUCE_INDENT))

    story += etape("10.3", "Préparer les données du nouveau territoire")
    story += bloc_code(
        "# Depuis le dossier du nouveau projet :\n"
        "python scripts/rebuild_for_new_perimeter.py\n"
        "python scripts/optimize_for_deployment.py"
    )

    story += etape("10.4", "Créer un nouveau dépôt GitHub privé et déployer")
    story.append(Paragraph("Répéter les étapes 6 et 7 pour ce nouveau projet.", CORPS_INDENT))
    story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph("<b>Ce qui est commun à tous les déploiements</b>", TITRE_SS))
    story.append(tableau(
        ["Élément", "Commun ?", "Note"],
        [
            ["Structure des pages Streamlit", "✅ Oui", "Identique pour tous les territoires"],
            ["Graphiques Plotly (Sankey, heatmap, lignes de désir…)", "✅ Oui", "Dynamiques selon les données"],
            ["Export CSV / PDF", "✅ Oui", "Généré depuis les données chargées"],
            ["Authentification mot de passe", "✅ Oui", "Hash différent par déploiement"],
            ["Format des données OPSAM (VKM, flux E/T/I, D1-D5)", "✅ Oui", "Standard OPSAM"],
            ["Noms, codes, couleurs des territoires", "⚙️ Config", "Via territoire.yaml"],
            ["Chemins NAS sources", "⚙️ Config", "Via territoire.yaml ou env vars"],
            ["Logique M1/M2 si >1 modèle OPSAM", "⚠️ Partiel", "À adapter si autre structure"],
        ],
        col_widths=[6 * cm, 2.5 * cm, 8.5 * cm],
    ))

    story.append(Spacer(1, 0.5 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=BLEU_DREAL))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        "Document généré automatiquement par <code>scripts/generer_modop_pdf.py</code>  "
        "— DREAL Bourgogne-Franche-Comté — Juillet 2026",
        _style("Pied", fontSize=8, textColor=colors.HexColor("#9E9E9E"),
               alignment=TA_CENTER),
    ))

    return story


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

def main() -> None:
    racine = Path(__file__).resolve().parent.parent
    sortie = racine / "modop_plateforme_streamlit_opsam.pdf"

    doc = SimpleDocTemplate(
        str(sortie),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2.2 * cm,
        title="Mode Opératoire — Plateforme Streamlit OPSAM",
        author="DREAL Bourgogne-Franche-Comté",
        subject="Alimentation, optimisation et diffusion de la plateforme inter-SERM",
    )

    story = construire_contenu()
    doc.build(story, onFirstPage=_page_callback, onLaterPages=_page_callback)

    print(f"PDF généré : {sortie}  ({sortie.stat().st_size / 1024:.0f} Ko)")


if __name__ == "__main__":
    main()
