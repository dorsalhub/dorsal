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

import importlib

import pytest

IMPORT_CONTRACT: dict[str, dict[str, list[str]]] = {
    "DorsalHub": {
        "dorsal.file.validators.file_record": [
            "FileRecord",
            "FileRecordStrict",
            "Annotation",
            "AnnotationGroup",
            "AnnotationGroupInfo",
            "AnnotationStub",
            "AnnotationSource",
            "FileTag",
            "NewFileTag",
            "FileUrl",
            "FileRecordDateTime",
        ],
        "dorsal.file.sharding": ["reassemble_record", "build_annotation_or_annotationgroup"],
        "dorsal.common.validators": [
            "String64",
            "String128",
            "String256",
            "String1024",
            "String4096",
            "TString64",
            "TString255",
            "TString256",
        ],
        "dorsal.common.validators.strings": ["String256", "String1024"],
        "dorsal.common.model": ["AnnotationWebSource", "scrub_pii_from_model"],
        "dorsal.common.constants": ["CORE_FILE_DATASETS"],
        "dorsal.client.validators": ["FileUrlRequest"],
        "dorsal.file.utils.hashes": [
            "parse_validate_hash",
            "RX_LOWERCASE_HEX_32",
            "RX_LOWERCASE_HEX_40",
            "RX_LOWERCASE_HEX_64",
        ],
        "dorsal.file.utils.size": ["human_filesize", "parse_filesize"],
        "dorsal.file.integrity": ["normalize_record_privacy"],
        "dorsal.file.permissions": ["is_permitted_public_media_type"],
        "dorsal.file.validators.base": ["FileCoreValidationModel", "FileCoreValidationModelStrict"],
        "dorsal.file.validators.ebook": ["EbookValidationModel"],
        "dorsal.file.validators.mediainfo": ["MediaInfoValidationModel", "MediaInfoTrack"],
        "dorsal.file.validators.office_document": ["OfficeDocumentValidationModel"],
        "dorsal.file.validators.pdf": ["PDFValidationModel"],
        "dorsal": ["LocalFile"],
        "dorsal.client": ["DorsalClient"],
    },
    "dorsal-worker": {
        "dorsal": ["DorsalClient", "LocalFile"],
        "dorsal.file.utils.infer_mediatype": ["get_media_type"],
        "dorsal.file.permissions": ["is_permitted_public_media_type"],
        "dorsal.common.exceptions": ["TaggingError"],
    },
    "FileSushi": {
        "dorsal.file.model_runner": ["run_model"],
        "dorsal.api.adapters": ["export_record"],
    },
    "pdf-extractor": {
        "dorsal.file.preprocessing.pdf": ["extract_pdf_layout_per_mille", "ocr_extract_pdf_text"],
        "dorsal.common.model": ["AnnotationModel"],
    },
    "dorsal-whisper": {
        "dorsal": ["AnnotationModel"],
        "dorsal.common.language": ["normalize_language_alpha3"],
        "dorsal.testing": ["run_model"],
    },
    "dorsalhub-adapters": {
        "dorsal.file.validators.open_schema": ["get_open_schema_validator"],
        "dorsal.common.validators.json_schema": ["get_json_schema_validator"],
        "dorsal.api.dataset": ["get_dataset_schema"],
    },
}

CASES = [
    pytest.param(module, name, id=f"{consumer}: from {module} import {name}")
    for consumer, modules in IMPORT_CONTRACT.items()
    for module, names in modules.items()
    for name in names
]


@pytest.mark.parametrize("module, name", CASES)
def test_downstream_import_still_works(module, name):
    imported = importlib.import_module(module)

    assert getattr(imported, name, None) is not None, f"{module}.{name} is gone"
