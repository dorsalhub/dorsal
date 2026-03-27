# Copyright 2025-2026 Dorsal Hub LTD
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

import pathlib
from unittest.mock import MagicMock, ANY

import pytest
import typer
from typer.testing import CliRunner

from dorsal.cli import app
from dorsal.common.exceptions import DorsalError

runner = CliRunner()


@pytest.fixture
def mock_rich_console(mocker):
    mock_console = MagicMock()
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_console)
    mocker.patch("dorsal.cli.local_app.report_cmd.get_rich_console", return_value=mock_console)
    return mock_console


@pytest.fixture
def mock_exit_cli(mocker):
    def _side_effect(code=0, message=None):
        raise typer.Exit(code)

    return mocker.patch("dorsal.cli.local_app.report_cmd.exit_cli", side_effect=_side_effect)


@pytest.fixture
def mock_generators(mocker):
    mock_file_gen = mocker.patch("dorsal.api.file.generate_html_file_report")
    mock_dir_gen = mocker.patch("dorsal.api.file.generate_html_directory_report")
    return {"file": mock_file_gen, "dir": mock_dir_gen}


@pytest.fixture
def mock_webbrowser(mocker):
    return mocker.patch("webbrowser.open")


def test_report_cache_conflict(mock_exit_cli, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    result = runner.invoke(app, ["local", "report", str(target), "--use-cache", "--skip-cache"])
    assert result.exit_code != 0
    mock_exit_cli.assert_called_with(code=ANY, message="Error: --use-cache and --skip-cache cannot be used together.")


def test_report_file_success(mock_rich_console, mock_generators, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()

    result = runner.invoke(app, ["local", "report", str(target)])

    assert result.exit_code == 0
    mock_generators["file"].assert_called_once()
    mock_generators["dir"].assert_not_called()

    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Report saved successfully" in printed_text


def test_report_file_ignored_dir_flags(mock_rich_console, mock_generators, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()

    runner.invoke(app, ["local", "report", str(target), "--recursive"])

    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Directory-specific flags (--recursive) are ignored" in printed_text


def test_report_dir_success(mock_rich_console, mock_generators, tmp_path):
    target = tmp_path / "test_dir"
    target.mkdir()

    result = runner.invoke(app, ["local", "report", str(target), "--recursive"])

    assert result.exit_code == 0
    mock_generators["dir"].assert_called_once_with(
        dir_path=str(target),
        output_path=ANY,
        template="default",
        use_cache=True,  # default returned by determine_use_cache_value if no flags passed
        recursive=True,
    )
    mock_generators["file"].assert_not_called()


def test_report_output_inference(mock_generators, tmp_path):
    """Tests generating paths when --output is a directory vs an exact file."""
    target_file = tmp_path / "test.txt"
    target_file.touch()
    target_dir = tmp_path / "test_dir"
    target_dir.mkdir()

    out_dir = tmp_path / "reports"
    out_dir.mkdir()

    # Output to directory (File Target)
    runner.invoke(app, ["local", "report", str(target_file), "--output", str(out_dir)])
    expected_file_path = out_dir / "test_report.html"
    mock_generators["file"].assert_called_with(
        file_path=str(target_file), output_path=str(expected_file_path), template=ANY, use_cache=ANY
    )

    # Output to directory (Directory Target)
    runner.invoke(app, ["local", "report", str(target_dir), "--output", str(out_dir)])
    expected_dir_path = out_dir / "dir-test_dir_report.html"
    mock_generators["dir"].assert_called_with(
        dir_path=str(target_dir), output_path=str(expected_dir_path), template=ANY, use_cache=ANY, recursive=ANY
    )


def test_report_open_browser_success(mock_generators, mock_webbrowser, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()

    runner.invoke(app, ["local", "report", str(target), "--open"])
    mock_webbrowser.assert_called_once()
    assert "file://" in mock_webbrowser.call_args.args[0]


def test_report_open_browser_failure(mock_rich_console, mock_generators, mock_webbrowser, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    mock_webbrowser.side_effect = Exception("No browser found")

    runner.invoke(app, ["local", "report", str(target), "--open"])

    printed_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Could not automatically open the report" in printed_text


def test_report_dorsal_error(mock_exit_cli, mock_generators, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    mock_generators["file"].side_effect = DorsalError("Template not found")

    runner.invoke(app, ["local", "report", str(target)])
    mock_exit_cli.assert_called()
    assert "Failed to generate report: Template not found" in mock_exit_cli.call_args.kwargs["message"]


def test_report_generic_error(mock_exit_cli, mock_generators, tmp_path):
    target = tmp_path / "test.txt"
    target.touch()
    mock_generators["file"].side_effect = Exception("OS Crash")

    runner.invoke(app, ["local", "report", str(target)])
    mock_exit_cli.assert_called()
    assert "An unexpected error occurred: OS Crash" in mock_exit_cli.call_args.kwargs["message"]
