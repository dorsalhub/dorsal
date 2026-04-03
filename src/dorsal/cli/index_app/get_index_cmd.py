# Copyright 2026 Dorsal Hub LTD
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

import datetime
import json
import logging
import os
import pathlib
import string
from typing import Annotated, Optional

import typer

from dorsal.common import constants

logger = logging.getLogger(__name__)


def get_index_record(
    ctx: typer.Context,
    identifier: Annotated[
        str,
        typer.Argument(help="The absolute file path or SHA256 hash of the local record to retrieve."),
    ],
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output the record as a raw JSON object.",
            rich_help_panel="Output Options",
        ),
    ] = False,
    save: Annotated[
        bool,
        typer.Option(
            "-s",
            "--save",
            help="Save the JSON record to the default directory or --output path.",
            rich_help_panel="Output Options",
        ),
    ] = False,
    output_path: Annotated[
        Optional[pathlib.Path],
        typer.Option(
            "--output",
            "-o",
            help="Path to save the output JSON file.",
            dir_okay=True,
            file_okay=True,
            writable=True,
            resolve_path=True,
            rich_help_panel="Output Options",
        ),
    ] = None,
):
    """
    Retrieve and display a full file record from the local search index.
    """
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.api.search import search_local
    from dorsal.session import get_shared_index
    from dorsal.cli.views.file import create_file_info_panel

    console = get_rich_console()
    palette = ctx.obj["palette"]
    icons = ctx.obj["icons"]
    borders = ctx.obj["borders"]

    if output_path and not save:
        if str(output_path).lower().endswith(".json"):
            save = True
        else:
            if not output_path.is_dir():
                console.print(
                    f"Warning --output path '{output_path}' was specified with an unknown extension."
                    f" Please use -s (for .json) or specify a .json file.",
                    style=palette.get("warning", "yellow"),
                )

    index = get_shared_index()
    record = None

    if not json_output:
        console.print(
            f"Checking local index for record matching: [{palette.get('primary_value', 'cyan')}]{identifier}[/]"
        )

    if os.path.isabs(identifier) or os.path.exists(identifier):
        path_str = str(pathlib.Path(identifier).resolve())
        record = index.get_record(path=path_str)

    if not record and len(identifier) == 64 and all(c in string.hexdigits for c in identifier):
        results = search_local(f"sha256:{identifier}", index=index, limit=1)
        if results:
            record = results[0]

    if not record:
        console.print(
            f"\n[{palette.get('warning', 'yellow')}]Not Found:[/] No local records found."
        )
        if len(identifier) == 64:
            hub_cmd = f"dorsal hub get {identifier}"
            console.print(
                f"\n[{palette.get('info', 'dim')}]Tip: To search DorsalHub:[/] [{palette.get('primary_value', 'cyan')}]{hub_cmd}[/]"
            )
        exit_cli(code=EXIT_CODE_ERROR)

    try:
        record_dict = json.loads(record.record_json)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to decode cached record JSON: {e}")
        exit_cli(code=EXIT_CODE_ERROR, message="Corrupted record found in local index.")

    record_dict["hash"] = record.hash_sha256
    record_dict["validation_hash"] = record.hash_blake3
    record_dict["quick_hash"] = record.hash_quick
    record_dict["similarity_hash"] = record.hash_tlsh

    dt_mod = datetime.datetime.fromtimestamp(record.modified_time, tz=datetime.timezone.utc)
    record_dict["local_filesystem"] = {"full_path": record.abspath, "date_modified": dt_mod.isoformat()}

    record_json_str = json.dumps(record_dict, indent=2, ensure_ascii=False)

    if json_output:
        console.print(record_json_str)
        exit_cli()

    base_record = record_dict.get("annotations", {}).get("file/base", {})
    title = f"File Record: {record.name or 'Unknown'}"
    is_private = base_record.get("private", False)
    panel = create_file_info_panel(
        record_dict=record_dict,
        title=title,
        private=is_private,
        palette=palette,
        icons=icons,
        box_style=borders,
        source="cache",
    )

    console.print()
    console.print(panel)

    if save:
        _save_json_report(
            record_json_str=record_json_str,
            output_path=output_path,
            hash_string=record.hash_sha256 or "unknown_hash",
            palette=palette,
            json_to_stdout=json_output,
        )


def _get_final_path(hash_string: str, output_path: Optional[pathlib.Path], suffix: str) -> pathlib.Path:
    """Helper to determine the final save path for a report."""

    if output_path:
        if output_path.is_dir():
            return output_path / f"{hash_string}{suffix}"
        else:
            return output_path

    constants.CLI_GET_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return constants.CLI_GET_REPORTS_DIR / f"local-{hash_string}-{timestamp}{suffix}"


def _save_json_report(
    record_json_str: str,
    output_path: Optional[pathlib.Path],
    hash_string: str,
    palette: dict,
    json_to_stdout: bool,
):
    """Saves the fetched record to a JSON file."""
    from dorsal.common.cli import get_rich_console, EXIT_CODE_ERROR, exit_cli

    console = get_rich_console()

    final_path = _get_final_path(hash_string, output_path, ".json")

    try:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        with open(final_path, "w", encoding="utf-8") as fp:
            fp.write(record_json_str)

        if not json_to_stdout:
            console.print(f"\n✅ JSON record saved to: [{palette.get('primary_value')}]{final_path}[/]")
    except IOError as err:
        logger.error(f"Failed to save get report: {err}")
        exit_cli(code=EXIT_CODE_ERROR, message=f"Error writing to file: {err}")
    except Exception as e:
        logger.error(f"Failed to save JSON report: {e}")
        console.print(
            f"⚠️ Could not save JSON report to {final_path}. Error: {e}", style=palette.get("warning", "yellow")
        )
