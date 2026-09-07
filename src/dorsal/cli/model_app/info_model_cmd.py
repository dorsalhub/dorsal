import typer
from typing import Annotated

from dorsal.common.cli import get_rich_console, exit_cli, EXIT_CODE_ERROR, render_model_help_panel


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
    from rich.panel import Panel
    from rich.text import Text

    ui_context = ctx.obj
    console = get_rich_console()
    palette = ui_context.get("palette", {})
    borders = ui_context.get("borders", "rounded")

    # 1. Fetch Resolution Intent and Metadata
    resolution = prepare_model_target(target)

    if resolution.strategy == "error":
        console.print(f"[{palette.get('error', 'bold red')}]Error:[/] {resolution.error_message}")
        exit_cli(code=EXIT_CODE_ERROR)

    # 2. Fetch the Unified Help Payload
    help_info = get_model_help(target=target)

    # 3. Build the Metadata Panel
    meta_lines = []

    # Identity
    model_id = help_info.get("model_id", target)
    version = help_info.get("model_version", "unknown")
    meta_lines.append(f"[{palette.get('key', 'dim')}]ID:[/] {model_id} (v{version})")

    # Description (Registry takes precedence, fallback to raw Class docstring)
    description = None
    if resolution.metadata and resolution.metadata.description:
        description = resolution.metadata.description
    elif help_info.get("class_description"):
        description = help_info["class_description"]

    if description:
        meta_lines.append(f"[{palette.get('key', 'dim')}]Description:[/] {description}")

    # URLs
    if resolution.metadata:
        meta = resolution.metadata
        if meta.url:
            meta_lines.append(
                f"[{palette.get('key', 'dim')}]URL:[/] [{palette.get('link', 'blue underline')}]{meta.url}[/]"
            )
        if getattr(meta, "source_url", None):
            meta_lines.append(
                f"[{palette.get('key', 'dim')}]Source Code:[/] [{palette.get('link', 'blue underline')}]{meta.source_url}[/]"
            )

    # --- Add the Usage snippet directly to the panel ---
    meta_lines.append("")  # Blank line for visual breathing room
    quick_start_cmd = f"dorsal model run {target} ./path/to/file"
    meta_lines.append(
        f"[{palette.get('key', 'dim')}]Usage:[/] [{palette.get('primary_value', 'cyan')}]{quick_start_cmd}[/]"
    )

    meta_panel = Panel(
        "\n".join(meta_lines),
        title=f"[{palette.get('panel_title', 'bold blue')}]Model Info: {target}[/]",
        border_style=palette.get("panel_border", "blue"),
        box=borders,
        expand=False,
    )

    # 4. Render the output
    console.print(meta_panel)

    options_panel = render_model_help_panel(help_info, ui_context)
    if options_panel:
        console.print()
        console.print(options_panel)
