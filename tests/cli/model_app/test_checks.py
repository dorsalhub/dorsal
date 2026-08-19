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

import sys
import pytest
import typer
from unittest.mock import MagicMock

from rich.box import ROUNDED
from rich.panel import Panel

from dorsal.cli.model_app.checks import check_and_confirm_model_install
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.api.model import ModelTargetResolution, ModelMetadata

DUMMY_UI_CONTEXT = {"palette": DEFAULT_PALETTE, "icons": {}, "borders": ROUNDED}


@pytest.fixture
def mock_checks_deps(mocker, mock_rich_console):
    """
    Mocks backend dependencies for the model installation checks.
    """
    mocker.patch("dorsal.common.cli.get_rich_console", return_value=mock_rich_console)
    mocker.patch("dorsal.common.cli.get_error_console", return_value=mock_rich_console)

    mock_shutil_which = mocker.patch("dorsal.cli.model_app.checks.shutil.which", return_value="/usr/bin/git")
    mock_confirm = mocker.patch("dorsal.cli.model_app.checks.Confirm.ask", return_value=True)

    return {
        "shutil_which": mock_shutil_which,
        "confirm": mock_confirm,
    }


def test_check_install_verified_registry_model(mock_rich_console, mock_checks_deps):
    """Tests that verified models silently bypass the security prompt."""
    res = ModelTargetResolution(
        target="dorsal/gpt-neo",
        strategy="registry_id",
        metadata=ModelMetadata(is_official=True, is_verified=True, description="A powerful mocked model."),
    )

    check_and_confirm_model_install(res, DUMMY_UI_CONTEXT)

    assert not mock_rich_console.print.called


def test_check_install_unverified_warning(mock_rich_console, mock_checks_deps):
    """Tests that unverified models trigger the Safety Warning."""
    res = ModelTargetResolution(
        target="user/experimental-model",
        strategy="registry_id",
        metadata=ModelMetadata(is_official=False, is_verified=False),
    )

    check_and_confirm_model_install(res, DUMMY_UI_CONTEXT)

    panel = mock_rich_console.print.call_args.args[0]
    assert "Unverified" in panel.renderable


def test_check_install_local_path_warning(mock_rich_console, mock_checks_deps):
    """Tests that local directories always trigger the Safety Warning."""
    res = ModelTargetResolution(
        target="./my-local-model",
        strategy="local_path",
    )

    check_and_confirm_model_install(res, DUMMY_UI_CONTEXT)

    panel = mock_rich_console.print.call_args.args[0]
    assert "unverified source" in panel.renderable
    assert "Local Path" in panel.renderable


def test_check_install_skip_via_flags(mock_rich_console, mock_checks_deps):
    """Tests that 'force' or 'yes' flags bypass checks entirely."""
    res = ModelTargetResolution(
        target="user/sketchy-model",
        strategy="registry_id",
        metadata=ModelMetadata(is_official=False, is_verified=False),
    )

    check_and_confirm_model_install(res, DUMMY_UI_CONTEXT, yes=True)

    assert not mock_rich_console.print.called


def test_check_install_missing_git_dependency(mock_rich_console, mock_checks_deps):
    """Tests handling of models requiring Git when Git is missing."""
    mock_checks_deps["shutil_which"].return_value = None

    res = ModelTargetResolution(
        target="dorsal/gpt-neo",
        strategy="registry_id",
        metadata=ModelMetadata(
            is_official=False, is_verified=False, source_url="https://github.com/dorsal/gpt-neo.git"
        ),
    )

    with pytest.raises(typer.Exit):
        check_and_confirm_model_install(res, DUMMY_UI_CONTEXT)

    panel_calls = [c for c in mock_rich_console.print.call_args_list if isinstance(c.args[0], Panel)]
    assert len(panel_calls) > 0, "Missing System Dependency Panel was never printed"

    panel = panel_calls[0].args[0]
    assert "Missing System Dependency" in str(panel.title)
    assert "requires Git to install" in str(panel.renderable)


def test_check_install_user_cancels(mock_rich_console, mock_checks_deps):
    """Tests that the user can decline the confirmation prompt."""
    mock_checks_deps["confirm"].return_value = False
    res = ModelTargetResolution(target="./sketchy", strategy="local_path")

    with pytest.raises(typer.Exit):
        check_and_confirm_model_install(res, DUMMY_UI_CONTEXT)

    assert "Cancelled" in str(mock_rich_console.print.call_args.args[0])


def test_check_install_pipx_note(mock_rich_console, mock_checks_deps, mocker):
    """Tests that a note is displayed when running in a pipx environment."""
    mocker.patch("sys.prefix", "/home/user/.local/pipx/venvs/dorsal")
    res = ModelTargetResolution(target="./my-model", strategy="local_path")

    check_and_confirm_model_install(res, DUMMY_UI_CONTEXT)

    printed_text = str(mock_rich_console.print.call_args_list[0].args[0])
    assert "running inside a pipx environment" in printed_text
