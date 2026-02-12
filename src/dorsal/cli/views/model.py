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

from typing import Any, Dict, Union, List

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.syntax import Syntax
from rich.tree import Tree
from rich.bar import Bar
from rich.rule import Rule
from rich.json import JSON

from dorsal.file.validators.file_record import Annotation, AnnotationGroup


def create_model_result_panel(
    result: Union[Annotation, AnnotationGroup],
    target: str,
    file_name: str,
    palette: Dict[str, str],
) -> Panel:
    """
    Dispatcher that renders a rich Panel for a model run result.
    """

    if isinstance(result, AnnotationGroup):
        record = result.annotations[0].record
        group_info = f" (Group of {len(result.annotations)})"
    else:
        record = result.record
        group_info = ""

    data: Union[Dict[str, Any], None] = None

    if record is not None:
        data = record.model_dump()

    content: RenderableType
    schema_type: str

    if data is None:
        return Panel(
            Text("No record data returned.", style=palette.get("error", "red")),
            title=f"[{palette.get('panel_title_error', 'red')}]✨ Empty Result{group_info}[/]",
            border_style=palette.get("panel_border_error", "red"),
        )

    if "vector" in data:
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
    header.add_row(f"[bold]{target}[/]", f"📄 [dim]{file_name}[/]")

    return Panel(
        Group(header, Rule(style=palette.get("info", "dim")), Text(""), content),
        title=f"[{title_style}]✨ {schema_type} Result{group_info}[/]",
        border_style=border_style,
        expand=False,
    )


def _score_bar(score: float, width: int = 20) -> Bar:
    """Helper to create a visual score bar."""
    color = "green" if score > 0.7 else "yellow" if score > 0.4 else "red"
    return Bar(size=width, begin=0, end=score, color=color, bgcolor="bright_black")


def _render_classification(data: Dict, palette: Dict) -> RenderableType:
    table = Table(box=None, padding=(0, 2), show_header=True)
    table.add_column("Label", style="bold white")
    table.add_column("Score", justify="right")
    table.add_column("Confidence", width=20)

    labels = sorted(data.get("labels", []), key=lambda x: x.get("score", 0), reverse=True)

    for item in labels[:10]:
        score = item.get("score", 0)
        table.add_row(item.get("label", "Unknown"), f"{score:.4f}", _score_bar(score))

    if len(labels) > 10:
        table.add_row(f"... and {len(labels) - 10} more", "", "")

    meta: List[RenderableType] = []
    if desc := data.get("score_explanation"):
        meta.append(Text(f"Score: {desc}", style="dim italic"))

    return Group(table, *meta)


def _render_object_detection(data: Dict, palette: Dict) -> RenderableType:
    objects = data.get("objects", [])

    table = Table(box=None, padding=(0, 2), show_header=True)
    table.add_column("Label", style="bold white")
    table.add_column("Score", justify="right")
    table.add_column("Location")

    for obj in objects[:15]:
        loc = "Unknown"
        if box := obj.get("box"):
            loc = f"Box [x:{float(box.get('x', 0)):.1f}, y:{float(box.get('y', 0)):.1f}]"
        elif poly := obj.get("polygon"):
            loc = f"Poly ({len(poly)} pts)"

        table.add_row(obj.get("label", "Unknown"), f"{obj.get('score', 0):.2f}", loc)

    return Group(Text(f"Found {len(objects)} objects.", style=palette.get("info", "white")), Text(""), table)


def _render_entity_extraction(data: Dict, palette: Dict) -> RenderableType:
    entities = data.get("entities", [])

    table = Table(box=None, padding=(0, 2), show_header=True)
    table.add_column("Label", style="cyan")
    table.add_column("Text", style="bold white")
    table.add_column("Normalized Value", style="dim")
    table.add_column("Score", justify="right")

    for ent in entities[:15]:
        val = str(ent.get("value")) if ent.get("value") is not None else "-"
        table.add_row(ent.get("label", "UNK"), ent.get("text", "")[:50], val[:30], f"{ent.get('score', 0):.2f}")

    return Group(Text(f"Extracted {len(entities)} entities.", style=palette.get("info", "white")), Text(""), table)


def _render_audio_transcription(data: Dict, palette: Dict) -> RenderableType:
    renderables: List[RenderableType] = []

    info_grid = Table.grid(padding=(0, 2))
    info_grid.add_column(style="dim")
    info_grid.add_column(style="bold")
    if lang := data.get("language"):
        info_grid.add_row("Language:", lang)
    renderables.append(info_grid)
    renderables.append(Text(""))

    if full_text := data.get("text"):
        renderables.append(Panel(full_text, title="Full Transcription", border_style="dim"))
        renderables.append(Text(""))

    segments = data.get("segments", [])
    if segments:
        seg_table = Table(box=None, padding=(0, 1), show_header=True)
        seg_table.add_column("Time", style="dim")
        seg_table.add_column("Speaker", style="cyan")
        seg_table.add_column("Text")

        for seg in segments[:10]:
            start = seg.get("start_time", 0)
            end = seg.get("end_time", 0)
            speaker = seg.get("speaker", {}).get("name", "Unknown")
            text = seg.get("text", "")

            time_str = f"{start:.1f}-{end:.1f}s"
            seg_table.add_row(time_str, speaker, text)

        renderables.append(seg_table)
        if len(segments) > 10:
            renderables.append(Text(f"... {len(segments) - 10} more segments", style="dim"))

    return Group(*renderables)


