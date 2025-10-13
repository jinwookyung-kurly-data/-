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

DATA_URL = "https://raw.githubusercontent.com/jinwookyung-kurly-data/-/blob/main/오출자동화_test_927.csv"
TOTALS_URL = "https://raw.githubusercontent.com/jinwookyung-kurly-data/-/main/total.csv"

# ==============================
# 유틸 함수
# ==============================
def load_csv_from_url(url: str) -> pd.DataFrame:
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

def build_totals_map(totals_df: pd.DataFrame) -> dict:
    """
    total.csv → { 날짜(date): Total_unit(int) }
    컬럼 이름 유연 처리: 날짜는 D 또는 날짜, 유닛은 Total_unit
    """
    if totals_df.empty:
        return {}
    df = totals_df.copy()
    df.columns = df.columns.str.strip()

    # 날짜 컬럼 후보
    date_col = None
    for cand in ["D", "날짜", "date", "Date"]:
        if cand in df.columns:
            date_col = cand
            break
    if date_col is None:
        st.warning("total.csv 에 날짜 컬럼(D/날짜)이 없어 분모를 만들 수 없습니다.")
        return {}

    if "Total_unit" not in df.columns:
        st.warning("total.csv 에 Total_unit 컬럼이 없어 분모를 만들 수 없습니다.")
        return {}

    # 숫자 정리
    df["Total_unit"] = (
        df["Total_unit"].astype(str).str.replace(",", "", regex=False)
    )
    df["Total_unit"] = pd.to_numeric(df["Total_unit"], errors="coerce").fillna(0).astype(int)

    # 날짜 파싱 (여러 포맷 허용)
    dstr = df[date_col].astype(str)
    dstr = dstr.str.replace(" ", "")
    dstr = dstr.str.replace("년", "-").str.replace("월", "-").str.replace("일", "")
    dstr = dstr.str.replace(r"[.]", "-", regex=True)
    df["__date__"] = pd.to_datetime(dstr, errors="coerce").dt.date

    mp = {d: int(u) for d, u in df[["__date__", "Total_unit"]].dropna().itertuples(index=False, name=None)}
    return mp

# ==============================
# 페이지 기본 설정
# ==============================
st.set_page_config(page_title="오출 및 누락 현황 대시보드", layout="wide")
st.title("오출 및 누락 현황 대시보드 ")

st.caption(
    "오출=교차오배분, 누락=생산누락. **실제율=OF귀책만**, **추정율=전체 기준**. "
    "분모(전체 유닛)는 `total.csv`의 `Total_unit`을 우선 사용합니다. "
    "아래에서 **total.csv도 업로드**할 수 있습니다."
)

# ==============================
# 데이터 로드 (본 데이터 + total.csv)
# ==============================
col_up1, col_up2 = st.columns([2, 1])
with col_up1:
    uploaded = st.file_uploader("📄 누락/오출 CSV 업로드", type=["csv"], key="data_csv")
with col_up2:
    uploaded_totals = st.file_uploader("📈 total.csv 업로드 (선택)", type=["csv"], key="totals_csv")

# 본 데이터
df = pd.read_csv(uploaded, encoding="utf-8-sig") if uploaded else load_csv_from_url(DATA_URL)
if uploaded is None:
    st.info("샘플 데이터를 사용합니다.")
else:
    st.success("업로드된 파일 사용 중.")

# total.csv
if uploaded_totals is not None:
    try:
        totals_df = pd.read_csv(uploaded_totals, encoding="utf-8-sig")
        st.success("업로드된 total.csv 사용 중.")
    except Exception:
        totals_df = pd.read_csv(uploaded_totals)  # 인코딩 자동
        st.success("업로드된 total.csv 사용 중.")
else:
    totals_df = load_csv_from_url(TOTALS_URL)
    if totals_df.empty:
        st.warning("total.csv 를 찾지 못했습니다. 당일 분모는 업로드 CSV의 유닛 합계를 사용합니다.")
    else:
        st.info("샘플 total.csv 사용 중.")

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

# total.csv → map
totals_map = build_totals_map(totals_df)

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

# 분자(유닛)
ochul_all = int(day.loc[day["is_ochul"], "유닛"].sum())
ochul_of  = int(day.loc[day["is_ochul"] & day["is_of"], "유닛"].sum())
nul_all   = int(day.loc[day["is_nul"],   "유닛"].sum())
nul_of    = int(day.loc[day["is_nul"]   & day["is_of"], "유닛"].sum())

# 비율
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
# 상태값 요약 (건수 + 유닛합계)
# ==============================
st.markdown("### 🧩 상태값 요약")
status_summary = (
    day.groupby("상태")
      .agg(건수=("유닛", "size"), 유닛합계=("유닛", "sum"))
      .reset_index()
      .sort_values("유닛합계", ascending=False)
)
st.dataframe(status_summary, use_container_width=True)

