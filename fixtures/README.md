# Fixtures

`uv run python scripts/generate_fixtures.py` tạo `synthetic_tutorial.mp4` bằng FFmpeg testsrc2, 6 giây, 960×540, 10 FPS, không audio. `annotation.json` mô tả ground truth kỹ thuật. Nội dung là test pattern tổng hợp, không có bước tutorial, không được dùng để tuyên bố chất lượng Gemini.

Integration test tự tạo video 4 giây trong temp, chia chunk 3 giây/overlap 1 giây để kiểm tra timeline bằng FFmpeg thật. Test MOV/WebM tạo container thật từ clip tổng hợp. Test duration giảm giới hạn cấu hình xuống 1 giây, không gửi AI.

Bộ 5 tutorial phần mềm theo mục 15.4 của `PROJECT_SPEC.md` và bộ 8 video nhiều lĩnh vực của spec ngày 22/10/2026 đều chưa được cung cấp, chưa chạy. Với bộ 8 video, đáp án ghi theo `fixtures/eval/README.md` và kết quả vào `docs/evaluation-template.md`, trước khi xem output. Không đưa video riêng tư hoặc raw provider output vào Git.

Generator cũng tạo `synthetic_long.mp4` (305 giây, 128×72, 1 FPS) và `synthetic_overlimit.mp4` (1201 giây). Đây là màu tĩnh tổng hợp để xác nhận timeline chunk 0–300 / 295–305 bằng FFmpeg thật và từ chối video >20 phút. Không dùng để đo chất lượng nội dung hoặc chứng minh đạt rubric 5 tutorial thật.
