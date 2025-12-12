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
import json
from typing import Annotated

from rich.panel import Panel
from rich.text import Text

from dorsal.common.cli import get_rich_console, exit_cli, handle_error, EXIT_CODE_ERROR
from dorsal.common.exceptions import (
    AuthError,
    DorsalClientError,
    DorsalOfflineError,
    ForbiddenError,
    NotFoundError,
    BadRequestError,
    DuplicateTagError,
    TaggingError,
)

tag_app = typer.Typer(
    name="tag",
    help="Add or remove tags from a remote file record.",
    no_args_is_help=True,
)


@tag_app.command(name="add")
def add_tag(
    ctx: typer.Context,
    hash_string: Annotated[str, typer.Argument(help="The hash of the file to tag.")],
    label: Annotated[
        str | None,
        typer.Argument(help="A simple private label (e.g. 'urgent'). Equivalent to `--name=label --value=urgent`"),
    ] = None,
    name: Annotated[str | None, typer.Option("--name", "-n", help="The name of the tag (e.g. 'genre').")] = None,
    value: Annotated[str | None, typer.Option("--value", "-v", help="The value for the tag (e.g. 'SciFi').")] = None,
    public: Annotated[bool, typer.Option("--public", help="Create a public tag.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Output result as a raw JSON object.")] = False,
):
    """
    Adds a public or private tag to a file record on DorsalHub.

    You can add tags in two ways:

    1. **Label (Private Only):**
       `dorsal tag add <hash> urgent` -> Creates 'label:urgent'

    2. **Key-Value Pair (Private or Public):**
       `dorsal tag add <hash> --name genre --value sci-fi` -> Creates 'genre:sci-fi'
    """
    from dorsal.api.file import add_tag_to_file, add_label_to_file

    console = get_rich_console()
    palette: dict[str, str] = ctx.obj["palette"]

    is_private_tag = not public

    if label:
        if public:
            handle_error(
                palette,
                "Invalid Request: Simple labels must be PRIVATE. Remove the --public flag or use --name/--value for public tags.",
                json_output,
            )
            return

        if name or value:
            handle_error(
                palette,
                "Ambiguous Request: Please provide EITHER a simple label OR a --name/--value pair, not both.",
                json_output,
            )
            return

        name = "label"
        value = label
        is_private_tag = True

    else:
        if not name or not value:
            handle_error(
                palette, "Missing Arguments: You must provide either a label OR both --name and --value.", json_output
            )
            return

    try:
        if not json_output:
            tag_type_str = "private" if is_private_tag else "public"
            display_val = f"'{value}' (label)" if label else f"'{name}:{value}'"

            console.print(
                f"✏️  Adding {tag_type_str} tag {display_val} to file [{palette.get('hash_value', 'magenta')}]{hash_string}...[/]"
            )

        if label:
            response = add_label_to_file(hash_string=hash_string, label=label)
        else:
            response = add_tag_to_file(hash_string=hash_string, name=name, value=value, private=is_private_tag)

        if json_output:
            console.print(response.model_dump_json(indent=2))
        else:
            tag_style = palette.get("tag_private") if is_private_tag else palette.get("tag_public")
            success_message = Text.assemble(
                ("✅ Successfully added tag '", palette.get("success", "green")),
                (f"{name}:{value}", f"bold {tag_style}"),
                ("'.", palette.get("success", "green")),
            )
            console.print(success_message)

    except NotFoundError:
        handle_error(
            palette,
            f"Cannot add tag: No file record found for hash '{hash_string}",
            json_output,
        )
    except ForbiddenError as err:
        handle_error(palette, f"Cannot add tag. {err}", json_output)
    except BadRequestError as err:
        handle_error(
            palette,
            f"Invalid Tag: The server rejected the tag '{name}:{value}'.\nReason: {err}",
            json_output,
        )
    except (TaggingError, DuplicateTagError, ValueError) as err:
        handle_error(palette, f"Invalid Tag: {err}", json_output)
    except DorsalOfflineError:
        raise
    except AuthError:
        raise
    except DorsalClientError as err:
        handle_error(palette, f"API Error: {err.message}", json_output)
    except Exception as err:
        handle_error(palette, f"An unexpected error occurred: {err}", json_output)


@tag_app.command(name="rm")
def remove_tag(
    ctx: typer.Context,
    hash_string: Annotated[str, typer.Argument(help="The hash of the file record.")],
    tag_id: Annotated[str, typer.Option("--tag-id", help="The unique ID of the tag to remove.")],
    json_output: Annotated[bool, typer.Option("--json", help="Output result as a raw JSON object.")] = False,
):
    """Removes a specific tag from a file record using its unique ID."""
    from dorsal.api.file import remove_tag_from_file

    console = get_rich_console()
    palette: dict[str, str] = ctx.obj["palette"]

    try:
        if not json_output:
            console.print(
                f"🗑️  Removing tag [{palette.get('error', 'red')}]{tag_id}[/] from file [{palette.get('hash_value', 'magenta')}]{hash_string}...[/]"
            )

        remove_tag_from_file(hash_string=hash_string, tag_id=tag_id)

        if json_output:
            console.print(
                json.dumps(
                    {"success": True, "detail": f"Tag '{tag_id}' removed."},
                    ensure_ascii=False,
                )
            )
        else:
            success_message = Text.assemble(
                ("✅ Successfully removed tag '", palette.get("success", "green")),
                (tag_id, f"bold {palette.get('error', 'red')}"),
                ("'.", palette.get("success", "green")),
            )
            console.print(success_message)

    except NotFoundError:
        handle_error(
            palette,
            f"Could not find a file with that hash, or a tag with ID '{tag_id}' on that file.",
            json_output,
        )
    except (TaggingError, ValueError) as e:
        handle_error(palette, f"Invalid Request: {e}", json_output)
    except DorsalOfflineError:
        raise
    except AuthError:
        raise
    except DorsalClientError as e:
        handle_error(palette, f"API Error: {e.message}", json_output)
    except Exception as e:
        handle_error(palette, f"An unexpected error occurred: {e}", json_output)
