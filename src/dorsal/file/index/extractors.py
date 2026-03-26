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

from typing import Any, Callable


RawEAVTuple = tuple[str, Any]
FullEAVTuple = tuple[str, str, str | None, float | None]


ExtractorFunc = Callable[[dict[str, Any]], tuple[list[str], list[RawEAVTuple]]]


def create_eav_tuple(schema_id: str, key: str, value: Any) -> FullEAVTuple | None:
    """Safely routes values to text or numeric EAV columns."""
    if value is None:
        return None
    if isinstance(value, bool):
        return (schema_id, key, str(value).lower(), None)
    if isinstance(value, (int, float)):
        return (schema_id, key, None, float(value))
    return (schema_id, key, str(value), None)


class ExtractorRegistry:
    """
    A lightweight, in-memory registry for annotation schema extractors.

    This uses a decorator pattern to allow third-party developers (using `dorsal model init`)
    to register custom extractors for their own schemas at runtime, without modifying
    core Dorsal source code.
    """

    def __init__(self) -> None:
        self._extractors: dict[str, ExtractorFunc] = {}

    def register(self, schema_id: str) -> Callable[[ExtractorFunc], ExtractorFunc]:
        """Decorator to register an extractor for a specific schema."""

        def decorator(func: ExtractorFunc) -> ExtractorFunc:
            self._extractors[schema_id] = func
            return func

        return decorator

    def extract(self, schema_id: str, rec_dict: dict[str, Any]) -> tuple[list[str], list[FullEAVTuple]]:
        """Runs universal extraction rules, followed by the schema-specific extractor."""
        fts_texts: list[str] = []
        eav_attributes: list[FullEAVTuple] = []

        def add_attr(key: str, value: Any) -> None:
            tup = create_eav_tuple(schema_id, key, value)
            if tup:
                eav_attributes.append(tup)

        if "producer" in rec_dict:
            add_attr("producer", rec_dict["producer"])

        if "attributes" in rec_dict and isinstance(rec_dict["attributes"], dict):
            for k, v in rec_dict["attributes"].items():
                add_attr(k, v)

        if schema_id in self._extractors:
            spec_fts, spec_eav = self._extractors[schema_id](rec_dict)
            fts_texts.extend(spec_fts)

            for key, val in spec_eav:
                tup = create_eav_tuple(schema_id, key, val)
                if tup:
                    eav_attributes.append(tup)

        return fts_texts, eav_attributes


registry = ExtractorRegistry()


@registry.register("open/audio-transcription")
def _extract_audio(rec: dict[str, Any]) -> tuple[list[str], list[RawEAVTuple]]:
    fts: list[str] = []
    eav: list[RawEAVTuple] = []
    if "text" in rec:
        fts.append(rec["text"])
    for seg in rec.get("segments", []):
        if isinstance(seg, dict) and "text" in seg:
            fts.append(seg["text"])
    eav.append(("language", rec.get("language")))
    eav.append(("track_id", rec.get("track_id")))
    return fts, eav


@registry.register("open/classification")
def _extract_classification(rec: dict[str, Any]) -> tuple[list[str], list[RawEAVTuple]]:
    fts: list[str] = []
    eav: list[RawEAVTuple] = []
    eav.append(("target", rec.get("target")))
    for label_obj in rec.get("labels", []):
        if isinstance(label_obj, dict):
            eav.append(("label", label_obj.get("label")))
    return fts, eav


@registry.register("open/document-extraction")
def _extract_doc(rec: dict[str, Any]) -> tuple[list[str], list[RawEAVTuple]]:
    fts: list[str] = []
    eav: list[RawEAVTuple] = []
    for block in rec.get("blocks", []):
        if isinstance(block, dict) and "text" in block:
            fts.append(block["text"])
    return fts, eav


@registry.register("open/entity-extraction")
def _extract_entity(rec: dict[str, Any]) -> tuple[list[str], list[RawEAVTuple]]:
    fts: list[str] = []
    eav: list[RawEAVTuple] = []
    for entity in rec.get("entities", []):
        if isinstance(entity, dict):
            if "text" in entity:
                fts.append(entity["text"])
            if "definition" in entity:
                fts.append(entity["definition"])
            eav.append(("label", entity.get("label")))
            eav.append(("concept", entity.get("concept")))
            eav.append(("value", entity.get("value")))
    return fts, eav


@registry.register("open/generic")
def _extract_generic(rec: dict[str, Any]) -> tuple[list[str], list[RawEAVTuple]]:
    fts: list[str] = []
    eav: list[RawEAVTuple] = []
    if "description" in rec:
        fts.append(rec["description"])
    data_obj = rec.get("data", {})
    if isinstance(data_obj, dict):
        for k, v in data_obj.items():
            eav.append((k, v))
    return fts, eav


@registry.register("open/geolocation")
def _extract_geo(rec: dict[str, Any]) -> tuple[list[str], list[RawEAVTuple]]:
    fts: list[str] = []
    eav: list[RawEAVTuple] = []
    props = rec.get("properties", {})
    if isinstance(props, dict) and props:
        eav.append(("camera_make", props.get("camera_make")))
        eav.append(("camera_model", props.get("camera_model")))
    return fts, eav


@registry.register("open/llm-output")
def _extract_llm(rec: dict[str, Any]) -> tuple[list[str], list[RawEAVTuple]]:
    fts: list[str] = []
    eav: list[RawEAVTuple] = []
    if "prompt" in rec:
        fts.append(rec["prompt"])
    if "response_data" in rec:
        fts.append(str(rec["response_data"]))
    eav.append(("model", rec.get("model")))
    eav.append(("language", rec.get("language")))
    return fts, eav


@registry.register("open/object-detection")
def _extract_obj(rec: dict[str, Any]) -> tuple[list[str], list[RawEAVTuple]]:
    fts: list[str] = []
    eav: list[RawEAVTuple] = []
    for obj in rec.get("objects", []):
        if isinstance(obj, dict):
            eav.append(("label", obj.get("label")))
    return fts, eav


@registry.register("open/regression")
def _extract_regression(rec: dict[str, Any]) -> tuple[list[str], list[RawEAVTuple]]:
    fts: list[str] = []
    eav: list[RawEAVTuple] = []
    eav.append(("target", rec.get("target")))
    eav.append(("unit", rec.get("unit")))
    for point in rec.get("points", []):
        if isinstance(point, dict):
            eav.append(("value", point.get("value")))
    return fts, eav


@registry.register("dorsal/arxiv")
def _extract_arxiv(rec: dict[str, Any]) -> tuple[list[str], list[RawEAVTuple]]:
    fts: list[str] = []
    eav: list[RawEAVTuple] = []
    if "title" in rec:
        fts.append(rec["title"])
    if "abstract" in rec:
        fts.append(rec["abstract"])
    for author in rec.get("authors", []):
        fts.append(author)
        eav.append(("author", author))
    for category in rec.get("categories", []):
        eav.append(("category", category))
    eav.append(("arxiv_id", rec.get("arxiv_id")))
    eav.append(("doi", rec.get("doi")))
    eav.append(("journal_ref", rec.get("journal_ref")))
    return fts, eav
