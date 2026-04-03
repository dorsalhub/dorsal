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
    Registry for annotation schema extractors with strict, global EAV type enforcement.
    """

    def __init__(self) -> None:
        self._extractors: dict[str, ExtractorFunc] = {}
        self._numeric_keys: set[str] = set()
        self._text_keys: set[str] = set()

    def register(
        self, schema_id: str, numeric_keys: list[str] | None = None, text_keys: list[str] | None = None
    ) -> Callable[[ExtractorFunc], ExtractorFunc]:
        """Decorator to register an extractor and strictly declare its key types."""
        num_keys = set(numeric_keys or [])
        txt_keys = set(text_keys or [])

        overlap = num_keys.intersection(txt_keys)
        if overlap:
            raise ValueError(f"Schema '{schema_id}' declares keys as both numeric and text: {overlap}")

        for k in num_keys:
            if k in self._text_keys:
                raise ValueError(
                    f"Global EAV Type Conflict: Key '{k}' is already registered as text, but '{schema_id}' is declaring it as numeric."
                )
            self._numeric_keys.add(k)

        for k in txt_keys:
            if k in self._numeric_keys:
                raise ValueError(
                    f"Global EAV Type Conflict: Key '{k}' is already registered as numeric, but '{schema_id}' is declaring it as text."
                )
            self._text_keys.add(k)

        def decorator(func: ExtractorFunc) -> ExtractorFunc:
            self._extractors[schema_id] = func
            return func

        return decorator

    def is_numeric_key(self, key: str) -> bool:
        """Single source of truth for query routing."""
        return key in self._numeric_keys

    def create_eav_tuple(self, schema_id: str, key: str, value: Any) -> FullEAVTuple | None:
        """Safely routes values to columns, enforcing global types."""
        if value is None:
            return None

        if key in self._numeric_keys:
            try:
                return (schema_id, key, None, float(value))
            except (ValueError, TypeError) as err:
                raise TypeError(
                    f"EAV Type Error: Key '{key}' is declared as numeric, but received non-numeric value '{value}' in schema '{schema_id}'."
                ) from err

        if key not in self._text_keys:
            self._text_keys.add(key)

        if isinstance(value, bool):
            return (schema_id, key, str(value).lower(), None)

        return (schema_id, key, str(value), None)

    def extract(self, schema_id: str, rec_dict: dict[str, Any]) -> tuple[list[str], list[FullEAVTuple]]:
        fts_texts: list[str] = []
        eav_attributes: list[FullEAVTuple] = []

        def add_attr(key: str, value: Any) -> None:
            tup = self.create_eav_tuple(schema_id, key, value)
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
                tup = self.create_eav_tuple(schema_id, key, val)
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


@registry.register("open/regression", numeric_keys=["regression_value"])
def _extract_regression(rec: dict[str, Any]) -> tuple[list[str], list[RawEAVTuple]]:
    fts: list[str] = []
    eav: list[RawEAVTuple] = []
    eav.append(("target", rec.get("target")))
    eav.append(("unit", rec.get("unit")))
    for point in rec.get("points", []):
        if isinstance(point, dict):
            eav.append(("regression_value", point.get("value")))
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


@registry.register("file/pdf", numeric_keys=["page_count"])
def _extract_file_pdf(rec: dict[str, Any]) -> tuple[list[str], list[RawEAVTuple]]:
    fts: list[str] = []
    eav: list[RawEAVTuple] = []

    for text_field in ["title", "author", "subject"]:
        if rec.get(text_field):
            fts.append(rec[text_field])

    for kw in rec.get("keywords", []):
        fts.append(kw)
        eav.append(("keyword", kw))

    if rec.get("author"):
        eav.append(("author", rec["author"]))
    if rec.get("creator"):
        eav.append(("creator", rec["creator"]))
    if rec.get("page_count") is not None:
        eav.append(("page_count", rec["page_count"]))
    if rec.get("version"):
        eav.append(("version", rec["version"]))

    return fts, eav


@registry.register("file/ebook")
def _extract_file_ebook(rec: dict[str, Any]) -> tuple[list[str], list[RawEAVTuple]]:
    fts: list[str] = []
    eav: list[RawEAVTuple] = []

    for text_field in ["title", "publisher", "description"]:
        val = rec.get(text_field)
        if val:
            fts.append(val)
            if text_field == "title":
                eav.append(("title", val))

    for author in rec.get("authors", []):
        fts.append(author)
        eav.append(("author", author))

    for contributor in rec.get("contributors", []):
        fts.append(contributor)
        eav.append(("contributor", contributor))

    for subject in rec.get("subjects", []):
        fts.append(subject)
        eav.append(("subject", subject))

    if rec.get("publisher"):
        eav.append(("publisher", rec["publisher"]))
    if rec.get("language"):
        eav.append(("language", rec["language"]))
    if rec.get("isbn"):
        fts.append(rec["isbn"])
        eav.append(("isbn", rec["isbn"]))

    return fts, eav


@registry.register("file/mediainfo", numeric_keys=["width", "height", "duration", "bitrate", "framerate", "channels"])
def _extract_file_mediainfo(rec: dict[str, Any]) -> tuple[list[str], list[RawEAVTuple]]:
    fts: list[str] = []
    eav: list[RawEAVTuple] = []

    text_fields = ["Title", "Album", "Performer", "Composer", "Director", "Genre", "Description", "Synopsis", "Comment"]
    for field in text_fields:
        val = rec.get(field)
        if val:
            fts.append(str(val))

    if rec.get("Encoded_Application_String"):
        fts.append(str(rec["Encoded_Application_String"]))
    if rec.get("Format_Info"):
        fts.append(str(rec["Format_Info"]))
    if rec.get("CodecID"):
        fts.append(str(rec["CodecID"]))

    video_track = rec.get("Video", [])
    audio_track = rec.get("Audio", [])

    if isinstance(video_track, list) and video_track:
        video_track = video_track[0]
    if isinstance(audio_track, list) and audio_track:
        audio_track = audio_track[0]

    if not isinstance(video_track, dict):
        video_track = {}
    if not isinstance(audio_track, dict):
        audio_track = {}

    width = rec.get("Width") or video_track.get("Width")
    if width is not None:
        eav.append(("width", width))

    height = rec.get("Height") or video_track.get("Height")
    if height is not None:
        eav.append(("height", height))

    format_str = rec.get("Format_String") or video_track.get("Format_String")
    if format_str:
        eav.append(("format", format_str))

    codec = rec.get("CodecID") or rec.get("Format_Info") or video_track.get("CodecID")
    if codec:
        eav.append(("codec", codec))

    duration = rec.get("Duration") or video_track.get("Duration") or audio_track.get("Duration")
    if duration is not None:
        eav.append(("duration", duration))

    framerate = rec.get("FrameRate") or video_track.get("FrameRate")
    if framerate is not None:
        eav.append(("framerate", framerate))

    bitrate = (
        rec.get("OverallBitRate") or rec.get("BitRate") or video_track.get("BitRate") or audio_track.get("BitRate")
    )
    if bitrate is not None:
        eav.append(("bitrate", bitrate))

    channels = rec.get("Channels") or audio_track.get("Channels")
    if channels is not None:
        eav.append(("channels", channels))

    encoder = rec.get("Encoded_Application_String")
    if encoder:
        eav.append(("encoder", encoder))

    return fts, eav


@registry.register(
    "file/office",
    numeric_keys=[
        "revision",
        "page_count",
        "word_count",
        "char_count",
        "paragraph_count",
        "slide_count",
        "row_count",
        "column_count",
    ],
)
def _extract_file_office_document(rec: dict[str, Any]) -> tuple[list[str], list[RawEAVTuple]]:
    fts: list[str] = []
    eav: list[RawEAVTuple] = []

    for field in ["title", "subject", "author", "last_modified_by", "application_name", "template"]:
        val = rec.get(field)
        if val:
            fts.append(str(val))
            eav.append((field, val))

    for kw in rec.get("keywords", []):
        fts.append(str(kw))
        eav.append(("keyword", kw))

    if rec.get("language"):
        eav.append(("language", rec["language"]))
    if rec.get("revision") is not None:
        eav.append(("revision", rec["revision"]))
    if rec.get("is_password_protected") is not None:
        eav.append(("is_password_protected", rec["is_password_protected"]))
    if rec.get("has_comments") is not None:
        eav.append(("has_comments", rec["has_comments"]))

    custom = rec.get("custom_properties", {})
    if isinstance(custom, dict):
        for k, v in custom.items():
            fts.append(str(v))
            eav.append((str(k), v))

    word = rec.get("word", {})
    if isinstance(word, dict) and word:
        for k in ["page_count", "word_count", "char_count", "paragraph_count"]:
            if word.get(k) is not None:
                eav.append((k, word[k]))
        if word.get("has_track_changes") is not None:
            eav.append(("has_track_changes", word["has_track_changes"]))

    excel = rec.get("excel", {})
    if isinstance(excel, dict) and excel:
        if excel.get("has_macros") is not None:
            eav.append(("has_macros", excel["has_macros"]))

        for sheet_name in excel.get("sheet_names", []):
            fts.append(str(sheet_name))

        sheets = excel.get("sheets", [])
        max_rows, max_cols = 0, 0
        if isinstance(sheets, list):
            for sheet in sheets:
                if isinstance(sheet, dict):
                    fts.append(str(sheet.get("name", "")))
                    max_rows = max(max_rows, sheet.get("row_count") or 0)
                    max_cols = max(max_cols, sheet.get("column_count") or 0)

                    for col in sheet.get("column_names", []):
                        fts.append(str(col))

        if max_rows > 0:
            eav.append(("row_count", max_rows))
        if max_cols > 0:
            eav.append(("column_count", max_cols))

    ppt = rec.get("powerpoint", {})
    if isinstance(ppt, dict) and ppt:
        if ppt.get("slide_count") is not None:
            eav.append(("slide_count", ppt["slide_count"]))
        for master in ppt.get("slide_master_names", []):
            fts.append(str(master))

    return fts, eav
