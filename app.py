
# -*- coding: utf-8 -*-
import io
import pandas as pd
import streamlit as st
import plotly.express as px

# =========================
# Config
# =========================
st.set_page_config(page_title="누락 현황 대시보드", layout="wide")

TARGET_OCHUL = 0.00019  # 0.019%
TARGET_NUL   = 0.00041  # 0.041%
RECOVERABLE_BLAMES_DEFAULT = ["시스템오류","배송귀책","CC팀귀책","공급사귀책","고객귀책"]

REQUIRED_COLS = ["날짜","주문번호","유닛","타입","상태","포장완료시간","분류완료시간","포장작업자","풋월작업자","사유","귀책"]

# =========================
# Helpers
# =========================
def normalize_status(v: str) -> str:
    t = str(v or "").strip().replace(" ", "")
    if t in ["교차오배분","교차오배분건","교차","오배분"]:
        return "교차 오배분"
    if "생산누락" in t:
        return "생산누락"
    if "배송누락" in t:
        return "배송누락"
    # 그대로
    return str(v).strip()

def normalize_blame(v: str) -> str:
    t = str(v or "").strip().lower().replace(" ", "")
    mapping = [
        (["of", "of귀책", "of책임"], "OF귀책"),
        (["시스템", "system", "시스템오류"], "시스템오류"),
        (["배송", "배송귀책", "delivery"], "배송귀책"),
        (["cc", "cc팀", "cc팀귀책"], "CC팀귀책"),
        (["공급사", "vendor", "공급사귀책"], "공급사귀책"),
        (["확인불가", "불명", "미확인"], "확인불가"),
        (["고객", "고객귀책"], "고객귀책"),
    ]
    for keys, label in mapping:
        for k in keys:
            if k in t:
                return label
    if t in ("", "nan", "none"):
        return "미분류"
    return str(v).strip()

def summarize(df, col):
    g = df.groupby(col)["유닛"].agg(건수="size", 유닛="sum").reset_index()
    return g.sort_values(["유닛","건수"], ascending=False)

def pct(x):
    return f"{x*100:.3f}%"

def pp(x):
    return f"{x*100:+.3f} pp"

# =========================
# UI - Sidebar
# =========================
st.title("📦 누락 현황 대시보드 (모바일 최적화)")
st.caption("파일 업로드 → 날짜 선택 → 오출/누락율 & 귀책 요약. 외부 API 미사용.")

with st.sidebar:
    st.header("1) 데이터 업로드")
    uploaded = st.file_uploader("CSV 또는 XLSX 업로드 (헤더 필수)", type=["csv","xlsx"])
    st.markdown("**필수 컬럼 순서는 상관없지만, 컬럼명은 다음과 같아야 합니다.**")
    st.code(", ".join(REQUIRED_COLS), language="text")
    st.divider()
    st.header("2) 옵션")
    recoverable_blames = st.multiselect("복구 가정 귀책 선택",
                                        options=["OF귀책","시스템오류","배송귀책","CC팀귀책","공급사귀책","확인불가","고객귀책","미분류"],
                                        default=RECOVERABLE_BLAMES_DEFAULT)
    ochul_statuses = st.multiselect("오출로 산정할 상태",
                                    options=["교차 오배분","생산누락","배송누락"],
                                    default=["교차 오배분"])
    nul_statuses   = st.multiselect("누락으로 산정할 상태",
                                    options=["생산누락","배송누락","교차 오배분"],
                                    default=["생산누락","배송누락"])
    st.caption("※ 현장 기준에 맞게 상태/귀책을 조정하세요.")

if not uploaded:
    st.info("좌측 사이드바에서 파일을 업로드해주세요.")
    st.stop()

# =========================
# Load data
# =========================
if uploaded.name.endswith(".xlsx"):
    df = pd.read_excel(uploaded)
else:
    # Try UTF-8-SIG then CP949
    raw = uploaded.read()
    try:
        df = pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig")
    except Exception:
        df = pd.read_csv(io.BytesIO(raw), encoding="cp949")

missing_cols = [c for c in REQUIRED_COLS if c not in df.columns]
if missing_cols:
    st.error(f"다음 컬럼이 누락되었습니다: {', '.join(missing_cols)}")
    st.stop()

df = df[REQUIRED_COLS].copy()
df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce").dt.date
df["유닛"] = pd.to_numeric(df["유닛"], errors="coerce").fillna(0).astype(int)
df["상태_std"] = df["상태"].apply(normalize_status)
df["귀책_std"] = df["귀책"].apply(normalize_blame)

dates = sorted(df["날짜"].dropna().unique())
if not dates:
    st.error("날짜 컬럼을 날짜 형식으로 해석하지 못했습니다. 포맷을 YYYY-MM-DD로 맞춰주세요.")
    st.stop()

# =========================
# Tabs
# =========================
tab_day, tab_trend, tab_data = st.tabs(["📅 선택 일자 요약", "📈 추이(멀티일자)", "🗂 데이터/다운로드"])

