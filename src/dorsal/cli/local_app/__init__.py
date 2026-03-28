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
from dorsal.cli.local_app.push_cmd import push_target
from dorsal.cli.local_app.report_cmd import report_target
from dorsal.cli.local_app.info_cmd import info_target
from dorsal.cli.local_app.identify_cmd import identify_target
from dorsal.cli.local_app.hash_cmd import hash_target
from dorsal.cli.local_app.duplicates_cmd import duplicates_target

app = typer.Typer(
    name="local",
    help="Scan, manage, identify and push local files and directories.",
    no_args_is_help=True,
)

app.command(name="scan")(scan_target)
app.command(name="push")(push_target)
app.command(name="report")(report_target)
app.command(name="info")(info_target)
app.command(name="hash")(hash_target)
app.command(name="id")(identify_target)
app.command(name="identify", hidden=True)(identify_target)
app.command(name="dupes")(duplicates_target)
app.command(name="duplicates", hidden=True)(duplicates_target)
