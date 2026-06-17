"""
ClaimLens v2 - 약제 청구심사 지원 시스템
공공데이터포털 API 통합 연동 (단일 키) + 적응증 기반 상병코드 자동 표시
"""

import hashlib
import hmac
import html
import json
import os
import re
import sqlite3
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
BASE_DIR  = Path(__file__).parent
DB_PATH   = BASE_DIR / "data" / "review_assist.db"
SEED_PATH = BASE_DIR / "seed_data.json"
NOW = lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")

st.set_page_config(
    page_title="ClaimLens | 약제 심사 지원",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────
def secret(name: str, default: str = "") -> str:
    try:
        v = st.secrets.get(name, "")
    except Exception:
        v = ""
    return str(v or os.environ.get(name, default))

def esc(v: Any) -> str:
    return html.escape(str(v or ""))

def clean_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()

# ─────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────
def inject_css() -> None:
    st.markdown("""
<style>
:root{
  --g0:#051f1b;--g1:#087f73;--g2:#0aada0;--g3:#5ddfd3;
  --ink:#152622;--muted:#557068;--line:#dce8e5;--bg:#f4f7f6;--white:#fff;
  --amber:#c47d0e;--amber-bg:#fff8e8;--red:#c0392b;--red-bg:#fff0ee;
  --blue:#1a6fb5;--blue-bg:#eef4fc;--purple:#6b3fa0;
}
.stApp{background:var(--bg);}
[data-testid="stSidebar"]{background:linear-gradient(180deg,#051f1b 0%,#0a3530 100%);border-right:1px solid #0d4a43;}
[data-testid="stSidebar"] *{color:#d4ece8!important;}
[data-testid="stSidebar"] hr{border-color:#1a5a52!important;}

/* 브랜드 */
.brand-logo{font-size:1.7rem;font-weight:800;letter-spacing:-.05em;color:#f0faf8;}
.brand-logo span{color:#5ddfd3;}
.brand-sub{font-size:.78rem;color:#7ab5ac;margin-top:.1rem;padding-bottom:1rem;}

/* 히어로 */
.hero{background:linear-gradient(120deg,#051f1b 0%,#0e6b60 60%,#129689 100%);
  border-radius:18px;color:white;padding:1.8rem 2rem;margin-bottom:1.2rem;border:1px solid #0d5a52;}
.hero h1{font-size:1.9rem;margin:0 0 .4rem;letter-spacing:-.06em;font-weight:800;}
.hero p{color:#b8e0da;margin:0;font-size:.93rem;}

/* 약가 배너 */
.price-band{display:flex;flex-wrap:wrap;gap:1rem 2rem;
  background:linear-gradient(90deg,#e8f8f6,#f0fbfa);
  border:1px solid #b5e0da;border-radius:14px;padding:.9rem 1.3rem;margin:.8rem 0;align-items:center;}
.price-item .lbl{font-size:.74rem;color:var(--muted);font-weight:600;text-transform:uppercase;letter-spacing:.06em;}
.price-item .val{font-size:1.08rem;font-weight:800;color:var(--g0);margin-top:.1rem;}
.price-item .val.hi{color:var(--g1);font-size:1.2rem;}

/* 약제 헤더 */
.drug-header{background:white;border:1.5px solid var(--line);border-radius:18px;
  padding:1.5rem 1.8rem;margin:.8rem 0;box-shadow:0 2px 12px rgba(8,127,115,.06);}
.drug-header h2{font-size:1.75rem;letter-spacing:-.06em;margin:.3rem 0 .5rem;color:var(--ink);font-weight:800;}
.drug-header .sub{color:var(--muted);font-size:.9rem;margin-bottom:.3rem;}
.drug-header .summary{color:var(--ink);font-size:.95rem;margin-top:.6rem;
  border-top:1px solid var(--line);padding-top:.6rem;}

/* 배지 */
.pill{display:inline-block;border-radius:999px;padding:.25rem .7rem;margin:0 .3rem .3rem 0;
  font-size:.76rem;font-weight:700;}
.pill-green{background:#d6f4ef;color:#076b61;}
.pill-amber{background:#fff0cc;color:#8b5e00;}
.pill-red{background:#fde8e6;color:#a0291e;}
.pill-blue{background:#ddeeff;color:#1a5fa0;}
.pill-purple{background:#ede5ff;color:#5a2ea0;}
.pill-gray{background:#e8eeec;color:#445550;}

/* API 상태 패널 */
.api-panel{background:white;border:1px solid var(--line);border-radius:12px;
  padding:.8rem 1.1rem;margin-bottom:.8rem;font-size:.82rem;}
.api-panel .ap-title{font-weight:800;color:var(--ink);margin-bottom:.4rem;font-size:.88rem;}
.api-row{display:flex;align-items:center;gap:.5rem;margin-bottom:.25rem;}
.api-row .ap-name{color:var(--muted);min-width:150px;font-size:.78rem;}
.api-badge{display:inline-flex;align-items:center;gap:.3rem;font-size:.72rem;
  font-weight:700;border-radius:999px;padding:.18rem .55rem;}
.api-ok{background:#d6f4ef;color:#076b61;}
.api-fail{background:#fde8e6;color:#a0291e;}
.api-skip{background:#e8eeec;color:#445550;}

/* 네비 */
.nav-strip{display:flex;gap:.35rem;flex-wrap:wrap;margin:1rem 0 .5rem;
  background:white;border:1px solid var(--line);border-radius:14px;padding:.6rem .8rem;}
.nav-strip a{text-decoration:none!important;border:1px solid #c5ddd9;color:#076b61!important;
  background:#f0faf8;border-radius:8px;padding:.45rem .75rem;font-weight:700;font-size:.84rem;transition:all .15s;}
.nav-strip a:hover{background:#087f73;color:white!important;border-color:#087f73;}

/* 섹션 */
.sec-eyebrow{font-size:.7rem;text-transform:uppercase;letter-spacing:.12em;
  font-weight:700;color:var(--g1);margin-bottom:.3rem;}
.sec-title{font-size:1.15rem;font-weight:800;color:var(--ink);margin:0 0 1rem;letter-spacing:-.03em;}

/* 상병 카드 */
.icd-card{display:flex;align-items:flex-start;gap:.8rem;
  background:#f8fcfb;border:1px solid #cde8e3;border-radius:11px;
  padding:.75rem 1rem;margin-bottom:.5rem;transition:border-color .15s;}
.icd-card:hover{border-color:var(--g1);}
.icd-code{font-family:monospace;font-size:.88rem;font-weight:800;color:var(--g1);
  min-width:62px;background:#e0f4f1;border-radius:6px;padding:.2rem .5rem;text-align:center;white-space:nowrap;}
.icd-info{flex:1;}
.icd-name{font-size:.95rem;font-weight:700;color:var(--ink);}
.icd-group-label{font-size:.78rem;color:var(--muted);margin-top:.1rem;}
.icd-warn{font-size:.78rem;background:var(--amber-bg);border-left:3px solid var(--amber);
  border-radius:0 6px 6px 0;padding:.3rem .6rem;color:#7a4e00;margin-top:.35rem;}

/* 알림 박스 */
.nb{border-radius:10px;padding:.85rem 1.1rem;font-size:.88rem;margin:.5rem 0;border-left:4px solid;}
.nb-info{background:var(--blue-bg);border-color:var(--blue);color:#0d3d6b;}
.nb-warn{background:var(--amber-bg);border-color:var(--amber);color:#654200;}
.nb-danger{background:var(--red-bg);border-color:var(--red);color:#7a1a13;}
.nb-ok{background:#e8f8f3;border-color:#12a073;color:#0a4a35;}

/* 참고자료 카드 */
.ref-card{border:1px solid var(--line);border-radius:11px;padding:.8rem 1rem;margin-bottom:.5rem;background:white;}
.ref-필수{border-left:4px solid var(--red);}
.ref-보조{border-left:4px solid var(--blue);}
.ref-공식{border-left:4px solid var(--g1);}

/* 동일성분 카드 */
.same-card{background:#f8fcfb;border:1px solid #cde8e3;border-radius:11px;padding:.75rem 1rem;margin-bottom:.5rem;}

/* 출처 */
.source-row{display:flex;align-items:flex-start;gap:.7rem;padding:.6rem 0;
  border-top:1px solid var(--line);font-size:.87rem;}
.src-sec{font-weight:700;color:var(--ink);min-width:100px;}
.source-row a{color:var(--g1)!important;font-weight:600;}

/* 검색 결과 행 */
.result-row{background:white;border:1px solid var(--line);border-radius:13px;
  padding:.9rem 1.1rem;margin-bottom:.5rem;transition:border-color .15s;}
.result-row:hover{border-color:var(--g2);}
.result-name{font-size:1rem;font-weight:800;color:var(--ink);}
.result-meta{font-size:.83rem;color:var(--muted);margin-top:.15rem;}

/* 버튼 */
div[data-testid="stButton"] button{border-radius:10px;font-weight:700;}
div[data-testid="stButton"] button[kind="primary"]{background:var(--g1);border-color:var(--g1);color:white;}
div[data-testid="stButton"] button[kind="primary"]:hover{background:#076b61;}
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
        """)
        # ★ query 컬럼 포함 — 원본 스키마와 동일하게 유지
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                drug_id TEXT NOT NULL,
                drug_name TEXT NOT NULL,
                query TEXT NOT NULL DEFAULT '',
                occurred_at TEXT NOT NULL
            )
        """)
        # 기존 DB에 query 컬럼이 없을 경우 안전하게 추가
        try:
            conn.execute("ALTER TABLE search_events ADD COLUMN query TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass

        if conn.execute("SELECT COUNT(*) AS c FROM drugs").fetchone()["c"] == 0:
            records = json.loads(SEED_PATH.read_text(encoding="utf-8"))
            _upsert(conn, records)


def _searchable(d: dict) -> str:
    return " ".join([
        d.get("name",""), d.get("ingredient_display",""),
        d.get("reimbursement_code",""), d.get("manufacturer",""),
        " ".join(d.get("ingredients",[])),
    ]).lower()


def validate(d: dict) -> list[str]:
    return [f"`{k}` 누락" for k in ["id","name","ingredient_display"]
            if not str(d.get(k,"")).strip()]


def _upsert(conn, records: list[dict]) -> int:
    n = 0
    for d in records:
        if validate(d):
            continue
        conn.execute("""
            INSERT INTO drugs
              (id,name,ingredient_display,reimbursement_code,manufacturer,
               category_code,searchable,payload,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name,ingredient_display=excluded.ingredient_display,
              reimbursement_code=excluded.reimbursement_code,manufacturer=excluded.manufacturer,
              category_code=excluded.category_code,searchable=excluded.searchable,
              payload=excluded.payload,updated_at=excluded.updated_at
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


def log_select(drug: dict, query: str = "") -> None:
    # ★ 중복 방지: 같은 세션에서 동일 약제 중복 로그 방지
    key = f"logged::{drug['id']}"
    if st.session_state.get(key):
        return
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO search_events (drug_id,drug_name,query,occurred_at) VALUES (?,?,?,?)",
            (drug["id"], drug["name"], query[:100], NOW())
        )
    st.session_state[key] = True


