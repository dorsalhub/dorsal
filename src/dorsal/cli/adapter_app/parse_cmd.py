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

import logging
import json
import pathlib
from typing import Annotated, Any, Optional, List

import typer

logger = logging.getLogger(__name__)


def parse_adapter(
    ctx: typer.Context,
    file_path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Path to the source file to parse (e.g., a .srt or .txt file).",
        ),
    ],
    schema_id: Annotated[
        str,
        typer.Argument(
            help="The schema to parse into (e.g., 'audio-transcription').",
        ),
    ],
    schema_version: Annotated[
        Optional[str],
        typer.Option(
            "--schema-version",
            help="The schema version to validate against. Defaults to the version this release of Dorsal uses.",
        ),
    ] = None,
    source_format: Annotated[
        Optional[str],
        typer.Option(
            "--format",
            "-f",
            help="The format of the source file (e.g., 'srt', 'vtt'). Inferred from extension if omitted.",
        ),
    ] = None,
    options: Annotated[
        Optional[List[str]],
        typer.Option(
            "--opt",
            "-o",
            help="Runtime options for the parser in 'key=value' format. Can be used multiple times.",
        ),
    ] = None,
    output_path: Annotated[
        Optional[pathlib.Path],
        typer.Option(
            "--output",
            "-out",
            help="Custom output file/directory path. Overrides auto-save naming.",
        ),
    ] = None,
    no_save: Annotated[
        bool,
        typer.Option(
            "--no-save",
            help="Disable auto-saving results to disk (useful for pure piping to stdout).",
        ),
    ] = False,
):
    """
    Parse a standard file format into a valid Dorsal JSON record using an adapter.
    """
    from dorsal.common.cli import (
        exit_cli,
        EXIT_CODE_ERROR,
        get_rich_console,
        get_error_console,
        parse_cli_options,
        print_json_output,
        warn_if_deprecated_schema_id,
    )
    from dorsal.common.constants import OPEN_VALIDATION_SCHEMAS_VER
    from dorsal.common.exceptions import DorsalError
    from dorsal.api.adapters import parse_file_from_path

    console = get_rich_console()
    error_console = get_error_console()
    palette: dict[str, str] = ctx.obj.get("palette", {}) if ctx.obj else {}

    warn_if_deprecated_schema_id(schema_id, palette)
    parsed_options = parse_cli_options(options=options, palette=palette)
    schema_version = parsed_options.pop("schema_version", None) or schema_version

    try:
        record_dict = parse_file_from_path(
            file_path=file_path,
            schema_id=schema_id,
            source_format=source_format,
            schema_version=schema_version,
            **parsed_options,
        )
    except DorsalError as e:
        error_console.print(f"[{palette.get('error', 'bold red')}]Parse failed:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)
    except Exception as e:
        logger.exception("Unexpected error during parsing.")
        error_console.print(f"[{palette.get('error', 'bold red')}]Unexpected error:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)

    from dorsal.file.schemas import open_schema_name

    final_payload: dict[str, Any] = {
        "schema_id": open_schema_name(schema_id) or schema_id,
        "file_path": str(file_path.resolve()),
        "record": record_dict,
    }
    if open_schema_name(schema_id) is not None:
        final_payload["schema_version"] = schema_version or OPEN_VALIDATION_SCHEMAS_VER

    out_dir = output_path if output_path and output_path.is_dir() else pathlib.Path.cwd()
    save_path = output_path if output_path and not output_path.is_dir() else out_dir / f"{file_path.stem}.dorsal.json"

    saved_path_msg = None
    if not no_save:
        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(json.dumps(final_payload, indent=2, ensure_ascii=False), encoding="utf-8")
            saved_path_msg = str(save_path.resolve())
        except Exception as e:
            error_console.print(f"[{palette.get('error', 'bold red')}]Failed to write output file:[/] {e}")
            exit_cli(code=EXIT_CODE_ERROR)

    print_json_output(final_payload, console)

    if not no_save and saved_path_msg:
        error_console.print(
            f"\n[{palette.get('info', 'dim')}]Parsed record saved successfully:\n  ↳ {saved_path_msg}[/]"
        )
