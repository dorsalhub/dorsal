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
            dir_okay=False,
            readable=True,
            resolve_path=True,
            help="Path to the file to process.",
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
    private: Annotated[
        bool,
        typer.Option(
            "--private",
            help="Mark the resulting annotation as private.",
            rich_help_panel="Model Configuration",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output the raw result as JSON to stdout. Automatically skips safety prompts.",
            rich_help_panel="Output Options",
        ),
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip the safety confirmation prompt if installation is required.")
    ] = False,
):
    """
    Run a model on a local file.

    If the model is not installed locally, Dorsal will attempt to fetch
    and install it from the registry automatically.
    """
    from dorsal.common.exceptions import DorsalError, AuthError
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_rich_console, get_error_console
    from dorsal.api.model import run_or_install_model
    from dorsal.cli.views.model import create_model_result_panel
    from dorsal.registry.resolution import resolve_target, is_package_installed
    from dorsal.cli.model_app.checks import check_and_confirm_model_install

    console = get_rich_console()
    error_console = get_error_console()
    palette = ctx.obj["palette"]

    parsed_options = _parse_cli_options(options)

    if not json_output:
        try:
            strategy, package_name = resolve_target(target)
            if not is_package_installed(package_name):
                check_and_confirm_model_install(target, palette, yes=yes)
        except Exception:
            pass

    if not json_output:
        console.print(
            f"Running model [{palette.get('primary_value', 'cyan')}]{target}[/] "
            f"on [{palette.get('primary_value', 'cyan')}]{file_path.name}[/]..."
        )

    try:
        with (
            console.status(
                f"[{palette.get('info', 'dim')}]Processing... (This may trigger an install)[/]",
                spinner="dots",
            )
            if not json_output
            else _DummyContext()
        ):
            result = run_or_install_model(
                target=target,
                file_path=str(file_path),
                options=parsed_options,
                ignore_linter_errors=ignore_lint,
                private=private,
            )

        if json_output:
            data = result.model_dump(exclude_none=True) if hasattr(result, "model_dump") else result.dict()
            console.print(json.dumps(data, indent=2, default=str, ensure_ascii=False))
        else:
            panel = create_model_result_panel(result=result, target=target, file_name=file_path.name, palette=palette)
            console.print(panel)

    except (DorsalError, AuthError) as e:
        if json_output:
            error_console.print(json.dumps({"error": str(e)}))
            exit_cli(code=EXIT_CODE_ERROR)
        else:
            error_console.print(f"[{palette.get('error', 'bold red')}]Run Failed:[/] {e}")
            exit_cli(code=EXIT_CODE_ERROR)

    except Exception as e:
        logger.exception("Unexpected error during model run")
        if json_output:
            error_console.print(json.dumps({"error": "Unexpected internal error", "details": str(e)}))
        else:
            error_console.print(f"[{palette.get('error', 'bold red')}]Unexpected Error:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)


def _parse_cli_options(options: Optional[List[str]]) -> dict[str, Any]:
    """Helper to parse a list of 'key=value' strings into a dictionary."""
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


class _DummyContext:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False
