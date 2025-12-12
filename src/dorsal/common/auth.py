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

import logging
import os
from enum import Enum
from typing import TypedDict, Optional

from dorsal.common.config import (
    load_config,
    remove_config_value,
    set_config_value,
    get_project_level_config,
    get_global_config_path,
)
from dorsal.common import constants
from dorsal.common.exceptions import AuthError
from dorsal.common.validators import get_truthy_envvar

logger = logging.getLogger(__name__)


class APIKeySource(Enum):
    ENV = "env"
    PROJECT = "project"
    GLOBAL = "global"
    NONE = "none"


class APIKeyDetails(TypedDict):
    source: APIKeySource
    value: Optional[str]
    path: Optional[str]


def is_offline_mode() -> bool:
    return get_truthy_envvar("DORSAL_OFFLINE", strict=True)


def get_api_key_from_env() -> str | None:
    return os.getenv(constants.ENV_DORSAL_API_KEY_STR)


def get_api_key_from_config() -> str | None:
    config, _ = load_config()
    return config.get(constants.CONFIG_SECTION_AUTH, {}).get(constants.CONFIG_OPTION_API_KEY)


def get_email_from_config() -> str | None:
    config, _ = load_config()
    return config.get(constants.CONFIG_SECTION_AUTH, {}).get(constants.CONFIG_OPTION_EMAIL)


def get_api_key_details() -> APIKeyDetails:
    """
    Finds the active API key and returns its details.
    Precedence: Environment -> Project Config -> Global Config
    """
    api_key_from_env = get_api_key_from_env()
    if api_key_from_env:
        return APIKeyDetails(source=APIKeySource.ENV, value=api_key_from_env, path=None)

    project_config, project_path = get_project_level_config()
    api_key_from_project = project_config.get(constants.CONFIG_SECTION_AUTH, {}).get(constants.CONFIG_OPTION_API_KEY)
    if api_key_from_project:
        return APIKeyDetails(source=APIKeySource.PROJECT, value=api_key_from_project, path=str(project_path))

    config, _ = load_config()
    api_key_from_config = config.get(constants.CONFIG_SECTION_AUTH, {}).get(constants.CONFIG_OPTION_API_KEY)

    if api_key_from_config:
        global_path = get_global_config_path()
        return APIKeyDetails(source=APIKeySource.GLOBAL, value=api_key_from_config, path=str(global_path))

    return APIKeyDetails(source=APIKeySource.NONE, value=None, path=None)


def write_auth_config(api_key: str, email: str | None = None, scope: str = "global") -> None:
    """Writes authentication details to the specified config scope."""
    set_config_value(
        section=constants.CONFIG_SECTION_AUTH,
        option=constants.CONFIG_OPTION_API_KEY,
        value=api_key,
        scope=scope,
    )
    if email:
        set_config_value(
            section=constants.CONFIG_SECTION_AUTH,
            option=constants.CONFIG_OPTION_EMAIL,
            value=email,
            scope=scope,
        )


def remove_api_key(scope: APIKeySource) -> bool:
    """Removes the API key from the specified config scope."""
    if scope not in [APIKeySource.PROJECT, APIKeySource.GLOBAL]:
        return False
    return remove_config_value(
        section=constants.CONFIG_SECTION_AUTH,
        option=constants.CONFIG_OPTION_API_KEY,
        scope=scope.value,
    )


def read_api_key(api_key: str | None = None) -> str:
    """
    Reads the active API key, raising an AuthError if none is found.
    """
    if api_key:
        return api_key

    details = get_api_key_details()
    key = details["value"]
    if key:
        return key

    raise AuthError(
        f"API key not found. Provide it via the `api_key` argument, "
        f"the '{constants.ENV_DORSAL_API_KEY_STR}' environment variable, or run "
        f"`dorsal auth login`."
    )


def get_theme_from_config() -> str | None:
    config, _ = load_config()
    return config.get(constants.CONFIG_SECTION_UI, {}).get(constants.CONFIG_OPTION_THEME)


def write_theme_to_config(theme_name: str) -> None:
    set_config_value(
        section=constants.CONFIG_SECTION_UI,
        option=constants.CONFIG_OPTION_THEME,
        value=theme_name,
    )
