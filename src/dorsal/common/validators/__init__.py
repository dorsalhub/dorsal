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

import importlib
import logging
import os
from typing import Annotated, Any, Callable, NamedTuple, Type

from pydantic import AfterValidator, BaseModel, TypeAdapter

from dorsal.common.exceptions import ValidationError
from dorsal.common.language import get_language_set
from dorsal.common.validators.datasets import DatasetID, is_valid_dataset_id_or_schema_id
from dorsal.common.validators.json_schema import (
    JsonSchemaValidator,
    JsonSchemaValidatorType,
    get_json_schema_validator,
    json_schema_validate_records,
)
from dorsal.common.validators.strings import (
    GLOBAL_STRING_LIMIT,
    String64,
    String128,
    String255,
    String256,
    String1024,
    String4096,
    StringNotEmpty,
    TString64,
    TString128,
    TString255,
    TString256,
    TString1024,
    TString4096,
)


logger = logging.getLogger(__name__)

__all__ = [
    "CallableImportPath",
    "import_callable",
    "check_local_file_exists",
    "get_truthy_envvar",
    "Pagination",
    "LanguageName",
    "validate_language_name",
    "apply_pydantic_validator",
    "GLOBAL_STRING_LIMIT",
    "String64",
    "String128",
    "String255",
    "String256",
    "String1024",
    "String4096",
    "TString64",
    "TString128",
    "TString255",
    "TString256",
    "TString1024",
    "TString4096",
    "StringNotEmpty",
    "JsonSchemaValidator",
    "JsonSchemaValidatorType",
    "get_json_schema_validator",
    "json_schema_validate_records",
    "is_valid_dataset_id_or_schema_id",
    "DatasetID",
    "get_language_set",
]


class CallableImportPath(NamedTuple):
    """module and name combine to form the full path to an imporable callable.

    use with `import_callable`

    """

    module: StringNotEmpty
    name: StringNotEmpty


def import_callable(import_path: CallableImportPath) -> Callable:
    module = importlib.import_module(import_path.module)
    callable_ = getattr(module, import_path.name)
    return callable_


def check_local_file_exists(local_path: str) -> None:
    if not os.path.isfile(local_path):
        raise ValidationError(f"File '{local_path}' does not exist or cannot be accessed.")


def get_truthy_envvar(envvar: str, strict=False) -> bool:
    """Check envvar exists and its value.

    If envvar does not exist, return False
    If `strict` is True, return True IFF envvar has obvious positive boolean value
    If `strict` is False, return True IFF envvar does not have an obvious negative boolean value

    """
    value = os.environ.get(envvar)
    if not value:
        return False
    if strict:
        if value.lower() in ("1", "true", "y", "t", "yes"):
            return True
        return False
    if value.lower() in ("0", "false", "n", "f", "no"):
        return False
    return True


class Pagination(BaseModel):
    current_page: int
    record_count: int
    page_count: int
    per_page: int
    has_next: bool
    has_prev: bool
    start_index: int
    end_index: int


def validate_language_name(value: str) -> str:
    language_set = get_language_set()
    if value not in language_set:
        raise ValueError(f"Unsupported language: {value}")
    return value


LanguageName = Annotated[str, AfterValidator(validate_language_name)]


def apply_pydantic_validator(value: Any, validator: Type[Any]) -> Any:
    """
    Checks if a value is valid for a given Pydantic type/validator.

    Args:
        value: The thing we want to validate.
        validator: The Pydantic Annotated type (e.g., ModelID).

    Returns:
        True if the value is valid, False otherwise.
    """
    return TypeAdapter(validator).validate_python(value)
