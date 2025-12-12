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


def is_jupyter_environment() -> bool:
    """Checks if the code is running in a Jupyter environment."""
    try:
        from IPython import get_ipython  # type: ignore

        if "IPKernelApp" in get_ipython().config:
            return True
    except (ImportError, AttributeError):
        return False
    except Exception:
        return False
    return False
