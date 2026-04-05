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
import time
from unittest.mock import MagicMock, ANY
from typer.testing import CliRunner

from rich.box import ROUNDED
import typer

from dorsal.cli.model_app.run_model_cmd import run_model
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.common.exceptions import DorsalError, AuthError
from dorsal.file.configs.model_runner import RunModelResult
from dorsal.common.model import AnnotationModelSource


cli_app = typer.Typer()

DUMMY_UI_CONTEXT = {"palette": DEFAULT_PALETTE, "icons": {}, "borders": ROUNDED}


@cli_app.callback()
def main_callback(ctx: typer.Context):
    ctx.obj = DUMMY_UI_CONTEXT


cli_app.command(name="run")(run_model)

runner = CliRunner()


@pytest.fixture
def mock_run_deps(mocker, mock_rich_console):
    """
    Mocks backend dependencies for the `run-model` command.
    Targeting upstream sources to handle local function imports.
    """

    mock_error_console = MagicMock()

    mock_error_console.get_time.side_effect = time.time
    mock_error_console.is_terminal = False

    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_rich_console)
    mocker.patch("dorsal.common.cli.get_error_console", return_value=mock_error_console)

    mock_runner = mocker.patch("dorsal.api.model.run_or_install_model")

    default_result = RunModelResult(
        name="MockModel",
        source=AnnotationModelSource(type="Model", id="mock/model", version="1.0.0"),
        records=[{"summary": "Processed successfully"}],  # <--- CHANGED HERE
        schema_id="mock/schema",
    )
    mock_runner.return_value = default_result

    mock_resolve = mocker.patch("dorsal.registry.resolution.resolve_target")
    mock_resolve.return_value = ("registry", "dorsal-receipt-scanner")

    mock_is_installed = mocker.patch("dorsal.registry.resolution.is_package_installed")
    mock_is_installed.return_value = True

    mock_check_safety = mocker.patch("dorsal.cli.model_app.checks.check_and_confirm_model_install")
    mock_create_panel = mocker.patch("dorsal.cli.views.model.create_model_result_panel")

    return {
        "run_logic": mock_runner,
        "result": default_result,
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
            progress_callback=ANY,
        )

        mock_run_deps["create_panel"].assert_called_once()
        assert mock_rich_console.print.called


def test_run_model_with_options_parsing(mock_run_deps):
    """Tests that --opt key=value pairs are parsed into a dictionary and malformed ones warned."""
    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(
            cli_app,
            ["run", "dorsal/scanner", str(test_file), "--opt", "engine=ocr", "-o", "dpi=300", "-o", "invalid_opt"],
        )

        assert result.exit_code == 0
        expected_options = {"engine": "ocr", "dpi": 300}
        assert mock_run_deps["run_logic"].call_args.kwargs["options"] == expected_options

        printed_messages = [str(call.args[0]) for call in mock_run_deps["error_console"].print.call_args_list]
        assert any("Skipping malformed option 'invalid_opt'" in msg for msg in printed_messages)


def test_run_model_triggers_safety_check_when_not_installed(mock_run_deps):
    """Tests that safety checks are triggered if the package isn't installed."""
    mock_run_deps["is_installed"].return_value = False

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file)])

        # Update DEFAULT_PALETTE to DUMMY_UI_CONTEXT here:
        mock_run_deps["check_safety"].assert_called_once_with("dorsal/scanner", DUMMY_UI_CONTEXT, yes=False)


def test_run_model_json_output(mock_rich_console, mock_run_deps):
    """Tests --json mode, verifying raw output and skipped safety UI."""
    mock_run_deps["is_installed"].return_value = False

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file), "--json"])

        assert result.exit_code == 0

        mock_run_deps["check_safety"].assert_called_once()

        printed_messages = [str(call.args[0]) for call in mock_run_deps["error_console"].print.call_args_list]
        assert any("requires installation" in msg for msg in printed_messages)

        json_str = mock_rich_console.print.call_args.args[0]
        data = json.loads(json_str)

        assert data["results"][0]["records"][0]["summary"] == "Processed successfully"


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


