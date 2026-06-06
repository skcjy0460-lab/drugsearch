"""
ClaimLens v2 - 약제 청구심사 지원 시스템
공공 API(HIRA·MFDS) 연동 + 적응증 기반 상병코드 자동 표시
"""

import hashlib
import hmac
import html
import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st

# ─────────────────────────────────────────────
# 기본 설정
# ─────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DB_PATH  = BASE_DIR / "data" / "review_assist.db"
SEED_PATH = BASE_DIR / "seed_data.json"
NOW = lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")

st.set_page_config(
    page_title="ClaimLens | 약제 심사 지원",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# 유틸리티
# ─────────────────────────────────────────────
def secret(name: str, default: str = "") -> str:
    try:
        v = st.secrets.get(name, "")
    except Exception:
        v = ""
    return str(v or os.environ.get(name, default))


def esc(v: Any) -> str:
    return html.escape(str(v or ""))


# ─────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────
def inject_css() -> None:
    st.markdown("""
<style>
:root {
  --g0:#051f1b; --g1:#087f73; --g2:#0aada0; --g3:#5ddfd3;
  --ink:#152622; --muted:#557068; --line:#dce8e5; --bg:#f4f7f6;
  --white:#ffffff;
  --amber:#c47d0e; --amber-bg:#fff8e8;
  --red:#c0392b; --red-bg:#fff0ee;
  --blue:#1a6fb5; --blue-bg:#eef4fc;
  --purple:#6b3fa0; --purple-bg:#f3eeff;
}

/* ── 전체 배경 ── */
.stApp { background: var(--bg); }

/* ── 사이드바 ── */
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #051f1b 0%, #0a3530 100%);
  border-right: 1px solid #0d4a43;
}
[data-testid="stSidebar"] * { color: #d4ece8 !important; }
[data-testid="stSidebar"] .stRadio label { color: #d4ece8 !important; }
[data-testid="stSidebar"] hr { border-color: #1a5a52 !important; }

/* ── 브랜드 로고 ── */
.brand-wrap { padding: 1rem 0 0.5rem; }
.brand-logo {
  font-size: 1.7rem; font-weight: 800; letter-spacing: -0.05em;
  color: #f0faf8;
}
.brand-logo span { color: #5ddfd3; }
.brand-sub { font-size: 0.78rem; color: #7ab5ac; margin-top: 0.1rem; }

/* ── 히어로 배너 ── */
.hero {
  background: linear-gradient(120deg, #051f1b 0%, #0e6b60 60%, #129689 100%);
  border-radius: 18px; color: white;
  padding: 1.8rem 2rem; margin-bottom: 1.2rem;
  border: 1px solid #0d5a52;
}
.hero h1 { font-size: 1.9rem; margin: 0 0 0.4rem; letter-spacing: -0.06em; font-weight: 800; }
.hero p  { color: #b8e0da; margin: 0; font-size: 0.93rem; }

/* ── 약제 헤더 카드 ── */
.drug-header {
  background: white; border: 1.5px solid var(--line);
  border-radius: 18px; padding: 1.5rem 1.8rem;
  margin: 0.8rem 0; box-shadow: 0 2px 12px rgba(8,127,115,.06);
}
.drug-header h2 {
  font-size: 1.75rem; letter-spacing: -0.06em;
  margin: 0.3rem 0 0.5rem; color: var(--ink); font-weight: 800;
}
.drug-header .sub { color: var(--muted); font-size: 0.9rem; margin-bottom: 0.3rem; }
.drug-header .summary { color: var(--ink); font-size: 0.95rem; margin-top: 0.6rem; border-top: 1px solid var(--line); padding-top: 0.6rem; }

/* ── 배지(pill) ── */
.pill {
  display: inline-block; border-radius: 999px;
  padding: 0.25rem 0.7rem; margin: 0 0.3rem 0.3rem 0;
  font-size: 0.76rem; font-weight: 700;
}
.pill-green  { background: #d6f4ef; color: #076b61; }
.pill-amber  { background: #fff0cc; color: #8b5e00; }
.pill-red    { background: #fde8e6; color: #a0291e; }
.pill-blue   { background: #ddeeff; color: #1a5fa0; }
.pill-purple { background: #ede5ff; color: #5a2ea0; }
.pill-gray   { background: #e8eeec; color: #445550; }

/* ── 약가 정보 배너 ── */
.price-band {
  display: flex; flex-wrap: wrap; gap: 1rem 2rem;
  background: linear-gradient(90deg, #e8f8f6, #f0fbfa);
  border: 1px solid #b5e0da; border-radius: 14px;
  padding: 0.9rem 1.3rem; margin: 0.8rem 0;
  align-items: center;
}
.price-item .label { font-size: 0.74rem; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; }
.price-item .val   { font-size: 1.08rem; font-weight: 800; color: var(--g0); margin-top: 0.1rem; }
.price-item .val.highlight { color: var(--g1); font-size: 1.2rem; }

/* ── 섹션 네비 ── */
.nav-strip {
  display: flex; gap: 0.35rem; flex-wrap: wrap;
  margin: 1rem 0 0.5rem; background: white;
  border: 1px solid var(--line); border-radius: 14px;
  padding: 0.6rem 0.8rem;
}
.nav-strip a {
  text-decoration: none !important;
  border: 1px solid #c5ddd9; color: #076b61 !important;
  background: #f0faf8; border-radius: 8px;
  padding: 0.45rem 0.75rem; font-weight: 700; font-size: 0.84rem;
  transition: all 0.15s;
}
.nav-strip a:hover { background: #087f73; color: white !important; border-color: #087f73; }

/* ── 리포트 섹션 ── */
.report-section {
  background: white; border: 1px solid var(--line);
  border-radius: 16px; padding: 1.4rem 1.6rem;
  margin: 0.8rem 0; box-shadow: 0 1px 6px rgba(0,0,0,.04);
}
.report-eyebrow {
  font-size: 0.7rem; text-transform: uppercase;
  letter-spacing: 0.12em; font-weight: 700;
  color: var(--g1); margin-bottom: 0.3rem;
}
.report-title {
  font-size: 1.15rem; font-weight: 800;
  color: var(--ink); margin: 0 0 1rem; letter-spacing: -0.03em;
}

/* ── 상병코드 카드 ── */
.icd-grid { display: flex; flex-direction: column; gap: 0.5rem; margin-top: 0.5rem; }
.icd-card {
  display: flex; align-items: flex-start; gap: 0.8rem;
  background: #f8fcfb; border: 1px solid #cde8e3;
  border-radius: 11px; padding: 0.75rem 1rem;
  transition: border-color 0.15s;
}
.icd-card:hover { border-color: var(--g1); }
.icd-card .code {
  font-family: monospace; font-size: 0.88rem; font-weight: 800;
  color: var(--g1); min-width: 60px; background: #e0f4f1;
  border-radius: 6px; padding: 0.2rem 0.5rem; text-align: center;
  white-space: nowrap;
}
.icd-card .info { flex: 1; }
.icd-card .icd-name { font-size: 0.95rem; font-weight: 700; color: var(--ink); }
.icd-card .icd-group { font-size: 0.78rem; color: var(--muted); margin-top: 0.1rem; }
.icd-card .icd-reason { font-size: 0.82rem; color: #557068; margin-top: 0.25rem; }
.icd-card .badges { margin-top: 0.3rem; }
.icd-warning {
  font-size: 0.78rem; background: #fff8e8;
  border-left: 3px solid var(--amber); border-radius: 0 6px 6px 0;
  padding: 0.3rem 0.6rem; color: #7a4e00; margin-top: 0.35rem;
}

/* ── API 상태 배지 ── */
.api-badge {
  display: inline-flex; align-items: center; gap: 0.3rem;
  font-size: 0.72rem; font-weight: 700; border-radius: 999px;
  padding: 0.18rem 0.55rem;
}
.api-ok   { background: #d6f4ef; color: #076b61; }
.api-fail { background: #fde8e6; color: #a0291e; }
.api-skip { background: #e8eeec; color: #445550; }

/* ── 알림 박스 ── */
.notice-box {
  border-radius: 10px; padding: 0.85rem 1.1rem;
  font-size: 0.88rem; margin: 0.5rem 0;
  border-left: 4px solid;
}
.notice-info   { background: #eef4fc; border-color: var(--blue);   color: #0d3d6b; }
.notice-warn   { background: var(--amber-bg); border-color: var(--amber); color: #654200; }
.notice-danger { background: var(--red-bg);   border-color: var(--red);   color: #7a1a13; }
.notice-ok     { background: #e8f8f3; border-color: #12a073; color: #0a4a35; }

/* ── 동일성분 카드 ── */
.same-card {
  background: #f8fcfb; border: 1px solid #cde8e3;
  border-radius: 11px; padding: 0.75rem 1rem;
  margin-bottom: 0.5rem;
}
.same-card .sname { font-weight: 800; color: var(--ink); font-size: 0.95rem; }
.same-card .scode { font-family: monospace; font-size: 0.82rem; color: var(--g1); margin: 0.15rem 0; }
.same-card .snote { font-size: 0.82rem; color: var(--muted); }

/* ── 참고자료 카드 ── */
.ref-card {
  border: 1px solid var(--line); border-radius: 11px;
  padding: 0.8rem 1rem; margin-bottom: 0.5rem; background: white;
}
.ref-level-필수 { border-left: 4px solid var(--red); }
.ref-level-보조 { border-left: 4px solid var(--blue); }
.ref-level-공식 { border-left: 4px solid var(--g1); }
.ref-title { font-weight: 800; color: var(--ink); font-size: 0.92rem; }
.ref-body  { font-size: 0.87rem; color: #3a5550; margin-top: 0.3rem; }
.ref-badge {
  display: inline-block; border-radius: 5px;
  font-size: 0.7rem; font-weight: 700; padding: 0.1rem 0.45rem; margin-right: 0.4rem;
}
.badge-필수 { background: #fde8e6; color: #a0291e; }
.badge-보조 { background: #ddeeff; color: #1a5fa0; }
.badge-공식 { background: #d6f4ef; color: #076b61; }

/* ── 출처 ── */
.source-row {
  display: flex; align-items: flex-start; gap: 0.7rem;
  padding: 0.6rem 0; border-top: 1px solid var(--line); font-size: 0.87rem;
}
.source-row .src-section { font-weight: 700; color: var(--ink); min-width: 100px; }
.source-row a { color: var(--g1) !important; font-weight: 600; }

/* ── API 상태 패널 ── */
.api-panel {
  background: white; border: 1px solid var(--line);
  border-radius: 12px; padding: 0.8rem 1rem;
  margin-bottom: 0.8rem; font-size: 0.82rem;
}
.api-panel .ap-title { font-weight: 800; color: var(--ink); margin-bottom: 0.4rem; }
.api-row { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.2rem; }
.api-row .ap-name { color: var(--muted); min-width: 120px; font-size: 0.78rem; }

/* ── 버튼 ── */
div[data-testid="stButton"] button {
  border-radius: 10px; border-color: #c5ddd9; font-weight: 700;
}
div[data-testid="stButton"] button[kind="primary"] {
  background: var(--g1); border-color: var(--g1); color: white;
}
div[data-testid="stButton"] button[kind="primary"]:hover {
  background: #076b61;
}

/* ── 검색 결과 행 ── */
.result-row {
  background: white; border: 1px solid var(--line);
  border-radius: 13px; padding: 0.9rem 1.1rem;
  margin-bottom: 0.5rem; transition: border-color 0.15s;
}
.result-row:hover { border-color: var(--g2); }
.result-name { font-size: 1.0rem; font-weight: 800; color: var(--ink); }
.result-meta { font-size: 0.83rem; color: var(--muted); margin-top: 0.15rem; }

/* ── 스태트 카드 ── */
.stat-card {
  background: white; border: 1px solid var(--line);
  border-radius: 13px; padding: 1rem 1.1rem; text-align: center;
}
.stat-label { font-size: 0.75rem; color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; }
.stat-value { font-size: 1.6rem; font-weight: 800; color: var(--ink); margin-top: 0.2rem; }
.stat-value.green { color: var(--g1); }

h1, h2, h3 { color: var(--ink); }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# DB
# ─────────────────────────────────────────────
def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS drugs (
                id TEXT PRIMARY KEY, name TEXT NOT NULL,
                ingredient_display TEXT NOT NULL,
                reimbursement_code TEXT, manufacturer TEXT,
                category_code TEXT, searchable TEXT NOT NULL,
                payload TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                drug_id TEXT NOT NULL, drug_name TEXT NOT NULL,
                occurred_at TEXT NOT NULL
            )
        """)
        if conn.execute("SELECT COUNT(*) as c FROM drugs").fetchone()["c"] == 0:
            records = json.loads(SEED_PATH.read_text(encoding="utf-8"))
            _upsert(conn, records)


def _searchable(d: dict) -> str:
    return " ".join([
        d.get("name",""), d.get("ingredient_display",""),
        d.get("reimbursement_code",""), d.get("manufacturer",""),
        " ".join(d.get("ingredients",[])),
    ]).lower()


def validate(d: dict) -> list[str]:
    errs = [f"`{k}` 누락" for k in ["id","name","ingredient_display"] if not str(d.get(k,"")).strip()]
    return errs


def _upsert(conn, records: list[dict]) -> int:
    n = 0
    for d in records:
        if validate(d):
            continue
        conn.execute("""
            INSERT INTO drugs
              (id,name,ingredient_display,reimbursement_code,manufacturer,category_code,searchable,payload,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name, ingredient_display=excluded.ingredient_display,
              reimbursement_code=excluded.reimbursement_code, manufacturer=excluded.manufacturer,
              category_code=excluded.category_code, searchable=excluded.searchable,
              payload=excluded.payload, updated_at=excluded.updated_at
        """, (
            d["id"], d["name"], d["ingredient_display"],
            d.get("reimbursement_code",""), d.get("manufacturer",""),
            d.get("category_code",""), _searchable(d),
            json.dumps(d, ensure_ascii=False), NOW(),
        ))
        n += 1
    return n


def find_drugs(q: str) -> list[dict]:
    t = q.strip().lower()
    with get_conn() as conn:
        if not t:
            rows = conn.execute("SELECT payload FROM drugs ORDER BY name LIMIT 12").fetchall()
        else:
            rows = conn.execute(
                "SELECT payload FROM drugs WHERE searchable LIKE ? ORDER BY name LIMIT 20",
                (f"%{t}%",)
            ).fetchall()
    return [json.loads(r["payload"]) for r in rows]


def load_drug(did: str) -> dict | None:
    with get_conn() as conn:
        r = conn.execute("SELECT payload FROM drugs WHERE id=?", (did,)).fetchone()
    return json.loads(r["payload"]) if r else None


def log_select(drug: dict) -> None:
    key = f"{drug['id']}::logged"
    if st.session_state.get(key):
        return
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO search_events (drug_id,drug_name,occurred_at) VALUES (?,?,?)",
            (drug["id"], drug["name"], NOW())
        )
    st.session_state[key] = True


