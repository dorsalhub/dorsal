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
# WITHOUT WARRANTIES OR CONDITIONS OF ANY, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Utility module for normalizing, extracting, and validating
language codes, names, and locales.

This module uses 'langcodes' as its primary engine and supports
a custom 'language_code_mapping.json' for overrides and
a 'supported_locales.json' for whitelisting.

Requires: pip install langcodes[data]
"""

import json
import logging
import os
import re
from typing import Dict, Optional, Set, cast
from functools import lru_cache

try:
    from langcodes import Language, tag_is_valid, find as find_lang, LanguageTagError, DEFAULT_LANGUAGE

    _LANGCODES_AVAILABLE = True
except ImportError:
    _LANGCODES_AVAILABLE = False

    class Language:  # type: ignore[no-redef]
        pass

    class LanguageTagError(Exception):  # type: ignore[no-redef]
        pass

    DEFAULT_LANGUAGE = "en"

logger = logging.getLogger(__name__)


_BASE_DIR = os.path.dirname(__file__)
_MAPPING_FILE = os.path.join(_BASE_DIR, "language_mapping.json")


@lru_cache()
def _get_language_map() -> Dict[str, Dict[str, str | None]]:
    """
    Loads the custom language override map from the JSON file.
    This map is used as a "first pass" before consulting langcodes.
    """
    try:
        with open(_MAPPING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.info(f"Custom language map not found at {_MAPPING_FILE}. Relying on 'langcodes' library only.")
    except json.JSONDecodeError:
        logger.error(f"Critical: Failed to decode language mapping file {_MAPPING_FILE}")
    except Exception as e:
        logger.error(f"Critical: An unexpected error occurred loading {_MAPPING_FILE}: {e}")
    return {}


@lru_cache()
def get_language_set() -> set[str]:
    """
    Get the set of unique, non-null language *names*
    from the *custom override map*.
    """
    language_map = _get_language_map()
    return {cast(str, v.get("name")) for v in language_map.values() if v and v.get("name")}


@lru_cache()
def get_alpha_3_set() -> set[str]:
    """
    Get the set of unique, non-null language *alpha-3 codes*
    from the *custom override map*.
    """
    language_map = _get_language_map()
    return {cast(str, v.get("alpha_3")) for v in language_map.values() if v and v.get("alpha_3")}


@lru_cache()
def _get_lang_obj(lang_str: str | None) -> Optional[Language]:
    """Get a langcodes.Language object from any input string (code, name, or alias)."""
    if not _LANGCODES_AVAILABLE:
        logger.error("The 'langcodes[data]' library is not installed. Language normalization will not work.")
        return None

    if not lang_str or not isinstance(lang_str, str):
        return None

    clean_str = lang_str.strip()

    language_map = _get_language_map()
    if data := language_map.get(clean_str.lower()):
        code_to_parse = data.get("alpha_3") or data.get("name")
        if code_to_parse:
            try:
                return Language.get(code_to_parse)
            except LanguageTagError:
                pass

    code_str = clean_str.replace("_", "-")
    try:
        return Language.get(code_str)
    except LanguageTagError:
        pass

    try:
        return find_lang(clean_str)
    except (LookupError, NotImplementedError):
        logger.debug(f"Could not find or parse language: '{lang_str}'")
        return None


def normalize_language_name(lang_str: str | None) -> str | None:
    """
    Cleans a messy language string and converts it to its standard
    English language name (e.g., "English", "Chinese (Simplified)").

    Relies on 'langcodes[data]' library.
    """
    lang_obj = _get_lang_obj(lang_str)
    if not lang_obj:
        return None

    try:
        return lang_obj.language_name(DEFAULT_LANGUAGE)
    except Exception:
        return None


def normalize_language_alpha3(lang_str: str | None) -> str | None:
    """
    Cleans a messy language string and converts it to its standard
    ISO 639-3 alpha-3 code (e.g., "eng", "fra", "zho").

    Relies on 'langcodes' library.
    """
    lang_obj = _get_lang_obj(lang_str)
    if not lang_obj:
        return None

    try:
        return lang_obj.to_alpha3()
    except LookupError:
        logger.debug(f"Language '{lang_str}' has no alpha-3 code.")
        return None


@lru_cache()
def extract_locale_code(lang_str: str | None) -> str | None:
    """
    Cleans and extracts a BCP-47-like locale code from a messy string.
    This function *identifies* and *cleans* potential locale codes.
    It does not *validate* them against a list of *supported* locales.

    e.g., " en-GB " -> "en-GB"
          "en_US"   -> "en-US"
          "es-419"  -> "es-419"
          "English" -> None (this is a name, not a valid tag)
    """
    if not _LANGCODES_AVAILABLE:
        logger.error("The 'langcodes' library is not installed. Locale extraction will not work.")
        return None

    if not lang_str or not isinstance(lang_str, str):
        return None

    clean_str = lang_str.strip().replace("_", "-")

    if tag_is_valid(clean_str):
        return clean_str

    logger.debug(f"Could not extract a valid locale code from: '{lang_str}'")
    return None
