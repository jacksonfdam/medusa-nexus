"""CLI — `mnexus` binary. Click-based, terse, acid-tongued where appropriate."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from mnexus import __version__
from mnexus.config import NexusConfig
from mnexus.core.orchestrator import MedusaNexus

console = Console()


@click.group(help="🔱 MEDUSA NEXUS — unified mobile threat analysis. Every head sees a different angle.")
@click.version_option(__version__, prog_name="mnexus")
@click.pass_context
def cli(ctx: click.Context) -> None:
    ctx.ensure_object(dict)
    ctx.obj["config"] = NexusConfig.from_env()


@cli.command()
@click.pass_context
def doctor(ctx: click.Context) -> None:
    """Verify every engine is installed, reachable, and not lying about its version."""
    nexus = MedusaNexus(ctx.obj["config"])
    results = asyncio.run(nexus.doctor())

    table = Table(title="mnexus doctor", show_lines=False)
    table.add_column("engine", style="cyan", no_wrap=True)
    table.add_column("status", no_wrap=True)
    table.add_column("version")
    table.add_column("path")
    table.add_column("note", style="magenta")

    exit_code = 0
    for r in results:
        ok = r["installed"]
        status = "[green]OK[/green]" if ok else "[red]MISSING[/red]"
        if not ok:
            exit_code = 1
        table.add_row(str(r["name"]), status, str(r["version"] or "—"), str(r["path"] or "—"), str(r["message"]))

    console.print(table)
    sys.exit(exit_code)


@cli.command()
@click.argument("apk_path", type=click.Path(exists=True, path_type=Path))
@click.option("--package", "package_name", required=True, help="Target package name (e.g. com.target.app).")
@click.option("--version", "version_name", default="unknown", help="Version name — for project labeling.")
@click.pass_context
def scan(ctx: click.Context, apk_path: Path, package_name: str, version_name: str) -> None:
    """Static scan: ingest an APK, run every static engine, build the attack surface."""
    nexus = MedusaNexus(ctx.obj["config"])
    project = asyncio.run(nexus.ingest_apk(apk_path, package_name=package_name, version=version_name))

    surface = project.attack_surface
    total = len(surface.findings) if surface else 0
    score = surface.risk_score() if surface else 0.0

    console.print(f"[cyan]project[/cyan] {project.id} · {project.name}")
    console.print(f"[cyan]risk[/cyan] {score}/100 · [cyan]findings[/cyan] {total}")


@cli.command()
@click.option("--package", "package_name", required=True)
@click.option("--modules", default="ssl_bypass,root_bypass,crypto_log",
              help="Comma-separated Medusa/auto module names.")
@click.option("--duration", default=300, type=int, help="Session length in seconds.")
def dynamic(package_name: str, modules: str, duration: int) -> None:
    """Dynamic session: spawn, load hooks, watch. Stubbed — wires up in iteration 2."""
    console.print(f"[yellow]pending[/yellow] dynamic runner: {package_name} / {modules} / {duration}s")


@cli.command()
@click.option("--project", "project_id", required=True)
@click.option("--template", type=click.Choice(["executive", "technical", "owasp-matrix", "diff"]), default="technical")
@click.option("--format", "fmt", type=click.Choice(["pdf", "html", "markdown", "json"]), default="markdown")
@click.option("--output", "output_path", required=True, type=click.Path(path_type=Path))
@click.pass_context
def report(ctx: click.Context, project_id: str, template: str, fmt: str, output_path: Path) -> None:
    """Emit a report. Every template ships a Mitigation Playbook. Not optional."""
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


@cli.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=8765, type=int)
def serve(host: str, port: int) -> None:
    """Start the web UI + REST API. Local-first; bind to 127.0.0.1 by default."""
    import uvicorn

    uvicorn.run("mnexus.api.main:app", host=host, port=port, reload=False)


def main() -> None:
    """Entry point installed as the `mnexus` console script."""
    cli(obj={})


if __name__ == "__main__":
    main()
