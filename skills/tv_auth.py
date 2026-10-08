"""TradingView OAuth 2.1 授權 Skill。

對應 TradingView 官方 MCP 伺服器：
    authorization server : https://www.tradingview.com
    protected resource   : https://mcp.tradingview.com/mcp
    metadata             : https://www.tradingview.com/.well-known/oauth-authorization-server

流程（OAuth 2.1，公開用戶端）
    1. 動態註冊 client（RFC 7591），結果快取於 data/cache/tv_oauth_client.json
    2. Authorization Code + PKCE（S256），以本機 127.0.0.1 回呼接收授權碼
    3. 交換 access_token / refresh_token，存於 data/cache/tv_oauth_token.json
    4. token 到期前自動以 refresh_token 換新；refresh 失敗才需要重新登入

安全性
    - 使用 PKCE，不需要 client secret
    - state 以 secrets.token_urlsafe 產生並嚴格比對，防 CSRF
    - token 檔案權限設為僅擁有者可讀；請勿提交進版控（見 .gitignore）

用法
    python -m skills.tv_auth login      # 開瀏覽器登入並授權
    python -m skills.tv_auth status     # 檢視目前授權狀態
    python -m skills.tv_auth logout     # 撤銷並刪除本機 token
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import secrets
import socket
import stat
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "cache"
CLIENT_FILE = CACHE / "tv_oauth_client.json"
TOKEN_FILE = CACHE / "tv_oauth_token.json"

METADATA_URL = "https://www.tradingview.com/.well-known/oauth-authorization-server"
RESOURCE = "https://mcp.tradingview.com/mcp"
SCOPES = "mcp:read mcp:tools"
CLIENT_NAME = "Stock Strategy Agent"
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = int(os.getenv("TV_OAUTH_PORT", "8765"))
EXPIRY_SKEW = 60  # 秒；提前換新避免臨界失效

_CALLBACK_HTML = """<!doctype html><meta charset="utf-8">
<title>TradingView 授權</title>
<body style="font-family:system-ui;padding:3rem;text-align:center">
<h2>{title}</h2><p>{msg}</p><p>可以關閉此分頁，回到終端機繼續。</p></body>"""


class TVAuthError(Exception):
    pass


@dataclass
class Token:
    access_token: str
    refresh_token: str | None
    expires_at: float
    scope: str = ""
    token_type: str = "Bearer"

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at - EXPIRY_SKEW

    def to_dict(self) -> dict:
        return {
            "access_token": self.access_token, "refresh_token": self.refresh_token,
            "expires_at": self.expires_at, "scope": self.scope, "token_type": self.token_type,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Token":
        return cls(d["access_token"], d.get("refresh_token"), float(d.get("expires_at", 0)),
                   d.get("scope", ""), d.get("token_type", "Bearer"))

    @classmethod
    def from_response(cls, d: dict, fallback_refresh: str | None = None) -> "Token":
        if "access_token" not in d:
            raise TVAuthError(f"token 回應缺少 access_token: {str(d)[:200]}")
        return cls(d["access_token"], d.get("refresh_token") or fallback_refresh,
                   time.time() + float(d.get("expires_in", 3600)),
                   d.get("scope", ""), d.get("token_type", "Bearer"))


# ---------------------------------------------------------------------------
# 檔案讀寫（token 含敏感資訊）
# ---------------------------------------------------------------------------

def _write_private_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        log.debug("無法設定 %s 權限", path)


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("%s 無法讀取: %s", path.name, exc)
        return None


# ---------------------------------------------------------------------------
# Metadata / 動態註冊
# ---------------------------------------------------------------------------

def discover(timeout: float = 20.0) -> dict:
    try:
        r = requests.get(METADATA_URL, timeout=timeout)
        r.raise_for_status()
        meta = r.json()
    except (requests.RequestException, ValueError) as exc:
        raise TVAuthError(f"無法取得 OAuth metadata: {exc}") from exc
    for key in ("authorization_endpoint", "token_endpoint"):
        if key not in meta:
            raise TVAuthError(f"OAuth metadata 缺少 {key}")
    if "S256" not in meta.get("code_challenge_methods_supported", ["S256"]):
        raise TVAuthError("授權伺服器不支援 PKCE S256")
    return meta


def register_client(meta: dict, redirect_uri: str, timeout: float = 25.0) -> dict:
    """動態註冊（RFC 7591）；已註冊且 redirect_uri 相同則沿用快取。"""
    cached = _read_json(CLIENT_FILE)
    if cached and redirect_uri in cached.get("redirect_uris", []):
        return cached

    endpoint = meta.get("registration_endpoint")
    if not endpoint:
        raise TVAuthError("授權伺服器未提供 registration_endpoint，請改用環境變數 TV_OAUTH_CLIENT_ID")
    body = {
        "client_name": CLIENT_NAME,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": SCOPES,
    }
    try:
        r = requests.post(endpoint, json=body, timeout=timeout)
    except requests.RequestException as exc:
        raise TVAuthError(f"動態註冊失敗: {exc}") from exc
    if r.status_code not in (200, 201):
        raise TVAuthError(f"動態註冊失敗 HTTP {r.status_code}: {r.text[:200]}")
    client = r.json()
    _write_private_json(CLIENT_FILE, client)
    log.info("已註冊 OAuth client: %s", client.get("client_id"))
    return client


# ---------------------------------------------------------------------------
# 本機回呼伺服器
# ---------------------------------------------------------------------------

class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict = {}
    expected_state: str = ""
    done: threading.Event

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_error(404)
            return
        q = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}

        if q.get("state") != type(self).expected_state:
            ok, title, msg = False, "授權失敗", "state 不符，可能是 CSRF 攻擊或流程過期。"
            type(self).result = {"error": "state_mismatch"}
        elif "error" in q:
            ok, title = False, "授權被拒絕"
            msg = f"{q['error']}: {q.get('error_description', '')}"
            type(self).result = {"error": q["error"]}
        elif "code" in q:
            ok, title, msg = True, "授權成功", "已取得授權碼。"
            type(self).result = {"code": q["code"]}
        else:
            ok, title, msg = False, "授權失敗", "回呼缺少 code 參數。"
            type(self).result = {"error": "missing_code"}

        payload = _CALLBACK_HTML.format(title=title, msg=msg).encode("utf-8")
        self.send_response(200 if ok else 400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
        type(self).done.set()

    def log_message(self, *args) -> None:  # 靜音 http.server 預設輸出
        pass


def _wait_for_code(port: int, state: str, timeout: float) -> str:
    _CallbackHandler.result = {}
    _CallbackHandler.expected_state = state
    _CallbackHandler.done = threading.Event()
    try:
        server = HTTPServer((CALLBACK_HOST, port), _CallbackHandler)
    except OSError as exc:
        raise TVAuthError(f"無法在 {CALLBACK_HOST}:{port} 啟動回呼伺服器（連接埠被占用？）: {exc}") from exc

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if not _CallbackHandler.done.wait(timeout):
            raise TVAuthError(f"等待授權逾時（{timeout:.0f} 秒）")
    finally:
        server.shutdown()
        server.server_close()

    result = _CallbackHandler.result
    if "code" not in result:
        raise TVAuthError(f"授權失敗: {result.get('error', 'unknown')}")
    return result["code"]


def _free_port(port: int) -> int:
    with socket.socket() as s:
        try:
            s.bind((CALLBACK_HOST, port))
            return port
        except OSError:
            pass
    with socket.socket() as s:
        s.bind((CALLBACK_HOST, 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# 授權流程
# ---------------------------------------------------------------------------

def build_authorize_url(meta: dict, client_id: str, redirect_uri: str,
                        verifier: str, state: str) -> str:
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": RESOURCE,  # RFC 8707，MCP 規範要求
    }
    return f"{meta['authorization_endpoint']}?{urllib.parse.urlencode(params)}"


def _post_token(meta: dict, data: dict, timeout: float = 25.0) -> dict:
    try:
        r = requests.post(meta["token_endpoint"], data=data,
                          headers={"Content-Type": "application/x-www-form-urlencoded"},
                          timeout=timeout)
    except requests.RequestException as exc:
        raise TVAuthError(f"token 端點連線失敗: {exc}") from exc
    if r.status_code != 200:
        raise TVAuthError(f"token 交換失敗 HTTP {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except ValueError as exc:
        raise TVAuthError(f"token 回應非 JSON: {r.text[:200]}") from exc


def login(timeout: float = 300.0, open_browser: bool = True, port: int | None = None) -> Token:
    """執行完整 OAuth 2.1 授權碼 + PKCE 流程，成功後存檔並回傳 Token。"""
    meta = discover()
    chosen_port = _free_port(port or CALLBACK_PORT)
    redirect_uri = f"http://{CALLBACK_HOST}:{chosen_port}/callback"
    client = register_client(meta, redirect_uri)
    client_id = os.getenv("TV_OAUTH_CLIENT_ID") or client["client_id"]

    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(32)
    url = build_authorize_url(meta, client_id, redirect_uri, verifier, state)

    print("請在瀏覽器登入 TradingView 並授權：")
    print(url)
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            log.debug("無法自動開啟瀏覽器")

    code = _wait_for_code(chosen_port, state, timeout)
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "code_verifier": verifier,
        "resource": RESOURCE,
    }
    if client.get("client_secret"):
        payload["client_secret"] = client["client_secret"]

    token = Token.from_response(_post_token(meta, payload))
    _write_private_json(TOKEN_FILE, token.to_dict())
    print(f"授權成功，scope={token.scope or SCOPES}")
    return token


def refresh(token: Token) -> Token:
    if not token.refresh_token:
        raise TVAuthError("沒有 refresh_token，需要重新登入")
    meta = discover()
    client = _read_json(CLIENT_FILE) or {}
    client_id = os.getenv("TV_OAUTH_CLIENT_ID") or client.get("client_id")
    if not client_id:
        raise TVAuthError("找不到 client_id，需要重新登入")
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": token.refresh_token,
        "client_id": client_id,
        "resource": RESOURCE,
    }
    if client.get("client_secret"):
        payload["client_secret"] = client["client_secret"]
    new = Token.from_response(_post_token(meta, payload), fallback_refresh=token.refresh_token)
    _write_private_json(TOKEN_FILE, new.to_dict())
    log.info("access token 已更新")
    return new


def load_token() -> Token | None:
    data = _read_json(TOKEN_FILE)
    try:
        return Token.from_dict(data) if data else None
    except (KeyError, TypeError, ValueError):
        return None


def get_access_token(interactive: bool = False) -> str | None:
    """取得有效 access token；過期自動 refresh。

    interactive=False（排程情境）時，若尚未授權或 refresh 失敗則回傳 None，
    由呼叫端印出提示，不會卡住流程。
    """
    env = os.getenv("TV_ACCESS_TOKEN")
    if env:
        return env

    token = load_token()
    if token is None:
        if not interactive:
            return None
        token = login()
    elif token.expired:
        try:
            token = refresh(token)
        except TVAuthError as exc:
            log.warning("refresh 失敗: %s", exc)
            if not interactive:
                return None
            token = login()
    return token.access_token


def logout() -> None:
    token = load_token()
    if token:
        try:
            meta = discover()
            endpoint = meta.get("revocation_endpoint")
            client = _read_json(CLIENT_FILE) or {}
            if endpoint:
                requests.post(endpoint, data={
                    "token": token.refresh_token or token.access_token,
                    "token_type_hint": "refresh_token" if token.refresh_token else "access_token",
                    "client_id": os.getenv("TV_OAUTH_CLIENT_ID") or client.get("client_id", ""),
                }, timeout=15)
        except (TVAuthError, requests.RequestException) as exc:
            log.warning("撤銷 token 失敗（仍會刪除本機檔案）: %s", exc)
    TOKEN_FILE.unlink(missing_ok=True)
    print("已登出，本機 token 已刪除。")


def status() -> dict:
    token = load_token()
    client = _read_json(CLIENT_FILE) or {}
    if token is None:
        info = {"authorized": False, "client_id": client.get("client_id")}
    else:
        info = {
            "authorized": not token.expired,
            "client_id": client.get("client_id"),
            "scope": token.scope,
            "expires_in": round(token.expires_at - time.time()),
            "has_refresh_token": bool(token.refresh_token),
        }
    print(json.dumps(info, indent=2, ensure_ascii=False))
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TradingView OAuth 2.1 授權")
    parser.add_argument("action", choices=["login", "status", "logout", "refresh"], nargs="?",
                        default="login")
    parser.add_argument("--no-browser", action="store_true", help="不自動開啟瀏覽器")
    parser.add_argument("--timeout", type=float, default=300.0, help="等待授權秒數")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        if args.action == "login":
            login(timeout=args.timeout, open_browser=not args.no_browser)
        elif args.action == "status":
            status()
        elif args.action == "logout":
            logout()
        elif args.action == "refresh":
            token = load_token()
            if token is None:
                print("尚未授權，請先執行 login")
                return 1
            refresh(token)
            print("已更新 access token")
        return 0
    except TVAuthError as exc:
        print(f"授權失敗：{exc}")
        return 1
    except KeyboardInterrupt:
        print("已取消")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
