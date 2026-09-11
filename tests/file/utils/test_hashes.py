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
from dorsal.common.exceptions import ValidationError

from dorsal.file.utils.hashes import (
    HashStringValidator,
    hash_string_validator,
    parse_validate_hash,
)

SAMPLE_MD5 = "d41d8cd98f00b204e9800998ecf8427e"
SAMPLE_SHA1 = "da39a3ee5e6b4b0d3255bfef95601890afd80709"
SAMPLE_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
SAMPLE_TLSH = "T11234567890ABCDEF1234567890ABCDEF1234567890ABCDEF1234567890ABCDEF123456"


class TestParseValidateHash:
    """Functional tests for parse_validate_hash."""

    @pytest.mark.parametrize(
        ("raw_hash", "expected_value", "expected_type"),
        [
            (SAMPLE_MD5, SAMPLE_MD5, "MD5"),
            (SAMPLE_SHA1, SAMPLE_SHA1, "SHA-1"),
            (SAMPLE_SHA256, SAMPLE_SHA256, "SHA-256"),
            (SAMPLE_TLSH, SAMPLE_TLSH.lower(), "TLSH"),
            (SAMPLE_MD5.upper(), SAMPLE_MD5, "MD5"),
            (SAMPLE_SHA256.upper(), SAMPLE_SHA256, "SHA-256"),
        ],
    )
    def test_unprefixed_valid_hashes(self, raw_hash, expected_value, expected_type):
        val, hash_type = parse_validate_hash(raw_hash)
        assert val == expected_value
        assert hash_type == expected_type

    @pytest.mark.parametrize(
        ("prefix", "raw_value", "expected_type"),
        [
            ("sha-256", SAMPLE_SHA256, "SHA-256"),
            ("sha256", SAMPLE_SHA256, "SHA-256"),
            ("blake3", SAMPLE_SHA256, "BLAKE3"),
            ("quick", SAMPLE_SHA256, "QUICK"),
            ("dorsal", SAMPLE_SHA256, "DORSAL"),
            ("md5", SAMPLE_MD5, "MD5"),
            ("sha-1", SAMPLE_SHA1, "SHA-1"),
            ("sha1", SAMPLE_SHA1, "SHA-1"),
            ("tlsh", SAMPLE_TLSH, "TLSH"),
        ],
    )
    def test_prefixed_valid_hashes(self, prefix, raw_value, expected_type):
        prefixed_input = f"{prefix}:{raw_value}"
        val, hash_type = parse_validate_hash(prefixed_input)
        assert val == raw_value.lower()
        assert hash_type == expected_type

    @pytest.mark.parametrize(
        "invalid_input",
        [
            "",
            None,
            12345,
            "not_a_hash",
            "d41d8cd98f00b204e9800998ecf8427",
            "da39a3ee5e6b4b0d3255bfef95601890afd807090",
            "sha-256:invalid_len",
            "unknown_prefix:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "tlsh:not_a_valid_tlsh_length",
        ],
    )
    def test_invalid_hashes(self, invalid_input):
        val, hash_type = parse_validate_hash(invalid_input)
        assert val is None
        assert hash_type is None


class TestHashStringValidator:
    """Functional tests for HashStringValidator class."""

    @pytest.fixture
    def validator(self):
        return HashStringValidator()

    @pytest.mark.parametrize(
        ("candidate", "expected"),
        [
            ("SHA-256", True),
            ("BLAKE3", True),
            ("TLSH", True),
            ("QUICK", True),
            ("MD5", True),
            ("SHA-1", True),
            ("DORSAL", True),
            ("INVALID", False),
            ("sha-256", False),
        ],
    )
    def test_is_supported_hash_function(self, validator, candidate, expected):
        assert validator.is_supported_hash_function(candidate) == expected

    @pytest.mark.parametrize(
        ("candidate_string", "hash_function", "expected"),
        [
            (SAMPLE_SHA256, "SHA-256", True),
            (SAMPLE_SHA256, "sha-256", True),
            (SAMPLE_MD5, "MD5", True),
            (SAMPLE_SHA1, "SHA-1", True),
            (SAMPLE_TLSH, "TLSH", True),
            ("invalid_hash", "SHA-256", False),
            (12345, "SHA-256", False),
            (SAMPLE_MD5, "SHA-256", False),
        ],
    )
    def test_is_valid(self, validator, candidate_string, hash_function, expected):
        assert validator.is_valid(candidate_string, hash_function) == expected

    def test_is_valid_unsupported_function_raises(self, validator):
        with pytest.raises(ValidationError, match="Unknown/unsupported hash function"):
            validator.is_valid(SAMPLE_SHA256, "UNSUPPORTED_FUNC")

    def test_validate_success(self, validator):
        assert validator.validate(SAMPLE_SHA256, "SHA-256") is None

    def test_validate_failure_raises(self, validator):
        with pytest.raises(ValidationError, match="Invalid SHA-256 string"):
            validator.validate("bad_hash", "SHA-256")

    def test_get_valid_hash_formatting(self, validator):

        res_sha256 = validator.get_valid_hash(SAMPLE_SHA256.upper(), "SHA-256")
        assert res_sha256 == SAMPLE_SHA256.lower()

        res_tlsh = validator.get_valid_hash(SAMPLE_TLSH.lower(), "TLSH")
        assert res_tlsh == SAMPLE_TLSH.upper()

        assert validator.get_valid_hash("invalid", "SHA-256") is None

    def test_module_singleton_instance(self):
        assert isinstance(hash_string_validator, HashStringValidator)
