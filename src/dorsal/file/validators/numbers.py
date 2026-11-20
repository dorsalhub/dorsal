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
import math
from typing import Any, Literal, NamedTuple, Sequence, cast, get_args

from pydantic import BaseModel, Field

OnBadNumber = Literal["drop", "raise"]
ON_BAD_NUMBER_DEFAULT: OnBadNumber = "drop"
VALUE_DISPLAY_LIMIT = 64
CHANGES_SHOWN_LIMIT = 10
REJECTION_DISPLAY_LIMIT = 300


class DroppedValue(BaseModel):
    """A number removed from an OATS record because it can't be stored as it is."""

    record: int = Field(default=0, description="The index of the record in its result.")
    path: list[str | int] = Field(description="Where the number was in the record, as keys and list indexes.")
    value: str = Field(description="The number, as text.")
    reason: str = Field(description="Why it was removed.")


class ConvertedValue(BaseModel):
    """A value rewritten in an OATS record without changing what it means, such as `-0.0` to `0.0`."""

    record: int = Field(default=0, description="The index of the record in its result.")
    path: list[str | int] = Field(description="Where the value is in the record, as keys and list indexes.")
    before: str = Field(description="The value as it was, as text.")
    after: str = Field(description="The value as it is now, as text.")


class NumberChanges(BaseModel):
    """What was dropped from or converted in the records of one OATS annotation."""

    schema_id: str | None = Field(description="The schema of the records.")
    schema_version: str | None = Field(default=None, description="The schema version the records were checked at.")
    source_id: str | None = Field(default=None, description="The model or manual source that made the records.")
    part: int | None = Field(default=None, description="The part number, for a record split into parts.")
    dropped: list[DroppedValue] = Field(default_factory=list)
    converted: list[ConvertedValue] = Field(default_factory=list)
    rejected: str | None = Field(
        default=None, description="Why the record was rejected for a bad number and not kept, if it was."
    )


class CheckedRecords(NamedTuple):
    """Records as `oatschema.check_numbers` left them, with what it dropped and converted."""

    records: list[dict[str, Any]]
    dropped: list[DroppedValue]
    converted: list[ConvertedValue]


def number_rejection_reason(error: Any) -> str | None:
    """Return why `oatschema.check_numbers` rejected a record for a bad number, or None if it was for another reason."""
    message = str(getattr(error, "message", "") or "")
    if "after dropping bad numbers" in message or (
        not getattr(error, "schema_path", ()) and message.startswith("… is ")
    ):
        path = getattr(error, "path", ())
        reason = f"{message} at {format_path(path)}" if path and "after dropping" not in message else message
        return reason if len(reason) <= REJECTION_DISPLAY_LIMIT else f"{reason[: REJECTION_DISPLAY_LIMIT - 1]}…"
    return None


def check_on_bad_number(on_bad_number: object) -> OnBadNumber:
    """Return `on_bad_number` if it is `"drop"` or `"raise"`, otherwise raise ValueError."""
    if on_bad_number not in get_args(OnBadNumber):
        raise ValueError(f"`on_bad_number` must be 'drop' or 'raise', not {on_bad_number!r}.")
    return cast(OnBadNumber, on_bad_number)


def display_value(value: Any) -> str:
    """Return a short text form of a number or value from a record."""
    item = getattr(value, "item", None)
    if callable(item) and not isinstance(value, (int, float, str)):
        try:
            value = item()
        except Exception:
            return f"<{type(value).__name__}>"
    if isinstance(value, int) and not isinstance(value, bool) and value.bit_length() > 160:
        digits = int(value.bit_length() * math.log10(2)) + 1
        return f"{'-' if value < 0 else ''}an integer of about {digits} digits"
    text = repr(value)
    return text if len(text) <= VALUE_DISPLAY_LIMIT else f"{text[: VALUE_DISPLAY_LIMIT - 1]}…"


def check_open_schema_numbers(
    records: Sequence[Any], schema_name: str, version: str, *, on_bad_number: OnBadNumber = ON_BAD_NUMBER_DEFAULT
) -> CheckedRecords:
    """
    Run `oatschema.check_numbers` on each record at `version`, which also validates it.

    Raises:
        oatschema.ValidationError: A record is rejected, or isn't valid after its numbers are checked.
        TypeError: A record is not JSON data.
        ValueError: `on_bad_number` is not `"drop"` or `"raise"`.
    """
    import oatschema

    on_bad_number = check_on_bad_number(on_bad_number)
    checked: list[dict[str, Any]] = []
    dropped: list[DroppedValue] = []
    converted: list[ConvertedValue] = []
    for index, record in enumerate(records):
        result = oatschema.check_numbers(
            record, cast("oatschema.SchemaName", schema_name), version, on_bad_number=on_bad_number
        )
        checked.append(result.record)
        dropped.extend(
            DroppedValue(record=index, path=list(item.path), value=display_value(item.value), reason=item.reason)
            for item in result.dropped
        )
        converted.extend(
            ConvertedValue(
                record=index, path=list(item.path), before=display_value(item.before), after=display_value(item.after)
            )
            for item in result.converted
        )
    return CheckedRecords(checked, dropped, converted)


def changes_from_parsed(record: Any) -> tuple[list[DroppedValue], list[ConvertedValue]]:
    """Return what an `oatschema-adapters` parser dropped and converted, from the `ParsedRecord` it returned."""
    dropped = [
        DroppedValue(path=list(item.path), value=display_value(item.value), reason=item.reason)
        for item in getattr(record, "dropped", ())
    ]
    converted = [
        ConvertedValue(path=list(item.path), before=display_value(item.before), after=display_value(item.after))
        for item in getattr(record, "converted", ())
    ]
    return dropped, converted


def format_path(path: Sequence[str | int]) -> str:
    """Return a JSON Pointer for `path`, such as `/blocks/0/score`."""
    if not path:
        return "/"
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in path)


def describe_number_changes(
    dropped: Sequence[DroppedValue],
    converted: Sequence[ConvertedValue],
    *,
    limit: int = CHANGES_SHOWN_LIMIT,
    rejected: str | None = None,
) -> list[str]:
    """Return one line per rejection, dropped or converted value, at most `limit` of them, then a line counting the rest."""
    lines = [f"rejected the record: {rejected}"] if rejected else []
    lines += [f"dropped {item.value} at {format_path(item.path)} ({item.reason})" for item in dropped]
    lines += [f"converted {item.before} to {item.after} at {format_path(item.path)}" for item in converted]
    if len(lines) > limit:
        hidden = len(lines) - limit
        lines = lines[:limit] + [f"and {hidden} more"]
    return lines


def log_number_changes(
    logger: logging.Logger,
    label: str,
    dropped: Sequence[DroppedValue],
    converted: Sequence[ConvertedValue],
    *,
    level: int = logging.INFO,
) -> None:
    """Log what was dropped (at `level`) and converted (at info) in the records described by `label`."""
    if dropped:
        logger.log(
            level,
            "Dropped %d bad number(s) from %s: %s",
            len(dropped),
            label,
            "; ".join(describe_number_changes(dropped, [], limit=3)),
        )
    if converted:
        logger.info(
            "Converted %d value(s) in %s: %s",
            len(converted),
            label,
            "; ".join(describe_number_changes([], converted, limit=3)),
        )
