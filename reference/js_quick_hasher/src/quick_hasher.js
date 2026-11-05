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

import { createHash } from "node:crypto";
import { open } from "node:fs/promises";

import {
  CHUNK_SIZE,
  FILE_SIZE_CHUNKS,
  loadPredictableNumbers,
  LOWER_FILESIZE_CHUNKS,
  MAX_CHUNKS,
  MAX_PERMITTED_FILESIZE,
  MIN_CHUNKS,
  MIN_PERMITTED_FILESIZE,
  PREDICTABLE_COUNT,
  UPPER_FILESIZE_CHUNKS,
} from "./config.js";
import { FileInstabilityError, FileSizeOutOfRangeError } from "./error.js";
import { Predictable } from "./predictable.js";

function bisectLeft(sorted, value) {
  let low = 0;
  let high = sorted.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (sorted[middle] < value) {
      low = middle + 1;
    } else {
      high = middle;
    }
  }
  return low;
}

/**
 * Return the number of chunks to sample for a file size.
 *
 * @param {number} fileSize File size in bytes.
 * @returns {number}
 */
export function getChunkCount(fileSize) {
  if (fileSize >= UPPER_FILESIZE_CHUNKS) {
    return MAX_CHUNKS;
  }
  if (fileSize <= LOWER_FILESIZE_CHUNKS) {
    return MIN_CHUNKS;
  }
  return Math.min(MAX_CHUNKS, MIN_CHUNKS + bisectLeft(FILE_SIZE_CHUNKS, fileSize));
}

/**
 * Return the sorted chunk indices to sample for a file size.
 *
 * @param {number} fileSize File size in bytes.
 * @param {BigUint64Array} numbers The predictable number sequence.
 * @returns {number[]}
 */
export function sampleChunkIndices(fileSize, numbers) {
  const totalChunks = Math.floor(fileSize / CHUNK_SIZE);
  const sampleSize = Math.min(getChunkCount(fileSize), totalChunks);
  const reservoir = Array.from({ length: sampleSize }, (_, index) => index);
  const predictable = new Predictable(numbers, fileSize % PREDICTABLE_COUNT);
  for (let i = sampleSize; i < totalChunks; i++) {
    const j = predictable.randint(0, i);
    if (j < sampleSize) {
      reservoir[j] = i;
    }
  }
  return reservoir.sort((a, b) => a - b);
}

async function readChunk(handle, buffer, offset) {
  let filled = 0;
  while (filled < buffer.length) {
    const { bytesRead } = await handle.read(buffer, filled, buffer.length - filled, offset + filled);
    if (bytesRead === 0) {
      break;
    }
    filled += bytesRead;
  }
  return filled;
}

/** Generates a QUICK hash for a large file by sampling content chunks. */
export class QuickHasher {
  #numbers;

  /**
   * @param {object} [options]
   * @param {string} [options.predictableBinPath] Path to `predictable.bin`.
   */
  constructor({ predictableBinPath } = {}) {
    this.#numbers = loadPredictableNumbers(predictableBinPath);
  }

  /**
   * Generate the QUICK hash of a file.
   *
   * @param {string} filePath Path to the file.
   * @returns {Promise<string>} The hash as lowercase hexadecimal.
   * @throws {FileSizeOutOfRangeError} If the file is too small or too large to be hashed.
   * @throws {FileInstabilityError} If the file shrinks while it is being hashed.
   */
  async hash(filePath) {
    const handle = await open(filePath, "r");
    try {
      const { size } = await handle.stat();
      if (size < MIN_PERMITTED_FILESIZE || size > MAX_PERMITTED_FILESIZE) {
        throw new FileSizeOutOfRangeError(
          `File size ${size} bytes is outside the permitted range (${MIN_PERMITTED_FILESIZE} - ${MAX_PERMITTED_FILESIZE} bytes)`,
        );
      }
      const hasher = createHash("sha256");
      const buffer = Buffer.allocUnsafe(CHUNK_SIZE);
      for (const chunkIndex of sampleChunkIndices(size, this.#numbers)) {
        const offset = chunkIndex * CHUNK_SIZE;
        const bytesRead = await readChunk(handle, buffer, offset);
        if (bytesRead === 0) {
          throw new FileInstabilityError(`Read empty chunk at offset ${offset}: file may have changed during hashing`);
        }
        hasher.update(buffer.subarray(0, bytesRead));
      }
      return hasher.digest("hex");
    } finally {
      await handle.close();
    }
  }
}
