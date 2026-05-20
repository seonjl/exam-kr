"""공통 GLM API 호출 모듈.

scripts/enrich.py, extract_concepts.py, normalize_concepts.py 에서 공통 사용.
기존 call_claude() (claude -p 서브프로세스) 를 GLM OpenAI 호환 API 로 교체.

설정:
- API 키: 환경변수 GLM_API_KEY 또는 ~/.hermes/auth.json 의 zai credential_pool
- base_url: 환경변수 GLM_BASE_URL 또는 기본 https://api.z.ai/api/coding/paas/v4
- 모델: 환경변수 GLM_MODEL 또는 기본 glm-4.5-air (비용 효율)
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from openai import OpenAI

# ── 설정 ──────────────────────────────────────────────

def _load_credentials() -> tuple[str, str]:
    """API 키와 base_url 을 우선순위대로 로드."""
    key = os.environ.get("GLM_API_KEY")
    base = os.environ.get("GLM_BASE_URL")
    if key:
        return key, base or "https://api.z.ai/api/coding/paas/v4"

    # fallback: ~/.hermes/auth.json
    auth_path = Path.home() / ".hermes" / "auth.json"
    if auth_path.exists():
        d = json.loads(auth_path.read_text(encoding="utf-8"))
        pool = d.get("credential_pool", {}).get("zai", [])
        if pool:
            entry = pool[0]
            return entry["access_token"], entry.get("base_url", "https://api.z.ai/api/coding/paas/v4")

    raise RuntimeError("GLM_API_KEY 환경변수 또는 ~/.hermes/auth.json(zai) 이 필요합니다.")


API_KEY, BASE_URL = _load_credentials()
DEFAULT_MODEL = os.environ.get("GLM_MODEL", "glm-4.5")

# 싱글톤 클라이언트 (스레드세이프)
_client = None
_client_lock = threading.Lock()


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    return _client


# ── 공용 함수 ─────────────────────────────────────────

def call_glm(
    prompt: str,
    *,
    model: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.7,
    timeout: int = 120,
    retries: int = 3,
) -> str:
    """GLM API 로 텍스트 생성. 기존 call_claude() 와 동일 인터페이스.

    Returns: 생성된 텍스트 (stripped)
    Raises: RuntimeError after retries exhausted
    """
    model = model or DEFAULT_MODEL
    client = _get_client()
    last_err = ""

    for attempt in range(retries):
        if attempt:
            time.sleep(2 + 2 * attempt)
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
            out = (resp.choices[0].message.content or "").strip()
            if not out:
                last_err = "empty output"
                continue
            return out
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            continue

    raise RuntimeError(f"GLM API failed after {retries} retries: {last_err}")


# ── CLI 테스트 ─────────────────────────────────────────

if __name__ == "__main__":
    import sys
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "1+1=? 답만 출력해"
    print(f"model={DEFAULT_MODEL} prompt={prompt!r}")
    t0 = time.time()
    result = call_glm(prompt)
    dt = time.time() - t0
    print(f"→ {result!r} ({dt:.1f}s)")
