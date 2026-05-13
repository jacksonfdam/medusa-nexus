"""Medusa-flavoured runtime script generators.

The Runtime tab in the project UI doesn't reinvent the Medusa CLI —
it generates parametrised Frida scripts the analyst can either copy
into their own session or load through Nexus's existing Dynamic tab
(``POST /v1/projects/{id}/dynamic/start``).

Every script emits structured events via ``send({channel: 'runtime',
…})`` so the orchestrator's ``POST /v1/projects/{id}/dynamic/events``
ingest captures them under the ``runtime`` channel — no extra
transport, no separate streaming endpoint. The UI polls
``/v1/projects/{id}/dynamic/events`` and renders runtime rows the
same way it already renders ssl_pin rows.

Five actions land here, all 1:1 with a Medusa CLI command:

  * ``enumerate_classes``    — ``enumerate classes <filter>``
  * ``describe_class``       — ``describe_java_class <fqcn>``
  * ``jtrace_method``        — ``jtrace <Class!method>``
  * ``enumerate_modules``    — ``libs`` (native module list with bases)
  * ``spawn_log``            — ``spawn <package>`` + log lifecycle

Anything that's already a stable recipe (SSL bypass, crypto monitor,
intent monitor, …) belongs in the Recipes library instead. This
module fills the gap of ad-hoc commands you'd type at the
medusa➤ prompt.
"""

from __future__ import annotations

import json
from typing import Any, Callable

# ─── helpers ──────────────────────────────────────────────────────────


def _wrap_java_perform(body: str) -> str:
    """Wrap a JS snippet in the standard ``Java.perform`` boilerplate.

    Every Medusa-style hook runs inside ``Java.perform`` so the VM is
    attached before the body runs. The wrap also catches errors and
    surfaces them via ``send`` so the Dynamic console doesn't swallow
    them silently."""
    return (
        "Java.perform(function () {\n"
        "  try {\n"
        f"{body}\n"
        "  } catch (e) {\n"
        "    try { send({ channel: 'runtime', kind: 'error', message: String(e), stack: (e && e.stack) || '' }); } catch (_) {}\n"
        "  }\n"
        "});\n"
    )


def _js_string(s: str) -> str:
    """Safely embed a Python string into a JS source literal."""
    return json.dumps(s, ensure_ascii=False)


def _validate_class_name(fqcn: str) -> str:
    """Sanity-check a fully-qualified Java class name.

    Frida's ``Java.use`` accepts any string the VM has loaded, but a
    name with whitespace / quotes is almost always operator error —
    reject it with a clear message instead of injecting a broken
    script."""
    fqcn = fqcn.strip()
    if not fqcn:
        raise ValueError("class name is empty")
    for ch in fqcn:
        if not (ch.isalnum() or ch in "._$"):
            raise ValueError(f"invalid character {ch!r} in class name {fqcn!r}")
    return fqcn


def _validate_method_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("method name is empty")
    for ch in name:
        if not (ch.isalnum() or ch in "_$<>"):
            raise ValueError(f"invalid character {ch!r} in method name {name!r}")
    return name


# ─── action implementations ───────────────────────────────────────────


def _action_enumerate_classes(package: str, params: dict[str, Any]) -> dict[str, Any]:
    """Java.enumerateLoadedClasses → filter by regex → emit one event per match.

    Mirrors Medusa's ``enumerate classes <pattern>`` command. ``pattern``
    is treated as a JS regex source (no flags); default ``.*`` returns
    everything the VM has loaded by the time the script attaches.

    ``limit`` caps emissions so a wildcard against a typical app
    (~30k classes) doesn't drown the event ingest. Defaults to 500.
    """
    pattern = str(params.get("pattern") or ".*")
    limit = int(params.get("limit") or 500)
    body = (
        f"    const RE = new RegExp({_js_string(pattern)});\n"
        f"    const LIMIT = {limit};\n"
        "    let seen = 0, kept = 0;\n"
        "    Java.enumerateLoadedClasses({\n"
        "      onMatch: function (name) {\n"
        "        seen += 1;\n"
        "        if (kept >= LIMIT) return;\n"
        "        if (!RE.test(name)) return;\n"
        "        kept += 1;\n"
        "        send({ channel: 'runtime', kind: 'class', name: name });\n"
        "      },\n"
        "      onComplete: function () {\n"
        "        send({ channel: 'runtime', kind: 'enumerate_done', seen: seen, kept: kept, pattern: " + _js_string(pattern) + " });\n"
        "      },\n"
        "    });"
    )
    return {
        "channel": "runtime",
        "script": _wrap_java_perform(body),
        "hint": f"Attach to {package or '<package>'} and watch the runtime channel — one event per class match (capped at {limit}).",
    }


