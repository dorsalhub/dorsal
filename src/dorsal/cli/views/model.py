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

from __future__ import annotations
import logging
from typing import Any, TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.syntax import Syntax
from rich.bar import Bar
from rich.rule import Rule
from rich.json import JSON
from rich.box import Box

from dorsal.cli.themes import UIContext
from dorsal.cli.themes.borders import get_borders

if TYPE_CHECKING:
    from dorsal.file.configs.model_runner import RunModelResult
    from dorsal.client.validators import FileAnnotationResponse, FileAnnotationGroupResponse

logger = logging.getLogger(__name__)


def _tight_panel(content: RenderableType, title: str, border_style: str, borders: Box, **kwargs) -> RenderableType:
    """Helper to automatically strip Panel wrappers when borders are disabled."""
    if borders == get_borders("none"):
        return Group(Text.from_markup(f"{title}\n"), content)
    return Panel(content, title=title, border_style=border_style, box=borders, **kwargs)


def create_model_result_panel(
    result: "RunModelResult | FileAnnotationResponse | FileAnnotationGroupResponse",
    title: str,
    file_name: str,
    ui_context: UIContext,
    max_length: int = 10,
) -> RenderableType:
    """
    Dispatcher that renders a rich layout for a model run result.
    """
    from dorsal.file.configs.model_runner import RunModelResult
    from dorsal.client.validators import FileAnnotationResponse, FileAnnotationGroupResponse

    logger.debug(f"Rendering model result panel for '{file_name}' (Target: {title})")
    logger.debug(f"Result object type: {type(result).__name__}")

    palette = ui_context["palette"]
    borders = ui_context["borders"]
    icons = ui_context["icons"]

    data: dict[str, Any] | None = None
    group_info = ""
    schema_id = ""

    if isinstance(result, RunModelResult):
        logger.debug("Extracting record directly from RunModelResult")
        if result.records:
            data = result.records[0]
            if len(result.records) > 1:
                group_info = f" (Chunk 1 of {len(result.records)})"
        else:
            data = None
        schema_id = getattr(result, "schema_id", "") or ""

    elif isinstance(result, FileAnnotationGroupResponse):
        logger.debug("Extracting record from FileAnnotationGroupResponse")
        if result.group.annotations and result.group.annotations[0].record:
            data = result.group.annotations[0].record.model_dump()
            schema_id = getattr(result.group.annotations[0], "schema_id", "")
        group_info = f" (Group of {len(result.group.annotations)})"

    elif isinstance(result, FileAnnotationResponse):
        logger.debug("Extracting record from FileAnnotationResponse")
        data = result.record
        schema_id = getattr(result, "schema_id", "")

    logger.debug(f"Extracted schema_id: '{schema_id}'")

    if not data:
        logger.debug("No record data found in result. Returning Empty Result panel.")
        return _tight_panel(
            content=Text("No record data returned.", style=palette.get("error", "red")),
            title=f"[{palette.get('panel_title_error', 'red')}]{icons.get('error', '')}Empty Result{group_info}[/]",
            border_style=palette.get("panel_border_error", "red"),
            borders=borders,
        )

    content: RenderableType
    schema_type: str

    if schema_id in RENDERER_REGISTRY:
        logger.debug(f"Found specific renderer for schema_id '{schema_id}' in RENDERER_REGISTRY.")
        render_func, schema_type = RENDERER_REGISTRY[schema_id]
        content = render_func(data, ui_context, max_length)
    else:
        logger.debug(f"No specific renderer found for schema_id '{schema_id}'. Falling back to Raw JSON Output.")
        content = JSON.from_data(data)
        schema_type = "Raw Output"

    title_style = palette.get("panel_title_success", "green")
    border_style = palette.get("panel_border_success", "green")

    header = Table.grid(expand=True)
    header.add_column(justify="left")
    header.add_column(justify="right")
    header.add_row(
        Text(title, style=palette.get("section_title", "bold")), Text(f"{file_name}", style=palette.get("info", "dim"))
    )

    main_content = Group(header, Rule(style=palette.get("info", "dim")), Text(""), content)

    logger.debug("Successfully constructed Panel layout.")
    return _tight_panel(
        content=main_content,
        title=f"[{title_style}]{icons.get('info', '')}{schema_type} Result{group_info}[/]",
        border_style=border_style,
        borders=borders,
        expand=False,
    )


