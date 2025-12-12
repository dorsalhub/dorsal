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

import json
import logging
import pathlib
import re
from typing import Annotated, Any, Literal, TYPE_CHECKING, Union

from pydantic import BaseModel, Field

from dorsal.common import constants
from dorsal.common.model import AnnotationModelSource
from dorsal.common.validators import CallableImportPath, DatasetID
from dorsal.file.annotation_models.mediainfo.config import MEDIAINFO_MEDIA_TYPES
from dorsal.file.validators.base import MediaTypePartString

logger = logging.getLogger(__name__)


class RunModelResult(BaseModel):
    """
    The standardized result object returned by `ModelRunner` execution steps.

    This object encapsulates the output of a single Annotation Model, including
    its generated data, source identity, execution timing, and any errors encountered.
    """

    name: str = Field(description="The display name of the model (usually the class name).")
    source: AnnotationModelSource = Field(
        description="Structured metadata identifying the model source (ID, version, variant)."
    )
    record: dict[str, Any] | None = Field(
        description="The generated annotation record (dict). None if the model failed, was skipped, or produced no output."
    )
    schema_id: DatasetID | None = Field(
        description="The validation schema/model ID against which this record was validated."
    )
    schema_version: str | None = Field(
        default=None, description="The version of the schema/model against which this record was validated."
    )
    time_taken: int | float | None = Field(
        default=None, description="Execution time in seconds. Populated only if debug mode is active."
    )
    error: str | None = Field(
        default=None,
        description="A descriptive error message if the model failed, crashed, or if a dependency was not met.",
    )


class DependencyConfig(BaseModel):
    """
    - `type` (str): The primary identifier of the dependency.
    - `checker` (CallableImportPath) - Defines the path to the dependency check function
                           - The dependency check function returns a boolean indicating whether the dependency was met
                           - The dependency check function always takes, as input, the list of prior model outputs (which is always at least the base file model result, at index 0)
    - `silent` (bool): - When set to `False`, raises a `DependencyNotMetError` exception whenever the dependency is not met
                       - When set to `True`, no exception is raised in the case of a dependency not being met.
    """

    type: str
    checker: CallableImportPath
    silent: bool = True


class MediaTypeDependencyConfig(DependencyConfig):
    """This dependency configures which Media Types to execute a model for.

    You can define the match rule for Media Type using any combination of `pattern`, `include`, or `exclude`.

    - `silent` (bool = True): - by default, when not met, the MediaTypeDependencyConfig does not raise.
                              - Set to `False` if you want it to raise an exception
    - `pattern` (str or re.Pattern): match the media type using a regular expression. If the media type matches, the model executes
    - `include` - If the Media Type is in this sequence, the model executes
    - `exclude` - Exclusion rule: if the media type is in this sequence (even if it matches via `pattern` or `include`) it is blocked

    """

    type: Literal["media_type"] = "media_type"
    checker: CallableImportPath = CallableImportPath("dorsal.file.configs.model_runner", "check_media_type_dependency")
    silent: bool = True
    pattern: str | re.Pattern | None = None
    include: set[MediaTypePartString] | None = None
    exclude: set[MediaTypePartString] | None = None


class FileExtensionDependencyConfig(DependencyConfig):
    """This dependency configures which file extensions to execute a model for."""

    type: Literal["extension"] = "extension"
    checker: CallableImportPath = CallableImportPath("dorsal.file.configs.model_runner", "check_extension_dependency")
    silent: bool = True
    extensions: set[str]


class FileSizeDependencyConfig(DependencyConfig):
    """This dependency configures a model to run based on file size."""

    type: Literal["file_size"] = "file_size"
    checker: CallableImportPath = CallableImportPath("dorsal.file.configs.model_runner", "check_size_dependency")
    silent: bool = True
    min_size: int | None = None
    max_size: int | None = None


class FilenameDependencyConfig(DependencyConfig):
    """This dependency configures a model to run based on the file's name."""

    type: Literal["file_name"] = "file_name"
    checker: CallableImportPath = CallableImportPath("dorsal.file.configs.model_runner", "check_name_dependency")
    silent: bool = True
    pattern: str | re.Pattern


ModelRunnerDependencyConfig = Annotated[
    Union[MediaTypeDependencyConfig, FileExtensionDependencyConfig, FileSizeDependencyConfig, FilenameDependencyConfig],
    Field(discriminator="type"),
]


