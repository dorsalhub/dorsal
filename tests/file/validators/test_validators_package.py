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

import os
import subprocess
import sys
import textwrap

import pytest


def _run_fresh(code: str, tmp_path) -> subprocess.CompletedProcess:
    env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "DORSAL_INDEX_ENABLED": "false"}
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=120,
    )


@pytest.mark.parametrize(
    "attribute, expected",
    [
        ("classification", "OpenSchemaValidator"),
        ("document_extraction_validator", "OpenSchemaValidator"),
        ("get_open_schema_validator", "function"),
        ("OpenSchemaValidator", "type"),
        ("does_not_exist", "AttributeError: module 'dorsal.file.validators' has no attribute 'does_not_exist'"),
        ("ranking", "AttributeError: Open schema 'ranking' is not in schema version"),
        ("__wrapped__", "AttributeError"),
    ],
)
def test_attributes_resolve_in_a_fresh_interpreter(attribute, expected, tmp_path):
    result = _run_fresh(
        f"""
        import sys
        import dorsal.file.validators as validators
        assert "dorsal.file.validators.open_schema" not in sys.modules
        try:
            value = getattr(validators, {attribute!r})
        except AttributeError as err:
            print(f"AttributeError: {{err}}")
        else:
            print(type(value).__name__)
        """,
        tmp_path,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert "RecursionError" not in result.stderr
    assert result.stdout.strip().startswith(expected)


def test_dir_works_in_a_fresh_interpreter(tmp_path):
    result = _run_fresh(
        """
        import dorsal.file.validators as validators
        names = dir(validators)
        assert "classification" in names and "get_open_schema_validator" in names, names
        print("ok")
        """,
        tmp_path,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "ok"
