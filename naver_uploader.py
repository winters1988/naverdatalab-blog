# -*- coding: utf-8 -*-
"""
네이버 블로그 자동 업로드 - pyautogui 이미지 인식 방식
기존 autonaverblogwirte_winters.py 방식을 app.py 콘텐츠 파이프라인에 연결
- 새 Chrome 실행 없이 이미 열린 Chrome에서 동작
- 이미지 파일: title_area.png, content_area.png, publish_btn.png, confirm_btn.png
"""

import sys
import json
import os
import re
import io
import time
import pyautogui
import pyperclip
import win32clipboard
from datetime import datetime
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 이미지 파일 경로 (기존 파일 재활용)
IMG_ACCOUNT     = os.path.join(BASE_DIR, "google_account.png")
IMG_WRITE_MENU  = os.path.join(BASE_DIR, "write_menu_btn.png")
IMG_TITLE_AREA  = os.path.join(BASE_DIR, "title_area.png")
IMG_CONTENT     = os.path.join(BASE_DIR, "content_area.png")
IMG_PUBLISH     = os.path.join(BASE_DIR, "publish_btn.png")
IMG_CONFIRM     = os.path.join(BASE_DIR, "confirm_btn.png")
IMG_OK          = os.path.join(BASE_DIR, "ok.png")

pyautogui.FAILSAFE = True   # 마우스를 화면 모서리로 이동하면 즉시 중단
pyautogui.PAUSE    = 0.3


def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")


def copy_html_to_clipboard(html: str):
    """Windows 클립보드에 HTML 형식으로 복사 (Naver 에디터가 렌더링된 형태로 붙여넣기 가능)"""
    # HTML Clipboard Format 헤더 계산
    prefix = (
        "Version:0.9\r\n"
        "StartHTML:00000097\r\n"
        "EndHTML:00000000\r\n"
        "StartFragment:00000097\r\n"
        "EndFragment:00000000\r\n"
    )
    fragment = f"<html><body><!--StartFragment-->{html}<!--EndFragment--></body></html>"
    full = prefix + fragment
    end = len(full.encode("utf-8"))
    # EndHTML / EndFragment 위치 채워넣기
    full = full.replace("EndHTML:00000000",   f"EndHTML:{end:08d}")
    full = full.replace("EndFragment:00000000", f"EndFragment:{end:08d}")

    cf_html = win32clipboard.RegisterClipboardFormat("HTML Format")
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardData(cf_html, full.encode("utf-8"))
    # 동시에 plain text도 세팅 (fallback)
    plain = re.sub(r"<[^>]+>", "", html).strip()
    win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, plain)
    win32clipboard.CloseClipboard()
    log("HTML 클립보드 세팅 완료")


def clean_title(title: str) -> str:
    """마크다운 기호 및 이스케이프 제거"""
    title = title.replace("**", "").replace("*", "")
    title = re.sub(r"^#+\s*", "", title)
    title = re.sub(r"\\(.)", r"\1", title)  # \! \. 등 마크다운 이스케이프 제거
    return title.strip()


def find_and_click(img_path: str, timeout: int = 20, confidence: float = 0.8,
                   clicks: int = 1, desc: str = "") -> bool:
    """이미지 탐색 후 클릭. timeout 초 안에 찾지 못하면 False 반환."""
    label = desc or os.path.basename(img_path)
    log(f"탐색 중: {label}")
    for _ in range(timeout):
        try:
            loc = pyautogui.locateOnScreen(img_path, confidence=confidence)
            if loc:
                pyautogui.click(pyautogui.center(loc), clicks=clicks)
                log(f"클릭 완료: {label}")
                return True
        except Exception:
            pass
        time.sleep(1)
    log(f"[실패] {label} 을 화면에서 찾지 못했습니다.")
    return False


