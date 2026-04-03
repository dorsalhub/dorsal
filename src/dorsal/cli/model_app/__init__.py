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

from dorsal.cli.model_app.init_model_cmd import init_model
from dorsal.cli.model_app.install_model_cmd import install_model
from dorsal.cli.model_app.run_model_cmd import run_model
from dorsal.cli.model_app.uninstall_model_cmd import uninstall_model


app = typer.Typer(
    name="model", help="[bold]install[/bold] and [bold]run[/bold] Annotation Models from DorsalHub or create your own.", no_args_is_help=True
)

app.command(name="init")(init_model)
app.command(name="install")(install_model)
app.command(name="run")(run_model)
app.command(name="uninstall")(uninstall_model)
