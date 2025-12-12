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

import copy
import datetime
import logging
import re
from typing import Any, Literal

try:
    from dateutil.parser import parse as dateutil_parse

    DATEUTIL_AVAILABLE = True
except ImportError:
    DATEUTIL_AVAILABLE = False

from pydantic import BaseModel

logger = logging.getLogger(__name__)

PLACEHOLDER_DATE_RX = re.compile(r"^(0001|0101)-01-01")
MIN_DATE = datetime.datetime(1450, 1, 1)


class PDFDatetime:
    """
    Opinionated parser for PDF-style date strings (e.g., 'D:20230101120000Z').

    Built for the quirks of PDF metadata fields (/CreationDate, /ModDate) and includes "heroic" heuristics to salvage
    dates from malformed or corrupted strings common in the wild.

    NOTE: This is NOT a general-purpose date parser. It makes assumptions (e.g., minimum valid years, placeholder detection)
    For general parsing, you're usually better off using `python-dateutil`.
    """

    _rx_pdf_date_std = re.compile(
        r"^(?:D:)?"
        r"(?P<year>\d{4})"
        r"(?P<month>\d{2})?"
        r"(?P<day>\d{2})?"
        r"(?P<hour>\d{2})?"
        r"(?P<minute>\d{2})?"
        r"(?P<second>\d{2})?"
        r"(?P<tz_offset_char>[Zz\+\-])?"
        r"(?P<tz_hour>\d{2})?'?"
        r"(?P<tz_minute>\d{2})?'?"
        r".*$"
    )

    def __init__(self, mode: str = "pdfium"):
        self.mode: str = mode

    def _clean_date_string(self, date_str: str) -> str:
        """Clean common extraneous characters from PDF date strings."""
        if self.mode == "pdfium":
            return date_str.strip(" ()\x00")
        logger.debug(
            "Date string cleaning: Unrecognized mode '%s', returning original: '%s'",
            self.mode,
            date_str,
        )
        return date_str

    def _is_plausible_date(self, dt: datetime.datetime) -> bool:
        """Check if a parsed datetime is within a reasonable range."""
        min_date = MIN_DATE
        max_date = datetime.datetime.now() + datetime.timedelta(days=365 * 5)

        if dt.tzinfo:
            min_date = min_date.replace(tzinfo=dt.tzinfo)
            max_date = max_date.replace(tzinfo=dt.tzinfo)

        return min_date < dt < max_date

    def _parse_pdf_standard_format(self, cleaned_date_str: str) -> datetime.datetime | None:
        """Attempt to parse a date string using the standard PDF date format regex and strptime."""
        match = self._rx_pdf_date_std.match(cleaned_date_str)
        if not match:
            return None

        gd = match.groupdict()

        year = gd.get("year")
        month = gd.get("month", "01")
        day = gd.get("day", "01")

        date_parts_str = f"{year}{month}{day}"
        format_str = "%Y%m%d"

        if gd.get("hour"):
            date_parts_str += gd["hour"]
            format_str += "%H"
            if gd.get("minute"):
                date_parts_str += gd["minute"]
                format_str += "%M"
                if gd.get("second"):
                    date_parts_str += gd["second"]
                    format_str += "%S"

        tz_offset_char = gd.get("tz_offset_char")
        tz_hour_str = gd.get("tz_hour")
        tz_minute_str = gd.get("tz_minute")

        if tz_offset_char:
            if tz_offset_char.upper() == "Z":
                date_parts_str += "+0000"
                format_str += "%z"
            elif tz_offset_char in ("+", "-") and tz_hour_str:
                date_parts_str += f"{tz_offset_char}{tz_hour_str}"
                format_str += "%z"
                if tz_minute_str:
                    date_parts_str += tz_minute_str
                else:
                    date_parts_str += "00"

        try:
            dt_obj = datetime.datetime.strptime(date_parts_str, format_str)
            logger.debug(
                "Successfully parsed PDF date string '%s' (processed as '%s' with format '%s') -> %s",
                cleaned_date_str,
                date_parts_str,
                format_str,
                dt_obj,
            )
            return dt_obj
        except ValueError as err:
            logger.debug(
                "strptime failed for PDF date string '%s' (processed as '%s' with format '%s'): %s. Will try other methods.",
                cleaned_date_str,
                date_parts_str,
                format_str,
                err,
            )
            return None

    def _parse_with_dateutil(self, cleaned_date_str: str) -> datetime.datetime | None:
        """Attempt to parse a date string using dateutil.parser.parse as a fallback."""
        if not DATEUTIL_AVAILABLE:
            logger.debug(
                "dateutil library not available, skipping parse_with_dateutil for '%s'.",
                cleaned_date_str,
            )
            return None
        try:
            dt_obj = dateutil_parse(cleaned_date_str)
            logger.debug(
                "Successfully parsed with dateutil: '%s' -> %s",
                cleaned_date_str,
                dt_obj,
            )
            return dt_obj
        except (ValueError, TypeError, OverflowError) as err:
            logger.debug(
                "dateutil.parser.parse failed for date string '%s': %s. Will try prefix parsing.",
                cleaned_date_str,
                err,
            )
            return None
        except Exception:
            logger.exception(
                "Unexpected error from dateutil.parser.parse for date string '%s'.",
                cleaned_date_str,
            )
            return None

    def _parse_date_prefix_heroically(self, cleaned_date_str: str) -> datetime.datetime | None:
        """Heroic last attempt: parse only the YYYYMMDD prefix if it's valid.

        In cases where there is a date, followed by unparseable junk (not uncommon in PDFs), dateutil.parser.parse will give up.

        This includes cases where the date is intuitively quite obvious.
            e.g. "200608281756261" is probably '2006-08-28', despite the nonsense that follows.

        Note: upstream from this method, we've already established that `date` appeared in a  document in a standard metadata field
              reserved for dates. It is therefore not unreasonable to assume that, if it begins with a valid date, then we can take
              it at face value

        Useful for dates followed by unparseable junk, e.g., "D:200608281756261".

        """
        date_to_check = cleaned_date_str[2:] if cleaned_date_str.upper().startswith("D:") else cleaned_date_str

        if (
            len(date_to_check) >= 8
            and date_to_check[:4].isdigit()
            and date_to_check[4:6].isdigit()
            and date_to_check[6:8].isdigit()
        ):
            year_str, month_str, day_str = (
                date_to_check[:4],
                date_to_check[4:6],
                date_to_check[6:8],
            )

            try:
                year = int(year_str)
                month = int(month_str)
                day = int(day_str)
                if not (MIN_DATE.year <= year <= datetime.datetime.now().year + 5):  # Plausible year range
                    logger.debug(
                        "Heroic parse: Year %d out of plausible range for prefix '%s'.",
                        year,
                        date_to_check[:8],
                    )
                    return None
                if not (1 <= month <= 12):
                    logger.debug(
                        "Heroic parse: Month %d out of range for prefix '%s'.",
                        month,
                        date_to_check[:8],
                    )
                    return None
                if not (1 <= day <= 31):
                    logger.debug(
                        "Heroic parse: Day %d out of range for prefix '%s'.",
                        day,
                        date_to_check[:8],
                    )
                    return None

                dt_obj = datetime.datetime.strptime(date_to_check[:8], "%Y%m%d")
                logger.debug(
                    "Heroically parsed date prefix: '%s' (from '%s') -> %s",
                    date_to_check[:8],
                    cleaned_date_str,
                    dt_obj,
                )
                return dt_obj
            except ValueError as err:
                logger.debug(
                    "Heroic prefix parse (strptime) failed for '%s': %s",
                    date_to_check[:8],
                    err,
                )
                return None
        return None

    def parse(self, date_input: str | None) -> datetime.datetime | None:
        """
        Parse PDF document date strings (/CreationDate, /ModDate) into datetime objects.

        Args:
          * date_input: The date string to parse.

        Returns:
          * A datetime.datetime object if parsing is successful.
          * None if the input is None, not a string, or cannot be parsed.
        """
        if not isinstance(date_input, str):
            logger.debug(
                "Failed to parse date: input is not a string (type: %s). Value: '%s'",
                type(date_input).__name__,
                str(date_input)[:100],
            )
            return None
        if not date_input.strip():
            logger.debug("Failed to parse date: input string is empty or whitespace.")
            return None

        cleaned_date_str = self._clean_date_string(date_str=date_input)
        logger.debug(
            "Attempting to parse cleaned date string: '%s' (original: '%s')",
            cleaned_date_str,
            date_input,
        )

        if PLACEHOLDER_DATE_RX.match(cleaned_date_str) or cleaned_date_str.lower() == "none":
            logger.debug("Probable placeholder date: '%s'", date_input)
            return None

        dt_obj = self._parse_pdf_standard_format(cleaned_date_str)
        if dt_obj:
            return dt_obj if self._is_plausible_date(dt_obj) else None

        dt_obj = self._parse_with_dateutil(cleaned_date_str)
        if dt_obj:
            return dt_obj if self._is_plausible_date(dt_obj) else None

        dt_obj = self._parse_date_prefix_heroically(cleaned_date_str)
        if dt_obj:
            return dt_obj

        logger.debug(
            "All parsing attempts failed for date string: '%s' (original: '%s')",
            cleaned_date_str,
            date_input,
        )
        return None


