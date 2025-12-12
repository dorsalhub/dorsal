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

from dorsal.cli.cache_app.build_cache_cmd import build_cache
from dorsal.cli.cache_app.clear_cache_cmd import clear_cache
from dorsal.cli.cache_app.path_cache_cmd import get_cache_path
from dorsal.cli.cache_app.optimize_cache_cmd import optimize_cache
from dorsal.cli.cache_app.prune_cache_cmd import prune_cache
from dorsal.cli.cache_app.show_cache_cmd import show_cache
from dorsal.cli.cache_app.export_cmd import export_cache_cmd


app = typer.Typer(name="cache", help="""Commands to manage the local cache.""", no_args_is_help=True)

app.command(name="build")(build_cache)
app.command(name="clear")(clear_cache)
app.command(name="path")(get_cache_path)
app.command(name="optimize")(optimize_cache)
app.command(name="prune")(prune_cache)
app.command(name="show")(show_cache)
app.command(name="export")(export_cache_cmd)