def _extract_color(style_str: str, default: str) -> str:
    """Helper to safely extract just a color name from a rich style string."""
    if not style_str:
        return default
    words = style_str.replace("on ", "").split()
    for w in reversed(words):
        if w not in ("bold", "dim", "italic", "underline", "strike", "blink", "reverse"):
            return w
    return default


def _score_bar(score: float, palette: dict[str, str], width: int = 20) -> Bar:
    """Helper to create a visual score bar respecting the theme palette."""
    if score > 0.7:
        style_str = palette.get("success", "green")
    elif score > 0.4:
        style_str = palette.get("warning", "yellow")
    else:
        style_str = palette.get("error", "red")

    color = _extract_color(style_str, "default")
    bgcolor = _extract_color(palette.get("table_row_alt", "bright_black"), "black")

    return Bar(size=width, begin=0, end=score, color=color, bgcolor=bgcolor)


def _render_arxiv(data: dict[str, Any], ui_context: UIContext, max_length: int) -> RenderableType:
    logger.debug("Executing _render_arxiv")
    palette = ui_context["palette"]
    borders = ui_context["borders"]
    renderables: list[RenderableType] = []

    title = data.get("title", "Untitled")
    title = " ".join(title.split())
    arxiv_id = data.get("arxiv_id", "Unknown ID")
    version = data.get("version", "")

    id_str = f"{arxiv_id} (v{version})" if version else arxiv_id

    renderables.append(Text(title, style=palette.get("section_title", "bold")))
    renderables.append(Text(id_str, style=palette.get("info", "dim")))

    authors = data.get("authors", [])
    if authors:
        display_authors = authors[:max_length]
        author_str = ", ".join(display_authors)
        if len(authors) > max_length:
            author_str += f", ... (+{len(authors) - max_length})"
        renderables.append(Text(author_str, style=f"{palette.get('primary_value_alt', 'cyan')} italic"))

    renderables.append(Text(""))

    abstract = data.get("abstract", "")
    if abstract:
        renderables.append(
            _tight_panel(
                content=abstract,
                title=f"[{palette.get('panel_title_info', 'dim')}]Abstract[/]",
                border_style=palette.get("panel_border_info", "dim"),
                borders=borders,
            )
        )
        renderables.append(Text(""))

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=palette.get("key", "dim"))
    grid.add_column(style=palette.get("primary_value", "default"))

    if url := data.get("url"):
        grid.add_row("URL", Text(url, style=palette.get("link", "underline")))
    if categories := data.get("categories"):
        grid.add_row("Categories", ", ".join(categories))
    if doi := data.get("doi"):
        grid.add_row("DOI", doi)
    if journal := data.get("journal_ref"):
        grid.add_row("Journal", journal)
    if license_str := data.get("license"):
        grid.add_row("License", license_str)

    if grid.row_count > 0:
        renderables.append(grid)

    return Group(*renderables)


def _render_classification(data: dict[str, Any], ui_context: UIContext, max_length: int) -> RenderableType:
    logger.debug("Executing _render_classification")
    palette = ui_context["palette"]
    renderables: list[RenderableType] = []

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=palette.get("key", "dim"))
    grid.add_column(style=palette.get("primary_value", "bold"))
    if target := data.get("target"):
        grid.add_row("Target:", str(target))
    if producer := data.get("producer"):
        grid.add_row("Producer:", str(producer))
    if grid.row_count > 0:
        renderables.extend([grid, Text("")])

    labels = data.get("labels", [])
    if labels:
        table = Table(box=None, padding=(0, 2), show_header=True)
        table.add_column("Label", style=palette.get("table_header", "bold"))
        table.add_column("Score", justify="right", style=palette.get("primary_value", "cyan"))
        table.add_column("Confidence", width=20)

        labels_sorted = sorted(labels, key=lambda x: x.get("score", 0), reverse=True)
        for item in labels_sorted[:max_length]:
            score = item.get("score", 0)
            table.add_row(item.get("label", "Unknown"), f"{score:.4f}", _score_bar(score, palette))

        if len(labels_sorted) > max_length:
            table.add_row(f"... and {len(labels_sorted) - max_length} more", "", "")
        renderables.append(table)
    else:
        vocab = data.get("vocabulary", [])
        if vocab:
            renderables.append(Text(f"Vocabulary: {', '.join(vocab[:max_length])}", style=palette.get("info", "dim")))
        elif v_url := data.get("vocabulary_url"):
            renderables.append(Text(f"Vocabulary URL: {v_url}", style=palette.get("link", "underline")))

    if desc := data.get("score_explanation"):
        renderables.extend([Text(""), Text(f"Score: {desc}", style=f"{palette.get('info', 'dim')} italic")])

    return Group(*renderables)


