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
import pathlib
from typer.testing import CliRunner
from unittest.mock import MagicMock


from dorsal.cli import app
from dorsal.cli.cache_app import export_cmd

runner = CliRunner()


@pytest.fixture
def mock_export_cache_cmd(mocker):
    """Mocks dependencies for the `cache export` command."""
    # Patch the backend function at its original source location
    mock_export = mocker.patch("dorsal.file.utils.cache.export_cache", return_value=1234)

    # Mock the constants directory to avoid filesystem interaction
    mock_exports_dir = MagicMock(spec=pathlib.Path)
    mocker.patch("dorsal.common.constants.CLI_EXPORTS_DIR", mock_exports_dir)

    # Mock datetime to create a predictable timestamped filename
    mock_dt = MagicMock()
    mock_dt.now.return_value.strftime.return_value = "20250101-120000"
    mocker.patch.object(export_cmd, "datetime", mock_dt)

    return {
        "export_cache": mock_export,
        "exports_dir": mock_exports_dir,
    }


def test_export_cache_default_path_and_format(mock_rich_console, mock_export_cache_cmd):
    """Tests exporting with default options, which should create a timestamped filename."""
    result = runner.invoke(app, ["cache", "export"])

    assert result.exit_code == 0
    mock_export_cache_cmd["exports_dir"].mkdir.assert_called_once_with(parents=True, exist_ok=True)

    expected_path = mock_export_cache_cmd["exports_dir"] / "cache-export-20250101-120000.json.gz"

    mock_export_cache_cmd["export_cache"].assert_called_once_with(
        output_path=expected_path, format="json.gz", include_records=True
    )

    all_printed_text = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list)
    assert f"Successfully exported 1,234 records to '{expected_path}'" in all_printed_text


def test_export_cache_with_output_path_inferred_format(mock_rich_console, mock_export_cache_cmd, tmp_path):
    """Tests exporting to a specific path and ensuring the format is inferred from the extension."""
    output_file = tmp_path / "my-cache.json"
    result = runner.invoke(app, ["cache", "export", "--output", str(output_file)])

    assert result.exit_code == 0
    mock_export_cache_cmd["export_cache"].assert_called_once_with(
        output_path=output_file.resolve(), format="json", include_records=True
    )

    all_printed_text = "".join(str(call.args[0]) for call in mock_rich_console.print.call_args_list)
    assert f"Successfully exported 1,234 records to '{output_file.resolve()}'" in all_printed_text


def test_export_cache_with_format_override(mock_rich_console, mock_export_cache_cmd, tmp_path):
    """Tests that the --format flag correctly overrides the file extension."""
    output_file = tmp_path / "my-cache.data"
    result = runner.invoke(app, ["cache", "export", "--output", str(output_file), "--format", "json.gz"])

    assert result.exit_code == 0
    mock_export_cache_cmd["export_cache"].assert_called_once_with(
        output_path=output_file.resolve(), format="json.gz", include_records=True
    )


def test_export_cache_no_records(mock_export_cache_cmd):
    """Tests that the --no-records flag is passed correctly to the backend."""
    result = runner.invoke(app, ["cache", "export", "--no-records"])

    assert result.exit_code == 0
    # Check that the final call was made with include_records=False
    assert mock_export_cache_cmd["export_cache"].call_args.kwargs["include_records"] is False


def test_export_cache_invalid_format():
    """Tests that providing an unsupported format causes a graceful failure."""
    result = runner.invoke(app, ["cache", "export", "--format", "xml"])

    assert result.exit_code != 0
    assert "Invalid format 'xml'" in result.output


def test_export_cache_io_error(mock_export_cache_cmd):
    """Tests that an IOError from the backend is handled gracefully."""
    mock_export_cache_cmd["export_cache"].side_effect = IOError("Disk is full")

    result = runner.invoke(app, ["cache", "export"])

    assert result.exit_code != 0
    assert "Export failed: Disk is full" in result.output
