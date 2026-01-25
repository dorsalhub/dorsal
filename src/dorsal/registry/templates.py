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

# --- DORSAL REGISTRY CONFIG ---
# This registers your model with the Dorsal ecosystem.
[project.entry-points."dorsal.models"]
{entry_point_name} = "{module_name}:DORSAL_CONFIG"

# --- PACKAGING CONFIG ---
[tool.hatch.build.targets.wheel]
packages = ["{module_name}"]
"""

MODEL_TEMPLATE = """from dorsal import AnnotationModel

class {class_name}(AnnotationModel):
    id = "local/{entry_point_name}"
    version = "0.1.0"

    def main(self):
        # The file content is available at self.file_path
        # The base metadata (hash, size) is in self.base_record
        
        # TODO: Implement your logic here.
        # This return value must match the 'open/generic' schema.
        return {{
            "data": {{
                "hello": "world"
            }},
            "producer": self.id
        }}
"""

CONFIG_TEMPLATE = """from dorsal.file.dependencies import make_media_type_dependency
from .model import {class_name}

# The Registry Contract
DORSAL_CONFIG = {{
    "model_class": {class_name},
    "schema_id": "open/generic",
    "dependencies": [
        # Example: Run only on PDFs
        # make_media_type_dependency(include=["application/pdf"])
    ],
    "options": {{
        # Define default options here
    }}
}}
"""

INIT_TEMPLATE = """from .config import DORSAL_CONFIG

__all__ = ["DORSAL_CONFIG"]
"""

# NEW: Uses dorsal.testing.run_model to simulate a real execution
TEST_TEMPLATE = """import pytest
from dorsal.testing import run_model
from {module_name}.config import DORSAL_CONFIG

def test_model_integration(tmp_path):
    \"\"\"
    Tests the model running inside the Dorsal harness.
    This verifies config, schema validation, and execution logic.
    \"\"\"
    # 1. Setup a dummy file
    dummy_file = tmp_path / "test_doc.txt"
    dummy_file.write_text("Hello Dorsal!")

    # 2. Run the model using the actual config
    result = run_model(
        annotation_model=DORSAL_CONFIG["model_class"],
        file_path=str(dummy_file),
        schema_id=DORSAL_CONFIG["schema_id"],
        validation_model=DORSAL_CONFIG.get("validation_model"),
        dependencies=DORSAL_CONFIG.get("dependencies"),
        options=DORSAL_CONFIG.get("options"),
    )

    # 3. Assertions
    assert result.error is None, f"Model execution failed: {{result.error}}"
    assert result.record is not None, "Model returned no data"
    
    # Check expected output from the template logic
    assert result.record["data"]["hello"] == "world"
"""
