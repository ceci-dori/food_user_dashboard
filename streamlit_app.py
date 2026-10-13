import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="사용자 행동 탐색 대시보드", layout="wide")
st.title("사용자 행동 탐색 대시보드")
st.caption("주별 세션 퍼널 | 플랫폼 · 유입 경로별 | 2025.07 ~ 2026.06")

# ------------------------------------------------------------
# 0. 필요한 데이터만 추출 — 쓸 테이블과 컬럼만 메모리 DB에 올리고, 정제 테이블 events를 처음 한 번만 만듦
# ------------------------------------------------------------
DATA_DIR = "data"                          # 원본 CSV를 넣어 둔 폴더
NEEDED = {                                 # 이번 대시보드에 필요한 테이블과 컬럼
    "app_events": ["event_id", "event_datetime", "customer_id", "session_id",
                   "event_name", "platform", "traffic_source"],
}

@st.cache_resource
def get_db():                              # 필요한 컬럼만 메모리 DB에 올리고, 정제 테이블 events를 만듦 (처음 한 번만)
    con = sqlite3.connect(":memory:", check_same_thread=False)
    for name, cols in NEEDED.items():
        pd.read_csv(f"{DATA_DIR}/{name}.csv", usecols=cols).to_sql(name, con, index=False)
    # 5주차 제외 규칙: QA 계정 제외 · 중복 이벤트 제거
    con.execute("""
        CREATE TABLE events AS
        SELECT event_id, event_datetime, customer_id, session_id, event_name, platform, traffic_source
          FROM (SELECT *,
                       ROW_NUMBER() OVER (PARTITION BY session_id, event_datetime, event_name
                                          ORDER BY event_id) AS dup
                  FROM app_events
                 WHERE customer_id NOT LIKE 'QA%')
         WHERE dup = 1
    """)
    # 세션별로 묶는 집계가 빨라지도록 session_id에 인덱스를 붙임 (없으면 첫 실행이 몇 분 걸릴 수 있음)
    con.execute("CREATE INDEX idx_events_session ON events(session_id)")
    return con

# ------------------------------------------------------------
# 1. 데이터 준비 — 정제된 events 테이블을 SQL로 집계
# ------------------------------------------------------------
@st.cache_data
def query(sql):                            # SQL을 실행해 표로 돌려줌
    return pd.read_sql(sql, get_db())

# 주 × 플랫폼 × 유입 경로별 세션 퍼널
SQL_WEEKLY_FUNNEL = """
WITH s AS (                                 -- 세션의 첫 이벤트로 플랫폼 · 유입 경로 · 주 정하기
    SELECT session_id, platform, traffic_source,
           DATE(MIN(event_datetime), 'weekday 0', '-6 days') AS 주시작일
      FROM events
     GROUP BY session_id
)
SELECT s.주시작일,
       s.platform       AS 플랫폼,
       s.traffic_source AS 유입경로,
       COUNT(DISTINCT e.session_id)                                                       AS 세션수,
       COUNT(DISTINCT CASE WHEN e.event_name = 'view_restaurant' THEN e.session_id END)   AS 조회세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'add_to_cart'     THEN e.session_id END)   AS 장바구니세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'begin_checkout'  THEN e.session_id END)   AS 결제시작세션,
       COUNT(DISTINCT CASE WHEN e.event_name = 'order_complete'  THEN e.session_id END)   AS 주문세션,
       SUM(CASE WHEN e.event_name = 'payment_fail' THEN 1 ELSE 0 END)                     AS 결제실패
  FROM events e
  JOIN s ON e.session_id = s.session_id
 WHERE s.주시작일 < '2026-06-29'            -- 이틀치뿐인 마지막 주 제외
 GROUP BY 1, 2, 3
 ORDER BY 1, 2, 3
"""

@st.cache_data
def load_data():
    data = query(SQL_WEEKLY_FUNNEL)
    data["주시작일"] = pd.to_datetime(data["주시작일"]).dt.date
    return data

df = load_data()                           # 주 × 플랫폼 × 유입 경로별 세션 퍼널

