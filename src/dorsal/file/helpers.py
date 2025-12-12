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

from __future__ import annotations
import datetime
import json
import logging
from typing import Any, TypedDict, List, Optional, Union, Dict

logger = logging.getLogger(__name__)

__all__ = [
    "build_classification_record",
    "build_embedding_record",
    "build_generic_record",
    "build_llm_output_record",
    "build_location_record",
    "build_transcription_record",
]


def _validate_attributes(attributes: dict[str, Any]) -> None:
    """
    Validates that an attributes dictionary conforms to the strict schema:
    - Maximum 16 properties.
    - Flat structure (no nested dictionaries or lists).
    - Allowed values: string, number, boolean, null.
    """
    if len(attributes) > 16:
        raise ValueError(f"The 'attributes' object cannot have more than 16 properties. Got {len(attributes)}.")

    for key, value in attributes.items():
        if isinstance(value, (dict, list, tuple, set)):
            raise TypeError(
                f"The 'attributes' object must be flat. Key '{key}' has value of type "
                f"'{type(value).__name__}', which is not allowed."
            )


class ClassificationLabel(TypedDict, total=False):
    """A dictionary for a single classification label."""

    label: str
    score: float
    timestamp: str | datetime.datetime
    attributes: dict[str, Any]


def build_classification_record(
    labels: list[str | ClassificationLabel],
    vocabulary: list[str] | None = None,
    score_explanation: str | None = None,
    vocabulary_url: str | None = None,
) -> dict[str, Any]:
    """
    Builds a valid 'open/classification' annotation record.

    Args:
        labels: A list of simple strings (e.g., ["cat", "dog"]) or
            dictionaries (e.g., [{"label": "cat", "score": 0.95}]).
        vocabulary: Optional list of all possible labels.
        score_explanation: Optional string explaining the 'score' field.
        vocabulary_url: Optional URL pointing to an external vocabulary.

    Returns:
        A dictionary structured to match the 'open/classification' schema.
    """
    processed_labels: list[ClassificationLabel] = []
    if not isinstance(labels, list):
        raise TypeError(f"'labels' must be a list of strings or dictionaries, got {type(labels).__name__}.")

    for item in labels:
        if isinstance(item, str):
            processed_labels.append({"label": item})
        elif isinstance(item, dict):
            if "attributes" in item:
                _validate_attributes(item["attributes"])
            processed_labels.append(item)
        else:
            raise TypeError(
                f"Items in 'labels' list must be a string (str) or a "
                f"dictionary (ClassificationLabel), got {type(item).__name__}."
            )

    if not processed_labels and vocabulary is None and vocabulary_url is None:
        raise ValueError(
            "The 'classification' schema requires 'vocabulary' or 'vocabulary_url' "
            "to be provided when the 'labels' list is empty."
        )

    record_data: dict[str, Any] = {
        "labels": processed_labels,
    }

    if score_explanation is not None:
        record_data["score_explanation"] = score_explanation
    if vocabulary is not None:
        record_data["vocabulary"] = vocabulary
    if vocabulary_url is not None:
        record_data["vocabulary_url"] = vocabulary_url

    return record_data


