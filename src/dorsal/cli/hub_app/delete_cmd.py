# Copyright 2025-2026 Dorsal Hub LTD
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
import logging
import enum

if TYPE_CHECKING:
    from dorsal.cli.themes import UIContext

logger = logging.getLogger(__name__)


class DeletionScope(str, enum.Enum):
    all = "all"
    public = "public"
    private = "private"
    none = "none"


def delete_file_record(
    ctx: typer.Context,
    hash_string: Annotated[str, typer.Argument(help="The hash of the file record to delete.")],
    record: Annotated[
        DeletionScope,
        typer.Option(
            case_sensitive=False,
            help="Specify which core file record(s) to delete.",
        ),
    ] = DeletionScope.all,
    tags: Annotated[
        DeletionScope,
        typer.Option(
            case_sensitive=False,
            help="Specify which of the user's tags to delete for this hash.",
        ),
    ] = DeletionScope.all,
    annotations: Annotated[
        DeletionScope,
        typer.Option(
            case_sensitive=False,
            help="Specify which of the user's annotations to delete for this hash.",
        ),
    ] = DeletionScope.all,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Bypass the interactive confirmation prompt. Use with caution.",
        ),
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output result as a raw JSON object.")] = False,
):
    """
    Deletes a file record and/or its associated data from DorsalHub.

    The default behavior is a "full clean", targeting all records, tags, and
    annotations associated with the user for the given hash.
    """
    from rich.markup import escape
    from rich.text import Text

    from dorsal.api.file import get_dorsal_file_record, _delete_dorsal_file_record
    from dorsal.cli.views.file import create_file_info_panel
    from dorsal.cli.views.layout import message as format_message, section
    from dorsal.common.cli import (
        get_error_console,
        get_rich_console,
        exit_cli,
        handle_error,
        print_raw_output,
    )
    from dorsal.common.exceptions import AuthError, DorsalClientError, DorsalOfflineError, NotFoundError

    console = get_rich_console()
    error_console = get_error_console()
    ui_context: "UIContext" = ctx.obj
    palette = ui_context["palette"]
    icons = ui_context.get("icons", {})
    borders = ui_context.get("borders")
    hash_color = palette.get("hash_value", "default")

    fetch_scope: bool | None
    if record == DeletionScope.private:
        fetch_scope = False
    elif record == DeletionScope.public:
        fetch_scope = True
    else:
        fetch_scope = None

    try:
        if not yes and not json_output:
            with error_console.status("Finding record to delete"):
                file_to_delete = get_dorsal_file_record(hash_string=hash_string, mode="pydantic", public=fetch_scope)
            record_dict = file_to_delete.model_dump(by_alias=True, exclude_none=True, mode="json")

            file_name = ((record_dict.get("annotations") or {}).get("file/base") or {}).get("record", {}).get("name")
            panel_title = "File record to be deleted"
            if file_name:
                panel_title = f"{panel_title}: {escape(str(file_name))}"

            panel = create_file_info_panel(
                record_dict=record_dict,
                title=panel_title,
                private=fetch_scope,
                palette=palette,
                icons=icons,
                box_style=borders,
                override_title_style=palette.get("error", "default"),
                override_border_style=palette.get("panel_border_error", "default"),
            )
            console.print(panel)

            bullet_points = []

            if record == DeletionScope.all:
                bullet_points.append("- Delete both [bold]public and private[/] records")
            elif record == DeletionScope.public:
                bullet_points.append("- Delete the [bold]public[/] record")
            elif record == DeletionScope.private:
                bullet_points.append("- Delete the [bold]private[/] record")

            if tags == DeletionScope.all:
                bullet_points.append("- Delete your [bold]public and private[/] tags")
            elif tags == DeletionScope.public:
                bullet_points.append("- Delete your [bold]public[/] tags")
            elif tags == DeletionScope.private:
                bullet_points.append("- Delete your [bold]private[/] tags")

            if annotations == DeletionScope.all:
                bullet_points.append("- Delete your [bold]public and private[/] annotations")
            elif annotations == DeletionScope.public:
                bullet_points.append("- Delete your [bold]public[/] annotations")
            elif annotations == DeletionScope.private:
                bullet_points.append("- Delete your [bold]private[/] annotations")

            if not bullet_points:
                summary_text = "This operation will perform no deletions."
            else:
                header = f"For the hash [{hash_color}]{escape(hash_string)}[/{hash_color}] this operation will:"
                body = "\n".join(bullet_points)
                summary_text = f"{header}\n{body}"

            console.print()
            console.print(
                section(
                    f"{icons.get('warning', '')}Action summary",
                    Text.from_markup(summary_text),
                    ui_context,
                    title_style=palette.get("panel_title_warning", "bold yellow"),
                    border_style=palette.get("panel_border_warning", "yellow"),
                )
            )
            console.print()

            console.print(
                f"[{palette.get('warning', 'default')}]Are you sure you want to perform this deletion operation?[/]",
                end="",
            )
            typer.confirm("", abort=True, show_default=True)
            console.print()

        with error_console.status(f"Deleting record [{hash_color}]{escape(hash_string)}[/]"):
            response = _delete_dorsal_file_record(
                file_hash=hash_string, record=record.value, tags=tags.value, annotations=annotations.value
            )

        if json_output:
            print_raw_output(response.model_dump_json(indent=2), console)
        else:
            if response.file_deleted == 0 and response.file_modified == 0:
                message = "Operation completed. No records were deleted or modified."
            elif response.file_deleted > 0 and response.file_modified > 0:
                message = f"{response.file_deleted} record(s) deleted and {response.file_modified} modified."
            elif response.file_deleted > 0:
                message = f"{response.file_deleted} record(s) permanently deleted."
            else:
                message = "Public file record ownership rolled back."

            details = f"Removed {response.tags_deleted} tag(s) and {response.annotations_deleted} annotation(s)."

            success_text = Text.assemble(
                (f"{message}\n", palette.get("success", "bold green")),
                (details, palette.get("key", "dim")),
            )

            console.print(
                format_message(
                    f"{icons.get('success', '')}Deletion complete", success_text, ui_context, level="success"
                )
            )

    except NotFoundError:
        scope_str = "any of your accessible records"
        if fetch_scope is True:
            scope_str = "public records"
        elif fetch_scope is False:
            scope_str = "your private records"

        message = f"File record with hash '{hash_string}' not found in {scope_str}."
        handle_error(ui_context, f"Cannot delete: {message}", json_output)
    except typer.Abort:
        if not json_output:
            console.print(f"[{palette.get('warning', 'default')}]Deletion aborted by user.[/]")
        exit_cli()
    except DorsalOfflineError:
        raise
    except AuthError:
        raise
    except DorsalClientError as e:
        handle_error(ui_context, f"API Error: {e.message}", json_output)
    except Exception as e:
        logger.exception("An unexpected error occurred during 'file delete'")
        handle_error(ui_context, f"An unexpected error occurred: {e}", json_output)
