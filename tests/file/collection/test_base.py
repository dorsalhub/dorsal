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
import datetime
from unittest.mock import MagicMock, patch

from dorsal.file.collection.base import _BaseFileCollection, _check_file_for_filter


class TestBaseCollectionFilterLogic:
    """Tests the underlying dictionary/attribute filtering logic."""

    @pytest.fixture
    def mock_file(self):
        f = MagicMock()
        f.size = 1000
        f.media_type = "text/plain"
        f.name = "test.txt"
        f.tags = ["important", "review"]

        f.annotations = MagicMock()
        f.annotations.file_base = MagicMock()
        f.annotations.file_base.name = "nested_test.txt"
        return f

    def test_filter_exact_match(self, mock_file):
        assert _check_file_for_filter(mock_file, {"media_type": "text/plain"}) is True
        assert _check_file_for_filter(mock_file, {"media_type": "image/png"}) is False

    def test_filter_operators(self, mock_file):
        assert _check_file_for_filter(mock_file, {"size__gt": 500}) is True
        assert _check_file_for_filter(mock_file, {"size__gt": 1500}) is False
        assert _check_file_for_filter(mock_file, {"size__lt": 1500}) is True
        assert _check_file_for_filter(mock_file, {"size__gte": 1000}) is True
        assert _check_file_for_filter(mock_file, {"size__lte": 1000}) is True

    def test_filter_contains_and_in(self, mock_file):

        assert _check_file_for_filter(mock_file, {"tags__contains": "important"}) is True
        assert _check_file_for_filter(mock_file, {"name__contains": "test"}) is True

        assert _check_file_for_filter(mock_file, {"media_type__in": ["text/plain", "application/json"]}) is True
        assert _check_file_for_filter(mock_file, {"media_type__in": ["image/png"]}) is False

    def test_filter_nested_attributes(self, mock_file):
        assert _check_file_for_filter(mock_file, {"annotations__file_base__name": "nested_test.txt"}) is True
        assert _check_file_for_filter(mock_file, {"annotations__file_base__name": "wrong.txt"}) is False

    def test_filter_missing_attribute_fails_gracefully(self, mock_file):
        """If the attribute doesn't exist, it should safely return False."""
        assert _check_file_for_filter(mock_file, {"does_not_exist": 123}) is False
        assert _check_file_for_filter(mock_file, {"nested__missing__attr__gt": 10}) is False


class TestBaseFileCollectionRepresentations:
    def test_repr_local_short_path(self):
        col = _BaseFileCollection([], source_info={"type": "local", "path": "/short/path"})
        assert "[/short/path]" in repr(col)

    def test_repr_local_long_path(self):
        col = _BaseFileCollection(
            [], source_info={"type": "local", "path": "/a/very/long/path/that/will/be/truncated.txt"}
        )
        assert "[.../will/be/truncated.txt]" in repr(col)

    def test_repr_remote_collection(self):
        col = _BaseFileCollection([], source_info={"type": "remote", "collection_id": "col_123"})
        assert "[remote id: col_123]" in repr(col)

    def test_repr_generic_fallback(self):
        col = _BaseFileCollection([])
        assert "[from list]" in repr(col)


class TestBaseFileCollectionMethods:
    @pytest.fixture
    def populated_col(self):
        file1 = MagicMock(hash="h1", size=100)
        file2 = MagicMock(hash="h1", size=100)
        file3 = MagicMock(hash="h2", size=500)
        col = _BaseFileCollection([file1, file2, file3])
        col._is_populated = True
        return col

    def test_info_unpopulated_raises_error(self):
        col = _BaseFileCollection([])
        with pytest.raises(TypeError, match="call the .populate\\(\\) method first"):
            col.info()

    def test_info_empty_collection(self):
        col = _BaseFileCollection([])
        col._is_populated = True
        info = col.info()
        assert info["overall"]["total_files"] == 0
        assert info["overall"]["largest_file"] is None

    def test_find_duplicates_unpopulated_raises_error(self):
        col = _BaseFileCollection([])
        with pytest.raises(TypeError, match="call the .populate\\(\\) method first"):
            col.find_duplicates()

    def test_find_duplicates_empty_collection(self):
        col = _BaseFileCollection([])
        col._is_populated = True
        assert col.find_duplicates() == {}

    def test_find_duplicates_no_duplicates_found(self):
        col = _BaseFileCollection([MagicMock(hash="h1", size=10), MagicMock(hash="h2", size=20)])
        col._is_populated = True
        assert col.find_duplicates() == {}

    @patch("dorsal.file.collection.base.is_jupyter_environment", return_value=True)
    def test_find_duplicates_jupyter_ui(self, mock_jupyter, populated_col):
        """Covers the tqdm branch for duplicate finding."""
        res = populated_col.find_duplicates()
        assert res["total_sets"] == 1
        assert res["total_wasted_space_bytes"] == 100

    def test_find_duplicates_rich_console_ui(self, populated_col):
        """Covers the Rich Console branch for duplicate finding."""
        from rich.console import Console

        res = populated_col.find_duplicates(console=Console())
        assert res["total_sets"] == 1

    def test_filter_no_kwargs(self, populated_col):
        """Covers the fast-return when filter is called with no arguments."""
        filtered = populated_col.filter()
        assert len(filtered) == 3

    def test_get_flattened_data_empty_annotations(self):
        """Covers the branch where a file has no annotations during flattening."""
        file_no_ann = MagicMock(hash="h1")
        file_no_ann.to_dict.return_value = {"annotations": None}
        col = _BaseFileCollection([file_no_ann])
        headers, rows = col._get_flattened_data()

        assert "hash" in headers
        assert len(rows) == 1
        assert rows[0]["hash"] == "h1"

    def test_to_csv_empty_collection(self, tmp_path):
        """Covers early exits for empty collections in to_csv."""
        col = _BaseFileCollection([])
        out = tmp_path / "out.csv"
        col.to_csv(str(out))
        assert not out.exists()

    def test_to_sqlite_empty_collection(self, tmp_path):
        """Covers early exits for empty collections in to_sqlite."""
        col = _BaseFileCollection([])
        out = tmp_path / "out.db"
        col.to_sqlite(str(out))
        assert not out.exists()

    def test_to_sqlite_no_flattened_rows(self, tmp_path, mocker):
        """Covers early exit when flattening yields no rows."""
        col = _BaseFileCollection([MagicMock()])
        mocker.patch.object(col, "_get_flattened_data", return_value=(["hash"], []))
        out = tmp_path / "out.db"
        col.to_sqlite(str(out))
        assert not out.exists()
