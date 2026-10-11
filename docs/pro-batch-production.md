# Pro Batch: mỗi bài viết là một request

Lựa chọn ngày 12/10/2026 thay thế cách chữa hai bài trong một lần gọi và các lượt Standard/Flex. Các bài đã trả và các phản hồi đã lưu giữ nguyên hợp đồng, nguồn và prompt của lượt đó.

## Cấu hình cho bài mới

| Trường | Giá trị |
|---|---|
| `GEMINI_ESSAY_REQUEST_MODE` | `per_essay_batch` |
| `GEMINI_ESSAY_MODEL` | `gemini-3.1-pro-preview` |
| `GEMINI_ESSAY_SERVICE_TIER` | `batch` |
| `GEMINI_ESSAY_BUNDLE` | `false` |
| `GEMINI_PRO_MAX_OUTPUT_TOKENS` | `16384` cho mỗi bài, gồm suy luận và đầu ra |

Workflow gán trực tiếp cấu hình này cho `grade` và `pilot`, tránh biến repository cũ vô tình đưa bài mới về Standard/Flex. `Settings.from_env()` kiểm tra tổ hợp; tổ hợp sai dừng trước yêu cầu sinh. `legacy` chỉ dành cho đọc, thu kết quả và giao các lượt đã lưu; không phải đường dự phòng khi Batch lỗi. Chấm vở, ảnh và OCR tiếp tục dùng Flash theo quy tắc hiện hành. Pro nhận văn bản đã xác minh và đúng **một** bài học sinh mỗi request; không gửi lại ảnh vở cho Pro.

## Kiến thức của Cô: lưu bản gốc, gửi bản biên soạn theo buổi

Theo lựa chọn tiếp theo của Cô ngày 12/10/2026, lượt mới được dùng bản biên soạn gọn gồm quy tắc của đúng buổi, nền tảng liên quan và bài mẫu phù hợp. Kho nguyên văn lý thuyết, bài mẫu, bản dịch và tài liệu vở vẫn được giữ đầy đủ, có hash và định vị nguồn. Bản gửi model không được mô tả là nguyên văn 100% nếu đã biên soạn.

Bản biên soạn phải có phiên bản riêng, đối chiếu được mỗi quy tắc với nguồn gốc và ghi rõ các mục không đưa vào cùng lý do: nội dung trùng, mẫu trend không phù hợp bài static, biểu mẫu trống, hướng dẫn hành chính hoặc dữ liệu minh họa không thuộc đề hiện tại. Không biến ví dụ thành cấu trúc bắt buộc, không mang số liệu của bài mẫu sang bài học sinh và không bỏ quy tắc nền tảng như xác định đại lượng, quy chiếu, nhóm dữ liệu và liên kết thực chất. Nếu nguồn cũ có câu thiếu/chấm câu sai hoặc đã được Cô đính chính, lưu bản gốc nhưng áp dụng ý nghĩa và hướng dẫn đã xác minh, không dạy lại lỗi đó.

Gộp các hướng dẫn chấm/kiểm toán bị lặp trong prompt thành một hợp đồng ngắn hơn là tối ưu cách diễn đạt, không phải giảm phạm vi lỗi cần kiểm tra. Vẫn giữ mọi chú thích lỗi thực, bản chữa đầy đủ và bằng chứng kiểm tra số liệu/ngôn ngữ. Chỉ dùng phiên bản đã đối chiếu nguồn và được phép cho lượt mới; không sửa prompt hoặc bản chữa đã niêm phong trong lịch sử.

## Gửi và thu kết quả

1. Xác minh nguồn, danh tính, cutoff/ngoại lệ, điều kiện vở, phiên bản prompt/bản kiến thức biên soạn và ngân sách. Dự trù phải tính đủ từng request độc lập trước khi phát sinh chi phí vở. Giữ nguyên các trần hiện hành; không hạ số lỗi cần chữa, tự bỏ kiến thức ngoài phạm vi biên soạn đã duyệt hoặc tự tăng trần để vừa ngân sách.
2. Tạo request riêng có khóa ổn định cho từng bài, lưu checkpoint và dự phòng chi phí, xuất JSONL rồi upload bằng Files API. Tệp chứa bài học sinh và lý thuyết nên phải giữ riêng; không commit hoặc tải lên GitHub Actions artifact công khai.
3. Gửi Batch đúng một lần và lưu tên job. Lượt chạy kết thúc khi job đang chờ; không giữ runner chờ nhiều giờ. Nếu chưa biết Google đã nhận yêu cầu hay chưa, giữ trạng thái chờ xác minh và dự phòng, không gửi lại.
4. Cron 15 phút gọi `python -m src.main --collect-batches`. Lệnh này chỉ đọc checkpoint/kết quả Batch đã gửi, không quét lại Form, PDF hoặc gọi sinh mới. Kết quả ghép theo khóa request, không theo thứ tự dòng. Thiếu dòng, sai khóa, lỗi từng request, phản hồi bị cắt hoặc JSON sai được giữ để xử lý; không tự gọi Standard/Flex hoặc trả tiền thử lại.
5. Kết quả đầy đủ đi qua kiểm tra nguồn và hợp đồng chất lượng, xuất dashboard, kiểm tra dashboard thực tế, rồi ghi chính xác Google Sheets/Toàn diện và đọc lại ô. Nếu bước giao bài lỗi, tiếp tục từ đầu ra đã lưu; không chấm lại. Các cảnh báo chất lượng và ngoại lệ phải tuân thủ chính sách giao bài/ủy quyền hiện hành.

