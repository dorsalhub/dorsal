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
import warnings
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
from dorsal.common.constants import OPEN_VALIDATION_SCHEMAS_VER
from dorsal.common.exceptions import DorsalError

TRANSCRIPTION = {
    "text": "Hello world.",
    "language": "eng",
    "segments": [{"text": "Hello world.", "start_time": 0.0, "end_time": 1.5}],
}

DOCUMENT = {
    "extraction_type": "text",
    "unit": "pt",
    "page_width": 612,
    "page_height": 792,
    "blocks": [
        {
            "block_type": "text",
            "text": "Title",
            "page_number": 1,
            "box": {"x": 72, "y": 72, "width": 300, "height": 24},
        },
        {
            "block_type": "text",
            "text": "Body text.",
            "page_number": 1,
            "box": {"x": 72, "y": 110, "width": 400, "height": 14},
        },
    ],
}

ARXIV = {
    "arxiv_id": "2101.00001v2",
    "title": "A Paper",
    "authors": ["Ada Lovelace", "Alan Turing"],
    "abstract": "We study things.",
    "categories": ["cs.LG", "stat.ML"],
    "doi": "10.1000/xyz",
    "url": "https://arxiv.org/abs/2101.00001v2",
}


class DummyRecord(BaseModel):
    """A dummy Pydantic model for testing BaseModel normalization."""

    text_field: str = Field(alias="textField")
    number: int


@patch("oatschema_adapters.get_adapter")
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


@patch("oatschema_adapters.get_adapter")
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


@patch("oatschema_adapters.get_adapter")
def test_export_record_with_kwargs(mock_get_adapter):
    """Test that kwargs are threaded through to the adapter export method."""
    mock_adapter_instance = MagicMock()
    mock_get_adapter.return_value = mock_adapter_instance

    record = {"foo": "bar"}
    export_record(record, schema_id="test/schema", target_format="tsv", include_speakers=True)

    mock_adapter_instance.export.assert_called_once_with(record, include_speakers=True)


@pytest.mark.parametrize("schema_id", ["audio-transcription", "open/audio-transcription"])
@patch("oatschema_adapters.get_adapter")
def test_export_record_oats_schema_gets_bare_name_and_default_version(mock_get_adapter, schema_id):
    mock_adapter_instance = MagicMock()
    mock_get_adapter.return_value = mock_adapter_instance

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        export_record({"foo": "bar"}, schema_id=schema_id, target_format="srt")

    mock_get_adapter.assert_called_once_with("audio-transcription", "srt")
    mock_adapter_instance.export.assert_called_once_with({"foo": "bar"}, schema_version=OPEN_VALIDATION_SCHEMAS_VER)


@patch("oatschema_adapters.get_adapter")
def test_export_record_passes_the_records_version(mock_get_adapter):
    mock_adapter_instance = MagicMock()
    mock_get_adapter.return_value = mock_adapter_instance

    export_record({"foo": "bar"}, "audio-transcription", "srt", schema_version="0.5.0", validate=False)

    mock_adapter_instance.export.assert_called_once_with({"foo": "bar"}, schema_version="0.5.0", validate=False)


@patch("oatschema_adapters.get_adapter")
def test_export_record_handles_exceptions(mock_get_adapter):
    """Test that adapter export failures are caught and wrapped in a DorsalError."""
    mock_get_adapter.side_effect = ValueError("Unsupported format 'fake'")

    with pytest.raises(DorsalError, match="Failed to export record to fake: Unsupported format 'fake'"):
        export_record({"key": "value"}, schema_id="test/schema", target_format="fake")


@patch("dorsal.api.adapters.export_record")
def test_export_record_to_file_success(mock_export_record, tmp_path):
    """Test standard file export and format inference from the file extension."""
    mock_export_record.return_value = "Mocked Export String"

    out_file = tmp_path / "output_test.srt"

    result = export_record_to_file({"foo": "bar"}, out_file, "test/schema")

    assert result == "Mocked Export String"
    assert out_file.read_text(encoding="utf-8") == "Mocked Export String"

    mock_export_record.assert_called_once_with(
        {"foo": "bar"}, schema_id="test/schema", target_format="srt", schema_version=None
    )


