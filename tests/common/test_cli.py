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


import sys
import pytest
from unittest.mock import ANY, patch, MagicMock

from rich.panel import Panel
from rich.console import Group
from typer.testing import CliRunner
from unittest.mock import patch
import typer

from dorsal.common.exceptions import AuthError
from dorsal.common import cli


@patch("typer.secho")
def test_exit_cli_success_with_message(mock_secho):
    """Test exiting with a success code and a message."""
    with pytest.raises(typer.Exit) as excinfo:
        cli.exit_cli(code=0, message="Operation successful.")

    assert excinfo.value.exit_code == 0
    mock_secho.assert_called_once_with("Operation successful.", err=True)


@patch("typer.secho")
def test_exit_cli_error_with_message(mock_secho):
    """Test exiting with an error code and ensuring the message is prefixed."""
    with pytest.raises(typer.Exit) as excinfo:
        cli.exit_cli(code=1, message="File not found.")

    assert excinfo.value.exit_code == 1
    mock_secho.assert_called_once_with("Error: File not found.", fg=typer.colors.RED, err=True)


@patch("typer.secho")
def test_exit_cli_no_message(mock_secho):
    """Test that no message is printed if none is provided."""
    with pytest.raises(typer.Exit) as excinfo:
        cli.exit_cli(code=5)

    assert excinfo.value.exit_code == 5
    mock_secho.assert_not_called()


@pytest.mark.parametrize(
    "use_cache_flag, skip_cache_flag, expected_arg",
    [
        (True, False, True),
        (False, True, False),
        (True, True, True),
        (False, False, None),
    ],
)
@patch("dorsal.file.index.config.get_index_enabled")
def test_determine_use_cache_value(mock_get_cache_enabled, use_cache_flag, skip_cache_flag, expected_arg):
    """Test the logic for resolving cache flags."""
    mock_get_cache_enabled.side_effect = lambda use_index=None, **kwargs: use_index

    cli.determine_use_cache_value(use_cache=use_cache_flag, skip_cache=skip_cache_flag)

    mock_get_cache_enabled.assert_called_once_with(use_index=expected_arg)


def test_parse_cli_options_empty():
    """Test that empty or None options return an empty dictionary."""
    assert cli.parse_cli_options(None, {}) == {}
    assert cli.parse_cli_options([], {}) == {}


@patch("dorsal.common.cli.get_error_console")
def test_parse_cli_options_malformed(mock_get_error_console):
    """Test that options missing an '=' sign are skipped and a warning is printed."""
    mock_console = MagicMock()
    mock_get_error_console.return_value = mock_console

    options = ["valid=true", "invalid_no_equals"]
    palette = {"panel_title_warning": "yellow"}

    result = cli.parse_cli_options(options, palette)

    assert result == {"valid": True}
    mock_console.print.assert_called_once()
    assert "Skipping malformed option 'invalid_no_equals'" in mock_console.print.call_args[0][0]


def test_parse_cli_options_basic_types():
    """Test parsing of standard types: booleans, nulls, ints, floats, and strings."""
    options = [
        "is_true=true",
        "is_yes=yes",
        "is_false=false",
        "is_no=no",
        "is_null=null",
        "is_none=none",
        "integer=42",
        "floating=3.14",
        "string=hello world",
        "mixed_case_bool=TrUe",
    ]

    expected = {
        "is_true": True,
        "is_yes": True,
        "is_false": False,
        "is_no": False,
        "is_null": None,
        "is_none": None,
        "integer": 42,
        "floating": 3.14,
        "string": "hello world",
        "mixed_case_bool": True,
    }

    assert cli.parse_cli_options(options, {}) == expected


def test_parse_cli_options_json_structures():
    """Test parsing of JSON dictionaries and arrays, including fallbacks for invalid JSON."""
    options = [
        'vad_filter={"threshold": 0.8, "min_speech_duration_ms": 250}',
        'array_val=[1, 2, "three"]',
        'invalid_json={"missing_bracket": true',
        "not_quite_json={just some text}",
    ]

    expected = {
        "vad_filter": {"threshold": 0.8, "min_speech_duration_ms": 250},
        "array_val": [1, 2, "three"],
        "invalid_json": '{"missing_bracket": true',
        "not_quite_json": "{just some text}",
    }

    assert cli.parse_cli_options(options, {}) == expected