AI_NOTES = {
    "전체": "전체 주문 전환율은 14.5%이며 가장 낮은 단계 전환율은 조회세션에서 장바구니세션으로 이어지는 41.4% 구간이다. 다른 집단과 비교해 전반적인 지표의 기준이 된다. 특정 원인은 단정할 수 없으나 사용자들의 상품 탐색 단계에서 이탈이 집중되는 것으로 보인다.",
    "Android": "안드로이드의 주문 전환율은 14.3%이며 가장 낮은 단계 전환율은 조회세션에서 장바구니세션으로 이어지는 41.8% 구간이다. 전체 평균과 유사한 수준을 보인다. 2026-04-20 주부터 2026-06-01 주까지 결제 전환율 하락세가 이어졌으며 결제 과정에 문제가 있었던 것으로 보인다.",
    "iOS": "아이오스의 주문 전환율은 14.8%이며 가장 낮은 단계 전환율은 조회세션에서 장바구니세션으로 이어지는 40.8% 구간이다. 안드로이드에 비해 주문 전환율이 소폭 높다. 2026-05-04 주와 2026-06-15 주 등에 일시적 하락이 나타났으며 환경적 요인의 영향일 것으로 보인다.",
    "organic": "오가닉의 주문 전환율은 16.0%이며 가장 낮은 단계 전환율은 조회세션에서 장바구니세션으로 이어지는 41.4% 구간이다. 전체 집단 대비 세션 수가 가장 많고 전환율도 안정적이다. 자연 유입 사용자의 구매 의도가 비교적 높았던 것으로 보인다.",
    "paid_ad": "유료 광고의 주문 전환율은 26.3%로 가장 높으며 가장 낮은 단계 전환율은 조회세션에서 장바구니세션으로 이어지는 53.7% 구간이다. 다른 유입경로에 비해 모든 퍼널 단계의 전환율이 월등히 높다. 타겟팅된 광고를 통해 구매 전환 가능성이 높은 사용자가 유입된 것으로 보인다.",
    "push": "푸시 유입의 주문 전환율은 3.2%이며 가장 낮은 단계 전환율은 세션수에서 조회세션으로 이어지는 28.4% 구간이다. 다른 경로들과 달리 첫 단계인 조회 구간에서 가장 큰 이탈이 발생한다. 푸시 메시지를 통해 유입된 사용자의 관여도가 상대적으로 낮았던 것으로 보인다.",
    "referral": "레퍼럴의 주문 전환율은 0.0%이며 가장 낮은 단계 전환율은 조회세션에서 장바구니세션으로 이어지는 23.2% 구간이다. 세션 수가 121개로 500개 미만이며 최종 주문이 발생하지 않았다. 표본 규모가 매우 작아 추가적인 데이터 확인이 필요하다."
}

AI_SOURCE = "bot: Gemini가 미리 만든 해설 · 전체 기간 기준"
# ------------------------------------------------------------
# 사이드바 필터
# ------------------------------------------------------------
st.sidebar.header("필터")

# 기간 필터
weeks = sorted(df["주시작일"].unique())
selected_period = st.sidebar.select_slider(
    "기간",
    options=weeks,
    value=(weeks[0], weeks[-1])
)

# 평소 범위 기준 기간 추가
baseline_end_idx = min(25, len(weeks) - 1)
selected_baseline_period = st.sidebar.select_slider(
    "평소 범위 기준 기간",
    options=weeks,
    value=(weeks[0], weeks[baseline_end_idx]),
    help="문제가 없던 기간을 고르세요. 이 기간의 주별 값 범위를 '평소 범위'로 씁니다."
)

# 플랫폼 필터
platforms = sorted(df["플랫폼"].unique())
selected_platforms = st.sidebar.multiselect(
    "플랫폼",
    options=platforms,
    default=platforms
)

# 유입 경로 필터
traffic_sources = sorted(df["유입경로"].unique())
selected_traffic_sources = st.sidebar.multiselect(
    "유입 경로",
    options=traffic_sources,
    default=traffic_sources
)