def test_export_record_to_file_inference_failure(tmp_path):
    """Test error handling when the format cannot be inferred from the output path."""
    out_file = tmp_path / "file_without_extension"

    with pytest.raises(DorsalError, match="Could not infer target format from file extension"):
        export_record_to_file({"foo": "bar"}, out_file, "test/schema")


@patch("dorsal.api.adapters.export_record")
def test_export_record_to_file_write_failure(mock_export_record, tmp_path):
    """Test that OS-level write errors are safely wrapped in a DorsalError."""
    mock_export_record.return_value = "Mocked Export String"
    out_file = tmp_path / "output_test.srt"

    with patch("builtins.open", side_effect=PermissionError("Access Denied")):
        with pytest.raises(DorsalError, match="Failed to write exported text to file"):
            export_record_to_file({"foo": "bar"}, out_file, "test/schema")


@patch("oatschema_adapters.get_adapter")
def test_parse_file_with_string_and_kwargs(mock_get_adapter):
    """Test parsing raw string content directly, alongside passing kwargs."""
    mock_adapter_instance = MagicMock()
    mock_adapter_instance.parse.return_value = {"parsed": "data"}
    mock_get_adapter.return_value = mock_adapter_instance

    raw_content = "some raw text"
    result = parse_file(raw_content, schema_id="test/schema", source_format="txt", strict=True)

    assert result == {"parsed": "data"}
    mock_adapter_instance.parse.assert_called_once_with(raw_content, strict=True)


@patch("oatschema_adapters.get_adapter")
def test_parse_file_with_file_like_object(mock_get_adapter):
    """Test parsing from a file-like object using the .read() duck-typing."""
    mock_adapter_instance = MagicMock()
    mock_adapter_instance.parse_file.return_value = {"parsed": "data"}
    mock_get_adapter.return_value = mock_adapter_instance

    fp = io.StringIO("some file content")
    result = parse_file(fp, schema_id="test/schema", source_format="txt")

    assert result == {"parsed": "data"}
    mock_adapter_instance.parse_file.assert_called_once_with(fp)


@patch("oatschema_adapters.get_adapter")
def test_parse_file_oats_schema_gets_bare_name_and_version(mock_get_adapter):
    mock_adapter_instance = MagicMock()
    mock_get_adapter.return_value = mock_adapter_instance

    parse_file("content", schema_id="document-extraction", source_format="txt", schema_version="0.7.0")

    mock_get_adapter.assert_called_once_with("document-extraction", "txt")
    mock_adapter_instance.parse.assert_called_once_with("content", schema_version="0.7.0")


@patch("oatschema_adapters.get_adapter")
def test_parse_file_handles_exceptions(mock_get_adapter):
    """Test that adapter parse failures are caught and wrapped in a DorsalError."""
    mock_get_adapter.side_effect = ValueError("Corrupt file")

    with pytest.raises(DorsalError, match="Failed to parse record from fake: Corrupt file"):
        parse_file("content", schema_id="test/schema", source_format="fake")


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
    assert mock_parse_file.call_args.kwargs["schema_version"] is None


def test_parse_file_from_path_missing_file(tmp_path):
    """Test error handling when the requested input path does not exist."""
    missing_file = tmp_path / "ghost_file.srt"

    with pytest.raises(DorsalError, match="not a valid file or does not exist"):
        parse_file_from_path(missing_file, "test/schema")


def test_parse_file_from_path_inference_failure(tmp_path):
    """Test error handling when the format cannot be inferred from the input path."""
    in_file = tmp_path / "file_without_extension"
    in_file.write_text("dummy data", encoding="utf-8")

    with pytest.raises(DorsalError, match="Could not infer source format from file extension"):
        parse_file_from_path(in_file, "test/schema")


@patch("dorsal.api.adapters.parse_file")
def test_parse_file_from_path_dorsal_error_propagation(mock_parse_file, tmp_path):
    """Test that existing DorsalErrors raised by parse_file bubble up cleanly without double-wrapping."""
    mock_parse_file.side_effect = DorsalError("Specific internal adapter validation failed.")

    in_file = tmp_path / "input_test.txt"
    in_file.write_text("dummy data", encoding="utf-8")

    with pytest.raises(DorsalError, match="Specific internal adapter validation failed."):
        parse_file_from_path(in_file, "test/schema")


