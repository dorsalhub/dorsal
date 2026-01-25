# Copyright 2026 Dorsal Hub LTD
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

import pathlib
from typing import Type, Any, Union
import re

from pydantic import BaseModel, Field, HttpUrl, field_validator

# Import existing core types
from dorsal.common.model import AnnotationModel
from dorsal.file.configs.model_runner import DependencyType


class ModelSpec(BaseModel):
    """Specification for external (installed) model packages."""

    # 1. The Model Class
    # The registry will extract the module path from this class.
    model_class: Type[AnnotationModel]

    # 2. The Output Schema
    # e.g., 'open/classification' or 'my-org/custom-schema'
    schema_id: str

    # 3. Default Dependencies
    # The model author defines *when* this model should run by default.
    # The registry writes these to dorsal.toml, but the user can edit them later.
    dependencies: list[DependencyType] | None = None

    # 4. Optional Validation Logic
    # Can be a Pydantic model class, a dict (JSON Schema), or a Validator instance.
    validation_model: Any | None = None

    # 5. Default Runtime Options
    # Passed to the model's main() method.
    options: dict[str, Any] | None = None

    @field_validator("model_class")
    @classmethod
    def validate_model_class(cls, v):
        # Enforce inheritance from the base class
        if not issubclass(v, AnnotationModel):
            raise ValueError(f"External model_class must inherit from dorsal.AnnotationModel, got {v}")
        return v


class InitResult(BaseModel):
    path: pathlib.Path
    package_name: str
    clean_name: str


def is_registry_id(target: str) -> bool:
    """
    Determines if a target string is a Registry ID (e.g. 'dorsal/whisper')
    vs a file path, git URL, or archive.
    """
    # If it looks like a path or URL, it's not a registry ID
    if any(x in target for x in ["/", "\\", ".", "git+"]):
        # Exception: "owner/model" contains a slash but no extension/protocol
        # simple heuristic: does it start with http, git, file, or ./ ?
        if re.match(r"^(http|https|git\+|file:|/|\./|\.\.)", target):
            return False

        # If it ends in an extension like .whl or .tar.gz
        if re.search(r"\.(whl|tar\.gz|zip)$", target):
            return False

        return True

    # Single word (e.g. "whisper") is also treated as a registry ID (or PyPI package)
    # For now, we assume everything that isn't a path is a Registry ID lookup.
    return True
