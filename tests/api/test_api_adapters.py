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

import io
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from dorsal.api.adapters import (
    export_record,
    export_record_to_file,
    parse_file,
    parse_file_from_path,
    get_supported_formats,
    get_format_extension,
)
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
        parse_file("content", schema_id="test/schema", source_format="txt")

    with pytest.raises(DorsalError, match="Please pip install dorsalhub-adapters to enable exports"):
        get_supported_formats(schema_id="test/schema")

    with pytest.raises(DorsalError, match="Please pip install dorsalhub-adapters to enable exports"):
        get_format_extension(schema_id="test/schema", target_format="txt")


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
def test_export_record_with_kwargs(mock_get_adapter):
    """Test that kwargs are threaded through to the adapter export method."""
    mock_adapter_instance = MagicMock()
    mock_get_adapter.return_value = mock_adapter_instance

    record = {"foo": "bar"}
    export_record(record, schema_id="test/schema", target_format="tsv", include_speakers=True)

    mock_adapter_instance.export.assert_called_once_with(record, include_speakers=True)


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
@patch("dorsal.api.adapters.get_adapter")
def test_export_record_handles_exceptions(mock_get_adapter):
    """Test that adapter export failures are caught and wrapped in a DorsalError."""
    mock_get_adapter.side_effect = ValueError("Unsupported format 'fake'")

    with pytest.raises(DorsalError, match="Failed to export record to fake: Unsupported format 'fake'"):
        export_record({"key": "value"}, schema_id="test/schema", target_format="fake")


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
@patch("dorsal.api.adapters.export_record")
def test_export_record_to_file_success(mock_export_record, tmp_path):
    """Test standard file export and format inference from the file extension."""
    mock_export_record.return_value = "Mocked Export String"

    out_file = tmp_path / "output_test.srt"

    result = export_record_to_file({"foo": "bar"}, out_file, "test/schema")

    assert result == "Mocked Export String"
    assert out_file.read_text(encoding="utf-8") == "Mocked Export String"

    mock_export_record.assert_called_once_with({"foo": "bar"}, schema_id="test/schema", target_format="srt")


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
def test_export_record_to_file_inference_failure(tmp_path):
    """Test error handling when the format cannot be inferred from the output path."""
    out_file = tmp_path / "file_without_extension"

    with pytest.raises(DorsalError, match="Could not infer target format from file extension"):
        export_record_to_file({"foo": "bar"}, out_file, "test/schema")


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
@patch("dorsal.api.adapters.export_record")
def test_export_record_to_file_write_failure(mock_export_record, tmp_path):
    """Test that OS-level write errors are safely wrapped in a DorsalError."""
    mock_export_record.return_value = "Mocked Export String"
    out_file = tmp_path / "output_test.srt"

    with patch("builtins.open", side_effect=PermissionError("Access Denied")):
        with pytest.raises(DorsalError, match="Failed to write exported text to file"):
            export_record_to_file({"foo": "bar"}, out_file, "test/schema")


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
@patch("dorsal.api.adapters.get_adapter")
def test_parse_file_with_string_and_kwargs(mock_get_adapter):
    """Test parsing raw string content directly, alongside passing kwargs."""
    mock_adapter_instance = MagicMock()
    mock_adapter_instance.parse.return_value = {"parsed": "data"}
    mock_get_adapter.return_value = mock_adapter_instance

    raw_content = "some raw text"
    result = parse_file(raw_content, schema_id="test/schema", source_format="txt", strict=True)

    assert result == {"parsed": "data"}
    mock_adapter_instance.parse.assert_called_once_with(raw_content, strict=True)


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
@patch("dorsal.api.adapters.get_adapter")
def test_parse_file_with_file_like_object(mock_get_adapter):
    """Test parsing from a file-like object using the .read() duck-typing."""
    mock_adapter_instance = MagicMock()
    mock_adapter_instance.parse_file.return_value = {"parsed": "data"}
    mock_get_adapter.return_value = mock_adapter_instance

    fp = io.StringIO("some file content")
    result = parse_file(fp, schema_id="test/schema", source_format="txt")

    assert result == {"parsed": "data"}
    mock_adapter_instance.parse_file.assert_called_once_with(fp)


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
@patch("dorsal.api.adapters.get_adapter")
def test_parse_file_handles_exceptions(mock_get_adapter):
    """Test that adapter parse failures are caught and wrapped in a DorsalError."""
    mock_get_adapter.side_effect = ValueError("Corrupt file")

    with pytest.raises(DorsalError, match="Failed to parse record from fake: Corrupt file"):
        parse_file("content", schema_id="test/schema", source_format="fake")


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
@patch("dorsal.api.adapters.parse_file")
def test_parse_file_from_path_success(mock_parse_file, tmp_path):
    """Test standard file parsing and format inference from the input extension."""
    mock_parse_file.return_value = {"parsed": "data"}

    in_file = tmp_path / "input_test.vtt"
    in_file.write_text("dummy webvtt content", encoding="utf-8")

    result = parse_file_from_path(in_file, "test/schema")

    assert result == {"parsed": "data"}
    mock_parse_file.assert_called_once()
    assert mock_parse_file.call_args.kwargs["source_format"] == "vtt"


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
def test_parse_file_from_path_missing_file(tmp_path):
    """Test error handling when the requested input path does not exist."""
    missing_file = tmp_path / "ghost_file.srt"

    with pytest.raises(DorsalError, match="not a valid file or does not exist"):
        parse_file_from_path(missing_file, "test/schema")


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
def test_parse_file_from_path_inference_failure(tmp_path):
    """Test error handling when the format cannot be inferred from the input path."""
    in_file = tmp_path / "file_without_extension"
    in_file.write_text("dummy data", encoding="utf-8")

    with pytest.raises(DorsalError, match="Could not infer source format from file extension"):
        parse_file_from_path(in_file, "test/schema")


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
@patch("dorsal.api.adapters.parse_file")
def test_parse_file_from_path_dorsal_error_propagation(mock_parse_file, tmp_path):
    """Test that existing DorsalErrors raised by parse_file bubble up cleanly without double-wrapping."""
    mock_parse_file.side_effect = DorsalError("Specific internal adapter validation failed.")

    in_file = tmp_path / "input_test.txt"
    in_file.write_text("dummy data", encoding="utf-8")

    with pytest.raises(DorsalError, match="Specific internal adapter validation failed."):
        parse_file_from_path(in_file, "test/schema")


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
@patch("dorsal.api.adapters.parse_file")
def test_parse_file_from_path_unexpected_error(mock_parse_file, tmp_path):
    """Test that unexpected runtime exceptions are caught and wrapped cleanly."""
    mock_parse_file.side_effect = Exception("System crash")

    in_file = tmp_path / "input_test.txt"
    in_file.write_text("dummy data", encoding="utf-8")

    with pytest.raises(DorsalError, match="Failed to read or parse file"):
        parse_file_from_path(in_file, "test/schema")


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


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
def test_get_format_extension_success():
    """Test that get_format_extension successfully retrieves the custom extension string."""
    mock_registry = MagicMock()
    mock_adapter = MagicMock()
    mock_adapter.extension = "hocr.html"
    mock_registry.get_adapter.return_value = mock_adapter

    with patch.dict("sys.modules", {"dorsal_adapters": MagicMock(), "dorsal_adapters.registry": mock_registry}):
        result = get_format_extension("test/schema", "hocr")

        assert result == "hocr.html"
        mock_registry.get_adapter.assert_called_once_with("test/schema", "hocr")


@patch("dorsal.api.adapters._ADAPTERS_AVAILABLE", True)
@patch("dorsal.api.adapters.logger")
def test_get_format_extension_fallback(mock_logger):
    """Test that get_format_extension safely falls back to target_format on exception."""
    mock_registry = MagicMock()
    mock_registry.get_adapter.side_effect = ValueError("Adapter not found")

    with patch.dict("sys.modules", {"dorsal_adapters": MagicMock(), "dorsal_adapters.registry": mock_registry}):
        result = get_format_extension("test/schema", "fake_format")

        assert result == "fake_format"

        mock_logger.warning.assert_called_once()
        assert "Adapter not found for schema" in mock_logger.warning.call_args[0][0]
