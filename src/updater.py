import os
import sys
import time
import requests
import platform
import subprocess
from datetime import datetime

# GitHub 저장소 정보
REPO_OWNER = "MS-Song"
REPO_NAME = "ai-tradding"
GITHUB_API_URL = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"

def is_running_as_executable() -> bool:
    """
    PyInstaller/Nuitka 등으로 빌드된 단일 실행파일로 실행 중인지 확인합니다.
    - EXE/SH 등 단일 실행파일: True  → 자동 업데이트 동작
    - python main.py 등 개발 실행:  False → 알림만 표시
    """
    return getattr(sys, 'frozen', False)

def check_for_updates(current_version):
    """GitHub API를 통해 최신 버전을 확인합니다."""
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
                # 3단계까지 동일한데 최신 버전의 마디 수가 더 많다면(드문 경우) 업데이트 간주 안함 (사용자 요청에 따라 3단계까지만 관리)
                pass

            if has_update:
                # 플랫폼에 맞는 자산 찾기
                is_windows = platform.system() == "Windows"
                target_asset_name = "KIS-Vibe-Trader.exe" if is_windows else "KIS-Vibe-Trader-Linux"
                
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
        print(f"Update check error: {e}")
    
    return {"has_update": False}

def download_update(url, target_path, progress_cb=None):
    """업데이트 파일을 다운로드합니다."""
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
        print(f"Download error: {e}")
        return False

def apply_update_and_restart(new_binary_path):
    """업데이트를 적용하고 프로그램을 재기동합니다."""
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
