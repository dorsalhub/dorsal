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

import logging
import pathlib
import typer
from typing import Annotated, Any, TYPE_CHECKING, cast

from rich.text import Text
from rich.markup import escape

from dorsal.common.constants import API_MAX_BATCH_SIZE
from dorsal.common.cli import (
    EXIT_CODE_ERROR,
    get_rich_console,
    determine_use_cache_value,
    exit_cli,
    get_error_console,
    print_json_output,
    print_raw_output,
)
from dorsal.common.exceptions import (
    DorsalClientError,
    DorsalOfflineError,
    AuthError,
    PartialIndexingError,
    DorsalError,
)

if TYPE_CHECKING:
    from dorsal.cli.themes import UIContext
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
        ),
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
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="[Dir Only] Bypass API limits and upload oversized files individually.",
            rich_help_panel="Directory Push Options",
        ),
    ] = False,
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
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]

    if use_cache and skip_cache:
        exit_cli(code=EXIT_CODE_ERROR, message="Error: --use-cache and --skip-cache flags cannot be used together.")
    if skip_cache and overwrite_cache:
        exit_cli(
            code=EXIT_CODE_ERROR, message="Error: --skip-cache and --overwrite-cache flags cannot be used together."
        )

    use_cache_value = determine_use_cache_value(use_cache=use_cache, skip_cache=skip_cache)

    if path.is_file():
        dir_flags_used = any(
            [
                recursive,
                create_collection,
                collection_name,
                collection_desc,
                dry_run,
                ignore_duplicates,
                not fail_fast,
                lazy,
            ]
        )
        if dir_flags_used:
            get_error_console().print(
                f"[{palette.get('warning', 'yellow')}]Warning:[/] Directory-specific push flags are ignored when pushing a single file."
            )

        _process_file_push(
            ctx=ctx,
            path=path,
            use_cache_value=use_cache_value,
            overwrite_cache=overwrite_cache,
            public=public,
            strict=strict,
            json_output=json_output,
            resolve_links=resolve_links,
            ui_context=ui_context,
            console=console,
        )
    else:
        _process_dir_push(
            ctx=ctx,
            path=path,
            use_cache_value=use_cache_value,
            overwrite_cache=overwrite_cache,
            public=public,
            strict=strict,
            json_output=json_output,
            resolve_links=resolve_links,
            recursive=recursive,
            create_collection=create_collection,
            collection_name=collection_name,
            collection_desc=collection_desc,
            dry_run=dry_run,
            ignore_duplicates=ignore_duplicates,
            fail_fast=fail_fast,
            force=force,
            lazy=lazy,
            ui_context=ui_context,
            console=console,
        )


def _process_file_push(
    ctx, path, use_cache_value, overwrite_cache, public, strict, json_output, resolve_links, ui_context, console
) -> None:
    error_console = get_error_console()
    from rich.console import Group

    from dorsal.cli.views.layout import key_values, message, section
    from dorsal.file.dorsal_file import LocalFile

    palette = ui_context["palette"]
    icons = ui_context.get("icons", {})
    access_level_str = "public" if public else "private"

    try:
        with error_console.status(
            f"Preparing to push metadata for [{palette.get('primary_value', 'cyan')}]{escape(path.name)}[/] as a {access_level_str} record"
        ):
            local_file = LocalFile(
                file_path=str(path),
                use_cache=use_cache_value,
                overwrite_cache=overwrite_cache,
                follow_symlinks=resolve_links,
            )

        logger.debug("Record to push: %s", local_file.model_dump_json(exclude_none=True, by_alias=True))

        with error_console.status("Pushing to DorsalHub..."):
            api_response = local_file.push(public=public, strict=strict)

        if json_output:
            print_json_output(api_response.model_dump(mode="json"), console)
            exit_cli()

        if api_response.results and api_response.success > 0:
            pushed_hash = api_response.results[0].hash
            details = key_values(ui_context)
            details.add("SHA-256", str(pushed_hash), style=palette.get("hash_value", "magenta"))
            details.add(
                "Access",
                Text(
                    access_level_str.capitalize(),
                    style=palette.get(f"access_{access_level_str}", "default"),
                ),
            )
            body = Group(
                Text("The file record was successfully pushed to DorsalHub.", style=palette.get("success", "green")),
                details,
            )
            console.print(
                section(
                    f"{icons.get('success', '')}Push complete",
                    body,
                    ui_context,
                    title_style=palette.get("panel_title_success", "bold green"),
                    border_style=palette.get("panel_border_success", "green"),
                )
            )
        else:
            detail: str | None = "Unknown"
            if api_response.results and hasattr(api_response.results[0], "detail"):
                if api_response.results[0].annotations:
                    detail = api_response.results[0].annotations[0].detail

            failure_text = Text(f"The file could not be pushed to DorsalHub.\nReason: {detail}")
            console.print(message(f"{icons.get('error', '')}Push failed", failure_text, ui_context, level="error"))

    except PartialIndexingError as e:
        if json_output:
            error_payload = {"error": "PartialIndexingError", "message": str(e), "summary": e.summary}
            print_json_output(error_payload, error_console)
        else:
            error_console.print(f"[{palette.get('error', 'bold red')}]Strict Mode Error:[/] {e}")
            if e.summary and "failures" in e.summary:
                error_console.print(f"[{palette.get('warning', 'yellow')}]Failures detected:[/]")
                for failure in e.summary["failures"]:
                    error_console.print(f"  - {failure}")
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


