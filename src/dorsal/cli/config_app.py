# Copyright 2025-2026 Dorsal Hub LTD
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import typer
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.box import Box
from typing import Dict, Annotated, Optional
import json

from dorsal.cli.themes import UIContext

app = typer.Typer(
    name="config",
    help="View or manage Dorsal settings.",
    no_args_is_help=True,
)

theme_app = typer.Typer(name="theme", help="List and set UI themes, icons, and borders.", no_args_is_help=True)
app.add_typer(theme_app)

pipeline_app = typer.Typer(
    name="pipeline", help="Inspect and manage the annotation model pipeline.", no_args_is_help=True
)
app.add_typer(pipeline_app)

@app.command(name="show")
def show_config(
    ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the configuration as a raw JSON object."),
    ] = False,
):
    """
    Displays the current configuration status and paths.
    """
    from dorsal.common.cli import get_rich_console
    from dorsal.common.config import load_config
    from dorsal.api.config import get_config_summary
    from dorsal.cli.themes.borders import get_borders

    console = get_rich_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]
    borders = ui_context["borders"]

    config_data = get_config_summary()

    if json_output:
        console.print(json.dumps(config_data, indent=2, default=str))
        raise typer.Exit()

    raw_config, _ = load_config()
    ui_cfg = raw_config.get("ui", {})
    active_theme = ui_cfg.get("theme", "default")
    active_icons = ui_cfg.get("icons", "emoji")
    active_borders = ui_cfg.get("borders", "rounded")

    if config_data["api_key_set"]:
        status_text = Text(f"Set (from {config_data['api_key_source']})", style=palette.get("success", "green"))
    else:
        status_text = Text("Not Set", style=palette.get("warning", "yellow"))

    user_text = (
        Text(config_data["logged_in_user"], style=palette.get("primary_value", "default"))
        if config_data["logged_in_user"]
        else Text("N/A (run 'dorsal auth login')", style=palette.get("info", "dim"))
    )

    config_table = Table.grid(expand=True, padding=(0, 2))
    config_table.add_column(justify="right", style=palette.get("key", "dim"), width=22)
    config_table.add_column()

    config_table.add_row("Current Theme:", Text(active_theme, style=palette.get("primary_value", "default")))
    config_table.add_row("Current Icons:", Text(active_icons, style=palette.get("primary_value", "default")))
    config_table.add_row("Current Borders:", Text(active_borders, style=palette.get("primary_value", "default")))
    config_table.add_row("Logged-In User:", user_text)
    config_table.add_row("API Key Status:", status_text)
    config_table.add_row("API URL:", Text(config_data["api_url"], style=palette.get("primary_value", "default")))
    config_table.add_row(
        "Reports Path:", Text(config_data["reports_path"], style=palette.get("primary_value", "default"))
    )
    config_table.add_row(
        "Active Config File:", Text(config_data["active_config_path"], style=palette.get("primary_value", "default"))
    )
    config_table.add_row(
        "Global Config File:", Text(config_data["global_config_path"], style=palette.get("primary_value", "default"))
    )
    if config_data['index_compression_enabled']:
        config_table.add_row(
            "Index Compression:", 
            Text(f"{config_data['index_compression_mode']} (Level {config_data['index_compression_level']})", style=palette.get("primary_value", "cyan"))
        )
    else:
        config_table.add_row(
            "Index Compression: Not Enabled"
        )

    is_none_style = borders == get_borders("none")
    title_text = f"[{palette.get('panel_title', 'bold')}]Dorsal Configuration[/]"

    if is_none_style:
        console.print(Group(Text.from_markup(f"{title_text}\n"), config_table))
    else:
        console.print(
            Panel(
                config_table,
                title=title_text,
                border_style=palette.get("panel_border", "default"),
                box=borders,
                expand=False,
            )
        )

    console.print("\n[dim]For more detail on the pipeline config, run:[/]")
    console.print("[dim]  dorsal config pipeline show[/]")


