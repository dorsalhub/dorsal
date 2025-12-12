# Copyright 2025 Dorsal Hub LTD
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

import typer
import pytest
from pathlib import Path
from typer.testing import CliRunner
from dorsal.cli.file_app.report_cmd import make_file_report
from dorsal.common.exceptions import DorsalError
from dorsal.common.cli import EXIT_CODE_ERROR


@pytest.fixture
def test_app():
    app = typer.Typer()

    @app.callback()
    def main(ctx: typer.Context):
        ctx.obj = {"palette": {"primary_value": "green", "key": "cyan", "panel_title": "white", "panel_border": "blue"}}

    app.command(name="report")(make_file_report)
    return app


@pytest.fixture
def runner():
    return CliRunner()


def test_report_success_default(runner, test_app, tmp_path, mocker):
    """
    Test happy path: existing file, default output, implicit cache settings.
    """
    target_file = tmp_path / "data.csv"
    target_file.write_text("content")

    mock_generate = mocker.patch("dorsal.cli.file_app.report_cmd.generate_html_file_report")
    mock_console = mocker.patch("dorsal.cli.file_app.report_cmd.get_rich_console")
    mocker.patch("dorsal.cli.file_app.report_cmd.determine_use_cache_value", return_value=True)

    result = runner.invoke(test_app, ["report", str(target_file)])

    assert result.exit_code == 0

    mock_generate.assert_called_once()
    call_args = mock_generate.call_args[1]
    assert call_args["file_path"] == str(target_file)
    assert call_args["use_cache"] is True
    assert "scan" in call_args["output_path"]

    # Success messages typically go to stdout
    assert "Report saved successfully" in str(mock_console.return_value.print.call_args)


def test_report_conflict_flags(runner, test_app, tmp_path):
    """
    Test that mutually exclusive flags (--use-cache and --skip-cache) trigger an exit.
    """
    target_file = tmp_path / "test.txt"
    target_file.touch()

    result = runner.invoke(test_app, ["report", str(target_file), "--use-cache", "--skip-cache"])

    assert result.exit_code != 0
    assert "Error: --use-cache and --skip-cache cannot be used together" in result.stderr


def test_report_custom_output_directory(runner, test_app, tmp_path, mocker):
    target_file = tmp_path / "dataset.csv"
    target_file.touch()

    output_dir = tmp_path / "reports"
    output_dir.mkdir()

    mock_generate = mocker.patch("dorsal.cli.file_app.report_cmd.generate_html_file_report")
    mocker.patch("dorsal.cli.file_app.report_cmd.get_rich_console")

    result = runner.invoke(test_app, ["report", str(target_file), "--output", str(output_dir)])

    assert result.exit_code == 0

    actual_output = mock_generate.call_args[1]["output_path"]
    assert str(output_dir) in actual_output
    assert "dataset_report.html" in actual_output


def test_report_api_error_handling(runner, test_app, tmp_path, mocker):
    """
    Test that exceptions raised by the logic layer are caught and formatted nicely.
    """
    target_file = tmp_path / "corrupt.file"
    target_file.touch()

    mocker.patch(
        "dorsal.cli.file_app.report_cmd.generate_html_file_report", side_effect=DorsalError("File is encrypted")
    )
    mocker.patch("dorsal.cli.file_app.report_cmd.get_rich_console")

    result = runner.invoke(test_app, ["report", str(target_file)])

    assert result.exit_code != 0
    assert "Failed to generate report" in result.stderr
    assert "File is encrypted" in result.stderr


def test_report_unexpected_error(runner, test_app, tmp_path, mocker):
    """
    Test handling of generic/unexpected exceptions.
    """
    target_file = tmp_path / "oops.file"
    target_file.touch()

    mocker.patch(
        "dorsal.cli.file_app.report_cmd.generate_html_file_report",
        side_effect=ValueError("Something went really wrong"),
    )
    mocker.patch("dorsal.cli.file_app.report_cmd.get_rich_console")

    result = runner.invoke(test_app, ["report", str(target_file)])

    assert result.exit_code != 0
    assert "An unexpected error occurred" in result.stderr


def test_report_open_in_browser(runner, test_app, tmp_path, mocker):
    target_file = tmp_path / "viz.data"
    target_file.touch()

    mocker.patch("dorsal.cli.file_app.report_cmd.generate_html_file_report")
    mocker.patch("dorsal.cli.file_app.report_cmd.get_rich_console")

    mock_browser = mocker.patch("webbrowser.open")

    result = runner.invoke(test_app, ["report", str(target_file), "--open"])

    assert result.exit_code == 0
    mock_browser.assert_called_once()
    assert "file://" in mock_browser.call_args[0][0]


def test_file_not_found_handled_by_typer(runner, test_app):
    """
    Test that Typer automatically handles non-existent files
    because of `exists=True` in the Argument definition.
    """
    result = runner.invoke(test_app, ["report", "ghost_file.txt"])

    assert result.exit_code != 0
    assert "does not exist" in result.stderr
