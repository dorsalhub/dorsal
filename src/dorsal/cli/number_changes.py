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

import warnings
from enum import Enum
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from rich.console import Console

    from dorsal.cli.themes import UIContext
    from dorsal.file.validators.numbers import ConvertedValue, DroppedValue

ON_BAD_NUMBER_HELP = (
    "What to do with a bad number (NaN, infinity, beyond ±9007199254740991, or outside its field's bounds) in an "
    "OATS record: 'drop' removes a bad optional value and reports it, 'raise' rejects the record."
)


class OnBadNumberOption(str, Enum):
    """The values of `--on-bad-number`."""

    drop = "drop"
    raise_ = "raise"


def silence_dropped_number_warnings() -> None:
    """Hide `oatschema`'s `DroppedNumberWarning`, which the CLI reports in its own output."""
    warnings.filterwarnings("ignore", message="check_numbers dropped", category=UserWarning)


def print_number_changes(
    error_console: "Console",
    ui_context: "UIContext",
    label: str,
    dropped: Sequence["DroppedValue"],
    converted: Sequence["ConvertedValue"],
    rejected: str | None = None,
) -> None:
    """Print a warning to stderr listing what was rejected, dropped or converted in the records described by `label`."""
    if not dropped and not converted and not rejected:
        return
    from rich.markup import escape
    from rich.text import Text

    from dorsal.cli.views.layout import message
    from dorsal.file.validators.numbers import describe_number_changes

    body = Text("\n".join(describe_number_changes(dropped, converted, rejected=rejected)))
    error_console.print(message(escape(label), body, ui_context, level="warning"))


def change_label(change: Any, file_label: str | None = None) -> str:
    """Return a label naming the schema, source, part and file of a `NumberChanges`."""
    label = f"{change.schema_id} from {change.source_id}" if change.source_id else str(change.schema_id)
    if change.part:
        label += f" (part {change.part})"
    return f"{file_label}: {label}" if file_label else label


def print_local_file_changes(
    error_console: "Console", ui_context: "UIContext", local_files: Any, *, with_file_names: bool = True
) -> None:
    """Print a warning to stderr for each OATS annotation of `local_files` that had values dropped or converted."""
    for local_file in local_files:
        for change in getattr(local_file, "number_changes", None) or []:
            file_label = getattr(local_file, "file_path", None) if with_file_names else None
            print_number_changes(
                error_console,
                ui_context,
                change_label(change, file_label),
                change.dropped,
                change.converted,
                getattr(change, "rejected", None),
            )


def local_file_changes_json(local_files: Any) -> dict[str, Any]:
    """Return the number changes of `local_files` as JSON data, by file path, leaving out files with none."""
    return {
        str(local_file.file_path): [change.model_dump(mode="json") for change in local_file.number_changes]
        for local_file in local_files
        if getattr(local_file, "number_changes", None)
    }


def number_changes_json(dropped: Sequence["DroppedValue"], converted: Sequence["ConvertedValue"]) -> dict[str, Any]:
    """Return `dropped` and `converted` as JSON data."""
    return {
        "dropped": [item.model_dump(mode="json") for item in dropped],
        "converted": [item.model_dump(mode="json") for item in converted],
    }
