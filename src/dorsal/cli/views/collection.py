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

from typing import TYPE_CHECKING

from rich.console import RenderableType

from dorsal.cli.views.layout import key_values, section

if TYPE_CHECKING:
    from dorsal.file.validators.collection import FileCollection
    from dorsal.cli.themes import UIContext


def collection_metadata(collection: "FileCollection", ui_context: "UIContext") -> RenderableType:
    """Renders a collection's metadata under a "Collection metadata" heading."""
    from dorsal.file.utils.size import human_filesize

    if collection.date_modified is not None:
        date_modified = collection.date_modified.strftime("%Y-%m-%d %H:%M:%S")
    else:
        date_modified = "None"

    metadata = key_values(
        ui_context,
        [
            ("ID", collection.collection_id),
            ("Name", collection.name),
            ("Description", collection.description or None),
            ("File count", f"{collection.file_count:,}"),
            ("Total size", human_filesize(collection.total_size)),
            ("Access", "Private" if collection.is_private else "Public"),
            ("Modified", date_modified),
        ],
    )

    return section("Collection metadata", metadata, ui_context)
