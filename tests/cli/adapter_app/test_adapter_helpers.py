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

import pytest
from dorsal.cli.adapter_app.helpers import extract_records


def test_extract_batch_various_packaging_styles():
    """
    Tests batch processing where items inside the 'results' list are
    packaged in different structural formats.
    """
    json_data = {
        "results": [
            {"file_path": "/test/1", "schema_id": "SchemaA", "record": {"text": "Alpha"}},
            {"file_path": "/test/2", "record": {"schema_id": "SchemaB", "text": "Beta"}},
            {"file_path": "/test/3", "schema_id": "SchemaC", "text": "Gamma"},
        ]
    }

    result = extract_records(json_data)

    assert len(result) == 3

    assert result[0] == ("SchemaA", {"text": "Alpha"}, "/test/1")

    assert result[1] == ("SchemaB", {"schema_id": "SchemaB", "text": "Beta"}, "/test/2")

    assert result[2] == ("SchemaC", {"file_path": "/test/3", "schema_id": "SchemaC", "text": "Gamma"}, "/test/3")


def test_extract_batch_missing_schema():
    """Tests that a batch item missing a schema_id throws a ValueError."""
    json_data = {"results": [{"file_path": "test.txt", "record": {"data": "missing schema"}}]}

    with pytest.raises(ValueError, match="Missing 'schema_id' in JSON wrapper"):
        extract_records(json_data)


def test_extract_batch_with_schema_override():
    """Tests that a schema_override applies to batch items."""
    json_data = {"results": [{"file_path": "test.txt", "record": {"data": "stuff"}}]}

    result = extract_records(json_data, schema_override="OverrideSchema")

    assert len(result) == 1
    assert result[0] == ("OverrideSchema", {"data": "stuff"}, "test.txt")


def test_extract_single_standard_wrapper():
    """Tests a single JSON object properly wrapped with schema_id and record."""
    json_data = {"schema_id": "SingleSchema", "record": {"data": "single value"}, "file_path": "single.txt"}

    result = extract_records(json_data)

    assert len(result) == 1
    assert result[0] == ("SingleSchema", {"data": "single value"}, "single.txt")


def test_extract_single_raw_missing_override():
    """Tests that a raw, unwrapped single record without an override throws a ValueError."""
    json_data = {"data": "raw data", "file_path": "raw.txt"}

    with pytest.raises(ValueError, match="Raw record detected without a schema wrapper"):
        extract_records(json_data)


def test_extract_single_raw_with_override():
    """Tests a raw, unwrapped single record paired with an explicit schema_override."""
    json_data = {"data": "raw data", "file_path": "raw.txt"}

    result = extract_records(json_data, schema_override="ForcedSchema")

    assert len(result) == 1

    assert result[0] == ("ForcedSchema", json_data, "raw.txt")
