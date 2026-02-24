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
    format: Annotated[
        str,
        typer.Argument(
            help="The target format to export to (e.g., 'srt', 'vtt', 'md').",
        ),
    ],
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
    from rich.table import Table

    console = get_rich_console()
    error_console = get_error_console()
    palette: dict[str, str] = ctx.obj.get("palette", {})

    # 1. Read JSON
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        error_console.print(f"[{palette.get('error', 'bold red')}]Invalid JSON file:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)

    # 2. Extract Schema and Records
    try:
        records_to_process = extract_records(data, schema_override=schema_id)
    except ValueError as e:
        error_console.print(f"[{palette.get('error', 'bold red')}]Validation Error:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)

    # 3. Process via Adapters
    try:
        from dorsal_adapters.registry import get_adapter
    except ImportError:
        error_console.print(
            f"[{palette.get('error', 'bold red')}]Error:[/] 'dorsalhub-adapters' package is not installed."
        )
        exit_cli(code=EXIT_CODE_ERROR)

    is_batch = len(records_to_process) > 1
    export_files_to_save = []
    terminal_outputs = []
    results_data = []

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

        try:
            adapter = get_adapter(current_schema_id, format)
            exported_text = adapter.export(record)
            terminal_outputs.append(exported_text)

            # If user explicitly passed a single output file path and it's not a batch, use it.
            save_path = output_path if output_path and not is_batch else out_dir / f"{base_name}.{format}"

            export_files_to_save.append((save_path, exported_text))

            results_data.append({"input_name": input_name, "status": "Success", "output_name": save_path.name})
        except Exception as e:
            logger.exception("Adapter export failed.")
            results_data.append({"input_name": input_name, "status": "Error", "error": str(e)})
            if not is_batch:
                error_console.print(
                    f"[{palette.get('error', 'bold red')}]Export Failed for schema '{current_schema_id}':[/] {e}"
                )
                exit_cli(code=EXIT_CODE_ERROR)

    # 4. Auto-Save Logic
    saved_paths_msg = []
    if not no_save:
        for path, text in export_files_to_save:
            try:
                path.write_text(text, encoding="utf-8")
                saved_paths_msg.append(str(path.resolve()))
            except Exception as e:
                error_console.print(f"\n[{palette.get('error', 'bold red')}]Failed to write output file:[/] {e}")
                exit_cli(code=EXIT_CODE_ERROR)

    # 5. Output to Terminal
    if not is_batch:
        # For single files, print to stdout so users can pipe the result
        console.print(terminal_outputs[0], end="")
        if not no_save and saved_paths_msg:
            error_console.print(
                f"\n[{palette.get('info', 'dim')}]Outputs saved successfully:\n  ↳ {saved_paths_msg[0]}[/]"
            )
    else:
        # For batches, render the summary table instead of printing a giant text block
        table = Table(
            title=f"[{palette.get('panel_title', 'bold')}]Export Results: {file_path.name}[/]",
            header_style=palette.get("table_header", "bold blue"),
        )
        table.add_column("Input File")
        table.add_column("Status")

        if not no_save:
            table.add_column(f"{format.upper()} Output")

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
