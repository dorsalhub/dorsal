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

import os
from unittest.mock import MagicMock
import pytest

from dorsal.file.annotation_models.base.model import FileCoreAnnotationModel


class TestFileCoreAnnotationModel:
    @pytest.fixture
    def file_model(self):
        return FileCoreAnnotationModel(file_path="/fake/path/document.pdf")

    def test_main_success_default(self, file_model, mocker):
        """Tests successful extraction with standard defaults."""
        mock_hashes = {
            "SHA-256": "9e63994af3be98ca2cc02b0395d8da6a85f1e27885033ae3ee1a2af37af99d38",
            "BLAKE3": "2217ebed1834f296d7d0cec08f349afd24c030c2077e3f2410f11235cfa2366d",
            "QUICK": "quickhash123",
            "TLSH": "tlshhash456",
        }
        mocker.patch.object(file_model, "_get_file_hashes", return_value=mock_hashes)
        mocker.patch.object(file_model, "_get_filesize", return_value=1024)
        mocker.patch.object(file_model, "_get_media_type", return_value="application/pdf")

        result = file_model.main()

        assert result == {
            "hash": "9e63994af3be98ca2cc02b0395d8da6a85f1e27885033ae3ee1a2af37af99d38",
            "similarity_hash": "tlshhash456",
            "quick_hash": "quickhash123",
            "all_hashes": [
                {"id": "SHA-256", "value": "9e63994af3be98ca2cc02b0395d8da6a85f1e27885033ae3ee1a2af37af99d38"},
                {"id": "BLAKE3", "value": "2217ebed1834f296d7d0cec08f349afd24c030c2077e3f2410f11235cfa2366d"},
                {"id": "QUICK", "value": "quickhash123"},
                {"id": "TLSH", "value": "tlshhash456"},
            ],
            "name": "document.pdf",
            "extension": ".pdf",
            "size": 1024,
            "media_type": "application/pdf",
        }
        assert file_model.error is None

    def test_main_success_without_hash_calculation(self, file_model, mocker):
        """Tests execution when calculate_hashes is set to False."""
        mock_hashes_func = mocker.patch.object(file_model, "_get_file_hashes")
        mocker.patch.object(file_model, "_get_filesize", return_value=2048)
        mocker.patch.object(file_model, "_get_media_type", return_value="application/pdf")

        result = file_model.main(calculate_hashes=False)

        mock_hashes_func.assert_not_called()
        assert result["hash"] is None
        assert result["similarity_hash"] is None
        assert result["quick_hash"] is None
        assert result["all_hashes"] is None
        assert result["name"] == "document.pdf"
        assert result["extension"] == ".pdf"
        assert result["size"] == 2048

    def test_main_missing_primary_hash(self, file_model, mocker):
        """Hits the branch where hashing succeeds but fails to calculate SHA-256."""
        mocker.patch.object(file_model, "_get_file_hashes", return_value={"MD5": "abc12345"})

        result = file_model.main()

        assert result is None
        assert file_model.error == "Core SHA-256 hash calculation failed."

    def test_main_os_error(self, file_model, mocker):
        """Hits the FileNotFoundError/IOError/OSError branch, which sets error and re-raises."""
        mocker.patch.object(file_model, "_get_file_hashes", side_effect=FileNotFoundError("File not found"))

        with pytest.raises(FileNotFoundError):
            file_model.main()

        assert "File system error during processing" in file_model.error

    def test_main_unexpected_error(self, file_model, mocker):
        """Hits the general Exception catch block, setting error and re-raising."""
        mocker.patch.object(file_model, "_get_file_hashes", side_effect=RuntimeError("Unexpected error"))

        with pytest.raises(RuntimeError):
            file_model.main()

        assert "Unexpected error during FileCoreAnnotationModel processing" in file_model.error


class TestFileCoreAnnotationModelHelpers:
    @pytest.fixture
    def file_model(self):
        return FileCoreAnnotationModel(file_path="/fake/path/document.TXT")

    def test_get_file_hashes_success(self, file_model, mocker):
        """Tests successful invocation of multi_hash."""
        mock_multi_hash = mocker.patch("dorsal.file.annotation_models.base.model.multi_hash")
        mock_multi_hash.return_value = {"SHA-256": "fakehash"}

        hashes = file_model._get_file_hashes(calculate_similarity_hash=True)

        mock_multi_hash.assert_called_once_with(
            file_path="/fake/path/document.TXT",
            similarity_hash=True,
            follow_symlinks=False,
        )
        assert hashes == {"SHA-256": "fakehash"}

    def test_get_file_hashes_exception(self, file_model, mocker):
        """Tests that multi_hash exceptions are re-raised."""
        mocker.patch("dorsal.file.annotation_models.base.model.multi_hash", side_effect=IOError("Read error"))

        with pytest.raises(IOError):
            file_model._get_file_hashes()

    def test_get_filesize_regular_file(self, file_model, mocker):
        """Tests filesize extraction for a standard file."""
        mocker.patch("os.path.islink", return_value=False)
        mocker.patch("os.path.getsize", return_value=4096)

        assert file_model._get_filesize() == 4096

    def test_get_filesize_symlink_no_follow(self, file_model, mocker):
        """Tests filesize extraction for a symlink when follow_symlinks is False."""
        file_model.follow_symlinks = False
        mocker.patch("os.path.islink", return_value=True)
        mock_lstat = mocker.patch("os.lstat")
        mock_lstat.return_value.st_size = 128

        assert file_model._get_filesize() == 128
        mock_lstat.assert_called_once_with("/fake/path/document.TXT")

    def test_get_filesize_symlink_follow(self, file_model, mocker):
        """Tests filesize extraction for a symlink when follow_symlinks is True."""
        file_model.follow_symlinks = True
        mocker.patch("os.path.islink", return_value=True)
        mocker.patch("os.path.getsize", return_value=2048)

        assert file_model._get_filesize() == 2048

    def test_get_filesize_os_error(self, file_model, mocker):
        """Tests error propagation in _get_filesize."""
        mocker.patch("os.path.islink", return_value=False)
        mocker.patch("os.path.getsize", side_effect=OSError("Access denied"))

        with pytest.raises(OSError):
            file_model._get_filesize()

    def test_get_filename(self, file_model):
        """Tests extracting filename from path."""
        assert file_model._get_filename() == "document.TXT"

    def test_get_file_extension(self, file_model):
        """Tests parsing and normalizing extensions."""
        assert file_model._get_file_extension("archive.tar.gz") == ".gz"
        assert file_model._get_file_extension("document.TXT") == ".txt"
        assert file_model._get_file_extension("LICENSE") is None
        assert file_model._get_file_extension("file.") is None
        assert file_model._get_file_extension("") is None

    def test_get_media_type(self, file_model, mocker):
        """Tests invocation of get_media_type utility function."""
        mock_get_media_type = mocker.patch("dorsal.file.annotation_models.base.model.get_media_type")
        mock_get_media_type.return_value = "text/plain"

        media_type = file_model._get_media_type(file_extension=".txt")

        mock_get_media_type.assert_called_once_with(
            file_path="/fake/path/document.TXT",
            file_extension=".txt",
            follow_symlinks=False,
        )
        assert media_type == "text/plain"
