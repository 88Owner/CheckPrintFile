"""Probe PrintService Operational Event ID 307."""

from __future__ import annotations

import sys

try:
    import win32evtlog
except ImportError:
    print("pywin32 missing")
    sys.exit(1)

CHANNEL = "Microsoft-Windows-PrintService/Operational"
QUERY = "*[System[(EventID=307)]]"


def main() -> None:
    try:
        handle = win32evtlog.EvtQuery(
            CHANNEL,
            win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryReverseDirection,
            QUERY,
        )
        print("EvtQuery OK")
    except Exception as exc:
        print("EvtQuery failed:", type(exc).__name__, exc)
        print("Hint: bật log Operational của PrintService nếu chưa enable.")
        return

    try:
        events = win32evtlog.EvtNext(handle, 8)
    except Exception as exc:
        print("EvtNext failed:", type(exc).__name__, exc)
        return

    print("events:", 0 if not events else len(events))
    for i, ev in enumerate(events or []):
        xml = win32evtlog.EvtRender(ev, win32evtlog.EvtRenderEventXml)
        print(f"\n===== EVENT {i} =====")
        print(xml)


if __name__ == "__main__":
    main()
