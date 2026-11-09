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

import json
import sys
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from dorsal.cli import app
from dorsal.client.validators import RegistryModelResponse

runner = CliRunner()

MODEL_SOURCE = """from dorsal import AnnotationModel


class StubOptionsModel(AnnotationModel):
    id = "stub/options"
    version = "1.0.0"

    def main(self, **options):
        self.variant = ",".join(f"{key}={options[key]}" for key in sorted(options)) or None
        return {"data": {"received": ",".join(sorted(options)), "language": str(options.get("language", "auto"))}}
"""

CONFIG_HEAD = """model_class = "StubOptionsModel"
schema_id = "generic"
schema_version = "0.8.0"

[options]
beam_size = { type = "int", default = 5, help = "Beam size." }
"""

DOCUMENTED_LANGUAGE = 'language = { type = "str", help = "Input language. Auto-detected if not provided." }\n'


def _install_stub_package(*, root, monkeypatch, module_name, with_language):
    """Installs a stub model package, with a dist-info and a `dorsal.models` entry point, onto `sys.path`."""
    site = root / f"site_{module_name}"
    package_dir = site / module_name
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text(MODEL_SOURCE, encoding="utf-8")
    (package_dir / "model_config.toml").write_text(
        CONFIG_HEAD + (DOCUMENTED_LANGUAGE if with_language else ""), encoding="utf-8"
    )

    dist_name = module_name.replace("_", "-")
    dist_info = site / f"{module_name}-1.0.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {dist_name}\nVersion: 1.0.0\n", encoding="utf-8")
    (dist_info / "entry_points.txt").write_text(f"[dorsal.models]\nstub = {module_name}\n", encoding="utf-8")

    monkeypatch.syspath_prepend(str(site))
    return dist_name


@pytest.fixture(autouse=True)
def forget_stub_modules():
    """Removes the stub packages' modules from `sys.modules` before and after each test."""
    names = ("stub_documented_model", "stub_absent_model")
    for name in names:
        sys.modules.pop(name, None)
    yield
    for name in names:
        sys.modules.pop(name, None)


@pytest.fixture
def text_file(tmp_path):
    path = tmp_path / "file.txt"
    path.write_text("hello world", encoding="utf-8")
    return str(path)


@pytest.fixture
def registry(mocker):
    """Resolves registry ids `stub/<name>` to the package `<name>` without contacting DorsalHub."""
    client = MagicMock()

    def get_registry_model(model_identifier, use_cache=True):
        namespace, name = model_identifier.split("/", 1)
        return RegistryModelResponse(
            namespace=namespace,
            name=name,
            version="1.0.0",
            install_url=f"git+https://example.com/{name}.git@0123456789abcdef",
            schema_id="generic",
            package_name=name,
            is_official=True,
            is_verified=True,
        )

    client.get_registry_model.side_effect = get_registry_model
    mocker.patch("dorsal.api.model.get_shared_dorsal_client", return_value=client)
    mocker.patch("dorsal.registry.resolution.get_shared_dorsal_client", return_value=client)
    return client


def _run_json(*, console, args):
    console.reset_mock()
    result = runner.invoke(app, ["run", *args, "--json", "--no-save"])
    assert result.exit_code == 0, result.output
    (data,) = json.loads(console.print.call_args.args[0])["results"]
    assert data.get("error") is None, data
    (record,) = data["records"]
    source = {key: value for key, value in data["source"].items() if key != "execution_id"}
    return {"source": source, "record": record}


def _targets(*, dist_name):
    return {"package": dist_name, "registry_id": f"stub/{dist_name}"}


@pytest.mark.parametrize("target_kind", ["package", "registry_id"])
def test_documented_option_without_default_is_not_passed(
    target_kind, tmp_path, monkeypatch, mock_rich_console, registry, text_file
):
    documented = _install_stub_package(
        root=tmp_path, monkeypatch=monkeypatch, module_name="stub_documented_model", with_language=True
    )
    absent = _install_stub_package(
        root=tmp_path, monkeypatch=monkeypatch, module_name="stub_absent_model", with_language=False
    )

    with_documented = _run_json(
        console=mock_rich_console, args=[_targets(dist_name=documented)[target_kind], text_file]
    )
    with_absent = _run_json(console=mock_rich_console, args=[_targets(dist_name=absent)[target_kind], text_file])

    assert with_documented["source"]["variant"] == "beam_size=5"
    assert with_documented["record"]["data"] == {"received": "beam_size", "language": "auto"}
    assert with_documented == with_absent


@pytest.mark.parametrize("target_kind", ["package", "registry_id"])
def test_documented_option_without_default_is_set_by_opt(
    target_kind, tmp_path, monkeypatch, mock_rich_console, registry, text_file
):
    documented = _install_stub_package(
        root=tmp_path, monkeypatch=monkeypatch, module_name="stub_documented_model", with_language=True
    )

    output = _run_json(
        console=mock_rich_console, args=[_targets(dist_name=documented)[target_kind], text_file, "--opt", "language=fr"]
    )

    assert output["source"]["variant"] == "beam_size=5,language=fr"
    assert output["record"]["data"] == {"received": "beam_size,language", "language": "fr"}
