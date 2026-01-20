# Copyright 2025-2026 Dorsal Hub LTD
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
import re
from unittest.mock import MagicMock


from dorsal.file.configs import model_runner
from dorsal.file.configs.model_runner import (
    check_media_type_dependency,
    check_extension_dependency,
    check_size_dependency,
    check_name_dependency,
    MediaTypeDependencyConfig,
    FileExtensionDependencyConfig,
    FileSizeDependencyConfig,
    FilenameDependencyConfig,
)


@pytest.fixture
def mock_results():
    """Factory to create a list containing a single mock RunModelResult."""

    def _create(record_data):
        mock_res = MagicMock()

        mock_res.record = record_data
        return [mock_res]

    return _create


class TestCheckMediaTypeDependency:
    """Tests for check_media_type_dependency including all unhappy paths."""

    def test_missing_base_record(self):
        """Unhappy Path: model_results[0].record is None."""
        results = [MagicMock(record=None)]
        config = MediaTypeDependencyConfig(include={"text/plain"})

        assert check_media_type_dependency(results, config) is False

    def test_record_missing_media_type_field(self, mock_results):
        """Unhappy Path: record exists but has no 'media_type' key."""
        results = mock_results({"size": 100})
        config = MediaTypeDependencyConfig(include={"text/plain"})

        assert check_media_type_dependency(results, config) is False

    def test_explicit_exclude_full_match(self, mock_results):
        """Unhappy Path: Media type matches an entry in 'exclude' list fully."""
        results = mock_results({"media_type": "application/pdf"})
        config = MediaTypeDependencyConfig(exclude={"application/pdf"})

        assert check_media_type_dependency(results, config) is False

    def test_explicit_exclude_head_match(self, mock_results):
        """Unhappy Path: Media type head (prefix) matches 'exclude'."""
        results = mock_results({"media_type": "image/png"})
        config = MediaTypeDependencyConfig(exclude={"image"})

        assert check_media_type_dependency(results, config) is False

    def test_include_rule_mismatch(self, mock_results):
        """Unhappy Path: Inclusion rules exist, but media type doesn't match."""
        results = mock_results({"media_type": "text/csv"})
        config = MediaTypeDependencyConfig(include={"application/pdf"})

        assert check_media_type_dependency(results, config) is False

    def test_pattern_rule_mismatch(self, mock_results):
        """Unhappy Path: Regex pattern provided, but doesn't match."""
        results = mock_results({"media_type": "audio/mpeg"})
        config = MediaTypeDependencyConfig(pattern=r"^image/.*")

        assert check_media_type_dependency(results, config) is False

    def test_include_full_match_success(self, mock_results):
        """Happy Path: Exact match in 'include'."""
        results = mock_results({"media_type": "application/json"})
        config = MediaTypeDependencyConfig(include={"application/json", "text/plain"})

        assert check_media_type_dependency(results, config) is True

    def test_include_head_match_success(self, mock_results):
        """Happy Path: Head match in 'include'."""
        results = mock_results({"media_type": "video/mp4"})
        config = MediaTypeDependencyConfig(include={"video"})

        assert check_media_type_dependency(results, config) is True

    def test_pattern_string_match_success(self, mock_results):
        """Happy Path: Regex string matches."""
        results = mock_results({"media_type": "text/x-python"})
        config = MediaTypeDependencyConfig(pattern=r"text/.*")

        assert check_media_type_dependency(results, config) is True

    def test_pattern_compiled_match_success(self, mock_results):
        """Happy Path: Compiled regex matches."""
        results = mock_results({"media_type": "application/vnd.ms-excel"})
        config = MediaTypeDependencyConfig(pattern=re.compile(r".*excel$"))

        assert check_media_type_dependency(results, config) is True

    def test_no_rules_passthrough(self, mock_results):
        """Happy Path: No include/exclude/pattern rules provided -> Pass."""
        results = mock_results({"media_type": "any/thing"})
        config = MediaTypeDependencyConfig()

        assert check_media_type_dependency(results, config) is True


class TestCheckExtensionDependency:
    def test_extension_match_success(self, mock_results):
        results = mock_results({"extension": ".pdf"})
        config = FileExtensionDependencyConfig(extensions={".pdf", ".txt"})

        assert check_extension_dependency(results, config) is True

    def test_extension_case_insensitivity(self, mock_results):
        """Verify extension matching handles case differences (logic usually lowercases)."""
        results = mock_results({"extension": ".PDF"})
        config = FileExtensionDependencyConfig(extensions={".pdf"})

        assert check_extension_dependency(results, config) is True

    def test_extension_mismatch(self, mock_results):
        results = mock_results({"extension": ".jpg"})
        config = FileExtensionDependencyConfig(extensions={".png"})

        assert check_extension_dependency(results, config) is False

    def test_missing_record_or_extension(self, mock_results):
        assert (
            check_extension_dependency([MagicMock(record=None)], FileExtensionDependencyConfig(extensions={".pdf"}))
            is False
        )

        assert (
            check_extension_dependency(
                mock_results({"other": "field"}), FileExtensionDependencyConfig(extensions={".pdf"})
            )
            is False
        )

        assert (
            check_extension_dependency(
                mock_results({"extension": None}), FileExtensionDependencyConfig(extensions={".pdf"})
            )
            is False
        )


class TestCheckSizeDependency:
    def test_size_within_range(self, mock_results):
        results = mock_results({"size": 500})
        config = FileSizeDependencyConfig(min_size=100, max_size=1000)

        assert check_size_dependency(results, config) is True

    def test_size_below_min(self, mock_results):
        results = mock_results({"size": 50})
        config = FileSizeDependencyConfig(min_size=100)

        assert check_size_dependency(results, config) is False

    def test_size_above_max(self, mock_results):
        results = mock_results({"size": 2000})
        config = FileSizeDependencyConfig(max_size=1000)

        assert check_size_dependency(results, config) is False

    def test_invalid_size_field(self, mock_results):
        assert check_size_dependency(mock_results({}), FileSizeDependencyConfig(min_size=1)) is False

        assert check_size_dependency(mock_results({"size": "big"}), FileSizeDependencyConfig(min_size=1)) is False


class TestCheckNameDependency:
    def test_name_match_regex_string(self, mock_results):
        results = mock_results({"name": "report_2025.pdf"})
        config = FilenameDependencyConfig(pattern=r"^report_\d+")

        assert check_name_dependency(results, config) is True

    def test_name_match_compiled_regex(self, mock_results):
        results = mock_results({"name": "test_file.py"})
        config = FilenameDependencyConfig(pattern=re.compile(r"\.py$"))

        assert check_name_dependency(results, config) is True

    def test_name_mismatch(self, mock_results):
        results = mock_results({"name": "image.png"})
        config = FilenameDependencyConfig(pattern=r"\.txt$")

        assert check_name_dependency(results, config) is False

    def test_missing_name_field(self, mock_results):
        results = mock_results({"size": 100})
        config = FilenameDependencyConfig(pattern=r".*")

        assert check_name_dependency(results, config) is False
