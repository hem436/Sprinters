"""Images (phone photos of handwritten notes, scans): one page, class SCANNED, always OCR (contract 10 X2, X5).

`ImageOps.exif_transpose` first: phone photos are often stored rotated with an EXIF orientation tag.
"""
from pathlib import Path

from PIL import Image

from ingestion.config import ExtractConfig
from ingestion.layout import SectionTracker
from ingestion.ocr import OcrEngine, OcrFailed, ocr_to_blocks, prepare_image
from ingestion.types import PageResult


def extract_image(path: Path | str, cfg: ExtractConfig, ocr: OcrEngine | None, progress=None) -> list[PageResult]:
    result = PageResult(page=1, page_class="SCANNED", method="ocr")
    if progress:
        progress("ocr", 1, 1)
    if ocr is None:
        result.flags.append("OCR_FAILED")
        result.signals["ocr_error"] = "no OCR engine configured"
        return [result]
    with Image.open(path) as raw:
        image = prepare_image(raw, cfg.ocr_max_edge_px)
        result.signals = {"width": image.size[0], "height": image.size[1]}
        try:
            out = ocr.read(image)
        except OcrFailed as e:
            result.flags.append("OCR_FAILED")
            result.signals["ocr_error"] = str(e)[:200]
            result.ocr = e.usage
            return [result]
    result.ocr = out.usage
    result.ocr_result = out
    result.blocks = ocr_to_blocks(out, SectionTracker())
    result.chars = sum(len(b.text) for b in result.blocks)
    return [result]
