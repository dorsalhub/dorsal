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
from rich.text import Text
from typing import Annotated, Optional

from dorsal.cli.themes import UIContext

app = typer.Typer(
    name="config",
    help="[bold]show[/bold] and manage Dorsal settings.",
    no_args_is_help=True,
)

theme_app = typer.Typer(
    name="theme", help="[bold]list[/bold] and [bold]set[/bold] UI themes, icons, and borders.", no_args_is_help=True
)
app.add_typer(theme_app)

pipeline_app = typer.Typer(
    name="pipeline",
    help="[bold]show[/bold] and [bold]manage[/bold] the annotation model pipeline.",
    no_args_is_help=True,
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
    from dorsal.common.cli import get_rich_console, print_json_output
    from dorsal.common.config import load_config
    from dorsal.api.config import get_config_summary
    from dorsal.cli.views.layout import key_values, section

    console = get_rich_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]

    config_data = get_config_summary()

    if json_output:
        print_json_output(config_data, console)
        raise typer.Exit()

    raw_config, _ = load_config()
    ui_cfg = raw_config.get("ui", {})
    configured = (ui_cfg.get("theme", "default"), ui_cfg.get("icons", "none"), ui_cfg.get("borders", "none"))
    effective = (
        ui_context.get("theme_name", configured[0]),
        ui_context.get("icons_name", configured[1]),
        ui_context.get("borders_name", configured[2]),
    )

    if config_data["api_key_set"]:
        status_text = Text(f"Set (from {config_data['api_key_source']})", style=palette.get("success", "green"))
    else:
        status_text = Text("Not set", style=palette.get("warning", "yellow"))

    user_text = (
        Text(config_data["logged_in_user"], style=palette.get("primary_value", "default"))
        if config_data["logged_in_user"]
        else Text("N/A (run 'dorsal auth login')", style=palette.get("info", "dim"))
    )

    config_table = key_values(ui_context)
    for label, active, in_file in zip(
        ("Current theme", "Current icons", "Current borders"), effective, configured, strict=True
    ):
        value = Text(active, style=palette.get("primary_value", "default"))
        if active != in_file:
            value.append(f"  (config file: {in_file})", style=palette.get("info", "dim"))
        config_table.add(label, value)
    config_table.add("Logged-in user", user_text)
    config_table.add("API key status", status_text)
    config_table.add("API URL", config_data["api_url"])
    config_table.add("Reports path", config_data["reports_path"])
    config_table.add("Active config file", config_data["active_config_path"])
    config_table.add("Global config file", config_data["global_config_path"])
    if config_data["index_compression_enabled"]:
        config_table.add(
            "Index compression",
            f"{config_data['index_compression_mode']} (Level {config_data['index_compression_level']})",
        )
    else:
        config_table.add("Index compression", "Not enabled")

    console.print(section("Dorsal configuration", config_table, ui_context))
    console.print()
    console.print("[dim]For more detail on the pipeline config, run:[/]")
    console.print("[dim]  dorsal config pipeline show[/]")


def _create_theme_preview_panel(
    theme_name: str, theme_palette: dict[str, str], ui_context: UIContext
) -> RenderableType:
    from dorsal.cli.views.layout import KeyValues, section

    preview = KeyValues(
        key_style=theme_palette.get("key", "dim"), value_style=theme_palette.get("primary_value", "default")
    )
    preview.add("Key", "Primary value")
    preview.add("Hash", "a1b2c3d4e5f62a3b4c...", style=theme_palette.get("hash_value", "default"))
    preview.add(
        "Tags",
        Text.assemble(
            ("public_tag", theme_palette.get("tag_public", "default")),
            (" (public)", theme_palette.get("tag_subtext", "default")),
            "\n",
            ("private_tag", theme_palette.get("tag_private", "default")),
            (" (private)", theme_palette.get("tag_subtext", "default")),
        ),
    )

    return section(
        theme_name,
        preview,
        ui_context,
        title_style=theme_palette.get("panel_title_alt", theme_palette.get("panel_title", "default")),
        border_style=theme_palette.get("panel_border_alt", theme_palette.get("panel_border", "default")),
        padding=(0, 1),
    )


