# -*- coding: utf-8 -*-
import pyautogui
import pyperclip
import time
import os
import json
import random
from datetime import datetime
from openai import OpenAI

# ==========================================
# [설정 로드 및 OpenAI 설정]
# ==========================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_config():
    """config.json 파일 로드"""
    with open(os.path.join(BASE_DIR, "config.json"), "r", encoding="utf-8") as f:
        return json.load(f)

config = load_config()

# OpenAI API 설정
client = OpenAI(api_key=config["OPENAI_API_KEY"])

BLOG_ID = config["BLOG_ID"]
POST_ID_LIST = config.get("POST_ID_LIST", [])
MAX_POST_COUNT = config.get("MAX_POST_COUNT", 10)
INTERVAL_SEC = config["INTERVAL_SEC"]

# 이미지 파일 경로
IMG_ACCOUNT = "google_account.png"
IMG_TARGET_MSG = "target_word_img.png"
IMG_WRITE_MENU = "write_menu_btn.png"
IMG_TITLE_AREA = "title_area.png"
IMG_CONTENT_AREA = "content_area.png"
IMG_PUBLISH = "publish_btn.png"
IMG_CONFIRM = "confirm_btn.png"

# ==========================================
# [함수 정의]
# ==========================================

def save_url_to_text(full_url):
    """추출된 전체 URL을 줄바꿈하여 "URL", 형식으로 저장"""
    file_path = os.path.join(BASE_DIR, "extracted_urls.txt")
    
    # 파일에 기록 (줄바꿈 \n 추가)
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(f'"{full_url}",\n')
    
    print(f"[기록 완료] 전체 URL이 저장되었습니다: {full_url}")

def get_current_url_via_f6():
    """F6 키를 눌러 주소창에서 전체 URL 복사"""
    print("[정보] URL 추출을 위해 주소창(F6)에 접근합니다.")
    time.sleep(5) # 발행 후 페이지 이동 완료를 위해 넉넉히 대기
    pyautogui.press('f6')
    time.sleep(0.5)
    pyautogui.hotkey('ctrl', 'c')
    time.sleep(0.5)
    
    full_url = pyperclip.paste().strip()
    if full_url.startswith("http"):
        return full_url
    else:
        print("[경고] 유효한 URL을 복사하지 못했습니다.")
        return None

def get_gpt_title_only():
    """GPT를 통해 현재 날짜 기준 대한민국 주요 뉴스 제목 1개만 생성"""
    current_now = datetime.now().strftime('%Y년 %m월 %d일')
    prompt = f"당신은 전문 뉴스 큐레이터입니다. {current_now} 대한민국에서 가장 화제가 되는 뉴스 1개를 선정하여 블로그 제목 스타일로 작성하세요."
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "오직 '제목'만 출력하세요. 이모지 사용 금지. 따옴표 없이 깔끔하게 출력하세요."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=100
        )
        title = response.choices[0].message.content.strip()
        title = title.replace('"', '').replace("'", "")
        return title
    except Exception as e:
        print(f"GPT 제목 생성 에러: {e}")
        return f"{current_now} 대한민국 주요 실시간 뉴스 및 이슈 요약"

def find_and_click(img_name, timeout=15, clicks=1, msg=None):
    """이미지 서칭 및 클릭 함수"""
    img_path = os.path.join(BASE_DIR, img_name)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 탐색 중: {msg if msg else img_name}")
    for _ in range(timeout):
        try:
            location = pyautogui.locateOnScreen(img_path, confidence=0.8)
            if location:
                center = pyautogui.center(location)
                pyautogui.click(center, clicks=clicks)
                return True
        except: pass
        time.sleep(1)
    return False

def run_blog_automation(target_id):
    """블로그 자동 포스팅 핵심 로직"""
    
    blog_title = get_gpt_title_only()
    print(f"[생성된 제목] {blog_title}")

    # 크롬 실행
    pyautogui.hotkey('win', 'r')
    time.sleep(0.5)
    pyautogui.write("chrome")
    pyautogui.press('enter')
    
    if not find_and_click(IMG_ACCOUNT, msg="계정 선택"): return False
    time.sleep(2)

    # 타켓 블로그 주소 접속
    pyautogui.hotkey('ctrl', 'l')
    pyperclip.copy(f"https://blog.naver.com/{BLOG_ID}/{target_id}")
    pyautogui.hotkey('ctrl', 'v')
    pyautogui.press('enter')
    time.sleep(5)

    # 본문 복사
    if find_and_click(IMG_TARGET_MSG, clicks=3, msg="기존 본문 내용 복사"):
        time.sleep(1)
        pyautogui.hotkey('ctrl', 'c') 
        print("[정보] 기존 본문 내용을 클립보드에 복사했습니다.")

    # 글쓰기 버튼 클릭
    if not find_and_click(IMG_WRITE_MENU, msg="글쓰기 버튼"): return False
    print("[정보] 스마트에디터 로딩 대기 (15초)...")
    time.sleep(15)

    # 본문 붙여넣기
    pyautogui.hotkey('ctrl', 'v') 
    time.sleep(2)
    pyautogui.press('enter')

    # 제목 입력을 위해 상단으로 스크롤
    for _ in range(5):
        pyautogui.press('pageup')
        time.sleep(0.2)
    
    # 제목 입력
    if find_and_click(IMG_TITLE_AREA, msg="제목 영역"):
        pyperclip.copy(blog_title)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(1)

    # 발행 절차
    if find_and_click(IMG_PUBLISH, msg="발행 버튼 클릭"):
        time.sleep(2)
        if find_and_click(IMG_CONFIRM, msg="최종 발행 확인"):
            print(f">>> [성공] ID:{target_id} 포스팅 완료")
            
            # --- 발행 완료 페이지로 이동 대기 후 URL 추출 ---
            time.sleep(5) 
            full_url = get_current_url_via_f6()
            if full_url:
                save_url_to_text(full_url)
            
            time.sleep(2)
            pyautogui.hotkey('alt', 'f4') 
            return True
    
    pyautogui.hotkey('alt', 'f4')
    return False

# ==========================================
# [메인 실행부]
# ==========================================
if __name__ == "__main__":
    print(f"GPT 제목 생성 기반 자동 포스팅 시작 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    
    for idx, target_id in enumerate(POST_ID_LIST):
        print(f"\n" + "="*50)
        print(f"현재 타겟 그룹: {idx + 1}/{len(POST_ID_LIST)} (ID: {target_id})")
        
        for i in range(MAX_POST_COUNT):
            print(f"--- [{target_id}] {i+1}/{MAX_POST_COUNT} 회차 포스팅 시작")
            try:
                success = run_blog_automation(target_id)
                if not success:
                    print(f"--- [알림] {target_id} 회차 중 문제가 발생했습니다.")
            except Exception as e:
                print(f"!!! 시스템 에러 발생: {e}")
            
            print(f"--- 다음 회차까지 {INTERVAL_SEC}초 대기 중...")
            time.sleep(INTERVAL_SEC)

    print("\n" + "="*50)
    print("모든 자동 포스팅 작업 및 URL 추출이 완료되었습니다.")