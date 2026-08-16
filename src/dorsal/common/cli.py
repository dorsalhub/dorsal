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

import json
import sys
from typing import Any, NoReturn, Sequence, TYPE_CHECKING

import typer
from typer.core import TyperCommand

from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text
from dorsal.common.exceptions import AuthError

if TYPE_CHECKING:
    import typer._click as _click
    from dorsal.cli.themes import UIContext


EXIT_CODE_SUCCESS = 0
EXIT_CODE_ERROR = 1

_console_instance: Console | None = None
_error_console_instance: Console | None = None


def get_rich_console() -> Console:
    """Returns a single, shared Console instance, creating it if necessary."""
    global _console_instance
    if _console_instance is None:
        _console_instance = Console()
    return _console_instance


def get_error_console() -> Console:
    """Returns a shared Console instance bound to stderr for diagnostic output."""
    global _error_console_instance
    if _error_console_instance is None:
        _error_console_instance = Console(stderr=True)
    return _error_console_instance


def exit_cli(code: int = EXIT_CODE_SUCCESS, message: str | None = None) -> NoReturn:
    """Comprehensible and testable wrapper for exiting a CLI command.

    Args:
        code: The exit code to use. Defaults to 0 (success).
        message: An optional message to print to stderr before exiting.
                 If the code is > 0, the message will be prefixed with "Error: ".
    """
    if message:
        if code > 0:
            typer.secho(f"Error: {message}", fg=typer.colors.RED, err=True)
        else:
            typer.secho(message, err=True)

    raise typer.Exit(code=code)


def determine_use_cache_value(use_cache: bool, skip_cache: bool) -> bool:
    from dorsal.file.index.config import get_index_enabled

    use_cache_choice = None
    if use_cache:
        use_cache_choice = True
    elif skip_cache:
        use_cache_choice = False

    use_cache_value = get_index_enabled(use_index=use_cache_choice)

    return use_cache_value


def handle_error(ui_context: "UIContext", message: str, json_output: bool):
    from dorsal.cli.themes.borders import get_borders

    console = get_rich_console()
    palette = ui_context["palette"]
    borders = ui_context["borders"]

    if json_output:
        console.print(json.dumps({"error": True, "detail": message}, indent=2, ensure_ascii=False))
    else:
        title_text = f"[{palette.get('panel_title_error', 'bold red')}]Error[/]"

        if borders == get_borders("none"):
            console.print(Group(Text.from_markup(f"\n{title_text}"), Text(message, justify="left")))
        else:
            panel = Panel(
                Text(message, justify="left"),
                title=title_text,
                border_style=palette.get("panel_border_error", "red"),
                expand=False,
                padding=(1, 2),
                box=borders,
            )
            console.print(panel)
    exit_cli(code=EXIT_CODE_ERROR)


def handle_auth_error(err: AuthError, console: Console, ui_context: "UIContext") -> None:
    """Handler for AuthError."""
    from dorsal.cli.themes.borders import get_borders

    palette = ui_context["palette"]
    borders = ui_context["borders"]
    icons = ui_context.get("icons", {})

    if "--json" in sys.argv:
        error_payload = {
            "success": False,
            "error": "Authentication Required",
            "detail": "You are not currently logged in.",
            "original_message": str(err),
            "fix": "Run 'dorsal auth login' or set the DORSAL_API_KEY environment variable.",
        }
        print(json.dumps(error_payload, indent=2))
        return

    message = Text.assemble(
        ("You are not currently logged in.\n\n", palette.get("warning", "yellow")),
        ("To authenticate, you can either:\n", "default"),
        ("  1. Run ", "default"),
        ("dorsal auth login\n", f"bold {palette.get('primary_value', 'cyan')}"),
        ("  2. Set the ", "default"),
        ("DORSAL_API_KEY", f"bold {palette.get('primary_value', 'cyan')}"),
        (" environment variable.", "default"),
    )

    title_text = (
        f"[{palette.get('panel_title_info', 'bold cyan')}]{icons.get('warning', '⚠️ ')}Authentication Required[/]"
    )

    if borders == get_borders("none"):
        console.print(Group(Text.from_markup(f"\n{title_text}"), message))
    else:
        console.print(
            Panel(
                message,
                expand=False,
                title=title_text,
                border_style=palette.get("panel_border_info", "cyan"),
                box=borders,
                padding=(1, 2),
            )
        )


