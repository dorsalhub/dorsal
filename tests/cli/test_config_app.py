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


import io
import pytest
import json
from pathlib import Path
from unittest.mock import MagicMock
from typer.testing import CliRunner
from rich.console import Console

from dorsal.cli import app
from dorsal.common.auth import APIKeySource

runner = CliRunner()


def _printed(mock_console) -> str:
    """Renders everything printed to a mocked console as plain text."""
    console = Console(record=True, width=120, file=io.StringIO())
    for call in mock_console.print.call_args_list:
        console.print(*call.args)
    return console.export_text()


@pytest.fixture
def mock_config_app(mocker):
    """
    Mocks all backend dependencies for the `dorsal config` commands.
    """

    mocker.patch(
        "dorsal.common.config.load_config",
        return_value=(
            {"ui": {"theme": "dracula", "icons": "ascii", "borders": "heavy"}},
            Path("/fake/path/dorsal.toml"),
        ),
    )

    mocker.patch("dorsal.api.config.get_global_config_path", return_value=Path("/fake/global/dorsal.toml"))
    mocker.patch("dorsal.api.config.get_email_from_config", return_value="test@example.com")
    mocker.patch("dorsal.api.config.get_theme_from_config", return_value="dracula")

    mocker.patch(
        "dorsal.api.config.get_api_key_details",
        return_value={
            "source": APIKeySource.PROJECT,
            "value": "fake_key",
            "path": Path("/fake/path/dorsal.toml"),
        },
    )

    mocker.patch("dorsal.api.config.constants.BASE_URL", "https://api.dorsalhub.test/v1")

    mocker.patch("dorsal.cli.themes.palettes.BUILT_IN_PALETTES", {"default": {}, "dracula": {}})
    mocker.patch("dorsal.cli.themes.palettes._load_custom_palettes", return_value={})
    mocker.patch("dorsal.common.auth.write_ui_config")

    mocker.patch("dorsal.common.constants.LOCAL_DORSAL_DIR", Path("/fake/dorsal/dir"))


def test_show_config_logged_in(mock_rich_console, mock_config_app):
    """Tests `config show` output when the user is logged in."""
    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0
    output = _printed(mock_rich_console)

    assert "  Current theme       dracula " in output
    assert "  Current icons       ascii " in output
    assert "  Current borders     heavy " in output
    assert "  Logged-in user      test@example.com " in output
    assert "project config" in output
    assert "config file:" not in output


def test_show_config_reports_effective_ui(mock_rich_console, mock_config_app, monkeypatch):
    """Tests that `config show` reports UI settings overridden by flags and env vars, not just the config file."""
    monkeypatch.setenv("DORSAL_ICONS", "none")

    result = runner.invoke(app, ["--borders", "none", "--theme", "default", "config", "show"])

    assert result.exit_code == 0
    output = _printed(mock_rich_console)
    assert "  Current icons       none  (config file: ascii)\n" in output
    assert "  Current borders     none  (config file: heavy)\n" in output


def test_show_config_logged_out(mocker, mock_rich_console, mock_config_app):
    """Tests `config show` output when the user is logged out."""
    mocker.patch(
        "dorsal.api.config.get_api_key_details",
        return_value={"source": APIKeySource.NONE, "value": None, "path": None},
    )
    mocker.patch("dorsal.api.config.get_email_from_config", return_value=None)

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0
    output = _printed(mock_rich_console)

    assert "  API key status      Not set " in output
    assert "  Logged-in user      N/A (run 'dorsal auth login') " in output


def test_show_config_json_output(mock_rich_console, mock_config_app):
    """Tests `config show --json` output."""
    result = runner.invoke(app, ["config", "show", "--json"])

    assert result.exit_code == 0
    json_output_str = mock_rich_console.print.call_args.args[0]
    data = json.loads(json_output_str)

    assert data["api_key_set"] is True
    assert "project config" in data["api_key_source"]
    assert data["logged_in_user"] == "test@example.com"


def test_show_config_bordered(mock_rich_console, mock_config_app):
    """Tests that `config show` draws a panel with the configured border style."""
    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0
    output = _printed(mock_rich_console)
    assert "┏━ Dorsal configuration" in output


def test_show_config_no_borders(mock_rich_console, mock_config_app):
    """Tests that `config show` has no box characters or trailing whitespace when borders=none."""
    result = runner.invoke(app, ["--borders", "none", "config", "show"])

    assert result.exit_code == 0
    output = _printed(mock_rich_console)
    assert not any(char in output for char in "┏━│╭─")
    assert all(line == line.rstrip() for line in output.splitlines())
    assert output.endswith("\n\nFor more detail on the pipeline config, run:\n  dorsal config pipeline show\n")


