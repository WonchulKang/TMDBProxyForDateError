import re
import json
import logging
import argparse
from datetime import datetime, timezone

import requests
from flask import Flask, request, Response

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
TMDB_BASE_URL = "https://api.themoviedb.org"

# UTC 날짜 패턴: "2019-04-29 08:21:50 UTC"
UTC_DATE_PATTERN = re.compile(
    r'"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)"'
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)


# ──────────────────────────────────────────────
# 날짜 변환
# ──────────────────────────────────────────────
def convert_utc_dates(text: str) -> tuple[str, int]:
    """
    응답 본문에서 TMDB UTC 날짜 문자열을 ISO 8601로 변환합니다.
    Returns (변환된 텍스트, 변환 횟수)
    """
    count = 0

    def replacer(match: re.Match) -> str:
        nonlocal count
        raw = match.group(1)  # e.g. "2019-04-29 08:21:50 UTC"
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S UTC")
            dt = dt.replace(tzinfo=timezone.utc)
            iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            count += 1
            return f'"{iso}"'
        except ValueError:
            log.warning("날짜 변환 실패: %s", raw)
            return match.group(0)

    result = UTC_DATE_PATTERN.sub(replacer, text)
    return result, count


# ──────────────────────────────────────────────
# 프록시 핸들러
# ──────────────────────────────────────────────
@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def proxy(path: str):
    target_url = f"{TMDB_BASE_URL}/{path}"

    # 요청 헤더 복사 (hop-by-hop 헤더 제외)
    excluded_headers = {"host", "content-length", "transfer-encoding", "connection"}
    headers = {
        k: v for k, v in request.headers
        if k.lower() not in excluded_headers
    }

    try:
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            params=request.args,
            data=request.get_data(),
            timeout=15,
            allow_redirects=False,
        )
    except requests.RequestException as e:
        log.error("TMDB 요청 실패: %s", e)
        return Response(f"Proxy error: {e}", status=502)

    # Content-Type 확인
    content_type = resp.headers.get("Content-Type", "")
    is_json = "application/json" in content_type

    if is_json:
        body_text = resp.text
        converted, count = convert_utc_dates(body_text)
        if count:
            log.info("날짜 변환: %d개 (%s)", count, path)
        body = converted.encode("utf-8")
    else:
        body = resp.content

    # 응답 헤더 복사
    response_headers = {
        k: v for k, v in resp.headers.items()
        if k.lower() not in {"content-encoding", "transfer-encoding", "content-length", "connection"}
    }

    return Response(
        body,
        status=resp.status_code,
        headers=response_headers,
    )


# ──────────────────────────────────────────────
# 진입점
# ──────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TMDB Proxy for Jellyfin")
    parser.add_argument("--host", default="0.0.0.0", help="바인딩 주소 (기본: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=21514, help="포트 번호 (기본: 21514)")
    parser.add_argument("--debug", action="store_true", help="디버그 모드")
    args = parser.parse_args()

    log.info("TMDB 프록시 시작: http://%s:%d → %s", args.host, args.port, TMDB_BASE_URL)
    app.run(host=args.host, port=args.port, debug=args.debug)