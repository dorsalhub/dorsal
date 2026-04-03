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

import json
import os
import pytest
from unittest.mock import MagicMock
from dorsal.file.annotation_models.mediainfo.model import MediaInfoAnnotationModel, PYMEDIAINFO_AVAILABLE


@pytest.fixture
def mediainfo_setup(mocker):
    """
    Provides a MediaInfoAnnotationModel instance along with safely
    mocked module-level dependencies to avoid real system calls.
    """

    mocker.patch("dorsal.file.annotation_models.mediainfo.model.PYMEDIAINFO_AVAILABLE", True)

    mock_media_info = MagicMock()
    mocker.patch("dorsal.file.annotation_models.mediainfo.model.MediaInfo", mock_media_info)

    model = MediaInfoAnnotationModel(file_path="/fake/media.mp4")

    return model, mock_media_info


class TestMediaInfoAnnotationModel:
    def test_normalize_track_list_success(self, mediainfo_setup):
        """Hits the happy path where '#value' dicts are successfully flattened."""
        model, _ = mediainfo_setup
        raw_tracks = [
            {
                "@type": "General",
                "Duration": {"#value": "120.5"},
                "NormalField": "KeptAsIs",
                "NestedDictNotValue": {"other": "data"},
            },
            {"@type": "Video", "BitRate": {"#value": "5000"}},
        ]

        result = model._normalize_track_list(raw_tracks)

        assert result[0]["Duration"] == "120.5"
        assert result[0]["NormalField"] == "KeptAsIs"
        assert result[0]["NestedDictNotValue"] == {"other": "data"}
        assert result[1]["BitRate"] == "5000"

    def test_normalize_track_list_non_string_value(self, mediainfo_setup):
        """Hits the branch where '#value' exists but isn't a string (should skip)."""
        model, _ = mediainfo_setup
        raw_tracks = [{"@type": "General", "Number": {"#value": 100}}]

        result = model._normalize_track_list(raw_tracks)

        assert result[0]["Number"] == {"#value": 100}

    def test_extract_and_group_tracks_success(self, mediainfo_setup):
        """Hits the happy path grouping multiple track types accurately."""
        model, _ = mediainfo_setup
        tracks = [
            {"@type": "General", "ID": "gen"},
            {"@type": "Video", "ID": "vid1"},
            {"@type": "Video", "ID": "vid2"},
            {"@type": "Audio", "ID": "aud1"},
        ]

        result = model._extract_and_group_tracks(tracks)

        assert result is not None
        assert result["General"]["ID"] == "gen"
        assert len(result["Video"]) == 2
        assert len(result["Audio"]) == 1

    def test_extract_and_group_tracks_skip_missing_type(self, mediainfo_setup, caplog):
        """Hits the branch where a track lacks an '@type' and gets skipped."""
        model, _ = mediainfo_setup
        tracks = [{"@type": "General", "ID": "gen"}, {"MissingType": True}]

        result = model._extract_and_group_tracks(tracks)

        assert "MissingType" not in result
        assert "Skipping track with no '@type' field" in caplog.text

    def test_extract_and_group_tracks_duplicate_general(self, mediainfo_setup, caplog):
        """Hits the branch handling multiple 'General' tracks."""
        model, _ = mediainfo_setup
        tracks = [{"@type": "General", "ID": "first"}, {"@type": "General", "ID": "second"}]

        result = model._extract_and_group_tracks(tracks)

        assert result["General"]["ID"] == "first"
        assert "Duplicate 'General' track found" in caplog.text

    def test_extract_and_group_tracks_missing_general(self, mediainfo_setup):
        """Hits the failure branch where 'General' track is absent."""
        model, _ = mediainfo_setup
        tracks = [{"@type": "Video", "ID": "vid"}]

        result = model._extract_and_group_tracks(tracks)

        assert result is None
        assert "Mandatory 'General' track missing" in model.error

    def test_main_success(self, mediainfo_setup):
        """Hits the complete successful end-to-end extraction and formatting."""
        model, mock_media_info = mediainfo_setup

        valid_json_output = {
            "media": {
                "track": [
                    {"@type": "General", "Format": "MPEG-4"},
                    {"@type": "Video", "Width": "1920", "Nested": {"#value": "FlattenMe"}},
                ]
            },
            "creatingLibrary": {"name": "MediaInfoLib", "version": "21.09"},
        }
        mock_media_info.parse.return_value = json.dumps(valid_json_output)

        result = model.main()

        mock_media_info.parse.assert_called_once_with(filename="/fake/media.mp4", output="JSON")
        assert result is not None
        assert result["Format"] == "MPEG-4"
        assert result["Video"][0]["Width"] == "1920"
        assert result["Video"][0]["Nested"] == "FlattenMe"
        assert result["creatingLibrary"]["name"] == "MediaInfoLib"
        assert model.error is None

    def test_main_missing_creating_library(self, mediainfo_setup, caplog):
        """Hits the valid branch where creatingLibrary data is missing."""
        model, mock_media_info = mediainfo_setup

        valid_json_output = {"media": {"track": [{"@type": "General"}]}}
        mock_media_info.parse.return_value = json.dumps(valid_json_output)

        result = model.main()

        assert result["creatingLibrary"] is None
        assert "did not contain 'creatingLibrary' information" in caplog.text

    def test_main_library_unavailable(self, mocker):
        """Hits the dependency check branch."""
        mocker.patch("dorsal.file.annotation_models.mediainfo.model.PYMEDIAINFO_AVAILABLE", False)
        model = MediaInfoAnnotationModel(file_path="/fake/media.mp4")

        result = model.main()

        assert result is None
        assert "pymediainfo library is not installed" in model.error

    def test_main_file_not_found(self, mediainfo_setup):
        """Hits the FileNotFoundError branch during MediaInfo parse."""
        model, mock_media_info = mediainfo_setup
        mock_media_info.parse.side_effect = FileNotFoundError("File gone")

        result = model.main()

        assert result is None
        assert "Media file not found at path" in model.error

    def test_main_pymediainfo_runtime_error(self, mediainfo_setup):
        """Hits the RuntimeError branch (e.g. mediainfo binary missing)."""
        model, mock_media_info = mediainfo_setup
        mock_media_info.parse.side_effect = RuntimeError("Binary not found")

        result = model.main()

        assert result is None
        assert "pymediainfo failed to parse file" in model.error

    def test_main_json_decode_error(self, mediainfo_setup):
        """Hits the JSONDecodeError branch when MediaInfo outputs garbage data."""
        model, mock_media_info = mediainfo_setup
        mock_media_info.parse.return_value = "{ broken json: true "

        result = model.main()

        assert result is None
        assert "Failed to decode JSON output from MediaInfo" in model.error

    def test_main_unexpected_error(self, mediainfo_setup):
        """Hits the generic Exception branch during parsing."""
        model, mock_media_info = mediainfo_setup
        mock_media_info.parse.side_effect = Exception("Cosmic ray bit flip")

        result = model.main()

        assert result is None
        assert "An unexpected error occurred during MediaInfo parsing" in model.error

    def test_main_missing_media_track_structure(self, mediainfo_setup):
        """Hits the KeyError/TypeError branch when output is successfully parsed but lacks structure."""
        model, mock_media_info = mediainfo_setup

        mock_media_info.parse.return_value = json.dumps({"completely_different": "schema"})

        result = model.main()

        assert result is None
        assert "missing expected structure ('media.track')" in model.error

    def test_main_grouping_returns_none(self, mediainfo_setup, mocker):
        """Hits the branch where grouping fails (e.g. no General track) forcing main to return None."""
        model, mock_media_info = mediainfo_setup
        mock_media_info.parse.return_value = json.dumps({"media": {"track": []}})

        result = model.main()

        assert result is None
        assert "Mandatory 'General' track missing" in model.error


