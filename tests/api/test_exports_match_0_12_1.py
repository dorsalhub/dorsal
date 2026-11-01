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

import json
import warnings
from pathlib import Path

import pytest

from dorsal.api.adapters import export_record, parse_file

RECORDED = json.loads((Path(__file__).parents[1] / "data" / "expected" / "exports-0.12.1.json").read_text("utf-8"))

THEME_COMMENTS = [
    ("/* Dorsal" + "Hub Light Theme */", "/* Light Theme */"),
    ("/* Dorsal" + "Hub Dark Theme */", "/* Dark Theme */"),
    ('content="dorsal' + '-adapters"', 'content="oatschema-adapters"'),
]
SCHEMAS = {"audio": "open/audio-transcription", "document": "open/document-extraction"}


def _expected(case_id: str) -> dict:
    expected = {key: RECORDED["cases"][case_id][key] for key in ("out", "err")}
    if expected["out"]:
        for old, new in THEME_COMMENTS:
            expected["out"] = expected["out"].replace(old, new)
    return expected


def _run(case_id: str) -> dict:
    kind, *parts = case_id.split("|")
    if kind == "filesushi":
        record = RECORDED["pdf_record" if parts[0] == "valid.pdf" else "image_only_pdf_record"]
        if parts[1] == "html":
            layout, style, fragment = parts[2], parts[3], parts[4] == "True"
            call = lambda: export_record(  # noqa: E731
                record, "open/document-extraction", "html", layout=layout, style=style, fragment=fragment
            )
        else:
            frontmatter = parts[2] == "frontmatter=True"
            call = lambda: export_record(record, "open/document-extraction", "md", include_frontmatter=frontmatter)  # noqa: E731
    elif kind == "export":
        spec = RECORDED["cases"][case_id]["call"]
        record = RECORDED["oats_fixtures"][spec["fixture"]]
        schema = SCHEMAS[spec["fixture"].split("-")[0]]
        call = lambda: export_record(  # noqa: E731
            record, schema, spec["format"], schema_version="0.5.0", **spec["options"]
        )
    elif kind == "parse":
        spec = RECORDED["cases"][case_id]["call"]
        record = RECORDED["oats_fixtures"][spec["fixture"]]
        call = lambda: json.dumps(  # noqa: E731
            parse_file(
                export_record(record, "open/audio-transcription", spec["format"], validate=False),
                "open/audio-transcription",
                spec["format"],
            ),
            sort_keys=True,
        )
    elif kind == "pdf-record":
        spec = RECORDED["cases"][case_id]["call"]
        record = RECORDED["pdf_record" if spec["record"] == "valid.pdf" else "image_only_pdf_record"]
        call = lambda: export_record(  # noqa: E731
            record, "document-extraction", spec["format"], schema_version=spec["schema_version"]
        )
    elif kind == "arxiv":
        record = RECORDED["arxiv_records"][int(parts[0])]
        options = {"[]": {}, "['validate']": {"validate": False}, "['unknown_option']": {"unknown_option": 1}}[parts[2]]
        call = lambda: export_record(record, "dorsal/arxiv", parts[1], **options)  # noqa: E731
    else:
        record = RECORDED["arxiv_records"][int(parts[0])]
        call = lambda: json.dumps(  # noqa: E731
            parse_file(export_record(record, "dorsal/arxiv", "md"), "dorsal/arxiv", "md"), sort_keys=True
        )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            return {"out": call(), "err": None}
        except Exception as err:
            cause = err.__cause__
            while cause is not None and cause.__cause__ is not None:
                cause = cause.__cause__
            return {"out": None, "err": f"{type(err).__name__}<-{type(cause).__name__ if cause else '-'}"}


UNCHANGED = sorted(k for k, v in RECORDED["cases"].items() if "documented_change" not in v)
DOCUMENTED = sorted(k for k, v in RECORDED["cases"].items() if "documented_change" in v)


@pytest.mark.parametrize("case_id", UNCHANGED)
def test_export_matches_0_12_1(case_id):
    assert _run(case_id) == _expected(case_id)


@pytest.mark.parametrize("case_id", DOCUMENTED)
def test_documented_changes_differ_from_0_12_1(case_id):
    result = _run(case_id)

    assert result["err"] is None, RECORDED["cases"][case_id]["documented_change"]
    assert result != _expected(case_id), RECORDED["cases"][case_id]["documented_change"]


def test_recording_covers_every_kind_of_case():
    kinds = {case_id.split("|")[0] for case_id in RECORDED["cases"]}

    assert kinds == {"arxiv", "arxiv-parse", "export", "filesushi", "parse", "pdf-record"}
    assert len(RECORDED["cases"]) == 305
    assert len(DOCUMENTED) == 31
