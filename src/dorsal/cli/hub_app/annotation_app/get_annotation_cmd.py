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

import pathlib
import logging
import json
from typing import Annotated, Optional

import typer

from dorsal.cli.themes import UIContext

logger = logging.getLogger(__name__)


def get_annotation(
    ctx: typer.Context,
    annotation_id: Annotated[str, typer.Argument(help="The UUID of the annotation to hydrate.")],
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output the raw result as JSON to stdout. Mutes terminal UI panels.",
            rich_help_panel="Output Options",
        ),
    ] = False,
    export_format: Annotated[
        Optional[str],
        typer.Option(
            "--export",
            "-e",
            help="Export the result to a specific format (e.g., 'csl', 'vtt', 'md'). Outputs raw text to stdout.",
            rich_help_panel="Output Options",
        ),
    ] = None,
    export_options: Annotated[
        Optional[list[str]],
        typer.Option(
            "--export-opt",
            help="Export options in 'key=value' format. Can be used multiple times.",
            rich_help_panel="Output Options",
        ),
    ] = None,
    output_path: Annotated[
        Optional[pathlib.Path],
        typer.Option(
            "--output",
            "-o",
            help="Optional file or directory path to save the fetched result.",
            rich_help_panel="Output Options",
        ),
    ] = None,
):
    """
    Hydrate and view a specific annotation.
    """
    if json_output and export_format:
        raise typer.BadParameter("You cannot use --json and --export at the same time for standard output.")

    from dorsal.api.file import get_file_annotation
    from dorsal.common.cli import (
        DummyContext,
        EXIT_CODE_ERROR,
        exit_cli,
        get_rich_console,
        get_error_console,
        parse_cli_options,
    )
    from dorsal.common.exceptions import NotFoundError, DorsalClientError
    from dorsal.cli.views.model import create_model_result_panel
    from dorsal.api.adapters import export_record, get_format_extension

    console = get_rich_console()
    error_console = get_error_console()

    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]

    parsed_export_options = parse_cli_options(options=export_options, palette=palette) if export_options else {}

    is_stdout_raw = (json_output or export_format) and not output_path

    try:
        with (
            DummyContext()
            if is_stdout_raw
            else console.status(f"[{palette.get('info', 'dim')}]Downloading annotation...[/]")
        ):
            if json_output:
                data_str = get_file_annotation(annotation_id, mode="json")
                schema_id = "Annotation"
            else:
                hydrated = get_file_annotation(annotation_id, mode="pydantic")
                schema_id = getattr(hydrated, "schema_id", "Annotation")

        if export_format:
            record_dict = getattr(hydrated, "record", {})
            if not record_dict and hasattr(hydrated, "model_dump"):
                record_dict = hydrated.model_dump().get("record", {})

            if not record_dict:
                raise ValueError("No record data found in this annotation to export.")

            data_str = export_record(
                record=record_dict,
                schema_id=schema_id,
                target_format=export_format,
                **parsed_export_options,
            )

        if output_path:
            out_dir = output_path if output_path.is_dir() else output_path.parent
            out_dir.mkdir(parents=True, exist_ok=True)

            if output_path.is_dir():
                if export_format:
                    ext = get_format_extension(schema_id, export_format)
                    save_path = output_path / f"{annotation_id}.{ext}"
                else:
                    save_path = output_path / f"{annotation_id}.json"
            else:
                save_path = output_path

            if not (json_output or export_format):
                dump_dict = hydrated.model_dump(exclude_none=True) if hasattr(hydrated, "model_dump") else {}
                data_str = json.dumps(dump_dict, indent=2, ensure_ascii=False)

            save_path.write_text(data_str, encoding="utf-8")
            error_console.print(
                f"[{palette.get('info', 'dim')}]Output saved successfully:\n  ↳ {save_path.resolve()}[/]"
            )

            if not (json_output or export_format):
                panel = create_model_result_panel(
                    result=hydrated, title=schema_id, file_name=f"ID: {annotation_id}", ui_context=ui_context
                )
                console.print(panel)

        else:
            if json_output or export_format:
                console.print(data_str, end="" if export_format else "\n")
            else:
                panel = create_model_result_panel(
                    result=hydrated, title=schema_id, file_name=f"ID: {annotation_id}", ui_context=ui_context
                )
                console.print(panel)

    except typer.Exit:
        raise
    except ValueError as e:
        if json_output or export_format:
            error_console.print(json.dumps({"success": False, "error": "Data Error", "detail": str(e)}))
        else:
            error_console.print(f"[{palette.get('warning', 'yellow')}]Data Error:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)
    except NotFoundError as e:
        if json_output or export_format:
            error_console.print(json.dumps({"success": False, "error": "Not Found", "detail": e.message}))
        else:
            error_console.print(f"[{palette.get('warning', 'yellow')}]Not Found:[/] {e.message}")
        exit_cli(code=EXIT_CODE_ERROR)
    except DorsalClientError as e:
        if json_output or export_format:
            error_console.print(json.dumps({"success": False, "error": "API Error", "detail": e.message}))
        else:
            error_console.print(f"[{palette.get('error', 'bold red')}]API Error:[/] {e.message}")
        exit_cli(code=EXIT_CODE_ERROR)
    except Exception as e:
        logger.exception("Unexpected error during annotation fetch")
        if json_output or export_format:
            error_console.print(json.dumps({"success": False, "error": "Unexpected Error", "detail": str(e)}))
        else:
            error_console.print(f"[{palette.get('error', 'bold red')}]Failed to get annotation:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)
