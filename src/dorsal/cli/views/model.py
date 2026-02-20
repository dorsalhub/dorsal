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
from typing import Any, TYPE_CHECKING

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.syntax import Syntax
from rich.bar import Bar
from rich.rule import Rule
from rich.json import JSON

if TYPE_CHECKING:
    from dorsal.file.validators.file_record import Annotation, AnnotationGroup
    from dorsal.client.validators import FileAnnotationResponse, FileAnnotationGroupResponse


def create_model_result_panel(
    result: Annotation | AnnotationGroup | FileAnnotationResponse | FileAnnotationGroupResponse,
    target: str,
    file_name: str,
    palette: dict[str, str],
) -> Panel:
    """
    Dispatcher that renders a rich Panel for a model run result.
    """
    from dorsal.file.validators.file_record import Annotation, AnnotationGroup
    from dorsal.client.validators import FileAnnotationResponse, FileAnnotationGroupResponse

    data: dict[str, Any] | None = None
    group_info = ""

    
    if isinstance(result, AnnotationGroup):
        if result.annotations and result.annotations[0].record:
            data = result.annotations[0].record.model_dump()
        group_info = f" (Group of {len(result.annotations)})"

    elif isinstance(result, FileAnnotationGroupResponse):
        if result.group.annotations and result.group.annotations[0].record:
            data = result.group.annotations[0].record.model_dump()
        group_info = f" (Group of {len(result.group.annotations)})"

    elif isinstance(result, FileAnnotationResponse):
        data = result.record

    elif isinstance(result, Annotation):
        if result.record:
            data = result.record.model_dump()

    content: RenderableType
    schema_type: str

    
    if not data:
        return Panel(
            Text("No record data returned.", style=palette.get("error", "red")),
            title=f"[{palette.get('panel_title_error', 'red')}] Empty Result{group_info}[/]",
            border_style=palette.get("panel_border_error", "red"),
        )

    
    if target == "dorsal/arxiv":
        content = _render_arxiv(data, palette)
        schema_type = "ArXiv Record"

    elif "vector" in data:
        content = _render_embedding(data, palette)
        schema_type = "Embedding"

    elif "labels" in data and ("vocabulary" in data or "vocabulary_url" in data or "target" in data):
        content = _render_classification(data, palette)
        schema_type = "Classification"

    elif "entities" in data:
        content = _render_entity_extraction(data, palette)
        schema_type = "Entity Extraction"

    elif "objects" in data:
        content = _render_object_detection(data, palette)
        schema_type = "Object Detection"

    elif "segments" in data or ("text" in data and "language" in data and "speaker" in data):
        content = _render_audio_transcription(data, palette)
        schema_type = "Audio Transcription"

    elif "blocks" in data and "extraction_type" in data:
        content = _render_document_extraction(data, palette)
        schema_type = "Document Extraction"

    elif "prompt" in data and "response_data" in data:
        content = _render_llm_output(data, palette)
        schema_type = "LLM Output"

    elif "points" in data and "target" in data:
        content = _render_regression(data, palette)
        schema_type = "Regression"

    elif data.get("type") == "Feature" and "geometry" in data:
        content = _render_geolocation(data, palette)
        schema_type = "Geolocation"

    elif "data" in data and "description" in data:
        content = _render_generic(data, palette)
        schema_type = "Generic Data"

    else:
        content = JSON.from_data(data)
        schema_type = "Raw Output"

    title_style = palette.get("panel_title_success", "green")
    border_style = palette.get("panel_border_success", "green")

    header = Table.grid(expand=True)
    header.add_column(justify="left")
    header.add_column(justify="right")
    header.add_row(
        Text(target, style=palette.get("section_title", "bold")), 
        Text(f"{file_name}", style=palette.get("info", "dim"))
    )

    return Panel(
        Group(header, Rule(style=palette.get("info", "dim")), Text(""), content),
        title=f"[{title_style}]{schema_type} Result{group_info}[/]",
        border_style=border_style,
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


def _render_arxiv(data: dict[str, Any], palette: dict[str, str]) -> RenderableType:
    renderables: list[RenderableType] = []

    
    title = data.get("title", "Untitled")
    title = " ".join(title.split())
    arxiv_id = data.get("arxiv_id", "Unknown ID")
    version = data.get("version", "")
    
    
    if version:
        version_str = version if version.startswith("v") else f"v{version}"
        id_str = f"{arxiv_id} ({version_str})"
    else:
        id_str = arxiv_id

    renderables.append(Text(title, style=palette.get("section_title", "bold")))
    renderables.append(Text(id_str, style=palette.get("info", "dim")))

    
    authors = data.get("authors", [])
    if authors:
        
        renderables.append(Text(", ".join(authors), style=f"{palette.get('primary_value_alt', 'cyan')} italic"))

    renderables.append(Text(""))  

    
    abstract = data.get("abstract", "")
    if abstract:
        renderables.append(
            Panel(
                abstract, 
                title=f"[{palette.get('panel_title_info', 'dim')}]Abstract[/]", 
                border_style=palette.get("panel_border_info", "dim")
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


def _render_classification(data: dict[str, Any], palette: dict[str, str]) -> RenderableType:
    table = Table(box=None, padding=(0, 2), show_header=True)
    table.add_column("Label", style=palette.get("table_header", "bold"))
    table.add_column("Score", justify="right", style=palette.get("primary_value", "default"))
    table.add_column("Confidence", width=20)

    labels = sorted(data.get("labels", []), key=lambda x: x.get("score", 0), reverse=True)

    for item in labels[:10]:
        score = item.get("score", 0)
        table.add_row(item.get("label", "Unknown"), f"{score:.4f}", _score_bar(score, palette))

    if len(labels) > 10:
        table.add_row(f"... and {len(labels) - 10} more", "", "")

    meta: list[RenderableType] = []
    if desc := data.get("score_explanation"):
        meta.append(Text(f"Score: {desc}", style=f"{palette.get('info', 'dim')} italic"))

    return Group(table, *meta)


def _render_object_detection(data: dict[str, Any], palette: dict[str, str]) -> RenderableType:
    objects = data.get("objects", [])

    table = Table(box=None, padding=(0, 2), show_header=True)
    table.add_column("Label", style=palette.get("table_header", "bold"))
    table.add_column("Score", justify="right", style=palette.get("primary_value", "default"))
    table.add_column("Location", style=palette.get("primary_value", "default"))

    for obj in objects[:15]:
        loc = "Unknown"
        if box := obj.get("box"):
            loc = f"Box [x:{float(box.get('x', 0)):.1f}, y:{float(box.get('y', 0)):.1f}]"
        elif poly := obj.get("polygon"):
            loc = f"Poly ({len(poly)} pts)"

        table.add_row(obj.get("label", "Unknown"), f"{obj.get('score', 0):.2f}", loc)

    return Group(Text(f"Found {len(objects)} objects.", style=palette.get("info", "dim")), Text(""), table)


def _render_entity_extraction(data: dict[str, Any], palette: dict[str, str]) -> RenderableType:
    entities = data.get("entities", [])

    table = Table(box=None, padding=(0, 2), show_header=True)
    table.add_column("Label", style=palette.get("table_header", "bold"))
    table.add_column("Text", style=palette.get("primary_value", "default"))
    table.add_column("Normalized Value", style=palette.get("info", "dim"))
    table.add_column("Score", justify="right", style=palette.get("primary_value", "default"))

    for ent in entities[:15]:
        val = str(ent.get("value")) if ent.get("value") is not None else "-"
        table.add_row(ent.get("label", "UNK"), ent.get("text", "")[:50], val[:30], f"{ent.get('score', 0):.2f}")

    return Group(Text(f"Extracted {len(entities)} entities.", style=palette.get("info", "dim")), Text(""), table)


def _render_audio_transcription(data: dict[str, Any], palette: dict[str, str]) -> RenderableType:
    renderables: list[RenderableType] = []

    info_grid = Table.grid(padding=(0, 2))
    info_grid.add_column(style=palette.get("key", "dim"))
    info_grid.add_column(style=palette.get("primary_value", "bold"))
    if lang := data.get("language"):
        info_grid.add_row("Language:", lang)
    renderables.append(info_grid)
    renderables.append(Text(""))

    if full_text := data.get("text"):
        renderables.append(
            Panel(
                full_text, 
                title=f"[{palette.get('panel_title_info', 'dim')}]Full Transcription[/]", 
                border_style=palette.get("panel_border_info", "dim")
            )
        )
        renderables.append(Text(""))

    segments = data.get("segments", [])
    if segments:
        seg_table = Table(box=None, padding=(0, 1), show_header=True)
        seg_table.add_column("Time", style=palette.get("info", "dim"))
        seg_table.add_column("Speaker", style=palette.get("table_header", "bold"))
        seg_table.add_column("Text", style=palette.get("primary_value", "default"))

        for seg in segments[:10]:
            start = seg.get("start_time", 0)
            end = seg.get("end_time", 0)
            speaker = seg.get("speaker", {}).get("name", "Unknown")
            text = seg.get("text", "")

            time_str = f"{start:.1f}-{end:.1f}s"
            seg_table.add_row(time_str, speaker, text)

        renderables.append(seg_table)
        if len(segments) > 10:
            renderables.append(Text(f"... {len(segments) - 10} more segments", style=palette.get("info", "dim")))

    return Group(*renderables)


def _render_llm_output(data: dict[str, Any], palette: dict[str, str]) -> RenderableType:
    renderables: list[RenderableType] = []

    model_name = data.get("model", "Unknown Model")
    renderables.append(Text(f"Model: {model_name}", style=palette.get("section_title", "bold")))

    prompt = data.get("prompt", "")
    if len(prompt) > 200:
        prompt = prompt[:200] + "..."
    renderables.append(
        Panel(
            prompt, 
            title=f"[{palette.get('panel_title_info', 'dim')}]Input Prompt[/]", 
            border_style=palette.get("panel_border_info", "dim"), 
            height=5
        )
    )

    response = data.get("response_data", "")
    response_render: RenderableType
    if isinstance(response, str) and (response.strip().startswith("{") or response.strip().startswith("[")):
        response_render = Syntax(response, "json", word_wrap=True)
    else:
        response_render = Text(str(response))

    renderables.append(
        Panel(
            response_render, 
            title=f"[{palette.get('panel_title_success', 'bold green')}]Response[/]", 
            border_style=palette.get("panel_border_success", "green")
        )
    )

    if metadata := data.get("generation_metadata"):
        if usage := metadata.get("usage"):
            stats = f"Tokens: {usage.get('total_tokens')} (Prompt: {usage.get('prompt_tokens')}, Compl: {usage.get('completion_tokens')})"
            renderables.append(Text(stats, style=palette.get("info", "dim")))

    return Group(*renderables)


def _render_embedding(data: dict[str, Any], palette: dict[str, str]) -> RenderableType:
    vector = data.get("vector", [])
    dim = len(vector)

    vec_preview = "[" + ", ".join(f"{v:.4f}" for v in vector[:8])
    if dim > 8:
        vec_preview += ", ..."
    vec_preview += "]"

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=palette.get("key", "dim"))
    grid.add_column(style=palette.get("primary_value", "bold"))

    grid.add_row("Model", str(data.get("model", "Unknown")))
    grid.add_row("Dimensions", str(dim))
    grid.add_row("Target", str(data.get("target", "None")))

    return Group(
        grid, 
        Text(""), 
        Panel(
            vec_preview, 
            title=f"[{palette.get('panel_title_info', 'dim')}]Vector Data[/]", 
            border_style=palette.get("panel_border_info", "dim")
        )
    )


def _render_document_extraction(data: dict[str, Any], palette: dict[str, str]) -> RenderableType:
    blocks = data.get("blocks", [])

    stats: dict[str, int] = {}
    for b in blocks:
        btype = b.get("block_type", "unknown")
        stats[btype] = stats.get(btype, 0) + 1

    summary = ", ".join(f"{k}: {v}" for k, v in stats.items())

    renderables: list[RenderableType] = [
        Text(f"Extraction Type: {data.get('extraction_type')}", style=palette.get("section_title", "bold")),
        Text(f"Summary: {summary}", style=palette.get("info", "dim")),
        Text(""),
    ]

    text_blocks = [b for b in blocks if b.get("text")]
    for b in text_blocks[:5]:
        renderables.append(
            Panel(
                b.get("text", ""),
                title=f"[{palette.get('panel_title_info', 'dim')}]Block {b.get('id', '')[:8]} (Page {b.get('page_number')})[/]",
                border_style=palette.get("panel_border_info", "dim"),
            )
        )

    if len(text_blocks) > 5:
        renderables.append(Text(f"... {len(text_blocks) - 5} more blocks", style=palette.get("info", "dim")))

    return Group(*renderables)


def _render_geolocation(data: dict[str, Any], palette: dict[str, str]) -> RenderableType:
    geo = data.get("geometry", {})
    props = data.get("properties", {})

    geo_type = geo.get("type", "Unknown")
    coords = geo.get("coordinates", [])

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=palette.get("key", "dim"))
    grid.add_column(style=palette.get("primary_value", "default"))

    grid.add_row("Type", geo_type)
    grid.add_row("Coordinates", str(coords))

    if props:
        renderables: list[RenderableType] = [
            grid, 
            Rule(style=palette.get("info", "dim")), 
            Text("Properties", style=palette.get("section_title", "bold"))
        ]
        for k, v in props.items():
            if v:
                renderables.append(Text(f"{k}: {v}", style=palette.get("primary_value", "default")))
        return Group(*renderables)

    return grid


def _render_regression(data: dict[str, Any], palette: dict[str, str]) -> RenderableType:
    points = data.get("points", [])
    target = data.get("target", "Unknown Target")
    unit = data.get("unit", "")

    table = Table(box=None, padding=(0, 2), show_header=True)
    table.add_column("Timestamp", style=palette.get("info", "dim"))
    table.add_column(f"Value ({unit})", style=palette.get("table_header", "bold"))
    table.add_column("Statistic", style=palette.get("primary_value", "default"))
    table.add_column("Interval", style=palette.get("primary_value", "default"))

    for p in points[:10]:
        val = p.get("value")
        val_str = f"{val:.4f}" if isinstance(val, float) else str(val)

        interval = ""
        if p.get("interval_lower") is not None:
            interval = f"[{p['interval_lower']:.2f}, {p['interval_upper']:.2f}]"

        table.add_row(p.get("timestamp", "-"), val_str, p.get("statistic", "point"), interval)

    return Group(Text(f"Regression Target: {target}", style=palette.get("section_title", "bold")), Text(""), table)


def _render_generic(data: dict[str, Any], palette: dict[str, str]) -> RenderableType:
    kv_data = data.get("data", {})
    desc = data.get("description", "Generic Data")

    table = Table(box=None, padding=(0, 2))
    table.add_column("Key", style=palette.get("key", "bold dim"))
    table.add_column("Value", style=palette.get("primary_value", "default"))

    for k, v in kv_data.items():
        table.add_row(k, str(v))

    return Group(Text(desc, style=f"{palette.get('info', 'dim')} italic"), Text(""), table)