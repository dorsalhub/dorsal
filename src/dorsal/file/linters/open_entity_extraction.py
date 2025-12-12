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
from typing import List, Self
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


class _LinterEntityItem(BaseModel):
    """Internal model to parse the 'label' field from an entity object."""

    label: str


class OpenEntityExtractionLinter(BaseModel):
    """
    A linter for valid 'open/entity-extraction' records.

    Enforces data quality rules:
    - If `vocabulary` is present, every entity's `label` must be in that vocabulary.
    """

    entities: List[_LinterEntityItem] = Field(default_factory=list, description="The array of entity objects to check.")
    vocabulary: list[str] | None = Field(default=None, description="The vocabulary to check entity labels against.")

    @model_validator(mode="after")
    def check_labels_are_in_vocabulary(self) -> Self:
        """
        Enforces that all entity labels exist in the vocabulary, if one is provided.
        """
        if self.vocabulary is not None:
            vocab_set = set(self.vocabulary)
            missing_labels = sorted(list({item.label for item in self.entities if item.label not in vocab_set}))

            if missing_labels:
                display_limit = 5
                missing_str = ", ".join(f"'{label}'" for label in missing_labels[:display_limit])
                if len(missing_labels) > display_limit:
                    missing_str += f", ... (+{len(missing_labels) - display_limit} more)"

                raise ValueError(
                    f"Integrity Error: {len(missing_labels)} labels found in 'entities' are not declared in the 'vocabulary': {missing_str}."
                )

        return self
