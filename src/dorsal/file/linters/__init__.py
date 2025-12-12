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

from dorsal.common.exceptions import DataQualityError, PydanticValidationError
from dorsal.file.linters.open_classification import OpenClassificationLinter
from dorsal.file.linters.open_entity_extraction import OpenEntityExtractionLinter

LINTER_MAP = {
    "open/classification": OpenClassificationLinter,
    "open/entity-extraction": OpenEntityExtractionLinter,
}

logger = logging.getLogger(__name__)


def apply_linter(schema_id: str | None, record: dict, raise_on_error: bool = True) -> None:
    """
    Applies a data quality "linter" to a schema-validated record, checking for semantic or logical issues
    which JSON Schema cannot express (e.g., "are all values in array "A" also in array "B"?).

    This function is called from two places:
    1.  **`FileAnnotator`:** For manual annotations (e.g., `LocalFile.add_classification`).
        `raise_on_error` is controlled by the `ignore_linter_errors` flag.

    2.  **`ModelRunner`:** For pipeline-generated annotations.
        `raise_on_error` is controlled by the `ignore_linter_errors` key
        in the `dorsal.toml` pipeline step.

    Args:
        schema_id: The schema ID (e.g., "open/classification") to check for a linter.
        record: The annotation record dictionary that has *already passed*
                JSON Schema validation.
        raise_on_error: If `True`, raises `DataQualityError` on failure.
                        If `False`, logs a `WARNING` instead.

    Raises:
        DataQualityError: If a linter is found, `raise_on_error` is `True`, and the quality checks fail.
    """
    if schema_id is None:
        return None

    linter_cls = LINTER_MAP.get(schema_id)

    if linter_cls is None:
        return None

    logger.debug(
        "Linter found for schema %s. Validating record against %s with `raise_on_error=%s`",
        schema_id,
        linter_cls.__name__,
        raise_on_error,
    )

    try:
        linter_cls.model_validate(record)

    except PydanticValidationError as err:
        if raise_on_error:
            bypass_msg = (
                "To ignore data quality errors, set `ignore_linter_errors` "
                "to true in either the pipeline step or "
                "`LocalFile` method used to create the annotation"
            )

            full_msg = f"Data quality validation failed for '{schema_id}': {err}\n\n{bypass_msg}"
            raise DataQualityError(full_msg) from err
        else:
            logger.warning("Ignoring data quality warning for '%s': %s", schema_id, err)

    return None
