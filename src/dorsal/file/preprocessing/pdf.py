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

from contextlib import contextmanager
from dataclasses import dataclass
import logging
from typing import Any, Generic, Generator, TypeVar

from dorsal.common.exceptions import DependencyError, PDFProcessingError

logger = logging.getLogger(__name__)

CoordType = TypeVar("CoordType", int, float)


@dataclass(slots=True, frozen=True)
class PDFToken(Generic[CoordType]):
    """A single text string with its bounding box."""

    text: str
    box: tuple[CoordType, CoordType, CoordType, CoordType]


@dataclass(slots=True, frozen=True)
class PDFPage(Generic[CoordType]):
    """A single PDF page."""

    page_number: int
    width: int
    height: int
    tokens: list[PDFToken[CoordType]]
    raw_text: str


@contextmanager
def _pdfium_open_pdf(file_path: str, password: str | None) -> Generator[Any, None, None]:
    try:
        import pypdfium2 as pdfium  # type: ignore
    except ImportError as err:
        raise DependencyError("The 'pypdfium2' library is required. Install via: pip install pypdfium2") from err

    pdf = None
    try:
        pdf = pdfium.PdfDocument(file_path, password=password)
        yield pdf
    except PDFProcessingError:
        raise
    except Exception as err:
        logger.exception("Unexpected error extracting layout from '%s'", file_path)
        raise PDFProcessingError(f"Unexpected error processing '{file_path}'") from err
    finally:
        if pdf:
            try:
                pdf.close()
            except Exception:
                pass


def extract_pdf_text(file_path: str, password: str | None = None) -> list[str]:
    """
    Extracts raw text from a PDF file, page by page.

    This is a high-level helper designed for text-analysis models that does *not* require
        spatial layout information (bounding boxes).

    Args:
        file_path: Path to the PDF file.
        password: Password for encrypted PDFs.

    Returns:
        list[str]: A list of strings, where each string is the raw text content of a single page.

    Example:
        >>> pages = extract_pdf_text("contract.pdf")
        >>> print(pages[0])
        "2023-01-03\nLEGAL CONTRACT\nRegarding..."
    """
    logger.debug("Extracting raw text from: '%s'", file_path)
    results: list[str] = []

    with _pdfium_open_pdf(file_path, password) as pdf:
        for page in pdf:
            try:
                text_page = page.get_textpage()
                page_text = text_page.get_text_range()
                results.append(page_text)
            except Exception as e:
                logger.warning("Failed to extract text from a page in '%s': %s", file_path, e)
                results.append("")

    return results


def extract_pdf_layout_per_mille(
    file_path: str,
    password: str | None = None,
    strict: bool = False,
) -> list[PDFPage[int]]:
    """
    Extracts text and layout (bounding boxes) scaled to the 0-1000 'per_mille' integer standard.

    This is the standard input format for models like LayoutLM (v1/v2/v3), LiLT,
    and Donut, which require integer coordinates discretized to a 1000x1000 grid.

    Coordinates:
        - Origin: Top-Left (0, 0)
        - Unit: Integer (0 to 1000)
        - Format: [x0, y0, x1, y1]

    Args:
        file_path: Path to the PDF file.
        password: Password for encrypted PDFs.

    Returns:
        list of PDFPage objects containing integer coordinates.
    """
    logger.debug("Extracting layout (per_mille) from: '%s'", file_path)
    results: list[PDFPage[int]] = []

    with _pdfium_open_pdf(file_path, password) as pdf:
        for i, page in enumerate(pdf):
            width_pt, height_pt = page.get_size()

            if width_pt <= 0 or height_pt <= 0:
                msg = (
                    f"Page {i + 1} in '{file_path}' has invalid dimensions (w={width_pt}, h={height_pt}). "
                    "Cannot calculate scale."
                )
                if strict:
                    raise PDFProcessingError(msg)

                logger.warning(f"{msg} Coordinates will be clamped to 1000 (Data Loss).")

            text_page = page.get_textpage()

            w_s = width_pt if width_pt > 0 else 1
            h_s = height_pt if height_pt > 0 else 1
            scale = 1000

            tokens: list[PDFToken[int]] = []
            rects = [text_page.get_rect(j) for j in range(text_page.count_rects())]

            for left, bottom, right, top in rects:
                text_segment = text_page.get_text_bounded(left, bottom, right, top)
                if not text_segment or not text_segment.strip():
                    continue

                x0, x1 = left, right
                y0, y1 = height_pt - top, height_pt - bottom

                box_int = (
                    int(max(0, min(scale, scale * (x0 / w_s)))),
                    int(max(0, min(scale, scale * (y0 / h_s)))),
                    int(max(0, min(scale, scale * (x1 / w_s)))),
                    int(max(0, min(scale, scale * (y1 / h_s)))),
                )
                tokens.append(PDFToken(text=text_segment, box=box_int))

            results.append(
                PDFPage(
                    page_number=i + 1,
                    width=int(width_pt),
                    height=int(height_pt),
                    tokens=tokens,
                    raw_text=page.get_textpage().get_text_range(),
                )
            )
    return results


