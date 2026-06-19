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

    # fallback: ~/.hermes/.env (수동 파싱, dotenv 불필요)
    env_path = Path.home() / ".hermes" / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if k == "GLM_API_KEY" and v:
                key = v
            elif k == "GLM_BASE_URL" and v and not base:
                base = v
        if key:
            return key, base or "https://api.z.ai/api/coding/paas/v4"

    raise RuntimeError("GLM_API_KEY 환경변수 또는 ~/.hermes/.env 이 필요합니다.")


API_KEY, BASE_URL = _load_credentials()
DEFAULT_MODEL = os.environ.get("GLM_MODEL", "glm-4.5")
# GLM_MODEL_CHAIN: 쉼표구분, 좋은 모델부터. 각 모델 fail 시 다음으로 fallback.
DEFAULT_CHAIN = [m.strip() for m in os.environ.get("GLM_MODEL_CHAIN", "").split(",") if m.strip()]

# 싱글톤 클라이언트 (스레드세이프)
_client = None
_client_lock = threading.Lock()


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = OpenAI(api_key=API_KEY, base_url=BASE_URL,
                                 max_retries=0, timeout=90)
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

    GLM_MODEL_CHAIN 환경변수가 설정되어 있으면 좋은 모델부터 시도, 실패 시 다음으로 fallback.
    각 모델은 `retries` 회 시도 후 다음 모델로 넘어감. 마지막 모델까지 실패 시 raise.
    429 (rate limit) / empty output 은 지수 백오프 (5, 10, 20, 40, 60초).

    Returns: 생성된 텍스트 (stripped)
    Raises: RuntimeError after all models exhausted
    """
    if model:
        chain = [model]
    elif DEFAULT_CHAIN:
        chain = list(DEFAULT_CHAIN)
    else:
        chain = [DEFAULT_MODEL]

    client = _get_client()
    last_err = ""

    for mdl in chain:
        for attempt in range(retries):
            try:
                resp = _create_with_hard_timeout(
                    client, mdl, prompt, max_tokens, temperature, timeout,
                )
                out = (resp.choices[0].message.content or "").strip()
                if not out:
                    last_err = f"{mdl}: empty output"
                    _rate_limit_backoff(attempt, last_err)
                    continue
                return out
            except Exception as e:
                last_err = f"{mdl}: {type(e).__name__}: {e}"
                _rate_limit_backoff(attempt, last_err)
                continue

    raise RuntimeError(f"GLM API failed after all models in chain ({chain}): {last_err}")


class _HardTimeoutError(Exception):
    pass


def _create_with_hard_timeout(client, model, prompt, max_tokens, temperature, timeout):
    """signal.alarm 기반 하드 타임아웃. streaming 대기 없이 강제 종료."""
    import signal

    def _handler(signum, frame):
        raise _HardTimeoutError(f"hard timeout {timeout}s")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
        return resp
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def _rate_limit_backoff(attempt: int, reason: str):
    """429 / empty output 에 대한 지수 백오프. attempt 는 0부터."""
    delays = [5, 10, 20, 40, 60]
    delay = delays[min(attempt, len(delays) - 1)]
    if attempt > 0 or "429" in reason or "empty" in reason:
        print(f"    [backoff] {delay}s (attempt {attempt+1}): {reason[:80]}",
              flush=True)
    time.sleep(delay)


# ── CLI 테스트 ─────────────────────────────────────────

if __name__ == "__main__":
    import sys
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "1+1=? 답만 출력해"
    print(f"model={DEFAULT_MODEL} prompt={prompt!r}")
    t0 = time.time()
    result = call_glm(prompt)
    dt = time.time() - t0
    print(f"→ {result!r} ({dt:.1f}s)")
