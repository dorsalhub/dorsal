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

from typing import Any
import json
import logging
import sys

from dorsal.common.exceptions import ValidationError
from dorsal.common.model import AnnotationModel
from dorsal.file.utils.dependencies import initialize_mediainfo

try:
    MediaInfo, MEDIAINFO_LIBRARY_FILE = initialize_mediainfo()
    PYMEDIAINFO_AVAILABLE = True
except ImportError as err:
    error_logger = logging.getLogger(__name__ + ".mediainfo_dependency")
    error_logger.error(str(err))
    MediaInfo = None  # type: ignore
    MEDIAINFO_LIBRARY_FILE = None
    PYMEDIAINFO_AVAILABLE = False

logger = logging.getLogger(__name__)


class MediaInfoAnnotationModel(AnnotationModel):
    """
    Extract metadata from media files using the pymediainfo library.

    This model parses the output of MediaInfo (obtained as JSON) and organizes it into a structured dictionary with a main "General" track
        and lists for other track types (Video, Audio, Text, etc.).
    """

    id = "dorsal/mediainfo"
    version = "1.0.0"
    variant = "pymediainfo"

    def _normalize_track_list(self, track_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Normalize field values within a list of tracks.

        Specifically, flattens structures like `{"#value": "some_string"}` to just `"some_string"`. Modifies the list in-place.

        Args:
          * track_list: A list of track dictionaries from MediaInfo.

        Returns:
          * The normalized track_list.
        """
        logger.debug("Normalizing track list fields...")
        for track in track_list:
            for field, value in track.items():
                if isinstance(value, dict) and "#value" in value and isinstance(value["#value"], str):
                    track[field] = value["#value"]
                    logger.debug(
                        "Normalized field '%s' in track type '%s'.",
                        field,
                        track.get("@type", "Unknown"),
                    )
        return track_list

    def _extract_and_group_tracks(self, track_list: list[dict[str, Any]]) -> dict[str, Any] | None:
        """
        Group tracks by their type (General, Video, Audio, etc.).

        The "General" track is stored directly. Other types are stored as lists of tracks.

        Args:
          * track_list: The list of (normalized) track dictionaries.

        Returns:
          * A dictionary grouping tracks by type, or None if 'General' track is missing (in which case `self.error` is set).
        """
        logger.debug("Extracting and grouping tracks by type...")
        grouped_tracks: dict[str, Any] = {}

        for track in track_list:
            track_type = track.get("@type")
            if not track_type:
                logger.debug("Skipping track with no '@type' field: %s", str(track)[:100])
                continue

            track_type_str = str(track_type)

            if track_type_str == "General":
                if "General" in grouped_tracks:
                    logger.warning(
                        "Duplicate 'General' track found for file '%s'. Using the first one encountered.",
                        self.file_path,
                    )
                else:
                    grouped_tracks["General"] = track
            else:
                grouped_tracks.setdefault(track_type_str, []).append(track)

        if "General" not in grouped_tracks:
            self.error = f"Mandatory 'General' track missing from MediaInfo output for file '{self.file_path}'."
            logger.error(self.error)
            return None

        logger.debug(
            "Tracks successfully grouped for file '%s'. Types found: %s",
            self.file_path,
            list(grouped_tracks.keys()),
        )
        return grouped_tracks

    def main(self) -> dict[str, Any] | None:
        """
        Extract, normalize, and structure metadata from the media file.

        Returns:
          * Dictionary of structured MediaInfo data if successful.
          * None if pymediainfo library is unavailable, file cannot be parsed, or essential data is missing.
            `self.error` will be set in case of failure.
        """
        if not PYMEDIAINFO_AVAILABLE:
            self.error = f"pymediainfo library is not installed; cannot process media file: '{self.file_path}'"
            logger.error(self.error)
            return None

        logger.debug("MediaInfoAnnotationModel: Starting parsing for '%s'", self.file_path)

        try:
            raw_mediainfo_json_str: str = MediaInfo.parse(filename=self.file_path, output="JSON")
            mediainfo_data = json.loads(raw_mediainfo_json_str)
            logger.debug("MediaInfo.parse and json.loads successful for '%s'", self.file_path)

        except FileNotFoundError:
            self.error = f"Media file not found at path: {self.file_path}"
            logger.error(self.error)
            return None
        except (RuntimeError, OSError) as err:
            self.error = f"pymediainfo failed to parse file '{self.file_path}': {err}"
            logger.exception("MediaInfoAnnotationModel: %s", self.error)
            return None
        except json.JSONDecodeError as err:
            self.error = f"Failed to decode JSON output from MediaInfo for file '{self.file_path}': {err}"
            logger.exception(
                "MediaInfoAnnotationModel: %s. Raw output snippet: %.200s",
                self.error,
                raw_mediainfo_json_str or "",
            )
            return None
        except Exception as err:
            self.error = f"An unexpected error occurred during MediaInfo parsing of '{self.file_path}': {err}"
            logger.exception("MediaInfoAnnotationModel: %s", self.error)
            return None

        try:
            track_list: list[dict[str, Any]] = mediainfo_data["media"]["track"]
            creating_library_data = mediainfo_data.get("creatingLibrary")
        except (KeyError, TypeError) as err:
            self.error = (
                f"MediaInfo JSON output for '{self.file_path}' missing expected structure ('media.track'): {err}"
            )
            logger.exception(
                "MediaInfoAnnotationModel: %s. Data snippet: %s",
                self.error,
                str(mediainfo_data)[:500],
            )
            return None

        normalized_track_list = self._normalize_track_list(track_list=track_list)
        grouped_tracks = self._extract_and_group_tracks(track_list=normalized_track_list)

        if grouped_tracks is None:
            return None

        general_track = grouped_tracks.pop("General")
        final_record = {**general_track, **grouped_tracks}

        final_record["creatingLibrary"] = creating_library_data
        if not creating_library_data:
            logger.debug(
                "MediaInfo output for '%s' did not contain 'creatingLibrary' information.",
                self.file_path,
            )

        logger.debug("MediaInfoAnnotationModel: Successfully processed file '%s'", self.file_path)
        return final_record
