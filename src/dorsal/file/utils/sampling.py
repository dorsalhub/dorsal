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

import logging
from itertools import islice
import math
from typing import Any, Iterable, TypeVar


from .predictable import Predictable
from ..configs.sampling import predictable_numbers

EOI = object

logger = logging.getLogger(__name__)


T_co = TypeVar("T_co", covariant=True)


def reservoir_sample_r(iterable: Iterable[T_co], k: int, seed: int) -> list[T_co]:
    """
    Selects a random sample of k items from an iterable using Algorithm R.

    Note: Algorithm R is used over L for cross-compatability (i.e. no dependencies of math.log, math.exp etc.)

    Args:
        iterable: The iterable to sample from.
        k: The desired sample size (number of items to select).
        seed: The seed for the `Predictable` number generator

    Returns:
        A list containing the random sample of k items. If the iterable
        contains fewer than k items, all items from the iterable are returned.
    """
    if k < 0:
        raise ValueError("Sample size k cannot be negative.")
    if k == 0:
        return []

    it = iter(iterable)

    reservoir: list[T_co] = list(islice(it, k))

    if len(reservoir) < k:
        return reservoir

    png = Predictable(sequence=predictable_numbers, seed=seed)
    for i, item in enumerate(it, start=k):
        j = png.randrange(0, i + 1)
        if j < k:
            reservoir[j] = item
    return reservoir