def test_run_model_unexpected_error_json_mode(mock_rich_console, mock_run_deps):
    """Tests error reporting in JSON mode for generic exceptions."""
    mock_run_deps["run_logic"].side_effect = Exception("Internal crash")

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file), "--json"])

        assert result.exit_code == 0

        error_json = mock_rich_console.print.call_args.args[0]
        data = json.loads(error_json)
        assert "Internal crash" in data["results"][0]["error"]


def test_run_model_export_success(mock_rich_console, mock_run_deps, mocker):
    mock_result = RunModelResult(
        name="FasterWhisperTranscriber",
        source=AnnotationModelSource(type="Model", id="dorsalhub/whisper", version="0.1.0"),
        records=[{"text": "Transcribed string"}],
        schema_id="open/audio-transcription",
    )
    mock_run_deps["run_logic"].return_value = mock_result

    mocker.patch("dorsal.api.adapters.export_record", return_value="1\n00:00:00 --> 00:00:01\nTranscribed string")

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.wav")
        test_file.touch()
        result = runner.invoke(cli_app, ["run", "dorsal/whisper", str(test_file), "--export", "srt", "--no-save"])

        assert result.exit_code == 0
        printed_text = mock_rich_console.print.call_args.args[0]
        assert "Transcribed string" in printed_text


def test_run_model_export_missing_adapters(mock_run_deps, mocker):
    mock_result = RunModelResult(
        name="FasterWhisperTranscriber",
        source=AnnotationModelSource(type="Model", id="dorsalhub/whisper", version="0.1.0"),
        records=[{"text": "Transcribed string"}],
        schema_id="open/audio-transcription",
    )
    mock_run_deps["run_logic"].return_value = mock_result

    mocker.patch(
        "dorsal.api.adapters.export_record",
        side_effect=DorsalError("Please pip install dorsalhub-adapters to enable exports."),
    )

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.wav")
        test_file.touch()
        result = runner.invoke(cli_app, ["run", "dorsal/whisper", str(test_file), "--export", "srt"])

        assert result.exit_code == 0

        printed_messages = [str(call.args[0]) for call in mock_run_deps["error_console"].print.call_args_list]
        assert any("dorsalhub-adapters" in msg for msg in printed_messages)


def test_run_model_export_adapter_error(mock_run_deps, mocker):
    mock_result = RunModelResult(
        name="FasterWhisperTranscriber",
        source=AnnotationModelSource(type="Model", id="dorsalhub/whisper", version="0.1.0"),
        records=[{"text": "Transcribed string"}],
        schema_id="open/audio-transcription",
    )
    mock_run_deps["run_logic"].return_value = mock_result

    mocker.patch(
        "dorsal.api.adapters.export_record",
        side_effect=DorsalError("Failed to export record to pdf: Format 'pdf' not supported"),
    )

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.wav")
        test_file.touch()
        result = runner.invoke(cli_app, ["run", "dorsal/whisper", str(test_file), "--export", "pdf"])

        assert result.exit_code == 0

        printed_messages = [str(call.args[0]) for call in mock_run_deps["error_console"].print.call_args_list]

        assert any("Export Error" in msg and "Format 'pdf' not supported" in msg for msg in printed_messages)


def test_run_model_with_output_path(mock_rich_console, mock_run_deps):
    """Covers path resolution when using the --output flag (Snippet 1)."""
    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        out_dir = pathlib.Path("custom_out")
        out_path = out_dir / "custom_name.json"

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file), "--output", str(out_path)])

        assert result.exit_code == 0
        assert out_dir.exists()
        assert out_path.exists()


def test_run_model_outer_unexpected_error(mock_run_deps, mocker):
    """Covers global unexpected error catching outside the processing loop (Snippet 3)."""

    mocker.patch("rich.progress.Progress.__enter__", side_effect=Exception("Outer UI crash"))

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file)])

        assert result.exit_code != 0

        error_msg = str(mock_run_deps["error_console"].print.call_args.args[0])
        assert "Unexpected Error:" in error_msg
        assert "Outer UI crash" in error_msg


