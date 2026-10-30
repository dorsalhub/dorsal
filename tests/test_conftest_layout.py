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

from pathlib import Path


def test_tests_have_a_single_conftest():
    tests_dir = Path(__file__).resolve().parent
    conftests = sorted(path.relative_to(tests_dir).as_posix() for path in tests_dir.rglob("conftest.py"))

    assert conftests == ["conftest.py"], (
        "Put shared fixtures in tests/conftest.py. The test directories are not packages, so another conftest.py "
        "replaces it as the `conftest` module, and pyfakefs then leaves its `Path` unpatched (fails on Python 3.11)."
    )
