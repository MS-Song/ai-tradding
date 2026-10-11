/**
 * AI-Vibe-Trader Retro Dashboard Core Controller
 * Handles data fetching, processing, statistics calculations, UI state management, and chart rendering.
 */

// Application State
let appData = null;
let selectedDate = null;
let activeTab = 'overview';

// Chart Instances (to destroy and rebuild on updates)
let charts = {
    netTimeline: null,
    vibePie: null,
    modelProfit: null,
    modelWinRate: null,
    typeDist: null,
    judgmentDist: null
};

// Global formatter for Korean Won currency
const formatCurrency = (val) => {
    const isNegative = val < 0;
    const absVal = Math.abs(val);
    const formatted = new Intl.NumberFormat('ko-KR', { style: 'currency', currency: 'KRW' })
        .format(absVal)
        .replace('₩', '₩ ');
    return isNegative ? `-${formatted}` : formatted;
};

// Global formatter for percentages
const formatPercent = (val) => {
    return `${val.toFixed(1)}%`;
};

// Initialize Application
document.addEventListener('DOMContentLoaded', () => {
    setupTabNavigation();
    setupEventListeners();
    fetchRetrospectiveData();
});

// Tab Navigation logic
function setupTabNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            const targetTab = item.getAttribute('data-tab');
            if (activeTab === targetTab) return;
            
            // Update active nav button
            document.querySelectorAll('.nav-item').forEach(btn => btn.classList.remove('active'));
            item.classList.add('active');
            
            // Switch tabs
            document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
            const targetPane = document.getElementById(`tab-${targetTab}`);
            if (targetPane) targetPane.classList.add('active');
            
            activeTab = targetTab;
            
            // Update header title based on active tab
            updateHeaderTitle(targetTab);
            
            // Redraw charts on tab change to handle rendering size issues
            setTimeout(() => {
                triggerChartsResize();
            }, 100);
        });
    });
}

function updateHeaderTitle(tab) {
    const titleEl = document.getElementById('page-title');
    const subtitleEl = document.getElementById('page-subtitle');
    
    if (tab === 'overview') {
        titleEl.textContent = '종합 성과 모니터';
        subtitleEl.textContent = '수집된 투자 복기 JSON 로그 기반 실시간 통계 분석';
    } else if (tab === 'daily-reports') {
        titleEl.textContent = '일별 투자 복기';
        subtitleEl.textContent = '일별 AI 피드백 보고서 및 포지션 정산 리포트';
    } else if (tab === 'strategy-breakdown') {
        titleEl.textContent = '전략 엔진 및 AI 성능 평가';
        subtitleEl.textContent = '자동매매 알고리즘 모델과 자율 결정 지표 정밀 평가';
    }
}

// Event Listeners setup
function setupEventListeners() {
    document.getElementById('btn-refresh').addEventListener('click', () => {
        fetchRetrospectiveData();
    });
    
    document.getElementById('btn-close-modal').addEventListener('click', closeModal);
    
    // Close modal on click outside content
    const modal = document.getElementById('trade-modal');
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            closeModal();
        }
    });
    
    // Escape key to close modal
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeModal();
        }
    });
}

// Fetch data from local server
async function fetchRetrospectiveData() {
    setLoadingState(true);
    try {
        const endpoints = ['/api/retrospective', '/trade_retrospective.json'];
        let response = null;
        let data = null;
        
        for (const url of endpoints) {
            try {
                const res = await fetch(url);
                if (res.ok) {
                    response = res;
                    data = await res.json();
                    break;
                }
            } catch (err) {
                console.warn(`Failed fetching from: ${url}`, err);
            }
        }
        
        if (!data) {
            throw new Error('Data could not be fetched from any local API endpoints');
        }
        
        appData = data;
        processRetrospectiveData();
    } catch (err) {
        console.error('Error loading trade retrospective JSON:', err);
        alert('매매 복기 JSON 데이터를 가져올 수 없습니다. 프로젝트 루트에 trade_retrospective.json 파일이 존재하는지, server.py가 실행 중인지 확인하세요.');
    } finally {
        setLoadingState(false);
    }
}

function setLoadingState(isLoading) {
    const btn = document.getElementById('btn-refresh');
    if (isLoading) {
        btn.disabled = true;
        btn.querySelector('span').textContent = '로딩 중...';
        btn.querySelector('svg').classList.add('spin-anim');
    } else {
        btn.disabled = false;
        btn.querySelector('span').textContent = '데이터 갱신';
        btn.querySelector('svg').classList.remove('spin-anim');
    }
}