def _render_entity_extraction(data: dict[str, Any], ui_context: UIContext, max_length: int) -> RenderableType:
    logger.debug("Executing _render_entity_extraction")
    palette = ui_context["palette"]
    renderables: list[RenderableType] = []

    info_grid = Table.grid(padding=(0, 2))
    info_grid.add_column(style=palette.get("key", "dim"))
    info_grid.add_column(style=palette.get("primary_value", "bold"))
    if val := data.get("producer"):
        info_grid.add_row("Producer:", str(val))
    if val := data.get("unit"):
        info_grid.add_row("Unit:", str(val))
    if info_grid.row_count > 0:
        renderables.extend([info_grid, Text("")])

    entities = data.get("entities", [])
    if not entities:
        renderables.append(Text("No entities found.", style=palette.get("info", "dim")))
        return Group(*renderables)

    table = Table(box=None, padding=(0, 2), show_header=True)
    table.add_column("Label", style=palette.get("table_header", "bold"))
    table.add_column("Concept", style=palette.get("info", "dim"))
    table.add_column("Text", style=palette.get("primary_value", "cyan"))
    table.add_column("Normalized Value", style=palette.get("primary_value_alt", "yellow"))
    table.add_column("Score", justify="right", style=palette.get("primary_value", "cyan"))

    for ent in entities[:max_length]:
        val = str(ent.get("value")) if ent.get("value") is not None else "-"
        table.add_row(
            ent.get("label", "UNK"),
            ent.get("concept", "-"),
            ent.get("text", "")[:50],
            val[:30],
            f"{ent.get('score', 0):.2f}" if "score" in ent else "-",
        )

    renderables.extend([table, Text(f"Extracted {len(entities)} entities.", style=palette.get("info", "dim"))])
    return Group(*renderables)


def _render_object_detection(data: dict[str, Any], ui_context: UIContext, max_length: int) -> RenderableType:
    logger.debug("Executing _render_object_detection")
    palette = ui_context["palette"]
    renderables: list[RenderableType] = []

    info_grid = Table.grid(padding=(0, 2))
    info_grid.add_column(style=palette.get("key", "dim"))
    info_grid.add_column(style=palette.get("primary_value", "bold"))
    if val := data.get("producer"):
        info_grid.add_row("Producer:", str(val))
    if val := data.get("unit"):
        info_grid.add_row("Unit:", str(val))
    if info_grid.row_count > 0:
        renderables.extend([info_grid, Text("")])

    objects = data.get("objects", [])
    table = Table(box=None, padding=(0, 2), show_header=True)
    table.add_column("Label", style=palette.get("table_header", "bold"))
    table.add_column("Score", justify="right", style=palette.get("primary_value", "cyan"))
    table.add_column("Location", style=palette.get("primary_value", "cyan"))

    for obj in objects[:max_length]:
        loc = "Unknown"
        if box := obj.get("box"):
            loc = f"Box [x:{float(box.get('x', 0)):.1f}, y:{float(box.get('y', 0)):.1f}]"
        elif poly := obj.get("polygon"):
            loc = f"Poly ({len(poly)} pts)"

        table.add_row(obj.get("label", "Unknown"), f"{obj.get('score', 0):.2f}" if "score" in obj else "-", loc)

    renderables.extend([table, Text(f"Found {len(objects)} objects.", style=palette.get("info", "dim"))])
    return Group(*renderables)