PDF_DATETIME = PDFDatetime()


def ensure_aware_datetimes(data: Any, strategy: Literal["utc", "local"] = "utc", in_place: bool = False) -> Any:
    """
    Coerce all datetime objects within a record to timezone aware datetime objects.

    Args:
        data: The data to fix (Model, dict, list, or datetime).
        strategy:
            - 'utc': Treat naive dates as UTC (e.g. 12:00 -> 12:00Z)
            - 'local': Treat naive dates as system local time (e.g. 12:00 -> 12:00-05:00)
        in_place:
            - If True, modifies dicts/lists in-place (faster).
            - If False, creates a deep copy first (safer).

    Returns:
        The object with fixed datetimes.
    """

    obj = data if in_place else copy.deepcopy(data)

    seen_offsets: set[str] = set()
    found_naive: bool = False

    def _get_offset_str(dt: datetime.datetime) -> str:
        offset = dt.tzinfo.utcoffset(dt) if dt.tzinfo else None
        return str(offset) if offset else "None"

    def _traverse(item: Any) -> Any:
        nonlocal found_naive

        if isinstance(item, datetime.datetime):
            if item.tzinfo is None or item.tzinfo.utcoffset(item) is None:
                found_naive = True
                if strategy == "utc":
                    return item.replace(tzinfo=datetime.timezone.utc)
                elif strategy == "local":
                    return item.astimezone()
            else:
                seen_offsets.add(_get_offset_str(item))
            return item

        if isinstance(item, BaseModel):
            for name in type(item).model_fields.keys():
                val = getattr(item, name)
                if val is not None:
                    fixed_val = _traverse(val)
                    if fixed_val is not val:
                        setattr(item, name, fixed_val)
            return item

        if isinstance(item, list):
            for i, element in enumerate(item):
                item[i] = _traverse(element)
            return item

        if isinstance(item, dict):
            for key, val in item.items():
                item[key] = _traverse(val)
            return item

        return item

    result = _traverse(obj)

    if found_naive and seen_offsets:
        logger.warning(
            "Timezone Consistency Warning: Input data contained both Naive and Aware timestamps. "
            "Naive dates were coerced to '%s', but existing aware dates had these offsets: %s. "
            "Verify this mixed-mode data is intended.",
            strategy.upper(),
            seen_offsets,
        )
    elif len(seen_offsets) > 1:
        logger.warning("Input data contains timestamps from multiple different timezones: %s. ", seen_offsets)

    return result
