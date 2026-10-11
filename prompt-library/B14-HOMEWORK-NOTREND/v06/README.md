# Buổi 14 · Hai bài Task 1 No Trend

Đây là gói dùng chung giữa các lớp học cùng bộ đề và cùng phiên bản nguồn. Không chứa hồ sơ, bài nộp hay ngoại lệ chi phí của học sinh. Trạng thái hiện tại: **thử bài thật không đạt chất lượng; không tái dùng để gọi model cho lớp khác**. Bản prompt và các kết quả đã sinh được giữ nguyên để kiểm tra; phải chuẩn bị phiên bản mới trước lần sinh được duyệt tiếp theo.

- Flash kiểm tra đúng ba phần được giao: sports, doctors' salaries, housing; chữ viết tay, phân tích/chia detail, mẫu Anh–dịch Việt, biểu đồ vẽ tay hoặc dán giấy thật. Loại đề homework mới và phiếu trống theo nguồn đã xác minh.
- Pro nhận hai bài chữ cùng dữ liệu bảng và lý thuyết đúng buổi. Một lần gọi cho mỗi học sinh; không gửi lại ảnh vở.
- So sánh mốc bằng nhau với `exceed/over`, thứ tự `respectively`, phạm vi cực trị, liên kết chú thích–bài gốc, và ví dụ từ vựng phải được kiểm tra nhất quán.
- `manifest.json` khóa dấu kiểm của bộ đề, yêu cầu vở, tài liệu được giao và các thành phần prompt. `src/lesson_packages.py` chọn theo nội dung, không theo tên lớp/học sinh. Nguồn hoặc yêu cầu thay đổi cần phiên bản mới; tên lớp mới không phải lý do viết lại prompt.
- Lớp sau vẫn phải xác minh dashboard, mốc nhận, bài nộp, quyền chấm và ngân sách riêng. Gói này không tự kích hoạt chấm hoặc thay thế manifest vận hành.

Kết quả các lượt cũ được giữ nguyên. Kiểm thử qua không đồng nghĩa model đã chấm đúng; phải nghiệm thu bài thật trước khi ghi gói là dùng lại đã đạt chất lượng.

Lượt thử 12/10/2026 vẫn có: gán một mệnh đề đúng nhưng chưa cụ thể thành lỗi số liệu; gọi nhầm lỗi quy chiếu thành lỗi ngữ pháp; ví dụ cụm từ thiếu môn học/phạm vi; sửa từ hoặc dấu câu mà không giải thích đầy đủ. Hai phản hồi đều bị giữ riêng. Không được nới kiểm tra, sửa tay bài chữa hoặc gọi lại tự động chỉ vì có ngân sách còn dư.
