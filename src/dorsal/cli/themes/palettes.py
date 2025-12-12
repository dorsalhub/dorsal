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

import json
import logging
import os
from pathlib import Path
from typing import Any

from dorsal.common import constants

logger = logging.getLogger(__name__)

DEFAULT_PALETTE: dict[str, str] = {
    # General UI
    "panel_border": "blue",
    "panel_title": "bold",
    "section_title": "bold",
    "key": "dim",
    "primary_value": "cyan",
    "hash_value": "magenta",
    # Tags & Access Levels
    "tag_public": "blue",
    "tag_private": "dark_orange3",
    "tag_subtext": "dim",
    "access_public": "cyan",
    "access_private": "bold dark_orange3",
    # Alternative Colors
    "panel_border_alt": "dark_orange3",
    "panel_title_alt": "bold yellow",
    "primary_value_alt": "yellow",
    # Semantic UI Styles
    "info": "dim",
    "success": "green",
    "warning": "yellow",
    "error": "bold red",
    "panel_border_info": "dim",
    "panel_title_info": "dim",
    "panel_border_success": "green",
    "panel_title_success": "bold green",
    "panel_border_warning": "yellow",
    "panel_title_warning": "bold yellow",
    "panel_border_error": "red",
    "panel_title_error": "bold red",
    # Data Display
    "table_header": "bold blue",
    "table_row_alt": "on #1e1e1e",
    # Progress Indicators
    "progress_bar": "red3",
    "progress_description": "default",
    "progress_percentage": "sky_blue2",
}


HIGH_CONTRAST_PALETTE: dict[str, str] = {
    # General UI
    "panel_border": "bright_white",
    "panel_title": "bold bright_white",
    "section_title": "bold bright_white",
    "key": "white",
    "primary_value": "bright_cyan",
    "hash_value": "bright_magenta",
    # Tags & Access Levels
    "tag_public": "bright_blue",
    "tag_private": "bright_yellow",
    "tag_subtext": "default",
    "access_public": "bright_cyan",
    "access_private": "bold bright_yellow",
    # Alternative Colors
    "panel_border_alt": "bright_yellow",
    "panel_title_alt": "bold bright_yellow",
    "primary_value_alt": "bright_yellow",
    # Semantic UI Styles
    "info": "default",
    "success": "bright_green",
    "warning": "bright_yellow",
    "error": "bold bright_red",
    "panel_border_info": "default",
    "panel_title_info": "default",
    "panel_border_success": "bright_green",
    "panel_title_success": "bold bright_green",
    "panel_border_warning": "bright_yellow",
    "panel_title_warning": "bold bright_yellow",
    "panel_border_error": "bright_red",
    "panel_title_error": "bold bright_red",
    # Data Display
    "table_header": "bold bright_blue",
    "table_row_alt": "on #2e2e2e",
    # Progress Indicators
    "progress_bar": "bright_red",
    "progress_description": "white",
    "progress_percentage": "bright_cyan",
}

LIGHT_THEME_PALETTE: dict[str, str] = {
    # General UI
    "panel_border": "royal_blue1",
    "panel_title": "bold black",
    "section_title": "bold black",
    "key": "grey50",
    "primary_value": "dark_cyan",
    "hash_value": "dark_magenta",
    # Tags & Access Levels
    "tag_public": "blue3",
    "tag_private": "orange3",
    "tag_subtext": "grey50",
    "access_public": "dark_cyan",
    "access_private": "bold orange3",
    # Alternative Colors
    "panel_border_alt": "orange3",
    "panel_title_alt": "bold dark_orange",
    "primary_value_alt": "orange3",
    # Semantic UI Styles
    "info": "grey50",
    "success": "green3",
    "warning": "dark_orange",
    "error": "bold red1",
    "panel_border_info": "grey50",
    "panel_title_info": "grey50",
    "panel_border_success": "green3",
    "panel_title_success": "bold green3",
    "panel_border_warning": "dark_orange",
    "panel_title_warning": "bold dark_orange",
    "panel_border_error": "red1",
    "panel_title_error": "bold red1",
    # Data Display
    "table_header": "bold black",
    "table_row_alt": "on grey93",
    # Progress Indicators
    "progress_bar": "deep_pink4",
    "progress_description": "grey50",
    "progress_percentage": "blue3",
}

MONOCHROME_PALETTE: dict[str, str] = {
    # General UI
    "panel_border": "white",
    "panel_title": "bold white",
    "section_title": "bold white",
    "key": "dim",
    "primary_value": "white",
    "hash_value": "bright_white",
    # Tags & Access Levels
    "tag_public": "white",
    "tag_private": "white",
    "tag_subtext": "dim",
    "access_public": "white",
    "access_private": "bold white",
    # Alternative Colors
    "panel_border_alt": "white",
    "panel_title_alt": "bold underline white",
    "primary_value_alt": "bright_white",
    # Semantic UI Styles
    "info": "dim",
    "success": "white",
    "warning": "white",
    "error": "bold white",
    "panel_border_info": "dim",
    "panel_title_info": "dim",
    "panel_border_success": "white",
    "panel_title_success": "bold white",
    "panel_border_warning": "white",
    "panel_title_warning": "bold white",
    "panel_border_error": "white",
    "panel_title_error": "bold white",
    # Data Display
    "table_header": "bold white",
    "table_row_alt": "dim",
    # Progress Indicators
    "progress_bar": "white",
    "progress_description": "dim",
    "progress_percentage": "white",
}

