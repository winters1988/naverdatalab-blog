import random
import time
import os
import shutil
import tempfile
import re
import json
import requests # <-- 추가: 프록시 상태 확인용
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from selenium.common.exceptions import StaleElementReferenceException 
from itertools import cycle 
from urllib.parse import urlsplit, urlunsplit 

# ==============================================================================
# 1. 환경 설정 변수 및 config.json 로드
# ==============================================================================

# configbacklink.json 우선 로드, 없으면 config.json 로드
_cfg_candidates = ["configbacklink.json", "config.json"]
config = None
for _cfg_file in _cfg_candidates:
    if os.path.exists(_cfg_file):
        try:
            with open(_cfg_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            print(f"✅ 설정 파일 로드: {_cfg_file}")
            break
        except json.JSONDecodeError:
            print(f"❌ FATAL ERROR: {_cfg_file} 파일 형식이 잘못되었습니다.")
            exit()

if config is None:
    print("❌ FATAL ERROR: configbacklink.json / config.json 을 찾을 수 없습니다. 프로그램을 종료합니다.")
    exit()

# --- 1-1. config.json 데이터 로드 및 변환 ---
PROXY_LIST_RAW = config.get("proxy_list_success", [])
PROXY_IP_PORTS = [f"{p['ip']}:{p['port']}" for p in PROXY_LIST_RAW if 'ip' in p and 'port' in p]

START_URLS = config.get("start_urls", [])
TARGET_DOMAINS = config.get("target_domains", [])
SEARCH_KEYWORDS = config.get("search_keywords", [])
NAVER_TV_CHANNEL_PATHS = config.get("naver_tv_channel_paths", [])
USER_AGENTS = config.get("user_agents", ['Mozilla/5.0 (Windows NT 10.0; Win64; x64)'])

# --- 1-2. 공통 상수 및 파생 변수 정의 ---
WAIT_TIMEOUT = 180
DWELL_TIME_MIN = config.get("dwell_time_min", 20)
DWELL_TIME_MAX = config.get("dwell_time_max", 30)

SUCCESS_LOG_PATH = "proxy_success_count.json" 

# ⭐ LINK_TEXT_KEYWORDS 업데이트 반영 (URL 형식 포함) ⭐
LINK_TEXT_KEYWORDS = list(set(
    SEARCH_KEYWORDS + TARGET_DOMAINS + 
    ["흥신소", "탐정사무소", "인천 흥신소","수원 흥신소", "https://kspdplus.co.kr", "kspdplus.co.kr"]
))


# --- 1-3. 필수 데이터 검증 ---
if not PROXY_IP_PORTS or not START_URLS or not TARGET_DOMAINS:
    print("❌ FATAL ERROR: config.json에 필수 데이터(프록시, URL, 타겟)가 부족합니다. 프로그램을 종료합니다.")
    exit()
    
#=====================================================================
# 2. 유틸리티 함수
#==============================================================================

def get_dwell_time():
    """체류 시간(초)을 랜덤으로 리턴"""
    lo = min(DWELL_TIME_MIN, DWELL_TIME_MAX)
    hi = max(DWELL_TIME_MIN, DWELL_TIME_MAX)
    return random.randint(lo, hi)

def record_success(ip, port, target_domain):
    """프록시 사용 성공 횟수를 JSON 파일에 기록"""
    key = f"{ip}:{port}"
    
    if os.path.exists(SUCCESS_LOG_PATH):
        try:
            with open(SUCCESS_LOG_PATH, "r", encoding="utf-8") as f:
                proxy_success_count = json.load(f)
        except json.JSONDecodeError:
            print("⚠️ 기존 성공 기록 파일 형식이 잘못되어 초기화합니다.")
            proxy_success_count = {}
    else:
        proxy_success_count = {}

    proxy_success_count[key] = proxy_success_count.get(key, 0) + 1
    
    try:
        with open(SUCCESS_LOG_PATH, "w", encoding="utf-8") as f:
            json.dump(proxy_success_count, f, indent=2, ensure_ascii=False)
        print(f"✅ 성공 기록: {key}에서 {target_domain} 접속 성공. (총 {proxy_success_count[key]}회 기록)")
    except Exception as e:
        print(f"❌ 성공 기록 파일 저장 중 오류 발생: {e}")

# 🆕 추가된 프록시 생존 확인 함수
def is_proxy_alive(ip, port):
    """
    requests를 사용하여 프록시 서버가 활성화되어 있는지 확인합니다.
    """
    try:
        proxies = {
            "http": f"http://{ip}:{port}",
            "https": f"http://{ip}:{port}"
        }
        # httpbin.org/ip를 사용하여 실제 IP가 프록시 IP인지 확인 (간단한 응답 코드 확인)
        res = requests.get("https://httpbin.org/ip", proxies=proxies, timeout=5)
        return res.status_code == 200
    except requests.exceptions.RequestException as e:
        # print(f"🚫 프록시({ip}:{port}) 비활성화 확인됨: {e}")
        return False


def random_short_sleep(min_sec=1, max_sec=3):
    """실제 사용자 서핑 모방을 위한 랜덤 짧은 대기 시간"""
    sleep_time = random.uniform(min_sec, max_sec)
    print(f"💤 짧은 대기: {sleep_time:.2f}초...")
    time.sleep(sleep_time)

def random_scroll(driver, min_scrolls=1, max_scrolls=3):
    """실제 사용자처럼 페이지를 랜덤으로 스크롤합니다."""
    scroll_count = random.randint(min_scrolls, max_scrolls)
    print(f"↕️ 페이지 스크롤 시도: {scroll_count}회")
    
    for _ in range(scroll_count):
        scroll_amount = random.randint(250, 800)
        driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
        time.sleep(random.uniform(1, 2))
    time.sleep(random.uniform(1, 3))

def is_target_link_text(text: str) -> bool:
    """
    링크 텍스트가 핵심 키워드 중 하나를 포함하고 있는지 확인합니다.
    (이 함수는 사용되지 않으나 구조 유지를 위해 보존)
    """
    if not text:
        return False
        
    core_keywords = ["흥신소", "인천 흥신소", "탐정사무소"]
    
    normalized = " ".join(text.split()).lower()
    
    for keyword in core_keywords:
        if keyword.lower() in normalized:
            return True
            
    return False

# 유틸리티 함수: 내부 링크 클릭
def click_random_internal_link(driver, target_domain):
    """
    현재 페이지의 내부 링크 중 하나를 랜덤으로 클릭합니다.
    """
    try:
        links = driver.find_elements(By.TAG_NAME, 'a')
        
        internal_links = []
        for link in links:
            try:
                href = link.get_attribute('href')
                # target 속성이 _blank가 아니거나 target 속성이 없으며, 내부 링크인 경우
                is_internal = href and href.startswith(('http', 'https')) and target_domain in urlsplit(href).netloc
                is_not_blank = not link.get_attribute('target') or link.get_attribute('target') != '_blank'

                if is_internal and is_not_blank:
                    internal_links.append(link)
            except StaleElementReferenceException:
                continue

        if not internal_links:
            return False

        # 랜덤으로 링크를 선택하고 클릭
        chosen_link = random.choice(internal_links)
        print(f"🔗 내부 링크 클릭 시도: {chosen_link.get_attribute('href')}")
        
        # JS를 이용한 강제 클릭
        driver.execute_script("arguments[0].click();", chosen_link)
        random_short_sleep(2, 4)
        return True

    except Exception as e:
        print(f"❌ 랜덤 내부 링크 클릭 중 오류: {e}")
        return False

# 유틸리티 함수: 네이버 직접 이동 및 서핑 후 복귀
def click_naver_ad_like_link(driver):
    """
    www.naver.com으로 직접 이동하여 짧은 서핑을 수행한 후,
    뒤로 가기(`.back()`)를 통해 타겟 사이트로 복귀합니다.
    """
    original_url = driver.current_url
    
    try:
        print("➡️ 'www.naver.com'으로 직접 이동 시도.")
        driver.get("https://www.naver.com")
        random_short_sleep(3, 5)

        if 'naver.com' in driver.current_url:
            print("✅ 네이버 진입 성공. 짧게 서핑 후 복귀 모션 시작.")
            
            # 1. 네이버 메인에서 랜덤 링크 탐색 및 클릭
            try:
                links = driver.find_elements(By.TAG_NAME, 'a')
                clickable_links = [
                    link for link in links 
                    if link.is_displayed() 
                    and (link.text or link.get_attribute('href')) 
                    and (not link.get_attribute('target') or link.get_attribute('target') != '_blank')
                ]
                
                if clickable_links:
                    chosen_link = random.choice(clickable_links)
                    link_text = chosen_link.text if chosen_link.text else chosen_link.get_attribute('href')
                    print(f"🔗 네이버 내 랜덤 링크 클릭 시도: {link_text[:50]}...")
                    
                    # 새 창 방지 및 클릭
                    driver.execute_script("arguments[0].removeAttribute('target');", chosen_link)
                    driver.execute_script("arguments[0].click();", chosen_link)
                    random_short_sleep(5, 8) # 이동 및 체류
            except Exception as e:
                print(f"❌ 네이버 내 랜덤 링크 클릭 중 오류: {e}")

            # 2. 스크롤
            random_scroll(driver, 1, 2)
            time.sleep(random.uniform(3, 7))
            
            # 3. 뒤로 가기 기능으로 타겟 사이트 복귀
            driver.back()
            print("⬅️ '뒤로 가기'를 통해 타겟 사이트로 복귀 완료.")
            random_short_sleep(2, 4) # 복귀 후 대기
            
            # 복귀 성공 확인 (선택 사항)
            if original_url in driver.current_url:
                print("✅ 복귀 URL 확인 성공.")
            else:
                print(f"⚠️ 복귀 URL 확인 실패. (기대: {original_url}, 현재: {driver.current_url})")

            return True

        return False

    except Exception as e:
        print(f"❌ 네이버 이동/복귀 중 오류: {e}")
        return False


# ==============================================================================
# 3. 핵심 로직 함수
# ==============================================================================

def handle_target_visit(driver, ip, port, target_domain):
    """
    타겟 링크 클릭 후 체류, 스크롤, 내부 탐색 및 외부 이탈(Naver) 모션 로직
    """
    
    # 1. 성공 기록
    record_success(ip, port, target_domain)
    print(f"📌 [{ip}:{port}] 타겟 진입 성공 기록 반영됨. 현재 URL = {driver.current_url}")
    
    # 2. 사이트 체류 및 초기 스크롤
    dwell = get_dwell_time()
    print(f"⏱ 타겟 사이트 체류시간: {dwell}초")
    random_scroll(driver, min_scrolls=2, max_scrolls=4)
    
    # 3. 체류 시간 동안 랜덤 모션 수행
    start_time = time.time()
    
    # 내부 링크 클릭 횟수: 1~2회 시도
    internal_click_count = random.randint(1, 2)
    
    for i in range(internal_click_count):
        if time.time() - start_time > dwell * 0.7: # 체류 시간 70%가 지나면 내부 탐색 중단
            break
            
        print(f"🔄 내부 탐색 시도 {i+1}/{internal_click_count}...")
        click_random_internal_link(driver, target_domain)
        random_scroll(driver, 1, 2)
        random_short_sleep(3, 5)

    # 4. 외부 이탈 시도 (Naver 직접 이동 및 서핑 후 복귀)
    print("📤 외부 이탈 모션 시작 (Naver 직접 이동 및 서핑 후 복귀)...")
    click_naver_ad_like_link(driver)
    
    # 5. 남은 시간 대기 (Naver 서핑 시간 포함)
    remaining_time = dwell - (time.time() - start_time)
    if remaining_time > 0:
        print(f"😴 남은 체류 시간 대기: {remaining_time:.2f}초...")
        time.sleep(remaining_time)
        
    return True

def simulate_blog_to_target(driver, url, ip, port, target_domain):
    """
    네이버 블로그/일반 웹페이지에서 타겟 하이퍼링크를 직접 찾아 클릭합니다.
    """
    try:
        # 블로그/일반 페이지 접속
        driver.get(url)
        random_short_sleep(2, 4) 
        print(f"➡️ [BLG 경로] 타겟 URL({url})로 이동 완료.")
        
        # iframe 처리: 네이버 블로그라면 iframe으로 전환 시도
        if 'blog.naver.com' in url:
            try:
                # 'mainFrame' iframe으로 전환
                WebDriverWait(driver, 10).until(
                    EC.frame_to_be_available_and_switch_to_it((By.ID, "mainFrame"))
                )
                print("✅ 네이버 블로그 mainFrame iframe 전환 성공.")
            except TimeoutException:
                print("⚠️ 네이버 블로그 mainFrame iframe 전환 실패. 본문에서 탐색 시도.")
            except Exception as e:
                 print(f"⚠️ 네이버 블로그 iframe 전환 중 예외 발생: {e}")
        
        # --- 타겟 하이퍼링크 탐색 로직 ---
        print("➡️ 타겟 링크 탐색 시작...")
        
        xpath_conditions = []
        for kw in LINK_TEXT_KEYWORDS:
            # 텍스트에 키워드가 포함되거나 (normalize-space(.) 사용)
            xpath_conditions.append(f"contains(normalize-space(.), '{kw}')")
            # href에 키워드가 포함되는 경우
            xpath_conditions.append(f"contains(@href, '{kw}')")
            
        # 또한, TARGET_DOMAINS에 있는 도메인을 href에 포함하는 경우를 명시적으로 추가
        xpath_conditions.append(f"contains(@href, '{target_domain}')")
        
        # 모든 조건을 'or'로 연결
        target_link_xpath = f"//a[{' or '.join(xpath_conditions)}]"
        
        found_target = False
        
        # 5회 재시도 루프
        for attempt in range(5):
            try:
                if attempt > 0:
                    print(f"⚠️ 타겟 링크 탐색 실패 (시도 {attempt}). 5초 대기 후 재시도...")
                    time.sleep(5)
                
                # 가시적이고 클릭 가능한 요소 대기
                target_elem = WebDriverWait(driver, 15).until( 
                    EC.element_to_be_clickable((By.XPATH, target_link_xpath))
                )
                
                # 🚩 중요 변경: 새 창이 열리지 않도록 target 속성 제거
                driver.execute_script("arguments[0].removeAttribute('target');", target_elem)
                
                # 클릭 시도 (JS 클릭 강제 실행)
                driver.execute_script("arguments[0].click();", target_elem) 
                time.sleep(random.uniform(3, 5))
                
                # 타겟 진입 후 로직 실행
                handle_target_visit(driver, ip, port, target_domain)
                found_target = True
                break

            except TimeoutException:
                if attempt == 4:
                    print("❌ 타겟 링크 탐색 최종 실패 (5회 시도).")
                continue
            except Exception as e:
                print(f"❌ 타겟 링크 클릭 중 예상치 못한 오류: {e}")
                break
        
        # iframe에서 메인 컨텐츠로 복귀 (블로그인 경우)
        if 'blog.naver.com' in url and driver.current_window_handle:
              try:
                  driver.switch_to.default_content()
              except:
                  pass

        return found_target

    except Exception as e:
        print(f"❌ 블로그 -> 타겟 로직 실행 중 오류: {e}")
        
        # iframe에서 메인 컨텐츠로 복귀 (오류 발생 시에도 복귀 시도)
        if 'blog.naver.com' in url and driver.current_window_handle:
              try:
                  driver.switch_to.default_content()
              except:
                  pass
        return False


def simulate_firefox(proxy_ip_port, start_url, user_agent, target_domain, channel_path, search_keyword):
    """
    Firefox WebDriver를 초기화하고 블로그->타겟 시뮬레이션 로직을 실행합니다.
    """
    ip, port = proxy_ip_port.split(':')
    user_data_dir = tempfile.mkdtemp()
    driver = None
    
    # 🆕 1. 프록시 생존 여부 확인
    if not is_proxy_alive(ip, port):
        print(f"🚫 프록시 비활성화됨: {ip}:{port}. 스킵합니다.")
        return False # 프록시 비활성화 시 False 반환
    
    try:
        # 2. WebDriver 및 프록시/UA 설정
        options = FirefoxOptions()
        options.headless = True 

        profile = webdriver.FirefoxProfile()
        profile.set_preference("network.proxy.type", 1)
        profile.set_preference("network.proxy.http", ip)
        profile.set_preference("network.proxy.http_port", int(port))
        profile.set_preference("general.useragent.override", user_agent)
        options.profile = profile

        driver = webdriver.Firefox(options=options)
        driver.set_page_load_timeout(WAIT_TIMEOUT) 
        
        print(f"\n🧭 FIREFOX | 프록시: {proxy_ip_port} | UA: {user_agent}")
        print(f"🔗 시작 URL: {start_url} | 타겟 도메인: {target_domain}")

        # 3. 메인 로직 실행 (블로그 -> 타겟)
        success = simulate_blog_to_target(driver, start_url, ip, port, target_domain)

        return success

    except Exception as e:
        print(f"❌ 전체 로직 실행 중 오류 발생: {e}")
        return False
    finally:
        # 4. 브라우저 종료 및 임시 폴더 삭제
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        shutil.rmtree(user_data_dir, ignore_errors=True)
        

# ==============================================================================
# 4. 메인 실행 블록
# ==============================================================================

if __name__ == '__main__':
    
    # --- 필수 데이터 검증 ---
    if not PROXY_IP_PORTS or not START_URLS or not TARGET_DOMAINS:
        print("❌ FATAL ERROR: config.json에 필수 데이터(프록시, URL, 타겟)가 부족합니다. 프로그램을 종료합니다.")
        exit()
    
    # 🔁 프록시 / URL / UA 순환 설정
    proxy_cycle = cycle(PROXY_IP_PORTS)
    url_cycle = cycle(START_URLS)
    ua_cycle = cycle(USER_AGENTS)
    
    # 타겟 도메인과 검색 키워드를 묶어 순환
    if len(TARGET_DOMAINS) != len(SEARCH_KEYWORDS):
        print("⚠️ TARGET_DOMAINS와 SEARCH_KEYWORDS의 길이가 다릅니다. 짧은 리스트를 기준으로 순환합니다.")
        
    target_data_cycle = cycle(list(zip(TARGET_DOMAINS, SEARCH_KEYWORDS)))
    
    # 🚩 프로그램 무한 실행
    while True:
        simulation_successful = False
        
        try:
            proxy = next(proxy_cycle)
            start_url = next(url_cycle)
            user_agent = next(ua_cycle)
            
            current_target_data = next(target_data_cycle)
            target_domain = current_target_data[0]
            search_keyword = current_target_data[1] 
            
            print("\n" + "="*50)
            print("🚀 새 시뮬레이션 시작: 네이버 블로그/일반 URL -> 타겟 링크 클릭")
            
            simulation_successful = simulate_firefox(
                proxy_ip_port=proxy,
                start_url=start_url,
                user_agent=user_agent,
                target_domain=target_domain,
                channel_path="", 
                search_keyword=search_keyword 
            )
            
            if simulation_successful:
                # 성공 시 짧은 대기 후 다음 시도
                wait_between_runs = random.randint(5, 10) 
                print(f"✅ 시뮬레이션 성공. 다음 실행까지 {wait_between_runs}초 대기...")
            else:
                # 프록시 비활성화 또는 기타 실패 시 좀 더 긴 대기
                wait_between_runs = random.randint(0, 0)
                print(f"❌ 시뮬레이션 실패/프록시 비활성화. 다음 실행까지 {wait_between_runs}초 대기...")
                
            time.sleep(wait_between_runs)

        except KeyboardInterrupt:
            print("\n👋 사용자 요청으로 프로그램 종료.")
            break
        except Exception as e:
            print(f"\n❌ 메인 루프에서 치명적인 오류 발생: {e}")
            time.sleep(60)