def test_run_model_batch_processing(mock_rich_console, mock_run_deps, mocker):
    """Covers batch processing tables, truncation, error rows, and completion messages (Snippets 4 & 6)."""

    mocker.patch("dorsal.api.adapters.export_record", return_value="Simulated exported text")

    with runner.isolated_filesystem():
        test_dir = pathlib.Path("batch_input")
        test_dir.mkdir()

        for i in range(12):
            (test_dir / f"test_{i}.pdf").touch()

        def mock_run_logic(*args, **kwargs):
            if "test_0.pdf" in kwargs.get("file_path", ""):
                raise Exception("Simulated inner error")
            return mock_run_deps["result"]

        mock_run_deps["run_logic"].side_effect = mock_run_logic

        result = runner.invoke(
            cli_app, ["run", "dorsal/scanner", str(test_dir), "--max-length", "10", "--export", "txt"]
        )

        assert result.exit_code == 0


def test_run_model_single_file_inner_error_display(mock_run_deps):
    """Covers single-file interactive display of unhandled inner loop errors (Snippet 5)."""
    mock_run_deps["run_logic"].side_effect = Exception("Inner crash during run")

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file)])

        assert result.exit_code == 0

        error_calls = [str(call.args[0]) for call in mock_run_deps["error_console"].print.call_args_list]
        assert any("Error processing file: Inner crash during run" in msg for msg in error_calls)


def test_run_model_progress_hook_coverage(mock_run_deps):
    """Tests the inner progress_hook function with and without descriptions."""

    def mock_run_with_progress(*args, **kwargs):
        cb = kwargs.get("progress_callback")
        if cb:
            cb(10.0, 100.0)
            cb(50.0, 100.0, "Downloading model weights...")
        return mock_run_deps["result"]

    mock_run_deps["run_logic"].side_effect = mock_run_with_progress

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file)])

        assert result.exit_code == 0

        mock_run_deps["run_logic"].assert_called_once()


def test_run_model_export_model_error_validation(mock_run_deps):
    """Tests that exporting fails gracefully if the model returned an error state."""

    mock_result = RunModelResult(
        name="MockModel",
        source=AnnotationModelSource(type="Model", id="mock/model", version="1.0.0"),
        records=[{"summary": "Partial output"}],
        schema_id="mock/schema",
        error="Inference failed halfway.",
    )
    mock_run_deps["run_logic"].return_value = mock_result

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file), "--export", "md"])

        assert result.exit_code == 0

        printed_messages = [str(call.args[0]) for call in mock_run_deps["error_console"].print.call_args_list]
        assert any("Data Error on test.pdf" in msg for msg in printed_messages)
        assert any("Cannot export due to model error: Inference failed halfway." in msg for msg in printed_messages)


def test_run_model_export_missing_schema_id(mock_run_deps):
    """Tests that exporting fails gracefully if the result lacks a schema_id."""

    mock_result = RunModelResult(
        name="MockModel",
        source=AnnotationModelSource(type="Model", id="mock/model", version="1.0.0"),
        records=[{"summary": "Processed successfully"}],
        schema_id=None,
    )
    mock_run_deps["run_logic"].return_value = mock_result

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file), "--export", "md"])

        assert result.exit_code == 0

        printed_messages = [str(call.args[0]) for call in mock_run_deps["error_console"].print.call_args_list]
        assert any("Data Error on test.pdf" in msg for msg in printed_messages)
        assert any("Missing schema_id for export." in msg for msg in printed_messages)


def test_run_model_json_and_export_conflict():
    """Covers the Typer BadParameter raise when both --json and --export are provided."""
    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file), "--json", "--export", "txt"])

        assert result.exit_code != 0
        assert "cannot use" in result.output
        assert "at the same time" in result.output
        assert "standard output" in result.output


