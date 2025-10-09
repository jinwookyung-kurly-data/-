# -*- coding: utf-8 -*-
import io, re
from datetime import datetime, date, timedelta

import chardet
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# ==============================
# 상수 / 경로
# ==============================
TARGET_OCHUL = 0.00019   # 0.019%
TARGET_NUL   = 0.00041   # 0.041%
OCHUL_STATUS = "교차오배분"   # 오출 산정
NUL_STATUS   = "생산누락"     # 누락 산정
OF_LABEL     = "OF귀책"       # 실제율은 OF만

DATA_URL   = "https://raw.githubusercontent.com/jinwookyung-kurly-data/-/main/오출자동화_test_927.csv"
TOTALS_URL = "https://raw.githubusercontent.com/jinwookyung-kurly-data/-/main/total.csv"  # ← 여기에 두신 total.csv

# ==============================
# 유틸
# ==============================
def load_csv_safely(url: str) -> pd.DataFrame:
    try:
        r = requests.get(url)
        r.raise_for_status()
        raw = r.content
        enc = (chardet.detect(raw).get("encoding") or "utf-8")
        text = raw.decode(enc, errors="replace")
        return pd.read_csv(io.StringIO(text))
    except Exception as e:
        st.warning(f"⚠️ {url} 로드 실패: {e}")
        return pd.DataFrame()

def parse_korean_date(q: str, available_dates: list[date]) -> date | None:
    if not q: return None
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
        return want if want in available_dates else (min(available_dates, key=lambda x: abs(x - want)) if available_dates else None)
    return None

def pct(x: float) -> str: return f"{x*100:.3f}%"
def pp(x: float)  -> str: return f"{x*100:+.3f} pp"

# ==============================
# 페이지
# ==============================
st.set_page_config(page_title="누락 현황 대시보드", layout="wide")
st.title("🎯 누락 현황 대시보드 (자연어 + 실제/추정 + total.csv 연동)")

st.caption("오출=교차오배분, 누락=생산누락. **실제율=OF귀책만**, **추정율=귀책 무관 전체**. "
           "분모(전체 유닛)는 `total.csv`의 `Total_unit`을 우선 사용합니다.")

# ==============================
# 데이터 로드
# ==============================
uploaded = st.file_uploader("CSV 업로드 (헤더: 날짜,주문번호,유닛,타입,상태,포장완료시간,분류완료시간,포장작업자,풋월작업자,사유,귀책)", type=["csv"])
df = pd.read_csv(uploaded, encoding="utf-8-sig") if uploaded else load_csv_safely(DATA_URL)
if uploaded is None:
    st.info("샘플 데이터를 사용합니다.")
else:
    st.success("업로드된 파일 사용 중.")


# 컬럼 정규화
rename_map = {"포장완료로":"포장완료시간","분류완료로":"분류완료시간","포장완료":"포장완료시간","분류완료":"분류완료시간"}
df.rename(columns=rename_map, inplace=True)
df.columns = df.columns.str.replace("\ufeff","",regex=True).str.strip()

expected = ["날짜","주문번호","유닛","타입","상태","포장완료시간","분류완료시간","포장작업자","풋월작업자","사유","귀책"]
missing = [c for c in expected if c not in df.columns]
if missing:
    st.error(f"❌ CSV 헤더 형식 불일치\n빠진 컬럼: {missing}\n감지된 헤더: {list(df.columns)}")
    st.stop()

df["유닛"] = pd.to_numeric(df["유닛"], errors="coerce").fillna(0).astype(int)
df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce").dt.date
df["is_ochul"] = df["상태"].astype(str).str.contains(OCHUL_STATUS, na=False)
df["is_nul"]   = df["상태"].astype(str).str.contains(NUL_STATUS,   na=False)
df["is_of"]    = df["귀책"].astype(str).str.replace(" ","").str.upper().eq(OF_LABEL.upper())

dates = sorted(df["날짜"].dropna().unique().tolist())
if not dates:
    st.error("날짜를 해석하지 못했습니다.")
    st.stop()