def _create_theme_preview_panel(theme_name: str, palette: dict[str, str], borders: Box) -> RenderableType:
    from dorsal.cli.themes.borders import get_borders

    border_style = palette.get("panel_border_alt", palette.get("panel_border", "default"))
    title_style = palette.get("panel_title_alt", palette.get("panel_title", "default"))

    preview_grid = Table.grid(padding=(0, 2))
    preview_grid.add_column(style=palette.get("key", "dim"), width=12)
    preview_grid.add_column()
    preview_grid.add_row("Key:", Text("Primary Value", style=palette.get("primary_value", "default")))
    preview_grid.add_row("Hash:", Text("a1b2c3d4e5f62a3b4c...", style=palette.get("hash_value", "default")))

    public_tag_text = Text.assemble(
        ("public_tag", palette.get("tag_public", "default")),
        (" (public)", palette.get("tag_subtext", "default")),
    )
    private_tag_text = Text.assemble(
        ("private_tag", palette.get("tag_private", "default")),
        (" (private)", palette.get("tag_subtext", "default")),
    )
    preview_grid.add_row("Tags:", public_tag_text)
    preview_grid.add_row("", private_tag_text)

    is_none_style = borders == get_borders("none")
    title_text = f"[{title_style}]{theme_name}[/]"

    if is_none_style:
        return Group(Text.from_markup(f"{title_text}\n"), preview_grid)

    return Panel(
        preview_grid,
        title=title_text,
        border_style=border_style,
        box=borders,
        expand=False,
    )


@theme_app.command(name="list")
def list_themes(ctx: typer.Context):
    """Lists all available built-in and custom color themes."""
    from dorsal.common.cli import get_rich_console
    from dorsal.cli.themes.palettes import BUILT_IN_PALETTES, _load_custom_palettes
    from dorsal.cli.themes.borders import get_borders

    console = get_rich_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]
    borders = ui_context["borders"]

    renderables: list[RenderableType] = [Text.from_markup(f"[{palette.get('panel_title')}]🎨 Available Themes[/]")]
    renderables.append(Text.from_markup(f"\n[{palette.get('section_title')}]Built-in Themes[/]"))

    for name, theme_palette in BUILT_IN_PALETTES.items():
        renderables.append(_create_theme_preview_panel(name, theme_palette, borders))

    custom = _load_custom_palettes()
    if custom:
        renderables.append(Text(""))
        renderables.append(
            Text.from_markup(f"[{palette.get('section_title')}]Custom Themes[/] (from ~/.dorsal/palettes.json)")
        )
        for name, theme_palette in custom.items():
            renderables.append(_create_theme_preview_panel(name, theme_palette, borders))

    command_color = palette.get("primary_value", "default")
    renderables.append(
        Text.from_markup(
            f"\n[bold {command_color}]dorsal config theme set <name>[/] to set a theme.\n\n"
            f"Or use the --theme flag before another command\ne.g. [bold {command_color}]dorsal --theme mono file push ...[/]"
        )
    )

    is_none_style = borders == get_borders("none")
    title_text = f"[{palette.get('panel_title')}]Theme Configuration[/]"

    if is_none_style:
        console.print(Group(Text.from_markup(f"{title_text}\n"), *renderables))
    else:
        console.print(
            Panel(
                Group(*renderables),
                expand=False,
                title=title_text,
                border_style=palette.get("panel_border", "blue"),
                box=borders,
                padding=(1, 2),
            )
        )


