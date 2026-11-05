# JavaScript `QUICK` Hash Reference Implementation

A standalone Node.js implementation of `QUICK` hashing with no dependencies. It is a clean, verifiable example for developers working outside Python and produces hashes identical to Dorsal's Python `QuickHasher`. It is not a published package.

## Prerequisites

- [Node.js](https://nodejs.org) 20 or newer
- `predictable.bin`, read from `src/dorsal/file/configs/` in this repository. To use a copy elsewhere, pass `--predictable-bin <path>`, or `predictableBinPath` to `QuickHasher`.

## Usage

```sh
cd reference/js_quick_hasher
node src/main.js /path/to/your/file
```

The hash is written to stdout. The file must be between 32 MiB and 1 PiB.

```js
import { QuickHasher } from "./src/quick_hasher.js";

const quickHash = await new QuickHasher().hash("/path/to/your/file");
```

## Algorithm

1. Let `size` be the file size in bytes and `total = floor(size / 1 MiB)`. Bytes after the last whole chunk are never read.
2. Find the sample size `k`: 8 up to 128 MiB, 1024 from 128 GiB, otherwise `8 + bisect_left(FILE_SIZE_CHUNKS, size)`.
3. Run reservoir sampling (Algorithm R) over chunk indices `0..total`, drawing from the `predictable.bin` sequence of little-endian `u64` values. Start at offset `size % 100000` and wrap at the end. For each `i >= k`, `j = floor(value * (i + 1) / 10^18)`; if `j < k`, then `reservoir[j] = i`.
4. Sort the indices, then SHA-256 the chunks in that order.

The sequence values exceed `Number.MAX_SAFE_INTEGER`, so step 3 needs `BigInt`. File sizes and offsets stay within safe integers, since 1 PiB is 2^50.

## Verification

```sh
npm test
```

`test/vectors.json` holds the expected results, covering chunk sampling and hashes of real files. To regenerate it from the Python implementation, run this from the repository root:

```sh
uv run python reference/js_quick_hasher/test/generate_vectors.py
```

To compare directly on a file of your own:

```sh
uv run python -c "from dorsal.file import get_quick_hash; print(get_quick_hash('/path/to/your/file'))"
node reference/js_quick_hasher/src/main.js /path/to/your/file
```
