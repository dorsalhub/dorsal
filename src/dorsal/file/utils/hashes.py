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

from enum import Enum
from typing import Any, Literal
import re
import logging

from dorsal.common.exceptions import ValidationError

logger = logging.getLogger(__name__)

HashFunctionId = Literal["BLAKE3", "SHA-256", "TLSH", "QUICK"]

RX_HEX_64 = re.compile(r"^[0-9a-fA-F]{64}$")
RX_TLSH = re.compile(r"^[tT]{1}1[0-9a-fA-F]{70}$")

RX_LOWERCASE_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
RX_LOWERCASE_HEX_32 = re.compile(r"^[0-9a-f]{32}$")
RX_LOWERCASE_HEX_24 = re.compile(r"^[0-9a-f]{24}$")

RX_MAPPING_HASH_FUNCTION_STRING = {
    "BLAKE3": RX_LOWERCASE_HEX_64,
    "SHA-256": RX_LOWERCASE_HEX_64,
    "TLSH": RX_TLSH,
    "QUICK": RX_LOWERCASE_HEX_64,
}
SUPPORTED_HASH_FUNCTIONS = set(RX_MAPPING_HASH_FUNCTION_STRING.keys())


class HashFunction(Enum):
    SHA256 = "SHA-256"
    BLAKE3 = "BLAKE3"
    QUICK = "QUICK"
    TLSH = "TLSH"


RX_PREFIXED_HASH = re.compile(r"^(?P<prefix>sha-?256|blake3|quick|tlsh):(?P<value>.+)$", re.IGNORECASE)

PREFIX_MAP = {
    "sha-256": HashFunction.SHA256,
    "sha256": HashFunction.SHA256,
    "blake3": HashFunction.BLAKE3,
    "quick": HashFunction.QUICK,
    "tlsh": HashFunction.TLSH,
}


def parse_validate_hash(hash_string: str) -> tuple[str, str] | tuple[None, None]:
    """Returns the normalized (lower-cased) hash string, with hash function identifier.

    Supports: SHA-256, BLAKE3, TLSH and QUICK.

    """
    logger.debug("hash string: %s", hash_string)
    if not isinstance(hash_string, str) or not hash_string:
        logger.debug("error: %s", type(hash_string))
        return None, None

    length = len(hash_string)

    if length == 64:
        return (hash_string.lower(), HashFunction.SHA256.value) if RX_HEX_64.match(hash_string) else (None, None)

    if length == 72 and hash_string.lower().startswith("t"):
        return (hash_string.lower(), HashFunction.TLSH.value) if RX_TLSH.match(hash_string) else (None, None)

    match_ = RX_PREFIXED_HASH.match(hash_string)
    logger.debug("match: %s", match_)
    if not match_:
        return None, None

    groups = match_.groupdict()
    prefix = groups["prefix"].lower()
    value = groups["value"]
    hash_type = PREFIX_MAP.get(prefix)

    logger.debug(
        "groups: %s, prefix: %s, value: %s, hash_type: %s",
        groups,
        prefix,
        value,
        hash_type,
    )

    if not hash_type:
        return None, None

    if hash_type == HashFunction.TLSH:
        if not RX_TLSH.match(value):
            return None, None
    else:
        if not RX_HEX_64.match(value):
            return None, None

    return value.lower(), hash_type.value


class HashStringValidator:
    def is_supported_hash_function(self, candidate: str) -> bool:
        if candidate in RX_MAPPING_HASH_FUNCTION_STRING:
            return True
        return False

    def is_valid(self, candidate_string: str | Any, hash_function: str) -> bool:
        if not isinstance(candidate_string, str):
            return False
        hash_function = hash_function.upper()
        if not RX_MAPPING_HASH_FUNCTION_STRING.get(hash_function.upper()):
            raise ValidationError(f"Unknown/unsupported hash function: {hash_function}")
        return bool(RX_MAPPING_HASH_FUNCTION_STRING[hash_function].match(candidate_string.lower()))

    def validate(self, candidate_string: str, hash_function: str) -> None:
        if self.is_valid(candidate_string=candidate_string, hash_function=hash_function):
            return None
        raise ValidationError(f"Invalid {hash_function} string: {candidate_string}")

    def get_valid_hash(self, candidate_string: str, hash_function: str) -> str | None:
        if self.is_valid(candidate_string=candidate_string, hash_function=hash_function):
            if hash_function == "TLSH":
                return candidate_string.upper()
            return candidate_string.lower()
        return None


hash_string_validator = HashStringValidator()
