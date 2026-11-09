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

import pytest

from dorsal.registry.model_config import model_config_options


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
