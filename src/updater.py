import os
import sys
import time
import logging
import requests
import platform
import subprocess
from datetime import datetime

_upd_log = logging.getLogger("VibeTrader")

# GitHub 저장소 정보
REPO_OWNER = "MS-Song"
REPO_NAME = "ai-tradding"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"

def is_running_as_executable() -> bool:
    """PyInstaller/Nuitka 등으로 빌드된 단일 실행파일(.exe 등)로 실행 중인지 확인합니다.

    실행파일 형태일 때만 자동 업데이트(파일 교체 및 재시작) 로직이 활성화됩니다. 
    Python 인터프리터(`python main.py`)로 실행 시에는 알림만 표시됩니다.

    Returns:
        bool: 단일 실행파일로 실행 중이면 True, 아니면 False.
    """
    return getattr(sys, 'frozen', False)

def check_for_updates(current_version: str) -> dict:
    """GitHub API를 통해 최신 릴리즈 버전을 확인하고 업데이트 정보를 반환합니다.

    버전 비교는 `major.minor.patch` 3단계를 기준으로 수행하며, 현재 플랫폼(Windows/Linux)에 
    적합한 실행파일 에셋 URL을 추출합니다.

    Args:
        current_version (str): 현재 프로그램의 버전 문자열.

    Returns:
        dict: 업데이트 존재 여부(`has_update`), 최신 버전, 다운로드 URL, 변경 내역(`body`)을 포함하는 딕셔너리.
    """
    try:
        response = requests.get(GITHUB_API_URL, timeout=10)
        if response.status_code == 200:
            data = response.json()
            latest_tag = data.get("tag_name", "").replace("v", "")
            
            # 버전 비교 (빌드 번호 무시하고 3단계까지만 비교: major.minor.patch)
            curr_parts = [int(p) for p in current_version.split('.') if p.isdigit()][:3]
            late_parts = [int(p) for p in latest_tag.split('.') if p.isdigit()][:3]
            
            has_update = False
            for i in range(min(len(curr_parts), len(late_parts))):
                if late_parts[i] > curr_parts[i]:
                    has_update = True
                    break
                elif late_parts[i] < curr_parts[i]:
                    break
            else:
                # 3단계까지 동일한데 최신 버전의 마디 수가 더 많다면 업데이트 간주 안함
                pass

            if has_update:
                # 플랫폼에 맞는 자산 찾기
                is_windows = platform.system() == "Windows"
                target_asset_name = "AI-Vibe-Trader.exe" if is_windows else "AI-Vibe-Trader-Linux"
                
                asset_url = ""
                for asset in data.get("assets", []):
                    if asset.get("name") == target_asset_name:
                        asset_url = asset.get("browser_download_url")
                        break
                
                return {
                    "has_update": True,
                    "latest_version": latest_tag,
                    "download_url": asset_url,
                    "body": data.get("body", "")
                }
    except Exception as e:
        _upd_log.error(f"Update check error: {e}")
    
    return {"has_update": False}

def download_update(url: str, target_path: str, progress_cb=None) -> bool:
    """GitHub로부터 업데이트 파일을 스트리밍 방식으로 다운로드합니다.

    Args:
        url (str): 다운로드할 에셋의 URL.
        target_path (str): 저장할 임시 파일 경로.
        progress_cb (callable, optional): 다운로드 진행률을 업데이트하기 위한 콜백 함수 (downloaded, total_size 인자 전달).

    Returns:
        bool: 다운로드 성공 시 True, 실패 시 False.
    """
    try:
        response = requests.get(url, stream=True, timeout=30)
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(target_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb and total_size > 0:
                        progress_cb(downloaded, total_size)
        return True
    except Exception as e:
        _upd_log.error(f"Download error: {e}")
        return False

def apply_update_and_restart(new_binary_path: str):
    """현재 실행 중인 바이너리를 새 파일로 교체하고 프로그램을 재시작합니다.
    
    OS별로 적절한 스크립트(Windows: .bat, Linux: .sh)를 생성하여 
    현재 프로세스 종료 후 파일을 덮어쓰고 새 프로세스를 실행하도록 예약합니다.

    Args:
        new_binary_path (str): 다운로드된 새 실행파일의 임시 경로.
    """
    is_windows = platform.system() == "Windows"
    current_exe = sys.executable if getattr(sys, 'frozen', False) else sys.argv[0]
    
    if is_windows:
        # Windows 배치 파일 생성
        bat_content = f"""@echo off
timeout /t 2 /nobreak > nul
move /y "{new_binary_path}" "{current_exe}"
start "" "{current_exe}"
del %0
"""
        bat_path = "update.bat"
        with open(bat_path, "w", encoding="cp949") as f:
            f.write(bat_content)
        
        subprocess.Popen([bat_path], shell=True)
        sys.exit(0)
    else:
        # Linux 쉘 스크립트 생성
        sh_content = f"""#!/bin/bash
sleep 2
mv "{new_binary_path}" "{current_exe}"
chmod +x "{current_exe}"
"{current_exe}" &
rm $0
"""
        sh_path = "update.sh"
        with open(sh_path, "w") as f:
            f.write(sh_content)
        
        os.chmod(sh_path, 0o755)
        subprocess.Popen(["/bin/bash", sh_path])
        sys.exit(0)
