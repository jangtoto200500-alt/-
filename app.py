"""Read-only, owner-password-protected Shorts Studio companion for Render.

This service NEVER accepts credentials, performs YouTube OAuth, or uploads a video.
For deployment: add strong ADMIN_PASSWORD via Render secret environment variables.
"""
from __future__ import annotations

import base64
import datetime as dt
import hmac
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHANNEL_ID = 'UCG2U_iDGOxCXanGmBdiJ-GA'  # Already confirmed on vidIQ; not a secret.
CHANNEL_URL = 'https://www.youtube.com/channel/' + CHANNEL_ID
_CACHE = {'data': None, 'expires': 0}
_CACHE_LOCK = threading.Lock()


def read_public_youtube_stats(fetch=None):
    """Only PUBLIC channel statistics. An API key cannot authorize uploads."""
    key = os.getenv('YOUTUBE_API_KEY', '').strip()
    if not key:
        return {'state': '미연결', 'reason': 'YouTube Data API Key가 서버에 설정되지 않음', 'stats': None}
    with _CACHE_LOCK:
        if _CACHE['data'] is not None and time.time() < _CACHE['expires']:
            return _CACHE['data']
    params = urllib.parse.urlencode({
        'part': 'snippet,statistics', 'id': CHANNEL_ID, 'key': key,
    })
    url = 'https://www.googleapis.com/youtube/v3/channels?' + params
    try:
        if fetch is None:
            with urllib.request.urlopen(url, timeout=8) as r:
                doc = json.loads(r.read(256_000))
        else:
            doc = fetch(url)
        items = doc.get('items') or []
        if len(items) != 1 or items[0].get('id') != CHANNEL_ID:
            raise ValueError('채널 조회 결과가 일치하지 않음')
        entry = items[0]
        st = entry.get('statistics', {})
        result = {'state': '공개 통계 조회 연결', 'reason': None,
                  'stats': {
                      'title': entry.get('snippet', {}).get('title'),
                      'subscribers': int(st['subscriberCount']) if 'subscriberCount' in st else None,
                      'views': int(st['viewCount']) if 'viewCount' in st else None,
                      'videos': int(st['videoCount']) if 'videoCount' in st else None,
                      'checked_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                  }}
        with _CACHE_LOCK:
            _CACHE['data'] = result
            _CACHE['expires'] = time.time() + 300
        return result
    except (ValueError, TypeError, KeyError, urllib.error.URLError, TimeoutError, OSError):
        return {'state': '조회 오류', 'reason': '공식 API 요청에 실패함. Render 로그에서 환경변수와 API 활성화를 점검하세요.', 'stats': None}


def snapshot():
    return {
        'brand': '원리한입',
        'channel_id': CHANNEL_ID,
        'channel_url': CHANNEL_URL,
        'channel_identity_verified_via_vidiq': True,
        'server_mode': 'READ_ONLY_MONITOR',
        'youtube_upload_oauth': '미연결 / 서버에서 업로드 비활성화',
        'publish_permission': '없음 — 공개 업로드 차단',
        'cloud_24h_rendering': '미구현',
        'monetization': '미확인',
        'bank_settlement': '미연결',
        'video_inventory': [
            {'id': 'usb_c_cable', 'name': 'USB-C 케이블, 다 똑같을까?', 'format': 'MP4 / 25초', 'youtube_uploaded': False},
            {'id': 'winglets', 'name': '비행기 날개 끝은 왜 꺾였을까?', 'format': 'MP4 / 25초', 'youtube_uploaded': False},
        ],
        'youtube_public_data': read_public_youtube_stats(),
        'refreshed_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    }


HTML = '''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>원리한입 | Shorts Studio</title>
<style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;background:#080f1d;color:#ecf5ff}
*{box-sizing:border-box} body{margin:0;background:radial-gradient(circle at 88% -10%,#134574,transparent 35%),#080f1d}
header{padding:27px clamp(18px,5vw,65px);border-bottom:1px solid #1f3550;display:flex;justify-content:space-between;gap:16px;align-items:center}
.brand{font-weight:850;font-size:22px;letter-spacing:-.4px}.pill{border:1px solid #1e7b74;border-radius:25px;padding:7px 12px;color:#68edd1;background:#09302d;font-size:12px}
main{max-width:1090px;margin:30px auto;padding:0 20px 50px}.muted{color:#9cabc2} h1{font-size:clamp(28px,5vw,42px);margin:8px 0} h2{font-size:18px;margin:0 0 15px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin:26px 0}.card,.panel{background:#101c2e;border:1px solid #25405d;border-radius:15px;padding:20px}.card .value{font-size:30px;font-weight:800;margin:15px 0 0}.value.minor{font-size:17px}
.cols{display:grid;grid-template-columns:1.05fr .95fr;gap:14px}.line{border-top:1px solid #29405a;padding:14px 0;display:flex;justify-content:space-between;gap:15px}.line b{text-align:right}.note{margin-top:22px;color:#94adc3;font-size:13px;line-height:1.6}
a{color:#73dff5} .list{padding:0;list-style:none}.list li{padding:13px 0;border-top:1px solid #28405c}.tag{font-size:12px;color:#ffd089}.stamp{font-size:12px;color:#97a7b9}
@media(max-width:750px){.cols{grid-template-columns:1fr}header{align-items:flex-start;flex-direction:column}}
</style></head><body><header><div class="brand">◈ 원리한입 <span class="muted" style="font-size:13px;font-weight:500">Shorts Studio · Render</span></div><span class="pill">읽기 전용 · 실제 게시 비활성화</span></header>
<main><div class="muted">YouTube 원본 쇼츠 운영 프로젝트</div><h1>운영 상태 대시보드</h1><div class="muted">실제 승인된 API 데이터만 표시하며 매출과 광고 수익은 추정하지 않습니다.</div>
<div class="cards"><div class="card"><span class="muted">구독자 · 공식 API</span><div id="subscribers" class="value">미연결</div></div><div class="card"><span class="muted">누적 조회수 · 공식 API</span><div id="views" class="value">미연결</div></div><div class="card"><span class="muted">공개 동영상 · 공식 API</span><div id="videos" class="value">미연결</div></div><div class="card"><span class="muted">실제 수익·입금</span><div class="value minor">미확인</div></div></div>
<div class="cols"><section class="panel"><h2>연결·안전 상태</h2><div class="line"><span class="muted">채널</span><b><a href="https://www.youtube.com/channel/UCG2U_iDGOxCXanGmBdiJ-GA" target="_blank" rel="noopener">원리한입</a></b></div><div class="line"><span class="muted">vidIQ 채널 식별</span><b>확인됨</b></div><div class="line"><span class="muted">공개 통계 API</span><b id="status">확인 중</b></div><div class="line"><span class="muted">Google OAuth 업로드</span><b class="tag">미연결</b></div><div class="line"><span class="muted">실제 게시/예약</span><b class="tag">비활성화</b></div><div class="line"><span class="muted">24시간 영상 렌더링</span><b class="tag">미구현</b></div></section>
<section class="panel"><h2>영상 제작 목록</h2><ul class="list"><li><b>USB-C 케이블, 다 똑같을까?</b><div class="muted">MP4 · 25초 · 유튜브 업로드 미확인</div></li><li><b>비행기 날개 끝은 왜 꺾였을까?</b><div class="muted">MP4 · 25초 · 유튜브 업로드 미확인</div></li></ul><p class="note">두 영상은 로컬 패키지에 있으며 이 서버는 영상 파일을 공개 배포하지 않습니다.</p></section></div>
<p class="note">자료 업데이트 시각: <span id="timestamp">확인 중</span>. Render 무료 인스턴스는 유휴 시간에 중단될 수 있으므로 24시간 무중단 운영으로 표시하지 않습니다.</p></main>
<script>fetch('/api/status',{cache:'no-store'}).then(async r=>{if(!r.ok)throw Error('인증 필요');return r.json()}).then(d=>{let y=d.youtube_public_data;document.querySelector('#status').textContent=y.state;const s=y.stats;if(s){for(const [id,key] of [['subscribers','subscribers'],['views','views'],['videos','videos']])document.querySelector('#'+id).textContent=s[key]===null?'미확인':s[key].toLocaleString('ko-KR')}document.querySelector('#timestamp').textContent=d.refreshed_at_utc}).catch(()=>document.querySelector('#status').textContent='연결 확인 필요');</script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    server_version = 'WonrihanipReadOnly/1.0'

    def send_headers(self, status=200, mime='text/plain; charset=utf-8', length=0):
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(length))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; connect-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()

    def _body(self, status, content, mime):
        raw = content.encode('utf-8')
        self.send_headers(status, mime, len(raw))
        self.wfile.write(raw)

    def _authorized(self):
        password = os.getenv('ADMIN_PASSWORD', '')
        if len(password) < 16:
            self._body(503, 'ADMIN_PASSWORD (16자 이상)가 안전하게 설정되지 않았습니다.', 'text/plain; charset=utf-8')
            return False
        head = self.headers.get('Authorization', '')
        try:
            if not head.startswith('Basic '):
                raise ValueError('missing')
            credentials = base64.b64decode(head[6:], validate=True).decode('utf-8')
            user, pwd = credentials.split(':', 1)
        except (ValueError, UnicodeDecodeError, base64.binascii.Error):
            user, pwd = '', ''
        correct_user = hmac.compare_digest(user, os.getenv('ADMIN_USER', 'owner'))
        correct_pass = hmac.compare_digest(pwd, password)
        if not (correct_user and correct_pass):
            data = b'Login required'
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="Shorts Studio Owner", charset="UTF-8"')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return False
        return True

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/health':
            return self._body(200, json.dumps({'status':'ok','mode':'read_only'}), 'application/json')
        if not self._authorized():
            return
        if path == '/':
            return self._body(200, HTML, 'text/html; charset=utf-8')
        if path == '/api/status':
            return self._body(200, json.dumps(snapshot(), ensure_ascii=False), 'application/json; charset=utf-8')
        return self._body(404, 'Not found', 'text/plain; charset=utf-8')

    def do_POST(self):
        return self._body(405, '이 서버에서는 업로드, 인증정보 입력, 공개 게시가 비활성화되어 있습니다.', 'text/plain; charset=utf-8')

    def log_message(self, fmt, *args):
        # Avoid logging Authorization and query strings.
        pass


def main():
    port=int(os.getenv('PORT', '10000'))
    if not (1 <= port <= 65535):
        raise ValueError('PORT out of range')
    print(f'원리한입 읽기 전용 대시보드 / port={port}', flush=True)
    ThreadingHTTPServer(('0.0.0.0', port), Handler).serve_forever()

if __name__=='__main__':
    main()
