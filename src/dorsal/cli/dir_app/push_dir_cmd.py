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

import json
import logging
import typer
import pathlib
from typing import Annotated, TYPE_CHECKING, cast

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.markup import escape

if TYPE_CHECKING:
    from dorsal.file.collection.local import LocalFileCollection
    from dorsal.file.dorsal_file import LocalFile

logger = logging.getLogger(__name__)


def push_directory(
    ctx: typer.Context,
    path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            help="The directory path containing files to scan and push.",
        ),
    ],
    private: Annotated[
        bool,
        typer.Option(
            "--private/--public",
            help="Index records as private or public.",
        ),
    ] = True,
    recursive: Annotated[
        bool,
        typer.Option(
            "--recursive/--no-recursive",
            "-r/-R",
            help="Scan subdirectories recursively.",
        ),
    ] = False,
    create_collection: Annotated[
        bool,
        typer.Option(
            "--create-collection",
            help="Create a private collection on DorsalHub containing the pushed files.",
        ),
    ] = False,
    collection_name: Annotated[
        str | None,
        typer.Option(
            "--name",
            help="Name for the new collection. Defaults to the directory name if not provided.",
        ),
    ] = None,
    collection_desc: Annotated[str | None, typer.Option("--desc", help="Description for the new collection.")] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="Scan files and show what would be pushed, without sending data to the server.",
        ),
    ] = False,
    ignore_duplicates: Annotated[
        bool,
        typer.Option(
            "--ignore-duplicates",
            help="Keep the first file of any duplicates and push it, ignoring subsequent copies.",
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
            help="Bypass the local cache and re-process all files, overriding any global setting.",
            rich_help_panel="Cache Options",
        ),
    ] = False,
    overwrite_cache: Annotated[
        bool,
        typer.Option(
            "--overwrite-cache",
            help="Re-process all files and overwrite the local cache with new data.",
            rich_help_panel="Cache Options",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output the final summary as a raw JSON object to stdout for scripting.",
        ),
    ] = False,
):
    """
    Scans a directory, pushes all file metadata to DorsalHub,
    and optionally creates a new remote collection from the contents.
    """
    from dorsal.common.constants import API_MAX_BATCH_SIZE
    from dorsal.common.cli import (
        EXIT_CODE_ERROR,
        get_rich_console,
        exit_cli,
        determine_use_cache_value,
    )
    from dorsal.file.collection.local import LocalFileCollection
    from dorsal.file.dorsal_file import LocalFile
    from dorsal.common.exceptions import AuthError, DorsalError, DorsalOfflineError

    console = get_rich_console()
    palette: dict[str, str] = ctx.obj["palette"]
    progress_console = None if json_output else console

    if create_collection and not collection_name:
        collection_name = path.name
        if not json_output:
            console.print(
                f"[{palette.get('info', 'dim')}]--name not provided. Defaulting to directory name: '[bold]{collection_name}[/]'[/]"
            )

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

    if not json_output:
        action_verb = "publish" if create_collection else "push"
        console.print(f"📡 Preparing to {action_verb} metadata from [{palette['primary_value']}]{escape(str(path))}[/]")

    try:
        collection = LocalFileCollection(
            source=str(path),
            recursive=recursive,
            console=progress_console,
            palette=palette,
            use_cache=use_cache_value,
            overwrite_cache=overwrite_cache,
        )

        if not collection:
            exit_cli(message=f"No valid files found in '{escape(str(path))}'.")

        if ignore_duplicates:
            original_count = len(collection)
            unique_files = list({f.hash: f for f in collection}.values())
            if len(unique_files) < original_count:
                collection = LocalFileCollection(
                    source=cast(list[LocalFile], unique_files),
                    use_cache=use_cache_value,
                )
                if not json_output:
                    console.print(
                        f"[{palette.get('info', 'dim')}]Ignoring {original_count - len(unique_files)} duplicate files.[/]"
                    )

        if dry_run:
            _display_dry_run_panel(collection=collection, use_cache=use_cache_value, palette=palette)
            exit_cli()

        if create_collection and len(collection.files) > API_MAX_BATCH_SIZE:
            logger.warning(
                f"Directory too large to create a collection via the CLI (limit: {API_MAX_BATCH_SIZE}). Instead, use the `LocalFileCollection` directly."
            )
            create_collection = False

        elif create_collection:
            if collection_name is None:
                return exit_cli(
                    code=EXIT_CODE_ERROR,
                    message="Internal Error: Collection name was not set before creation.",
                )
            remote_collection = collection.create_remote_collection(
                name=collection_name, description=collection_desc, is_private=private
            )

            if json_output:
                console.print(remote_collection.metadata.model_dump_json(indent=2, by_alias=True, exclude_none=True))
            else:
                success_panel = Panel(
                    f"✅ Successfully pushed {len(collection)} files and created collection.\n\n"
                    f"[bold]URL:[/] [link={remote_collection.metadata.private_url}]{remote_collection.metadata.private_url}[/link]",
                    title=f"[{palette.get('panel_title_success', 'bold green')}]Publish Complete[/]",
                    border_style=palette.get("panel_border_success", "green"),
                    expand=False,
                )
                console.print(success_panel)

        if not create_collection:
            summary = collection.push(private=private, console=progress_console, palette=palette)

            is_duplicate_error = False
            if summary.get("failed_api_batches", 0) > 0:
                for detail in summary.get("batch_processing_details", []):
                    if detail.get("status") == "failure" and "Cannot process duplicate files" in detail.get(
                        "error_message", ""
                    ):
                        is_duplicate_error = True
                        break

            if is_duplicate_error:
                if not json_output:
                    command_color = palette.get("primary_value", "default")
                    error_text = Text.from_markup(
                        "[bold]Push failed because the directory contains duplicate files.[/]\n\n"
                        "To get a summary of the duplicate files, run:\n"
                        f'[bold {command_color}]dorsal dir duplicates "{escape(str(path))}"[/]\n\n'
                        "To push this directory anyway (the first of each duplicate will be indexed), run:\n"
                        f'[bold {command_color}]dorsal dir push "{escape(str(path))}" --ignore-duplicates[/]',
                    )
                    error_panel = Panel(
                        error_text,
                        title=f"[{palette.get('panel_title_error', 'bold red')}]Duplicate Files Detected[/]",
                        border_style=palette.get("panel_border_error", "red"),
                        expand=False,
                    )
                    console.print(error_panel)
                else:
                    console.print(json.dumps(summary, indent=2, default=str, ensure_ascii=False))

                exit_cli(code=EXIT_CODE_ERROR)

            if json_output:
                console.print(json.dumps(summary, indent=2, default=str, ensure_ascii=False))
            else:
                _display_summary_panel(
                    summary=summary,
                    private=private,
                    palette=palette,
                    use_cache=use_cache_value,
                    collection=collection,
                )

    except DorsalError as err:
        exit_cli(code=EXIT_CODE_ERROR, message=str(err))
    except typer.Exit:
        raise
    except DorsalOfflineError:
        raise
    except AuthError:
        raise
    except Exception as err:
        logger.exception("An unexpected error occurred in 'dir push'")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {err}")


