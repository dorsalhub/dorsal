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

import typer

from dorsal.cli.index_app.build_index_cmd import build_search_index
from dorsal.cli.index_app.delete_index_cmd import delete_search_index
from dorsal.cli.index_app.path_index_cmd import get_index_db_path
from dorsal.cli.index_app.optimize_index_cmd import optimize_search_index
from dorsal.cli.index_app.prune_index_cmd import prune_search_index
from dorsal.cli.index_app.summary_index_cmd import show_index_summary
from dorsal.cli.index_app.export_index_cmd import export_index_cmd
from dorsal.cli.index_app.search_index_cmd import search_index_cmd
from dorsal.cli.index_app.get_index_cmd import get_index_record


app = typer.Typer(name="index", help="Manage local search index settings.", no_args_is_help=True)

app.command(name="get")(get_index_record)
app.command(name="build")(build_search_index)
app.command(name="delete")(delete_search_index)
app.command(name="path")(get_index_db_path)
app.command(name="optimize")(optimize_search_index)
app.command(name="prune")(prune_search_index)
app.command(name="summary")(show_index_summary)
app.command(name="export")(export_index_cmd)
app.command(name="search")(search_index_cmd)
