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

from __future__ import annotations
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console


def is_jupyter_environment() -> bool:
    """Checks if the code is running in a Jupyter environment."""
    try:
        from IPython import get_ipython  # type: ignore

        if "IPKernelApp" in get_ipython().config:
            return True
    except (ImportError, AttributeError):
        return False
    except Exception:
        return False
    return False


def should_show_progress(show_progress: bool | None, console: Console | None = None) -> bool:
    """
    Determines if a progress bar should be displayed.

    Priority:
    1. Explicit 'show_progress' argument (True/False).
    2. Active Jupyter environment.
    3. Explicit 'console' object passed.
    4. Interactive terminal.

    Args:
        show_progress: Explicit override.
        console: Optional Rich Console instance.
    """
    if show_progress is not None:
        return show_progress

    if is_jupyter_environment():
        return True

    if console is not None:
        return True

    try:
        return sys.stdout.isatty()
    except Exception:
        return False
