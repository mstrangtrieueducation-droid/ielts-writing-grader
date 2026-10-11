# Kiểm tra chất lượng chung cho luồng Flash → Pro

Ngày 11/10/2026, prompt mới `hybrid-two-essays-v04-source-grounded-quality` thay cách kiểm tra chỉ dựa vào JSON đủ mục. Áp dụng cho lượt bundle mới; vở/đầu vào vẫn Flash, bài viết vẫn đúng hai bài chữ của một em trong một lần gọi. Không thêm model kiểm toán, ảnh gửi Pro hoặc tự gọi trả phí lại.

## Phân biệt đúng loại vấn đề

Mỗi chú thích phân loại grammar, data, clarity, punctuation, register hoặc optional. Chưa rõ đối tượng/thứ tự hoặc có cách hiểu hợp lý đúng là vấn đề làm rõ; không kết luận chắc chắn sai số liệu/ngữ pháp. Gợi ý diễn đạt không trở thành lỗi bắt buộc. Nhận định số liệu được xét riêng, không bị một lỗi khác trong câu làm đổi trạng thái.

## Số liệu kiểm tra bằng chương trình

Nguồn đã xác minh phải có ma trận đầy đủ. Hỗ trợ ký hiệu cũ với `Column order A/B. Group=1/2; Other=3/4.` hoặc JSON rõ ràng:

```json
{"columns":["Information","Teaching"],"rows":{"Economics":[59,95],"Law":[72,62]}}
```

Không suy luận ô dữ liệu từ mô tả, OCR hoặc model chấm. Thiếu hàng/cột, hàng không đọc được, số không rõ hoặc ma trận chưa cấu trúc thì giữ lại **trước khi tốn tiền kiểm tra vở**. Prompt nhận mã ô, giá trị và cực trị/phạm vi chênh lệch do chương trình tính trước.

Model phải chỉ rõ ô dữ liệu và phạm vi cho nhận định cao/thấp nhất trong gợi ý, bài viết tham khảo và ví dụ cụm từ. Trong một hàng/cột phải có cụm giới hạn phạm vi hiện ngay trong câu; chỉ đặt tên hạng mục ở chủ ngữ chưa đủ. Bộ kiểm tra tự tính cực trị, chênh lệch và kiểm tra tất cả các ô được viện dẫn. Không mặc định tổng các ngành là số trường duy nhất. Nhận định toàn bảng sai không thể qua bằng cách tự khai là đúng trong JSON.

Mỗi kiểm tra số có bằng chứng ô và toán tử. Chương trình đối chiếu `>`/`>=`/`<`/`<=`/`=`; phân biệt mốc trên lỏng nhưng đúng với số sai. Năm/thứ hạng chỉ được viện dẫn từ đề đã xác minh. Bằng chứng không được bỏ bớt đối tượng cùng được gộp trong câu. Thứ tự `respectively` chưa rõ vẫn có thể là ambiguous; số đúng với đối tượng đã rõ không được gán ambiguous chỉ vì số trước đó sai.

Kiểm tra sửa âm thầm bắt viết hoa kiểu Uk→UK và dấu kết thúc đoạn. Các chú thích phải trích đúng nguồn. Trước **mọi lần ghi dashboard/Toàn diện** của lượt mới, chạy lại bộ kiểm tra từ raw đã lưu và so khớp nguyên payload; đổi nội dung sau kiểm tra bị giữ lại.

Mọi số xuất hiện trong câu sửa, bài viết tham khảo và ví dụ cụm từ cũng phải có bằng chứng ô/quan hệ so sánh. Bộ kiểm tra tính lại và đối chiếu với toán tử thực sự viết trong câu, không nhận lời model tự khai rằng `exceeding` là `>=`. Số năm/thứ hạng không được dùng để hợp thức hóa một số lượng sai. Bắt đúng lỗi ở bài gốc nhưng viết lại sai vẫn bị giữ lại.

## Giữ lịch sử và giới hạn tiền

Schema mới là `AuditedProEssayBundle`/`AuditedFlashEssayBundle`; schema cũ được giữ nguyên. Prompt, phiên bản hợp đồng và raw mới được lưu riêng. Lượt cũ đã trả, raw pilot bị từ chối, khoản sử dụng hoặc dự phòng chi phí không bị sửa hay phát lại bởi cập nhật này. Lượt lỗi mới chuyển held, giữ raw; không tự sửa bài chữa hay trả phí lần nữa. Các trường kiểm toán được giữ riêng trong checkpoint, không trở thành lời dẫn hệ thống trên bài học sinh.

Token counter vẫn dự trù cả prompt/schema và giới hạn output hiện hành trước gọi. Không tăng ngân sách, giảm số lỗi hoặc bật các cờ chấm tự động. Các kiểm tra này bắt các lỗi đã có bằng chứng hồi quy; chúng không thay thế nghiệm thu sư phạm trên bài thật và không bảo đảm phát hiện mọi lỗi ngôn ngữ. Luồng mới chưa được gọi trả phí để nghiệm thu.