def handle_offline_error(e: Exception, console: Console, ui_context: "UIContext"):
    """
    Centralized handler for DorsalOfflineError.
    """
    from dorsal.cli.themes.borders import get_borders

    palette = ui_context["palette"]
    borders = ui_context["borders"]
    icons = ui_context.get("icons", {})

    if "--json" in sys.argv:
        error_payload = {
            "success": False,
            "error": "Offline Mode Active",
            "detail": "Communication with DorsalHub is blocked because offline mode is enabled.",
            "original_message": str(e),
            "fix": "Unset the 'DORSAL_OFFLINE' environment variable.",
        }
        print(json.dumps(error_payload, indent=2))
        return

    message = Text.assemble(
        ("Offline Mode is currently active.\n\n", palette.get("warning", "yellow")),
        ("DorsalHub API Access is blocked.\n\n", "default"),
        ("To restore access, unset the", "default"),
        (" DORSAL_OFFLINE", f"bold {palette.get('primary_value', 'cyan')}"),
        (" environment variable.", "default"),
    )

    title_text = (
        f"[{palette.get('panel_title_warning', 'bold yellow')}]{icons.get('warning', '⚠️ ')}Dorsal API Access Blocked[/]"
    )

    if borders == get_borders("none"):
        console.print(Group(Text.from_markup(f"\n{title_text}"), message))
    else:
        console.print(
            Panel(
                message,
                expand=False,
                title=title_text,
                border_style=palette.get("panel_border_warning", "yellow"),
                box=borders,
                padding=(1, 2),
            )
        )


def parse_cli_options(options: Sequence[str] | None, palette: dict[str, str]) -> dict[str, Any]:
    """Parses a sequence of 'key=value' strings into a dictionary."""
    if not options:
        return {}

    result: dict[str, Any] = {}
    error_console = get_error_console()

    for item in options:
        if "=" not in item:
            error_console.print(
                f"[{palette.get('panel_title_warning')}]Warning:[/] Skipping malformed option '{item}'."
                "Must be in 'key=value' format."
            )
            continue

        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()

        if (value.startswith("{") and value.endswith("}")) or (value.startswith("[") and value.endswith("]")):
            try:
                result[key] = json.loads(value)
                continue
            except json.JSONDecodeError:
                pass

        result[key] = value

    return result


class DummyContext:
    """A no-op context manager to suppress spinners when outputting raw JSON."""

    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class DynamicHelpCommand(TyperCommand):
    """
    Base Typer command class for injecting dynamic, context-sensitive help.
    Subclasses must define `target_param_name` and override `get_dynamic_renderable`.
    """

    target_param_name: str = "target"

    def get_dynamic_renderable(self, target: str, ui_context: Any) -> Any | None:
        """Override this to return a Rich renderable for the extra help."""
        raise NotImplementedError("Subclasses must implement get_dynamic_renderable")

    def format_help(self, ctx: "_click.Context", formatter: "_click.HelpFormatter") -> None:

        super().format_help(ctx, formatter)

        target_val = ctx.params.get(self.target_param_name)

        if not target_val:
            cmd_chain = []
            current_ctx: "_click.Context | None" = ctx

            while current_ctx and current_ctx.info_name:
                cmd_chain.append(current_ctx.info_name)
                current_ctx = current_ctx.parent

            cmd_chain.reverse()
            subcommands = cmd_chain[1:]

            cmd_idx = -1
            if subcommands:
                match_idx = 0
                for i, arg in enumerate(sys.argv):
                    if arg == subcommands[match_idx]:
                        match_idx += 1
                        if match_idx == len(subcommands):
                            cmd_idx = i
                            break
            else:
                try:
                    if self.name is not None:
                        cmd_idx = sys.argv.index(self.name)
                except ValueError:
                    pass

            if cmd_idx != -1:
                for arg in sys.argv[cmd_idx + 1 :]:
                    if not arg.startswith("-"):
                        target_val = arg
                        break

            if not target_val and getattr(ctx, "args", None):
                for arg in ctx.args:
                    if not arg.startswith("-"):
                        target_val = arg
                        break

        if target_val:
            ui_context: "UIContext | None" = ctx.find_object(dict)  # type: ignore[assignment]
            if ui_context is None:
                from dorsal.cli.themes import get_ui_theme

                ui_context = get_ui_theme()

            extra_help = self.get_dynamic_renderable(target_val, ui_context)
            if extra_help:
                console = get_rich_console()
                console.print()
                console.print(extra_help)


