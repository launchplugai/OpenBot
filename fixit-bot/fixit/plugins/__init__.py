"""Plugin loader — teach the crow about specific stacks."""

from __future__ import annotations

import importlib
from fixit.plugins.base import Plugin, ContextHint


_BUILTIN_PLUGINS = {
    "openbot": "fixit.plugins.openbot",
}


def load_plugin(name: str) -> Plugin:
    """Load a plugin by name."""
    if name in _BUILTIN_PLUGINS:
        module = importlib.import_module(_BUILTIN_PLUGINS[name])
        # Convention: plugin class is the module's Plugin subclass
        for attr in dir(module):
            obj = getattr(module, attr)
            if isinstance(obj, type) and issubclass(obj, Plugin) and obj is not Plugin:
                return obj()
    raise ValueError(f"Unknown plugin: {name}. Available: {list(_BUILTIN_PLUGINS.keys())}")


__all__ = ["Plugin", "ContextHint", "load_plugin"]
