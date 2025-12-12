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


import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from typer.testing import CliRunner
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


from dorsal.cli import app
from dorsal.common.auth import APIKeySource, APIKeyDetails

runner = CliRunner()


@pytest.fixture
def mock_config_app(mocker):
    """
    Mocks all backend dependencies for the `dorsal config` commands.
    """
    mocker.patch("dorsal.api.config.load_config", return_value=({}, Path("/fake/path/dorsal.toml")))
    mocker.patch("dorsal.api.config.get_global_config_path", return_value=Path("/fake/global/dorsal.toml"))

    mocker.patch("dorsal.api.config.get_email_from_config", return_value="test@example.com")
    mocker.patch("dorsal.api.config.get_theme_from_config", return_value="default")

    mocker.patch(
        "dorsal.api.config.get_api_key_details",
        return_value={
            "source": APIKeySource.PROJECT,
            "value": "fake_key",
            "path": Path("/fake/path/dorsal.toml"),
        },
    )

    mocker.patch("dorsal.api.config.constants.BASE_URL", "https://api.dorsal.ai/v2")

    mocker.patch("dorsal.cli.themes.palettes.BUILT_IN_PALETTES", {"default": {}, "dark": {}})
    mocker.patch("dorsal.cli.themes.palettes._load_custom_palettes", return_value={})
    mocker.patch("dorsal.common.auth.write_theme_to_config")

    mocker.patch("dorsal.common.constants.LOCAL_DORSAL_DIR", Path("/fake/dorsal/dir"))


@patch("rich.table.Table.grid")
def test_show_config_logged_in(mock_table_grid, mock_rich_console, mock_config_app):
    """Tests `config show` output when the user is logged in."""
    mock_table = MagicMock()
    mock_table_grid.return_value = mock_table

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0
    all_rows_text = ""
    for call in mock_table.add_row.call_args_list:
        all_rows_text += " ".join(str(arg) for arg in call.args)

    assert "test@example.com" in all_rows_text
    assert "project config" in all_rows_text


@patch("rich.table.Table.grid")
def test_show_config_logged_out(mock_table_grid, mocker, mock_rich_console, mock_config_app):
    """Tests `config show` output when the user is logged out."""
    mock_table = MagicMock()
    mock_table_grid.return_value = mock_table

    mocker.patch(
        "dorsal.api.config.get_api_key_details",
        return_value={"source": APIKeySource.NONE, "value": None, "path": None},
    )
    mocker.patch("dorsal.api.config.get_email_from_config", return_value=None)

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0
    all_rows_text = ""
    for call in mock_table.add_row.call_args_list:
        all_rows_text += " ".join(str(arg) for arg in call.args)

    assert "Not Set" in all_rows_text
    assert "N/A (run 'dorsal auth login')" in all_rows_text


def test_show_config_json_output(mock_rich_console, mock_config_app):
    """Tests `config show --json` output."""
    result = runner.invoke(app, ["config", "show", "--json"])

    assert result.exit_code == 0
    json_output_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_output_str)

    assert data["api_key_set"] is True
    assert "project config" in data["api_key_source"]
    assert data["logged_in_user"] == "test@example.com"


def test_list_themes_built_in_only(mock_rich_console, mock_config_app):
    """Tests `config theme list` with only built-in themes."""
    result = runner.invoke(app, ["config", "theme", "list"])

    assert result.exit_code == 0
    panel_output = mock_rich_console.print.call_args.args[0]
    group_renderables = panel_output.renderable.renderables

    all_text_content = []
    for r in group_renderables:
        if isinstance(r, Panel):
            all_text_content.append(str(r.title))
        else:
            all_text_content.append(str(r))

    combined_text = "".join(all_text_content)

    assert "Built-in Themes" in combined_text
    assert "Custom Themes" not in combined_text


