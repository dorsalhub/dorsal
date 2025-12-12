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

import datetime
import logging
import re
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, Field

logger = logging.getLogger(__name__)


def get_dataset_id(dataset_string: str | Any) -> str:
    """Parses dataset_id out of a string.

    Example: extracts 'namespace/name' from a potentially prefixed string
        'https://dorsalhub.com/d/dorsal/iso-language' -> 'dorsal/iso-language'

    Args:
        dataset_string: User-provided dataset string. Expected format: 'namespace/name'.

    Returns:
        str: The dataset ID.

    Raises:
        ValueError: Not a string or no Dataset ID found.

    """
    if not isinstance(dataset_string, str):
        logger.warning("Invalid type: expected str, got %s.", type(dataset_string).__name__)
        raise ValueError(f"Dataset ID must be a string, got {type(dataset_string).__name__}.")

    match = re.match(
        pattern=r"^(?:.*\/)?(?P<dataset_id>[a-z0-9\-]{3,32}\/[a-z0-9\-]{3,32})$",
        string=dataset_string,
    )

    if match:
        extracted_id = match.group("dataset_id")
        logger.debug(
            "Successfully extracted Dataset ID: '%s' from input string: '%s'.",
            extracted_id,
            dataset_string,
        )
        return extracted_id
    else:
        logger.warning(
            "Invalid Dataset ID format: '%s'. No valid ID pattern found.",
            dataset_string,
        )
        raise ValueError(f"Invalid Dataset ID format: '{dataset_string}'. Expected 'namespace/name'.")


def check_no_double_hyphens(value: str) -> str:
    """Raises ValueError if the string contains double-hyphens"""
    if "--" in value:
        raise ValueError("must not contain double hyphens")
    return value


NAMESPACE_ID_OR_DATASET_NAME_REGEX = r"^[a-z0-9\-]{3,32}$"

DATASET_ID_REGEX = r"^[a-z0-9\-]{3,32}\/[a-z0-9\-]{3,32}$"
RX_DATASET_ID = re.compile(DATASET_ID_REGEX)

DatasetNamespace = Annotated[str, Field(pattern=r"^[a-z0-9\-]{3,32}$")]
DatasetName = Annotated[str, Field(pattern=r"^[a-z0-9\-]{3,32}$")]
DatasetID = Annotated[str, Field(pattern=DATASET_ID_REGEX), AfterValidator(check_no_double_hyphens)]


def is_valid_dataset_id_or_schema_id(value: str | Any) -> bool:
    if not isinstance(value, str):
        return False
    return bool(RX_DATASET_ID.match(value))


class Dataset(BaseModel):
    dataset_id: DatasetID
    type: Literal["Reference", "File"]
    key_field: str
    version: str
    dataset_schema: dict = Field(alias="schema")
    date_created: datetime.datetime
    date_modified: datetime.datetime
