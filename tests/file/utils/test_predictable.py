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
from dorsal.file.utils.predictable import Predictable

# A sequence of 3 integers representing 0.0, 0.5, and 0.9 (approx)
# SCALE is 10**18
FIXED_SEQUENCE = [0, 5 * 10**17, 9 * 10**17]


def test_init_valid():
    p = Predictable(FIXED_SEQUENCE, seed=0)
    assert p._get_current_value() == 0


def test_init_seed_offset():
    p = Predictable(FIXED_SEQUENCE, seed=1)
    assert p._get_current_value() == 5 * 10**17


def test_init_invalid_seed():
    with pytest.raises(ValueError):
        Predictable(FIXED_SEQUENCE, seed=99)
    with pytest.raises(ValueError):
        Predictable(FIXED_SEQUENCE, seed=-1)


def test_random_generation():
    p = Predictable(FIXED_SEQUENCE)

    assert p.random() == 0.0
    assert p.random() == 0.5
    assert p.random() == 0.9
    # Wrap around
    assert p.random() == 0.0


def test_randint():
    # Using a simpler sequence for integer mapping
    # 0.0 -> maps to 'a'
    # 0.9 -> maps near 'b'
    p = Predictable([0, 99 * 10**16])  # 0.0, 0.99

    # randint(10, 20) range size 11
    # 0.0 * 11 = 0 -> 10 + 0 = 10
    assert p.randint(10, 20) == 10

    # 0.99 * 11 = 10.89 -> int is 10 -> 10 + 10 = 20
    assert p.randint(10, 20) == 20


def test_randint_invalid():
    p = Predictable(FIXED_SEQUENCE)
    with pytest.raises(ValueError):
        p.randint(10, 5)  # b < a


def test_randrange():
    # Sequence: 0.0, 0.5, 0.9
    p = Predictable(FIXED_SEQUENCE)

    # randrange(10): range(0, 10) -> size 10
    # 0.0 -> 0
    assert p.randrange(10) == 0

    # 0.5 -> 5
    assert p.randrange(10) == 5

    # 0.9 -> 9
    assert p.randrange(10) == 9


def test_randrange_start_stop():
    # Sequence: 0.0
    p = Predictable([0])

    # randrange(5, 10) -> range(5, 10) -> starts at 5
    assert p.randrange(5, 10) == 5


def test_randrange_errors():
    p = Predictable(FIXED_SEQUENCE)

    # Invalid step
    with pytest.raises(NotImplementedError):
        p.randrange(0, 10, step=2)

    # Empty range (stop <= start)
    with pytest.raises(ValueError):
        p.randrange(10, 10)

    # Invalid upper bound when stop is None
    with pytest.raises(ValueError):
        p.randrange(0)
