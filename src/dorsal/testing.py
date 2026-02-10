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

import logging
from typing import Any, Type
from pydantic import BaseModel

from dorsal.common.model import AnnotationModel
from dorsal.common.validators.json_schema import JsonSchemaValidator
from dorsal.file.configs.model_runner import RunModelResult, ModelRunnerDependencyConfig
from dorsal.file.model_runner import run_model as _run_model_impl

logger = logging.getLogger(__name__)

__all__ = ["run_model", "RunModelResult"]


def run_model(
    annotation_model: Type[AnnotationModel],
    file_path: str,
    *,
    schema_id: str | None = None,
    validation_model: Type[BaseModel] | JsonSchemaValidator | None = None,
    dependencies: list[ModelRunnerDependencyConfig | dict] | ModelRunnerDependencyConfig | dict | None = None,
    options: dict[str, Any] | None = None,
    debug: bool = True,
) -> RunModelResult:
    """Test wrapper for dorsal.file.run_model."""
    if annotation_model.__module__ == "__main__":
        import logging

        logging.getLogger(__name__).debug(
            "Warning: Model '%s' is defined in __main__."
            "Move it to an importable .py file before using 'register_model' or that function will complain.",
            annotation_model.__name__,
        )

    # 2. Delegate to Production Logic with Explicit Args
    return _run_model_impl(
        annotation_model=annotation_model,
        file_path=file_path,
        schema_id=schema_id,
        validation_model=validation_model,
        dependencies=dependencies,
        options=options,
        debug=debug,
    )
