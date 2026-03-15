"""
네이버 데이터랩 트렌드 기반 블로그 자동 작성기 (Streamlit UI)
- 1단계: 데이터랩 대분류 급상승 탐지
- 2단계: Gemini로 구체적 세부 주제 추출
- 3단계: SEO 블로그 글 생성 (사진 위치 포함) + 한국 테마 사진 자동 매칭
- 4단계: 글+사진 합본 미리보기 & 한번에 복사
"""

import streamlit as st
from streamlit_autorefresh import st_autorefresh
import sch_state
import json
import os
import re
import base64
import requests
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from dotenv import load_dotenv
import google.generativeai as genai
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")
UNSPLASH_ACCESS_KEY = os.getenv("UNSPLASH_ACCESS_KEY", "")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")
NAVER_BLOG_ID = os.getenv("NAVER_BLOG_ID", "")

IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blog_images")
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
os.makedirs(IMG_DIR, exist_ok=True)


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=4)


def get_next_hyperlink() -> dict:
    """하이퍼링크를 순환 반환하고 인덱스 저장"""
    cfg = load_config()
    links = cfg.get("hyperlinks", [])
    if not links:
        return {"keyword": "탐정사무소", "url": "https://kspdplus.co.kr/"}
    idx = cfg.get("link_index", 0) % len(links)
    cfg["link_index"] = (idx + 1) % len(links)
    save_config(cfg)
    return links[idx]

TOPIC_POOL = {
    "부동산": ["아파트", "전세", "부동산", "청약", "분양"],
    "주식투자": ["주식", "코스피", "삼성전자", "ETF", "배당주"],
    "건강식품": ["다이어트", "영양제", "건강식품", "체중감량", "홍삼"],
    "여행": ["제주도", "해외여행", "국내여행", "항공권", "숙박"],
    "맛집": ["맛집", "카페", "음식점", "배달음식", "인스타맛집"],
    "육아": ["육아", "어린이집", "유치원", "아기", "출산"],
    "취업": ["취업", "채용", "자기소개서", "이직", "공무원"],
    "패션뷰티": ["화장품", "스킨케어", "패션", "옷", "뷰티"],
    "자동차": ["전기차", "자동차", "중고차", "SUV", "자동차보험"],
    "금융대출": ["대출", "금리", "적금", "예금", "카드혜택"],
    "반려동물": ["강아지", "고양이", "반려동물", "펫", "동물병원"],
    "게임": ["게임", "롤", "모바일게임", "PC게임", "신작게임"],
    "공연문화": ["콘서트", "뮤지컬", "전시회", "영화", "드라마"],
    "스포츠": ["야구", "축구", "프로야구", "골프", "운동"],
    "날씨재난": ["날씨", "미세먼지", "태풍", "폭염", "한파"],
    "IT기술": ["AI", "챗GPT", "스마트폰", "노트북", "앱"],
    "요리레시피": ["레시피", "요리", "집밥", "간단요리", "저녁메뉴"],
    "인테리어": ["인테리어", "가구", "셀프인테리어", "소품", "청소"],
    "교육학습": ["수능", "영어공부", "자격증", "온라인강의", "독서"],
    "의료건강": ["병원", "건강검진", "다이어트약", "탈모", "피부과"],
}

BLOG_STYLES = {
    "일상 공감형": "친한 친구에게 말하듯 편하게, 본인 경험 위주로 서술. '~했거든요', '~더라고요' 체를 쓰고, 솔직한 감정과 실수담도 넣어서 공감을 이끌어냄",
    "정보 전달형": "핵심 정보를 깔끔하게 전달하되 딱딱하지 않게. 실제로 써본 후기나 비교 경험을 섞어서 신뢰감을 줌. 수치나 구체적 사례 포함",
    "후기 리뷰형": "직접 체험한 사람의 시점으로 장단점을 솔직하게 서술. 기대했던 것 vs 실제 차이, 아쉬운 점도 가감 없이 작성",
    "트렌드 분석형": "요즘 왜 이게 뜨는지 나름의 분석과 해석을 담아 작성. 주변 사례, 데이터, 개인 관찰을 엮어서 읽는 재미를 줌",
}


# ─────────────────────────────────────────────
# API 함수
# ─────────────────────────────────────────────

def query_datalab(keyword_groups, start_date, end_date, time_unit="date"):
    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json",
    }
    body = {"startDate": start_date, "endDate": end_date, "timeUnit": time_unit, "keywordGroups": keyword_groups[:5]}
    resp = requests.post(url, headers=headers, data=json.dumps(body))
    resp.raise_for_status()
    return resp.json()


def search_naver_news(query, display=10):
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    params = {"query": query, "display": display, "sort": "date"}
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    items = resp.json().get("items", [])
    return [{"title": re.sub(r"<.*?>", "", it["title"]).replace("&amp;", "&").replace("&quot;", '"'),
             "description": re.sub(r"<.*?>", "", it["description"]).replace("&amp;", "&").replace("&quot;", '"'),
             "link": it["link"]} for it in items]


# 저작권 문제가 있는 언론사/뉴스 도메인 - 이 도메인의 이미지는 제외
NEWS_DOMAINS = {
    "imgnews.naver.net", "news.naver.com",
    "yna.co.kr", "yonhapnews.co.kr", "yonhapnewstv.co.kr",
    "chosun.com", "donga.com", "joins.com", "joongang.co.kr",
    "hankyung.com", "mk.co.kr", "sedaily.com", "hankookilbo.com",
    "khan.co.kr", "ohmynews.com", "pressian.com",
    "kbs.co.kr", "mbc.co.kr", "sbs.co.kr", "jtbc.co.kr", "tvchosun.com",
    "ytn.co.kr", "mbn.co.kr", "channela.co.kr",
    "newsis.com", "news1.kr", "newspim.com", "edaily.co.kr",
    "heraldcorp.com", "mt.co.kr", "etnews.com", "zdnet.co.kr",
    "sportschosun.com", "sports.chosun.com", "osen.co.kr",
    "isplus.com", "xportsnews.com", "enews24.net",
}


def is_news_image(url: str) -> bool:
    """URL이 언론사 이미지인지 판별"""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        # 서브도메인 포함 체크 (예: imgnews.naver.net)
        return any(host == d or host.endswith("." + d) for d in NEWS_DOMAINS)
    except Exception:
        return False


def search_naver_images(query, display=15):
    """네이버 이미지 검색 API - 언론사 이미지 자동 제외"""
    url = "https://openapi.naver.com/v1/search/image"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    # display를 넉넉히 받아서 필터링 후 남은 것 사용
    params = {"query": query, "display": display, "sort": "sim", "filter": "large"}
    try:
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        results = []
        for p in resp.json().get("items", []):
            link = p.get("link", "")
            thumb = p.get("thumbnail", "")
            if not link:
                continue
            if is_news_image(link):
                continue  # 언론사 이미지 제외
            results.append({
                "id": f"naver_{abs(hash(link))}",
                "source": "Naver",
                "url_medium": thumb or link,
                "url_large": link,
                "alt": re.sub(r"<.*?>", "", p.get("title", "")),
                "photographer": "세상소식 전하는 더원플러스 탐정사무소",
                "color": "#eee",
            })
        return results
    except Exception:
        return []


