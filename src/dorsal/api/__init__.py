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

from dorsal.api.file import (
    add_tag_to_file,
    delete_private_dorsal_file_record,
    delete_public_dorsal_file_record,
    find_duplicates,
    generate_html_directory_report,
    generate_html_file_report,
    get_directory_info,
    get_dorsal_file_record,
    identify_file,
    index_directory,
    index_file,
    scan_directory,
    scan_file,
    remove_tag_from_file,
    search_global_files,
    search_user_files,
)

from dorsal.api.dataset import (
    get_dataset,
    get_dataset_schema,
    make_schema_validator,
    validate_dataset_records,
)

from dorsal.api.collection import (
    add_files_to_collection,
    delete_collection,
    export_collection,
    get_collection,
    list_collections,
    make_collection_private,
    make_collection_public,
    remove_files_from_collection,
    update_collection,
)

from dorsal.api.config import (
    register_model,
    show_model_pipeline,
    remove_model_by_name,
    activate_model_by_name,
    deactivate_model_by_name,
)


__all__ = [
    # file
    "add_tag_to_file",
    "delete_private_dorsal_file_record",
    "delete_public_dorsal_file_record",
    "find_duplicates",
    "generate_html_directory_report",
    "generate_html_file_report",
    "get_directory_info",
    "get_dorsal_file_record",
    "identify_file",
    "index_directory",
    "index_file",
    "scan_directory",
    "scan_file",
    "remove_tag_from_file",
    "search_global_files",
    "search_user_files",
    # dataset
    "get_dataset",
    "get_dataset_schema",
    "make_schema_validator",
    "validate_dataset_records",
    # collection
    "add_files_to_collection",
    "delete_collection",
    "export_collection",
    "get_collection",
    "list_collections",
    "make_collection_private",
    "make_collection_public",
    "remove_files_from_collection",
    "update_collection",
    # config
    "register_model",
    "show_model_pipeline",
    "remove_model_by_name",
    "activate_model_by_name",
    "deactivate_model_by_name",
]
