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

import typer
import pathlib
import json
import logging
from typing import Annotated

from rich.panel import Panel
from rich.text import Text
from rich.markup import escape

logger = logging.getLogger(__name__)


def identify_file_cmd(
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
            help="Use SHA-256 to hash the file, instead of the default QUICK hash.",
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
            help="Bypass the local cache and re-process the file, overriding any global setting.",
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
    """
    Identifies a local file by its hash, by checking DorsalHub.
    """
    from dorsal.api.file import identify_file
    from dorsal.cli.views.file import create_file_info_panel
    from dorsal.common.cli import (
        get_rich_console,
        exit_cli,
        EXIT_CODE_ERROR,
        determine_use_cache_value,
    )
    from dorsal.common.exceptions import AuthError, DorsalClientError, DorsalOfflineError, NotFoundError

    console = get_rich_console()
    palette = ctx.obj["palette"]

    if use_cache and skip_cache:
        exit_cli(
            code=EXIT_CODE_ERROR,
            message="Error: --use-cache and --skip-cache flags cannot be used together.",
        )

    use_cache_value = determine_use_cache_value(use_cache=use_cache, skip_cache=skip_cache)

    if not json_output:
        console.print(f"🔎 Identifying file [{palette['primary_value']}]{escape(path.name)}[/]...")

    try:
        is_quick_mode = not secure

        file_record_dict = identify_file(
            file_path=str(path),
            quick=is_quick_mode,
            use_cache=use_cache_value,
            mode="dict",
        )

        if json_output:
            console.print(json.dumps(file_record_dict, indent=2, default=str, ensure_ascii=False))
            raise typer.Exit(0)

        panel = create_file_info_panel(
            record_dict=file_record_dict,
            title="✅ File Identified",
            private=None,
            palette=palette,
        )
        console.print(panel)

    except typer.Exit:
        raise
    except NotFoundError as e:
        if json_output:
            error_payload = {
                "success": False,
                "error": "Not Found",
                "detail": e.message,
            }
            console.print(json.dumps(error_payload, indent=2))
        else:
            message = Text.assemble(
                ("This file has not been indexed to DorsalHub.\n\n", "default"),
                ("Why not (privately) index it yourself, by running:\n", "default"),
                (
                    f'dorsal file push "{escape(str(path))}"\n\n',
                    f"bold {palette.get('primary_value', 'default')}",
                ),
                ("You can also index it publicly, by running:\n", "default"),
                (
                    f'dorsal file push "{escape(str(path))}" --public',
                    f"bold {palette.get('primary_value', 'default')}",
                ),
            )
            console.print(
                Panel(
                    message,
                    title=f"[{palette.get('panel_title_warning', 'bold yellow')}]⚠️ Not Found[/]",
                    border_style=palette.get("panel_border_warning", "yellow"),
                    expand=False,
                )
            )
        exit_cli(code=EXIT_CODE_ERROR)
    except DorsalOfflineError:
        raise
    except AuthError:
        raise

    except DorsalClientError as err:
        if json_output:
            error_payload = {
                "success": False,
                "error": "API Error",
                "detail": err.message,
            }
            console.print(json.dumps(error_payload, indent=2))
        else:
            exit_cli(code=EXIT_CODE_ERROR, message=f"API Error: {err.message}")
        exit_cli(code=EXIT_CODE_ERROR)
    except Exception as err:
        logger.exception(f"CLI 'identify' command failed for path {path}.")
        if json_output:
            error_payload = {
                "success": False,
                "error": "Unexpected Error",
                "detail": str(err),
            }
            console.print(json.dumps(error_payload, indent=2))
        else:
            exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {err}")
        exit_cli(code=EXIT_CODE_ERROR)
