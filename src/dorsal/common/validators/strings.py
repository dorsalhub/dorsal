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
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

logger = logging.getLogger(__name__)


def truncate_string(value: str, min_length: int, max_length: int) -> str:
    if len(value) < min_length:
        raise ValueError("String must be non-empty.")
    if len(value) > max_length:
        logger.debug("Truncating long string (%s): %s", max_length, value)
    return value[:max_length]


def truncate_string_64(value: str) -> str:
    return truncate_string(value=value, min_length=1, max_length=64)


def truncate_string_128(value: str) -> str:
    return truncate_string(value=value, min_length=1, max_length=128)


def truncate_string_255(value: str) -> str:
    return truncate_string(value=value, min_length=1, max_length=255)


def truncate_string_256(value: str) -> str:
    return truncate_string(value=value, min_length=1, max_length=256)


def truncate_string_4096(value: str) -> str:
    return truncate_string(value=value, min_length=1, max_length=4096)


def truncate_string_1024(value: str) -> str:
    return truncate_string(value=value, min_length=1, max_length=1024)


# == Non-empty String ===
String64 = Annotated[str, Field(min_length=1, max_length=64)]
String128 = Annotated[str, Field(min_length=1, max_length=128)]
String255 = Annotated[str, Field(min_length=1, max_length=255)]
String256 = Annotated[str, Field(min_length=1, max_length=256)]
String1024 = Annotated[str, Field(min_length=1, max_length=1024)]
String4096 = Annotated[str, Field(min_length=1, max_length=4096)]
StringNotEmpty = Annotated[str, Field(min_length=1)]

# == TString: Truncated Non-empty String ===
# - Truncates if longer than specified max length without raising (debug log)
TString64 = Annotated[str, AfterValidator(truncate_string_64)]
TString128 = Annotated[str, AfterValidator(truncate_string_128)]
TString255 = Annotated[str, AfterValidator(truncate_string_255)]
TString256 = Annotated[str, AfterValidator(truncate_string_256)]
TString1024 = Annotated[str, AfterValidator(truncate_string_1024)]
TString4096 = Annotated[str, AfterValidator(truncate_string_4096)]

# Global upper limit on strings in field values
GLOBAL_STRING_LIMIT = 4096
