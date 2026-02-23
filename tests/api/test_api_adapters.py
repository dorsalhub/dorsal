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

from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from dorsal.api.adapters import export_record, get_supported_formats
from dorsal.common.exceptions import DorsalError


class DummyRecord(BaseModel):
    """A dummy Pydantic model for testing BaseModel normalization."""

    text_field: str = Field(alias="textField")
    number: int


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", False)
def test_missing_adapters_package():
    """Ensure a helpful DorsalError is raised if dorsalhub-adapters is not installed."""
    with pytest.raises(DorsalError, match="Please pip install dorsalhub-adapters to enable exports"):
        export_record({"key": "value"}, schema_id="test/schema", target_format="txt")

    with pytest.raises(DorsalError, match="Please pip install dorsalhub-adapters to enable exports"):
        get_supported_formats(schema_id="test/schema")


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
@patch("dorsal.api.adapters.get_adapter")
def test_export_record_with_dict(mock_get_adapter):
    """Test exporting a standard python dictionary."""
    mock_adapter_instance = MagicMock()
    mock_adapter_instance.export.return_value = "Mocked Export String"
    mock_get_adapter.return_value = mock_adapter_instance

    record = {"foo": "bar"}
    result = export_record(record, schema_id="test/schema", target_format="srt")

    assert result == "Mocked Export String"
    mock_get_adapter.assert_called_once_with("test/schema", "srt")
    mock_adapter_instance.export.assert_called_once_with(record)


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
@patch("dorsal.api.adapters.get_adapter")
def test_export_record_with_pydantic_model(mock_get_adapter):
    """Test that Pydantic models are correctly normalized to dictionaries before export."""
    mock_adapter_instance = MagicMock()
    mock_adapter_instance.export.return_value = "Mocked Export String"
    mock_get_adapter.return_value = mock_adapter_instance

    record = DummyRecord(textField="Hello World", number=42)
    result = export_record(record, schema_id="test/schema", target_format="vtt")

    assert result == "Mocked Export String"

    expected_dict = {"textField": "Hello World", "number": 42}
    mock_adapter_instance.export.assert_called_once_with(expected_dict)


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
@patch("dorsal.api.adapters.get_adapter")
def test_export_record_handles_exceptions(mock_get_adapter):
    """Test that adapter export failures are caught and wrapped in a DorsalError."""

    mock_get_adapter.side_effect = ValueError("Unsupported format 'fake'")

    with pytest.raises(DorsalError, match="Failed to export record to fake: Unsupported format 'fake'"):
        export_record({"key": "value"}, schema_id="test/schema", target_format="fake")


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
def test_get_supported_formats():
    """Test that format listing proxies correctly to the registry."""
    mock_registry = MagicMock()
    mock_registry.ALIAS_MAPPING = {}
    mock_registry.list_formats.return_value = [("srt", "SubRip Text"), ("vtt", "WebVTT")]

    with patch.dict("sys.modules", {"dorsal_adapters": MagicMock(), "dorsal_adapters.registry": mock_registry}):
        result = get_supported_formats("test/schema")

        assert result == [("srt", "SubRip Text"), ("vtt", "WebVTT")]
        mock_registry.list_formats.assert_called_once_with("test/schema")