def _action_describe_class(package: str, params: dict[str, Any]) -> dict[str, Any]:
    """Java.use(class).class → list methods + fields → emit one event with the summary.

    Mirrors Medusa's ``describe_java_class <fqcn>``. Strips reflection
    boilerplate to the bits that matter for hook planning: method
    signatures (overloads listed) and instance-field types.
    """
    fqcn = _validate_class_name(str(params.get("class") or ""))
    body = (
        f"    const cls = Java.use({_js_string(fqcn)});\n"
        "    const methods = {};\n"
        "    const refl = cls.class.getDeclaredMethods();\n"
        "    for (let i = 0; i < refl.length; i++) {\n"
        "      const m = refl[i];\n"
        "      const name = m.getName();\n"
        "      const sig = m.toGenericString();\n"
        "      if (!methods[name]) methods[name] = [];\n"
        "      methods[name].push(sig);\n"
        "    }\n"
        "    const fields = [];\n"
        "    const fl = cls.class.getDeclaredFields();\n"
        "    for (let j = 0; j < fl.length; j++) {\n"
        "      fields.push({ name: fl[j].getName(), type: fl[j].getType().getName() });\n"
        "    }\n"
        "    send({ channel: 'runtime', kind: 'class_described', class: " + _js_string(fqcn) + ", methods: methods, fields: fields });"
    )
    return {
        "channel": "runtime",
        "script": _wrap_java_perform(body),
        "hint": f"Returns one 'class_described' event with every declared method (incl. overloads) and field of {fqcn}.",
    }


def _action_jtrace_method(package: str, params: dict[str, Any]) -> dict[str, Any]:
    """Install a per-overload tracer on ``class!method`` (Medusa's jtrace).

    Knobs (all optional):

      * ``log_args``    — default true; serialises args via String(v).
      * ``log_return``  — default true.
      * ``log_stack``   — default false; getStackTrace() is expensive.
    """
    fqcn = _validate_class_name(str(params.get("class") or ""))
    method = _validate_method_name(str(params.get("method") or ""))
    log_args = bool(params.get("log_args", True))
    log_return = bool(params.get("log_return", True))
    log_stack = bool(params.get("log_stack", False))

    body = (
        f"    const cls = Java.use({_js_string(fqcn)});\n"
        f"    const target = cls[{_js_string(method)}];\n"
        "    if (!target) {\n"
        f"      send({{ channel: 'runtime', kind: 'jtrace_error', message: 'no method ' + {_js_string(method)} + ' on ' + {_js_string(fqcn)} }});\n"
        "      return;\n"
        "    }\n"
        "    const overloads = target.overloads || [target];\n"
        "    overloads.forEach(function (ovl) {\n"
        "      const sig = (ovl.argumentTypes || []).map(function (t) { return t.className || t.name || String(t); }).join(',');\n"
        "      ovl.implementation = function () {\n"
        "        const ev = { channel: 'runtime', kind: 'jtrace', class: " + _js_string(fqcn) + ", method: " + _js_string(method) + ", signature: sig };\n"
        + ("        ev.args = Array.prototype.slice.call(arguments).map(function (a) { try { return String(a); } catch (_) { return '<unstringable>'; } });\n" if log_args else "")
        + "        const rv = this[" + _js_string(method) + "].apply(this, arguments);\n"
        + ("        try { ev.ret = String(rv); } catch (_) { ev.ret = '<unstringable>'; }\n" if log_return else "")
        + ("        try {\n"
           "          const T = Java.use('java.lang.Thread');\n"
           "          ev.stack = T.currentThread().getStackTrace().toString();\n"
           "        } catch (_) {}\n" if log_stack else "")
        + "        send(ev);\n"
        "        return rv;\n"
        "      };\n"
        "    });\n"
        f"    send({{ channel: 'runtime', kind: 'jtrace_installed', class: {_js_string(fqcn)}, method: {_js_string(method)}, overloads: overloads.length }});"
    )
    return {
        "channel": "runtime",
        "script": _wrap_java_perform(body),
        "hint": f"Per-call event on every {fqcn}!{method}() overload. {'+args' if log_args else ''} {'+return' if log_return else ''} {'+stack' if log_stack else ''}".strip(),
    }


