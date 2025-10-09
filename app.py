# -*- coding: utf-8 -*-
import io, re
from datetime import datetime, date, timedelta

import chardet
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# ==============================
# 상수 (현장 기준)
# ==============================
TARGET_OCHUL = 0.00019   # 0.019%
TARGET_NUL   = 0.00041   # 0.041%

# 트래킹 및 영향도 계산 기준
OCHUL_STATUS = "교차오배분"   # 오출 산정 유형
NUL_STATUS   = "생산누락"     # 누락 산정 유형
OF_LABEL     = "OF귀책"       # 영향도는 OF귀책만 반영

# 샘플 CSV (GitHub Raw URL)
SAMPLE_URL = "https://raw.githubusercontent.com/jinwookyung-kurly-data/-/main/오출자동화_test_927.csv"

# ==============================
# 유틸
# ==============================
def load_csv_safely(url: str) -> pd.DataFrame:
    """인코딩 자동 감지 후 원격 CSV 로드"""
    try:
        r = requests.get(url)
        raw = r.content
        enc = (chardet.detect(raw).get("encoding") or "utf-8")
        text = raw.decode(enc, errors="replace")
        return pd.read_csv(io.StringIO(text))
    except Exception as e:
        st.error(f"CSV 로드 오류: {e}")
        return pd.DataFrame()

def parse_korean_date(q: str, available_dates: list[date]) -> date | None:
    """'오늘/어제/그제' + 다양한 날짜 포맷 인식"""
    if not q:
        return None
    q = q.strip()
    today = datetime.today().date()

    if "오늘" in q:  return today
    if "어제" in q:  return today - timedelta(days=1)
    if "그제" in q or "그저께" in q: return today - timedelta(days=2)

    m = re.search(r"(\d{4})[.\-\/]\s?(\d{1,2})[.\-\/]\s?(\d{1,2})", q) or re.search(r"(\d{4})(\d{2})(\d{2})", q)
    if m:
        y, mth, d = map(int, m.groups())
        try:
            want = date(y, mth, d)
        except ValueError:
            return None
        if want in available_dates:
            return want
        if available_dates:
            return min(available_dates, key=lambda x: abs(x - want))
    return None

def pct(x: float) -> str:
    return f"{x*100:.3f}%"

def pp(x: float) -> str:
    return f"{x*100:+.3f} pp"

# ==============================
# 페이지 설정
# ==============================
st.set_page_config(page_title="누락 현황 대시보드", layout="wide")
st.title("🎯 누락 현황 대시보드 (자연어 + 영향도 계산 + 트래킹)")

st.caption(
    "CSV 업로드 또는 샘플 데이터를 사용해 **교차오배분(오출)** / **생산누락(누락)** 을 집계합니다. "
    "자연어로 ‘오늘 오출율’, ‘2025-09-27 누락 요약’처럼 질의할 수 있어요. "
    "영향도 계산은 **OF귀책**만 반영합니다."
)

# ==============================
# 데이터 로드
# ==============================
uploaded = st.file_uploader("CSV 파일 업로드 (헤더 포함)", type=["csv"])
if uploaded:
    df = pd.read_csv(uploaded, encoding="utf-8-sig")
    st.success("✅ 업로드된 파일이 사용됩니다.")
else:
    df = load_csv_safely(SAMPLE_URL)
    st.info("ℹ️ 샘플 데이터(오출자동화_test_927.csv)가 자동 로드되었습니다.")

# 컬럼 정규화
rename_map = {
    "포장완료로": "포장완료시간",
    "분류완료로": "분류완료시간",
    "포장완료":   "포장완료시간",
    "분류완료":   "분류완료시간",
}
df.rename(columns=rename_map, inplace=True)
df.columns = df.columns.str.replace("\ufeff", "", regex=True).str.strip()

expected = ["날짜","주문번호","유닛","타입","상태","포장완료시간","분류완료시간","포장작업자","풋월작업자","사유","귀책"]
missing = [c for c in expected if c not in df.columns]
if missing:
    st.error(f"❌ CSV 헤더 형식 불일치\n빠진 컬럼: {missing}\n감지된 헤더: {list(df.columns)}")
    st.stop()

# 타입/날짜 정리
df["유닛"] = pd.to_numeric(df["유닛"], errors="coerce").fillna(0).astype(int)
df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce").dt.date

