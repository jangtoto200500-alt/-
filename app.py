from __future__ import annotations

import base64
import datetime as dt
import email.policy
from email.parser import BytesParser
import hmac
import hashlib
import html
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

CHANNEL_ID = "UCG2U_iDGOxCXanGmBdiJ-GA"
YT_SCOPE = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
MAX_UPLOAD_BYTES = 35 * 1024 * 1024  # 35MB: 쇼츠 시험 업로드 전용
OAUTH_COOKIE = "wonri_oauth_state"
TOKEN_LOCK = threading.Lock()
TOKEN_MEMORY = {"refresh": "", "access": "", "expires": 0}
CACHE = {"until": 0, "data": None}


def setting(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def base_url() -> str:
    return setting("APP_BASE_URL", "https://wonrihanip-shorts-monitor.onrender.com").rstrip("/")


def admin_ready() -> bool:
    return len(setting("ADMIN_PASSWORD")) >= 16


def google_ready() -> bool:
    return bool(setting("GOOGLE_CLIENT_ID") and setting("GOOGLE_CLIENT_SECRET"))


def has_refresh_token() -> bool:
    with TOKEN_LOCK:
        return bool(setting("YT_REFRESH_TOKEN") or TOKEN_MEMORY["refresh"])


def api_request(url: str, *, method="GET", headers=None, data=None, timeout=30) -> bytes:
    request = Request(url, data=data, method=method, headers=headers or {})
    with urlopen(request, timeout=timeout) as response:
        return response.read(200_000 if method == "GET" else 5_000_000)


def public_stats() -> dict:
    key = setting("YOUTUBE_API_KEY")
    if not key:
        return {"connected": False, "note": "YOUTUBE_API_KEY 미설정", "subscribers": None, "views": None, "videos": None}
    if CACHE["until"] > time.time() and CACHE["data"]:
        return CACHE["data"]
    args = urlencode({"part": "statistics", "id": CHANNEL_ID, "key": key})
    try:
        doc = json.loads(api_request("https://www.googleapis.com/youtube/v3/channels?" + args, timeout=9))
        item = (doc.get("items") or [])[0]
        if item["id"] != CHANNEL_ID:
            raise ValueError("wrong channel")
        s = item.get("statistics", {})
        result = {"connected": True, "note": "공식 공개 통계", "subscribers": int(s["subscriberCount"]) if "subscriberCount" in s else None,
                  "views": int(s["viewCount"]) if "viewCount" in s else None,
                  "videos": int(s["videoCount"]) if "videoCount" in s else None}
        CACHE.update(until=time.time() + 300, data=result)
        return result
    except Exception:
        return {"connected": False, "note": "공식 API 조회 오류: 키/할당량 확인", "subscribers": None, "views": None, "videos": None}


def exchange_token(fields: dict) -> dict:
    raw = urlencode(fields).encode("utf-8")
    result = api_request("https://oauth2.googleapis.com/token", method="POST",
                         data=raw, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=18)
    return json.loads(result)


def access_token() -> str:
    with TOKEN_LOCK:
        if TOKEN_MEMORY["access"] and time.time() < TOKEN_MEMORY["expires"] - 120:
            return TOKEN_MEMORY["access"]
        refresh = setting("YT_REFRESH_TOKEN") or TOKEN_MEMORY["refresh"]
    if not refresh or not google_ready():
        raise RuntimeError("OAuth 미설정: Google Client ID/Secret 및 Refresh Token 필요")
    result = exchange_token({"client_id": setting("GOOGLE_CLIENT_ID"),
                             "client_secret": setting("GOOGLE_CLIENT_SECRET"),
                             "refresh_token": refresh, "grant_type": "refresh_token"})
    token = result["access_token"]
    with TOKEN_LOCK:
        TOKEN_MEMORY.update(access=token, expires=time.time() + int(result.get("expires_in", 3600)))
    return token


def verify_owned_channel(token: str) -> None:
    url = "https://www.googleapis.com/youtube/v3/channels?" + urlencode({"part": "id", "mine": "true"})
    data = json.loads(api_request(url, headers={"Authorization": "Bearer " + token}, timeout=12))
    if CHANNEL_ID not in [v.get("id") for v in data.get("items", [])]:
        raise RuntimeError("승인한 Google 계정이 원리한입 채널 소유자가 아닙니다")


def private_upload(mp4: bytes, title: str, description: str, when_kr: str) -> str:
    """업로드 시 비공개 기본. 미래 일정이 있으면 YouTube 자체 예약 공개."""
    token = access_token()
    verify_owned_channel(token)
    status = {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
    if when_kr:
        kst = dt.timezone(dt.timedelta(hours=9))
        local = dt.datetime.fromisoformat(when_kr).replace(tzinfo=kst)
        if local.astimezone(dt.timezone.utc) < dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=15):
            raise ValueError("예약 시각은 현재보다 15분 이상 뒤여야 합니다")
        status["publishAt"] = local.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    meta = {"snippet": {"title": title, "description": description, "categoryId": "28", "defaultLanguage": "ko"}, "status": status}
    start_url = "https://www.googleapis.com/upload/youtube/v3/videos?" + urlencode({"uploadType": "resumable", "part": "snippet,status"})
    req = Request(start_url, data=json.dumps(meta, ensure_ascii=False).encode(), method="POST", headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(len(mp4))})
    with urlopen(req, timeout=30) as response:
        upload_url = response.headers.get("Location", "")
    host = urlsplit(upload_url)
    if host.scheme != "https" or not (host.hostname == "googleapis.com" or
            (host.hostname or "").endswith(".googleapis.com") or host.hostname == "upload.youtube.com"):
        raise RuntimeError("Google 업로드 주소를 검증하지 못했습니다")
    response = api_request(upload_url, method="PUT", data=mp4, timeout=180,
                           headers={"Authorization": "Bearer " + token, "Content-Type": "video/mp4", "Content-Length": str(len(mp4))})
    video_id = json.loads(response).get("id", "")
    if not video_id or not all(c.isalnum() or c in "-_" for c in video_id):
        raise RuntimeError("YouTube가 정상적인 videoId를 반환하지 않았습니다")
    return video_id


