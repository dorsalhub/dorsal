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

import json
import os
import subprocess
import sys
import textwrap

import pytest

from dorsal.common.model_config import model_config_options


def test_scalars_are_values_and_tables_are_documented_options():
    config = {
        "options": {
            "flat": "value",
            "documented": {"type": "int", "default": 42, "help": "A number."},
            "falsy_default": {"type": "bool", "default": False},
            "dict_default": {"type": "dict", "default": {"min_silence_duration_ms": 500}},
            "no_default": {"type": "str", "help": "Auto-detected if not provided."},
            "empty_table": {},
        }
    }

    assert model_config_options(config=config) == {
        "flat": "value",
        "documented": 42,
        "falsy_default": False,
        "dict_default": {"min_silence_duration_ms": 500},
    }


@pytest.mark.parametrize("config", [{}, {"options": {}}, {"options": None}])
def test_no_options(config):
    assert model_config_options(config=config) == {}


def test_is_public_in_dorsal_testing():
    from dorsal import testing

    assert testing.model_config_options is model_config_options
    assert "model_config_options" in testing.__all__


def test_importing_dorsal_testing_stays_light(tmp_path):
    code = """
        import json, sys
        import pydantic
        import dorsal.common.model
        import dorsal.common.validators.json_schema
        import dorsal.file.configs.model_runner
        import dorsal.file.model_runner
        before = set(sys.modules)
        import dorsal.testing
        print(json.dumps({"loaded": sorted(sys.modules), "added": sorted(set(sys.modules) - before)}))
    """
    env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "DORSAL_INDEX_ENABLED": "false"}
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr[-2000:]
    modules = json.loads(result.stdout)
    heavy = ("dorsal.registry", "dorsal.api", "dorsal.session", "dorsal.client", "requests")
    assert not [name for name in modules["loaded"] if name in heavy or name.startswith(tuple(f"{h}." for h in heavy))]
    assert modules["added"] == ["dorsal.common.model_config", "dorsal.testing"]
