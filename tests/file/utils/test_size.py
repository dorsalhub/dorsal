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
from dorsal.file.utils.size import get_filesize, human_filesize, parse_filesize


def test_get_filesize_success(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("12345")
    assert get_filesize(str(f)) == 5


def test_get_filesize_error(tmp_path):
    with pytest.raises(OSError):
        get_filesize(str(tmp_path / "ghost.txt"))


def test_human_filesize():
    assert human_filesize(100) == "100 B"
    assert human_filesize(1024) == "1 KiB"
    assert human_filesize(1024 * 1024) == "1 MiB"
    assert human_filesize(1024 * 1024 * 1024) == "1.00 GiB"

    # Config has 'KiB': 0 decimal places, so 1.46 KiB rounds to '1 KiB'
    assert human_filesize(1500) == "1 KiB"


def test_parse_filesize_integers():
    assert parse_filesize("100") == 100
    assert parse_filesize("  500  ") == 500


def test_parse_filesize_units_si():
    assert parse_filesize("1 KB") == 1000
    assert parse_filesize("2.5 MB") == 2_500_000
    assert parse_filesize("1 GB") == 1_000_000_000


def test_parse_filesize_units_iec():
    assert parse_filesize("1 KiB") == 1024
    assert parse_filesize("1 MiB") == 1024 * 1024


def test_parse_filesize_case_insensitivity():
    assert parse_filesize("1 kib") == 1024
    assert parse_filesize("1 KIB") == 1024


def test_parse_filesize_errors():
    with pytest.raises(ValueError):
        parse_filesize("invalid")

    with pytest.raises(ValueError):
        parse_filesize("100 ZB")

    with pytest.raises(ValueError):
        parse_filesize("ten MB")
