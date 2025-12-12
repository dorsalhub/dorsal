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

from dorsal.cli.collection_app.add_files_cmd import add_files
from dorsal.cli.collection_app.remove_files_cmd import remove_files
from dorsal.cli.collection_app.make_private_cmd import make_private
from dorsal.cli.collection_app.make_public_cmd import make_public

from dorsal.cli.collection_app.delete_cmd import delete_collection
from dorsal.cli.collection_app.export_cmd import export_dorsal_collection
from dorsal.cli.collection_app.list_cmd import list_dorsal_collections
from dorsal.cli.collection_app.show_cmd import show_collection
from dorsal.cli.collection_app.update_cmd import update_collection


app = typer.Typer(
    name="collection",
    help="Commands to manage remote file collections on DorsalHub.",
    no_args_is_help=True,
)

app.command(name="delete")(delete_collection)
app.command(name="export")(export_dorsal_collection)
app.command(name="list")(list_dorsal_collections)
app.command(name="show")(show_collection)
app.command(name="update")(update_collection)
app.command(name="make-private")(make_private)
app.command(name="make-public")(make_public)
app.command(name="add-files")(add_files)
app.command(name="remove-files")(remove_files)
