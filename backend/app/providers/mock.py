from app.schemas.tutorial_v2 import TutorialDraftV2


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
        end = min(duration, 2)
        draft = TutorialDraftV2.model_validate(
            {
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
                "materials": [],
                "equipment": [],
                "steps": [
                    {
                        "local_id": "fixture-step",
                        "title": "MOCK: kiểm tra frame nguồn",
                        "start_sec": 0,
                        "end_sec": end,
                        "actions": ["Đối chiếu frame với video do bạn tải lên."],
                        "expected_result": None,
                        "parameters": [],
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
                    }
                ],
                "troubleshooting": [],
                "uncertainties": [
                    {"description": "MOCK: chưa có phân tích AI thật.", "start_sec": None, "end_sec": None}
                ],
            },
            context={"duration": duration},
        )
        return {
            "text": draft.model_dump_json(by_alias=True),
            "usage": None,
            "model": "mock-fixture",
            "request_id": None,
            "error": None,
        }

    @staticmethod
    def decode(text):
        return text

    def delete(self, name):
        return None

    def close(self):
        pass
