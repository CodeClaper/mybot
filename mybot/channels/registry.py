
import pkgutil
import importlib

from loguru import logger
from mybot.channels.base import BaseChannel

_INTERNAL = frozenset({"base", "manager", "registry"})

def discover_channel_names() -> list[str]:
    """
    Return all builtin channel module by scanning the package.
    """
    import mybot.channels as pkg
    return [
        name
        for _, name, ispkg in pkgutil.iter_modules(pkg.__path__)
        if name not in _INTERNAL and not ispkg
    ]

def load_channel_class(module_name: str) -> type[BaseChannel]:
    """
    Import *module_name* and return the first baseChannel subclass found.
    """
    from mybot.channels.base import BaseChannel as _Base

    mod = importlib.import_module(f"mybot.channels.{module_name}")
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if isinstance(obj, type) and issubclass(obj, _Base) and obj is not _Base:
            return obj
    
    raise ImportError(f"Not BaseChannel subclass in mybot.channels.{module_name}")

def discover_all() -> dict[str, type[BaseChannel]]:
    """
    Return all builtin channels.
    """

    builtin: dict[str, type[BaseChannel]] = {}
    for modname in discover_channel_names():
        try:
            builtin[modname] = load_channel_class(modname)
        except ImportError as e:
            logger.debug("Skipping builtin channel {}: {}", modname, e)
    return builtin

