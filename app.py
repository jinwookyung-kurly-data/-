# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import io
import requests
import chardet

# ---------------------------------------------------------
# 안전한 CSV 로더 함수
# ---------------------------------------------------------
def load_csv_safely(url: str):
    """인코딩 자동 감지 후 CSV 로드"""
    try:
        response = requests.get(url)
        raw_data = response.content
        detected = chardet.detect(raw_data)
        encoding = detected["encoding"] or "utf-8"
        text = raw_data.decode(encoding, errors="replace")
        df = pd.read_csv(io.StringIO(text))
        return df
    except Exception as e:
        st.error(f"CSV 로드 중 오류 발생: {e}")
        return pd.DataFrame()

# ---------------------------------------------------------
# 페이지 설정
# ---------------------------------------------------------
st.set_page_config(page_title="누락 현황 대시보드", layout="wide")

st.title("🎯 누락 현황 대시보드 (자동 샘플 포함 버전)")
st.caption("CSV 업로드 또는 샘플 데이터를 사용하여 오출/누락 현황을 요약합니다.")

# ---------------------------------------------------------
# 샘플 데이터 URL
# ---------------------------------------------------------
sample_url = "https://raw.githubusercontent.com/jinwookyung-kurly-data/main/오출자동화_test_927.csv"

# ---------------------------------------------------------
# 파일 업로드 or 샘플 사용
# ---------------------------------------------------------
uploaded_file = st.file_uploader("CSV 파일을 업로드하세요", type=["csv"])
if uploaded_file is not None:
    df = pd.read_csv(uploaded_file, encoding="utf-8-sig")
    st.success("✅ 업로드된 파일이 사용됩니다.")
else:
    df = load_csv_safely(sample_url)
    st.info("ℹ️ 샘플 데이터(`오출자동화_test_927.csv`)가 자동으로 로드되었습니다.")

# ---------------------------------------------------------
# 컬럼 체크
# ---------------------------------------------------------
expected_cols = ["날짜", "주문번호", "유닛", "타입", "상태", "포장완료시간", "분류완료시간", "포장작업자", "풋월작업자", "사유", "귀책"]
if not all(col in df.columns for col in expected_cols):
    st.error("❌ CSV 헤더 형식이 일치하지 않습니다.")
    st.stop()

# ---------------------------------------------------------
# 통계 요약
# ---------------------------------------------------------
total_units = df["유닛"].sum()
by_blame = df.groupby("귀책")["유닛"].sum().reset_index().sort_values("유닛", ascending=False)
by_type = df.groupby("상태")["유닛"].sum().reset_index().sort_values("유닛", ascending=False)

# ---------------------------------------------------------
# 타겟 대비율 계산
# ---------------------------------------------------------
target_오출 = 0.019 / 100
target_누락 = 0.041 / 100

오출_유닛 = df[df["상태"].str.contains("오출|오배분", na=False)]["유닛"].sum()
누락_유닛 = df[df["상태"].str.contains("누락", na=False)]["유닛"].sum()

오출율 = 오출_유닛 / total_units if total_units > 0 else 0
누락율 = 누락_유닛 / total_units if total_units > 0 else 0

# ---------------------------------------------------------
# 요약 지표
# ---------------------------------------------------------
col1, col2 = st.columns(2)
with col1:
    st.metric("📦 총 유닛 수", f"{total_units:,}")
    st.metric("🚨 오출율", f"{오출율*100:.3f}%", f"{(오출율-target_오출)*100:.3f}% vs 타겟")
with col2:
    st.metric("❗ 누락율", f"{누락율*100:.3f}%", f"{(누락율-target_누락)*100:.3f}% vs 타겟")

st.subheader("📊 귀책별 유닛 요약")
st.dataframe(by_blame, use_container_width=True)

st.subheader("📋 상태별 유닛 요약")
st.dataframe(by_type, use_container_width=True)

# ---------------------------------------------------------
# 상세 데이터
# ---------------------------------------------------------
with st.expander("🔍 원본 데이터 보기"):
    st.dataframe(df, use_container_width=True)

st.caption("※ 오출 타겟 0.019%, 생산 누락 타겟 0.041% 기준으로 계산됩니다.")