def _process_dir_push(
    ctx,
    path,
    use_cache_value,
    overwrite_cache,
    public,
    strict,
    json_output,
    resolve_links,
    recursive,
    create_collection,
    collection_name,
    collection_desc,
    dry_run,
    ignore_duplicates,
    fail_fast,
    lazy,
    force,
    ui_context,
    console,
) -> None:
    error_console = get_error_console()
    from rich.console import Group

    from dorsal.common.exceptions import ExceedsApiLimitError
    from dorsal.cli.views.layout import key_values, message, section, table
    from dorsal.file.collection.local import LocalFileCollection
    from dorsal.file.dorsal_file import LocalFile

    palette = ui_context["palette"]
    icons = ui_context.get("icons", {})
    progress_console = get_error_console() if json_output else console

    if create_collection and not collection_name:
        collection_name = path.name
        if not json_output:
            error_console.print(
                f"[{palette.get('info', 'dim')}]--name not provided. Defaulting to directory name: '[bold]{escape(str(collection_name))}[/]'[/]"
            )

    if not json_output:
        action_verb = "publish" if create_collection else "push"
        error_console.print(
            f"Preparing to {action_verb} metadata from [{palette.get('primary_value', 'cyan')}]{escape(str(path))}[/]",
            soft_wrap=True,
        )

    try:
        collection = LocalFileCollection(
            source=str(path),
            recursive=recursive,
            console=progress_console,
            palette=palette,
            use_cache=use_cache_value,
            overwrite_cache=overwrite_cache,
            follow_symlinks=resolve_links,
            lazy=lazy,
        )

        if not collection:
            exit_cli(message=f"No valid files found in '{escape(str(path))}'.")

        duplicate_groups = _find_duplicate_groups(collection)
        if ignore_duplicates:
            if duplicate_groups:
                skipped = {file_path for _, paths in duplicate_groups for file_path in paths[1:]}
                unique_files = [f for f in collection if f.file_path not in skipped]
                collection = LocalFileCollection(source=cast(list[LocalFile], unique_files), use_cache=use_cache_value)
                if not json_output:
                    error_console.print(f"[{palette.get('info', 'dim')}]Ignoring {len(skipped)} duplicate files.[/]")
        elif duplicate_groups and not dry_run:
            _report_duplicate_files(path, duplicate_groups, json_output, ui_context, error_console)
            exit_cli(code=EXIT_CODE_ERROR)

        if dry_run:
            _display_dry_run_panel(
                collection=collection, use_cache=use_cache_value, ui_context=ui_context, console=console
            )
            exit_cli()

        if create_collection and len(collection.files) > API_MAX_BATCH_SIZE:
            logger.warning(
                f"Directory too large to create a collection via the CLI (limit: {API_MAX_BATCH_SIZE}). Instead, use the `LocalFileCollection` directly."
            )
            create_collection = False

        elif create_collection:
            if collection_name is None:
                exit_cli(code=EXIT_CODE_ERROR, message="Internal Error: Collection name was not set before creation.")

            remote_collection = collection.create_remote_collection(
                name=collection_name, description=collection_desc, public=public
            )

            if json_output:
                print_raw_output(
                    remote_collection.metadata.model_dump_json(indent=2, by_alias=True, exclude_none=True), console
                )
            else:
                url = str(remote_collection.metadata.private_url)
                details = key_values(ui_context)
                details.add("URL", Text(url, style=f"{palette.get('link', 'underline')} link {url}"))
                body = Group(Text(f"Successfully pushed {len(collection)} files and created collection."), details)
                console.print(
                    section(
                        f"{icons.get('success', '')}Publish complete",
                        body,
                        ui_context,
                        title_style=palette.get("panel_title_success", "bold green"),
                        border_style=palette.get("panel_border_success", "green"),
                    )
                )

        if not create_collection:
            summary = collection.push(
                public=public,
                console=progress_console,
                palette=palette,
                fail_fast=fail_fast,
                strict=strict,
                include_oversized=force,
            )

            is_duplicate_error = False
            if summary.get("failed", 0) > 0:
                for detail in summary.get("errors", []):
                    if "Cannot process duplicate files" in detail.get("error_message", ""):
                        is_duplicate_error = True
                        break

            if is_duplicate_error:
                if json_output:
                    print_json_output(summary, console)
                else:
                    _report_duplicate_files(path, None, json_output, ui_context, error_console)
                exit_cli(code=EXIT_CODE_ERROR)

            if json_output:
                print_json_output(summary, console)
            else:
                _display_summary_panel(summary, public, ui_context, use_cache_value, collection, console)

    except ExceedsApiLimitError as e:
        if json_output:
            error_output = {"error": "ExceedsApiLimitError", "message": str(e), "excess": e.excess}
            print_json_output(error_output, error_console)
        else:
            from dorsal.file.utils.size import human_filesize

            error_text = Text.from_markup(
                f"[bold]Push failed: {len(e.excess)} file(s) exceed the API batch size limit.[/]\n"
                "To push this directory anyway, run the command with the [bold]--force[/] flag.\n\n"
                f"[{palette.get('warning', 'yellow')}]Oversized records:[/]"
            )

            for item in e.excess[:5]:
                error_text.append(f"\n- {item['path']} ({human_filesize(item['size'])})")
            if len(e.excess) > 5:
                error_text.append(f"\n… and {len(e.excess) - 5} more.")

            error_console.print(message(f"{icons.get('error', '')}Check failed", error_text, ui_context, level="error"))
        exit_cli(code=EXIT_CODE_ERROR)

    except PartialIndexingError as e:
        if json_output:
            partial_error_output: dict[str, Any] = {
                "error": "PartialIndexingError",
                "message": str(e),
                "summary": e.summary,
            }
            print_json_output(partial_error_output, error_console)
        else:
            error_console.print(f"[{palette.get('error', 'bold red')}]Strict Mode Failed:[/] {e}")
            summary = e.summary
            if summary and (summary.get("failed", 0) > 0 or summary.get("errors") or summary.get("failures")):
                failed_table = table(ui_context, title="Strict integrity failures")

                failed_table.add_column("Error detail", style=palette.get("error", "red"))
                if "failures" in summary:
                    for failure in summary["failures"]:
                        failed_table.add_row(escape(str(failure)))
                elif "errors" in summary:
                    for error in summary["errors"]:
                        msg = error.get("message") if isinstance(error, dict) else str(error)
                        failed_table.add_row(escape(str(msg)))
                error_console.print(failed_table)
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


