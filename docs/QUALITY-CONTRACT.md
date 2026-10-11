# Kiểm tra chất lượng chung cho luồng Flash → Pro

## Prompt v06 và tái dùng giữa các lớp

**Cập nhật 12/10/2026:** hai lượt sinh thật với v06 đều chưa đạt. Gói hiện là `live_quality_rejected`; `verify_package_sources` chặn gọi model với gói này cho mọi lớp. 137 kiểm thử chuẩn bị trước đây không chứng minh chất lượng model. Giữ nguyên raw, prompt đã gọi và các khoản chi; phải có phiên bản được sửa, kiểm thử và quyền chi tiêu mới trước bất kỳ lượt sinh tiếp theo. Không tự nâng trần hoặc hạ kiểm tra để công bố bản chưa đạt.

Khi Cô đã được báo các lỗi và vẫn yêu cầu quy trình đăng **đúng bản hiện có**, dùng riêng `deliver-teacher-authorized`. Mỗi hồ sơ cần xác nhận rõ, dấu kiểm raw/nguồn/binding/payload và toàn bộ tệp nguồn. Luồng đăng hiển thị bình thường, xác minh dashboard thật rồi đọc lại chính xác Toàn diện, không gọi model. Nhật ký đánh giá chất lượng, raw và prompt không bị sửa thành đạt. Chỉ thị đăng một bản có sẵn không cho phép tự chấm thêm, không bỏ điều kiện vở/mốc nhận, và không áp dụng cho lớp khác. Kiểm thử bao gồm nội dung bị thay sau xác nhận, khóa vở, cờ sinh trả phí và phục hồi lỗi ghi Toàn diện.

V06 làm rõ `correction_quote` phải là trích nguyên văn bài gốc, không phải lời giải thích tiếng Việt; kiểm tra mọi chỉnh sửa có nội dung; tính trước các ô bằng mốc so sánh nghiêm ngặt để model kiểm tra `>`/`<` với từng nhóm. Không tự gán lỗi nếu chưa xác định được nhóm/hạng mục.

Bộ kiểm tra chấp nhận phạm vi đặt trước nhận định trong cùng mệnh đề và cặp số gắn đúng thứ tự `respectively`. Không lấy phạm vi từ câu/mệnh đề khác ngoài trích dẫn, không biến hai số của hai nhóm thành mỗi số áp dụng cho cả hai. Trường hợp một câu gộp hai ngành vẫn phải kiểm tra từng ngành cho mọi quốc gia được gộp. Những lỗi số liệu thật, số không có bằng chứng và kết quả bị giữ lại vẫn không được xuất bản.

Gói `B14-HOMEWORK-NOTREND/v06` được chọn bằng dấu kiểm của bộ đề và yêu cầu vở, không theo lớp/học sinh. Dữ liệu lớp, mốc nhận, quyền chấm và ngân sách được gắn riêng. Nguồn hoặc prompt đổi thì phải lập phiên bản mới. Trạng thái gói là `prepared_not_live_accepted`: 137 kiểm thử qua, chưa đồng nghĩa model đã chấm chuẩn. Vở đã trả được tái dùng theo bằng chứng; chuẩn bị lại bài viết không tự gọi Flash hoặc Pro, không lấy lại quyền chi tiêu đã dùng ở lượt cũ.

## Trả riêng kết quả vở đã xác minh

`deliver-pilot-notebook` chỉ công bố nhận xét vở đã được đối chiếu độc lập, khi bài viết của lượt thử còn giữ lại. Kiểm tra đúng nguồn/giờ nhận, khóa vở, dấu kiểm toàn bộ tệp, nội dung nhận xét đã duyệt. Mọi bài viết bị giữ lại vẫn ẩn; dashboard và Toàn diện chỉ ghi nhận xét vở và “Bài viết: đang chờ trả bản chữa.” Không đánh dấu job/lớp hoàn tất, không sửa raw hay hạ điều kiện nghiệm thu bài viết, không gọi model. Bằng chứng công bố vở nằm riêng trong `notebook_publication`; lần trả bài viết đầy đủ sau này vẫn phải qua mọi kiểm tra cũ. Cả hai chế độ công bố buộc tắt sinh trả phí. 126 kiểm thử đạt.

## Cập nhật 12/10: không bắt lỗi sai khi so sánh tổng riêng từng nhóm