def paste_image_from_file(img_path: str):
    """로컬 이미지를 비트맵으로 클립보드에 올린 뒤 Ctrl+V로 네이버 에디터에 삽입.
    네이버 에디터가 붙여넣기를 받으면 자동으로 자체 CDN에 업로드."""
    try:
        img = Image.open(img_path).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "BMP")
        bmp_data = buf.getvalue()[14:]   # BMP 파일 헤더 14바이트 제거 → DIB 포맷

        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, bmp_data)
        win32clipboard.CloseClipboard()

        time.sleep(0.3)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(3)   # 네이버가 이미지를 CDN에 업로드하는 시간 대기
        pyautogui.press("enter")  # 커서를 이미지 아래로 이동
        time.sleep(0.5)
        log(f"이미지 삽입 완료: {os.path.basename(img_path)}")
        return True
    except Exception as e:
        log(f"[실패] 이미지 삽입 오류: {e}")
        return False


def open_chrome_and_select_profile():
    """Win+R로 Chrome 실행 → 윈터스 프로필 선택"""
    log("Chrome 실행 중...")
    pyautogui.hotkey("win", "r")
    time.sleep(0.8)
    pyautogui.write("chrome", interval=0.05)
    pyautogui.press("enter")
    time.sleep(3)

    # 프로필 선택 화면에서 윈터스 계정 클릭
    if not find_and_click(IMG_ACCOUNT, timeout=15, desc="윈터스 프로필 선택"):
        log("[경고] 프로필 선택 화면이 없거나 이미 선택됨. 계속 진행합니다.")
    time.sleep(2)


def navigate_to_blog_write(blog_id: str):
    """주소창에 블로그 글쓰기 URL 입력"""
    url = f"https://blog.naver.com/{blog_id}/postwrite"
    pyautogui.hotkey("ctrl", "l")
    time.sleep(0.5)
    pyperclip.copy(url)
    pyautogui.hotkey("ctrl", "v")
    pyautogui.press("enter")
    log(f"이동: {url}")


