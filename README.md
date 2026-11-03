# PDF Print Checker

Ứng dụng desktop Windows theo dõi thư mục PDF và xác định file nào đã in xong qua Print Spooler.

## Tính năng

- Chọn thư mục PDF, lưu lại cho lần mở sau
- Quét tự động + theo dõi thay đổi thư mục (Watchdog)
- **Đọc lịch sử Event Viewer**: `PrintService/Operational` — **Event ID 307**
  - Document Name, User, Printer Name, Time, Pages
- Đồng bộ lịch sử in đã xảy ra (kể cả khi app đang tắt)
- Fallback theo dõi Print Spooler nếu cần
- Không đánh dấu khi Document Name generic / khớp mơ hồ
- Thống kê: tổng PDF / đã in / chưa in
- Lưu trạng thái bằng SQLite (`%LOCALAPPDATA%\PDFPrintChecker`)

## Bật log in (bắt buộc lần đầu)

Log `Microsoft-Windows-PrintService/Operational` mặc định **tắt**.

Trong app bấm **Bật Event Log in** (UAC Admin), hoặc thủ công:

1. `eventvwr.msc`
2. Applications and Services Logs → Microsoft → Windows → PrintService
3. Chuột phải **Operational** → Enable Log

Nên bật thêm policy **Allow job name in event logs** (app cũng cố gắng bật khi dùng nút trên).
Nếu không bật, Document Name thường chỉ là `Print Document` → app **không** tự khớp file.

## Chạy từ mã nguồn

```bat
python -m pip install -r requirements.txt
python main.py
```

## Đóng gói EXE (có icon)

```bat
build_exe.bat
```

File chạy: `dist\PDFPrintChecker\PDFPrintChecker.exe`

Tạo shortcut Desktop (icon sẵn):

```bat
create_desktop_shortcut.bat
```

Không cần Internet, Docker hay server.

## Giao diện

- Nhóm **ĐÃ IN** / **CHƯA IN**
- Thống kê: tổng PDF, đã in, chưa in
- Nút: Chọn thư mục, Quét lại, Làm mới, Mở file PDF, Mở thư mục

## Lưu ý độ chính xác

Ứng dụng đối chiếu tên tài liệu trong Print Job với tên file PDF (sau khi bỏ hậu tố trình đọc PDF phổ biến). Nếu khớp mơ hồ / nhiều ứng viên → **không** tự đánh dấu đã in.
