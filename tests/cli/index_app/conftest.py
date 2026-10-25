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

import io
from typing import Callable
from unittest.mock import MagicMock

import pytest
from rich.console import Console


def render_printed(mock_console: MagicMock, width: int = 120) -> str:
    """Renders everything printed to a mocked Rich console and returns it as plain text."""
    console = Console(file=io.StringIO(), width=width, record=True, color_system=None, force_terminal=False)
    for printed in mock_console.print.call_args_list:
        kwargs = {k: v for k, v in printed.kwargs.items() if k in ("style", "end", "sep", "soft_wrap")}
        console.print(*printed.args, **kwargs)
    return console.export_text()


@pytest.fixture
def rendered() -> Callable[..., str]:
    """Returns a function that renders a mocked console's printed output to plain text."""
    return render_printed
