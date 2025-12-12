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

import typer

from dorsal.cli.record_app.get_cmd import get_file_record
from dorsal.cli.record_app.delete_cmd import delete_file_record
from dorsal.cli.record_app.tag_app import tag_app
from dorsal.cli.record_app.search_cmd import search_record

app = typer.Typer(
    name="record",
    help="Commands to manage remote file metadata.",
    no_args_is_help=True,
)

app.command(name="get")(get_file_record)
app.command(name="delete")(delete_file_record)
app.command(name="search")(search_record)
app.add_typer(tag_app, name="tag")
