"""Generate owned synthetic media with known timing; no provider call."""

import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "fixtures"
root.mkdir(exist_ok=True)
command = [
    "ffmpeg",
    "-v",
    "error",
    "-y",
    "-f",
    "lavfi",
    "-i",
    "testsrc2=size=960x540:rate=10:duration=6",
    "-c:v",
    "libx264",
    "-threads",
    "2",
    "-pix_fmt",
    "yuv420p",
    str(root / "synthetic_tutorial.mp4"),
]
subprocess.run(command, check=True)
for filename, duration in [("synthetic_long.mp4", 305), ("synthetic_overlimit.mp4", 1201)]:
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x315c48:s=128x72:r=1:d={duration}",
            "-c:v",
            "libx264",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            str(root / filename),
        ],
        check=True,
    )
(root / "annotation.json").write_text(
    json.dumps(
        {
            "license": "Project-generated synthetic fixture",
            "quality_evaluation": "Not a real user tutorial and not a Gemini quality benchmark",
            "reference": {
                "duration_sec": 6,
                "fps": 10,
                "has_audio": False,
                "content": "FFmpeg testsrc2 test pattern; contains no tutorial steps",
            },
        },
        indent=2,
    )
)