@theme_app.command(name="list")
def list_themes(ctx: typer.Context):
    """Lists all available built-in and custom color themes."""
    from dorsal.common.cli import get_rich_console
    from dorsal.cli.themes.palettes import BUILT_IN_PALETTES, DEFAULT_PALETTE, _load_custom_palettes
    from dorsal.cli.views.layout import heading, is_borderless, section

    console = get_rich_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]
    section_style = palette.get("section_title", "bold")
    borderless = is_borderless(ui_context)

    def theme_group(title: str, palettes: dict[str, dict[str, str]]) -> list[RenderableType]:
        previews: list[RenderableType] = []
        for name, theme_palette in palettes.items():
            if previews:
                previews.append(Text(""))
            previews.append(_create_theme_preview_panel(name, {**DEFAULT_PALETTE, **theme_palette}, ui_context))
        if borderless:
            return [section(title, Group(Text(""), *previews), ui_context, title_style=section_style)]
        return [heading(title, section_style), *previews]

    renderables = theme_group("Built-in themes", BUILT_IN_PALETTES)

    custom = _load_custom_palettes()
    if custom:
        renderables.append(Text(""))
        renderables.extend(theme_group("Custom themes [dim](from ~/.dorsal/palettes.json)[/]", custom))

    command_color = palette.get("primary_value", "default")
    renderables.append(
        Text.from_markup(
            f"\n[bold {command_color}]dorsal config theme set <name>[/] to set a theme.\n\n"
            f"Or use the --theme flag before another command\ne.g. [bold {command_color}]dorsal --theme mono file push ...[/]"
        )
    )

    if borderless:
        console.print(Group(*renderables))
    else:
        console.print(section("Available themes", Group(*renderables), ui_context))


@theme_app.command(name="set")
def set_ui_preferences(
    ctx: typer.Context,
    theme_name: Annotated[Optional[str], typer.Argument(help="The name of the color theme to set.")] = None,
    icons: Annotated[
        Optional[str], typer.Option("--icons", help="The icon style to set (e.g., none, emoji, ascii).")
    ] = None,
    borders: Annotated[
        Optional[str], typer.Option("--borders", help="The border style to set (e.g., none, rounded, heavy, ascii).")
    ] = None,
    global_scope: Annotated[
        bool,
        typer.Option(
            "--global", "-g", help="Save to the global user config (~/.dorsal) instead of the project config."
        ),
    ] = False,
):
    """Sets UI preferences (theme, icons, borders) and saves them to the config file."""
    from dorsal.common.cli import (
        get_rich_console,
        exit_cli,
        EXIT_CODE_ERROR,
        get_error_console,
    )
    from dorsal.common.auth import write_ui_config
    from dorsal.cli.themes.palettes import BUILT_IN_PALETTES, _load_custom_palettes
    from dorsal.cli.themes.icons import ICON_SETS
    from dorsal.cli.themes.borders import BORDER_SETS
    from dorsal.cli.views.layout import key_values, section

    console = get_rich_console()
    error_console = get_error_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]

    if not theme_name and not icons and not borders:
        error_console.print(
            f"[{palette.get('warning', 'yellow')}]No UI preferences provided to set. Provide a theme name or use --icons / --borders.[/]"
        )
        exit_cli(code=EXIT_CODE_ERROR)

    if theme_name:
        all_palettes = {**BUILT_IN_PALETTES, **_load_custom_palettes()}
        if theme_name not in all_palettes:
            error_console.print(
                f"[{palette.get('error', 'red')}]Error:[/] Theme '{theme_name}' not found. Use `dorsal config theme list` to see available themes."
            )
            exit_cli(code=EXIT_CODE_ERROR)

    if icons and icons not in ICON_SETS:
        error_console.print(
            f"[{palette.get('error', 'red')}]Error:[/] Icon set '{icons}' not found. Valid options: {', '.join(ICON_SETS.keys())}"
        )
        exit_cli(code=EXIT_CODE_ERROR)

    if borders and borders not in BORDER_SETS:
        error_console.print(
            f"[{palette.get('error', 'red')}]Error:[/] Border style '{borders}' not found. Valid options: {', '.join(BORDER_SETS.keys())}"
        )
        exit_cli(code=EXIT_CODE_ERROR)

    scope = "global" if global_scope else "project"

    try:
        write_ui_config(theme=theme_name, icons=icons, borders=borders, scope=scope)

        updates = key_values(ui_context, [("Theme", theme_name), ("Icons", icons), ("Borders", borders)])
        console.print(
            section(
                f"{ui_context['icons'].get('success', '')}UI preferences updated in {scope} config",
                updates,
                ui_context,
                title_style=palette.get("success", "green"),
                border_style=palette.get("panel_border_success", "green"),
            )
        )
    except OSError as e:
        exit_cli(code=EXIT_CODE_ERROR, message=f"Error saving configuration: {e}")


