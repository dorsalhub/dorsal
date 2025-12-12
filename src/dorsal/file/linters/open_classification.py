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
from pydantic import BaseModel, Field, model_validator, ConfigDict, ValidationError

logger = logging.getLogger(__name__)


class _LinterLabelItem(BaseModel):
    """Internal model to parse the 'label' field from a label object."""

    label: str


class OpenClassificationLinter(BaseModel):
    """
    A linter for valid 'open/classification' records.

    Enforces data quality rules:

    - If any value in `labels` is not in `vocabulary`, this model complains.

    Example:
        ```python
        valid_data = {
            "labels": [{"label": "pear"}],
            "vocabulary": ["apple", "pear"]
        }

        invalid_data = {
            "labels": [{"label": "cheese"}],
            "vocabulary": ["apple", "pear"]
        }

        # This will execute just fine
        OpenClassificationLinter(**valid_data)

        # This will raise `pydantic.ValidationError`
        OpenClassificationLinter.model_validate(**invalid_data)
        ```
    """

    labels: List[_LinterLabelItem] = Field(default_factory=list, description="The array of label objects to check.")
    vocabulary: list[str] | None = Field(default=None, description="The vocabulary to check labels against.")

    @model_validator(mode="after")
    def check_labels_are_in_vocabulary(self) -> Self:
        """
        Enforces that all labels exist in the vocabulary, if one is provided.
        """
        if self.vocabulary is not None:
            vocab_set = set(self.vocabulary)
            missing_labels = [item.label for item in self.labels if item.label not in vocab_set]

            if missing_labels:
                missing_str = ", ".join(f"'{label}'" for label in missing_labels)
                raise ValueError(f"The following labels are not in the provided vocabulary: {missing_str}.")

        return self
