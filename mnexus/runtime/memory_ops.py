"""Memory Inspector — live scan / read / write / module enumeration over Frida.

Mirrors the workflow a sénior iOS pentester runs by hand:

  1. ``mem.modules()``    → enumerate loaded modules, find the one
                            you care about (your own binary, a
                            decompressed framework, …).
  2. ``mem.scan(pat)``    → Memory.scanSync across readable ranges
                            (or scoped to a single module). Returns
                            every hit's address.
  3. ``mem.read(addr,n)`` → dump N bytes from that address as hex
                            so the UI can render them as a hex
                            editor.
  4. ``mem.write(a,hex)`` → overwrite with raw bytes. The talk's
                            "token swap" lives here — find the
                            JWT in heap, write the victim's token
                            on top of it.

The "tooling script" exports an RPC surface via Frida's
``rpc.exports``. Loaded once per FridaSession and addressed through
``script.exports_sync.<method>`` from Python (wrapped in
``asyncio.to_thread`` so the event loop doesn't block on Frida's
sync call).

Safety note: the write path is intentionally not gated server-side.
The analyst is the operator; gating belongs in the UI ('are you
sure?' dialog before the request goes out). Memory writes can
crash the target — that's the contract.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)


# Loaded into every FridaSession alongside user-supplied recipes. Stays
# OUT of the IIFE wrapper because rpc.exports has to be at module scope
# in Frida — the IIFE wrapper hides it.
TOOLING_SCRIPT_SOURCE = r"""
// MEDUSA NEXUS memory tooling — auto-injected by FridaSession.
// Exposed RPC surface: mem_scan, mem_read, mem_write, mem_modules.

function _hex_of(byteArray) {
    if (!byteArray) return '';
    var arr = new Uint8Array(byteArray);
    var out = new Array(arr.length);
    for (var i = 0; i < arr.length; i++) {
        var b = arr[i].toString(16);
        out[i] = (b.length === 1) ? '0' + b : b;
    }
    return out.join(' ');
}

function _parse_hex(s) {
    if (!s) return [];
    return s.split(/\s+/).filter(function (t) { return t.length > 0; })
        .map(function (t) { return parseInt(t, 16); });
}

rpc.exports = {
    // Enumerate loaded modules. Caller uses this to choose a scope
    // for mem_scan; without it, the scan runs over every readable
    // range and a 50MB heap can take seconds.
    memModules: function () {
        var mods = Process.enumerateModules();
        return mods.map(function (m) {
            return {
                name: m.name,
                base: m.base.toString(),
                size: m.size,
                path: m.path || ''
            };
        });
    },

    // Scan readable memory for a Frida pattern ('65 6c 6f' or
    // 'aa ?? bb' with wildcards). `module` (string) scopes to one
    // module; `max_results` caps the response.
    memScan: function (pattern, opts) {
        opts = opts || {};
        var maxResults = opts.max_results || opts.maxResults || 100;
        var moduleName = opts.module || null;
        var ranges;
        if (moduleName) {
            var mod = Process.findModuleByName(moduleName);
            if (!mod) return { error: 'module not found: ' + moduleName, results: [] };
            ranges = mod.enumerateRanges('r--');
        } else {
            ranges = Process.enumerateRanges({ protection: 'r--', coalesce: true });
        }
        var results = [];
        var truncated = false;
        for (var i = 0; i < ranges.length; i++) {
            if (results.length >= maxResults) { truncated = true; break; }
            var r = ranges[i];
            try {
                var matches = Memory.scanSync(r.base, r.size, pattern);
                for (var j = 0; j < matches.length; j++) {
                    if (results.length >= maxResults) { truncated = true; break; }
                    results.push({
                        address: matches[j].address.toString(),
                        size: matches[j].size,
                        range_base: r.base.toString(),
                        range_size: r.size,
                        range_protection: r.protection
                    });
                }
            } catch (e) {
                // Some 'r--' regions become unreadable under guard pages;
                // Memory.scanSync raises a TypeError. Skip silently —
                // the analyst gets the readable hits regardless.
            }
        }
        return { results: results, truncated: truncated, ranges_scanned: ranges.length };
    },

    // Read N bytes from an address. Returns space-separated hex.
    memRead: function (address, size) {
        var p = ptr(address);
        var blob;
        try {
            blob = p.readByteArray(size);
        } catch (e) {
            return { error: 'read failed: ' + (e && e.message ? e.message : String(e)) };
        }
        return { address: address, size: size, hex: _hex_of(blob) };
    },

    // Overwrite at an address with raw bytes (space-separated hex).
    // Returns the previous bytes so the analyst can roll back.
    memWrite: function (address, hex) {
        var bytes = _parse_hex(hex);
        if (!bytes.length) return { error: 'no bytes parsed from input' };
        var p = ptr(address);
        var prev;
        try {
            prev = p.readByteArray(bytes.length);
        } catch (e) {
            prev = null;  // can't read prev — write anyway if writable
        }
        try {
            p.writeByteArray(bytes);
        } catch (e) {
            return { error: 'write failed: ' + (e && e.message ? e.message : String(e)) };
        }
        return {
            written: bytes.length,
            address: address,
            previous_hex: prev ? _hex_of(prev) : null
        };
    }
};
"""


class MemoryOps:
    """Async facade over a FridaSession's tooling script.

    Constructed by ``FridaSession`` when the tooling is loaded; callers
    reach it via ``session.mem``. All methods are async on the Python
    side; under the hood they call ``script.exports_sync.<m>(...)``
    inside ``asyncio.to_thread`` to keep the event loop free.
    """

    def __init__(self, tooling_script_handle: Any) -> None:
        self._handle = tooling_script_handle

    async def modules(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._handle.exports_sync.mem_modules)

    async def scan(
        self,
        pattern: str,
        *,
        module: str | None = None,
        max_results: int = 100,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._handle.exports_sync.mem_scan,
            pattern,
            {"module": module, "max_results": max_results},
        )

    async def read(self, address: str, size: int) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._handle.exports_sync.mem_read, address, size,
        )

    async def write(self, address: str, hex_bytes: str) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._handle.exports_sync.mem_write, address, hex_bytes,
        )