def get_ranking(hours: int | None) -> pd.DataFrame:
    sql = ("SELECT drug_name AS 약제명, COUNT(*) AS 검색수, MAX(occurred_at) AS 최근검색 "
           "FROM search_events")
    args: tuple = ()
    if hours:
        since = (datetime.now()-timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        sql += " WHERE occurred_at >= ?"
        args = (since,)
    sql += " GROUP BY drug_id,drug_name ORDER BY 검색수 DESC LIMIT 10"
    with get_conn() as conn:
        return pd.read_sql_query(sql, conn, params=args)


# ─────────────────────────────────────────────
# ★ 공공데이터포털 API - 단일 키 통합
#   공공데이터포털(data.go.kr)에서 발급받은 인증키 1개로
#   HIRA·식약처 5개 API 모두 사용
# ─────────────────────────────────────────────
API_TIMEOUT = 8

def get_api_key() -> str:
    """공공데이터포털 통합 API 키 반환"""
    return secret("PUBLIC_DATA_API_KEY")


@st.cache_data(ttl=3600, show_spinner=False)
def api_drug_price(drug_name: str, api_key: str) -> dict:
    """[15054445] HIRA 약가기준정보 - 상한금액·급여여부"""
    if not api_key:
        return {"status":"skip","data":None}
    try:
        url = "http://apis.data.go.kr/B551182/msInsrdMdctnPrscbInfoService/getInsrdMdctnPrscbInfo"
        params = {"serviceKey":api_key,"type":"json","itmNm":drug_name,"numOfRows":5,"pageNo":1}
        r = requests.get(url, params=params, timeout=API_TIMEOUT)
        r.raise_for_status()
        body = r.json().get("body",{})
        items = body.get("items",[]) or []
        if isinstance(items, dict):
            items = [items.get("item",{})] if items.get("item") else []
        return {"status":"ok","data":items[:3]}
    except Exception as e:
        return {"status":"fail","error":str(e)[:80],"data":None}


@st.cache_data(ttl=3600, show_spinner=False)
def api_drug_permit(drug_name: str, api_key: str) -> dict:
    """[15095677] 식약처 의약품 제품 허가정보 - 적응증·허가사항"""
    if not api_key:
        return {"status":"skip","data":None}
    try:
        url = "http://apis.data.go.kr/1471000/DrugPrdtPrmsnInfoService06/getDrugPrdtPrmsnDtlInq06"
        params = {"serviceKey":api_key,"type":"json","item_name":drug_name,"numOfRows":3,"pageNo":1}
        r = requests.get(url, params=params, timeout=API_TIMEOUT)
        r.raise_for_status()
        body = r.json().get("body",{})
        items = body.get("items",[]) or []
        if isinstance(items, dict):
            items = [items] if items else []
        return {"status":"ok","data":items[:2]}
    except Exception as e:
        return {"status":"fail","error":str(e)[:80],"data":None}


@st.cache_data(ttl=3600, show_spinner=False)
def api_drug_eiyak(drug_name: str, api_key: str) -> dict:
    """[15075057] 식약처 의약품개요정보(e약은요) - 효능·용법·주의·금기"""
    if not api_key:
        return {"status":"skip","data":None}
    try:
        url = "http://apis.data.go.kr/1471000/DrbEasyDrugInfoService/getDrbEasyDrugList"
        params = {"serviceKey":api_key,"type":"json","itemName":drug_name,"numOfRows":3,"pageNo":1}
        r = requests.get(url, params=params, timeout=API_TIMEOUT)
        r.raise_for_status()
        body = r.json().get("body",{})
        items = body.get("items",[]) or []
        if isinstance(items, dict):
            items = [items] if items else []
        return {"status":"ok","data":items[:2]}
    except Exception as e:
        return {"status":"fail","error":str(e)[:80],"data":None}


@st.cache_data(ttl=86400, show_spinner=False)
def api_disease_search(keyword: str, api_key: str) -> dict:
    """[15119055] HIRA 질병정보서비스 - KCD 상병코드 검색"""
    if not api_key:
        return {"status":"skip","data":None}
    try:
        url = "http://apis.data.go.kr/B551182/diseaseInfoService/getDissNameCodeList"
        params = {"serviceKey":api_key,"type":"json","disNm":keyword,"numOfRows":20,"pageNo":1}
        r = requests.get(url, params=params, timeout=API_TIMEOUT)
        r.raise_for_status()
        body = r.json().get("body",{})
        items = body.get("items",[]) or []
        if isinstance(items, dict):
            items = [items.get("item")] if items.get("item") else []
        return {"status":"ok","data":items}
    except Exception as e:
        return {"status":"fail","error":str(e)[:80],"data":None}


@st.cache_data(ttl=3600, show_spinner=False)
def api_review_criteria(drug_code: str, api_key: str) -> dict:
    """[15021028] HIRA 수가기준정보 - 심사기준"""
    if not api_key or not drug_code:
        return {"status":"skip","data":None}
    try:
        url = "http://apis.data.go.kr/B551182/msInsrdMdctnPrscbInfoService/getInsrdMdctnPrscbInfo"
        params = {"serviceKey":api_key,"type":"json","ediCd":drug_code,"numOfRows":10,"pageNo":1}
        r = requests.get(url, params=params, timeout=API_TIMEOUT)
        r.raise_for_status()
        body = r.json().get("body",{})
        items = body.get("items",[]) or []
        if isinstance(items, dict):
            items = [items] if items else []
        return {"status":"ok","data":items}
    except Exception as e:
        return {"status":"fail","error":str(e)[:80],"data":None}


def api_badge(status: str) -> str:
    if status == "ok":
        return '<span class="api-badge api-ok">● 연동 완료</span>'
    elif status == "fail":
        return '<span class="api-badge api-fail">● 연동 실패</span>'
    return '<span class="api-badge api-skip">● 키 미설정</span>'


# ─────────────────────────────────────────────
# 적응증 → KCD 상병코드 매핑 사전 (내장)
# ─────────────────────────────────────────────
INDICATION_ICD_MAP = [
    {"kw":["폐렴"],"group":"호흡기 감염","codes":[
        {"code":"J18.0","name":"기관지폐렴","benefit":"급여","main":True},
        {"code":"J18.1","name":"대엽성폐렴","benefit":"급여","main":True},
        {"code":"J18.9","name":"상세불명의 폐렴","benefit":"급여","main":False},
    ]},
    {"kw":["상기도감염","인두염","편도","인두"],"group":"상기도 감염","codes":[
        {"code":"J06.9","name":"급성 상기도감염, 상세불명","benefit":"급여","main":True},
        {"code":"J02.9","name":"급성 인두염, 상세불명","benefit":"급여","main":True},
        {"code":"J03.9","name":"급성 편도염, 상세불명","benefit":"급여","main":False},
    ]},
    {"kw":["기관지염","기관지"],"group":"하기도 감염","codes":[
        {"code":"J20.9","name":"급성 기관지염, 상세불명","benefit":"급여","main":True},
        {"code":"J40","name":"기관지염, 급성 또는 만성 상세불명","benefit":"급여","main":False},
    ]},
    {"kw":["중이염","귀"],"group":"귀 감염","codes":[
        {"code":"H66.0","name":"급성 화농성 중이염","benefit":"급여","main":True},
        {"code":"H66.9","name":"상세불명의 화농성 중이염","benefit":"조건부급여","main":False},
        {"code":"H65.0","name":"급성 장액성 중이염","benefit":"급여","main":False},
    ]},
    {"kw":["부비동염","축농증","부비동"],"group":"부비동 감염","codes":[
        {"code":"J01.9","name":"급성 부비동염, 상세불명","benefit":"급여","main":True},
        {"code":"J32.9","name":"만성 부비동염, 상세불명","benefit":"급여","main":False},
    ]},
    {"kw":["요로감염","방광염","요로"],"group":"요로계 감염","codes":[
        {"code":"N39.0","name":"요로감염, 상세불명","benefit":"급여","main":True},
        {"code":"N30.0","name":"급성 방광염","benefit":"급여","main":True},
        {"code":"N30.9","name":"방광염, 상세불명","benefit":"급여","main":False},
    ]},
    {"kw":["신우신염","신우"],"group":"신장 감염","codes":[
        {"code":"N10","name":"급성 세뇨관-간질성 신장염","benefit":"급여","main":True},
        {"code":"N12","name":"세뇨관-간질성 신장염, 상세불명","benefit":"조건부급여","main":False},
    ]},
    {"kw":["피부감염","농가진","봉와직염"],"group":"피부 감염","codes":[
        {"code":"L01.0","name":"농가진","benefit":"급여","main":True},
        {"code":"L03.1","name":"기타 사지의 봉와직염","benefit":"급여","main":False},
        {"code":"L03.9","name":"봉와직염, 상세불명","benefit":"급여","main":False},
    ]},
    {"kw":["소화성궤양","위궤양","십이지장궤양","궤양"],"group":"소화성 궤양","codes":[
        {"code":"K25.9","name":"위궤양, 상세불명","benefit":"급여","main":True},
        {"code":"K26.9","name":"십이지장궤양, 상세불명","benefit":"급여","main":True},
        {"code":"K27.9","name":"위공장궤양, 상세불명","benefit":"급여","main":False},
    ]},
    {"kw":["역류성식도염","위식도역류","역류"],"group":"위식도 역류","codes":[
        {"code":"K21.0","name":"식도염을 동반한 위-식도역류병","benefit":"급여","main":True},
        {"code":"K21.9","name":"식도염이 없는 위-식도역류병","benefit":"급여","main":False},
    ]},
    {"kw":["헬리코박터"],"group":"헬리코박터 감염","codes":[
        {"code":"B96.81","name":"헬리코박터 파이로리의 감염","benefit":"급여","main":True},
    ]},
    {"kw":["대장내시경","장정결","장 정결","내시경 검사","장 세척"],"group":"대장내시경 검사","codes":[
        {"code":"Z12.1","name":"결장의 악성신생물에 대한 특수선별검사",
         "benefit":"급여","main":True,"warning":"선별검진 목적인 경우 적용"},
        {"code":"Z01.8","name":"기타 명시된 특수검사","benefit":"급여","main":False},
        {"code":"R19.4","name":"배변습관의 변화","benefit":"급여","main":False,
         "warning":"증상 기반 내시경인 경우만 적용"},
    ]},
    {"kw":["고혈압"],"group":"고혈압","codes":[
        {"code":"I10","name":"본태성(원발성) 고혈압","benefit":"급여","main":True},
        {"code":"I15.9","name":"상세불명의 이차성 고혈압","benefit":"급여","main":False},
    ]},
    {"kw":["협심증","허혈성 심장"],"group":"허혈성 심장질환","codes":[
        {"code":"I20.9","name":"협심증, 상세불명","benefit":"급여","main":True},
        {"code":"I25.1","name":"죽상경화성 심장병","benefit":"급여","main":False},
    ]},
    {"kw":["심부전"],"group":"심부전","codes":[
        {"code":"I50.0","name":"울혈성 심부전","benefit":"급여","main":True},
        {"code":"I50.9","name":"심부전, 상세불명","benefit":"급여","main":False},
    ]},
    {"kw":["당뇨","혈당","인슐린"],"group":"당뇨병","codes":[
        {"code":"E11.9","name":"인슐린-비의존 당뇨병, 합병증 없음","benefit":"급여","main":True},
        {"code":"E11.8","name":"인슐린-비의존 당뇨병, 명시된 합병증","benefit":"급여","main":False},
        {"code":"E14.9","name":"상세불명 당뇨병, 합병증 없음","benefit":"급여","main":False},
    ]},
    {"kw":["고지혈증","이상지질","콜레스테롤"],"group":"이상지질혈증","codes":[
        {"code":"E78.0","name":"순수 고콜레스테롤혈증","benefit":"급여","main":True},
        {"code":"E78.5","name":"상세불명의 고지혈증","benefit":"급여","main":False},
    ]},
    {"kw":["통증","진통","소염","관절통"],"group":"통증/염증","codes":[
        {"code":"M79.3","name":"연조직 통증 증후군","benefit":"급여","main":True},
        {"code":"M54.5","name":"요통","benefit":"급여","main":False},
        {"code":"M79.1","name":"근육통","benefit":"급여","main":False},
    ]},
    {"kw":["골관절염","퇴행성관절"],"group":"관절염","codes":[
        {"code":"M19.9","name":"상세불명의 관절증","benefit":"급여","main":True},
        {"code":"M17.9","name":"상세불명의 무릎 관절증","benefit":"급여","main":False},
    ]},
    {"kw":["불안","불안장애"],"group":"불안장애","codes":[
        {"code":"F41.1","name":"범불안장애","benefit":"급여","main":True},
        {"code":"F41.9","name":"상세불명의 불안장애","benefit":"급여","main":False},
    ]},
    {"kw":["우울","우울증"],"group":"우울장애","codes":[
        {"code":"F32.9","name":"우울 삽화, 상세불명","benefit":"급여","main":True},
        {"code":"F33.9","name":"반복성 우울장애, 상세불명","benefit":"급여","main":False},
    ]},
    {"kw":["불면","수면장애","불면증"],"group":"수면장애","codes":[
        {"code":"G47.0","name":"수면 개시 및 유지 장애","benefit":"급여","main":True},
        {"code":"F51.0","name":"비기질성 불면증","benefit":"조건부급여","main":False},
    ]},
    {"kw":["갑상선","갑상샘"],"group":"갑상선 질환","codes":[
        {"code":"E03.9","name":"상세불명의 갑상선기능저하증","benefit":"급여","main":True},
        {"code":"E05.9","name":"상세불명의 갑상선중독증","benefit":"급여","main":False},
    ]},
]


def match_icd(indication_text: str, drug_name: str = "") -> list[dict]:
    combined = (indication_text + " " + drug_name).lower()
    result, seen = [], set()
    for entry in INDICATION_ICD_MAP:
        if any(kw.lower() in combined for kw in entry["kw"]):
            codes = [c for c in entry["codes"] if c["code"] not in seen]
            for c in codes:
                seen.add(c["code"])
            if codes:
                result.append({"group": entry["group"], "codes": codes})
    return result


def benefit_pill(b: str) -> str:
    cls = {"급여":"pill pill-green","조건부급여":"pill pill-amber",
           "비급여":"pill pill-red","확인필요":"pill pill-gray"}.get(b,"pill pill-gray")
    return f'<span class="{cls}">{esc(b)}</span>'


def main_pill(is_main: bool) -> str:
    return ('<span class="pill pill-purple">주상병</span>' if is_main
            else '<span class="pill pill-gray">부상병</span>')


# ─────────────────────────────────────────────
# AI - Google Gemini (무료 API)
# ─────────────────────────────────────────────
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL   = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


def ai_ok() -> bool:
    return bool(secret("GEMINI_API_KEY"))


def call_ai(drug: dict, note: str, task: str) -> str:
    gemini_key = secret("GEMINI_API_KEY")
    if not gemini_key:
        return "GEMINI_API_KEY 미설정 — Streamlit Secrets에 키를 입력하면 AI 기능이 활성화됩니다."

    ctx = {
        "약제명": drug.get("name",""),
        "성분명": drug.get("ingredient_display",""),
        "효능효과": drug.get("efficacy",[]),
        "용법용량": drug.get("dosage_official",[]),
        "주의사항": drug.get("cautions",[]),
        "금기사항": drug.get("contraindications",[]),
        "메모": note,
    }
    prompt = (
        "당신은 병원 청구심사 검토를 보조하는 전문가입니다.\n"
        "⚠️ 주의: 급여 인정 확정·진단·처방 판단은 하지 마세요. "
        "담당자가 확인할 사항을 정리하는 메모를 작성하십시오.\n\n"
        f"[작업] {task}\n\n"
        f"[약제 정보]\n{json.dumps(ctx, ensure_ascii=False, indent=2)}\n\n"
        "다음 세 단락으로 한국어로 작성하세요:\n"
        "1. 검토 요약 (3줄 이내)\n"
        "2. 확인 근거 (체크리스트 형태)\n"
        "3. 심사 주의사항"
    )

    try:
        r = requests.post(
            GEMINI_URL,
            params={"key": gemini_key},
            headers={"Content-Type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 1024,
                },
                "safetySettings": [
                    {"category": "HARM_CATEGORY_HARASSMENT",       "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_HATE_SPEECH",      "threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT","threshold": "BLOCK_NONE"},
                    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT","threshold": "BLOCK_NONE"},
                ],
            },
            timeout=30,
        )
        r.raise_for_status()
        d = r.json()
        # Gemini 응답 파싱
        candidates = d.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text","") for p in parts).strip()
            if text:
                return text
        return "Gemini 응답을 파싱할 수 없습니다. 잠시 후 다시 시도하세요."
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 400:
            return "API 키가 올바르지 않습니다. Streamlit Secrets의 GEMINI_API_KEY를 확인하세요."
        if e.response is not None and e.response.status_code == 429:
            return "Gemini 무료 API 호출 한도에 도달했습니다. 잠시 후 다시 시도하세요."
        return f"Gemini 연결 실패: {e}"
    except Exception as e:
        return f"AI 연결 실패 ({e.__class__.__name__}): {e}"