def test_list_themes_built_in_only(mock_rich_console, mock_config_app):
    """Tests `config theme list` with only built-in themes."""
    result = runner.invoke(app, ["--borders", "rounded", "config", "theme", "list"])

    assert result.exit_code == 0
    output = _printed(mock_rich_console)

    assert "╭─ Available themes" in output
    assert "Built-in themes" in output
    assert "╭─ dracula" in output
    assert "Custom themes" not in output


def test_list_themes_with_custom(mocker, mock_rich_console, mock_config_app):
    """Tests `config theme list` with custom themes present."""
    mocker.patch(
        "dorsal.cli.themes.palettes._load_custom_palettes",
        return_value={"my_theme": {}},
    )

    result = runner.invoke(app, ["--borders", "none", "config", "theme", "list"])

    assert result.exit_code == 0
    output = _printed(mock_rich_console)

    assert "Built-in themes" in output
    assert "Custom themes (from ~/.dorsal/palettes.json)\n\n  my_theme\n    Key   Primary value\n" in output


def test_list_themes_no_borders(mock_rich_console, mock_config_app):
    """Tests that borderless `config theme list` nests and separates the theme previews."""
    result = runner.invoke(app, ["--borders", "none", "config", "theme", "list"])
    assert result.exit_code == 0

    output = _printed(mock_rich_console)
    assert output.startswith(
        "Built-in themes\n"
        "\n"
        "  default\n"
        "    Key   Primary value\n"
        "    Hash  a1b2c3d4e5f62a3b4c...\n"
        "    Tags  public_tag (public)\n"
        "          private_tag (private)\n"
        "\n"
        "  dracula\n"
    )
    assert all(line == line.rstrip() for line in output.splitlines())


def test_set_ui_preferences_success(mock_rich_console, mock_config_app):
    """Tests successfully setting multiple valid UI preferences."""
    from dorsal.common.auth import write_ui_config

    result = runner.invoke(
        app,
        ["--borders", "none", "--icons", "none"]
        + ["config", "theme", "set", "dracula", "--icons", "ascii", "--borders", "none", "-g"],
    )

    assert result.exit_code == 0
    write_ui_config.assert_called_once_with(theme="dracula", icons="ascii", borders="none", scope="global")

    assert _printed(mock_rich_console) == (
        "UI preferences updated in global config\n  Theme    dracula\n  Icons    ascii\n  Borders  none\n"
    )


def test_set_ui_preferences_empty(mock_rich_console, mock_config_app, mock_error_console):
    """Tests setting UI preferences without providing any values."""
    result = runner.invoke(app, ["config", "theme", "set"])
    assert result.exit_code != 0
    mock_rich_console.print.assert_not_called()
    error_message = str(mock_error_console.print.call_args.args[0])
    assert "No UI preferences provided" in error_message


def test_set_ui_preferences_invalid_theme(mock_rich_console, mock_config_app, mock_error_console):
    """Tests setting a theme that does not exist."""
    result = runner.invoke(app, ["config", "theme", "set", "invalid_theme"])
    assert result.exit_code != 0
    error_message = str(mock_error_console.print.call_args.args[0])
    assert "Theme 'invalid_theme' not found" in error_message


def test_set_ui_preferences_invalid_icons(mock_rich_console, mock_config_app, mock_error_console):
    """Tests setting an icon style that does not exist."""
    result = runner.invoke(app, ["config", "theme", "set", "--icons", "invalid_icon_style"])
    assert result.exit_code != 0
    error_message = str(mock_error_console.print.call_args.args[0])
    assert "Icon set 'invalid_icon_style' not found" in error_message


def test_set_ui_preferences_invalid_borders(mock_rich_console, mock_config_app, mock_error_console):
    """Tests setting a border style that does not exist."""
    result = runner.invoke(app, ["config", "theme", "set", "--borders", "invalid_border_style"])
    assert result.exit_code != 0
    error_message = str(mock_error_console.print.call_args.args[0])
    assert "Border style 'invalid_border_style' not found" in error_message


def test_set_ui_preferences_os_error(mocker, mock_rich_console, mock_config_app):
    """Tests handling of an OSError when writing the UI config."""
    mocker.patch(
        "dorsal.common.auth.write_ui_config",
        side_effect=OSError("Permission denied"),
    )

    result = runner.invoke(app, ["config", "theme", "set", "dracula"])
    assert result.exit_code != 0

    error_in_mock = any("Permission denied" in str(call.args[0]) for call in mock_rich_console.print.call_args_list)
    assert error_in_mock or "Permission denied" in result.output


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
    assert _printed(mock_rich_console) == "Pipeline: The pipeline is currently empty.\n"


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
    ]

    result = runner.invoke(app, ["--borders", "rounded", "config", "pipeline", "show"])

    assert result.exit_code == 0

    output = _printed(mock_rich_console)
    assert output.startswith("Annotation model pipeline")
    assert "│   0 │ Default │ BaseModel" in output
    assert "Total models: 1" in output


