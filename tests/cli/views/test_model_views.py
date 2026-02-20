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

import io
import pytest
import re

from rich.console import Console


from dorsal.cli.views.model import create_model_result_panel
from dorsal.cli.themes.palettes import DEFAULT_PALETTE
from dorsal.file.validators.file_record import Annotation, AnnotationGroup, GenericFileAnnotation
from dorsal.common.model import AnnotationModelSource


DUMMY_SOURCE = AnnotationModelSource(id="test-model", version="1.0.0")


def render_to_string(renderable) -> str:
    """
    Renders a Rich object to a plain string to allow
    for text-based assertions on content.
    """
    console = Console(width=100, file=io.StringIO(), color_system=None)
    console.print(renderable)
    return console.file.getvalue()


def create_real_annotation(data: dict | None) -> Annotation:
    """Constructs a real Pydantic Annotation object."""

    return Annotation(record=data, source=DUMMY_SOURCE, private=False)


def test_render_classification():
    data = {
        "target": "sentiment",
        "labels": [
            {"label": "positive", "score": 0.95},
            {"label": "neutral", "score": 0.04},
            {"label": "negative", "score": 0.01},
        ],
    }
    ann = create_real_annotation(data)
    panel = create_model_result_panel(ann, "sentiment-model", "test.txt", DEFAULT_PALETTE)

    output = render_to_string(panel)
    assert "Classification Result" in str(panel.title)
    assert "positive" in output
    assert "0.9500" in output


def test_render_llm_output():
    data = {
        "model": "gpt-4o",
        "prompt": "What is 2+2?",
        "response_data": "The answer is 4.",
        "generation_metadata": {"usage": {"total_tokens": 10, "prompt_tokens": 5, "completion_tokens": 5}},
    }
    ann = create_real_annotation(data)
    panel = create_model_result_panel(ann, "llm-task", "query.txt", DEFAULT_PALETTE)

    output = render_to_string(panel)
    assert "LLM Output Result" in str(panel.title)
    assert "The answer is 4" in output
    assert "Tokens: 10" in output


def test_render_entity_extraction():
    data = {
        "entities": [
            {"label": "PERSON", "text": "John Doe", "score": 0.99, "value": "John Doe"},
            {"label": "GPE", "text": "London", "score": 0.85},
        ]
    }
    ann = create_real_annotation(data)
    panel = create_model_result_panel(ann, "ner-model", "doc.pdf", DEFAULT_PALETTE)

    output = render_to_string(panel)
    assert "Entity Extraction Result" in str(panel.title)
    assert "Extracted 2 entities" in output
    assert "John Doe" in output


