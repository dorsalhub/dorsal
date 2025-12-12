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


class Predictable:
    """Predictable number generator designed for cross-platform determinism.

    - Infinitely cycles through a pre-loaded sequence of large integers.
    - Methods 'random', 'randint', and 'randrange' mimic random.Random methods
      without the randomness, using integers for compatability
    - Parameter 'seed' optionally provides an offset into the sequence.

    """

    _SCALE = 10**18

    def __init__(self, sequence: list[int], seed: int = 0):
        """
        Initializes the generator with a sequence of large integers and a seed.

        Args:
            sequence: A list of large integers (pre-scaled from floats).
            seed: The starting offset in the sequence.
        """
        self.sequence = sequence
        self._check_offset(seed)
        self._current_index = seed

    def _check_offset(self, offset: int) -> None:
        """Ensure the offset value is less than number sequence length."""
        if not (0 <= offset < len(self.sequence)):
            raise ValueError(
                f"Seed (offset) is out of bounds. Must be an integer value between "
                f"0 and {len(self.sequence) - 1} (inclusive), got {offset}."
            )

    def _increment(self) -> None:
        """Iterate through sequence.

        Note: once the end is reached, begins again.

        """
        if self._current_index >= len(self.sequence) - 1:
            self._current_index = 0
        else:
            self._current_index += 1

    def _get_current_value(self) -> int:
        """Returns the large integer at the current index."""
        return self.sequence[self._current_index]

    def _next_predictable_int(self) -> int:
        """Return the integer at the current index, and moves the index along."""
        val = self._get_current_value()
        self._increment()
        return val

    def random(self) -> float:
        """Return a predictable float N where 0.0 <= N < 1.0."""
        return self._next_predictable_int() / self._SCALE

    def randint(self, a: int, b: int) -> int:
        """Return a predictable integer N such that a <= N <= b.

        Mimics `random.randint(a, b)` using portable integer arithmetic.

        Args:
            a: The lower bound (inclusive).
            b: The upper bound (inclusive).

        Raises:
            ValueError: If b < a.
        """
        if b < a:
            raise ValueError("'a' must be less than or equal to 'b'")

        range_size = b - a + 1
        predictable_int = self._next_predictable_int()

        return a + (predictable_int * range_size) // self._SCALE

    def randrange(self, start: int, stop: int | None = None, step: int = 1) -> int:
        """Return a predictably selected element from range(start, stop, step).

        Mimics `random.randrange()`.

        Currently only implemented for step = 1.

        Args:
            start: The start of the range. If `stop` is None, this is the upper bound (exclusive)
                   and the range starts at 0. Otherwise, `start` is the lower bound (inclusive).
            stop: The end of the range (exclusive). If None, `start` is treated as the stop value.
            step: The step of the range. Currently must be 1.

        Raises:
            NotImplementedError: If step is not 1.
            ValueError: If the range is empty or invalid.
        """
        if step != 1:
            raise NotImplementedError("randrange() with step != 1 is not implemented.")

        if stop is None:
            if start <= 0:
                raise ValueError(f"randrange() upper bound ({start}) must be positive when stop is None.")
            return self.randint(a=0, b=start - 1)
        else:
            if stop <= start:
                raise ValueError(f"randrange() range is empty or invalid ({start} >= {stop}).")
            return self.randint(a=start, b=stop - 1)
