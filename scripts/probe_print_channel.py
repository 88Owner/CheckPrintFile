"""Kiểm tra channel PrintService và thử bật nếu cần."""

from __future__ import annotations

import subprocess
import sys

try:
    import win32evtlog
except ImportError:
    print("pywin32 missing")
    sys.exit(1)

CHANNEL = "Microsoft-Windows-PrintService/Operational"


def wevtutil(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["wevtutil", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out


def main() -> None:
    code, out = wevtutil("gl", CHANNEL)
    print("=== wevtutil gl ===")
    print(out)

    # Đếm mọi event gần đây (không lọc ID)
    for eid in (307, 805, 800, 801, 842):
        q = f"*[System[(EventID={eid})]]"
        try:
            h = win32evtlog.EvtQuery(
                CHANNEL,
                win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryReverseDirection,
                q,
            )
            evs = win32evtlog.EvtNext(h, 3) or []
            print(f"EventID {eid}: {len(evs)} recent")
            if evs:
                xml = win32evtlog.EvtRender(evs[0], win32evtlog.EvtRenderEventXml)
                print(xml[:1800])
                print("---")
        except Exception as exc:
            print(f"EventID {eid}: error {exc}")

    # Thử query không lọc
    try:
        h = win32evtlog.EvtQuery(
            CHANNEL,
            win32evtlog.EvtQueryChannelPath | win32evtlog.EvtQueryReverseDirection,
            "*",
        )
        evs = win32evtlog.EvtNext(h, 5) or []
        print(f"Any events: {len(evs)}")
        if evs:
            print(win32evtlog.EvtRender(evs[0], win32evtlog.EvtRenderEventXml)[:2000])
    except Exception as exc:
        print("Any query failed:", exc)


if __name__ == "__main__":
    main()