// Parse and calculate metrics from JSON
function processRetrospectiveData() {
    if (!appData || !appData.reports) return;
    
    const reports = appData.reports;
    const sortedDates = Object.keys(reports).sort();
    
    if (sortedDates.length === 0) return;
    
    // Set retention days display
    document.getElementById('stats-retention-days').textContent = `최근 ${sortedDates.length}거래일 리포트 보관`;
    document.getElementById('report-count-badge').textContent = `${sortedDates.length}일`;
    
    // Calculate global stats
    let totalTrades = 0;
    let profitTradesCount = 0;
    let netProfit = 0;
    let totalWinsValue = 0;
    let totalLossesValue = 0;
    
    const stockStats = {};
    const vibeStats = { Bull: 0, Bear: 0, Neutral: 0 };
    const modelStats = {};
    const typeStats = {};
    const judgmentStats = { CORRECT: 0, FORCED: 0, UNLUCKY: 0, WRONG: 0, LATE: 0, EARLY: 0 };
    
    sortedDates.forEach(date => {
        const report = reports[date];
        
        // Vibe statistics
        const vibe = report.market_vibe || 'Neutral';
        vibeStats[vibe] = (vibeStats[vibe] || 0) + 1;
        
        // Combine profits and losses
        const dailyStocks = [
            ...(report.top_profits || []),
            ...(report.top_losses || [])
        ];
        
        dailyStocks.forEach(stock => {
            const code = stock.code;
            const name = stock.name;
            const stockProfit = stock.total_profit || 0;
            
            // Stock specific aggregation
            if (!stockStats[code]) {
                stockStats[code] = { code, name, cumulativeProfit: 0, tradesCount: 0 };
            }
            stockStats[code].cumulativeProfit += stockProfit;
            
            // Judgment tag analysis from daily AI report
            const judgment = getJudgmentTag(name, report.ai_analysis);
            if (judgmentStats[judgment] !== undefined) {
                judgmentStats[judgment]++;
            }
            
            // Individual Trades loop
            (stock.trades || []).forEach(trade => {
                totalTrades++;
                const profit = trade.profit || 0;
                netProfit += profit;
                
                if (profit > 0) {
                    profitTradesCount++;
                    totalWinsValue += profit;
                } else if (profit < 0) {
                    totalLossesValue += profit;
                }
                
                stockStats[code].tradesCount++;
                
                // Model stats aggregation
                const model = trade.model_id || 'Unknown';
                if (!modelStats[model]) {
                    modelStats[model] = { name: model, total: 0, wins: 0, losses: 0, profit: 0 };
                }
                modelStats[model].total++;
                modelStats[model].profit += profit;
                if (profit > 0) modelStats[model].wins++;
                else if (profit < 0) modelStats[model].losses++;
                
                // Trade type stats aggregation
                const type = trade.type || '일반';
                if (!typeStats[type]) {
                    typeStats[type] = { name: type, profit: 0, count: 0 };
                }
                typeStats[type].profit += profit;
                typeStats[type].count++;
            });
        });
    });
    
    const winRate = totalTrades > 0 ? (profitTradesCount / totalTrades) * 100 : 0;
    const avgProfitVal = profitTradesCount > 0 ? (totalWinsValue / profitTradesCount) : 0;
    const lossTradesCount = totalTrades - profitTradesCount;
    const avgLossVal = lossTradesCount > 0 ? (totalLossesValue / lossTradesCount) : 0;
    const avgRatio = Math.abs(avgLossVal) > 0 ? Math.abs(avgProfitVal) / Math.abs(avgLossVal) : 0;
    
    // Update global dashboard DOM elements
    updateOverviewMetrics({
        netProfit,
        winRate,
        totalTrades,
        daysCount: sortedDates.length,
        avgRatio,
        avgProfitVal,
        avgLossVal
    });
    
    // Render Latest Vibe
    const latestDate = sortedDates[sortedDates.length - 1];
    const latestReport = reports[latestDate];
    const latestVibe = latestReport.market_vibe || 'Neutral';
    
    const badgeEl = document.getElementById('current-vibe-badge');
    badgeEl.textContent = latestVibe;
    badgeEl.className = `vibe-badge vibe-${latestVibe.toLowerCase()}`;
    
    // Render Ranking of Stocks
    renderStockRankings(stockStats);
    
    // Build Timeline Chart Data
    const timelineData = calculateTimelineProfit(sortedDates, reports);
    
    // Initialize & Render Charts
    renderNetTimelineChart(timelineData);
    renderVibePieChart(vibeStats);
    renderModelPerformanceCharts(modelStats);
    renderAdditionalDistributionCharts(typeStats, judgmentStats);
    
    // Build and populate strategy breakdown table
    renderModelTable(modelStats);
    
    // Build Date Selection sidebar lists
    renderDateTimeline(sortedDates, reports);
    
    // Pre-select the latest date in detailed report tab
    selectDailyReport(latestDate);
}

// Update DOM overview metric values
function updateOverviewMetrics(stats) {
    const netProfitEl = document.getElementById('metric-net-profit');
    netProfitEl.textContent = formatCurrency(stats.netProfit);
    if (stats.netProfit < 0) {
        netProfitEl.className = 'metric-value text-glow-red';
    } else {
        netProfitEl.className = 'metric-value text-glow-green';
    }
    
    document.getElementById('metric-win-rate').textContent = formatPercent(stats.winRate);
    document.getElementById('metric-win-rate-progress').style.width = `${stats.winRate}%`;
    
    document.getElementById('metric-total-trades').textContent = `${stats.totalTrades}건`;
    document.getElementById('metric-days-count').textContent = `총 ${stats.daysCount}거래일 통계 산출`;
    
    document.getElementById('metric-avg-ratio').textContent = stats.avgRatio.toFixed(2);
    document.getElementById('metric-avg-values').innerHTML = 
        `<span class="text-green">${formatCurrency(stats.avgProfitVal)}</span> / ` + 
        `<span class="text-red">${formatCurrency(stats.avgLossVal)}</span>`;
}