@pytest.fixture
def mock_ui_context():
    """Provides a standard UI context for testing visual handlers."""
    return {
        "palette": {
            "panel_title_error": "red",
            "panel_border_error": "red",
            "panel_title_info": "cyan",
            "panel_border_info": "cyan",
            "panel_title_warning": "yellow",
            "panel_border_warning": "yellow",
            "warning": "yellow",
            "primary_value": "cyan",
            "text_default": "default",
        },
        "borders": "rounded",
        "icons": {"warning": "⚠️ ", "error": "❌ ", "lock": "🔒 "},
    }


@patch("dorsal.common.cli.exit_cli")
def test_handle_error_json(mock_exit, mock_rich_console, mock_ui_context):
    """Tests that handle_error outputs raw JSON when requested."""
    cli.handle_error(mock_ui_context, "Something broke.", json_output=True)

    mock_rich_console.print.assert_called_once()
    output = mock_rich_console.print.call_args[0][0]
    assert '"error": true' in output
    assert "Something broke." in output
    mock_exit.assert_called_once_with(code=cli.EXIT_CODE_ERROR)


@patch("dorsal.common.cli.exit_cli")
def test_handle_error_panel(mock_exit, mock_rich_console, mock_ui_context):
    """Tests that handle_error outputs a Rich Panel by default."""
    cli.handle_error(mock_ui_context, "Something broke.", json_output=False)

    printed_obj = mock_rich_console.print.call_args[0][0]
    assert isinstance(printed_obj, Panel)
    mock_exit.assert_called_once_with(code=cli.EXIT_CODE_ERROR)


@patch("dorsal.common.cli.exit_cli")
def test_handle_error_none_borders(mock_exit, mock_rich_console, mock_ui_context, mocker):
    """Tests that handle_error strips the Panel when borders are 'none'."""

    class MatchAnyBorder:
        def __eq__(self, other):
            return True

    mocker.patch("dorsal.cli.themes.borders.get_borders", return_value=MatchAnyBorder())

    cli.handle_error(mock_ui_context, "Something broke.", json_output=False)

    printed_obj = mock_rich_console.print.call_args[0][0]
    assert isinstance(printed_obj, Group)
    mock_exit.assert_called_once_with(code=cli.EXIT_CODE_ERROR)


@patch.object(sys, "argv", ["dorsal", "auth", "--json"])
def test_handle_auth_error_json(capsys, mock_rich_console, mock_ui_context):
    """Tests that auth errors bypass Rich and print raw JSON when --json is in sys.argv."""
    err = AuthError("Fake auth error")
    cli.handle_auth_error(err, mock_rich_console, mock_ui_context)

    captured = capsys.readouterr()
    assert '"success": false' in captured.out
    assert '"error": "Authentication Required"' in captured.out
    assert mock_rich_console.print.call_count == 0


@patch.object(sys, "argv", ["dorsal", "auth"])
def test_handle_auth_error_panel(mock_rich_console, mock_ui_context):
    """Tests the standard visual output for an auth error."""
    err = AuthError("Fake auth error")
    cli.handle_auth_error(err, mock_rich_console, mock_ui_context)

    printed_obj = mock_rich_console.print.call_args[0][0]
    assert isinstance(printed_obj, Panel)


@patch.object(sys, "argv", ["dorsal", "search", "--json"])
def test_handle_offline_error_json(capsys, mock_rich_console, mock_ui_context):
    """Tests that offline errors bypass Rich and print raw JSON when --json is in sys.argv."""
    err = Exception("Fake offline error")
    cli.handle_offline_error(err, mock_rich_console, mock_ui_context)

    captured = capsys.readouterr()
    assert '"success": false' in captured.out
    assert '"error": "Offline Mode Active"' in captured.out
    assert mock_rich_console.print.call_count == 0


@patch.object(sys, "argv", ["dorsal", "search"])
def test_handle_offline_error_panel(mock_rich_console, mock_ui_context):
    """Tests the standard visual output for an offline error."""
    err = Exception("Fake offline error")
    cli.handle_offline_error(err, mock_rich_console, mock_ui_context)

    printed_obj = mock_rich_console.print.call_args[0][0]
    assert isinstance(printed_obj, Panel)


def test_dummy_context():
    """Ensures the DummyContext manager operates as a functional no-op."""
    with cli.DummyContext() as ctx:
        assert ctx is None


runner = CliRunner()

app = typer.Typer()