`GRADING_ENABLED=false` giữ lại việc đăng dashboard/ghi Sheets, nhưng không cản thu kết quả job đã trả phí. `GEMINI_GENERATION_ENABLED=false` cấm gửi yêu cầu sinh mới; collector luôn ép cờ này về `false`. Chạy mới (`grade` hoặc `pilot`) yêu cầu **cả hai cờ true**. Sửa mã hoặc chạy preflight không tự bật cờ hay thay đổi ngân sách. `pilot` lưu thử nghiệm riêng; không tự công bố.

Giữ cùng `concurrency: ielts-grading-single-writer` cho mọi mode. `collect-pro-batch` vẫn thu được pilot gộp hai bài lịch sử; `deliver-pilot`, `deliver-pilot-notebook` và `deliver-teacher-authorized` dùng đầu ra đã lưu. Không chuyển lịch sử sang prompt/schema mới và không chấm lại bài cũ để khớp cách tổ chức Batch mới.

## Chi phí và độ trễ

Theo [tài liệu Gemini Batch API](https://ai.google.dev/gemini-api/docs/batch-api) và [bảng giá Gemini](https://ai.google.dev/gemini-api/docs/pricing), Batch được giảm 50% đơn giá token so với Standard. Đây là giảm giá trên **cùng lượng token**, không bảo đảm hóa đơn mới bằng một nửa lượt gộp hai bài trước đây. Hai request độc lập đều nhận bản kiến thức cần thiết, nên phần đầu vào chung được tính hai lần nếu không có cache thực sự được xác nhận. Token suy luận cũng phải tính vào dự trù đầu ra; không giả định chi phí cache bằng không.

Mục tiêu sau biên soạn là **10.000–15.000 token đầu vào tổng cộng cho hai bài** và **10.000–15.000 token đầu ra tổng cộng, gồm suy luận**. Với giá Batch giả định 1 USD/triệu token đầu vào, 6 USD/triệu token đầu ra và tỷ giá dự trù 26.000đ/USD, khoảng tương ứng là **1.820–2.730đ/học sinh/hai bài**, chưa gồm Flash và thuế. Đây là mục tiêu để đo bằng request thật, không phải bảo đảm độ dài, chất lượng hay hóa đơn. Nếu lượng token thực tế vượt mục tiêu, báo rõ; không tự cắt chú thích hoặc bản chữa để khớp con số.

Khoảng dự trù trên **không tự thay trần cấu hình 1.000đ/học sinh**. Khi chưa có ngân sách mới được cấu hình theo phê duyệt, kế hoạch vượt trần vẫn phải giữ lại trước yêu cầu sinh. Giới hạn 16.384 output token/bài cũng không có nghĩa model chắc chắn dùng hết hoặc chắc chắn hoàn thành trong khoảng mục tiêu.

Đo bằng `countTokens` ngày 12/10/2026 với hai bài đã lưu của một học sinh, gói buổi 14 v10 và cả schema/system instruction: **8.312 + 8.071 = 16.383 token đầu vào**. Gói kiến thức gửi model có 11.542 ký tự; kho 10 tài liệu gốc vẫn giữ nguyên. Nếu tổng đầu ra gồm suy luận là 10.000–15.000 token thì Pro Batch tương ứng **1.986–2.766đ/em/hai bài**, chưa gồm Flash, thuế và chênh lệch tỷ giá. Đây là đo đầu vào thật nhưng vẫn giả định đầu ra, chưa phải lượt chấm nghiệm thu. Dự phòng tối đa hiện tại là **5.637đ** với 16.384 output token mỗi bài và phần đệm đầu vào; chưa có quyền tự nâng trần để chạy mức này.

Batch tránh tuyến cấp năng lực Flex, nhưng vẫn có quota, lỗi API/request, job thất bại hoặc hết thời gian. Google nêu mục tiêu xử lý trong 24 giờ, không bảo đảm mọi job hoàn tất đúng mốc đó. Pipeline lưu trạng thái, thu lại ở lượt sau và báo lỗi có thể xử lý; không khẳng định Batch “không bao giờ nghẽn” hoặc “không thể lỗi”.

Các kiểm thử giả lập xác minh cách tổ chức request, phục hồi và giao bài; chúng không chứng minh chất lượng sư phạm của một bản chữa thật hoặc rằng ngân sách 1.000đ/em đủ cho bộ tài liệu đầy đủ.