# ==============================
# total.csv 로드 → 날짜별 분모 맵
# ==============================
totals_df = load_csv_safely(TOTALS_URL)
totals_map: dict[date,int] = {}
if not totals_df.empty:
    # 헤더 정리: Y, D, Day, Total_order, Total_unit
    cols = {c:c.strip() for c in totals_df.columns}
    totals_df.rename(columns=cols, inplace=True)
    # 날짜 파싱 (D가 '2024. 1. 1' 형태)
    if "D" in totals_df.columns:
        # 쉼표 제거 등 숫자 정리
        totals_df["Total_unit"] = (
            totals_df["Total_unit"].astype(str).str.replace(",", "", regex=False)
        )
        totals_df["Total_unit"] = pd.to_numeric(totals_df["Total_unit"], errors="coerce").fillna(0).astype(int)
        totals_df["D_date"] = pd.to_datetime(totals_df["D"], errors="coerce").dt.date
        totals_map = {d:int(u) for d,u in totals_df[["D_date","Total_unit"]].dropna().itertuples(index=False, name=None)}
    else:
        st.warning("`total.csv`에 'D' 컬럼이 없어 분모 매핑을 만들 수 없습니다. (무시하고 진행)")

# ==============================
# 자연어 + 날짜 선택 + 분모 설정
# ==============================
with st.sidebar:
    st.header("🔎 자연어 질문")
    q = st.text_input("예) '오늘 오출율', '어제 누락 요약', '2025/09/27 리포트'")
    st.caption("질문에 날짜가 없으면 아래 드롭다운 값을 사용합니다.")
    st.divider()
    man_date = st.selectbox("📅 날짜 선택", dates, index=len(dates)-1)

parsed = parse_korean_date(q, dates) if q else None
selected_date = parsed or man_date
if parsed:
    st.success(f"🗓 자연어에서 날짜 인식: **{selected_date}**")

# ==============================
# 선택 일자 요약 (실제/추정) — 분모: total.csv 우선
# ==============================
day = df[df["날짜"] == selected_date].copy()
if day.empty:
    st.warning("선택한 날짜 데이터가 없습니다.")
    st.stop()

# 분모 결정: total.csv > 파일 내 합계
den = int(totals_map.get(selected_date, int(day["유닛"].sum()) or 1))

# 유닛 합
ochul_all = int(day.loc[day["is_ochul"], "유닛"].sum())
ochul_of  = int(day.loc[day["is_ochul"] & day["is_of"], "유닛"].sum())
nul_all   = int(day.loc[day["is_nul"],   "유닛"].sum())
nul_of    = int(day.loc[day["is_nul"]   & day["is_of"], "유닛"].sum())

# 비율 (요청하신 규칙)
act_ochul = (ochul_of  / den) if den else 0.0     # 실제 오출율 = 교차오배분 & OF / 분모
est_ochul = (ochul_all / den) if den else 0.0     # 추정 오출율 = 교차오배분 전체 / 분모
act_nul   = (nul_of    / den) if den else 0.0     # 실제 누락율 = 생산누락 & OF / 분모
est_nul   = (nul_all   / den) if den else 0.0     # 추정 누락율 = 생산누락 전체 / 분모

st.subheader(f"📌 {selected_date} 요약 (분모={den:,})")
c1, c2, c3, c4 = st.columns(4)
c1.metric("오출(실제: OF)",  pct(act_ochul), pp(act_ochul - TARGET_OCHUL))
c2.metric("오출(추정: 전체)", pct(est_ochul), pp(est_ochul - TARGET_OCHUL))
c3.metric("누락(실제: OF)",  pct(act_nul),   pp(act_nul   - TARGET_NUL))
c4.metric("누락(추정: 전체)", pct(est_nul),   pp(est_nul   - TARGET_NUL))

# 비교 막대
colA, colB = st.columns(2)
with colA:
    fig1 = px.bar(x=["타겟","실제(OF)","추정(전체)"],
                  y=[TARGET_OCHUL*100, act_ochul*100, est_ochul*100],
                  labels={"x":"", "y":"%"},
                  title="오출율 비교")
    st.plotly_chart(fig1, use_container_width=True)