def get_ranking(hours: int | None) -> pd.DataFrame:
    sql = "SELECT drug_name AS 약제명, COUNT(*) AS 검색수, MAX(occurred_at) AS 최근검색 FROM search_events"
    args: tuple = ()
    if hours:
        since = (datetime.now()-timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        sql += " WHERE occurred_at >= ?"
        args = (since,)
    sql += " GROUP BY drug_id,drug_name ORDER BY 검색수 DESC LIMIT 10"
    with get_conn() as conn:
        return pd.read_sql_query(sql, conn, params=args)


# ─────────────────────────────────────────────
# 공공 API 연동
# ─────────────────────────────────────────────
API_TIMEOUT = 8

@st.cache_data(ttl=3600, show_spinner=False)
def api_drug_price(drug_name: str, api_key: str) -> dict:
    """약가기준정보 (15054445) - HIRA"""
    if not api_key:
        return {"status": "skip", "data": None}
    try:
        url = "http://apis.data.go.kr/B551182/msInsrdMdctnPrscbInfoService/getInsrdMdctnPrscbInfo"
        params = {
            "serviceKey": api_key, "type": "json",
            "itmNm": drug_name, "numOfRows": 5, "pageNo": 1
        }
        r = requests.get(url, params=params, timeout=API_TIMEOUT)
        r.raise_for_status()
        body = r.json().get("body", {})
        items = body.get("items", []) or []
        if isinstance(items, dict):
            items = [items.get("item", {})] if items.get("item") else []
        return {"status": "ok", "data": items[:3]}
    except Exception as e:
        return {"status": "fail", "error": str(e)[:80], "data": None}


@st.cache_data(ttl=3600, show_spinner=False)
def api_drug_permit(drug_name: str, api_key: str) -> dict:
    """의약품 제품 허가정보 (15095677) - 식약처"""
    if not api_key:
        return {"status": "skip", "data": None}
    try:
        url = "http://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService06/getDrugPrdtPrmsnDtlInq06"
        params = {
            "serviceKey": api_key, "type": "json",
            "item_name": drug_name, "numOfRows": 3, "pageNo": 1
        }
        r = requests.get(url, params=params, timeout=API_TIMEOUT)
        r.raise_for_status()
        body = r.json().get("body", {})
        items = body.get("items", []) or []
        if isinstance(items, dict):
            items = [items] if items else []
        return {"status": "ok", "data": items[:2]}
    except Exception as e:
        return {"status": "fail", "error": str(e)[:80], "data": None}


@st.cache_data(ttl=3600, show_spinner=False)
def api_drug_eiyak(drug_name: str, api_key: str) -> dict:
    """의약품개요정보 e약은요 (15075057) - 식약처"""
    if not api_key:
        return {"status": "skip", "data": None}
    try:
        url = "http://apis.data.go.kr/1471000/DrbEasyDrugInfoService/getDrbEasyDrugList"
        params = {
            "serviceKey": api_key, "type": "json",
            "itemName": drug_name, "numOfRows": 3, "pageNo": 1
        }
        r = requests.get(url, params=params, timeout=API_TIMEOUT)
        r.raise_for_status()
        body = r.json().get("body", {})
        items = body.get("items", []) or []
        if isinstance(items, dict):
            items = [items] if items else []
        return {"status": "ok", "data": items[:2]}
    except Exception as e:
        return {"status": "fail", "error": str(e)[:80], "data": None}


@st.cache_data(ttl=86400, show_spinner=False)
def api_disease_search(keyword: str, api_key: str) -> dict:
    """질병정보서비스 (15119055) - HIRA"""
    if not api_key:
        return {"status": "skip", "data": None}
    try:
        url = "http://apis.data.go.kr/B551182/diseaseInfoService/getDissNameCodeList"
        params = {
            "serviceKey": api_key, "type": "json",
            "disNm": keyword, "numOfRows": 20, "pageNo": 1
        }
        r = requests.get(url, params=params, timeout=API_TIMEOUT)
        r.raise_for_status()
        body = r.json().get("body", {})
        items = body.get("items", []) or []
        if isinstance(items, dict):
            items = [items.get("item")] if items.get("item") else []
        return {"status": "ok", "data": items}
    except Exception as e:
        return {"status": "fail", "error": str(e)[:80], "data": None}


@st.cache_data(ttl=86400, show_spinner=False)
def api_review_criteria(drug_code: str, api_key: str) -> dict:
    """수가기준정보 (15021028) - HIRA"""
    if not api_key or not drug_code:
        return {"status": "skip", "data": None}
    try:
        url = "http://apis.data.go.kr/B551182/msInsrdMdctnPrscbInfoService/getInsrdMdctnPrscbInfo"
        params = {
            "serviceKey": api_key, "type": "json",
            "ediCd": drug_code, "numOfRows": 10, "pageNo": 1
        }
        r = requests.get(url, params=params, timeout=API_TIMEOUT)
        r.raise_for_status()
        body = r.json().get("body", {})
        items = body.get("items", []) or []
        if isinstance(items, dict):
            items = [items] if items else []
        return {"status": "ok", "data": items}
    except Exception as e:
        return {"status": "fail", "error": str(e)[:80], "data": None}


def clean_html_text(text: str) -> str:
    """HTML 태그 제거 및 텍스트 정제"""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_indications_from_permit(permit_data: list[dict]) -> list[str]:
    """허가정보에서 적응증/효능효과 텍스트 추출"""
    result = []
    for item in permit_data or []:
        ee = item.get("EE_DOC_DATA") or item.get("ee_doc_data") or ""
        if ee:
            text = clean_html_text(ee)
            if text:
                result.append(text[:500])
    return result


def extract_indications_from_eiyak(eiyak_data: list[dict]) -> list[str]:
    """e약은요에서 효능 텍스트 추출"""
    result = []
    for item in eiyak_data or []:
        efcy = item.get("efcyQesitm") or ""
        if efcy:
            text = clean_html_text(efcy)
            if text:
                result.append(text[:400])
    return result


# ─────────────────────────────────────────────
# 적응증 → 상병코드 매핑 (키워드 기반)
# ─────────────────────────────────────────────

# 핵심 키워드 → 상병코드 매핑 사전
INDICATION_ICD_MAP = [
    # 호흡기
    {"keywords": ["폐렴"], "group": "호흡기 감염",
     "codes": [
         {"code":"J18.0","name":"기관지폐렴","benefit":"급여","main":True},
         {"code":"J18.1","name":"대엽성폐렴","benefit":"급여","main":True},
         {"code":"J18.9","name":"상세불명의 폐렴","benefit":"급여","main":False},
     ]},
    {"keywords": ["상기도감염","인두염","편도","인두"], "group": "상기도 감염",
     "codes": [
         {"code":"J06.9","name":"급성 상기도감염, 상세불명","benefit":"급여","main":True},
         {"code":"J02.9","name":"급성 인두염, 상세불명","benefit":"급여","main":True},
         {"code":"J03.9","name":"급성 편도염, 상세불명","benefit":"급여","main":False},
     ]},
    {"keywords": ["기관지염","기관지"], "group": "하기도 감염",
     "codes": [
         {"code":"J20.9","name":"급성 기관지염, 상세불명","benefit":"급여","main":True},
         {"code":"J40","name":"기관지염, 급성 또는 만성으로 명시되지 않은","benefit":"급여","main":False},
     ]},
    {"keywords": ["중이염","귀"], "group": "귀 감염",
     "codes": [
         {"code":"H66.0","name":"급성 화농성 중이염","benefit":"급여","main":True},
         {"code":"H66.9","name":"상세불명의 화농성 중이염","benefit":"조건부급여","main":False},
         {"code":"H65.0","name":"급성 장액성 중이염","benefit":"급여","main":False},
     ]},
    {"keywords": ["부비동염","축농증","부비동"], "group": "부비동 감염",
     "codes": [
         {"code":"J01.9","name":"급성 부비동염, 상세불명","benefit":"급여","main":True},
         {"code":"J32.9","name":"만성 부비동염, 상세불명","benefit":"급여","main":False},
     ]},
    {"keywords": ["요로감염","방광염","요로"], "group": "요로계 감염",
     "codes": [
         {"code":"N39.0","name":"요로감염, 상세불명","benefit":"급여","main":True},
         {"code":"N30.0","name":"급성 방광염","benefit":"급여","main":True},
         {"code":"N30.9","name":"방광염, 상세불명","benefit":"급여","main":False},
     ]},
    {"keywords": ["신우신염","신우"], "group": "신장 감염",
     "codes": [
         {"code":"N10","name":"급성 세뇨관-간질성 신장염","benefit":"급여","main":True},
         {"code":"N12","name":"세뇨관-간질성 신장염, 급성 또는 만성 상세불명","benefit":"조건부급여","main":False},
     ]},
    {"keywords": ["피부감염","농가진","봉와직염","피부"], "group": "피부 감염",
     "codes": [
         {"code":"L01.0","name":"농가진(기타 원인에 의한)","benefit":"급여","main":True},
         {"code":"L03.1","name":"기타 사지의 봉와직염","benefit":"급여","main":False},
         {"code":"L03.9","name":"봉와직염, 상세불명","benefit":"급여","main":False},
     ]},
    # 소화기
    {"keywords": ["소화성궤양","위궤양","십이지장궤양","궤양"], "group": "소화성 궤양",
     "codes": [
         {"code":"K25.9","name":"위궤양, 상세불명","benefit":"급여","main":True},
         {"code":"K26.9","name":"십이지장궤양, 상세불명","benefit":"급여","main":True},
         {"code":"K27.9","name":"위공장궤양, 상세불명","benefit":"급여","main":False},
     ]},
    {"keywords": ["역류성식도염","위식도역류","역류"], "group": "위식도 역류",
     "codes": [
         {"code":"K21.0","name":"식도염을 동반한 위-식도역류병","benefit":"급여","main":True},
         {"code":"K21.9","name":"식도염이 없는 위-식도역류병","benefit":"급여","main":False},
     ]},
    {"keywords": ["헬리코박터","H.pylori"], "group": "헬리코박터 감염",
     "codes": [
         {"code":"B96.81","name":"헬리코박터 파이로리의 감염","benefit":"급여","main":True},
     ]},
    {"keywords": ["대장내시경","장정결","대장 정결","내시경 검사"], "group": "대장내시경 검사",
     "codes": [
         {"code":"Z12.1","name":"결장의 악성신생물에 대한 특수선별검사","benefit":"급여","main":True,
          "warning":"선별검진 목적인 경우"},
         {"code":"Z01.8","name":"기타 명시된 특수검사","benefit":"급여","main":False},
         {"code":"R19.4","name":"배변습관의 변화","benefit":"급여","main":False,
          "warning":"증상 기반 내시경인 경우"},
     ]},
    # 심혈관
    {"keywords": ["고혈압"], "group": "고혈압",
     "codes": [
         {"code":"I10","name":"본태성(원발성) 고혈압","benefit":"급여","main":True},
         {"code":"I15.9","name":"상세불명의 이차성 고혈압","benefit":"급여","main":False},
     ]},
    {"keywords": ["협심증","심장"], "group": "허혈성 심장질환",
     "codes": [
         {"code":"I20.9","name":"협심증, 상세불명","benefit":"급여","main":True},
         {"code":"I25.1","name":"죽상경화성 심장병","benefit":"급여","main":False},
         {"code":"I25.9","name":"만성 허혈성 심장병, 상세불명","benefit":"급여","main":False},
     ]},
    {"keywords": ["심부전"], "group": "심부전",
     "codes": [
         {"code":"I50.0","name":"울혈성 심부전","benefit":"급여","main":True},
         {"code":"I50.9","name":"심부전, 상세불명","benefit":"급여","main":False},
     ]},
    # 당뇨·대사
    {"keywords": ["당뇨","혈당"], "group": "당뇨병",
     "codes": [
         {"code":"E11.9","name":"인슐린-비의존 당뇨병, 합병증 없음","benefit":"급여","main":True},
         {"code":"E11.8","name":"인슐린-비의존 당뇨병, 명시된 합병증","benefit":"급여","main":False},
         {"code":"E14.9","name":"상세불명 당뇨병, 합병증 없음","benefit":"급여","main":False},
     ]},
    {"keywords": ["고지혈증","이상지질","콜레스테롤","지질"], "group": "이상지질혈증",
     "codes": [
         {"code":"E78.0","name":"순수 고콜레스테롤혈증","benefit":"급여","main":True},
         {"code":"E78.5","name":"상세불명의 고지혈증","benefit":"급여","main":False},
     ]},
    # 신경·정신
    {"keywords": ["불안","불안장애"], "group": "불안장애",
     "codes": [
         {"code":"F41.1","name":"범불안장애","benefit":"급여","main":True},
         {"code":"F41.9","name":"상세불명의 불안장애","benefit":"급여","main":False},
     ]},
    {"keywords": ["우울","우울증"], "group": "우울장애",
     "codes": [
         {"code":"F32.9","name":"우울 삽화, 상세불명","benefit":"급여","main":True},
         {"code":"F33.9","name":"반복성 우울장애, 상세불명","benefit":"급여","main":False},
     ]},
    {"keywords": ["불면","수면장애","불면증"], "group": "수면장애",
     "codes": [
         {"code":"G47.0","name":"수면 개시 및 유지 장애","benefit":"급여","main":True},
         {"code":"F51.0","name":"비기질성 불면증","benefit":"조건부급여","main":False},
     ]},
    # 통증·근골격
    {"keywords": ["통증","진통","소염","관절"], "group": "통증/염증",
     "codes": [
         {"code":"M79.3","name":"연조직 통증 증후군","benefit":"급여","main":True},
         {"code":"M54.5","name":"요통","benefit":"급여","main":False},
         {"code":"M79.1","name":"근육통","benefit":"급여","main":False},
     ]},
    {"keywords": ["골관절염","퇴행성관절염"], "group": "관절염",
     "codes": [
         {"code":"M19.9","name":"상세불명의 관절증","benefit":"급여","main":True},
         {"code":"M17.9","name":"상세불명의 무릎 관절증","benefit":"급여","main":False},
     ]},
    # 호르몬·내분비
    {"keywords": ["갑상선","갑상샘"], "group": "갑상선 질환",
     "codes": [
         {"code":"E03.9","name":"상세불명의 갑상선기능저하증","benefit":"급여","main":True},
         {"code":"E05.9","name":"상세불명의 갑상선중독증","benefit":"급여","main":False},
     ]},
    # 항생제 공통
    {"keywords": ["세균감염","감염증","항균"], "group": "세균 감염 (일반)",
     "codes": [
         {"code":"A49.9","name":"상세불명의 세균성 감염","benefit":"급여","main":False},
     ]},
]


def match_icd_from_text(indication_text: str, drug_name: str = "") -> list[dict]:
    """적응증 텍스트에서 관련 ICD 코드 추출"""
    combined = (indication_text + " " + drug_name).lower()
    matched_groups = []
    seen_codes = set()

    for entry in INDICATION_ICD_MAP:
        if any(kw.lower() in combined for kw in entry["keywords"]):
            group_codes = []
            for c in entry["codes"]:
                if c["code"] not in seen_codes:
                    seen_codes.add(c["code"])
                    group_codes.append(c)
            if group_codes:
                matched_groups.append({
                    "group": entry["group"],
                    "codes": group_codes,
                })
    return matched_groups


def merge_icd_with_api(local_groups: list[dict], api_results: list[dict]) -> list[dict]:
    """API 조회 결과와 로컬 매핑 병합"""
    if not api_results:
        return local_groups
    existing_codes = {c["code"] for g in local_groups for c in g["codes"]}
    api_group_codes = []
    for item in api_results:
        code = item.get("disCode","") or item.get("disCd","")
        name = item.get("disNm","") or item.get("disNm","")
        if code and code not in existing_codes:
            existing_codes.add(code)
            api_group_codes.append({"code": code, "name": name, "benefit": "확인필요", "main": False})
    if api_group_codes:
        local_groups.append({"group": "API 조회 결과 (추가)", "codes": api_group_codes})
    return local_groups


# ─────────────────────────────────────────────
# AI 연동
# ─────────────────────────────────────────────
def ai_ok() -> bool:
    return bool(secret("OPENAI_API_KEY"))


def call_ai(drug: dict, note: str, task: str) -> str:
    api_key = secret("OPENAI_API_KEY")
    model   = secret("OPENAI_MODEL", "gpt-4.1-mini")
    if not api_key:
        return "OPENAI_API_KEY 미설정 — 규칙 기반 결과만 표시합니다."
    ctx = {
        "약제": drug.get("name"), "성분": drug.get("ingredient_display"),
        "효능": drug.get("efficacy",[]), "용법": drug.get("dosage_official",[]),
        "상병후보": drug.get("diagnosis_candidates",[]), "메모": note,
    }
    prompt = (
        "당신은 병원 청구심사 검토 보조자입니다. "
        "진단·급여 인정을 확정하지 마십시오. 제공 자료 안에서만 답하고 "
        "없는 사항은 '공식 원문 확인 필요'라고 표시하십시오.\n"
        f"작업: {task}\n결과는 '검토 요약', '확인 근거', '주의사항' 세 단락으로 한국어로 작성.\n"
        + json.dumps(ctx, ensure_ascii=False)
    )
    try:
        r = requests.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "input": prompt},
            timeout=30,
        )
        r.raise_for_status()
        d = r.json()
        if d.get("output_text"):
            return d["output_text"]
        parts = [c["text"] for o in d.get("output",[]) for c in o.get("content",[]) if c.get("text")]
        return "\n".join(parts) or "AI 응답 해석 실패"
    except Exception as e:
        return f"AI 연결 실패 ({e.__class__.__name__})"


