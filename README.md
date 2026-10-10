# Hệ thống chấm IELTS bằng Python / GitHub Actions

Mã nguồn chấm vở, sổ từ vựng, bài viết homework và PDF kiểm tra, với checkpoint riêng trên Drive, dashboard mã hóa và ghi nhận xét chính xác vào Toàn diện. Đây là một dự án triển khai riêng; tạo thư mục này không tự thay thế dashboard, trigger hoặc heartbeat đang vận hành.

## Những điểm đã sửa so với bản directive

- Gemini 1.5 đã ngừng phục vụ. Hai model được đặt bằng biến cấu hình và kiểm tra qua API trước khi chạy, không âm thầm đổi model khi lỗi. Danh mục hiện hành: https://ai.google.dev/gemini-api/docs/models ; lịch ngừng model: https://ai.google.dev/gemini-api/docs/deprecations .
- GitHub Actions có thể chạy trễ/bỏ lượt khi tải cao. Cron 15 phút là lịch đánh thức, không phải bảo đảm thời gian thực. Giờ nộp luôn lấy từ Form gốc, không từ Drive, tên tệp, giờ tải xuống hay giờ ghép PDF.
- Không chỉ có hai Secret: cần khóa mã hóa dashboard, thư mục trạng thái, nguồn guidelines, thư mục scan và model hợp lệ. Thiếu cấu hình thì preflight dừng; không báo đã triển khai thành công.
- Không công khai tên, điểm, bài viết, bản chữa hoặc link phụ huynh trong GitHub. `dashboard_data/` chỉ chứa AES-256-GCM; trình duyệt giải mã bằng khóa riêng trong fragment của link học sinh. Các link này là quyền truy cập: phải giữ riêng, không gửi vào nhóm lớp. Không thu hồi riêng một link trong phiên bản này; đổi khóa master cần tái mã hóa và cấp lại toàn bộ link.
- Notebook pass từ model ghi nhận chất lượng thực tế, không tự nói “theo xác nhận của Cô”. Chỉ dùng câu này khi có `notebook_overrides` đã được Cô xác nhận và lưu bằng chứng.
- Số đề lấy từ cấu hình thực tế; có thể 1/2/3 hoặc nhiều đề, không luôn ghi 2/2.
- Bài kiểm tra là luồng riêng, không áp dụng khóa vở hoặc cutoff homework. PDF scan phải có tên từng học sinh và đúng mã bài; PDF cả lớp chưa tách cần được chuẩn bị đúng danh tính trước khi nạp.

## Cấu trúc

`src/config.py`: cấu hình; ID tracker IELTS 45–50 được đưa vào Secret `CLASS_SHEET_MAP_JSON`, không commit vào mã công khai. Mở rộng cùng mapping cho lớp mới.

`drive_service.py`, `sheet_service.py`: đọc nguồn đúng ID/range, phân trang Drive, giữ ghi chú thủ công, không ghi đè công thức, đọc lại chính xác sau ghi.

`gemini_service.py`, `retry.py`: SDK Google GenAI, giới hạn request. Các thao tác đọc/ghi nguồn có backoff; riêng sinh kết quả trả phí chỉ gửi một lần, tắt cả retry SDK. Timeout/429/5xx hoặc JSON lỗi được giữ lại, không tự trả tiền để chạy lại. Phản hồi và token usage được lưu riêng trên Drive trước validation.

`graders/`: mọi kiểm tra ảnh vở/từ vựng và OCR chỉ dùng Flash, kể cả lượt kiểm tra độc lập khi nghi thiếu/đánh máy. Bất đồng hoặc ảnh chưa đọc rõ được giữ chờ. Mỗi bài viết chỉ một lượt Flash với JSON Schema: tự soát trong cùng prompt, sau đó kiểm tra bằng mã về định danh, số từ/đoạn, trích dẫn và tiêu chí định lượng. Không gọi model kiểm toán/sửa lại riêng; kiểm tra bằng mã không thay thế kiểm toán ngữ nghĩa độc lập.

