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
from typing import Annotated, Optional, List, Any

import typer

logger = logging.getLogger(__name__)


def run_model(
    ctx: typer.Context,
    target: Annotated[
        str,
        typer.Argument(help="The model identifier (e.g. 'dorsalhub/receipt-scanner' or 'ReceiptScanner')."),
    ],
    file_path: Annotated[
        pathlib.Path,
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=True,  # Supports directories for batch processing
            readable=True,
            resolve_path=True,
            help="Path to the file or directory to process.",
        ),
    ],
    options: Annotated[
        Optional[List[str]],
        typer.Option(
            "--opt",
            "-o",
            help="Runtime options in 'key=value' format. Can be used multiple times.",
            rich_help_panel="Model Configuration",
        ),
    ] = None,
    ignore_lint: Annotated[
        bool,
        typer.Option(
            "--ignore-lint",
            help="Bypass strict data quality checks and linter errors.",
            rich_help_panel="Model Configuration",
        ),
    ] = False,
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
            help="Export the result to a specific format (e.g., 'srt', 'vtt', 'md'). Outputs raw text to stdout.",
            rich_help_panel="Output Options",
        ),
    ] = None,
    max_length: Annotated[
        int,
        typer.Option(
            "--max-length",
            "-m",
            min=1,
            help="Maximum number of items/files to display in terminal tables and summaries.",
            rich_help_panel="Output Options",
        ),
    ] = 10,
    no_save: Annotated[
        bool,
        typer.Option(
            "--no-save",
            help="Disable auto-saving results to disk (useful for read-only environments).",
            rich_help_panel="Output Options",
        ),
    ] = False,
    output_path: Annotated[
        Optional[pathlib.Path],
        typer.Option(
            "--output",
            help="Custom output file/directory path. Overrides auto-save naming.",
            rich_help_panel="Output Options",
        ),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip the safety confirmation prompt if installation is required.")
    ] = False,
):
    """
    Run a model on a local file or directory.

    If the model is not installed locally, Dorsal will attempt to fetch
    and install it from the registry automatically.
    """
    if json_output and export_format:
        raise typer.BadParameter("You cannot use --json and --export at the same time for standard output.")

    from dorsal.common.exceptions import DorsalError, AuthError
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_rich_console, get_error_console
    from dorsal.api.model import run_or_install_model
    from dorsal.cli.views.model import create_model_result_panel
    from dorsal.registry.resolution import resolve_target, is_package_installed
    from dorsal.cli.model_app.checks import check_and_confirm_model_install
    from dorsal.file.validators.file_record import AnnotationGroup, Annotation
    from rich.table import Table
    from rich.progress import (
        Progress,
        SpinnerColumn,
        TextColumn,
        BarColumn,
        TaskProgressColumn,
        MofNCompleteColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
    )

    console = get_rich_console()
    error_console = get_error_console()
    palette: dict[str, str] = ctx.obj.get("palette", {})

    parsed_options = _parse_cli_options(options)

    # 1. Target Resolution & Installation
    if not (json_output or export_format):
        try:
            strategy, package_name = resolve_target(target)
            if not is_package_installed(package_name):
                check_and_confirm_model_install(target, palette, yes=yes)
        except typer.Exit:
            raise
        except Exception:
            pass

    # 2. Gather files for batch or single processing
    files_to_process = [f for f in file_path.iterdir() if f.is_file()] if file_path.is_dir() else [file_path]
    is_batch = len(files_to_process) > 1

    if not files_to_process:
        error_console.print(f"[{palette.get('error', 'bold red')}]Error:[/] No readable files found in target path.")
        exit_cli(code=EXIT_CODE_ERROR)

    if not (json_output or export_format):
        msg = f"Running model [{palette.get('primary_value', 'cyan')}]{target}[/] on "
        msg += (
            f"directory [{palette.get('primary_value', 'cyan')}]{file_path.name}/[/] ({len(files_to_process)} files)..."
            if is_batch
            else f"[{palette.get('primary_value', 'cyan')}]{file_path.name}[/]..."
        )
        error_console.print(msg)

    # 3. Execution Loop
    results_data = []
    raw_results: list[Annotation | AnnotationGroup | None] = []
    export_files_to_save = []
    out_dir = pathlib.Path.cwd()
    if output_path:
        if is_batch or output_path.is_dir() or not output_path.suffix:
            out_dir = output_path
        else:
            out_dir = output_path.parent

        out_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Progress bar configuration (transient=True so it disappears when done)
        with Progress(
            SpinnerColumn(),
            TextColumn(f"[{palette.get('info', 'dim')}]{{task.description}}"),
            BarColumn(complete_style=palette.get("success", "green")),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=error_console,
            transient=True,
        ) as progress:
            task = progress.add_task("Initializing...", total=len(files_to_process))

            for f in files_to_process:
                progress.update(task, description=f"Processing {f.name}...")
                try:
                    res: Annotation | AnnotationGroup = run_or_install_model(
                        target=target,
                        file_path=str(f),
                        options=parsed_options,
                        ignore_linter_errors=ignore_lint,
                    )

                    raw_results.append(res)
                    res_dict = res.model_dump(exclude_none=True)
                    res_dict = {"file_path": str(f), **res_dict}
                    results_data.append(res_dict)

                    if export_format:
                        try:
                            from dorsal_adapters.registry import get_adapter

                            if isinstance(res, AnnotationGroup):
                                from dorsal.file.sharding import reassemble_record

                                _, record_dict = reassemble_record(res)
                                schema_id = res.annotations[0].schema_id
                            else:
                                schema_id = res.schema_id
                                record_dict = res.record.model_dump(exclude_none=True) if res.record else {}

                            if not schema_id:
                                raise ValueError("Missing schema_id for export.")

                            adapter = get_adapter(schema_id, export_format)
                            exported_text = adapter.export(record_dict)

                            base_name = f.stem
                            save_path = (
                                output_path
                                if output_path and not is_batch
                                else out_dir / f"{base_name}.{export_format}"
                            )

                            export_files_to_save.append((save_path, exported_text))

                        except ImportError:
                            error_console.print(
                                f"[{palette.get('warning', 'yellow')}]Error:[/] 'dorsalhub-adapters' is required for exports."
                            )
                            exit_cli(code=EXIT_CODE_ERROR)
                        except ValueError as err:
                            error_console.print(
                                f"[{palette.get('warning', 'yellow')}]Export Error on {f.name}:[/] {err}"
                            )
                            res_dict["export_error"] = str(err)

                except (DorsalError, AuthError, typer.Exit):
                    raise

                except Exception as e:
                    logger.exception(f"Error processing {f.name}")
                    results_data.append({"file_path": str(f), "error": str(e)})
                    raw_results.append(None)

                progress.advance(task)

    except (DorsalError, AuthError) as e:
        if json_output:
            error_console.print(json.dumps({"error": str(e)}))
        else:
            error_console.print(f"[{palette.get('error', 'bold red')}]Run Failed:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)
    except typer.Exit:
        raise
    except Exception as e:
        logger.exception("Unexpected error during model run")
        if json_output:
            error_console.print(json.dumps({"error": "Unexpected internal error", "details": str(e)}))
        else:
            error_console.print(f"[{palette.get('error', 'bold red')}]Unexpected Error:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)

    final_json_data = {"results": results_data}

    # 4. Auto-Save Logic
    saved_paths_msg = []
    if not no_save:
        if output_path and not is_batch and not export_format:
            json_save_path = output_path
        else:
            base_name = file_path.name + "_batch" if is_batch else file_path.stem
            json_save_path = out_dir / f"{base_name}.dorsal.json"

        json_save_path.write_text(json.dumps(final_json_data, indent=2, ensure_ascii=False), encoding="utf-8")
        saved_paths_msg.append(str(json_save_path))

        if export_format:
            for path, text in export_files_to_save:
                path.write_text(text, encoding="utf-8")
                saved_paths_msg.append(str(path))

    # 5. Terminal Display Logic
    if export_format and not is_batch:
        for _, text in export_files_to_save:
            console.print(text, end="")
    elif json_output:
        console.print(json.dumps(final_json_data, indent=2, ensure_ascii=False))
    else:
        if is_batch:
            table = Table(
                title=f"[{palette.get('panel_title', 'bold')}]Results: {target}[/]",
                header_style=palette.get("table_header", "bold blue"),
            )
            table.add_column("Input File")
            table.add_column("Status")

            if not no_save:
                table.add_column("JSON Output")
                if export_format:
                    table.add_column(f"{export_format.upper()} Output")

            display_results = results_data[:max_length]
            hidden_count = len(results_data) - max_length

            for item in display_results:
                input_name = pathlib.Path(item["file_path"]).name
                base_name = pathlib.Path(item["file_path"]).stem
                row = []

                if "error" in item and item["error"]:
                    status_text = f"[{palette.get('error', 'bold red')}]Error: {item['error']}[/]"
                    row.extend([input_name, status_text])
                    if not no_save:
                        row.append("-")
                        if export_format:
                            row.append("-")
                else:
                    status_text = f"[{palette.get('success', 'green')}]Success[/]"
                    row.extend([input_name, status_text])
                    if not no_save:
                        json_path = out_dir / f"{base_name}.dorsal.json"
                        row.append(f"[{palette.get('primary_value', 'cyan')}]{json_path.name}[/]")

                        if export_format:
                            if item.get("export_error"):
                                row.append(f"[{palette.get('error', 'bold red')}]Failed[/]")
                            else:
                                exp_path = out_dir / f"{base_name}.{export_format}"
                                row.append(f"[{palette.get('primary_value', 'cyan')}]{exp_path.name}[/]")

                table.add_row(*row)

            if hidden_count > 0:
                trunc_msg = f"[{palette.get('info', 'dim')}]... and {hidden_count} more files[/]"
                empty_cols = [""] * (len(table.columns) - 1)
                table.add_row(trunc_msg, *empty_cols)

            console.print(table)
        else:
            first_res_dict = results_data[0]
            if "error" in first_res_dict and first_res_dict["error"] is not None:
                error_console.print(
                    f"[{palette.get('error', 'bold red')}]Error processing file: {first_res_dict['error']}[/]"
                )
            else:
                first_raw_result = raw_results[0]
                if first_raw_result is not None:
                    panel = create_model_result_panel(
                        result=first_raw_result,
                        title=target,
                        file_name=file_path.name,
                        palette=palette,
                        max_length=max_length,
                    )
                    console.print(panel)

    if not no_save and saved_paths_msg:
        if not is_batch:
            paths_formatted = "\n".join([f"  ↳ {p}" for p in saved_paths_msg])
            error_console.print(f"\n[{palette.get('info', 'dim')}]Outputs saved successfully:\n{paths_formatted}[/]")
        else:
            error_console.print(f"\n[{palette.get('info', 'dim')}]Complete. Files saved to {out_dir.resolve()}[/]")


def _parse_cli_options(options: Optional[List[str]]) -> dict[str, Any]:
    if not options:
        return {}

    result = {}
    for item in options:
        if "=" not in item:
            logger.warning(f"Skipping malformed option '{item}'. Must be in 'key=value' format.")
            continue
        key, value = item.split("=", 1)
        result[key.strip()] = value.strip()
    return result
