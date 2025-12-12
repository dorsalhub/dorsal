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

import json
import logging
import mimetypes
import os
import sys
from typing import TYPE_CHECKING
import zipfile

from dorsal.file.utils.dependencies import initialize_mediainfo, initialize_magic


logger = logging.getLogger(__name__)

try:
    magic, MagicException = initialize_magic()
    PYMAGIC_AVAILABLE = True
except ImportError as err:
    logger.error(str(err))
    magic = None  # type: ignore
    MagicException = Exception  # type: ignore
    PYMAGIC_AVAILABLE = False

try:
    MediaInfo, MEDIAINFO_LIBRARY_FILE = initialize_mediainfo()
    PYMEDIAINFO_AVAILABLE = True
except ImportError:
    MediaInfo = None  # type: ignore
    MEDIAINFO_LIBRARY_FILE = None
    PYMEDIAINFO_AVAILABLE = False


RETURN_DEFAULT: set[str] = {
    "inode/x-empty",
}

PREFER_CUSTOM_RULES: set[str] = {
    ".mkv",
    ".docx",
    ".xlsx",
    ".pptx",
}

PREFER_BUILTIN_MIMETYPES: set[str | tuple[str, str]] = {
    "inode/blockdevice",
}

MAP_EXTENSION_TO_MEDIATYPE: dict[str, str] = {
    ".iso": "application/vnd.efi.iso",
}

MAP_MEDIATYPE_TO_MEDIATYPE: dict[str, str] = {
    "video/x-matroska": "video/matroska",
    "audio/x-flac": "audio/flac",
    "application/x-rar": "application/vnd.rar",
    "application/x-iso9660-image": "application/vnd.efi.iso",
}