`pipeline.py`, `state.py`: lưu phiên bản rubric, nguồn, receipt, kết quả và từng pha giao bài. Kết quả đã hoàn tất không tự chấm lại. Có lỗi tracker/Pages thì dùng kết quả đã lưu để giao lại.

`dashboard.py`, `delivery.py`: mã hóa, commit/push, đọc lại tệp Pages thực tế, mở trình duyệt headless kiểm tra thẻ bài và việc ẩn chi tiết, rồi mới ghi Toàn diện. Scan chỉ được chuyển sang processed sau tất cả bước đó.

Commit do `GITHUB_TOKEN` tạo không tự kích hoạt build Pages. Publisher gọi API yêu cầu build với quyền `pages: write`, rồi xác minh tệp thực tế; không dựa vào việc push thành công để báo đã đăng. Xem https://docs.github.com/en/actions/concepts/security/github_token .

`announcements.py`: chỉ tạo bản Zalo khi toàn bộ roster đã có kết quả dashboard/Toàn diện được xác minh. Lưu bản nhắn trong thư mục Drive riêng; không tự gửi Zalo.

## Cấu hình GitHub

Dùng repository riêng và bật Pages **Deploy from a branch → default branch → / (root)**. Renderer `index.html`, `dashboard.js` phải có trong cùng repo với `dashboard_data`. `DASHBOARD_BASE_URL` là URL gốc Pages của repo đó. Hệ thống này chưa phải adapter để thay renderer/dashboard cũ; không đổi link đang dùng của lớp khi chưa nghiệm thu chuyển đổi.

Secrets trong Settings → Secrets and variables → Actions:

| Secret | Nội dung |
|---|---|
| `GEMINI_API_KEY` | API key từ Google AI Studio có quyền dùng hai model đã chọn |
| `GCP_SA_KEY` | JSON service account; không dán vào chat hoặc commit vào repo |
| `GOOGLE_STATE_OAUTH_JSON` | Tùy chọn: refresh credential của chủ Drive để tạo/đọc checkpoint trong My Drive bằng quyền `drive.file`; không dùng credential này để sửa tracker |
| `DASHBOARD_MASTER_KEY` | Base64 của 32 byte ngẫu nhiên, giữ nguyên qua các lượt chạy |
| `CLASS_SHEET_MAP_JSON` | JSON mapping lớp → tracker ID, gồm sáu lớp Cô đã cung cấp |

Sinh khóa: `python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"`. Chạy riêng trên máy của Cô và đưa thẳng vào Secret; không lưu vào log Actions.

Repository variables:

| Variable | Yêu cầu |
|---|---|
| `GUIDELINES_SPREADSHEET_ID` | Sheet có tab `IELTS_WRITING_GUIDELINES` |
| `FOLDER_STATE_ID` | Thư mục Drive riêng lưu checkpoint/prompt/raw output/bản Zalo; không chia sẻ công khai |
| `FOLDER_INCOMING_SCAN_ID` | Thư mục scan chưa xử lý |
| `FOLDER_PROCESSED_SCAN_ID` | Thư mục scan xử lý xong, khác incoming/state |
| `GEMINI_NOTEBOOK_MODEL` | `gemini-3.8-flash`, duy nhất cho ảnh/vở/từ vựng/OCR |
| `GEMINI_ESSAY_MODEL` | `gemini-3.8-flash`, chấm chữ một lượt, không ảnh/PDF |
| `DASHBOARD_BASE_URL` | URL Pages gốc, HTTPS, không có fragment |
| `GRADING_ENABLED` | Chỉ đặt `true` sau preflight và nghiệm thu một bài thử |
| `GEMINI_GENERATION_ENABLED` | Mặc định tắt; phải bật riêng mới được gửi yêu cầu sinh trả phí |

Theo lựa chọn mới của Cô ngày 10/10/2026, **cả hai biến model phải là `gemini-3.8-flash`**. Chặn Pro và mọi fallback model ở cả cấu hình và ngay trước gọi API. Preflight chỉ kiểm tra quyền truy cập, không chứng minh chất lượng chữa bài. Không dùng `gemini-1.5-flash/pro` trong triển khai mới.

