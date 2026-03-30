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
import pytest
import typer
from unittest.mock import MagicMock

from rich.box import ROUNDED
from typer.testing import CliRunner

from dorsal.cli.annotation_app.get_annotation_cmd import get_annotation
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.common.exceptions import DorsalError, NotFoundError, DorsalClientError

cli_app = typer.Typer()

DUMMY_UI_CONTEXT = {"palette": DEFAULT_PALETTE, "icons": {}, "borders": ROUNDED}


@cli_app.callback()
def main_callback(ctx: typer.Context):
    ctx.obj = DUMMY_UI_CONTEXT


cli_app.command(name="get")(get_annotation)
runner = CliRunner()


@pytest.fixture
def mock_get_deps(mocker, mock_rich_console):
    mock_error_console = MagicMock()
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_rich_console)
    mocker.patch("dorsal.common.cli.get_error_console", return_value=mock_error_console)

    mock_api_get = mocker.patch("dorsal.api.file.get_file_annotation")
    mock_panel = mocker.patch("dorsal.cli.views.model.create_model_result_panel")

    return {
        "api_get": mock_api_get,
        "panel": mock_panel,
        "error_console": mock_error_console,
    }


def test_get_annotation_success(mock_rich_console, mock_get_deps):
    mock_result = MagicMock()
    mock_result.schema_id = "AudioTranscription"
    mock_get_deps["api_get"].return_value = mock_result
    mock_get_deps["panel"].return_value = "PanelOutput"

    result = runner.invoke(cli_app, ["get", "uuid-1234"])

    assert result.exit_code == 0
    mock_get_deps["api_get"].assert_called_with("uuid-1234", mode="pydantic")
    mock_get_deps["panel"].assert_called_once_with(
        result=mock_result, title="AudioTranscription", file_name="ID: uuid-1234", ui_context=DUMMY_UI_CONTEXT
    )
    assert mock_rich_console.print.called


def test_get_annotation_json(mock_rich_console, mock_get_deps):
    mock_get_deps["api_get"].return_value = '{"data": "raw"}'

    result = runner.invoke(cli_app, ["get", "uuid-1234", "--json"])

    assert result.exit_code == 0
    mock_get_deps["api_get"].assert_called_with("uuid-1234", mode="json")
    mock_rich_console.print.assert_called_with('{"data": "raw"}', end="\n")
    mock_get_deps["panel"].assert_not_called()


def test_get_annotation_error_panel(mock_get_deps):
    mock_get_deps["api_get"].side_effect = DorsalError("Annotation not found")

    result = runner.invoke(cli_app, ["get", "uuid-1234"])

    assert result.exit_code != 0
    error_msg = str(mock_get_deps["error_console"].print.call_args.args[0])
    assert "Annotation not found" in error_msg


def test_get_annotation_error_json(mock_get_deps):
    mock_get_deps["api_get"].side_effect = Exception("Internal crash")

    result = runner.invoke(cli_app, ["get", "uuid-1234", "--json"])

    assert result.exit_code != 0
    error_json = mock_get_deps["error_console"].print.call_args.args[0]
    data = json.loads(error_json)

    assert data["error"] == "Unexpected Error"
    assert data["detail"] == "Internal crash"


def test_get_annotation_exit_propagation(mock_get_deps):
    mock_get_deps["api_get"].side_effect = typer.Exit(0)
    result = runner.invoke(cli_app, ["get", "uuid-1234"])
    assert result.exit_code == 0


def test_get_annotation_not_found_panel(mock_get_deps):
    mock_get_deps["api_get"].side_effect = NotFoundError(message="Annotation 'uuid-1234' not found.")

    result = runner.invoke(cli_app, ["get", "uuid-1234"])

    assert result.exit_code != 0
    error_msg = str(mock_get_deps["error_console"].print.call_args.args[0])
    assert "Not Found:" in error_msg
    assert "Annotation 'uuid-1234' not found." in error_msg


def test_get_annotation_not_found_json(mock_get_deps):
    mock_get_deps["api_get"].side_effect = NotFoundError(message="Annotation 'uuid-1234' not found.")

    result = runner.invoke(cli_app, ["get", "uuid-1234", "--json"])

    assert result.exit_code != 0
    error_json = mock_get_deps["error_console"].print.call_args.args[0]
    data = json.loads(error_json)

    assert data["error"] == "Not Found"
    assert data["detail"] == "Annotation 'uuid-1234' not found."


def test_get_annotation_client_error_panel(mock_get_deps):
    mock_get_deps["api_get"].side_effect = DorsalClientError(message="Rate limit exceeded.")

    result = runner.invoke(cli_app, ["get", "uuid-1234"])

    assert result.exit_code != 0
    error_msg = str(mock_get_deps["error_console"].print.call_args.args[0])
    assert "API Error:" in error_msg
    assert "Rate limit exceeded." in error_msg


def test_get_annotation_client_error_json(mock_get_deps):
    mock_get_deps["api_get"].side_effect = DorsalClientError(message="Rate limit exceeded.")

    result = runner.invoke(cli_app, ["get", "uuid-1234", "--json"])

    assert result.exit_code != 0
    error_json = mock_get_deps["error_console"].print.call_args.args[0]
    data = json.loads(error_json)

    assert data["error"] == "API Error"
    assert data["detail"] == "Rate limit exceeded."


