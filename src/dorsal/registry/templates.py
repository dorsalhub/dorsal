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

PYPROJECT_TEMPLATE = """[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{package_name}"
version = "0.1.0"
description = "Dorsal model: {human_name}"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "dorsalhub",
]

[project.entry-points."dorsal.models"]
{entry_point_name} = "{module_name}"

[tool.hatch.build.targets.wheel]
packages = ["{module_name}"]

[tool.hatch.build.targets.wheel.force-include]
"{module_name}/model_config.toml" = "{module_name}/model_config.toml"
"""

MODEL_CONFIG_TEMPLATE = """# Dorsal Model Configuration
# Documentation: https://docs.dorsalhub.com/models/config

# --- BASIC CONFIG ---
# The name of your Annotation Model class
model_class = "{class_name}"

# The schema which validates the model output
schema_id = "open/generic"

# --- DEPENDENCIES ---
# Define when this model should run.

# Example 1 (media_type): Run on files with the `text/plain` media type
[[dependencies]]
type = "media_type"
include = ["text/plain"]

# Example 2 (media_type): Run on any audio/video files except for Matroska video
# [[dependencies]]
# type = "media_type"
# include = ["audio", "video", "text/plain"]
# exclude = ["video/matroska"]

# Example 3 (file extension): Run only on MS Office Docs
# [[dependencies]]
# type = "extension"
# extensions = ["doc", "docx]

# Example 4 (file size): Run only on files smaller than 100MB
# [[dependencies]]
# type = "file_size"
# max_size = "100MB"

# --- RUNTIME OPTIONS ---
[options]
# Pass keyword arguments to your model class `main` method
"""

INIT_TEMPLATE = """from .model import {class_name}

__all__ = ["{class_name}"]
"""

MODEL_TEMPLATE = """from importlib.metadata import version
from dorsal import AnnotationModel

class {class_name}(AnnotationModel):
    id = "local/{entry_point_name}"
    version = version("{package_name}")

    def main(self):
        
        # Implement your logic here.

        return {{"data": {{"Hello": "World"}}}}
"""

TEST_TEMPLATE = """import pytest
import pathlib
import tomllib
from dorsal.testing import run_model
from {module_name}.model import {class_name}

def test_model_integration(tmp_path):
    # 1. Setup a dummy file
    dummy_file = tmp_path / "test_doc.txt"
    dummy_file.write_text("Hello Dorsal!")

    # 2. Load Registry Metadata
    root = pathlib.Path(__file__).parent.parent
    with open(root / "{module_name}" / "model_config.toml", "rb") as f:
        config = tomllib.load(f)

    # 3. Run Model
    result = run_model(
        annotation_model={class_name},
        file_path=str(dummy_file),
        schema_id=config.get("schema_id", "open/generic"),
        dependencies=config.get("dependencies"),
        options=config.get("options"),
    )

    assert result.error is None, f"Model execution failed: {{result.error}}"
    assert result.record is not None
"""