# ─────────────────────────────────────────────
# 렌더: 상병코드 섹션
# ─────────────────────────────────────────────
def render_icd_section(drug: dict, api_key: str) -> None:
    st.markdown('<span id="diagnosis"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown(
            '<div class="sec-eyebrow">INDICATION → ICD MAPPING</div>'
            '<div class="sec-title">📋 적응증 기반 상병코드</div>',
            unsafe_allow_html=True
        )
        st.markdown(
            '<div class="nb nb-warn">⚠️ 상병코드는 의무기록에 기재된 진단·검사목적·증상에 근거해 선택해야 합니다. '
            '이 화면의 후보는 참고용이며 급여 인정을 확정하지 않습니다.</div>',
            unsafe_allow_html=True
        )

        # 적응증 텍스트 수집
        texts = list(drug.get("efficacy", []))
        permit_res = api_drug_permit(drug.get("name",""), api_key)
        eiyak_res  = api_drug_eiyak(drug.get("name",""), api_key)

        if permit_res["status"] == "ok":
            for item in (permit_res["data"] or []):
                t = clean_html(item.get("EE_DOC_DATA","") or item.get("ee_doc_data",""))
                if t: texts.append(t)
        if eiyak_res["status"] == "ok":
            for item in (eiyak_res["data"] or []):
                t = clean_html(item.get("efcyQesitm",""))
                if t: texts.append(t)

        combined = " ".join(texts)
        icd_groups = match_icd(combined, drug.get("name",""))

        # 로컬 DB 후보 추가
        existing = {c["code"] for g in icd_groups for c in g["codes"]}
        extra = []
        for cand in drug.get("diagnosis_candidates",[]):
            if cand.get("code") not in existing:
                extra.append({
                    "code": cand.get("code",""),
                    "name": cand.get("name",""),
                    "benefit": "급여",
                    "main": False,
                    "warning": cand.get("warning",""),
                })
        if extra:
            icd_groups.append({"group":"데이터베이스 등록 후보","codes":extra})

        if not icd_groups:
            st.info("적응증 텍스트에서 매핑 가능한 상병코드를 찾지 못했습니다.")
        else:
            total = sum(len(g["codes"]) for g in icd_groups)
            st.markdown(
                f'<div class="nb nb-ok">✅ 관련 상병코드 <strong>{total}개</strong> 확인 '
                f'(그룹 {len(icd_groups)}개)</div>', unsafe_allow_html=True
            )
            for grp in icd_groups:
                st.markdown(
                    f'<div style="font-size:.8rem;font-weight:800;color:#087f73;'
                    f'text-transform:uppercase;letter-spacing:.07em;margin:.8rem 0 .3rem;">'
                    f'📁 {esc(grp["group"])}</div>', unsafe_allow_html=True
                )
                for c in grp["codes"]:
                    warn_html = (f'<div class="icd-warn">⚠️ {esc(c["warning"])}</div>'
                                 if c.get("warning") else "")
                    st.markdown(f"""
                    <div class="icd-card">
                      <div class="icd-code">{esc(c['code'])}</div>
                      <div class="icd-info">
                        <div class="icd-name">{esc(c['name'])}</div>
                        <div style="margin-top:.3rem;">
                          {benefit_pill(c.get('benefit','확인필요'))}
                          {main_pill(c.get('main',False))}
                        </div>
                        {warn_html}
                      </div>
                    </div>
                    """, unsafe_allow_html=True)

        # 직접 검색
        st.markdown("---")
        st.markdown("**🔍 상병코드 직접 검색 (HIRA 질병정보 API)**")
        c1, c2 = st.columns([5,1])
        kw = c1.text_input("상병명 키워드", placeholder="예: 폐렴, 고혈압, 방광염",
                            key=f"icd-kw-{drug['id']}", label_visibility="collapsed")
        do_srch = c2.button("검색", key=f"icd-btn-{drug['id']}", type="primary", use_container_width=True)
        if do_srch and kw.strip():
            with st.spinner("HIRA 질병정보 조회 중..."):
                res = api_disease_search(kw.strip(), api_key)
            if res["status"] == "ok" and res["data"]:
                for item in res["data"]:
                    code = item.get("disCode","") or item.get("disCd","")
                    name = item.get("disNm","")
                    if code and name:
                        st.markdown(f"""
                        <div class="icd-card">
                          <div class="icd-code">{esc(code)}</div>
                          <div class="icd-info">
                            <div class="icd-name">{esc(name)}</div>
                            <div style="margin-top:.3rem;">
                              <span class="pill pill-blue">API 조회</span>
                            </div>
                          </div>
                        </div>
                        """, unsafe_allow_html=True)
            elif res["status"] == "skip":
                st.caption("API 키 설정 후 직접 검색이 활성화됩니다.")
            else:
                st.warning(f"결과 없음 또는 오류: {res.get('error','')}")

        # Gemini AI 상병 검토
        if ai_ok():
            st.markdown("---")
            st.markdown("**🤖 Gemini AI 보조 상병 검토**")
            note = st.text_area("진료기록 요약 또는 검사 목적",
                                 placeholder="예: 대장암 선별 목적의 대장내시경 예정, 고혈압 진단 후 첫 처방",
                                 key=f"dx-note-{drug['id']}", height=70)
            if st.button("🤖 Gemini AI 상병 검토 생성", key=f"dx-ai-{drug['id']}", type="primary"):
                with st.spinner("Gemini AI 분석 중..."):
                    st.info(call_ai(drug, note, "입력된 진료기록에 부합하는 상병 후보 검토 메모 작성"))
        else:
            st.caption("💡 GEMINI_API_KEY 설정 시 AI 상병 검토가 활성화됩니다.")


