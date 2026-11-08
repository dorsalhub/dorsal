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

import ctypes
from pathlib import Path

import pytest

pdfium = pytest.importorskip("pypdfium2")

from dorsal.file.preprocessing import pdf as dorsal_pdf  # noqa: E402

REAL_GET_BOUNDED_TEXT = pdfium.raw.FPDFText_GetBoundedText

TO_UNICODE = {
    0x41: "D835DC00",
    0x42: "0007",
    0x43: "0000",
    0x44: "D83DDE00",
    0x45: "DC00",
    0x46: "D800",
    0x47: "000B",
    0x48: "00E9",
    0x49: "4E2D",
}

PLAIN = "(The quick brown fox) Tj"
SPECIAL = "(xAyBzCwDvEuFtGsHrI) Tj"
LINES = [
    f"BT /F1 12 Tf 72 760 Td {PLAIN} ET",
    f"BT /F1 12 Tf 72 740 Td {SPECIAL} ET",
    f"BT /F1 12 Tf 80 742 Td {PLAIN} ET",
    f"BT /F1 12 Tf 72 720 Td {SPECIAL} 0 -14 Td {PLAIN} 0 -14 Td (AAAA) Tj ET",
    f"BT /F1 30 Tf 60 600 Td ({'ADA' * 40}) Tj ET",
    "BT /F1 12 Tf 72 500 Td [(Wide) -900 (Kerned) 250 (Gaps)] TJ ET",
    f"BT /F1 9 Tf 0.9 0.4 -0.4 0.9 300 300 Tm {SPECIAL} ET",
    f"BT /F1 12 Tf 700 900 Td {PLAIN} ET",
    "BT /F1 12 Tf 72 400 Td ( ) Tj ET",
    "BT /F1 12 Tf 72 380 Td (qFEpFFEEo) Tj ET",
]
CONTENT = "\n".join(LINES)
ASTRAL_CONTENT = "\n".join(
    [
        "BT /F2 12 Tf 72 760 Td (AAAAABBBBB) Tj ET",
        "BT /F2 12 Tf 72 700 Td (BABA) Tj ET",
        "BT /F2 12 Tf 72 600 Td (BBBxyz) Tj ET",
        "BT /F2 12 Tf 72 650 Td (xyzBBB) Tj ET",
        f"BT /F1 12 Tf 72 500 Td {PLAIN} ET",
    ]
)
A4 = (595.276, 841.89)
PAGES = [
    {"media": (0, 0, *A4)},
    {"media": (0, 0, *A4), "rotate": 90},
    {"media": (0, 0, *A4), "rotate": 180},
    {"media": (0, 0, *A4), "rotate": 270},
    {"media": (100, 100, 100 + A4[0], 100 + A4[1]), "crop": (150, 200, 645, 900), "rotate": 90},
    {"media": (-50, -50, A4[0] - 50, A4[1] - 50)},
    {"media": (0, 0, *A4), "content": ASTRAL_CONTENT},
    {"media": (0, 0, *A4), "content": ""},
]
ASTRAL_PAGE = len(PAGES) - 2


def _cmap() -> bytes:
    entries = "\n".join(f"<{code:02X}> <{target}>" for code, target in TO_UNICODE.items())
    return (
        "/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Adobe-Identity-UCS def /CMapType 2 def\n"
        "1 begincodespacerange <00> <FF> endcodespacerange\n"
        f"{len(TO_UNICODE)} beginbfchar\n{entries}\nendbfchar\n"
        "endcmap CMapName currentdict /CMap defineresource pop end end\n"
    ).encode()


def _stream(data: bytes) -> bytes:
    return b"<< /Length %d >>\nstream\n%s\nendstream" % (len(data), data)


def _write_pdf(path: Path) -> None:
    objects: list[bytes] = [
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 3 0 R >>",
        b"",
        _stream(_cmap()),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica"
        b" /Encoding << /Type /Encoding /Differences [65 /u1D400 66 /u1F600] >> >>",
    ]
    kids = []
    for page in PAGES:
        content = page.get("content", CONTENT).encode()
        objects.append(_stream(content))
        content_ref = len(objects)
        entries = [
            b"/Type /Page /Parent 2 0 R",
            b"/MediaBox [%s]" % " ".join(str(v) for v in page["media"]).encode(),
            b"/Resources << /Font << /F1 1 0 R /F2 4 0 R >> >>",
            b"/Contents %d 0 R" % content_ref,
        ]
        if "crop" in page:
            entries.append(b"/CropBox [%s]" % " ".join(str(v) for v in page["crop"]).encode())
        if "rotate" in page:
            entries.append(b"/Rotate %d" % page["rotate"])
        objects.append(b"<< " + b" ".join(entries) + b" >>")
        kids.append(len(objects))
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % k for k in kids),
        len(kids),
    )
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, len(objects), xref)
    path.write_bytes(bytes(out))


