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

AUDIO_MEDIA_TYPES = {
    "audio/aac",
    "audio/ac3",
    "audio/midi",
    "audio/mpeg",
    "audio/MPA",
    "audio/mp4",
    "audio/ogg",
    "audio/flac",
    "audio/x-hx-aac-adts",
    "audio/x-m4a",
    "audio/x-wav",
}

IMAGE_MEDIA_TYPES = {
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/tiff",
    # "image/svg",
    "image/vnd.adobe.photoshop",
    "image/webp",
    "image/x-gem",
    "image/x-icns",
    "image/x-icon",
    "image/x-ms-bmp",
    "image/x-pcx",
    "image/x-tga",
    "image/x-xpmi",
}

VIDEO_MEDIA_TYPES = {
    "application/vnd.rn-realmedia",
    "video/MP2P",
    "video/MP2T",
    "video/mp4",
    "video/mpeg",
    "video/ogg",
    "video/quicktime",
    "video/vnd.avi",
    "video/x-flv",
    "video/x-m4v",
    "video/x-ms-asf",
    "video/x-ms-wmv",
    "video/x-msvideo",
    "video/matroska",
    "video/mpeg4-generic",
    "video/webm",
}

OTHER_MEDIA_TYPES = {
    "application/x-shockwave-flash",
}

MEDIAINFO_MEDIA_TYPES = AUDIO_MEDIA_TYPES | IMAGE_MEDIA_TYPES | OTHER_MEDIA_TYPES | VIDEO_MEDIA_TYPES
