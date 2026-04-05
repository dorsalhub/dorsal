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

import logging
import pytest
import runpy
from typer.testing import CliRunner

import dorsal
from dorsal.common.exceptions import AuthError, DorsalOfflineError
from dorsal.cli.__init__ import app, cli_app, _extract_global_flag

runner = CliRunner()


def test_version_flag(mock_rich_console):
    """Test that the version flag prints correctly and exits."""
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    mock_rich_console.print.assert_called_once()
    assert "Dorsal" in mock_rich_console.print.call_args[0][0]


@pytest.mark.parametrize(
    "args, expected_level",
    [
        ([], logging.WARNING),
        (["-v"], logging.INFO),
        (["-vv"], logging.DEBUG),
        (["-vvv"], logging.DEBUG),
    ],
)
def test_main_verbose_logging(args, expected_level, mocker):
    """Test the verbosity flag routes to the correct logging levels."""

    mock_basic_config = mocker.patch("logging.basicConfig")

    @app.command(name="test-verbose-dummy", hidden=True)
    def dummy():
        pass

    result = runner.invoke(app, args + ["test-verbose-dummy"])
    assert result.exit_code == 0

    assert mock_basic_config.call_args.kwargs["level"] == expected_level


def test_main_json_logging(monkeypatch, mocker):
    """Test the --json flag forces CRITICAL logging and stderr console."""
    mock_basic_config = mocker.patch("logging.basicConfig")
    monkeypatch.setattr("sys.argv", ["dorsal", "--json", "test-json-dummy"])

    @app.command(name="test-json-dummy", hidden=True)
    def dummy():
        pass

    result = runner.invoke(app, ["test-json-dummy"])
    assert result.exit_code == 0

    assert mock_basic_config.call_args.kwargs["level"] == logging.CRITICAL


def test_extract_global_flag(monkeypatch):
    """Test the custom sys.argv parsing function handles both syntaxes."""
    monkeypatch.setattr("sys.argv", ["dorsal", "--theme", "dark", "--icons=emoji"])

    assert _extract_global_flag("--theme") == "dark"
    assert _extract_global_flag("--icons") == "emoji"
    assert _extract_global_flag("--borders") is None


def test_cli_app_auth_error(monkeypatch, mock_rich_console):
    """Test that AuthError is caught and handled correctly by the main wrapper."""

    @app.command(name="trigger-auth", hidden=True)
    def trigger_auth():
        raise AuthError("Not logged in!")

    monkeypatch.setattr("sys.argv", ["dorsal", "--theme", "dark", "trigger-auth"])

    with pytest.raises(SystemExit) as exc_info:
        cli_app()

    assert exc_info.value.code == 1


def test_cli_app_offline_error(monkeypatch, mock_rich_console):
    """Test that DorsalOfflineError is caught and handled correctly by the main wrapper."""

    @app.command(name="trigger-offline", hidden=True)
    def trigger_offline():
        raise DorsalOfflineError("Offline mode active!")

    monkeypatch.setattr("sys.argv", ["dorsal", "--borders", "heavy", "trigger-offline"])

    with pytest.raises(SystemExit) as exc_info:
        cli_app()

    assert exc_info.value.code == 1


def test_main_execution_block(monkeypatch):
    monkeypatch.setattr("sys.argv", ["dorsal", "--help"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(dorsal.cli.__file__, run_name="__main__")

    assert exc_info.value.code == 0