@theme_app.command(name="set")
def set_ui_preferences(
    ctx: typer.Context,
    theme_name: Annotated[Optional[str], typer.Argument(help="The name of the color theme to set.")] = None,
    icons: Annotated[
        Optional[str], typer.Option("--icons", help="The icon style to set (e.g., emoji, ascii, none).")
    ] = None,
    borders: Annotated[
        Optional[str], typer.Option("--borders", help="The border style to set (e.g., rounded, heavy, ascii, none).")
    ] = None,
    global_scope: Annotated[
        bool,
        typer.Option(
            "--global", "-g", help="Save to the global user config (~/.dorsal) instead of the project config."
        ),
    ] = False,
):
    """Sets UI preferences (theme, icons, borders) and saves them to the config file."""
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.common.auth import write_ui_config
    from dorsal.cli.themes.palettes import BUILT_IN_PALETTES, _load_custom_palettes
    from dorsal.cli.themes.icons import ICON_SETS
    from dorsal.cli.themes.borders import BORDER_SETS

    console = get_rich_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]

    if not theme_name and not icons and not borders:
        console.print(
            f"[{palette.get('warning', 'yellow')}]No UI preferences provided to set. Provide a theme name or use --icons / --borders.[/]"
        )
        exit_cli(code=EXIT_CODE_ERROR)

    if theme_name:
        all_palettes = {**BUILT_IN_PALETTES, **_load_custom_palettes()}
        if theme_name not in all_palettes:
            console.print(
                f"[{palette.get('error', 'red')}]Error:[/] Theme '{theme_name}' not found. Use `dorsal config theme list` to see available themes."
            )
            exit_cli(code=EXIT_CODE_ERROR)

    if icons and icons not in ICON_SETS:
        console.print(
            f"[{palette.get('error', 'red')}]Error:[/] Icon set '{icons}' not found. Valid options: {', '.join(ICON_SETS.keys())}"
        )
        exit_cli(code=EXIT_CODE_ERROR)

    if borders and borders not in BORDER_SETS:
        console.print(
            f"[{palette.get('error', 'red')}]Error:[/] Border style '{borders}' not found. Valid options: {', '.join(BORDER_SETS.keys())}"
        )
        exit_cli(code=EXIT_CODE_ERROR)

    scope = "global" if global_scope else "project"

    try:
        write_ui_config(theme=theme_name, icons=icons, borders=borders, scope=scope)

        updates = []
        if theme_name:
            updates.append(f"Theme: [bold {palette.get('primary_value', 'cyan')}]{theme_name}[/]")
        if icons:
            updates.append(f"Icons: [bold {palette.get('primary_value', 'cyan')}]{icons}[/]")
        if borders:
            updates.append(f"Borders: [bold {palette.get('primary_value', 'cyan')}]{borders}[/]")

        success_message = Text.from_markup(
            f"[{palette.get('success', 'green')}]✅ UI preferences updated in {scope} config:[/]\n  "
            + "\n  ".join(updates)
        )
        console.print(success_message)
    except OSError as e:
        exit_cli(code=EXIT_CODE_ERROR, message=f"Error saving configuration: {e}")


def _handle_pipeline_action(target: str, func_index, func_name, action_desc: str):
    """
    Helper to dispatch commands to either index-based or name-based API functions.
    """
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR

    console = get_rich_console()

    try:
        idx = int(target)
        func_index(index=idx)
        console.print(f"[green]Successfully {action_desc} model at index {idx}.[/]")
    except ValueError:
        try:
            func_name(name=target)
            console.print(f"[green]Successfully {action_desc} model '{target}'.[/]")
        except Exception as e:
            console.print(f"[red]Error: {e} [/]")
            exit_cli(EXIT_CODE_ERROR)
    except Exception as e:
        console.print(f"[red]Error: {e} [/]")
        exit_cli(EXIT_CODE_ERROR)


