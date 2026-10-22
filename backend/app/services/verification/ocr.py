"""Local on-screen text recognition. PaddleOCR is imported and loaded on first use."""

import os
from pathlib import Path

DETECTION_MODEL = "PP-OCRv5_mobile_det"
DEFAULT_RECOGNITION_MODEL = "en_PP-OCRv5_mobile_rec"
KOREAN_RECOGNITION_MODEL = "korean_PP-OCRv5_mobile_rec"
KOREAN_CODES = {"ko", "kor", "korean"}


def recognition_model(language):
    if language and language.strip().lower() in KOREAN_CODES:
        return KOREAN_RECOGNITION_MODEL
    return DEFAULT_RECOGNITION_MODEL


def reading_order(texts, boxes):
    """Top-to-bottom rows, left-to-right inside a row; boxes are (x1, y1, x2, y2)."""
    items = []
    for text, box in zip(texts, boxes):
        text = str(text).strip()
        if text:
            x1, y1, x2, y2 = (float(v) for v in box)
            items.append((text, x1, (y1 + y2) / 2, max(y2 - y1, 1.0)))
    items.sort(key=lambda item: item[2])
    rows = []
    for item in items:
        if rows and abs(item[2] - rows[-1]["y"]) <= 0.5 * min(item[3], rows[-1]["height"]):
            row = rows[-1]
            row["items"].append(item)
            row["y"] = sum(i[2] for i in row["items"]) / len(row["items"])
            row["height"] = min(row["height"], item[3])
        else:
            rows.append({"items": [item], "y": item[2], "height": item[3]})
    return [item[0] for row in rows for item in sorted(row["items"], key=lambda i: i[1])]


class OCR:
    def __init__(self, settings=None):
        self.settings = settings
        self._pipelines = {}

    def _pipeline(self, language):
        rec = recognition_model(language)
        if rec not in self._pipelines:
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            from paddleocr import PaddleOCR

            self._pipelines[rec] = PaddleOCR(
                text_detection_model_name=DETECTION_MODEL,
                text_recognition_model_name=rec,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        return self._pipelines[rec]

    def read(self, image: Path, language: str | None = None) -> str:
        lines = []
        for result in self._pipeline(language).predict(str(image)):
            texts = list(result["rec_texts"])
            boxes = result["rec_boxes"]
            boxes = boxes.tolist() if hasattr(boxes, "tolist") else list(boxes)
            lines.extend(reading_order(texts, boxes))
        return "\n".join(lines)


def get_ocr(settings):
    return OCR(settings) if settings.ocr_engine == "paddleocr" else None