def search_unsplash(query, per_page=4):
    """Unsplash API - fallback"""
    if not UNSPLASH_ACCESS_KEY:
        return []
    url = "https://api.unsplash.com/search/photos"
    headers = {"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"}
    params = {"query": query, "per_page": per_page, "orientation": "landscape"}
    try:
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return [{"id": f"unsplash_{p['id']}", "source": "Unsplash",
                 "url_medium": p["urls"]["regular"],
                 "url_large": p["urls"]["full"],
                 "alt": p.get("alt_description", ""),
                 "photographer": p["user"]["name"],
                 "color": p.get("color", "#eee")} for p in resp.json().get("results", [])]
    except Exception:
        return []


def search_pexels(query, per_page=4):
    """Pexels API - fallback"""
    if not PEXELS_API_KEY:
        return []
    url = "https://api.pexels.com/v1/search"
    headers = {"Authorization": PEXELS_API_KEY}
    params = {"query": query, "per_page": per_page, "locale": "ko-KR"}
    try:
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return [{"id": f"pexels_{p['id']}", "source": "Pexels",
                 "url_medium": p["src"]["medium"],
                 "url_large": p["src"]["large"],
                 "alt": p.get("alt", ""),
                 "photographer": p["photographer"],
                 "color": p.get("avg_color", "#eee")} for p in resp.json().get("photos", [])]
    except Exception:
        return []


def search_all_sources(query, per_source=4):
    """네이버 이미지 우선, 없으면 Unsplash -> Pexels fallback"""
    results = search_naver_images(query, display=per_source * 2)
    if not results:
        results = search_unsplash(query, per_source)
    if not results:
        results = search_pexels(query, per_source)
    return results


def download_photo(url, filename):
    filepath = os.path.join(IMG_DIR, filename)
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
        return filepath
    except Exception:
        return None


# ─────────────────────────────────────────────
# 1단계: 데이터랩 트렌드
# ─────────────────────────────────────────────

def get_trending_topics(selected_categories=None):
    today = datetime.now()
    recent_end = today.strftime("%Y-%m-%d")
    recent_start = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    prev_start = (today - timedelta(days=28)).strftime("%Y-%m-%d")
    prev_end = (today - timedelta(days=8)).strftime("%Y-%m-%d")

    if selected_categories:
        topics = [{"groupName": n, "keywords": TOPIC_POOL[n]} for n in selected_categories if n in TOPIC_POOL]
    else:
        topics = [{"groupName": n, "keywords": kws} for n, kws in TOPIC_POOL.items()]

    scores = {}
    for i in range(0, len(topics), 5):
        batch = topics[i:i + 5]
        try:
            recent_data = query_datalab(batch, recent_start, recent_end)
            prev_data = query_datalab(batch, prev_start, prev_end)
        except Exception as e:
            st.warning(f"데이터랩 오류 (배치 {i // 5 + 1}): {e}")
            continue
        for j, result in enumerate(recent_data.get("results", [])):
            name = result["title"]
            r_avg = sum(d["ratio"] for d in result["data"]) / max(len(result["data"]), 1)
            p_avg = 0
            if j < len(prev_data.get("results", [])):
                p_avg = sum(d["ratio"] for d in prev_data["results"][j]["data"]) / max(len(prev_data["results"][j]["data"]), 1)
            surge = (r_avg / p_avg) if p_avg > 0 else r_avg
            scores[name] = {"recent_avg": round(r_avg, 2), "prev_avg": round(p_avg, 2),
                            "surge_ratio": round(surge, 2), "keywords": batch[j]["keywords"], "daily_data": result["data"]}

    return [{"topic": n, **d} for n, d in sorted(scores.items(), key=lambda x: x[1]["surge_ratio"], reverse=True)]


# ─────────────────────────────────────────────
# 2단계: 세부 주제 추출
# ─────────────────────────────────────────────

def collect_news(keywords):
    all_news, seen = [], set()
    for kw in keywords[:3]:
        try:
            for n in search_naver_news(kw, 7):
                if n["title"] not in seen:
                    seen.add(n["title"])
                    all_news.append(n)
        except Exception:
            continue
    return all_news


def extract_detailed_topics(category_name, keywords, news_list=None):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")
    today = datetime.now().strftime("%Y년 %m월 %d일")

    news_section = ""
    if news_list:
        news_section = "\n[참고: 최신 뉴스]\n"
        for i, n in enumerate(news_list[:15], 1):
            news_section += f"{i}. {n['title']} - {n['description'][:80]}\n"

    prompt = f"""오늘은 {today}입니다.
'{category_name}' 카테고리에서 네이버 검색량이 급상승 중입니다.
관련 키워드: {', '.join(keywords)}
{news_section}
지금 네이버 블로그에 쓰면 검색 유입이 많을 매우 구체적인 글 주제 5개를 제안하세요.

[규칙]
- 대분류 금지. "스포츠"(X) -> "2026 KBO 개막전 팀별 우승 전망과 신인 분석"(O)
- {today} 기준 시의성 있는 주제
- 각 주제의 SEO 키워드 3~5개
- 각 소제목에 맞는 네이버 이미지 검색용 한국어 키워드 4개 (구체적이고 명확하게, 예: "프로야구 개막전 경기장", "선수 훈련 장면")

[출력 형식 - 파이프 구분, 5줄만]
1번|구체적 주제|지금 써야 하는 이유|SEO키워드1,SEO키워드2,SEO키워드3|사진키워드1,사진키워드2,사진키워드3,사진키워드4

다른 텍스트 없이 5줄만 출력."""

    response = model.generate_content(prompt)
    return parse_topics(response.text)


def parse_topics(text):
    topics = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|")
        if len(parts) >= 4:
            photo_kws = [k.strip() for k in parts[4].split(",")] if len(parts) >= 5 else []
            topics.append({
                "title": parts[1].strip(),
                "reason": parts[2].strip(),
                "seo_keywords": [k.strip() for k in parts[3].strip().split(",")],
                "photo_keywords": photo_kws,
            })
    return topics[:5]


# ─────────────────────────────────────────────
# 3단계: 블로그 글 생성 (사진 위치 포함)
# ─────────────────────────────────────────────

