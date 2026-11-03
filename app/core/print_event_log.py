"""Đọc lịch sử in từ Event Viewer: PrintService/Operational — Event ID 307."""

from __future__ import annotations

import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

CHANNEL = "Microsoft-Windows-PrintService/Operational"
EVENT_ID_PRINTED = 307

# Namespace Event Log XML
_NS = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}

# Policy ghi tên tài liệu vào event (nếu không bật → Param2 = "Print Document")
_JOB_NAME_REG = r"HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Printers"
_JOB_NAME_VALUE = "AllowJobNameInEvents"

# Cache trạng thái channel — tránh gọi wevtutil liên tục (gây nháy cửa sổ console)
_channel_lock = threading.Lock()
_channel_cached: bool | None = None
_channel_checked_at: float = 0.0
_CHANNEL_CACHE_TTL = 30.0  # giây


def _subprocess_kwargs() -> dict:
    """Chạy process ẩn, không nháy cửa sổ CMD trên Windows."""
    kwargs: dict = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
    }
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs



@dataclass(frozen=True)
class PrintServiceEvent307:
    """Chi tiết Event ID 307 — DocumentPrinted."""

    record_id: int
    event_time: datetime  # UTC
    job_id: int | None
    document_name: str
    user_name: str
    client_computer: str
    printer_name: str
    port_name: str
    size_bytes: int | None
    pages: int | None

    @property
    def document_is_generic(self) -> bool:
        name = (self.document_name or "").strip().lower()
        return name in {"", "print document", "document"}


def invalidate_channel_cache() -> None:
    global _channel_cached, _channel_checked_at
    with _channel_lock:
        _channel_cached = None
        _channel_checked_at = 0.0


def is_channel_enabled(*, force: bool = False) -> bool:
    """
    Kiểm tra PrintService/Operational đã bật chưa.
    Có cache 30s để worker không gọi wevtutil mỗi vài giây (tránh nháy console).
    """
    global _channel_cached, _channel_checked_at
    now = time.monotonic()
    with _channel_lock:
        if (
            not force
            and _channel_cached is not None
            and (now - _channel_checked_at) < _CHANNEL_CACHE_TTL
        ):
            return _channel_cached

    enabled = _read_channel_enabled()
    with _channel_lock:
        _channel_cached = enabled
        _channel_checked_at = time.monotonic()
    return enabled


def _read_channel_enabled() -> bool:
    code, out = _wevtutil("gl", CHANNEL)
    if code != 0:
        return False
    for line in out.splitlines():
        if line.strip().lower().startswith("enabled:"):
            return "true" in line.lower()
    return False


def enable_channel_elevated() -> tuple[bool, str]:
    """
    Bật log Operational + cho phép ghi tên job vào event.
    Dùng UAC (runas). Trả về (ok, message).
    """
    ps = (
        f'wevtutil sl "{CHANNEL}" /e:true; '
        f'New-Item -Path "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows NT\\Printers" '
        f"-Force | Out-Null; "
        f'Set-ItemProperty -Path "HKLM:\\SOFTWARE\\Policies\\Microsoft\\Windows NT\\Printers" '
        f'-Name "{_JOB_NAME_VALUE}" -Value 1 -Type DWord -Force'
    )
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-WindowStyle",
            "Hidden",
            "-Command",
            (
                "Start-Process powershell -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList "
                f"'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command \"{ps}\"'"
            ),
        ]
        proc = subprocess.run(cmd, **_subprocess_kwargs())
        invalidate_channel_cache()
        if is_channel_enabled(force=True):
            return True, "Đã bật PrintService/Operational và Allow job name in event logs."
        detail = (proc.stderr or proc.stdout or "").strip()
        return False, detail or "Chưa bật được log (có thể đã hủy UAC)."
    except OSError as exc:
        return False, str(exc)


