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

import json
import pathlib
import pytest
import typer
from unittest.mock import MagicMock
from typer.testing import CliRunner

from dorsal.cli.adapter_app.export_cmd import export_adapter
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.common.exceptions import DorsalError


cli_app = typer.Typer()


@cli_app.callback()
def main_callback(ctx: typer.Context):
    ctx.obj = {"palette": DEFAULT_PALETTE}


cli_app.command(name="export")(export_adapter)

runner = CliRunner()


@pytest.fixture
def mock_export_deps(mocker, mock_rich_console):
    """
    Mocks backend dependencies for the `export` command.
    """
    mock_error_console = MagicMock()
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_rich_console)
    mocker.patch("dorsal.common.cli.get_error_console", return_value=mock_error_console)

    mock_extract = mocker.patch("dorsal.cli.adapter_app.helpers.extract_records")
    mock_extract.return_value = [("MockSchema", {"text": "Extracted string"}, None)]

    # MOCK UPDATE: Patch the API boundary instead of the underlying registry
    mock_export_file = mocker.patch("dorsal.api.adapters.export_record_to_file")
    mock_export_file.return_value = "Mocked exported format content"

    mock_export_record = mocker.patch("dorsal.api.adapters.export_record")
    mock_export_record.return_value = "Mocked exported format content"

    return {
        "extract": mock_extract,
        "export_file": mock_export_file,
        "export_record": mock_export_record,
        "error_console": mock_error_console,
    }


def test_export_basic_success(mock_rich_console, mock_export_deps):
    """Tests a standard single-file export to stdout and auto-save via the API wrapper."""
    with runner.isolated_filesystem():
        test_file = pathlib.Path("test_file.dorsal.json")
        test_file.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")

        result = runner.invoke(cli_app, ["export", str(test_file), "srt"])

        assert result.exit_code == 0, result.output

        # Verify the API wrapper was called correctly
        mock_export_deps["export_file"].assert_called_once()
        kwargs = mock_export_deps["export_file"].call_args.kwargs
        assert kwargs["schema_id"] == "MockSchema"
        assert kwargs["target_format"] == "srt"
        assert kwargs["output_path"] == pathlib.Path.cwd() / "test_file.srt"

        printed_text = mock_rich_console.print.call_args.args[0]
        assert "Mocked exported format content" in str(printed_text)


def test_export_infer_format_from_output(mock_rich_console, mock_export_deps):
    """NEW TEST: Verifies that target_format can be completely omitted if inferred from --output."""
    with runner.isolated_filesystem():
        test_file = pathlib.Path("test_file.dorsal.json")
        test_file.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")

        # Omit the format argument, pass an --output with a valid extension
        result = runner.invoke(cli_app, ["export", str(test_file), "--output", "my_custom_subs.vtt"])

        assert result.exit_code == 0

        # Verify it inferred "vtt" perfectly
        kwargs = mock_export_deps["export_file"].call_args.kwargs
        assert kwargs["target_format"] == "vtt"
        assert kwargs["output_path"] == pathlib.Path("my_custom_subs.vtt")


def test_export_batch_success(mock_rich_console, mock_export_deps):
    """Tests batch processing which should render a table instead of raw text."""
    mock_export_deps["extract"].return_value = [
        ("MockSchema", {"text": "Rec 1"}, None),
        ("MockSchema", {"text": "Rec 2"}, None),
    ]

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test_file.dorsal.json")
        test_file.write_text(json.dumps([{"dummy": "data1"}, {"dummy": "data2"}]), encoding="utf-8")

        result = runner.invoke(cli_app, ["export", str(test_file), "md"])

        assert result.exit_code == 0

        # Verify the API was called twice with uniquely sequenced filenames
        assert mock_export_deps["export_file"].call_count == 2
        call_1_kwargs = mock_export_deps["export_file"].call_args_list[0].kwargs
        call_2_kwargs = mock_export_deps["export_file"].call_args_list[1].kwargs

        assert call_1_kwargs["output_path"].name == "test_file_1.md"
        assert call_2_kwargs["output_path"].name == "test_file_2.md"

        table_call_arg = mock_rich_console.print.call_args.args[0]
        assert type(table_call_arg).__name__ == "Table"
        assert "Export Results" in str(table_call_arg.title)


def test_export_invalid_json(mock_export_deps):
    """Tests handling of a malformed JSON input file."""
    with runner.isolated_filesystem():
        test_file = pathlib.Path("bad_file.json")
        test_file.write_text("{ bad json : ", encoding="utf-8")

        result = runner.invoke(cli_app, ["export", str(test_file), "srt"])

        assert result.exit_code != 0
        error_msg = str(mock_export_deps["error_console"].print.call_args.args[0])
        assert "Invalid JSON file" in error_msg


