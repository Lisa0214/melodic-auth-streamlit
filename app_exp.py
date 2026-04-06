import streamlit as st
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta
import random
import re
import time
import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ======================
# Config / Paths
# ======================
BASE_DIR = Path(__file__).resolve().parent
CLIPS_DIR = BASE_DIR / "music data" / "clip_cache"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True, parents=True)
LOG_PATH = LOG_DIR / "verification_log.csv"

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

N_CHALLENGE = 10
N_DISTRACT = N_CHALLENGE - 1
MAX_WRONG_YES = 2
LOCK_SECONDS = 30
BOT_THRESHOLD = 0.8  # 反應低於 0.8 秒判定為 Bot
GSHEET_NAME = "melodic_auth_log"

# ======================
# Google Sheet Helpers
# ======================
def init_gsheet():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    return client.open(GSHEET_NAME).sheet1

def append_gsheet(event: dict):
    sheet = init_gsheet()
    sheet.append_row([
        event.get("timestamp"),
        event.get("user_email"),
        event.get("event"),
        event.get("seed"),
        event.get("reaction_time"),
        event.get("clip"),
        event.get("passed")
    ])

# ======================
# Helpers
# ======================
def now_iso():
    return datetime.now().isoformat(timespec="seconds")

def append_log(event: dict):
    # 本地 CSV 備份
    df = pd.DataFrame([event])
    if LOG_PATH.exists():
        df.to_csv(LOG_PATH, mode="a", header=False, index=False, encoding="utf-8-sig")
    else:
        df.to_csv(LOG_PATH, mode="w", header=True, index=False, encoding="utf-8-sig")

    # Google Sheet 主資料
    try:
        append_gsheet(event)
        print("GSHEET OK")
    except Exception as e:
        print("GSHEET ERROR:", e)

def build_challenge(all_mp3s, secret_clip: Path, seed=None):
    if seed is None:
        seed = random.randrange(1, 2**31 - 1)
    rng = random.Random(seed)
    pool = [p for p in all_mp3s if p != secret_clip]
    k = min(N_DISTRACT, len(pool))
    distractors = rng.sample(pool, k=k) if k > 0 else []
    challenge = distractors + [secret_clip]
    rng.shuffle(challenge)
    return challenge, seed

# ======================
# Load mp3 list
# ======================
mp3s = sorted(CLIPS_DIR.rglob("*.mp3"))
if not mp3s:
    st.error(f"找不到 mp3。請檢查路徑: {CLIPS_DIR}")
    st.stop()

# ======================
# Session State Init
# ======================
init_states = {
    "stage": "setup",
    "user_email": "",
    "secret_clip": None,
    "challenge": [],
    "idx": 0,
    "wrong_yes": 0,
    "locked_until": None,
    "challenge_seed": None,
    "challenge_list": [],
    "play_start_time": None
}

for key, val in init_states.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ======================
# Page: Setup
# ======================
if st.session_state.stage == "setup":
    st.title("🎼 Melodic Auth — Setup")
    st.subheader("受試者註冊與密碼設定")

    user_email = st.text_input(
        "受試者 Email",
        value=st.session_state.user_email or "user@example.com"
    ).strip()

    secret_clip = st.selectbox(
        "請選你的密碼歌（Secret Song）",
        options=mp3s,
        format_func=lambda p: p.name
    )
    st.audio(str(secret_clip))

    if st.button("✅ 確認並開始驗證"):
        if not EMAIL_RE.match(user_email):
            st.error("請輸入有效 Email 格式")
            st.stop()

        st.session_state.user_email = user_email
        st.session_state.secret_clip = secret_clip

        challenge, seed = build_challenge(mp3s, secret_clip)
        st.session_state.challenge = challenge
        st.session_state.challenge_seed = seed
        st.session_state.challenge_list = [p.name for p in challenge]
        st.session_state.idx = 0
        st.session_state.wrong_yes = 0
        st.session_state.locked_until = None
        st.session_state.play_start_time = None

        append_log({
            "timestamp": now_iso(),
            "user_email": st.session_state.user_email,
            "event": "CHALLENGE_START",
            "seed": st.session_state.challenge_seed,
            "reaction_time": 0,
            "clip": secret_clip.name,
            "passed": "N/A"
        })

        st.session_state.stage = "experiment"
        st.rerun()