// Calculate chronological cumulative profit timeline
function calculateTimelineProfit(sortedDates, reports) {
    let cumulative = 0;
    const labels = [];
    const cumulativeVals = [];
    const dailyProfits = [];
    const dailyLosses = [];
    
    sortedDates.forEach(date => {
        const report = reports[date];
        let dayProfit = 0;
        let dayLoss = 0;
        
        const dailyStocks = [
            ...(report.top_profits || []),
            ...(report.top_losses || [])
        ];
        
        dailyStocks.forEach(stock => {
            (stock.trades || []).forEach(trade => {
                const profit = trade.profit || 0;
                cumulative += profit;
                if (profit > 0) {
                    dayProfit += profit;
                } else {
                    dayLoss += profit;
                }
            });
        });
        
        labels.push(date.substring(5)); // Show MM-DD format
        cumulativeVals.push(cumulative);
        dailyProfits.push(dayProfit);
        dailyLosses.push(Math.abs(dayLoss));
    });
    
    return { labels, cumulativeVals, dailyProfits, dailyLosses };
}

// Render Top 5 Stock Rankings
function renderStockRankings(stockStats) {
    const container = document.getElementById('stock-ranks-container');
    container.innerHTML = '';
    
    const sortedStocks = Object.values(stockStats)
        .sort((a, b) => b.cumulativeProfit - a.cumulativeProfit);
    
    const topStocks = sortedStocks.slice(0, 5);
    
    if (topStocks.length === 0) {
        container.innerHTML = '<div class="text-muted text-center py-4">거래 기록이 없습니다.</div>';
        return;
    }
    
    topStocks.forEach((stock, idx) => {
        const item = document.createElement('div');
        item.className = 'rank-item';
        
        let medalClass = '';
        if (idx === 0) medalClass = 'gold';
        else if (idx === 1) medalClass = 'silver';
        else if (idx === 2) medalClass = 'bronze';
        
        const isProfitable = stock.cumulativeProfit >= 0;
        const profitClass = isProfitable ? 'text-green' : 'text-red';
        const formattedProfit = formatCurrency(stock.cumulativeProfit);
        
        item.innerHTML = `
            <div class="rank-left">
                <span class="rank-num ${medalClass}">${idx + 1}</span>
                <div class="rank-meta">
                    <span class="rank-name">${stock.name}</span>
                    <span class="rank-code">${stock.code} (${stock.tradesCount}회 매매)</span>
                </div>
            </div>
            <div class="rank-profit-container">
                <span class="rank-profit-val ${profitClass}">${formattedProfit}</span>
            </div>
        `;
        
        // Open detailed view modal on rank item click
        item.addEventListener('click', () => {
            openStockModal(stock.code, stock.name);
        });
        
        container.appendChild(item);
    });
}

// Extract judgment tags from text
function getJudgmentTag(stockName, aiAnalysis) {
    if (!aiAnalysis) return 'CORRECT';
    const cleanName = stockName.replace(/[\[\]]/g, '').trim();
    const lines = aiAnalysis.split('\n');
    for (const line of lines) {
        if (line.includes(cleanName)) {
            const match = line.match(/판정:\s*([A-Z]+)/i);
            if (match) {
                const tag = match[1].toUpperCase();
                // Map known tags, clean unrecognized ones to CORRECT
                const validTags = ['CORRECT', 'FORCED', 'UNLUCKY', 'WRONG', 'LATE', 'EARLY'];
                if (validTags.includes(tag)) {
                    return tag;
                }
            }
        }
    }
    // Fallback if containing unlucky, forced etc keywords in case regex fails
    const lowercaseAnalysis = aiAnalysis.toLowerCase();
    if (lowercaseAnalysis.includes(cleanName)) {
        if (lowercaseAnalysis.includes('forced') || lowercaseAnalysis.includes('불가항력')) return 'FORCED';
        if (lowercaseAnalysis.includes('unlucky') || lowercaseAnalysis.includes('아쉬움')) return 'UNLUCKY';
        if (lowercaseAnalysis.includes('wrong') || lowercaseAnalysis.includes('판단 미스') || lowercaseAnalysis.includes('실수')) return 'WRONG';
        if (lowercaseAnalysis.includes('late') || lowercaseAnalysis.includes('늦은')) return 'LATE';
        if (lowercaseAnalysis.includes('early') || lowercaseAnalysis.includes('조기')) return 'EARLY';
    }
    return 'CORRECT';
}

