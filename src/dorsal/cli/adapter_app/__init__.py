# Copyright 2026 Dorsal Hub LTD
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

from dorsal.cli.adapter_app.export_cmd import export_adapter
from dorsal.cli.adapter_app.list_cmd import list_adapters
from dorsal.cli.adapter_app.parse_cmd import parse_adapter


app = typer.Typer(
    name="adapter",
    help="[bold]export[/bold] annotations into standard formats (SRT, VTT, Markdown, etc.).",
    no_args_is_help=True,
)

app.command(name="export")(export_adapter)
app.command(name="list")(list_adapters)
app.command(name="parse")(parse_adapter)