def _render_embedding(data: dict[str, Any], ui_context: UIContext, max_length: int) -> RenderableType:
    logger.debug("Executing _render_embedding")
    palette = ui_context["palette"]
    borders = ui_context["borders"]
    renderables: list[RenderableType] = []

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=palette.get("key", "dim"))
    grid.add_column(style=palette.get("primary_value", "bold"))

    if model := data.get("model"):
        grid.add_row("Model", str(model))
    if target := data.get("target"):
        grid.add_row("Target", str(target))

    vector = data.get("vector")
    if isinstance(vector, list):
        dim = len(vector)
        grid.add_row("Type", "Dense Array")
        grid.add_row("Dimensions", str(dim))
        vec_preview = "[" + ", ".join(f"{v:.4f}" for v in vector[:max_length])
        if dim > max_length:
            vec_preview += f", ... (+{dim - max_length} more)"
        vec_preview += "]"
    elif isinstance(vector, dict):
        dim = vector.get("dimensions", "Unknown")
        indices = vector.get("indices", [])
        grid.add_row("Type", "Sparse Object")
        grid.add_row("Dimensions", str(dim))
        grid.add_row("Non-zero Elements", str(len(indices)))
        vec_preview = f"Indices: {indices[:max_length]}...\nValues: {vector.get('values', [])[:max_length]}..."
    else:
        vec_preview = "Unknown vector format."

    renderables.extend(
        [
            grid,
            Text(""),
            _tight_panel(
                content=vec_preview,
                title=f"[{palette.get('panel_title_info', 'dim')}]Vector Data[/]",
                border_style=palette.get("panel_border_info", "dim"),
                borders=borders,
            ),
        ]
    )

    return Group(*renderables)


def _render_audio_transcription(data: dict[str, Any], ui_context: UIContext, max_length: int) -> RenderableType:
    logger.debug("Executing _render_audio_transcription")
    palette = ui_context["palette"]
    borders = ui_context["borders"]
    renderables: list[RenderableType] = []

    info_grid = Table.grid(padding=(0, 2))
    info_grid.add_column(style=palette.get("key", "dim"))
    info_grid.add_column(style=palette.get("primary_value", "bold"))

    for key, label in [
        ("track_id", "Track ID"),
        ("producer", "Producer"),
        ("language", "Language"),
        ("duration", "Duration (s)"),
    ]:
        if val := data.get(key):
            info_grid.add_row(f"{label}:", str(val))

    if info_grid.row_count > 0:
        renderables.extend([info_grid, Text("")])

    if full_text := data.get("text"):
        renderables.extend(
            [
                _tight_panel(
                    content=full_text,
                    title=f"[{palette.get('panel_title_info', 'dim')}]Full Transcription[/]",
                    border_style=palette.get("panel_border_info", "dim"),
                    borders=borders,
                ),
                Text(""),
            ]
        )

    segments = data.get("segments", [])
    if segments:
        seg_table = Table(box=None, padding=(0, 1), show_header=True)
        seg_table.add_column("Time", style=palette.get("info", "dim"))
        seg_table.add_column("Speaker", style=palette.get("table_header", "bold"))
        seg_table.add_column("Text", style=palette.get("primary_value", "cyan"))

        for seg in segments[:max_length]:
            start = seg.get("start_time", 0)
            end = seg.get("end_time", 0)
            speaker_obj = seg.get("speaker", {})
            speaker = speaker_obj.get("name") or str(speaker_obj.get("id", "Unknown"))

            seg_table.add_row(f"{start:.1f}-{end:.1f}s", speaker, seg.get("text", ""))

        renderables.append(seg_table)
        if len(segments) > max_length:
            renderables.append(
                Text(f"... {len(segments) - max_length} more segments", style=palette.get("info", "dim"))
            )

    return Group(*renderables)