def _wevtutil(*args: str) -> tuple[int, str]:
    proc = subprocess.run(["wevtutil", *args], **_subprocess_kwargs())
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _parse_system_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    # 2024-01-01T12:00:00.1234567Z
    cleaned = value.replace("Z", "+00:00")
    if "." in cleaned:
        head, rest = cleaned.split(".", 1)
        frac = ""
        tz = "+00:00"
        for i, ch in enumerate(rest):
            if ch.isdigit():
                frac += ch
            else:
                tz = rest[i:]
                break
        frac = (frac + "000000")[:6]
        cleaned = f"{head}.{frac}{tz}"
    try:
        dt = datetime.fromisoformat(cleaned)
    except ValueError:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_event_xml(xml_text: str) -> PrintServiceEvent307 | None:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    event_id_el = root.find("e:System/e:EventID", _NS)
    if event_id_el is None or (event_id_el.text or "").strip() != str(EVENT_ID_PRINTED):
        return None

    record_el = root.find("e:System/e:EventRecordID", _NS)
    time_el = root.find("e:System/e:TimeCreated", _NS)
    record_id = int((record_el.text or "0").strip() or 0)
    event_time = _parse_system_time(time_el.get("SystemTime") if time_el is not None else None)

    # UserData/DocumentPrinted/Param1..Param8 (namespace publisher thay đổi theo bản Windows)
    doc_node = None
    for child in root.iter():
        if child.tag.endswith("DocumentPrinted"):
            doc_node = child
            break
    if doc_node is None:
        return None

    def param(n: int) -> str:
        for el in doc_node:
            if el.tag.endswith(f"Param{n}"):
                return (el.text or "").strip()
        return ""


    def to_int(s: str) -> int | None:
        try:
            return int(s.replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    return PrintServiceEvent307(
        record_id=record_id,
        event_time=event_time,
        job_id=to_int(param(1)),
        document_name=param(2),
        user_name=param(3),
        client_computer=param(4),
        printer_name=param(5),
        port_name=param(6),
        size_bytes=to_int(param(7)),
        pages=to_int(param(8)),
    )


def iter_event_307(
    *,
    max_events: int = 500,
    after_record_id: int | None = None,
) -> list[PrintServiceEvent307]:
    """
    Đọc Event ID 307 (mới → cũ), trả về list đã parse.
    Nếu after_record_id: chỉ lấy record_id > after_record_id.
    """
    try:
        import win32evtlog
    except ImportError as exc:
        raise RuntimeError("Thiếu pywin32") from exc

    query = f"*[System[(EventID={EVENT_ID_PRINTED})]]"
    try:
        handle = win32evtlog.EvtQuery(
            CHANNEL,
            win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryReverseDirection,
            query,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Không đọc được {CHANNEL}: {exc}") from exc

    results: list[PrintServiceEvent307] = []
    remaining = max_events
    while remaining > 0:
        batch = min(50, remaining)
        try:
            events = win32evtlog.EvtNext(handle, batch)
        except Exception:
            break
        if not events:
            break
        for ev in events:
            xml_text = win32evtlog.EvtRender(ev, win32evtlog.EvtRenderEventXml)
            parsed = parse_event_xml(xml_text)
            if parsed is None:
                continue
            if after_record_id is not None and parsed.record_id <= after_record_id:
                # Vì đọc ngược thời gian: gặp record cũ hơn → dừng
                return list(reversed(results))
            results.append(parsed)
        remaining -= len(events)

    # results đang mới→cũ; trả về cũ→mới để xử lý theo thứ tự thời gian
    return list(reversed(results))


def watch_new_events(last_record_id: int, *, limit: int = 100) -> list[PrintServiceEvent307]:
    """Lấy các Event 307 mới hơn last_record_id."""
    # Dùng cache; không force để tránh gọi wevtutil mỗi vòng poll
    if not is_channel_enabled(force=False):
        return []
    try:
        events = iter_event_307(
            max_events=limit,
            after_record_id=last_record_id if last_record_id > 0 else None,
        )
    except RuntimeError:
        return []
    if last_record_id <= 0:
        return events
    return [e for e in events if e.record_id > last_record_id]