@pytest.mark.skipif(not PYMEDIAINFO_AVAILABLE, reason="pymediainfo or underlying mediainfo library is not installed.")
class TestMediaInfoAnnotationModelIntegration:
    def test_integration_valid_mp4(self):
        """Tests end-to-end extraction on a real MP4 file."""
        file_path = "tests/data/valid.mp4"
        assert os.path.exists(file_path), f"Test asset missing: {file_path}"

        model = MediaInfoAnnotationModel(file_path=file_path)
        result = model.main()

        assert result is not None
        assert model.error is None

        assert result.get("Format") == "MPEG-4"

        assert "Video" in result
        assert isinstance(result["Video"], list)
        assert len(result["Video"]) >= 1

        assert result["Video"][0].get("Width") == "480"

    def test_integration_valid_mkv(self):
        """Tests end-to-end extraction on a real MKV file."""
        file_path = "tests/data/valid.mkv"
        assert os.path.exists(file_path), f"Test asset missing: {file_path}"

        model = MediaInfoAnnotationModel(file_path=file_path)
        result = model.main()

        assert result is not None
        assert model.error is None
        assert result.get("Format") == "Matroska"
        assert "Video" in result

    def test_integration_valid_image_file(self):
        """
        Tests how MediaInfo behaves with non-video files.
        MediaInfo often successfully parses images, returning 'General' and 'Image' tracks.
        """
        file_path = "tests/data/valid.jpg"
        assert os.path.exists(file_path), f"Test asset missing: {file_path}"

        model = MediaInfoAnnotationModel(file_path=file_path)
        result = model.main()

        assert result is not None
        assert model.error is None
        assert result.get("Format") == "JPEG"

        assert "Image" in result
        assert isinstance(result["Image"], list)

    def test_integration_empty_file(self):
        file_path = "tests/data/empty.txt"
        assert os.path.exists(file_path), f"Test asset missing: {file_path}"

        model = MediaInfoAnnotationModel(file_path=file_path)
        result = model.main()

        assert result is not None
        assert model.error is None

        assert result.get("FileExtension") == "txt"

        assert "Video" not in result
        assert "Audio" not in result
        assert "Image" not in result

    def test_integration_native_file_not_found(self):
        """Tests the native OS/Python FileNotFoundError without mocking."""
        model = MediaInfoAnnotationModel(file_path="tests/data/literally_does_not_exist.mp4")
        result = model.main()

        assert result is None
        assert "Media file not found at path" in model.error
