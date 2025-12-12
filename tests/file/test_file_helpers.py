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


import pytest
import datetime
from dorsal.file.helpers import (
    build_regression_point,
    build_regression_record,
    build_single_point_regression_record,
    build_classification_record,
    build_embedding_record,
    build_llm_output_record,
    build_location_record,
    build_transcription_record,
    build_generic_record,
)


def test_build_regression_point_minimal():
    """Test building a point with just a value."""
    result = build_regression_point(value=42.0)
    assert result == {"value": 42.0}


def test_build_regression_point_null_value():
    """Test building a point with None value (e.g. missing sensor data)."""
    result = build_regression_point(value=None, attributes={"status": "missing"})
    assert result == {"value": None, "attributes": {"status": "missing"}}


def test_build_regression_point_full():
    """Test building a point with all optional fields."""
    dt = datetime.datetime(2025, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)

    result = build_regression_point(
        value=100.5,
        statistic="mean",
        quantile_level=None,  # Should be ignored if None
        interval_lower=95.0,
        interval_upper=105.0,
        score=0.98,
        timestamp=dt,
        attributes={"source": "sensor_1"},
    )

    assert result == {
        "value": 100.5,
        "statistic": "mean",
        "interval_lower": 95.0,
        "interval_upper": 105.0,
        "score": 0.98,
        "timestamp": "2025-01-01T12:00:00+00:00",
        "attributes": {"source": "sensor_1"},
    }


def test_build_regression_point_quantile():
    """Test quantile specific logic."""
    result = build_regression_point(value=50, statistic="quantile", quantile_level=0.95)
    assert result == {"value": 50, "statistic": "quantile", "quantile_level": 0.95}


def test_build_regression_record_manual_points():
    """
    Test the base `build_regression_record` which now expects a list of points.
    This simulates the 'Time-Series' use case.
    """
    p1 = build_regression_point(value=10.0, timestamp="2025-01-01")
    p2 = build_regression_point(value=11.0, timestamp="2025-01-02")

    result = build_regression_record(points=[p1, p2], target="temperature", unit="celsius")

    assert result["target"] == "temperature"
    assert result["unit"] == "celsius"
    assert len(result["points"]) == 2
    assert result["points"][0]["value"] == 10.0
    assert result["points"][1]["value"] == 11.0


def test_build_single_point_regression_record():
    """
    Test the convenience wrapper `build_single_point_regression_record`.
    This simulates the 'Single Prediction' use case.
    """
    dt = datetime.datetime(2025, 1, 1, 12, 0, 0)

    result = build_single_point_regression_record(
        value=0.87, target="model_confidence", unit="probability", statistic="mean", score=1.0, timestamp=dt
    )

    # Check Root fields
    assert result["target"] == "model_confidence"
    assert result["unit"] == "probability"

    # Check Point fields (Should be wrapped in a list of 1)
    assert len(result["points"]) == 1
    point = result["points"][0]
    assert point["value"] == 0.87
    assert point["statistic"] == "mean"
    assert point["score"] == 1.0
    assert point["timestamp"] == dt.isoformat()


# --- Classification Tests ---


def test_build_classification_record_strings():
    """Test converting string list to label objects."""
    result = build_classification_record(labels=["cat", "dog"], vocabulary=["cat", "dog", "bird"])
    assert result["vocabulary"] == ["cat", "dog", "bird"]
    assert result["labels"] == [{"label": "cat"}, {"label": "dog"}]


def test_build_classification_record_dicts():
    """Test passing dictionaries with scores."""
    labels = [{"label": "cat", "score": 0.9}, {"label": "dog", "score": 0.1}]
    result = build_classification_record(labels=labels, score_explanation="Probability")
    assert result["labels"] == labels
    assert result["score_explanation"] == "Probability"


# --- Embedding Tests ---


def test_build_embedding_record():
    vector = [0.1, 0.2, 0.3]
    result = build_embedding_record(vector=vector, model="CLIP")

    assert result["vector"] == vector
    assert result["model"] == "CLIP"


# --- LLM Output Tests ---


def test_build_llm_output_record():
    result = build_llm_output_record(
        model="gpt-4",
        response_data="Hello world",
        prompt="Say hello",
        language="eng",
        score=1.0,
        generation_params={"temperature": 0.7},
        generation_metadata={"finish_reason": "stop"},
    )

    assert result["model"] == "gpt-4"
    assert result["response_data"] == "Hello world"
    assert result["prompt"] == "Say hello"
    assert result["language"] == "eng"
    assert result["score"] == 1.0
    assert result["generation_params"] == {"temperature": 0.7}
    assert result["generation_metadata"] == {"finish_reason": "stop"}


# --- Geolocation Tests ---


def test_build_location_record():
    result = build_location_record(
        longitude=-0.1278,
        latitude=51.5074,
        timestamp="2025-01-01T12:00:00Z",
        camera_make="Canon",
        camera_model="EOS 5D",
    )

    assert result["type"] == "Feature"
    assert result["geometry"]["type"] == "Point"
    assert result["geometry"]["coordinates"] == [-0.1278, 51.5074]

    props = result["properties"]
    assert props["timestamp"] == "2025-01-01T12:00:00Z"
    assert props["camera_make"] == "Canon"
    assert props["camera_model"] == "EOS 5D"


# --- Transcription Tests ---


def test_build_transcription_record():
    result = build_transcription_record(text="Hello world", language="eng", track_id=1)
    assert result["text"] == "Hello world"
    assert result["language"] == "eng"
    assert result["track_id"] == 1


# --- Generic Tests ---


def test_build_generic_record():
    data = {"key": "value", "count": 1}
    result = build_generic_record(data=data, description="Test data")
    assert result["data"] == data
    assert result["description"] == "Test data"