def _render_document_extraction(data: dict[str, Any], ui_context: UIContext, max_length: int) -> RenderableType:
    logger.debug("Executing _render_document_extraction")
    palette = ui_context["palette"]
    borders = ui_context["borders"]
    blocks = data.get("blocks", [])
    stats: dict[str, int] = {}
    for b in blocks:
        btype = b.get("block_type", "unknown")
        stats[btype] = stats.get(btype, 0) + 1

    summary = ", ".join(f"{k}: {v}" for k, v in stats.items())
    renderables: list[RenderableType] = []

    info_grid = Table.grid(padding=(0, 2))
    info_grid.add_column(style=palette.get("key", "dim"))
    info_grid.add_column(style=palette.get("primary_value", "bold"))
    for key, label in [("extraction_type", "Type"), ("producer", "Producer"), ("unit", "Unit")]:
        if val := data.get(key):
            info_grid.add_row(f"{label}:", str(val))

    if info_grid.row_count > 0:
        renderables.append(info_grid)

    renderables.extend([Text(f"Summary: {summary}", style=palette.get("info", "dim")), Text("")])

    text_blocks = [b for b in blocks if b.get("text")]
    for b in text_blocks[:max_length]:
        renderables.append(
            _tight_panel(
                content=b.get("text", ""),
                title=f"[{palette.get('panel_title_info', 'dim')}]Block {b.get('id', '')[:8]} (Page {b.get('page_number', '?')})[/]",
                border_style=palette.get("panel_border_info", "dim"),
                borders=borders,
            )
        )

    if len(text_blocks) > max_length:
        renderables.append(Text(f"... {len(text_blocks) - max_length} more blocks", style=palette.get("info", "dim")))

    return Group(*renderables)


def _render_llm_output(data: dict[str, Any], ui_context: UIContext, max_length: int) -> RenderableType:
    logger.debug("Executing _render_llm_output")
    palette = ui_context["palette"]
    borders = ui_context["borders"]
    renderables: list[RenderableType] = []

    renderables.append(Text(f"Model: {data.get('model', 'Unknown Model')}", style=palette.get("section_title", "bold")))
    if lang := data.get("language"):
        renderables.append(Text(f"Language: {lang}", style=palette.get("info", "dim")))

    prompt = data.get("prompt", "")
    if len(prompt) > 200:
        prompt = prompt[:200] + "..."
    renderables.append(
        _tight_panel(
            content=prompt,
            title=f"[{palette.get('panel_title_info', 'dim')}]Input Prompt[/]",
            border_style=palette.get("panel_border_info", "dim"),
            borders=borders,
            height=5,
        )
    )

    response = data.get("response_data", "")
    response_render: RenderableType
    if isinstance(response, str) and (response.strip().startswith("{") or response.strip().startswith("[")):
        response_render = Syntax(response, "json", word_wrap=True)
    else:
        response_render = Text(str(response))

    renderables.append(
        _tight_panel(
            content=response_render,
            title=f"[{palette.get('panel_title_success', 'bold green')}]Response[/]",
            border_style=palette.get("panel_border_success", "green"),
            borders=borders,
        )
    )

    meta_grid = Table.grid(padding=(0, 2))
    meta_grid.add_column(style=palette.get("key", "dim"))
    meta_grid.add_column(style=palette.get("info", "dim"))

    if usage := data.get("generation_metadata", {}).get("usage"):
        stats = f"Tokens: {usage.get('total_tokens')} (Prompt: {usage.get('prompt_tokens')}, Compl: {usage.get('completion_tokens')})"
        meta_grid.add_row("Usage:", stats)

    if params := data.get("generation_params", {}):
        param_str = ", ".join(f"{k}={v}" for k, v in params.items() if k in ("temperature", "top_p", "max_tokens"))
        if param_str:
            meta_grid.add_row("Params:", param_str)

    if meta_grid.row_count > 0:
        renderables.append(meta_grid)

    return Group(*renderables)