# 집단 조건만 적용한 데이터 g
g = df[
    (df["플랫폼"].isin(selected_platforms)) &
    (df["유입경로"].isin(selected_traffic_sources))
]

# 기존 f는 g에 기간 조건을 더해 만듦
f = g[
    (g["주시작일"] >= selected_period[0]) &
    (g["주시작일"] <= selected_period[1])
]

# ------------------------------------------------------------
# 사이드바 데이터 다운로드 버튼 영역 (BOM 추가)
# ------------------------------------------------------------
st.sidebar.html("<hr style='margin: 20px 0; border: none; border-top: 1px solid #ddd;'>")
st.sidebar.subheader("데이터 내려받기")

col_dl1, col_dl2 = st.sidebar.columns(2)

csv_total = df.to_csv(index=False, encoding="utf-8-sig")
col_dl1.download_button(
    label="전체 다운로드",
    data=csv_total.encode("utf-8-sig"),
    file_name="전체_데이터.csv",
    mime="text/csv"
)

csv_filtered = f.to_csv(index=False, encoding="utf-8-sig")
col_dl2.download_button(
    label="부분 다운로드",
    data=csv_filtered.encode("utf-8-sig"),
    file_name="필터적용_데이터.csv",
    mime="text/csv"
)

if f.empty:
    st.warning("선택한 조건에 해당하는 데이터가 없습니다. 필터를 바꿔 주세요.")
    st.stop()

# ------------------------------------------------------------
# 2. KPI 카드
# ------------------------------------------------------------
def rate(a, b):
    return a / b * 100 if b else 0

t = f[["세션수", "결제시작세션", "주문세션"]].sum()
c1, c2, c3 = st.columns(3)
c1.metric("세션 수", f"{t['세션수']:,}개")
c2.metric("주문 전환율 (방문 → 주문)", f"{rate(t['주문세션'], t['세션수']):.1f}%")
c3.metric("결제 전환율 (결제 시작 → 주문)", f"{rate(t['주문세션'], t['결제시작세션']):.1f}%")

