# Fixtures

`uv run python scripts/generate_fixtures.py` tạo `synthetic_tutorial.mp4` bằng FFmpeg testsrc2, 6 giây, 960×540, 10 FPS, không audio. `annotation.json` mô tả ground truth kỹ thuật. Nội dung là test pattern tổng hợp, không có bước tutorial, không được dùng để tuyên bố chất lượng Gemini.

Integration test tự tạo video 4 giây trong temp, chia chunk 3 giây/overlap 1 giây để kiểm tra timeline bằng FFmpeg thật. Test MOV/WebM tạo container thật từ clip tổng hợp. Test duration giảm giới hạn cấu hình xuống 1 giây, không gửi AI.

Bộ 5 tutorial có quyền sử dụng và đánh giá >5 phút theo mục 15.4 chưa được cung cấp. Dùng `docs/evaluation-template.md` để ghi annotation trước khi xem output. Không đưa video riêng tư hoặc raw provider output vào Git.

Generator cũng tạo `synthetic_long.mp4` (305 giây, 128×72, 1 FPS) và `synthetic_overlimit.mp4` (1201 giây). Đây là màu tĩnh tổng hợp để xác nhận timeline chunk 0–300 / 295–305 bằng FFmpeg thật và từ chối video >20 phút. Không dùng để đo chất lượng nội dung hoặc chứng minh đạt rubric 5 tutorial thật.
