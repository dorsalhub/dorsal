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

import importlib.util
import sys
import pytest
import pathlib
from unittest.mock import patch
from dorsal.registry import initialize
from dorsal.common.exceptions import DorsalError


def test_create_project_success(tmp_path):
    """
    Test that a new project is created with the correct structure and content.
    """

    project_name = "My Cool Scanner"
    result = initialize.create_new_annotation_model_project(project_name, target_dir=tmp_path)

    expected_clean_name = "my-cool-scanner"
    expected_pkg_name = "dorsal-my-cool-scanner"

    assert result.clean_name == expected_clean_name
    assert result.package_name == expected_pkg_name
    assert result.path == tmp_path / expected_clean_name

    project_root = result.path
    module_dir = project_root / "my_cool_scanner"
    tests_dir = project_root / "tests"

    assert project_root.exists()
    assert module_dir.exists()
    assert tests_dir.exists()

    assert (project_root / "pyproject.toml").exists()
    assert (project_root / "README.md").exists()
    assert (project_root / ".gitignore").exists()
    assert (module_dir / "__init__.py").exists()
    assert (module_dir / "model.py").exists()
    assert (project_root / "model_config.toml").exists()
    assert (tests_dir / "test_model.py").exists()

    pyproject_content = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    assert f'name = "{expected_pkg_name}"' in pyproject_content
    assert f'description = "Dorsal model: {project_name}"' in pyproject_content

    model_config = (project_root / "model_config.toml").read_text(encoding="utf-8")
    assert 'schema_id = "generic"' in model_config
    assert 'schema_version = "0.8.0"' in model_config

    model_content = (module_dir / "model.py").read_text(encoding="utf-8")
    assert "class MyCoolScanner(AnnotationModel):" in model_content


def test_create_project_already_exists(tmp_path):
    """
    Test that we do not overwrite an existing directory.
    """

    project_name = "Existing Project"
    clean_name = "existing-project"
    (tmp_path / clean_name).mkdir()

    with pytest.raises(DorsalError) as exc:
        initialize.create_new_annotation_model_project(project_name, target_dir=tmp_path)

    assert f"Directory '{tmp_path / clean_name}' already exists" in str(exc.value)


def test_create_project_os_error(tmp_path):
    """
    Test that OS errors (like permission denied) are caught and re-raised as DorsalError.
    """

    with patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")):
        with pytest.raises(DorsalError) as exc:
            initialize.create_new_annotation_model_project("Fail Project", target_dir=tmp_path)

        assert "Failed to initialize project directory" in str(exc.value)


@pytest.fixture(autouse=True)
def forget_generated_modules():
    """Removes the generated projects' modules from `sys.modules` before and after each test."""

    def forget():
        for name in [name for name in sys.modules if name.split(".")[0] in ("fresh_probe", "option_probe")]:
            del sys.modules[name]

    forget()
    yield
    forget()


def _load_generated_test(*, project_root, module_name, package_name, monkeypatch):
    """Imports a generated project's `tests/test_model.py` as if the project were installed."""
    model_path = project_root / module_name / "model.py"
    model_source = model_path.read_text(encoding="utf-8")
    model_path.write_text(
        model_source.replace(f'version = version("{package_name}")', 'version = "0.1.0"'), encoding="utf-8"
    )

    monkeypatch.syspath_prepend(str(project_root))

    spec = importlib.util.spec_from_file_location("generated_test_model", project_root / "tests" / "test_model.py")
    assert spec is not None and spec.loader is not None
    generated = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generated)
    return generated


def test_generated_test_passes(tmp_path, monkeypatch):
    result = initialize.create_new_annotation_model_project("Fresh Probe", target_dir=tmp_path)
    generated = _load_generated_test(
        project_root=result.path,
        module_name="fresh_probe",
        package_name="dorsal-fresh-probe",
        monkeypatch=monkeypatch,
    )

    generated.test_model_integration(tmp_path)


def test_generated_test_passes_documented_option_defaults_only(tmp_path, monkeypatch):
    result = initialize.create_new_annotation_model_project("Option Probe", target_dir=tmp_path)
    project_root = result.path

    with (project_root / "model_config.toml").open("a", encoding="utf-8") as f:
        f.write('beam_size = { type = "int", default = 5, help = "Beam size." }\n')
        f.write('language = { type = "str", help = "Auto-detected if not provided." }\n')

    model_path = project_root / "option_probe" / "model.py"
    model_source = model_path.read_text(encoding="utf-8")
    model_source = model_source.replace("    def main(self):", "    def main(self, beam_size: int = 1):")
    model_source = model_source.replace(
        'return {"data": {"Hello": "World"}}', 'return {"data": {"beam_size": beam_size}}'
    )
    model_path.write_text(model_source, encoding="utf-8")

    generated = _load_generated_test(
        project_root=project_root,
        module_name="option_probe",
        package_name="dorsal-option-probe",
        monkeypatch=monkeypatch,
    )

    captured = {}
    real_run_model = generated.run_model

    def spy_run_model(**kwargs):
        results = real_run_model(**kwargs)
        captured["options"] = kwargs["options"]
        captured["records"] = results[0].records
        return results

    monkeypatch.setattr(generated, "run_model", spy_run_model)
    generated.test_model_integration(tmp_path)

    assert captured["options"] == {"beam_size": 5}
    assert captured["records"] == [{"data": {"beam_size": 5}}]