def test_list_themes_with_custom(mocker, mock_rich_console, mock_config_app):
    """Tests `config theme list` with custom themes present."""
    mocker.patch(
        "dorsal.cli.themes.palettes._load_custom_palettes",
        return_value={"my_theme": {}},
    )

    result = runner.invoke(app, ["config", "theme", "list"])

    assert result.exit_code == 0
    panel_output = mock_rich_console.print.call_args.args[0]
    group_renderables = panel_output.renderable.renderables

    all_text_content = []
    for r in group_renderables:
        if isinstance(r, Panel):
            all_text_content.append(str(r.title))
        elif isinstance(r, str):
            all_text_content.append(r)
        elif isinstance(r, Text):
            all_text_content.append(r.plain)

    combined_text = "".join(all_text_content)

    assert "Built-in Themes" in combined_text
    assert "Custom Themes" in combined_text
    assert "my_theme" in combined_text


def test_set_theme_success(mock_rich_console, mock_config_app):
    """Tests successfully setting a valid theme."""
    result = runner.invoke(app, ["config", "theme", "set", "dark"])

    assert result.exit_code == 0
    from dorsal.common.auth import write_theme_to_config

    write_theme_to_config.assert_called_once_with("dark")
    success_message = str(mock_rich_console.print.call_args.args[0])
    assert "Default theme set to 'dark'" in success_message


def test_set_theme_not_found(mock_rich_console, mock_config_app):
    """Tests setting a theme that does not exist."""
    result = runner.invoke(app, ["config", "theme", "set", "invalid_theme"])

    assert result.exit_code != 0
    error_message = str(mock_rich_console.print.call_args.args[0])
    assert "Theme 'invalid_theme' not found" in error_message


def test_set_theme_os_error(mocker, mock_rich_console, mock_config_app):
    """Tests handling of an OSError when writing the theme config."""
    mocker.patch(
        "dorsal.common.auth.write_theme_to_config",
        side_effect=OSError("Permission denied"),
    )

    result = runner.invoke(app, ["config", "theme", "set", "dark"])

    assert result.exit_code != 0
    assert "Error saving configuration: Permission denied" in result.output


@pytest.fixture
def mock_pipeline_api(mocker):
    """Mocks the API functions used by the pipeline CLI."""
    return {
        "show": mocker.patch("dorsal.api.config.show_model_pipeline"),
        "remove_idx": mocker.patch("dorsal.api.config.remove_model_by_index"),
        "remove_name": mocker.patch("dorsal.api.config.remove_model_by_name"),
        "activate_idx": mocker.patch("dorsal.api.config.activate_model_by_index"),
        "activate_name": mocker.patch("dorsal.api.config.activate_model_by_name"),
        "deactivate_idx": mocker.patch("dorsal.api.config.deactivate_model_by_index"),
        "deactivate_name": mocker.patch("dorsal.api.config.deactivate_model_by_name"),
        "get_steps": mocker.patch("dorsal.api.config.get_model_pipeline"),
        "import_callable": mocker.patch("dorsal.common.validators.import_callable"),
    }


def test_pipeline_show_empty(mock_rich_console, mock_pipeline_api):
    """Tests `config pipeline show` when empty."""
    mock_pipeline_api["show"].return_value = []

    result = runner.invoke(app, ["config", "pipeline", "show"])

    assert result.exit_code == 0
    assert "pipeline is currently empty" in str(mock_rich_console.print.call_args.args[0].renderable)


def test_pipeline_show_populated(mock_rich_console, mock_pipeline_api):
    """Tests `config pipeline show` with data."""
    mock_pipeline_api["show"].return_value = [
        {
            "index": 0,
            "status": "Base (Locked)",
            "name": "BaseModel",
            "module": "dorsal.annotation_models",
            "schema_id": "base",
            "dependencies": "None",
        },
        {
            "index": 1,
            "status": "Deactivated",
            "name": "CustomModel",
            "module": "my.pkg",
            "schema_id": "custom",
            "dependencies": "pdf",
        },
    ]

    result = runner.invoke(app, ["config", "pipeline", "show"])

    assert result.exit_code == 0
    assert "Annotation Model Pipeline" in str(mock_rich_console.print.call_args.args[0].title)


