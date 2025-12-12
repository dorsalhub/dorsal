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
import pathlib

WEB_URL = os.getenv("DORSAL_WEB_URL", "https://dorsalhub.com")
DOCS_URL = os.getenv("DORSAL_DOCS_URL", "https://docs.dorsalhub.com")
BASE_URL = os.getenv("DORSAL_API_URL", "https://api.dorsalhub.com")

API_MAX_BATCH_SIZE = 1000
ANNOTATION_MAX_SIZE_BYTES = 1024 * 1024

# == Auth & Config ==
ENV_DORSAL_API_KEY_STR = "DORSAL_API_KEY"
ENV_DORSAL_CACHE_ENABLED = "DORSAL_CACHE_ENABLED"
ENV_DORSAL_CACHE_COMPRESSION = "DORSAL_CACHE_COMPRESSION"

LOCAL_DORSAL_DIR = pathlib.Path.home() / ".dorsal"

# Names for the hierarchical config search
PROJECT_CONFIG_FILENAMES = ["dorsal.toml", ".dorsal.toml"]
GLOBAL_CONFIG_FILENAME = "dorsal.toml"
PROJECT_CONFIG_SUBDIR = ".dorsal"

# TOML Sections and Keys
CONFIG_SECTION_AUTH = "auth"
CONFIG_OPTION_API_KEY = "api_key"
CONFIG_OPTION_EMAIL = "email"
CONFIG_SECTION_UI = "ui"
CONFIG_OPTION_THEME = "theme"
CONFIG_SECTION_CACHE = "cache"
CONFIG_OPTION_ENABLED = "enabled"
CONFIG_OPTION_COMPRESSION = "compression"


# == CLI ==
CLI_EXPORTS_DIR = LOCAL_DORSAL_DIR / "export"
CLI_SCAN_REPORTS_DIR = LOCAL_DORSAL_DIR / "scan"
CLI_STATS_REPORTS_DIR = LOCAL_DORSAL_DIR / "stats"
CLI_DUPLICATES_REPORTS_DIR = LOCAL_DORSAL_DIR / "duplicates"
CLI_GET_REPORTS_DIR = LOCAL_DORSAL_DIR / "get"
CLI_SEARCH_REPORTS_DIR = LOCAL_DORSAL_DIR / "search"
CLI_SUPPORTED_EXPORT_FORMATS = ["csv", "json"]
CLI_DEFAULT_EXPORT_FORMAT = "json"


# == Docs ==
DOCS_URL_API_TROUBLESHOOTING = f"{WEB_URL}/reference/exceptions/"
DOCS_URL_API_ERRORS = f"{WEB_URL}/reference/exceptions/"
DOCS_URL_API_AUTH = f"{DOCS_URL}/cli/auth/#dorsal-auth-login"
DOCS_URL_API_ERRORS_NETWORK = f"{WEB_URL}/reference/exceptions/"
DOCS_URL_API_ERRORS_VALIDATION = f"{WEB_URL}/reference/exceptions/"
DOCS_URL_DORSAL_FILE_TAGS = f"{WEB_URL}/reference/tags"

# == API ==
API_ENDPOINT_COLLECTIONS = "v1/collections"
API_ENDPOINT_EXPORT = "v1/export"
API_ENDPOINT_FILES = "v1/files"
API_ENDPOINT_FILE_SEARCH = "v1/files/search"
API_ENDPOINT_NAMESPACES = "v1/namespaces"
API_ENDPOINT_FILE_TAG_VALIDATION = "v1/files/tags/validate"
API_ENDPOINT_USER_CHECK_FILES_INDEXED = "v1/users/files-indexed"

# == Core Schemas ==
FILE_BASE_ANNOTATION_SCHEMA = "file/base"
CORE_EBOOK_ANNOTATION_SCHEMA = "file/ebook"
CORE_PDF_ANNOTATION_SCHEMA = "file/pdf"
CORE_MEDIAINFO_ANNOTATION_SCHEMA = "file/mediainfo"
CORE_OFFICE_DOCUMENT_ANNOTATION_SCHEMA = "file/office"
CORE_FILE_DATASETS = {
    FILE_BASE_ANNOTATION_SCHEMA,
    CORE_EBOOK_ANNOTATION_SCHEMA,
    CORE_PDF_ANNOTATION_SCHEMA,
    CORE_MEDIAINFO_ANNOTATION_SCHEMA,
    CORE_OFFICE_DOCUMENT_ANNOTATION_SCHEMA,
}

VALID_DATASET_TYPES = ["File", "Reference"]


# == Open Validation Schemas ===
OPEN_VALIDATION_SCHEMAS_VER = "0.1.0"
ENV_DORSAL_OPEN_VALIDATION_SCHEMAS_DIR = "DORSAL_OPEN_VALIDATION_SCHEMAS_DIR"
