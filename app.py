# -*- coding: utf-8 -*-
import io, re
from datetime import datetime, date, timedelta
import chardet
import pandas as pd
import requests
import streamlit as st

# ==============================
# 상수 / 경로
# ==============================
TARGET_OCHUL = 0.00019   # 0.019%
TARGET_NUL   = 0.00041   # 0.041%
OCHUL_STATUS = "교차오배분"
NUL_STATUS   = "생산누락"
OF_LABEL     = "OF귀책"

DATA_URL   = "https://raw.githubusercontent.com/jinwookyung-kurly-data/-/main/오출자동화_test_927.csv"
TOTALS_URL = "https://raw.githubusercontent.com/jinwookyung-kurly-data/-/main/total.csv"

# ==============================
# 유틸 함수
# ==============================
def load_csv_safely(url: str) -> pd.DataFrame:
    """GitHub raw csv 안전 로더"""
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
    """'오늘', '어제', '2025.09.27' 등의 입력 파싱"""
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
# 페이지 기본 설정
# ==============================
st.set_page_config(page_title="누락 현황 대시보드", layout="wide")
st.title("누락 현황 대시보드 ")

st.caption("오출=교차오배분, 누락=생산누락. **실제율=OF귀책만**, **추정율=전체 기준**. "
           "분모(전체 유닛)는 `total.csv`의 `Total_unit`을 우선 사용합니다.")

# ==============================
# 데이터 로드
# ==============================
uploaded = st.file_uploader("CSV 업로드", type=["csv"])
df = pd.read_csv(uploaded, encoding="utf-8-sig") if uploaded else load_csv_safely(DATA_URL)
if uploaded is None:
    st.info("샘플 데이터를 사용합니다.")
else:
    st.success("업로드된 파일 사용 중.")

# 컬럼 정리
rename_map = {"포장완료로":"포장완료시간","분류완료로":"분류완료시간","포장완료":"포장완료시간","분류완료":"분류완료시간"}
df.rename(columns=rename_map, inplace=True)
df.columns = df.columns.str.replace("\ufeff","",regex=True).str.strip()

expected = ["날짜","주문번호","유닛","타입","상태","포장완료시간","분류완료시간","포장작업자","풋월작업자","사유","귀책"]
missing = [c for c in expected if c not in df.columns]
if missing:
    st.error(f"❌ CSV 헤더 형식 불일치\n빠진 컬럼: {missing}")
    st.stop()

# 형 변환
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
# total.csv 로드
# ==============================
totals_df = load_csv_safely(TOTALS_URL)
totals_map: dict[date,int] = {}
if not totals_df.empty:
    totals_df.columns = totals_df.columns.str.strip()
    if "Total_unit" in totals_df.columns and "D" in totals_df.columns:
        totals_df["Total_unit"] = totals_df["Total_unit"].astype(str).str.replace(",","",regex=False)
        totals_df["Total_unit"] = pd.to_numeric(totals_df["Total_unit"], errors="coerce").fillna(0).astype(int)
        totals_df["D_date"] = pd.to_datetime(totals_df["D"], errors="coerce").dt.date
        totals_map = {d:int(u) for d,u in totals_df[["D_date","Total_unit"]].dropna().itertuples(index=False, name=None)}

# ==============================
# 날짜 선택
# ==============================
with st.sidebar:
    st.header("🔎 자연어 날짜 선택")
    q = st.text_input("예) '오늘', '어제', '2025/09/27'")
    st.divider()
    man_date = st.selectbox("📅 날짜 선택", dates, index=len(dates)-1)

parsed = parse_korean_date(q, dates) if q else None
selected_date = parsed or man_date
if parsed:
    st.success(f"🗓 인식된 날짜: **{selected_date}**")

# ==============================
# 선택 일자 요약 (유닛 기준)
# ==============================
day = df[df["날짜"] == selected_date].copy()
if day.empty:
    st.warning("선택한 날짜 데이터가 없습니다.")
    st.stop()