// Render Net Timeline Area Chart
function renderNetTimelineChart(data) {
    const ctx = document.getElementById('chart-net-timeline').getContext('2d');
    
    if (charts.netTimeline) {
        charts.netTimeline.destroy();
    }
    
    // Create gradient fill for cumulative line
    const gradCyan = ctx.createLinearGradient(0, 0, 0, 300);
    gradCyan.addColorStop(0, 'rgba(0, 242, 254, 0.25)');
    gradCyan.addColorStop(1, 'rgba(0, 242, 254, 0.00)');
    
    charts.netTimeline = new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.labels,
            datasets: [
                {
                    label: '누적 순익',
                    data: data.cumulativeVals,
                    type: 'line',
                    borderColor: '#00f2fe',
                    borderWidth: 3,
                    pointBackgroundColor: '#00f2fe',
                    pointBorderColor: '#080a10',
                    pointBorderWidth: 2,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    tension: 0.35,
                    fill: true,
                    backgroundColor: gradCyan,
                    yAxisID: 'y'
                },
                {
                    label: '일일 익절',
                    data: data.dailyProfits,
                    type: 'bar',
                    backgroundColor: 'rgba(16, 185, 129, 0.35)',
                    borderColor: 'rgba(16, 185, 129, 0.7)',
                    borderWidth: 1,
                    borderRadius: 4,
                    barPercentage: 0.5,
                    yAxisID: 'y1'
                },
                {
                    label: '일일 손절',
                    data: data.dailyLosses,
                    type: 'bar',
                    backgroundColor: 'rgba(244, 63, 94, 0.35)',
                    borderColor: 'rgba(244, 63, 94, 0.7)',
                    borderWidth: 1,
                    borderRadius: 4,
                    barPercentage: 0.5,
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false // Using custom styled HTML legend
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    backgroundColor: '#111422',
                    titleColor: '#9ca3af',
                    bodyColor: '#f3f4f6',
                    borderColor: 'rgba(255, 255, 255, 0.08)',
                    borderWidth: 1,
                    padding: 12,
                    titleFont: { family: 'Inter', size: 11 },
                    bodyFont: { family: 'Inter', size: 12 },
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            if (context.parsed.y !== null) {
                                label += formatCurrency(context.parsed.y);
                            }
                            return label;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: {
                        color: 'rgba(255, 255, 255, 0.03)'
                    },
                    ticks: {
                        color: '#9ca3af',
                        font: { family: 'Inter', size: 10 }
                    }
                },
                y: {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    grid: {
                        color: 'rgba(255, 255, 255, 0.04)',
                        drawBorder: false
                    },
                    ticks: {
                        color: '#00f2fe',
                        font: { family: 'Outfit', size: 10 },
                        callback: function(value) {
                            return value >= 0 ? '+' + value / 1000 + 'k' : value / 1000 + 'k';
                        }
                    }
                },
                y1: {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    grid: {
                        drawOnChartArea: false // Only show grid lines for cumulative
                    },
                    ticks: {
                        color: '#9ca3af',
                        font: { family: 'Inter', size: 10 },
                        callback: function(value) {
                            return value / 1000 + 'k';
                        }
                    }
                }
            }
        }
    });
}

// Render Vibe Distribution Pie Chart
function renderVibePieChart(vibeStats) {
    const ctx = document.getElementById('chart-vibe-pie').getContext('2d');
    
    if (charts.vibePie) {
        charts.vibePie.destroy();
    }
    
    const labels = Object.keys(vibeStats);
    const dataVals = Object.values(vibeStats);
    const backgroundColors = labels.map(vibe => {
        if (vibe === 'Bull') return 'rgba(16, 185, 129, 0.65)';
        if (vibe === 'Bear') return 'rgba(244, 63, 94, 0.65)';
        return 'rgba(59, 130, 246, 0.65)';
    });
    const borderColors = labels.map(vibe => {
        if (vibe === 'Bull') return '#10b981';
        if (vibe === 'Bear') return '#f43f5e';
        return '#3b82f6';
    });
    
    charts.vibePie = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data: dataVals,
                backgroundColor: backgroundColors,
                borderColor: borderColors,
                borderWidth: 1,
                hoverOffset: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    backgroundColor: '#111422',
                    titleColor: '#9ca3af',
                    bodyColor: '#f3f4f6',
                    borderColor: 'rgba(255, 255, 255, 0.08)',
                    borderWidth: 1,
                    padding: 8,
                    titleFont: { family: 'Inter', size: 10 },
                    bodyFont: { family: 'Inter', size: 11 }
                }
            },
            cutout: '70%'
        }
    });
    
    // Render custom HTML legend for Vibe stats
    const legendEl = document.getElementById('vibe-stats-legend');
    legendEl.innerHTML = '';
    
    const total = dataVals.reduce((a, b) => a + b, 0);
    
    labels.forEach((label, idx) => {
        let dotColor = 'bg-blue';
        if (label === 'Bull') dotColor = 'bg-emerald';
        else if (label === 'Bear') dotColor = 'bg-coral';
        
        const val = dataVals[idx];
        const pct = total > 0 ? (val / total * 100).toFixed(0) : 0;
        
        legendEl.innerHTML += `
            <div class="vibe-legend-item">
                <div class="vibe-legend-left">
                    <span class="vibe-color-dot ${dotColor}"></span>
                    <span>${label}</span>
                </div>
                <span class="vibe-legend-val">${val}일 (${pct}%)</span>
            </div>
        `;
    });
}

