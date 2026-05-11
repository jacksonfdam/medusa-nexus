"""CLI — `mnexus` binary.

Two modes share one entrypoint:

    1. `mnexus`                 → interactive REPL (Claude/Gemini vibe).
    2. `mnexus <subcommand>`    → flat one-shot commands (doctor / scan / serve / etc.).

The interactive mode boots a banner + live engine status, then prompts for
slash-commands. The flat subcommands are unchanged for scripts and CI.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import click
from rich.align import Align
from rich.box import HEAVY, ROUNDED
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from mnexus import __version__
from mnexus.config import NexusConfig
from mnexus.core.orchestrator import MedusaNexus

console = Console()


# ─── Banner ──────────────────────────────────────────────────────────────

_BANNER_LINES = [
    "███╗   ███╗███████╗██████╗ ██╗   ██╗███████╗ █████╗ ",
    "████╗ ████║██╔════╝██╔══██╗██║   ██║██╔════╝██╔══██╗",
    "██╔████╔██║█████╗  ██║  ██║██║   ██║███████╗███████║",
    "██║╚██╔╝██║██╔══╝  ██║  ██║██║   ██║╚════██║██╔══██║",
    "██║ ╚═╝ ██║███████╗██████╔╝╚██████╔╝███████║██║  ██║",
    "╚═╝     ╚═╝╚══════╝╚═════╝  ╚═════╝ ╚══════╝╚═╝  ╚═╝",
    "",
    "███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗",
    "████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝",
    "██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗",
    "██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║",
    "██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║",
    "╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝",
]


def _banner() -> Group:
    """Tri-color banner: cyan title + magenta tagline + acid kicker."""
    body = Text("\n".join(_BANNER_LINES), style="bold cyan")
    tag = Text("every head sees a different angle", style="italic magenta")
    line = Text("─" * 56, style="dim cyan")
    kicker = Text(f"v{__version__}  ·  unified mobile threat analysis", style="bold green")
    return Group(
        Align.center(Text("🔱", style="bold cyan")),
        Align.center(body),
        Align.center(tag),
        Align.center(line),
        Align.center(kicker),
    )


def show_banner() -> None:
    """Print the banner once at REPL startup."""
    console.print()
    console.print(_banner())
    console.print()
    console.print(
        Panel(
            Text.from_markup(
                "[bold cyan]Welcome to MEDUSA NEXUS.[/bold cyan]\n"
                "Type [bold green]/help[/bold green] for commands, [bold green]/doctor[/bold green] to verify engines, "
                "or [bold green]/serve[/bold green] to launch the web UI.\n"
                "Hit [bold magenta]Ctrl-D[/bold magenta] (or type [bold green]/exit[/bold green]) to leave."
            ),
            border_style="cyan",
            box=ROUNDED,
            padding=(0, 2),
        )
    )
    console.print()


# ─── Slash commands ──────────────────────────────────────────────────────

# Each slash command lives in its own function. The dispatcher uses prefix
# matching so `/doc` works as a shortcut for `/doctor`.

class ReplState:
    """Mutable state shared across slash commands within one REPL session."""

    def __init__(self, config: NexusConfig) -> None:
        self.config = config
        self.nexus = MedusaNexus(config)
        self.active_project_id: str | None = None
        self.server_proc: subprocess.Popen[bytes] | None = None
        self.server_host = "127.0.0.1"
        self.server_port = 8765


def _help(state: ReplState, args: list[str]) -> None:
    table = Table(box=ROUNDED, border_style="dim cyan", show_header=True, header_style="bold magenta")
    table.add_column("command", style="bold cyan", no_wrap=True)
    table.add_column("description")
    rows = [
        ("/help",            "Show this table."),
        ("/doctor",          "Run engine health checks (live spinner)."),
        ("/scan <apk>",      "Static scan an APK file. Auto-detects package + version."),
        ("/play-account <verb>", "Manage stored Play identities · list · add · use · delete · show."),
        ("/play-scan <pkg>",     "Stream an APK from Google Play and scan for Firebase / credential leaks."),
        ("/projects",        "List stored projects with risk score + finding counts."),
        ("/use <id>",        "Set the active project for subsequent commands."),
        ("/findings [sev]",  "List findings on the active project (optional severity filter)."),
        ("/rescan",          "Re-run static fan-out on the active project."),
        ("/report [fmt]",    "Generate a report for the active project (md|json|html|pdf)."),
        ("/export <fmt>",    "Write the API collection / deeplink probe (postman|caido|burp|moxy|deeplinks)."),
        ("/serve [port]",    "Start the FastAPI server in the background (default 8765)."),
        ("/stop",            "Stop the background server."),
        ("/open [path]",     "Open the web UI in the browser (default /#/dashboard)."),
        ("/url",             "Print the URL of the running server."),
        ("/devices",         "List ADB-connected devices."),
        ("/adb <args>",      "Run a one-shot adb command (recorded in the audit log)."),
        ("/vphone <verb>",   "super-tart-vphone: list · info · start · stop · ssh · install · status."),
        ("/clear",           "Clear the screen."),
        ("/exit, /quit",     "Leave the REPL."),
    ]
    for cmd, desc in rows:
        table.add_row(cmd, desc)
    console.print(table)


def _doctor(state: ReplState, args: list[str]) -> None:
    """Run /v1/doctor with a live spinner per row.

    Pass ``--env`` (or ``-e``) to also dump the MNEXUS_* env vars the running
    process actually sees — handy when an engine reports MISS because the
    shell that launched mnexus didn't source ~/.mnexus/env.sh.
    """
    show_env = any(a in ("--env", "-e", "--verbose", "-v") for a in args)

    console.print()
    spinner = Spinner("dots", text=Text("running engine health checks…", style="cyan"))
    with Live(spinner, console=console, transient=True):
        results = asyncio.run(state.nexus.doctor())

    table = Table(box=ROUNDED, border_style="dim cyan", show_header=True, header_style="bold magenta")
    table.add_column("engine", style="bold cyan", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("version")
    table.add_column("note", style="dim")
    ok = bad = 0
    for r in results:
        installed = r["installed"]
        if installed:
            status = Text("● OK", style="bold green")
            ok += 1
        else:
            status = Text("● MISS", style="bold red")
            bad += 1
        table.add_row(str(r["name"]), status, str(r["version"] or "—"), str(r["message"]))
    console.print(table)
    if bad:
        console.print(f"  [bold red]{bad}[/bold red] engine(s) missing · [green]{ok}[/green] healthy")
    else:
        console.print(f"  [bold green]all {ok} engines online[/bold green] — every head answered")

    if show_env:
        _doctor_env_dump(state)
    elif bad:
        console.print("  [dim]hint: re-run with [bold]/doctor --env[/bold] to see which MNEXUS_* vars made it to this process[/dim]")


def _doctor_env_dump(state: ReplState) -> None:
    """Print every MNEXUS_* env var the running process can see, with secrets masked.

    Reads from `os.environ` directly (the source of truth for the current
    shell) AND from `state.config` (the values pydantic actually loaded into
    the orchestrator). When the two disagree the issue is almost always that
    the user `source`d env.sh in another shell, or that some other layer
    (a wrapper script, a pyenv shim) clobbered the env.
    """
    table = Table(box=ROUNDED, border_style="dim magenta", show_header=True,
                  header_style="bold magenta", title="MNEXUS_* environment", title_style="dim")
    table.add_column("variable", style="bold cyan", no_wrap=True)
    table.add_column("os.environ", no_wrap=False)
    table.add_column("nexus.config", no_wrap=False)

    def mask(value: object) -> str:
        if value is None or value == "":
            return "[dim]—[/dim]"
        s = str(value)
        if any(t in (table_var or "") for t in ("KEY", "TOKEN", "SECRET")):
            return s[:4] + "…" + s[-4:] if len(s) > 12 else "[dim]set[/dim]"
        return s

    cfg = state.config
    rows = [
        ("MNEXUS_ADB_PATH",      cfg.adb_path),
        ("MNEXUS_JADX_PATH",     cfg.jadx_path),
        ("MNEXUS_APKTOOL_PATH",  cfg.apktool_path),
        ("MNEXUS_GHIDRA_PATH",   cfg.ghidra_path),
        ("MNEXUS_MEDUSA_PATH",   cfg.medusa_path),
        ("MNEXUS_STHENO_PATH",   cfg.stheno_path),
        ("MNEXUS_WORKSPACE",     cfg.workspace),
        ("MNEXUS_DB_PATH",       cfg.db_path),
        ("MNEXUS_MOBSF_URL",     cfg.mobsf_url),
        ("MNEXUS_MOBSF_API_KEY", cfg.mobsf_api_key),
        ("MNEXUS_BURP_URL",      cfg.burp_url),
        ("MNEXUS_BURP_API_KEY",  cfg.burp_api_key),
        ("MNEXUS_CAIDO_URL",     cfg.caido_url),
        ("MNEXUS_CAIDO_API_KEY", cfg.caido_api_key),
        ("MNEXUS_PROXY_FLAVOR",  cfg.proxy_flavor),
    ]
    for table_var, cfg_value in rows:
        env_value = os.environ.get(table_var)
        env_cell = mask(env_value) if env_value is not None else "[dim]unset[/dim]"
        cfg_cell = mask(cfg_value)
        # Highlight mismatches — the most common cause of "MISS but env is set".
        if env_value is None and cfg_value not in (None, "", cfg.__class__.model_fields[_field_for(table_var)].default):
            cfg_cell = f"[yellow]{cfg_cell}[/yellow] [dim](from default)[/dim]"
        elif env_value is not None and str(cfg_value or "") != str(env_value):
            cfg_cell = f"[red]{cfg_cell}[/red] [dim](≠ env)[/dim]"
        table.add_row(table_var, env_cell, cfg_cell)
    console.print()
    console.print(table)


def _field_for(env_var: str) -> str:
    """MNEXUS_FOO_BAR → foo_bar (NexusConfig field name)."""
    return env_var.removeprefix("MNEXUS_").lower()


def _scan(state: ReplState, args: list[str]) -> None:
    if not args:
        console.print("[red]usage:[/red] /scan <apk-path> [--package <pkg>] [--version <ver>]")
        return
    apk_path = Path(args[0]).expanduser()
    if not apk_path.exists():
        console.print(f"[red]not found:[/red] {apk_path}")
        return

    package = ""
    version = "unknown"
    it = iter(args[1:])
    for tok in it:
        if tok in ("--package", "-p"):
            package = next(it, "")
        elif tok in ("--version", "-v"):
            version = next(it, "unknown")

    # Try to auto-detect.
    if not package:
        engine = state.nexus.engines.get("apktool")
        if engine is not None:
            try:
                meta = asyncio.run(engine.extract_manifest(apk_path))
                package = meta.get("package", "")
                if not version or version == "unknown":
                    version = meta.get("version_name") or "unknown"
            except Exception:
                pass
    if not package:
        package = Prompt.ask("[cyan]package[/cyan] (e.g. com.target.app)")

    spinner = Spinner("dots", text=Text(f"ingesting {apk_path.name}…", style="cyan"))
    with Live(spinner, console=console, transient=True):
        project = asyncio.run(state.nexus.ingest_apk(apk_path, package_name=package, version=version))

    surface = project.attack_surface
    score = surface.risk_score() if surface else 0.0
    total = len(surface.findings) if surface else 0
    counts = surface.findings_by_severity() if surface else {}
    state.active_project_id = project.id

    panel = Panel(
        Text.from_markup(
            f"[bold cyan]{project.id}[/bold cyan]  ·  [magenta]{project.name}[/magenta]\n\n"
            f"[bold green]risk[/bold green]      {score}/100\n"
            f"[bold green]findings[/bold green]  {total}  "
            f"([red]{counts.get('critical', 0)}c[/red] [yellow]{counts.get('high', 0)}h[/yellow] "
            f"{counts.get('medium', 0)}m {counts.get('low', 0)}l)\n"
            f"[bold green]surface[/bold green]   {len(surface.exported_components) if surface else 0} components · "
            f"{len(surface.deeplinks) if surface else 0} deeplinks · "
            f"{len(surface.native_libraries) if surface else 0} native libs\n"
            f"[bold green]hooks[/bold green]     {len(project.suggested_hooks)} auto-generated\n\n"
            f"[dim]Active project set. Try [/dim][bold green]/findings[/bold green][dim] or "
            f"[/dim][bold green]/report[/bold green][dim].[/dim]"
        ),
        title="[bold cyan]✓ ingest complete[/bold cyan]",
        border_style="green",
        box=ROUNDED,
        padding=(0, 2),
    )
    console.print(panel)


def _projects(state: ReplState, args: list[str]) -> None:
    rows = state.nexus.db.list_projects()
    if not rows:
        console.print("[dim]no projects yet — try[/dim] [bold green]/scan ./target.apk[/bold green]")
        return
    table = Table(box=ROUNDED, border_style="dim cyan", show_header=True, header_style="bold magenta")
    table.add_column("id", style="bold cyan", no_wrap=True)
    table.add_column("package", style="cyan")
    table.add_column("version")
    table.add_column("risk", justify="right")
    table.add_column("findings", justify="right")
    table.add_column("updated", style="dim")
    for r in rows:
        proj = state.nexus.db.load_project(r["id"])
        if not proj or not proj.attack_surface:
            risk = 0.0
            n = 0
        else:
            risk = proj.attack_surface.risk_score()
            n = len(proj.attack_surface.findings)
        active = " ◀" if r["id"] == state.active_project_id else ""
        risk_color = "red" if risk >= 75 else ("yellow" if risk >= 50 else "green")
        table.add_row(
            f"{r['id']}{active}",
            r["package_name"] or "—",
            r["version_name"] or "—",
            Text(f"{risk:.1f}", style=risk_color),
            str(n),
            (r.get("updated_at") or "")[:19],
        )
    console.print(table)


def _use(state: ReplState, args: list[str]) -> None:
    if not args:
        console.print("[red]usage:[/red] /use <PRJ-id>")
        return
    pid = args[0]
    proj = state.nexus.db.load_project(pid)
    if not proj:
        console.print(f"[red]no project:[/red] {pid}")
        return
    state.active_project_id = pid
    console.print(f"[green]✓ active project:[/green] [bold cyan]{pid}[/bold cyan] · {proj.package_name}")


def _findings(state: ReplState, args: list[str]) -> None:
    pid = state.active_project_id
    if not pid:
        console.print("[red]no active project — run /use <id> first[/red]")
        return
    proj = state.nexus.db.load_project(pid)
    if not proj or not proj.attack_surface:
        console.print("[dim]no findings on this project[/dim]")
        return
    sev_filter = args[0].lower() if args else ""
    findings = proj.attack_surface.findings
    if sev_filter:
        findings = [f for f in findings if f.severity.value == sev_filter]
    if not findings:
        console.print(f"[dim]no findings{' at severity=' + sev_filter if sev_filter else ''}[/dim]")
        return
    table = Table(box=ROUNDED, border_style="dim cyan", show_header=True, header_style="bold magenta")
    table.add_column("id", style="bold cyan", no_wrap=True)
    table.add_column("sev", no_wrap=True)
    table.add_column("engine", style="cyan")
    table.add_column("title")
    table.add_column("location", style="dim")
    SEV_STYLE = {"critical": "bold red", "high": "yellow", "medium": "magenta", "low": "green", "info": "dim"}
    for f in findings:
        table.add_row(
            f.id,
            Text(f.severity.value.upper(), style=SEV_STYLE.get(f.severity.value, "white")),
            f.source_engine,
            f.title[:80],
            (f.location or "—")[:40],
        )
    console.print(table)


def _rescan(state: ReplState, args: list[str]) -> None:
    pid = state.active_project_id
    if not pid:
        console.print("[red]no active project — run /use <id> first[/red]")
        return
    proj = state.nexus.db.load_project(pid)
    if not proj:
        console.print(f"[red]no project: {pid}[/red]")
        return
    apk = proj.apk_path if isinstance(proj.apk_path, Path) else Path(str(proj.apk_path))
    if not apk.exists():
        console.print(f"[red]APK no longer at {apk} — re-import[/red]")
        return
    spinner = Spinner("dots", text=Text(f"re-running pipeline on {pid}…", style="cyan"))
    with Live(spinner, console=console, transient=True):
        proj = asyncio.run(state.nexus.ingest_apk(apk, package_name=proj.package_name, version=proj.version_name, existing_id=proj.id))
    n = len(proj.attack_surface.findings) if proj.attack_surface else 0
    risk = proj.attack_surface.risk_score() if proj.attack_surface else 0.0
    console.print(f"[green]✓ rescan done[/green] · {n} findings · risk {risk}/100")


def _report(state: ReplState, args: list[str]) -> None:
    pid = state.active_project_id
    if not pid:
        console.print("[red]no active project — /use <id> first[/red]")
        return
    fmt = (args[0] if args else "markdown").lower()
    if fmt in ("md",):
        fmt = "markdown"
    if fmt not in ("markdown", "json", "html", "pdf"):
        console.print(f"[red]unknown format[/red] {fmt} (use markdown|json|html|pdf)")
        return
    out_dir = state.config.workspace / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = {"markdown": "md", "json": "json", "html": "html", "pdf": "pdf"}[fmt]
    out = out_dir / f"{pid}.{suffix}"
    proj = state.nexus.db.load_project(pid)
    if not proj:
        console.print(f"[red]no project: {pid}[/red]")
        return
    from mnexus.reporting.generator import ReportFormat, ReportGenerator, ReportTemplate
    try:
        ReportGenerator(proj).generate(ReportTemplate.TECHNICAL, ReportFormat(fmt), str(out))
    except NotImplementedError as e:
        console.print(f"[yellow]format not implemented yet:[/yellow] {e}")
        return
    console.print(f"[green]✓ report:[/green] [bold cyan]{out}[/bold cyan]")


def _serve(state: ReplState, args: list[str]) -> None:
    if state.server_proc and state.server_proc.poll() is None:
        console.print(f"[yellow]server already running[/yellow] on http://{state.server_host}:{state.server_port}")
        return
    if args:
        try:
            state.server_port = int(args[0])
        except ValueError:
            console.print(f"[red]bad port:[/red] {args[0]}")
            return
    cmd = [sys.executable, "-m", "uvicorn", "mnexus.api.main:app",
           "--host", state.server_host, "--port", str(state.server_port)]
    spinner = Spinner("dots", text=Text(f"starting server on {state.server_host}:{state.server_port}…", style="cyan"))
    with Live(spinner, console=console, transient=True):
        state.server_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Wait for /v1/health.
        url = f"http://{state.server_host}:{state.server_port}/v1/health"
        deadline = time.time() + 8.0
        ok = False
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=0.4) as r:
                    if r.status == 200:
                        ok = True
                        break
            except Exception:
                pass
            time.sleep(0.2)
    if ok:
        console.print(
            Panel(
                Text.from_markup(
                    f"[bold green]✓ server ready[/bold green]\n"
                    f"[cyan]web ui[/cyan]   http://{state.server_host}:{state.server_port}/\n"
                    f"[cyan]swagger[/cyan]  http://{state.server_host}:{state.server_port}/docs"
                ),
                border_style="green",
                box=ROUNDED,
                padding=(0, 2),
            )
        )
    else:
        console.print("[red]✕ server didn't answer /v1/health within 8s — check `mnexus serve` directly[/red]")


def _stop(state: ReplState, args: list[str]) -> None:
    if not state.server_proc or state.server_proc.poll() is not None:
        console.print("[dim]no running server[/dim]")
        return
    state.server_proc.terminate()
    try:
        state.server_proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        state.server_proc.kill()
    state.server_proc = None
    console.print("[green]✓ server stopped[/green]")


def _open(state: ReplState, args: list[str]) -> None:
    import webbrowser
    path = args[0] if args else "/"
    if not path.startswith("/"):
        path = "/" + path
    url = f"http://{state.server_host}:{state.server_port}{path}"
    webbrowser.open(url)
    console.print(f"[green]→ opening[/green] {url}")


def _url(state: ReplState, args: list[str]) -> None:
    console.print(f"[cyan]{state.server_host}:{state.server_port}[/cyan] · "
                  f"http://{state.server_host}:{state.server_port}/")


def _devices(state: ReplState, args: list[str]) -> None:
    """Quick `adb devices -l` listing."""
    import shutil
    if not shutil.which(state.config.adb_path):
        console.print("[red]adb not on PATH[/red]")
        return
    proc = subprocess.run([state.config.adb_path, "devices", "-l"], capture_output=True, text=True)
    out = proc.stdout.strip()
    if not out:
        console.print("[dim]no devices[/dim]")
        return
    console.print(Panel(out, title="[bold cyan]adb devices -l[/bold cyan]", border_style="dim cyan", box=ROUNDED))


def _adb(state: ReplState, args: list[str]) -> None:
    if not args:
        console.print("[red]usage:[/red] /adb <args…>  (e.g. /adb shell getprop ro.build.version.release)")
        return
    import shutil
    if not shutil.which(state.config.adb_path):
        console.print("[red]adb not on PATH[/red]")
        return
    proc = subprocess.run([state.config.adb_path, *args], capture_output=True, text=True)
    out = (proc.stdout + proc.stderr).strip() or "(no output)"
    style = "green" if proc.returncode == 0 else "red"
    console.print(Panel(out, title=f"[bold {style}]$ adb {' '.join(args)}[/bold {style}]", border_style=style, box=ROUNDED))


def _play_account(state: ReplState, args: list[str]) -> None:
    """`/play-account <verb> [...]` — manage stored Play identities.

    Verbs: add · list (ls) · use · delete (rm) · show.

    Bare `/play-account` is treated as `list`. Names are
    alphanumeric/-/_ only and unique; one account can be flagged
    default and that's the one `/play-scan` uses when no `--account`
    is given.
    """
    verb = (args[0] if args else "list").lower()
    rest = args[1:]

    if verb in ("list", "ls"):
        _play_account_list(state)
    elif verb == "add":
        _play_account_add(state, rest)
    elif verb == "use":
        _play_account_use(state, rest)
    elif verb in ("delete", "rm"):
        _play_account_delete(state, rest)
    elif verb == "show":
        _play_account_show(state, rest)
    else:
        console.print(
            f"[red]unknown verb:[/red] {verb}  (try: list · add · use · delete · show)"
        )


def _play_account_list(state: ReplState) -> None:
    accounts = state.nexus.db.list_play_accounts()
    if not accounts:
        console.print(
            "[dim]no Play accounts stored. add one with [/dim]"
            "[bold green]/play-account add --name <handle> --email <gmail> "
            "--password <pw>[/bold green]"
        )
        return
    table = Table(box=ROUNDED, border_style="dim cyan", show_header=True, header_style="bold magenta")
    table.add_column("name", style="bold cyan", no_wrap=True)
    table.add_column("email")
    table.add_column("gsfid", style="dim")
    table.add_column("notes", style="dim")
    table.add_column("default", justify="center")
    for a in accounts:
        local, _, domain = a.email.partition("@")
        masked_email = f"{local}@{domain}" if domain else a.email
        table.add_row(
            a.name,
            masked_email,
            "✓" if a.gsfid else "—",
            (a.notes or "")[:40],
            "★" if a.is_default else "",
        )
    console.print(table)


def _play_account_add(state: ReplState, args: list[str]) -> None:
    name = ""
    email = ""
    aas = ""
    password = ""
    notes = ""
    set_default = False
    it = iter(args)
    for tok in it:
        if tok in ("--name", "-n"):
            name = next(it, "")
        elif tok in ("--email", "-e"):
            email = next(it, "")
        elif tok in ("--aas", "-a"):
            aas = next(it, "")
        elif tok in ("--password", "-p"):
            password = next(it, "")
        elif tok in ("--notes",):
            notes = next(it, "")
        elif tok in ("--default", "-d"):
            set_default = True
        else:
            console.print(f"[yellow]ignored arg:[/yellow] {tok}")

    if not name:
        name = Prompt.ask("[cyan]name[/cyan] (handle, e.g. research-1)").strip()
    if not email:
        email = Prompt.ask("[cyan]gmail[/cyan]").strip()
    if not aas and not password:
        secret = Prompt.ask(
            "[cyan]aas_token[/cyan] (paste existing, or leave empty to enter password)",
            password=True,
        ).strip()
        if secret.startswith("aas_") or len(secret) > 60:
            aas = secret
        else:
            password = secret or Prompt.ask(
                "[cyan]google password[/cyan] (or app password if 2FA is on)",
                password=True,
            ).strip()
    if not name or not email or not (aas or password):
        console.print("[red]name, email, and one of (aas, password) are required[/red]")
        return

    from mnexus.models.play_account import PlayAccount
    from mnexus.playintel.play_client import PlayAuthError, PlayCredentials

    if aas:
        token = aas
    else:
        spinner = Spinner("dots", text=Text("minting AAS token via /auth…", style="cyan"))
        try:
            with Live(spinner, console=console, transient=True):
                creds = PlayCredentials.from_password(email, password)
        except PlayAuthError as e:
            console.print(f"[red]login failed:[/red] {e}")
            return
        token = creds.aas_token

    # If this is the first stored account, promote it to default
    # automatically — saves a second `use` step on the happy path.
    existing = state.nexus.db.list_play_accounts()
    if not existing:
        set_default = True

    try:
        account = PlayAccount(
            name=name,
            email=email,
            aas_token=token,
            notes=notes,
            is_default=set_default,
        )
    except ValueError as e:
        console.print(f"[red]invalid input:[/red] {e}")
        return

    state.nexus.db.save_play_account(account)
    console.print(
        f"[green]✓ stored[/green] [bold cyan]{name}[/bold cyan]"
        + (" [magenta]·  default[/magenta]" if set_default else "")
    )
    if not aas:
        console.print(
            "[dim]Minted AAS token from password; the password itself was not stored.[/dim]"
        )
    console.print(
        "[dim]Run [bold]/play-scan <package>[/bold] to verify (first call "
        "mints a GSFID via /checkin and persists it back to the row).[/dim]"
    )


def _play_account_use(state: ReplState, args: list[str]) -> None:
    if not args:
        console.print("[red]usage:[/red] /play-account use <name>")
        return
    name = args[0]
    if state.nexus.db.set_default_play_account(name):
        console.print(f"[green]✓ default →[/green] [bold cyan]{name}[/bold cyan]")
    else:
        console.print(f"[red]no Play account named:[/red] {name}")


def _play_account_delete(state: ReplState, args: list[str]) -> None:
    if not args:
        console.print("[red]usage:[/red] /play-account delete <name>")
        return
    name = args[0]
    if state.nexus.db.delete_play_account(name):
        console.print(f"[green]✓ deleted[/green] [bold cyan]{name}[/bold cyan]")
    else:
        console.print(f"[yellow]nothing to delete:[/yellow] {name}")


def _play_account_show(state: ReplState, args: list[str]) -> None:
    if not args:
        console.print("[red]usage:[/red] /play-account show <name>")
        return
    account = state.nexus.db.get_play_account(args[0])
    if account is None:
        console.print(f"[red]no Play account named:[/red] {args[0]}")
        return
    redacted = account.redact()
    body = "\n".join(f"[cyan]{k}:[/cyan] {v}" for k, v in redacted.items())
    console.print(
        Panel(
            body,
            title=f"[bold cyan]🔑 {account.name}[/bold cyan]",
            border_style="cyan",
            box=ROUNDED,
        )
    )


def _play_scan(state: ReplState, args: list[str]) -> None:
    """`/play-scan <package>` — stream an APK from Google Play and analyze it.

    Active Firebase / Firestore / Storage probes are **opt-in** (you're hitting
    third-party services on behalf of someone else's app — be explicit about
    consent). Pass ``--probe`` to enable, or set
    ``MNEXUS_PLAYINTEL_ACTIVE_PROBES=1`` in the environment.
    """
    if not args:
        console.print(
            "[red]usage:[/red] /play-scan <package> [--apk <local-path>] [--probe]"
        )
        return

    package = args[0]
    apk_override: Path | None = None
    # Default OFF — active probes are an opt-in network-touch.
    env_flag = os.environ.get("MNEXUS_PLAYINTEL_ACTIVE_PROBES", "").lower() in {"1", "true", "yes", "on"}
    run_probes = env_flag
    account_name: str | None = None
    it = iter(args[1:])
    for tok in it:
        if tok in ("--apk", "-a"):
            val = next(it, "")
            if val:
                apk_override = Path(val).expanduser()
        elif tok in ("--account", "-A"):
            val = next(it, "")
            if val:
                account_name = val
        elif tok in ("--probe", "--probes"):
            run_probes = True
        elif tok in ("--no-probe", "--no-probes"):
            run_probes = False
        else:
            console.print(f"[yellow]ignored arg:[/yellow] {tok}")
    if run_probes:
        console.print(
            "[yellow]⚠ active probes enabled — this hits the target's Firebase / Firestore / Storage. "
            "Make sure you have permission to test this app.[/yellow]"
        )

    from mnexus.engines.play_intel_engine import PlayIntelEngine
    from mnexus.playintel.apk_source import (
        BundledAPKSource,
        PlayProtocolSource,
        local_source_for,
    )
    from mnexus.playintel.play_client import PlayAuthError

    play_source = None
    bundled_source = None
    if apk_override and apk_override.exists():
        source = local_source_for(apk_override, workspace=state.config.workspace)
        if isinstance(source, BundledAPKSource):
            bundled_source = source
            source_label = f"local-bundle:{apk_override.name}"
        else:
            source_label = f"local:{apk_override.name}"
    else:
        try:
            play_source = PlayProtocolSource(
                account_name=account_name, store=state.nexus.db
            )
            source = play_source
            source_label = (
                f"play:{play_source._client.credentials.account_name}"  # noqa: SLF001
                if play_source._client.credentials.account_name  # noqa: SLF001
                else "play"
            )
        except PlayAuthError as e:
            console.print(f"[red]Play auth failed:[/red] {e}")
            console.print(
                "[dim]Add an account with [bold]/play-account add[/bold] "
                "or pass [bold]--apk <local-file>[/bold].[/dim]"
            )
            return

    engine = PlayIntelEngine(state.config)
    spinner = Spinner(
        "dots", text=Text(f"streaming + scanning {package} via {source_label}…", style="cyan")
    )
    try:
        with Live(spinner, console=console, transient=True):
            outcome, findings = asyncio.run(
                engine.analyze_package(
                    package,
                    source=source,
                    workspace=state.config.workspace,
                    run_active_probes=run_probes,
                )
            )
    finally:
        if play_source is not None:
            play_source.close()
        if bundled_source is not None:
            bundled_source.close()

    n_secrets = len(outcome.report.confirmed_secrets())
    n_suspected = len(outcome.report.suspected_secrets())
    n_configs = len({c.project_id for c in outcome.report.firebase_configs if c.project_id})
    n_vulns = len(outcome.report.vulnerabilities)

    panel = Panel(
        Text.from_markup(
            f"[bold cyan]{package}[/bold cyan]  ·  [magenta]{source_label}[/magenta]\n\n"
            f"[bold green]firebase configs[/bold green]   {n_configs} unique project(s)\n"
            f"[bold green]confirmed secrets[/bold green]  {n_secrets}\n"
            f"[bold green]suspected[/bold green]          {n_suspected} (review manually)\n"
            f"[bold green]active vulns[/bold green]       {n_vulns}\n"
            f"[bold green]findings[/bold green]           {len(findings)}\n"
            f"[bold green]saved to[/bold green]           "
            f"{outcome.saved_files_dir or '— (nothing saved)'}\n"
        ),
        title="[bold cyan]✓ play-scan complete[/bold cyan]",
        border_style="green",
        box=ROUNDED,
        padding=(0, 2),
    )
    console.print(panel)

    if findings:
        table = Table(box=ROUNDED, border_style="dim cyan", show_header=True, header_style="bold magenta")
        table.add_column("sev", no_wrap=True)
        table.add_column("title")
        table.add_column("location", style="dim")
        SEV_STYLE = {"critical": "bold red", "high": "yellow", "medium": "magenta", "low": "green", "info": "dim"}
        for f in findings:
            table.add_row(
                Text(f.severity.value.upper(), style=SEV_STYLE.get(f.severity.value, "white")),
                f.title[:80],
                (f.location or "—")[:50],
            )
        console.print(table)


def _vphone(state: ReplState, args: list[str]) -> None:
    """`/vphone [list|info|start|stop|ssh|install|status] …` — super-tart-vphone control."""
    verb = (args[0] if args else "list").lower()
    rest = args[1:]
    eng = state.nexus.engines.get("vphone")
    if eng is None:
        console.print("[red]vphone engine not registered[/red]")
        return

    if verb == "status":
        # Same shape as /v1/doctor — but only for vphone.
        result = asyncio.run(eng.health_check())
        style = "green" if result.installed else "yellow"
        console.print(Panel(
            f"[bold {style}]{('● OK' if result.installed else '● MISSING')}[/bold {style}]   "
            f"[dim]{result.message}[/dim]\n"
            f"[cyan]version:[/cyan] {result.version or '—'}\n"
            f"[cyan]path:[/cyan]    {result.path or '—'}",
            title="[bold cyan]🔱 vphone status[/bold cyan]",
            border_style=style, box=ROUNDED,
        ))
        return

    if verb in ("list", "ls"):
        rows = asyncio.run(eng.list_vms())
        if not rows:
            console.print("[dim]no VMs (or `tart` not configured) — run scripts/setup-vphone.sh[/dim]")
            return
        table = Table(box=ROUNDED, border_style="dim cyan", show_header=True, header_style="bold magenta")
        table.add_column("name", style="bold cyan", no_wrap=True)
        table.add_column("state")
        table.add_column("size", style="dim")
        table.add_column("source", style="dim")
        for r in rows:
            state_label = r.get("state", "")
            running = r.get("running")
            chip = Text(state_label, style="bold green" if running else "dim")
            table.add_row(r.get("name", ""), chip, r.get("size", ""), r.get("source", ""))
        console.print(table)
        return

    if verb == "info":
        if not rest:
            console.print("[red]usage:[/red] /vphone info <name>")
            return
        info = asyncio.run(eng.vm_info(rest[0]))
        if not info.get("exists"):
            console.print(f"[red]no such VM:[/red] {rest[0]} — {info.get('reason', '')}")
            return
        console.print(Panel(
            "\n".join(f"[cyan]{k}:[/cyan] {v}" for k, v in info.items() if k not in ("raw", "exists")),
            title=f"[bold cyan]🔱 vphone · {rest[0]}[/bold cyan]",
            border_style="cyan", box=ROUNDED,
        ))
        return

    if verb in ("start", "boot"):
        if not rest:
            console.print("[red]usage:[/red] /vphone start <name>")
            return
        try:
            res = asyncio.run(eng.start(rest[0]))
        except RuntimeError as e:
            console.print(f"[red]start failed:[/red] {e}")
            return
        if res.get("already_running"):
            console.print(f"[yellow]already running:[/yellow] pid={res['pid']}")
        else:
            console.print(f"[green]✓ started[/green] [bold cyan]{rest[0]}[/bold cyan] · pid={res['pid']} · ssh: {res['ssh_endpoint']}")
        return

    if verb == "stop":
        if not rest:
            console.print("[red]usage:[/red] /vphone stop <name>")
            return
        try:
            res = asyncio.run(eng.stop(rest[0]))
        except RuntimeError as e:
            console.print(f"[red]stop failed:[/red] {e}")
            return
        marker = "✓" if res["exit"] == 0 else "✕"
        style = "green" if res["exit"] == 0 else "red"
        console.print(f"[bold {style}]{marker}[/bold {style}] stop {rest[0]} · exit={res['exit']}")
        if res["output"].strip():
            console.print(f"[dim]{res['output'].strip()[:200]}[/dim]")
        return

    if verb == "ssh":
        if len(rest) < 2:
            console.print("[red]usage:[/red] /vphone ssh <name> -- <cmd…>")
            return
        # Drop a leading `--` separator if the user typed it.
        target = rest[0]
        cmd_tokens = rest[1:]
        if cmd_tokens and cmd_tokens[0] == "--":
            cmd_tokens = cmd_tokens[1:]
        cmd = " ".join(cmd_tokens)
        if not cmd:
            console.print("[red]empty command[/red]")
            return
        res = asyncio.run(eng.ssh(target, cmd))
        title_style = "green" if res["exit"] == 0 else "red"
        console.print(Panel(
            res["output"].strip() or "(no output)",
            title=f"[bold {title_style}]$ ssh {target} -- {cmd}[/bold {title_style}]  [dim]exit={res['exit']}[/dim]",
            border_style=title_style, box=ROUNDED,
        ))
        return

    if verb == "install":
        if len(rest) < 2:
            console.print("[red]usage:[/red] /vphone install <name> <ipa-path>")
            return
        ipa = Path(rest[1]).expanduser()
        if not ipa.exists():
            console.print(f"[red]not found:[/red] {ipa}")
            return
        spinner = Spinner("dots", text=Text(f"installing {ipa.name} → {rest[0]}…", style="cyan"))
        with Live(spinner, console=console, transient=True):
            res = asyncio.run(eng.install_ipa(rest[0], ipa))
        if res.get("ok"):
            console.print(f"[green]✓ installed[/green] [bold cyan]{res.get('bundle','')}[/bold cyan]")
        else:
            console.print("[red]✕ install failed[/red]")
            console.print(Panel(res.get("log", "(no log)"), border_style="red", box=ROUNDED))
        return

    console.print(f"[red]unknown vphone verb:[/red] {verb}  (try: list · info · start · stop · ssh · install · status)")


def _clear(state: ReplState, args: list[str]) -> None:
    console.clear()
    show_banner()


def _exit(state: ReplState, args: list[str]) -> None:
    raise EOFError


def _export(state: ReplState, args: list[str]) -> None:
    """`/export <fmt> [--project <id>] [--out <dir>]` — write the export to disk.

    Formats: postman, caido, burp, moxy, deeplinks.
    Pulls from the active project (set via /use) unless --project is passed.
    """
    if not args or args[0] in ("-h", "--help"):
        console.print(
            "[red]usage:[/red] /export <postman|caido|burp|moxy|deeplinks> "
            "[--project <id>] [--out <dir>]"
        )
        return

    fmt = args[0].lower()
    valid = {"postman", "caido", "burp", "moxy", "deeplinks", "deeplink"}
    if fmt not in valid:
        console.print(f"[red]unknown format:[/red] {fmt} — pick one of {sorted(valid)}")
        return

    project_id = state.active_project_id
    out_dir = Path.cwd()
    it = iter(args[1:])
    for tok in it:
        if tok in ("--project", "-p"):
            project_id = next(it, "")
        elif tok in ("--out", "-o"):
            out_dir = Path(next(it, ".")).expanduser()
    if not project_id:
        console.print("[red]no active project.[/red] Run [bold]/use <id>[/bold] or pass [bold]--project <id>[/bold].")
        return

    project = state.nexus.db.load_project(project_id)
    if not project:
        console.print(f"[red]no project with id[/red] {project_id}")
        return

    from mnexus.exporters import (
        to_burp_items,
        to_caido,
        to_deeplink_script,
        to_moxy_config,
        to_postman,
    )

    generators = {
        "postman":   (to_postman,         "postman_collection.json"),
        "caido":     (to_caido,           "caido.json"),
        "burp":      (to_burp_items,      "burp-items.xml"),
        "moxy":      (to_moxy_config,     "moxy.yml"),
        "deeplinks": (to_deeplink_script, "deeplink-probe.sh"),
        "deeplink":  (to_deeplink_script, "deeplink-probe.sh"),
    }
    gen, suffix = generators[fmt]
    out_path = out_dir / f"{project_id}-{suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)
    body = gen(project)
    out_path.write_text(body, encoding="utf-8")
    if fmt in ("deeplinks", "deeplink"):
        out_path.chmod(0o755)
    console.print(f"[green]✓ {fmt}[/green] · [bold]{out_path}[/bold] · {len(body)} bytes")


# Dispatch table — first match by prefix wins on ambiguity.
SLASH_COMMANDS = {
    "help":      _help,
    "doctor":    _doctor,
    "scan":      _scan,
    "play-account":  _play_account,
    "play-accounts": _play_account,  # alias matches the noun-phrase reflex
    "play-scan":     _play_scan,
    "projects":  _projects,
    "use":       _use,
    "findings":  _findings,
    "rescan":    _rescan,
    "report":    _report,
    "export":    _export,
    "exports":   _export,
    "serve":     _serve,
    "stop":      _stop,
    "open":      _open,
    "url":       _url,
    "devices":   _devices,
    "adb":       _adb,
    "vphone":    _vphone,
    "vphones":   _vphone,
    "clear":     _clear,
    "exit":      _exit,
    "quit":      _exit,
}


def _resolve_slash(name: str) -> tuple[str, callable] | None:
    """Exact match first, then unique prefix match."""
    if name in SLASH_COMMANDS:
        return name, SLASH_COMMANDS[name]
    matches = [(k, v) for k, v in SLASH_COMMANDS.items() if k.startswith(name)]
    return matches[0] if len(matches) == 1 else None


# ─── Optional: prompt_toolkit completer for cushy autocomplete ───────────

def _make_session():
    """Return a prompt_toolkit PromptSession if available, else None."""
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import WordCompleter
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.styles import Style
    except ImportError:
        return None
    history_path = Path.home() / ".mnexus" / "history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    completer = WordCompleter(
        ["/" + c for c in SLASH_COMMANDS.keys()],
        ignore_case=True, sentence=True,
    )
    style = Style.from_dict({"prompt": "bold cyan", "rprompt": "magenta"})
    return PromptSession(
        history=FileHistory(str(history_path)),
        completer=completer,
        style=style,
        complete_while_typing=True,
    )


def _repl(config: NexusConfig) -> int:
    state = ReplState(config)
    show_banner()
    # First boot: run a quick doctor with concise output.
    _doctor_brief(state)

    session = _make_session()
    while True:
        try:
            if session:
                from prompt_toolkit.formatted_text import HTML
                line = session.prompt(HTML(_prompt_html(state)))
            else:
                line = console.input(_prompt_plain(state))
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]bye 🔱[/dim]\n")
            if state.server_proc and state.server_proc.poll() is None:
                _stop(state, [])
            return 0

        line = line.strip()
        if not line:
            continue

        # Unknown / not-a-slash → treat as `/help` hint.
        if not line.startswith("/"):
            console.print("[dim]commands start with `/`. type [/dim][bold green]/help[/bold green][dim] for the list.[/dim]")
            continue

        try:
            tokens = shlex.split(line[1:])
        except ValueError as e:
            console.print(f"[red]parse error:[/red] {e}")
            continue
        if not tokens:
            continue
        name, *args = tokens
        match = _resolve_slash(name.lower())
        if not match:
            console.print(f"[red]unknown command:[/red] /{name}  (try [bold green]/help[/bold green])")
            continue
        canon, fn = match
        try:
            fn(state, args)
        except EOFError:
            if state.server_proc and state.server_proc.poll() is None:
                _stop(state, [])
            console.print("[dim]bye 🔱[/dim]\n")
            return 0
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]/{canon} failed:[/red] {e.__class__.__name__}: {e}")


def _doctor_brief(state: ReplState) -> None:
    """One-liner doctor at startup. Saves screen real estate."""
    spinner = Spinner("dots", text=Text("checking engines…", style="dim cyan"))
    with Live(spinner, console=console, transient=True):
        try:
            results = asyncio.run(state.nexus.doctor())
        except Exception:
            results = []
    if not results:
        return
    ok = sum(1 for r in results if r["installed"])
    total = len(results)
    miss = [r["name"] for r in results if not r["installed"]]
    color = "green" if ok == total else "yellow"
    msg = f"  [bold {color}]engines: {ok}/{total} healthy[/bold {color}]"
    if miss:
        msg += f"  ·  [dim]missing:[/dim] [red]{', '.join(miss)}[/red]"
    msg += f"  ·  [dim]workspace:[/dim] [cyan]{state.config.workspace}[/cyan]"
    console.print(msg)
    console.print()


def _prompt_html(state: ReplState) -> str:
    """prompt_toolkit-flavored prompt with project context."""
    proj = f"<ansimagenta>{state.active_project_id}</ansimagenta> " if state.active_project_id else ""
    return f"<ansicyan>🔱 nexus</ansicyan> {proj}<ansigreen>❯</ansigreen> "


def _prompt_plain(state: ReplState) -> str:
    proj = f"[magenta]{state.active_project_id}[/magenta] " if state.active_project_id else ""
    return f"[bold cyan]🔱 nexus[/bold cyan] {proj}[bold green]❯[/bold green] "


# ─── Click subcommands (one-shot mode) ───────────────────────────────────

@click.group(
    invoke_without_command=True,
    help="🔱 MEDUSA NEXUS — unified mobile threat analysis. Run with no args for the interactive REPL.",
)
@click.version_option(__version__, prog_name="mnexus")
@click.pass_context
def cli(ctx: click.Context) -> None:
    ctx.ensure_object(dict)
    ctx.obj["config"] = NexusConfig.from_env()
    ctx.obj["config"].ensure_workspace()
    if ctx.invoked_subcommand is None:
        sys.exit(_repl(ctx.obj["config"]))


@cli.command(name="repl", help="Open the interactive REPL (default when run with no args).")
@click.pass_context
def repl_cmd(ctx: click.Context) -> None:
    sys.exit(_repl(ctx.obj["config"]))


@cli.command(help="Verify every engine is installed, reachable, and not lying about its version.")
@click.pass_context
def doctor(ctx: click.Context) -> None:
    state = ReplState(ctx.obj["config"])
    _doctor(state, [])
    # Exit non-zero if anything is missing — useful in CI.
    results = asyncio.run(state.nexus.doctor())
    sys.exit(0 if all(r["installed"] for r in results) else 1)


@cli.command(help="Static scan: ingest an APK, run every static engine, build the attack surface.")
@click.argument("apk_path", type=click.Path(exists=True, path_type=Path))
@click.option("--package", "package_name", default="", help="Target package name (auto-detected if omitted).")
@click.option("--version", "version_name", default="", help="Version name (auto-detected if omitted).")
@click.pass_context
def scan(ctx: click.Context, apk_path: Path, package_name: str, version_name: str) -> None:
    state = ReplState(ctx.obj["config"])
    args = [str(apk_path)]
    if package_name:
        args += ["--package", package_name]
    if version_name:
        args += ["--version", version_name]
    _scan(state, args)


@cli.group(name="play-account", help="Manage stored Play identities (the account manager that backs `play-scan`).")
def play_account_group() -> None:
    """Subcommand group: add / list / use / delete / show."""


@play_account_group.command("add", help="Register a Play identity. Pass --password to mint the AAS token from email+password.")
@click.option("--name", "-n", required=True, help="Short handle for this identity (alphanumeric / - / _ only).")
@click.option("--email", "-e", required=True, help="Gmail address tied to the account.")
@click.option("--aas", "-a", "aas_token", default="", help="AAS master token. Omit to use --password mode.")
@click.option("--password", "-p", default="", help="Password / app password; minted to AAS via /auth and not stored.")
@click.option("--notes", default="", help="Free-form note (e.g. 'qa rig', 'research-2026-q2').")
@click.option("--default/--no-default", default=False, help="Mark this account as the default for /play-scan.")
@click.pass_context
def play_account_add(
    ctx: click.Context,
    name: str,
    email: str,
    aas_token: str,
    password: str,
    notes: str,
    default: bool,
) -> None:
    if not aas_token and not password:
        click.echo("error: pass either --aas <token> or --password <pwd>", err=True)
        ctx.exit(2)
    state = ReplState(ctx.obj["config"])
    args = ["--name", name, "--email", email]
    if aas_token:
        args += ["--aas", aas_token]
    if password:
        args += ["--password", password]
    if notes:
        args += ["--notes", notes]
    if default:
        args.append("--default")
    _play_account_add(state, args)


@play_account_group.command("list", help="Show stored Play identities (no token values are echoed).")
@click.pass_context
def play_account_list(ctx: click.Context) -> None:
    state = ReplState(ctx.obj["config"])
    _play_account_list(state)


@play_account_group.command("use", help="Mark <name> as the default account for /play-scan.")
@click.argument("name")
@click.pass_context
def play_account_use(ctx: click.Context, name: str) -> None:
    state = ReplState(ctx.obj["config"])
    _play_account_use(state, [name])


@play_account_group.command("delete", help="Remove a stored account by name.")
@click.argument("name")
@click.pass_context
def play_account_delete(ctx: click.Context, name: str) -> None:
    state = ReplState(ctx.obj["config"])
    _play_account_delete(state, [name])


@play_account_group.command("show", help="Show one account's metadata (token is redacted).")
@click.argument("name")
@click.pass_context
def play_account_show(ctx: click.Context, name: str) -> None:
    state = ReplState(ctx.obj["config"])
    _play_account_show(state, [name])


@cli.command(name="play-scan", help="Stream an APK from Google Play and scan for Firebase / credential leaks.")
@click.argument("package", type=str)
@click.option("--apk", "apk_path", type=click.Path(path_type=Path), default=None,
              help="Local APK file to scan instead of fetching from Play.")
@click.option("--account", "-A", "account_name", default="",
              help="Stored Play identity to scan as (default: the one flagged default).")
@click.option("--no-probes", is_flag=True, default=False,
              help="Skip the active Firebase / Firestore / Storage probes (offline mode).")
@click.pass_context
def play_scan(
    ctx: click.Context,
    package: str,
    apk_path: Path | None,
    account_name: str,
    no_probes: bool,
) -> None:
    state = ReplState(ctx.obj["config"])
    args = [package]
    if apk_path:
        args += ["--apk", str(apk_path)]
    if account_name:
        args += ["--account", account_name]
    if no_probes:
        args.append("--no-probes")
    _play_scan(state, args)


@cli.command(help="Generate a report — every template ships a Mitigation Playbook.")
@click.option("--project", "project_id", required=True)
@click.option("--template", type=click.Choice(["executive", "technical", "owasp-matrix", "diff"]), default="technical")
@click.option("--format", "fmt", type=click.Choice(["pdf", "html", "markdown", "json"]), default="markdown")
@click.option("--output", "output_path", required=True, type=click.Path(path_type=Path))
@click.pass_context
def report(ctx: click.Context, project_id: str, template: str, fmt: str, output_path: Path) -> None:
    from mnexus.core.artifact_store import ArtifactStore
    from mnexus.reporting.generator import ReportFormat, ReportGenerator, ReportTemplate
    config: NexusConfig = ctx.obj["config"]
    store = ArtifactStore(config.db_path)
    project = store.load_project(project_id)
    if not project:
        console.print(f"[red]no project with id {project_id}[/red]")
        sys.exit(2)
    gen = ReportGenerator(project)
    path = gen.generate(ReportTemplate(template), ReportFormat(fmt), str(output_path))
    console.print(f"[green]report[/green] written to {path}")


@cli.command(help="Start the FastAPI backend + serve the web UI. Local-first by default.")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8765, type=int)
@click.option("--reload/--no-reload", default=False, help="Auto-reload on file changes (dev only).")
def serve(host: str, port: int, reload: bool) -> None:
    import uvicorn
    console.print(f"[bold green]🔱 mnexus[/bold green] → http://{host}:{port}/    (Ctrl-C to stop)")
    uvicorn.run("mnexus.api.main:app", host=host, port=port, reload=reload)


@cli.command(name="dev", help="Dev mode: install deps if needed, start server with reload, stream status.")
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8765, type=int)
@click.pass_context
def dev_cmd(ctx: click.Context, host: str, port: int) -> None:
    """Best-effort one-command dev loop: bootstrap → reload-server → live health check."""
    state = ReplState(ctx.obj["config"])
    show_banner()
    console.print("[bold cyan]→ dev mode[/bold cyan] · auto-reload + live health check\n")
    _doctor_brief(state)

    import uvicorn
    console.print(f"[bold green]✓[/bold green] http://{host}:{port}/      [dim](Ctrl-C to stop)[/dim]")
    console.print(f"[bold green]✓[/bold green] http://{host}:{port}/docs  [dim]swagger[/dim]\n")
    try:
        uvicorn.run("mnexus.api.main:app", host=host, port=port, reload=True, log_level="info")
    except KeyboardInterrupt:
        console.print("\n[dim]bye 🔱[/dim]")


@cli.command(name="vphone", help="super-tart-vphone control (research-only).",
             context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
@click.argument("verb", required=False, default="list",
                type=click.Choice(["list", "ls", "info", "start", "stop", "ssh", "install", "status"]))
@click.argument("rest", nargs=-1)
@click.pass_context
def vphone_cmd(ctx: click.Context, verb: str, rest: tuple[str, ...]) -> None:
    """Flat CLI for vphones — same verbs as the REPL's `/vphone`.

    Examples:
        mnexus vphone list
        mnexus vphone status
        mnexus vphone start ios-test
        mnexus vphone ssh ios-test -- uname -a
        mnexus vphone install ios-test ~/Downloads/target.ipa
    """
    state = ReplState(ctx.obj["config"])
    _vphone(state, [verb, *rest])


def main() -> None:
    """Entry point installed as the `mnexus` console script."""
    cli(obj={})


if __name__ == "__main__":
    main()