def _handle_pipeline_action(target: str, func_index, func_name, action_desc: str):
    """
    Helper to dispatch commands to either index-based or name-based API functions.
    """
    from dorsal.common.cli import (
        get_rich_console,
        exit_cli,
        EXIT_CODE_ERROR,
        get_error_console,
    )

    console = get_rich_console()
    error_console = get_error_console()

    try:
        idx = int(target)
        func_index(index=idx)
        console.print(f"[green]Successfully {action_desc} model at index {idx}.[/]")
    except ValueError:
        try:
            func_name(name=target)
            console.print(f"[green]Successfully {action_desc} model '{target}'.[/]")
        except Exception as e:
            error_console.print(f"[red]Error:[/] {e}")
            exit_cli(EXIT_CODE_ERROR)
    except Exception as e:
        error_console.print(f"[red]Error:[/] {e}")
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
    from dorsal.common.cli import get_rich_console, print_json_output
    from dorsal.api.config import show_model_pipeline

    from dorsal.cli.views.layout import message, table

    console = get_rich_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]
    icons = ui_context["icons"]

    summary = show_model_pipeline()

    if json_output:
        print_json_output(summary, console)
        raise typer.Exit()

    if not summary:
        console.print(message("Pipeline", "The pipeline is currently empty.", ui_context, level="warning"))
        return

    pipeline_table = table(
        ui_context,
        title="Annotation model pipeline",
        caption=f"Total models: {len(summary)}",
        caption_justify="left",
        caption_style=palette.get("info", "dim"),
    )
    pipeline_table.add_column("Idx", justify="right", style="dim")
    pipeline_table.add_column("Status", justify="left")
    pipeline_table.add_column("Model name", style="bold")
    pipeline_table.add_column("Module", style="dim")
    pipeline_table.add_column("Schema ID", style="cyan")
    pipeline_table.add_column("Dependencies", style="dim")

    for step in summary:
        status = f"[{palette.get('success', 'green')}]{icons.get('success', '')}Active[/]"
        name = Text(step["name"])

        if step["status"] == "Deactivated":
            status = f"[{palette.get('error', 'red')}]{icons.get('error', '')}Off[/]"
        elif step["status"] == "Base (Locked)":
            status = "[dim]Default[/]"
            name.stylize("dim")

        pipeline_table.add_row(
            str(step["index"]),
            status,
            name,
            Text(step["module"]),
            Text(step["schema_id"]),
            Text(str(step["dependencies"])),
        )

    console.print(pipeline_table)


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
    from dorsal.common.cli import (
        get_rich_console,
        exit_cli,
        EXIT_CODE_ERROR,
        get_error_console,
    )
    from dorsal.common.validators import import_callable, CallableImportPath
    from dorsal.api.config import get_model_pipeline, remove_model_by_index

    console = get_rich_console()
    error_console = get_error_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]

    steps = get_model_pipeline(scope="effective")
    broken_indices = []

    with error_console.status("Checking pipeline integrity..."):
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
        console.print(
            f"[{palette.get('success', 'green')}]{ui_context['icons'].get('success', '')}All pipeline models are importable.[/]"
        )
        raise typer.Exit()

    console.print(f"[{palette.get('error', 'red')}]Found {len(broken_indices)} broken models:[/]")
    for idx, name, err in broken_indices:
        console.print(f"  - Index {idx}: [bold]{name}[/] - {err}")

    if fix:
        for idx, name, _ in reversed(broken_indices):
            try:
                remove_model_by_index(index=idx)
                console.print(f"  [yellow]Removed broken model '{name}' (Index {idx})[/]")
            except Exception as e:
                error_console.print(f"  [red]Failed to remove index {idx}: {e}[/]")

        console.print(f"\n[{palette.get('success', 'green')}]Cleanup complete.[/]")
    else:
        console.print("\n[dim]Run with [white]--fix[/] to automatically remove these models.[/]")
        exit_cli(EXIT_CODE_ERROR)