def build_prompt(detailed_topic, category, style_name, style_desc, custom_angle, word_count, extra_keywords, news_ctx):
    today = datetime.now().strftime("%Y년 %m월 %d일")
    seo_kws = ", ".join(detailed_topic["seo_keywords"])

    news_ref = ""
    if news_ctx:
        news_ref = "\n[참고 뉴스]\n" + "".join(f"- {n['title']}: {n['description'][:80]}\n" for n in news_ctx[:8])

    angle = f"\n글의 핵심 각도: {custom_angle}\n" if custom_angle and custom_angle.strip() else ""
    extra = f"\n추가 SEO 키워드 (2회 이상 포함): {extra_keywords}\n" if extra_keywords and extra_keywords.strip() else ""

    prompt = f"""당신은 월 방문자 5만 이상의 네이버 파워블로거입니다.
오늘은 {today}입니다.

[글 주제] {detailed_topic['title']}
[써야 하는 이유] {detailed_topic['reason']}
[핵심 SEO 키워드] {seo_kws}
[카테고리] {category}
{news_ref}{angle}{extra}
[글쓰기 스타일: {style_name}]
{style_desc}

[사진 삽입 규칙 - 매우 중요]
- 소제목(###) 바로 다음 줄에 반드시 [사진N] 태그를 넣어주세요
- 구조 예시:
  ### 소제목1
  [사진1]
  본문 내용...

  ### 소제목2
  [사진2]
  본문 내용...

  ### 소제목3
  [사진3]
  본문 내용...

  ### 소제목4
  [사진4]
  본문 내용...
- 태그는 반드시 별도 줄에 단독으로 작성
- [사진1]은 첫 번째 소제목 아래 (썸네일용)

[네이버 SEO 규칙]
1. 제목: 핵심 키워드 앞배치, 30자 이내
2. 본문 첫 2줄에 핵심 키워드 포함
3. 소제목(###)에 검색 키워드 포함
4. 핵심 키워드 본문에서 5~8회 반복
5. 해시태그 12개 이상

[금지]
- 이모지 금지
- "~알아보겠습니다", "~살펴보겠습니다" 금지
- "첫째, 둘째, 셋째" 나열 금지
- "결론적으로", "요약하자면" 금지
- 뻔한 서론 금지, 구체적 장면으로 시작
- 거짓 정보 금지

[자연스러움]
- 짧은 문장과 긴 문장 교차
- 접속사 다양하게 (그런데, 사실, 솔직히, 어쨌든)
- 톤 변화 (진지 -> 가벼움 -> 진지)
- "저도 잘 몰랐는데", "의외였어요" 같은 인간미

[분량] {word_count}자 내외, 소제목 3~4개

제목부터 시작:"""
    return prompt


def generate_blog(prompt):
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")
    text = model.generate_content(prompt).text
    # 마크다운 이스케이프 제거: \# → #, \* → * 등
    text = re.sub(r'\\#', '#', text)
    text = re.sub(r'\\\*', '*', text)
    text = re.sub(r'\\_', '_', text)
    return text


# ─────────────────────────────────────────────
# 4단계: 글+사진 합본 HTML 생성
# ─────────────────────────────────────────────

def fetch_photos_for_blog(photo_keywords, category, blog_title=""):
    """소제목별 사진 키워드 + 블로그 제목 조합, 언론사 제외 후 부족하면 쿼리 변형"""
    photos = {}
    title_hint = blog_title[:10].strip() if blog_title else ""

    for i, kw in enumerate(photo_keywords[:4], 1):
        results = []

        # 1차: 제목 힌트 + 키워드 조합
        combined = f"{title_hint} {kw}".strip() if title_hint else kw
        results = search_naver_images(combined, display=20)

        # 2차: 키워드만 단독 검색
        if not results:
            results = search_naver_images(kw, display=20)

        # 3차: 카테고리 + 키워드 조합
        if not results and category:
            results = search_naver_images(f"{category} {kw}", display=20)

        # 4차: fallback (Unsplash, Pexels)
        if not results:
            results = search_unsplash(kw, per_page=4) or search_pexels(kw, per_page=4)

        if results:
            photos[f"[사진{i}]"] = results[0]
    return photos


def build_combined_html(blog_text, photos, hyperlink: dict = None):
    """블로그 글의 [사진N] 태그를 실제 이미지로 치환한 HTML 생성"""
    if hyperlink is None:
        hyperlink = {"keyword": "탐정사무소", "url": "https://kspdplus.co.kr/"}
    lines = blog_text.split("\n")
    html_parts = []
    html_parts.append("""<div style="max-width:720px; margin:0 auto; font-family:'Noto Sans KR',sans-serif; line-height:1.9; color:#333; font-size:16px;">""")
    kw = hyperlink["keyword"]
    url = hyperlink["url"]
    html_parts.append(f'<p style="margin:0 0 16px 0;">세상소식을 전하는 <a href="{url}" target="_blank" style="color:#03C75A; text-decoration:none; font-weight:bold; font-size:38px;">{kw}</a> 입니다.</p>')

    for line in lines:
        stripped = line.strip()

        # [사진N] 태그 처리
        photo_match = re.match(r'\[사진(\d+)\]', stripped)
        if photo_match:
            tag = f"[사진{photo_match.group(1)}]"
            if tag in photos:
                photo = photos[tag]
                html_parts.append(f"""
<div style="text-align:center; margin:24px 0;">
  <img src="{photo['url_large']}" alt="{photo.get('alt','')}" style="max-width:100%; border-radius:8px; box-shadow:0 2px 8px rgba(0,0,0,0.1);" />
  <p style="font-size:12px; color:#999; margin-top:6px;">{photo['photographer']}</p>
</div>""")
            continue

        # 제목 (## 또는 # → border-left 버티컬 바, Naver 호환)
        if stripped.startswith("## ") or stripped.startswith("# "):
            title_text = re.sub(r'^#+\s*', '', stripped).replace("**", "")
            html_parts.append(f'<p style="border-left:5px solid #03C75A; padding:6px 0 6px 12px; margin:32px 0 12px; font-size:19px; font-weight:bold; color:#111; line-height:1.4;">{title_text}</p>')
        elif stripped.startswith("### "):
            sub_text = stripped.replace("### ", "").replace("**", "")
            html_parts.append(f'<p style="border-left:4px solid #aaaaaa; padding:4px 0 4px 10px; margin:24px 0 8px; font-size:16px; font-weight:bold; color:#333; line-height:1.4;">{sub_text}</p>')
        elif stripped.startswith("#"):
            # 해시태그
            html_parts.append(f'<span style="display:inline-block; background:#f0f0f0; color:#666; padding:4px 10px; margin:3px; border-radius:12px; font-size:13px;">{stripped}</span>')
        elif stripped.startswith("**") and stripped.endswith("**"):
            bold_text = stripped.strip("*")
            html_parts.append(f'<p style="border-left:4px solid #aaaaaa; padding:4px 0 4px 10px; margin:24px 0 8px; font-size:16px; font-weight:bold; color:#333; line-height:1.4;">{bold_text}</p>')
        elif stripped.startswith("---"):
            html_parts.append('<hr style="border:none; border-top:1px solid #eee; margin:20px 0;" />')
        elif stripped == "":
            html_parts.append('<br />')
        else:
            # 인라인 볼드 처리
            processed = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', stripped)
            html_parts.append(f'<p style="margin:8px 0;">{processed}</p>')

    html_parts.append("</div>")
    return "\n".join(html_parts)


# ─────────────────────────────────────────────
# 전체 자동 파이프라인
# ─────────────────────────────────────────────

UPLOADER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "naver_uploader.py")
UPLOAD_DATA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upload_data.json")


