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
from typing import Annotated, Any

from pydantic import BeforeValidator

from dorsal.common.validators.strings import TString4096

logger = logging.getLogger(__name__)


def truncate_list(max_length: int):
    def validator(v: Any) -> Any:
        if isinstance(v, (list, tuple)) and len(v) > max_length:
            logger.debug("Truncating sequence from %d to %d items.", len(v), max_length)
            return v[:max_length]
        return v

    return validator


# == TStringList: Truncated list containing truncated strings ===
# - Truncates list if longer than specified max length without raising. Additionally truncates inner strings.
TStringList256 = Annotated[list[TString4096], BeforeValidator(truncate_list(256))]
