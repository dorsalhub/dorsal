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
from typing import Annotated, Optional, List

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
            help="The target Dorsal schema ID to parse into (e.g., 'open/audio-transcription').",
        ),
    ],
    format: Annotated[
        str,
        typer.Argument(
            help="The format of the source file (e.g., 'srt', 'vtt', 'txt').",
        ),
    ],
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
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_rich_console, get_error_console, parse_cli_options
    from dorsal.common.exceptions import DorsalError
    from dorsal.api.adapters import parse_file

    console = get_rich_console()
    error_console = get_error_console()
    palette: dict[str, str] = ctx.obj.get("palette", {}) if ctx.obj else {}

    parsed_options = parse_cli_options(options=options, palette=palette)

    # 1. Parse the File
    try:
        # We pass the file stream directly; parse_file smartly routes it
        with open(file_path, "r", encoding="utf-8") as fp:
            record_dict = parse_file(content=fp, schema_id=schema_id, source_format=format, **parsed_options)
    except DorsalError as e:
        error_console.print(f"[{palette.get('error', 'bold red')}]Parse Failed:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)
    except Exception as e:
        logger.exception("Unexpected error during parsing.")
        error_console.print(f"[{palette.get('error', 'bold red')}]Unexpected Error:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)

    # 2. Construct Dorsal Payload Wrapper
    final_payload = {
        "schema_id": schema_id,
        "file_path": str(file_path.resolve()),
        "record": record_dict,
    }

    # 3. Auto-Save Logic
    out_dir = output_path if output_path and output_path.is_dir() else pathlib.Path.cwd()
    save_path = output_path if output_path and not output_path.is_dir() else out_dir / f"{file_path.stem}.dorsal.json"

    saved_path_msg = None
    if not no_save:
        try:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(json.dumps(final_payload, indent=2, ensure_ascii=False), encoding="utf-8")
            saved_path_msg = str(save_path.resolve())
        except Exception as e:
            error_console.print(f"\n[{palette.get('error', 'bold red')}]Failed to write output file:[/] {e}")
            exit_cli(code=EXIT_CODE_ERROR)

    # 4. Output to Terminal
    console.print(json.dumps(final_payload, indent=2, ensure_ascii=False))

    if not no_save and saved_path_msg:
        error_console.print(
            f"\n[{palette.get('info', 'dim')}]Parsed record saved successfully:\n  ↳ {saved_path_msg}[/]"
        )