# ─────────────────────────────────────────────
# 렌더: 약제 상세 전체
# ─────────────────────────────────────────────
def render_drug_detail(drug: dict, api_key: str) -> None:

    # ── API 데이터 일괄 조회 ──
    with st.spinner("공공 API 데이터 조회 중..."):
        price_res  = api_drug_price(drug.get("name",""), api_key)
        permit_res = api_drug_permit(drug.get("name",""), api_key)
        eiyak_res  = api_drug_eiyak(drug.get("name",""), api_key)
        review_res = api_review_criteria(drug.get("reimbursement_code",""), api_key)

    # ── API 상태 패널 ──
    gemini_status = 'ok' if ai_ok() else 'skip'
    st.markdown(f"""
    <div class="api-panel">
      <div class="ap-title">🔌 공공데이터포털 API 연동 상태 (단일 키)</div>
      <div class="api-row">
        <span class="ap-name">[15054445] 약가기준정보</span>
        {api_badge(price_res['status'])}
        <span style="font-size:.74rem;color:#557068;">상한금액·급여여부</span>
      </div>
      <div class="api-row">
        <span class="ap-name">[15095677] 의약품 허가정보</span>
        {api_badge(permit_res['status'])}
        <span style="font-size:.74rem;color:#557068;">적응증·허가사항</span>
      </div>
      <div class="api-row">
        <span class="ap-name">[15075057] e약은요</span>
        {api_badge(eiyak_res['status'])}
        <span style="font-size:.74rem;color:#557068;">효능·용법·주의·금기</span>
      </div>
      <div class="api-row">
        <span class="ap-name">[15021028] 수가기준정보</span>
        {api_badge(review_res['status'])}
        <span style="font-size:.74rem;color:#557068;">심사기준</span>
      </div>
      <div class="api-row">
        <span class="ap-name">[15119055] 질병정보</span>
        {api_badge('ok' if api_key else 'skip')}
        <span style="font-size:.74rem;color:#557068;">상병코드 직접 검색</span>
      </div>
      <div style="border-top:1px solid #dce8e5;margin:.5rem 0;"></div>
      <div class="api-row">
        <span class="ap-name">🤖 Gemini AI (무료)</span>
        {api_badge(gemini_status)}
        <span style="font-size:.74rem;color:#557068;">상병검토·용법용량 AI 보조</span>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 약가 정보 (API 우선) ──
    price_str  = drug.get("upper_price","공식 목록 확인")
    price_date = drug.get("price_effective_date","-")
    if price_res["status"] == "ok" and price_res["data"]:
        i0 = price_res["data"][0]
        price_str  = i0.get("uprcAmt","") or i0.get("mktPrc","") or price_str
        price_date = i0.get("acptDt","") or i0.get("applyDt","") or price_date

    # ── 약제 헤더 ──
    status_cls = "pill-amber" if any(k in drug.get("status","") for k in ["검토","예시"]) else "pill-green"
    st.markdown(f"""
    <div class="drug-header">
      <div>
        <span class="pill {status_cls}">{esc(drug.get('status',''))}</span>
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
        <div class="lbl">상한금액</div>
        <div class="val hi">{esc(str(price_str))}</div>
      </div>
      <div class="price-item">
        <div class="lbl">적용일</div>
        <div class="val">{esc(str(price_date))}</div>
      </div>
      <div class="price-item">
        <div class="lbl">투여경로</div>
        <div class="val">{esc(drug.get('route','-'))}</div>
      </div>
      <div class="price-item">
        <div class="lbl">약효분류</div>
        <div class="val">{esc(drug.get('category_code','-'))} {esc(drug.get('category_name',''))}</div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(
        '<div class="nb nb-warn">⚠️ 이 서비스는 청구심사 검토 보조용입니다. '
        '급여 인정·진단·처방 판단은 최신 고시·허가사항·공식 시스템과 전문가 검토를 기준으로 하십시오.</div>',
        unsafe_allow_html=True
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

    # ══ 1. 상병코드 ══
    render_icd_section(drug, api_key)

    # ══ 2. 용법용량 ══
    st.markdown('<span id="dosage"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="sec-eyebrow">DOSAGE · AI ASSIST</div>'
                    '<div class="sec-title">💊 용법용량</div>', unsafe_allow_html=True)
        if eiyak_res["status"] == "ok" and eiyak_res["data"]:
            val = clean_html(eiyak_res["data"][0].get("useMethodQesitm",""))
            if val:
                st.markdown(f'<span class="api-badge api-ok">● e약은요 API 실시간</span>',
                            unsafe_allow_html=True)
                st.info(val[:600])
        if permit_res["status"] == "ok" and permit_res["data"]:
            ud = clean_html(permit_res["data"][0].get("UD_DOC_DATA","") or
                            permit_res["data"][0].get("ud_doc_data",""))
            if ud:
                with st.expander("📡 식약처 허가정보 용법용량 전문"):
                    st.write(ud[:800])
        st.markdown("**📋 등록 데이터**")
        for item in drug.get("dosage_official",[]): st.markdown(f"- {item}")
        st.markdown("**🤖 AI 체크리스트**")
        for item in drug.get("dosage_ai_checklist",[]): st.markdown(f"- {item}")
        if ai_ok():
            if st.button("🤖 Gemini AI 용법용량 검토 생성", key=f"dose-ai-{drug['id']}", type="primary"):
                with st.spinner("Gemini AI 검토 중..."):
                    st.info(call_ai(drug, "", "투여 전 확인 체크리스트 및 청구심사 주의사항 작성"))
        else:
            st.caption("💡 GEMINI_API_KEY 설정 시 AI 보조 검토가 활성화됩니다.")

    # ══ 3. 효능효과 ══
    st.markdown('<span id="efficacy"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="sec-eyebrow">INDICATIONS & EFFICACY</div>'
                    '<div class="sec-title">✅ 효능효과</div>', unsafe_allow_html=True)
        if eiyak_res["status"] == "ok" and eiyak_res["data"]:
            val = clean_html(eiyak_res["data"][0].get("efcyQesitm",""))
            if val:
                st.markdown(f'<span class="api-badge api-ok">● e약은요 API</span>',
                            unsafe_allow_html=True)
                st.markdown(f"> {val[:500]}")
        if permit_res["status"] == "ok" and permit_res["data"]:
            ee = clean_html(permit_res["data"][0].get("EE_DOC_DATA","") or
                            permit_res["data"][0].get("ee_doc_data",""))
            if ee:
                with st.expander("📡 식약처 허가정보 효능효과 전문"):
                    st.write(ee[:1000])
        st.markdown("**📋 등록 효능효과**")
        for item in drug.get("efficacy",[]): st.markdown(f"- {item}")

    # ══ 4. 심사참고자료 ══
    st.markdown('<span id="review"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="sec-eyebrow">CLAIM REVIEW REFERENCES</div>'
                    '<div class="sec-title">📌 심사참고자료</div>', unsafe_allow_html=True)
        if review_res["status"] == "ok" and review_res["data"]:
            st.markdown(f'<span class="api-badge api-ok">● HIRA 수가기준 API 연동</span>',
                        unsafe_allow_html=True)
            with st.expander("심사기준 API 원문"):
                for item in review_res["data"][:3]: st.json(item)
        refs = drug.get("review_references",[])
        if refs:
            for ref in refs:
                lvl = ref.get("level","보조")
                short = "필수" if "필수" in lvl else ("공식" if "공식" in lvl else "보조")
                st.markdown(f"""
                <div class="ref-card ref-{short}">
                  <div style="font-weight:800;color:#152622;font-size:.92rem;">{esc(ref.get('title',''))}</div>
                  <div style="font-size:.87rem;color:#3a5550;margin-top:.3rem;">{esc(ref.get('body',''))}</div>
                  <div style="margin-top:.4rem;">
                    <span class="pill {'pill-red' if short=='필수' else ('pill-blue' if short=='보조' else 'pill-green')}">{esc(lvl)}</span>
                  </div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.caption("ℹ️ 등록된 심사참고자료가 없습니다.")

    # ══ 5. 동일성분 ══
    st.markdown('<span id="same"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="sec-eyebrow">SAME INGREDIENT PRODUCTS</div>'
                    '<div class="sec-title">🔄 동일성분약제</div>', unsafe_allow_html=True)
        same_list = drug.get("same_ingredient",[])
        if same_list:
            cols = st.columns(min(3, len(same_list)))
            for i, s in enumerate(same_list):
                with cols[i % len(cols)]:
                    st.markdown(f"""
                    <div class="same-card">
                      <div style="font-weight:800;color:#152622;">{esc(s.get('name',''))}</div>
                      <div style="font-family:monospace;font-size:.82rem;color:#087f73;margin:.15rem 0;">
                        코드: {esc(s.get('code',''))}</div>
                      <div style="font-size:.82rem;color:#557068;">{esc(s.get('note',''))}</div>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.caption("ℹ️ 공식 데이터 연계 후 동일성분 제품이 표시됩니다.")

    # ══ 6. 배수처방 ══
    st.markdown('<span id="multiple"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="sec-eyebrow">MULTIPLE PRESCRIPTION REVIEW</div>'
                    '<div class="sec-title">✖️ 배수처방 검토</div>', unsafe_allow_html=True)
        items = drug.get("multiple_prescription",[])
        if items:
            for item in items: st.markdown(f"- {item}")
        else:
            st.caption("ℹ️ 등록된 배수처방 기준이 없습니다.")

    # ══ 7. 주의사항 ══
    st.markdown('<span id="caution"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="sec-eyebrow">CAUTIONS</div>'
                    '<div class="sec-title">⚠️ 주의사항</div>', unsafe_allow_html=True)
        if eiyak_res["status"] == "ok" and eiyak_res["data"]:
            item = eiyak_res["data"][0]
            for field, label in [("atpnWarnQesitm","경고"),("atpnQesitm","주의"),("intrcQesitm","상호작용")]:
                val = clean_html(item.get(field,""))
                if val:
                    st.markdown(f'<span class="api-badge api-ok">● API · {label}</span>',
                                unsafe_allow_html=True)
                    st.markdown(f"> {val[:400]}")
        st.markdown("**📋 등록 주의사항**")
        for item in drug.get("cautions",[]): st.markdown(f"- {item}")

    # ══ 8. 금기사항 ══
    st.markdown('<span id="contra"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="sec-eyebrow">CONTRAINDICATIONS</div>'
                    '<div class="sec-title">🚫 금기사항</div>', unsafe_allow_html=True)
        if eiyak_res["status"] == "ok" and eiyak_res["data"]:
            val = clean_html(eiyak_res["data"][0].get("seQesitm",""))
            if val:
                st.markdown(f'<span class="api-badge api-ok">● API · 부작용/금기</span>',
                            unsafe_allow_html=True)
                st.markdown(f"> {val[:400]}")
        st.markdown("**📋 등록 금기사항**")
        for item in drug.get("contraindications",[]): st.markdown(f"- {item}")
        st.markdown(
            '<div class="nb nb-danger">🚫 최종 금기·상호작용 판단은 최신 허가사항 원문 및 HIRA DUR 결과를 기준으로 하십시오.</div>',
            unsafe_allow_html=True
        )

    # ══ 9. 출처 ══
    st.markdown('<span id="source"></span>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown('<div class="sec-eyebrow">EVIDENCE & SOURCES</div>'
                    '<div class="sec-title">📎 자료 출처</div>', unsafe_allow_html=True)
        for src in drug.get("sources",[]):
            st.markdown(f"""
            <div class="source-row">
              <div class="src-sec">{esc(src.get('section',''))}</div>
              <div>{esc(src.get('publisher',''))} ·
                <a href="{esc(src.get('url',''))}" target="_blank">{esc(src.get('title',''))}</a>
                <span style="color:#557068;font-size:.8rem;"> (확인일 {esc(src.get('checked_on',''))})</span>
              </div>
            </div>
            """, unsafe_allow_html=True)
        st.caption("운영 시 허가사항·급여목록·고시 개정일을 주기적으로 동기화하고 변경 이력을 보존하십시오.")


# ─────────────────────────────────────────────
# 페이지: 약제 검색
# ─────────────────────────────────────────────
def page_search(api_key: str) -> None:
    st.markdown("""
    <div class="hero">
      <h1>💊 약제 심사 지원 리포트</h1>
      <p>약품명 · 성분명 · 급여코드로 검색 → 공공 API 실시간 데이터 + 적응증 기반 상병코드를 한 화면에서 검토합니다.</p>
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns([7,1])
    query = c1.text_input("검색", value=st.session_state.get("query",""),
                           placeholder="예: 씨엠쿨산, 폴리에틸렌글리콜, 648602750",
                           label_visibility="collapsed")
    c2.button("검색", type="primary", use_container_width=True)
    st.session_state.query = query

    results = find_drugs(query) if query.strip() else []
    if query.strip():
        st.caption(f"검색 결과 **{len(results)}건**")
        if not results:
            st.info("일치하는 약제가 없습니다.")
        for drug in results:
            col_info, col_btn = st.columns([6,1])
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
            with col_btn:
                if st.button("상세 보기", key=f"open-{drug['id']}", use_container_width=True):
                    st.session_state.selected_drug = drug["id"]
                    log_select(drug, query)  # ★ query 인자 전달
                    st.rerun()

    selected_id = st.session_state.get("selected_drug")
    if selected_id:
        selected = load_drug(selected_id)
        if selected:
            st.divider()
            render_drug_detail(selected, api_key)


# ─────────────────────────────────────────────
# 페이지: 검색 순위
# ─────────────────────────────────────────────
def page_ranking() -> None:
    st.header("📊 약제 검색 순위")
    st.caption("상세 보기 클릭 기준 집계 · 환자식별정보 저장 없음")
    t1, t2, t3 = st.tabs(["실시간 (24h)","주간 (7일)","월간 (30일)"])
    for tab, hours in [(t1,24),(t2,168),(t3,720)]:
        with tab:
            df = get_ranking(hours)
            if df.empty:
                st.info("아직 집계된 기록이 없습니다.")
            else:
                df.insert(0,"순위",range(1,len(df)+1))
                st.dataframe(df, hide_index=True, use_container_width=True)


# ─────────────────────────────────────────────
# 페이지: API 설정 안내
# ─────────────────────────────────────────────
def page_api_guide() -> None:
    st.header("🔌 API 설정 가이드")
    st.markdown("""
    ### 핵심: 공공데이터포털 API 키는 1개입니다

    공공데이터포털(data.go.kr)에서 하나의 계정으로 5개 API를 신청하면
    **동일한 인증키 1개**로 모든 API를 사용할 수 있습니다.
    """)

    st.markdown(
        '<div class="nb nb-ok">✅ HIRA API · 식약처 API 구분 없이 '
        '<strong>공공데이터포털 인증키 1개</strong>로 모두 연동됩니다.</div>',
        unsafe_allow_html=True
    )

    apis = [
        ("약가기준정보","15054445","HIRA","상한금액·급여여부"),
        ("질병정보서비스","15119055","HIRA","KCD 상병코드 검색"),
        ("수가기준정보","15021028","HIRA","진료행위 심사기준"),
        ("의약품 제품 허가정보","15095677","식약처","적응증·허가사항"),
        ("의약품개요정보(e약은요)","15075057","식약처","효능·용법·주의·금기"),
    ]
    for name, num, org, desc in apis:
        st.markdown(f"""
        <div class="ref-card ref-공식" style="margin-bottom:.4rem;">
          <div style="font-weight:800;color:#152622;">{name}
            <span style="font-family:monospace;font-weight:400;color:#087f73;font-size:.85rem;"> #{num}</span>
          </div>
          <div style="font-size:.86rem;color:#3a5550;margin-top:.2rem;">
            기관: <strong>{org}</strong> &nbsp;|&nbsp; 제공: {desc}
          </div>
        </div>
        """, unsafe_allow_html=True)

    # ── Gemini AI 안내 ──
    st.markdown("### 🤖 AI 기능 (Google Gemini 무료)")
    st.markdown(
        '<div class="nb nb-info">ℹ️ AI 상병 검토·용법용량 분석은 <strong>Google Gemini 무료 API</strong>를 사용합니다. '
        '월 사용량 한도 내에서 무료로 이용할 수 있습니다.</div>',
        unsafe_allow_html=True
    )
    st.markdown(f"""
    <div class="ref-card ref-공식" style="margin-bottom:.4rem;">
      <div style="font-weight:800;color:#152622;">Google Gemini API
        <span style="font-family:monospace;font-weight:400;color:#087f73;font-size:.85rem;"> gemini-2.0-flash</span>
      </div>
      <div style="font-size:.86rem;color:#3a5550;margin-top:.2rem;">
        발급: <a href="https://aistudio.google.com" target="_blank">aistudio.google.com</a>
        &nbsp;|&nbsp; 무료 티어 사용 가능 &nbsp;|&nbsp; 상병 검토·용법 분석·심사 메모 생성
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    # ── Secrets 설정 ──
    st.markdown("### Streamlit Cloud Secrets 설정")
    st.markdown(
        '<div class="nb nb-warn">⚠️ API 키는 절대 코드나 GitHub에 올리지 마세요. '
        'Streamlit Cloud Secrets에만 입력하세요.</div>',
        unsafe_allow_html=True
    )
    st.code("""\
# Streamlit Cloud → 앱 Settings → Secrets 탭에 붙여넣기

# ① 공공데이터포털 인증키 (data.go.kr 마이페이지에서 확인)
PUBLIC_DATA_API_KEY = "여기에_공공데이터포털_인증키_입력"

# ② Google Gemini API 키 (aistudio.google.com에서 발급)
GEMINI_API_KEY = "여기에_Gemini_API_키_입력"

# ③ 관리자 비밀번호
ADMIN_PASSWORD = "여기에_관리자_비밀번호_입력"
""", language="toml")

    st.markdown("### Streamlit Cloud 설정 순서")
    st.markdown("""
1. [share.streamlit.io](https://share.streamlit.io) → 본인 앱 클릭
2. 우측 하단 **⋮** → **Settings** 클릭
3. **Secrets** 탭 클릭
4. 위 내용을 붙여넣고 실제 키 값 입력 후 **Save**
5. 앱 자동 재시작 → 사이드바에서 ✅ 확인
    """)

    st.markdown(
        '<div class="nb nb-info">ℹ️ 공공데이터포털 API 키 확인: '
        '<a href="https://www.data.go.kr" target="_blank">www.data.go.kr</a> → '
        '로그인 → 마이페이지 → 개발계정 → 인증키 발급현황</div>',
        unsafe_allow_html=True
    )


# ─────────────────────────────────────────────
# 페이지: 관리자
# ─────────────────────────────────────────────

# ─────────────────────────────────────────────
# CSV 컬럼 정의 (엑셀 작성 기준)
# ─────────────────────────────────────────────
CSV_COLUMNS = [
    "약품명",           # name
    "성분명",           # ingredient_display
    "급여코드",         # reimbursement_code
    "표준코드",         # standard_code
    "상한금액",         # upper_price
    "적용일",           # price_effective_date
    "제조사",           # manufacturer
    "투여경로",         # route  (경구 / 주사 / 외용 등)
    "약효분류코드",     # category_code
    "약효분류명",       # category_name
    "전문일반구분",     # professional
    "상태",             # status
    "요약",             # summary
    "효능효과",         # efficacy  (줄바꿈 | 로 구분)
    "용법용량",         # dosage_official (| 구분)
    "AI체크리스트",     # dosage_ai_checklist (| 구분)
    "주의사항",         # cautions (| 구분)
    "금기사항",         # contraindications (| 구분)
    "배수처방",         # multiple_prescription (| 구분)
    "동일성분약제명",   # same_ingredient[*].name (| 구분)
    "동일성분코드",     # same_ingredient[*].code (| 구분)
    "심사참고제목",     # review_references[*].title (| 구분)
    "심사참고내용",     # review_references[*].body  (| 구분)
    "심사참고레벨",     # review_references[*].level (| 구분)
]

SAMPLE_ROWS = [
    {
        "약품명": "씨엠쿨산",
        "성분명": "폴리에틸렌글리콜3350·전해질·아스코르브산 복합제",
        "급여코드": "648602750",
        "표준코드": "8806486027515",
        "상한금액": "9,290원 / 2000mL / 통",
        "적용일": "2026-01-01",
        "제조사": "씨엠지제약",
        "투여경로": "경구",
        "약효분류코드": "721",
        "약효분류명": "X선조영제",
        "전문일반구분": "전문의약품",
        "상태": "검토 필요",
        "요약": "대장 내시경 검사 전 장 정결에 사용되는 복합 산제입니다.",
        "효능효과": "대장 내시경 검사 전 장 정결을 목적으로 사용되는 장정결제입니다.|장내 삼투압을 높여 수분을 유지하고 변 배출을 돕습니다.",
        "용법용량": "18세 이상 성인 기준 총 2L 복용합니다.|분할 복용 시 검사 전날 저녁 1L + 당일 아침 1L를 복용합니다.",
        "AI체크리스트": "검사 예정 시각과 전처치 방식을 확인합니다.|신장·심장 질환 위험 환자는 의료진이 검토합니다.",
        "주의사항": "투여 초기 복부 팽만·복통이 나타날 수 있습니다.|탈수·전해질 이상 위험 환자는 처방 전 평가가 필요합니다.",
        "금기사항": "소화관 폐색 또는 천공이 있거나 의심되는 환자는 투여 금지입니다.|이 약 구성성분에 과민반응이 있는 환자는 투여 금지입니다.",
        "배수처방": "검사 1회에 필요한 처방 단위와 실제 검사 건을 대조합니다.|반복 처방 시 사유와 시행일을 기록에서 확인합니다.",
        "동일성분약제명": "맥스쿨산|크린콜씨산",
        "동일성분코드": "621802470|664102450",
        "심사참고제목": "청구 전 확인 포인트|DUR 연계",
        "심사참고내용": "검사 시행 여부, 처방 기록, 검사일과 투약일 연계를 확인하십시오.|환자 투약이력 및 금기 점검은 HIRA DUR 결과를 기준으로 확인하십시오.",
        "심사참고레벨": "필수 확인|공식 시스템 확인",
    },
    {
        "약품명": "케이캡정25밀리그램",
        "성분명": "테고프라잔 25mg",
        "급여코드": "640007800",
        "표준코드": "",
        "상한금액": "",
        "적용일": "",
        "제조사": "에이치케이이노엔(주)",
        "투여경로": "경구",
        "약효분류코드": "232",
        "약효분류명": "소화성궤양용제",
        "전문일반구분": "전문의약품",
        "상태": "참고 예시",
        "요약": "위산 분비 억제제(P-CAB 계열)로 역류성 식도염·위궤양 등에 사용합니다.",
        "효능효과": "역류성 식도염 치료|위궤양 치료|헬리코박터 제균 요법(병용)",
        "용법용량": "1일 1회 25mg 또는 50mg 경구 투여합니다.|식사와 관계없이 복용 가능합니다.",
        "AI체크리스트": "적응증·함량·투여기간 및 급여기준 적용 여부를 확인합니다.",
        "주의사항": "중증 간장애 환자는 신중 투여합니다.",
        "금기사항": "이 약 성분에 과민반응 환자는 투여 금지입니다.",
        "배수처방": "최신 심사기준 확인 필요합니다.",
        "동일성분약제명": "",
        "동일성분코드": "",
        "심사참고제목": "",
        "심사참고내용": "",
        "심사참고레벨": "",
    },
    {
        "약품명": "아목시실린캡슐250mg",
        "성분명": "아목시실린 250mg",
        "급여코드": "670700ATB",
        "표준코드": "",
        "상한금액": "",
        "적용일": "",
        "제조사": "샘플제약",
        "투여경로": "경구",
        "약효분류코드": "611",
        "약효분류명": "주로 그람양성균에 작용하는 것",
        "전문일반구분": "전문의약품",
        "상태": "검토 필요",
        "요약": "페니실린계 광범위 항생제로 상기도감염·중이염·요로감염 등에 사용합니다.",
        "효능효과": "폐렴|상기도감염|급성 중이염|요로감염|피부 및 연조직 감염",
        "용법용량": "성인 1회 250~500mg을 1일 3회 경구 투여합니다.|중증 감염 시 1회 500mg 1일 3회 투여합니다.",
        "AI체크리스트": "페니실린 과민반응 이력을 반드시 확인합니다.|신기능 저하 환자는 용량 조절이 필요합니다.",
        "주의사항": "페니실린계 항생제 과민반응 환자에서 신중 투여합니다.|장기 투여 시 내성균 및 비감수성균 발현에 주의합니다.",
        "금기사항": "페니실린계 항생제에 과민반응 병력이 있는 환자는 투여 금지입니다.",
        "배수처방": "감염 부위 및 중증도에 따른 용량·기간 기준을 확인합니다.",
        "동일성분약제명": "아모크신캡슐|오구멘틴정(복합제)",
        "동일성분코드": "670700ATB|670700BNB",
        "심사참고제목": "항생제 적정 사용|세균 배양검사",
        "심사참고내용": "항생제 처방 시 감염 부위·원인균·중증도를 확인하십시오.|세균 배양 및 감수성 검사 결과와 연계하여 검토합니다.",
        "심사참고레벨": "필수 확인|보조",
    },
]


def make_sample_csv() -> bytes:
    df = pd.DataFrame(SAMPLE_ROWS, columns=CSV_COLUMNS)
    return df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def csv_row_to_drug(row: pd.Series, idx: int) -> tuple[dict | None, list[str]]:
    """CSV 한 행 → drug dict 변환. 오류 목록도 반환"""
    errs = []

    def col(name: str) -> str:
        return str(row.get(name, "") or "").strip()

    def split_pipe(name: str) -> list[str]:
        val = col(name)
        return [x.strip() for x in val.split("|") if x.strip()] if val else []

    name = col("약품명")
    ingr = col("성분명")
    if not name:
        errs.append(f"{idx}행: 약품명 누락")
    if not ingr:
        errs.append(f"{idx}행: 성분명 누락")
    if errs:
        return None, errs

    # ID 자동 생성 (급여코드 우선, 없으면 약품명 해시)
    code = col("급여코드")
    drug_id = re.sub(r"[^a-z0-9]", "-", (code or name).lower())[:40]

    # 동일성분 리스트
    same_names = split_pipe("동일성분약제명")
    same_codes = split_pipe("동일성분코드")
    same_ingredient = [
        {"name": n, "code": c, "note": "동일성분 보조 조회 결과입니다. HIRA 약가목록을 재확인하세요."}
        for n, c in zip(same_names, same_codes + [""] * len(same_names))
    ]

    # 심사참고 리스트
    ref_titles  = split_pipe("심사참고제목")
    ref_bodies  = split_pipe("심사참고내용")
    ref_levels  = split_pipe("심사참고레벨")
    review_references = [
        {"title": t, "body": b, "level": lv}
        for t, b, lv in zip(
            ref_titles,
            ref_bodies  + [""] * len(ref_titles),
            ref_levels  + ["보조"] * len(ref_titles),
        )
    ]

    drug = {
        "id": drug_id,
        "name": name,
        "ingredient_display": ingr,
        "reimbursement_code": code,
        "standard_code": col("표준코드"),
        "upper_price": col("상한금액"),
        "price_effective_date": col("적용일"),
        "manufacturer": col("제조사"),
        "route": col("투여경로") or "경구",
        "category_code": col("약효분류코드"),
        "category_name": col("약효분류명"),
        "professional": col("전문일반구분") or "전문의약품",
        "status": col("상태") or "검토 필요",
        "verified_on": datetime.now().strftime("%Y-%m-%d"),
        "summary": col("요약"),
        "efficacy": split_pipe("효능효과"),
        "dosage_official": split_pipe("용법용량"),
        "dosage_ai_checklist": split_pipe("AI체크리스트"),
        "cautions": split_pipe("주의사항"),
        "contraindications": split_pipe("금기사항"),
        "multiple_prescription": split_pipe("배수처방"),
        "same_ingredient": same_ingredient,
        "review_references": review_references,
        "diagnosis_candidates": [],
        "sources": [],
        "ingredients": [ingr],
    }
    return drug, []


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

    # ── 샘플 CSV 다운로드 ──
    st.subheader("📥 샘플 양식 다운로드")
    st.markdown(
        '<div class="nb nb-info">ℹ️ 아래 샘플 CSV를 내려받아 <strong>엑셀</strong>에서 열고 약제 정보를 입력한 뒤 '
        '<strong>CSV UTF-8 형식</strong>으로 저장해서 업로드하세요.</div>',
        unsafe_allow_html=True
    )

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="📄 샘플 CSV 다운로드 (씨엠쿨산·케이캡·아목시실린 예시 포함)",
            data=make_sample_csv(),
            file_name="claimlens_약제입력_샘플.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.divider()

    # ── CSV 컬럼 안내 ──
    with st.expander("📋 CSV 컬럼 작성 가이드 보기"):
        guide_data = {
            "컬럼명": [
                "약품명","성분명","급여코드","표준코드","상한금액","적용일",
                "제조사","투여경로","약효분류코드","약효분류명","전문일반구분","상태","요약",
                "효능효과","용법용량","AI체크리스트","주의사항","금기사항","배수처방",
                "동일성분약제명","동일성분코드",
                "심사참고제목","심사참고내용","심사참고레벨",
            ],
            "필수여부": ["✅필수","✅필수","권장","선택","선택","선택",
                        "권장","선택","선택","선택","선택","선택","선택",
                        "권장","권장","선택","권장","권장","선택",
                        "선택","선택","선택","선택","선택"],
            "작성 방법": [
                "약품 정식 명칭","성분명 및 함량","HIRA 급여코드","바코드 표준코드","예: 9,290원/통","예: 2026-01-01",
                "제조·수입사명","경구/주사/외용 등","예: 232","예: 소화성궤양용제","전문의약품 또는 일반의약품","검토 필요 / 확인 완료 등","한 줄 요약",
                "여러 항목은 | 로 구분","여러 항목은 | 로 구분","여러 항목은 | 로 구분","여러 항목은 | 로 구분","여러 항목은 | 로 구분","여러 항목은 | 로 구분",
                "여러 약제는 | 로 구분","동일성분약제명과 순서 맞춰 | 구분",
                "여러 항목은 | 로 구분","심사참고제목과 순서 맞춰 | 구분","필수 확인 / 보조 / 공식 시스템 확인",
            ],
        }
        st.dataframe(pd.DataFrame(guide_data), hide_index=True, use_container_width=True)

        st.markdown("""
**| 구분 예시:**
```
효능효과 컬럼:  폐렴|상기도감염|요로감염
용법용량 컬럼:  1일 3회 250mg 투여합니다.|중증 시 500mg으로 증량합니다.
동일성분약제명: 아모크신캡슐|오구멘틴정
동일성분코드:   670700ATB|670700BNB   ← 약제명과 같은 순서로 입력
```
        """)

    st.divider()

    # ── CSV 업로드 ──
    st.subheader("📤 약제 CSV 업로드")
    st.markdown(
        '<div class="nb nb-warn">⚠️ 업로드 전 허가사항·급여목록·고시 최신 여부를 반드시 확인하십시오. '
        '업로드 즉시 DB에 반영됩니다.</div>',
        unsafe_allow_html=True
    )

    uploaded = st.file_uploader(
        "CSV 파일 선택 (UTF-8 또는 UTF-8 BOM 저장)",
        type=["csv"],
        help="엑셀에서 '다른 이름으로 저장' → 'CSV UTF-8(쉼표로 분리)' 선택"
    )

    if uploaded:
        try:
            # 인코딩 자동 감지 (UTF-8 BOM / UTF-8 / EUC-KR 순)
            raw = uploaded.getvalue()
            for enc in ["utf-8-sig", "utf-8", "euc-kr"]:
                try:
                    df = pd.read_csv(pd.io.common.BytesIO(raw), encoding=enc, dtype=str)
                    break
                except Exception:
                    continue
            else:
                raise ValueError("파일 인코딩을 인식할 수 없습니다. UTF-8로 저장 후 다시 시도하세요.")

            df = df.fillna("")
            st.markdown(f"**미리보기** ({len(df)}행)")
            st.dataframe(df.head(5), use_container_width=True)

            # 필수 컬럼 체크
            missing_cols = [c for c in ["약품명","성분명"] if c not in df.columns]
            if missing_cols:
                st.error(f"필수 컬럼 누락: {', '.join(missing_cols)}")
            else:
                if st.button("✅ 검증 후 DB 반영", type="primary"):
                    records, all_errs = [], []
                    for i, row in df.iterrows():
                        drug, errs = csv_row_to_drug(row, i+2)
                        if errs:
                            all_errs.extend(errs)
                        elif drug:
                            records.append(drug)

                    if all_errs:
                        st.error("오류가 있는 행:\n" + "\n".join(all_errs))
                    if records:
                        with get_conn() as conn:
                            n = _upsert(conn, records)
                        st.success(f"✅ {n}개 약제가 DB에 반영됐습니다!")
                        st.balloons()

        except Exception as e:
            st.error(f"파일 처리 오류: {e}")

    st.divider()

    # ── 현재 DB 약제 목록 ──
    st.subheader("📋 현재 등록된 약제 목록")
    with get_conn() as conn:
        df_db = pd.read_sql_query(
            "SELECT name AS 약품명, ingredient_display AS 성분명, "
            "reimbursement_code AS 급여코드, manufacturer AS 제조사, updated_at AS 업데이트일시 "
            "FROM drugs ORDER BY updated_at DESC",
            conn
        )
    if df_db.empty:
        st.info("등록된 약제가 없습니다.")
    else:
        st.dataframe(df_db, hide_index=True, use_container_width=True)
        # 현재 DB 전체 CSV 다운로드
        st.download_button(
            "📥 현재 DB 전체 CSV로 내려받기",
            data=df_db.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig"),
            file_name="claimlens_현재DB목록.csv",
            mime="text/csv",
        )


# ─────────────────────────────────────────────
# 사이드바
# ─────────────────────────────────────────────
def sidebar_nav() -> tuple[str, str]:
    st.sidebar.markdown("""
    <div style="padding:.8rem 0 .3rem;">
      <div class="brand-logo">Claim<span>Lens</span></div>
      <div class="brand-sub">병원 청구심사 약제 지원센터 v2</div>
    </div>
    """, unsafe_allow_html=True)

    page = st.sidebar.radio(
        "메뉴", ["💊 약제 검색","📊 검색 순위","🔌 API 설정","🔐 관리자"],
        label_visibility="collapsed"
    )

    st.sidebar.divider()
    api_key    = secret("PUBLIC_DATA_API_KEY")
    gemini_key = secret("GEMINI_API_KEY")

    # API 상태
    st.sidebar.markdown("**🔑 API 키 상태**")
    if api_key:
        st.sidebar.markdown("✅ 공공데이터포털 API : 설정됨")
    else:
        st.sidebar.markdown("❌ 공공데이터포털 API : 미설정")
        st.sidebar.caption("🔌 API 설정 메뉴에서 확인하세요")
    if gemini_key:
        st.sidebar.markdown("✅ AI(Gemini) : 설정됨")
    else:
        st.sidebar.markdown("❌ AI(Gemini) : 미설정 (선택)")

    st.sidebar.divider()
    st.sidebar.markdown("**📋 데이터 운영 원칙**")
    st.sidebar.caption(
        "허가사항: MFDS 기준\n\n급여·심사: HIRA 기준\n\n금기 점검: DUR 결과 우선\n\n상병코드: KCD-8 기준"
    )
    st.sidebar.markdown("`Beta · 내부 검토용`")

    return page, api_key


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
def main() -> None:
    init_db()
    inject_css()
    page, api_key = sidebar_nav()

    if page == "💊 약제 검색":
        page_search(api_key)
    elif page == "📊 검색 순위":
        page_ranking()
    elif page == "🔌 API 설정":
        page_api_guide()
    else:
        page_admin()


if __name__ == "__main__":
    main()
