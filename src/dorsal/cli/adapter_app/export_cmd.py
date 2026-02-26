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
from typing import Annotated, Optional

import typer

logger = logging.getLogger(__name__)


def export_adapter(
    ctx: typer.Context,
    file_path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
            help="Path to the Dorsal JSON output or raw record JSON.",
        ),
    ],
    target_format: Annotated[
        Optional[str],
        typer.Argument(
            help="The target format to export to (e.g., 'srt', 'vtt'). Optional if inferred from --output.",
        ),
    ] = None,
    schema_id: Annotated[
        Optional[str],
        typer.Option(
            "--schema-id",
            "-s",
            help="Explicitly pass the schema ID. Required if passing a raw record without a wrapper.",
        ),
    ] = None,
    output_path: Annotated[
        Optional[pathlib.Path],
        typer.Option(
            "--output",
            "-o",
            help="Custom output file/directory path. Overrides auto-save naming.",
        ),
    ] = None,
    no_save: Annotated[
        bool,
        typer.Option(
            "--no-save",
            help="Disable auto-saving results to disk (useful for read-only environments or pure piping).",
        ),
    ] = False,
):
    """
    Export a Dorsal JSON result into a different format using an adapter.
    """
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_rich_console, get_error_console
    from dorsal.cli.adapter_app.helpers import extract_records
    from dorsal.api.adapters import export_record, export_record_to_file, get_format_extension
    from rich.table import Table

    console = get_rich_console()
    error_console = get_error_console()
    palette: dict[str, str] = ctx.obj.get("palette", {}) if ctx.obj else {}

    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        error_console.print(f"[{palette.get('error', 'bold red')}]Invalid JSON file:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)

    try:
        records_to_process = extract_records(data, schema_override=schema_id)
    except ValueError as e:
        error_console.print(f"[{palette.get('error', 'bold red')}]Validation Error:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)

    resolved_format = target_format
    if not resolved_format:
        if output_path and not output_path.is_dir() and output_path.suffix:
            resolved_format = output_path.suffix.lstrip(".")
        else:
            error_console.print(
                f"[{palette.get('error', 'bold red')}]Usage Error:[/] You must provide a "
                "'target_format' argument (e.g., 'srt') unless an '--output' file path "
                "with an extension is provided."
            )
            exit_cli(code=EXIT_CODE_ERROR)

    is_batch = len(records_to_process) > 1
    terminal_outputs = []
    results_data = []
    saved_paths_msg = []

    out_dir = output_path if output_path and output_path.is_dir() else pathlib.Path.cwd()

    for i, (current_schema_id, record, orig_file_path) in enumerate(records_to_process):
        if orig_file_path:
            input_name = pathlib.Path(orig_file_path).name
            base_name = pathlib.Path(orig_file_path).stem
        else:
            input_name = f"Record {i + 1}"
            base_name = (
                file_path.name.replace(".dorsal.json", "")
                if file_path.name.endswith(".dorsal.json")
                else file_path.stem
            )
            if is_batch:
                base_name = f"{base_name}_{i + 1}"

        if output_path and not output_path.is_dir() and not is_batch:
            save_path = output_path
        else:
            ext = get_format_extension(current_schema_id, resolved_format)
            save_path = out_dir / f"{base_name}.{ext}"

        try:
            if no_save:
                exported_text = export_record(record, current_schema_id, target_format=resolved_format)
            else:
                exported_text = export_record_to_file(
                    record=record, output_path=save_path, schema_id=current_schema_id, target_format=resolved_format
                )
                saved_paths_msg.append(str(save_path.resolve()))

            terminal_outputs.append(exported_text)
            results_data.append(
                {"input_name": input_name, "status": "Success", "output_name": save_path.name if not no_save else "-"}
            )
        except Exception as e:
            logger.exception("Adapter export failed.")
            results_data.append({"input_name": input_name, "status": "Error", "error": str(e)})
            if not is_batch:
                error_console.print(
                    f"[{palette.get('error', 'bold red')}]Export Failed for schema '{current_schema_id}':[/] {e}"
                )
                exit_cli(code=EXIT_CODE_ERROR)

    if not is_batch:
        console.print(terminal_outputs[0], end="")
        if not no_save and saved_paths_msg:
            error_console.print(
                f"\n[{palette.get('info', 'dim')}]Outputs saved successfully:\n  ↳ {saved_paths_msg[0]}[/]"
            )
    else:
        table = Table(
            title=f"[{palette.get('panel_title', 'bold')}]Export Results: {file_path.name}[/]",
            header_style=palette.get("table_header", "bold blue"),
        )
        table.add_column("Input File")
        table.add_column("Status")

        if not no_save:
            table.add_column(f"{resolved_format.upper()} Output")

        for item in results_data:
            row = []
            if item["status"] == "Error":
                status_text = f"[{palette.get('error', 'bold red')}]Error: {item.get('error')}[/]"
                row.extend([item["input_name"], status_text])
                if not no_save:
                    row.append("-")
            else:
                status_text = f"[{palette.get('success', 'green')}]Success[/]"
                row.extend([item["input_name"], status_text])
                if not no_save:
                    row.append(f"[{palette.get('primary_value', 'cyan')}]{item['output_name']}[/]")

            table.add_row(*row)

        console.print(table)

        if not no_save and saved_paths_msg:
            error_console.print(f"\n[{palette.get('info', 'dim')}]Complete. Files saved to {out_dir.resolve()}[/]")
