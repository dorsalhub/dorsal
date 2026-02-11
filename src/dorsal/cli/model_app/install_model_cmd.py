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
import sys
import shutil
from typing import Annotated, Literal

import typer

from dorsal.common.constants import WEB_URL

logger = logging.getLogger(__name__)


def install_model(
    ctx: typer.Context,
    target: Annotated[str, typer.Argument(help="The pip target (Registry ID, git URL, or local path).")],
    global_install: Annotated[
        bool, typer.Option("--global", "-g", help="Install to global user config instead of project config.")
    ] = False,
    force: Annotated[bool, typer.Option("--force", "-f", help="Force reinstall the pip package.")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the safety confirmation prompt.")] = False,
):
    """
    Install a model from the Registry, Git, or a local folder.

    This command runs `pip install` and then automatically registers the model
    into your dorsal.toml configuration.
    """
    from rich.panel import Panel
    from rich.prompt import Confirm
    from rich.text import Text
    from dorsal.common.exceptions import DorsalError, NotFoundError, AuthError
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_rich_console
    from dorsal.registry.installer import install_model_target
    from dorsal.session import get_shared_dorsal_client
    from dorsal.registry.validators import is_registry_id

    console = get_rich_console()
    palette = ctx.obj["palette"]
    scope: Literal["global", "project"] = "global" if global_install else "project"

    if "pipx" in sys.prefix:
        console.print(
            f"[{palette.get('info', 'dim')}]Note: You are running inside a pipx environment.\n"
            "This plugin will be available to the CLI, but NOT to external Python scripts.[/]"
        )

    if not yes and not force:
        display_meta = {"Model": target, "Source": "Local Path"}

        status_badge = f"[{palette.get('warning', 'bold yellow')}]Unverified[/]"
        border_style = palette.get("panel_border_warning", "yellow")

        link_style = palette.get("link", "blue underline")

        if is_registry_id(target):
            try:
                with console.status(f"[{palette.get('info', 'dim')}]Fetching model details...[/]"):
                    client = get_shared_dorsal_client()
                    reg_data = client.get_registry_model(target)

                    if reg_data.is_official or reg_data.is_verified:
                        status_badge = f"[{palette.get('panel_border', 'bold blue')}]Verified[/]"
                        border_style = palette.get("panel_border", "blue")

                    dorsalhub_url = f"{WEB_URL}/models/{reg_data.namespace}/{reg_data.name}"
                    display_meta = {
                        "Model": f"{reg_data.namespace}/{reg_data.name}",
                        "Status": status_badge,
                        "URL": f"[{link_style} link={dorsalhub_url}]{dorsalhub_url}[/]",
                        "Description": reg_data.description or "No description provided.",
                    }

                    if reg_data.install_url:
                        if reg_data.install_url.startswith("git+") and not shutil.which("git"):
                            message = Text.assemble(
                                (f"The model '{target}' requires Git to install.\n\n", "default"),
                                ("Dorsal could not find the ", "default"),
                                ("git", f"bold {palette.get('primary_value', 'cyan')}"),
                                (" command in your system PATH.\n\n", "default"),
                                ("To proceed, please install Git from:\n", "default"),
                                ("https://git-scm.com/downloads", link_style),
                            )

                            console.print(
                                Panel(
                                    message,
                                    expand=False,
                                    title=f"[{palette.get('panel_title_error', 'bold red')}]Missing System Dependency[/]",
                                    border_style=palette.get("panel_border_error", "red"),
                                )
                            )
                            exit_cli(code=EXIT_CODE_ERROR)

                        raw_url = reg_data.install_url.replace("git+", "").split("@")[0]
                        display_meta["Source Code"] = f"[{link_style} link={raw_url}]{raw_url}[/]"

                    if reg_data.created_at:
                        display_meta["Published"] = reg_data.created_at.date().isoformat()

            except AuthError:
                raise

            except Exception as e:
                logger.debug(f"Metadata fetch failed: {e}")

                if "/" in target:
                    if isinstance(e, NotFoundError) or "404" in str(e):
                        console.print(
                            f"[{palette.get('error', 'bold red')}]Error: Model '{target}' not found in registry.[/]"
                        )
                    else:
                        console.print(
                            f"[{palette.get('error', 'bold red')}]Error: Failed to connect to registry for '{target}'.[/]\n{e}"
                        )
                    exit_cli(code=EXIT_CODE_ERROR)

                display_meta["Warning"] = "Could not fetch remote metadata."

        msg_lines = []
        for k, v in display_meta.items():
            msg_lines.append(f"[{palette.get('key', 'dim')}]{k}:[/] {v}")

        if "Unverified" in status_badge:
            msg_lines.append(f"\n[{palette.get('warning', 'bold yellow')}]⚠️ Safety Warning[/]")
            msg_lines.append("You are about to install executable code from an unverified source.")
            msg_lines.append("Please review the source above before proceeding.")

        console.print(
            Panel(
                "\n".join(msg_lines),
                title=f"[{palette.get('panel_title_warning', 'bold yellow')}]Model Info[/]",
                border_style=border_style,
                expand=False,
            )
        )

        if not Confirm.ask("Do you trust this source and want to proceed?"):
            console.print(f"[{palette.get('error', 'bold red')}]Cancelled.[/]")
            exit_cli(code=0)

    status_color = palette.get("primary_value", "bold cyan")
    with console.status(f"Installing model from [{status_color}]{target}[/]..."):
        try:
            package_name = install_model_target(target, scope=scope, force_reinstall=force)

        except AuthError:
            raise

        except DorsalError as e:
            console.print(f"[{palette.get('error', 'bold red')}]Install Failed:[/] {e}")
            exit_cli(code=EXIT_CODE_ERROR)
        except Exception as e:
            logger.exception("Unexpected error during installation")
            console.print(f"[{palette.get('error', 'bold red')}]Unexpected Error:[/] {e}")
            exit_cli(code=EXIT_CODE_ERROR)

    success_color = palette.get("primary_value", "cyan")
    success_message = f"Successfully installed [{success_color}]{package_name}[/]"
    if scope == "global":
        scope_color = palette.get("warning", "yellow")
        success_message += f"\nActive Scope: [{scope_color}]{scope}[/]"

    console.print(
        Panel(
            success_message,
            title=f"[{palette.get('panel_title_success', 'bold green')}]✅ Installation Complete[/]",
            border_style=palette.get("panel_border_success", "green"),
            expand=False,
        )
    )