def _render_regression(data: dict[str, Any], ui_context: UIContext, max_length: int) -> RenderableType:
    logger.debug("Executing _render_regression")
    palette = ui_context["palette"]
    points = data.get("points", [])
    target = data.get("target", "Unknown Target")
    unit = data.get("unit", "")

    renderables: list[RenderableType] = [
        Text(f"Regression Target: {target}", style=palette.get("section_title", "bold"))
    ]
    if producer := data.get("producer"):
        renderables.append(Text(f"Producer: {producer}", style=palette.get("info", "dim")))
    renderables.append(Text(""))

    table = Table(box=None, padding=(0, 2), show_header=True)
    table.add_column("Timestamp", style=palette.get("info", "dim"))
    table.add_column(f"Value ({unit})" if unit else "Value", style=palette.get("table_header", "bold"))
    table.add_column("Statistic", style=palette.get("primary_value", "cyan"))
    table.add_column("Interval", style=palette.get("primary_value", "cyan"))

    for p in points[:max_length]:
        val = p.get("value")
        val_str = f"{val:.4f}" if isinstance(val, float) else str(val)

        stat = p.get("statistic", "point")
        if stat == "quantile" and "quantile_level" in p:
            stat = f"quantile ({p['quantile_level']})"

        interval = ""
        if p.get("interval_lower") is not None and p.get("interval_upper") is not None:
            interval = f"[{p['interval_lower']:.2f}, {p['interval_upper']:.2f}]"

        table.add_row(p.get("timestamp", "-"), val_str, stat, interval)

    renderables.append(table)

    if len(points) > max_length:
        renderables.append(Text(f"... {len(points) - max_length} more points", style=palette.get("info", "dim")))

    return Group(*renderables)


def _render_geolocation(data: dict[str, Any], ui_context: UIContext, max_length: int) -> RenderableType:
    logger.debug("Executing _render_geolocation")
    palette = ui_context["palette"]
    geo = data.get("geometry") or {}
    props = data.get("properties") or {}

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=palette.get("key", "dim"))
    grid.add_column(style=palette.get("primary_value", "cyan"))

    grid.add_row("Type", geo.get("type", "Null Geometry"))
    if coords := geo.get("coordinates"):
        coord_str = str(coords)
        grid.add_row("Coordinates", coord_str[:100] + "..." if len(coord_str) > 100 else coord_str)

    if props:
        renderables: list[RenderableType] = [
            grid,
            Rule(style=palette.get("info", "dim")),
            Text("Properties", style=palette.get("section_title", "bold")),
        ]

        prop_items = list(props.items())
        for k, v in prop_items[:max_length]:
            if v is not None:
                renderables.append(Text(f"{k}: {v}", style=palette.get("primary_value", "cyan")))

        if len(prop_items) > max_length:
            renderables.append(
                Text(f"... {len(prop_items) - max_length} more properties", style=palette.get("info", "dim"))
            )

        return Group(*renderables)

    return grid


def _render_generic(data: dict[str, Any], ui_context: UIContext, max_length: int) -> RenderableType:
    logger.debug("Executing _render_generic")
    palette = ui_context["palette"]
    kv_data = data.get("data", {})
    renderables: list[RenderableType] = [
        Text(data.get("description", "Generic Data"), style=f"{palette.get('info', 'dim')} italic")
    ]
    if producer := data.get("producer"):
        renderables.append(Text(f"Producer: {producer}", style=palette.get("info", "dim")))
    renderables.append(Text(""))

    table = Table(box=None, padding=(0, 2))
    table.add_column("Key", style=palette.get("key", "dim"))
    table.add_column("Value", style=palette.get("primary_value", "cyan"))

    kv_items = list(kv_data.items())
    for k, v in kv_items[:max_length]:
        table.add_row(k, str(v))

    renderables.append(table)

    if len(kv_items) > max_length:
        renderables.append(Text(f"... {len(kv_items) - max_length} more properties", style=palette.get("info", "dim")))

    return Group(*renderables)


RENDERER_REGISTRY = {
    "dorsal/arxiv": (_render_arxiv, "ArXiv Record"),
    "open/audio-transcription": (_render_audio_transcription, "Audio Transcription"),
    "open/classification": (_render_classification, "Classification"),
    "open/document-extraction": (_render_document_extraction, "Document Extraction"),
    "open/embedding": (_render_embedding, "Embedding"),
    "open/entity-extraction": (_render_entity_extraction, "Entity Extraction"),
    "open/geolocation": (_render_geolocation, "Geolocation"),
    "open/llm-output": (_render_llm_output, "LLM Output"),
    "open/object-detection": (_render_object_detection, "Object Detection"),
    "open/regression": (_render_regression, "Regression"),
    "open/generic": (_render_generic, "Generic Data"),
}
