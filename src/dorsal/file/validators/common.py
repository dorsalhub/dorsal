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

from typing import Annotated

from dorsal.file.utils.hashes import RX_HEX_64, RX_TLSH
from pydantic import AfterValidator, BaseModel


def validate_hex64(value: str) -> str:
    """Return lowercased 64 char hex string or raise."""
    if len(value) != 64:
        raise ValueError(f"Invalid hash string: {value}")
    if RX_HEX_64.match(value):
        return value.lower()
    raise ValueError(f"Invalid hash string: {value}")


SHA256Hash = Annotated[str, AfterValidator(validate_hex64)]
QuickHash = Annotated[str, AfterValidator(validate_hex64)]
Blake3Hash = Annotated[str, AfterValidator(validate_hex64)]


def validate_tlsh(value: str) -> str:
    """Return uppercased 72 char TLSH hash string or raise."""
    if len(value) != 72:
        raise ValueError(f"Invalid hash string: {value}")
    if RX_TLSH.match(value):
        return value.upper()
    raise ValueError(f"Invalid hash string: {value}")


TLSHash = Annotated[str, AfterValidator(validate_tlsh)]
