# Rust `QUICK` Hash Reference Implementation

This directory contains a standalone Rust implementation of `QUICK` hashing.

The primary purpose of this code is to serve as a proof-of-concept and a reference for developers who need to generate `QUICK` hashes in a non-Python environment. It demonstrates that the hashing algorithm is fully portable and produces bit-for-bit identical hashes to the Python version.

This implementation is not intended to be a published crate, but rather a clean, understandable, and verifiable example.

## Prerequisites

- [Rust](https://www.rust-lang.org/tools/install) (latest stable version)
- The `predictable.bin` data file located in the `data/` directory. This file is essential for the deterministic sampling algorithm and must be present.

## How to Build and Run

0. **Copy `predictable.bin` file from `src.dorsal.file.configs` to the `rust_quick_hasher.src` directory**

1.  **Navigate to this directory:**
    ```sh
    cd reference_implementations/rust_quick_hasher
    ```

2.  **Build the project in release mode:**
    ```sh
    cargo build --release
    ```

3.  **Run the hasher on a file:**
    ```sh
    ./target/release/rust_quick_hasher "/path/to/your/file"
    ```

## Verification

To confirm that this Rust implementation produces the same hash as the Python version, you can run both against the same file.

#### Python `dorsal`

```python
from dorsal.file import get_quick_hash

file_path = "/path/to/your/file"
quick_hash = get_quick_hash(file_path)
print(f"Python QUICK Hash: {quick_hash}")
```

#### Rust

```sh
./target/release/rust_quick_hasher "/path/to/your/file"
```

The hash in each case should be identical.