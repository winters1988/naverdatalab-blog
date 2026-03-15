import random
import time
import os
import re
import json
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from itertools import cycle

# ==============================================================================
# 1. 환경 설정 및 config 로드 (configbacklink.json 우선, 없으면 config.json)
# ==============================================================================

_cfg_candidates = ["configbacklink.json", "config.json"]
config = None
for _cfg_file in _cfg_candidates:
    if os.path.exists(_cfg_file):
        try:
            with open(_cfg_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            print(f"[OK] 설정 파일 로드: {_cfg_file}")
            break
        except Exception as e:
            print(f"[ERR] {_cfg_file} 로드 실패: {e}")

if config is None:
    print("[FATAL] configbacklink.json / config.json 을 찾을 수 없습니다.")
    exit()

PROXY_LIST_RAW = config.get("proxy_list_success", [])
PROXY_IP_PORTS = [f"{p['ip']}:{p['port']}" for p in PROXY_LIST_RAW if 'ip' in p and 'port' in p]
START_URLS = config.get("start_urls", [])
TARGET_DOMAINS = config.get("target_domains", [])
SEARCH_KEYWORDS = config.get("search_keywords", [])
USER_AGENTS = config.get("user_agents", ['Mozilla/5.0 (Windows NT 10.0; Win64; x64)'])

WAIT_TIMEOUT = 180
DWELL_TIME_MIN = config.get("dwell_time_min", 20)
DWELL_TIME_MAX = config.get("dwell_time_max", 30)
SUCCESS_LOG_PATH = "proxy_success_count.json"

# 링크에서 찾을 텍스트 키워드들
TARGET_TEXT_KEYWORDS = ["흥신소", "탐정사무소", "수원흥신소", "인천흥신소", "전주흥신소", "대구흥신소", "부산흥신소", "kspdplus", "탐정"]

if not PROXY_IP_PORTS or not START_URLS or not TARGET_DOMAINS:
    print("[FATAL] 필수 데이터(프록시, URL, 타겟 도메인)가 부족합니다.")
    exit()

# ==============================================================================
# 2. 유틸리티 함수
# ==============================================================================

def get_dwell_time():
    return random.randint(min(DWELL_TIME_MIN, DWELL_TIME_MAX), max(DWELL_TIME_MIN, DWELL_TIME_MAX))

def is_proxy_alive(ip, port):
    try:
        proxies = {"http": f"http://{ip}:{port}", "https": f"http://{ip}:{port}"}
        res = requests.get("https://httpbin.org/ip", proxies=proxies, timeout=5)
        return res.status_code == 200
    except:
        return False

def record_success(ip, port, target_domain):
    key = f"{ip}:{port}"
    if os.path.exists(SUCCESS_LOG_PATH):
        try:
            with open(SUCCESS_LOG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except: data = {}
    else: data = {}

    data[key] = data.get(key, 0) + 1
    with open(SUCCESS_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[OK] 성공 기록: {key} -> {target_domain} (누적 {data[key]}회)")

def random_scroll(driver, min_s=1, max_s=3):
    for _ in range(random.randint(min_s, max_s)):
        driver.execute_script(f"window.scrollBy(0, {random.randint(300, 800)});")
        time.sleep(random.uniform(1, 2))

def click_random_internal_link(driver, matched_domain):
    try:
        links = driver.find_elements(By.TAG_NAME, 'a')
        internal = [l for l in links if l.get_attribute('href') and matched_domain in l.get_attribute('href')]
        if internal:
            chosen = random.choice(internal)
            driver.execute_script("arguments[0].click();", chosen)
            return True
    except: return False

# ==============================================================================
# 3. 핵심 로직 함수 (OR 조건 반영)
# ==============================================================================

def handle_target_visit(driver, ip, port, matched_domain):
    record_success(ip, port, matched_domain)
    dwell = get_dwell_time()
    print(f"[체류] 타겟 사이트({matched_domain}) 체류 시작: {dwell}초")

    start_time = time.time()
    while time.time() - start_time < dwell:
        random_scroll(driver, 1, 2)
        click_random_internal_link(driver, matched_domain)
        time.sleep(random.uniform(3, 7))
        if time.time() - start_time > dwell: break
    return True

def simulate_blog_to_target(driver, url, ip, port):
    """블로그 접속 후 TARGET_DOMAINS 리스트 중 하나라도 일치하면 클릭 (OR 조건)"""
    try:
        driver.get(url)
        time.sleep(random.uniform(3, 5))
        print(f"[접속] {url}")

        if 'blog.naver.com' in url:
            try:
                WebDriverWait(driver, 10).until(EC.frame_to_be_available_and_switch_to_it((By.ID, "mainFrame")))
                print("[OK] iframe 진입 성공")
            except: pass

        # 모든 링크 탐색
        all_links = driver.find_elements(By.TAG_NAME, "a")
        found_link = None
        matched_domain = ""

        print(f"[탐색] 타겟 도메인들({len(TARGET_DOMAINS)}개) 중 일치 항목 탐색...")

        # 1순위: 텍스트 키워드와 도메인이 모두 맞는 링크
        for link in all_links:
            try:
                if not link.is_displayed(): continue
                href = link.get_attribute('href')
                text = link.text.strip()
                if not href: continue

                domain_match = next((d for d in TARGET_DOMAINS if d in href), None)
                keyword_match = any(kw in text for kw in TARGET_TEXT_KEYWORDS)

                if domain_match and keyword_match:
                    found_link = link
                    matched_domain = domain_match
                    print(f"[적중] 키워드('{text}') & 도메인('{domain_match}') 발견!")
                    break
            except: continue

        # 2순위: 도메인 주소만 일치하는 링크
        if not found_link:
            for link in all_links:
                try:
                    href = link.get_attribute('href')
                    domain_match = next((d for d in TARGET_DOMAINS if d in href), None)
                    if domain_match and link.is_displayed():
                        found_link = link
                        matched_domain = domain_match
                        print(f"[도메인] 주소 기반 탐색 성공: {href}")
                        break
                except: continue

        if found_link:
            driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", found_link)
            time.sleep(2)
            driver.execute_script("arguments[0].removeAttribute('target');", found_link)
            driver.execute_script("arguments[0].click();", found_link)
            time.sleep(5)
            handle_target_visit(driver, ip, port, matched_domain)
            return True
        else:
            print(f"[실패] 설정된 타겟 도메인들을 찾지 못했습니다.")
            return False

    except Exception as e:
        print(f"[오류] {e}")
        return False
    finally:
        try: driver.switch_to.default_content()
        except: pass

def simulate_firefox(proxy_ip_port, start_url, user_agent):
    ip, port = proxy_ip_port.split(':')
    if not is_proxy_alive(ip, port):
        print(f"[스킵] 프록시 차단/오프라인: {proxy_ip_port}")
        return False

    driver = None
    try:
        options = FirefoxOptions()
        # options.add_argument('--headless')  # 화면 보려면 주석 유지
        options.add_argument('--width=1280')
        options.add_argument('--height=1000')

        profile = webdriver.FirefoxProfile()
        profile.set_preference("network.proxy.type", 1)
        profile.set_preference("network.proxy.http", ip)
        profile.set_preference("network.proxy.http_port", int(port))
        profile.set_preference("network.proxy.ssl", ip)
        profile.set_preference("network.proxy.ssl_port", int(port))
        profile.set_preference("general.useragent.override", user_agent)
        options.profile = profile

        driver = webdriver.Firefox(options=options)
        driver.set_page_load_timeout(WAIT_TIMEOUT)

        print(f"[브라우저] 가동 (Proxy: {proxy_ip_port})")
        return simulate_blog_to_target(driver, start_url, ip, port)

    except Exception as e:
        print(f"[브라우저 오류] {e}")
        return False
    finally:
        if driver:
            time.sleep(2)
            driver.quit()

# ==============================================================================
# 4. 메인 실행 루프
# ==============================================================================

if __name__ == '__main__':
    p_cycle = cycle(PROXY_IP_PORTS)
    u_cycle = cycle(START_URLS)
    ua_cycle = cycle(USER_AGENTS)

    print("[시작] OR 조건 검색 모드 시뮬레이션 시작")
    print(f"[설정] 감시 대상 도메인: {TARGET_DOMAINS}")
    print(f"[설정] 시작 URL 수: {len(START_URLS)}개")
    print(f"[설정] 프록시 수: {len(PROXY_IP_PORTS)}개")

    while True:
        try:
            proxy = next(p_cycle)
            url = next(u_cycle)
            ua = next(ua_cycle)

            print("\n" + "="*70)
            print(f"[작업] URL: {url}")

            success = simulate_firefox(proxy, url, ua)

            wait = random.randint(15, 30) if success else 3
            print(f"[완료] {'성공' if success else '실패'} | {wait}초 후 다음 회차")
            time.sleep(wait)

        except KeyboardInterrupt:
            print("\n[종료] 사용자 요청으로 종료.")
            break
        except Exception as e:
            print(f"[루프 오류] {e}")
            time.sleep(10)