def _prepare_upload(blog_text, photos, hyperlink, log):
    """업로드용 JSON 파일 생성 후 경로 반환"""
    image_paths = {}
    for tag in ["[사진1]", "[사진2]", "[사진3]", "[사진4]"]:
        if tag in photos:
            photo = photos[tag]
            num = re.search(r'\d+', tag).group()
            fpath = download_photo(photo["url_large"], f"upload_photo_{num}_{photo['id']}.jpg")
            if fpath:
                image_paths[f"___IMAGE_{num}___"] = fpath

    html_content = build_combined_html(blog_text, photos, hyperlink)
    html_no_img = html_content
    for num in ["1", "2", "3", "4"]:
        html_no_img = re.sub(
            r'<div[^>]*text-align:center[^>]*>.*?</div>',
            f'___IMAGE_{num}___', html_no_img, count=1, flags=re.DOTALL
        )
    html_no_img = re.sub(r'<p[^>]*>세상소식을 전하는.*?</p>', '', html_no_img, flags=re.DOTALL)

    first_line = re.sub(r'[#*`]', '', blog_text.split('\n')[0]).strip()
    cfg = load_config()
    blog_id = cfg.get("BLOG_ID", NAVER_BLOG_ID)

    # 업로드 파일명: 충돌 방지용 타임스탬프
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    upload_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upload_queue")
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, f"upload_data_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "title": first_line,
            "html_content": html_no_img,
            "blog_id": blog_id,
            "image_paths": image_paths,
            "hyperlink": hyperlink,
        }, f, ensure_ascii=False, indent=2)
    return path


def run_full_pipeline(style_name="친근한 이웃 블로거", word_count=1500,
                      custom_angle="", extra_keywords="", log_fn=None,
                      hyperlink: dict = None, topic_override: dict = None):
    """단건 STEP1~3 + 업로드. hyperlink/topic_override 지정 시 해당 값 사용."""
    def log(msg):
        ts = datetime.now().strftime("%H:%M:%S")
        full = f"[{ts}] {msg}"
        print(full)
        if log_fn:
            log_fn(full)
    try:
        if topic_override is None:
            log("STEP1: 데이터랩 트렌드 분석 중...")
            trending = get_trending_topics()
            if not trending:
                log("STEP1 실패")
                return False
            top = trending[0]
            log(f"STEP1 완료: [{top['topic']}] {top['surge_ratio']}배")

            log("STEP2: 세부 주제 추출 중...")
            news = collect_news(top["keywords"])
            detailed = extract_detailed_topics(top["topic"], top["keywords"], news or None)
            if not detailed:
                log("STEP2 실패")
                return False
            chosen = detailed[0]
            category = top["topic"]
        else:
            chosen = topic_override["topic"]
            category = topic_override["category"]
            news = topic_override.get("news", [])
            log(f"주제 재사용: [{chosen['title']}]")

        if hyperlink is None:
            hyperlink = get_next_hyperlink()

        log(f"STEP3: 글 생성 중... (하이퍼링크: [{hyperlink['keyword']}])")
        style_desc = BLOG_STYLES.get(style_name, list(BLOG_STYLES.values())[0])
        prompt = build_prompt(chosen, category, style_name, style_desc,
                              custom_angle, word_count, extra_keywords, news[:8])
        blog_text = generate_blog(prompt)
        photos = fetch_photos_for_blog(chosen.get("photo_keywords", []), category,
                                       blog_title=chosen["title"])
        log(f"STEP3 완료: {len(blog_text.replace(' ','').replace(chr(10),''))}자, 사진 {len(photos)}장")

        log("업로드 준비 중...")
        data_path = _prepare_upload(blog_text, photos, hyperlink, log)

        log("네이버 업로드 실행...")
        proc = subprocess.Popen([sys.executable, UPLOADER_PATH, data_path])
        proc.wait()  # 완료까지 대기
        log("업로드 완료.")
        return True
    except Exception as e:
        log(f"오류: {e}")
        return False


def run_all_hyperlinks_pipeline(style_name="친근한 이웃 블로거", word_count=1500,
                                 custom_angle="", extra_keywords="", log_fn=None,
                                 gap_seconds=60):
    """하이퍼링크 N개 × 트렌드 상위 N개 카테고리 → 카테고리별 다른 주제로 순차 발행."""
    import time as _time

    def log(msg):
        ts = datetime.now().strftime("%H:%M:%S")
        full = f"[{ts}] {msg}"
        print(full)
        if log_fn:
            log_fn(full)
    try:
        cfg = load_config()
        hyperlinks = cfg.get("hyperlinks", [])
        if not hyperlinks:
            log("하이퍼링크 목록이 비어 있습니다.")
            return False
        total = len(hyperlinks)

        # STEP1: 트렌드 전체 카테고리 확보
        log(f"STEP1: 데이터랩 트렌드 분석 중...")
        trending = get_trending_topics()
        if not trending:
            log("STEP1 실패")
            return False

        log(f"STEP1 완료: {len(trending)}개 카테고리 분석")
        for i, t in enumerate(trending[:total]):
            log(f"  {i+1}위. [{t['topic']}] 상승률 {t['surge_ratio']}배")

        # 카테고리 풀: 상위 N개를 랜덤 셔플 → 실행마다 다른 조합
        import random
        pool = trending[:max(total, len(trending))]
        random.shuffle(pool)
        log(f"\n이번 실행 카테고리 순서: {' → '.join(t['topic'] for t in pool[:total])}")

        # STEP2: 각 카테고리별 세부 주제 1개씩 미리 추출
        log("\nSTEP2: 카테고리별 세부 주제 추출 중...")
        plan = []  # [{"hyperlink", "category", "topic", "news"}]
        for i, hl in enumerate(hyperlinks):
            cat = pool[i % len(pool)]
            log(f"  [{i+1}/{total}] [{cat['topic']}] 주제 추출 중...")
            news = collect_news(cat["keywords"])
            detailed = extract_detailed_topics(cat["topic"], cat["keywords"], news or None)
            if not detailed:
                log(f"    → 추출 실패, 건너뜀")
                continue
            topic = detailed[0]
            plan.append({
                "hyperlink": hl,
                "category": cat["topic"],
                "topic": topic,
                "news": news,
            })
            log(f"    → {topic['title']}")

        if not plan:
            log("모든 주제 추출 실패")
            return False

        log(f"\nSTEP2 완료: 총 {len(plan)}건 준비됨")
        log("\n발행 계획:")
        for i, p in enumerate(plan):
            log(f"  {i+1}. [{p['hyperlink']['keyword']}] / {p['category']} / {p['topic']['title']}")

        # STEP3 + 업로드: 순차 실행
        for i, p in enumerate(plan):
            log(f"\n{'='*45}")
            log(f"[{i+1}/{len(plan)}] 발행 시작")
            log(f"  카테고리: {p['category']}")
            log(f"  주제: {p['topic']['title']}")
            log(f"  링크: [{p['hyperlink']['keyword']}] → {p['hyperlink']['url']}")
            log(f"{'='*45}")

            override = {"topic": p["topic"], "category": p["category"], "news": p["news"]}
            ok = run_full_pipeline(
                style_name=style_name, word_count=word_count,
                custom_angle=custom_angle, extra_keywords=extra_keywords,
                log_fn=log_fn, hyperlink=p["hyperlink"], topic_override=override,
            )
            if not ok:
                log(f"[{i+1}번] 실패, 다음으로 계속...")

            if i < len(plan) - 1:
                log(f"다음 발행까지 {gap_seconds}초 대기...")
                _time.sleep(gap_seconds)

        log(f"\n전체 {len(plan)}건 발행 완료!")

        # 발행된 URL 수집 후 backlink.py 실행
        _trigger_backlink(log)
        return True
    except Exception as e:
        log(f"오류: {e}")
        return False