# ======================
# Page: Experiment
# ======================
elif st.session_state.stage == "experiment":
    st.title("🎼 Melodic Auth — 驗證進行中")

    # Lock Check
    if st.session_state.locked_until and datetime.now() < st.session_state.locked_until:
        remain = int((st.session_state.locked_until - datetime.now()).total_seconds())
        st.error(f"🔒 系統鎖定中，請等待 {remain} 秒")
        st.stop()
    elif st.session_state.locked_until and datetime.now() >= st.session_state.locked_until:
        st.session_state.locked_until = None
        st.session_state.wrong_yes = 0

    idx = st.session_state.idx
    challenge = st.session_state.challenge

    if idx >= len(challenge):
        st.warning("❌ 驗證失敗：已播完所有音檔。")
        append_log({
            "timestamp": now_iso(),
            "user_email": st.session_state.user_email,
            "event": "VERIFICATION_FAILED",
            "seed": st.session_state.challenge_seed,
            "reaction_time": 0,
            "clip": "",
            "passed": False
        })
        st.session_state.stage = "done_fail"
        st.rerun()

    current_clip = challenge[idx]
    st.info(f"受試者：{st.session_state.user_email} ｜ 進度：{idx+1} / {len(challenge)}")

    if st.session_state.play_start_time is None:
        st.session_state.play_start_time = time.time()

    st.audio(str(current_clip))

    col1, col2 = st.columns(2)

    with col1:
        if st.button("NO（不是）", use_container_width=True):
            append_log({
                "timestamp": now_iso(),
                "user_email": st.session_state.user_email,
                "event": "ANSWER_NO",
                "seed": st.session_state.challenge_seed,
                "reaction_time": time.time() - st.session_state.play_start_time,
                "clip": current_clip.name,
                "passed": False
            })
            st.session_state.idx += 1
            st.session_state.play_start_time = None
            st.rerun()

    with col2:
        if st.button("YES（是）", use_container_width=True):
            reaction_time = time.time() - st.session_state.play_start_time
            is_secret = (current_clip == st.session_state.secret_clip)

            # Bot 偵測
            if reaction_time < BOT_THRESHOLD:
                st.error(f"🚨 異常操作！反應時延 {reaction_time:.3f}s 低於人類極限。")
                append_log({
                    "timestamp": now_iso(),
                    "user_email": st.session_state.user_email,
                    "event": "BOT_BLOCKED",
                    "seed": st.session_state.challenge_seed,
                    "reaction_time": reaction_time,
                    "clip": current_clip.name,
                    "passed": "BLOCKED"
                })
                st.session_state.play_start_time = None
                st.stop()

            if is_secret:
                st.success(f"✅ 驗證成功！反應時間：{reaction_time:.2f}s")
                append_log({
                    "timestamp": now_iso(),
                    "user_email": st.session_state.user_email,
                    "event": "VERIFIED_SUCCESS",
                    "seed": st.session_state.challenge_seed,
                    "reaction_time": reaction_time,
                    "clip": current_clip.name,
                    "passed": True
                })
                st.session_state.stage = "done_success"
                st.session_state.play_start_time = None
                st.rerun()
            else:
                st.session_state.wrong_yes += 1
                st.error(f"❌ 答錯了！(YES 錯誤：{st.session_state.wrong_yes}/{MAX_WRONG_YES})")

                append_log({
                    "timestamp": now_iso(),
                    "user_email": st.session_state.user_email,
                    "event": "ANSWER_YES_WRONG",
                    "seed": st.session_state.challenge_seed,
                    "reaction_time": reaction_time,
                    "clip": current_clip.name,
                    "passed": False
                })

                if st.session_state.wrong_yes >= MAX_WRONG_YES:
                    st.session_state.locked_until = datetime.now() + timedelta(seconds=LOCK_SECONDS)
                    append_log({
                        "timestamp": now_iso(),
                        "user_email": st.session_state.user_email,
                        "event": "LOCKED",
                        "seed": st.session_state.challenge_seed,
                        "reaction_time": reaction_time,
                        "clip": current_clip.name,
                        "passed": False
                    })

                st.session_state.idx += 1
                st.session_state.play_start_time = None
                st.rerun()

# ======================
# Page: Done Success
# ======================
elif st.session_state.stage == "done_success":
    st.container()
    st.balloons()

    col_icon, col_text = st.columns([1, 4])
    with col_icon:
        st.write("# ✅")
    with col_text:
        st.title("身份驗證成功")
        st.subheader("Welcome Back, Dr. Chen")

    st.success("系統已確認您的生物反應特徵與密碼旋律相符。")

    with st.expander("📊 本次驗證摘要"):
        st.write(f"**受試者 Email:** {st.session_state.user_email}")
        st.write("驗證已完成，資料已安全記錄於系統。")

    st.divider()

    st.write("### 下一步操作")
    c1, c2 = st.columns(2)

    with c1:
        if st.button("🔄 重新進行驗證", use_container_width=True):
            st.session_state.idx = 0
            st.session_state.wrong_yes = 0
            st.session_state.play_start_time = None
            st.session_state.stage = "setup"
            st.rerun()

    with c2:
        if st.button("🚪 結束並登出", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()

# ======================
# Page: Done Fail
# ======================
elif st.session_state.stage == "done_fail":
    st.container()

    col_icon, col_text = st.columns([1, 4])
    with col_icon:
        st.write("# ❌")
    with col_text:
        st.title("身份驗證失敗")
        st.subheader("Verification Failed")

    st.error("未在限制條件內完成正確驗證，請重新嘗試。")

    with st.expander("📊 本次驗證摘要"):
        st.write(f"**受試者 Email:** {st.session_state.user_email}")
        st.write("本次驗證未通過，資料已記錄於系統。")

    st.divider()

    st.write("### 下一步操作")
    c1, c2 = st.columns(2)

    with c1:
        if st.button("🔄 重新進行驗證", use_container_width=True):
            st.session_state.idx = 0
            st.session_state.wrong_yes = 0
            st.session_state.play_start_time = None
            st.session_state.locked_until = None
            st.session_state.stage = "setup"
            st.rerun()

    with c2:
        if st.button("🚪 結束並登出", use_container_width=True):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()