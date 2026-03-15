"""
네이버 데이터랩 트렌드 분석 + Gemini AI 블로그 자동 작성 프로그램
- 실시간 검색량이 몰리는 주제를 자동 탐지하여 블로그 글 생성
"""

import sys
import io
import os
import json
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
import google.generativeai as genai

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

load_dotenv()

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# 네이버에서 자주 검색되는 주제 카테고리 (키워드 그룹)
TOPIC_GROUPS = [
    {"groupName": "부동산", "keywords": ["아파트", "전세", "부동산", "청약", "분양"]},
    {"groupName": "주식투자", "keywords": ["주식", "코스피", "삼성전자", "ETF", "배당주"]},
    {"groupName": "건강식품", "keywords": ["다이어트", "영양제", "건강식품", "체중감량", "홍삼"]},
    {"groupName": "여행", "keywords": ["제주도", "해외여행", "국내여행", "항공권", "숙박"]},
    {"groupName": "맛집", "keywords": ["맛집", "카페", "음식점", "배달음식", "인스타맛집"]},
    {"groupName": "육아", "keywords": ["육아", "어린이집", "유치원", "아기", "출산"]},
    {"groupName": "취업", "keywords": ["취업", "채용", "자기소개서", "이직", "공무원"]},
    {"groupName": "패션뷰티", "keywords": ["화장품", "스킨케어", "패션", "옷", "뷰티"]},
    {"groupName": "자동차", "keywords": ["전기차", "자동차", "중고차", "SUV", "자동차보험"]},
    {"groupName": "금융대출", "keywords": ["대출", "금리", "적금", "예금", "카드혜택"]},
    {"groupName": "반려동물", "keywords": ["강아지", "고양이", "반려동물", "펫", "동물병원"]},
    {"groupName": "게임", "keywords": ["게임", "롤", "모바일게임", "PC게임", "신작게임"]},
    {"groupName": "공연문화", "keywords": ["콘서트", "뮤지컬", "전시회", "영화", "드라마"]},
    {"groupName": "스포츠", "keywords": ["야구", "축구", "프로야구", "골프", "운동"]},
    {"groupName": "날씨재난", "keywords": ["날씨", "미세먼지", "태풍", "폭염", "한파"]},
    {"groupName": "IT기술", "keywords": ["AI", "챗GPT", "스마트폰", "노트북", "앱"]},
    {"groupName": "요리레시피", "keywords": ["레시피", "요리", "집밥", "간단요리", "저녁메뉴"]},
    {"groupName": "인테리어", "keywords": ["인테리어", "가구", "셀프인테리어", "소품", "청소"]},
    {"groupName": "교육학습", "keywords": ["수능", "영어공부", "자격증", "온라인강의", "독서"]},
    {"groupName": "의료건강", "keywords": ["병원", "건강검진", "다이어트약", "탈모", "피부과"]},
]


def query_datalab(keyword_groups: list[dict], start_date: str, end_date: str, time_unit: str = "date") -> dict:
    """네이버 데이터랩 검색어 트렌드 API 호출 (최대 5개 그룹)"""
    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
        "Content-Type": "application/json",
    }
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": time_unit,
        "keywordGroups": keyword_groups[:5],
    }
    response = requests.post(url, headers=headers, data=json.dumps(body))
    response.raise_for_status()
    return response.json()


def get_trending_topics(top_n: int = 3) -> list[dict]:
    """
    최근 7일 vs 직전 21일을 비교하여 검색량 상승폭이 큰 주제를 찾는다.
    상승률 = (최근7일 평균) / (직전21일 평균) - 데이터랩 상대 검색량 기준
    """
    today = datetime.now()
    recent_end = today.strftime("%Y-%m-%d")
    recent_start = (today - timedelta(days=7)).strftime("%Y-%m-%d")
    prev_start = (today - timedelta(days=28)).strftime("%Y-%m-%d")
    prev_end = (today - timedelta(days=8)).strftime("%Y-%m-%d")

    scores = {}

    # 5개씩 묶어서 쿼리
    for i in range(0, len(TOPIC_GROUPS), 5):
        batch = TOPIC_GROUPS[i:i+5]
        try:
            recent_data = query_datalab(batch, recent_start, recent_end, "date")
            prev_data = query_datalab(batch, prev_start, prev_end, "date")
        except Exception as e:
            print(f"  데이터랩 조회 오류 (배치 {i//5+1}): {e}")
            continue

        for j, result in enumerate(recent_data.get("results", [])):
            group_name = result["title"]
            recent_avg = sum(d["ratio"] for d in result["data"]) / max(len(result["data"]), 1)

            prev_avg = 0
            if j < len(prev_data.get("results", [])):
                prev_result = prev_data["results"][j]
                prev_avg = sum(d["ratio"] for d in prev_result["data"]) / max(len(prev_result["data"]), 1)

            # 상승률 계산 (이전 기간이 0이면 최근값 그대로)
            if prev_avg > 0:
                surge_ratio = recent_avg / prev_avg
            else:
                surge_ratio = recent_avg

            scores[group_name] = {
                "recent_avg": round(recent_avg, 2),
                "prev_avg": round(prev_avg, 2),
                "surge_ratio": round(surge_ratio, 3),
                "keywords": batch[j]["keywords"],
            }

    if not scores:
        return []

    # 상승률 기준 정렬
    sorted_topics = sorted(scores.items(), key=lambda x: x[1]["surge_ratio"], reverse=True)
    return [{"topic": name, **data} for name, data in sorted_topics[:top_n]]


