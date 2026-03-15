"""
스케줄러 전역 상태 모듈.
Streamlit이 app.py를 재실행해도 이 모듈의 변수는 초기화되지 않음.
"""
import threading

running: bool = False
logs: list[str] = []
lock = threading.Lock()

# 방문자 프로그램 (backlink.py) 프로세스 핸들
backlink_proc = None  # subprocess.Popen
