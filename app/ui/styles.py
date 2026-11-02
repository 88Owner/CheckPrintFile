"""Style sheet giao diện rõ ràng, tách màu ĐÃ / CHƯA gửi lệnh in."""

APP_STYLESHEET = """
* {
    font-family: "Segoe UI", "Tahoma", sans-serif;
    font-size: 13px;
}

QMainWindow, QWidget#central {
    background-color: #eef2f6;
    color: #1a2332;
}

QLabel#titleLabel {
    font-size: 22px;
    font-weight: 700;
    color: #0f1c2e;
}

QLabel#subtitleLabel {
    color: #5b6b7c;
    font-size: 12px;
}

QLabel#folderLabel {
    color: #334155;
    font-size: 12px;
    font-weight: 600;
    padding: 4px 0;
}

/* ── Thanh thống kê ── */
QFrame#statsBar {
    background-color: #ffffff;
    border: 1px solid #cfd8e3;
    border-radius: 12px;
}

QFrame#statCardTotal {
    background-color: #f1f5f9;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    min-width: 110px;
}

QFrame#statCardPrinted {
    background-color: #ecfdf5;
    border: 2px solid #10b981;
    border-radius: 10px;
    min-width: 130px;
}

QFrame#statCardPending {
    background-color: #fff7ed;
    border: 2px solid #f97316;
    border-radius: 10px;
    min-width: 140px;
}

QLabel#statTotalValue, QLabel#statPrinted, QLabel#statPending {
    font-size: 26px;
    font-weight: 800;
}

QLabel#statTotalValue { color: #1e293b; }
QLabel#statPrinted { color: #047857; }
QLabel#statPending { color: #c2410c; }

QLabel#statTotalCap, QLabel#statPrintedCap, QLabel#statPendingCap {
    font-size: 11px;
    font-weight: 600;
}

QLabel#statTotalCap { color: #64748b; }
QLabel#statPrintedCap { color: #059669; }
QLabel#statPendingCap { color: #ea580c; }

/* ── Nút ── */
QPushButton {
    background-color: #ffffff;
    border: 1px solid #94a3b8;
    border-radius: 8px;
    padding: 9px 14px;
    color: #1e293b;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #f8fafc;
    border-color: #64748b;
}

QPushButton:pressed {
    background-color: #e2e8f0;
}

QPushButton#primaryButton {
    background-color: #2563eb;
    color: #ffffff;
    border: none;
}

QPushButton#primaryButton:hover {
    background-color: #1d4ed8;
}

QPushButton#primaryButton:pressed {
    background-color: #1e40af;
}

/* ── Nhóm ĐÃ GỬI (xanh) ── */
QGroupBox#boxPrinted {
    background-color: #f0fdf4;
    border: 2px solid #22c55e;
    border-radius: 12px;
    margin-top: 18px;
    padding-top: 14px;
    font-weight: 700;
    font-size: 14px;
    color: #166534;
}

QGroupBox#boxPrinted::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 2px 10px;
    background-color: #22c55e;
    color: #ffffff;
    border-radius: 6px;
}

QTreeWidget#treePrinted {
    background-color: #ffffff;
    border: 1px solid #86efac;
    border-radius: 8px;
    outline: none;
    alternate-background-color: #f0fdf4;
    color: #14532d;
}

QTreeWidget#treePrinted::item:selected {
    background-color: #86efac;
    color: #14532d;
}

QTreeWidget#treePrinted QHeaderView::section {
    background-color: #dcfce7;
    border: none;
    border-bottom: 1px solid #86efac;
    padding: 8px;
    color: #166534;
    font-weight: 700;
}

/* ── Nhóm CHƯA GỬI (cam) — nổi bật ── */
QGroupBox#boxPending {
    background-color: #fff7ed;
    border: 2px solid #f97316;
    border-radius: 12px;
    margin-top: 18px;
    padding-top: 14px;
    font-weight: 700;
    font-size: 14px;
    color: #9a3412;
}

QGroupBox#boxPending::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 2px 10px;
    background-color: #f97316;
    color: #ffffff;
    border-radius: 6px;
}

QTreeWidget#treePending {
    background-color: #ffffff;
    border: 1px solid #fdba74;
    border-radius: 8px;
    outline: none;
    alternate-background-color: #ffedd5;
    color: #7c2d12;
    font-weight: 600;
}

QTreeWidget#treePending::item {
    padding: 8px 4px;
    border-bottom: 1px solid #fed7aa;
}

QTreeWidget#treePending::item:selected {
    background-color: #fb923c;
    color: #ffffff;
}

QTreeWidget#treePending QHeaderView::section {
    background-color: #ffedd5;
    border: none;
    border-bottom: 2px solid #f97316;
    padding: 8px;
    color: #9a3412;
    font-weight: 700;
}

QTreeWidget::item {
    padding: 7px 4px;
}

QStatusBar {
    background-color: #ffffff;
    border-top: 1px solid #cbd5e1;
    color: #475569;
}

QToolTip {
    background-color: #0f172a;
    color: #ffffff;
    border: none;
    padding: 6px;
}
"""