@pytest.fixture(scope="module")
def special_pdf(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("bounded") / "special.pdf"
    _write_pdf(path)
    return path


@pytest.fixture
def bounded_calls(monkeypatch):
    calls = []
    real = pdfium.raw.FPDFText_GetBoundedText

    def counting(*args):
        calls.append(args[-1])
        return real(*args)

    monkeypatch.setattr(pdfium.raw, "FPDFText_GetBoundedText", counting)
    return calls


def _full_text(text_page, rect) -> str:
    size = 4096
    buffer = (ctypes.c_ushort * size)()
    left, bottom, right, top = rect
    units = REAL_GET_BOUNDED_TEXT(text_page, left, top, right, bottom, buffer, size)
    return ctypes.string_at(buffer, 2 * max(units - 1, 0)).decode("utf-16-le", "surrogatepass")


def _has_surrogates(text: str) -> bool:
    return any(0xD800 <= ord(c) <= 0xDFFF or ord(c) > 0xFFFF for c in text)


def _probe_rects(text_page) -> list[tuple[float, float, float, float]]:
    rects = [text_page.get_rect(j) for j in range(text_page.count_rects())]
    extra = [
        (0.0, 0.0, 2000.0, 2000.0),
        (-500.0, -500.0, 5000.0, 5000.0),
        (72.0, 700.0, 300.0, 770.0),
        (300.0, 770.0, 72.0, 700.0),
        (100.0, 735.0, 100.0, 745.0),
        (1e9, 1e9, 2e9, 2e9),
        (60.0, 590.0, 600.0, 640.0),
    ]
    overlapping = [(left - 3, bottom - 3, right + 40, top + 15) for left, bottom, right, top in rects]
    return rects + extra + overlapping


def test_reader_matches_pypdfium_on_every_rectangle(special_pdf, bounded_calls):
    doc = pdfium.PdfDocument(str(special_pdf))
    checked = astral = 0
    try:
        for index, page in enumerate(doc):
            text_page = page.get_textpage()
            rects = _probe_rects(text_page)
            expected = [text_page.get_text_bounded(*rect) for rect in rects]
            read = dorsal_pdf._BoundedTextReader(text_page)
            for rect, native in zip(rects, expected, strict=True):
                has_surrogates = _has_surrogates(_full_text(text_page, rect))
                bounded_calls.clear()
                assert read(*rect) == native
                assert bounded_calls[0] > 0
                assert bounded_calls[1:] == ([0] if has_surrogates and not dorsal_pdf._WCHAR_IS_UTF16 else [])
                astral += has_surrogates and index != ASTRAL_PAGE
                checked += 1
    finally:
        doc.close()
    assert checked > 100
    assert astral > 10


def test_reader_text_has_controls_nul_and_surrogates(special_pdf):
    doc = pdfium.PdfDocument(str(special_pdf))
    try:
        text_page = doc[0].get_textpage()
        texts = [dorsal_pdf._BoundedTextReader(text_page)(*rect) for rect in _probe_rects(text_page)]
    finally:
        doc.close()
    joined = "".join(texts)
    assert "\x07" in joined and "\x0b" in joined and "\r\n" in joined and "é" in joined
    assert _has_surrogates(joined)


@pytest.mark.parametrize(
    "extract",
    [
        dorsal_pdf.extract_pdf_layout_per_mille,
        dorsal_pdf.extract_pdf_layout_normalized,
        dorsal_pdf.extract_pdf_layout_pts,
    ],
)
def test_layout_text_matches_pypdfium_with_one_text_page_per_page(special_pdf, extract, mocker):
    doc = pdfium.PdfDocument(str(special_pdf))
    try:
        expected = []
        for page in doc:
            text_page = page.get_textpage()
            rects = [text_page.get_rect(j) for j in range(text_page.count_rects())]
            texts = [text_page.get_text_bounded(*rect) for rect in rects]
            expected.append(([t for t in texts if t and t.strip()], page.get_textpage().get_text_range()))
    finally:
        doc.close()

    load_page = mocker.spy(pdfium.raw, "FPDFText_LoadPage")
    pages = extract(str(special_pdf))

    assert load_page.call_count == len(PAGES)
    assert [([token.text for token in page.tokens], page.raw_text) for page in pages] == expected
    assert sum(len(page.tokens) for page in pages) > 30
    assert pages[-1].tokens == [] and pages[-1].raw_text == ""


def test_reader_falls_back_when_the_buffer_is_full(special_pdf, monkeypatch):
    doc = pdfium.PdfDocument(str(special_pdf))
    try:
        text_page = doc[0].get_textpage()
        rect = _probe_rects(text_page)[0]
        expected = text_page.get_text_bounded(*rect)
        read = dorsal_pdf._BoundedTextReader(text_page)
        monkeypatch.setattr(read, "_size", 3)
        assert len(expected) > 3
        assert read(*rect) == expected
    finally:
        doc.close()


def test_reader_matches_pypdfium_where_pdfium_measures_less_than_it_fills(special_pdf):
    doc = pdfium.PdfDocument(str(special_pdf))
    shorter = []
    split_pairs = 0
    try:
        text_page = doc[ASTRAL_PAGE].get_textpage()
        read = dorsal_pdf._BoundedTextReader(text_page)
        for rect in _probe_rects(text_page):
            left, bottom, right, top = rect
            measured = REAL_GET_BOUNDED_TEXT(text_page, left, top, right, bottom, None, 0)
            filled = _full_text(text_page, rect).encode("utf-16-le", "surrogatepass")
            expected = text_page.get_text_bounded(*rect)
            assert read(*rect) == expected
            if 0 < measured < len(filled) // 2:
                shorter.append(expected)
                split_pairs += 0xD800 <= int.from_bytes(filled[2 * measured - 2 : 2 * measured], "little") <= 0xDBFF
    finally:
        doc.close()
    if dorsal_pdf._WCHAR_IS_UTF16:
        assert shorter == [], "a 16-bit wchar_t makes pdfium measure in UTF-16 units, so measure equals fill"
    else:
        assert "\U0001d400" * 5 in shorter, "pdfium no longer measures astral text shorter than it fills"
        assert split_pairs > 0, "pdfium no longer cuts astral text inside a surrogate pair"
