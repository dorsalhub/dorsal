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

import sys
import pytest
from unittest.mock import patch, MagicMock

from dorsal.common import environment


def test_is_jupyter_environment_true():
    """Test the case where the code IS running in a Jupyter kernel."""
    # Create a mock for the IPython module and its get_ipython function
    mock_ipython = MagicMock()
    mock_ipython.get_ipython.return_value.config = {"IPKernelApp": {}}

    # Temporarily inject our mock module into the system's list of modules
    with patch.dict(sys.modules, {"IPython": mock_ipython}):
        assert environment.is_jupyter_environment() is True


def test_is_jupyter_environment_false_not_kernel():
    """Test the case where IPython is present but it's not a Jupyter kernel."""
    mock_ipython = MagicMock()
    mock_ipython.get_ipython.return_value.config = {}  # Config does not contain the key

    with patch.dict(sys.modules, {"IPython": mock_ipython}):
        assert environment.is_jupyter_environment() is False


def test_is_jupyter_environment_no_ipython_module():
    """Test the case where the IPython module is not installed, causing an ImportError."""
    # Temporarily remove IPython from sys.modules to simulate it not being installed
    with patch.dict(sys.modules, {"IPython": None}):
        assert environment.is_jupyter_environment() is False


def test_is_jupyter_environment_ipython_returns_none():
    """Test the case where get_ipython() returns None, causing an AttributeError."""
    mock_ipython = MagicMock()
    mock_ipython.get_ipython.return_value = None  # Simulate being in a non-interactive session

    with patch.dict(sys.modules, {"IPython": mock_ipython}):
        assert environment.is_jupyter_environment() is False


def test_is_jupyter_environment_generic_exception():
    """Test that any other unexpected exception is caught and returns False."""
    mock_ipython = MagicMock()
    mock_ipython.get_ipython.side_effect = RuntimeError("A generic, unexpected error")

    with patch.dict(sys.modules, {"IPython": mock_ipython}):
        assert environment.is_jupyter_environment() is False