def generate_blog_post(trending_topics: list[dict]) -> str:
    """Gemini AI로 자연스러운 블로그 포스트 생성"""
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")

    today = datetime.now().strftime("%Y년 %m월 %d일")

    topic_info = ""
    for t in trending_topics:
        topic_info += (
            f"\n- 주제: {t['topic']}"
            f"\n  관련 키워드: {', '.join(t['keywords'])}"
            f"\n  최근 7일 평균 검색 지수: {t['recent_avg']}"
            f"\n  직전 21일 평균 검색 지수: {t['prev_avg']}"
            f"\n  상승률: {t['surge_ratio']:.1f}배\n"
        )

    main_topic = trending_topics[0]["topic"] if trending_topics else "일반 생활"

    prompt = f"""당신은 10년 경력의 네이버 파워블로거입니다. 오늘 날짜는 {today}입니다.

아래는 지금 이 순간 네이버에서 검색량이 급증하고 있는 주제들입니다.

[현재 검색량 급증 주제]
{topic_info}

위 주제 중 가장 많이 검색되고 있는 '{main_topic}'을 중심으로 블로그 글을 써주세요.
필요하다면 다른 급상승 주제들도 자연스럽게 연결해도 좋습니다.

[반드시 지켜야 할 규칙]
1. 이모지(이모티콘) 절대 사용 금지
2. AI가 쓴 것처럼 보이는 표현 금지:
   - "~해보겠습니다", "~알아볼게요", "~살펴보겠습니다" 같은 서두 표현 사용 금지
   - "첫째", "둘째", "셋째" 같은 번호 나열 금지
   - "결론적으로", "마지막으로", "요약하자면" 같은 정리 표현 금지
   - 과도하게 정형화된 목록 구조 금지
3. 자연스러운 구어체 사용: 실제 사람이 블로그에 쓰는 것처럼 솔직하고 편안하게
4. 개인적인 경험이나 의견을 섞어서 공감대 형성
5. 독자가 "이거 나 얘기네" 싶게 만드는 생활밀착형 내용
6. 소제목은 간결하게, 딱딱한 문어체 제목은 피할 것
7. 전체 분량 1800자 이상
8. 마지막에 검색 최적화 해시태그 12개 이상 (# 형식, 줄 바꿈으로 구분)

[글 구조 참고]
- 도입: 요즘 부쩍 이 주제가 화제인 이유를 자연스럽게 풀어내기
- 본문: 정보성 내용이지만 딱딱하지 않게, 중간중간 "사실 저도...", "주변에서 많이들..." 같은 표현 섞기
- 마무리: 독자에게 질문 던지기 또는 공감 유도

지금 바로 글 시작해주세요 (제목부터):"""

    response = model.generate_content(prompt)
    return response.text


def save_blog_post(content: str, topic: str) -> str:
    """생성된 블로그 포스트를 파일로 저장"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_topic = topic.replace("/", "_").replace(" ", "_")
    filename = f"blog_{safe_topic}_{timestamp}.txt"
    filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return filepath


def main():
    print("=== 네이버 데이터랩 기반 블로그 자동 작성기 ===\n")

    # 1. 데이터랩으로 급상승 주제 탐지
    print("[1단계] 네이버 데이터랩 검색 트렌드 분석 중...")
    trending = get_trending_topics(top_n=3)

    if not trending:
        print("  데이터랩 조회 실패. API 키와 권한을 확인해주세요.")
        return

    print(f"\n  급상승 검색 주제 TOP {len(trending)}:")
    for i, t in enumerate(trending, 1):
        print(f"  {i}. {t['topic']} (상승률 {t['surge_ratio']:.1f}배, 최근 검색지수 {t['recent_avg']})")

    main_topic = trending[0]["topic"]

    # 2. 블로그 글 생성
    print(f"\n[2단계] '{main_topic}' 주제로 블로그 글 생성 중...")
    try:
        blog_content = generate_blog_post(trending)
    except Exception as e:
        print(f"  블로그 생성 오류: {e}")
        return

    # 3. 출력 및 저장
    print("\n" + "=" * 60)
    print(blog_content)
    print("=" * 60)

    saved_path = save_blog_post(blog_content, main_topic)
    print(f"\n저장 완료: {saved_path}")


if __name__ == "__main__":
    main()
