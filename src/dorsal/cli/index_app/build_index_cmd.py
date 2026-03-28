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
import logging
import typer
import pathlib
from typing import Annotated

logger = logging.getLogger(__name__)


def build_search_index(
    ctx: typer.Context,
    path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            help="The directory path to scan and populate the search index with.",
        ),
    ],
    recursive: Annotated[
        bool,
        typer.Option(
            "--recursive/--no-recursive",
            "-r/-R",
            help="Scan subdirectories recursively.",
        ),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            "-f",
            help="Force re-processing and re-indexing of all files, even if they are already in the search index.",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the summary as a raw JSON object."),
    ] = False,
    resolve_links: Annotated[
        bool,
        typer.Option(
            "--follow-links/--no-follow-links",
            help="Follow symlinks to index target content vs indexing the link itself.",
        ),
    ] = True,
    lazy: Annotated[
        bool,
        typer.Option(
            "--lazy",
            help="Start processing immediately with an indeterminate progress bar.",
        ),
    ] = False,
):
    """
    Scans a directory and populates the search index with full metadata records.

    This command ensures that subsequent operations (like 'scan' or 'duplicates')
    on the same directory will be significantly faster by pre-populating the search index.
    """
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.file.collection.local import LocalFileCollection

    console = get_rich_console()

    palette = ctx.obj["palette"]
    progress_console = None if json_output else console

    try:
        if force:
            status_message = f"Force-building search index for '{path}' (re-processing all files)..."
            use_cache_value = False
        else:
            status_message = f"Building or updating search index for '{path}'..."
            use_cache_value = True

        if not json_output:
            with console.status(status_message):
                collection = LocalFileCollection(
                    source=str(path),
                    recursive=recursive,
                    console=progress_console,
                    palette=palette,
                    use_cache=use_cache_value,
                    follow_symlinks=resolve_links,
                    lazy=lazy,
                )
        else:
            collection = LocalFileCollection(
                source=str(path),
                recursive=recursive,
                console=progress_console,
                palette=palette,
                use_cache=use_cache_value,
                follow_symlinks=resolve_links,
            )

        collection_info = collection.info()
        source_breakdown = collection_info.get("by_source", [])
        files_from_index = 0
        files_from_disk = 0

        for source_stat in source_breakdown:
            if source_stat.get("source") == "cache":
                files_from_index = source_stat.get("count", 0)
            elif source_stat.get("source") == "disk":
                files_from_disk = source_stat.get("count", 0)

        if json_output:
            result = {
                "success": True,
                "total_files_processed": len(collection),
                "loaded_from_index": files_from_index,
                "newly_added_to_index": files_from_disk,
            }
            console.print(json.dumps(result, indent=2))
            exit_cli()

        console.print(f"[{palette.get('success', 'green')}]✅ Search Index updated successfully.[/]")
        console.print(f"   - Total files processed: {len(collection)}")
        console.print(f"   - Loaded from index: {files_from_index}")
        console.print(f"   - Newly added to index: {files_from_disk}")

    except typer.Exit:
        raise
    except Exception as err:
        logger.exception("Failed to build search index.")
        exit_cli(
            code=EXIT_CODE_ERROR,
            message=f"An error occurred while building the index: {err}",
        )
