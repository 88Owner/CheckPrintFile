# PDF Print Checker

Ứng dụng desktop Windows theo dõi thư mục PDF và xác định file nào đã in xong qua Print Spooler.

## Tính năng

- Chọn thư mục PDF, lưu lại cho lần mở sau
- Quét tự động + theo dõi thay đổi thư mục (Watchdog)
- Theo dõi lệnh Print trên Windows Print Spooler (pywin32)
- Đánh dấu **ĐÃ GỬI LỆNH IN** ngay khi Spooler xuất hiện job khớp tên file PDF
- Không đánh dấu khi job bị hủy ngay, hoặc không khớp chắc chắn tên file
- Thống kê trong thư mục: tổng PDF / đã gửi lệnh in / chưa gửi lệnh in
- Lưu trạng thái bằng SQLite (`%LOCALAPPDATA%\PDFPrintChecker`)
- Nếu nội dung PDF đổi (hash SHA-256), trạng thái in được reset

## Chạy từ mã nguồn

```bat
python -m pip install -r requirements.txt
python main.py
```

## Đóng gói EXE

```bat
build_exe.bat
```

Hoặc:

```bat
python -m PyInstaller PDFPrintChecker.spec
```

File chạy: `dist\PDFPrintChecker\PDFPrintChecker.exe`

Không cần Internet, Docker hay server.

## Giao diện

- Nhóm **ĐÃ IN** / **CHƯA IN**
- Thống kê: tổng PDF, đã in, chưa in
- Nút: Chọn thư mục, Quét lại, Làm mới, Mở file PDF, Mở thư mục

## Lưu ý độ chính xác

Ứng dụng đối chiếu tên tài liệu trong Print Job với tên file PDF (sau khi bỏ hậu tố trình đọc PDF phổ biến). Nếu khớp mơ hồ / nhiều ứng viên → **không** tự đánh dấu đã in.