Service account cần Sheets API + Drive API và quyền Editor trên guideline/tracker/state/incoming/processed; quyền đọc các Form response, bài học, chart và tệp học sinh. Nếu tạo tệp state bằng service account, dùng **Shared Drive** hỗ trợ service account và cấp đúng quyền. Service account thường không có storage quota để tạo tệp mới trong My Drive: chia sẻ một thư mục My Drive đơn thuần không bảo đảm ghi state được. Không chuyển tệp scan gốc ra khỏi vị trí đang cần cho lớp; incoming nên là bản scan dành riêng cho pipeline.

Khi tài khoản không có Shared Drive, cấu hình `GOOGLE_STATE_OAUTH_JSON` cho thư mục state do chính ứng dụng tạo trong My Drive của Cô. Writer state và audit dùng quyền `drive.file`; mọi thao tác Sheets/đọc nguồn/chuyển scan vẫn dùng service account. Chỉ chia sẻ incoming/processed và nguồn cần thiết cho service account. Không đưa token hoặc API key vào code/log công khai.

Workflow giữ một writer bằng `concurrency`, không hủy job đang chạy; tối đa 12 hồ sơ/lượt, tiếp tục ở lượt sau. Không chạy nhiều repository hoặc CLI khác cùng ghi vào một state folder. Timeout job là 120 phút, vẫn có giới hạn GitHub runner, Gemini và Google API; checkpoint giải quyết việc tiếp tục, không xóa mọi quota.

## Guidelines: hợp đồng nguồn rõ ràng

Tab `IELTS_WRITING_GUIDELINES` có đúng ba cột:

`task_code | assignment_type | config_json`

Mỗi dòng là **một lớp + một buổi/bộ đề**, `task_code` không trùng trong lớp. `assignment_type`: `vocabulary`, `notebook`, `homework`, `assessment`. `config_json` theo schema `Binding` trong `src/schemas.py`; hai cột đầu ghi đè cùng thuộc tính trong JSON. Dữ liệu config là nguồn chỉ Cô/người quản trị được sửa, không lấy chỉ dẫn từ bài nộp học sinh.

Mẫu trong `examples/notebook-binding.json` **chưa active**, có dữ liệu minh họa cần thay bằng ID/checklist/lịch thật. Không dùng ngày ví dụ làm lịch lớp. Kiểm tra local bằng:

```sh
python -m src.main --validate-config examples/notebook-binding.json
```

Các trường bắt buộc cần xác minh:

