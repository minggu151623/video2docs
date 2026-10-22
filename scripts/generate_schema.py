import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "backend"))
from app.schemas.tutorial import TutorialDraftV1

(root / "frontend/src/types/tutorial.schema.json").write_text(
    json.dumps(TutorialDraftV1.model_json_schema(), indent=2)
)
