"""Exporters — turn an `AttackSurface` into ready-to-replay collections.

After a static scan we know:

  * `attack_surface.api_endpoints` — URLs harvested from JADX strings,
    Firebase configs, MobSF urls/secrets, manifest meta.
  * `attack_surface.deeplinks` — every `<intent-filter>`/scheme/host triple.
  * `attack_surface.exported_components` — manifest activities/services/etc.

These exporters render those into formats that a tester can open in
their tool of choice with one click. Every exporter is a pure function
returning a string (or bytes for binary formats) — no I/O, no side
effects, easy to unit-test.

Public functions:

  * `to_postman(project)` → JSON string (Postman v2.1 collection)
  * `to_caido(project)` → JSON string (Caido sitemap import)
  * `to_burp_items(project)` → XML string (Burp Suite items file)
  * `to_moxy_config(project)` → YAML string (Moxy proxy ruleset)
  * `to_deeplink_script(project)` → bash script (am start probe loop)
"""

from mnexus.exporters.api_collections import to_burp_items, to_caido, to_moxy_config, to_postman
from mnexus.exporters.deeplink_script import to_deeplink_script

__all__ = [
    "to_burp_items",
    "to_caido",
    "to_deeplink_script",
    "to_moxy_config",
    "to_postman",
]