with colB:
    fig2 = px.bar(x=["타겟","실제(OF)","추정(전체)"],
                  y=[TARGET_NUL*100, act_nul*100, est_nul*100],
                  labels={"x":"", "y":"%"},
                  title="누락율 비교")
    st.plotly_chart(fig2, use_container_width=True)

# ==============================
# 📈 일자별 트래킹 (total.csv 분모 우선)
# ==============================
daily = (
    df.groupby("날짜")
      .apply(lambda x: pd.Series({
          "오출(전체)": int(x.loc[x["is_ochul"], "유닛"].sum()),
          "오출(OF)" : int(x.loc[x["is_ochul"] & x["is_of"], "유닛"].sum()),
          "누락(전체)": int(x.loc[x["is_nul"],   "유닛"].sum()),
          "누락(OF)" : int(x.loc[x["is_nul"]   & x["is_of"], "유닛"].sum()),
          "분모":       int(totals_map.get(x.name, int(x["유닛"].sum()) or 1))
      }))
      .reset_index().sort_values("날짜")
)
if not daily.empty:
    daily["오출율(실제:OF)"]  = daily["오출(OF)"]   / daily["분모"]
    daily["오출율(추정:전체)"] = daily["오출(전체)"] / daily["분모"]
    daily["누락율(실제:OF)"]  = daily["누락(OF)"]   / daily["분모"]
    daily["누락율(추정:전체)"] = daily["누락(전체)"] / daily["분모"]
    daily["타겟(오출)"] = TARGET_OCHUL
    daily["타겟(누락)"] = TARGET_NUL

    st.markdown("### 📈 트래킹")
    fig_o = px.line(daily, x="날짜", y=["오출율(실제:OF)","오출율(추정:전체)","타겟(오출)"], markers=True, title="오출율 추이")
    fig_n = px.line(daily, x="날짜", y=["누락율(실제:OF)","누락율(추정:전체)","타겟(누락)"], markers=True, title="누락율 추이")
    for f in (fig_o, fig_n): f.update_yaxes(tickformat=".2%")
    st.plotly_chart(fig_o, use_container_width=True)
    st.plotly_chart(fig_n, use_container_width=True)

    view = daily.copy()
    for c in ["오출율(실제:OF)","오출율(추정:전체)","누락율(실제:OF)","누락율(추정:전체)","타겟(오출)","타겟(누락)"]:
        view[c] = (view[c]*100).round(3)
    st.dataframe(view, use_container_width=True)
else:
    st.info("여러 날짜가 포함된 파일을 업로드하면 추이를 볼 수 있습니다.")

# ==============================
# 세부 요약 (선택 일자)
# ==============================
st.markdown("### 🧾 귀책/상태/작업자 요약 (선택 일자)")
col1, col2 = st.columns(2)
with col1:
    g1 = day.groupby("귀책")["유닛"].agg(건수="size", 유닛="sum").reset_index().sort_values("유닛", ascending=False)
    st.write("**귀책별**"); st.dataframe(g1, use_container_width=True)
    g2 = day.groupby("상태")["유닛"].agg(건수="size", 유닛="sum").reset_index().sort_values("유닛", ascending=False)
    st.write("**상태별**"); st.dataframe(g2, use_container_width=True)
with col2:
    g3 = day.groupby("포장작업자")["유닛"].agg(건수="size", 유닛="sum").reset_index().sort_values("유닛", ascending=False)
    st.write("**포장작업자별**"); st.dataframe(g3, use_container_width=True)
    g4 = day.groupby("풋월작업자")["유닛"].agg(건수="size", 유닛="sum").reset_index().sort_values("유닛", ascending=False)
    st.write("**풋월작업자별**"); st.dataframe(g4, use_container_width=True)

st.caption("※ 분모는 total.csv의 Total_unit을 우선 사용하며, 없으면 업로드 파일 내 유닛 합계로 대체합니다.")
