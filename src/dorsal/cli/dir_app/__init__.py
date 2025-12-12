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

from dorsal.cli.dir_app.push_dir_cmd import push_directory
from dorsal.cli.dir_app.scan_dir_cmd import scan_directory
from dorsal.cli.dir_app.info_dir_cmd import info_directory
from dorsal.cli.dir_app.duplicates_dir_cmd import duplicates_dir

app = typer.Typer(
    name="dir",
    help="Commands to manage local files and directories.",
    no_args_is_help=True,
)

app.command(name="push")(push_directory)
app.command(name="scan")(scan_directory)
app.command(name="info")(info_directory)
app.command(name="duplicates")(duplicates_dir)
