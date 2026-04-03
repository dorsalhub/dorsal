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

import logging
from typing import Annotated, Optional
import pathlib
import sys
import typer
from rich.logging import RichHandler
from rich.console import Console

from dorsal.version import __version__
from dorsal.common.exceptions import AuthError, DorsalOfflineError
from dorsal.common.cli import get_rich_console, handle_auth_error, handle_offline_error, exit_cli, EXIT_CODE_ERROR
from dorsal.cli.themes import get_ui_theme
from dorsal.cli.adapter_app import app as adapter_app_
from dorsal.cli.index_app import app as index_app_
from dorsal.cli.config_app import app as config_app_
from dorsal.cli.auth_app import app as auth_app_
from dorsal.cli.model_app import app as model_app_
from dorsal.cli.hub_app import app as hub_app_
from dorsal.cli.collection_app import app as collection_app_
from dorsal.cli.config_app import theme_app as theme_app_
from dorsal.cli.config_app import pipeline_app as pipeline_app_
from dorsal.cli.model_app.install_model_cmd import install_model
from dorsal.cli.model_app.run_model_cmd import run_model
from dorsal.cli.index_app.search_index_cmd import search_index_cmd
from dorsal.cli.local_app import app as local_app_
from dorsal.cli.index_app.get_index_cmd import get_index_record
from dorsal.cli.local_app.scan_cmd import scan_target
from dorsal.cli.local_app.push_cmd import push_target
from dorsal.cli.local_app.report_cmd import report_target
from dorsal.cli.local_app.info_cmd import info_target
from dorsal.cli.local_app.identify_cmd import identify_target
from dorsal.cli.local_app.hash_cmd import hash_target
from dorsal.cli.local_app.duplicates_cmd import duplicates_target

logger = logging.getLogger(__name__)

current_working_directory = str(pathlib.Path.cwd())
if current_working_directory not in sys.path:
    sys.path.insert(0, current_working_directory)


def _extract_global_flag(flag_name: str) -> str | None:
    """Safely extracts a flag from sys.argv handling both space and '=' syntax."""
    for i, arg in enumerate(sys.argv):
        if arg == flag_name:
            if i + 1 < len(sys.argv):
                return sys.argv[i + 1]
        elif arg.startswith(f"{flag_name}="):
            return arg.split("=", 1)[1]
    return None


def version_callback(value: bool):
    """Prints the version of the application and exits."""
    if value:
        from dorsal.common.cli import get_rich_console

        console = get_rich_console()
        console.print(f"Dorsal Version {__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="dorsal",
    help="Extract, validate, and sync structured file metadata.",
    add_completion=False,
    pretty_exceptions_enable=True,
    no_args_is_help=True,
    rich_markup_mode="rich",
    epilog=(f"[dim]Powered by Dorsal v{__version__}[/dim]"),
)


cli_apps = [
    hub_app_,
    collection_app_,
    model_app_,
    pipeline_app_,
    adapter_app_,
    auth_app_,
    index_app_,
    config_app_,
    theme_app_,
]

for _cli_app in cli_apps:
    if _cli_app.info.help:
        _cli_app.info.help = f"... {_cli_app.info.help}"


@app.callback()
def main(
    ctx: typer.Context,
    version: Annotated[
        Optional[bool],
        typer.Option(
            "--version",
            callback=version_callback,
            is_eager=True,
            help="Show the application's version and exit.",
        ),
    ] = None,
    verbose: int = typer.Option(
        0,
        "--verbose",
        "-v",
        count=True,
        help="Increase logging verbosity. -v for INFO, -vv for DEBUG.",
    ),
    theme: str = typer.Option(None, "--theme", help="Override the default color theme."),
    icons: str = typer.Option(None, "--icons", help="Override the icon style (emoji, ascii, none)."),
    borders: str = typer.Option(None, "--borders", help="Override panel borders (rounded, heavy, ascii, none)."),
):
    """
    Dorsal CLI: A tool for interacting with the Dorsal data platform.
    """
    is_json_output = "--json" in sys.argv

    if verbose == 1:
        log_level = logging.INFO
    elif verbose >= 2:
        log_level = logging.DEBUG
    else:
        log_level = logging.WARNING

    if is_json_output:
        log_level = logging.CRITICAL
        log_console = Console(stderr=True)
    else:
        from dorsal.common.cli import get_rich_console

        log_console = get_rich_console()

    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                rich_tracebacks=True,
                show_path=False,
                console=log_console,
                level=log_level,
            )
        ],
    )

    logger = logging.getLogger("dorsal")
    logger.info(f"Logging level set to {logging.getLevelName(log_level)}")
    ctx.obj = get_ui_theme(theme_override=theme, icon_override=icons, border_override=borders)


