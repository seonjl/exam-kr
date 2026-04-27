"""sitemap.xml 생성: / + /exam/<code> + /exam/<code>/<session>"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
OUT = ROOT / "webapp" / "sitemap.xml"
BASE = sys.argv[1] if len(sys.argv) > 1 else ""


def main() -> None:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    lines.append(f"  <url><loc>{BASE}/</loc><priority>1.0</priority></url>")
    exams = json.loads((DATA / "exams.json").read_text(encoding="utf-8"))["exams"]
    for e in exams:
        code = e["code"]
        lines.append(f"  <url><loc>{BASE}/exam/{code}</loc><priority>0.8</priority></url>")
        sess_path = DATA / code / "sessions.json"
        if not sess_path.exists():
            continue
        for s in json.loads(sess_path.read_text(encoding="utf-8"))["sessions"]:
            lines.append(f"  <url><loc>{BASE}/exam/{code}/{s['code']}</loc><priority>0.6</priority></url>")
    lines.append("</urlset>")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