@app.command(name="run", cls=cli.ModelHelpCommand)
def dummy_run(
    target: str = typer.Argument(..., help="The target model."),
    file_path: str = typer.Argument(..., help="The file path."),
):
    pass


@patch("sys.argv", ["dorsal", "run", "FasterWhisper", "audio.mp3", "--help"])
@patch("dorsal.api.model.get_model_help")
def test_dynamic_help_standard_position(mock_get_model_help):
    """Test when --help is at the very end of the command."""
    mock_get_model_help.return_value = {
        "status": "success",
        "package_name": "FasterWhisper",
        "model_class": "FasterWhisperTranscriber",
        "options": {},
    }

    result = runner.invoke(app, ["run", "FasterWhisper", "audio.mp3", "--help"])

    assert result.exit_code == 0
    mock_get_model_help.assert_called_once()
    assert mock_get_model_help.call_args[1]["target"] == "FasterWhisper"


@patch("sys.argv", ["dorsal", "run", "--help", "FasterWhisper"])
@patch("dorsal.api.model.get_model_help")
def test_dynamic_help_eager_position(mock_get_model_help):
    """Test when --help interrupts the command before positional arguments."""
    mock_get_model_help.return_value = {
        "status": "success",
        "package_name": "FasterWhisper",
        "model_class": "FasterWhisperTranscriber",
        "options": {},
    }

    result = runner.invoke(app, ["run", "--help", "FasterWhisper"])

    assert result.exit_code == 0
    mock_get_model_help.assert_called_once()
    assert mock_get_model_help.call_args[1]["target"] == "FasterWhisper"


@patch("sys.argv", ["dorsal", "run", "--help"])
@patch("dorsal.api.model.get_model_help")
def test_dynamic_help_no_target(mock_get_model_help):
    """Test when --help is called with no target at all."""
    result = runner.invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    mock_get_model_help.assert_not_called()
    assert "Usage:" in result.stdout


def test_dynamic_help_not_implemented():
    """Test that the base class requires subclasses to implement the renderable method."""

    class IncompleteHelpCommand(cli.DynamicHelpCommand):
        pass

    cmd = IncompleteHelpCommand(name="incomplete")
    with pytest.raises(NotImplementedError, match="Subclasses must implement get_dynamic_renderable"):
        cmd.get_dynamic_renderable("target", {})


@patch("sys.argv", ["dorsal", "model", "run", "FasterWhisper", "--help"])
@patch("dorsal.api.model.get_model_help")
def test_dynamic_help_nested_commands(mock_get_model_help):
    """Test target extraction when the command is nested (e.g., 'model run')."""
    parent_app = typer.Typer()
    child_app = typer.Typer()
    parent_app.add_typer(child_app, name="model")

    @child_app.command(name="run", cls=cli.ModelHelpCommand)
    def nested_run(target: str = typer.Argument(...)):
        pass

    mock_get_model_help.return_value = {
        "status": "success",
        "package_name": "FasterWhisper",
        "model_class": "FasterWhisperTranscriber",
        "options": {},
    }

    result = runner.invoke(parent_app, ["model", "run", "FasterWhisper", "--help"])

    assert result.exit_code == 0
    mock_get_model_help.assert_called_once()
    assert mock_get_model_help.call_args[1]["target"] == "FasterWhisper"


@patch("sys.argv", ["dorsal", "weird_alias", "--help"])
@patch("dorsal.api.model.get_model_help")
def test_dynamic_help_value_error_fallback(mock_get_model_help):
    """Test that it fails gracefully if sys.argv doesn't contain the command name at all."""
    result = runner.invoke(app, ["run", "--help"])

    assert result.exit_code == 0
    mock_get_model_help.assert_not_called()


def test_dynamic_help_ctx_args_fallback():
    """Test the safety net where click dumped unparsed args into ctx.args."""
    mock_ctx = MagicMock()
    mock_ctx.params = {"target": None}
    mock_ctx.parent = None
    mock_ctx.info_name = "run"
    mock_ctx.args = ["--some-flag", "CtxFallbackModel"]
    mock_ctx.find_object.return_value = {"palette": {}, "borders": "none"}

    mock_formatter = MagicMock()

    cmd = cli.ModelHelpCommand(name="run", callback=lambda: None)

    with patch("sys.argv", ["dorsal", "run", "--help"]):
        with patch.object(cli.ModelHelpCommand, "get_dynamic_renderable", return_value=None) as mock_get:
            with patch("typer.core.TyperCommand.format_help"):
                cmd.format_help(mock_ctx, mock_formatter)

                mock_get.assert_called_once_with("CtxFallbackModel", ANY)


