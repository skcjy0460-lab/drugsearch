import hashlib
import hmac
import html
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st


BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "data" / "review_assist.db"
SEED_PATH = BASE_DIR / "seed_data.json"
NOW = lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")

st.set_page_config(
    page_title="ClaimLens | 약제 심사 지원",
    page_icon="CL",
    layout="wide",
    initial_sidebar_state="expanded",
)


def secret_value(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.environ.get(name, default))


def connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database() -> None:
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drugs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                ingredient_display TEXT NOT NULL,
                reimbursement_code TEXT,
                manufacturer TEXT,
                category_code TEXT,
                searchable TEXT NOT NULL,
                payload TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS search_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                drug_id TEXT NOT NULL,
                drug_name TEXT NOT NULL,
                query TEXT NOT NULL,
                occurred_at TEXT NOT NULL
            )
            """
        )
        count = conn.execute("SELECT COUNT(*) AS count FROM drugs").fetchone()["count"]
        if count == 0:
            records = json.loads(SEED_PATH.read_text(encoding="utf-8"))
            upsert_drugs(conn, records)


def searchable_text(drug: dict[str, Any]) -> str:
    fields = [
        drug.get("name", ""),
        drug.get("ingredient_display", ""),
        drug.get("reimbursement_code", ""),
        drug.get("manufacturer", ""),
        " ".join(drug.get("ingredients", [])),
    ]
    return " ".join(fields).lower()


def validate_drug(drug: dict[str, Any]) -> list[str]:
    required = ["id", "name", "ingredient_display"]
    errors = [f"`{key}` 값이 없습니다." for key in required if not str(drug.get(key, "")).strip()]
    for key in ["efficacy", "dosage_official", "cautions", "contraindications", "sources"]:
        if key in drug and not isinstance(drug[key], list):
            errors.append(f"`{key}`는 목록 형식이어야 합니다.")
    return errors


def upsert_drugs(conn: sqlite3.Connection, records: list[dict[str, Any]]) -> int:
    saved = 0
    for drug in records:
        if validate_drug(drug):
            continue
        conn.execute(
            """
            INSERT INTO drugs (
                id, name, ingredient_display, reimbursement_code, manufacturer,
                category_code, searchable, payload, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                ingredient_display=excluded.ingredient_display,
                reimbursement_code=excluded.reimbursement_code,
                manufacturer=excluded.manufacturer,
                category_code=excluded.category_code,
                searchable=excluded.searchable,
                payload=excluded.payload,
                updated_at=excluded.updated_at
            """,
            (
                drug["id"],
                drug["name"],
                drug["ingredient_display"],
                drug.get("reimbursement_code", ""),
                drug.get("manufacturer", ""),
                drug.get("category_code", ""),
                searchable_text(drug),
                json.dumps(drug, ensure_ascii=False),
                NOW(),
            ),
        )
        saved += 1
    return saved


def find_drugs(query: str) -> list[dict[str, Any]]:
    text = query.strip().lower()
    with connection() as conn:
        if not text:
            rows = conn.execute("SELECT payload FROM drugs ORDER BY name LIMIT 12").fetchall()
        else:
            rows = conn.execute(
                "SELECT payload FROM drugs WHERE searchable LIKE ? ORDER BY name LIMIT 20",
                (f"%{text}%",),
            ).fetchall()
    return [json.loads(row["payload"]) for row in rows]


def load_drug(drug_id: str) -> dict[str, Any] | None:
    with connection() as conn:
        row = conn.execute("SELECT payload FROM drugs WHERE id = ?", (drug_id,)).fetchone()
    return json.loads(row["payload"]) if row else None


def log_selection(drug: dict[str, Any], query: str) -> None:
    marker = f"{drug['id']}::{query.strip().lower()}"
    if st.session_state.get("last_logged") == marker:
        return
    with connection() as conn:
        conn.execute(
            "INSERT INTO search_events (drug_id, drug_name, query, occurred_at) VALUES (?, ?, ?, ?)",
            (drug["id"], drug["name"], "", NOW()),
        )
    st.session_state.last_logged = marker


def ranking(hours: int | None) -> pd.DataFrame:
    sql = """
        SELECT drug_name AS 약제명, COUNT(*) AS 검색수, MAX(occurred_at) AS 최근검색
        FROM search_events
    """
    args: tuple[str, ...] = ()
    if hours is not None:
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        sql += " WHERE occurred_at >= ?"
        args = (since,)
    sql += " GROUP BY drug_id, drug_name ORDER BY 검색수 DESC, 최근검색 DESC LIMIT 10"
    with connection() as conn:
        return pd.read_sql_query(sql, conn, params=args)


def css() -> None:
    st.markdown(
        """
        <style>
          :root { --green:#087f73; --ink:#142824; --muted:#61716d; --line:#e4eae7; --cream:#f6f8f7; }
          .stApp { background: var(--cream); color: var(--ink); }
          [data-testid="stSidebar"] { background: #102d29; }
          [data-testid="stSidebar"] * { color: #f4f8f7; }
          .brand { color:#f7fbfa; font-size:1.55rem; font-weight:750; letter-spacing:-.04em; padding: .65rem 0 .1rem; }
          .brand span { color:#57d3b5; }
          .caption-light { color:#a5c3bc; font-size:.84rem; padding-bottom:1.4rem; }
          .hero { background: linear-gradient(112deg,#102e2a,#176359); border-radius:20px; color:white; padding:1.55rem 1.8rem; margin-bottom:1rem;}
          .hero h1 {font-size:1.8rem; margin:0 0 .35rem; letter-spacing:-.055em;}
          .hero p {color:#d6e9e5; margin:0; font-size:.94rem;}
          .drug-header {background:white; border:1px solid var(--line); border-radius:18px; padding:1.45rem 1.5rem; margin-top:.5rem;}
          .drug-header h2 {font-size:1.8rem; letter-spacing:-.06em; margin:.18rem 0 .45rem;}
          .pill {display:inline-block; border-radius:999px; padding:.28rem .62rem; margin:0 .35rem .35rem 0; font-size:.78rem; font-weight:650; background:#e4f3ef; color:#086a61;}
          .pill.review {background:#fff1d7; color:#8b5800;}
          .meta {color:var(--muted); font-size:.91rem;}
          .nav-grid {display:flex; gap:.42rem; flex-wrap:wrap; margin:1rem 0 .4rem;}
          .nav-grid a {text-decoration:none!important; border:1px solid #cee2dd; color:#075e56!important; background:white; border-radius:10px; padding:.55rem .72rem; font-weight:650; font-size:.88rem;}
          .nav-grid a:hover {background:#e9f5f2;}
          .report {background:white; border:1px solid var(--line); border-radius:17px; padding:1.25rem 1.4rem; margin:.9rem 0;}
          .report h3 {font-size:1.15rem; letter-spacing:-.04em; margin:0 0 .8rem;}
          .eyebrow {font-size:.74rem; text-transform:uppercase; color:#087f73; letter-spacing:.1em; font-weight:700; margin-bottom:.25rem;}
          .notice {background:#edf6f3; border-left:4px solid #087f73; border-radius:8px; padding:.85rem 1rem; color:#274b45; font-size:.9rem;}
          .warning {background:#fff6e8; border-left:4px solid #c4881d; border-radius:8px; padding:.85rem 1rem; color:#654610; font-size:.9rem;}
          .source {border-top:1px solid var(--line); padding:.7rem 0; font-size:.9rem;}
          .source a {color:#087f73!important; font-weight:600;}
          .stat-card {background:white; border:1px solid var(--line); border-radius:14px; padding:.85rem;}
          div[data-testid="stButton"] button {border-radius:10px; border-color:#d6e5e1; font-weight:600;}
          div[data-testid="stButton"] button[kind="primary"] {background:#087f73;}
          h1,h2,h3 {color:var(--ink);}
        </style>
        """,
        unsafe_allow_html=True,
    )


def esc(value: Any) -> str:
    return html.escape(str(value or ""))


def render_list(items: list[str]) -> None:
    if items:
        for item in items:
            st.markdown(f"- {item}")
    else:
        st.info("등록된 자료가 없습니다. 관리자 검증 후 업데이트가 필요합니다.")


@contextmanager
def report_section(anchor: str, label: str, subtitle: str = ""):
    st.markdown(f'<span id="{anchor}"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(
            f'<div class="eyebrow">{esc(subtitle)}</div><h3>{esc(label)}</h3>',
            unsafe_allow_html=True,
        )
        yield


def candidate_matches(drug: dict[str, Any], clinical_note: str) -> list[dict[str, str]]:
    note = clinical_note.lower()
    candidates = drug.get("diagnosis_candidates", [])
    matched = [
        item for item in candidates
        if any(term.lower() in note for term in item.get("match_terms", []))
    ]
    return matched or candidates


def ai_available() -> bool:
    return bool(secret_value("OPENAI_API_KEY"))


def call_ai_assistant(drug: dict[str, Any], clinical_note: str, task: str) -> str:
    api_key = secret_value("OPENAI_API_KEY")
    model = secret_value("OPENAI_MODEL", "gpt-4.1-mini")
    if not api_key:
        return "OPENAI_API_KEY가 설정되지 않아 규칙 기반 보조 결과만 표시합니다."
    context = {
        "약제": drug.get("name"),
        "성분": drug.get("ingredient_display"),
        "효능": drug.get("efficacy", []),
        "허가용법참고": drug.get("dosage_official", []),
        "상병후보": drug.get("diagnosis_candidates", []),
        "사용자입력": clinical_note,
    }
    prompt = (
        "당신은 병원 청구심사 담당자의 검토 보조자입니다. 진단하거나 급여 인정을 확정하지 마십시오. "
        "제공된 자료 안에서만 답하고, 자료에 없는 사항은 '공식 원문 확인 필요'라고 표시하십시오. "
        f"작업: {task}. 출력은 한국어로 '검토 요약', '확인할 근거', '주의사항' 세 부분으로 간결하게 작성하십시오.\n"
        + json.dumps(context, ensure_ascii=False)
    )
    try:
        response = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": prompt},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("output_text"):
            return data["output_text"]
        parts = []
        for output in data.get("output", []):
            for content in output.get("content", []):
                if content.get("text"):
                    parts.append(content["text"])
        return "\n".join(parts) or "AI 응답을 해석하지 못했습니다."
    except requests.RequestException as exc:
        return f"AI 연결에 실패했습니다. 규칙 기반 자료를 우선 확인하십시오. ({exc.__class__.__name__})"


def source_links(drug: dict[str, Any]) -> None:
    for source in drug.get("sources", []):
        url = esc(source.get("url"))
        st.markdown(
            f'<div class="source"><b>{esc(source.get("section"))}</b> · {esc(source.get("publisher"))} '
            f'· <a href="{url}" target="_blank">{esc(source.get("title"))}</a>'
            f' <span class="meta">(확인일 {esc(source.get("checked_on"))})</span></div>',
            unsafe_allow_html=True,
        )


def render_drug_detail(drug: dict[str, Any]) -> None:
    status_class = "review" if "검토" in drug.get("status", "") or "예시" in drug.get("status", "") else ""
    st.markdown(
        f"""
        <div class="drug-header">
          <span class="pill {status_class}">{esc(drug.get("status"))}</span>
          <span class="pill">{esc(drug.get("professional"))}</span>
          <h2>{esc(drug.get("name"))} <span class="meta">[{esc(drug.get("ingredient_display"))}]</span></h2>
          <p class="meta">제조사 {esc(drug.get("manufacturer"))} &nbsp;|&nbsp; 급여코드 {esc(drug.get("reimbursement_code"))}
          &nbsp;|&nbsp; 표준코드 {esc(drug.get("standard_code", "-"))} &nbsp;|&nbsp; 투여경로 {esc(drug.get("route"))}</p>
          <p class="meta">상한금액 {esc(drug.get("upper_price", "공식 목록 확인 필요"))}
          &nbsp;|&nbsp; 적용일 {esc(drug.get("price_effective_date", "-"))}
          &nbsp;|&nbsp; 자료 확인일 {esc(drug.get("verified_on"))}</p>
          <p>{esc(drug.get("summary"))}</p>
        </div>
        <div class="nav-grid">
          <a href="#dosage">용법용량 [AI]</a><a href="#efficacy">효능효과</a>
          <a href="#review">심사참고자료</a><a href="#same">동일성분약제</a>
          <a href="#multiple">배수처방</a><a href="#caution">주의사항</a><a href="#contra">금기사항</a>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="warning">이 서비스는 청구심사 검토 보조용입니다. 급여 인정, 진단, 처방 및 DUR 판단은 '
        "최신 고시·허가사항·환자 정보·공식 시스템 결과와 전문가 검토를 기준으로 확정하십시오.</div>",
        unsafe_allow_html=True,
    )

    with report_section("classification", "약효분류코드", "DRUG CLASSIFICATION"):
        left, right = st.columns(2)
        left.metric("분류코드", drug.get("category_code", "-"))
        right.metric("분류명", drug.get("category_name", "-"))

    render_diagnosis_section(drug)

    with report_section("dosage", "용법용량", "AI REVIEW ASSIST"):
        st.markdown("**허가·복약자료 기반 확인사항**")
        render_list(drug.get("dosage_official", []))
        st.markdown("**AI 보조 체크리스트**")
        render_list(drug.get("dosage_ai_checklist", []))
        if ai_available():
            if st.button("용법용량 AI 검토 생성", key=f"dose-ai-{drug['id']}"):
                with st.spinner("검토 요약을 생성하고 있습니다."):
                    st.info(call_ai_assistant(drug, "", "투여 전 확인 체크리스트 작성"))
        else:
            st.caption("관리자가 API 키를 설정하면 입력 맥락에 따른 AI 보조 검토를 추가로 생성할 수 있습니다.")

    with report_section("efficacy", "효능효과", "INDICATIONS"):
        render_list(drug.get("efficacy", []))

    with report_section("review", "심사참고자료", "CLAIM REVIEW"):
        if not drug.get("review_references"):
            st.info("등록된 심사참고자료가 없습니다. 공식 고시 연계 후 표시됩니다.")
        for reference in drug.get("review_references", []):
            st.markdown(f"**{reference.get('title')}**  \n`{reference.get('level')}` {reference.get('body')}")

    with report_section("same", "동일성분약제", "SAME INGREDIENT"):
        for same in drug.get("same_ingredient", []):
            st.markdown(f"**{same.get('name')}**  \n코드: `{same.get('code')}`  \n{same.get('note')}")
        if not drug.get("same_ingredient"):
            st.info("공식 데이터 연계 후 동일성분 제품이 표시됩니다.")

    with report_section("multiple", "배수처방", "MULTIPLE PRESCRIPTION REVIEW"):
        render_list(drug.get("multiple_prescription", []))

    with report_section("caution", "주의사항", "CAUTIONS"):
        render_list(drug.get("cautions", []))

    with report_section("contra", "금기사항", "CONTRAINDICATIONS"):
        render_list(drug.get("contraindications", []))

    with report_section("source", "자료 출처 및 검증 상태", "EVIDENCE"):
        source_links(drug)
        st.caption("운영 시 허가사항·급여목록·고시 개정일을 주기적으로 동기화하고 변경 이력을 보존해야 합니다.")


def render_diagnosis_section(drug: dict[str, Any]) -> None:
    with report_section("diagnosis", "상병코드 조회 기능", "AI CODING ASSIST"):
        st.markdown(
            '<div class="notice">상병코드는 의무기록에 기재된 검사 목적·증상·확정 진단에 근거해 선택해야 합니다. '
            "약제명만으로 상병을 자동 확정하지 않습니다.</div>",
            unsafe_allow_html=True,
        )
        note = st.text_area(
            "검사 목적 또는 진료기록 요약",
            placeholder="예: 건강검진 중 대장암 선별 목적의 대장내시경 예정",
            key=f"clinical-{drug['id']}",
            height=78,
        )
        if st.button("상병 후보 검토", key=f"dx-{drug['id']}", type="primary"):
            matches = candidate_matches(drug, note)
            if not matches:
                st.info("등록된 후보가 없습니다. 공식 KCD 기준과 진료기록을 확인하십시오.")
            for item in matches:
                st.markdown(
                    f"**`{item.get('code')}` {item.get('name')}**  \n"
                    f"{item.get('reason')}  \n:orange[확인:] {item.get('warning')}"
                )
            if ai_available() and note.strip():
                with st.spinner("AI 보조 메모를 작성하고 있습니다."):
                    st.info(call_ai_assistant(drug, note, "입력 기록에 부합할 수 있는 상병 후보 검토 메모 작성"))


def search_page() -> None:
    st.markdown(
        '<div class="hero"><h1>약제 심사 지원 리포트</h1>'
        "<p>약품명, 성분명 또는 급여코드로 검색하고 공식 근거 확인이 필요한 항목까지 한 화면에서 검토합니다.</p></div>",
        unsafe_allow_html=True,
    )
    search_col, submit_col = st.columns([7, 1])
    query = search_col.text_input(
        "약제 검색",
        value=st.session_state.get("query", ""),
        placeholder="예: 씨엠쿨산, 폴리에틸렌글리콜3350, 급여코드",
        label_visibility="collapsed",
    )
    submit_col.button("검색", type="primary", use_container_width=True)
    st.session_state.query = query
    results = find_drugs(query) if query.strip() else []
    if query.strip():
        st.caption(f"검색 결과 {len(results)}건 · 상세 보기 선택 시 검색 순위에 반영됩니다.")
        if not results:
            st.info("일치하는 약제가 없습니다. 관리자 데이터 업로드 또는 공식 API 연계가 필요합니다.")
        for drug in results:
            c1, c2 = st.columns([5, 1])
            c1.markdown(
                f"**{drug['name']}** [{drug.get('ingredient_display', '')}]  \n"
                f"<span class='meta'>급여코드 {esc(drug.get('reimbursement_code'))} · {esc(drug.get('manufacturer'))}</span>",
                unsafe_allow_html=True,
            )
            if c2.button("상세 보기", key=f"open-{drug['id']}", use_container_width=True):
                st.session_state.selected_drug = drug["id"]
                log_selection(drug, query)
                st.rerun()
    selected_id = st.session_state.get("selected_drug")
    if selected_id:
        selected = load_drug(selected_id)
        if selected:
            render_drug_detail(selected)


def ranking_page() -> None:
    st.header("약제 검색 순위")
    st.caption("상세 보기를 선택한 검색 이벤트를 집계합니다. 환자식별정보는 저장하지 않습니다.")
    live, weekly, monthly = st.tabs(["실시간", "주간", "월간"])
    periods = [(live, 24, "최근 24시간"), (weekly, 24 * 7, "최근 7일"), (monthly, 24 * 30, "최근 30일")]
    for tab_item, hours, title in periods:
        with tab_item:
            data = ranking(hours)
            st.subheader(title)
            if data.empty:
                st.info("아직 집계할 검색 기록이 없습니다.")
            else:
                data.insert(0, "순위", range(1, len(data) + 1))
                st.dataframe(data, hide_index=True, use_container_width=True)
    st.markdown(
        '<div class="notice">운영 환경에서는 사용자별 접근권한, 감사로그 보존기간, 개인정보 비수집 정책을 '
        "내부 규정과 함께 확정하십시오.</div>",
        unsafe_allow_html=True,
    )


def matcher_page() -> None:
    st.header("상병 매칭 워크벤치")
    st.caption("먼저 약제를 선택한 뒤 검사 목적 또는 기록 문구를 입력해 검토 후보를 확인합니다.")
    drugs = find_drugs("")
    labels = {f"{drug['name']} [{drug['ingredient_display']}]": drug for drug in drugs}
    choice = st.selectbox("약제 선택", list(labels.keys()))
    render_diagnosis_section(labels[choice])


def admin_configured() -> bool:
    return bool(secret_value("ADMIN_PASSWORD"))


def administrator_page() -> None:
    st.header("관리자 데이터 관리")
    st.caption("약제 자료 적재는 인증된 관리자만 수행할 수 있습니다.")
    if not admin_configured():
        st.error("관리자 비밀번호가 설정되지 않았습니다. 배포 환경의 `ADMIN_PASSWORD`를 설정해야 업로드가 활성화됩니다.")
        return
    if not st.session_state.get("admin_authenticated", False):
        password = st.text_input("관리자 비밀번호", type="password")
        if st.button("관리자 로그인", type="primary"):
            if hmac.compare_digest(password, secret_value("ADMIN_PASSWORD")):
                st.session_state.admin_authenticated = True
                st.rerun()
            else:
                st.error("비밀번호가 일치하지 않습니다.")
        return
    st.success("관리자 인증 완료")
    if st.button("로그아웃"):
        st.session_state.admin_authenticated = False
        st.rerun()
    st.divider()
    st.subheader("검증 데이터 JSON 업로드")
    st.markdown(
        "업로드 파일은 `seed_data.json`과 동일한 배열 형식이어야 합니다. 실제 서비스 반영 전 "
        "허가사항, 급여목록, 고시 및 출처 확인일을 검수하십시오."
    )
    uploaded = st.file_uploader("약제 JSON 파일", type=["json"], accept_multiple_files=False)
    if uploaded and st.button("검증 후 데이터 반영", type="primary"):
        try:
            records = json.loads(uploaded.getvalue().decode("utf-8"))
            if not isinstance(records, list):
                raise ValueError("최상위 형식은 약제 목록 배열이어야 합니다.")
            errors: list[str] = []
            for index, record in enumerate(records, start=1):
                errors.extend([f"{index}번 항목: {error}" for error in validate_drug(record)])
            if errors:
                st.error("\n".join(errors))
            else:
                with connection() as conn:
                    count = upsert_drugs(conn, records)
                st.success(f"{count}개 약제 자료를 반영했습니다.")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            st.error(f"파일을 반영할 수 없습니다: {exc}")
    st.subheader("업로드용 템플릿")
    st.download_button(
        "현재 예시 JSON 내려받기",
        SEED_PATH.read_bytes(),
        file_name="drug_data_template.json",
        mime="application/json",
    )


def sidebar() -> str:
    st.sidebar.markdown('<div class="brand">Claim<span>Lens</span></div>', unsafe_allow_html=True)
    st.sidebar.markdown('<div class="caption-light">병원 청구심사 약제 지원센터</div>', unsafe_allow_html=True)
    page = st.sidebar.radio(
        "이동",
        ["약제 검색", "상병 매칭", "검색 순위", "관리자"],
        label_visibility="collapsed",
    )
    st.sidebar.divider()
    st.sidebar.markdown("**데이터 운영 원칙**")
    st.sidebar.caption("허가사항: MFDS/약학정보원 확인\n\n급여·심사: HIRA 기준 확인\n\n금기 점검: DUR 결과 우선")
    st.sidebar.markdown("`Beta / 내부 검토용`")
    return page


def main() -> None:
    initialize_database()
    css()
    page = sidebar()
    if page == "약제 검색":
        search_page()
    elif page == "상병 매칭":
        matcher_page()
    elif page == "검색 순위":
        ranking_page()
    else:
        administrator_page()


if __name__ == "__main__":
    main()