def _action_enumerate_modules(package: str, params: dict[str, Any]) -> dict[str, Any]:
    """Process.enumerateModules → emit a list of native .so libs + bases.

    Medusa's ``libs`` command. Strips out non-Bionic system libs from the
    default view unless ``include_system`` is true.
    """
    include_system = bool(params.get("include_system", False))
    body = (
        "    const mods = Process.enumerateModules().filter(function (m) {\n"
        f"      if ({'true' if include_system else 'false'}) return true;\n"
        "      // Default: keep app-private .so files (typically /data/app/.../lib/<abi>/).\n"
        "      return /\\/data\\/app|\\/data\\/data/.test(m.path);\n"
        "    }).map(function (m) {\n"
        "      return { name: m.name, base: m.base.toString(), size: m.size, path: m.path };\n"
        "    });\n"
        "    send({ channel: 'runtime', kind: 'modules', modules: mods });"
    )
    # Process.enumerateModules works without Java.perform; wrap anyway so
    # the error-catching boilerplate fires for arch mismatches etc.
    return {
        "channel": "runtime",
        "script": _wrap_java_perform(body),
        "hint": f"One 'modules' event with the {package or '<package>'} app's loaded .so libraries.",
    }


def _action_spawn_log(package: str, params: dict[str, Any]) -> dict[str, Any]:
    """Log application lifecycle (Application.onCreate, MainActivity.onCreate).

    Helps the analyst confirm the hook landed before the app starts
    doing work — Medusa's typical `spawn + run` workflow."""
    body = (
        "    const App = Java.use('android.app.Application');\n"
        "    App.onCreate.implementation = function () {\n"
        "      send({ channel: 'runtime', kind: 'lifecycle', stage: 'Application.onCreate', package: " + _js_string(package) + " });\n"
        "      return this.onCreate.apply(this, arguments);\n"
        "    };\n"
        "    const Activity = Java.use('android.app.Activity');\n"
        "    Activity.onCreate.overload('android.os.Bundle').implementation = function (b) {\n"
        "      send({ channel: 'runtime', kind: 'lifecycle', stage: 'Activity.onCreate', class: this.getClass().getName().toString() });\n"
        "      return this.onCreate(b);\n"
        "    };"
    )
    return {
        "channel": "runtime",
        "script": _wrap_java_perform(body),
        "hint": "Emits one 'lifecycle' event for Application.onCreate and one per Activity.onCreate.",
    }


# ─── dispatcher ───────────────────────────────────────────────────────


_ACTIONS: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]] = {
    "enumerate_classes": _action_enumerate_classes,
    "describe_class":    _action_describe_class,
    "jtrace_method":     _action_jtrace_method,
    "enumerate_modules": _action_enumerate_modules,
    "spawn_log":         _action_spawn_log,
}


def generate_runtime_script(action: str, package: str, params: dict[str, Any]) -> dict[str, Any]:
    """Resolve ``action`` against the dispatcher table.

    Raises:
        KeyError: action name isn't registered (caller should 400).
        ValueError: a parameter failed validation (caller should 400).
    """
    if action not in _ACTIONS:
        raise KeyError(action)
    return _ACTIONS[action](package, params)


def available_actions() -> list[str]:
    """Sorted list of dispatcher keys — useful for /docs and the UI."""
    return sorted(_ACTIONS.keys())
