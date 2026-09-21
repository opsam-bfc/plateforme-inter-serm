"""Compatibilité cartes Plotly (MapLibre / traces *map*).

Plotly 7 supprime ``choropleth_mapbox``, ``Scattermapbox`` et les clés
``mapbox_*`` du layout. Les helpers ci-dessous centralisent l'API
``map_style`` / ``map_center`` / ``map_zoom``, supportée dès Plotly 6.
"""

from __future__ import annotations

from typing import Any, Optional

import plotly.graph_objects as go


def layout_carte(
    style: str,
    *,
    center: Optional[dict[str, float]] = None,
    zoom: Optional[float] = None,
    **extra: Any,
) -> dict[str, Any]:
    """Clés de layout pour une figure avec fond cartographique."""
    layout: dict[str, Any] = {"map_style": style}
    if center is not None:
        layout["map_center"] = center
    if zoom is not None:
        layout["map_zoom"] = zoom
    layout.update(extra)
    return layout


def layout_carte_noeud(
    style: str,
    center: dict[str, float],
    zoom: float,
    layers: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """Bloc ``map`` pour ``fig.update_layout(map=...)``."""
    noeud: dict[str, Any] = {
        "style": style,
        "center": center,
        "zoom": zoom,
    }
    if layers:
        noeud["layers"] = layers
    return {"map": noeud}


def scatter_map(**kwargs: Any) -> go.Scattermap:
    """Trace ligne/point/texte sur fond carto (Plotly 6+)."""
    return go.Scattermap(**kwargs)
