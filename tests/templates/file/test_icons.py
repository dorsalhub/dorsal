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

from dorsal.templates.file.icons import get_media_type_icon, ICON_MAP


def test_get_icon_exact_match():
    """Test that an exact match in the map returns the specific icon."""
    icon = get_media_type_icon("application/pdf")
    assert icon == ICON_MAP["application/pdf"]
    assert "<svg" in icon


def test_get_icon_main_type_fallback():
    """
    Test that a subtype not in the map (video/mp4)
    falls back to the main type (video).
    """
    icon = get_media_type_icon("video/mp4")
    assert icon == ICON_MAP["video"]


def test_get_icon_default_fallback():
    """
    Test that a completely unknown type falls back to default.
    """
    icon = get_media_type_icon("chemical/x-pdb")
    assert icon == ICON_MAP["default"]
