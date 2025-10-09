# ==============================
# 🧮 귀책 제외 What-if 시뮬레이터
# ==============================
st.markdown("### 🧮 귀책 제외 What-if (선택한 귀책이 **발생하지 않았다**고 가정)")

# 현재 데이터에 존재하는 귀책 목록(정렬)
blame_options = sorted([b for b in df["귀책"].dropna().astype(str).str.strip().unique().tolist()])
exclude_blames = st.multiselect(
    "제외할 귀책 선택",
    options=blame_options,
    help="선택한 귀책을 **제외**하고 오출/누락율을 다시 계산합니다. (분모는 그대로 유지)"
)

if exclude_blames:
    # 제외 마스크
    mask_keep = ~day["귀책"].astype(str).str.strip().isin(exclude_blames)

    # 유닛 재계산 (제외 반영)
    adj_ochul_all = int(day.loc[mask_keep & day["is_ochul"], "유닛"].sum())
    adj_ochul_of  = int(day.loc[mask_keep & day["is_ochul"] & day["is_of"], "유닛"].sum())
    adj_nul_all   = int(day.loc[mask_keep & day["is_nul"],   "유닛"].sum())
    adj_nul_of    = int(day.loc[mask_keep & day["is_nul"]   & day["is_of"], "유닛"].sum())

    # 비율 재계산
    adj_est_ochul = (adj_ochul_all / den) if den else 0.0   # 추정 오출율 (전체)
    adj_act_ochul = (adj_ochul_of  / den) if den else 0.0   # 실제 오출율 (OF)
    adj_est_nul   = (adj_nul_all   / den) if den else 0.0   # 추정 누락율 (전체)
    adj_act_nul   = (adj_nul_of    / den) if den else 0.0   # 실제 누락율 (OF)

    # 표시
    st.write(f"**제외된 귀책:** {', '.join(exclude_blames)}")
    colW1, colW2 = st.columns(2)
    with colW1:
        st.write("**오출율 변화**")
        st.metric("실제(OF) → 조정", f"{adj_act_ochul*100:.3f}%", f"{(adj_act_ochul - act_ochul)*100:+.3f} pp")
        st.metric("추정(전체) → 조정", f"{adj_est_ochul*100:.3f}%", f"{(adj_est_ochul - est_ochul)*100:+.3f} pp")
        fig_w1 = px.bar(
            x=["타겟","기존 실제(OF)","조정 실제(OF)","기존 추정(전체)","조정 추정(전체)"],
            y=[TARGET_OCHUL*100, act_ochul*100, adj_act_ochul*100, est_ochul*100, adj_est_ochul*100],
            labels={"x":"", "y":"%"},
            title="오출율 What-if"
        )
        st.plotly_chart(fig_w1, use_container_width=True)

    with colW2:
        st.write("**누락율 변화**")
        st.metric("실제(OF) → 조정", f"{adj_act_nul*100:.3f}%", f"{(adj_act_nul - act_nul)*100:+.3f} pp")
        st.metric("추정(전체) → 조정", f"{adj_est_nul*100:.3f}%", f"{(adj_est_nul - est_nul)*100:+.3f} pp")
        fig_w2 = px.bar(
            x=["타겟","기존 실제(OF)","조정 실제(OF)","기존 추정(전체)","조정 추정(전체)"],
            y=[TARGET_NUL*100, act_nul*100, adj_act_nul*100, est_nul*100, adj_est_nul*100],
            labels={"x":"", "y":"%"},
            title="누락율 What-if"
        )
        st.plotly_chart(fig_w2, use_container_width=True)

    with st.expander("📄 What-if 상세표"):
        tbl = pd.DataFrame({
            "항목": ["오출(실제:OF)","오출(추정:전체)","누락(실제:OF)","누락(추정:전체)"],
            "기존(%)": [act_ochul*100, est_ochul*100, act_nul*100, est_nul*100],
            "조정(%)": [adj_act_ochul*100, adj_est_ochul*100, adj_act_nul*100, adj_est_nul*100],
            "변화(pp)": [(adj_act_ochul-act_ochul)*100, (adj_est_ochul-est_ochul)*100,
                      (adj_act_nul-act_nul)*100, (adj_est_nul-est_nul)*100],
            "타겟 대비(pp)": [
                (adj_act_ochul - TARGET_OCHUL)*100,
                (adj_est_ochul - TARGET_OCHUL)*100,
                (adj_act_nul   - TARGET_NUL)*100,
                (adj_est_nul   - TARGET_NUL)*100,
            ],
        })
        st.dataframe(tbl.round(3), use_container_width=True)
else:
    st.caption("왼쪽에서 제외할 귀책을 선택하면 What-if 결과가 표시됩니다.")
