# Contributing to Dorsal

First off, thank you for considering contributing! This project thrives on community involvement, and we appreciate any contribution, from a small typo fix to a new Annotation Model or CLI feature.

This document provides a set of guidelines for contributing to the `dorsal` repository.

## Code of Conduct

This project and everyone participating in it is governed by our [Code of Conduct](./CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## How Can I Contribute?

There are two main ways to contribute to this project:

### 1. Suggesting Improvements or Reporting Bugs

If you find a bug in the CLI, an issue with a metadata extractor, or have a suggestion for the Python API, please **[open an issue](https://github.com/dorsalhub/dorsal/issues)**.
- For bugs, please use the "Bug Report" template and include the output of `dorsal --version`.
- For improvements, feel free to use a blank issue and provide a clear description of your suggestion.

### 2. Contributing Code

If you want to add a feature, fix a bug, or add a new built-in Annotation Model, we'd love your help!

1.  **Check for existing work:** Make sure a similar feature or fix isn't already in progress.
2.  **Open an issue:** For larger changes, it is best to discuss the implementation details with maintainers before writing code.
3.  **Create a Pull Request:** Once the direction is clear, you can open a pull request.

## Development Setup

We use `uv` for dependency management and task running.

1.  **Fork the repository** and clone it locally.
2.  **Install `uv`** (if not installed): 
    * **Unix/macOS:** `curl -LsSf https://astral.sh/uv/install.sh | sh`
    * **Windows:** `irm https://astral.sh/uv/install.ps1 | iex`
3.  **Install System Dependencies:**
    Some dependencies (`python-magic`, `pymediainfo`) require system-level libraries.
    * **macOS:**
        ```bash
        brew install libmagic mediainfo
        ```
    * **Linux (Ubuntu/Debian):**
        ```bash
        sudo apt-get install libmagic1 libmediainfo0v5
        ```
    * **Windows:** Binaries are usually handled automatically by the python packages.
4.  **Install Python Dependencies:**
    This command will create a virtual environment and install the project with all development dependencies.
    ```bash
    uv sync
    ```

## Quality Control

We enforce strict linting and type checking in our CI pipeline. To ensure your PR passes, please run the following checks locally.

### Static Analysis
We use `ruff` for linting/formatting and `mypy` for static type checking.

1.  **Format Code:**
    ```bash
    uv run ruff format .
    ```
2.  **Lint Code:**
    ```bash
    uv run ruff check .
    ```
3.  **Type Check:**
    ```bash
    uv run mypy src/dorsal
    ```

If contributing, it's a good idea to run your code against [`scripts/check.sh`](https://github.com/dorsalhub/dorsal/blob/main/scripts/check.sh) which automates these checks.


## Pull Request Process

1.  **Create your branch** from `main`.
2.  **Implement your changes.**
3.  **Add Tests:**
      * If you are fixing a bug, add a test case that reproduces the bug (and passes with your fix).
      * If you are adding a feature, add unit tests to cover the new functionality.
4.  **Run Quality Checks:** Ensure [`scripts/check.sh`](https://github.com/dorsalhub/dorsal/blob/main/scripts/check.sh) (or individual commands) passes.
5.  **Documentation:**
      * If you changed the CLI or API, please update the relevant Markdown files in the `/docs` folder.
      * If you added a new dependency, ensure it is reflected in `pyproject.toml`.
6.  **Submit the Pull Request.**

### Style Guide

  * **Type Safety:** We use type hints extensively. Please ensure your code passes `mypy` analysis.
  * **Docstrings:** All public classes and methods must have docstrings explaining arguments, return values, and exceptions.

### Commit Messages
We follow the [Conventional Commits](https://www.conventionalcommits.org/) specification. 
Please structure your commit messages as `<type>(<scope>): <description>`.
Example: `feat(cli): add support for JSON output`

## Legal & Licensing

Dorsal is available under the Apache 2.0 License.

**License:**
By contributing to Dorsal, you agree that your contributions will be licensed under the [Apache License, Version 2.0](https://www.apache.org/licenses/LICENSE-2.0). You retain the copyright to your contributions, but grant us and other users a perpetual, irrevocable, worldwide license to use them.

**Copyright Headers:**
* **Existing Files:** Please do not remove existing copyright headers.
* **New Files:** If you create a new file, please copy the standard header found in other files, but you may attribute it to "Dorsal Hub LTD and Contributors" or append your own name if you wish.

Thank you again for your interest in making Dorsal a better tool for everyone!