- `source_file_ids`: bài học/mẫu của đúng buổi, không dùng một checklist chung thay nội dung được giao. `notebook_requirements`: mọi nhóm/mục, kể cả dịch khi thực sự yêu cầu. `notebook_copy_scope`: ranh giới phần phải chép và phần loại trừ. Đề, biểu đồ bài tập mới, trang trả lời trống và hướng dẫn thao tác/nộp bài không phải yêu cầu chép vở. Không tự thêm phần bị Cô xóa khỏi nguồn.
- `version`, `source_reference`, `source_verified`: phiên bản prompt và bằng chứng đọc nguồn. Đổi nội dung sau freeze bị giữ lại để kiểm toán, không tự nâng rubric lịch sử.
- `next_writing_date`, `next_writing_evidence`: lần Writing thực tế kế tiếp của đúng buổi trên dashboard, kể cả kiểm tra; cutoff 00:00 Việt Nam ngày đó. `due_at` có timezone dùng để phân biệt hạn bài tập với cutoff.
- `form_spreadsheet_id`, `form_tab`, `name_column`, `receipt_column`, `notebook_columns`, `essay_columns`: đúng các cột Form, dùng chữ cột A1. `essay_columns` là map số đề → cột, ví dụ `{"1":"E","2":"F","3":"G"}`. Chỉ Forms là nguồn nhận homework; tracker chỉ roster và kết quả.
- `tracker_header_exact`: toàn bộ giá trị header thật của cột nhận xét, không chỉ “W29” nếu ô có cả tên/hạn. Header phải khớp duy nhất. `tracker_header_range` bắt đầu ở cột A để vị trí cột tương ứng chính xác.
- `roster_start_row/end_row`: chỉ vùng học sinh, không bao gồm tiêu đề. Dòng trống bị bỏ; mỗi tên/ID phải duy nhất. `aliases` chỉ chứa xác nhận tên rõ ràng, không fuzzy match nhầm học sinh. Các ID phải ổn định khi đổi thứ tự dòng.
- `dashboard_link_column`: tùy chọn; chỉ điền một cột mới trống dành riêng cho link hệ thống này. Link cũ/ghi chú/công thức được giữ, không tự thay.
- `essays`: mỗi đề có `exercise`, IELTS `task`, question, **taught_theory**, **assigned_outline**, **ground_truth**, chart ID khi cần. Không suy số liệu chart từ bài học sinh. Nhận xét/test band phụ thuộc loại bài thực tế.
- `vocabulary`: mỗi từ là một Requirement, `text` nêu rõ có cần IPA/nghĩa/ví dụ không. Không mặc định mọi buổi đều cần ví dụ.
- `notebook_overrides`: stable student ID → mã/bằng chứng xác nhận bổ sung của Cô. Không là lời tự nhận của học sinh. Khóa vở cũ không được mở chỉ bằng bản upload mới.
- `regrade_authorizations`: stable student ID → mã quyết định chấm lại cụ thể. Tạo attempt mới; kết quả thô trước đó vẫn ở Drive. Rubric của attempt đang dở được freeze; không sửa JSON nguồn để lén đổi tiêu chí trong attempt đó.

Buổi 21/39 bị loại trước Form/PDF. Buổi 1–5 cần `early_lesson_authorized=true` và checklist riêng đã xác minh. Buổi 6 chỉ vở, không thẻ đề trống. Bài kiểm tra cần cấu hình `assessment` riêng, không kích hoạt từ lịch homework. Tuần lưu trữ trước 30/09 không tự mở lại.

Homework chọn bản mới nhất còn hợp lệ của mỗi em; mỗi đề lấy text mới nhất không trống và lưu receipt của chính nó. Bản chỉ nộp từ cutoff trở đi không đọc ảnh/PDF, không gọi model. Bài hợp lệ trước cutoff vẫn được chấm sau cutoff. Tệp chưa đọc được/bất đồng audit giữ pending; log vận hành chỉ mã job và loại lỗi, chi tiết nằm trong state riêng. Tên Form chưa khớp thì không kết luận roster còn lại “chưa nộp”.

## Scan và webhook

Tên scan: `IELTS49_Nguyen Thu Hang_TEST3.pdf` hoặc `IELTS 49_Nguyễn_Thu_Hằng_TEST3.pdf`. Mã `TEST3` phải khớp Binding riêng của lớp; một PDF/học sinh/bộ đề. Đề trống/chưa viết xong được giữ đúng bản gốc, không đoán là mất trang; phần không đọc rõ chờ xác minh.

`repository_dispatch` yêu cầu caller có token được phép gửi event cho repo, ví dụ API:

`POST https://api.github.com/repos/OWNER/REPO/dispatches`

Body `{"event_type":"new_scan_uploaded"}` hoặc `{"event_type":"on_form_submit"}`. Không truyền PDF, credential hoặc điểm qua event. Pipeline đọc lại nguồn đã xác minh; không tin ID task/student tùy ý trong webhook. Cron vẫn là fallback nếu uploader/Form không có relay. Workflow không tự cài trigger Google Form; nếu muốn tức thời cần nối uploader/Form vào dispatch API riêng. Không cần Apps Script để chấm hoặc chạy lịch 15 phút.

## Chuyển đổi và nghiệm thu

