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


def extract_records(
    json_data: dict[str, Any], schema_override: str | None = None
) -> list[tuple[str, dict[str, Any], str | None]]:
    """
    Extracts the schema_id, record dictionary, and original file path from a JSON payload.

    Returns:
        A list of tuples containing (schema_id, record_dict, file_path).
    """
    if "results" in json_data and isinstance(json_data["results"], list):
        extracted = []
        for item in json_data["results"]:
            annotation_meta = (
                item.get("record", {})
                if isinstance(item.get("record"), dict) and "schema_id" in item.get("record", {})
                else item
            )

            schema_id = schema_override or annotation_meta.get("schema_id")
            if not schema_id:
                raise ValueError("Missing 'schema_id' in JSON wrapper. Please provide one using --schema-id.")

            record_payload = annotation_meta.get("record", annotation_meta)
            file_path = item.get("file_path")  # Grab the original file path

            extracted.append((schema_id, record_payload, file_path))

        return extracted

    if not schema_override:
        if "schema_id" in json_data and "record" in json_data:
            return [(json_data["schema_id"], json_data["record"], json_data.get("file_path"))]

        raise ValueError("Raw record detected without a schema wrapper. You must explicitly provide a --schema-id.")

    return [(schema_override, json_data, json_data.get("file_path"))]
