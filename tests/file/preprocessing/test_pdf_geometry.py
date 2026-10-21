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

import re
from pathlib import Path

import pytest

pdfium = pytest.importorskip("pypdfium2")

from dorsal.file.preprocessing.pdf import (  # noqa: E402
    extract_pdf_layout_normalized,
    extract_pdf_layout_per_mille,
    extract_pdf_layout_pts,
)

A4 = (595.276, 841.89)
LINE = "(The quick brown fox jumps over the lazy dog) Tj"
TEXT_AT_ORIGIN = f"BT /F1 12 Tf 72 760 Td {LINE} ET"
TEXT_SHIFTED = f"BT /F1 12 Tf 172 860 Td {LINE} ET"

PAGES = {
    "normal": {"media": (0, 0, *A4), "content": TEXT_AT_ORIGIN},
    "rotate_90": {"media": (0, 0, *A4), "content": TEXT_AT_ORIGIN, "rotate": 90},
    "rotate_180": {"media": (0, 0, *A4), "content": TEXT_AT_ORIGIN, "rotate": 180},
    "rotate_270": {"media": (0, 0, *A4), "content": TEXT_AT_ORIGIN, "rotate": 270},
    "cropped": {"media": (0, 0, *A4), "crop": (50, 100, 545, 800), "content": TEXT_AT_ORIGIN},
    "offset_mediabox": {"media": (100, 100, 100 + A4[0], 100 + A4[1]), "content": TEXT_SHIFTED},
    "offset_cropped_rotate_90": {
        "media": (100, 100, 100 + A4[0], 100 + A4[1]),
        "crop": (150, 200, 645, 900),
        "rotate": 90,
        "content": TEXT_SHIFTED,
    },
    "tiny": {"media": (0, 0, 0.5, 0.5), "content": ""},
}

TEXT_RECT_ON_A4 = (72.17, 757.37, 308.75, 768.74)
L, B, R, T = TEXT_RECT_ON_A4

EXPECTED_PTS = {
    "normal": ((L, A4[1] - T, R, A4[1] - B), A4),
    "rotate_90": ((B, L, T, R), A4[::-1]),
    "rotate_180": ((A4[0] - R, B, A4[0] - L, T), A4),
    "rotate_270": ((A4[1] - T, A4[0] - R, A4[1] - B, A4[0] - L), A4[::-1]),
    "cropped": ((L - 50, 800 - T, R - 50, 800 - B), (495, 700)),
    "offset_mediabox": ((L, A4[1] - T, R, A4[1] - B), A4),
    "offset_cropped_rotate_90": ((B + 100 - 200, L + 100 - 150, T + 100 - 200, R + 100 - 150), (700, 495)),
}

EXPECTED_PER_MILLE = {
    "normal": (121, 86, 518, 100),
    "rotate_90": (899, 121, 913, 518),
    "rotate_180": (481, 899, 878, 913),
    "rotate_270": (86, 481, 100, 878),
    "cropped": (44, 44, 522, 61),
    "offset_mediabox": (121, 86, 518, 100),
    "offset_cropped_rotate_90": (939, 44, 955, 522),
}

TEXT_CASES = list(EXPECTED_PTS)


def _write_pdf(path: Path, pages: list[dict]) -> None:
    objects: list[bytes] = [b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", b""]
    pages_ref = 2
    kids = []
    for page in pages:
        content = page["content"].encode()
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(content), content))
        content_ref = len(objects)
        boxes = b"/MediaBox [%s]" % " ".join(str(v) for v in page["media"]).encode()
        if "crop" in page:
            boxes += b" /CropBox [%s]" % " ".join(str(v) for v in page["crop"]).encode()
        if "rotate" in page:
            boxes += b" /Rotate %d" % page["rotate"]
        objects.append(
            b"<< /Type /Page /Parent %d 0 R %s /Resources << /Font << /F1 1 0 R >> >> /Contents %d 0 R >>"
            % (pages_ref, boxes, content_ref)
        )
        kids.append(len(objects))
    objects[pages_ref - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
    )
    objects.append(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_ref)

    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, len(objects), xref)
    path.write_bytes(bytes(out))


def _rendered_ink_box(file_path: str, page_index: int, scale: int = 4) -> tuple[float, float, float, float]:
    doc = pdfium.PdfDocument(file_path)
    try:
        bitmap = doc[page_index].render(scale=scale, grayscale=True)
        width, height, stride = bitmap.width, bitmap.height, bitmap.stride
        buffer = bytes(bitmap.buffer)
    finally:
        doc.close()
    dark = re.compile(rb"[\x00-\x7f]")
    rows = []
    lefts = []
    rights = []
    for r in range(height):
        row = buffer[r * stride : r * stride + width]
        hits = [m.start() for m in dark.finditer(row)]
        if hits:
            rows.append(r)
            lefts.append(hits[0])
            rights.append(hits[-1])
    assert rows, "nothing was rendered"
    return (min(lefts) / scale, rows[0] / scale, (max(rights) + 1) / scale, (rows[-1] + 1) / scale)


@pytest.fixture(scope="module")
def geometry_pdf(tmp_path_factory) -> str:
    path = tmp_path_factory.mktemp("pdf_geometry") / "geometry.pdf"
    _write_pdf(path, list(PAGES.values()))
    return str(path)


def _page(pages, case: str):
    return pages[list(PAGES).index(case)]


@pytest.fixture(scope="module")
def pts_pages(geometry_pdf):
    return extract_pdf_layout_pts(geometry_pdf)


