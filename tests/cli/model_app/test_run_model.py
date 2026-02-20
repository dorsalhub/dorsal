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


from dorsal.cli.model_app.run_model_cmd import run_model
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.common.exceptions import DorsalError, AuthError
from dorsal.file.validators.file_record import Annotation, GenericFileAnnotation


cli_app = typer.Typer()


@cli_app.callback()
def main_callback(ctx: typer.Context):
    ctx.obj = {"palette": DEFAULT_PALETTE}


cli_app.command(name="run")(run_model)

runner = CliRunner()


@pytest.fixture
def mock_run_deps(mocker, mock_rich_console):
    """
    Mocks backend dependencies for the `run-model` command.
    Targeting upstream sources to handle local function imports.
    """

    mock_error_console = MagicMock()

    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_rich_console)
    mocker.patch("dorsal.common.cli.get_error_console", return_value=mock_error_console)

    mock_runner = mocker.patch("dorsal.api.model.run_or_install_model")
    mock_result = MagicMock()
    mock_result.model_dump.return_value = {"summary": "Processed successfully"}
    mock_runner.return_value = mock_result

    mock_resolve = mocker.patch("dorsal.registry.resolution.resolve_target")
    mock_resolve.return_value = ("registry", "dorsal-receipt-scanner")

    mock_is_installed = mocker.patch("dorsal.registry.resolution.is_package_installed")
    mock_is_installed.return_value = True

    mock_check_safety = mocker.patch("dorsal.cli.model_app.checks.check_and_confirm_model_install")
    mock_create_panel = mocker.patch("dorsal.cli.views.model.create_model_result_panel")

    return {
        "run_logic": mock_runner,
        "result": mock_result,
        "resolve": mock_resolve,
        "is_installed": mock_is_installed,
        "check_safety": mock_check_safety,
        "create_panel": mock_create_panel,
        "error_console": mock_error_console,
    }


def test_run_model_basic_success(mock_rich_console, mock_run_deps):
    """Tests a standard model run on a file in interactive mode."""
    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file)])

        assert result.exit_code == 0, result.output

        mock_run_deps["run_logic"].assert_called_once_with(
            target="dorsal/scanner",
            file_path=str(test_file.resolve()),
            options={},
            ignore_linter_errors=False,
            private=False,
        )

        mock_run_deps["create_panel"].assert_called_once()
        assert mock_rich_console.print.called


def test_run_model_with_options_parsing(mock_run_deps, caplog):
    """Tests that --opt key=value pairs are parsed into a dictionary and malformed ones warned."""
    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(
            cli_app,
            ["run", "dorsal/scanner", str(test_file), "--opt", "engine=ocr", "-o", "dpi=300", "-o", "invalid_opt"],
        )

        assert result.exit_code == 0
        expected_options = {"engine": "ocr", "dpi": "300"}
        assert mock_run_deps["run_logic"].call_args.kwargs["options"] == expected_options

        assert "Skipping malformed option 'invalid_opt'" in caplog.text


def test_run_model_triggers_safety_check_when_not_installed(mock_run_deps):
    """Tests that safety checks are triggered if the package isn't installed."""
    mock_run_deps["is_installed"].return_value = False

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file)])

        mock_run_deps["check_safety"].assert_called_once_with("dorsal/scanner", DEFAULT_PALETTE, yes=False)


def test_run_model_json_output(mock_rich_console, mock_run_deps):
    """Tests --json mode, verifying raw output and skipped safety UI."""
    mock_run_deps["is_installed"].return_value = False

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file), "--json"])

        assert result.exit_code == 0

        mock_run_deps["check_safety"].assert_not_called()

        json_str = mock_rich_console.print.call_args.args[0]
        data = json.loads(json_str)
        assert data["summary"] == "Processed successfully"


def test_run_model_dorsal_error_handling(mock_run_deps):
    """Tests handling of specific DorsalError exceptions in interactive mode."""
    mock_run_deps["run_logic"].side_effect = DorsalError("Model execution failed")

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file)])

        assert result.exit_code != 0

        error_msg = str(mock_run_deps["error_console"].print.call_args.args[0])
        assert "Model execution failed" in error_msg


