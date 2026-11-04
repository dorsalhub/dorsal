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

import re

RX_ARXIV = re.compile(r"^(\d{2})(\d{2})\.\d{4,5}(v\d+)?$")
RX_ARXIV_LEGACY = re.compile(r"/(\d{2})(\d{2})\d{3}(v\d+)?$")


def extract_date_from_id(arxiv_id: str) -> tuple[str, str] | None:
    """Infers the publication year and month from an arXiv ID."""
    modern_match = RX_ARXIV.match(arxiv_id)
    if modern_match:
        yy, mm = modern_match.group(1), modern_match.group(2)
        return str(2000 + int(yy)), str(int(mm))

    legacy_match = RX_ARXIV_LEGACY.search(arxiv_id)
    if legacy_match:
        yy, mm = legacy_match.group(1), legacy_match.group(2)
        year = str(1900 + int(yy)) if int(yy) > 80 else str(2000 + int(yy))
        return year, str(int(mm))

    return None