@pytest.fixture(scope="module")
def per_mille_pages(geometry_pdf):
    return extract_pdf_layout_per_mille(geometry_pdf)


@pytest.fixture(scope="module")
def normalized_pages(geometry_pdf):
    return extract_pdf_layout_normalized(geometry_pdf)


@pytest.mark.parametrize("case", TEXT_CASES)
def test_pts_boxes_are_in_displayed_page_space(pts_pages, case):
    page = _page(pts_pages, case)
    expected_box, (width, height) = EXPECTED_PTS[case]

    assert (page.width, page.height) == (int(width), int(height))
    assert len(page.tokens) == 1
    assert page.tokens[0].box == pytest.approx(expected_box, abs=1.0)


@pytest.mark.parametrize("case", TEXT_CASES)
def test_per_mille_boxes_are_in_displayed_page_space(per_mille_pages, case):
    page = _page(per_mille_pages, case)
    width, height = EXPECTED_PTS[case][1]

    assert (page.width, page.height) == (int(width), int(height))
    assert len(page.tokens) == 1
    assert page.tokens[0].box == pytest.approx(EXPECTED_PER_MILLE[case], abs=2)
    assert all(isinstance(v, int) for v in page.tokens[0].box)


@pytest.mark.parametrize("case", TEXT_CASES)
def test_normalized_boxes_are_in_displayed_page_space(normalized_pages, case):
    page = _page(normalized_pages, case)
    box, (width, height) = EXPECTED_PTS[case]

    expected = (box[0] / width, box[1] / height, box[2] / width, box[3] / height)
    assert page.tokens[0].box == pytest.approx(expected, abs=0.002)


@pytest.mark.parametrize("case", TEXT_CASES)
def test_pts_boxes_match_what_pdfium_renders(geometry_pdf, pts_pages, case):
    ink = _rendered_ink_box(geometry_pdf, list(PAGES).index(case))
    box = _page(pts_pages, case).tokens[0].box

    assert box == pytest.approx(ink, abs=1.0)


def test_unrotated_page_at_origin_matches_previous_mapping(geometry_pdf, per_mille_pages):
    doc = pdfium.PdfDocument(geometry_pdf)
    try:
        page = doc[0]
        width, height = page.get_size()
        text_page = page.get_textpage()
        assert text_page.count_rects() == 1
        left, bottom, right, top = text_page.get_rect(0)
    finally:
        doc.close()

    def scaled(v: float, size: float) -> int:
        return int(max(0, min(1000, 1000 * (v / size))))

    previous = (
        scaled(left, width),
        scaled(height - top, height),
        scaled(right, width),
        scaled(height - bottom, height),
    )
    assert _page(per_mille_pages, "normal").tokens[0].box == previous
    assert _page(per_mille_pages, "offset_mediabox").tokens[0].box == previous


@pytest.mark.parametrize(
    "extract", [extract_pdf_layout_per_mille, extract_pdf_layout_normalized, extract_pdf_layout_pts]
)
def test_pages_under_one_point_report_size_one(geometry_pdf, extract):
    page = _page(extract(geometry_pdf), "tiny")

    assert (page.width, page.height) == (1, 1)
    assert page.tokens == []


MULTI_LINE = "BT /F1 12 Tf 72 760 Td (First line of the page) Tj 0 -40 Td (Second line) Tj 0 -40 Td (Third) Tj ET"
MULTI_LINE_SHIFTED = (
    "BT /F1 12 Tf 172 860 Td (First line of the page) Tj 0 -40 Td (Second line) Tj 0 -40 Td (Third) Tj ET"
)
TEXT_ORDER_PAGES = [
    {"media": (0, 0, *A4), "content": MULTI_LINE},
    {"media": (0, 0, *A4), "content": MULTI_LINE, "rotate": 90},
    {"media": (0, 0, *A4), "content": MULTI_LINE, "rotate": 180},
    {"media": (0, 0, *A4), "content": MULTI_LINE, "rotate": 270},
    {"media": (0, 0, *A4), "crop": (50, 100, 545, 800), "content": MULTI_LINE},
    {"media": (100, 100, 100 + A4[0], 100 + A4[1]), "content": MULTI_LINE_SHIFTED},
    {
        "media": (100, 100, 100 + A4[0], 100 + A4[1]),
        "crop": (150, 200, 645, 900),
        "rotate": 90,
        "content": MULTI_LINE_SHIFTED,
    },
]


def _texts_as_in_0_12_0(file_path: str) -> list[list[str]]:
    doc = pdfium.PdfDocument(file_path)
    try:
        pages = []
        for page in doc:
            text_page = page.get_textpage()
            rects = [text_page.get_rect(j) for j in range(text_page.count_rects())]
            texts = []
            for left, bottom, right, top in rects:
                segment = text_page.get_text_bounded(left, bottom, right, top)
                if segment and segment.strip():
                    texts.append(segment)
            pages.append(texts)
        return pages
    finally:
        doc.close()


@pytest.mark.parametrize(
    "extract", [extract_pdf_layout_per_mille, extract_pdf_layout_normalized, extract_pdf_layout_pts]
)
def test_token_texts_and_order_are_unchanged_by_geometry(tmp_path, extract):
    path = tmp_path / "text_order.pdf"
    _write_pdf(path, TEXT_ORDER_PAGES)

    expected = _texts_as_in_0_12_0(str(path))
    got = [[token.text for token in page.tokens] for page in extract(str(path))]

    assert expected[0] == ["First line of the page", "Second line", "Third"]
    assert got == expected
    assert all(sorted(page_texts) == sorted(expected[0]) for page_texts in got)