# ------------------------------------------------------------
# 규칙 기반 설명 문장 (st.info)
# ------------------------------------------------------------
def generate_rule_explanation(f_data, g_data, selected_per, baseline_per):
    # 선택 기간 주 목록 추출
    f_weeks = sorted(f_data["주시작일"].unique())
    if len(f_weeks) < 4:
        return "비교하려면 선택 기간을 4주 이상 골라 주세요.", "비교하려면 선택 기간을 4주 이상 골라 주세요."

    # 마지막 4주 기간 문자열 (예: "2026-05-04 주부터 4주")
    last_4_weeks = f_weeks[-4:]
    period_str = f"{last_4_weeks[0]} 주부터 4주"

    # 마지막 4주 합계 데이터
    f_last4 = f_data[f_data["주시작일"].isin(last_4_weeks)][["세션수", "결제시작세션", "주문세션"]].sum()
    cur_order_rate = rate(f_last4["주문세션"], f_last4["세션수"])
    cur_checkout_rate = rate(f_last4["주문세션"], f_last4["결제시작세션"])

    # 평소 범위 기준 기간 데이터 (g 데이터 기준)
    g_base = g_data[(g_data["주시작일"] >= baseline_per[0]) & (g_data["주시작일"] <= baseline_per[1])]
    
    # 주별로 집계 후 분모가 0인 주 제외
    weekly_base = g_base.groupby("주시작일")[["세션수", "결제시작세션", "주문세션"]].sum().reset_index()
    
    weekly_order_rates = []
    weekly_checkout_rates = []
    for _, row in weekly_base.iterrows():
        if row["세션수"] > 0:
            weekly_order_rates.append(row["주문세션"] / row["세션수"] * 100)
        if row["결제시작세션"] > 0:
            weekly_checkout_rates.append(row["주문세션"] / row["결제시작세션"] * 100)

    if len(weekly_order_rates) < 4 or len(weekly_checkout_rates) < 4:
        msg = "기준 기간을 이 집단의 데이터가 있는 시기로 옮겨 주세요."
        return msg, msg

    ord_min, ord_max = min(weekly_order_rates), max(weekly_order_rates)
    chk_min, chk_max = min(weekly_checkout_rates), max(weekly_checkout_rates)

    # 주문 전환율 문장 생성
    if cur_order_rate < ord_min:
        diff = ord_min - cur_order_rate
        msg_order = f"주문 전환율({cur_order_rate:.1f}%)은 {period_str} 동안 평소 범위({ord_min:.1f}% ~ {ord_max:.1f}%)보다 {diff:.1f}%p 낮습니다."
    elif cur_order_rate > ord_max:
        diff = cur_order_rate - ord_max
        msg_order = f"주문 전환율({cur_order_rate:.1f}%)은 {period_str} 동안 평소 범위({ord_min:.1f}% ~ {ord_max:.1f}%)보다 {diff:.1f}%p 높습니다."
    else:
        msg_order = f"주문 전환율({cur_order_rate:.1f}%)은 {period_str} 동안 평소 범위({ord_min:.1f}% ~ {ord_max:.1f}%) 안에 있습니다."

    # 결제 전환율 문장 생성
    if cur_checkout_rate < chk_min:
        diff = chk_min - cur_checkout_rate
        msg_checkout = f"결제 전환율({cur_checkout_rate:.1f}%)은 {period_str} 동안 평소 범위({chk_min:.1f}% ~ {chk_max:.1f}%)보다 {diff:.1f}%p 낮습니다."
    elif cur_checkout_rate > chk_max:
        diff = cur_checkout_rate - chk_max
        msg_checkout = f"결제 전환율({cur_checkout_rate:.1f}%)은 {period_str} 동안 평소 범위({chk_min:.1f}% ~ {chk_max:.1f}%)보다 {diff:.1f}%p 높습니다."
    else:
        msg_checkout = f"결제 전환율({cur_checkout_rate:.1f}%)은 {period_str} 동안 평소 범위({chk_min:.1f}% ~ {chk_max:.1f}%) 안에 있습니다."

    return msg_checkout, msg_order

# ------------------------------------------------------------
# 규칙 기반 설명 및 전체 AI 해설 영역 (단일 컨테이너)
# ------------------------------------------------------------
info_checkout, info_order = generate_rule_explanation(f, g, selected_period, selected_baseline_period)

with st.container(border=True):
    st.markdown("**📏 지금 숫자 읽기**")
    st.markdown(f"- 💳 **결제 전환율 분석**: {info_checkout}")
    st.markdown(f"- 📈 **주문 전환율 분석**: {info_order}")
    st.caption(f"📏 자동 계산 · 평소 범위 기준 기간 {selected_baseline_period[0]} ~ {selected_baseline_period[1]} (주별 값)")
    
    with st.expander("🤖 AI 해설 · 전체", expanded=False):
        st.write(AI_NOTES.get("전체", "이 집단의 해설은 아직 없습니다."))
    st.caption(AI_SOURCE)

st.divider()

# ------------------------------------------------------------
# 3. 차트
# ------------------------------------------------------------
left, right = st.columns(2)

# 3-1. 주별 결제 전환율 (플랫폼별)
wp = f.groupby(["주시작일", "플랫폼"])[["결제시작세션", "주문세션"]].sum().reset_index()
wp["결제전환율"] = (wp["주문세션"] / wp["결제시작세션"] * 100).round(1)
fig1 = px.line(wp, x="주시작일", y="결제전환율", color="플랫폼", markers=True,
               title="주별 결제 전환율 (플랫폼별)")
fig1.update_layout(yaxis_title="결제 전환율 (%)", xaxis_title="")
left.plotly_chart(fig1, width="stretch")

# 3-2. 세션 퍼널
steps = {"1.방문": "세션수", "2.식당조회": "조회세션", "3.장바구니": "장바구니세션",
         "4.결제시작": "결제시작세션", "5.주문완료": "주문세션"}