def extract_pdf_layout_normalized(
    file_path: str, password: str | None = None, strict: bool = False
) -> list[PDFPage[float]]:
    """
    Extracts text and layout (bounding boxes) normalized to 0.0-1.0 floats.

    Useful for resolution-independent geometry processing or Computer Vision
    models (like YOLO/R-CNN) that expect relative coordinates.

    Coordinates:
        - Origin: Top-Left (0, 0)
        - Unit: Float (0.0 to 1.0)
        - Format: [x0, y0, x1, y1]

    Args:
        file_path: Path to the PDF file.
        password: Password for encrypted PDFs.

    Returns:
        list of PDFPage objects containing float coordinates.
    """
    logger.debug("Extracting layout (normalized) from: '%s'", file_path)
    results: list[PDFPage[float]] = []

    with _pdfium_open_pdf(file_path, password) as pdf:
        for i, page in enumerate(pdf):
            width_pt, height_pt = page.get_size()

            if width_pt <= 0 or height_pt <= 0:
                msg = (
                    f"Page {i + 1} in '{file_path}' has invalid dimensions (w={width_pt}, h={height_pt}). "
                    "Cannot normalize coordinates."
                )
                if strict:
                    raise PDFProcessingError(msg)

                logger.warning(f"{msg} Coordinates will likely exceed 1.0.")

            text_page = page.get_textpage()

            w_s = width_pt if width_pt > 0 else 1
            h_s = height_pt if height_pt > 0 else 1

            tokens: list[PDFToken[float]] = []
            rects = [text_page.get_rect(j) for j in range(text_page.count_rects())]

            for left, bottom, right, top in rects:
                text_segment = text_page.get_text_bounded(left, bottom, right, top)
                if not text_segment or not text_segment.strip():
                    continue

                x0, x1 = left, right
                y0, y1 = height_pt - top, height_pt - bottom

                box_float = (float(x0 / w_s), float(y0 / h_s), float(x1 / w_s), float(y1 / h_s))
                tokens.append(PDFToken(text=text_segment, box=box_float))

            results.append(
                PDFPage(
                    page_number=i + 1,
                    width=int(width_pt),
                    height=int(height_pt),
                    tokens=tokens,
                    raw_text=page.get_textpage().get_text_range(),
                )
            )
    return results


def extract_pdf_layout_pts(file_path: str, password: str | None = None, strict: bool = False) -> list[PDFPage[float]]:
    """
    Extracts text and layout using raw PDF Points (pt).

    Note: While PDF uses a Bottom-Left origin internally, this function
    transforms coordinates to Top-Left origin to match standard computer
    vision and web coordinate systems.

    Coordinates:
        - Origin: Top-Left (0, 0)
        - Unit: PDF Points (1/72 inch) - Float
        - Format: [x0, y0, x1, y1]

    Args:
        file_path: Path to the PDF file.
        password: Password for encrypted PDFs.

    Returns:
        list of PDFPage objects containing float coordinates.
    """
    logger.debug("Extracting layout (pts) from: '%s'", file_path)
    results: list[PDFPage[float]] = []

    with _pdfium_open_pdf(file_path, password) as pdf:
        for i, page in enumerate(pdf):
            width_pt, height_pt = page.get_size()

            if width_pt <= 0 or height_pt <= 0:
                msg = f"Page {i + 1} in '{file_path}' has invalid dimensions (w={width_pt}, h={height_pt})."
                if strict:
                    raise PDFProcessingError(f"{msg} Cannot calculate valid origin transform.")

                logger.warning(f"{msg} Y-coordinates may be negative.")

            text_page = page.get_textpage()

            tokens: list[PDFToken[float]] = []
            rects = [text_page.get_rect(j) for j in range(text_page.count_rects())]

            for left, bottom, right, top in rects:
                text_segment = text_page.get_text_bounded(left, bottom, right, top)
                if not text_segment or not text_segment.strip():
                    continue

                x0, x1 = left, right
                y0, y1 = height_pt - top, height_pt - bottom

                box_float = (float(x0), float(y0), float(x1), float(y1))
                tokens.append(PDFToken(text=text_segment, box=box_float))

            results.append(
                PDFPage(
                    page_number=i + 1,
                    width=int(width_pt),
                    height=int(height_pt),
                    tokens=tokens,
                    raw_text=page.get_textpage().get_text_range(),
                )
            )
    return results


