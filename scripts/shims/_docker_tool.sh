#!/usr/bin/env bash
# MEDUSA NEXUS — containerised binary-engine shim (core).
#
# Lets the path-based engines (jadx, apktool, ghidra) run their tool INSIDE the
# ghidra-tools container while believing they spawned a local binary. The
# engines in mnexus/engines/ stay untouched — you only repoint MNEXUS_*_PATH at
# the wrappers in this dir.
#
#   $1   = tool name as it sits on the container PATH (jadx | apktool | analyzeHeadless)
#   $@   = the exact argv the engine built
#
# Host workspace paths are rewritten to the container mount. This works ONLY
# because the orchestrator's Ingest phase copies APK/IPA bytes INTO the
# workspace before any engine runs — so every path an engine passes lives under
# $MNEXUS_HOME/workspace, which the compose file bind-mounts at /workspace.
set -Eeuo pipefail

TOOL="$1"; shift

CONTAINER="${MNEXUS_GHIDRA_TOOLS_CONTAINER:-mnexus-ghidra-tools}"
WS_HOST="${MNEXUS_HOME:-$HOME/.mnexus}/workspace"
WS_CONT="/workspace"

# Rewrite any host-workspace path in argv to its in-container mount point.
args=()
for a in "$@"; do
  args+=( "${a//$WS_HOST/$WS_CONT}" )
done

# No TTY, no stdin: these are batch invocations. stdout/stderr pass straight
# back to the engine's subprocess reader.
exec docker exec "$CONTAINER" "$TOOL" ${args[@]+"${args[@]}"}