fun = pd.DataFrame({"단계": list(steps), "세션수": [f[c].sum() for c in steps.values()]})
fig2 = px.funnel(fun, x="세션수", y="단계", title="세션 퍼널")
right.plotly_chart(fig2, width="stretch")

# 3-3. 유입 경로별 주문 전환율
ws = f.groupby("유입경로")[["세션수", "주문세션"]].sum().reset_index()
ws["주문전환율"] = (ws["주문세션"] / ws["세션수"] * 100).round(1)
ws = ws.sort_values("주문전환율")
fig3 = px.bar(ws, x="주문전환율", y="유입경로", orientation="h", text_auto=".1f",
              hover_data=["세션수"], title="유입 경로별 주문 전환율")
if not ws.empty and ws["주문전환율"].max() > 0:
    fig3.update_xaxes(range=[0, ws["주문전환율"].max() * 1.2])
fig3.update_layout(xaxis_title="주문 전환율 (%)", yaxis_title="")
st.plotly_chart(fig3, width="stretch")

st.divider()

# ------------------------------------------------------------
# 4. 집단 비교 영역
# ------------------------------------------------------------
st.subheader("집단 비교")
group_col_map = {"플랫폼": "플랫폼", "유입경로": "유입경로"}
selected_group = st.radio("비교 기준", ["플랫폼", "유입경로"], horizontal=True)
col_name = group_col_map[selected_group]

# 집단별 5단계 세션 수 집계
group_agg = f.groupby(col_name)[["세션수", "조회세션", "장바구니세션", "결제시작세션", "주문세션"]].sum().reset_index()

# 세션 수가 500개 미만인 집단 확인
low_session_groups = group_agg[group_agg["세션수"] < 500][col_name].tolist()
if low_session_groups:
    st.caption(f"⚠️ 세션 수가 500개 미만인 집단({', '.join(low_session_groups)})이 있어 값이 크게 흔들릴 수 있습니다.")

# 누적 전환율 퍼널용 데이터 변환 (첫 단계 대비 %)
funnel_records = []
for _, row in group_agg.iterrows():
    g_name = row[col_name]
    base_session = row["세션수"]
    stages = [
        ("1.방문", row["세션수"], base_session),
        ("2.식당조회", row["조회세션"], base_session),
        ("3.장바구니", row["장바구니세션"], base_session),
        ("4.결제시작", row["결제시작세션"], base_session),
        ("5.주문완료", row["주문세션"], base_session),
    ]
    for stage_name, val, base in stages:
        pct = (val / base * 100) if base else 0
        funnel_records.append({
            col_name: g_name,
            "단계": stage_name,
            "누적전환율": round(pct, 1),
            "세션수": val
        })
df_funnel = pd.DataFrame(funnel_records)

# 단계 전환율(직전 단계 대비 %) 막대용 데이터 변환
step_conversion_records = []
for _, row in group_agg.iterrows():
    g_name = row[col_name]
    s1, s2, s3, s4, s5 = row["세션수"], row["조회세션"], row["장바구니세션"], row["결제시작세션"], row["주문세션"]

    transitions = [
        ("방문 → 조회", s2, s1),
        ("조회 → 장바구니", s3, s2),
        ("장바구니 → 결제시작", s4, s3),
        ("결제시작 → 주문완료", s5, s4)
    ]

    for t_name, current_val, prev_val in transitions:
        step_rate = (current_val / prev_val * 100) if prev_val else 0
        step_conversion_records.append({
            col_name: g_name,
            "단계전환": t_name,
            "단계전환율": round(step_rate, 1),
            "기준세션수": prev_val
        })
df_step = pd.DataFrame(step_conversion_records)

comp_left, comp_right = st.columns(2)

# 왼쪽: 누적 전환율 퍼널
fig_comp_funnel = px.funnel(
    df_funnel,
    x="누적전환율",
    y="단계",
    color=col_name,
    title=f"집단별 누적 전환율 퍼널 ({selected_group} 기준)",
    hover_data=["세션수"]
)
comp_left.plotly_chart(fig_comp_funnel, width="stretch")