def _find_duplicate_groups(collection) -> list[tuple[str, list[str]]]:
    """Groups files that share a content hash, as `(hash, [paths...])` in scan order. Files without a hash are skipped."""
    by_hash: dict[str, list[str]] = {}
    for f in collection:
        if f.hash:
            by_hash.setdefault(f.hash, []).append(f.file_path)
    return [(file_hash, paths) for file_hash, paths in by_hash.items() if len(paths) > 1]


def _report_duplicate_files(path, duplicate_groups, json_output, ui_context, error_console) -> None:
    """Prints the duplicate-files error to stderr: JSON with `json_output`, otherwise a panel with the fixes."""
    from dorsal.cli.views.layout import message

    palette = ui_context["palette"]
    icons = ui_context.get("icons", {})

    if json_output:
        error_payload: dict[str, Any] = {
            "success": False,
            "error": "Duplicate Files",
            "detail": "The directory contains files with identical content. Use --ignore-duplicates to push the "
            "first file of each duplicate set.",
        }
        if duplicate_groups:
            error_payload["duplicates"] = [{"hash": h, "paths": paths} for h, paths in duplicate_groups]
        print_json_output(error_payload, error_console)
        return

    command_color = palette.get("primary_value", "default")
    error_text = Text.from_markup("[bold]Push failed because the directory contains duplicate files.[/]\n")
    if duplicate_groups:
        max_groups = 5
        for _, paths in duplicate_groups[:max_groups]:
            error_text.append("\n" + " = ".join(pathlib.Path(p).name for p in paths))
        if len(duplicate_groups) > max_groups:
            error_text.append(f"\n… and {len(duplicate_groups) - max_groups} more duplicate sets.")
        error_text.append("\n")
    error_text.append_text(
        Text.from_markup(
            "\nTo get a summary of the duplicate files, run:\n"
            f'[bold {command_color}]dorsal local duplicates "{escape(str(path))}"[/]\n\n'
            "To push this directory anyway (the first of each duplicate will be indexed), run:\n"
            f'[bold {command_color}]dorsal local push "{escape(str(path))}" --ignore-duplicates[/]'
        )
    )
    error_console.print(
        message(f"{icons.get('error', '')}Duplicate files detected", error_text, ui_context, level="error")
    )


