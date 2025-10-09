# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import io, re
import requests
import chardet
from datetime import datetime, date, timedelta

# -------------------------------
# 안전한 CSV 로더
# -------------------------------
def load_csv_safely(url: str) -> pd.DataFrame:
    try:
        r = requests.get(url)
        raw = r.content
        enc = (chardet.detect(raw).get("encoding") or "utf-8")
        text = raw.decode(enc, errors="replace")
        return pd.read_csv(io.StringIO(text))
    except Exception as e:
        st.error(f"CSV 로드 오류: {e}")
        return pd.DataFrame()

# -------------------------------
# 한국어 자연어 날짜 파서
# -------------------------------
def parse_korean_date(q: str, available_dates: list[date]) -> date | None:
    if not q:
        return None
    q = q.strip()

    today = datetime.today().date()
    if "오늘" in q:
        return today
    if "어제" in q:
        return today - timedelta(days=1)
    if "그제" in q or "그저께" in q:
        return today - timedelta(days=2)

    # YYYY-MM-DD / YYYY.MM.DD / YYYY/MM/DD
    m = re.search(r"(\d{4})[.\-\/]\s?(\d{1,2})[.\-\/]\s?(\d{1,2})", q)
    if not m:
        # YYYYMMDD
        m = re.search(r"(\d{4})(\d{2})(\d{2})", q)
    if m:
        y, mth, d = map(int, m.groups())
        try:
            want = date(y, mth, d)
        except ValueError:
            return None
        # 있으면 그대로, 없으면 가장 가까운 날짜로 보정
        if want in available_dates:
            return want
        if available_dates:
            return min(available_dates, key=lambda x: abs(x - want))
    return None

# -------------------------------
# 페이지 설정
# -------------------------------
st.set_page_config(page_title="누락 현황 대시보드", layout="wide")
st.title("🎯 누락 현황 대시보드 (자연어 질문 + 샘플 자동 로드)")

st.caption("CSV 업로드 또는 샘플 데이터를 사용하여 일자별 오출/누락 현황을 요약합니다. "
           "자연어로 예: ‘2025-09-27 누락 요약’, ‘오늘 오출율’, ‘어제 리포트’")

# 샘플 CSV (GitHub Raw URL)
sample_url = "https://raw.githubusercontent.com/jinwookyung-kurly-data/-/main/오출자동화_test_927.csv"

# -------------------------------
# 파일 업로드 / 샘플 데이터
# -------------------------------
uploaded = st.file_uploader("CSV 파일 업로드 (헤더 포함)", type=["csv"])
if uploaded is not None:
    df = pd.read_csv(uploaded, encoding="utf-8-sig")
    st.success("✅ 업로드된 파일이 사용됩니다.")
else:
    df = load_csv_safely(sample_url)
    st.info("ℹ️ 샘플 데이터(오출자동화_test_927.csv)가 자동 로드되었습니다.")

# 컬럼 정규화 (이름 변형 흡수)
rename_map = {
    "포장완료로": "포장완료시간",
    "분류완료로": "분류완료시간",
    "포장완료": "포장완료시간",
    "분류완료": "분류완료시간",
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

dates = sorted([d for d in df["날짜"].dropna().unique().tolist()])
if not dates:
    st.error("날짜 컬럼을 해석하지 못했습니다. YYYY-MM-DD로 저장해주세요.")
    st.stop()

# -------------------------------
# 자연어 질문 + 날짜 선택 UI
# -------------------------------
with st.sidebar:
    st.header("🔎 자연어 질문")
    q = st.text_input("예) '2025-09-27 누락 현황', '오늘 오출율', '어제 요약'")
    st.caption("질문에 날짜가 없으면 아래 드롭다운 날짜를 사용합니다.")
    st.divider()
    manual_date = st.selectbox("📅 날짜 선택", dates, index=len(dates)-1)

# 자연어에서 날짜 추출 → 없으면 드롭다운 값 사용
parsed = parse_korean_date(q, dates) if q else None
selected_date = parsed or manual_date
if parsed:
    st.success(f"🗓 자연어에서 날짜 인식: **{selected_date}**")

# -------------------------------
# 선택 일자 데이터로 요약
# -------------------------------
day = df[df["날짜"] == selected_date].copy()
if day.empty:
    st.warning("선택한 날짜의 데이터가 없습니다.")
    st.stop()

# 오출/누락 정의
is_ochul = day["상태"].astype(str).str.contains("오출|오배분", na=False)
is_nul   = day["상태"].astype(str).str.contains("누락",       na=False)

total_units  = int(day["유닛"].sum())
ochul_units  = int(day.loc[is_ochul, "유닛"].sum())
nul_units    = int(day.loc[is_nul, "유닛"].sum())

target_ochul = 0.019 / 100  # 0.019%
target_nul   = 0.041 / 100  # 0.041%

ochul_rate = (ochul_units / total_units) if total_units else 0.0
nul_rate   = (nul_units   / total_units) if total_units else 0.0

st.subheader(f"📌 {selected_date} 요약")
c1, c2, c3, c4 = st.columns(4)
c1.metric("전체 건수", f"{len(day):,}")
c2.metric("전체 유닛", f"{total_units:,}")
c3.metric("오출율", f"{ochul_rate*100:.3f}%", f"{(ochul_rate - target_ochul)*100:+.3f} pp")
c4.metric("누락율", f"{nul_rate*100:.3f}%", f"{(nul_rate - target_nul)*100:+.3f} pp")

# 표/요약
st.markdown("### 🧾 귀책·상태·작업자 요약")
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

st.caption("※ 오출 타겟 0.019%, 생산 누락 타겟 0.041%. 자연어 예: '어제 누락 요약', '2025/09/27 오출율'.")