def normalize_ws(text: str) -> str:
    """Collapses all whitespace (including newlines and non-breaking spaces) into single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def test_render_object_detection():
    data = {
        "objects": [
            {"label": "car", "score": 0.9, "box": {"x": 10, "y": 20, "width": 50, "height": 30}},
            {"label": "tree", "score": 0.7, "polygon": [{"x": 1, "y": 1}, {"x": 2, "y": 2}, {"x": 1, "y": 2}]},
        ],
        "unit": "px",
    }
    ann = create_real_annotation(data)
    panel = create_model_result_panel(ann, "yolo", "image.jpg", DEFAULT_PALETTE)

    output = normalize_ws(render_to_string(panel))
    assert "Object Detection Result" in str(panel.title)
    assert "Found 2 objects" in output


def test_render_embedding():
    data = {
        "model": "text-embedding-3-small",
        "vector": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        "target": "document_content",
    }
    ann = create_real_annotation(data)
    panel = create_model_result_panel(ann, "embedder", "data.json", DEFAULT_PALETTE)

    output = normalize_ws(render_to_string(panel))
    assert "Embedding Result" in str(panel.title)
    assert "Dimensions 10" in output
    assert "0.1000" in output


def test_render_audio_transcription():
    data = {
        "language": "eng",
        "text": "Hello world.",
        "segments": [{"start_time": 0.0, "end_time": 1.5, "text": "Hello", "speaker": {"id": "spk1", "name": "Alice"}}],
    }
    ann = create_real_annotation(data)
    panel = create_model_result_panel(ann, "whisper", "audio.mp3", DEFAULT_PALETTE)

    output = render_to_string(panel)
    assert "Audio Transcription Result" in str(panel.title)
    assert "Hello world" in output
    assert "Alice" in output


def test_render_document_extraction():
    data = {
        "extraction_type": "text",
        "blocks": [
            {"block_type": "text", "text": "Paragraph 1", "page_number": 1, "id": "uuid-1"},
            {"block_type": "text", "text": "Paragraph 2", "page_number": 1, "id": "uuid-2"},
        ],
    }
    ann = create_real_annotation(data)
    panel = create_model_result_panel(ann, "ocr", "scan.pdf", DEFAULT_PALETTE)

    output = normalize_ws(render_to_string(panel))
    assert "Document Extraction Result" in str(panel.title)
    assert "Paragraph 1" in output
    assert "text: 2" in output


def test_render_regression():
    data = {
        "target": "temperature",
        "unit": "C",
        "points": [{"value": 22.5, "timestamp": "2026-01-01T12:00:00Z", "statistic": "mean"}],
    }
    ann = create_real_annotation(data)
    panel = create_model_result_panel(ann, "weather-model", "sensor.log", DEFAULT_PALETTE)

    output = normalize_ws(render_to_string(panel))
    assert "Regression Result" in str(panel.title)
    assert "Regression Target: temperature" in output
    assert "22.5000" in output


def test_render_geolocation():
    data = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [-0.1278, 51.5074]},
        "properties": {"city": "London", "country": "UK"},
    }
    ann = create_real_annotation(data)
    panel = create_model_result_panel(ann, "geocoder", "loc.txt", DEFAULT_PALETTE)

    output = normalize_ws(render_to_string(panel))
    assert "Geolocation Result" in str(panel.title)
    assert "Coordinates [-0.1278, 51.5074]" in output
    assert "city: London" in output


def test_render_generic():
    data = {"description": "Custom Statistics", "data": {"mean": 10, "std": 2, "count": 100}}
    ann = create_real_annotation(data)
    panel = create_model_result_panel(ann, "stat-model", "data.csv", DEFAULT_PALETTE)

    output = normalize_ws(render_to_string(panel))
    assert "Generic Data Result" in str(panel.title)
    assert "Custom Statistics" in output
    assert "mean" in output
    assert "10" in output


def test_render_annotation_group():
    data1 = {"vector": [1, 2]}
    data2 = {"vector": [3, 4]}
    ann1 = create_real_annotation(data1)
    ann2 = create_real_annotation(data2)
    group = AnnotationGroup(annotations=[ann1, ann2])

    panel = create_model_result_panel(group, "multi-embed", "file.txt", DEFAULT_PALETTE)

    output = normalize_ws(render_to_string(panel))
    assert "Embedding Result (Group of 2)" in str(panel.title)
    assert "Dimensions 2" in output


def test_render_fallback_raw_output():
    data = {"unexpected_field": "some_value", "random": 123}
    ann = create_real_annotation(data)
    panel = create_model_result_panel(ann, "unknown-model", "test.bin", DEFAULT_PALETTE)

    output = normalize_ws(render_to_string(panel))
    assert "Raw Output Result" in str(panel.title)
    assert "unexpected_field" in output


def test_render_empty_data():
    ann = create_real_annotation(None)
    panel = create_model_result_panel(ann, "empty-model", "empty.txt", DEFAULT_PALETTE)

    output = normalize_ws(render_to_string(panel))
    assert "Empty Result" in str(panel.title)
    assert "No record data returned" in output


def test_panel_metadata_display():
    data = {"vector": [1]}
    ann = create_real_annotation(data)
    panel = create_model_result_panel(ann, "TARGET_ID", "FILE_NAME.ext", DEFAULT_PALETTE)

    output = normalize_ws(render_to_string(panel))
    assert "TARGET_ID" in output
    assert "FILE_NAME.ext" in output


def test_render_arxiv():
    data = {
        "title": "   Deep Learning   \nFor Cats",
        "arxiv_id": "2104.12345",
        "version": "v2",
        "authors": ["Alice Smith", "Bob Jones"],
        "abstract": "This is a detailed abstract about cats and neural networks.",
        "url": "https://arxiv.org/abs/2104.12345",
        "categories": ["cs.AI", "cs.CV"],
        "doi": "10.1000/xyz123",
        "journal_ref": "Journal of Feline AI",
        "license": "CC-BY-SA 4.0",
    }
    ann = create_real_annotation(data)
    panel = create_model_result_panel(ann, "dorsal/arxiv", "paper.pdf", DEFAULT_PALETTE)

    output = normalize_ws(render_to_string(panel))
    assert "ArXiv Record Result" in str(panel.title)
    assert "Deep Learning For Cats" in output
    assert "2104.12345 (v2)" in output
    assert "Alice Smith, Bob Jones" in output
    assert "This is a detailed abstract" in output
    assert "https://arxiv.org/abs/2104.12345" in output
    assert "cs.AI, cs.CV" in output
