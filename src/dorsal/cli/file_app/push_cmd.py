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

import typer
from typing import Annotated
import pathlib
import logging
from rich.panel import Panel
from rich.text import Text
import json

logger = logging.getLogger(__name__)


def push_file(
    ctx: typer.Context,
    path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="The path to the single file to push to DorsalHub.",
        ),
    ],
    public: Annotated[
        bool,
        typer.Option("--public/--private", help="Index the file record as public or private."),
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
            help="Bypass the local cache and re-process the file (does not update cache).",
            rich_help_panel="Cache Options",
        ),
    ] = False,
    overwrite_cache: Annotated[
        bool,
        typer.Option(
            "--overwrite-cache",
            help="Re-process the file and overwrite the local cache with new data.",
            rich_help_panel="Cache Options",
        ),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Fail with an error code if any metadata is rejected (Partial Success).",
            rich_help_panel="Integrity Options",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the API response as a raw JSON object."),
    ] = False,
    resolve_links: Annotated[
        bool,
        typer.Option(
            "--follow-links/--no-follow-links",
            help="Follow symlinks to index target metadata vs indexing the link itself.",
        ),
    ] = True,
):
    """
    Pushes a single file's metadata to DorsalHub.
    """
    from dorsal.common.cli import (
        EXIT_CODE_ERROR,
        get_rich_console,
        determine_use_cache_value,
        exit_cli,
    )
    from dorsal.file.dorsal_file import LocalFile
    from dorsal.common.exceptions import (
        DorsalClientError,
        DorsalOfflineError,
        AuthError,
        PartialIndexingError,
    )

    console = get_rich_console()

    if use_cache and skip_cache:
        exit_cli(
            code=EXIT_CODE_ERROR,
            message="Error: --use-cache and --skip-cache flags cannot be used together.",
        )

    if skip_cache and overwrite_cache:
        exit_cli(
            code=EXIT_CODE_ERROR,
            message="Error: --skip-cache and --overwrite-cache flags cannot be used together.",
        )

    use_cache_value = determine_use_cache_value(use_cache=use_cache, skip_cache=skip_cache)
    palette: dict[str, str] = ctx.obj["palette"]
    access_level_str = "public" if public else "private"

    if not json_output:
        console.print(
            f"📡 Preparing to push metadata for [{palette['primary_value']}]{path.name}[/] as a {access_level_str} record..."
        )

    try:
        local_file = LocalFile(
            file_path=str(path),
            use_cache=use_cache_value,
            overwrite_cache=overwrite_cache,
            follow_symlinks=resolve_links,
        )

        logger.debug("Record to push: %s", local_file.model_dump_json(exclude_none=True, by_alias=True))

        with console.status("Pushing to DorsalHub..."):
            api_response = local_file.push(public=public, strict=strict)

        if json_output:
            console.print(json.dumps(api_response.model_dump(mode="json"), indent=2, ensure_ascii=False))
            exit_cli()

        if api_response.results and api_response.success > 0:
            pushed_hash = api_response.results[0].hash
            success_text = Text.assemble(
                (
                    "The file record was successfully pushed to DorsalHub.\n\n",
                    palette.get("success", "bold green"),
                ),
                ("SHA256 Hash: ", palette.get("key", "dim")),
                (f"{pushed_hash}", palette.get("hash_value", "magenta")),
            )
            panel_title = "✅ Push Complete"
            panel_border_style = palette.get("panel_border_success", "green")
        else:
            detail: str | None = "Unknown"
            if api_response.results and hasattr(api_response.results[0], "detail"):
                if api_response.results[0].annotations:
                    detail = api_response.results[0].annotations[0].detail

            success_text = Text(
                f"The file could not be pushed to DorsalHub.\nReason: {detail}",
                style=palette.get("error", "bold red"),
            )
            panel_title = "❌ Push Failed"
            panel_border_style = palette.get("panel_border_error", "red")

        console.print(
            Panel(
                success_text,
                expand=False,
                title=panel_title,
                border_style=panel_border_style,
            )
        )

    except PartialIndexingError as e:
        if json_output:
            error_payload = {
                "error": "PartialIndexingError",
                "message": str(e),
                "summary": e.summary,
            }
            console.print(json.dumps(error_payload, indent=2, ensure_ascii=False))
        else:
            console.print(f"[{palette.get('error', 'bold red')}]Strict Mode Error:[/] {e}")
            if e.summary and "failures" in e.summary:
                console.print(f"[{palette.get('warning', 'yellow')}]Failures detected:[/]")
                for failure in e.summary["failures"]:
                    console.print(f"  - {failure}")

        exit_cli(code=EXIT_CODE_ERROR)

    except typer.Exit:
        raise
    except DorsalOfflineError:
        raise
    except AuthError:
        raise
    except DorsalClientError as e:
        exit_cli(code=EXIT_CODE_ERROR, message=f"API Error: {e.message}")
    except Exception as e:
        logger.exception(f"An unexpected error occurred while pushing file {path}.")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {e}")
