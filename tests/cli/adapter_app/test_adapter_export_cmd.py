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

    mock_registry = mocker.MagicMock()
    mock_adapter = mocker.MagicMock()
    mock_adapter.export.return_value = "Mocked exported format content"
    mock_registry.get_adapter.return_value = mock_adapter

    mocker.patch.dict("sys.modules", {"dorsal_adapters": mocker.MagicMock(), "dorsal_adapters.registry": mock_registry})

    return {
        "extract": mock_extract,
        "registry": mock_registry,
        "adapter": mock_adapter,
        "error_console": mock_error_console,
    }


def test_export_basic_success(mock_rich_console, mock_export_deps):
    """Tests a standard single-file export to stdout and auto-save."""
    with runner.isolated_filesystem():
        test_file = pathlib.Path("test_file.dorsal.json")
        test_file.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")

        result = runner.invoke(cli_app, ["export", str(test_file), "srt"])

        assert result.exit_code == 0, result.output

        mock_export_deps["registry"].get_adapter.assert_called_once_with("MockSchema", "srt")
        mock_export_deps["adapter"].export.assert_called_once_with({"text": "Extracted string"})

        printed_text = mock_rich_console.print.call_args.args[0]
        assert "Mocked exported format content" in str(printed_text)

        expected_output_file = pathlib.Path("test_file.srt")
        assert expected_output_file.exists()
        assert expected_output_file.read_text(encoding="utf-8") == "Mocked exported format content"


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

        assert pathlib.Path("test_file_1.md").exists()
        assert pathlib.Path("test_file_2.md").exists()

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


def test_export_missing_adapters_package(mocker, mock_export_deps):
    """Tests graceful failure when the optional dorsalhub-adapters is missing."""
    mocker.patch.dict("sys.modules", {"dorsal_adapters.registry": None})

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.json")
        test_file.write_text(json.dumps({"valid": "data"}), encoding="utf-8")

        result = runner.invoke(cli_app, ["export", str(test_file), "srt"])

        assert result.exit_code != 0
        error_msg = str(mock_export_deps["error_console"].print.call_args.args[0])
        assert "'dorsalhub-adapters' package is not installed" in error_msg


def test_export_adapter_runtime_error(mock_export_deps):
    """Tests handling when a specific adapter fails to process the record."""
    mock_export_deps["adapter"].export.side_effect = Exception("Format constraint violated")

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.json")
        test_file.write_text(json.dumps({"valid": "data"}), encoding="utf-8")

        result = runner.invoke(cli_app, ["export", str(test_file), "md"])

        assert result.exit_code != 0
        error_msg = str(mock_export_deps["error_console"].print.call_args.args[0])
        assert "Export Failed for schema" in error_msg
        assert "Format constraint violated" in error_msg


def test_export_no_save_flag(mock_export_deps):
    """Tests that the --no-save flag successfully suppresses file writing."""
    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.json")
        test_file.write_text(json.dumps({"dummy": "data"}), encoding="utf-8")

        result = runner.invoke(cli_app, ["export", str(test_file), "srt", "--no-save"])

        assert result.exit_code == 0

        assert test_file.exists()
        assert not pathlib.Path("test.srt").exists()


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

    mock_export_deps["adapter"].export.side_effect = ["Mocked success content", Exception("Simulated batch failure")]

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test_batch.dorsal.json")
        test_file.write_text(json.dumps([{"dummy": "data1"}, {"dummy": "data2"}]), encoding="utf-8")

        result = runner.invoke(cli_app, ["export", str(test_file), "md"])

        assert result.exit_code == 0

        assert pathlib.Path("test_batch_1.md").exists()
        assert not pathlib.Path("test_batch_2.md").exists()

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

        assert pathlib.Path("my_custom_image_name.srt").exists()
        assert not pathlib.Path("generic_wrapper.srt").exists()


def test_export_file_write_failure(mocker, mock_export_deps):
    """
    Tests the exception handler for when writing the final output file to disk fails.
    """
    mock_export_deps["extract"].return_value = [("MockSchema", {"text": "Rec"}, None)]

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.json")
        test_file.write_text(json.dumps({"valid": "data"}), encoding="utf-8")

        mocker.patch("pathlib.Path.write_text", side_effect=PermissionError("Access denied to disk"))

        result = runner.invoke(cli_app, ["export", str(test_file), "srt"])

        assert result.exit_code != 0

        error_msg = str(mock_export_deps["error_console"].print.call_args.args[0])
        assert "Failed to write output file" in error_msg
        assert "Access denied to disk" in error_msg
