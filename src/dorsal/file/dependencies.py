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
import re
from typing import Sequence

from dorsal.file.configs.model_runner import (
    FileExtensionDependencyConfig,
    FilenameDependencyConfig,
    FileSizeDependencyConfig,
    MediaTypeDependencyConfig,
)
from dorsal.file.utils.size import parse_filesize


logger = logging.getLogger(__name__)


def make_media_type_dependency(
    include: Sequence[str] | None = None,
    exclude: Sequence[str] | None = None,
    pattern: str | re.Pattern | None = None,
    silent: bool = True,
) -> MediaTypeDependencyConfig:
    """
    Helper function to create a media type dependency configuration.

    Args:
        include: A sequence (list or tuple) of media types (e.g., ["application/pdf"]).
        exclude: A sequence (list or tuple) of media types to explicitly exclude.
        pattern: A regex pattern to match against the media type.
        silent: If False, raises an error if the dependency isn't met.
    """
    if isinstance(include, str):
        raise TypeError(
            f"The 'include' argument must be a sequence (like a list or tuple) of strings, not a single string.\n"
            f'       Did you mean: include=["{include}"] ?'
        )

    if isinstance(exclude, str):
        raise TypeError(
            f"The 'exclude' argument must be a sequence (like a list or tuple) of strings, not a single string.\n"
            f'       Did you mean: exclude=["{exclude}"] ?'
        )

    if not include and not exclude and not pattern:
        raise ValueError(
            "A media type dependency must have at least one rule ('include', 'exclude', or 'pattern').\n"
            "If the model should run on all media types, call 'dorsal.testing.run_model' without 'dependencies' instead."
        )

    return MediaTypeDependencyConfig(
        include=set(include) if include else None,
        exclude=set(exclude) if exclude else None,
        pattern=pattern,
        silent=silent,
    )


def make_file_extension_dependency(
    extensions: Sequence[str],
    silent: bool = True,
) -> FileExtensionDependencyConfig:
    """
    Helper function to create a file extension dependency configuration.

    Args:
        extensions: A sequence (list or tuple) of file extensions (e.g., [".pdf", ".txt"]).
        silent: If False, raises an error if the dependency isn't met.
    """
    if isinstance(extensions, str):
        raise TypeError(
            f"The 'extensions' argument must be a sequence (like a list or tuple) of strings, not a single string.\n"
            f'       Did you mean: extensions=["{extensions}"] ?'
        )

    if not extensions:
        raise ValueError(
            "A file extension dependency must have at least one extension.\n"
            "If the model should run on all file types, call 'dorsal.testing.run_model' without 'dependencies' instead."
        )

    processed_extensions = {f".{ext.lstrip('.').lower()}" for ext in extensions}

    return FileExtensionDependencyConfig(
        extensions=processed_extensions,
        silent=silent,
    )


def make_file_size_dependency(
    min_size: int | str | None = None,
    max_size: int | str | None = None,
    silent: bool = True,
) -> FileSizeDependencyConfig:
    """
    Helper function to create a file size dependency configuration.
    Accepts integers for bytes or strings like "10MB", "500KB".

    Args:
        min_size: The minimum file size (inclusive) for the model to run.
        max_size: The maximum file size (inclusive) for the model to run.
        silent: If False, raises an error if the dependency isn't met.
    """
    min_size_bytes = parse_filesize(min_size) if isinstance(min_size, str) else min_size
    max_size_bytes = parse_filesize(max_size) if isinstance(max_size, str) else max_size

    if min_size_bytes is None and max_size_bytes is None:
        raise ValueError("A file size dependency must have at least one of 'min_size' or 'max_size'.")

    return FileSizeDependencyConfig(
        min_size=min_size_bytes,
        max_size=max_size_bytes,
        silent=silent,
    )


def make_file_name_dependency(
    pattern: str | re.Pattern,
    silent: bool = True,
) -> FilenameDependencyConfig:
    """
    Helper function to create a filename pattern dependency configuration.
    The model will only run if the file's name matches the provided regex pattern.

    Args:
        pattern: The regex pattern (str or re.Pattern) to match against the filename.
        silent: If False, raises an error if the dependency isn't met.
    """
    if not pattern:
        raise ValueError("The 'pattern' argument cannot be empty.")

    return FilenameDependencyConfig(
        pattern=pattern,
        silent=silent,
    )
