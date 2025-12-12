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

import os


def get_file_paths(dir_path: str, recursive: bool = False) -> list[str]:
    file_paths = []
    if recursive:
        for root, _, files in os.walk(dir_path):
            for file in files:
                file_path = os.path.join(root, file)
                file_paths.append(file_path)
    else:
        for entry in os.listdir(dir_path):
            file_path = os.path.join(dir_path, entry)
            if os.path.isfile(file_path):
                file_paths.append(file_path)
    return file_paths
