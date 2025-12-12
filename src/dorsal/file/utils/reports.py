# Copyright 2025 Dorsal Hub LTD
#
# Licensed under the Apache License, Version 2.0 (the "License");
# You may not use this file except in compliance with the License.
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
from collections import Counter, defaultdict
from typing import TYPE_CHECKING, Callable, Dict, Any, TypedDict
import pathlib
import logging

from dorsal.common import constants, config
from dorsal.common.exceptions import TemplateNotFoundError
from dorsal.file.utils.size import human_filesize


if TYPE_CHECKING:
    from dorsal.file.collection.local import LocalFileCollection

logger = logging.getLogger(__name__)


class _LargestFileInfo(TypedDict):
    name: str | None
    size: int


def resolve_template_path(report_type: str, name_or_path: str) -> tuple[pathlib.Path, pathlib.Path]:
    """
    Finds and validates a template file for a specific report type.
    """
    explicit_path = pathlib.Path(name_or_path).resolve()
    if explicit_path.is_file():
        logger.debug(f"Template search: Found valid file at explicit path: {explicit_path}")
        return explicit_path, explicit_path.parent

    template_filename = f"{name_or_path}.html"

    dorsal_config, _ = config.load_config()
    project_templates_dir = dorsal_config.get(constants.CONFIG_SECTION_UI, {}).get("report_templates_dir")
    if project_templates_dir:
        _, config_path = config.get_project_level_config()
        if config_path:
            project_root = config_path.parent
            project_template_path = (project_root / project_templates_dir / report_type / template_filename).resolve()
            if project_template_path.is_file():
                logger.debug(f"Template search: Found project template at: {project_template_path}")
                return project_template_path, project_template_path.parent

    user_template_path = constants.LOCAL_DORSAL_DIR / "templates" / report_type / template_filename
    if user_template_path.is_file():
        logger.debug(f"Template search: Found user-defined template at: {user_template_path}")
        return user_template_path, user_template_path.parent

    built_in_path = pathlib.Path(__file__).parent.parent.parent / "templates" / report_type / template_filename
    logger.debug("Checking built-in path: %s", built_in_path)
    if built_in_path.is_file():
        logger.debug(f"Template search: Found built-in template at: {built_in_path}")
        return built_in_path, built_in_path.parent

    raise TemplateNotFoundError(f"Template '{name_or_path}' for report type '{report_type}' could not be found.")


def get_summary_stats_data(collection: "LocalFileCollection") -> dict:
    """Returns data needed for the summary stats panel."""
    return collection.info()


def get_duplicates_data(collection: "LocalFileCollection") -> dict:
    """Returns data needed for the duplicates panel."""
    return collection.find_duplicates()


def get_collection_overview_data(collection: "LocalFileCollection") -> dict:
    """
    Prepares a comprehensive dataset for the collection overview panel,
    including data for all visualizations.
    """
    if not collection.files:
        return {}

    CHART_ITEM_CAP = 14

    collection_info = collection.info()
    total_collection_size = collection_info.get("overall", {}).get("total_size", 0)

    all_media_types_by_size = collection_info.get("by_type", [])
    media_type_by_size_data = all_media_types_by_size[:CHART_ITEM_CAP]
    if len(all_media_types_by_size) > CHART_ITEM_CAP:
        other_items = all_media_types_by_size[CHART_ITEM_CAP:]
        other_size = sum(item["total_size"] for item in other_items)
        other_count = sum(item["count"] for item in other_items)
        other_percentage = (other_size / total_collection_size) * 100 if total_collection_size > 0 else 0
        media_type_by_size_data.append(
            {
                "media_type": "Other",
                "total_size": other_size,
                "count": other_count,
                "percentage": other_percentage,
            }
        )

    media_type_counts = Counter(f.media_type for f in collection.files)
    all_media_types_by_count = media_type_counts.most_common()
    top_media_types_by_count = all_media_types_by_count[:CHART_ITEM_CAP]
    media_type_by_count_data = [{"media_type": mt, "count": count} for mt, count in top_media_types_by_count]
    if len(all_media_types_by_count) > CHART_ITEM_CAP:
        other_count = sum(count for _, count in all_media_types_by_count[CHART_ITEM_CAP:])
        media_type_by_count_data.append({"media_type": "Other", "count": other_count})

    extension_counts = Counter(f.extension for f in collection.files if f.extension)
    all_extensions_by_count = extension_counts.most_common()
    top_extensions_by_count_tuples = all_extensions_by_count[:CHART_ITEM_CAP]
    top_extensions_by_count = [{"extension": ext, "count": count} for ext, count in top_extensions_by_count_tuples]
    if len(all_extensions_by_count) > CHART_ITEM_CAP:
        other_count = sum(count for _, count in all_extensions_by_count[CHART_ITEM_CAP:])
        top_extensions_by_count.append({"extension": "Other", "count": other_count})

    extension_sizes: defaultdict[str, int] = defaultdict(int)
    for f in collection.files:
        if f.extension:
            extension_sizes[f.extension] += f.size
    all_extensions_by_size = sorted(extension_sizes.items(), key=lambda item: item[1], reverse=True)
    top_extensions_by_size_tuples = all_extensions_by_size[:CHART_ITEM_CAP]
    top_extensions_by_size = [{"extension": ext, "total_size": size} for ext, size in top_extensions_by_size_tuples]
    if len(all_extensions_by_size) > CHART_ITEM_CAP:
        other_size = sum(size for _, size in all_extensions_by_size[CHART_ITEM_CAP:])
        top_extensions_by_size.append({"extension": "Other", "total_size": other_size})

    largest_files_dist_data: list[_LargestFileInfo] = []
    if total_collection_size > 0:
        all_files_sorted = sorted(collection.files, key=lambda f: f.size, reverse=True)
        top_files = all_files_sorted[:CHART_ITEM_CAP]
        largest_files_dist_data = [{"name": f.name, "size": f.size} for f in top_files]
        if len(all_files_sorted) > CHART_ITEM_CAP:
            size_of_top_files = sum(f.size for f in top_files)
            other_size = total_collection_size - size_of_top_files
            if other_size > 0:
                largest_files_dist_data.append({"name": "Other", "size": other_size})

    timeline_data = [{"x": f.date_modified.isoformat(), "y": f.name} for f in collection.files]
    most_recent_file = (
        sorted(collection.files, key=lambda f: f.date_modified, reverse=True)[0] if collection.files else None
    )

    return {
        "media_type": {
            "by_size": media_type_by_size_data,
            "by_count": media_type_by_count_data,
        },
        "extension": {
            "by_size": top_extensions_by_size,
            "by_count": top_extensions_by_count,
        },
        "largest_files": {
            "by_size": largest_files_dist_data,
        },
        "timeline_data": timeline_data,
        "most_recent_file_record": (most_recent_file.to_dict() if most_recent_file else None),
    }


