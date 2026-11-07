from app.schemas.tutorial_v2 import TutorialDraftV2

NOT_TUTORIAL_PREFIX = "mock-not-tutorial"
TWO_STEPS_PREFIX = "mock-two-steps"


class MockProvider:
    """Synthetic plumbing fixture; never represents actual video understanding."""

    field_names = {}

    def __init__(self, settings):
        self.settings = settings

    def check(self):
        return {"model": "mock-fixture", "video_smoke": "mock only"}

    def upload(self, path, record, check_cancel):
        check_cancel()
        return None

    def analyze(self, reference, duration, language, metadata, repair=None):
        name = str(metadata.get("original_name") or "")
        if name.startswith(NOT_TUTORIAL_PREFIX):
            draft = self.not_tutorial(language)
        else:
            draft = self.tutorial(duration, language, extra_step=name.startswith(TWO_STEPS_PREFIX))
        return {
            "text": draft.model_dump_json(by_alias=True),
            "usage": None,
            "model": "mock-fixture",
            "request_id": None,
            "error": None,
        }

    @staticmethod
    def not_tutorial(language):
        return TutorialDraftV2.model_validate(
            {
                "schema_version": "2.0",
                "is_tutorial": False,
                "not_tutorial_reason": "MOCK: không phải tutorial",
                "domain": "other",
                "yield": None,
                "title": "MOCK: Video không phải hướng dẫn",
                "summary": "Dữ liệu tổng hợp mô phỏng video không phải hướng dẫn.",
                "language": language,
                "objectives": [],
                "prerequisites": [],
                "safety": [],
                "materials": [],
                "equipment": [],
                "steps": [],
                "troubleshooting": [],
                "uncertainties": [],
            }
        )

    @staticmethod
    def tutorial(duration, language, extra_step=False):
        end = min(duration, 2)
        audio = {"start_sec": 0, "end_sec": end, "source": "audio", "description": "Lời nói tổng hợp."}
        screen = {"start_sec": 0, "end_sec": end, "source": "visual", "description": "Chữ tổng hợp."}
        data = {
            "schema_version": "2.0",
            "is_tutorial": True,
            "not_tutorial_reason": None,
            "domain": "other",
            "yield": None,
            "title": "MOCK: Tài liệu kiểm thử luồng",
            "summary": "Dữ liệu tổng hợp để kiểm thử ứng dụng; chưa phân tích nội dung video.",
            "language": language,
            "objectives": [],
            "prerequisites": [],
            "safety": [],
            "materials": [
                {
                    "name": "MOCK: vật liệu mẫu",
                    "quantity": "2",
                    "unit": "gói",
                    "note": None,
                    "evidence_spans": [screen],
                    "basis": "observed",
                    "quote": None,
                    "on_screen_text": "2 gói",
                }
            ],
            "equipment": [],
            "steps": [
                {
                    "local_id": "fixture-step",
                    "title": "MOCK: kiểm tra frame nguồn",
                    "start_sec": 0,
                    "end_sec": end,
                    "actions": ["Đối chiếu frame với video do bạn tải lên."],
                    "expected_result": None,
                    "parameters": [
                        {
                            "name": "MOCK: thông số mẫu",
                            "value": "5",
                            "unit": "phút",
                            "evidence_spans": [audio],
                            "basis": "stated",
                            "quote": "năm phút",
                            "on_screen_text": None,
                        }
                    ],
                    "exact_inputs": [],
                    "warnings": [],
                    "tips": [],
                    "evidence_spans": [
                        {
                            "start_sec": 0,
                            "end_sec": end,
                            "source": "visual",
                            "description": "Mốc tổng hợp để kiểm tra trích frame thật.",
                        }
                    ],
                    "screenshot_candidates_sec": [end / 2],
                    "needs_review": True,
                    "review_reason": "Mock không có khả năng hiểu video.",
                },
            ],
            "troubleshooting": [],
            "uncertainties": [
                {"description": "MOCK: chưa có phân tích AI thật.", "start_sec": None, "end_sec": None}
            ],
        }
        if extra_step:
            data["steps"].append(
                {
                    **data["steps"][0],
                    "local_id": "fixture-step-2",
                    "title": "MOCK: bước không có mục cần kiểm chứng",
                    "actions": ["Bước chỉ có thao tác, không có thông số hay lời trích."],
                    "parameters": [],
                    "needs_review": False,
                    "review_reason": None,
                }
            )
        return TutorialDraftV2.model_validate(data, context={"duration": duration})

    @staticmethod
    def decode(text):
        return text

    def delete(self, name):
        return None

    def close(self):
        pass