# 전처리(마스크용)
df["is_ochul"] = df["상태"].astype(str).str.contains(OCHUL_STATUS, na=False)
df["is_nul"]   = df["상태"].astype(str).str.contains(NUL_STATUS,   na=False)
df["is_of"]    = df["귀책"].astype(str).str.replace(" ", "").str.upper().eq(OF_LABEL.upper())

dates = sorted(df["날짜"].dropna().unique().tolist())
if not dates:
    st.error("날짜 컬럼을 해석하지 못했습니다. YYYY-MM-DD로 저장해주세요.")
    st.stop()

# ==============================
# 자연어 질의 + 날짜 선택
# ==============================
with st.sidebar:
    st.header("🔎 자연어 질문")
    q = st.text_input("예) '오늘 오출율', '어제 누락 요약', '2025/09/27 리포트'")
    st.caption("질문에 날짜가 없으면 아래 드롭다운 날짜를 사용합니다.")
    st.divider()
    manual_date = st.selectbox("📅 날짜 선택", dates, index=len(dates)-1)

parsed = parse_korean_date(q, dates) if q else None
selected_date = parsed or manual_date
if parsed:
    st.success(f"🗓 자연어에서 날짜 인식: **{selected_date}**")

# ==============================
# 선택 일자 요약
# ==============================
day = df[df["날짜"] == selected_date].copy()
if day.empty:
    st.warning("선택한 날짜의 데이터가 없습니다.")
    st.stop()

total_units = int(day["유닛"].sum())

# 실제값
ochul_units = int(day.loc[day["is_ochul"], "유닛"].sum())
nul_units   = int(day.loc[day["is_nul"],   "유닛"].sum())
ochul_rate  = (ochul_units / total_units) if total_units else 0.0
nul_rate    = (nul_units   / total_units) if total_units else 0.0

# OF 귀책만 영향(제외 가정)
of_ochul_units = int(day.loc[day["is_ochul"] & day["is_of"], "유닛"].sum())
of_nul_units   = int(day.loc[day["is_nul"]   & day["is_of"], "유닛"].sum())

hypo_ochul_rate = ((ochul_units - of_ochul_units) / total_units) if total_units else 0.0
hypo_nul_rate   = ((nul_units   - of_nul_units)   / total_units) if total_units else 0.0

st.subheader(f"📌 {selected_date} 요약")
c1, c2, c3, c4 = st.columns(4)
c1.metric("전체 건수", f"{len(day):,}")
c2.metric("전체 유닛", f"{total_units:,}")
c3.metric("오출율", pct(ochul_rate), pp(ochul_rate - TARGET_OCHUL))
c4.metric("누락율", pct(nul_rate),   pp(nul_rate   - TARGET_NUL))

# ==============================
# 🎯 타겟 대비 영향도 계산기 (OF귀책 반영)
# ==============================
st.markdown("### 🎯 타겟 대비 영향도 (OF귀책 제외 가정)")

colA, colB = st.columns(2)
with colA:
    st.write("**오출(교차오배분)**")
    st.metric("실제", pct(ochul_rate),  pp(ochul_rate - TARGET_OCHUL))
    st.metric("OF 제외 가정", pct(hypo_ochul_rate), pp(hypo_ochul_rate - TARGET_OCHUL))
    st.caption(f"개선폭: {pp(ochul_rate - hypo_ochul_rate)} (OF귀책 유닛 {of_ochul_units:,} 제거 기준)")

    # 막대 비교
    fig1 = px.bar(
        x=["타겟", "실제", "OF 제외 가정"],
        y=[TARGET_OCHUL*100, ochul_rate*100, hypo_ochul_rate*100],
        labels={"x":"", "y":"%"},
        title="오출율 비교"
    )
    st.plotly_chart(fig1, use_container_width=True)

with colB:
    st.write("**누락(생산누락)**")
    st.metric("실제", pct(nul_rate),  pp(nul_rate - TARGET_NUL))
    st.metric("OF 제외 가정", pct(hypo_nul_rate), pp(hypo_nul_rate - TARGET_NUL))
    st.caption(f"개선폭: {pp(nul_rate - hypo_nul_rate)} (OF귀책 유닛 {of_nul_units:,} 제거 기준)")

    fig2 = px.bar(
        x=["타겟", "실제", "OF 제외 가정"],
        y=[TARGET_NUL*100, nul_rate*100, hypo_nul_rate*100],
        labels={"x":"", "y":"%"},
        title="누락율 비교"
    )
    st.plotly_chart(fig2, use_container_width=True)