@pipeline_app.command(name="show")
def show_pipeline(
    ctx: typer.Context,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the pipeline configuration as a raw JSON array."),
    ] = False,
):
    """
    Show the current effective pipeline configuration.
    """
    from dorsal.common.cli import get_rich_console
    from dorsal.api.config import show_model_pipeline
    import json

    console = get_rich_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]
    borders = ui_context["borders"]

    summary = show_model_pipeline()

    if json_output:
        console.print(json.dumps(summary, indent=2, default=str))
        raise typer.Exit()

    if not summary:
        console.print(
            Panel("The pipeline is currently empty.", title="Pipeline", border_style=palette["warning"], box=borders)
        )
        return

    table = Table(expand=True, box=borders, padding=(0, 2))
    table.add_column("Idx", justify="right", style="dim")
    table.add_column("Status", justify="left", width=10)
    table.add_column("Model Name", style="bold")
    table.add_column("Module", style="dim")
    table.add_column("Schema ID", style="cyan")
    table.add_column("Dependencies", style="dim")

    for step in summary:
        status = "✅ Active"
        name = step["name"]

        if step["status"] == "Deactivated":
            status = "❌ Off"
        elif step["status"] == "Base (Locked)":
            status = "[dim]🔒 Default[/]"
            name = f"[dim]{step['name']}[/]"

        table.add_row(str(step["index"]), status, name, step["module"], step["schema_id"], str(step["dependencies"]))

    from dorsal.cli.themes.borders import get_borders

    is_none_style = borders == get_borders("none")
    title_text = f"[{palette.get('panel_title')}]Annotation Model Pipeline[/]"

    if is_none_style:
        console.print(Group(Text.from_markup(f"{title_text}\n[dim]Total Models: {len(summary)}[/]\n"), table))
    else:
        console.print(
            Panel(
                table,
                expand=False,
                title=title_text,
                border_style=palette.get("panel_border", "blue"),
                box=borders,
                subtitle=f"Total Models: {len(summary)}",
            )
        )


@pipeline_app.command(name="remove")
def remove_step(target: str = typer.Argument(..., help="The index or name of the model to remove.")):
    """Remove a model from the pipeline."""
    from dorsal.api.config import remove_model_by_index, remove_model_by_name

    _handle_pipeline_action(target, remove_model_by_index, remove_model_by_name, "removed")


@pipeline_app.command(name="activate")
def activate_step(target: str = typer.Argument(..., help="The index or name of the model to activate.")):
    """Enable a previously deactivated model."""
    from dorsal.api.config import activate_model_by_index, activate_model_by_name

    _handle_pipeline_action(target, activate_model_by_index, activate_model_by_name, "activated")


@pipeline_app.command(name="deactivate")
def deactivate_step(target: str = typer.Argument(..., help="The index or name of the model to deactivate.")):
    """Disable a model without removing it from the config."""
    from dorsal.api.config import deactivate_model_by_index, deactivate_model_by_name

    _handle_pipeline_action(target, deactivate_model_by_index, deactivate_model_by_name, "deactivated")


@pipeline_app.command(name="check")
def check_pipeline(
    ctx: typer.Context,
    fix: bool = typer.Option(False, "--fix", help="Automatically remove models with broken import paths."),
):
    """
    Verifies that all registered models can be imported.
    """
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.common.validators import import_callable, CallableImportPath
    from dorsal.api.config import get_model_pipeline, remove_model_by_index

    console = get_rich_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]

    steps = get_model_pipeline(scope="effective")
    broken_indices = []

    with console.status("Checking pipeline integrity..."):
        for i, step in enumerate(steps):
            if i == 0:
                continue

            model_path = step.annotation_model
            try:
                import_callable(model_path)
                if isinstance(step.validation_model, CallableImportPath):
                    import_callable(step.validation_model)
            except (ImportError, ModuleNotFoundError, AttributeError) as e:
                broken_indices.append((i, step.annotation_model.name, str(e)))

    if not broken_indices:
        console.print(f"[{palette.get('success', 'green')}]✓ All pipeline models are importable.[/]")
        raise typer.Exit()

    console.print(f"[{palette.get('error', 'red')}]Found {len(broken_indices)} broken models:[/]")
    for idx, name, err in broken_indices:
        console.print(f"  • Index {idx}: [bold]{name}[/] - {err}")

    if fix:
        for idx, name, _ in reversed(broken_indices):
            try:
                remove_model_by_index(index=idx)
                console.print(f"  [yellow]Removed broken model '{name}' (Index {idx})[/]")
            except Exception as e:
                console.print(f"  [red]Failed to remove index {idx}: {e}[/]")

        console.print(f"\n[{palette.get('success', 'green')}]Cleanup complete.[/]")
    else:
        console.print("\n[dim]Run with [white]--fix[/] to automatically remove these models.[/]")
        exit_cli(EXIT_CODE_ERROR)