def _display_dry_run_panel(collection: "LocalFileCollection", use_cache: bool, palette: dict):
    """Helper to display the dry run output."""
    from dorsal.file.utils.size import human_filesize
    from dorsal.common.cli import get_rich_console

    console = get_rich_console()

    files_from_cache = sum(1 for f in collection if f._source == "cache") if use_cache else 0
    cache_info_str = f" ({files_from_cache} from cache)" if files_from_cache > 0 else ""

    console.print(
        Panel(
            f"DRY RUN MODE: Would push {len(collection)} files.",
            border_style=palette.get("panel_border_warning", "yellow"),
        )
    )
    console.print(f"🔎 Found {len(collection)} file(s) that would be pushed{cache_info_str}:")
    scan_table = Table(box=box.ROUNDED, header_style=palette["table_header"])
    scan_table.add_column("Filename", style=palette["primary_value"], no_wrap=True)
    scan_table.add_column("Size")
    scan_table.add_column("Media Type")
    scan_table.add_column("Source", justify="center")
    for file in collection:
        source_text = "Cache" if file._source == "cache" else "Disk"
        source_style = palette.get("success", "green") if file._source == "cache" else palette.get("key", "dim")
        scan_table.add_row(
            file.name,
            human_filesize(file.size),
            file.media_type,
            f"[{source_style}]{source_text}[/]",
        )
    console.print(scan_table)


def _display_summary_panel(
    summary: dict,
    private: bool,
    palette: dict,
    use_cache: bool,
    collection: "LocalFileCollection",
):
    """Helper to display the standard push summary."""
    from dorsal.common.cli import get_rich_console

    console = get_rich_console()

    files_from_cache = sum(1 for f in collection if f._source == "cache") if use_cache else 0
    access_level_str = "Private" if private else "Public"
    access_level_style = (
        palette.get("access_private", "default") if private else palette.get("access_public", "default")
    )

    summary_table = Table.grid(expand=True)
    summary_table.add_column(justify="right", style=palette["key"], width=25)
    summary_table.add_column(justify="left")
    summary_table.add_row("Access Level:", Text(access_level_str, style=access_level_style))
    summary_table.add_row(
        "Files Scanned:",
        f"{summary.get('total_records_in_collection')} ({files_from_cache} from cache)",
    )
    summary_table.add_row("File Records to Push:", str(summary.get("total_records_to_push")))
    summary_table.add_row(
        "File Records Accepted:",
        Text(str(summary.get("total_records_accepted_by_api")), style=palette["success"]),
    )

    if summary.get("total_batches_created", 0) > 1:
        summary_table.add_row()
        summary_table.add_row("Batches Created:", str(summary.get("total_batches_created")))
        summary_table.add_row(
            "Successful Batches:",
            Text(str(summary.get("successful_api_batches")), style=palette["success"]),
        )
        summary_table.add_row(
            "Failed Batches:",
            Text(str(summary.get("failed_api_batches")), style=palette["error"]),
        )

    console.print(
        Panel(
            summary_table,
            title=f"[{palette.get('panel_title_success', 'bold green')}]Push Complete[/]",
            expand=False,
            border_style=palette.get("panel_border_success", "green"),
        )
    )

    if summary.get("failed_api_batches", 0) > 0:
        console.print(f"\n[{palette['error']}]⚠️ Some batches failed to process:[/{palette['error']}]")
        failed_table = Table(
            title="Failed Batch Details",
            expand=True,
            header_style=palette["table_header"],
        )
        failed_table.add_column("Batch #", style=palette["primary_value"], ratio=15)
        failed_table.add_column("Error Type", style=palette["warning"], ratio=25)
        failed_table.add_column("Error Message", ratio=60)
        for detail in summary.get("batch_processing_details", []):
            if detail["status"] == "failure":
                failed_table.add_row(
                    str(detail["batch_number"]),
                    detail["error_type"],
                    detail["error_message"],
                )
        console.print(failed_table)