1. Đưa source vào **repo riêng**, bật Pages root, thêm Secrets/variables và chia sẻ nguồn Google. Giữ `GRADING_ENABLED` chưa bật.
2. Nhập/check từng Binding dựa trên dashboard và nguồn của Cô. Không kích hoạt bằng checklist mẫu.
3. Actions → Run workflow → **preflight**. Bước này chỉ kiểm tra đọc/model; không gọi chấm và không ghi kết quả.
4. Chạy một Binding mới chưa có bài trả trước đó; workflow mode **pilot** với Secret `PILOT_SELECTION_JSON` gồm chính xác `class_name`, `task_code`, `student_ids`. Lượt này gọi Gemini trên nguồn thật và lưu kết quả riêng, không ghi dashboard/tracker. Kiểm tra nguồn, chất lượng và bản xem trước trước khi chuyển sang mode **grade** để kiểm tra giao kết quả. Test giả lập không thay thế nghiệm thu một bài thật.
5. Trước khi cắt luồng cũ: nhập lịch sử/cutoff và các khóa vở được kiểm toán, hoặc chỉ kích hoạt buổi mới chưa có kết quả. Hệ thống chặn hồ sơ đã có block chấm trong tracker mà chưa có checkpoint của hệ thống mới. **Importer lịch sử dashboard cũ chưa được cung cấp trong bản này**; không giả vờ đã di chuyển toàn bộ lịch sử/khóa.
6. Dừng writer/heartbeat chấm cũ cho chính phạm vi chuyển đổi, bảo đảm chỉ một owner; sau đó bật `GRADING_ENABLED=true`. Không tắt trigger Form/dashboard khác khi chỉ thay engine chấm.

Kết nối repo/API/billing và lượt thử riêng không đồng nghĩa đã bật chấm toàn bộ. Chỉ bật `GRADING_ENABLED` sau khi nghiệm thu chất lượng và giao kết quả; trạng thái triển khai thật phải đọc từ cấu hình và bằng chứng chạy. Không tạo thêm automation trong Codex khi workflow chưa được nghiệm thu.

Lượt thử trả phí được Cô chỉ định riêng dùng manual `mode=pilot`, `authorized_flash_trial=true` và `PILOT_SELECTION_JSON` giới hạn đúng một học sinh. Điều này không bật hai biến generation/schedule toàn cục. Sau khi đối chiếu bài gốc/số liệu và lưu bằng chứng chất lượng gắn SHA256 của payload, `mode=deliver-pilot` chỉ đăng kết quả đã duyệt, không gọi chấm lại. Không duyệt payload lỗi để có kết quả đăng; một lượt thử chưa chứng minh chất lượng cho mọi đề/lớp.

## Kiểm thử và vận hành

```sh
python -m venv .venv
# Windows: .venv/Scripts/python.exe ; Linux: .venv/bin/python
python -m pip install -r requirements.txt
python -m pytest -q
python -m playwright install chromium --only-shell
python tests/ui_smoke.py
```

`tests/ui_smoke.py` dùng bài giả lập và local HTTP server; không tải/chấm bài thật, không cần credential. Test pipeline kiểm tra cutoff chính xác, không đọc PDF của bài quá muộn, khóa vở, lỗi định danh, source/paragraph/word count, giữ ghi chú, retry, mã hóa, tiếp tục giao bài và không chấm lại.

Nếu lỗi: đọc `job-<hash>.json` trong state folder để biết phase/last_error; prompt/raw ở `attempt-*.json`, usage và phản hồi đã nhận cũng có trong cost ledger riêng. Không xóa job/ledger để chạy lại. `dashboard_verified`/`tracker_verified` tiếp tục giao từ kết quả cũ. Lỗi sinh kết quả, JSON hoặc nguồn chưa rõ giữ lại; không tự retry trả phí. Checkpoint đã gửi nhưng chưa biết kết quả giữ nguyên dự phòng chi phí. Hồ sơ pilot cũ còn vấn đề kiểm toán không tự được coi là đạt bởi việc đổi luồng.

## Luồng tiết kiệm theo yêu cầu ngày 10/10/2026