# 오른쪽: 단계 전환율 막대 (barmode="group")
fig_comp_bar = px.bar(
    df_step,
    x="단계전환",
    y="단계전환율",
    color=col_name,
    barmode="group",
    text_auto=".1f",
    title=f"집단별 단계 전환율 ({selected_group} 기준)",
    hover_data=["기준세션수"]
)
fig_comp_bar.update_layout(yaxis_title="단계 전환율 (%)", xaxis_title="")
comp_right.plotly_chart(fig_comp_bar, width="stretch")

st.divider()

# ------------------------------------------------------------
# 5. 드릴다운 영역: 언제부터, 무엇 때문일까
# ------------------------------------------------------------
st.subheader("드릴다운: 언제부터, 무엇 때문일까")

dd_col1, dd_col2 = st.columns(2)

available_groups = sorted(f[col_name].unique())
selected_sub_group = dd_col1.selectbox("자세히 볼 집단", available_groups)

step_options = [
    "방문 → 식당조회",
    "식당조회 → 장바구니",
    "장바구니 → 결제시작",
    "결제시작 → 주문"
]
selected_step_option = dd_col2.selectbox("단계", step_options)

# 단계 매핑 설정 (현재 단계, 직전 단계 컬럼명)
step_mapping = {
    "방문 → 식당조회": ("조회세션", "세션수"),
    "식당조회 → 장바구니": ("장바구니세션", "조회세션"),
    "장바구니 → 결제시작": ("결제시작세션", "장바구니세션"),
    "결제시작 → 주문": ("주문세션", "결제시작세션")
}
curr_col, prev_col = step_mapping[selected_step_option]

# 다른 축 결정 (플랫폼이면 유입경로, 유입경로면 플랫폼)
other_col = "유입경로" if col_name == "플랫폼" else "플랫폼"

# 차트 ① 데이터 준비
df_drill = f[f[col_name] == selected_sub_group].groupby(["주시작일", other_col])[[curr_col, prev_col]].sum().reset_index()
df_drill["전환율"] = df_drill.apply(
    lambda row: (row[curr_col] / row[prev_col] * 100) if row[prev_col] > 0 else None, axis=1
)

fig_drill1 = px.line(
    df_drill,
    x="주시작일",
    y="전환율",
    color=other_col,
    markers=True,
    title=f"① {selected_sub_group}의 주별 {selected_step_option} 전환율 — {other_col}별로 쪼개 보기"
)
fig_drill1.update_layout(yaxis_title="전환율 (%)", xaxis_title="")
st.plotly_chart(fig_drill1, width="stretch")
st.caption("모든 갈래가 같은 시점에 함께 움직였다면, 그 축은 원인이 아닙니다.")

# 차트 ② 데이터 준비 (결제실패 주별 집계: 고른 집단 vs 그 외)
df_fail_base = f.copy()
df_fail_base["그룹분류"] = df_fail_base[col_name].apply(
    lambda x: selected_sub_group if x == selected_sub_group else "그 외"
)

df_fail = df_fail_base.groupby(["주시작일", "그룹분류"])["결제실패"].sum().reset_index()

color_map = {selected_sub_group: "#d62728", "그 외": "#7f7f7f"}

fig_drill2 = px.bar(
    df_fail,
    x="주시작일",
    y="결제실패",
    color="그룹분류",
    barmode="stack",
    color_discrete_map=color_map,
    title=f"② 주별 결제 실패 건수 ({selected_sub_group} vs 그 외)"
)
fig_drill2.update_layout(yaxis_title="결제 실패 건수", xaxis_title="")
st.plotly_chart(fig_drill2, width="stretch")
st.caption("문제가 생긴 시점과 함께 움직였다면 원인 후보입니다. 함께 움직였다고 원인이 확정되지는 않습니다.")

# 2. 드릴다운 차트 아래에 st.expander 추가
target = selected_sub_group
note_text = AI_NOTES.get(target, "이 집단의 해설은 아직 없습니다.")
with st.expander(f"🤖 AI 해설 · {target}", expanded=False):
    st.write(note_text)
st.caption(AI_SOURCE)