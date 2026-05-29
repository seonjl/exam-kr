#!/usr/bin/env python3
"""빈 보기 이미지 → 비전 모델 텍스트 변환.

comcbt 이미지 URL이 있는 빈 보기를 glm-4.5v로 텍스트 변환.
비파괴 — 기존 필드 보존, choice.text만 채움.

Usage:
    .venv/bin/python3 scripts/vision_fill_choices.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import ssl
import sys
import time
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image

# ── GLM 클라이언트 ──
sys.path.insert(0, str(Path(__file__).resolve().parent))
from call_glm import _load_credentials
from openai import OpenAI

EXAMS = ["s2", "g1", "g2", "iz", "sa", "c1", "k1", "kt", "nd"]

# ── 이미지 처리 ──

def download_to_b64(url: str) -> str:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120"
    })
    resp = urllib.request.urlopen(req, context=ctx, timeout=15)
    data = resp.read()
    img = Image.open(BytesIO(data))
    if img.mode in ("P", "PA"):
        img = img.convert("RGBA")
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3] if "A" in img.mode else None)
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def vision_ocr(client: OpenAI, b64_jpg: str) -> str:
    resp = client.chat.completions.create(
        model="glm-4.5v",
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "이 이미지에 있는 수식, 기호, 텍스트를 정확히 읽어서 "
                        "LaTeX 또는 일반 텍스트로 변환해. "
                        "다른 설명은 하지 말고 내용만 출력해."
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64_jpg}"},
                },
            ],
        }],
        max_tokens=300,
    )
    return resp.choices[0].message.content.strip()


# ── 메인 ──

def collect_targets() -> list[tuple[str, str, dict, dict]]:
    """빈 보기 + comcbt 이미지 + vision_summary 없는 문항 수집."""
    targets = []
    for exam in EXAMS:
        files = sorted(glob.glob(f"data/{exam}/{exam}_*.json"))
        for f in files:
            with open(f) as fh:
                data = json.load(fh)
            for q in data["questions"]:
                choices = q.get("choices", [])
                has_empty = any(not c.get("text", "").strip() for c in choices)
                has_comcbt = any(
                    "comcbt" in img
                    for c in choices
                    for img in c.get("images", [])
                    if isinstance(img, str)
                )
                if has_empty and has_comcbt and not q.get("vision_image_summary"):
                    targets.append((exam, f, data, q))
    return targets


def process_one(client: OpenAI, q: dict) -> dict:
    """한 문항의 빈 보기를 비전 처리. 변경 내역 반환."""
    changes = {"filled": 0, "errors": 0, "details": []}
    choices = q.get("choices", [])

    for i, c in enumerate(choices):
        if c.get("text", "").strip():
            continue
        imgs = c.get("images", [])
        texts = []
        for img_url in imgs:
            if not isinstance(img_url, str) or "comcbt" not in img_url:
                continue
            try:
                b64 = download_to_b64(img_url)
                text = vision_ocr(client, b64)
                texts.append(text)
                time.sleep(0.3)
            except Exception as e:
                changes["errors"] += 1
                changes["details"].append(f"보기{i+1} 오류: {e}")

        if texts:
            combined = " / ".join(texts)
            c["text"] = combined
            changes["filled"] += 1
            changes["details"].append(f"보기{i+1}: {combined[:60]}")

    return changes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    key, base_url = _load_credentials()
    client = OpenAI(api_key=key, base_url=base_url)

    targets = collect_targets()
    print(f"처리 대상: {len(targets)}문항", flush=True)

    if args.limit:
        targets = targets[:args.limit]

    total_filled = 0
    total_errors = 0

    for idx, (exam, fpath, data, q) in enumerate(targets):
        label = f"[{exam}] {data['date']} Q{q['number']}"
        print(f"[{idx+1}/{len(targets)}] {label}", end=" ", flush=True)

        if args.dry_run:
            imgs_count = sum(
                1 for c in q["choices"]
                for img in c.get("images", [])
                if isinstance(img, str) and "comcbt" in img and not c.get("text", "").strip()
            )
            print(f"(dry-run) {imgs_count} 이미지", flush=True)
            continue

        result = process_one(client, q)
        total_filled += result["filled"]
        total_errors += result["errors"]

        if result["filled"]:
            print(f"채움 {result['filled']}개", end=" ", flush=True)
        if result["errors"]:
            print(f"오류 {result['errors']}개", end=" ", flush=True)
        print(flush=True)

        # 파일 저장
        if result["filled"] and not args.dry_run:
            with open(fpath, "w") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)

        time.sleep(0.2)

    print(f"\n완료: 채움 {total_filled} 보기, 오류 {total_errors}건", flush=True)


if __name__ == "__main__":
    main()