def test_run_model_empty_directory(mock_run_deps, mocker):
    """Covers the exit_cli and error print when no readable files are found in a directory."""
    mocker.patch("dorsal.common.cli.exit_cli", side_effect=typer.Exit(1))

    with runner.isolated_filesystem():
        empty_dir = pathlib.Path("empty_dir")
        empty_dir.mkdir()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(empty_dir)])

        assert result.exit_code != 0

        printed_messages = [str(call.args[0]) for call in mock_run_deps["error_console"].print.call_args_list]
        assert any("No readable files found in target path" in msg for msg in printed_messages)


def test_run_model_install_check_aborted(mock_run_deps):
    """Covers the `except typer.Exit: raise` block when a user aborts the install prompt."""
    mock_run_deps["is_installed"].return_value = False
    mock_run_deps["check_safety"].side_effect = typer.Exit(1)

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file)])

        assert result.exit_code != 0
        mock_run_deps["run_logic"].assert_not_called()


def test_run_model_install_check_exception_passed(mock_run_deps):
    """Covers the `except Exception: pass` block if resolution or checking fails non-fatally."""
    mock_run_deps["is_installed"].return_value = False
    mock_run_deps["check_safety"].side_effect = Exception("Random unexpected error")

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file)])

        assert result.exit_code == 0
        mock_run_deps["run_logic"].assert_called_once()


def test_run_model_export_empty_record(mock_run_deps):
    """Covers the ValueError raise when a model returns no record dictionary to export."""
    mock_result = RunModelResult(
        name="MockModel",
        source=AnnotationModelSource(type="Model", id="mock/model", version="1.0.0"),
        records=[],
        schema_id="mock/schema",
    )
    mock_run_deps["run_logic"].return_value = mock_result

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file), "--export", "md"])

        assert result.exit_code == 0

        printed_messages = [str(call.args[0]) for call in mock_run_deps["error_console"].print.call_args_list]
        assert any("Data Error" in msg for msg in printed_messages)
        assert any("No record data generated to export" in msg for msg in printed_messages)


def test_run_model_filename_override_single(mock_run_deps, mocker):
    """Covers --filename for JSON and export, plus --output dir creation."""
    mock_result = RunModelResult(
        name="MockModel",
        source=AnnotationModelSource(type="Model", id="mock/model", version="1.0.0"),
        records=[{"part": 1}],
        schema_id="open/generic",
    )
    mock_run_deps["run_logic"].return_value = mock_result
    mocker.patch("dorsal.api.adapters.export_record", return_value="exported text")

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(
            cli_app,
            [
                "run",
                "dorsal/scanner",
                str(test_file),
                "--output",
                "my_dir",
                "--filename",
                "custom_name",
                "--export",
                "txt",
            ],
        )

        assert result.exit_code == 0
        assert pathlib.Path("my_dir").is_dir()
        assert pathlib.Path("my_dir/custom_name.dorsal.json").exists()
        assert pathlib.Path("my_dir/custom_name.txt").exists()


def test_run_model_batch_filename_warning(mock_run_deps):
    """Covers the warning when --filename is used with a directory of files."""
    with runner.isolated_filesystem():
        test_dir = pathlib.Path("batch_input")
        test_dir.mkdir()
        (test_dir / "1.pdf").touch()
        (test_dir / "2.pdf").touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_dir), "--filename", "ignored_name"])

        assert result.exit_code == 0
        printed_messages = [str(call.args[0]) for call in mock_run_deps["error_console"].print.call_args_list]
        assert any("ignored during batch processing" in msg for msg in printed_messages)


def test_run_model_chunked_export_iteration(mock_run_deps, mocker):
    """Covers lines where len(records_to_export) > 1 loops and appends suffix _1, _2."""
    mock_result = RunModelResult(
        name="MockModel",
        source=AnnotationModelSource(type="Model", id="mock/model", version="1.0.0"),
        records=[{"part": 1}, {"part": 2}],
        schema_id="open/generic",
    )
    mock_run_deps["run_logic"].return_value = mock_result
    mock_export = mocker.patch("dorsal.api.adapters.export_record", return_value="chunked")

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file), "--export", "txt"])

        assert result.exit_code == 0
        assert mock_export.call_count == 2

        printed_messages = [str(call.args[0]) for call in mock_run_deps["error_console"].print.call_args_list]
        assert any("test_1.txt" in msg for msg in printed_messages)
        assert any("test_2.txt" in msg for msg in printed_messages)


