# Copyright 2025 Dorsal Hub LTD
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

import typer
import datetime
import json
import logging
import pathlib

from typing import Annotated, Optional

from dorsal.common import constants

logger = logging.getLogger(__name__)


def get_file_record(
    ctx: typer.Context,
    hash_string: Annotated[str, typer.Argument(help="The hash (e.g., SHA256) of the file to find.")],
    private: Annotated[
        bool,
        typer.Option(
            "--private",
            help="Restrict search to only your private file records.",
            rich_help_panel="Search Options",
        ),
    ] = False,
    public: Annotated[
        bool,
        typer.Option(
            "--public",
            help="Restrict search to only public file records.",
            rich_help_panel="Search Options",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output the full metadata as a raw JSON object.",
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
    Get a single file record from DorsalHub by its hash.
    By default, searches for records you have access to (both public and private).
    """
    from dorsal.api import get_dorsal_file_record
    from dorsal.cli.views.file import create_file_info_panel
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.common.exceptions import NotFoundError, AuthError, DorsalClientError, DorsalOfflineError

    console = get_rich_console()
    palette = ctx.obj["palette"]

    if private and public:
        exit_cli(
            code=EXIT_CODE_ERROR,
            message="Cannot use --private and --public flags simultaneously.",
        )

    if output_path and not save:
        if str(output_path).lower().endswith(".json"):
            save = True
        else:
            if not output_path.is_dir():
                console.print(
                    f"⚠️ [yellow]Warning:[/] --output path '{output_path}' was specified with an unknown extension."
                    f" Please use -s (for .json) or specify a .json file.",
                    style="yellow",
                )

    private_scope = None
    search_type_str = " "
    if private:
        private_scope = True
        search_type_str = " private "
    elif public:
        private_scope = False
        search_type_str = " public "

    if not json_output:
        console.print(
            f"🔎 Searching for{search_type_str}file record with hash [{palette['primary_value']}]{hash_string}[/]"
        )

    try:
        file_record = get_dorsal_file_record(hash_string=hash_string, private=private_scope, mode="pydantic")

        record_dict = file_record.model_dump(by_alias=True, exclude_none=True, mode="json")
        record_json_str = json.dumps(record_dict, indent=2, ensure_ascii=False)

        if json_output:
            console.print(record_json_str)
            exit_cli()

        if file_record.annotations:
            title = f"File Record: {file_record.annotations.file_base.record.name}"
        else:
            title = "File Record"

        panel = create_file_info_panel(
            record_dict=record_dict,
            title=title,
            private=private_scope,
            palette=palette,
        )
        console.print(panel)

        if save:
            _save_json_report(
                record_json_str=record_json_str,
                output_path=output_path,
                hash_string=hash_string,
                palette=palette,
                json_to_stdout=json_output,
            )

    except typer.Exit:
        raise
    except NotFoundError as e:
        if json_output:
            error_payload = {
                "success": False,
                "error": "Not Found",
                "detail": e.message,
            }
            console.print(json.dumps(error_payload, indent=2))
            exit_cli(code=EXIT_CODE_ERROR)
        else:
            console.print(f"\n[{palette['warning']}]⚠️ Not Found:[/] {e.message}")
            exit_cli()
    except DorsalOfflineError:
        raise
    except AuthError:
        raise
    except DorsalClientError as err:
        exit_cli(code=EXIT_CODE_ERROR, message=f"API Error: {err.message}")
    except Exception as err:
        logger.exception("An unexpected error occurred in 'file get'")
        exit_cli(code=EXIT_CODE_ERROR, message=f"An unexpected error occurred: {err}")


def _get_final_path(hash_string: str, output_path: Optional[pathlib.Path], suffix: str) -> pathlib.Path:
    """Helper to determine the final save path for a report."""

    if output_path:
        if output_path.is_dir():
            return output_path / f"{hash_string}{suffix}"
        else:
            return output_path

    constants.CLI_GET_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return constants.CLI_GET_REPORTS_DIR / f"{hash_string}-{timestamp}{suffix}"


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
        console.print(f"⚠️ Could not save JSON report to {final_path}. Error: {e}", style="yellow")
