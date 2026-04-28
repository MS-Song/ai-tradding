# Data Manager Refactoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Break down `src/data_manager.py` (which has become a God Object of ~1,000 lines) into smaller, manageable files without changing its core functionality.

**Architecture:** We will extract the various background worker loops from the `DataManager` class into separate, domain-specific modules inside the `src/workers/` directory. The `DataManager` instance will be passed to these extracted worker functions (or classes) to maintain access to its state, locks, API, and strategy.

**Tech Stack:** Python (Threading, Concurrent Futures, Queue)

---

### Task 1: Initialize the Workers Package

**Files:**
- Create: `src/workers/__init__.py`

- [ ] **Step 1: Write minimal implementation**

```python
# src/workers/__init__.py
"""
Background workers for data synchronization, trading, and system tasks.
"""
```

- [ ] **Step 2: Commit**

```bash
git add src/workers/__init__.py
git commit -m "refactor: initialize workers package"
```

---

### Task 2: Extract Market & Theme Workers

**Files:**
- Create: `src/workers/market_worker.py`
- Modify: `src/data_manager.py` (Lines where `index_update_worker` and `theme_update_worker` are defined)

- [ ] **Step 1: Write the extracted market worker logic**

```python
# src/workers/market_worker.py
import time
from datetime import datetime
from src.utils import is_market_open, is_ai_enabled_time
from src.theme_engine import analyze_popular_themes, save_theme_data
from src.logger import log_error

def run_index_update_worker(dm):
    """시장 트렌드 분석 및 네이버 인기/거래량 종목 수집 워커"""
    while dm.is_running:
        curr_t = time.time()

        # 1) 시장 트렌드 분석
        try:
            dm.set_busy("시장분석", "INDEX")
            dm.strategy.determine_market_trend()
            with dm.data_lock:
                dm.cached_market_data = dm.strategy.current_market_data
                dm.cached_vibe = dm.strategy.current_market_vibe
                dm.cached_panic = dm.strategy.global_panic
                dm.cached_dema_info = getattr(dm.strategy.analyzer, 'dema_info', {})
                dm.market_info_status = "정상"
                dm.worker_results["INDEX"] = "성공"
                dm.worker_last_tasks["INDEX"] = "시장 지수 및 VIBE 분석"
            dm.last_times["index"] = curr_t
            kospi_info = dm.cached_market_data.get("KOSPI")
            dm.is_kr_market_active = kospi_info.get("status") == "02" if (kospi_info and "status" in kospi_info) else is_market_open()
        except RuntimeError: break
        except Exception as e:
            log_error(f"Market Trend Update Error: {e}")
            with dm.data_lock:
                dm.market_info_status = "실패"
                dm.worker_results["INDEX"] = "실패"
            
        with dm.data_lock:
            curr_vibe = dm.cached_vibe
            curr_time_str = datetime.now().strftime('%H:%M')
            today_str = datetime.now().strftime('%Y-%m-%d')
            
            if curr_vibe != dm.last_notified_vibe:
                dm.notifier.notify_alert("시장 VIBE 변화", f"🔄 `{dm.last_notified_vibe}` → `{curr_vibe}`")
                dm.last_notified_vibe = curr_vibe
            
            if "09:00" <= curr_time_str <= "09:05" and dm.notified_dates["market_start"] != today_str:
                if dm.is_kr_market_active:
                    dm.notifier.notify_market_start(curr_vibe)
                    dm.notified_dates["market_start"] = today_str

        # 2) 네이버 인기/거래량 종목 수집
        try:
            dm.set_busy("종목 수집", "INDEX")
            h_raw = dm.api.get_naver_hot_stocks()
            v_raw = dm.api.get_naver_volume_stocks()
            themes = analyze_popular_themes(h_raw, v_raw)
            
            shared_info = {}
            for item in h_raw + v_raw:
                code = item.get('code')
                if code:
                    price = float(str(item.get('price', 0)).replace(',', ''))
                    rate = float(item.get('rate', 0.0))
                    prev_close = price / (1 + rate / 100) if rate != -100 else price
                    cv = price - prev_close
                    
                    shared_info[code] = {
                        "price": price,
                        "day_rate": rate,
                        "day_val": cv,
                        "name": item.get('name', code)
                    }
            
            with dm.data_lock:
                dm.cached_hot_raw = h_raw
                dm.cached_vol_raw = v_raw
                
                for c, info in shared_info.items():
                    if c in dm.cached_stock_info:
                        dm.cached_stock_info[c].update(info)
                    else:
                        base = {"tp": 0, "sl": 0, "spike": False, "ma_20": 0, "prev_vol": 0, "day_val": 0, "day_rate": 0, "price": 0}
                        base.update(info)
                        dm.cached_stock_info[c] = base
                        
                dm.worker_results["RANKING"] = "성공"
                dm.worker_last_tasks["RANKING"] = "실시간 인기/거래량 종목 수집"
            dm.last_times["ranking"] = curr_t
        except RuntimeError: break
        except Exception as e:
            log_error(f"Hot/Vol Ranking Update Error: {e}")
            h_raw, v_raw, themes = dm.cached_hot_raw, dm.cached_vol_raw, []

        # 3) AI 추천 갱신
        try:
            if is_ai_enabled_time() or getattr(dm.strategy, "debug_mode", False):
                def rec_prog_cb(c, t, msg=""):
                    dm.set_busy(f"AI분석({c}/{t})", "INDEX")
                dm.strategy.update_ai_recommendations(themes, h_raw, v_raw, progress_cb=rec_prog_cb)
            else:
                pass
            
            dm.strategy.refresh_yesterday_recs_performance(h_raw, v_raw)
            
            # 4) AI 비용 갱신
            if curr_t - dm.last_times.get("billing", 0) > 5:
                try:
                    costs = dm.strategy.get_ai_costs()
                    with dm.data_lock:
                        dm.cached_ai_costs = costs
                        dm.worker_results["BILLING"] = "성공"
                        dm.worker_last_tasks["BILLING"] = "AI API 사용료 집계"
                    dm.last_times["billing"] = curr_t
                except Exception as e:
                    log_error(f"Billing Update Error: {e}")
        except RuntimeError: break
        except Exception as e:
            log_error(f"AI Rec Update Error: {e}")
        finally:
            dm.clear_busy("INDEX")

        time.sleep(5)

def run_theme_update_worker(dm):
    """테마 데이터를 주기적으로 크롤링하여 파일로 저장"""
    while dm.is_running:
        try:
            dm.set_busy("테마 데이터 수집", "THEME")
            theme_map = dm.api.get_naver_theme_data()
            if theme_map:
                save_theme_data(theme_map)
                dm.add_trading_log("✨ 테마 데이터베이스 갱신 완료")
        except Exception as e:
            try:
                log_error(f"Theme Update Error: {e}")
            except: pass
        finally:
            with dm.data_lock:
                dm.worker_results["THEME"] = "성공"
            dm.clear_busy("THEME")
        
        time.sleep(6 * 3600)
```