def test_get_annotation_mutually_exclusive_flags():
    """Covers the Typer BadParameter raise when both --json and --export are used."""
    result = runner.invoke(cli_app, ["get", "uuid-1234", "--json", "--export", "csl"])

    assert result.exit_code != 0
    assert "at the same time" in result.output


def test_get_annotation_export_success(mocker, mock_rich_console, mock_get_deps):
    """Covers successful export logic using the hydrated.record attribute."""
    mock_result = MagicMock()
    mock_result.schema_id = "Article"
    mock_result.record = {"title": "Test Paper"}
    mock_get_deps["api_get"].return_value = mock_result

    mock_export = mocker.patch("dorsal.api.adapters.export_record", return_value="exported_csl_string")

    result = runner.invoke(cli_app, ["get", "uuid-1234", "--export", "csl"])

    assert result.exit_code == 0
    mock_export.assert_called_once_with(record={"title": "Test Paper"}, schema_id="Article", target_format="csl")
    mock_rich_console.print.assert_called_with("exported_csl_string", end="")


def test_get_annotation_export_fallback_model_dump(mocker, mock_rich_console, mock_get_deps):
    """Covers the fallback logic when hydrated.record is missing but model_dump() exists."""
    mock_result = MagicMock()
    del mock_result.record
    mock_result.schema_id = "Article"
    mock_result.model_dump.return_value = {"record": {"title": "Fallback Data"}}
    mock_get_deps["api_get"].return_value = mock_result

    mock_export = mocker.patch("dorsal.api.adapters.export_record", return_value="exported_fallback_string")

    result = runner.invoke(cli_app, ["get", "uuid-1234", "--export", "csl"])

    assert result.exit_code == 0
    mock_export.assert_called_once_with(record={"title": "Fallback Data"}, schema_id="Article", target_format="csl")


def test_get_annotation_export_missing_record(mock_get_deps):
    """Covers the ValueError raise when no record data is found for export, and its JSON error format."""
    mock_result = MagicMock()
    mock_result.record = {}
    mock_result.model_dump.return_value = {}
    mock_get_deps["api_get"].return_value = mock_result

    result = runner.invoke(cli_app, ["get", "uuid-1234", "--export", "csl"])

    assert result.exit_code != 0
    error_json = mock_get_deps["error_console"].print.call_args.args[0]
    data = json.loads(error_json)
    assert data["error"] == "Data Error"
    assert "No record data found" in data["detail"]


def test_get_annotation_value_error_ui(mock_get_deps):
    """Covers the ValueError handler for standard UI output (no --json or --export)."""
    mock_get_deps["api_get"].side_effect = ValueError("Corrupt file")

    result = runner.invoke(cli_app, ["get", "uuid-1234"])

    assert result.exit_code != 0
    error_msg = str(mock_get_deps["error_console"].print.call_args.args[0])
    assert "Data Error:" in error_msg
    assert "Corrupt file" in error_msg


def test_get_annotation_output_file_standard(tmp_path, mock_get_deps, mock_rich_console):
    """Covers saving standard output directly to a file and dumping the pydantic model."""
    out_file = tmp_path / "custom_out.json"

    mock_result = MagicMock()
    mock_result.schema_id = "Article"
    mock_result.model_dump.return_value = {"id": "uuid-1234", "schema_id": "Article"}
    mock_get_deps["api_get"].return_value = mock_result
    mock_get_deps["panel"].return_value = "PanelOutput"

    result = runner.invoke(cli_app, ["get", "uuid-1234", "--output", str(out_file)])

    assert result.exit_code == 0
    assert out_file.exists()

    saved_data = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved_data["id"] == "uuid-1234"
    assert mock_rich_console.print.called


def test_get_annotation_output_dir_json(tmp_path, mock_get_deps):
    """Covers saving pure JSON output to a directory (auto-resolving filename to .json)."""
    out_dir = tmp_path / "out_folder"
    out_dir.mkdir()

    mock_get_deps["api_get"].return_value = '{"raw": "json"}'

    result = runner.invoke(cli_app, ["get", "uuid-1234", "--json", "--output", str(out_dir)])

    assert result.exit_code == 0
    expected_file = out_dir / "uuid-1234.json"
    assert expected_file.exists()
    assert expected_file.read_text(encoding="utf-8") == '{"raw": "json"}'


def test_get_annotation_output_dir_export(mocker, tmp_path, mock_get_deps):
    """Covers saving exported output to a directory (auto-resolving extension)."""
    out_dir = tmp_path / "out_folder"
    out_dir.mkdir()

    mock_result = MagicMock()
    mock_result.schema_id = "Article"
    mock_result.record = {"title": "Test"}
    mock_get_deps["api_get"].return_value = mock_result

    mocker.patch("dorsal.api.adapters.export_record", return_value="exported text")
    mocker.patch("dorsal.api.adapters.get_format_extension", return_value="csl")

    result = runner.invoke(cli_app, ["get", "uuid-1234", "--export", "csl", "--output", str(out_dir)])

    assert result.exit_code == 0
    expected_file = out_dir / "uuid-1234.csl"
    assert expected_file.exists()
    assert expected_file.read_text(encoding="utf-8") == "exported text"
