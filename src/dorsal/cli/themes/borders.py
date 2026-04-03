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

from rich import box
from rich.box import Box

INVISIBLE_BOX = Box("    \n    \n    \n    \n    \n    \n    \n    \n")

BORDER_SETS: dict[str, Box] = {
    "rounded": box.ROUNDED,
    "heavy": box.HEAVY,
    "ascii": box.ASCII,
    "minimal": box.MINIMAL,
    "double": box.DOUBLE,
    "square": box.SQUARE,
    "markdown": box.MARKDOWN,
    "none": INVISIBLE_BOX,
}


def get_borders(name: str = "rounded") -> Box:
    """Returns the requested rich box style, falling back to ROUNDED if not found."""
    return BORDER_SETS.get(name, box.ROUNDED)