- [ ] **Step 2: Remove old methods from `src/data_manager.py`**
In `src/data_manager.py`, delete the `index_update_worker` and `theme_update_worker` methods. Replace them with nothing (we'll update `start_workers` later).

- [ ] **Step 3: Commit**
```bash
git add src/workers/market_worker.py src/data_manager.py
git commit -m "refactor: extract market and theme workers"
```

---

### Task 3: Extract Data Sync Worker

**Files:**
- Create: `src/workers/sync_worker.py`
- Modify: `src/data_manager.py` (Lines where `data_sync_worker` is defined)

- [ ] **Step 1: Write the extracted sync worker logic**

```python
# src/workers/sync_worker.py
import time
import queue
import math
import concurrent.futures
from datetime import datetime
from src.logger import log_error, trading_log

def run_data_sync_worker(dm, is_virtual):
    """데이터 동기화 워커 (KIS API: 잔고/시세 수집 전용)"""
    dm.update_all_data(is_virtual, force=True)
    
    start_wait = time.time()
    while not getattr(dm.strategy, "first_analysis_attempted", False) and time.time() - start_wait < 15:
        dm.set_busy(f"초기 분석 대기 ({int(time.time()-start_wait)}s)", "DATA")
        time.sleep(1)
    dm.clear_busy("DATA")

    last_lite_sync = 0
    last_heavy_sync = 0

    while dm.is_running:
        try:
            try:
                req_type = dm._sync_queue.get(timeout=3.0)
            except queue.Empty:
                req_type = "AUTO"

            curr_t = time.time()
            if curr_t - last_lite_sync < 1.0:
                continue

            dm.set_busy("잔고 동기화", "DATA")
            h, a = dm.api.get_full_balance(force=True)

            if h or a.get('total_asset', 0) > 0:
                recent_codes = set()
                with trading_log.lock:
                    now_dt = datetime.now()
                    for t in trading_log.data.get("trades", []):
                        try:
                            t_dt = datetime.strptime(t["time"], '%Y-%m-%d %H:%M:%S')
                            if (now_dt - t_dt).total_seconds() < 600:
                                recent_codes.add(t["code"])
                            else:
                                break
                        except: continue
                
                all_relevant_codes = list(set([stock.get('pdno') for stock in h]) | recent_codes)
                bulk_data = dm.api.get_naver_stocks_realtime(all_relevant_codes)
                temp_stock_info = {}

                def fetch_stock_task(code):
                    n_data = bulk_data.get(code)
                    task_id = f"STOCK_{code}"
                    
                    s_name = next((s.get('prdt_name') for s in h if s.get('pdno')==code), code)
                    if s_name == code: s_name = dm.cached_stock_info.get(code, {}).get('name', code)
                    if s_name == code and n_data: s_name = n_data.get('name', code)
                    
                    is_heavy_cycle = (curr_t - last_heavy_sync > 60)
                    p_data = None
                    if is_heavy_cycle or code not in dm.cached_stock_info:
                        p_data = dm.api.get_inquire_price(code)
                        with dm.data_lock: 
                            dm.worker_results[task_id] = "성공" if p_data else "실패"
                            dm.worker_last_tasks[task_id] = "실시간 시세 및 지표 수집"
                    
                    if n_data:
                        curr_p, day_rate, day_val = n_data['price'], n_data['rate'], n_data['cv']
                        old_info = dm.cached_stock_info.get(code, {})
                        p_data_fallback = {
                            "price": curr_p, "vrss": day_val, "ctrt": day_rate,
                            "vol": n_data['aq'], "high": n_data['hv'], "low": n_data['lv'],
                            "prev_vol": p_data.get("prev_vol", 0) if p_data else old_info.get("prev_vol", 0)
                        }
                        tp, sl, spike = dm.strategy.get_dynamic_thresholds(code, dm.cached_vibe.lower(), p_data_fallback)
                        p_vol = p_data_fallback["prev_vol"]
                    else:
                        if not p_data: p_data = dm.api.get_inquire_price(code)
                        tp, sl, spike = dm.strategy.get_dynamic_thresholds(code, dm.cached_vibe.lower(), p_data)
                        curr_p = p_data.get('price', 0) if p_data else 0
                        day_val = p_data.get('vrss', 0) if p_data else 0
                        day_rate = p_data.get('ctrt', 0) if p_data else 0
                        p_vol = p_data.get('prev_vol', 0) if p_data else 0
                    
                    ma_20 = dm.ma_20_cache.get(code, 0.0)
                    if ma_20 == 0 or (curr_t - dm.last_times.get(f"ma_{code}", 0) > 60):
                        try:
                            m_candles = dm.api.get_minute_chart_price(code)
                            if m_candles:
                                closes = [float(str(c.get('stck_prpr') or c.get('stck_clpr')).strip()) for c in m_candles if (c.get('stck_prpr') or c.get('stck_clpr'))]
                                ma_vals = dm.strategy.indicator_eng.calculate_sma(closes, [20])
                                ma_20 = ma_vals.get("sma_20", 0.0)
                        except: pass
                    
                    return code, {
                        "tp": tp, "sl": sl, "spike": spike, "day_val": day_val, "day_rate": day_rate,
                        "ma_20": ma_20, "price": curr_p, "prev_vol": p_vol, "name": s_name
                    }, task_id, ma_20

                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                    futures = [executor.submit(fetch_stock_task, c) for c in all_relevant_codes]
                    for f in concurrent.futures.as_completed(futures):
                        c, info, tid, ma = f.result()
                        temp_stock_info[c] = info
                        if info.get('name'):
                            with dm.data_lock:
                                if c not in dm.cached_stock_info: dm.cached_stock_info[c] = {}
                                dm.cached_stock_info[c]['name'] = info['name']
                                dm.worker_names[tid] = f"{c}_{info['name']}"
                        if ma > 0: 
                            dm.ma_20_cache[c] = ma
                            dm.last_times[f"ma_{c}"] = curr_t
                        if curr_t - dm.last_times.get(tid.lower(), 0) > 60:
                            dm.last_times[tid.lower()] = curr_t

                dm._update_daily_metrics(a)
                with dm.data_lock:
                    dm.cached_holdings = h
                    dm.cached_asset = a
                    dm.cached_holdings_fetched = True
                    if a.get('total_asset', 0) > 0:
                        dm.strategy.last_known_asset = float(a['total_asset'])
                    dm.cached_stock_info.update(temp_stock_info)
                
                dm.last_times["asset"] = curr_t
                last_lite_sync = curr_t
                if curr_t - last_heavy_sync > 60:
                    last_heavy_sync = curr_t
                    
                dm.worker_results["DATA"] = "성공"
                dm.worker_last_tasks["DATA"] = "전체 잔고 데이터 동기화 완료"
                dm.clear_busy("DATA")

                with dm.data_lock:
                    stale_keys = []
                    for k in dm.last_times.keys():
                        if k.startswith("stock_"):
                            code = k.replace("stock_", "")
                            if code not in all_relevant_codes:
                                stale_keys.append(k)
                    
                    for k in stale_keys:
                        dm.last_times.pop(k, None)
                        dm.worker_names.pop(k.upper(), None)
                        dm.worker_results.pop(k.upper(), None)
                        dm.worker_last_tasks.pop(k.upper(), None)
                        code_only = k.replace("stock_", "")
                        dm.ma_20_cache.pop(code_only, None)
                        dm.last_times.pop(f"slow_{code_only}", None)
                        dm.last_times.pop(f"ma_{code_only}", None)
        except Exception as e:
            log_error(f"Data Sync Worker Error: {e}")
            dm.worker_results["DATA"] = "실패"
        finally:
            dm.clear_busy("DATA")
```

- [ ] **Step 2: Remove `data_sync_worker` from `src/data_manager.py`**
Delete the `data_sync_worker` method from `DataManager` in `src/data_manager.py`.

- [ ] **Step 3: Commit**
```bash
git add src/workers/sync_worker.py src/data_manager.py
git commit -m "refactor: extract data sync worker"
```

---

### Task 4: Extract Trading Worker

**Files:**
- Create: `src/workers/trade_worker.py`
- Modify: `src/data_manager.py` (Lines where `trading_worker` is defined)

- [ ] **Step 1: Write the extracted trade worker logic**

```python
# src/workers/trade_worker.py
import time
import math
from datetime import datetime
from src.logger import log_error

def run_trading_worker(dm, is_virtual):
    """매매 집행 워커 (전략 실행 전용)"""
    while dm.is_running:
        try:
            if not hasattr(dm.strategy, 'analyzer') or not dm.cached_holdings_fetched:
                time.sleep(2)
                continue

            curr_t = time.time()
            vibe = dm.cached_vibe
            a = dm.cached_asset
            h = dm.cached_holdings
            
            if curr_t - dm.last_times.get("recommendation", 0) > 300:
                dm.set_busy("AI 추천 갱신", "TRADE")
                dm.cached_recommendations = dm.strategy.get_buy_recommendations(market_trend=vibe.lower())
                dm.last_times["recommendation"] = curr_t
                dm.clear_busy("TRADE")

            if dm.is_kr_market_active and not dm.cached_panic:
                dm.set_busy("매매 사이클", "TRADE")
                try:
                    auto_res = dm.strategy.run_cycle(
                        market_trend=vibe.lower(), 
                        skip_trade=False,
                        holdings=h,
                        asset_info=a
                    )
                    if auto_res:
                        for r in auto_res: dm.add_trading_log(f"🤖 자동: {r}")
                        dm.add_log("🔄 매매 발생: 즉시 동기화 요청")
                        dm._sync_queue.put("LITE")
                    
                    if dm.strategy.risk_mgr.is_halted:
                        if not dm.last_notified_halted:
                            dm.notifier.notify_alert("서킷 브레이커 발동", "🚨 계좌 손실 임계치 도달로 인해 모든 자동 매수가 중단되었습니다.", is_critical=True)
                            dm.last_notified_halted = True
                    elif dm.last_notified_halted:
                        dm.notifier.notify_alert("서킷 브레이커 해제", "✅ 리스크가 완화되어 자동 매수가 다시 활성화되었습니다.")
                        dm.last_notified_halted = False
                    
                    today_str = datetime.now().strftime('%Y-%m-%d')
                    curr_time_str = datetime.now().strftime('%H:%M')
                    if "15:30" <= curr_time_str <= "15:35" and dm.notified_dates.get("market_end") != today_str:
                        dm.notifier.notify_market_end(a)
                        dm.notified_dates["market_end"] = today_str
                    
                    dm.worker_results["TRADE"] = "성공"
                    dm.worker_last_tasks["TRADE"] = "매매 사이클 실행 완료"
                finally:
                    dm.clear_busy("TRADE")
                
                dm.notify_latest_trades()
            else:
                dm.worker_results["TRADE"] = "대기 (장외)"

        except Exception as e:
            log_error(f"Trading Worker Error: {e}")
            dm.worker_results["TRADE"] = "실패"
        finally:
            dm.clear_busy("TRADE")
        
        time.sleep(5)
```

- [ ] **Step 2: Remove `trading_worker` from `src/data_manager.py`**
Delete the `trading_worker` method from `DataManager` in `src/data_manager.py`.

- [ ] **Step 3: Commit**
```bash
git add src/workers/trade_worker.py src/data_manager.py
git commit -m "refactor: extract trading worker"
```

---

### Task 5: Extract System Workers

**Files:**
- Create: `src/workers/system_worker.py`
- Modify: `src/data_manager.py` (Remaining worker methods)

- [ ] **Step 1: Write the extracted system workers logic**

```python
# src/workers/system_worker.py
import time
from datetime import datetime
from src.logger import log_error, trading_log, cleanup_text_log

def run_log_cleanup_worker(dm):
    """로그 파일을 주기적으로 정리 (1시간 주기)"""
    while dm.is_running:
        try:
            dm.set_busy("로그 정리 중", "CLEANUP")
            dm.add_log("로그 파일 정리를 시작합니다...")
            
            j_cleaned = trading_log.cleanup(days_to_keep=2)
            e_cleaned = cleanup_text_log("error.log", days_to_keep=2)
            t_cleaned = cleanup_text_log("trading.log", days_to_keep=2)
            tel_cleaned = cleanup_text_log("telegram.log", days_to_keep=2)
            
            if j_cleaned or e_cleaned or t_cleaned or tel_cleaned:
                dm.add_log("오래된 로그 파일 정리를 완료했습니다.")
            else:
                dm.add_log("로그 파일이 이미 최신 상태입니다.")
            
            with dm.data_lock:
                dm.worker_results["CLEANUP"] = "성공"
                
        except Exception as e:
            log_error(f"Log Cleanup Worker Error: {e}")
        finally:
            dm.clear_busy("CLEANUP")
        
        time.sleep(3600)

def run_retrospective_worker(dm):
    """투자 적중 복기 워커 (장 마감 후 30분 주기)"""
    from datetime import time as dtime
    
    while dm.is_running:
        try:
            now = datetime.now()
            if now.weekday() >= 5:
                time.sleep(1800)
                continue
            
            if now.time() < dtime(16, 0):
                time.sleep(60)
                continue
            
            if now.time() > dtime(22, 0):
                time.sleep(1800)
                continue
            
            retro = getattr(dm.strategy, 'retrospective', None)
            if not retro:
                time.sleep(1800)
                continue
            
            today_str = now.strftime('%Y-%m-%d')
            vibe = dm.cached_vibe or "Neutral"
            
            if not retro.has_daily_report(today_str):
                dm.set_busy("복기 리포트 생성", "RETRO")
                dm.add_log("📝 당일 투자 적중 복기 분석을 시작합니다...")
                report = retro.generate_daily_report(today_str, vibe)
                if report:
                    dm.add_trading_log("📊 투자 적중 복기 리포트가 생성되었습니다 (P:성과 → 4번 탭)")
                    dm.add_log("✅ 투자 적중 복기 리포트 생성 완료")
                    summary = report.get("ai_analysis", {}).get("overall_lesson", "당일 매매 복기가 완료되었습니다.")
                    dm.notifier.notify_alert("📊 투자 적중 복기 리포트", summary)
                else:
                    dm.add_log("ℹ️ 당일 매매 기록이 없어 복기 리포트를 생성하지 않았습니다")
            else:
                existing = retro.get_report(today_str)
                if existing and existing.get("update_count", 1) < 4:
                    dm.set_busy("복기 사후분석", "RETRO")
                    dm.add_log("🔄 투자 적중 사후 분석을 업데이트합니다...")
                    retro.update_post_market_analysis(today_str, vibe)
                    dm.add_log(f"✅ 투자 적중 사후 분석 업데이트 완료 ({existing.get('update_count', 1)+1}회차)")
            
        except Exception as e:
            log_error(f"Retrospective Worker Error: {e}")
        finally:
            with dm.data_lock:
                dm.worker_results["RETRO"] = "성공"
            dm.clear_busy("RETRO")
        
        time.sleep(1800)

def run_updater_worker(dm):
    """업데이트 체크 워커 (1시간 주기)"""
    current_ver = ""
    try:
        with open("VERSION", "r") as f:
            current_ver = f.read().strip()
    except: return

    while dm.is_running:
        try:
            dm.set_busy("최신 버전 확인 중", "UPDATE")
            from src.updater import check_for_updates
            res = check_for_updates(current_ver)
            if res.get("has_update"):
                with dm.data_lock:
                    is_already_notified = dm.update_info.get("has_update")
                    dm.update_info.update({
                        "has_update": True,
                        "latest_version": res["latest_version"],
                        "download_url": res["download_url"]
                    })
                
                if not is_already_notified:
                    dm.notifier.notify_alert("신규 업데이트 발견", f"🆕 신규 버전 `v{res['latest_version']}`이 릴리스되었습니다.\n단축키 `U`를 눌러 업데이트를 진행하세요.")
                dm.add_log(f"🚀 새로운 버전 v{res['latest_version']}이(가) 출시되었습니다! (U 키를 눌러 업데이트)")
            
            with dm.data_lock:
                dm.last_times['update'] = time.time()
                dm.worker_results["UPDATE"] = "성공"
        except Exception as e:
            try: log_error(f"Updater Worker Error: {e}")
            except: pass
        finally:
            dm.clear_busy("UPDATE")
        
        time.sleep(3600)

def run_telegram_status_worker(dm):
    """30분 단위 정기 상태 보고 워커"""
    time.sleep(30)
    from datetime import time as dtime
    
    while dm.is_running:
        try:
            config_enabled = getattr(dm.strategy, 'config', {}).get('vibe_strategy', {}).get('telegram_report_enabled', True)
            if not config_enabled:
                time.sleep(600)
                continue

            now = datetime.now()
            market_start = dtime(9, 0)
            market_end = dtime(15, 30)
            is_market_time = market_start <= now.time() <= market_end
            
            if now.weekday() >= 5:
                time.sleep(3600)
                continue

            if not is_market_time:
                time.sleep(300)
                continue
            
            with dm.data_lock:
                vibe = dm.cached_vibe
                asset = dm.cached_asset
                holdings = dm.cached_holdings
                last_time = dm.last_update_time or now.strftime('%H:%M:%S')

            if asset.get('total_asset', 0) > 0:
                vibe_emoji = "🟢" if "BULL" in vibe.upper() else "🔴" if "BEAR" in vibe.upper() else "🟡" if "NEUTRAL" in vibe.upper() else "⚪"
                
                msg = f"• *장세:* {vibe_emoji} {vibe}\n"
                msg += f"• *자산:* {asset['total_asset']:,.0f}원\n"
                msg += f"• *수익금 (수익률):* {int(asset.get('daily_pnl_amt', 0)):+,}원 ({abs(asset.get('daily_pnl_rate', 0.0)):.2f}%)\n"
                
                if holdings:
                    msg += f"• *보유 종목 ({len(holdings)}개):*\n"
                    sorted_h = sorted(holdings, key=lambda x: float(x.get('evlu_pfls_rt', 0)), reverse=True)
                    for h in sorted_h:
                        rt = float(h.get('evlu_pfls_rt', 0))
                        qty = int(float(h.get('hldg_qty', 0)))
                        price = float(h.get('prpr', 0))
                        pnl = (price - float(h.get('pchs_avg_pric', 0))) * qty
                        msg += f"  - {h['prdt_name']}: `{int(pnl):+,}원 ({abs(rt):.2f}%)` ({qty}주, {price:,.0f}원)\n"
                else:
                    msg += f"• *보유 종목:* 없음\n"
                
                dm.notifier.notify_alert(f"정기 상태 보고 ({last_time})", msg)
            
        except Exception as e:
            log_error(f"Telegram Status Worker Error: {e}")
        
        time.sleep(1800)
```

- [ ] **Step 2: Remove system workers from `src/data_manager.py`**
Delete `log_cleanup_worker`, `retrospective_worker`, `updater_worker`, and `telegram_status_worker` from `DataManager` in `src/data_manager.py`.

- [ ] **Step 3: Commit**
```bash
git add src/workers/system_worker.py src/data_manager.py
git commit -m "refactor: extract system workers"
```

---

### Task 6: Update `DataManager.start_workers()`

**Files:**
- Modify: `src/data_manager.py` (Update imports and the `start_workers` method)

- [ ] **Step 1: Write the updated `start_workers` implementation**
Update `start_workers` in `src/data_manager.py` to import and call the extracted functions:

```python
    def start_workers(self, is_virtual):
        import threading
        from src.workers.market_worker import run_index_update_worker, run_theme_update_worker
        from src.workers.sync_worker import run_data_sync_worker
        from src.workers.trade_worker import run_trading_worker
        from src.workers.system_worker import (
            run_log_cleanup_worker, 
            run_retrospective_worker, 
            run_updater_worker, 
            run_telegram_status_worker
        )

        threading.Thread(target=run_index_update_worker, args=(self,), daemon=True).start()
        threading.Thread(target=run_data_sync_worker, args=(self, is_virtual), daemon=True).start()
        threading.Thread(target=run_trading_worker, args=(self, is_virtual), daemon=True).start()
        threading.Thread(target=run_theme_update_worker, args=(self,), daemon=True).start()
        threading.Thread(target=run_log_cleanup_worker, args=(self,), daemon=True).start()
        threading.Thread(target=run_retrospective_worker, args=(self,), daemon=True).start()
        threading.Thread(target=run_updater_worker, args=(self,), daemon=True).start()
        threading.Thread(target=run_telegram_status_worker, args=(self,), daemon=True).start()
```

- [ ] **Step 2: Run minimal verification**
No test files are provided here, but you can verify it doesn't syntax error by running `python -c "from src.data_manager import DataManager"`.

- [ ] **Step 3: Commit**
```bash
git add src/data_manager.py
git commit -m "refactor: hook up extracted workers to data_manager"
```
