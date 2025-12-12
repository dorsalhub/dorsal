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
from unittest.mock import patch
import typer

from dorsal.common import cli


@patch("typer.secho")
def test_exit_cli_success_with_message(mock_secho):
    """Test exiting with a success code and a message."""
    with pytest.raises(typer.Exit) as excinfo:
        cli.exit_cli(code=0, message="Operation successful.")

    # Check that the exception has the correct exit code
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
@patch("dorsal.common.cli.get_cache_enabled")
def test_determine_use_cache_value(mock_get_cache_enabled, use_cache_flag, skip_cache_flag, expected_arg):
    """Test the logic for resolving cache flags."""
    mock_get_cache_enabled.side_effect = lambda use_cache: use_cache

    cli.determine_use_cache_value(use_cache=use_cache_flag, skip_cache=skip_cache_flag)

    mock_get_cache_enabled.assert_called_once_with(use_cache=expected_arg)