def test_pipeline_show_no_borders(mock_rich_console, mock_pipeline_api):
    """Tests that borderless `config pipeline show` prints plain, left-aligned columns."""
    mock_pipeline_api["show"].return_value = [
        {
            "index": 0,
            "status": "Base (Locked)",
            "name": "BaseModel",
            "module": "dorsal",
            "schema_id": "base",
            "dependencies": "None",
        },
        {
            "index": 1,
            "status": "Deactivated",
            "name": "[Other]",
            "module": "pkg",
            "schema_id": "open/x",
            "dependencies": ["a"],
        },
    ]

    result = runner.invoke(app, ["--borders", "none", "config", "pipeline", "show"])

    assert result.exit_code == 0
    assert _printed(mock_rich_console) == (
        "Annotation model pipeline\n"
        "Idx  Status   Model name  Module  Schema ID  Dependencies\n"
        "  0  Default  BaseModel   dorsal  base       None\n"
        "  1  Off      [Other]     pkg     open/x     ['a']\n"
        "Total models: 2\n"
    )


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

    result_idx = runner.invoke(app, ["config", "pipeline", command, "1"])
    assert result_idx.exit_code == 0
    mock_pipeline_api[api_idx].assert_called_with(index=1)
    assert f"Successfully {verb} model at index 1" in str(mock_rich_console.print.call_args.args[0])

    result_name = runner.invoke(app, ["config", "pipeline", command, "MyModel"])
    assert result_name.exit_code == 0
    mock_pipeline_api[api_name].assert_called_with(name="MyModel")
    assert f"Successfully {verb} model 'MyModel'" in str(mock_rich_console.print.call_args.args[0])


def test_pipeline_action_error(mock_rich_console, mock_pipeline_api, mock_error_console):
    """Test error handling in pipeline actions."""
    mock_pipeline_api["remove_idx"].side_effect = IndexError("Index out of range")

    result = runner.invoke(app, ["config", "pipeline", "remove", "99"])

    assert result.exit_code != 0
    assert "Error:[/] Index out of range" in str(mock_error_console.print.call_args.args[0])


def test_pipeline_check_clean(mock_rich_console, mock_pipeline_api):
    """Tests `config pipeline check` when everything is fine."""

    step1 = MagicMock()
    step1.annotation_model = "valid.path"
    step1.validation_model = None

    mock_pipeline_api["get_steps"].return_value = [MagicMock(), step1]

    result = runner.invoke(app, ["config", "pipeline", "check"])

    assert result.exit_code == 0
    assert "All pipeline models are importable" in str(mock_rich_console.print.call_args.args[0])


def test_pipeline_check_broken_with_fix(mock_rich_console, mock_pipeline_api):
    """Tests `config pipeline check --fix` with broken models."""

    step_broken = MagicMock()
    step_broken.annotation_model.name = "BrokenModel"

    mock_pipeline_api["get_steps"].return_value = [MagicMock(), step_broken]

    mock_pipeline_api["import_callable"].side_effect = ImportError("Missing module")

    result = runner.invoke(app, ["config", "pipeline", "check", "--fix"])

    assert result.exit_code == 0

    output_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "Found 1 broken models" in output_text
    assert "Removed broken model 'BrokenModel'" in output_text

    mock_pipeline_api["remove_idx"].assert_called_with(index=1)


def test_pipeline_check_broken_no_fix(mock_rich_console, mock_pipeline_api):
    """Tests `config pipeline check` (no fix) exits with error."""
    step_broken = MagicMock()
    step_broken.annotation_model.name = "BrokenModel"
    mock_pipeline_api["get_steps"].return_value = [MagicMock(), step_broken]
    mock_pipeline_api["import_callable"].side_effect = ImportError("Missing module")

    result = runner.invoke(app, ["config", "pipeline", "check"])

    assert result.exit_code != 0

    output_text = "".join(str(c.args[0]) for c in mock_rich_console.print.call_args_list)
    assert "--fix" in output_text
    assert "automatically remove" in output_text

    mock_pipeline_api["remove_idx"].assert_not_called()


def test_pipeline_show_json_output(mock_rich_console, mock_pipeline_api):
    """Tests `config pipeline show --json` output."""
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
            "status": "Active",
            "name": "MyCustomModel",
            "module": "custom.pkg",
            "schema_id": "custom_schema",
            "dependencies": ["base"],
        },
    ]

    result = runner.invoke(app, ["config", "pipeline", "show", "--json"])

    assert result.exit_code == 0

    json_output_str = mock_rich_console.print.call_args.args[0]

    data = json.loads(json_output_str)

    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["name"] == "BaseModel"
    assert data[1]["schema_id"] == "custom_schema"
