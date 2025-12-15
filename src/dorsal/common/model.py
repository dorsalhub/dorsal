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

import inspect
import logging
import re
from typing import Annotated, Any, Callable, Literal, Type, TypeGuard, TypeVar, Union, cast

from pydantic import AfterValidator, AliasChoices, BaseModel, ConfigDict, Field, StringConstraints
from pydantic_core import PydanticUndefined

from dorsal.common.exceptions import PydanticValidationError
from dorsal.common.validators import String256, apply_pydantic_validator
from dorsal.common.constants import DOCS_URL

T = TypeVar("T")

logger = logging.getLogger(__name__)


class AnnotationModel:
    """
    The base class for all Annotation Models.

    See: [AnnotationModel docs](http://docs.dorsalhub.com/reference/annotation-model/)

    Subclasses must implement the `main` method.
    """

    id: str
    version: str | None = None
    variant: str | None = None

    file_path: str
    error: str | None

    name: str | None
    extension: str | None
    size: int | None
    media_type: str | None
    hash: str | None
    similarity_hash: str | None
    quick_hash: str | None

    def __init_subclass__(cls, **kwargs):
        """Sets 'id' and 'version' if they are not provided."""
        super().__init_subclass__(**kwargs)

        if not hasattr(cls, "id") or cls.id is None:
            safe_name = cls.__name__[:256] or "unnamed-model"
            logger.warning(
                f"'{cls.__name__}' does not define an 'id'. "
                f"Defaulting to '{safe_name}'.\n"
                f"For setting model `id` for discoverability see: {DOCS_URL}/reference/annotation-model"
            )
            cls.id = safe_name

        else:
            try:
                cls.id = apply_pydantic_validator(value=cls.id, validator=String256)
            except PydanticValidationError as err:
                safe_name = cls.__name__[:256] or "unnamed-model"
                cls.id = safe_name
                logger.debug(err)
                logger.warning(
                    f"`{cls.__name__}.id` (`{cls.id}`) is not a valid Model ID. "
                    f"Defaulting to '{safe_name}'.\n"
                    f"For setting model `id` for discoverability see: {DOCS_URL}/reference/annotation-model"
                )

    def __init__(self, file_path: str):
        """Initializes the model, setting the file_path."""
        self.file_path = file_path
        self.error: str | None = None
        self.name: str | None = None
        self.extension: str | None = None
        self.size: int | None = None
        self.media_type: str | None = None
        self.hash: str | None = None
        self.similarity_hash: str | None = None
        self.quick_hash: str | None = None

    def set_error(self, message: str):
        """
        Sets a graceful error message for the model and logs it as a warning.

        Call this and return None from `main()` for non-critical,
        expected failures (e.g., file is not the right type).
        """
        logger.warning(
            "Model '%s' (v%s) failed for file '%s': %s",
            self.id,
            self.version,
            self.file_path,
            message,
        )
        self.error = message

    def log_debug(self, message: str):
        """Logs a debug message with standardized model context."""
        logger.debug(
            "Model '%s' (v%s) for file '%s': %s",
            self.id,
            self.version,
            self.file_path,
            message,
        )

    def main(self, *args, **kwargs) -> dict | None:
        """
        The main entrypoint for the annotation model.
        This method must be implemented by the subclass.

        - On success: return a dictionary of the annotation data.
        - On graceful failure: call self._set_error("reason") and return None.
        - On critical failure: raise an Exception (e.g., a missing dependency).
        """
        raise NotImplementedError("The `main` method must be implemented by the subclass.")


class AnnotationSourceBase(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str
    id: String256 | None = None
    version: String256 | None = None
    variant: String256 | None = None
    user_id: int | None = Field(default=None, validation_alias=AliasChoices("user_no", "user_id"))


class AnnotationModelSource(AnnotationSourceBase):
    type: Literal["Model"] = "Model"
    id: String256


class AnnotationManualSource(AnnotationSourceBase):
    type: Literal["Manual"] = "Manual"
    id: String256


class AnnotationUserUnknownSource(AnnotationSourceBase):
    type: Literal["Unknown"] = "Unknown"
    id: String256


class AnnotationUserRecordSource(AnnotationSourceBase):
    type: Literal["UserRecords"] = "UserRecords"
    id: String256 | None = None


AnnotationSource = Annotated[
    Union[
        AnnotationModelSource,
        AnnotationManualSource,
        AnnotationUserUnknownSource,
        AnnotationUserRecordSource,
    ],
    Field(discriminator="type"),
]


def is_pydantic_model_class(candidate: Any) -> TypeGuard[Type[BaseModel]]:
    """
    Checks if a candidate is a Pydantic BaseModel class (not an instance).
    """
    if inspect.isclass(candidate) and issubclass(candidate, BaseModel):
        return True
    return False


def is_pydantic_model_instance(candidate: Any) -> TypeGuard[BaseModel]:
    """
    Checks if a candidate is an instance of a Pydantic BaseModel.
    """
    return isinstance(candidate, BaseModel)


def scrub_pii_from_model(model_instance: Any) -> Any:
    """Scrub PII-risk fields from a validation model and its nested objects.

    - Checks for a `pii_risk=True` argument to `pydantic.Field` on the model.

    Example:
        class Documet(Model):
            author: str = Field(description="Document author", json_schema_extra={"pii_risk": True})
            title: str = Field(description="Document title")

    """
    if not isinstance(model_instance, BaseModel):
        return model_instance

    for field_name, field_info in type(model_instance).model_fields.items():
        extra = field_info.json_schema_extra
        is_pii = extra.get("pii_risk", False) if isinstance(extra, dict) else False

        if is_pii:
            if field_info.default_factory is not None:
                factory = cast(Callable[[], Any], field_info.default_factory)
                setattr(model_instance, field_name, factory())

            elif field_info.default is not PydanticUndefined:
                setattr(model_instance, field_name, field_info.default)

            else:
                setattr(model_instance, field_name, None)

        else:
            current_value = getattr(model_instance, field_name, None)
            if not current_value:
                continue
            if isinstance(current_value, BaseModel):
                scrub_pii_from_model(current_value)
            elif isinstance(current_value, list):
                for item in current_value:
                    scrub_pii_from_model(item)

    return model_instance