- Cả vở và bài viết đều dùng Flash; không fallback Pro. Lượt chữa bài viết chỉ nhận `EssaySpec` bằng chữ (đề, lý thuyết đã học, dàn ý và dữ liệu biểu đồ đã xác minh), bài gõ chữ và rubric. Không đính kèm vở, PDF bài học hoặc ảnh biểu đồ vào lượt chữa chữ. Task 1 thiếu ground truth dạng chữ thì giữ lại, không đoán.
- Vở vẫn đọc đủ trang, không giảm trang để giảm tiền. Flash có thể có lượt thứ hai cho kết luận thiếu/đánh máy; dự trù cơ sở dưới đây tính một lượt vở, lượt thứ hai tăng tiền.
- `cost_control.py` dự phòng chi phí trước mỗi yêu cầu, dùng token counter cho đầu vào cộng 20% + 256 token, output cap 8192 gồm suy luận. Sổ chi phí bền vững chung cho đúng lớp/buổi, không reset khi đổi học sinh, workflow hoặc authorization. Tiền chưa rõ tiếp tục chiếm dự phòng. Phản hồi nhận được được tái dùng mà không gọi lại.
- Ngưỡng ứng dụng là **14.900đ/lớp/buổi**. Vượt dự phòng thì dừng trước gọi; có thể còn học sinh chưa chấm. Đây không phải cam kết hoàn tất cả lớp dưới 15.000đ, cũng không phải cap billing Google. Tỷ giá 26.000đ/USD chỉ giả định; sai khác hóa đơn/thuế chưa được nghiệm thu bằng lượt thật. Bảng giá được khóa đến 31/12/2026, hết hiệu lực giữ lại.
- Flash chữa bài viết dùng `thinking_level=medium`; kiểm tra vở/OCR dùng `low`. Giữ soát toàn bộ bài và mọi lỗi có căn cứ, kiểm tra logic/ý/đoạn/đại lượng/grammar/word choice, ví dụ cụ thể trong nhận xét áp dụng lý thuyết và tính nhất quán giữa lỗi và bản chữa. Không giới hạn số lỗi nhằm ép ngân sách. JSON bị cắt vẫn giữ lại, không tự sinh lại. Chất lượng luồng mới chưa nghiệm thu bằng bài thật; không bảo đảm ngang Pro chỉ nhờ prompt và Schema. Không bật tự động hoặc trả bài từ thay đổi mã này.

Dự trù giấy theo [bảng giá Google](https://ai.google.dev/gemini-api/docs/pricing), Standard: Flash $0,75 input / $3,75 output trên 1 triệu token đến 31/12/2026. Output **gồm suy luận và JSON**. Giá Pro vẫn có trong bộ tính để đối chiếu lịch sử; điều này không cho phép gọi Pro nữa.

Giả định bài viết: 3.000–5.000 token đầu vào gồm rubric/lý thuyết/schema và 2.000–4.000 token đầu ra. Vở: 10.000–20.000 input và 1.000–2.000 output. Không dùng số từ bài gõ làm toàn bộ token bill.

| Phạm vi | Dự trù VND |
|---|---:|
| Một bài Flash, một lượt | 253,5–487,5 |
| Một vở Flash, một lượt | 292,5–585 |
| 25 em, mỗi em 1 bài + vở | 13.650–26.812,5 |
| 25 em, mỗi em 2 bài + vở | 19.987,5–39.000 |

Các con số là kịch bản, không phải token đã đo hoặc mức phí bảo đảm. Kiểm tra lại vở, OCR bài viết tay, nguồn dài hơn, output dài hơn hoặc tỷ giá/thuế thay đổi sẽ làm tăng chi phí. Không chuyển sang model khác hoặc cắt bớt lỗi để làm vừa ngân sách nếu chưa có hướng dẫn của Cô.

Hạn chế cần lưu ý: đây là chấm bằng AI có kiểm toán tự động, không bảo đảm không bỏ sót lỗi; cần nghiệm thu rubric bằng bài thật. Tệp quá lớn bị giữ lại thay vì bớt trang. Video không bị tải xuống hoặc được chấm phát âm bởi luồng này. Không có tự tách danh tính trong một PDF cả lớp, không chuyển ngầm dashboard cũ, không tự sửa bài mẫu của Cô.
