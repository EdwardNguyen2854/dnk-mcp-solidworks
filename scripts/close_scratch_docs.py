#!/usr/bin/env python
"""Close probe leftovers: unsaved part/assembly/drawing documents.

Probe scripts discard their scratch documents, but a crashed or timed-out
probe leaves them open (and they cost memory). This closes every open
document that has no file path and an auto-generated name
(Part12, Assembly3, Drawing7); anything with a path is never touched.

    python scripts/close_scratch_docs.py            # close leftovers
    python scripts/close_scratch_docs.py --dry-run  # list only
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from solidworks_mcp.com import binding  # noqa: E402
from solidworks_mcp.domain import session  # noqa: E402

SCRATCH_NAME = re.compile(r"^(Part|Assembly|Drawing)\d+$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    application = session.app()
    raw_docs = application.GetDocuments() or []
    targets = []
    for raw in raw_docs:
        doc = session.wrap_doc(raw)
        title = str(binding.value(doc.GetTitle))
        path = str(binding.value(doc.GetPathName))
        if path or not SCRATCH_NAME.match(title):
            continue
        targets.append((doc, title))

    print(f"open: {len(raw_docs)}; scratch candidates: {len(targets)}")
    for _, title in targets:
        print(f"  {title}")

    if args.dry_run:
        return 0
    closed = 0
    for doc, title in targets:
        try:
            doc.SetSaveFlag()
            # CloseDoc returns nothing on this build; success means the title
            # is gone from the open-document list afterwards.
            application.CloseDoc(title)
            if title not in {
                str(binding.value(session.wrap_doc(raw).GetTitle))
                for raw in application.GetDocuments() or []
            }:
                closed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  failed to close {title}: {type(exc).__name__}: {exc}")
    print(f"closed: {closed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