# ==============================
# 📈 일자별 트래킹 (멀티일자)
# ==============================
st.markdown("### 📈 오출/누락율 트래킹 (일자별)")

daily = (
    df.groupby("날짜")
      .apply(lambda x: pd.Series({
          "총유닛":            int(x["유닛"].sum()),
          "오출유닛":          int(x.loc[x["is_ochul"], "유닛"].sum()),
          "누락유닛":          int(x.loc[x["is_nul"],   "유닛"].sum()),
          "오출(OF)":         int(x.loc[x["is_ochul"] & x["is_of"], "유닛"].sum()),
          "누락(OF)":         int(x.loc[x["is_nul"]   & x["is_of"], "유닛"].sum()),
      }))
      .reset_index()
      .sort_values("날짜")
)

if not daily.empty:
    daily["오출율"]        = daily.apply(lambda r: (r["오출유닛"]/r["총유닛"]) if r["총유닛"] else 0.0, axis=1)
    daily["누락율"]        = daily.apply(lambda r: (r["누락유닛"]/r["총유닛"]) if r["총유닛"] else 0.0, axis=1)
    daily["오출율(OF제외)"] = daily.apply(lambda r: ((r["오출유닛"]-r["오출(OF)"])/r["총유닛"]) if r["총유닛"] else 0.0, axis=1)
    daily["누락율(OF제외)"] = daily.apply(lambda r: ((r["누락유닛"]-r["누락(OF)"])/r["총유닛"]) if r["총유닛"] else 0.0, axis=1)
    daily["타겟(오출)"]     = TARGET_OCHUL
    daily["타겟(누락)"]     = TARGET_NUL

    fig_tr1 = px.line(daily, x="날짜", y=["오출율","오출율(OF제외)","타겟(오출)"], markers=True, title="오출율 추이")
    fig_tr2 = px.line(daily, x="날짜", y=["누락율","누락율(OF제외)","타겟(누락)"], markers=True, title="누락율 추이")
    for f in (fig_tr1, fig_tr2):
        f.update_yaxes(tickformat=".2%")
    st.plotly_chart(fig_tr1, use_container_width=True)
    st.plotly_chart(fig_tr2, use_container_width=True)

    # 표 보기(퍼센트 보기 좋게)
    view = daily.copy()
    for c in ["오출율","누락율","오출율(OF제외)","누락율(OF제외)","타겟(오출)","타겟(누락)"]:
        view[c] = (view[c]*100).round(3)
    st.dataframe(view, use_container_width=True)
else:
    st.info("여러 날짜가 포함된 파일을 업로드하면 추이를 볼 수 있습니다.")

# ==============================
# 세부 요약 표
# ==============================
st.markdown("### 🧾 귀책·상태·작업자 요약 (선택 일자)")
colA, colB = st.columns(2)
with colA:
    g1 = day.groupby("귀책")["유닛"].agg(건수="size", 유닛="sum").reset_index().sort_values("유닛", ascending=False)
    st.write("**귀책별**")
    st.dataframe(g1, use_container_width=True)
    g2 = day.groupby("상태")["유닛"].agg(건수="size", 유닛="sum").reset_index().sort_values("유닛", ascending=False)
    st.write("**상태별**")
    st.dataframe(g2, use_container_width=True)
with colB:
    g3 = day.groupby("포장작업자")["유닛"].agg(건수="size", 유닛="sum").reset_index().sort_values("유닛", ascending=False)
    st.write("**포장작업자별**")
    st.dataframe(g3, use_container_width=True)
    g4 = day.groupby("풋월작업자")["유닛"].agg(건수="size", 유닛="sum").reset_index().sort_values("유닛", ascending=False)
    st.write("**풋월작업자별**")
    st.dataframe(g4, use_container_width=True)

with st.expander("🔍 원본 데이터 (해당 일자)"):
    st.dataframe(day, use_container_width=True)

st.caption("※ 오출 타겟 0.019%, 생산 누락 타겟 0.041%. 영향도는 OF귀책만 제외하여 계산합니다.")