def render_model_help_panel(help_info: dict[str, Any], ui_context: dict[str, Any]) -> Panel | None:
    """Renders a Rich Panel for model help data returned by get_model_help."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.console import Group
    from rich.text import Text

    palette = ui_context.get("palette", {})
    borders = ui_context.get("borders", "rounded")
    status = help_info.get("status")

    if status == "error":
        # Cleaned up error title and payload
        return Panel(
            help_info.get("error", "Unknown error"),
            title="[bold yellow]Model Resolution Failed[/]",
            border_style="yellow",
            box=borders,
        )

    if status == "not_installed":
        target = help_info["target"]
        pkg = help_info["package_name"]

        if "/" in target:
            return Panel(
                f"Registry model [bold cyan]{target}[/] (package: [bold]{pkg}[/]) is not installed.\n"
                f"Run [bold]dorsal model install {target}[/] to install it and view its runtime options.",
                title=f"Model: {target}",
                border_style="cyan",
                box=borders,
            )
        else:
            return Panel(
                f"Model [bold cyan]{target}[/] is not installed.\n"
                f"To install a model from DorsalHub, use its full model ID in [bold]organization/project[/] format, e.g. [bold]dorsalhub/whisper[/]",
                title=f"Model: {target}",
                border_style="cyan",
                box=borders,
            )

    if status == "config_error":
        return Panel(
            f"Failed to load configuration for '{help_info['package_name']}': {help_info.get('error')}",
            title="[bold red]Configuration Error[/]",
            border_style="red",
            box=borders,
        )

    options = help_info.get("options", {})
    model_class = help_info.get("model_class", "UnknownClass")

    if not options:
        return Panel(
            f"The model [bold]{model_class}[/] does not define any default options.",
            title=f"Model: {help_info['package_name']}",
            border_style="green",
            box=borders,
        )

    table = Table(show_header=True, header_style="bold", box=None, expand=True)
    table.add_column("Option", style=palette.get("primary_value", "cyan"), width=20)
    table.add_column("Type", style="green", width=10)
    table.add_column("Default", style="magenta", width=15)
    table.add_column("Description", style="default")

    type_ui_mapping = {
        "str": "String",
        "int": "Integer",
        "float": "Float",
        "bool": "Boolean",
        "dict": "JSON",
        "list": "Array",
    }

    for opt_key, opt_data in options.items():
        raw_type = opt_data.get("type", "str")
        display_type = type_ui_mapping.get(raw_type, raw_type.capitalize())

        default_val = opt_data.get("default")
        if default_val is None:
            default_str = "<unassigned>"
        elif default_val == "":
            default_str = '""'
        else:
            default_str = str(default_val)

        table.add_row(opt_key, display_type, default_str, opt_data.get("help", "No description provided."))

    footer = Text("\nPass model options via --opt.", style="dim")

    return Panel(
        Group(table, footer),
        title=f"Model Options: {model_class}",
        title_align="left",
        border_style=palette.get("panel_border_info", "green"),
        padding=(1, 2),
        box=borders,
    )


class ModelHelpCommand(DynamicHelpCommand):
    target_param_name = "target"

    def get_dynamic_renderable(self, target: str, ui_context: dict) -> Any | None:
        from dorsal.api.model import get_model_help

        help_info = get_model_help(target=target)

        return render_model_help_panel(help_info, ui_context)


class AdapterHelpCommand(DynamicHelpCommand):
    target_param_name = "target_format"

    def get_dynamic_renderable(self, target: str, ui_context: dict) -> Any | None:
        from dorsal.api.adapters import get_adapter_help

        return get_adapter_help(target, ui_context)