// Render Strategy Breakdown / AI Model Comparison Charts
function renderModelPerformanceCharts(modelStats) {
    const pCtx = document.getElementById('chart-model-profit').getContext('2d');
    const wCtx = document.getElementById('chart-model-winrate').getContext('2d');
    
    if (charts.modelProfit) charts.modelProfit.destroy();
    if (charts.modelWinRate) charts.modelWinRate.destroy();
    
    const models = Object.keys(modelStats);
    const profits = models.map(m => modelStats[m].profit);
    const totalTrades = models.map(m => modelStats[m].total);
    const winRates = models.map(m => {
        const s = modelStats[m];
        return s.total > 0 ? (s.wins / s.total * 100) : 0;
    });
    
    // Bar Colors
    const modelColors = models.map(m => {
        if (m.toLowerCase().includes('gemini-3.1-flash') || m.toLowerCase().includes('g3.1flp')) {
            return 'rgba(168, 85, 247, 0.65)'; // Purple for Gemini 3.1 Flash Lite
        }
        if (m.toLowerCase().includes('gemini-3')) {
            return 'rgba(59, 130, 246, 0.65)'; // Blue for Gemini 3
        }
        if (m.toLowerCase().includes('tl/sp')) {
            return 'rgba(0, 242, 254, 0.65)'; // Cyan for Trend-Line/Stop-Profit rule model
        }
        return 'rgba(156, 163, 175, 0.65)'; // Grey for Manual/Unknown
    });
    
    const modelBorderColors = models.map(m => {
        if (m.toLowerCase().includes('gemini-3.1-flash') || m.toLowerCase().includes('g3.1flp')) return '#a855f7';
        if (m.toLowerCase().includes('gemini-3')) return '#3b82f6';
        if (m.toLowerCase().includes('tl/sp')) return '#00f2fe';
        return '#9ca3af';
    });
    
    // Render Profits Bar Chart
    charts.modelProfit = new Chart(pCtx, {
        type: 'bar',
        data: {
            labels: models,
            datasets: [{
                label: '누적 실현손익',
                data: profits,
                backgroundColor: modelColors,
                borderColor: modelBorderColors,
                borderWidth: 1,
                borderRadius: 6
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#111422',
                    bodyColor: '#f3f4f6',
                    borderColor: 'rgba(255, 255, 255, 0.08)',
                    borderWidth: 1,
                    callbacks: {
                        label: function(context) {
                            return formatCurrency(context.parsed.x);
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.03)' },
                    ticks: { color: '#9ca3af', font: { family: 'Inter', size: 10 } }
                },
                y: {
                    grid: { display: false },
                    ticks: { color: '#f3f4f6', font: { family: 'Outfit', size: 11, weight: '600' } }
                }
            }
        }
    });
    
    // Render Win Rate Combo Line/Bar Chart
    charts.modelWinRate = new Chart(wCtx, {
        type: 'bar',
        data: {
            labels: models,
            datasets: [
                {
                    label: '매매 횟수',
                    type: 'bar',
                    data: totalTrades,
                    backgroundColor: 'rgba(255, 255, 255, 0.05)',
                    borderColor: 'rgba(255, 255, 255, 0.1)',
                    borderWidth: 1,
                    borderRadius: 4,
                    yAxisID: 'y1'
                },
                {
                    label: '승률 (%)',
                    type: 'line',
                    data: winRates,
                    borderColor: '#00f2fe',
                    borderWidth: 2,
                    pointBackgroundColor: '#00f2fe',
                    pointHoverRadius: 5,
                    tension: 0.2,
                    yAxisID: 'y'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: '#9ca3af', font: { family: 'Inter', size: 10 } }
                },
                tooltip: {
                    backgroundColor: '#111422',
                    bodyColor: '#f3f4f6',
                    borderColor: 'rgba(255, 255, 255, 0.08)',
                    borderWidth: 1,
                    padding: 8
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: '#9ca3af', font: { family: 'Inter', size: 10 } }
                },
                y: {
                    type: 'linear',
                    position: 'left',
                    min: 0,
                    max: 100,
                    grid: { color: 'rgba(255, 255, 255, 0.03)' },
                    ticks: {
                        color: '#00f2fe',
                        font: { family: 'Inter', size: 10 },
                        callback: function(val) { return val + '%'; }
                    }
                },
                y1: {
                    type: 'linear',
                    position: 'right',
                    grid: { display: false },
                    ticks: {
                        color: '#9ca3af',
                        font: { family: 'Inter', size: 10 }
                    }
                }
            }
        }
    });
}

// Render Model summary stats Table
function renderModelTable(modelStats) {
    const tbody = document.getElementById('table-model-stats-body');
    tbody.innerHTML = '';
    
    Object.values(modelStats).forEach(model => {
        const row = document.createElement('tr');
        const winrate = model.total > 0 ? (model.wins / model.total * 100) : 0;
        const avgProfit = model.total > 0 ? model.profit / model.total : 0;
        
        row.innerHTML = `
            <td><strong class="text-white">${model.name}</strong></td>
            <td>${model.total}</td>
            <td class="text-green">${model.wins}</td>
            <td class="text-red">${model.losses}</td>
            <td class="text-white"><strong>${formatPercent(winrate)}</strong></td>
            <td class="${model.profit >= 0 ? 'text-green' : 'text-red'}"><strong>${formatCurrency(model.profit)}</strong></td>
            <td class="${avgProfit >= 0 ? 'text-green' : 'text-red'}">${formatCurrency(avgProfit)}</td>
        `;
        tbody.appendChild(row);
    });
}

