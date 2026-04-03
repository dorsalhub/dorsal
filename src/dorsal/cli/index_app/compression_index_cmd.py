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
import typer
from typing import Annotated, Optional

logger = logging.getLogger(__name__)


def set_index_compression_cmd(
    ctx: typer.Context,
    mode: Annotated[
        Optional[str], typer.Option("--mode", help="The compression algorithm to use (zlib or zstd).")
    ] = None,
    level: Annotated[
        Optional[int], typer.Option("--level", help="The compression level (zlib: 0-9, zstd: 1-22).")
    ] = None,
    global_scope: Annotated[
        bool, typer.Option("--global", "-g", help="Save to the global user config (~/.dorsal) instead of project.")
    ] = False
):
    """View or set the compression algorithm and level for the local search index."""
    from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR
    from dorsal.api.config import set_compression
    from dorsal.cli.themes import UIContext
    
    console = get_rich_console()
    ui_context: UIContext = ctx.obj
    palette = ui_context["palette"]
    borders = ui_context["borders"]

    if mode is None and level is None:
        from dorsal.api.config import get_config_summary
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
        
        config_data = get_config_summary()
        
        is_compressed = config_data.get("index_compression_enabled", False)
        current_mode = config_data.get("index_compression_mode", "zlib")
        current_level = config_data.get("index_compression_level", 6)

        table = Table.grid(expand=False, padding=(0, 1))
        table.add_column(justify="right", style=palette.get("key", "dim"))
        table.add_column(justify="left", style=palette.get("primary_value", "cyan"))

        if is_compressed:
            status_text = Text("Enabled", style=palette.get("success", "green"))
        else:
            status_text = Text("Not Enabled", style=palette.get("warning", "yellow"))

        table.add_row("Status:", status_text)
        if is_compressed:
            table.add_row("Mode:", current_mode)
            table.add_row("Level:", str(current_level))

        console.print(
            Panel(
                table,
                title=f"[{palette.get('panel_title', 'bold')}]Index Compression Settings[/]",
                border_style=palette.get("panel_border", "blue"),
                box=borders,
                expand=False,
                padding=(0, 1)
            )
        )

        console.print(ctx.get_help())
        raise typer.Exit()

    scope = "global" if global_scope else "project"
    
    try:
        safe_mode = mode.lower() if mode else None
        
        set_compression(mode=safe_mode, level=level, scope=scope)
        
        updates = []
        if safe_mode:
            updates.append(f"Algorithm: [bold {palette.get('primary_value', 'cyan')}]{safe_mode}[/]")
        if level is not None:
            updates.append(f"Level: [bold {palette.get('primary_value', 'cyan')}]{level}[/]")

        console.print(
            f"[{palette.get('success', 'green')}]✅ Index compression settings updated in {scope} config:[/]\n  "
            + "\n  ".join(updates)
        )
        
        console.print(
            "\n[dim]Newly indexed records will use these settings."
            "\nTo apply these changes to existing records in the index, run:[/] "
            f"[{palette.get('primary_value', 'cyan')}]dorsal index optimize[/]"
        )
        
    except ValueError as e:
        console.print(f"[{palette.get('error', 'red')}]Validation Error:[/] {e}")
        exit_cli(code=EXIT_CODE_ERROR)
    except Exception as e:
        exit_cli(code=EXIT_CODE_ERROR, message=f"Failed to save settings: {e}")