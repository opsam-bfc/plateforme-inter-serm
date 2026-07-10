"""Package config — configuration du territoire pour la plateforme inter-SERM."""

from config.territoire_loader import (
    TerritoireConfig,
    Zone,
    cfg,
    charger_config,
    codes_zones,
    ordre_zones,
    serm_info,
    slugs_reseau,
)

__all__ = [
    "TerritoireConfig",
    "Zone",
    "cfg",
    "charger_config",
    "codes_zones",
    "ordre_zones",
    "serm_info",
    "slugs_reseau",
]