def _trigger_backlink(log_fn=None):
    """published_urls.json → configbacklink.json start_urls 업데이트 → backlink.py 실행"""
    def log(msg):
        ts = datetime.now().strftime("%H:%M:%S")
        full = f"[{ts}] {msg}"
        print(full)
        if log_fn:
            log_fn(full)

    url_log = os.path.join(BASE_DIR, "published_urls.json")
    backlink_cfg = os.path.join(BASE_DIR, "configbacklink.json")
    backlink_py  = os.path.join(BASE_DIR, "backlink.py")

    if not os.path.exists(url_log):
        log("[백링크] published_urls.json 없음. 건너뜀.")
        return
    if not os.path.exists(backlink_py):
        log("[백링크] backlink.py 없음. 건너뜀.")
        return

    try:
        with open(url_log, encoding="utf-8") as f:
            published = json.load(f)
        new_urls = [p["url"] for p in published if p.get("url")]
        if not new_urls:
            log("[백링크] 발행된 URL 없음.")
            return

        # configbacklink.json start_urls 업데이트
        cfg = {}
        if os.path.exists(backlink_cfg):
            with open(backlink_cfg, encoding="utf-8") as f:
                cfg = json.load(f)

        # 기존 URL + 새 URL 합산 (중복 제거, 최신 50개 유지)
        existing = cfg.get("start_urls", [])
        merged = list(dict.fromkeys(new_urls + existing))[:50]
        cfg["start_urls"] = merged
        with open(backlink_cfg, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        log(f"[백링크] configbacklink.json start_urls {len(merged)}개 업데이트")

        # backlink.py 백그라운드 실행
        import subprocess as _sp
        proc = _sp.Popen(
            [sys.executable, backlink_py],
            cwd=BASE_DIR,
            creationflags=0x00000008,  # DETACHED_PROCESS (Windows)
        )
        sch_state.backlink_proc = proc
        log("[백링크] backlink.py 백그라운드 실행 시작!")

    except Exception as e:
        log(f"[백링크] 오류: {e}")


# ─────────────────────────────────────────────
# 스케줄러 (싱글톤)
# ─────────────────────────────────────────────

_scheduler = None
_scheduler_lock = threading.Lock()

# ── 스케줄러 전역 상태 (스레드 ↔ UI 공유)
# 스케줄러 상태는 sch_state 모듈에서 관리 (Streamlit 재실행 시 초기화 방지)

def get_scheduler():
    global _scheduler
    with _scheduler_lock:
        if _scheduler is None:
            _scheduler = BackgroundScheduler(timezone="Asia/Seoul")
            _scheduler.start()
    return _scheduler


def rebuild_schedule(times: list[str], enabled: bool):
    """스케줄 재설정. times = ['09:00', '18:00'] 형식"""
    sch = get_scheduler()
    sch.remove_all_jobs()
    if not enabled:
        return
    for t in times:
        try:
            h, m = t.strip().split(":")
            sch.add_job(
                run_full_pipeline,
                CronTrigger(hour=int(h), minute=int(m), timezone="Asia/Seoul"),
                id=f"auto_blog_{h}_{m}",
                replace_existing=True,
            )
        except Exception as e:
            print(f"스케줄 추가 오류 ({t}): {e}")


# ─────────────────────────────────────────────
# Streamlit UI
# ─────────────────────────────────────────────

def main():
    st.set_page_config(page_title="네이버 블로그 자동 작성기", layout="wide")
    st.title("네이버 데이터랩 블로그 작성기")
    st.caption("트렌드 탐지 -> 세부 주제 추출 -> 글+사진 자동 합본 -> 복사해서 바로 붙여넣기")

    with st.sidebar:
        st.header("설정")
        st.subheader("1. 카테고리")
        use_all = st.checkbox("전체 카테고리 분석", value=True)
        selected_cats = []
        if not use_all:
            selected_cats = st.multiselect("분석할 카테고리", list(TOPIC_POOL.keys()), default=list(TOPIC_POOL.keys())[:5])

        st.subheader("2. 글쓰기 스타일")
        style_name = st.selectbox("문체 선택", list(BLOG_STYLES.keys()))

        st.subheader("3. 글 분량")
        word_count = st.slider("목표 글자수", 800, 3000, 1500, step=100)

        st.subheader("4. 커스텀 설정")
        custom_angle = st.text_input("글의 핵심 각도 (선택)", placeholder="예: 직장인 퇴근 후 시점")
        extra_keywords = st.text_input("추가 SEO 키워드", placeholder="예: 2026년, 추천, 꿀팁")

        st.markdown("---")
        st.subheader("5. 사진 소스")
        st.success("Naver 이미지 검색 (기본)")
        sources_extra = []
        if UNSPLASH_ACCESS_KEY:
            sources_extra.append("Unsplash")
        if PEXELS_API_KEY:
            sources_extra.append("Pexels")
        if sources_extra:
            st.caption(f"fallback: {', '.join(sources_extra)}")

    # 메인 영역
    tab_auto, tab_pipeline, tab_preview, tab_schedule = st.tabs([
        "자동 실행", "수동 파이프라인", "미리보기 & 복사", "스케줄러"
    ])

    # ===== 자동 실행 탭 =====
    with tab_auto:
        st.subheader("자동 실행")

        cfg_auto = load_config()
        links_auto = cfg_auto.get("hyperlinks", [])
        idx_auto = cfg_auto.get("link_index", 0)

        col_a, col_b = st.columns(2)
        with col_a:
            auto_style = st.selectbox("문체", list(BLOG_STYLES.keys()), key="auto_style")
            auto_words = st.slider("글자수", 800, 3000, 1500, step=100, key="auto_words")
        with col_b:
            auto_angle = st.text_input("핵심 각도 (선택)", key="auto_angle",
                                        placeholder="예: 직장인 30대 시점")
            auto_keywords = st.text_input("추가 SEO 키워드 (선택)", key="auto_kw",
                                           placeholder="예: 2026년, 추천")
            gap_sec = st.number_input("발행 간격 (초)", min_value=10, max_value=600,
                                       value=60, step=10, key="auto_gap")

        st.markdown("---")

        # 하이퍼링크 현황 표시
        if links_auto:
            st.markdown("**하이퍼링크 발행 순서**")
            cols = st.columns(len(links_auto))
            for i, lk in enumerate(links_auto):
                with cols[i]:
                    is_next = (i == idx_auto % len(links_auto))
                    border = "border:2px solid #03C75A;" if is_next else "border:1px solid #ddd;"
                    bg = "background:#f0fff4;" if is_next else "background:#fafafa;"
                    label = "다음" if is_next else f"{i+1}번"
                    st.markdown(
                        f'<div style="{border}{bg}border-radius:8px;padding:8px;text-align:center;font-size:13px;">'
                        f'<b>{label}</b><br>{lk["keyword"]}<br>'
                        f'<span style="color:#888;font-size:11px;">{lk["url"][:30]}...</span></div>',
                        unsafe_allow_html=True
                    )

        st.markdown("")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("단건 실행 (다음 링크 1개)", type="primary", key="btn_single"):
                log_box = st.empty()
                logs = []
                def _log_s(msg):
                    logs.append(msg)
                    log_box.code("\n".join(logs[-25:]))
                with st.spinner("실행 중..."):
                    ok = run_full_pipeline(
                        style_name=auto_style, word_count=auto_words,
                        custom_angle=auto_angle, extra_keywords=auto_keywords,
                        log_fn=_log_s,
                    )
                st.success("완료!") if ok else st.error("오류 발생, 로그 확인")

        with c2:
            if st.button(f"전체 일괄 실행 ({len(links_auto)}건)", type="primary", key="btn_all"):
                log_box2 = st.empty()
                logs2 = []
                def _log_a(msg):
                    logs2.append(msg)
                    log_box2.code("\n".join(logs2[-30:]))
                with st.spinner(f"전체 {len(links_auto)}건 순차 발행 중..."):
                    ok = run_all_hyperlinks_pipeline(
                        style_name=auto_style, word_count=auto_words,
                        custom_angle=auto_angle, extra_keywords=auto_keywords,
                        log_fn=_log_a, gap_seconds=int(gap_sec),
                    )
                st.success(f"전체 {len(links_auto)}건 완료!") if ok else st.error("오류 발생")

    with tab_pipeline:
        step1, step2, step3 = st.columns([1, 1, 1])

        # ===== STEP 1 =====
        with step1:
            st.subheader("STEP 1. 대분류 트렌드")
            if st.button("데이터랩 조회", type="primary", width="stretch"):
                with st.spinner("분석 중..."):
                    trending = get_trending_topics(None if use_all else selected_cats)
                if trending:
                    st.session_state["trending"] = trending
                    for k in ["detailed_topics", "selected_detail", "news_context", "blog_text", "combined_html", "blog_photos"]:
                        st.session_state.pop(k, None)
                else:
                    st.error("조회 실패")

            if "trending" in st.session_state:
                for i, t in enumerate(st.session_state["trending"][:10], 1):
                    s = t["surge_ratio"]
                    bar = "|" * min(int(s * 3), 30)
                    rank = f" [{i}위]" if i <= 3 else ""
                    st.text(f"{i:>2}. {t['topic']:<8} {s:>5.1f}배 {bar}{rank}")

                import pandas as pd
                chart = {}
                for t in st.session_state["trending"][:3]:
                    for d in t["daily_data"]:
                        chart.setdefault(d["period"], {})[t["topic"]] = d["ratio"]
                if chart:
                    df = pd.DataFrame.from_dict(chart, orient="index")
                    df.index = pd.to_datetime(df.index)
                    st.line_chart(df.sort_index(), height=180)

                st.markdown("---")
                opts = [f"{t['topic']} ({t['surge_ratio']}배)" for t in st.session_state["trending"]]
                idx = st.selectbox("세부 분석할 카테고리", range(len(opts)), format_func=lambda x: opts[x])
                st.session_state["sel_cat_idx"] = idx

        # ===== STEP 2 =====
        with step2:
            st.subheader("STEP 2. 세부 주제 추출")
            if "trending" not in st.session_state:
                st.info("STEP 1 먼저")
            else:
                cat = st.session_state["trending"][st.session_state.get("sel_cat_idx", 0)]
                st.markdown(f"**{cat['topic']}** 세부 분석")

                if st.button("세부 주제 추출", type="primary", width="stretch"):
                    with st.spinner("뉴스 수집 시도..."):
                        news = collect_news(cat["keywords"])
                    st.session_state["news_context"] = news
                    st.caption(f"뉴스 {len(news)}건" if news else "Gemini 자체 지식 사용")

                    with st.spinner("Gemini 분석 중..."):
                        detailed = extract_detailed_topics(cat["topic"], cat["keywords"], news or None)
                    if detailed:
                        st.session_state["detailed_topics"] = detailed
                        st.session_state["detail_category"] = cat["topic"]
                        for k in ["blog_text", "combined_html", "blog_photos"]:
                            st.session_state.pop(k, None)
                    else:
                        st.error("추출 실패")

                if "detailed_topics" in st.session_state:
                    st.markdown("---")
                    topics = st.session_state["detailed_topics"]
                    for i, dt in enumerate(topics):
                        st.markdown(f"**{i+1}. {dt['title']}**")
                        st.caption(dt["reason"])
                        st.caption(f"SEO: {', '.join(dt['seo_keywords'])}")

                    sel = st.radio("주제 선택", range(len(topics)), format_func=lambda x: topics[x]["title"])
                    st.session_state["selected_detail"] = topics[sel]

        # ===== STEP 3 =====
        with step3:
            st.subheader("STEP 3. 글+사진 생성")
            if "selected_detail" not in st.session_state:
                st.info("STEP 2 먼저")
            else:
                detail = st.session_state["selected_detail"]
                category = st.session_state.get("detail_category", "")
                st.markdown(f"**{detail['title']}**")

                if st.button("글 + 사진 한번에 생성", type="primary", width="stretch"):
                    news_ctx = st.session_state.get("news_context", [])

                    # 글 생성
                    prompt = build_prompt(detail, category, style_name, BLOG_STYLES[style_name],
                                          custom_angle, word_count, extra_keywords, news_ctx)
                    with st.spinner("Gemini 글 생성 중..."):
                        try:
                            blog_text = generate_blog(prompt)
                            st.session_state["blog_text"] = blog_text
                        except Exception as e:
                            st.error(f"글 생성 오류: {e}")
                            blog_text = None

                    # 사진 검색
                    if blog_text:
                        with st.spinner("한국 테마 사진 검색 중..."):
                            photo_kws = detail.get("photo_keywords", [])
                            blog_title = blog_text.split("\n")[0].replace("**", "").replace("*", "").replace("#", "").replace("\\!", "!").replace("\\.", ".").replace("\\,", ",").strip()
                            photos = fetch_photos_for_blog(photo_kws, category, blog_title)
                            st.session_state["blog_photos"] = photos

                        # 합본 HTML 생성
                        if photos:
                            html = build_combined_html(blog_text, photos)
                            st.session_state["combined_html"] = html
                            st.success(f"글 생성 + 사진 {len(photos)}장 매칭 완료! '미리보기 & 복사' 탭으로 이동하세요.")
                        else:
                            html = build_combined_html(blog_text, {})
                            st.session_state["combined_html"] = html
                            st.warning("사진 검색 결과 없음. 글만 생성됨.")
                    elif blog_text:
                        html = build_combined_html(blog_text, {})
                        st.session_state["combined_html"] = html
                        st.success("글 생성 완료! (Pexels 키 미설정으로 사진 없음)")

                # 매칭된 사진 미리보기
                if "blog_photos" in st.session_state and st.session_state["blog_photos"]:
                    st.markdown("---")
                    st.markdown("**매칭된 사진**")
                    photos = st.session_state["blog_photos"]
                    pcols = st.columns(min(len(photos), 4))
                    for i, (tag, photo) in enumerate(photos.items()):
                        with pcols[i % len(pcols)]:
                            st.image(photo["url_medium"], caption=f"{tag} ({photo.get('source', '')})", width="stretch")

                    # 사진 교체
                    st.markdown("---")
                    replace_slot = st.selectbox("사진 교체할 위치", list(photos.keys()))
                    new_kw = st.text_input("새 검색어 (한국어 권장)", placeholder="예: 프로야구 경기장 관중")
                    if new_kw and st.button("사진 교체"):
                        results = search_all_sources(new_kw, per_source=3)
                        if results:
                            st.session_state["blog_photos"][replace_slot] = results[0]
                            st.session_state["combined_html"] = build_combined_html(
                                st.session_state["blog_text"], st.session_state["blog_photos"])
                            st.rerun()
                        else:
                            st.warning("결과 없음")

                # 글 편집
                if "blog_text" in st.session_state:
                    st.markdown("---")
                    char_count = len(st.session_state["blog_text"].replace(" ", "").replace("\n", ""))
                    st.caption(f"글자수: {char_count}자")
                    edited = st.text_area("글 직접 수정", value=st.session_state["blog_text"], height=350)
                    if edited != st.session_state["blog_text"]:
                        st.session_state["blog_text"] = edited
                        photos = st.session_state.get("blog_photos", {})
                        st.session_state["combined_html"] = build_combined_html(edited, photos)

    # ===== 미리보기 & 복사 탭 =====
    with tab_preview:
        if "combined_html" not in st.session_state:
            st.info("'작성 파이프라인' 탭에서 글+사진을 먼저 생성하세요.")
        else:
            html_content = st.session_state["combined_html"]

            st.subheader("블로그 미리보기")
            st.caption("아래 미리보기를 확인하고, 복사 버튼으로 한번에 복사하세요.")

            # 미리보기 렌더링
            st.components.v1.html(f"""
            <html>
            <head>
                <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700&display=swap" rel="stylesheet">
            </head>
            <body style="background:#fafafa; padding:20px;">
                {html_content}
            </body>
            </html>
            """, height=800, scrolling=True)

            st.markdown("---")

            # 복사 버튼들
            col1, col2, col3 = st.columns(3)

            with col1:
                # HTML 복사 (네이버 블로그 HTML 모드용)
                st.download_button(
                    "HTML 파일 다운로드",
                    data=html_content.encode("utf-8"),
                    file_name=f"blog_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html",
                    mime="text/html",
                    width="stretch",
                )

            with col2:
                # 텍스트만 복사
                plain_text = st.session_state.get("blog_text", "")
                st.download_button(
                    "TXT 파일 다운로드",
                    data=plain_text.encode("utf-8"),
                    file_name=f"blog_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                    mime="text/plain",
                    width="stretch",
                )

            with col3:
                # 사진 전체 다운로드
                if st.button("사진 전체 다운로드", width="stretch"):
                    photos = st.session_state.get("blog_photos", {})
                    if photos:
                        saved = 0
                        for tag, photo in photos.items():
                            num = re.search(r'\d+', tag).group()
                            fname = f"blog_photo_{num}_{photo['id']}.jpg"
                            if download_photo(photo["url_large"], fname):
                                saved += 1
                        st.success(f"blog_images/ 폴더에 {saved}장 저장 완료")
                    else:
                        st.warning("저장할 사진 없음")

            # 클립보드 복사 (JavaScript)
            st.markdown("---")
            st.subheader("클립보드 복사")
            st.caption("아래 버튼을 누르면 HTML이 클립보드에 복사됩니다. 네이버 블로그 에디터에 바로 붙여넣기 하세요.")

            escaped_html = html_content.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
            copy_js = f"""
            <button onclick="copyToClipboard()" style="
                background:#03C75A; color:white; border:none; padding:14px 32px;
                border-radius:8px; font-size:16px; font-weight:bold; cursor:pointer;
                width:100%; margin:8px 0;">
                전체 복사하기 (글 + 사진 HTML)
            </button>
            <div id="copy-status" style="text-align:center; margin-top:8px; font-size:14px; color:#666;"></div>
            <script>
            function copyToClipboard() {{
                const htmlContent = `{escaped_html}`;
                const blob = new Blob([htmlContent], {{type: 'text/html'}});
                const item = new ClipboardItem({{'text/html': blob, 'text/plain': new Blob([htmlContent], {{type: 'text/plain'}})}});
                navigator.clipboard.write([item]).then(() => {{
                    document.getElementById('copy-status').innerText = '복사 완료! 네이버 블로그 에디터에 Ctrl+V 하세요.';
                    document.getElementById('copy-status').style.color = '#03C75A';
                }}).catch(err => {{
                    // fallback
                    const ta = document.createElement('textarea');
                    ta.value = htmlContent;
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand('copy');
                    document.body.removeChild(ta);
                    document.getElementById('copy-status').innerText = '복사 완료! (텍스트로 복사됨)';
                    document.getElementById('copy-status').style.color = '#03C75A';
                }});
            }}
            </script>
            """
            st.components.v1.html(copy_js, height=80)

            # 네이버 블로그 자동 업로드
            st.markdown("---")
            st.subheader("네이버 블로그 자동 업로드")

            if not NAVER_BLOG_ID or NAVER_BLOG_ID == "여기에_네이버_아이디":
                st.warning(".env 파일에 NAVER_BLOG_ID=본인아이디 를 설정해주세요.")
            else:
                st.info(f"블로그 ID: {NAVER_BLOG_ID}  |  Chrome 기존 로그인 세션 사용")
                st.caption("Chrome이 열려있으면 자동으로 닫고 다시 실행합니다. 업로드 후 브라우저에서 직접 발행 버튼을 누르세요.")

                if st.button("네이버 블로그에 자동 업로드", type="primary", width="stretch"):
                    import tempfile, subprocess, sys

                    blog_text = st.session_state.get("blog_text", "")
                    first_line = blog_text.split("\n")[0].replace("**", "").replace("*", "").replace("#", "").replace("\\!", "!").replace("\\.", ".").replace("\\,", ",").strip()

                    # 임시 JSON 파일로 데이터 전달
                    tmp = tempfile.NamedTemporaryFile(
                        mode="w", suffix=".json", delete=False, encoding="utf-8"
                    )
                    # 모든 이미지 로컬 다운로드 + 이미지 위치에 마커 삽입
                    photos = st.session_state.get("blog_photos", {})
                    image_paths = {}
                    for tag in ["[사진1]", "[사진2]", "[사진3]", "[사진4]"]:
                        if tag in photos:
                            photo = photos[tag]
                            num = re.search(r'\d+', tag).group()
                            fpath = download_photo(photo["url_large"], f"upload_photo_{num}_{photo['id']}.jpg")
                            if fpath:
                                image_paths[f"___IMAGE_{num}___"] = fpath

                    # 이미지 div를 마커로 교체 + 탐정사무소 첫줄 제거 (업로더가 직접 처리)
                    html_no_img = html_content
                    for num in ["1", "2", "3", "4"]:
                        html_no_img = re.sub(
                            r'<div[^>]*text-align:center[^>]*>.*?</div>',
                            f'___IMAGE_{num}___',
                            html_no_img, count=1, flags=re.DOTALL
                        )
                    html_no_img = re.sub(r'<p[^>]*>세상소식을 전하는.*?</p>', '', html_no_img, flags=re.DOTALL)

                    json.dump({
                        "title": first_line,
                        "html_content": html_no_img,
                        "blog_id": NAVER_BLOG_ID,
                        "image_paths": image_paths,  # {"___IMAGE_1___": "path", ...}
                    }, tmp, ensure_ascii=False)
                    tmp.close()

                    uploader = os.path.join(os.path.dirname(os.path.abspath(__file__)), "naver_uploader.py")
                    subprocess.Popen([sys.executable, uploader, tmp.name])
                    st.success("Chrome이 열립니다. 내용을 확인 후 직접 발행 버튼을 눌러주세요.")


    # ===== 스케줄러 탭 =====
    with tab_schedule:
        cfg_sch = load_config()
        running = sch_state.running

        # ── 상단 상태 표시
        if running:
            st.success("실행 중 — 블로그 발행 + 방문자 프로그램 순환 중")
        else:
            st.info("중지됨")

        st.markdown("---")

        # ── 설정
        col_left, col_right = st.columns(2)
        with col_left:
            st.markdown("**발행 간격**")
            interval_hours = st.number_input(
                "발행 주기 (시간)", min_value=1, max_value=24,
                value=cfg_sch.get("interval_hours", 12), step=1,
                key="sch_interval"
            )
            gap_min = st.number_input(
                "포스팅 간 대기 (초)", min_value=30, max_value=600,
                value=cfg_sch.get("gap_seconds", 60), step=10,
                key="sch_gap"
            )

        with col_right:
            st.markdown("**하이퍼링크 목록**")
            import pandas as pd
            links = cfg_sch.get("hyperlinks", [])
            df_links = pd.DataFrame(links if links else [{"keyword": "", "url": ""}])
            edited_df = st.data_editor(
                df_links,
                column_config={
                    "keyword": st.column_config.TextColumn("키워드", width="small"),
                    "url":     st.column_config.TextColumn("URL",    width="large"),
                },
                num_rows="dynamic",
                width="stretch",
                key="link_editor",
            )
            if st.button("목록 저장", key="btn_save_links"):
                new_links = edited_df.dropna(subset=["keyword","url"])
                new_links = new_links[
                    (new_links["keyword"].str.strip() != "") &
                    (new_links["url"].str.strip() != "")
                ].to_dict("records")
                cfg_sch["hyperlinks"] = new_links
                save_config(cfg_sch)
                st.success(f"{len(new_links)}개 저장")
                st.rerun()

        st.markdown("---")

        # ── 시작 / 중지 버튼
        btn_col1, btn_col2 = st.columns(2)
        with btn_col1:
            if not running:
                if st.button("시작", type="primary", width="stretch", key="btn_start"):
                    cfg_sch["interval_hours"] = interval_hours
                    cfg_sch["gap_seconds"]    = gap_min
                    save_config(cfg_sch)

                    sch_state.running = True
                    with sch_state.lock:
                        sch_state.logs.clear()

                    _ih  = interval_hours
                    _gap = gap_min

                    def _sch_loop():
                        import time as _t

                        def _log(msg):
                            ts = datetime.now().strftime("%H:%M:%S")
                            line = f"[{ts}] {msg}"
                            print(line)
                            with sch_state.lock:
                                sch_state.logs.append(line)
                                if len(sch_state.logs) > 300:
                                    sch_state.logs[:] = sch_state.logs[-300:]

                        while sch_state.running:
                            _log("===== 발행 사이클 시작 =====")
                            run_all_hyperlinks_pipeline(
                                style_name="친근한 이웃 블로거",
                                word_count=1500,
                                gap_seconds=_gap,
                                log_fn=_log,
                            )
                            if not sch_state.running:
                                break
                            _log(f"===== 사이클 완료. {_ih}시간 후 재실행 =====")
                            _t.sleep(_ih * 3600)

                        _log("스케줄러 중지됨.")

                    t = threading.Thread(target=_sch_loop, daemon=True, name="sch_loop")
                    t.start()
                    st.rerun()

        with btn_col2:
            if running:
                if st.button("중지", type="secondary", width="stretch", key="btn_stop"):
                    sch_state.running = False
                    st.rerun()

        # ── 방문자 프로그램 (backlink.py)
        st.markdown("---")
        st.subheader("방문자 프로그램")

        # published_urls.json 현황 표시
        url_log_path = os.path.join(BASE_DIR, "published_urls.json")
        published_urls_count = 0
        if os.path.exists(url_log_path):
            try:
                with open(url_log_path, encoding="utf-8") as _f:
                    _pub = json.load(_f)
                published_urls_count = len([p for p in _pub if p.get("url")])
                st.caption(f"발행된 블로그 URL: **{published_urls_count}개** (published_urls.json)")
                if published_urls_count > 0:
                    with st.expander("URL 목록 확인"):
                        for _p in _pub[-10:]:
                            st.text(f"{_p.get('published_at','')[:16]}  {_p.get('title','')[:30]}")
                            st.caption(_p.get('url', ''))
            except Exception:
                st.caption("published_urls.json 읽기 실패")
        else:
            st.caption("published_urls.json 없음 — 블로그 발행 후 URL이 자동 저장됩니다.")

        # 방문자 프로그램 실행 상태 확인
        _bl_proc = sch_state.backlink_proc
        bl_running = _bl_proc is not None and _bl_proc.poll() is None

        if bl_running:
            st.success("방문자 프로그램 실행 중 (backlink.py)")
        else:
            st.info("방문자 프로그램 중지됨")

        bl_col1, bl_col2 = st.columns(2)
        with bl_col1:
            if not bl_running:
                if st.button(
                    f"방문 프로그램 시작 ({published_urls_count}개 URL)",
                    type="primary", key="btn_bl_start",
                    disabled=(published_urls_count == 0),
                ):
                    def _bl_log(msg):
                        ts = datetime.now().strftime("%H:%M:%S")
                        line = f"[{ts}] {msg}"
                        print(line)
                        with sch_state.lock:
                            sch_state.logs.append(line)
                    _trigger_backlink(_bl_log)
                    st.rerun()
            else:
                st.success("실행 중")

        with bl_col2:
            if bl_running:
                if st.button("방문 프로그램 중지", type="secondary", key="btn_bl_stop"):
                    try:
                        sch_state.backlink_proc.terminate()
                    except Exception:
                        pass
                    sch_state.backlink_proc = None
                    with sch_state.lock:
                        sch_state.logs.append(
                            f"[{datetime.now().strftime('%H:%M:%S')}] [백링크] 방문자 프로그램 중지됨."
                        )
                    st.rerun()

        # ── 실시간 로그
        st.markdown("---")
        lcol1, lcol2 = st.columns([4, 1])
        with lcol1:
            st.markdown("**실행 로그**")
        with lcol2:
            if st.button("로그 지우기", key="btn_clear_log"):
                with sch_state.lock:
                    sch_state.logs.clear()
                st.rerun()

        with sch_state.lock:
            logs_snapshot = list(sch_state.logs)

        if logs_snapshot:
            # 최신 로그가 아래에 오도록, 최근 100줄만 표시
            log_text = "\n".join(logs_snapshot[-100:])
            st.code(log_text, language=None)
        else:
            st.caption("시작 버튼을 누르면 로그가 실시간으로 표시됩니다.")

        # 실행 중일 때 2초마다 자동 새로고침 (UI 블로킹 없음)
        if running or bl_running:
            st_autorefresh(interval=2000, key="sch_autorefresh")


if __name__ == "__main__":
    main()
