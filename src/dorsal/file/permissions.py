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

import re

MEDIA_TYPE_HEAD_PERMITTED = {
    "text",
    "audio",
    "image",
    "video",
}

MEDIA_TYPE_PERMITTED = {
    "application/x-shockwave-flash",
    "application/pdf",
}

PUBLIC_MEDIA_TYPES_PROHIBITED = {

}

RX_MEDIA_TYPE = re.compile(r"^\w+\/[-+.\w]+$")

def is_permitted_public_media_type(media_type: str) -> bool:
    """Returns True if the media type permits public indexing."""
    if not isinstance(media_type, str):
        return False

    if not RX_MEDIA_TYPE.match(media_type):
        return False
    
    media_type_lower = media_type.lower()
    
    if media_type_lower in PUBLIC_MEDIA_TYPES_PROHIBITED:
        return False

    if media_type_lower in MEDIA_TYPE_PERMITTED:
        return True

    head = media_type.split("/")[0]
    if head in MEDIA_TYPE_HEAD_PERMITTED:
        return True
        
    return False