// Render Additional Distribution Charts (Type & Judgement distribution)
function renderAdditionalDistributionCharts(typeStats, judgmentStats) {
    const tCtx = document.getElementById('chart-type-distribution').getContext('2d');
    const jCtx = document.getElementById('chart-judgment-distribution').getContext('2d');
    
    if (charts.typeDist) charts.typeDist.destroy();
    if (charts.judgmentDist) charts.judgmentDist.destroy();
    
    // 1. Type Distribution
    const types = Object.keys(typeStats);
    const typeProfits = types.map(t => typeStats[t].profit);
    const typeColors = types.map(t => {
        if (t.includes('익절')) return 'rgba(16, 185, 129, 0.6)';
        if (t.includes('손절')) return 'rgba(244, 63, 94, 0.6)';
        if (t.includes('수익확정')) return 'rgba(59, 130, 246, 0.6)';
        if (t.includes('자율매도')) return 'rgba(168, 85, 247, 0.6)';
        return 'rgba(156, 163, 175, 0.6)';
    });
    
    charts.typeDist = new Chart(tCtx, {
        type: 'bar',
        data: {
            labels: types,
            datasets: [{
                label: '구분별 손익 합계',
                data: typeProfits,
                backgroundColor: typeColors,
                borderWidth: 0,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#111422',
                    bodyColor: '#f3f4f6',
                    callbacks: {
                        label: function(c) { return formatCurrency(c.parsed.y); }
                    }
                }
            },
            scales: {
                x: { grid: { display: false }, ticks: { color: '#9ca3af', font: { family: 'Inter', size: 9 } } },
                y: { grid: { color: 'rgba(255, 255, 255, 0.03)' }, ticks: { color: '#9ca3af', font: { family: 'Inter', size: 9 } } }
            }
        }
    });
    
    // 2. Judgement Tag Distribution
    const tags = Object.keys(judgmentStats);
    const tagCounts = Object.values(judgmentStats);
    const tagColors = tags.map(t => {
        if (t === 'CORRECT') return 'rgba(16, 185, 129, 0.65)';
        if (t === 'FORCED') return 'rgba(59, 130, 246, 0.65)';
        if (t === 'UNLUCKY') return 'rgba(245, 158, 11, 0.65)';
        if (t === 'WRONG') return 'rgba(244, 63, 94, 0.65)';
        if (t === 'LATE') return 'rgba(168, 85, 247, 0.65)';
        return 'rgba(0, 242, 254, 0.65)'; // EARLY
    });
    
    charts.judgmentDist = new Chart(jCtx, {
        type: 'polarArea',
        data: {
            labels: tags,
            datasets: [{
                data: tagCounts,
                backgroundColor: tagColors,
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                    labels: { color: '#9ca3af', boxWidth: 8, font: { family: 'Inter', size: 9 } }
                },
                tooltip: {
                    backgroundColor: '#111422',
                    bodyColor: '#f3f4f6'
                }
            },
            scales: {
                r: {
                    grid: { color: 'rgba(255, 255, 255, 0.03)' },
                    angleLines: { color: 'rgba(255, 255, 255, 0.03)' },
                    ticks: { backdropColor: 'transparent', color: '#9ca3af', font: { size: 9 } }
                }
            }
        }
    });
}

// Draw list of dates in report detail sidebar
function renderDateTimeline(sortedDates, reports) {
    const listEl = document.getElementById('report-dates-list');
    listEl.innerHTML = '';
    
    // Sort dates in reverse chronological order for sidebar selector
    const reverseDates = [...sortedDates].reverse();
    
    reverseDates.forEach(date => {
        const report = reports[date];
        const vibe = report.market_vibe || 'Neutral';
        
        let netDayProfit = 0;
        const dailyStocks = [
            ...(report.top_profits || []),
            ...(report.top_losses || [])
        ];
        
        dailyStocks.forEach(stock => {
            (stock.trades || []).forEach(trade => {
                netDayProfit += trade.profit || 0;
            });
        });
        
        const isProfitable = netDayProfit >= 0;
        const profitClass = isProfitable ? 'text-green' : 'text-red';
        const formattedProfit = formatCurrency(netDayProfit);
        
        const item = document.createElement('div');
        item.className = 'date-item';
        item.setAttribute('data-date', date);
        
        item.innerHTML = `
            <div class="date-item-left">
                <span class="date-text">${date}</span>
                <span class="date-meta-sub">${vibe}장세 • ${dailyStocks.length}종목</span>
            </div>
            <span class="date-profit ${profitClass}">${formattedProfit}</span>
        `;
        
        item.addEventListener('click', () => {
            selectDailyReport(date);
        });
        
        listEl.appendChild(item);
    });
}

// Select a specific daily report
function selectDailyReport(date) {
    if (!appData || !appData.reports) return;
    
    const reports = appData.reports;
    const report = reports[date];
    
    if (!report) return;
    
    selectedDate = date;
    
    // Remove active class from other dates in sidebar
    document.querySelectorAll('.date-item').forEach(item => {
        if (item.getAttribute('data-date') === date) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });
    
    // Show report container view
    document.getElementById('no-report-placeholder').classList.add('hidden');
    const viewContainer = document.getElementById('report-detail-view');
    viewContainer.classList.remove('hidden');
    
    // Update Banner
    document.getElementById('report-date-title').textContent = `${date} 매매 복기 리포트`;
    
    const vibeEl = document.getElementById('report-vibe-badge');
    vibeEl.textContent = report.market_vibe || 'Neutral';
    vibeEl.className = `vibe-badge vibe-${(report.market_vibe || 'Neutral').toLowerCase()}`;
    
    document.getElementById('report-generated-at').textContent = report.generated_at || '-';
    document.getElementById('report-updated-at').textContent = report.updated_at || '-';
    document.getElementById('report-update-count').textContent = report.update_count || '1';
    
    // Calculate Day profit
    let dailyNetProfit = 0;
    const dailyStocks = [
        ...(report.top_profits || []),
        ...(report.top_losses || [])
    ];
    
    dailyStocks.forEach(stock => {
        (stock.trades || []).forEach(trade => {
            dailyNetProfit += trade.profit || 0;
        });
    });
    
    const profitEl = document.getElementById('report-daily-profit');
    profitEl.textContent = formatCurrency(dailyNetProfit);
    if (dailyNetProfit < 0) {
        profitEl.className = 'banner-stat-value text-red';
    } else {
        profitEl.className = 'banner-stat-value text-green';
    }
    
    // Render AI Analysis (Convert simple markdown sections to beautiful styled blocks)
    renderAIAnalysis(report.ai_analysis);
    
    // Render daily stocks lists
    renderDailyStocksLists(report.top_profits || [], report.top_losses || [], report.ai_analysis);
}

