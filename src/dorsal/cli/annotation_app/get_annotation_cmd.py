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
from typing import Annotated

import typer

logger = logging.getLogger(__name__)


class _DummyContext:
    """A no-op context manager to suppress spinners when outputting raw JSON."""

    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def get_annotation(
    ctx: typer.Context,
    annotation_id: Annotated[str, typer.Argument(help="The UUID of the annotation to hydrate.")],
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output the raw result as JSON to stdout.", rich_help_panel="Output Options"),
    ] = False,
):
    """
    Hydrate and view a specific annotation.
    """
    from dorsal.api.file import get_file_annotation
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_rich_console, get_error_console
    from dorsal.common.exceptions import NotFoundError, DorsalClientError
    from dorsal.cli.views.model import create_model_result_panel

    console = get_rich_console()
    error_console = get_error_console()
    palette = ctx.obj["palette"]

    try:
        with (
            console.status(f"[{palette.get('info', 'dim')}]Downloading annotation...[/]")
            if not json_output
            else _DummyContext()
        ):
            if json_output:
                json_str = get_file_annotation(annotation_id, mode="json")
                console.print(json_str)
                return

            hydrated = get_file_annotation(annotation_id, mode="pydantic")
            schema_id = getattr(hydrated, "schema_id", "Annotation")

        panel = create_model_result_panel(
            result=hydrated, title=schema_id, file_name=f"ID: {annotation_id}", palette=palette
        )
        console.print(panel)
    except typer.Exit:
        raise
    except NotFoundError as e:
        if json_output:
            error_console.print(json.dumps({"success": False, "error": "Not Found", "detail": e.message}))
        else:
            error_console.print(f"[{palette.get('warning', 'yellow')}]Not Found:[/] {e.message}")
        exit_cli(code=EXIT_CODE_ERROR)
    except DorsalClientError as e:
        if json_output:
            error_console.print(json.dumps({"success": False, "error": "API Error", "detail": e.message}))
        else:
            error_console.print(f"[{palette.get('error', 'bold red')}]API Error:[/] {e.message}")
        exit_cli(code=EXIT_CODE_ERROR)
    except Exception as e:
        if json_output:
            error_console.print(json.dumps({"success": False, "error": "Unexpected Error", "detail": str(e)}))
        else:
            error_console.print(f"[{palette.get('error', 'bold red')}]Failed to get annotation:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)
