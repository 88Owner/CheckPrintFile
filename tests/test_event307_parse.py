"""Parse Event ID 307 XML."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.print_event_log import parse_event_xml

SAMPLE = """<?xml version="1.0"?>
<Event xmlns="http://schemas.microsoft.com/win/2004/08/events/event">
  <System>
    <Provider Name="Microsoft-Windows-PrintService"/>
    <EventID>307</EventID>
    <TimeCreated SystemTime="2026-11-03T02:15:30.1234567Z"/>
    <EventRecordID>42</EventRecordID>
    <Channel>Microsoft-Windows-PrintService/Operational</Channel>
  </System>
  <UserData>
    <DocumentPrinted xmlns="http://schemas.microsoft.com/windows/2011/08/windows/WMI">
      <Param1>7</Param1>
      <Param2>hoa_don_01.pdf</Param2>
      <Param3>ADMIN</Param3>
      <Param4>\\\\DESKTOP-PC</Param4>
      <Param5>Microsoft Print to PDF</Param5>
      <Param6>PORTPROMPT:</Param6>
      <Param7>20480</Param7>
      <Param8>3</Param8>
    </DocumentPrinted>
  </UserData>
</Event>
"""


def test_parse_fields():
    ev = parse_event_xml(SAMPLE)
    assert ev is not None
    assert ev.record_id == 42
    assert ev.job_id == 7
    assert ev.document_name == "hoa_don_01.pdf"
    assert ev.user_name == "ADMIN"
    assert ev.printer_name == "Microsoft Print to PDF"
    assert ev.pages == 3
    assert ev.size_bytes == 20480
    assert not ev.document_is_generic


def test_generic_document():
    xml = SAMPLE.replace("hoa_don_01.pdf", "Print Document")
    ev = parse_event_xml(xml)
    assert ev is not None
    assert ev.document_is_generic


if __name__ == "__main__":
    test_parse_fields()
    test_generic_document()
    print("OK: event 307 parse tests passed")
