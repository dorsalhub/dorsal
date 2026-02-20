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

import datetime
import pytest
import typer
from unittest.mock import MagicMock
from rich.panel import Panel

from dorsal.cli.model_app.checks import check_and_confirm_model_install
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.common.exceptions import NotFoundError


@pytest.fixture
def mock_checks_deps(mocker, mock_rich_console):
    """
    Mocks backend dependencies for the model installation checks.
    Targeting patches locally within the module to prevent network leakage.
    """

    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_rich_console)

    mock_get_client = mocker.patch("dorsal.session.get_shared_dorsal_client")
    mock_client_instance = mock_get_client.return_value

    mock_reg_data = MagicMock()
    mock_reg_data.namespace = "dorsal"
    mock_reg_data.name = "gpt-neo"
    mock_reg_data.is_official = True
    mock_reg_data.is_verified = True
    mock_reg_data.description = "A powerful mocked model."
    mock_reg_data.install_url = "git+https://github.com/dorsal/gpt-neo.git"
    mock_reg_data.created_at = datetime.datetime.now()

    mock_client_instance.get_registry_model.return_value = mock_reg_data

    mock_is_registry_id = mocker.patch("dorsal.registry.validators.is_registry_id", return_value=True)

    mock_shutil_which = mocker.patch("dorsal.cli.model_app.checks.shutil.which", return_value="/usr/bin/git")

    mock_confirm = mocker.patch("dorsal.cli.model_app.checks.Confirm.ask", return_value=True)

    return {
        "client": mock_client_instance,
        "reg_data": mock_reg_data,
        "is_registry_id": mock_is_registry_id,
        "shutil_which": mock_shutil_which,
        "confirm": mock_confirm,
    }


def test_check_install_verified_registry_model(mock_rich_console, mock_checks_deps):
    """Tests check logic for a verified model from the registry."""
    check_and_confirm_model_install("dorsal/gpt-neo", DEFAULT_PALETTE)

    mock_checks_deps["client"].get_registry_model.assert_called_once_with("dorsal/gpt-neo")

    assert mock_rich_console.print.called
    panel = mock_rich_console.print.call_args.args[0]
    assert "Verified" in panel.renderable
    assert "gpt-neo" in panel.renderable


def test_check_install_unverified_warning(mock_rich_console, mock_checks_deps):
    """Tests that unverified models trigger the Safety Warning."""
    mock_checks_deps["reg_data"].is_official = False
    mock_checks_deps["reg_data"].is_verified = False

    check_and_confirm_model_install("user/experimental-model", DEFAULT_PALETTE)

    panel = mock_rich_console.print.call_args.args[0]
    assert "Unverified" in panel.renderable
    assert "Safety Warning" in panel.renderable


def test_check_install_skip_via_flags(mock_rich_console, mock_checks_deps):
    """Tests that 'force' or 'yes' flags bypass checks entirely."""
    check_and_confirm_model_install("dorsal/gpt-neo", DEFAULT_PALETTE, yes=True)

    mock_checks_deps["client"].get_registry_model.assert_not_called()
    assert not mock_rich_console.print.called


def test_check_install_missing_git_dependency(mock_rich_console, mock_checks_deps):
    """Tests handling of models requiring Git when Git is missing."""
    mock_checks_deps["shutil_which"].return_value = None

    with pytest.raises(typer.Exit):
        check_and_confirm_model_install("dorsal/gpt-neo", DEFAULT_PALETTE)

    panel_calls = [c for c in mock_rich_console.print.call_args_list if isinstance(c.args[0], Panel)]
    assert len(panel_calls) > 0, "Missing System Dependency Panel was never printed"

    panel = panel_calls[0].args[0]
    assert "Missing System Dependency" in str(panel.title)
    assert "requires Git to install" in str(panel.renderable)


def test_check_install_registry_not_found(mock_rich_console, mock_checks_deps):
    """Tests 404 error handling from the registry."""
    mock_checks_deps["client"].get_registry_model.side_effect = NotFoundError("404 Not Found")

    with pytest.raises(typer.Exit):
        check_and_confirm_model_install("dorsal/missing", DEFAULT_PALETTE)

    assert "Model 'dorsal/missing' not found in registry" in str(mock_rich_console.print.call_args.args[0])


def test_check_install_user_cancels(mock_rich_console, mock_checks_deps):
    """Tests that the user can decline the confirmation prompt."""
    mock_checks_deps["confirm"].return_value = False

    with pytest.raises(typer.Exit):
        check_and_confirm_model_install("dorsal/gpt-neo", DEFAULT_PALETTE)

    assert "Cancelled" in str(mock_rich_console.print.call_args.args[0])


def test_check_install_pipx_note(mock_rich_console, mock_checks_deps, mocker):
    """Tests that a note is displayed when running in a pipx environment."""
    mocker.patch("sys.prefix", "/home/user/.local/pipx/venvs/dorsal")

    check_and_confirm_model_install("dorsal/gpt-neo", DEFAULT_PALETTE)

    printed_text = str(mock_rich_console.print.call_args_list[0].args[0])
    assert "running inside a pipx environment" in printed_text
