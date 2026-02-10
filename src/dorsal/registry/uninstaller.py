# Copyright 2025-2026 Dorsal Hub LTD
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

import sys
import subprocess
import logging
from typing import Literal

from dorsal.api.config import unregister_model
from dorsal.common.exceptions import DorsalError
from dorsal.registry.resolution import resolve_target

logger = logging.getLogger(__name__)


def _run_pip_uninstall_streaming(package_name: str) -> bool:
    """
    Runs pip uninstall in a subprocess.
    Returns True if a package was actually removed, False otherwise.
    """
    logger.info(f"Attempting to uninstall python package: {package_name}...")

    cmd = [sys.executable, "-m", "pip", "uninstall", "-y", package_name]

    is_verbose = logger.isEnabledFor(logging.INFO)

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    captured_lines = []
    skipped = False

    if process.stdout:
        for line in process.stdout:
            # Pip outputs this specific message if the package isn't found
            if f"Skipping {package_name} as it is not installed" in line:
                skipped = True

            if is_verbose:
                sys.stdout.write(line)
            captured_lines.append(line)

    return_code = process.wait()

    if return_code != 0:
        # If pip errors out (permissions, etc), we treat it as a failure
        full_log = "".join(captured_lines)
        if not is_verbose:
            sys.stderr.write(f"\n[!] Pip Uninstall Log for '{package_name}':\n")
            sys.stderr.write(full_log)
        logger.warning(f"Pip reported an error uninstalling '{package_name}'.")
        return False

    return not skipped


def uninstall_model_target(
    target: str,
    scope: Literal["project", "global"] = "project",
) -> str:
    """
    Uninstalls a model.
    Raises DorsalError if NO action was taken (nothing removed from config AND nothing removed from pip).
    """
    logger.info(f"Processing uninstall target: {target}")

    _, safe_package_name = resolve_target(target)

    did_modify_config = False
    did_uninstall_pip = False

    try:
        unregister_model(package_name=safe_package_name, scope=scope)
        did_modify_config = True
    except KeyError:
        logger.debug(f"Config cleanup skipped: '{safe_package_name}' not found in {scope} config.")
    except Exception as e:
        raise DorsalError(f"Failed to update dorsal configuration: {e}") from e

    did_uninstall_pip = _run_pip_uninstall_streaming(safe_package_name)

    if not did_modify_config and not did_uninstall_pip:
        raise DorsalError(
            f"Could not find model '{target}' (resolved as package: '{safe_package_name}') "
            f"in the {scope} configuration OR installed in the environment."
        )

    action_summary = []
    if did_modify_config:
        action_summary.append(f"removed from {scope} config")
    if did_uninstall_pip:
        action_summary.append("uninstalled python package")

    logger.info(f"Successfully uninstalled {safe_package_name} ({', '.join(action_summary)})")
    return safe_package_name