@patch("sys.argv", ["dorsal", "export", "srt", "--help"])
@patch("dorsal.api.adapters.get_adapter_help")
def test_adapter_help_command(mock_get_adapter_help):
    """Test the AdapterHelpCommand variant and its dynamic renderable."""
    adapter_app = typer.Typer()

    @adapter_app.command(name="export", cls=cli.AdapterHelpCommand)
    def export_cmd(target_format: str = typer.Argument(...)):
        pass

    mock_get_adapter_help.return_value = "Mocked Adapter Panel"

    result = runner.invoke(adapter_app, ["export", "srt", "--help"])

    assert result.exit_code == 0
    mock_get_adapter_help.assert_called_once()

    assert mock_get_adapter_help.call_args[0][0] == "srt"


@patch("sys.argv", ["standalone", "MyRootModel", "--help"])
@patch("dorsal.api.model.get_model_help")
def test_dynamic_help_root_command(mock_get_model_help):
    """Test fallback when the command has no parent subcommands (root level)."""
    root_app = typer.Typer()

    @root_app.command(name="standalone", cls=cli.ModelHelpCommand)
    def root_cmd(target: str = typer.Argument(...)):
        pass

    mock_get_model_help.return_value = {
        "status": "success",
        "package_name": "MyRootModel",
        "model_class": "MyRootModelClass",
        "options": {},
    }

    result = runner.invoke(root_app, ["MyRootModel", "--help"])

    assert result.exit_code == 0
    mock_get_model_help.assert_called_once()
    assert mock_get_model_help.call_args[1]["target"] == "MyRootModel"


def test_render_model_help_panel_error(mock_ui_context):
    """Test the panel rendering when model resolution fails."""
    help_info = {"status": "error", "target": "my-target", "error": "Resolution failed"}
    panel = cli.render_model_help_panel(help_info, mock_ui_context)

    assert isinstance(panel, Panel)
    assert "Resolution failed" in str(panel.renderable)
    assert "Model Resolution Failed" in str(panel.title)


def test_render_model_help_panel_not_installed(mock_ui_context):
    """Test the panel rendering when a model is resolved but not installed."""
    help_info = {"status": "not_installed", "target": "my-target", "package_name": "my-pkg"}
    panel = cli.render_model_help_panel(help_info, mock_ui_context)

    assert isinstance(panel, Panel)
    assert "my-pkg" in str(panel.renderable)
    assert "dorsal model install my-target" in str(panel.renderable)
    assert "Model: my-target" in str(panel.title)


def test_render_model_help_panel_config_error(mock_ui_context):
    """Test the panel rendering when the model_config.toml is missing or invalid."""
    help_info = {"status": "config_error", "package_name": "my-pkg", "error": "Invalid TOML"}
    panel = cli.render_model_help_panel(help_info, mock_ui_context)

    assert isinstance(panel, Panel)
    assert "Failed to load configuration for 'my-pkg'" in str(panel.renderable)
    assert "Invalid TOML" in str(panel.renderable)
    assert "Configuration Error" in str(panel.title)


def test_render_model_help_panel_success_no_options(mock_ui_context):
    """Test the panel rendering when a model successfully loads but has no options."""
    help_info = {"status": "success", "package_name": "my-pkg", "model_class": "MyClass", "options": {}}
    panel = cli.render_model_help_panel(help_info, mock_ui_context)

    assert isinstance(panel, Panel)
    assert "does not define any default options" in str(panel.renderable)
    assert "Model: my-pkg" in str(panel.title)


def test_render_model_help_panel_success_with_options(mock_ui_context):
    """Test the full table rendering for a model with a valid configuration and options."""
    from rich.table import Table

    help_info = {
        "status": "success",
        "package_name": "my-pkg",
        "model_class": "MyClass",
        "options": {
            "batch_size": {"default": 16, "help": "Batch size for inference"},
            "language": {"help": "Target language"},
        },
    }

    panel = cli.render_model_help_panel(help_info, mock_ui_context)

    assert isinstance(panel, Panel)
    assert isinstance(panel.renderable, Group)
    assert "Model Options: MyClass" in str(panel.title)

    table = panel.renderable.renderables[0]
    assert isinstance(table, Table)

    assert len(table.columns) == 3
    assert table.columns[0].header == "Option"
