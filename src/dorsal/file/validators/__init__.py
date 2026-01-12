# Copyright 2025-2026 Dorsal Hub LTD
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

from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from dorsal.common.validators.json_schema import JsonSchemaValidator

    audio_transcription: JsonSchemaValidator
    classification: JsonSchemaValidator
    document_extraction: JsonSchemaValidator
    embedding: JsonSchemaValidator
    entity_extraction: JsonSchemaValidator
    generic: JsonSchemaValidator
    geolocation: JsonSchemaValidator
    llm_output: JsonSchemaValidator
    object_detection: JsonSchemaValidator
    regression: JsonSchemaValidator


def __getattr__(name: str):
    """
    Lazy-loads attributes from the 'open_schema' submodule.
    This ensures that simply importing 'dorsal.file.validators' is instant
    and does not trigger the heavy schema parsing machinery.
    """
    from dorsal.file.validators import open_schema

    try:
        return getattr(open_schema, name)
    except AttributeError as err:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'") from err


def __dir__() -> List[str]:
    """
    Exposes the available validators to dir(), enabling autocomplete in
    interactive shells (IPython/Jupyter) and dynamic inspection.
    """
    from dorsal.file.validators import open_schema

    return sorted(list(globals().keys()) + list(open_schema.__all__))
