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

from dorsal.cli.file_app.scan_cmd import scan_file
from dorsal.cli.file_app.push_cmd import push_file
from dorsal.cli.file_app.report_cmd import make_file_report
from dorsal.cli.file_app.hash_cmd import hash_file
from dorsal.cli.file_app.identify_cmd import identify_file_cmd

app = typer.Typer(
    name="file",
    help="Commands to manage local file metadata.",
    no_args_is_help=True,
)

app.command(name="scan")(scan_file)
app.command(name="push")(push_file)
app.command(name="report")(make_file_report)
app.command(name="hash")(hash_file)
app.command(name="identify")(identify_file_cmd)
app.command(name="id", hidden=True)(identify_file_cmd)
