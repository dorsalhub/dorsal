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
from pathlib import Path
from unittest.mock import MagicMock


from dorsal.api import index as api_index
from dorsal.file.index.dorsal_index import DorsalIndex


@pytest.fixture
def mock_shared_index(mocker) -> MagicMock:
    """Provides a mocked shared index and patches the local module reference."""
    mock_idx = MagicMock(spec=DorsalIndex)
    
    mocker.patch("dorsal.api.index.get_shared_index", return_value=mock_idx)
    return mock_idx


@pytest.fixture
def mock_custom_index() -> MagicMock:
    """Provides an isolated mock index to simulate user-provided instances."""
    return MagicMock(spec=DorsalIndex)


def test_get_active_index_uses_provided(mock_custom_index):
    """Test that _get_active_index prioritizes the provided index."""
    assert api_index._get_active_index(mock_custom_index) is mock_custom_index


def test_get_active_index_falls_back_to_shared(mock_shared_index):
    """Test that _get_active_index falls back to the shared index if None is provided."""
    assert api_index._get_active_index(None) is mock_shared_index


def test_optimize(mock_custom_index):
    """Test the optimize wrapper delegates correctly."""
    mock_custom_index.optimize.return_value = {"stale_records_removed": 5}
    
    result = api_index.optimize(index=mock_custom_index)
    
    assert result == {"stale_records_removed": 5}
    mock_custom_index.optimize.assert_called_once()


def test_prune(mock_custom_index):
    """Test the prune wrapper delegates correctly."""
    mock_custom_index.prune.return_value = (10, 50)
    
    result = api_index.prune(index=mock_custom_index)
    
    assert result == (10, 50)
    mock_custom_index.prune.assert_called_once()


def test_clear_with_custom_index(mock_custom_index, mocker):
    """Test that clearing a custom index DOES NOT clear the shared index state."""
    mock_clear_shared = mocker.patch("dorsal.api.index.clear_shared_index")
    
    api_index.clear(index=mock_custom_index)
    
    mock_custom_index.clear.assert_called_once()
    mock_clear_shared.assert_not_called()


def test_clear_with_shared_index(mock_shared_index, mocker):
    """Test that clearing without an index clears BOTH the DB and the shared state."""
    mock_clear_shared = mocker.patch("dorsal.api.index.clear_shared_index")
    
    api_index.clear(index=None)
    
    mock_shared_index.clear.assert_called_once()
    mock_clear_shared.assert_called_once()


def test_summary(mock_custom_index):
    """Test the summary wrapper delegates correctly."""
    mock_custom_index.summary.return_value = {"total_records": 100}
    
    result = api_index.summary(index=mock_custom_index)
    
    assert result == {"total_records": 100}
    mock_custom_index.summary.assert_called_once()


def test_get_path(mock_custom_index):
    """Test get_path returns the resolved absolute path."""
    mock_path = MagicMock(spec=Path)
    mock_path.resolve.return_value = Path("/resolved/absolute/path.db")
    mock_custom_index.db_path = mock_path
    
    result = api_index.get_path(index=mock_custom_index)
    
    assert result == Path("/resolved/absolute/path.db")
    mock_path.resolve.assert_called_once()


def test_export_with_custom_args(mock_custom_index):
    """Test the export wrapper with fully specified arguments."""
    mock_custom_index.export.return_value = 42
    out_path = Path("/tmp/export.json")
    
    result = api_index.export(
        output_path=out_path,
        format="json",
        include_records=False,
        index=mock_custom_index
    )
    
    assert result == 42
    mock_custom_index.export.assert_called_once_with(
        output_path=out_path,
        format="json",
        include_records=False
    )


def test_export_with_default_args(mock_shared_index):
    """Test the export wrapper handles default arguments routing correctly."""
    mock_shared_index.export.return_value = 99
    out_path = Path("/tmp/export.json.gz")
    
    result = api_index.export(output_path=out_path)
    
    assert result == 99
    
    mock_shared_index.export.assert_called_once_with(
        output_path=out_path,
        format="json.gz",
        include_records=True
    )