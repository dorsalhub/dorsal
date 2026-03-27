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

from __future__ import annotations

import json
import logging
import pathlib
import typer
from typing import Annotated, TYPE_CHECKING, cast

from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.markup import escape

from dorsal.common.constants import API_MAX_BATCH_SIZE
from dorsal.common.cli import (
    EXIT_CODE_ERROR,
    get_rich_console,
    determine_use_cache_value,
    exit_cli,
)
from dorsal.common.exceptions import (
    DorsalClientError,
    DorsalOfflineError,
    AuthError,
    PartialIndexingError,
    DorsalError,
)

if TYPE_CHECKING:
    from dorsal.file.dorsal_file import LocalFile
    from dorsal.file.collection.local import LocalFileCollection

logger = logging.getLogger(__name__)


def push_target(
    ctx: typer.Context,
    path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=True,
            readable=True,
            resolve_path=True,
            help="The path to the file or directory to push to DorsalHub.",
        ),
    ],
    
    public: Annotated[
        bool,
        typer.Option("--public/--private", help="Index the record(s) as public or private."),
    ] = False,
    strict: Annotated[
        bool,
        typer.Option(
            "--strict",
            help="Fail immediately with an error code if any metadata is rejected (Partial Success).",
            rich_help_panel="Integrity Options",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the API response as a raw JSON object to stdout."),
    ] = False,
    
    recursive: Annotated[
        bool,
        typer.Option(
            "--recursive/--no-recursive",
            "-r/-R",
            help="[Dir Only] Scan subdirectories recursively.",
            rich_help_panel="Directory Push Options",
        ),
    ] = False,
    create_collection: Annotated[
        bool,
        typer.Option(
            "--create-collection",
            help="[Dir Only] Create a private collection on DorsalHub containing the pushed files.",
            rich_help_panel="Directory Push Options",
        ),
    ] = False,
    collection_name: Annotated[
        str | None,
        typer.Option(
            "--name",
            help="[Dir Only] Name for the new collection. Defaults to the directory name if not provided.",
            rich_help_panel="Directory Push Options",
        ),
    ] = None,
    collection_desc: Annotated[
        str | None, 
        typer.Option(
            "--desc", 
            help="[Dir Only] Description for the new collection.",
            rich_help_panel="Directory Push Options",
        )
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="[Dir Only] Scan files and show what would be pushed, without sending data to the server.",
            rich_help_panel="Directory Push Options",
        ),
    ] = False,
    ignore_duplicates: Annotated[
        bool,
        typer.Option(
            "--ignore-duplicates",
            help="[Dir Only] Keep the first file of any duplicates and push it, ignoring subsequent copies.",
            rich_help_panel="Directory Push Options",
        ),
    ] = False,
    fail_fast: Annotated[
        bool,
        typer.Option(
            "--fail-fast/--no-fail-fast",
            help="[Dir Only] Stop immediately if a batch fails (HTTP error).",
            rich_help_panel="Directory Push Options",
        ),
    ] = True,
    lazy: Annotated[
        bool,
        typer.Option(
            "--lazy",
            help="[Dir Only] Start processing immediately with an indeterminate progress bar.",
            rich_help_panel="Performance Options",
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
            help="Bypass the local cache and re-process the file(s).",
            rich_help_panel="Cache Options",
        ),
    ] = False,
    overwrite_cache: Annotated[
        bool,
        typer.Option(
            "--overwrite-cache",
            help="Re-process the file(s) and overwrite the local cache with new data.",
            rich_help_panel="Cache Options",
        ),
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
    Pushes local file or directory metadata to DorsalHub,
    with options for strict validation and collection creation.
    """
    console = get_rich_console()
    palette = ctx.obj.get("palette", {})

    
    if use_cache and skip_cache:
        exit_cli(code=EXIT_CODE_ERROR, message="Error: --use-cache and --skip-cache flags cannot be used together.")
    if skip_cache and overwrite_cache:
        exit_cli(code=EXIT_CODE_ERROR, message="Error: --skip-cache and --overwrite-cache flags cannot be used together.")

    use_cache_value = determine_use_cache_value(use_cache=use_cache, skip_cache=skip_cache)

    
    if path.is_file():
        dir_flags_used = any([recursive, create_collection, collection_name, collection_desc, dry_run, ignore_duplicates, not fail_fast, lazy])
        if dir_flags_used:
             console.print("⚠️ [yellow]Warning:[/] Directory-specific push flags are ignored when pushing a single file.", style=palette.get("warning", "yellow"))
             
        _process_file_push(
            ctx=ctx, path=path, use_cache_value=use_cache_value, overwrite_cache=overwrite_cache,
            public=public, strict=strict, json_output=json_output, resolve_links=resolve_links,
            palette=palette, console=console
        )
    else:
        _process_dir_push(
            ctx=ctx, path=path, use_cache_value=use_cache_value, overwrite_cache=overwrite_cache,
            public=public, strict=strict, json_output=json_output, resolve_links=resolve_links,
            recursive=recursive, create_collection=create_collection, collection_name=collection_name,
            collection_desc=collection_desc, dry_run=dry_run, ignore_duplicates=ignore_duplicates,
            fail_fast=fail_fast, lazy=lazy, palette=palette, console=console
        )





def _process_file_push(ctx, path, use_cache_value, overwrite_cache, public, strict, json_output, resolve_links, palette, console):
    from dorsal.file.dorsal_file import LocalFile

    access_level_str = "public" if public else "private"

    if not json_output:
        console.print(f"📡 Preparing to push metadata for [{palette.get('primary_value', 'cyan')}]{path.name}[/] as a {access_level_str} record...")

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
                ("The file record was successfully pushed to DorsalHub.\n\n", palette.get("success", "bold green")),
                ("SHA256 Hash: ", palette.get("key", "dim")),
                (f"{pushed_hash}", palette.get("hash_value", "magenta")),
            )
            panel_title, panel_border_style = "✅ Push Complete", palette.get("panel_border_success", "green")
        else:
            detail: str | None = "Unknown"
            if api_response.results and hasattr(api_response.results[0], "detail"):
                if api_response.results[0].annotations:
                    detail = api_response.results[0].annotations[0].detail

            success_text = Text(f"The file could not be pushed to DorsalHub.\nReason: {detail}", style=palette.get("error", "bold red"))
            panel_title, panel_border_style = "❌ Push Failed", palette.get("panel_border_error", "red")

        console.print(Panel(success_text, expand=False, title=panel_title, border_style=panel_border_style))

    except PartialIndexingError as e:
        if json_output:
            error_payload = {"error": "PartialIndexingError", "message": str(e), "summary": e.summary}
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
    except (DorsalOfflineError, AuthError):
        raise
    except DorsalClientError as e:
        exit_cli(code=EXIT_CODE_ERROR, message=f"API Error: {e.message}")
    except Exception as e:
        logger.exception(f"An unexpected error occurred while pushing file {path}.")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {e}")





def _process_dir_push(ctx, path, use_cache_value, overwrite_cache, public, strict, json_output, resolve_links, recursive, create_collection, collection_name, collection_desc, dry_run, ignore_duplicates, fail_fast, lazy, palette, console):
    from dorsal.file.collection.local import LocalFileCollection
    from dorsal.file.dorsal_file import LocalFile

    progress_console = None if json_output else console

    if create_collection and not collection_name:
        collection_name = path.name
        if not json_output:
            console.print(f"[{palette.get('info', 'dim')}]--name not provided. Defaulting to directory name: '[bold]{collection_name}[/]'[/]")

    if not json_output:
        action_verb = "publish" if create_collection else "push"
        console.print(f"📡 Preparing to {action_verb} metadata from [{palette.get('primary_value', 'cyan')}]{escape(str(path))}[/]")

    try:
        collection = LocalFileCollection(
            source=str(path), recursive=recursive, console=progress_console, palette=palette,
            use_cache=use_cache_value, overwrite_cache=overwrite_cache, follow_symlinks=resolve_links, lazy=lazy,
        )

        if not collection:
            exit_cli(message=f"No valid files found in '{escape(str(path))}'.")

        if ignore_duplicates:
            original_count = len(collection)
            unique_files = list({f.hash: f for f in collection}.values())
            if len(unique_files) < original_count:
                collection = LocalFileCollection(source=cast(list[LocalFile], unique_files), use_cache=use_cache_value)
                if not json_output:
                    console.print(f"[{palette.get('info', 'dim')}]Ignoring {original_count - len(unique_files)} duplicate files.[/]")

        if dry_run:
            _display_dry_run_panel(collection=collection, use_cache=use_cache_value, palette=palette, console=console)
            exit_cli()

        if create_collection and len(collection.files) > API_MAX_BATCH_SIZE:
            logger.warning(f"Directory too large to create a collection via the CLI (limit: {API_MAX_BATCH_SIZE}). Instead, use the `LocalFileCollection` directly.")
            create_collection = False

        elif create_collection:
            if collection_name is None:
                return exit_cli(code=EXIT_CODE_ERROR, message="Internal Error: Collection name was not set before creation.")
                
            remote_collection = collection.create_remote_collection(name=collection_name, description=collection_desc, public=public)

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
            summary = collection.push(public=public, console=progress_console, palette=palette, fail_fast=fail_fast, strict=strict)

            is_duplicate_error = False
            if summary.get("failed", 0) > 0:
                for detail in summary.get("errors", []):
                    if "Cannot process duplicate files" in detail.get("error_message", ""):
                        is_duplicate_error = True
                        break

            if is_duplicate_error:
                if not json_output:
                    command_color = palette.get("primary_value", "default")
                    error_text = Text.from_markup(
                        "[bold]Push failed because the directory contains duplicate files.[/]\n\n"
                        "To get a summary of the duplicate files, run:\n"
                        f'[bold {command_color}]dorsal local duplicates "{escape(str(path))}"[/]\n\n'
                        "To push this directory anyway (the first of each duplicate will be indexed), run:\n"
                        f'[bold {command_color}]dorsal local push "{escape(str(path))}" --ignore-duplicates[/]',
                    )
                    console.print(Panel(error_text, title=f"[{palette.get('panel_title_error', 'bold red')}]Duplicate Files Detected[/]", border_style=palette.get("panel_border_error", "red"), expand=False))
                else:
                    console.print(json.dumps(summary, indent=2, default=str, ensure_ascii=False))
                exit_cli(code=EXIT_CODE_ERROR)

            if json_output:
                console.print(json.dumps(summary, indent=2, default=str, ensure_ascii=False))
            else:
                _display_summary_panel(summary, public, palette, use_cache_value, collection, console)

    except PartialIndexingError as e:
        if json_output:
            error_output = {"error": "PartialIndexingError", "message": e, "summary": e.summary}
            console.print(json.dumps(error_output, indent=2, default=str, ensure_ascii=False))
        else:
            console.print(f"[{palette.get('error', 'bold red')}]Strict Mode Failed:[/] {e}")
            summary = e.summary
            if summary and (summary.get("failed", 0) > 0 or summary.get("errors") or summary.get("failures")):
                failed_table = Table(title="Strict Integrity Failures", expand=True, header_style=palette.get("table_header", "bold"), style="red")
                failed_table.add_column("Error Detail", style="red")
                if "failures" in summary:
                    for failure in summary["failures"]: failed_table.add_row(escape(str(failure)))
                elif "errors" in summary:
                    for error in summary["errors"]:
                        msg = error.get("message") if isinstance(error, dict) else str(error)
                        failed_table.add_row(escape(str(msg)))
                console.print(failed_table)
        exit_cli(code=EXIT_CODE_ERROR, message="Directory push failed strict integrity check.")

    except typer.Exit:
        raise
    except (DorsalOfflineError, AuthError):
        raise
    except DorsalError as err:
        exit_cli(code=EXIT_CODE_ERROR, message=str(err))
    except Exception as err:
        logger.exception("An unexpected error occurred in 'dir push'")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {err}")





def _display_dry_run_panel(collection, use_cache, palette, console):
    from dorsal.file.utils.size import human_filesize

    files_from_cache = sum(1 for f in collection if f._source == "cache") if use_cache else 0
    cache_info_str = f" ({files_from_cache} from cache)" if files_from_cache > 0 else ""

    console.print(Panel(f"DRY RUN MODE: Would push {len(collection)} files.", border_style=palette.get("panel_border_warning", "yellow")))
    console.print(f"🔎 Found {len(collection)} file(s) that would be pushed{cache_info_str}:")
    
    scan_table = Table(box=box.ROUNDED, header_style=palette.get("table_header", "bold"))
    scan_table.add_column("Filename", style=palette.get("primary_value", "cyan"), no_wrap=True)
    scan_table.add_column("Size")
    scan_table.add_column("Media Type")
    scan_table.add_column("Source", justify="center")
    
    for file in collection:
        source_text, source_style = ("Cache", palette.get("success", "green")) if file._source == "cache" else ("Disk", palette.get("key", "dim"))
        scan_table.add_row(file.name, human_filesize(file.size), file.media_type, f"[{source_style}]{source_text}[/]")
    console.print(scan_table)


def _display_summary_panel(summary, public, palette, use_cache, collection, console):
    files_from_cache = sum(1 for f in collection if f._source == "cache") if use_cache else 0
    access_level_str, access_level_style = ("Public", palette.get("access_public", "default")) if public else ("Private", palette.get("access_private", "default"))

    summary_table = Table.grid(expand=True)
    summary_table.add_column(justify="right", style=palette.get("key", "dim"), width=25)
    summary_table.add_column(justify="left")
    summary_table.add_row("Access Level:", Text(access_level_str, style=access_level_style))
    summary_table.add_row("Files Scanned:", f"{summary.get('total_records', 0)} ({files_from_cache} from cache)")
    summary_table.add_row("File Records Accepted:", Text(str(summary.get("success", 0)), style=palette.get("success", "green")))

    batches = summary.get("batches", [])
    if len(batches) > 1:
        successful_batches = sum(1 for b in batches if b["status"] == "success")
        summary_table.add_row()
        summary_table.add_row("Batches Created:", str(len(batches)))
        summary_table.add_row("Successful Batches:", Text(str(successful_batches), style=palette.get("success", "green")))
        if failed_batches := len(batches) - successful_batches:
            summary_table.add_row("Failed Batches:", Text(str(failed_batches), style=palette.get("error", "red")))

    console.print(Panel(summary_table, title=f"[{palette.get('panel_title_success', 'bold green')}]Push Complete[/]", expand=False, border_style=palette.get("panel_border_success", "green")))

    if summary.get("failed", 0) > 0 or summary.get("errors"):
        console.print(f"\n[{palette.get('error', 'red')}]⚠️ Some batches failed to process:[/]")
        failed_table = Table(title="Failed Batch Details", expand=True, header_style=palette.get("table_header", "bold"))
        failed_table.add_column("Batch #", style=palette.get("primary_value", "cyan"), ratio=15)
        failed_table.add_column("Error Type", style=palette.get("warning", "yellow"), ratio=25)
        failed_table.add_column("Error Message", ratio=60)

        for error in summary.get("errors", []):
            failed_table.add_row(str(error.get("batch_index", "?")), error.get("error_type", "Unknown"), error.get("error_message", "No message"))
        console.print(failed_table)