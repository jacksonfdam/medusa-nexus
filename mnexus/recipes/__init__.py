"""Built-in Frida recipes that ship in-tree.

Medusa modules from disk (under ~/.mnexus/tools/medusa/modules) are loaded by
the API at request time. The recipes here are guaranteed to be available
without any external setup, so the recipes screen has content immediately
after `git clone`.

Each recipe is a dict with the same shape `/v1/recipes` returns — name,
origin, category, description, compatibility, platform, script.
"""

from __future__ import annotations

from mnexus.recipes.builtin import BUILTIN_RECIPES

__all__ = ["BUILTIN_RECIPES"]