def safe_page(title: str, content: str) -> str:
    return f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>body{{background:#081522;color:#e5effc;font:16px system-ui,sans-serif;padding:20px;max-width:800px;margin:auto}}a{{color:#6ee5e4}}article{{background:#132b41;border:1px solid #315572;border-radius:16px;padding:22px;margin:18px 0}}input,textarea,button{{font:inherit;border-radius:8px;padding:12px;max-width:100%;box-sizing:border-box}}input,textarea{{display:block;width:100%;background:#f8fcff;color:#102336;margin:8px 0 16px}}button{{background:#17b1a7;color:white;border:0;cursor:pointer}}p{{line-height:1.6}}small{{color:#b3c9db}}</style></head><body>
<h1>원리한입 · Shorts Studio</h1>{content}<p><small>실제 업로드는 사용자 조작으로만 수행합니다. 이 서버는 수익 발생을 보장하지 않습니다.</small></p></body></html>'''


def dashboard() -> str:
    auth = "연결됨" if has_refresh_token() and google_ready() else "미연결"
    s = public_stats()
    stat = lambda x: "미확인" if s[x] is None else f'{s[x]:,}'
    oauth = '<a href="/oauth/start">YouTube 업로드 권한 인증 시작</a>' if google_ready() else '<b>Google OAuth Client ID / Secret 환경변수 미설정</b>'
    form = '''<form action="/upload" method="post" enctype="multipart/form-data">
<label>제목 (100자 이하)<input name="title" maxlength="100" required value="원리한입 | 원리가 보이는 30초"></label>
<label>설명<textarea name="description" rows="3" maxlength="2000">원리한입 오리지널 과학·기술 설명 쇼츠 #shorts</textarea></label>
<label>MP4 영상 (최대 35MB)<input type="file" name="video" accept="video/mp4" required></label>
<label>한국시간 예약 공개 (선택사항: 공란이면 비공개)<input name="schedule_kr" type="datetime-local"></label>
<button type="submit">이 영상 업로드 (기본 비공개)</button></form>'''
    return safe_page("원리한입 대시보드", f'''<article><h2>실제 채널</h2><p><a href="https://www.youtube.com/channel/{CHANNEL_ID}">원리한입 · @원리-i2m</a></p>
<p>공식 API 통계: {html.escape(s['note'])}</p><p>구독자 {stat('subscribers')} · 조회수 {stat('views')} · 공개 영상 {stat('videos')}</p>
<p>업로드 OAuth: <strong>{auth}</strong> · 실제 광고 수익: <strong>미확인</strong></p></article>
<article><h2>① Google OAuth</h2><p>{oauth}</p><p>Google의 승인을 받은 뒤 Refresh Token을 Render 비밀 환경변수 YT_REFRESH_TOKEN에 저장하면 서버 재시작 후에도 업로드 권한이 유지됩니다.</p></article>
<article><h2>② 업로드 시험</h2><p>처음에는 예약 시각을 비워 <b>비공개</b>로만 시험하세요.</p>{form}</article>''')


class Handler(BaseHTTPRequestHandler):
    server_version = "ShortsStudio/2.0"

    def log_message(self, fmt, *args):
        # OAuth authorization code, Basic 인증 헤더, API Key 로그 출력 금지
        pass

    def send(self, status: int, body: str | bytes, mime="text/html; charset=utf-8", extra=None):
        payload = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        for name, value in {"Cache-Control": "no-store", "X-Frame-Options": "DENY",
                            "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"}.items():
            self.send_header(name, value)
        for name, value in (extra or []):
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(payload)

    def authenticated(self) -> bool:
        pwd = setting("ADMIN_PASSWORD")
        if len(pwd) < 16:
            self.send(503, safe_page("설정 필요", "<article>Render 환경변수 ADMIN_PASSWORD에 16자 이상 비밀번호를 설정하세요.</article>"))
            return False
        try:
            header = self.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                raise ValueError("missing basic auth")
            plain = base64.b64decode(header[6:], validate=True).decode("utf-8")
            user, secret = plain.split(":", 1)
        except (ValueError, UnicodeError):
            user, secret = "", ""
        # hmac.compare_digest(str, str) 는 비 ASCII에서 TypeError가 나므로 bytes 비교
        if not (hmac.compare_digest(user.encode("utf-8"), setting("ADMIN_USER", "owner").encode("utf-8")) and
                hmac.compare_digest(secret.encode("utf-8"), pwd.encode("utf-8"))):
            self.send(401, "Login required", "text/plain; charset=utf-8", extra=[("WWW-Authenticate", 'Basic realm="Shorts Studio"')])
            return False
        return True

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/health", "/healthz"):
            return self.send(200, '{"status":"ok","read_only_default":true}', "application/json")
        if path == "/oauth/callback":
            return self.oauth_callback()
        if not self.authenticated():
            return
        if path == "/":
            return self.send(200, dashboard())
        if path == "/api/status":
            return self.send(200, json.dumps({"channel_id": CHANNEL_ID, "stats": public_stats(),
                                              "upload_oauth_configured": google_ready() and has_refresh_token(),
                                              "actual_revenue": None}, ensure_ascii=False), "application/json; charset=utf-8")
        if path == "/oauth/start":
            if not google_ready():
                return self.send(503, safe_page("OAuth 설정 필요", "<article>Render에 GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET을 먼저 등록하세요.</article>"))
            state = secrets.token_urlsafe(32)
            params = {"client_id": setting("GOOGLE_CLIENT_ID"), "redirect_uri": base_url() + "/oauth/callback",
                      "response_type": "code", "scope": YT_SCOPE, "state": state,
                      "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"}
            url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
            self.send(302, "Redirecting to Google", "text/plain; charset=utf-8", extra=[
                ("Set-Cookie", f"{OAUTH_COOKIE}={state}; Secure; HttpOnly; SameSite=Lax; Path=/oauth/callback; Max-Age=600"),
                ("Location", url)])
            return
        self.send(404, safe_page("404", "<article>주소를 찾지 못했습니다.</article>"))

    def oauth_callback(self):
        q = parse_qs(urlsplit(self.path).query)
        state = q.get("state", [""])[0]
        cookies = self.headers.get("Cookie", "")
        cookie_state = ""
        for segment in cookies.split(";"):
            k, sep, v = segment.strip().partition("=")
            if sep and k == OAUTH_COOKIE:
                cookie_state = v
        if not state or not cookie_state or not hmac.compare_digest(state, cookie_state):
            return self.send(403, safe_page("검증 실패", "<article>OAuth 요청 상태 검증 실패. 대시보드에서 다시 시도하세요.</article>"))
        cleared = [("Set-Cookie", f"{OAUTH_COOKIE}=; Secure; HttpOnly; SameSite=Lax; Path=/oauth/callback; Max-Age=0")]
        if q.get("error"):
            return self.send(400, safe_page("동의 취소", "<article>Google 동의가 완료되지 않았습니다.</article>"), extra=cleared)
        code = q.get("code", [""])[0]
        if not code:
            return self.send(400, safe_page("코드 누락", "<article>Google 인증 코드가 누락되었습니다.</article>"), extra=cleared)
        try:
            tok = exchange_token({"code": code, "client_id": setting("GOOGLE_CLIENT_ID"),
                                  "client_secret": setting("GOOGLE_CLIENT_SECRET"), "redirect_uri": base_url() + "/oauth/callback",
                                  "grant_type": "authorization_code"})
            verify_owned_channel(tok["access_token"])
            refresh = tok.get("refresh_token", "")
            with TOKEN_LOCK:
                TOKEN_MEMORY.update(refresh=refresh or TOKEN_MEMORY["refresh"], access=tok["access_token"],
                                    expires=time.time() + int(tok.get("expires_in", 3600)))
            if not refresh:
                message = "승인 완료. Refresh Token이 새로 발급되지 않았습니다. 이미 Render에 YT_REFRESH_TOKEN을 저장했는지 확인하세요."
            else:
                # 토큰은 URL·GitHub·로그에 절대 기록하지 않고 승인 브라우저에만 한 번 표시
                message = ("승인 완료! 서버 재시작 후에도 사용하려면 아래 민감한 값을 Render Environment의 "
                           "YT_REFRESH_TOKEN에 직접 저장하세요. 타인과 공유하지 마세요."
                           f"<textarea readonly rows='5'>{html.escape(refresh)}</textarea>")
            return self.send(200, safe_page("OAuth 성공", f"<article><h2>YouTube 승인 성공</h2><p>{message}</p><p><a href='/'>대시보드로 이동</a></p></article>"), extra=cleared)
        except Exception:
            return self.send(502, safe_page("OAuth 연결 오류", "<article>Google 권한 확인에 실패했습니다. 승인한 채널, OAuth 클라이언트와 리디렉션 URI를 확인하세요.</article>"), extra=cleared)

    def do_POST(self):
        if urlsplit(self.path).path != "/upload":
            return self.send(405, "not allowed", "text/plain")
        if not self.authenticated():
            return
        if self.headers.get("Origin", "") != base_url():
            return self.send(403, safe_page("요청 차단", "<article>허용되지 않은 출처의 요청입니다.</article>"))
        if not (google_ready() and has_refresh_token()):
            return self.send(503, safe_page("OAuth 미연결", "<article>YouTube 업로드 OAuth를 먼저 연결하세요.</article>"))
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not (1 <= length <= MAX_UPLOAD_BYTES + 16_384):
            return self.send(413, safe_page("용량 초과", "<article>MP4 영상 크기는 최대 35MB입니다.</article>"))
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data;"):
            return self.send(415, "multipart required", "text/plain")
        payload = self.rfile.read(length)
        message = BytesParser(policy=email.policy.default).parsebytes(
            b"MIME-Version: 1.0\r\nContent-Type: " + content_type.encode("ascii", "ignore") + b"\r\n\r\n" + payload)
        fields = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name:
                fields[name] = part.get_payload(decode=True) or b""
        try:
            title = fields.get("title", b"").decode("utf-8").strip()
            description = fields.get("description", b"").decode("utf-8").strip()
            schedule = fields.get("schedule_kr", b"").decode("utf-8").strip()
            media = fields.get("video", b"")
            if not 1 <= len(title) <= 100 or len(description) > 2000:
                raise ValueError("제목은 1~100자, 설명은 2,000자 이하여야 합니다")
            if not 12 < len(media) <= MAX_UPLOAD_BYTES or media[4:8] != b"ftyp":
                raise ValueError("유효한 MP4 파일을 선택하세요")
            video_id = private_upload(media, title, description, schedule)
            return self.send(200, safe_page("업로드 완료", f"<article><h2>시험 업로드 성공</h2><p><a href='https://studio.youtube.com/video/{html.escape(video_id)}/edit'>YouTube Studio에서 비공개 영상 확인</a></p><p>공개 상태: {'예약 공개' if schedule else '비공개'}</p></article>"))
        except ValueError as error:
            return self.send(400, safe_page("입력 오류", "<article>" + html.escape(str(error)) + "</article>"))
        except Exception:
            return self.send(502, safe_page("업로드 실패", "<article>Google OAuth/API 오류가 발생했습니다. OAuth 권한, API 할당량, 채널 선택을 확인하세요. 영상을 다시 업로드하기 전에 YouTube Studio에서 중복 여부를 확인하세요.</article>"))


if __name__ == "__main__":
    port = int(setting("PORT", "10000"))
    print("Shorts Studio ready; password and tokens are never printed", flush=True)
    print("CONFIG_READY admin={} google_oauth={} refresh_token={} youtube_public_api={}".format(admin_ready(), google_ready(), has_refresh_token(), bool(setting("YOUTUBE_API_KEY"))), flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
