#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
海底捞 · 微信小程序每日签到（Python 轻量版）

依赖：requests、PySocks（仅走 SOCKS5 代理时需要）
    pip install requests requests[socks]

环境变量：
    hdl_data     必填。token，多账号用 @ 分隔：TOKEN_APP_甲@TOKEN_APP_乙
    WARP_PROXY   可选。IPv6-only VPS 借助 WARP 代理访问，如 socks5://127.0.0.1:40000
    IS_DEBUG     可选。true 时打印原始响应
    TG_BOT_TOKEN / TG_USER_ID   可选。Telegram 推送
    SCKEY        可选。Server酱推送
    bark_key     可选。Bark 推送
"""
import os
import sys
import json
import time
import random

try:
    import requests
except ImportError:
    print("缺少依赖，请执行: pip install requests requests[socks]")
    sys.exit(1)

API_BASE = "https://superapp-public.kiwa-tech.com/activity/wxapp/signin"
USER_AGENT = ("Mozilla/5.0 (iPhone; CPU iPhone OS 26_1 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
              "MicroMessenger/8.0.73(0x18004926) NetType/WIFI Language/zh_CN "
              "miniProgram/wx1ddeb67115f30d1a")

IS_DEBUG = os.environ.get("IS_DEBUG", "false").lower() == "true"

# ---- 代理配置 ----
def build_proxies():
    p = os.environ.get("WARP_PROXY", "").strip()
    if not p:
        return None
    # 强制 DNS 走代理解析（socks5 -> socks5h），对 IPv4-only 目标更稳
    if p.lower().startswith("socks5://"):
        p = "socks5h://" + p[len("socks5://"):]
    return {"http": p, "https": p}

PROXIES = build_proxies()

def build_headers(token):
    return {
        "Host": "superapp-public.kiwa-tech.com",
        "deviceid": "null",
        "accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "user-agent": USER_AGENT,
        "reqtype": "APPH5",
        "_haidilao_app_token": token,
        "origin": "https://superapp-public.kiwa-tech.com",
        "sec-fetch-site": "same-origin",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        "referer": f"https://superapp-public.kiwa-tech.com/app-sign-in/?SignInToken={token}&source=MiniApp",
    }

def debug(obj):
    if IS_DEBUG:
        print("[DEBUG]", obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False))

def post(session, path, token, body):
    url = f"{API_BASE}/{path}"
    try:
        r = session.post(url, headers=build_headers(token), data=body,
                         proxies=PROXIES, timeout=20)
        try:
            return r.json()
        except ValueError:
            return {"_http_status": r.status_code, "_raw": r.text[:300]}
    except Exception as e:
        return {"_error": str(e)}

def is_token_invalid(res):
    if not res:
        return False
    if res.get("code") == "unauthorized":
        return True
    msg = res.get("msg") or ""
    return any(k in msg for k in ("token", "登录", "未授权", "超时"))

def sign_in(session, token, idx):
    res = post(session, "signin", token, json.dumps({"signinSource": "MiniApp"}))
    debug(res)
    if not res:
        return f"账号{idx}: ❌签到无响应", False
    if res.get("_error"):
        return f"账号{idx}: ❌网络错误 {res['_error']}", True
    if is_token_invalid(res):
        return f"账号{idx}: ❌{res.get('msg', 'token 失效')}，请重新抓取", False
    if res.get("success") is True:
        detail = (res.get("data") or {}).get("signinQueryDetailList") or []
        today = next((x for x in detail if x.get("currentOr") == 1), None)
        if today:
            if today.get("dailySigninStatus") == 1:
                return f"账号{idx}: ✨今日已签", True
            return (f"账号{idx}: ✅签到成功,+{today.get('fragment', 0)}🧩,"
                    f"连签{today.get('daysSeries', 0)}天"), True
        return f"账号{idx}: ✅签到成功", True
    return f"账号{idx}: ❌{res.get('msg', '签到失败')}", True

def query_fragment(session, token, idx):
    res = post(session, "queryFragment", token, "")
    debug(res)
    if res and res.get("success") is True:
        total = (res.get("data") or {}).get("total", "?")
        return f"当前共 {total} 碎片🧩"
    return ""

def notify(title, content):
    print(f"\n====== {title} ======\n{content}\n==================\n")
    tg_token, tg_user = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_USER_ID")
    if tg_token and tg_user:
        try:
            requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage",
                          json={"chat_id": tg_user, "text": f"{title}\n\n{content}"}, timeout=15)
        except Exception as e:
            print("[WARN] TG 推送失败:", e)
    sckey = os.environ.get("SCKEY")
    if sckey:
        try:
            requests.post(f"https://sctapi.ftqq.com/{sckey}.send",
                          data={"title": title, "desp": content}, timeout=15)
        except Exception as e:
            print("[WARN] Server酱推送失败:", e)
    bark = os.environ.get("bark_key")
    if bark:
        try:
            requests.post("https://api.day.app/push",
                          json={"title": title, "body": content, "device_key": bark}, timeout=15)
        except Exception as e:
            print("[WARN] Bark 推送失败:", e)

def main():
    raw = os.environ.get("hdl_data", "").strip()
    if not raw:
        print("❌ 未检测到 hdl_data 环境变量")
        sys.exit(1)
    if PROXIES:
        print(f"[INFO] 已启用代理出口: {list(PROXIES.values())[0]}")

    tokens = [t for t in raw.split("@") if t]
    print(f"[INFO] 共找到 {len(tokens)} 个账号")
    lines = []
    with requests.Session() as session:
        for i, token in enumerate(tokens, 1):
            msg, ok = sign_in(session, token, i)
            frag = query_fragment(session, token, i) if ok else ""
            line = f"{msg}{('，' + frag) if frag else ''}"
            print(line)
            lines.append(line)
            time.sleep(random.uniform(1, 3))
    notify("海底捞签到", "\n".join(lines))

if __name__ == "__main__":
    main()
