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
    assert (module_dir / "model_config.toml").exists()
    assert (tests_dir / "test_model.py").exists()

    pyproject_content = (project_root / "pyproject.toml").read_text(encoding="utf-8")
    assert f'name = "{expected_pkg_name}"' in pyproject_content
    assert f'description = "Dorsal model: {project_name}"' in pyproject_content

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
