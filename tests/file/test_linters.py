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

import pytest
from pydantic import ValidationError
from dorsal.common.exceptions import DataQualityError
from dorsal.file.linters.open_classification import OpenClassificationLinter
from dorsal.file.linters.open_entity_extraction import OpenEntityExtractionLinter
from dorsal.file.linters import apply_linter


def test_classification_valid_vocab():
    """Valid case: all labels exist in vocabulary."""
    data = {
        "labels": [{"label": "apple"}, {"label": "pear"}],
        "vocabulary": ["apple", "pear", "banana"],
    }
    model = OpenClassificationLinter(**data)
    assert len(model.labels) == 2


def test_classification_no_vocab():
    """Valid case: no vocabulary provided, so no validation occurs."""
    data = {"labels": [{"label": "alien_fruit"}]}
    model = OpenClassificationLinter(**data)
    assert model.labels[0].label == "alien_fruit"


def test_classification_invalid_label():
    """Invalid case: label 'rock' is not in vocabulary."""
    data = {
        "labels": [{"label": "apple"}, {"label": "rock"}],
        "vocabulary": ["apple", "pear"],
    }
    with pytest.raises(ValidationError) as exc:
        OpenClassificationLinter.model_validate(data)

    assert "The following labels are not in the provided vocabulary" in str(exc.value)
    assert "'rock'" in str(exc.value)


# --- OpenEntityExtractionLinter Tests ---


def test_entity_valid_vocab():
    """Valid case: all entity labels exist in vocabulary."""
    data = {
        "entities": [
            {"label": "PER", "text": "John Doe"},
            {"label": "LOC", "text": "London"},
        ],
        "vocabulary": ["PER", "LOC", "ORG"],
    }
    model = OpenEntityExtractionLinter(**data)
    assert len(model.entities) == 2


def test_entity_no_vocab():
    """Valid case: no vocabulary provided, so no validation occurs."""
    data = {"entities": [{"label": "ALIEN_TECH", "text": "Ray Gun"}]}
    model = OpenEntityExtractionLinter(**data)
    assert model.entities[0].label == "ALIEN_TECH"


def test_entity_invalid_label():
    """Invalid case: entity label 'BAD_LABEL' is not in vocabulary."""
    data = {
        "entities": [
            {"label": "PER", "text": "John"},
            {"label": "BAD_LABEL", "text": "Unknown"},
        ],
        "vocabulary": ["PER", "LOC"],
    }
    with pytest.raises(ValidationError) as exc:
        OpenEntityExtractionLinter.model_validate(data)

    # Matches the specific error message format defined in entity_extraction.py
    assert "Integrity Error" in str(exc.value)
    assert "labels found in 'entities' are not declared" in str(exc.value)
    assert "'BAD_LABEL'" in str(exc.value)


# --- apply_linter Logic Tests ---


def test_apply_linter_success():
    """Test happy path for apply_linter (Classification)."""
    record = {"labels": [{"label": "cat"}], "vocabulary": ["cat", "dog"]}
    assert apply_linter("open/classification", record) is None


def test_apply_linter_entity_success():
    """Test happy path for apply_linter (Entity Extraction)."""
    record = {
        "entities": [{"label": "PER", "text": "Alice"}],
        "vocabulary": ["PER", "LOC"],
    }
    assert apply_linter("open/entity-extraction", record) is None


def test_apply_linter_unknown_schema():
    """Test graceful exit if schema ID is unknown or None."""
    assert apply_linter("unknown/schema", {}) is None
    assert apply_linter(None, {}) is None


def test_apply_linter_error_raised():
    """Test raise_on_error=True."""
    record = {"labels": [{"label": "dog"}], "vocabulary": ["cat"]}

    with pytest.raises(DataQualityError) as exc:
        apply_linter("open/classification", record, raise_on_error=True)

    assert "Data quality validation failed" in str(exc.value)
    assert "set `ignore_linter_errors` to true" in str(exc.value)


def test_apply_linter_warning_only(caplog):
    """Test raise_on_error=False (should log warning only)."""
    record = {"labels": [{"label": "dog"}], "vocabulary": ["cat"]}

    apply_linter("open/classification", record, raise_on_error=False)

    # Check that no error was raised, but a warning was logged
    assert "Ignoring data quality warning" in caplog.text
    assert "open/classification" in caplog.text
