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

from collections.abc import Mapping
from typing import Any


def model_config_options(*, config: Mapping[str, Any]) -> dict[str, Any]:
    """Return the option values a parsed `model_config.toml` passes to its model.

    A scalar under `[options]` is a value. A table is a documented option whose value is its `default`;
    a table without a `default` is left out, so the model's own default applies.
    """
    options: dict[str, Any] = {}
    for key, value in (config.get("options") or {}).items():
        if not isinstance(value, dict):
            options[key] = value
        elif "default" in value:
            options[key] = value["default"]
    return options
