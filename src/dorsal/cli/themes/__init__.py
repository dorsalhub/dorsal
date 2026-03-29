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
from typing import TypedDict
from rich.box import Box

# 1. Import the module, not the function!
from dorsal.common import config as dorsal_config
from dorsal.common.validators import get_truthy_envvar
from dorsal.cli.themes.palettes import get_palette
from dorsal.cli.themes.icons import get_icons
from dorsal.cli.themes.borders import get_borders


class UIContext(TypedDict):
    palette: dict[str, str]
    icons: dict[str, str]
    borders: Box


def get_ui_theme(
    theme_override: str | None = None,
    icon_override: str | None = None,
    border_override: str | None = None,
) -> UIContext:
    """
    Constructs the complete UI state by merging CLI flags,
    environment variables, config files, and defaults.
    """
    config, _ = dorsal_config.load_config()
    ui_config = config.get("ui", {})

    theme_name = theme_override or os.getenv("DORSAL_THEME") or ui_config.get("theme", "default")

    if get_truthy_envvar("NO_EMOJI", strict=True):
        icon_name = "none"
    else:
        icon_name = icon_override or os.getenv("DORSAL_ICONS") or ui_config.get("icons", "emoji")

    border_name = border_override or os.getenv("DORSAL_BORDERS") or ui_config.get("borders", "rounded")

    return {
        "palette": get_palette(theme_name),
        "icons": get_icons(icon_name),
        "borders": get_borders(border_name),
    }