den = int(totals_map.get(selected_date, int(day["유닛"].sum()) or 1))
ochul_all = int(day.loc[day["is_ochul"], "유닛"].sum())
ochul_of  = int(day.loc[day["is_ochul"] & day["is_of"], "유닛"].sum())
nul_all   = int(day.loc[day["is_nul"],   "유닛"].sum())
nul_of    = int(day.loc[day["is_nul"]   & day["is_of"], "유닛"].sum())

act_ochul = (ochul_of  / den) if den else 0.0
est_ochul = (ochul_all / den) if den else 0.0
act_nul   = (nul_of    / den) if den else 0.0
est_nul   = (nul_all   / den) if den else 0.0

st.subheader(f"📌 {selected_date} 요약 (총 Unit={den:,})")
c1, c2, c3, c4 = st.columns(4)
c1.metric("오출(실제:OF)",  pct(act_ochul), pp(act_ochul - TARGET_OCHUL))
c2.metric("오출(추정:전체)", pct(est_ochul), pp(est_ochul - TARGET_OCHUL))
c3.metric("누락(실제:OF)",  pct(act_nul),   pp(act_nul   - TARGET_NUL))
c4.metric("누락(추정:전체)", pct(est_nul),   pp(est_nul   - TARGET_NUL))

# ==============================
# 상태값 요약
# ==============================
st.markdown("### 🧩 상태값 요약")
status_summary = (
    day["상태"]
      .astype(str)
      .value_counts()
      .reset_index()
      .rename(columns={"index": "상태", "상태": "건수"})
)
st.dataframe(status_summary, use_container_width=True)

# ==============================
# 귀책 제외 What-if (추정율 기준)
# ==============================
st.markdown("### 🧮 귀책 제외 What-if (추정율 기준)")
blame_options = sorted([b for b in df["귀책"].dropna().astype(str).str.strip().unique().tolist()])
exclude_blames = st.multiselect("제외할 귀책 선택", options=blame_options)

if exclude_blames:
    mask_keep = ~day["귀책"].astype(str).str.strip().isin(exclude_blames)
    adj_ochul_all = int(day.loc[mask_keep & day["is_ochul"], "유닛"].sum())
    adj_nul_all   = int(day.loc[mask_keep & day["is_nul"],   "유닛"].sum())

    adj_est_ochul = (adj_ochul_all / den) if den else 0.0
    adj_est_nul   = (adj_nul_all   / den) if den else 0.0

    st.write(f"**제외된 귀책:** {', '.join(exclude_blames)}")

    tbl = pd.DataFrame({
        "항목": ["오출율(추정:전체)", "누락율(추정:전체)"],
        "기존(%)": [est_ochul*100, est_nul*100],
        "조정(%)": [adj_est_ochul*100, adj_est_nul*100],
        "변화(pp)": [(adj_est_ochul-est_ochul)*100, (adj_est_nul-est_nul)*100],
        "타겟대비(pp)": [
            (adj_est_ochul - TARGET_OCHUL)*100,
            (adj_est_nul   - TARGET_NUL)*100
        ]
    })
    st.dataframe(tbl.round(3), use_container_width=True)
else:
    st.caption("왼쪽에서 제외할 귀책을 선택하면 조정 결과가 표시됩니다.")

# ==============================
# 사유 TOP + 귀책별 요약
# ==============================
st.markdown("### 🧾 사유 TOP")
reason_top = (
    day.groupby("사유")["유닛"]
       .agg(건수="size", 유닛="sum")
       .reset_index()
       .rename(columns={"사유": "reason"})
       .sort_values("유닛", ascending=False)
)
st.dataframe(reason_top.head(15), use_container_width=True)

st.markdown("### ⚙️ 귀책별 카운트 요약")
blame_summary = (
    day.groupby("귀책")["유닛"]
       .agg(건수="size", 유닛합계="sum")
       .reset_index()
       .sort_values("유닛합계", ascending=False)
)
st.dataframe(blame_summary, use_container_width=True)

# ==============================
# 전체 데이터 보기
# ==============================
st.markdown("### 📊 정리된 데이터 열람")
with st.expander("📂 전체 데이터 보기"):
    st.dataframe(df, use_container_width=True, height=500)
with st.expander("📅 선택 일자 데이터 보기"):
    st.dataframe(day, use_container_width=True, height=400)