@patch("dorsal.api.adapters.parse_file")
def test_parse_file_from_path_unexpected_error(mock_parse_file, tmp_path):
    """Test that unexpected runtime exceptions are caught and wrapped cleanly."""
    mock_parse_file.side_effect = Exception("System crash")

    in_file = tmp_path / "input_test.txt"
    in_file.write_text("dummy data", encoding="utf-8")

    with pytest.raises(DorsalError, match="Failed to read or parse file"):
        parse_file_from_path(in_file, "test/schema")


@patch("oatschema_adapters.list_formats")
def test_get_supported_formats(mock_list_formats):
    """Test that format listing proxies to the registry with the bare OATS schema name."""
    mock_list_formats.return_value = [("srt", "SubRip Text"), ("vtt", "WebVTT")]

    result = get_supported_formats("audio-transcription")

    assert result == [("srt", "SubRip Text"), ("vtt", "WebVTT")]
    mock_list_formats.assert_called_once_with("audio-transcription")


@patch("oatschema_adapters.get_adapter")
def test_get_format_extension_success(mock_get_adapter):
    """Test that get_format_extension successfully retrieves the custom extension string."""
    mock_adapter = MagicMock()
    mock_adapter.extension = "hocr.html"
    mock_get_adapter.return_value = mock_adapter

    result = get_format_extension("test/schema", "hocr")

    assert result == "hocr.html"
    mock_get_adapter.assert_called_once_with("test/schema", "hocr")


@patch("dorsal.api.adapters.logger")
@patch("oatschema_adapters.get_adapter")
def test_get_format_extension_fallback(mock_get_adapter, mock_logger):
    """Test that get_format_extension safely falls back to target_format on exception."""
    mock_get_adapter.side_effect = ValueError("Adapter not found")

    result = get_format_extension("test/schema", "fake_format")

    assert result == "fake_format"

    mock_logger.warning.assert_called_once()
    assert "Adapter not found for schema" in mock_logger.warning.call_args[0][0]


@pytest.mark.parametrize(
    "schema_name, record, target_format, options",
    [
        ("audio-transcription", TRANSCRIPTION, "srt", {}),
        ("audio-transcription", TRANSCRIPTION, "vtt", {}),
        ("document-extraction", DOCUMENT, "md", {"include_frontmatter": False}),
        ("document-extraction", DOCUMENT, "html", {"layout": "col", "style": "none", "fragment": True}),
        ("document-extraction", DOCUMENT, "tsv", {}),
    ],
)
def test_open_prefix_and_bare_name_export_identically(schema_name, record, target_format, options):
    bare = export_record(record, schema_name, target_format, **options)

    with pytest.warns(DeprecationWarning, match=f"'open/{schema_name}' is deprecated.*use '{schema_name}'"):
        prefixed = export_record(record, f"open/{schema_name}", target_format, **options)

    assert prefixed == bare
    with pytest.warns(DeprecationWarning):
        assert get_supported_formats(schema_name) == get_supported_formats(f"open/{schema_name}")
    with pytest.warns(DeprecationWarning):
        assert get_format_extension(schema_name, target_format) == get_format_extension(
            f"open/{schema_name}", target_format
        )


def test_bare_name_does_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        export_record(TRANSCRIPTION, "audio-transcription", "txt")
        get_supported_formats("audio-transcription")


def test_export_validates_at_the_default_version():
    record = {**TRANSCRIPTION, "track_id": 1}

    with pytest.raises(DorsalError, match="track_id"):
        export_record(record, "audio-transcription", "srt")


def test_export_validates_at_the_records_version():
    record = {**TRANSCRIPTION, "track_id": 1}

    assert export_record(record, "audio-transcription", "srt", schema_version="0.5.0").startswith("1\n")


def test_export_unknown_version_raises():
    with pytest.raises(DorsalError, match="9.9.9"):
        export_record(TRANSCRIPTION, "audio-transcription", "srt", schema_version="9.9.9")


def test_export_unknown_option_raises():
    with pytest.raises(DorsalError, match="include_speakerz"):
        export_record(TRANSCRIPTION, "audio-transcription", "srt", include_speakerz=True)


