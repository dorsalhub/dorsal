// Copyright 2025-2026 Dorsal Hub LTD
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import { PREDICTABLE_SCALE } from "./config.js";

/** Predictable number generator that cycles through a pre-loaded sequence. */
export class Predictable {
  #numbers;
  #index;

  /**
   * @param {BigUint64Array} numbers The predictable number sequence.
   * @param {number} seed The starting offset in the sequence.
   */
  constructor(numbers, seed) {
    if (!Number.isInteger(seed) || seed < 0 || seed >= numbers.length) {
      throw new RangeError(`Seed must be an integer between 0 and ${numbers.length - 1}, got ${seed}`);
    }
    this.#numbers = numbers;
    this.#index = seed;
  }

  /**
   * Return a predictable integer N where a <= N <= b.
   *
   * @param {number} a The lower bound.
   * @param {number} b The upper bound.
   * @returns {number}
   */
  randint(a, b) {
    if (b < a) {
      throw new RangeError("'a' must be less than or equal to 'b'");
    }
    const value = this.#numbers[this.#index];
    this.#index = (this.#index + 1) % this.#numbers.length;
    return a + Number((value * BigInt(b - a + 1)) / PREDICTABLE_SCALE);
  }
}
