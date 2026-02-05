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
from typing import Annotated, Literal

import typer

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
    from dorsal.common.exceptions import DorsalError, NotFoundError, AuthError
    from dorsal.common.cli import exit_cli, EXIT_CODE_ERROR, get_rich_console
    from dorsal.registry.installer import install_model_target
    from dorsal.session import get_shared_dorsal_client
    from dorsal.registry.validators import is_registry_id

    console = get_rich_console()
    palette = ctx.obj["palette"]
    scope: Literal["global", "project"] = "global" if global_install else "project"

    # --- 0. Environment Check (Pipx isolation warning) ---
    if "pipx" in sys.prefix:
        console.print(
            f"[{palette.get('info', 'dim')}]Note: You are running inside a pipx environment.\n"
            "This plugin will be available to the CLI, but NOT to external Python scripts.[/]"
        )

    # --- 1. Safety Check / Pre-flight ---
    if not yes and not force:
        display_meta = {"Target": target, "Source": "Local/Direct"}

        trust_badge = f"[{palette.get('error', 'bold red')}]UNVERIFIED[/]"
        border_style = palette.get("panel_border_warning", "yellow")

        if is_registry_id(target):
            try:
                with console.status(f"[{palette.get('info', 'dim')}]Fetching model details...[/]"):
                    client = get_shared_dorsal_client()
                    reg_data = client.get_registry_model(target)

                    # Update Badge based on Trust Signals
                    if reg_data.is_official:
                        trust_badge = f"[{palette.get('success', 'bold green')}]OFFICIAL MODEL[/] 🛡️"
                        border_style = palette.get("panel_border_success", "green")
                    elif reg_data.is_verified:
                        trust_badge = f"[{palette.get('panel_border', 'bold blue')}]VERIFIED PUBLISHER[/] ☑️"
                        border_style = palette.get("panel_border", "blue")

                    display_meta["Trust Level"] = trust_badge
                    display_meta["Target"] = f"{reg_data.namespace}/{reg_data.name}"
                    display_meta["Description"] = reg_data.description or "No description provided."

                    if reg_data.install_url:
                        raw_url = reg_data.install_url.replace("git+", "").split("@")[0]
                        display_meta["Source Code"] = raw_url

                    if reg_data.created_at:
                        display_meta["Published"] = str(reg_data.created_at)

            # --- CRITICAL FIX 1: Catch AuthError specifically ---
            except AuthError:
                raise  # Bubble up to the global handler (displays the Auth Panel)

            except Exception as e:
                logger.debug(f"Metadata fetch failed: {e}")

                # Fail Fast for Registry IDs (404s or other non-auth errors)
                if "/" in target:
                    # We strictly check for NotFoundError or 404 string
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

        # Build the Review Panel
        msg_lines = []
        for k, v in display_meta.items():
            msg_lines.append(f"[{palette.get('key', 'dim')}]{k}:[/] {v}")

        if "UNVERIFIED" in trust_badge:
            msg_lines.append(f"\n[{palette.get('warning', 'bold yellow')}]⚠️  Safety Warning[/]")
            msg_lines.append("You are about to install executable code from an unverified source.")
            msg_lines.append("Please review the source above before proceeding.")

        msg_lines.append(f"\n[{palette.get('info', 'dim')}]Review full registry at: https://dorsalhub.com/registry[/]")

        console.print(
            Panel(
                "\n".join(msg_lines),
                title=f"[{palette.get('panel_title_warning', 'bold yellow')}]🔍 Review Model[/]",
                border_style=border_style,
            )
        )

        if not Confirm.ask("Do you trust this source and want to proceed?"):
            console.print(f"[{palette.get('error', 'bold red')}]Aborted.[/]")
            exit_cli(code=0)

    # --- 2. Installation ---
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

    # --- 3. Success Output ---
    success_color = palette.get("primary_value", "cyan")
    scope_color = palette.get("warning", "yellow")

    console.print(
        Panel(
            f"Successfully installed [{success_color}]{package_name}[/]\nActive Scope: [{scope_color}]{scope}[/]",
            title=f"[{palette.get('panel_title_success', 'bold green')}]✅ Installation Complete[/]",
            border_style=palette.get("panel_border_success", "green"),
        )
    )