# ─────────────────────────────────────────────
# 렌더 헬퍼
# ─────────────────────────────────────────────
def api_badge(status: str) -> str:
    if status == "ok":
        return '<span class="api-badge api-ok">● API 연동</span>'
    elif status == "fail":
        return '<span class="api-badge api-fail">● 연동 실패</span>'
    else:
        return '<span class="api-badge api-skip">● 키 미설정</span>'


@contextmanager
def section(anchor: str, eyebrow: str, title: str):
    st.markdown(f'<span id="{anchor}"></span>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="report-section">
      <div class="report-eyebrow">{esc(eyebrow)}</div>
      <div class="report-title">{esc(title)}</div>
    </div>
    """, unsafe_allow_html=True)
    with st.container(border=True):
        yield


def render_list(items: list[str], empty_msg: str = "등록된 자료 없음") -> None:
    if items:
        for item in items:
            st.markdown(f"- {item}")
    else:
        st.caption(f"ℹ️ {empty_msg}")


def benefit_pill(b: str) -> str:
    cls = {"급여":"pill pill-green","조건부급여":"pill pill-amber",
           "비급여":"pill pill-red","확인필요":"pill pill-gray"}.get(b, "pill pill-gray")
    return f'<span class="{cls}">{esc(b)}</span>'


def main_pill(is_main: bool) -> str:
    if is_main:
        return '<span class="pill pill-purple">주상병</span>'
    return '<span class="pill pill-gray">부상병</span>'


# ─────────────────────────────────────────────
# 상병코드 섹션 렌더
# ─────────────────────────────────────────────
def render_icd_section(drug: dict, api_keys: dict) -> None:
    hira_key = api_keys.get("hira","")
    permit_key = api_keys.get("mfds","")

    st.markdown('<span id="diagnosis"></span>', unsafe_allow_html=True)

    with st.container(border=True):
        col_title, col_badge = st.columns([5,1])
        with col_title:
            st.markdown(
                '<div class="report-eyebrow">INDICATION → ICD MAPPING</div>'
                '<div class="report-title">📋 적응증 기반 상병코드</div>',
                unsafe_allow_html=True
            )

        st.markdown(
            '<div class="notice-box notice-warn">'
            '⚠️ 상병코드는 반드시 의무기록에 기재된 진단·검사 목적·증상에 근거해 선택해야 합니다. '
            '이 화면의 후보는 참고용이며 급여 인정을 확정하지 않습니다.'
            '</div>', unsafe_allow_html=True
        )

        # 적응증 텍스트 수집 (API + 로컬)
        indication_texts = []

        # 1) 로컬 DB 효능효과
        for t in drug.get("efficacy", []):
            indication_texts.append(t)
        # 2) 허가정보 API
        permit_res = api_drug_permit(drug.get("name",""), permit_key)
        if permit_res["status"] == "ok" and permit_res["data"]:
            for t in extract_indications_from_permit(permit_res["data"]):
                indication_texts.append(t)
        # 3) e약은요 API
        eiyak_res = api_drug_eiyak(drug.get("name",""), permit_key)
        if eiyak_res["status"] == "ok" and eiyak_res["data"]:
            for t in extract_indications_from_eiyak(eiyak_res["data"]):
                indication_texts.append(t)

        combined_text = " ".join(indication_texts)
        drug_name = drug.get("name","")

        # ICD 매핑
        icd_groups = match_icd_from_text(combined_text, drug_name)

        # 로컬 DB 상병 후보 추가
        local_candidates = drug.get("diagnosis_candidates",[])
        if local_candidates:
            local_extra = []
            existing_codes = {c["code"] for g in icd_groups for c in g["codes"]}
            for cand in local_candidates:
                if cand.get("code") not in existing_codes:
                    local_extra.append({
                        "code": cand.get("code",""),
                        "name": cand.get("name",""),
                        "benefit": "급여",
                        "main": False,
                        "warning": cand.get("warning",""),
                    })
            if local_extra:
                icd_groups.append({"group": "데이터베이스 등록 후보", "codes": local_extra})

        if not icd_groups:
            st.info("적응증 텍스트에서 매핑 가능한 상병코드를 찾지 못했습니다. 아래 직접 검색을 이용하세요.")
        else:
            total = sum(len(g["codes"]) for g in icd_groups)
            st.markdown(
                f'<div class="notice-box notice-ok">✅ 총 <strong>{total}개</strong> 관련 상병코드 확인 '
                f'(그룹 {len(icd_groups)}개)</div>',
                unsafe_allow_html=True
            )

            for group in icd_groups:
                st.markdown(
                    f'<div style="font-size:0.8rem;font-weight:800;color:#087f73;'
                    f'text-transform:uppercase;letter-spacing:.07em;margin:0.8rem 0 0.3rem;">'
                    f'📁 {esc(group["group"])}</div>',
                    unsafe_allow_html=True
                )
                for code_info in group["codes"]:
                    warning = code_info.get("warning","")
                    warn_html = f'<div class="icd-warning">⚠️ {esc(warning)}</div>' if warning else ""
                    st.markdown(f"""
                    <div class="icd-card">
                      <div class="code">{esc(code_info['code'])}</div>
                      <div class="info">
                        <div class="icd-name">{esc(code_info['name'])}</div>
                        <div class="badges">
                          {benefit_pill(code_info.get('benefit','확인필요'))}
                          {main_pill(code_info.get('main', False))}
                        </div>
                        {warn_html}
                      </div>
                    </div>
                    """, unsafe_allow_html=True)

        # 직접 상병 검색
        st.markdown("---")
        st.markdown("**🔍 상병코드 직접 검색 (HIRA 질병정보 API)**")
        col_q, col_btn = st.columns([5,1])
        with col_q:
            kw = st.text_input("상병명 키워드", placeholder="예: 폐렴, 고혈압, 당뇨",
                               key=f"icd-search-{drug['id']}", label_visibility="collapsed")
        with col_btn:
            do_search = st.button("검색", key=f"icd-btn-{drug['id']}", type="primary", use_container_width=True)

        if do_search and kw.strip():
            with st.spinner("HIRA 질병정보 조회 중..."):
                res = api_disease_search(kw.strip(), hira_key)
            if res["status"] == "ok" and res["data"]:
                st.markdown(f"**검색 결과 {len(res['data'])}건**")
                for item in res["data"]:
                    code = item.get("disCode","") or item.get("disCd","")
                    name = item.get("disNm","")
                    if code and name:
                        st.markdown(f"""
                        <div class="icd-card">
                          <div class="code">{esc(code)}</div>
                          <div class="info">
                            <div class="icd-name">{esc(name)}</div>
                            <div class="badges"><span class="pill pill-blue">API 조회</span></div>
                          </div>
                        </div>
                        """, unsafe_allow_html=True)
            elif res["status"] == "skip":
                st.caption("HIRA API 키가 설정되지 않아 직접 검색이 비활성화됩니다.")
            else:
                st.warning(f"조회 결과 없음 또는 오류: {res.get('error','')}")

        # 진료기록 기반 AI 상병 검토
        if ai_ok():
            st.markdown("---")
            st.markdown("**🤖 AI 보조 상병 검토**")
            note = st.text_area(
                "진료기록 요약 또는 검사 목적 입력",
                placeholder="예: 건강검진 중 대장암 선별 목적의 대장내시경 예정",
                key=f"dx-note-{drug['id']}", height=70,
            )
            if st.button("AI 상병 검토 생성", key=f"dx-ai-{drug['id']}", type="primary"):
                with st.spinner("AI 검토 메모 작성 중..."):
                    result = call_ai(drug, note, "입력 진료기록에 부합하는 상병 후보 검토 메모 작성")
                st.info(result)


# ─────────────────────────────────────────────
# 약제 상세 렌더
# ─────────────────────────────────────────────
def render_drug_detail(drug: dict, api_keys: dict) -> None:
    hira_key  = api_keys.get("hira","")
    mfds_key  = api_keys.get("mfds","")

    # ── API 데이터 조회 ──
    with st.spinner("공공 API에서 최신 데이터를 가져오는 중..."):
        price_res  = api_drug_price(drug.get("name",""), hira_key)
        permit_res = api_drug_permit(drug.get("name",""), mfds_key)
        eiyak_res  = api_drug_eiyak(drug.get("name",""), mfds_key)
        review_res = api_review_criteria(drug.get("reimbursement_code",""), hira_key)

    # ── API 상태 표시 ──
    st.markdown(f"""
    <div class="api-panel">
      <div class="ap-title">🔌 공공 API 연동 상태</div>
      <div class="api-row">
        <span class="ap-name">약가기준 (HIRA)</span>
        {api_badge(price_res['status'])}
        {'<span style="font-size:.75rem;color:#557068;margin-left:.3rem">상한금액·급여코드</span>' if price_res['status']=='ok' else ''}
      </div>
      <div class="api-row">
        <span class="ap-name">허가정보 (식약처)</span>
        {api_badge(permit_res['status'])}
        {'<span style="font-size:.75rem;color:#557068;margin-left:.3rem">허가사항·적응증</span>' if permit_res['status']=='ok' else ''}
      </div>
      <div class="api-row">
        <span class="ap-name">e약은요 (식약처)</span>
        {api_badge(eiyak_res['status'])}
        {'<span style="font-size:.75rem;color:#557068;margin-left:.3rem">효능·용법·주의</span>' if eiyak_res['status']=='ok' else ''}
      </div>
      <div class="api-row">
        <span class="ap-name">심사기준 (HIRA)</span>
        {api_badge(review_res['status'])}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 약가 API 데이터로 상한금액 업데이트 ──
    api_price_str = drug.get("upper_price", "공식 목록 확인")
    api_price_date = drug.get("price_effective_date", "-")
    if price_res["status"] == "ok" and price_res["data"]:
        item0 = price_res["data"][0]
        api_price_str = item0.get("uprcAmt","") or item0.get("mktPrc","") or api_price_str
        api_price_date = item0.get("acptDt","") or item0.get("applyDt","") or api_price_date

    # ── 약제 헤더 ──
    status_pill_cls = "pill-amber" if "검토" in drug.get("status","") or "예시" in drug.get("status","") else "pill-green"
    st.markdown(f"""
    <div class="drug-header">
      <div>
        <span class="pill {status_pill_cls}">{esc(drug.get('status',''))}</span>
        <span class="pill pill-blue">{esc(drug.get('professional',''))}</span>
        <span class="pill pill-gray">{esc(drug.get('route',''))}</span>
      </div>
      <h2>{esc(drug.get('name',''))}
        <span style="font-size:1rem;font-weight:400;color:#557068;">
          [{esc(drug.get('ingredient_display',''))}]
        </span>
      </h2>
      <div class="sub">
        제조사 <strong>{esc(drug.get('manufacturer',''))}</strong>
        &nbsp;|&nbsp; 급여코드 <code>{esc(drug.get('reimbursement_code',''))}</code>
        &nbsp;|&nbsp; 표준코드 <code>{esc(drug.get('standard_code','-'))}</code>
      </div>
      <div class="sub">
        약효분류 <strong>{esc(drug.get('category_code','-'))}</strong>
        {esc(drug.get('category_name',''))}
        &nbsp;|&nbsp; 자료 확인일 {esc(drug.get('verified_on',''))}
      </div>
      <div class="summary">{esc(drug.get('summary',''))}</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 약가 배너 ──
    st.markdown(f"""
    <div class="price-band">
      <div class="price-item">
        <div class="label">상한금액</div>
        <div class="val highlight">{esc(str(api_price_str))}</div>
      </div>
      <div class="price-item">
        <div class="label">적용일</div>
        <div class="val">{esc(str(api_price_date))}</div>
      </div>
      <div class="price-item">
        <div class="label">투여경로</div>
        <div class="val">{esc(drug.get('route','-'))}</div>
      </div>
      <div class="price-item">
        <div class="label">약효분류</div>
        <div class="val">{esc(drug.get('category_code','-'))} {esc(drug.get('category_name',''))}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 경고 배너 ──
    st.markdown(
        '<div class="notice-box notice-warn">'
        '⚠️ 이 서비스는 청구심사 검토 보조용입니다. '
        '급여 인정·진단·처방 판단은 최신 고시·허가사항·공식 시스템 결과와 전문가 검토를 기준으로 하십시오.'
        '</div>', unsafe_allow_html=True
    )

    # ── 섹션 네비 ──
    st.markdown("""
    <div class="nav-strip">
      <a href="#diagnosis">📋 상병코드</a>
      <a href="#dosage">💊 용법용량</a>
      <a href="#efficacy">✅ 효능효과</a>
      <a href="#review">📌 심사참고</a>
      <a href="#same">🔄 동일성분</a>
      <a href="#multiple">✖️ 배수처방</a>
      <a href="#caution">⚠️ 주의사항</a>
      <a href="#contra">🚫 금기사항</a>
      <a href="#source">📎 출처</a>
    </div>
    """, unsafe_allow_html=True)

    # ══════════════════════════════════════════
    # 1. 상병코드 (적응증 → ICD 자동 매핑)
    # ══════════════════════════════════════════
    render_icd_section(drug, api_keys)

    # ══════════════════════════════════════════
    # 2. 용법용량
    # ══════════════════════════════════════════
    st.markdown('<span id="dosage"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(
            '<div class="report-eyebrow">AI REVIEW ASSIST</div>'
            '<div class="report-title">💊 용법용량</div>',
            unsafe_allow_html=True
        )

        # e약은요 API 데이터
        if eiyak_res["status"] == "ok" and eiyak_res["data"]:
            item = eiyak_res["data"][0]
            useMethod = clean_html_text(item.get("useMethodQesitm",""))
            if useMethod:
                st.markdown("**📡 식약처 e약은요 (API 실시간)**")
                st.info(useMethod[:600])

        # 허가정보 API 용법
        if permit_res["status"] == "ok" and permit_res["data"]:
            item = permit_res["data"][0]
            ud = clean_html_text(item.get("UD_DOC_DATA","") or item.get("ud_doc_data",""))
            if ud:
                st.markdown("**📡 식약처 허가정보 (API)**")
                with st.expander("용법용량 상세 보기"):
                    st.write(ud[:800])

        st.markdown("**📋 등록 데이터 기준**")
        render_list(drug.get("dosage_official",[]))

        st.markdown("**🤖 AI 체크리스트**")
        render_list(drug.get("dosage_ai_checklist",[]))

        if ai_ok():
            if st.button("용법용량 AI 검토 생성", key=f"dose-ai-{drug['id']}", type="primary"):
                with st.spinner("AI 검토 중..."):
                    st.info(call_ai(drug, "", "투여 전 확인 체크리스트 및 심사 주의사항 작성"))
        else:
            st.caption("OPENAI_API_KEY 설정 시 AI 보조 검토가 활성화됩니다.")

    # ══════════════════════════════════════════
    # 3. 효능효과
    # ══════════════════════════════════════════
    st.markdown('<span id="efficacy"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(
            '<div class="report-eyebrow">INDICATIONS & EFFICACY</div>'
            '<div class="report-title">✅ 효능효과</div>',
            unsafe_allow_html=True
        )

        # e약은요 API
        if eiyak_res["status"] == "ok" and eiyak_res["data"]:
            item = eiyak_res["data"][0]
            efcy = clean_html_text(item.get("efcyQesitm",""))
            if efcy:
                st.markdown(f'<span class="api-badge api-ok">● 식약처 e약은요 API</span>',
                            unsafe_allow_html=True)
                st.markdown(f"> {efcy[:500]}")

        # 허가정보 API 효능
        if permit_res["status"] == "ok" and permit_res["data"]:
            item = permit_res["data"][0]
            ee = clean_html_text(item.get("EE_DOC_DATA","") or item.get("ee_doc_data",""))
            if ee:
                with st.expander("📡 식약처 허가정보 효능효과 전문"):
                    st.write(ee[:1000])

        st.markdown("**📋 등록 효능효과**")
        render_list(drug.get("efficacy",[]))

    # ══════════════════════════════════════════
    # 4. 심사참고자료
    # ══════════════════════════════════════════
    st.markdown('<span id="review"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(
            '<div class="report-eyebrow">CLAIM REVIEW REFERENCES</div>'
            '<div class="report-title">📌 심사참고자료</div>',
            unsafe_allow_html=True
        )

        # 수가기준 API
        if review_res["status"] == "ok" and review_res["data"]:
            st.markdown(f'<span class="api-badge api-ok">● HIRA 심사기준 API 연동</span>',
                        unsafe_allow_html=True)
            with st.expander("심사기준 API 원문 보기"):
                for item in review_res["data"][:3]:
                    st.json(item)

        refs = drug.get("review_references",[])
        if refs:
            for ref in refs:
                lvl = ref.get("level","보조")
                lvl_short = "필수" if "필수" in lvl else ("공식" if "공식" in lvl else "보조")
                st.markdown(f"""
                <div class="ref-card ref-level-{lvl_short}">
                  <div>
                    <span class="ref-badge badge-{lvl_short}">{esc(lvl)}</span>
                    <span class="ref-title">{esc(ref.get('title',''))}</span>
                  </div>
                  <div class="ref-body">{esc(ref.get('body',''))}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.caption("ℹ️ 등록된 심사참고자료가 없습니다. 관리자 업로드 후 표시됩니다.")

    # ══════════════════════════════════════════
    # 5. 동일성분약제
    # ══════════════════════════════════════════
    st.markdown('<span id="same"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(
            '<div class="report-eyebrow">SAME INGREDIENT PRODUCTS</div>'
            '<div class="report-title">🔄 동일성분약제</div>',
            unsafe_allow_html=True
        )
        same_list = drug.get("same_ingredient",[])
        if same_list:
            cols = st.columns(min(3, len(same_list)))
            for i, same in enumerate(same_list):
                with cols[i % len(cols)]:
                    st.markdown(f"""
                    <div class="same-card">
                      <div class="sname">{esc(same.get('name',''))}</div>
                      <div class="scode">코드: {esc(same.get('code',''))}</div>
                      <div class="snote">{esc(same.get('note',''))}</div>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.caption("ℹ️ 공식 데이터 연계 후 동일성분 제품이 표시됩니다.")

    # ══════════════════════════════════════════
    # 6. 배수처방
    # ══════════════════════════════════════════
    st.markdown('<span id="multiple"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(
            '<div class="report-eyebrow">MULTIPLE PRESCRIPTION REVIEW</div>'
            '<div class="report-title">✖️ 배수처방 검토</div>',
            unsafe_allow_html=True
        )
        render_list(drug.get("multiple_prescription",[]))

    # ══════════════════════════════════════════
    # 7. 주의사항
    # ══════════════════════════════════════════
    st.markdown('<span id="caution"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(
            '<div class="report-eyebrow">CAUTIONS</div>'
            '<div class="report-title">⚠️ 주의사항</div>',
            unsafe_allow_html=True
        )

        # e약은요 API 주의사항
        if eiyak_res["status"] == "ok" and eiyak_res["data"]:
            item = eiyak_res["data"][0]
            for field, label in [
                ("atpnWarnQesitm","경고"),("atpnQesitm","주의"),("intrcQesitm","상호작용")
            ]:
                val = clean_html_text(item.get(field,""))
                if val:
                    st.markdown(f'<span class="api-badge api-ok">● API · {label}</span>',
                                unsafe_allow_html=True)
                    st.markdown(f"> {val[:400]}")

        st.markdown("**📋 등록 주의사항**")
        render_list(drug.get("cautions",[]))

    # ══════════════════════════════════════════
    # 8. 금기사항
    # ══════════════════════════════════════════
    st.markdown('<span id="contra"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(
            '<div class="report-eyebrow">CONTRAINDICATIONS</div>'
            '<div class="report-title">🚫 금기사항</div>',
            unsafe_allow_html=True
        )

        # e약은요 API 금기
        if eiyak_res["status"] == "ok" and eiyak_res["data"]:
            item = eiyak_res["data"][0]
            seQ = clean_html_text(item.get("seQesitm",""))
            if seQ:
                st.markdown(f'<span class="api-badge api-ok">● API · 부작용/금기</span>',
                            unsafe_allow_html=True)
                st.markdown(f"> {seQ[:400]}")

        st.markdown("**📋 등록 금기사항**")
        render_list(drug.get("contraindications",[]))

        st.markdown(
            '<div class="notice-box notice-danger">'
            '🚫 최종 금기·상호작용 판단은 최신 허가사항 원문 및 HIRA DUR 점검 결과를 기준으로 하십시오.'
            '</div>', unsafe_allow_html=True
        )

    # ══════════════════════════════════════════
    # 9. 출처
    # ══════════════════════════════════════════
    st.markdown('<span id="source"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(
            '<div class="report-eyebrow">EVIDENCE & SOURCES</div>'
            '<div class="report-title">📎 자료 출처 및 검증 상태</div>',
            unsafe_allow_html=True
        )
        sources = drug.get("sources",[])
        if sources:
            for src in sources:
                st.markdown(f"""
                <div class="source-row">
                  <div class="src-section">{esc(src.get('section',''))}</div>
                  <div>
                    {esc(src.get('publisher',''))} ·
                    <a href="{esc(src.get('url',''))}" target="_blank">{esc(src.get('title',''))}</a>
                    <span style="color:#557068;font-size:.8rem;"> (확인일 {esc(src.get('checked_on',''))})</span>
                  </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.caption("등록된 출처 정보가 없습니다.")
        st.caption("운영 시 허가사항·급여목록·고시 개정일을 주기적으로 동기화하고 변경 이력을 보존하십시오.")


# ─────────────────────────────────────────────
# 페이지: 약제 검색
# ─────────────────────────────────────────────
def page_search(api_keys: dict) -> None:
    st.markdown("""
    <div class="hero">
      <h1>💊 약제 심사 지원 리포트</h1>
      <p>약품명 · 성분명 · 급여코드로 검색하고, 공공 API 실시간 연동 데이터와 적응증 기반 상병코드를 한 화면에서 검토합니다.</p>
    </div>
    """, unsafe_allow_html=True)

    col_q, col_btn = st.columns([7,1])
    query = col_q.text_input(
        "검색", value=st.session_state.get("query",""),
        placeholder="예: 씨엠쿨산, 폴리에틸렌글리콜, 648602750",
        label_visibility="collapsed"
    )
    col_btn.button("검색", type="primary", use_container_width=True)
    st.session_state.query = query

    results = find_drugs(query) if query.strip() else []

    if query.strip():
        st.caption(f"검색 결과 **{len(results)}건** · 상세 보기 클릭 시 검색순위에 반영됩니다.")
        if not results:
            st.info("일치하는 약제가 없습니다. 관리자 메뉴에서 데이터를 추가하거나 API 키를 설정하세요.")

        for drug in results:
            col_info, col_act = st.columns([6,1])
            with col_info:
                st.markdown(f"""
                <div class="result-row">
                  <div class="result-name">{esc(drug['name'])}</div>
                  <div class="result-meta">
                    성분: {esc(drug.get('ingredient_display',''))} &nbsp;|&nbsp;
                    급여코드: <code>{esc(drug.get('reimbursement_code',''))}</code> &nbsp;|&nbsp;
                    제조사: {esc(drug.get('manufacturer',''))}
                  </div>
                </div>
                """, unsafe_allow_html=True)
            with col_act:
                if st.button("상세 보기", key=f"open-{drug['id']}", use_container_width=True):
                    st.session_state.selected_drug = drug["id"]
                    log_select(drug)
                    st.rerun()

    selected_id = st.session_state.get("selected_drug")
    if selected_id:
        selected = load_drug(selected_id)
        if selected:
            st.divider()
            render_drug_detail(selected, api_keys)


# ─────────────────────────────────────────────
# 페이지: 검색 순위
# ─────────────────────────────────────────────
def page_ranking() -> None:
    st.header("📊 약제 검색 순위")
    st.caption("상세 보기 클릭 기준으로 집계합니다. 환자식별정보는 저장하지 않습니다.")

    tab1, tab2, tab3 = st.tabs(["실시간 (24h)","주간 (7일)","월간 (30일)"])
    for tab, hours, label in [(tab1,24,"최근 24시간"),(tab2,168,"최근 7일"),(tab3,720,"최근 30일")]:
        with tab:
            df = get_ranking(hours)
            if df.empty:
                st.info("아직 집계된 검색 기록이 없습니다.")
            else:
                df.insert(0,"순위",range(1,len(df)+1))
                st.dataframe(df, hide_index=True, use_container_width=True)

    st.markdown(
        '<div class="notice-box notice-info">'
        'ℹ️ 운영 환경에서는 접근 권한·감사로그 보존기간·개인정보 비수집 정책을 내부 규정과 함께 확정하십시오.'
        '</div>', unsafe_allow_html=True
    )


# ─────────────────────────────────────────────
# 페이지: API 설정 안내
# ─────────────────────────────────────────────
def page_api_guide() -> None:
    st.header("🔌 API 설정 가이드")
    st.markdown("""
    공공데이터포털(data.go.kr)에서 아래 5개 API를 신청하고, `.streamlit/secrets.toml`에 키를 설정하세요.
    """)

    apis = [
        ("약가기준정보","15054445","HIRA","약제 상한금액·급여여부","HIRA_API_KEY"),
        ("질병정보서비스","15119055","HIRA","KCD 상병코드 직접 검색","HIRA_API_KEY"),
        ("수가기준정보","15021028","HIRA","진료행위 심사기준","HIRA_API_KEY"),
        ("의약품 제품 허가정보","15095677","식약처","적응증·허가사항","MFDS_API_KEY"),
        ("의약품개요정보(e약은요)","15075057","식약처","효능·용법·주의·금기","MFDS_API_KEY"),
    ]

    for name, num, org, desc, key_name in apis:
        st.markdown(f"""
        <div class="ref-card" style="border-left:4px solid #087f73;margin-bottom:.5rem;">
          <div class="ref-title">{name}</div>
          <div class="ref-body">
            번호: <code>{num}</code> &nbsp;|&nbsp; 기관: {org} &nbsp;|&nbsp; 제공: {desc}<br>
            환경변수/secrets 키: <code>{key_name}</code>
          </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("**secrets.toml 예시**")
    st.code("""
HIRA_API_KEY  = "발급받은_HIRA_인증키"
MFDS_API_KEY  = "발급받은_식약처_인증키"
ADMIN_PASSWORD = "관리자비밀번호"
OPENAI_API_KEY = ""   # 선택사항
""", language="toml")

    st.markdown(
        '<div class="notice-box notice-info">'
        'ℹ️ HIRA와 식약처 API 키는 서로 다른 키입니다. '
        'data.go.kr에서 각각 신청 후 발급받아 별도로 설정하세요.'
        '</div>', unsafe_allow_html=True
    )


# ─────────────────────────────────────────────
# 페이지: 관리자
# ─────────────────────────────────────────────
def page_admin() -> None:
    st.header("🔐 관리자 데이터 관리")
    admin_pw = secret("ADMIN_PASSWORD")
    if not admin_pw:
        st.error("ADMIN_PASSWORD가 설정되지 않아 관리자 기능이 비활성화됩니다.")
        return
    if not st.session_state.get("admin_auth"):
        pw = st.text_input("관리자 비밀번호", type="password")
        if st.button("로그인", type="primary"):
            if hmac.compare_digest(pw, admin_pw):
                st.session_state.admin_auth = True
                st.rerun()
            else:
                st.error("비밀번호 불일치")
        return

    st.success("✅ 관리자 인증 완료")
    if st.button("로그아웃"):
        st.session_state.admin_auth = False
        st.rerun()

    st.divider()
    st.subheader("약제 JSON 업로드")
    st.markdown("`seed_data.json`과 동일한 배열 구조로 업로드하세요.")
    uploaded = st.file_uploader("JSON 파일 선택", type=["json"])
    if uploaded and st.button("검증 후 반영", type="primary"):
        try:
            records = json.loads(uploaded.getvalue().decode("utf-8"))
            if not isinstance(records, list):
                raise ValueError("최상위 형식이 배열이어야 합니다.")
            errs = []
            for i, r in enumerate(records,1):
                errs += [f"{i}번: {e}" for e in validate(r)]
            if errs:
                st.error("\n".join(errs))
            else:
                with get_conn() as conn:
                    n = _upsert(conn, records)
                st.success(f"{n}개 약제 반영 완료")
        except Exception as e:
            st.error(f"파일 처리 오류: {e}")

    st.subheader("템플릿 다운로드")
    st.download_button(
        "seed_data.json 내려받기",
        SEED_PATH.read_bytes(),
        file_name="drug_data_template.json",
        mime="application/json"
    )


# ─────────────────────────────────────────────
# 사이드바 + 메인
# ─────────────────────────────────────────────
def sidebar_nav() -> tuple[str, dict]:
    st.sidebar.markdown("""
    <div class="brand-wrap">
      <div class="brand-logo">Claim<span>Lens</span></div>
      <div class="brand-sub">병원 청구심사 약제 지원센터 v2</div>
    </div>
    """, unsafe_allow_html=True)

    page = st.sidebar.radio(
        "메뉴", ["💊 약제 검색", "📊 검색 순위", "🔌 API 설정", "🔐 관리자"],
        label_visibility="collapsed"
    )

    st.sidebar.divider()
    st.sidebar.markdown("**🔑 API 키 상태**")

    hira_key = secret("HIRA_API_KEY")
    mfds_key = secret("MFDS_API_KEY")

    hira_status = "✅ 설정됨" if hira_key else "❌ 미설정"
    mfds_status = "✅ 설정됨" if mfds_key else "❌ 미설정"
    ai_status   = "✅ 설정됨" if secret("OPENAI_API_KEY") else "❌ 미설정"

    st.sidebar.caption(
        f"HIRA API: {hira_status}\n\n"
        f"식약처 API: {mfds_status}\n\n"
        f"AI(OpenAI): {ai_status}"
    )

    st.sidebar.divider()
    st.sidebar.markdown("**📋 데이터 운영 원칙**")
    st.sidebar.caption(
        "허가사항: MFDS 기준\n\n"
        "급여·심사: HIRA 기준\n\n"
        "금기 점검: DUR 결과 우선\n\n"
        "상병코드: KCD-8 기준"
    )
    st.sidebar.markdown("`Beta · 내부 검토용`")

    api_keys = {"hira": hira_key, "mfds": mfds_key}
    return page, api_keys


def main() -> None:
    init_db()
    inject_css()
    page, api_keys = sidebar_nav()

    if page == "💊 약제 검색":
        page_search(api_keys)
    elif page == "📊 검색 순위":
        page_ranking()
    elif page == "🔌 API 설정":
        page_api_guide()
    else:
        page_admin()


if __name__ == "__main__":
    main()
