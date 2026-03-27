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

from dorsal.cli.local_app.scan_cmd import scan_target
# (Imports for other commands will go here once we port them)

app = typer.Typer(
    name="local",
    help="Scan, manage, identify and push local files and directories.",
    no_args_is_help=True,
)

app.command(name="scan")(scan_target)