def _display_dry_run_panel(collection, use_cache, ui_context, console) -> None:
    from dorsal.cli.views.layout import message, table
    from dorsal.file.utils.size import human_filesize

    palette = ui_context["palette"]

    files_from_cache = sum(1 for f in collection if f._source == "cache") if use_cache else 0
    cache_info_str = f" ({files_from_cache} from cache)" if files_from_cache > 0 else ""

    console.print(
        message(
            "Dry run",
            f"Would push {len(collection)} file(s){cache_info_str}.",
            ui_context,
            level="warning",
            padding=(0, 1),
        )
    )
    console.print()

    scan_table = table(ui_context)
    scan_table.add_column("Filename", style=palette.get("primary_value", "cyan"), no_wrap=True)
    scan_table.add_column("Size", justify="right")
    scan_table.add_column("Media type")
    scan_table.add_column("Source")

    for file in collection:
        source_text, source_style = (
            ("Cache", palette.get("success", "green"))
            if file._source == "cache"
            else ("Disk", palette.get("key", "dim"))
        )
        scan_table.add_row(
            Text(file.name), human_filesize(file.size), file.media_type, Text(source_text, style=source_style)
        )
    console.print(scan_table)


def _display_summary_panel(summary, public, ui_context, use_cache, collection, console):
    from dorsal.cli.views.layout import key_values, section, table

    error_console = get_error_console()
    palette = ui_context["palette"]
    icons = ui_context.get("icons", {})
    success_style = palette.get("success", "green")
    error_style = palette.get("error", "red")

    files_from_cache = sum(1 for f in collection if f._source == "cache") if use_cache else 0
    access_level_str, access_level_style = (
        ("Public", palette.get("access_public", "default"))
        if public
        else ("Private", palette.get("access_private", "default"))
    )

    details = key_values(ui_context)
    details.add("Access level", Text(access_level_str, style=access_level_style))
    details.add("Files scanned", f"{summary.get('total_records', 0)} ({files_from_cache} from cache)")
    details.add("File records accepted", str(summary.get("success", 0)), style=success_style)

    batches = summary.get("batches", [])
    if len(batches) > 1:
        successful_batches = sum(1 for b in batches if b["status"] == "success")
        details.add("Batches created", str(len(batches)))
        details.add("Successful batches", str(successful_batches), style=success_style)
        if failed_batches := len(batches) - successful_batches:
            details.add("Failed batches", str(failed_batches), style=error_style)

    oversized = summary.get("oversized_records", [])
    if oversized:
        oversized_kv = details.section("Oversized file records", str(len(oversized)))

        successful_oversized = sum(1 for r in oversized if r.get("status") == "success")
        if successful_oversized:
            oversized_kv.add("Successful", str(successful_oversized), style=success_style)

        failed_oversized = sum(1 for r in oversized if r.get("status") in ("failure", "partial_failure"))
        if failed_oversized:
            oversized_kv.add("Failed/partial", str(failed_oversized), style=error_style)

    console.print(
        section(
            f"{icons.get('success', '')}Push complete",
            details,
            ui_context,
            title_style=palette.get("panel_title_success", "bold green"),
            border_style=palette.get("panel_border_success", "green"),
        )
    )

    if summary.get("failed", 0) > 0 or summary.get("errors"):
        error_console.print()
        error_console.print(f"[{error_style}]{icons.get('warning', '')}Some batches failed to process:[/]")
        failed_table = table(ui_context, title="Failed batch details", expand=True)
        failed_table.add_column("Batch #", style=palette.get("primary_value", "cyan"), ratio=15)
        failed_table.add_column("Error type", style=palette.get("warning", "yellow"), ratio=25)
        failed_table.add_column("Error message", ratio=60)

        for error in summary.get("errors", []):
            failed_table.add_row(
                str(error.get("batch_index", "?")),
                Text(str(error.get("error_type", "Unknown"))),
                Text(str(error.get("error_message", "No message"))),
            )
        error_console.print(failed_table)
