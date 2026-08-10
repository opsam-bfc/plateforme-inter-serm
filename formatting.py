"""formatting.py.

Formats d'affichage français pour l'interface Streamlit et Plotly :
  - séparateur de milliers : espace
  - séparateur décimal : virgule (si décimales demandées)
"""

from __future__ import annotations

import math
from typing import Any


def fmt_nombre(val: Any, decimales: int = 0) -> str:
    """Formate un nombre au format français.

    Args:
        val: Valeur numérique (ou None / NaN).
        decimales: Nombre de chiffres après la virgule (0 = entier).

    Returns:
        Chaîne formatée, ou ``"-"`` si valeur absente.
    """
    if val is None:
        return "-"
    try:
        n = float(val)
    except (TypeError, ValueError):
        return str(val)
    if math.isnan(n):
        return "-"

    signe = "-" if n < 0 else ""
    n = abs(n)

    if decimales == 0:
        return signe + f"{int(round(n)):,}".replace(",", " ")

    brut = f"{n:,.{decimales}f}"
    entier, dec = brut.split(".")
    return signe + entier.replace(",", " ") + "," + dec
