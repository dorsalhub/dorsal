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
import uuid
import datetime
from pydantic import ValidationError

from dorsal.file.validators.file_record import FileRecord, Annotations, AnnotationStub, Annotation, AnnotationSource
from dorsal.common.model import AnnotationModelSource


@pytest.fixture
def mock_source():
    return AnnotationModelSource(type="Model", id="test-model", version="1.0.0", user_id=1)


@pytest.fixture
def valid_stub(mock_source):
    return AnnotationStub(
        hash="a" * 64,  # Valid SHA256 length
        id=uuid.uuid4(),
        source=mock_source,
        user_id=1,
        date_modified=datetime.datetime.now(datetime.timezone.utc),
    )


# --- Test Block 1: Hash Consistency (FileRecord) ---


class TestFileRecordHashes:
    def test_identical_hashes_raise_error(self):
        """
        Target: FileRecord._identical_hash_check
        Ensures strict separation between hash types (e.g. hash vs quick_hash).
        """
        common_hash = "a" * 64

        # Scenario: The main SHA256 hash is accidentally identical to the QuickHash
        with pytest.raises(ValidationError) as exc:
            FileRecord(
                hash=common_hash,
                quick_hash=common_hash,  # This triggers the collision check
                validation_hash=None,
                similarity_hash=None,
            )

        # Verify strict error message
        assert "Inconsistent hash values" in str(exc.value)
        assert "hash" in str(exc.value) and "quick_hash" in str(exc.value)

    def test_distinct_hashes_are_valid(self):
        """Ensures the validator passes when hashes are different."""
        rec = FileRecord(hash="a" * 64, quick_hash="b" * 64, validation_hash=None, similarity_hash=None)
        assert rec.hash != rec.quick_hash


# --- Test Block 2: Polymorphic Annotations List ---


class TestAnnotationsExtras:
    def test_mixed_list_instantiation(self, valid_stub, mock_source):
        """
        Target: Annotations._validate_and_type_extras
        Tests mixing a raw dict (needs parsing) with a pre-existing object (AnnotationStub).
        """
        valid_base_dict = {
            "source": mock_source.model_dump(),
            "record": {"hash": "a" * 64, "size": 1024, "media_type": "text/plain", "name": "test_file.txt"},
        }

        raw_stub_dict = {
            "hash": "b" * 64,
            "id": str(uuid.uuid4()),
            "source": valid_stub.source.model_dump(),
            "user_id": 2,
            "date_modified": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        anns = Annotations(**{"file/base": valid_base_dict, "custom_list": [raw_stub_dict, valid_stub]})

        custom_list = anns.custom_list
        assert len(custom_list) == 2
        assert isinstance(custom_list[0], AnnotationStub)
        assert isinstance(custom_list[1], AnnotationStub)
        assert custom_list[0].hash == raw_stub_dict["hash"]

    def test_invalid_list_item_type(self, mock_source):
        """
        Target: Annotations._validate_and_type_extras (else clause)
        Tests passing a list containing an invalid type (int).
        """
        valid_base_dict = {
            "source": mock_source.model_dump(),
            "record": {"hash": "a" * 64, "size": 1024, "media_type": "text/plain", "name": "test_file.txt"},
        }

        with pytest.raises(ValidationError) as exc:
            Annotations(**{"file/base": valid_base_dict, "bad_list": [12345]})

        assert "List item is not a valid Annotation type" in str(exc.value)