@pytest.mark.parametrize(
    "command, api_idx, api_name, verb",
    [
        ("remove", "remove_idx", "remove_name", "removed"),
        ("activate", "activate_idx", "activate_name", "activated"),
        ("deactivate", "deactivate_idx", "deactivate_name", "deactivated"),
    ],
)
def test_pipeline_actions(mock_rich_console, mock_pipeline_api, command, api_idx, api_name, verb):
    """Generic test for remove/activate/deactivate by index and name."""

    # 1. Test by Index
    result_idx = runner.invoke(app, ["config", "pipeline", command, "1"])
    assert result_idx.exit_code == 0
    mock_pipeline_api[api_idx].assert_called_with(index=1)
    assert f"Successfully {verb} model at index 1" in str(mock_rich_console.print.call_args.args[0])

    # 2. Test by Name
    result_name = runner.invoke(app, ["config", "pipeline", command, "MyModel"])
    assert result_name.exit_code == 0
    mock_pipeline_api[api_name].assert_called_with(name="MyModel")
    assert f"Successfully {verb} model 'MyModel'" in str(mock_rich_console.print.call_args.args[0])


def test_pipeline_action_error(mock_rich_console, mock_pipeline_api):
    """Test error handling in pipeline actions."""
    mock_pipeline_api["remove_idx"].side_effect = IndexError("Index out of range")

    result = runner.invoke(app, ["config", "pipeline", "remove", "99"])

    assert result.exit_code != 0
    assert "Error: Index out of range" in str(mock_rich_console.print.call_args.args[0])


def test_pipeline_check_clean(mock_rich_console, mock_pipeline_api):
    """Tests `config pipeline check` when everything is fine."""
    # Mock step objects
    step1 = MagicMock()
    step1.annotation_model = "valid.path"
    step1.validation_model = None

    mock_pipeline_api["get_steps"].return_value = [MagicMock(), step1]  # index 0 skipped

    result = runner.invoke(app, ["config", "pipeline", "check"])

    assert result.exit_code == 0
    assert "All pipeline models are importable" in str(mock_rich_console.print.call_args.args[0])


def test_pipeline_check_broken_with_fix(mock_rich_console, mock_pipeline_api):
    """Tests `config pipeline check --fix` with broken models."""
    # Setup broken step
    step_broken = MagicMock()
    step_broken.annotation_model.name = "BrokenModel"
    # Mock get_steps returning [base, broken]
    mock_pipeline_api["get_steps"].return_value = [MagicMock(), step_broken]

    mock_pipeline_api["import_callable"].side_effect = ImportError("Missing module")

    # Run with --fix
    result = runner.invoke(app, ["config", "pipeline", "check", "--fix"])

    assert result.exit_code == 0

    # Verify output
    output_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Found 1 broken models" in output_text
    assert "Removed broken model 'BrokenModel'" in output_text

    # Verify removal call (Index 1)
    mock_pipeline_api["remove_idx"].assert_called_with(index=1)


def test_pipeline_check_broken_no_fix(mock_rich_console, mock_pipeline_api):
    """Tests `config pipeline check` (no fix) exits with error."""
    step_broken = MagicMock()
    step_broken.annotation_model.name = "BrokenModel"
    mock_pipeline_api["get_steps"].return_value = [MagicMock(), step_broken]
    mock_pipeline_api["import_callable"].side_effect = ImportError("Missing module")

    result = runner.invoke(app, ["config", "pipeline", "check"])

    # Should fail exit code
    assert result.exit_code != 0

    output_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "--fix" in output_text
    assert "automatically remove" in output_text

    # Verify NO removal called
    mock_pipeline_api["remove_idx"].assert_not_called()