def test_export_converts_string_options():
    assert not export_record(DOCUMENT, "document-extraction", "md", include_frontmatter="false").startswith("---")
    assert export_record(DOCUMENT, "document-extraction", "md", include_frontmatter="true").startswith("---")
    assert export_record({"text": "hi", "language": 3}, "audio-transcription", "txt", validate="false").strip() == "hi"


def test_export_failed_validation_message_is_bounded():
    with pytest.raises(DorsalError) as exc_info:
        export_record({"text": "x" * 5_000_000, "language": 3}, "audio-transcription", "txt")
    assert len(str(exc_info.value)) < 2_000


def test_parse_file_real_adapter_at_records_version():
    record = parse_file("1\n00:00:00,000 --> 00:00:01,500\nHello world.\n", "audio-transcription", "srt")

    assert record["segments"][0]["text"] == "Hello world."


def test_arxiv_formats_are_listed():
    assert [name for name, _ in get_supported_formats("dorsal/arxiv")] == ["bibtex", "csl-json", "md", "ris"]


@pytest.mark.parametrize(
    "target_format, extension",
    [
        ("bibtex", "bib"),
        ("bib", "bib"),
        ("csl-json", "csl.json"),
        ("csl", "csl.json"),
        ("md", "md"),
        ("markdown", "md"),
        ("ris", "ris"),
    ],
)
def test_arxiv_format_extensions(target_format, extension):
    assert get_format_extension("dorsal/arxiv", target_format) == extension


def test_arxiv_exports():
    assert export_record(ARXIV, "dorsal/arxiv", "bibtex").startswith("@misc{2101_00001v2,")
    assert '"publisher": "arXiv"' in export_record(ARXIV, "dorsal/arxiv", "csl-json")
    assert export_record(ARXIV, "dorsal/arxiv", "ris").splitlines()[0] == "TY  - PREP"
    assert "# A Paper" in export_record(ARXIV, "dorsal/arxiv", "md")


def test_arxiv_md_round_trips():
    parsed = parse_file(export_record(ARXIV, "dorsal/arxiv", "md"), "dorsal/arxiv", "md")

    assert parsed["title"] == ARXIV["title"]
    assert parsed["authors"] == ARXIV["authors"]


@pytest.mark.parametrize("value", [False, "false", "0", "no", "off"])
@patch("dorsal.adapters.arxiv.md.validate_record")
def test_arxiv_validate_option_off(mock_validate, value):
    export_record(ARXIV, "dorsal/arxiv", "md", validate=value)

    mock_validate.assert_not_called()


@pytest.mark.parametrize("value", [True, "true", "1"])
@patch("dorsal.adapters.arxiv.ris.validate_record")
def test_arxiv_validate_option_on(mock_validate, value):
    export_record(ARXIV, "dorsal/arxiv", "ris", validate=value)

    mock_validate.assert_called_once_with(ARXIV, schema_id="dorsal/arxiv")


def test_arxiv_registration_never_replaces_a_format(monkeypatch):
    import oatschema_adapters

    from dorsal.adapters.arxiv import register_arxiv_adapters

    get_supported_formats("dorsal/arxiv")
    calls = []
    monkeypatch.setattr(oatschema_adapters, "register_adapter", lambda *a, **k: calls.append((a, k)))

    register_arxiv_adapters()

    assert calls == []


def test_arxiv_registration_skips_formats_registered_first(monkeypatch):
    import oatschema_adapters

    from dorsal.adapters.arxiv import ARXIV_FORMATS, register_arxiv_adapters

    calls = []
    monkeypatch.setattr(oatschema_adapters, "list_formats", lambda schema: [("ris", "Someone else's RIS")])
    monkeypatch.setattr(oatschema_adapters, "register_adapter", lambda *a, **k: calls.append(a))

    register_arxiv_adapters()

    assert [a[1] for a in calls] == [name for name, *_ in ARXIV_FORMATS if name != "ris"]
    assert all("replace" not in k for k in [{}])


def test_arxiv_does_not_shadow_oats_formats():
    import oatschema_adapters

    get_supported_formats("dorsal/arxiv")

    for schema in oatschema_adapters.list_schemas():
        if schema == "dorsal/arxiv":
            continue
        for name, _ in oatschema_adapters.list_formats(schema):
            assert oatschema_adapters.get_adapter(schema, name).format_name == name
            assert not oatschema_adapters.get_adapter(schema, name).export.__module__.startswith("dorsal")