def extract_pdf_pages(
    file_path: str,
    scale: float = 2.0,
    password: str | None = None,
    pages: list[int] | None = None,
) -> Generator[Any, None, None]:
    """
    Yields PDF pages as `PIL.Image.Image`.

    Args:
        file_path: Path to the PDF file.
        scale: Rasterization scale. 1.0 ~= 72 DPI. 2.0 ~= 144 DPI (Recommended for OCR/VDU).
        password: Password for encrypted PDFs.
        pages: Optional list of 0-indexed page numbers to render. If None, renders all.

    Yields:
        PIL.Image.Image: A Pillow image object for the page.

    Raises:
        PDFProcessingError: If the file cannot be read.
        DependencyError: If 'pypdfium2' or 'Pillow' are missing.
    """
    try:
        import pypdfium2 as pdfium  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError as err:
        raise DependencyError(
            "Libraries 'pypdfium2' and 'Pillow' are required for PDF rendering. Full error: {err}"
        ) from err

    pdf = None
    try:
        logger.debug("Rendering pages for PDF: '%s' (Scale: %.1f)", file_path, scale)
        pdf = pdfium.PdfDocument(file_path, password=password)

        n_pages = len(pdf)
        target_indices = pages if pages is not None else range(n_pages)

        for i in target_indices:
            if i < 0 or i >= n_pages:
                logger.warning("Skipping invalid page index %d (Max: %d)", i, n_pages - 1)
                continue

            page = pdf[i]
            bitmap = page.render(scale=scale, rotation=0)
            pil_image = bitmap.to_pil()
            yield pil_image

    except Exception as err:
        logger.error("Error rendering PDF '%s': %s", file_path, err)
        raise PDFProcessingError(f"Error rendering PDF: {err}") from err
    finally:
        if pdf:
            try:
                pdf.close()
            except Exception:
                pass


def ocr_extract_pdf_text(
    file_path: str,
    language: str = "eng",
    password: str | None = None,
    render_scale: float = 3.0,
    config: str = "",
) -> list[str]:
    """
    Extracts text from a PDF using Optical Character Recognition (Tesseract).

    This function renders the PDF to high-resolution images and then runs Tesseract on each page.
    It is suitable for scanned documents where `extract_pdf_text` returns empty strings.

    Args:
        file_path: Path to the PDF file.
        language: Tesseract language code (e.g., 'eng', 'deu', 'fra').
        password: Password for encrypted PDFs.
        render_scale: Rasterization scale factor.
                      1.0 ~= 72 DPI (Fast, low accuracy).
                      3.0 ~= 216 DPI (Recommended default).
                      4.17 ~= 300 DPI (High accuracy, slower).
        config: Optional Tesseract config string (e.g., '--psm 6').


    Returns:
        list[str]: A list of strings, where each string is the OCR text of a page.

    Raises:
        DependencyError: If `pytesseract` is not installed OR if the Tesseract
                         binary is not found in the system PATH.
        PDFProcessingError: If the PDF cannot be read or rendered.
    """
    try:
        import pytesseract  # type: ignore
    except ImportError as err:
        raise DependencyError(
            "The 'pytesseract' library is required for OCR. Install via: pip install pytesseract"
        ) from err

    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError as err:
        raise DependencyError(
            "The Tesseract OCR engine is not installed or not in your PATH.\n"
            "Please install the binary for your operating system:\n"
            "-> https://tesseract-ocr.github.io/tessdoc/Installation.html"
        ) from err
    except Exception as err:
        raise DependencyError(f"Unable to execute Tesseract binary: {err}") from err

    logger.debug("Starting OCR extraction for: '%s' (Lang: %s)", file_path, language)
    results: list[str] = []

    try:
        page_generator = extract_pdf_pages(file_path, scale=render_scale, password=password)

        for i, page_image in enumerate(page_generator):
            try:
                page_text = pytesseract.image_to_string(page_image, lang=language, config=config)
                results.append(page_text)
            except pytesseract.TesseractError as e:
                logger.warning("OCR failed on page %d of '%s': %s", i + 1, file_path, e)
                results.append("")

    except Exception as err:
        logger.error("Error during OCR rendering/processing for '%s': %s", file_path, err)
        raise PDFProcessingError(f"OCR failed: {err}") from err

    logger.debug("OCR complete. Extracted %d pages.", len(results))
    return results
