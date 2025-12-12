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

import pytest
import logging
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field
from dorsal.file.utils.dates import PDFDatetime, ensure_aware_datetimes


class DemoModel(BaseModel):
    name: str
    dt: datetime | None = None
    nested: dict[str, datetime] = Field(default_factory=dict)
    tags: list[datetime] = Field(default_factory=list)


@pytest.fixture
def parser():
    return PDFDatetime()


def test_parse_pdf_standard_format(parser):
    # D:YYYYMMDDHHmmSSZ
    assert parser.parse("D:20230101120000Z") == datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Without 'D:' prefix
    assert parser.parse("20230101120000Z") == datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    # With separators (rare but possible in loose parsing or dateutil fallback)
    # The regex in dates.py is strict about digits, so standard format usually expects compact.
    assert parser.parse("D:20231225") == datetime(2023, 12, 25)


def test_parse_pdf_timezones(parser):
    # UTC-5
    dt = parser.parse("D:20230101120000-05'00'")
    assert dt.hour == 12
    # Check offset
    assert dt.tzinfo is not None
    # -05:00 is 5 hours behind UTC
    assert dt.utcoffset() == timedelta(hours=-5)

    # UTC+1
    dt = parser.parse("D:20230101120000+01'00'")
    assert dt.utcoffset() == timedelta(hours=1)


def test_parse_heroic_recovery(parser):
    # Valid date prefix followed by garbage
    # "20200101" is valid, followed by nonsense numbers
    dt = parser.parse("D:20200101999999")
    assert dt == datetime(2020, 1, 1)

    # Without D: prefix
    dt = parser.parse("20200101garbage")
    assert dt == datetime(2020, 1, 1)


def test_parse_invalid_inputs(parser):
    assert parser.parse(None) is None
    assert parser.parse("") is None
    assert parser.parse("   ") is None
    assert parser.parse(12345) is None  # Not a string

    # Placeholder dates
    assert parser.parse("0001-01-01") is None
    assert parser.parse("None") is None

    # Impossible dates
    assert parser.parse("20231301") is None  # Month 13
    assert parser.parse("20230001") is None  # Month 00


def test_normalize_naive_to_utc():
    naive = datetime(2023, 1, 1, 12, 0)
    result = ensure_aware_datetimes(naive, strategy="utc")

    assert result.tzinfo == timezone.utc
    assert result.year == 2023
    assert result.hour == 12


def test_normalize_list_recursion():
    naive1 = datetime(2023, 1, 1)
    naive2 = datetime(2023, 1, 2)
    data = [naive1, "string", naive2]

    result = ensure_aware_datetimes(data, strategy="utc")

    assert result[0].tzinfo == timezone.utc
    assert result[1] == "string"
    assert result[2].tzinfo == timezone.utc


def test_normalize_dict_recursion():
    naive = datetime(2023, 1, 1)
    data = {"event": naive, "meta": {"created": naive}}

    result = ensure_aware_datetimes(data, strategy="utc")

    assert result["event"].tzinfo == timezone.utc
    assert result["meta"]["created"].tzinfo == timezone.utc


def test_normalize_pydantic_model():
    naive = datetime(2023, 1, 1)
    model = DemoModel(name="test", dt=naive, nested={"key": naive}, tags=[naive])

    result = ensure_aware_datetimes(model, strategy="utc")

    assert result.dt.tzinfo == timezone.utc
    assert result.nested["key"].tzinfo == timezone.utc
    assert result.tags[0].tzinfo == timezone.utc
    # Ensure original is untouched (default in_place=False)
    assert model.dt.tzinfo is None


def test_normalize_in_place_mutation():
    naive = datetime(2023, 1, 1)
    data = {"d": naive}

    # Run in-place
    result = ensure_aware_datetimes(data, strategy="utc", in_place=True)

    assert result["d"].tzinfo == timezone.utc
    assert data["d"].tzinfo == timezone.utc  # Original mutated
    assert result is data  # Reference identity check


def test_normalize_time_soup_warning(caplog):
    """Test that mixing naive and aware timestamps triggers a warning."""
    naive = datetime(2023, 1, 1)
    aware = datetime(2023, 1, 1, tzinfo=timezone(timedelta(hours=1)))

    data = [naive, aware]

    with caplog.at_level(logging.WARNING):
        ensure_aware_datetimes(data, strategy="utc")

    assert "Timezone Consistency Warning" in caplog.text
    assert "Naive dates were coerced" in caplog.text


def test_normalize_multiple_timezones_warning(caplog):
    """Test that having multiple different aware timezones triggers a warning."""
    tz1 = timezone(timedelta(hours=1))
    tz2 = timezone(timedelta(hours=5))

    data = [datetime(2023, 1, 1, tzinfo=tz1), datetime(2023, 1, 1, tzinfo=tz2)]

    with caplog.at_level(logging.WARNING):
        ensure_aware_datetimes(data)

    assert "timestamps from multiple different timezones" in caplog.text


def test_normalize_already_correct():
    """Test that data which is already uniform and aware is processed silently."""
    utc_date = datetime(2023, 1, 1, tzinfo=timezone.utc)
    data = {"a": utc_date, "b": utc_date}

    # Should not warn
    result = ensure_aware_datetimes(data, strategy="utc")
    assert result["a"] == utc_date
    assert result["b"] == utc_date