with tab_day:
    selected_date = st.selectbox("날짜 선택", dates, index=len(dates)-1)
    day = df[df["날짜"] == selected_date].copy()
    if day.empty:
        st.warning("선택한 날짜 데이터가 없습니다.")
        st.stop()

    total_units = int(day["유닛"].sum())
    total_cases = len(day)

    ochul_units = int(day[day["상태_std"].isin(ochul_statuses)]["유닛"].sum())
    nul_units   = int(day[day["상태_std"].isin(nul_statuses)]["유닛"].sum())
    ochul_rate  = (ochul_units / total_units) if total_units > 0 else 0.0
    nul_rate    = (nul_units   / total_units) if total_units > 0 else 0.0

    # Recoverable (status-aware)
    rec_ochul_units = int(day[(day["상태_std"].isin(ochul_statuses)) & (day["귀책_std"].isin(recoverable_blames))]["유닛"].sum())
    rec_nul_units   = int(day[(day["상태_std"].isin(nul_statuses))   & (day["귀책_std"].isin(recoverable_blames))]["유닛"].sum())
    hypo_ochul_rate = ((ochul_units - rec_ochul_units) / total_units) if total_units > 0 else 0.0
    hypo_nul_rate   = ((nul_units   - rec_nul_units)   / total_units) if total_units > 0 else 0.0

    st.subheader(f"📌 {selected_date} 헤드라인")
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("전체 건수", f"{total_cases:,}")
    c2.metric("전체 유닛", f"{total_units:,}")
    c3.metric("오출 유닛", f"{ochul_units:,}", delta=pp(ochul_rate - TARGET_OCHUL))
    c4.metric("누락 유닛", f"{nul_units:,}", delta=pp(nul_rate - TARGET_NUL))

    st.markdown("### 🎯 타겟 대비")
    cc1, cc2 = st.columns(2)
    with cc1:
        st.markdown("**오출율**")
        st.metric("실제", pct(ochul_rate), delta=pp(ochul_rate - TARGET_OCHUL))
        st.metric("가정(복구 제외)", pct(hypo_ochul_rate), delta=pp(hypo_ochul_rate - TARGET_OCHUL))
        fig1 = px.bar(x=["타겟","실제","가정"], y=[TARGET_OCHUL*100, ochul_rate*100, hypo_ochul_rate*100],
                      labels={"x":"","y":"%"})
        st.plotly_chart(fig1, use_container_width=True)
    with cc2:
        st.markdown("**누락율**")
        st.metric("실제", pct(nul_rate), delta=pp(nul_rate - TARGET_NUL))
        st.metric("가정(복구 제외)", pct(hypo_nul_rate), delta=pp(hypo_nul_rate - TARGET_NUL))
        fig2 = px.bar(x=["타겟","실제","가정"], y=[TARGET_NUL*100, nul_rate*100, hypo_nul_rate*100],
                      labels={"x":"","y":"%"})
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("### 🧾 세부 요약")
    t1, t2 = st.columns(2)
    with t1:
        st.markdown("**상태별 요약**")
        st.dataframe(summarize(day, "상태_std"), use_container_width=True)
        st.markdown("**귀책별 요약**")
        st.dataframe(summarize(day, "귀책_std"), use_container_width=True)
    with t2:
        st.markdown("**사유별 요약**")
        st.dataframe(summarize(day, "사유"), use_container_width=True)
        st.markdown("**작업자 요약**")
        st.dataframe(summarize(day, "포장작업자"), use_container_width=True)
        st.dataframe(summarize(day, "풋월작업자"), use_container_width=True)

with tab_trend:
    # Per-day totals and rates
    daily = (
        df.assign(날짜=pd.to_datetime(df["날짜"]))
          .groupby("날짜")
          .apply(lambda x: pd.Series({
              "총유닛": int(x["유닛"].sum()),
              "오출유닛": int(x[x["상태_std"].isin(ochul_statuses)]["유닛"].sum()),
              "누락유닛": int(x[x["상태_std"].isin(nul_statuses)]["유닛"].sum()),
              "오출(복구제외)": int(x[(x["상태_std"].isin(ochul_statuses)) & (x["귀책_std"].isin(recoverable_blames))]["유닛"].sum()),
              "누락(복구제외)": int(x[(x["상태_std"].isin(nul_statuses))   & (x["귀책_std"].isin(recoverable_blames))]["유닛"].sum()),
          }))
          .reset_index()
          .sort_values("날짜")
    )
    if not daily.empty:
        daily["오출율"] = daily.apply(lambda r: (r["오출유닛"]/r["총유닛"]) if r["총유닛"]>0 else 0.0, axis=1)
        daily["누락율"] = daily.apply(lambda r: (r["누락유닛"]/r["총유닛"]) if r["총유닛"]>0 else 0.0, axis=1)
        daily["오출율(가정)"] = daily.apply(lambda r: ((r["오출유닛"]-r["오출(복구제외)"])/r["총유닛"]) if r["총유닛"]>0 else 0.0, axis=1)
        daily["누락율(가정)"] = daily.apply(lambda r: ((r["누락유닛"]-r["누락(복구제외)"])/r["총유닛"]) if r["총유닛"]>0 else 0.0, axis=1)

        st.markdown("#### 일자별 오출/누락율 추이")
        fig_tr1 = px.line(daily, x="날짜", y=["오출율","오출율(가정)"], markers=True)
        fig_tr2 = px.line(daily, x="날짜", y=["누락율","누락율(가정)"], markers=True)
        st.plotly_chart(fig_tr1, use_container_width=True)
        st.plotly_chart(fig_tr2, use_container_width=True)

        st.markdown("#### 일자별 총괄 표")
        view = daily.copy()
        for c in ["오출율","누락율","오출율(가정)","누락율(가정)"]:
            view[c] = (view[c]*100).round(3)
        st.dataframe(view, use_container_width=True)
    else:
        st.info("여러 날짜가 포함된 파일을 업로드하면 추이를 볼 수 있습니다.")

with tab_data:
    st.markdown("#### 원본 데이터 미리보기")
    st.dataframe(df.head(1000), use_container_width=True)
    # Downloads
    st.download_button("현재 데이터 CSV 다운로드", data=df.to_csv(index=False).encode("utf-8-sig"),
                       file_name="data_clean.csv", mime="text/csv")
    st.caption("※ 업로드한 파일을 정규화(상태/귀책 표준화)한 결과를 다운로드할 수 있습니다.")