NEON_PALETTE: dict[str, str] = {
    # General UI
    "panel_border": "bright_cyan",
    "panel_title": "bold hot_pink",
    "section_title": "bold hot_pink",
    "key": "dim",
    "primary_value": "bright_cyan",
    "hash_value": "bright_magenta",
    # Tags & Access Levels
    "tag_public": "bright_cyan",
    "tag_private": "hot_pink",
    "tag_subtext": "dim",
    "access_public": "bright_cyan",
    "access_private": "bold hot_pink",
    # Alternative Colors
    "panel_border_alt": "bright_yellow",
    "panel_title_alt": "bold bright_yellow",
    "primary_value_alt": "bright_yellow",
    # Semantic UI Styles
    "info": "dim",
    "success": "bright_green",
    "warning": "bright_yellow",
    "error": "bold bright_red",
    "panel_border_info": "dim",
    "panel_title_info": "dim",
    "panel_border_success": "bright_green",
    "panel_title_success": "bold bright_green",
    "panel_border_warning": "bright_yellow",
    "panel_title_warning": "bold bright_yellow",
    "panel_border_error": "bright_red",
    "panel_title_error": "bold bright_red",
    # Data Display
    "table_header": "bold bright_cyan",
    "table_row_alt": "on #19112d",
    # Progress Indicators
    "progress_bar": "hot_pink",
    "progress_description": "default",
    "progress_percentage": "bright_cyan",
}

DRACULA_PALETTE: dict[str, str] = {
    # General UI
    "panel_border": "medium_purple",
    "panel_title": "bold hot_pink",
    "section_title": "bold hot_pink",
    "key": "grey50",
    "primary_value": "cyan",
    "hash_value": "hot_pink",
    # Tags & Access Levels
    "tag_public": "cyan",
    "tag_private": "dark_orange",
    "tag_subtext": "dim",
    "access_public": "cyan",
    "access_private": "bold dark_orange",
    # Alternative Colors
    "panel_border_alt": "yellow",
    "panel_title_alt": "bold yellow",
    "primary_value_alt": "yellow",
    # Semantic UI Styles
    "info": "dim",
    "success": "green",
    "warning": "yellow",
    "error": "bold red",
    "panel_border_info": "dim",
    "panel_title_info": "dim",
    "panel_border_success": "green",
    "panel_title_success": "bold green",
    "panel_border_warning": "yellow",
    "panel_title_warning": "bold yellow",
    "panel_border_error": "red",
    "panel_title_error": "bold red",
    # Data Display
    "table_header": "bold cyan",
    "table_row_alt": "on #44475a",
    # Progress Indicators
    "progress_bar": "hot_pink",
    "progress_description": "default",
    "progress_percentage": "cyan",
}

BUILT_IN_PALETTES = {
    "default": DEFAULT_PALETTE,
    "dracula": DRACULA_PALETTE,
    "high_contrast": HIGH_CONTRAST_PALETTE,
    "light": LIGHT_THEME_PALETTE,
    "mono": MONOCHROME_PALETTE,
    "neon": NEON_PALETTE,
}


def _load_custom_palettes() -> dict[str, Any]:
    """Loads user-defined palettes from the custom JSON file."""
    custom_palette_path = constants.LOCAL_DORSAL_DIR / "palettes.json"
    if not custom_palette_path.exists():
        return {}
    try:
        with open(custom_palette_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as err:
        logger.debug("Failed to load custom themes = %s", err)
        return {}


def get_palette(name: str | None = None) -> dict[str, str]:
    """
    Loads a palette by name, handling fallbacks and merging.
    - Precedence: Command-line --theme > DORSAL_THEME env var > config file > default.
    - Always merges with the default palette to ensure all keys are present.
    """
    from dorsal.common.auth import get_theme_from_config

    if name and name != "default":
        theme_name = name
    else:
        theme_name = os.getenv("DORSAL_THEME") or get_theme_from_config() or "default"

    custom_palettes = _load_custom_palettes()
    final_palette = DEFAULT_PALETTE.copy()

    if theme_name in custom_palettes:
        final_palette.update(custom_palettes[theme_name])
    elif theme_name in BUILT_IN_PALETTES:
        final_palette.update(BUILT_IN_PALETTES[theme_name])
    elif theme_name != "default":
        print(f"[Warning] Theme '{theme_name}' not found. Falling back to default.")

    return final_palette