Prompt mới là `hybrid-two-essays-v05-fair-comparison-scope`. So sánh tổng **riêng từng ngành** qua các nước đã xác minh không đồng nghĩa với cộng mọi ngành để đếm số trường duy nhất. Sự trùng lặp giữa các ngành không tự làm phép so sánh thứ nhất sai. Cần đọc phạm vi toàn bài; thiếu rõ phạm vi có thể là đề nghị làm rõ, không mặc định là lỗi số liệu.

Nguồn phải xác nhận `column_total_policy=additive_counts_across_disjoint_rows` và cung cấp `aggregation_scope_label` trước khi chương trình tính tổng cột. Mặc định không cho cộng. Không suy ra quyền cộng tỷ lệ phần trăm hay nhóm trùng nhau. So sánh `column_totals` được kiểm tra theo tổng tính từ ma trận và phạm vi hiện trong câu. Số tổng trong câu viết lại chưa thuộc hợp đồng kiểm tra số; prompt không yêu cầu đưa những số tổng đó vào bài học sinh.

Các gợi ý và ví dụ phải tự đủ nghĩa, có chủ thể và phạm vi so sánh. Prompt yêu cầu rà thay đổi giữa bài gốc và bản sửa để không bỏ chú thích viết hoa, dấu cuối đoạn, nghĩa từ và vai trò trong cách diễn đạt đánh giá. Kết quả vẫn phải qua nghiệm thu độc lập. Prompt v04 đã đóng băng tiếp tục chịu kiểm tra, không bị hạ thành kết quả cũ miễn kiểm tra. 117 kiểm thử đạt; chưa có thêm lượt sinh trả phí với v05.

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

Token counter vẫn dự trù cả prompt/schema và giới hạn output hiện hành trước gọi. Không tự tăng ngân sách, giảm số lỗi hoặc bật các cờ chấm tự động. Các kiểm tra này bắt các lỗi đã có bằng chứng hồi quy; chúng không thay thế nghiệm thu sư phạm trên bài thật và không bảo đảm phát hiện mọi lỗi ngôn ngữ.

Ngày 12/10/2026, một lượt thử trả phí theo hợp đồng mới đã trả đủ JSON nhưng không đạt cả bộ kiểm tra và đối chiếu độc lập. Raw được giữ lại, không xuất bản hoặc gọi lại tự động; luồng chưa được nghiệm thu chất lượng. Ngoại lệ chi phí nếu Cô duyệt phải ghi đúng lớp/buổi, học sinh, job, lời duyệt, trần mới và một lần gọi trong state riêng. Ngoại lệ không sửa trần ledger dùng chung và không áp dụng cho job khác. 114 kiểm thử đã qua, gồm kiểm tra không thể dùng lại ngoại lệ để gọi lần hai.

Với lượt có vở mới, kế hoạch riêng có thể ghi `generation_limits`: tối đa hai Flash (kiểm tra đầu và kiểm tra độc lập nếu báo không đạt) cùng đúng một Pro gộp hai bài. Phải có duyệt ngân sách tương ứng trước khi kích hoạt; số lượt phải khớp tổng giới hạn từng model. Phần Flash chưa dùng không thể chuyển thành một lượt Pro thứ hai. Ngoại lệ cũ không khai giới hạn này vẫn chỉ cho đúng một Pro. Bộ kiểm thử hiện tại: 118 đạt.


12/10/2026 — New grading only: teaching-fairness-v01 / hybrid v07 distinguishes conventional abbreviations from contractions/texting, requires source-specific taught application and contextual reference/semantic review. B13 v03 moves residual Other sports to the final Detail; other workers is not a residual sport. No old returned grading, paid checkpoints, tracker cells or raw outputs changed. B14 v07 requires a separately authorised live trial; local tests do not establish pedagogical correctness.

12/10/2026 — Teacher clarification: the homework skill supplies knowledge to Gemini, not an alternative grading engine. B14 v08 includes a scoped teacher-knowledge context distilled from the skill guides and the verified lesson 12/14 source paragraphs. The bundle sends this context once with both essays; the new binding removes the contradictory blanket abbreviation/like ban. Keep original lesson-specific data and grouping exceptions, never import future lesson requirements or sports-only ordering into unrelated tables. Reuse the content package across classes with fresh identity/source bindings. Historical paid prompts and outputs retain their frozen contracts. The new prepared package is not live quality approval or spending authority.
