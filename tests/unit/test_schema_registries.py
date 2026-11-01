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

import ast
import inspect
from typing import get_args

import oatschema
import pytest

from dorsal.file.schemas import OPEN_SCHEMA_NAME_MAP, OpenSchemaName

OATS_NAMES = set(get_args(oatschema.SchemaName))
OATS_IDS = {f"open/{name}" for name in OATS_NAMES}


def _oats_keys(registry) -> set[str]:
    return {key for key in registry if key.startswith("open/")}


def test_open_schema_name_equals_oatschema_schema_name():
    assert get_args(OpenSchemaName) == get_args(oatschema.SchemaName)
    assert set(OPEN_SCHEMA_NAME_MAP) == OATS_NAMES
    assert len(OATS_NAMES) == 12


def test_every_name_is_in_the_default_version():
    from dorsal.common.constants import OPEN_VALIDATION_SCHEMAS_VER

    for name in OATS_NAMES:
        oatschema.get_schema(name, OPEN_VALIDATION_SCHEMAS_VER)


def test_index_extractors_cover_every_schema():
    from dorsal.file.index.extractors import registry

    assert _oats_keys(registry._extractors) == OATS_IDS


def test_cli_views_cover_every_schema():
    from dorsal.cli.views.model import RENDERER_REGISTRY

    assert _oats_keys(RENDERER_REGISTRY) == OATS_IDS


def test_default_validator_attributes_cover_every_schema():
    from dorsal.file.validators import open_schema

    expected = {name.replace("-", "_") for name in OATS_NAMES}
    assert {key for key in open_schema._VALIDATOR_LOOKUP if not key.endswith("_validator")} == expected

    tree = ast.parse(inspect.getsource(open_schema))
    stubs = {
        node.target.id
        for block in tree.body
        if isinstance(block, ast.If) and getattr(block.test, "id", None) == "TYPE_CHECKING"
        for node in block.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert stubs == expected


@pytest.mark.parametrize(
    "registry_path, unsupported",
    [
        ("dorsal.file.chunking:MERGE_STRATEGY_REGISTRY", {"geolocation"}),
        ("dorsal.file.chunking:SPLIT_STRATEGY_REGISTRY", {"geolocation"}),
        ("dorsal.file.sharding:SHARDING_REGISTRY", {"embedding", "generic", "geolocation"}),
        (
            "dorsal.file.linters:LINTER_MAP",
            OATS_NAMES - {"classification", "entity-extraction"},
        ),
    ],
)
def test_opt_in_registries_name_every_schema_they_leave_out(registry_path, unsupported):
    import importlib

    module_name, attribute = registry_path.split(":")
    registry = getattr(importlib.import_module(module_name), attribute)

    assert _oats_keys(registry) | {f"open/{name}" for name in unsupported} == OATS_IDS
    assert not _oats_keys(registry) & {f"open/{name}" for name in unsupported}
