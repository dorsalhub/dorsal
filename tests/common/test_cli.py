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

import pytest
from unittest.mock import patch, MagicMock
import typer

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
