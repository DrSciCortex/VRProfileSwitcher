"""
Module Registry
To add a new module:
  1. Create modules/yourmodule.py implementing VRModule
  2. Import it here and add to MODULE_REGISTRY
  That's it — the GUI and switcher pick it up automatically.
"""

from modules.slimevr import SlimeVRModule
from modules.steamvr import SteamVRModule
from modules.resonite import ResoniteModule
from modules.eyetrackvr import EyeTrackVRModule
from modules.babble import BabbleModule

# Ordered list of available modules — order determines GUI display order
MODULE_REGISTRY: dict[str, type] = {
    SlimeVRModule.id: SlimeVRModule,
    SteamVRModule.id: SteamVRModule,
    ResoniteModule.id: ResoniteModule,
    EyeTrackVRModule.id: EyeTrackVRModule,
    BabbleModule.id: BabbleModule,
}


def get_module(module_id: str, options: dict | None = None):
    """Instantiate a module by ID with optional options dict."""
    cls = MODULE_REGISTRY.get(module_id)
    if cls is None:
        raise KeyError(f"Unknown module: {module_id!r}")
    return cls(options=options)


def all_modules(options_map: dict | None = None):
    """Yield instantiated module objects for all registered modules."""
    for mid, cls in MODULE_REGISTRY.items():
        opts = (options_map or {}).get(mid, {})
        yield cls(options=opts)