def test_export_validation_error(mock_export_deps):
    """Tests handling of ValueError thrown by the record extractor."""
    mock_export_deps["extract"].side_effect = ValueError("Missing schema information")

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.json")
        test_file.write_text(json.dumps({"bad": "data"}), encoding="utf-8")

        result = runner.invoke(cli_app, ["export", str(test_file), "vtt"])

        assert result.exit_code != 0
        error_msg = str(mock_export_deps["error_console"].print.call_args.args[0])
        assert "Validation Error" in error_msg
        assert "Missing schema information" in error_msg


def test_export_missing_adapters_package(mock_export_deps):
    """Tests graceful failure when the optional dorsalhub-adapters is missing."""
    # Simulate the API raising the missing dependency error
    mock_export_deps["export_file"].side_effect = DorsalError(
        "Please pip install dorsalhub-adapters to enable exports."
    )

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.json")
        test_file.write_text(json.dumps({"valid": "data"}), encoding="utf-8")

        result = runner.invoke(cli_app, ["export", str(test_file), "srt"])

        assert result.exit_code != 0
        error_msg = str(mock_export_deps["error_console"].print.call_args.args[0])
        assert "dorsalhub-adapters" in error_msg


def test_export_adapter_runtime_error(mock_export_deps):
    """Tests handling when a specific adapter fails to process the record."""
    mock_export_deps["export_file"].side_effect = Exception("Format constraint violated")

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.json")
        test_file.write_text(json.dumps({"valid": "data"}), encoding="utf-8")

        result = runner.invoke(cli_app, ["export", str(test_file), "md"])

        assert result.exit_code != 0
        error_msg = str(mock_export_deps["error_console"].print.call_args.args[0])
        assert "Export Failed for schema" in error_msg
        assert "Format constraint violated" in error_msg


def test_export_no_save_flag(mock_export_deps):
    """Tests that the --no-save flag routes to export_record instead of export_record_to_file."""
    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.json")
        test_file.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")

        result = runner.invoke(cli_app, ["export", str(test_file), "srt", "--no-save"])

        assert result.exit_code == 0

        # Verify export_file was NEVER called, and export_record was used instead
        mock_export_deps["export_file"].assert_not_called()
        mock_export_deps["export_record"].assert_called_once()


def test_export_schema_override_passed_down(mock_export_deps):
    """Tests that --schema-id correctly passes the value to the extractor."""
    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.json")
        test_file.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")

        runner.invoke(cli_app, ["export", str(test_file), "srt", "--schema-id", "CustomSchema"])

        mock_export_deps["extract"].assert_called_once_with({"dummy": "data"}, schema_override="CustomSchema")


def test_export_batch_with_adapter_error(mock_rich_console, mock_export_deps):
    """
    Tests batch processing where one record fails to export.
    This triggers the table rendering logic for item["status"] == "Error" and row.append("-").
    """
    mock_export_deps["extract"].return_value = [
        ("MockSchema", {"text": "Rec 1"}, None),
        ("MockSchema", {"text": "Rec 2"}, None),
    ]

    mock_export_deps["export_file"].side_effect = ["Mocked success content", Exception("Simulated batch failure")]

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test_batch.dorsal.json")
        test_file.write_text(json.dumps([{"dummy": "data1"}, {"dummy": "data2"}]), encoding="utf-8")

        result = runner.invoke(cli_app, ["export", str(test_file), "md"])

        assert result.exit_code == 0
        assert mock_export_deps["export_file"].call_count == 2

        table_call_arg = mock_rich_console.print.call_args.args[0]
        assert type(table_call_arg).__name__ == "Table"


def test_export_with_orig_file_path(mock_export_deps):
    """
    Tests that if the record has an orig_file_path, it derives the output
    file name from that path's stem instead of the raw JSON's name.
    """
    mock_export_deps["extract"].return_value = [
        ("MockSchema", {"text": "Rec"}, "internal_dir/my_custom_image_name.png")
    ]

    with runner.isolated_filesystem():
        test_file = pathlib.Path("generic_wrapper.dorsal.json")
        test_file.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")

        result = runner.invoke(cli_app, ["export", str(test_file), "srt"])

        assert result.exit_code == 0

        # Verify the custom file name was passed down correctly
        kwargs = mock_export_deps["export_file"].call_args.kwargs
        assert kwargs["output_path"].name == "my_custom_image_name.srt"


def test_export_usage_error_no_format_or_output(mock_export_deps):
    """
    NEW TEST: Tests the usage error check if the user omits the format AND
    doesn't provide an --output flag that can be inferred.
    """
    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.json")
        test_file.write_text(json.dumps({"valid": "data"}), encoding="utf-8")

        # No format provided, no --output provided
        result = runner.invoke(cli_app, ["export", str(test_file)])

        assert result.exit_code != 0

        error_msg = str(mock_export_deps["error_console"].print.call_args.args[0])
        assert "Usage Error" in error_msg
        assert "target_format" in error_msg
