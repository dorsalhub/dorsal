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

import logging
import importlib.metadata
from typing import Literal

from packaging.utils import canonicalize_name

from dorsal.api.config import find_package_name_by_class
from dorsal.common.exceptions import DorsalError, AuthError
from dorsal.registry.validators import is_registry_id
from dorsal.session import get_shared_dorsal_client

logger = logging.getLogger(__name__)

TargetModelStrategy = Literal["registry_id", "class_name", "package"]


def resolve_target(target: str) -> tuple[TargetModelStrategy, str]:
    """
    Resolves a user-provided target string into a canonical pip package name.

    Strategies:
    1. Registry ID (e.g. 'dorsalhub/whisper') -> Strategy: 'registry_id'
       - If the format matches a Registry ID but the lookup fails, this RAISES an error.

    2. Model Class Name (e.g. 'FasterWhisperTranscriber') -> Strategy: 'class_name'
       Resolves to the package name via local pipeline config.

    3. Package Name (e.g. 'dorsal-whisper') -> Strategy: 'package'
       Assumes the input is a reference to the pip installed package name.

    Args:
        target: The string reference provided by the user.

    Returns:
        tuple: (Strategy, package_name) e.g. ('package', 'dorsal-whisper')
    """
    raw_package_name = None
    strategy: TargetModelStrategy

    if is_registry_id(target):
        logger.debug(f"Resolving Registry ID: {target}")
        client = get_shared_dorsal_client()
        try:
            reg_data = client.get_registry_model(target)
            raw_package_name = reg_data.package_name
            strategy = "registry_id"
            logger.debug(f"Registry ID '{target}' resolved to '{raw_package_name}'")
        except AuthError as e:
            raise e
        except Exception as e:
            raise DorsalError(f"Failed to resolve model '{target}' in registry: {e}") from e

    if not raw_package_name:
        resolved_from_config = find_package_name_by_class(target)
        if resolved_from_config:
            raw_package_name = resolved_from_config
            strategy = "package"
            logger.debug(f"Class Name '{target}' resolved to '{raw_package_name}'")

    if not raw_package_name:
        raw_package_name = target
        strategy = "class_name"
        logger.debug(f"Assuming target '{target}' is a direct package name.")

    safe_package_name = canonicalize_name(raw_package_name)

    return (strategy, safe_package_name)


def is_package_installed(package_name: str) -> bool:
    """
    Helper to check if a package exists in the current environment.
    """
    try:
        importlib.metadata.distribution(package_name)
        return True
    except importlib.metadata.PackageNotFoundError:
        return False
