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
import copy
from typing import Literal, List, Any, cast

import tomlkit
import tomlkit.items
from pydantic import ValidationError

from dorsal.common import config
from dorsal.common.exceptions import DorsalError
from dorsal.file.configs.model_runner import ModelRunnerPipelineStep

logger = logging.getLogger(__name__)

PipelineScope = Literal["project", "global", "effective"]


class PipelineConfig:
    """
    Manages the reading and writing of the annotation model pipeline configuration.
    """

    @staticmethod
    def get_steps(scope: PipelineScope = "effective") -> List[ModelRunnerPipelineStep]:
        """Retrieves the current pipeline configuration."""
        raw_pipeline_list: list[dict[str, Any]] = []

        if scope == "effective":
            full_config, _ = config.load_config()
            raw_pipeline_list = full_config.get("model_pipeline", [])

        elif scope in ["project", "global"]:
            doc, _ = config.get_writable_toml_doc(scope)
            raw_pipeline_list = doc.get("model_pipeline", [])
            if isinstance(raw_pipeline_list, tomlkit.items.Array):
                raw_pipeline_list = raw_pipeline_list.unwrap()
        else:
            raise ValueError(f"Unknown scope: {scope}")

        validated_steps = []
        for i, step in enumerate(raw_pipeline_list):
            try:
                validated_steps.append(ModelRunnerPipelineStep.model_validate(step))
            except ValidationError as e:
                logger.warning("Pipeline step %d in scope '%s' is invalid: %s", i, scope, e)
                continue

        return validated_steps

    @staticmethod
    def _resolve_index_from_name(pipeline: list, name: str) -> int:
        """
        Finds the index of a model by name.
        Raises ValueError if the name is not found OR if multiple models share the name.
        """
        matches = []
        for i, step in enumerate(pipeline):
            model_path = step.get("annotation_model")
            if hasattr(model_path, "unwrap"):
                model_path = model_path.unwrap()

            if not model_path:
                continue

            full_name = ".".join(model_path)
            simple_name = model_path[-1]

            if name == full_name or name == simple_name:
                matches.append(i)

        if not matches:
            raise ValueError(f"Model '{name}' not found in pipeline.")

        if len(matches) > 1:
            raise ValueError(
                f"Ambiguous model name '{name}': found {len(matches)} occurrences at indices {matches}. "
                "Please perform this operation using the specific index instead."
            )

        return matches[0]

    @staticmethod
    def _validate_index(pipeline: list, index: int) -> int:
        """Validates and normalizes an integer index (supports negative indexing)."""
        if index < -len(pipeline) or index >= len(pipeline):
            raise IndexError(f"Index {index} out of range (length: {len(pipeline)})")

        if index < 0:
            return len(pipeline) + index
        return index

    @classmethod
    def _get_pipeline_for_writing(cls, scope: str):
        """Helper to load doc and ensure pipeline list exists (populating defaults if needed)."""
        doc, path = config.get_writable_toml_doc(scope)

        if "model_pipeline" not in doc:
            logger.debug("Initializing 'model_pipeline' in %s with library defaults.", scope)
            from dorsal.common.config import DEFAULT_CONFIG

            base_pipeline = copy.deepcopy(DEFAULT_CONFIG.get("model_pipeline", []))
            doc["model_pipeline"] = base_pipeline

        pipeline = doc["model_pipeline"]
        if not isinstance(pipeline, (list, tomlkit.items.Array)):
            pipeline = cast(Any, [])
            doc["model_pipeline"] = pipeline

        return doc, path, pipeline

    @classmethod
    def upsert_step(
        cls, step_data: dict[str, Any], overwrite: bool = False, scope: Literal["project", "global"] = "project"
    ) -> None:
        doc, path, pipeline = cls._get_pipeline_for_writing(scope)

        target_model_list = cast(list[str], step_data.get("annotation_model"))
        target_model_str = ".".join(target_model_list)

        found_index = -1
        for i, existing_step in enumerate(pipeline):
            existing_model_path = existing_step.get("annotation_model", [])
            if hasattr(existing_model_path, "unwrap"):
                existing_model_path = existing_model_path.unwrap()

            if ".".join(existing_model_path) == target_model_str:
                found_index = i
                break

        if found_index != -1:
            if not overwrite:
                raise FileExistsError(
                    f"Model '{target_model_str}' already exists in {scope} config. Use overwrite=True."
                )
            pipeline[found_index] = step_data
            logger.info("Updated existing model '%s' in %s config.", target_model_str, scope)
        else:
            pipeline.append(step_data)
            logger.info("Appended new model '%s' to %s config.", target_model_str, scope)

        config.save_toml_doc(doc, path)

    @classmethod
    def _modify_step(cls, index: int, action: str, scope: str, active_state: bool | None = None):
        """Internal helper to perform removal or status change."""
        doc, path, pipeline = cls._get_pipeline_for_writing(scope)

        if index == 0:
            verb = action
            if action == "status":
                if active_state is True:
                    verb = "activate"
                elif active_state is False:
                    verb = "deactivate"
                else:
                    verb = "change the status of"

            raise DorsalError(f"Cannot {verb} the Base Model (index 0).")

        if action == "remove":
            removed_item = pipeline[index]
            model_info = removed_item.get("annotation_model", ["unknown"])
            name = model_info[1] if isinstance(model_info, list) and len(model_info) > 1 else "unknown"

            del pipeline[index]
            logger.info("Removed pipeline step '%s' (index %d) from %s.", name, index, scope)

        elif action == "status":
            step = pipeline[index]
            should_be_deactivated = not active_state

            if not should_be_deactivated:
                if "deactivated" in step:
                    del step["deactivated"]
            else:
                step["deactivated"] = True

            status_str = "Activated" if active_state else "Deactivated"
            logger.info("%s pipeline step %d in %s.", status_str, index, scope)

        config.save_toml_doc(doc, path)

    @classmethod
    def remove_step_by_index(cls, index: int, scope: Literal["project", "global"] = "project") -> None:
        doc, path, pipeline = cls._get_pipeline_for_writing(scope)
        real_index = cls._validate_index(pipeline, index)
        cls._modify_step(real_index, "remove", scope)

    @classmethod
    def remove_step_by_name(cls, name: str, scope: Literal["project", "global"] = "project") -> None:
        doc, path, pipeline = cls._get_pipeline_for_writing(scope)
        real_index = cls._resolve_index_from_name(pipeline, name)
        cls._modify_step(real_index, "remove", scope)

    @classmethod
    def set_step_status_by_index(
        cls, index: int, active: bool, scope: Literal["project", "global"] = "project"
    ) -> None:
        doc, path, pipeline = cls._get_pipeline_for_writing(scope)
        real_index = cls._validate_index(pipeline, index)
        cls._modify_step(real_index, "status", scope, active_state=active)

    @classmethod
    def set_step_status_by_name(cls, name: str, active: bool, scope: Literal["project", "global"] = "project") -> None:
        doc, path, pipeline = cls._get_pipeline_for_writing(scope)
        real_index = cls._resolve_index_from_name(pipeline, name)
        cls._modify_step(real_index, "status", scope, active_state=active)