def build_embedding_record(
    vector: list[float],
    model: str | None = None,
    target: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Builds a valid 'open/embedding' annotation record.

    Args:
        vector: The embedding vector.
        model: Optional name of the model or model used.
        attributes: Optional arbitrary metadata (max 16 items, flat).

    Returns:
        A dictionary structured to match the 'open/embedding' schema.
    """
    record_data: dict[str, Any] = {
        "vector": vector,
    }
    if model is not None:
        record_data["model"] = model
    if target is not None:
        record_data["target"] = target

    if attributes is not None:
        _validate_attributes(attributes)
        record_data["attributes"] = attributes

    return record_data


def build_llm_output_record(
    model: str,
    response_data: str | dict[str, Any],
    prompt: str | None = None,
    language: str | None = None,
    score: float | None = None,
    score_explanation: str | None = None,
    generation_params: dict[str, Any] | None = None,
    generation_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Builds a valid 'open/llm-output' annotation record.

    Args:
        model: The ID or name of the generative model used.
        response_data: The generative output (string or simple dict).
        prompt: Optional prompt provided to the model.
        language: Optional 3-letter ISO-639-3 language code.
        score: Optional confidence or evaluation score [-1, 1].
        score_explanation: Optional explanation of what the score represents.
        generation_params: Optional dict of parameters sent to the API.
        generation_metadata: Optional dict of metadata returned by the API.

    Returns:
        A dictionary structured to match the 'open/llm-output' schema.
    """
    final_response_data: str
    if isinstance(response_data, dict):
        try:
            final_response_data = json.dumps(response_data)
        except TypeError as e:
            raise TypeError(
                f"The 'response_data' dictionary could not be serialized to JSON. "
                f"It may contain non-serializable types. Original error: {e}"
            ) from e
    else:
        final_response_data = response_data

    record_data: dict[str, Any] = {
        "model": model,
        "response_data": final_response_data,
    }

    if prompt is not None:
        record_data["prompt"] = prompt
    if language is not None:
        record_data["language"] = language
    if score is not None:
        record_data["score"] = score
    if score_explanation is not None:
        record_data["score_explanation"] = score_explanation
    if generation_params is not None:
        record_data["generation_params"] = generation_params
    if generation_metadata is not None:
        record_data["generation_metadata"] = generation_metadata

    return record_data


def build_location_record(
    longitude: float,
    latitude: float,
    id: str | int | float | None = None,
    timestamp: str | None = None,
    camera_make: str | None = None,
    camera_model: str | None = None,
    bbox: list[float] | None = None,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Builds a valid 'open/geolocation' record for a simple Point.

    Args:
        longitude: The longitude coordinate.
        latitude: The latitude coordinate.
        id: Optional unique identifier for the feature.
        timestamp: Optional ISO 8601 timestamp.
        camera_make: Optional make of the camera/sensor.
        camera_model: Optional model of the camera/sensor.
        bbox: Optional Bounding Box array (RFC 7946).
        properties: Optional dictionary of additional properties (GeoJSON 'properties').
                   Must not exceed 100 items.

    Returns:
        A dictionary structured to match the 'open/geolocation' schema (GeoJSON Feature).
    """
    feature_properties: dict[str, Any] = {}
    if timestamp is not None:
        feature_properties["timestamp"] = timestamp
    if camera_make is not None:
        feature_properties["camera_make"] = camera_make
    if camera_model is not None:
        feature_properties["camera_model"] = camera_model

    if properties is not None:
        feature_properties.update(properties)

    if len(feature_properties) > 100:
        raise ValueError(f"The 'properties' object cannot have more than 100 items. Got {len(feature_properties)}.")

    record_data: dict[str, Any] = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        "properties": feature_properties if feature_properties else None,
    }

    if id is not None:
        record_data["id"] = id
    if bbox is not None:
        record_data["bbox"] = bbox

    return record_data


def build_transcription_record(
    text: str,
    language: str | None = None,
    track_id: str | int | None = None,
) -> dict[str, Any]:
    """
    Builds a simple 'open/audio-transcription' record.

    Args:
        text: The full transcribed text.
        language: Optional 3-letter ISO-639-3 language code.
        track_id: Optional identifier for the audio track.

    Returns:
        A dictionary structured to match the 'open/audio-transcription' schema.
    """
    record_data: dict[str, Any] = {
        "text": text,
    }
    if language is not None:
        record_data["language"] = language
    if track_id is not None:
        record_data["track_id"] = track_id
    return record_data


def build_generic_record(
    data: dict[str, Union[str, int, float, bool, None]],
    description: str | None = None,
) -> dict[str, Any]:
    """
    Builds a valid 'open/generic' annotation record.

    Args:
        data: A flat dictionary of key-value pairs.
        description: A description of the data (max 256 chars). Can be None.

    Returns:
        A dictionary structured to match the 'open/generic' schema.
    """
    if len(data) > 128:
        raise ValueError(f"The 'data' object cannot have more than 128 items. Got {len(data)}.")

    for key, value in data.items():
        if isinstance(value, (dict, list, tuple, set)):
            raise TypeError(
                f"The 'generic' schema disallows nesting. "
                f"Key '{key}' has value of type '{type(value).__name__}', "
                f"but only str, int, float, bool, or None are allowed."
            )

    record_data: dict[str, Any] = {
        "data": data,
    }

    if description is not None:
        record_data["description"] = description

    return record_data


def build_regression_point(
    value: float | None,
    *,
    statistic: str | None = None,
    quantile_level: float | None = None,
    interval_lower: float | None = None,
    interval_upper: float | None = None,
    score: float | None = None,
    timestamp: str | datetime.datetime | None = None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Constructs a validated dictionary for a single regression data point.

    This helper is designed to be used when building complex datasets (like time-series or
    multi-point forecasts) where you need to generate a list of points before
    wrapping them in a full record.

    Args:
        value (float | None): The predicted or sampled value. Can be `None` to indicate
            a missing value (e.g. sensor failure or scheduled gap).
        statistic (str, optional): The statistical nature of this value.
            Must be one of: `'mean'`, `'median'`, `'mode'`, `'min'`, `'max'`,
            `'quantile'`, `'sample'`.
        quantile_level (float, optional): If `statistic='quantile'`, this defines
            the specific level (e.g., `0.95` for the 95th percentile).
        interval_lower (float, optional): The lower bound of the confidence interval
            or prediction interval.
        interval_upper (float, optional): The upper bound of the confidence interval
            or prediction interval.
        score (float, optional): A quality or confidence score for this specific
            point (0.0 to 1.0).
        timestamp (str | datetime, optional): The specific time this prediction applies to.
            If a `datetime` object is provided, it will be automatically formatted as
            an ISO 8601 string.
        attributes (dict, optional): Arbitrary metadata relevant to this specific point
            (e.g., `{'is_anomaly': True}`).

    Returns:
        dict[str, Any]: A dictionary representing a single regression point, ready
        to be included in the `points` array of an `open/regression` record.

    Examples:
        **1. Basic Point**

        ```python
        p = build_regression_point(value=42.0)
        # {'value': 42.0}
        ```

        **2. Point with Confidence Interval**

        ```python
        p = build_regression_point(
            value=105.5,
            interval_lower=100.0,
            interval_upper=110.0,
            statistic="mean"
        )
        ```

        **3. Building a Time-Series List**

        ```python
        data = [("2025-01-01", 50.0), ("2025-01-02", 55.5)]

        points = [
            build_regression_point(value=price, timestamp=date)
            for date, price in data
        ]
        ```
    """
    point: dict[str, Any] = {"value": value}

    if statistic:
        point["statistic"] = statistic
    if quantile_level is not None:
        point["quantile_level"] = quantile_level
    if interval_lower is not None:
        point["interval_lower"] = interval_lower
    if interval_upper is not None:
        point["interval_upper"] = interval_upper
    if score is not None:
        point["score"] = score
    if timestamp:
        point["timestamp"] = timestamp.isoformat() if hasattr(timestamp, "isoformat") else timestamp
    if attributes:
        point["attributes"] = attributes

    return point


def build_regression_record(
    points: list[dict[str, Any]],
    *,
    target: str | None = None,
    unit: str | None = None,
    producer: str | None = None,
    score_explanation: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Builds a full `open/regression` record from a list of point dictionaries.

    Use this function when you have manually constructed a list of points (e.g.
    using `build_regression_point` in a loop) and want to wrap them in the
    standard record structure with global metadata.

    Args:
        points (list[dict]): A list of point dictionaries.
        target (str, optional): The name of the variable being predicted
            (e.g., 'house_price', 'temperature', 'credit_score').
        unit (str, optional): The unit of measurement (e.g., 'USD', 'celsius', 'kg').
        producer (str, optional): The creator (model, tool, or author) of this
            regression data.
        score_explanation (str, optional): A description of what the `score` field
            represents (e.g., "Model Confidence").
        attributes (dict, optional): Arbitrary metadata relevant to the entire record.

    Returns:
        dict[str, Any]: A complete dictionary valid against the `open/regression` schema.

    Examples:
        **Constructing a Time-Series Record**

        ```python
        # 1. Create points
        points = [
            build_regression_point(value=10, timestamp="2025-01-01"),
            build_regression_point(value=12, timestamp="2025-01-02")
        ]

        # 2. Build record
        record = build_regression_record(
            points=points,
            target="daily_active_users",
            producer="AnalyticsBot v1"
        )
        ```
    """
    record: dict[str, Any] = {"points": points}

    if target:
        record["target"] = target
    if unit:
        record["unit"] = unit
    if producer:
        record["producer"] = producer
    if score_explanation:
        record["score_explanation"] = score_explanation
    if attributes:
        record["attributes"] = attributes

    return record


def build_single_point_regression_record(
    value: float | None,
    *,
    target: str | None = None,
    unit: str | None = None,
    producer: str | None = None,
    score_explanation: str | None = None,
    statistic: str | None = None,
    quantile_level: float | None = None,
    interval_lower: float | None = None,
    interval_upper: float | None = None,
    score: float | None = None,
    timestamp: str | datetime.datetime | None = None,
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Convenience helper to build a full `open/regression` record containing exactly one point.

    This function abstracts away the `points` array structure for the common use case
    of a single scalar prediction or measurement. It combines arguments for both the
    record (e.g. `target`) and the point (e.g. `value`).

    Args:
        value (float | None): The predicted or sampled value.
        target (str, optional): The name of the variable being predicted.
        unit (str, optional): The unit of measurement.
        producer (str, optional): The creator of this data.
        score_explanation (str, optional): Description of the score metric.
        statistic (str, optional): The statistical nature of the value.
        quantile_level (float, optional): Level for quantile statistics.
        interval_lower (float, optional): Lower bound of confidence interval.
        interval_upper (float, optional): Upper bound of confidence interval.
        score (float, optional): Quality score for the point.
        timestamp (str | datetime, optional): Time of the prediction.
        attributes (dict, optional): Attributes for the **point**.

    Returns:
        dict[str, Any]: A complete dictionary valid against the `open/regression` schema,
        containing a single item in the `points` list.

    Examples:
        **Simple Prediction**

        ```python
        record = build_single_point_regression_record(
            target="credit_score",
            value=750,
            statistic="mean"
        )
        ```
    """

    point = build_regression_point(
        value=value,
        statistic=statistic,
        quantile_level=quantile_level,
        interval_lower=interval_lower,
        interval_upper=interval_upper,
        score=score,
        timestamp=timestamp,
        attributes=attributes,
    )

    return build_regression_record(
        points=[point],
        target=target,
        unit=unit,
        producer=producer,
        score_explanation=score_explanation,
    )
