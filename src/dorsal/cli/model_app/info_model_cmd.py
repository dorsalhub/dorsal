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

import typer
from typing import TYPE_CHECKING, Annotated

from dorsal.common.cli import (
    get_rich_console,
    exit_cli,
    EXIT_CODE_ERROR,
    render_model_help_panel,
    get_error_console,
)

if TYPE_CHECKING:
    from dorsal.cli.themes import UIContext


def info_model(
    ctx: typer.Context,
    target: Annotated[
        str,
        typer.Argument(help="The model identifier (e.g. 'dorsalhub/receipt-scanner' or 'ReceiptScanner')."),
    ],
):
    """
    Display detailed information, metadata, and execution options for a specific model.
    """
    from dorsal.api.model import prepare_model_target, get_model_help
    from rich.style import Style
    from rich.text import Text

    from dorsal.cli.views.layout import key_values, section

    ui_context: UIContext = ctx.obj
    console = get_rich_console()
    error_console = get_error_console()
    palette = ui_context["palette"]

    resolution = prepare_model_target(target)

    if resolution.strategy == "error":
        error_console.print(f"[{palette.get('error', 'bold red')}]Error:[/] {resolution.error_message}")
        exit_cli(code=EXIT_CODE_ERROR)

    help_info = get_model_help(target=target)

    details = key_values(ui_context)
    model_id = help_info.get("model_id", target)
    version = help_info.get("model_version", "unknown")
    details.add("ID", f"{model_id} (v{version})")

    description = None
    if resolution.metadata and resolution.metadata.description:
        description = resolution.metadata.description
    elif help_info.get("class_description"):
        description = help_info["class_description"]

    if description:
        details.add("Description", description)

    link_style = Style.parse(palette.get("link", "blue underline"))
    if resolution.metadata:
        meta = resolution.metadata
        if meta.url:
            details.add("URL", Text(meta.url, style=link_style + Style(link=meta.url)))
        source_url = getattr(meta, "source_url", None)
        if source_url:
            details.add("Source code", Text(source_url, style=link_style + Style(link=source_url)))

    details.add("Usage", f"dorsal model run {target} ./path/to/file", style=palette.get("primary_value", "cyan"))

    console.print(
        section(
            f"Model info: {target}",
            details,
            ui_context,
            border_style=palette.get("panel_border", "blue"),
            padding=(0, 1),
        )
    )

    options_panel = render_model_help_panel(help_info, ui_context)
    if options_panel:
        console.print()
        console.print(options_panel)