// Render Markdown-like AI Analysis string
function renderAIAnalysis(markdownText) {
    const container = document.getElementById('report-ai-analysis');
    container.innerHTML = '';
    
    if (!markdownText) {
        container.innerHTML = '<p class="text-muted">AI 복기 코멘트가 제공되지 않았습니다.</p>';
        return;
    }
    
    // Parse line by line to create beautiful cards and blockquotes
    const lines = markdownText.split('\n');
    let currentQuoteBox = null;
    let quoteType = ''; // 'correct', 'forced', 'unlucky', 'wrong'
    
    lines.forEach(line => {
        const trimmed = line.trim();
        if (!trimmed) return;
        
        // Match header emojis
        if (trimmed.startsWith('📊')) {
            const el = document.createElement('h4');
            el.className = 'ai-main-header text-white font-weight-bold mb-3';
            el.innerHTML = trimmed;
            container.appendChild(el);
            return;
        }
        
        if (trimmed.startsWith('🟢 수익 종목 분석:') || trimmed.startsWith('🔴 손실 종목 분석:') || trimmed.startsWith('📝 종합 교훈:')) {
            // Close any existing quote boxes
            if (currentQuoteBox) {
                container.appendChild(currentQuoteBox);
                currentQuoteBox = null;
            }
            
            const titleEl = document.createElement('div');
            titleEl.className = 'ai-section-title text-white';
            
            let color = 'text-green';
            if (trimmed.includes('손실')) color = 'text-red';
            else if (trimmed.includes('교훈')) color = 'text-glow-blue';
            
            titleEl.innerHTML = `<span class="${color}">${trimmed}</span>`;
            container.appendChild(titleEl);
            
            // Create a general quote block for subsequent bullet points
            currentQuoteBox = document.createElement('div');
            currentQuoteBox.className = 'ai-quote-box';
            return;
        }
        
        // Match lists with judgments inside quote boxes
        if (trimmed.startsWith('-') || trimmed.startsWith('*')) {
            const listContent = trimmed.substring(1).trim();
            const li = document.createElement('li');
            
            // Parse inline bolding **word** or [word]
            let formattedContent = listContent
                .replace(/\*\*([^*]+)\*\*/g, '<strong class="text-white">$1</strong>')
                .replace(/\[([^\]]+)\]/g, '<strong class="text-white">[$1]</strong>');
            
            // Check for judgment tags inside list items to color-highlight
            let judgmentMatch = listContent.match(/\(판정:\s*([A-Z_]+)\)/i);
            if (judgmentMatch) {
                const judgment = judgmentMatch[1].toUpperCase();
                const tagClass = `tag-${judgment.toLowerCase()}`;
                
                // Replace inline (판정: CORRECT) with visual badge
                formattedContent = formattedContent.replace(
                    /\(판정:\s*([A-Z_]+)\)/i, 
                    `<span class="stock-tag-indicator ${tagClass}">${judgment}</span>`
                );
                
                // If there's an active general box, assign its specific style if it matches
                if (currentQuoteBox) {
                    if (judgment === 'CORRECT') currentQuoteBox.className = 'ai-quote-box correct';
                    else if (judgment === 'FORCED') currentQuoteBox.className = 'ai-quote-box forced';
                    else if (judgment === 'UNLUCKY') currentQuoteBox.className = 'ai-quote-box unlucky';
                    else if (judgment === 'WRONG') currentQuoteBox.className = 'ai-quote-box wrong';
                    else if (judgment === 'LATE') currentQuoteBox.className = 'ai-quote-box late';
                }
            }
            
            li.innerHTML = formattedContent;
            
            if (currentQuoteBox) {
                currentQuoteBox.appendChild(li);
            } else {
                const simpleList = document.createElement('ul');
                simpleList.className = 'pl-3 mb-3';
                simpleList.appendChild(li);
                container.appendChild(simpleList);
            }
            return;
        }
        
        // Simple numbered lists inside lessons
        const numMatch = trimmed.match(/^(\d+)\.\s*(.*)/);
        if (numMatch) {
            const num = numMatch[1];
            const content = numMatch[2];
            
            const li = document.createElement('li');
            li.innerHTML = `<strong class="text-white">${num}.</strong> ${content.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')}`;
            
            if (currentQuoteBox) {
                currentQuoteBox.appendChild(li);
            } else {
                currentQuoteBox = document.createElement('div');
                currentQuoteBox.className = 'ai-quote-box';
                currentQuoteBox.appendChild(li);
            }
            return;
        }
        
        // Standard paragraphs
        if (currentQuoteBox) {
            container.appendChild(currentQuoteBox);
            currentQuoteBox = null;
        }
        
        const p = document.createElement('p');
        p.innerHTML = trimmed.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        container.appendChild(p);
    });
    
    // Make sure to append any remaining box
    if (currentQuoteBox) {
        container.appendChild(currentQuoteBox);
    }
}