OOXML_SIGNATURES = {
    ".docx": ("word/document.xml", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".xlsx": ("xl/workbook.xml", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".pptx": ("ppt/presentation.xml", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
}

INCORRECT_OOXML_IDENTITIES = {
    "application/zip",
    "application/octet-stream",
    "application/x-zip-compressed",
}


def _get_mediainfo_format(file_path: str) -> str | None:
    """
    Parses the file with pymediainfo to get the general format.
    """
    try:
        mediainfo = MediaInfo.parse(file_path, output="JSON")
        mediainfo_data: dict[str, dict[str, dict]] = json.loads(mediainfo)
    except (RuntimeError, OSError) as err:
        logger.exception("Failed to open file path with MediaInfo: %s - %s", err, file_path)
        return None
    except Exception as err:
        logger.exception("Failed to open file path with MediaInfo: %s - %s", err, file_path)
        return None

    for track in mediainfo_data.get("media", {}).get("track", {}):
        track_type = track.get("@type")
        if track_type == "General":
            return track.get("Format")
    return None


def _infer_mediatype_rule_mkv(file_path: str, magical_prior: str | None = None) -> str | None:
    """
    Custom rule to correctly identify Matroska video files.
    """
    if magical_prior and magical_prior in (
        "video/x-matroska",
        "video/matroska",
    ):
        return "video/matroska"

    video_format = _get_mediainfo_format(file_path=file_path)
    if video_format == "Matroska":
        return "video/matroska"
    return None


def _infer_office_xml_rule(file_path: str, file_extension: str, magical_prior: str | None) -> str | None:
    """
    Inspects the internal structure of a Zip-based file to determine if it is
    a valid Office Open XML document (DOCX, XLSX, PPTX).
    """
    if magical_prior and magical_prior not in INCORRECT_OOXML_IDENTITIES:
        return None

    if file_extension not in OOXML_SIGNATURES:
        return None

    target_xml, target_mime = OOXML_SIGNATURES[file_extension]

    try:
        with zipfile.ZipFile(file_path, "r") as zf:
            namelist = set(zf.namelist())

            if target_xml in namelist:
                return target_mime

    except (zipfile.BadZipFile, OSError):
        return None

    return None


def _apply_custom_rules(file_path: str, file_extension: str, magical_prior: str | None = None) -> str | None:
    """
    Applies custom, extension-specific rules to infer media type.
    """
    if file_extension == ".mkv":
        return _infer_mediatype_rule_mkv(file_path=file_path, magical_prior=magical_prior)

    if file_extension in OOXML_SIGNATURES:
        return _infer_office_xml_rule(file_path=file_path, file_extension=file_extension, magical_prior=magical_prior)

    return None


def _strip_media_type_parameters(media_type_full: str | None) -> str | None:
    """
    Helper function to strip parameters (e.g., ';charset=utf-8') from a media type string.
    """
    if not media_type_full:
        return None
    if ";" in media_type_full:
        return media_type_full.split(";", 1)[0].strip()
    return media_type_full


def _get_libmagic_type(file_path: str) -> str | None:
    """
    Determines the media type using the `python-magic` library.
    """
    try:
        media_type = magic.from_file(file_path, mime=True)
        base_media_type = _strip_media_type_parameters(media_type)
        if media_type and base_media_type == media_type:
            logger.debug("libmagic.from_file for '%s' yielded: '%s'", file_path, base_media_type)
        elif not media_type:
            logger.debug("libmagic.from_file for '%s' yielded: None or empty string", file_path)
        return base_media_type
    except MagicException as e:
        logger.warning("libmagic (python-magic) failed for file '%s': %s.", file_path, e)
        return None
    except NameError:
        logger.error("python-magic library is not available or failed to import.")
        return None
    except Exception as e:
        logger.error("Unexpected error using libmagic for file '%s': %s", file_path, e)
        return None


def _get_mimetypes_library_type(file_path: str) -> str | None:
    """
    Guesses the media type using Python's built-in `mimetypes` library.
    """
    media_type, _ = mimetypes.guess_type(file_path, strict=False)
    base_media_type = _strip_media_type_parameters(media_type)
    if not media_type:
        logger.debug("mimetypes.guess_type for '%s' yielded: None", file_path)
    return base_media_type


def _get_default_media_type(file_path: str) -> str:
    """
    Determine a default media type based on basic file characteristics.
    """
    try:
        with open(file_path, "rb") as fp:
            first_byte = fp.read(1)
        if not first_byte:
            return "application/x-empty"
        return "application/octet-stream"
    except IOError as e:
        logger.error("Error determining default media type for '%s': %s", file_path, e)
        raise


def _refine_media_type_with_rules(
    initial_media_type: str | None, file_path: str, file_extension: str | None
) -> str | None:
    """
    Applies a series of rules to refine an initial base media type guess:

    1. Apply custom rules
    2. Override: Fallback to python `mimetypes` media-type for specific media types
    3. Override: Return default type for specific media types
    4. Normalize: Return normalized form for specific media types
    """
    current_type = initial_media_type
    logger.debug(
        "Refining media type. Initial base type: '%s', Extension: '%s'",
        current_type,
        file_extension,
    )

    if file_extension and file_extension in PREFER_CUSTOM_RULES:
        logger.debug("Applying custom inference rule for extension '%s'.", file_extension)
        custom_inferred_type = _apply_custom_rules(
            file_path=file_path,
            file_extension=file_extension,
            magical_prior=current_type,
        )
        current_type = _strip_media_type_parameters(custom_inferred_type) or current_type

    should_try_mimetypes_lib = False
    if current_type is None:
        should_try_mimetypes_lib = True
    elif current_type in PREFER_BUILTIN_MIMETYPES:
        should_try_mimetypes_lib = True
    elif file_extension and (current_type, file_extension) in PREFER_BUILTIN_MIMETYPES:
        should_try_mimetypes_lib = True

    if should_try_mimetypes_lib:
        mimetypes_lib_type = _get_mimetypes_library_type(file_path)
        if mimetypes_lib_type:
            current_type = mimetypes_lib_type
        elif file_extension and file_extension in MAP_EXTENSION_TO_MEDIATYPE:
            current_type = MAP_EXTENSION_TO_MEDIATYPE[file_extension]

    if current_type and current_type in RETURN_DEFAULT:
        current_type = _get_default_media_type(file_path)

    if current_type and current_type in MAP_MEDIATYPE_TO_MEDIATYPE:
        current_type = MAP_MEDIATYPE_TO_MEDIATYPE[current_type]

    logger.debug("Refined base media type after all rules: '%s'", current_type)
    return current_type


def get_media_type(file_path: str, file_extension: str | None) -> str:
    """
    Determines the 'best guess' media type for the file.

    This function orchestrates the media type detection process:
    1. Attempts to get a type using libmagic.
    2. Applies a series of refinement rules (custom logic, mimetypes library, mappings).
    3. Falls back to a basic default type if all else fails.

    Args:
        file_path: The absolute path to the file.
        file_extension: The file's extension (e.g., ".txt"), or None.

    Returns:
        The determined media type string. This method always returns a string,
        falling back to a default like 'application/octet-stream' if necessary.
    """
    libmagic_initial_type = _get_libmagic_type(file_path)

    refined_media_type = _refine_media_type_with_rules(
        initial_media_type=libmagic_initial_type,
        file_path=file_path,
        file_extension=file_extension,
    )

    final_media_type = refined_media_type if refined_media_type is not None else _get_default_media_type(file_path)

    logger.debug(
        "Final determined media type for '%s': %s (Initial libmagic: '%s')",
        file_path,
        final_media_type,
        libmagic_initial_type,
    )
    return final_media_type
