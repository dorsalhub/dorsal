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

from typing import Any

ARXIV_SCHEMA_ID = "dorsal/arxiv"


def is_enabled(value: Any) -> bool:
    """Return whether an option value is on, reading command-line strings such as `"false"` and `"0"` as off."""
    if isinstance(value, str):
        return value.strip().lower() not in {"", "false", "0", "no", "off"}
    return bool(value)


def validate_record(record: dict[str, Any], schema_id: str = ARXIV_SCHEMA_ID) -> None:
    """Validate a record against its DorsalHub dataset schema, raising `jsonschema_rs.ValidationError` on failure."""
    from dorsal.api.dataset import get_dataset_schema
    from dorsal.common.validators.json_schema import get_json_schema_validator

    schema = get_dataset_schema(schema_id)
    get_json_schema_validator(schema=schema, strict=True).validate(record)