// Render list of profits & losses stocks for the selected date
function renderDailyStocksLists(profits, losses, aiAnalysis) {
    const profitsList = document.getElementById('report-profits-list');
    const lossesList = document.getElementById('report-losses-list');
    
    profitsList.innerHTML = '';
    lossesList.innerHTML = '';
    
    // Render Profits
    if (profits.length === 0) {
        profitsList.innerHTML = '<div class="text-muted text-center py-4">익절 종목이 존재하지 않습니다.</div>';
    } else {
        profits.forEach(stock => {
            const judgment = getJudgmentTag(stock.name, aiAnalysis);
            profitsList.appendChild(createStockRow(stock, judgment, true));
        });
    }
    
    // Render Losses
    if (losses.length === 0) {
        lossesList.innerHTML = '<div class="text-muted text-center py-4">손절 종목이 존재하지 않습니다.</div>';
    } else {
        losses.forEach(stock => {
            const judgment = getJudgmentTag(stock.name, aiAnalysis);
            lossesList.appendChild(createStockRow(stock, judgment, false));
        });
    }
}

// Helper to create Stock row in Lists
function createStockRow(stock, judgment, isProfit) {
    const row = document.createElement('div');
    row.className = 'stock-row-item';
    
    const profitClass = isProfit ? 'text-green' : 'text-red';
    const tagClass = `tag-${judgment.toLowerCase()}`;
    
    row.innerHTML = `
        <div class="stock-row-left">
            <div class="stock-row-name-row">
                <span class="stock-row-name">${stock.name}</span>
                <span class="stock-tag-indicator ${tagClass}">${judgment}</span>
            </div>
            <span class="stock-row-info">
                종목 코드: ${stock.code} • ${stock.trades ? stock.trades.length : 0}회 매매 • 
                최종 모델: ${stock.last_model || 'Unknown'}
            </span>
        </div>
        <div class="stock-row-right">
            <span class="stock-row-profit ${profitClass}">${formatCurrency(stock.total_profit)}</span>
            <span class="stock-row-subtext">등락률: <strong class="${stock.day_rate >= 0 ? 'text-green' : 'text-red'}">${stock.day_rate}%</strong></span>
        </div>
    `;
    
    row.addEventListener('click', () => {
        openStockModal(stock.code, stock.name);
    });
    
    return row;
}

// Open detailed Modal for stock trades
function openStockModal(stockCode, stockName) {
    if (!appData || !appData.reports) return;
    
    // Find all trades for this stock across all days, focusing on selected date first if any
    let stockData = null;
    
    // Look in the currently selected daily report
    if (selectedDate && appData.reports[selectedDate]) {
        const report = appData.reports[selectedDate];
        const allDailyStocks = [...(report.top_profits || []), ...(report.top_losses || [])];
        stockData = allDailyStocks.find(s => s.code === stockCode);
    }
    
    // If not found in current date, look in other dates
    if (!stockData) {
        for (const date of Object.keys(appData.reports)) {
            const report = appData.reports[date];
            const allDailyStocks = [...(report.top_profits || []), ...(report.top_losses || [])];
            stockData = allDailyStocks.find(s => s.code === stockCode);
            if (stockData) break;
        }
    }
    
    if (!stockData) return;
    
    // Populating modal fields
    document.getElementById('modal-stock-title').textContent = `${stockName} (${stockCode})`;
    
    const profitEl = document.getElementById('modal-meta-total-profit');
    profitEl.textContent = formatCurrency(stockData.total_profit);
    if (stockData.total_profit < 0) {
        profitEl.className = 'text-red';
    } else {
        profitEl.className = 'text-green';
    }
    
    document.getElementById('modal-meta-closing-price').textContent = formatCurrency(stockData.closing_price || 0);
    
    const rateEl = document.getElementById('modal-meta-day-rate');
    rateEl.textContent = `${stockData.day_rate || 0.0}%`;
    if (stockData.day_rate >= 0) {
        rateEl.className = 'text-green';
    } else {
        rateEl.className = 'text-red';
    }
    
    document.getElementById('modal-meta-val').textContent = `PER: ${stockData.per || 'N/A'} / PBR: ${stockData.pbr || 'N/A'}`;
    
    // Populate trades table
    const tbody = document.getElementById('modal-trades-body');
    tbody.innerHTML = '';
    
    (stockData.trades || []).forEach(trade => {
        const row = document.createElement('tr');
        const isProfitable = trade.profit >= 0;
        
        row.innerHTML = `
            <td class="text-white">${trade.time || '-'}</td>
            <td><span class="stock-tag-indicator ${trade.type.includes('익절') || trade.type.includes('수익') ? 'tag-correct' : 'tag-wrong'}">${trade.type}</span></td>
            <td>${trade.qty}</td>
            <td>${formatCurrency(trade.price)}</td>
            <td class="${isProfitable ? 'text-green' : 'text-red'}"><strong>${formatCurrency(trade.profit)}</strong></td>
            <td><code class="text-white">${trade.model_id || 'Unknown'}</code></td>
            <td class="text-muted"><small>${trade.memo || '-'}</small></td>
        `;
        tbody.appendChild(row);
    });
    
    // Show Modal
    const modal = document.getElementById('trade-modal');
    modal.classList.remove('hidden');
    setTimeout(() => {
        modal.classList.add('show');
    }, 10);
}

function closeModal() {
    const modal = document.getElementById('trade-modal');
    modal.classList.remove('show');
    setTimeout(() => {
        modal.classList.add('hidden');
    }, 300);
}

// Force charts resizing (useful on tab change)
function triggerChartsResize() {
    Object.values(charts).forEach(chart => {
        if (chart) {
            chart.resize();
            chart.update();
        }
    });
}
