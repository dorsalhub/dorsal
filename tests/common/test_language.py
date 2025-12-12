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
import json
from dorsal.common.language import (
    _get_language_map,
    get_language_set,
    get_alpha_3_set,
    normalize_language_name,
    normalize_language_alpha3,
    extract_locale_code,
)


@pytest.fixture
def mock_mapping_file(tmp_path, mocker):
    """Mocks the JSON mapping file."""
    data = {
        "custom_lang": {"name": "CustomLang", "alpha_3": "cst"},
        "alias_lang": {"name": "English", "alpha_3": "eng"},
    }
    f = tmp_path / "language_mapping.json"
    f.write_text(json.dumps(data))

    mocker.patch("dorsal.common.language._MAPPING_FILE", str(f))
    _get_language_map.cache_clear()
    get_language_set.cache_clear()
    get_alpha_3_set.cache_clear()
    return f


@pytest.fixture
def mock_langcodes(mocker):
    """Mocks the langcodes library functions."""
    mock_mod = mocker.MagicMock()
    mock_lang_obj = mocker.MagicMock()
    mock_lang_obj.language_name.return_value = "English"
    mock_lang_obj.to_alpha3.return_value = "eng"

    mock_mod.Language.get.return_value = mock_lang_obj
    mock_mod.find.return_value = mock_lang_obj
    mock_mod.tag_is_valid.return_value = True

    mocker.patch("dorsal.common.language._LANGCODES_AVAILABLE", True)

    class MockLanguageTagError(Exception):
        pass

    mocker.patch("dorsal.common.language.LanguageTagError", MockLanguageTagError)
    mock_mod.LanguageTagError = MockLanguageTagError

    mocker.patch("dorsal.common.language.find_lang", mock_mod.find)
    mocker.patch("dorsal.common.language.Language", mock_mod.Language)
    mocker.patch("dorsal.common.language.tag_is_valid", mock_mod.tag_is_valid)

    return mock_mod


# --- Tests ---


def test_load_mapping_success(mock_mapping_file):
    mapping = _get_language_map()
    assert "custom_lang" in mapping


def test_load_mapping_missing(mocker):
    mocker.patch("dorsal.common.language._MAPPING_FILE", "nonexistent.json")
    _get_language_map.cache_clear()
    assert _get_language_map() == {}


def test_public_sets(mock_mapping_file):
    assert "CustomLang" in get_language_set()
    assert "cst" in get_alpha_3_set()


def test_normalize_name_custom_map(mock_mapping_file, mock_langcodes):
    mock_lang_instance = mock_langcodes.Language.get.return_value
    mock_lang_instance.language_name.return_value = "CustomLang"

    assert normalize_language_name("custom_lang") == "CustomLang"


def test_normalize_name_standard(mock_langcodes):
    assert normalize_language_name("en") == "English"


def test_normalize_name_lookup_error(mock_langcodes):
    # Simulate lookup failure for both find() and get()
    mock_langcodes.find.side_effect = LookupError

    # Make get() raise the specific error the code catches
    mock_langcodes.Language.get.side_effect = mock_langcodes.LanguageTagError

    # Clear cache for _get_lang_obj to force re-run
    from dorsal.common.language import _get_lang_obj

    _get_lang_obj.cache_clear()

    assert normalize_language_name("made_up_lang") is None


def test_normalize_alpha3(mock_langcodes):
    assert normalize_language_alpha3("en") == "eng"


def test_normalize_alpha3_und(mock_langcodes):
    # Undetermined language has no alpha3
    lang_obj = mock_langcodes.Language.get.return_value
    lang_obj.to_alpha3.side_effect = LookupError

    assert normalize_language_alpha3("und") is None


def test_library_not_available(mocker):
    mocker.patch("dorsal.common.language._LANGCODES_AVAILABLE", False)
    from dorsal.common.language import _get_lang_obj

    _get_lang_obj.cache_clear()

    assert normalize_language_name("en") is None
    assert extract_locale_code("en-US") is None


def test_extract_locale_code(mock_langcodes):
    assert extract_locale_code(" en_US ") == "en-US"

    mock_langcodes.tag_is_valid.return_value = False
    assert extract_locale_code("invalid_tag") is None