def upload(title: str, html_content: str, blog_id: str, image_paths: dict = None, hyperlink: dict = None):
    title = clean_title(title)
    image_paths = image_paths or {}
    log(f"업로드 시작 | 블로그: {blog_id}")
    log(f"제목: {title}")
    log(f"이미지: {len(image_paths)}장")

    # 1. Chrome 새로 열고 윈터스 프로필 선택
    open_chrome_and_select_profile()

    # 2. 블로그 글쓰기 URL로 이동
    navigate_to_blog_write(blog_id)

    log("스마트에디터 로딩 대기 (15초)...")
    time.sleep(15)

    # '작성 중인 글이 있습니다' 팝업 처리
    if find_and_click(IMG_OK, timeout=5, desc="작성중 글 팝업 확인"):
        log("이전 작성중 글 팝업 닫음")
        time.sleep(3)
    else:
        time.sleep(3)

    # 3. 본문 영역 클릭 (이미지 인식 3회 → 좌표 클릭 → 탭 키 순서로 시도)
    content_focused = False
    for _try in range(3):
        if find_and_click(IMG_CONTENT, timeout=10, desc=f"본문 영역 (시도 {_try + 1})"):
            content_focused = True
            break
        log(f"  본문 클릭 실패. 3초 후 재시도...")
        time.sleep(3)

    if not content_focused:
        # 대안1: 화면 중앙 아래쪽 클릭 (네이버 에디터 본문 위치)
        sw, sh = pyautogui.size()
        cx, cy = sw // 2, int(sh * 0.58)
        log(f"[대안1] 화면 좌표 클릭 ({cx}, {cy})")
        pyautogui.click(cx, cy)
        time.sleep(0.8)

        # 대안2: 그래도 안 되면 Tab 키 2회
        if not find_and_click(IMG_CONTENT, timeout=3, desc="좌표 클릭 후 본문 확인"):
            log("[대안2] 탭 키 2회로 본문 포커스 이동")
            pyautogui.press("tab")
            time.sleep(0.4)
            pyautogui.press("tab")
            time.sleep(0.4)

    time.sleep(1.0)

    # 4. 하이퍼링크 첫 줄 (upload_data.json의 hyperlink 값 사용)
    hl_kw  = hyperlink.get("keyword", "탐정사무소") if hyperlink else "탐정사무소"
    hl_url = hyperlink.get("url", "https://kspdplus.co.kr/") if hyperlink else "https://kspdplus.co.kr/"
    INTRO_HTML = (
        f'<p style="font-size:16px; line-height:1.8;">세상소식을 전하는 '
        f'<span style="font-size:38px; font-weight:bold;">'
        f'<a href="{hl_url}" target="_blank" '
        f'style="font-size:38px; font-weight:bold; color:#03C75A; text-decoration:none;">'
        f'{hl_kw}</a></span> 입니다.</p>'
    )
    copy_html_to_clipboard(INTRO_HTML)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(1.5)
    pyautogui.press("enter")
    time.sleep(0.5)

    # 5. 이미지 마커 기준으로 HTML 분할 → 텍스트-이미지 교차 삽입
    # 구조: 소제목(###) → [사진N] → 본문 순서 그대로 처리
    marker_pattern = re.compile(r'(___IMAGE_\d+___)')
    parts = marker_pattern.split(html_content)

    for part in parts:
        if marker_pattern.match(part):
            if part in image_paths:
                log(f"{part} 삽입 중...")
                paste_image_from_file(image_paths[part])
        else:
            cleaned = part.strip()
            if cleaned:
                copy_html_to_clipboard(cleaned)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(1.2)

    log("본문 붙여넣기 완료")
    time.sleep(1)

    # 7. 제목 입력
    for _ in range(10):
        pyautogui.press("pageup")
        time.sleep(0.15)

    pyperclip.copy(title)
    title_clicked = find_and_click(IMG_TITLE_AREA, desc="제목 영역")
    if not title_clicked:
        # 대안: 제목 영역은 에디터 상단 약 20% 위치
        sw, sh = pyautogui.size()
        pyautogui.click(sw // 2, int(sh * 0.20))
        time.sleep(0.5)
        log("[대안] 제목 영역 좌표 클릭")
        title_clicked = True

    pyautogui.hotkey("ctrl", "a")
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "v")
    log(f"제목 입력 완료: {title}")

    time.sleep(1)

    # 8. 발행
    if find_and_click(IMG_PUBLISH, desc="발행 버튼"):
        time.sleep(2)
        if find_and_click(IMG_CONFIRM, desc="발행 확인"):
            time.sleep(3)  # 발행 후 URL 전환 대기
            # 주소창에서 발행된 URL 캡처
            published_url = capture_current_url()
            log(f"발행 완료! URL: {published_url}")
            return True, published_url
        else:
            log("[안내] 발행 확인 버튼을 직접 눌러주세요.")
    else:
        log("[안내] 발행 버튼을 직접 눌러주세요.")

    return False, None


IMG_URL_COPY = os.path.join(BASE_DIR, "url_copy.png")

def capture_current_url() -> str:
    """발행 후 'URL 복사' 버튼 클릭 → 클립보드에서 URL 반환"""
    try:
        if find_and_click(IMG_URL_COPY, timeout=8, desc="URL 복사 버튼"):
            time.sleep(0.5)
            url = pyperclip.paste().strip()
            return url if url.startswith("http") else ""
    except Exception:
        pass
    return ""


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python naver_uploader.py <json파일>")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)

    success, published_url = upload(
        title=data["title"],
        html_content=data["html_content"],
        blog_id=data["blog_id"],
        image_paths=data.get("image_paths", {}),
        hyperlink=data.get("hyperlink"),
    )

    # 발행 URL을 JSON 파일과 같은 경로에 저장
    if published_url:
        url_log = os.path.join(BASE_DIR, "published_urls.json")
        try:
            existing = json.load(open(url_log, encoding="utf-8")) if os.path.exists(url_log) else []
        except Exception:
            existing = []
        existing.append({"url": published_url, "title": data["title"],
                          "published_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        with open(url_log, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        log(f"URL 저장 완료: {url_log}")

    sys.exit(0 if success else 1)
