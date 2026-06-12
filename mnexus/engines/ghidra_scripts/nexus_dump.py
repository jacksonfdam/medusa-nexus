# nexus_dump.py — Ghidra headless post-script (Jython 2.7, NOT host Python).
#
# Runs inside analyzeHeadless via `-postScript nexus_dump.py <out.json>`.
# Dumps a compact JSON view of ONE imported native binary (ELF .so or Mach-O)
# back to the path in argv[0], which ghidra_engine then merges into the
# per-binary Native-tab response. Symbol-table truth, not regex guessing.
#
# Lint-excluded in pyproject — the names below (currentProgram, getScriptArgs,
# println) are injected by Ghidra's GhidraScript runtime, undefined to mypy/ruff.
import json

# Caps so a 50MB stripped blob can't explode the JSON / the HTTP response.
_MAX_FUNCS = 4000
_MAX_IMPORTS = 2000
_MAX_STRINGS = 800

result = {
    "program": None,
    "language": None,
    "functions": [],
    "jni_exports": [],
    "imports": [],
    "strings": [],
}

try:
    result["program"] = str(currentProgram.getName())  # noqa: F821
    result["language"] = str(currentProgram.getLanguageID())  # noqa: F821

    # Defined functions — and the JNI bridge surface (Java_* exports) for free.
    fm = currentProgram.getFunctionManager()  # noqa: F821
    n = 0
    for f in fm.getFunctions(True):
        if n >= _MAX_FUNCS:
            break
        name = str(f.getName())
        result["functions"].append(name)
        if name.startswith("Java_"):
            result["jni_exports"].append(name)
        n += 1

    # External (imported) symbols — ptrace/dlopen/CCCrypt show up here as facts,
    # not as byte matches that might live in an unrelated data section.
    st = currentProgram.getSymbolTable()  # noqa: F821
    n = 0
    for s in st.getExternalSymbols():
        if n >= _MAX_IMPORTS:
            break
        result["imports"].append(str(s.getName()))
        n += 1

    # Defined strings (Ghidra's analysis already classified these).
    listing = currentProgram.getListing()  # noqa: F821
    it = listing.getDefinedData(True)
    n = 0
    while it.hasNext() and n < _MAX_STRINGS:
        d = it.next()
        try:
            dt = str(d.getDataType().getName()).lower()
            if "string" in dt or "unicode" in dt:
                v = d.getValue()
                if v is not None:
                    result["strings"].append(str(v))
                    n += 1
        except Exception:
            pass
except Exception as exc:  # never abort the headless run on a partial dump
    result["error"] = str(exc)

args = getScriptArgs()  # noqa: F821
if args is not None and len(args) > 0:
    fh = open(args[0], "w")
    try:
        fh.write(json.dumps(result))
    finally:
        fh.close()
    println(  # noqa: F821
        "nexus_dump: %d funcs, %d imports, %d strings"
        % (len(result["functions"]), len(result["imports"]), len(result["strings"]))
    )
