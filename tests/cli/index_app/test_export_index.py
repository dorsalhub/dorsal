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

import pytest
import pathlib
import sys
from typer.testing import CliRunner
from unittest.mock import MagicMock, ANY


from dorsal.cli import app

runner = CliRunner()


@pytest.fixture
def mock_export_index_cmd(mocker, tmp_path):
    """Mocks dependencies for the `index export` command."""
    mock_export = mocker.patch("dorsal.api.index.export", return_value=1234)

    mock_exports_dir = tmp_path / "dorsal_exports"
    mocker.patch("dorsal.common.constants.CLI_EXPORTS_DIR", mock_exports_dir)

    import sys

    mock_dt = mocker.patch.object(sys.modules["dorsal.cli.index_app.export_index_cmd"], "datetime")
    mock_dt.datetime.now.return_value.strftime.return_value = "20250101-120000"

    return {"export_index": mock_export, "exports_dir": mock_exports_dir, "datetime": mock_dt}


def test_export_index_default_path_and_format(mock_export_index_cmd):
    """Tests that omitting path/format args uses defaults and datetime suffix."""
    result = runner.invoke(app, ["index", "export"])

    assert result.exit_code == 0
    mock_export_index_cmd["export_index"].assert_called_once()

    called_kwargs = mock_export_index_cmd["export_index"].call_args.kwargs
    assert called_kwargs["format"] == "json.gz"
    assert called_kwargs["include_records"] is True
    assert "20250101-120000" in str(called_kwargs["output_path"])


def test_export_index_with_output_path_inferred_format(mock_export_index_cmd, tmp_path):
    """Tests that format is inferred from the path suffix."""
    output_file = tmp_path / "custom.json"
    result = runner.invoke(app, ["index", "export", "--output", str(output_file)])

    assert result.exit_code == 0
    mock_export_index_cmd["export_index"].assert_called_once_with(
        output_path=output_file.resolve(), format="json", include_records=True, progress_callback=ANY
    )


def test_export_index_with_format_override(mock_export_index_cmd, tmp_path):
    """Tests that the --format flag correctly overrides the file extension."""
    output_file = tmp_path / "my-index.data"
    result = runner.invoke(app, ["index", "export", "--output", str(output_file), "--format", "json.gz"])

    assert result.exit_code == 0
    mock_export_index_cmd["export_index"].assert_called_once_with(
        output_path=output_file.resolve(), format="json.gz", include_records=True, progress_callback=ANY
    )


def test_export_index_no_records(mock_export_index_cmd):
    """Tests that the --no-records flag is passed correctly to the backend."""
    result = runner.invoke(app, ["index", "export", "--no-records"])

    assert result.exit_code == 0
    assert mock_export_index_cmd["export_index"].call_args.kwargs["include_records"] is False


def test_export_index_invalid_format():
    """Tests that providing an unsupported format causes a graceful failure."""
    result = runner.invoke(app, ["index", "export", "--format", "xml"])

    assert result.exit_code != 0
    assert "Invalid format 'xml'" in result.output


def test_export_index_io_error(mock_export_index_cmd):
    """Tests that an IOError from the backend is handled gracefully."""
    mock_export_index_cmd["export_index"].side_effect = IOError("Disk is full")

    result = runner.invoke(app, ["index", "export"])

    assert result.exit_code != 0
    assert "Export failed: Disk is full" in result.output
