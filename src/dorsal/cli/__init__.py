# Copyright 2025 Dorsal Hub LTD
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
import typer
from rich.logging import RichHandler
from rich.console import Console
import sys
from dorsal.common.exceptions import AuthError, DorsalOfflineError
from dorsal.common.cli import get_rich_console, handle_auth_error, handle_offline_error, exit_cli, EXIT_CODE_ERROR
from dorsal.cli.themes.palettes import get_palette
from dorsal.cli.cache_app import app as cache_app_
from dorsal.cli.config_app import app as config_app_
from dorsal.cli.auth_app import app as auth_app_
from dorsal.cli.dir_app import app as dir_app_
from dorsal.cli.file_app import app as file_app_
from dorsal.cli.record_app import app as record_app_
from dorsal.cli.collection_app import app as collection_app_
from dorsal.cli.config_app import theme_app as theme_app_
from dorsal.cli.search_app import search_and_display
from dorsal.cli.file_app.identify_cmd import identify_file_cmd
from dorsal.cli.record_app.search_cmd import search_record

logger = logging.getLogger(__name__)

current_working_directory = str(pathlib.Path.cwd())
if current_working_directory not in sys.path:
    sys.path.insert(0, current_working_directory)


def version_callback(value: bool):
    """Prints the version of the application and exits."""
    if value:
        from dorsal.version import __version__
        from dorsal.common.cli import get_rich_console

        console = get_rich_console()
        console.print(f"Dorsal CLI Version: {__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="dorsal",
    help="A powerful tool for local file metadata generation and management.",
    add_completion=False,
    pretty_exceptions_enable=True,
    no_args_is_help=True,
)


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
    theme: str = typer.Option("default", "--theme", help="Set the color theme for the output."),
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
    ctx.obj = {"palette": get_palette(theme)}


app.command(name="search", help="Search DorsalHub file records.")(search_record)


@app.command(name="id", help="Identifies a local file by its hash, by checking DorsalHub.")
def id_alias(
    ctx: typer.Context,
    path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="The path to the local file to identify.",
        ),
    ],
    secure: Annotated[
        bool,
        typer.Option(
            "--secure",
            "-s",
            help="Use the slower, definitive SHA-256 hash instead of the default quick hash.",
        ),
    ] = False,
    use_cache: Annotated[
        bool,
        typer.Option(
            "--use-cache",
            help="Force the use of the cache, overriding any global setting.",
            rich_help_panel="Cache Options",
        ),
    ] = False,
    skip_cache: Annotated[
        bool,
        typer.Option(
            "--skip-cache",
            help="Bypass the local cache and re-process the file, overriding any global setting to enable it.",
            rich_help_panel="Cache Options",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output the full metadata as a raw JSON object to stdout for scripting.",
        ),
    ] = False,
):
    """Identifies a local file by its hash, by checking DorsalHub."""
    identify_file_cmd(
        ctx=ctx,
        path=path,
        secure=secure,
        use_cache=use_cache,
        skip_cache=skip_cache,
        json_output=json_output,
    )


app.add_typer(auth_app_, name="auth", help="Manage authentication and user sessions.")
app.add_typer(file_app_, name="file", help="Commands to manage local file metadata.")
app.add_typer(record_app_, name="record", help="Commands to manage remote file metadata.")
app.add_typer(dir_app_, name="dir")
app.add_typer(cache_app_, name="cache")
app.add_typer(config_app_, name="config", help="View the current library configuration.")
app.add_typer(collection_app_, name="collection", help="Commands to manage remote file collections.")
app.add_typer(theme_app_, name="theme", help="Identifies a local file by its hash, by checking DorsalHub.")


def cli_app():
    try:
        app()
    except AuthError as err:
        console = get_rich_console()

        theme = "default"
        if "--theme" in sys.argv:
            try:
                idx = sys.argv.index("--theme")
                theme = sys.argv[idx + 1]
            except IndexError:
                pass

        palette = get_palette(theme)
        handle_auth_error(err, console, palette)
        sys.exit(EXIT_CODE_ERROR)

    except DorsalOfflineError as err:
        console = get_rich_console()

        theme = "default"
        if "--theme" in sys.argv:
            try:
                idx = sys.argv.index("--theme")
                theme = sys.argv[idx + 1]
            except (ValueError, IndexError):
                pass

        palette = get_palette(theme)

        handle_offline_error(err, console, palette)
        sys.exit(EXIT_CODE_ERROR)


if __name__ == "__main__":
    cli_app()
