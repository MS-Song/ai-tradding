# Ranking System Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace KIS-based ranking with Naver Finance-based Realtime Hot Search and Volume Top stocks (up to 100 items), displaying top 10 in the UI and filtering out risky stocks.

**Architecture:** 
- Add `get_market_hot_stocks` and `get_market_volume_stocks` to `KISAPI` class in `src/api.py`.
- Implement Naver Finance crawling using `requests` and `BeautifulSoup`.
- Update `main.py` to use new caching variables and modify `draw_tui` for the new 10-item layout.
- Implement a filtering function for risky stocks (management, suspension, etc.).

**Tech Stack:** Python, Requests, BeautifulSoup4

---

### Task 1: Environment Setup

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Install BeautifulSoup4**
Run: `pip install beautifulsoup4`
Expected: Successfully installed

- [ ] **Step 2: Update requirements.txt**
Add `beautifulsoup4` and `lxml` (optional but recommended for speed) to `requirements.txt`.

- [ ] **Step 3: Commit**
```bash
git add requirements.txt
git commit -m "chore: add beautifulsoup4 to requirements"
```

### Task 2: Implement Naver Ranking Collection in `src/api.py`

**Files:**
- Modify: `src/api.py`

- [ ] **Step 1: Add BeautifulSoup import**
```python
from bs4 import BeautifulSoup
```

- [ ] **Step 2: Implement `get_naver_hot_stocks`**
Crawls `https://finance.naver.com/sise/last_7.naver` and returns filtered list.

- [ ] **Step 3: Implement `get_naver_volume_stocks`**
Crawls `https://finance.naver.com/sise/sise_quant.naver` for both KOSPI/KOSDAQ and returns filtered list.

- [ ] **Step 4: Implement `_filter_risky_stocks`**
Helper method to exclude stocks with names containing "관리", "정지", "환기", "정리매매".

- [ ] **Step 5: Replace old ranking methods**
Remove `_get_ranking`, `get_top_gainers`, `get_top_losers`.

- [ ] **Step 6: Commit**
```bash
git add src/api.py
git commit -m "feat: implement naver ranking collection and filter"
```

### Task 3: Update `main.py` for New Ranking UI

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Update Global Cache Variables**
Rename/Replace `_cached_gains_raw`, `_cached_loses_raw` with `_cached_hot_raw`, `_cached_vol_raw`.

- [ ] **Step 2: Update `data_update_worker`**
Change step 2 to call new naver ranking methods.

- [ ] **Step 3: Modify `draw_tui` Layout**
Update the ranking section to display 10 items for Hot and Volume stocks. Remove the "Gainers/Losers" headers.

- [ ] **Step 4: Verify UI Alignment**
Ensure the table doesn't break on different terminal widths.

- [ ] **Step 5: Commit**
```bash
git add main.py
git commit -m "feat: update UI to display naver hot and volume stocks"
```

### Task 4: Verification and Final Cleanup

**Files:**
- Create: `tools/test_naver_ranking.py`

- [ ] **Step 1: Create a test script**
Verify that `api.get_naver_hot_stocks()` returns valid data and excludes risky stocks.

- [ ] **Step 2: Run the test script**
Run: `python tools/test_naver_ranking.py`
Expected: Output showing top 100 items (raw) and top 10 (filtered).

- [ ] **Step 3: Final TUI Check**
Run: `python main.py`
Expected: TUI displays "🔥 HOT SEARCH" and "📊 VOLUME TOP" with 10 items each.

- [ ] **Step 4: Commit**
```bash
git add tools/test_naver_ranking.py
git commit -m "test: add naver ranking verification script"
```