# ==============================
# 귀책 제외 What-if (추정율 기준, 유닛도 함께)
# ==============================
st.markdown("### 🧮 귀책 제외 What-if (추정율 기준, 유닛 포함)")
blame_options = sorted([b for b in df["귀책"].dropna().astype(str).str.strip().unique().tolist()])
exclude_blames = st.multiselect("제외할 귀책 선택", options=blame_options)

if exclude_blames:
    mask_keep = ~day["귀책"].astype(str).str.strip().isin(exclude_blames)

    # 제외 후 유닛(분자)
    adj_ochul_all = int(day.loc[mask_keep & day["is_ochul"], "유닛"].sum())
    adj_nul_all   = int(day.loc[mask_keep & day["is_nul"],   "유닛"].sum())

    # 비율
    adj_est_ochul = (adj_ochul_all / den) if den else 0.0
    adj_est_nul   = (adj_nul_all   / den) if den else 0.0

    tbl = pd.DataFrame({
        "항목":        ["오출(추정:전체)", "누락(추정:전체)"],
        "기존유닛":     [ochul_all,         nul_all],
        "조정유닛":     [adj_ochul_all,     adj_nul_all],
        "변화유닛":     [adj_ochul_all - ochul_all, adj_nul_all - nul_all],
        "기존(%)":      [est_ochul*100,     est_nul*100],
        "조정(%)":      [adj_est_ochul*100, adj_est_nul*100],
        "변화(pp)":     [(adj_est_ochul-est_ochul)*100, (adj_est_nul-est_nul)*100],
        "타겟대비(pp)": [(adj_est_ochul - TARGET_OCHUL)*100,
                      (adj_est_nul   - TARGET_NUL)*100],
    })
    st.dataframe(tbl.round(3), use_container_width=True)
else:
    st.caption("왼쪽에서 제외할 귀책을 선택하면 조정 유닛/비율이 표시됩니다.")

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
# OF 기준 작업자 로그 + 작업자별 요약
# ==============================
of_fail = day[(day["is_of"]) & (day["is_ochul"] | day["is_nul"])].copy()

st.markdown("### 👷 작업자별 로그 (OF 기준 · 교차오배분/생산누락)")
if of_fail.empty:
    st.info("OF 기준의 교차오배분/생산누락 데이터가 없습니다.")
else:
    of_fail["포장완료시간"] = of_fail["포장완료시간"].astype(str)
    tabs = st.tabs(["포장 작업자 로그", "풋월 작업자 로그"])

    with tabs[0]:
        pack_log = of_fail[["포장작업자", "상태", "포장완료시간"]].rename(
            columns={"포장작업자": "작업자"}
        ).sort_values(["작업자", "포장완료시간"])
        st.dataframe(pack_log, use_container_width=True)

    with tabs[1]:
        put_log = of_fail[["풋월작업자", "상태", "포장완료시간"]].rename(
            columns={"풋월작업자": "작업자"}
        ).sort_values(["작업자", "포장완료시간"])
        st.dataframe(put_log, use_container_width=True)

    st.markdown("### 📦 작업자별 누락/오출 카운트 요약 (OF 기준)")
    colA, colB = st.columns(2)

    def worker_summary(df_src: pd.DataFrame, worker_col: str) -> pd.DataFrame:
        g = (
            df_src.groupby(worker_col)
                  .apply(lambda x: pd.Series({
                      "오출건수": int((x["is_ochul"]).sum()),
                      "누락건수": int((x["is_nul"]).sum()),
                      "오출유닛": int(x.loc[x["is_ochul"], "유닛"].sum()),
                      "누락유닛": int(x.loc[x["is_nul"], "유닛"].sum()),
                  }))
                  .reset_index()
                  .rename(columns={worker_col: "작업자"})
                  .sort_values(["오출건수", "누락건수", "오출유닛", "누락유닛"], ascending=False)
        )
        return g

    with colA:
        st.write("**포장작업자 요약**")
        st.dataframe(worker_summary(of_fail, "포장작업자"), use_container_width=True)

    with colB:
        st.write("**풋월작업자 요약**")
        st.dataframe(worker_summary(of_fail, "풋월작업자"), use_container_width=True)

# ==============================
# 전체 데이터 보기
# ==============================
st.markdown("### 📊 정리된 데이터 열람")
with st.expander("📂 전체 데이터 보기"):
    st.dataframe(df, use_container_width=True, height=500)
with st.expander("📅 선택 일자 데이터 보기"):
    st.dataframe(day, use_container_width=True, height=400)