def test_run_model_chunked_export_merge(mock_run_deps, mocker):
    """Covers chunked export combined with the --merge flag."""
    mock_result = RunModelResult(
        name="MockModel",
        source=AnnotationModelSource(type="Model", id="mock/model", version="1.0.0"),
        records=[{"part": 1}, {"part": 2}],
        schema_id="open/generic",
    )
    mock_run_deps["run_logic"].return_value = mock_result
    mock_merge = mocker.patch("dorsal.file.chunking.merge_chunked_records", return_value={"merged": "yes"})
    mock_export = mocker.patch("dorsal.api.adapters.export_record", return_value="merged text")

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file), "--export", "txt", "--merge"])

        assert result.exit_code == 0
        mock_merge.assert_called_once()
        assert mock_export.call_count == 1

        printed_messages = [str(call.args[0]) for call in mock_run_deps["error_console"].print.call_args_list]
        assert any("test.txt" in msg for msg in printed_messages)


def test_run_model_auth_error_propagation(mock_run_deps):
    """Covers AuthError caught from the inner loop."""
    mock_result = RunModelResult(
        name="MockModel",
        source=AnnotationModelSource(type="Model", id="mock/model", version="1.0.0"),
        records=[],
        schema_id="open/generic",
        error="Authentication failed: token expired",
    )
    mock_run_deps["run_logic"].return_value = mock_result

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file)])

        # Typer catches unhandled explicit raises and stores them in result.exception
        assert isinstance(result.exception, AuthError)


def test_run_model_outer_unhandled_exception_json(mock_rich_console, mock_run_deps, mocker):
    """Covers the global catch-all exception block formatted for --json."""
    mocker.patch("rich.progress.Progress.__enter__", side_effect=Exception("Outer catastrophic crash"))

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file), "--json"])

        assert result.exit_code != 0
        error_json = str(mock_run_deps["error_console"].print.call_args.args[0])
        assert "Outer catastrophic crash" in error_json


def test_run_model_batch_export_failed_row(mock_run_deps, mocker):
    """Covers batch table displaying the 'Failed' text for export errors."""
    mocker.patch("dorsal.api.adapters.export_record", side_effect=DorsalError("Adapter crashed"))

    with runner.isolated_filesystem():
        test_dir = pathlib.Path("batch_dir")
        test_dir.mkdir()
        (test_dir / "1.pdf").touch()
        (test_dir / "2.pdf").touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_dir), "--export", "txt"])

        assert result.exit_code == 0


def test_run_model_borders_none_padding(mock_run_deps):
    """Covers applying padding to the table when borders are None."""
    from dorsal.cli.themes.borders import get_borders

    old_borders = DUMMY_UI_CONTEXT["borders"]
    DUMMY_UI_CONTEXT["borders"] = get_borders("none")

    try:
        with runner.isolated_filesystem():
            test_dir = pathlib.Path("batch_dir")
            test_dir.mkdir()
            (test_dir / "1.pdf").touch()
            (test_dir / "2.pdf").touch()

            result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_dir)])
            assert result.exit_code == 0
    finally:
        DUMMY_UI_CONTEXT["borders"] = old_borders


def test_run_model_outer_typer_exit(mock_run_deps, mocker):
    """Covers propagating typer.Exit from the outer execution loop."""
    mocker.patch("rich.progress.Progress.__enter__", side_effect=typer.Exit(42))

    with runner.isolated_filesystem():
        test_file = pathlib.Path("test.pdf")
        test_file.touch()

        result = runner.invoke(cli_app, ["run", "dorsal/scanner", str(test_file)])
        assert result.exit_code == 42
