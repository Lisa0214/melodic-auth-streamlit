import streamlit as st
from pathlib import Path
import random
import time

# === 路徑 ===
BASE_DIR = Path(__file__).resolve().parent
CLIPS_DIR = BASE_DIR / "music data" / "clip_cache"

mp3s_all = sorted(CLIPS_DIR.rglob("*.mp3"))
if len(mp3s_all) < 10:
    st.error("mp3 不足 10 首，請確認 clip_cache 內音檔數量")
    st.stop()

st.set_page_config(page_title="Melodic Auth", layout="centered")
st.title("🎼 Melodic Auth – Demo (10-song challenge)")

# === 初始化：抽 10 首 + 選 1 首當密碼 ===
if "challenge" not in st.session_state:
    st.session_state.challenge = random.sample(mp3s_all, 10)
    st.session_state.secret = random.choice(st.session_state.challenge)
    st.session_state.idx = 0
    st.session_state.passed = False
    st.session_state.done = False
    st.session_state.last_tick = time.time()

challenge = st.session_state.challenge
secret = st.session_state.secret
idx = st.session_state.idx

# === 結束狀態 ===
if st.session_state.done:
    if st.session_state.passed:
        st.success("✅ 驗證成功")
        st.balloons()
    else:
        st.error("❌ 驗證失敗（10 首播完仍未 YES 到密碼歌）")
    if st.button("重新開始（重抽 10 首）"):
        for k in ["challenge", "secret", "idx", "passed", "done", "last_tick"]:
            st.session_state.pop(k, None)
        st.rerun()
    st.stop()

# === 若播到最後一首後還沒成功 → 失敗 ===
if idx >= len(challenge):
    st.session_state.done = True
    st.session_state.passed = False
    st.rerun()

current = challenge[idx]

st.info(f"🎧 第 {idx+1} / 10 首")
st.audio(str(current))  # 先讓使用者點一次 play（瀏覽器政策）

# === YES/NO 按鈕 ===
c1, c2 = st.columns(2)

with c1:
    if st.button("NO（不是）", use_container_width=True):
        st.session_state.idx += 1
        st.session_state.last_tick = time.time()
        st.rerun()

with c2:
    if st.button("YES（是）", use_container_width=True):
        if current == secret:
            st.session_state.done = True
            st.session_state.passed = True
            st.rerun()
        else:
            st.warning("⚠️ 這首不是密碼歌（Demo 規則：YES 錯就直接判失敗）")
            st.session_state.done = True
            st.session_state.passed = False
            st.rerun()

# === 自動輪播：每 6 秒換下一首（留 1 秒緩衝）===
AUTO_NEXT_SEC = 6
if time.time() - st.session_state.last_tick >= AUTO_NEXT_SEC:
    st.session_state.idx += 1
    st.session_state.last_tick = time.time()
    st.rerun()

st.caption("提示：第一次需要你手動點 Play 一次，之後會每 6 秒自動換下一首。")