def get_dynamic_size_histogram_data(collection: "LocalFileCollection") -> list[dict]:
    """
    Analyzes file sizes and groups them into statistically-determined,
    dynamic, human-readable bins.
    """
    import math
    import statistics

    sizes = [f.size for f in collection.files if f.size > 0]
    if not sizes:
        return []

    if len(set(sizes)) < 5 and len(sizes) < 20:
        size_counts = Counter(sizes)
        return [{"bin_label": human_filesize(size), "count": count} for size, count in sorted(size_counts.items())]

    n = len(sizes)
    if n > 1:
        q1 = statistics.quantiles(sizes, n=4)[0]
        q3 = statistics.quantiles(sizes, n=4)[2]
        iqr = q3 - q1
        if iqr > 0:
            bin_width = 2 * iqr / (n ** (1 / 3))
            num_bins = int(math.ceil((max(sizes) - min(sizes)) / bin_width)) if bin_width > 0 else 10
        else:
            num_bins = 1
    else:
        num_bins = 1

    num_bins = max(1, min(num_bins, 25))
    min_safe_size = min(s for s in sizes if s > 0)
    if max(sizes) / min_safe_size > 1000:
        log_min = math.log10(min_safe_size)
        log_max = math.log10(max(sizes))
        bin_edges = [10**i for i in [log_min + x * (log_max - log_min) / num_bins for x in range(num_bins + 1)]]
    else:
        min_size, max_size = min(sizes), max(sizes)
        step = (max_size - min_size) / num_bins
        bin_edges = [min_size + i * step for i in range(num_bins + 1)]

    bin_counts = [0] * num_bins
    for size in sizes:
        for i in range(num_bins):
            is_last_bin = i == num_bins - 1
            if (bin_edges[i] <= size < bin_edges[i + 1]) or (is_last_bin and size == bin_edges[i + 1]):
                bin_counts[i] += 1
                break

    chart_data = []
    for i in range(len(bin_counts)):
        if bin_counts[i] > 0:
            lower_edge = bin_edges[i]
            upper_edge = bin_edges[i + 1]
            label = f"{human_filesize(lower_edge)} - {human_filesize(upper_edge)}"
            chart_data.append({"bin_label": label, "count": bin_counts[i]})

    return chart_data


def get_file_explorer_data(collection: LocalFileCollection) -> dict:
    """
    Placeholder data generator for the file explorer.
    """
    return {}


REPORT_DATA_GENERATORS: Dict[str, Callable[[LocalFileCollection], Any]] = {
    "summary_stats": get_summary_stats_data,
    "collection_overview": get_collection_overview_data,
    "duplicates_report": get_duplicates_data,
    "dynamic_size_histogram": get_dynamic_size_histogram_data,
    "file_explorer": get_file_explorer_data,
}