def _render_llm_output(data: Dict, palette: Dict) -> RenderableType:
    renderables: List[RenderableType] = []

    model_name = data.get("model", "Unknown Model")
    renderables.append(Text(f"Model: {model_name}", style="bold cyan"))

    prompt = data.get("prompt", "")
    if len(prompt) > 200:
        prompt = prompt[:200] + "..."
    renderables.append(Panel(prompt, title="Input Prompt", border_style="dim", height=5))

    response = data.get("response_data", "")
    response_render: RenderableType
    if response.strip().startswith("{") or response.strip().startswith("["):
        response_render = Syntax(response, "json", word_wrap=True)
    else:
        response_render = Text(response)

    renderables.append(Panel(response_render, title="Response", border_style="green"))

    if metadata := data.get("generation_metadata"):
        if usage := metadata.get("usage"):
            stats = f"Tokens: {usage.get('total_tokens')} (Prompt: {usage.get('prompt_tokens')}, Compl: {usage.get('completion_tokens')})"
            renderables.append(Text(stats, style="dim"))

    return Group(*renderables)


def _render_embedding(data: Dict, palette: Dict) -> RenderableType:
    vector = data.get("vector", [])
    dim = len(vector)

    vec_preview = "[" + ", ".join(f"{v:.4f}" for v in vector[:8])
    if dim > 8:
        vec_preview += ", ..."
    vec_preview += "]"

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=palette.get("key", "dim"))
    grid.add_column(style="bold")

    grid.add_row("Model", str(data.get("model", "Unknown")))
    grid.add_row("Dimensions", str(dim))
    grid.add_row("Target", str(data.get("target", "None")))

    return Group(grid, Text(""), Panel(vec_preview, title="Vector Data", border_style="dim"))


def _render_document_extraction(data: Dict, palette: Dict) -> RenderableType:
    blocks = data.get("blocks", [])

    stats: Dict[str, int] = {}
    for b in blocks:
        btype = b.get("block_type", "unknown")
        stats[btype] = stats.get(btype, 0) + 1

    summary = ", ".join(f"{k}: {v}" for k, v in stats.items())

    renderables: List[RenderableType] = [
        Text(f"Extraction Type: {data.get('extraction_type')}", style="bold"),
        Text(f"Summary: {summary}", style="dim"),
        Text(""),
    ]

    text_blocks = [b for b in blocks if b.get("text")]
    for b in text_blocks[:5]:
        renderables.append(
            Panel(
                b.get("text", ""),
                title=f"Block {b.get('id', '')[:8]} (Page {b.get('page_number')})",
                border_style="dim",
            )
        )

    if len(text_blocks) > 5:
        renderables.append(Text(f"... {len(text_blocks) - 5} more blocks", style="dim"))

    return Group(*renderables)


def _render_geolocation(data: Dict, palette: Dict) -> RenderableType:
    geo = data.get("geometry", {})
    props = data.get("properties", {})

    geo_type = geo.get("type", "Unknown")
    coords = geo.get("coordinates", [])

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=palette.get("key", "dim"))
    grid.add_column()

    grid.add_row("Type", geo_type)
    grid.add_row("Coordinates", str(coords))

    if props:
        renderables: List[RenderableType] = [grid, Rule(style="dim"), Text("Properties", style="bold")]
        for k, v in props.items():
            if v:
                renderables.append(Text(f"{k}: {v}"))
        return Group(*renderables)

    return grid


def _render_regression(data: Dict, palette: Dict) -> RenderableType:
    points = data.get("points", [])
    target = data.get("target", "Unknown Target")
    unit = data.get("unit", "")

    table = Table(box=None, padding=(0, 2), show_header=True)
    table.add_column("Timestamp", style="dim")
    table.add_column(f"Value ({unit})", style="bold cyan")
    table.add_column("Statistic")
    table.add_column("Interval")

    for p in points[:10]:
        val = p.get("value")
        val_str = f"{val:.4f}" if isinstance(val, float) else str(val)

        interval = ""
        if p.get("interval_lower") is not None:
            interval = f"[{p['interval_lower']:.2f}, {p['interval_upper']:.2f}]"

        table.add_row(p.get("timestamp", "-"), val_str, p.get("statistic", "point"), interval)

    return Group(Text(f"Regression Target: {target}", style="bold"), Text(""), table)


def _render_generic(data: Dict, palette: Dict) -> RenderableType:
    kv_data = data.get("data", {})
    desc = data.get("description", "Generic Data")

    table = Table(box=None, padding=(0, 2))
    table.add_column("Key", style="bold dim")
    table.add_column("Value")

    for k, v in kv_data.items():
        table.add_row(k, str(v))

    return Group(Text(desc, style="italic"), Text(""), table)
