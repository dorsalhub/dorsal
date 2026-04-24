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
    Supports both legacy single 'record' outputs and new chunked 'records' arrays.

    Returns:
        A list of tuples containing (schema_id, record_dict, file_path).
    """
    extracted: list[tuple[str, dict[str, Any], str | None]] = []

    if "results" in json_data and isinstance(json_data["results"], list):
        for item in json_data["results"]:
            if not isinstance(item, dict):
                continue

            nested_record = item.get("record")
            nested_schema_id = nested_record.get("schema_id") if isinstance(nested_record, dict) else None

            schema_id = schema_override or item.get("schema_id") or nested_schema_id
            if not schema_id or not isinstance(schema_id, str):
                raise ValueError("Missing 'schema_id' in JSON wrapper. Please provide one using --schema-id.")

            raw_file_path = item.get("file_path")
            file_path = str(raw_file_path) if raw_file_path is not None else None

            if "records" in item and isinstance(item["records"], list):
                for record_payload in item["records"]:
                    if isinstance(record_payload, dict):
                        extracted.append((schema_id, record_payload, file_path))

            elif "record" in item and isinstance(item["record"], dict):
                extracted.append((schema_id, item["record"], file_path))

            else:
                extracted.append((schema_id, item, file_path))

        return extracted

    if not schema_override:
        schema_id = json_data.get("schema_id")
        raw_file_path = json_data.get("file_path")
        file_path = str(raw_file_path) if raw_file_path is not None else None

        if isinstance(schema_id, str):
            if "records" in json_data and isinstance(json_data["records"], list):
                for record_payload in json_data["records"]:
                    if isinstance(record_payload, dict):
                        extracted.append((schema_id, record_payload, file_path))
                return extracted

            if "record" in json_data and isinstance(json_data["record"], dict):
                return [(schema_id, json_data["record"], file_path)]

        raise ValueError("Raw record detected without a schema wrapper. You must explicitly provide a --schema-id.")

    raw_override_path = json_data.get("file_path")
    override_file_path = str(raw_override_path) if raw_override_path is not None else None

    return [(schema_override, json_data, override_file_path)]
