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

from dorsal.common.model import AnnotationModel
from dorsal.file.configs.model_runner import DependencyType

REGISTRY_ID_RX = re.compile(r"^[a-z0-9][a-z0-9._-]*\/[a-z0-9][a-z0-9._-]*$", re.IGNORECASE)
SAFE_INSTALL_URL_RX = re.compile(r"^git\+https?://[a-zA-Z0-9.\-_/]+\.git@[a-f0-9]{40}$")


class ModelSpec(BaseModel):
    """Specification for external (installed) model packages."""

    model_class: Type[AnnotationModel]
    schema_id: str
    dependencies: list[DependencyType] | None = None
    validation_model: Any | None = None
    options: dict[str, Any] | None = None

    @field_validator("model_class")
    @classmethod
    def validate_model_class(cls, v):
        if not issubclass(v, AnnotationModel):
            raise ValueError(f"External model_class must inherit from dorsal.AnnotationModel, got {v}")
        return v


class InitResult(BaseModel):
    path: pathlib.Path
    package_name: str
    clean_name: str


def is_registry_id(target: str) -> bool:
    """Determines if a target string is a valid Registry ID."""
    if "/" not in target:
        return False

    return bool(REGISTRY_ID_RX.match(target))


def is_valid_local_path(target: str) -> bool:
    """
    Determines if the target is a valid local resource (File or Directory).
    """
    path = pathlib.Path(target)
    return path.exists() and (path.is_dir() or path.is_file())


def validate_install_url(url: str) -> str:
    """
    Validates the install URL returned by the Registry API.
        1. Protocol must be git+http(s).
        2. Must end in .git@{sha} (pinned version).
    """
    if not SAFE_INSTALL_URL_RX.match(url):
        raise ValueError(
            f"Registry returned an invalid install URL: '{url}'. "
            "Expected format: 'git+https://host/repo.git@commit_sha'"
        )
    return url