# ==============================================================================
# Command & Group Registrations
# ==============================================================================

# --- Local Operations ---
app.command(
    name="scan", help="Scan a local file or directory. Generates file metadata.", rich_help_panel="Local Operations"
)(scan_target)
app.command(name="get", help="Get a file record from the local record cache.", rich_help_panel="Local Operations")(
    get_index_record
)
app.command(name="hash", help="Generate file hashes.", rich_help_panel="Local Operations")(hash_target)
app.command(name="search", help="Search local file index.", rich_help_panel="Local Operations")(search_index_cmd)
app.command(name="dupes", help="Check for duplicate files in a directory.", rich_help_panel="Local Operations")(
    duplicates_target
)
app.command(
    name="duplicates",
    help="Scan a directory, checking for duplicate files.",
    hidden=True,
    rich_help_panel="Local Operations",
)(duplicates_target)
app.command(name="info", help="High-level summary of a directory or a file.", rich_help_panel="Local Operations")(
    info_target
)
app.command(
    name="report", help="Generate HTML report for a local file or directory.", rich_help_panel="Local Operations"
)(report_target)

# --- DorsalHub & Cloud ---
app.add_typer(hub_app_, name="hub", rich_help_panel="DorsalHub")
app.command(name="id", help="Identify a local file by its hash. Queries DorsalHub.", rich_help_panel="DorsalHub")(
    identify_target
)
app.command(
    name="identify",
    help="Identify a local file by its hash. Queries DorsalHub.",
    hidden=True,
    rich_help_panel="DorsalHub",
)(identify_target)
app.command(name="push", help="Push metadata for a local file or directory to DorsalHub.", rich_help_panel="DorsalHub")(
    push_target
)
app.add_typer(collection_app_, name="collection", rich_help_panel="DorsalHub")

# --- Models & Pipelines ---
app.command(name="run", help="Run a model on a local file or directory.", rich_help_panel="Models & Pipelines")(
    run_model
)
app.command(
    name="install", help="Install a model from DorsalHub or a local folder.", rich_help_panel="Models & Pipelines"
)(install_model)
app.add_typer(model_app_, name="model", rich_help_panel="Models & Pipelines")
app.add_typer(pipeline_app_, name="pipeline", rich_help_panel="Models & Pipelines")
app.add_typer(adapter_app_, name="adapter", rich_help_panel="Models & Pipelines")

# --- Configuration & System ---
app.add_typer(auth_app_, name="auth", rich_help_panel="Configuration & System")
app.add_typer(index_app_, name="index", rich_help_panel="Configuration & System")
app.add_typer(config_app_, name="config", rich_help_panel="Configuration & System")
app.add_typer(theme_app_, name="theme", rich_help_panel="Configuration & System")

# --- Hidden / Internal ---
app.add_typer(local_app_, name="local", hidden=True)


def cli_app():
    try:
        app()
    except AuthError as err:
        from dorsal.common.cli import get_rich_console, EXIT_CODE_ERROR

        console = get_rich_console()

        # Safely extract all three UI overrides
        theme_override = _extract_global_flag("--theme")
        icons_override = _extract_global_flag("--icons")
        borders_override = _extract_global_flag("--borders")

        ui_context = get_ui_theme(
            theme_override=theme_override, icon_override=icons_override, border_override=borders_override
        )

        handle_auth_error(err, console, ui_context)
        sys.exit(EXIT_CODE_ERROR)

    except DorsalOfflineError as err:
        from dorsal.common.cli import get_rich_console, EXIT_CODE_ERROR

        console = get_rich_console()

        theme_override = _extract_global_flag("--theme")
        icons_override = _extract_global_flag("--icons")
        borders_override = _extract_global_flag("--borders")

        ui_context = get_ui_theme(
            theme_override=theme_override, icon_override=icons_override, border_override=borders_override
        )

        handle_offline_error(err, console, ui_context)
        sys.exit(EXIT_CODE_ERROR)


if __name__ == "__main__":
    cli_app()