def test_run_model_dorsal_error_json_mode(mock_run_deps):
    """Tests handling of specific DorsalError exceptions in JSON mode."""
    mock_run_deps["run_logic"].side_effect = DorsalError("API Limit Reached")

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file), "--json"])

        assert result.exit_code != 0

        error_json = mock_run_deps["error_console"].print.call_args.args[0]
        data = json.loads(error_json)
        assert data["error"] == "API Limit Reached"


def test_run_model_unexpected_error_json_mode(mock_run_deps):
    """Tests error reporting in JSON mode for generic exceptions."""
    mock_run_deps["run_logic"].side_effect = Exception("Internal crash")

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file), "--json"])

        assert result.exit_code != 0

        error_json = mock_run_deps["error_console"].print.call_args.args[0]
        data = json.loads(error_json)
        assert "Unexpected internal error" in data["error"]
        assert "Internal crash" in data["details"]


def test_run_model_export_success(mock_run_deps, mocker):
    real_record = GenericFileAnnotation(text="Transcribed string")
    real_annotation = Annotation.model_construct(record=real_record, schema_id="AudioTranscription")
    mock_run_deps["run_logic"].return_value = real_annotation

    mock_registry = mocker.MagicMock()
    mock_adapter = mocker.MagicMock()
    mock_adapter.export.return_value = "1\n00:00:00 --> 00:00:01\nTranscribed string"
    mock_registry.get_adapter.return_value = mock_adapter

    mocker.patch.dict("sys.modules", {"dorsal_adapters": mocker.MagicMock(), "dorsal_adapters.registry": mock_registry})

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.wav")
        test_file.touch()
        result = runner.invoke(cli_app, ["run", "dorsal/whisper", str(test_file), "--export", "srt"])

        assert result.exit_code == 0
        assert "Transcribed string" in result.output


def test_run_model_export_missing_adapters(mock_run_deps, mocker):
    real_annotation = Annotation.model_construct(record=GenericFileAnnotation(), schema_id="AudioTranscription")
    mock_run_deps["run_logic"].return_value = real_annotation

    mocker.patch.dict("sys.modules", {"dorsal_adapters.registry": None})

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.wav")
        test_file.touch()
        result = runner.invoke(cli_app, ["run", "dorsal/whisper", str(test_file), "--export", "srt"])

        assert result.exit_code != 0
        error_msg = str(mock_run_deps["error_console"].print.call_args_list[0].args[0])
        assert "dorsalhub-adapters" in error_msg


def test_run_model_export_invalid_return_type(mock_run_deps, mocker):
    mock_run_deps["run_logic"].return_value = {"bad": "data"}

    mock_registry = mocker.MagicMock()
    mocker.patch.dict("sys.modules", {"dorsal_adapters": mocker.MagicMock(), "dorsal_adapters.registry": mock_registry})

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.wav")
        test_file.touch()
        result = runner.invoke(cli_app, ["run", "dorsal/whisper", str(test_file), "--export", "srt"])

        assert result.exit_code != 0
        error_msg = str(mock_run_deps["error_console"].print.call_args.args[0])
        assert "Unexpected return type" in error_msg


def test_run_model_export_adapter_error(mock_run_deps, mocker):
    real_annotation = Annotation.model_construct(record=GenericFileAnnotation(), schema_id="AudioTranscription")
    mock_run_deps["run_logic"].return_value = real_annotation

    mock_registry = mocker.MagicMock()
    mock_registry.get_adapter.side_effect = ValueError("Format 'pdf' not supported")

    mocker.patch.dict("sys.modules", {"dorsal_adapters": mocker.MagicMock(), "dorsal_adapters.registry": mock_registry})

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.wav")
        test_file.touch()
        result = runner.invoke(cli_app, ["run", "dorsal/whisper", str(test_file), "--export", "pdf"])

        assert result.exit_code != 0
        error_msg = str(mock_run_deps["error_console"].print.call_args.args[0])
        assert "Export Error" in error_msg
        assert "Format 'pdf' not supported" in error_msg