def check_media_type_dependency(model_results: "list[RunModelResult]", config: "MediaTypeDependencyConfig") -> bool:
    """
    Check whether the media type is within the scope of the annotation model.

    - Performs exact string matches or regex matches on the full and partial media type.
    - Checks both *full* and *partial* media type in the following order:
        1. If in `exclude`, return False
        2. If in `include` or matching `pattern`, return True
        3. If `include` or `pattern` were provided, then it failed. Return False
        4. If neither `include` nor `pattern` were provided, then it passed. Return True
    """
    base_record = model_results[0].record

    if not base_record:
        logger.debug("No base record found for media type dependency check")
        return False

    media_type_full = base_record.get("media_type")
    if not media_type_full:
        logger.debug("Base record has no 'media_type' field")
        return False

    media_type_head, _ = media_type_full.split("/")

    if config.exclude:
        if media_type_full in config.exclude or media_type_head in config.exclude:
            logger.debug(f"Media type {media_type_full} is explicitly excluded.")
            return False

    has_inclusion_rules = config.include or config.pattern

    if has_inclusion_rules:
        if config.include:
            if media_type_full in config.include or media_type_head in config.include:
                logger.debug(f"Media type {media_type_full} matched 'include' list.")
                return True

        if config.pattern:
            if isinstance(config.pattern, str):
                rx = re.compile(config.pattern)
            else:
                rx = config.pattern

            m_full = rx.match(media_type_full)
            if m_full:
                logger.debug(f"Media type {media_type_full} matched 'pattern' (full).")
                return True

            m_head = rx.match(media_type_head)
            if m_head:
                logger.debug(f"Media type {media_type_full} matched 'pattern' (head).")
                return True

        logger.debug(f"Media type {media_type_full} did not match any 'include' or 'pattern' rules.")
        return False

    logger.debug(f"Media type {media_type_full} passed (no inclusion rules specified).")
    return True


def check_extension_dependency(model_results: list[RunModelResult], config: FileExtensionDependencyConfig) -> bool:
    """Check whether the extension is within the scope of the annotation model."""
    base_record = model_results[0].record

    if not base_record:
        logger.debug("No base record found")
        return False

    extension: str | None = base_record["extension"]
    if not extension:
        return False

    if extension.lower() in config.extensions:
        return True

    return False


def check_size_dependency(model_results: list[RunModelResult], config: FileSizeDependencyConfig) -> bool:
    """Check whether the file size is within the scope of the annotation model."""
    base_record = model_results[0].record

    if not base_record:
        logger.debug("No base record found for file size dependency check")
        return False

    file_size = base_record.get("size")
    if not isinstance(file_size, int):
        logger.debug("Base record has no valid 'size' field")
        return False

    if config.min_size is not None and file_size < config.min_size:
        logger.debug(f"File size {file_size} is less than min_size {config.min_size}.")
        return False

    if config.max_size is not None and file_size > config.max_size:
        logger.debug(f"File size {file_size} is greater than max_size {config.max_size}.")
        return False

    logger.debug(f"File size {file_size} passed dependency check.")
    return True


def check_name_dependency(model_results: list[RunModelResult], config: FilenameDependencyConfig) -> bool:
    """Check whether the file's name matches the regex pattern."""
    base_record = model_results[0].record

    if not base_record:
        logger.debug("No base record found for filename dependency check")
        return False

    filename = base_record.get("name")
    if not filename:
        logger.debug("Base record has no 'name' field")
        return False

    if isinstance(config.pattern, str):
        rx = re.compile(config.pattern)
    else:
        rx = config.pattern

    if rx.search(filename):
        logger.debug(f"Filename '{filename}' matched pattern '{config.pattern}'.")
        return True

    logger.debug(f"Filename '{filename}' did not match pattern '{config.pattern}'.")
    return False


class ModelRunnerPipelineStep(BaseModel):
    """Single step in the ModelRunner execution pipeline.

    - annotation_model: Two-part path to an Annotation Model.
    - dependencies: Rules to trigger execution.
    - validation_model: Path to validation logic.
    - schema_id: Unique dataset ID.
    - options: Runtime options for the model.
    - ignore_linter_errors: Skip strict linting if True.
    - deactivated: (Optional) If True, this step is skipped. Defaults to False.
    """

    annotation_model: CallableImportPath
    dependencies: list[ModelRunnerDependencyConfig] | None = None
    validation_model: CallableImportPath | dict | None = None
    schema_id: DatasetID
    options: dict[str, Any] | None = None
    ignore_linter_errors: bool = False
    deactivated: bool = False


BASE_ANNOTATION_MODEL = {
    "annotation_model": ["dorsal.file.annotation_models", "FileCoreAnnotationModel"],
    "validation_model": [
        "dorsal.file.validators.base",
        "FileCoreValidationModelStrict",
    ],
    "schema_id": constants.FILE_BASE_ANNOTATION_SCHEMA,
    "options": {"calculate_similarity_hash": True},
}
